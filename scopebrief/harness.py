import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Literal

import httpx

from .model import ChatModel
from .retrieval import (
    TOPIC_LABELS,
    bm25,
    explicitly_named,
    general_hit,
    question_terms,
    topics_for,
)
from .store import Evidence, Project, Role, Store

Strategy = Literal["baseline", "harness"]
Trace = Callable[[str, str, int], None]
TOP_K = 4
SOURCE_LIMIT = 9
CONTEXT_LIMIT = 4000


@dataclass
class Finding:
    project_id: str
    name: str
    status: str
    sources: list[Evidence]
    covered: list[str]
    missing: list[str]


def choose_excerpt(item: Evidence, question: str) -> str:
    if len(item.content) <= 175:
        return item.content
    terms = question_terms(question, [])
    candidates = re.findall(r"[^。！？；;\n]+[。！？；;]?", item.content)
    best = max(candidates, key=lambda s: len(question_terms(s, []) & terms), default=item.content)
    return best.strip()[:175]


def finding(
    project: Project,
    topics: list[str],
    evidence: list[Evidence],
    strategy: Strategy,
) -> Finding:
    picked: dict[str, Evidence] = {}
    covered, missing = [], []
    for topic in topics:
        matches = [e for e in evidence if topic == "general" or e.topic == topic]
        if not matches:
            missing.append(topic)
            continue
        covered.append(topic)
        picked[matches[0].id] = matches[0]
        if topic == "decision" and strategy == "harness":
            for item in matches[1:]:
                if item.decision != matches[0].decision:
                    picked[item.id] = item
                    break
    sources = list(picked.values())
    decisions = {item.decision for item in sources if item.topic == "decision"}
    if not sources:
        status = "insufficient"
    elif "decision" not in topics:
        status = "grounded"
    elif len(decisions) > 1:
        status = "conflict"
    else:
        status = next(iter(decisions), None) or "insufficient"
    return Finding(project.id, project.name, status, sources, covered, missing)


async def answer(
    store: Store,
    role: Role,
    question: str,
    requested: list[str],
    strategy: Strategy = "harness",
    model: ChatModel | None = None,
    on_event: Trace | None = None,
) -> dict:
    started = perf_counter()

    def event(stage: str, detail: str) -> None:
        if on_event:
            on_event(stage, detail, round((perf_counter() - started) * 1000))

    available = store.projects(role)
    selected = [project for project in available if project.id in requested]
    named = explicitly_named(question, store.projects("reviewer"))
    scope = [p for p in selected if not named or p in named]
    scope_limited = any(p not in selected for p in named)
    scope_detail = "部分提及项目超出可用范围。" if scope_limited else ""
    event("scope", f"已校验会话权限和检索范围，匹配 {len(scope)} 个项目。{scope_detail}")
    topics = topics_for(question)
    event("plan", "查找" + "、".join(TOPIC_LABELS[t] for t in topics) + "。")

    terms = question_terms(question, scope)
    corpus = store.evidence(role, [p.id for p in scope], current_only=strategy == "harness")
    ranking = bm25(terms, corpus)
    retrieved = [row.evidence for row in ranking if general_hit(row, terms)][:TOP_K]
    corpus_label = "当前版本" if strategy == "harness" else "全部版本"
    event(
        "retrieve",
        f"对 {len(corpus)} 条授权的{corpus_label}片段执行 BM25，初筛 {len(retrieved)} 条。",
    )

    by_project = {p.id: [e for e in retrieved if e.project_id == p.id] for p in scope}
    if strategy == "harness" and topics != ["general"]:
        ranked_ids = [e.evidence.id for e in ranking]
        rank_index = {entry: i for i, entry in enumerate(ranked_ids)}
        structured = [e for e in corpus if e.topic in topics]
        structured.sort(key=lambda entry: rank_index.get(entry.id, len(rank_index)))
        added = 0
        for project in scope:
            candidates = by_project[project.id]
            current_ids = {e.id for e in candidates}
            coverage = {e.topic for e in candidates}
            supplements = [
                e
                for e in structured
                if e.project_id == project.id
                and e.id not in current_ids
                and (e.topic not in coverage or e.topic == "decision")
            ]
            added += len(supplements)
            candidates.extend(supplements)
        if added:
            event("retry", f"按项目和资料标签复查，补查 {added} 条用于覆盖缺项或核对放行冲突。")

    findings = [finding(project, topics, by_project[project.id], strategy) for project in scope]
    evidence: list[Evidence] = []
    char_count = 0
    overflow = False
    for row in findings:
        next_size = sum(len(item.content) for item in row.sources)
        if (
            len(evidence) + len(row.sources) > SOURCE_LIMIT
            or char_count + next_size > CONTEXT_LIMIT
        ):
            overflow = True
            row.sources.clear()
            row.missing, row.covered, row.status = topics[:], [], "insufficient"
            continue
        evidence.extend(row.sources)
        char_count += next_size
    if overflow:
        event("budget", "证据超出单次上下文预算，超出部分标记为资料不足。")

    excerpts = {item.id: choose_excerpt(item, question) for item in evidence}
    usage = None
    generator = "extractive"
    if model and evidence:
        event("generate", f"用 {model.settings.model_name} 从 {len(evidence)} 条授权证据选择引文。")
        try:
            selection = await model.select(question, evidence)
            excerpts.update(selection.quotes)
            usage, generator = selection.usage, "model"
        except (ValueError, httpx.HTTPError, TimeoutError):
            generator = "fallback"
            event("fallback", "模型调用失败或引文未通过校验，使用原文摘录。")
    elif evidence:
        event("generate", f"从 {len(evidence)} 条授权证据生成原文摘录。")

    incomplete = scope_limited or any(row.missing or row.status == "conflict" for row in findings)
    if not evidence or all(row.status in {"insufficient", "conflict"} for row in findings):
        status = "insufficient"
    elif incomplete:
        status = "partial"
    else:
        status = "answered"
    if any(row.status == "conflict" for row in findings):
        verification = "发现当前资料中的放行记录冲突，相关项目转为人工确认。"
    elif incomplete or not evidence:
        verification = "有些问题缺少支持资料，已标出缺项。"
    else:
        verification = "已核对项目覆盖与引文。"
    event("verify", verification)
    event("complete", f"已保存 {len(evidence)} 条可追溯引文。")
    return {
        "status": status,
        "scope_limited": scope_limited,
        "generator": generator,
        "model": model.settings.model_name if model and evidence else None,
        "usage": usage,
        "duration_ms": round((perf_counter() - started) * 1000),
        "findings": [
            {
                "project_id": row.project_id,
                "name": row.name,
                "status": row.status,
                "topics": row.covered,
                "missing": row.missing,
                "citation_ids": [e.id for e in row.sources],
            }
            for row in findings
        ],
        "citations": [
            asdict(item) | {"quote": excerpts[item.id], "number": i}
            for i, item in enumerate(evidence, 1)
        ],
    }

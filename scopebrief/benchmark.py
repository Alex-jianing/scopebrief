import argparse
import asyncio
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from .harness import answer
from .model import ChatModel
from .settings import Settings
from .store import FIXTURES, Store

STRATEGIES = ("baseline", "harness")


def check(case: dict, result: dict) -> dict:
    expected = case.get("expect", {})
    observed = {row["project_id"]: row["status"] for row in result["findings"]}
    sources = {
        f"{s['project_id']}/{s['key']}/{s['revision']}/{s['topic']}" for s in result["citations"]
    }
    gold = set(case["sources"])
    stale = sum(not s["current"] for s in result["citations"])
    leak = case.get("role", "member") == "member" and any(
        s["project_id"] == "bridge" or "ORBIT-734" in s["quote"] for s in result["citations"]
    )
    missing = [key for key in expected if observed.get(key) != expected[key]]
    status_ok = result["status"] == case.get("status", "answered")
    failures = []
    if missing:
        failures.append(f"{len(missing)} 个项目结论与预期不一致")
    if len(gold - sources):
        failures.append(f"缺少 {len(gold - sources)} 条目标证据")
    if not status_ok:
        failures.append("回答状态与预期不一致")
    if stale:
        failures.append(f"引用 {stale} 条历史版本")
    if leak:
        failures.append("发现越权引文")
    return {
        "pass": not failures,
        "failures": failures,
        "gold_hits": len(gold & sources),
        "gold_total": len(gold),
        "correct_decisions": sum(
            observed.get(k) == v for k, v in expected.items() if v in {"go", "hold"}
        ),
        "decision_total": sum(v in {"go", "hold"} for v in expected.values()),
        "stale": stale,
        "leak": leak,
        "abstained": result["status"] == "insufficient",
        "duration_ms": result["duration_ms"],
        "generator": result["generator"],
    }


def summarize(cases: list[dict], strategy: str) -> dict:
    items = [case[strategy] for case in cases]
    durations = sorted(item["duration_ms"] for item in items)
    return {
        "passed": sum(x["pass"] for x in items),
        "total": len(items),
        "gold_hits": sum(x["gold_hits"] for x in items),
        "gold_total": sum(x["gold_total"] for x in items),
        "correct_decisions": sum(x["correct_decisions"] for x in items),
        "decision_total": sum(x["decision_total"] for x in items),
        "stale_citations": sum(x["stale"] for x in items),
        "leak_cases": sum(x["leak"] for x in items),
        "correct_abstentions": sum(
            item["abstained"] for case, item in zip(cases, items, strict=True) if case["abstain"]
        ),
        "abstention_total": sum(case["abstain"] for case in cases),
        "p95_ms": durations[math.ceil(len(durations) * 0.95) - 1],
        "model_cases": sum(x["generator"] == "model" for x in items),
        "fallback_cases": sum(x["generator"] == "fallback" for x in items),
    }


async def run_benchmark(model: ChatModel | None = None, only: str | None = None) -> dict:
    cases = json.loads((FIXTURES / "evaluation.json").read_text(encoding="utf-8"))
    if only is not None:
        cases = [case for case in cases if case["id"] == only]
        if not cases:
            raise ValueError(f"Unknown evaluation case {only}")
    rows = []
    with TemporaryDirectory(prefix="scopebrief-eval-") as folder:
        store = Store(Path(folder) / "eval.db")
        store.initialize()
        for case in cases:
            role = case.get("role", "member")
            scope = case.get("scope", [p.id for p in store.projects(role)])
            row = {key: case[key] for key in ("id", "group", "title")}
            row["abstain"] = case.get("status") == "insufficient"
            for strategy in STRATEGIES:
                result = await answer(store, role, case["question"], scope, strategy, model)
                row[strategy] = check(case, result)
            rows.append(row)
    return {
        "dataset": "release-reviews-v1",
        "mode": model.settings.model_name if model else "extractive",
        "metrics": {strategy: summarize(rows, strategy) for strategy in STRATEGIES},
        "cases": rows,
    }


def offline_report() -> dict:
    return asyncio.run(run_benchmark())


async def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Compare BM25 and ScopeBrief on the synthetic corpus."
    )
    parser.add_argument("--json", type=Path, help="Write the full evaluation report")
    parser.add_argument("--case", help="Run a single case by ID")
    parser.add_argument("--model", action="store_true", help="Use the configured chat model")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.model and not (settings.model_base_url and settings.model_name):
        parser.error("--model requires SCOPEBRIEF_MODEL_BASE_URL and SCOPEBRIEF_MODEL_NAME")
    async with httpx.AsyncClient(timeout=settings.model_timeout, trust_env=False) as client:
        model = ChatModel(settings, client) if args.model else None
        report = await run_benchmark(model, args.case)
    shown = {"dataset": report["dataset"], "mode": report["mode"], "metrics": report["metrics"]}
    print(json.dumps(shown, indent=2, ensure_ascii=False))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    asyncio.run(cli())

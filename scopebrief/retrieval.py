import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from .store import Evidence, Project

TOPIC_LABELS = {
    "decision": "放行结论",
    "blocker": "阻塞事项",
    "window": "变更时段",
    "rollback": "回退方案",
    "owner": "负责人",
    "verification": "验收信息",
    "dependency": "依赖关系",
    "general": "相关资料",
}
INTENTS = {
    "decision": r"(放行|上线结论|迁移准入|能.{0,3}(上线|灰度|迁移)|可.{0,3}(上线|灰度|迁移)"
    r"|是否.{0,3}(上线|灰度|迁移)|该不该发版|准入结果|上线状态)",
    "blocker": r"(阻塞|阻断|卡点|被卡|上线障碍|卡在|卡住|还差什么|待解除)",
    "window": r"(窗口|时段|几点|何时.{0,3}(上线|发布|灰度)|什么时候.{0,3}(灰度|上线))",
    "rollback": r"(回滚|回退|回切|撤回|退回旧|降回旧|退版本)",
    "owner": r"(负责人|谁.{0,3}(负责|值班|确认|牵头|管)|找谁|对接人|归谁)",
    "verification": r"(验收代号|验收步骤|如何验收|怎么验收|怎样.{0,3}验收|演练验收|验证步骤)",
    "dependency": r"(依赖|上游服务|调用哪些)",
}
TOKEN = re.compile(r"[\u3400-\u9fff]+|[a-z0-9]+(?:[-_.][a-z0-9]+)*")
FILLERS = (
    "请告诉我",
    "能告诉我",
    "请问",
    "想知道",
    "有谁知道",
    "的方案是什么",
    "是什么",
    "怎么办",
    "有哪些",
    "多少",
    "一下",
    "项目",
    "本次",
    "目前",
    "分别",
    "各自",
)
STOP = {
    "我们",
    "他们",
    "是否",
    "可以",
    "能否",
    "哪个",
    "怎么",
    "如何",
    "相关",
    "的资",
    "请问",
    "现在",
    "关于",
    "the",
    "is",
    "for",
    "and",
    "what",
}


@dataclass(frozen=True)
class Ranked:
    evidence: Evidence
    score: float
    hits: int


def topics_for(question: str) -> list[str]:
    matches = [topic for topic, pattern in INTENTS.items() if re.search(pattern, question)]
    return matches or ["general"]


def explicitly_named(question: str, projects: list[Project]) -> list[Project]:
    text = question.casefold()
    return [
        p
        for p in projects
        if any(
            re.search(
                rf"\b{re.escape(alias.casefold())}\b" if alias.isascii() else re.escape(alias),
                text,
            )
            for alias in p.aliases
        )
    ]


def tokens(text: str) -> list[str]:
    output: list[str] = []
    for word in TOKEN.findall(unicodedata.normalize("NFKC", text).casefold()):
        if word.isascii() or len(word) == 1:
            output.append(word)
        else:
            output.extend(word[i : i + 2] for i in range(len(word) - 1))
    return [t for t in output if t not in STOP]


def question_terms(question: str, scope: list[Project]) -> set[str]:
    text = question.casefold()
    for term in (*FILLERS, *(alias.casefold() for project in scope for alias in project.aliases)):
        pattern = rf"\b{re.escape(term)}\b" if term.isascii() else re.escape(term)
        text = re.sub(pattern, " ", text)
    return set(tokens(text))


def bm25(terms: set[str], corpus: list[Evidence]) -> list[Ranked]:
    """Score only evidence visible to this request. Double-weight section headings."""
    if not terms or not corpus:
        return []
    bags = [Counter(tokens(f"{e.heading} {e.heading} {e.title} {e.content}")) for e in corpus]
    lengths = [sum(bag.values()) for bag in bags]
    size = len(bags)
    avg = max(1, sum(lengths) / size)
    df = Counter(term for bag in bags for term in terms.intersection(bag))
    weights = {term: math.log1p((size - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}
    ranked: list[Ranked] = []
    for entry, bag, length in zip(corpus, bags, lengths, strict=True):
        common = sorted(terms.intersection(bag))
        norm = 1.2 * (0.25 + 0.75 * length / avg)
        score = sum(weights[t] * 2.2 * bag[t] / (bag[t] + norm) for t in common)
        if score:
            ranked.append(Ranked(entry, score, len(common)))
    return sorted(ranked, key=lambda row: (-row.score, row.evidence.id))


def general_hit(row: Ranked, terms: set[str]) -> bool:
    return row.hits >= max(2, math.ceil(len(terms) * 0.25))

import re
from dataclasses import dataclass

TOPICS = (
    "decision",
    "blocker",
    "window",
    "rollback",
    "owner",
    "verification",
    "dependency",
)
HEADING = re.compile(r"^#{1,6}\s+(.+)$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
TAG = re.compile(r"\s+\[([a-z]+)(?:=([a-z]+))?\]\s*$")
CHUNK_CHARS = 480
DOCUMENT_CHARS = 180_000


@dataclass(frozen=True)
class Section:
    heading: str
    topic: str
    decision: str | None
    content: str
    start_line: int
    end_line: int


def parse_markdown(body: str) -> list[Section]:
    """Preserve line offsets and optional structured metadata in headings."""
    if len(body) > DOCUMENT_CHARS or "\x00" in body:
        raise ValueError("正文包含无效字符或超过 180,000 字。")
    sections: list[Section] = []
    heading, topic, decision = "正文", "general", None
    lines: list[tuple[int, str]] = []
    size = 0
    fence: str | None = None

    def flush() -> None:
        nonlocal size
        while lines and not lines[-1][1].strip():
            lines.pop()
        if lines:
            sections.append(
                Section(
                    heading,
                    topic,
                    decision,
                    "\n".join(line for _, line in lines),
                    lines[0][0],
                    lines[-1][0],
                )
            )
        lines.clear()
        size = 0

    for number, line in enumerate(re.split(r"\r\n|\r|\n", body), 1):
        marker = FENCE.match(line)
        match = HEADING.match(line) if fence is None else None
        if match:
            flush()
            heading = match[1].strip()
            topic, decision = "general", None
            if tag := TAG.search(heading):
                if tag[1] in TOPICS:
                    topic, decision = tag[1], tag[2]
                    if topic == "decision" and decision not in {"go", "hold"}:
                        raise ValueError("放行结论须使用 [decision=go] 或 [decision=hold]")
                    if topic != "decision" and decision is not None:
                        raise ValueError("只有 decision 标签可以带值")
                    heading = heading[: tag.start()].strip()
            if len(heading) > 100:
                raise ValueError("Markdown 标题最多 100 字")
            continue
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1].startswith(fence):
                fence = None
        if len(line) > CHUNK_CHARS:
            flush()
            # Preserve the physical line number for every excerpt of a wrapped paragraph.
            while line:
                end = min(CHUNK_CHARS, len(line))
                if end < len(line):
                    boundary = max(line.rfind(mark, end * 3 // 4, end) for mark in " 。；，、!?;")
                    if boundary >= 0:
                        end = boundary + 1
                part, line = line[:end], line[end:]
                if part.strip():
                    sections.append(Section(heading, topic, decision, part, number, number))
            continue
        if size + len(line) + 1 > CHUNK_CHARS:
            flush()
        if lines or line.strip():
            lines.append((number, line))
            size += len(line) + 1
    flush()
    if not sections:
        raise ValueError("文档至少需要一段正文")
    return sections

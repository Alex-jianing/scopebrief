import re
import unicodedata

TOKEN = re.compile(r"[\u3400-\u9fff]+|[a-z0-9]+(?:[-_.][a-z0-9]+)*")
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


def tokens(text: str) -> list[str]:
    output: list[str] = []
    for word in TOKEN.findall(unicodedata.normalize("NFKC", text).casefold()):
        if word.isascii() or len(word) == 1:
            output.append(word)
        else:
            output.extend(word[i : i + 2] for i in range(len(word) - 1))
    return [t for t in output if t not in STOP]

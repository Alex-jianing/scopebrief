import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .documents import DOCUMENT_CHARS

UPLOAD_BYTES = 8 * 1024 * 1024
WORD_XML_BYTES = 12 * 1024 * 1024
MAX_PAGES = 80
PDF_PAGE_STREAM_BYTES = 4 * 1024 * 1024
WORD = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def source_name(value: str) -> str:
    name = posixpath.basename(value.strip().replace("\\", "/"))
    return re.sub(r"[\x00-\x1f\x7f]", "", name)[:180]


def _plain(data: bytes) -> str:
    for encoding in (
        ("utf-8-sig", "utf-16")
        if data.startswith((b"\xff\xfe", b"\xfe\xff"))
        else ("utf-8-sig", "gb18030")
    ):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文本编码未识别，请另存为 UTF-8 后导入。")


def _pdf(data: bytes) -> str:
    try:
        pdf = PdfReader(io.BytesIO(data))
        if pdf.is_encrypted:
            raise ValueError("请先另存为可读取的未加密 PDF。")
        if len(pdf.pages) > MAX_PAGES:
            raise ValueError(f"PDF 最多 {MAX_PAGES} 页，请分文件导入。")
        sections = []
        total = 0
        for i, page in enumerate(pdf.pages, 1):
            stream = page.get_contents()
            if stream is not None and len(stream.get_data()) > PDF_PAGE_STREAM_BYTES:
                raise ValueError(f"第 {i} 页的正文流过大，请拆分或精简 PDF。")
            text = (page.extract_text() or "").strip()
            if text:
                total += len(text) + 24
                if total > DOCUMENT_CHARS:
                    raise ValueError("提取结果超过正文长度上限，请分文件导入。")
                sections.append(f"## 第 {i} 页\n\n{text}")
    except (PyPdfError, OSError, RecursionError) as exc:
        raise ValueError("无法解析这份 PDF。") from exc
    if not sections:
        raise ValueError("PDF 中未提取到文本。扫描件请先做 OCR。")
    return "\n\n".join(sections)


def _word_text(node: ElementTree.Element) -> str:
    return "".join(part.text or "" for part in node.findall(".//w:t", WORD))


def _docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > WORD_XML_BYTES:
                raise ValueError("Word 正文体积超过导入上限。")
            xml = archive.read(info)
        if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)", xml.replace(b"\x00", b""), re.I):
            raise ValueError("Word 正文包含不受支持的 XML 声明。")
        root = ElementTree.fromstring(xml)
    except (
        zipfile.BadZipFile,
        KeyError,
        ElementTree.ParseError,
        RuntimeError,
        NotImplementedError,
    ) as exc:
        raise ValueError("无法解析这份 DOCX。") from exc
    body = root.find("w:body", WORD)
    if body is None:
        raise ValueError("Word 文件没有正文。")
    lines = []
    for item in body:
        tag = item.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = _word_text(item).strip()
            if text:
                style = item.find("w:pPr/w:pStyle", WORD)
                style_name = style.get(f"{{{WORD['w']}}}val", "") if style is not None else ""
                lines.append(f"## {text[:100]}" if style_name.startswith("Heading") else text)
        elif tag == "tbl":
            for row in item.findall("w:tr", WORD):
                row_text = " | ".join(_word_text(cell) for cell in row.findall("w:tc", WORD))
                if row_text.strip(" |"):
                    lines.append(row_text)
    return "\n\n".join(lines)


def import_document(filename: str, data: bytes) -> dict:
    name = source_name(filename)
    title, extension = posixpath.splitext(name)
    extractors = {".md": _plain, ".markdown": _plain, ".txt": _plain, ".pdf": _pdf, ".docx": _docx}
    parse = extractors.get(extension.lower())
    if parse is None:
        raise ValueError("请选择 Markdown、TXT、可复制文本的 PDF 或 DOCX。")
    if not data or len(data) > UPLOAD_BYTES:
        raise ValueError("文件为空或超过 8 MiB。")
    body = parse(data).replace("\x00", "").strip()
    if not body or len(body) > DOCUMENT_CHARS:
        raise ValueError("提取的正文为空或超过 180,000 字。")
    return {"title": title[:100], "source_name": name, "body": body}

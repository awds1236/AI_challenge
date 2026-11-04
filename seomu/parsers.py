"""문서 텍스트 추출기 (HWP/HWPX/PDF/DOCX/XLSX/HTML/TXT).

외부 서비스 없이 PC 안에서만 동작한다. 선택 의존성(pypdf, olefile, openpyxl)이
없으면 해당 형식만 건너뛴다.
"""
from __future__ import annotations

import html
import re
import struct
import zipfile
import zlib
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

SUPPORTED = {".txt", ".md", ".csv", ".hwp", ".hwpx", ".pdf", ".docx", ".xlsx", ".html", ".htm"}


class ParseError(RuntimeError):
    pass


def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


# ---------------------------------------------------------------- HTML
class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table",
             "section", "article", "header", "footer", "pre", "blockquote", "dt", "dd"}
    SKIP = {"script", "style", "noscript", "template", "svg", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append("\t")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    p = _HTMLText()
    try:
        p.feed(markup)
        p.close()
    except Exception:  # 깨진 HTML도 최대한 처리
        pass
    return normalize("".join(p.parts))


def normalize(text: str) -> str:
    text = html.unescape(text).replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t　]+\n", "\n", text)
    text = re.sub(r"[ \t　]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------- XML 기반 (HWPX / DOCX)
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _walk_xml(elem, out: list[str], text_tag: str, para_tag: str, tab_tags=("tab",), br_tags=("lineBreak", "br")):
    name = _local(elem.tag)
    if name == text_tag:
        if elem.text:
            out.append(elem.text)
        for ch in elem:
            cn = _local(ch.tag)
            if cn in tab_tags:
                out.append("\t")
            elif cn in br_tags:
                out.append("\n")
            if ch.tail:
                out.append(ch.tail)
        return
    if name in tab_tags:
        out.append("\t")
    elif name in br_tags:
        out.append("\n")
    for ch in elem:
        _walk_xml(ch, out, text_tag, para_tag, tab_tags, br_tags)
    if name == para_tag:
        out.append("\n")


def parse_hwpx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            names = sorted(
                (n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
                key=lambda n: int(re.findall(r"\d+", n)[-1]),
            )
            if not names:
                raise ParseError("HWPX 본문(section)이 없습니다")
            out: list[str] = []
            for n in names:
                root = ET.fromstring(z.read(n))
                _walk_xml(root, out, "t", "p")
            return normalize("".join(out))
    except zipfile.BadZipFile as e:
        raise ParseError(f"HWPX 파일이 손상되었습니다: {e}") from e


def parse_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError) as e:
        raise ParseError(f"DOCX 파일을 읽을 수 없습니다: {e}") from e
    out: list[str] = []
    _walk_xml(root, out, "t", "p", tab_tags=("tab",), br_tags=("br", "cr"))
    return normalize("".join(out))


# ---------------------------------------------------------------- HWP 5.0 (바이너리)
HWPTAG_PARA_TEXT = 67
_EXT_CTRL = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}


def _hwp_para_text(data: bytes) -> str:
    chars: list[str] = []
    i, n = 0, len(data) - 1
    while i < n:
        code = struct.unpack_from("<H", data, i)[0]
        if code < 32:
            if code in _EXT_CTRL:
                if code == 9:
                    chars.append("\t")
                i += 16
                continue
            if code in (10, 13):
                chars.append("\n")
            i += 2
            continue
        chars.append(chr(code))
        i += 2
    return "".join(chars)


def _hwp_records(data: bytes):
    pos, n = 0, len(data)
    while pos + 4 <= n:
        header = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        tag = header & 0x3FF
        size = (header >> 20) & 0xFFF
        if size == 0xFFF:
            if pos + 4 > n:
                break
            size = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        yield tag, data[pos:pos + size]
        pos += size


def parse_hwp(path: Path) -> str:
    try:
        import olefile  # type: ignore
    except ImportError as e:
        raise ParseError("HWP 파일을 읽으려면 olefile 패키지가 필요합니다 (pip install olefile)") from e
    if not olefile.isOleFile(str(path)):
        raise ParseError("올바른 HWP(5.0) 파일이 아닙니다")
    with olefile.OleFileIO(str(path)) as ole:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", header, 36)[0]
        compressed = bool(flags & 0x1)
        if flags & 0x4:
            raise ParseError("배포용(암호화) HWP 문서는 읽을 수 없습니다")
        sections = sorted(
            (e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
            key=lambda e: int(re.findall(r"\d+", e[1])[0]),
        )
        out: list[str] = []
        for entry in sections:
            raw = ole.openstream(entry).read()
            if compressed:
                try:
                    raw = zlib.decompress(raw, -15)
                except zlib.error:
                    raw = zlib.decompress(raw)
            for tag, payload in _hwp_records(raw):
                if tag == HWPTAG_PARA_TEXT:
                    out.append(_hwp_para_text(payload).rstrip("\n") + "\n")
        return normalize("".join(out))


# ---------------------------------------------------------------- PDF / XLSX
def parse_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as e:
        raise ParseError("PDF를 읽으려면 pypdf 패키지가 필요합니다 (pip install pypdf)") from e
    try:
        reader = PdfReader(str(path))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception as e:  # pypdf 내부 예외 다양
        raise ParseError(f"PDF를 읽을 수 없습니다: {e}") from e
    text = "\n\n".join(pages)
    if not text.strip():
        raise ParseError("PDF에 텍스트가 없습니다(스캔 이미지일 수 있음)")
    return normalize(text)


def parse_xlsx(path: Path) -> str:
    try:
        import openpyxl  # type: ignore
    except ImportError as e:
        raise ParseError("XLSX를 읽으려면 openpyxl 패키지가 필요합니다") from e
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    lines: list[str] = []
    for ws in wb.worksheets:
        lines.append(f"[시트: {ws.title}]")
        for row in ws.iter_rows(values_only=True):
            cells = ["" if v is None else str(v) for v in row]
            if any(c.strip() for c in cells):
                lines.append("\t".join(cells).rstrip())
    wb.close()
    return normalize("\n".join(lines))


# ---------------------------------------------------------------- 진입점
def parse_file(path: str | Path) -> str:
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".txt", ".md", ".csv"):
        return normalize(read_text_file(path))
    if ext in (".html", ".htm"):
        return html_to_text(read_text_file(path))
    if ext == ".hwpx":
        return parse_hwpx(path)
    if ext == ".hwp":
        return parse_hwp(path)
    if ext == ".pdf":
        return parse_pdf(path)
    if ext == ".docx":
        return parse_docx(path)
    if ext == ".xlsx":
        return parse_xlsx(path)
    raise ParseError(f"지원하지 않는 형식입니다: {ext}")


def guess_category(path: Path, text: str = "") -> str:
    name = path.stem
    probe = name + " " + text[:300]
    if re.search(r"조례|규칙\(.*(시|군|구|도)\)", probe) or "조례" in name:
        return "조례"
    if re.search(r"(법률|시행령|시행규칙|법\b|법$)", name) or re.search(r"^.{0,40}(법|시행령|시행규칙)\s*$", text[:200], re.M):
        return "법령"
    if re.search(r"내규|규정|지침|훈령|예규|매뉴얼|요령|기준", probe):
        return "내규"
    return "기타"

"""문서 텍스트 추출기 (HWP/HWPX/PDF/DOCX/XLSX/ODT/PPTX/RTF/HTML/MHT/EML/TXT, 이미지·스캔 PDF는 Windows OCR).

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

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff"}
SUPPORTED = {".txt", ".md", ".csv", ".hwp", ".hwpx", ".pdf", ".docx", ".xlsx", ".html", ".htm", ".xhtml",
             ".mht", ".mhtml", ".eml", ".odt", ".pptx", ".rtf", ".xml"} | IMAGE_EXT
# 규정 색인·붙임 미리 읽기용 (이미지 OCR은 느리므로 공문 본문으로 직접 가져올 때만 쓴다)
READABLE_EXT = SUPPORTED - IMAGE_EXT - {".xml"}


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
        self._after_link = False    # 링크 바로 뒤 (메뉴처럼 <a>가 붙어 있으면 글자가 붙어 버린다)

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append("\t")
        elif tag in ("a", "button") and self._after_link:
            self.parts.append(" ")
        self._after_link = False

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        self._after_link = tag in ("a", "button")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)
            if data.strip():
                self._after_link = False


def html_to_text(markup: str) -> str:
    p = _HTMLText()
    try:
        p.feed(markup)
        p.close()
    except Exception:  # 깨진 HTML도 최대한 처리
        pass
    return normalize("".join(p.parts))


# 홈페이지·업무포털 화면에서 본문이 아닌 영역 / 본문일 가능성이 높은 영역의 id·class
_NOISE_ATTR = re.compile(r"(^|[\s_-])(gnb|lnb|snb|nav|navi|menu|header|footer|foot|banner|quick|side|aside|util|"
                         r"sitemap|copyright|breadcrumb|location|skip|share|sns|search|login|popup|tab_?menu|paging|"
                         r"pagination|prev_?next|related|satisfaction|survey|top_?btn|family_?site)([\s_-]|$)", re.I)
_MAIN_ATTR = re.compile(r"(content|contents|cont|view|board|bbs|article|detail|read|post|doc|docbody|txt|body_?area|"
                        r"substance|main)", re.I)


def _official_slice(text: str) -> str | None:
    """공문 서식 그대로인 글(수신·제목 … 끝. … 시행·연락처)이면 공문이 시작하는 줄부터 끝까지.
    꼬리말 연락처까지 써야 하므로 본문 영역만 고르지 않는다."""
    if not re.search(r"끝\s*\.", text):
        return None
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if re.match(r"^\s*(수\s*신|제\s*목)(\s|[:：]|$)", l)), -1)
    if start < 0:
        return None
    return normalize("\n".join(lines[max(0, start - 3):]))         # 앞의 슬로건·기관명 줄 포함


def main_text(markup: str) -> str:
    """웹 페이지에서 메뉴·머리말·꼬리말을 빼고 본문 영역 글자만 (lxml이 없으면 전체 글자)."""
    full = html_to_text(markup)
    try:
        import lxml.html  # type: ignore
        doc = lxml.html.fromstring(markup)
    except Exception:
        return _official_slice(full) or full
    try:
        for el in doc.xpath("//script|//style|//noscript|//template|//nav|//aside"):
            el.drop_tree()
        for el in list(doc.iter()):
            if not isinstance(el.tag, str) or el.getparent() is None:
                continue
            attr = f"{el.get('id', '')} {el.get('class', '')}"
            tag = el.tag.lower()
            in_article = any(a.tag in ("article", "main") for a in el.iterancestors() if isinstance(a.tag, str))
            if (_NOISE_ATTR.search(attr) and not _MAIN_ATTR.search(attr)) or (tag in ("header", "footer") and not in_article):
                el.drop_tree()
        # 메뉴·꼬리말을 뺀 뒤에도 공문 서식이면 공문 전체(꼬리말 연락처 포함)를 쓴다
        official = _official_slice(html_to_text(lxml.html.tostring(doc, encoding="unicode")))
        if official:
            return official
        cands = [el for el in doc.iter() if isinstance(el.tag, str)
                 and (el.tag.lower() in ("article", "main") or _MAIN_ATTR.search(f"{el.get('id', '')} {el.get('class', '')}"))]
        best, best_len = None, 0
        for el in cands:
            n = len(re.sub(r"\s+", "", el.text_content() or ""))
            if n > best_len:
                best, best_len = el, n
        root = best if best is not None and best_len >= 80 else doc
        text = html_to_text(lxml.html.tostring(root, encoding="unicode"))
    except Exception:
        return full
    if len(text) < 40:
        return full
    m = re.search(r"^[ \t]*(?:제[ \t]*목|건[ \t]*명)[ \t]*[:：]?[ \t]*\S.*$", full, re.M)
    if m and not re.search(r"^[ \t]*(?:제[ \t]*목|건[ \t]*명)", text, re.M):
        text = m.group(0).strip() + "\n" + text          # 머리 표의 '제목' 줄은 살린다
    return text


def _decode_part(part) -> str:
    payload = part.get_payload(decode=True) or b""
    cs = part.get_content_charset() or ""
    for enc in [cs] + ["utf-8", "cp949", "euc-kr"]:
        if not enc:
            continue
        try:
            return payload.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return payload.decode("utf-8", "ignore")


def parse_mht(path: Path) -> str:
    """웹 페이지 '단일 파일'(.mht/.mhtml) — 업무포털·IE 기반 전자문서 시스템에서 자주 저장되는 형식."""
    import email
    from email import policy
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.compat32)
    htmls, texts = [], []
    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "text/html":
            htmls.append(_decode_part(part))
        elif ct == "text/plain":
            texts.append(_decode_part(part))
    if htmls:
        return main_text(max(htmls, key=len))
    if texts:
        return normalize("\n\n".join(texts))
    raw = read_text_file(path)          # MIME 머리가 없는 경우
    return main_text(raw) if "<" in raw else normalize(raw)


def read_eml(path: Path) -> dict:
    """메일(.eml): 제목·보낸이·날짜·본문과 첨부 파일 목록 [(이름, 바이트)]."""
    import email
    from email import policy
    from email.header import decode_header, make_header
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.compat32)

    def hdr(k: str) -> str:
        v = msg.get(k, "")
        try:
            return str(make_header(decode_header(v))) if v else ""
        except Exception:
            return str(v)

    plain, html_body, files = [], [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disp = (part.get("Content-Disposition") or "").lower()
        name = part.get_filename()
        if name:
            try:
                name = str(make_header(decode_header(name)))
            except Exception:
                pass
        if name or "attachment" in disp:
            files.append((name or "첨부파일", part.get_payload(decode=True) or b""))
        elif part.get_content_type() == "text/plain":
            plain.append(_decode_part(part))
        elif part.get_content_type() == "text/html":
            html_body.append(_decode_part(part))
    body = normalize("\n\n".join(plain)) if plain else (main_text("\n".join(html_body)) if html_body else "")
    return {"subject": hdr("Subject"), "from": hdr("From"), "date": hdr("Date"), "body": body, "files": files}


def parse_eml(path: Path) -> str:
    m = read_eml(path)
    head = [f"제목: {m['subject']}"] if m["subject"] else []
    head += [f"보낸 사람: {m['from']}"] if m["from"] else []
    head += [f"보낸 날짜: {m['date']}"] if m["date"] else []
    names = [n for n, _ in m["files"]]
    tail = ["", "첨부: " + ", ".join(names)] if names else []
    return normalize("\n".join(head + ["", m["body"]] + tail))


def parse_odt(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("content.xml"))
    except (zipfile.BadZipFile, KeyError) as e:
        raise ParseError(f"ODT 파일을 읽을 수 없습니다: {e}") from e
    out: list[str] = []

    def walk(el):
        name = _local(el.tag)
        if name == "tab":
            out.append("\t")
        elif name == "line-break":
            out.append("\n")
        elif name == "s":
            out.append(" ")
        if el.text and name not in ("tab", "line-break", "s"):
            out.append(el.text)
        for ch in el:
            walk(ch)
            if ch.tail:
                out.append(ch.tail)
        if name in ("p", "h"):
            out.append("\n")
        elif name == "table-cell":
            out.append("\t")
    walk(root)
    return normalize("".join(out))


def parse_pptx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            names = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                           key=lambda n: int(re.findall(r"\d+", n)[-1]))
            out: list[str] = []
            for i, n in enumerate(names, 1):
                out.append(f"\n[슬라이드 {i}]\n")
                _walk_xml(ET.fromstring(z.read(n)), out, "t", "p")
    except zipfile.BadZipFile as e:
        raise ParseError(f"PPTX 파일을 읽을 수 없습니다: {e}") from e
    return normalize("".join(out))


def parse_rtf(path: Path) -> str:
    """RTF의 글자만 (서식·그림 제외). \\'XX(코드페이지)와 \\uN(유니코드) 문자를 복원한다."""
    raw = path.read_bytes().decode("latin-1")
    m = re.search(r"\\ansicpg(\d+)", raw)
    cp = f"cp{m.group(1)}" if m else "cp949"
    raw = re.sub(r"\{\\\*[^{}]*\}|\{\\(?:fonttbl|colortbl|stylesheet|info|pict)[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", "", raw)
    out, buf = [], bytearray()

    def flush():
        if buf:
            try:
                out.append(bytes(buf).decode(cp))
            except (UnicodeDecodeError, LookupError):
                out.append(bytes(buf).decode("cp949", "ignore"))
            buf.clear()
    i, skip_next = 0, 0
    while i < len(raw):
        c = raw[i]
        if c == "\\":
            if raw.startswith("\\'", i):
                buf.append(int(raw[i + 2:i + 4], 16))
                i += 4
                continue
            flush()
            mm = re.match(r"\\([a-z]+)(-?\d+)? ?|\\(.)", raw[i:])
            if not mm:
                i += 1
                continue
            word, num, sym = mm.group(1), mm.group(2), mm.group(3)
            if word in ("par", "line", "row"):
                out.append("\n")
            elif word in ("tab", "cell"):
                out.append("\t")
            elif word == "u" and num:
                out.append(chr(int(num) % 65536))
                skip_next = 1
            elif sym in ("\\", "{", "}"):
                out.append(sym)
            i += mm.end()
            continue
        if c in "{}\r\n":
            flush()
            i += 1
            continue
        if skip_next:                      # \uN 뒤의 대체 문자 한 개는 건너뛴다
            skip_next = 0
            i += 1
            continue
        if ord(c) < 256:
            buf.append(ord(c))
        else:
            flush()
            out.append(c)
        i += 1
    flush()
    return normalize("".join(out))


_OCR_LABELS = (r"제출\s*서류|제출\s*자료|제출\s*기한|제출\s*방법|회신\s*자료|회신\s*기한|회신\s*방법|신청\s*기한|"
               r"신청\s*방법|접수\s*기한|문의\s*처|문의|담당자|연락처|일\s*시|장\s*소|대\s*상|행사명|교육명|기\s*간")


def fix_ocr_text(text: str) -> str:
    """OCR이 공문에서 자주 틀리는 표기를 바로잡는다 (1부→'1丁', 끝.→'曰', ☎→'ß', 항목 뒤 쌍점 누락 등).
    일반 단어의 오인식은 고칠 수 없으므로 공문 서식 표기에만 적용한다."""
    t = re.sub(r"(\d)\s*[丁卩部]", r"\1부", text)
    t = re.sub(r"\(\s*[ßβ帀]\s*", "(☎ ", t)
    t = re.sub(r"문의\s*[세제체치]\s*(?=[:：\s])", "문의처", t)
    t = re.sub(r"(?m)^(\s*)(?:불|븥|붇)\s*임(?=\s|$)", r"\1붙임", t)
    t = re.sub(r"바랍\s*[lI|1!니ㄴ][^\s가-힣]*(?=\s|$)", "바랍니다.", t)              # '바랍니다.' → '바랍l'
    lines = []
    for l in t.splitlines():
        s = l.strip()
        junk = bool(s) and len(s) <= 4 and not re.search(r"[가-힣A-Za-z0-9]", s.replace("그", ""))
        if junk or re.fullmatch(r"[曰日目口]\s*그?", s):
            if lines and not re.search(r"끝\s*\.\s*$", lines[-1]):
                lines[-1] += "  끝."                     # '끝.'이 '曰 그' 같은 글자로 읽힌 줄
            continue
        # '나. 제출 서류 ○○' → '나. 제출 서류: ○○' (쌍점이 빠지면 항목으로 읽지 못한다)
        l = re.sub(r"^(\s*(?:[가-하]\s*[.)]|\d{1,2}\s*[.)]|[-·○□])?\s*(?:" + _OCR_LABELS + r"))\s+(?=[^\s:：])", r"\1: ", l)
        lines.append(l)
    return "\n".join(lines)


def parse_image(path: Path) -> str:
    """사진·스캔 이미지 공문: Windows 내장 OCR로 글자를 읽는다 (인터넷 불필요)."""
    from . import winwindow
    if not winwindow.IS_WIN:
        raise ParseError("이미지 글자 읽기(OCR)는 Windows에서만 사용할 수 있습니다")
    text = winwindow.ocr_body(0, image=Path(path))
    if not text.strip():
        raise ParseError("이미지에서 글자를 읽지 못했습니다 (Windows 한국어 OCR 기능이 필요합니다)")
    return normalize(fix_ocr_text(text))


def _raw_jpegs(page) -> list[tuple[str, bytes]]:
    """Pillow 없이 PDF 페이지의 JPEG 그림(스캔 공문에 흔한 형식)을 꺼낸다."""
    out = []
    try:
        xobjs = page["/Resources"]["/XObject"].get_object()
    except Exception:
        return out
    for key in xobjs:
        try:
            obj = xobjs[key].get_object()
            filt = obj.get("/Filter")
            filters = [str(f) for f in filt] if isinstance(filt, list) else [str(filt)]
            if obj.get("/Subtype") == "/Image" and filters and filters[-1] == "/DCTDecode":
                out.append((".jpg", obj._data))
        except Exception:
            continue
    return out


def _ocr_pdf_images(reader, max_pages: int = 8) -> str:
    """스캔 PDF: 페이지에 들어 있는 그림을 꺼내 OCR한다."""
    import tempfile
    from . import winwindow
    if not winwindow.IS_WIN:
        return ""
    texts = []
    with tempfile.TemporaryDirectory() as td:
        for pi, page in enumerate(reader.pages[:max_pages]):
            try:
                imgs = [(Path(i.name).suffix or ".png", i.data) for i in page.images]
            except ImportError:          # Pillow가 없으면 JPEG(DCTDecode) 그림은 원본 바이트를 그대로 꺼낸다
                imgs = _raw_jpegs(page)
            except Exception:
                continue
            for ii, (suffix, data) in enumerate(imgs[:2]):
                p = Path(td) / f"p{pi}_{ii}{suffix}"
                try:
                    p.write_bytes(data)
                except Exception:
                    continue
                t = winwindow.ocr_body(0, image=p)
                if t.strip():
                    texts.append(t)
    return "\n\n".join(texts)


def normalize(text: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFC", html.unescape(text))      # 자모가 분리된 한글(NFD)을 붙인다
    text = re.sub(r"[​-‏⁠﻿]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
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
    if len(re.sub(r"\s", "", text)) < 20:
        ocr = _ocr_pdf_images(reader)            # 스캔 PDF → 그림 글자 읽기
        if ocr.strip():
            return normalize(fix_ocr_text(ocr))
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
    if ext in (".html", ".htm", ".xhtml"):
        return main_text(read_text_file(path))
    if ext in (".mht", ".mhtml"):
        return parse_mht(path)
    if ext == ".eml":
        return parse_eml(path)
    if ext == ".odt":
        return parse_odt(path)
    if ext == ".pptx":
        return parse_pptx(path)
    if ext == ".rtf":
        return parse_rtf(path)
    if ext == ".xml":
        raw = read_text_file(path)
        return main_text(raw) if re.search(r"<(html|body|p|div)\b", raw, re.I) else normalize(re.sub(r"<[^>]+>", "\n", raw))
    if ext in IMAGE_EXT:
        return parse_image(path)
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

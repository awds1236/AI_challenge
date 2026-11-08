"""공문 페이지 수집기.

세 가지 방식으로 공문 본문과 붙임 문서를 가져와 다운로드 폴더에 정리한다.
1) 브라우저 연동(Playwright): 프로그램이 띄운 브라우저에서 사용자가 로그인·공문을 연 뒤
   '현재 페이지 수집'을 누르면 본문(모든 iframe 포함)과 붙임파일을 로그인 세션 그대로 내려받는다.
2) URL 직접 수집: 로그인이 필요 없는 페이지를 주소로 수집한다.
3) 파일 가져오기: 이미 저장한 공문 파일(HWP/PDF/HTML 등)과 붙임을 폴더로 정리한다.
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import threading
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from .parsers import html_to_text, main_text, normalize

ATTACH_EXT = ("hwp", "hwpx", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "txt",
              "csv", "jpg", "jpeg", "png", "gif", "odt", "ods", "show", "cell", "egg", "7z")
_EXT_RE = re.compile(r"\.(" + "|".join(ATTACH_EXT) + r")(?:$|[?#&\s\]\)])", re.I)
_DL_HINT = re.compile(r"(download|filedown|file_down|getfile|atchfile|attach|fileid|fileSn|dnld|down\.do)", re.I)
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_name(name: str, limit: int = 80) -> str:
    name = _ILLEGAL.sub("_", name or "").strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    return (name[:limit].rstrip() or "제목없음")


_TITLE_TAIL = re.compile(
    r"\s*[-–—|:]\s*(?:개인\s*[-–]\s*|프로필\s*\d*\s*[-–]\s*|InPrivate\s*[-–]\s*)?"
    r"(?:Microsoft\s*Edge|Google\s*Chrome|Chrome|Chromium|Naver\s*Whale|Whale|Internet\s*Explorer|Mozilla\s*Firefox|Firefox|"
    r"온나라(?:\s*시스템)?|온나라\s*문서|문서\s*24|문서24|업무\s*관리\s*시스템|K-?에듀파인|에듀파인|전자\s*결재|그룹웨어|"
    r"전자\s*문서(?:\s*뷰어)?|문서\s*뷰어|문서\s*보기|문서|한글|Hwp|HWP|PDF|Adobe\s*Acrobat(?:\s*Reader)?(?:\s*DC)?|"
    r"메모장|Notepad|워드패드|WordPad|Microsoft\s*Word|Word)\s*$", re.I)
_TITLE_HEAD = re.compile(r"^(?:공지\s*사항|게시판|알림\s*마당|새\s*소식)?\s*(?:상세\s*보기|상세|내용\s*보기|보기)\s*[|:\-–]\s*")


def clean_title(title: str) -> str:
    """창·페이지 제목에서 브라우저·공문 시스템 이름, 폭 없는 공백, '상세보기 |' 같은 머리말을 뺀다."""
    import unicodedata
    t = unicodedata.normalize("NFC", title or "")
    t = re.sub(r"[​-‏⁠﻿]", "", t).replace("\xa0", " ").replace("　", " ")
    t = re.sub(r"\s+", " ", t).strip()
    for _ in range(3):
        t2 = _TITLE_TAIL.sub("", t).strip()
        if t2 == t or len(t2) < 2:
            break
        t = t2
    t = _TITLE_HEAD.sub("", t).strip()
    t = re.sub(r"\s*\|\s*[^|]{1,20}(?:시청|군청|구청|도청|청|부|처|원|공단|공사|재단|교육청|학교|대학교)\s*$", "", t)
    return t or (title or "").strip()


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suf = path.stem, path.suffix
    i = 2
    while True:
        cand = path.with_name(f"{stem} ({i}){suf}")
        if not cand.exists():
            return cand
        i += 1


def make_notice_folder(root: Path, title: str, when: datetime | None = None) -> Path:
    when = when or datetime.now()
    root.mkdir(parents=True, exist_ok=True)
    folder = unique_path(root / f"{when:%Y%m%d}_{safe_name(title, 60)}")
    folder.mkdir(parents=True)
    (folder / "붙임").mkdir()
    return folder


# ---------------------------------------------------------------- HTML 분석
class _LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self._cur: dict | None = None
        self.title = ""
        self._in_title = False
        self.h1: list[str] = []
        self._in_h = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            self._cur = {"href": a.get("href") or "", "onclick": a.get("onclick") or "",
                         "download": a.get("download"), "text": "", "title": a.get("title") or ""}
        elif tag == "title":
            self._in_title = True
        elif tag in ("h1", "h2"):
            self._in_h = True
            self.h1.append("")

    def handle_endtag(self, tag):
        if tag == "a" and self._cur is not None:
            self._cur["text"] = self._cur["text"].strip()
            self.links.append(self._cur)
            self._cur = None
        elif tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2"):
            self._in_h = False

    def handle_data(self, data):
        if self._cur is not None:
            self._cur["text"] += data
        if self._in_title:
            self.title += data
        if self._in_h and self.h1:
            self.h1[-1] += data


def is_attachment_link(link: dict) -> bool:
    href, text = link.get("href", ""), link.get("text", "") + " " + link.get("title", "")
    if href.lower().startswith(("mailto:", "tel:")):
        return False
    if link.get("download") is not None:
        return True
    if _EXT_RE.search(text) or _EXT_RE.search(href.split("?")[0] + " "):
        return True
    if _DL_HINT.search(href) or _DL_HINT.search(link.get("onclick", "")):
        return True
    return False


def extract_title(text: str, html_title: str = "", headings: list[str] | None = None) -> str:
    m = re.search(r"^\s*(?:제\s*목|문서\s*제목|건\s*명)\s*[:：]?\s*(.+)$", text, re.M)
    if m and len(m.group(1).strip()) > 2:
        return m.group(1).strip()[:120]
    for h in headings or []:
        h = h.strip()
        if 4 <= len(h) <= 120:
            return h
    if html_title.strip():
        return clean_title(html_title)[:120]
    for line in text.splitlines():
        line = line.strip()
        if 6 <= len(line) <= 100:
            return line
    return "공문"


_TITLE_ATTR = re.compile(r"(subject|tit|title|ntt_?sj|bbs_?sj|view_?head|headline|doc_?name)", re.I)
_TITLE_BAD_ATTR = re.compile(r"(sub_?title|site|logo|menu|gnb|lnb|snb|nav|search|popup|pop|modal|layer|quick|footer|"
                             r"banner|sitemap|location|breadcrumb|tab)", re.I)


def _title_text(el) -> str:
    """제목 요소의 글자에서 앞뒤의 짧은 분류 표시('일반', '공지', '일부', 'NEW')를 뗀다.
    '<span>일반</span><strong>제목</strong>'처럼 태그 사이에 공백이 없어도 붙지 않게 조각 사이를 띄운다."""
    text = re.sub(r"\s+", " ", " ".join(el.itertext())).strip()
    for ch in el.iterdescendants():
        if not isinstance(ch.tag, str):
            continue
        ct = re.sub(r"\s+", " ", ch.text_content() or "").strip()
        if 1 <= len(ct) <= 4:
            if text.startswith(ct + " "):
                text = text[len(ct) + 1:]
            elif text.endswith(" " + ct):
                text = text[:-len(ct) - 1]
    return text.strip()
_VIEW_ATTR = re.compile(r"(view|bbs|board|ntt|article|detail|read|post|cont|doc)", re.I)
_CHROME_ATTR = re.compile(r"(header|gnb|lnb|snb|nav|footer|menu|search|popup|sitemap|quick|util|banner)", re.I)


def post_title(markup: str) -> str:
    """게시판·문서 보기 화면에서 게시물 제목을 찾는다.
    <title>·h1은 사이트·메뉴 이름인 경우가 많아, 본문 보기 영역 안의 제목 요소(h3, .subject, .tit …)에 점수를 매긴다."""
    try:
        import lxml.html  # type: ignore
        doc = lxml.html.fromstring(markup)
    except Exception:
        return ""
    # <title>과 스크립트로 바꾸는 document.title (게시물 제목이 들어 있는 경우가 있다)
    page_titles = " ".join(re.findall(r"<title[^>]*>(.*?)</title>", markup, re.S | re.I)
                           + re.findall(r"document\.title\s*=\s*[\"'](.*?)[\"']", markup, re.I))
    site_title = re.sub(r"\s+", " ", (doc.findtext(".//title") or "")).strip()
    best: tuple = (0, 0, "")
    for el in doc.iter():
        if not isinstance(el.tag, str) or el.tag.lower() in ("script", "style", "title", "option", "a", "button"):
            continue
        if el.xpath(".//a|.//button|.//input|.//select"):      # 게시물 제목에는 링크·버튼이 없다 (메뉴·도구 상자 제외)
            continue
        text = _title_text(el)
        if not 8 <= len(text) <= 200 or re.search(r"(바로\s*가기|검색|메뉴$|로그인)", text):
            continue
        attr = f"{el.get('id', '')} {el.get('class', '')}"
        ancestors = [a for a in el.iterancestors() if isinstance(a.tag, str)]
        anc = " ".join(f"{a.get('id', '')} {a.get('class', '')}" for a in ancestors)
        near = " ".join(f"{a.get('id', '')} {a.get('class', '')}" for a in ancestors[:2])     # 부모·조부모
        score = 0
        if _TITLE_BAD_ATTR.search(attr):
            score -= 3                                          # 팝업·모달·메뉴 제목
        elif _TITLE_ATTR.search(attr):
            score += 3
        elif re.search(r"(subject|tit)", near, re.I) and not _TITLE_BAD_ATTR.search(near):
            score += 2                                          # 제목 상자 바로 안의 글자 (예: .subject > strong)
        if el.tag.lower() in ("h1", "h2", "h3", "h4"):
            score += 1
        if _VIEW_ATTR.search(anc):
            score += 2
        # 머리말·메뉴 안에 있으면 감점. 단 게시물 보기 상자 안의 '머리'(예: .board-view > .header)는 제외
        for i, a in enumerate(ancestors):
            a_attr = f"{a.get('id', '')} {a.get('class', '')} {a.tag if a.tag in ('header', 'nav', 'footer') else ''}"
            if _CHROME_ATTR.search(a_attr):
                above = " ".join(f"{b.get('id', '')} {b.get('class', '')}" for b in ancestors[i + 1:])
                if not _VIEW_ATTR.search(above):
                    score -= 4
                break
        if _CHROME_ATTR.search(attr):
            score -= 4
        if text and text in page_titles:
            score += 1
        if text == site_title:
            score -= 3
        key = (score, -len(text), text)
        if score >= 3 and key > best:
            best = key
    title = best[2]
    # '한글 제목 / English Title' → 한글 부분만
    m = re.match(r"^(.*[가-힣].*?)\s+/\s+[A-Za-z0-9 ,.:;'&()\-]+$", title)
    return (m.group(1) if m else title)[:120]


def analyze_html(markup: str, base_url: str = "") -> dict:
    lc = _LinkCollector()
    try:
        lc.feed(markup)
    except Exception:
        pass
    text = main_text(markup)            # 메뉴·꼬리말을 뺀 본문 영역
    attachments, by_key = [], {}
    for l in lc.links:
        if not is_attachment_link(l):
            continue
        href = l["href"]
        url = urllib.parse.urljoin(base_url, href) if href and not href.startswith("javascript") else ""
        key = url or (l["text"] + l["onclick"])
        name = l["text"] or l["title"] or Path(urllib.parse.urlparse(url).path).name
        if key in by_key:
            # 같은 붙임에 '다운로드' 버튼과 '파일이름.pdf' 링크가 함께 있으면 파일 이름을 쓴다
            if not _EXT_RE.search(by_key[key]["name"] + " ") and _EXT_RE.search(name + " "):
                by_key[key]["name"] = name
            continue
        by_key[key] = {"name": name, "url": url, "onclick": l["onclick"]}
        attachments.append(by_key[key])
    heads = [post_title(markup)] + lc.h1
    return {"title": extract_title(text, lc.title, [h for h in heads if h]), "text": text, "attachments": attachments}


# ---------------------------------------------------------------- 다운로드 보조
def filename_from_headers(cd: str | None, url: str, fallback: str = "붙임파일") -> str:
    name = ""
    if cd:
        m = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", cd, re.I)
        if m:
            name = urllib.parse.unquote(m.group(2).strip('" '), encoding=m.group(1) or "utf-8")
        else:
            m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I)
            if m:
                raw = m.group(1).strip()
                name = urllib.parse.unquote(raw)
                # 헤더가 latin-1로 해석된 한글 파일명 복원
                try:
                    b = name.encode("latin-1")
                    for enc in ("utf-8", "cp949"):
                        try:
                            name = b.decode(enc)
                            break
                        except UnicodeDecodeError:
                            continue
                except UnicodeEncodeError:
                    pass
    if not name:
        name = urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name)
    return safe_name(name or fallback, 120)


_COOKIES = None


def _ssl_context():
    """Windows 인증서 저장소로 검증하는 SSL 설정.
    공공기관 사이트 중에는 중간 인증서를 보내지 않는 곳이 많아 Python 기본 검증은 'unable to get local issuer
    certificate'로 실패한다 (브라우저는 Windows가 중간 인증서를 찾아 줘서 열린다). truststore가 있으면 Windows와
    같은 방식으로 검증한다. 검증 자체를 끄지는 않는다."""
    import ssl
    try:
        import truststore  # type: ignore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return ssl.create_default_context()


def _opener():
    # 수집 대상 사이트(내부 그룹웨어 등)에는 시스템 프록시 설정을 그대로 따른다.
    # 쿠키를 유지해야 '세션 쿠키를 심고 같은 주소로 다시 보내는' 사이트에서 무한 리디렉션이 나지 않는다.
    global _COOKIES
    import http.cookiejar
    if _COOKIES is None:
        _COOKIES = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_COOKIES),
                                       urllib.request.HTTPSHandler(context=_ssl_context()))


def iri_to_uri(url: str) -> str:
    """한글 등 ASCII가 아닌 문자가 든 주소를 퍼센트 인코딩한다 (이미 인코딩된 %XX는 그대로)."""
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc
    try:
        host = host.encode("idna").decode("ascii") if not host.isascii() else host
    except UnicodeError:
        pass
    q = lambda s, safe: urllib.parse.quote(s, safe=safe)  # noqa: E731
    return urllib.parse.urlunsplit((parts.scheme, host, q(parts.path, "/%:@!$&'()*+,;="),
                                    q(parts.query, "=&%:@!$'()*+,;/?"), q(parts.fragment, "%")))


def sniff_kind(path: Path) -> str:
    """파일 머리로 실제 형식을 본다: pdf / ole / hwpx / docx / xlsx / pptx / odt / zip / png / jpg / gif / html / text / ''."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return ""
    if head[:4] == b"%PDF":
        return "pdf"
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "ole"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:4] in (b"GIF8",):
        return "gif"
    if head[:2] == b"PK":
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
        except (zipfile.BadZipFile, OSError):
            return ""
        if any(re.match(r"Contents/section\d+\.xml$", n) for n in names):
            return "hwpx"
        if "word/document.xml" in names:
            return "docx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        if any(n.startswith("ppt/") for n in names):
            return "pptx"
        if "content.xml" in names:
            return "odt"
        return "zip"
    if not head or b"\0" in head:
        return ""
    text = ""
    for enc in ("utf-8", "cp949"):
        try:
            text = head.decode(enc)
            break
        except UnicodeDecodeError as e:
            if e.start > len(head) - 4:            # 4KB 경계에서 잘린 글자
                text = head[:e.start].decode(enc, "ignore")
                break
    if not text:
        return ""
    if re.search(r"<!doctype\s+html|<html[\s>]|<head[\s>]|<body[\s>]", text[:2048], re.I):
        return "html"
    printable = sum(1 for c in text if c.isprintable() or c in "\r\n\t")
    return "text" if printable / max(1, len(text)) > 0.97 else ""


# 확장자별로 실제 내용이 어떤 형식이어야 하는지 (모르는 확장자는 검사하지 않는다)
_EXPECT = {".hwp": {"ole"}, ".doc": {"ole"}, ".xls": {"ole"}, ".ppt": {"ole"}, ".pdf": {"pdf"},
           ".hwpx": {"hwpx", "zip"}, ".docx": {"docx"}, ".xlsx": {"xlsx"}, ".pptx": {"pptx"}, ".odt": {"odt"},
           ".zip": {"zip", "hwpx", "docx", "xlsx", "pptx", "odt"},
           ".png": {"png"}, ".jpg": {"jpg"}, ".jpeg": {"jpg"}, ".gif": {"gif"}}
_KIND_EXT = {"pdf": ".pdf", "hwpx": ".hwpx", "docx": ".docx", "xlsx": ".xlsx", "pptx": ".pptx", "odt": ".odt",
             "zip": ".zip", "png": ".png", "jpg": ".jpg", "gif": ".gif", "text": ".txt"}


def checked_download(path: Path, label: str = "") -> dict:
    """내려받은 붙임을 검사해 붙임 항목으로 만든다.
    - 파일 대신 웹 페이지(로그인 화면·오류 안내)가 왔으면 '받지 못함'으로 알린다.
    - 이름의 확장자와 실제 내용이 다르면(링크 글자는 '신청서.hwp'인데 내용은 글자 파일 등) 실제 형식으로 바꾼다.
      그대로 두면 미리보기도, PC 프로그램으로 열기도 되지 않는다."""
    path = Path(path)
    ext = path.suffix.lower()
    kind = sniff_kind(path)
    if kind == "html" and ext not in (".html", ".htm", ".xhtml", ".mht", ".mhtml", ".xml"):
        path.unlink(missing_ok=True)
        return {"name": label or path.name, "path": "", "ok": False,
                "error": "파일 대신 웹 페이지가 내려왔습니다 (로그인이 끊겼거나 내려받기 권한이 없을 수 있습니다) "
                         "— 브라우저 연동으로 수집하거나 직접 저장해 공문 폴더의 '붙임'에 넣어 주세요"}
    want = _EXPECT.get(ext)
    if want and kind and kind not in want and kind in _KIND_EXT:
        fixed = unique_path(path.with_suffix(_KIND_EXT[kind]))
        try:
            path.replace(fixed)
            path = fixed
        except OSError:
            pass
    return {"name": path.name, "path": str(path), "ok": True}


def download_url(url: str, dest_dir: Path, name_hint: str = "", timeout: float = 60) -> Path:
    req = urllib.request.Request(iri_to_uri(url), headers={"User-Agent": "Mozilla/5.0 SeomuAI"})
    with _opener().open(req, timeout=timeout) as r:
        cd = r.headers.get("Content-Disposition")
        name = filename_from_headers(cd, r.geturl(), name_hint)
        # 서버가 파일 이름을 알려 주지 않으면 주소 끝은 내부 이름('file-load', 'a1b2.hwpx')일 때가 많다
        # → 링크에 보이는 파일 이름이 있으면 그것을 쓴다
        if name_hint and _EXT_RE.search(name_hint + " ") and ("." not in name or not (cd and "filename" in cd.lower())):
            name = safe_name(name_hint, 120)
        path = unique_path(dest_dir / name)
        with open(path, "wb") as f:
            shutil.copyfileobj(r, f)
    return path


def fetch_url(url: str, timeout: float = 30) -> tuple[str, str]:
    req = urllib.request.Request(iri_to_uri(url), headers={"User-Agent": "Mozilla/5.0 SeomuAI"})
    with _opener().open(req, timeout=timeout) as r:
        raw = r.read()
        ctype = r.headers.get("Content-Type", "")
        final = r.geturl()
    m = re.search(r"charset=([\w-]+)", ctype, re.I) or re.search(rb'charset=["\']?([\w-]+)', raw[:2000])
    enc = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
    try:
        return raw.decode(enc, "replace"), final
    except LookupError:
        return raw.decode("utf-8", "replace"), final


@dataclass
class Captured:
    title: str
    text: str
    html: str
    url: str
    folder: Path
    files: list[dict] = field(default_factory=list)   # {"name","path","ok","error"}
    screenshot: str = ""


def save_body(folder: Path, title: str, text: str, html: str, url: str) -> None:
    (folder / "본문.txt").write_text(f"{title}\n출처: {url}\n수집: {datetime.now():%Y-%m-%d %H:%M}\n\n{text}",
                                    encoding="utf-8")
    if html:
        (folder / "본문.html").write_text(html, encoding="utf-8")


def collect_from_url(url: str, root: Path, title_override: str = "") -> Captured:
    markup, final = fetch_url(url)
    info = analyze_html(markup, final)
    title = title_override or info["title"]
    folder = make_notice_folder(root, title)
    save_body(folder, title, info["text"], markup, final)
    files = []
    for a in info["attachments"]:
        if not a["url"]:
            files.append({"name": a["name"], "path": "", "ok": False, "error": "스크립트 방식 링크(브라우저 연동 필요)"})
            continue
        try:
            p = download_url(a["url"], folder / "붙임", a["name"])
            files.append(checked_download(p, a["name"]))
        except Exception as e:  # 네트워크 오류 다양
            files.append({"name": a["name"], "path": "", "ok": False, "error": str(e)[:200]})
    return Captured(title, info["text"], markup, final, folder, files)


def _zip_name(info) -> str:
    """zip 안 파일 이름: 한국 PC에서 만든 zip은 이름이 cp949인데 UTF-8 표시가 없어 깨진다 → 복원."""
    name = info.filename
    if not (info.flag_bits & 0x800):
        try:
            name = name.encode("cp437").decode("cp949")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


def expand_archives(files: list[dict], max_files: int = 200, max_bytes: int = 500 << 20) -> list[dict]:
    """붙임 중 zip 파일을 같은 이름의 폴더에 풀고 그 안의 파일을 붙임 목록에 더한다 (zip 원본도 남긴다)."""
    import zipfile
    out = list(files)
    for f in files:
        p = Path(f.get("path") or "")
        if not f.get("ok") or p.suffix.lower() != ".zip" or not p.exists():
            continue
        try:
            with zipfile.ZipFile(p) as z:
                infos = [i for i in z.infolist() if not i.is_dir()][:max_files]
                if sum(i.file_size for i in infos) > max_bytes:
                    continue
                target = unique_path(p.with_suffix(""))
                target.mkdir(parents=True)
                for info in infos:
                    parts = [safe_name(x, 120) for x in re.split(r"[\\/]+", _zip_name(info)) if x not in ("", ".", "..")]
                    if not parts:
                        continue
                    dest = unique_path(target.joinpath(*parts))       # 상위 폴더로 빠져나가는 이름은 막는다
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    out.append({"name": f"{p.stem}/{dest.name}", "path": str(dest), "ok": True, "from": p.name})
        except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError):
            continue                 # 암호가 걸렸거나 손상된 zip은 원본만 둔다
    return out


def save_eml_attachments(eml: Path, dest: Path) -> list[dict]:
    """메일(.eml)에 첨부된 파일을 붙임 폴더로 꺼낸다."""
    from .parsers import read_eml
    files = []
    try:
        m = read_eml(eml)
    except Exception:
        return files
    for name, data in m["files"]:
        if not data:
            continue
        dest.mkdir(parents=True, exist_ok=True)
        p = unique_path(dest / safe_name(name, 120))
        p.write_bytes(data)
        files.append({"name": p.name, "path": str(p), "ok": True, "from": eml.name})
    return files


def collect_from_files(paths: list[str], root: Path, title: str = "", body_index: int = 0) -> Captured:
    """로컬 파일들로 공문 폴더 구성. body_index 번째 파일을 본문으로 본다."""
    from .parsers import ParseError, parse_file
    srcs = [Path(p) for p in paths if Path(p).exists()]
    if not srcs:
        raise FileNotFoundError("가져올 파일이 없습니다")
    expanded: list[Path] = []
    for s in srcs:
        expanded.extend(sorted(f for f in s.rglob("*") if f.is_file()) if s.is_dir() else [s])
    body_src = expanded[min(body_index, len(expanded) - 1)]
    try:
        text = parse_file(body_src)
        read_ok = True
    except (ParseError, OSError) as e:
        text = f"(본문을 읽지 못했습니다: {e})"
        read_ok = False
    # 본문을 못 읽었으면 오류 문장 대신 파일 이름을 제목으로
    title = title or (extract_title(text) if read_ok else "") or re.sub(r"[_]+", " ", body_src.stem).strip()
    folder = make_notice_folder(root, title)
    save_body(folder, title, text, "", str(body_src))
    files = []
    for f in expanded:
        dest_dir = folder if f == body_src else folder / "붙임"
        dest = unique_path(dest_dir / (("본문_" + f.name) if f == body_src else f.name))
        shutil.copy2(f, dest)
        if f != body_src:
            files.append({"name": dest.name, "path": str(dest), "ok": True})
        if f.suffix.lower() == ".eml":                     # 메일 공문: 첨부 파일도 붙임으로
            files.extend(save_eml_attachments(f, folder / "붙임"))
    return Captured(title, text, "", str(body_src), folder, files)


def collect_from_text(text: str, root: Path, title: str = "", html: str = "", base_url: str = "") -> Captured:
    """붙여넣은 공문 (어떤 공문 시스템이든 본문을 복사해 붙여 넣으면 된다).
    웹 페이지에서 복사하면 HTML도 함께 오므로 표 구조를 살리고 붙임 링크 이름을 찾는다."""
    text = normalize(text or "")
    links: list[dict] = []
    if html and html.strip():
        info = analyze_html(html, base_url)
        h_text = main_text(html)
        if len(h_text) >= len(text) * 0.6:            # HTML 쪽이 표·줄 구조가 더 정확하다
            text = h_text
        links = info["attachments"][:10]
    if len(re.sub(r"\s", "", text)) < 10:
        raise ValueError("붙여 넣은 본문이 너무 짧습니다. 공문 본문 전체를 복사해 붙여 넣어 주세요.")
    title = title or extract_title(text)
    folder = make_notice_folder(root, title)
    save_body(folder, title, text, html or "", base_url or "붙여넣기")
    files = []
    for a in links:
        if a["url"].startswith(("http://", "https://")):
            try:
                p = download_url(a["url"], folder / "붙임", a["name"], timeout=20)
                files.append(checked_download(p, a["name"]))
                continue
            except Exception as e:  # 로그인이 필요한 링크·업무망 안 주소 등
                code = getattr(e, "code", None)
                why = (f"서버 응답 {code}" if code else
                       "주소에 연결할 수 없음" if "getaddrinfo" in str(e) or "Errno" in str(e) else "연결 실패")
                err = (f"자동으로 받지 못했습니다({why}). 로그인이 필요한 링크일 수 있으니 "
                       "브라우저 연동으로 수집하거나, 파일을 직접 저장해 공문 폴더의 '붙임'에 넣어 주세요")
        else:
            err = "붙여넣기로는 내려받을 수 없는 링크입니다 — 직접 저장해 공문 폴더의 '붙임'에 넣어 주세요"
        files.append({"name": a["name"], "path": "", "ok": False, "error": err})
    return Captured(title, text, "", base_url or "붙여넣기", folder, files)


# ---------------------------------------------------------------- 브라우저 연동 (Playwright)
_JS_LINKS = r"""
() => Array.from(document.querySelectorAll('a, button, [onclick]')).map((el, i) => {
  el.setAttribute('data-seomu-idx', String(i));
  return {idx: i, tag: el.tagName.toLowerCase(), href: el.getAttribute('href') || '',
          abs: el.href || '', onclick: el.getAttribute('onclick') || '',
          download: el.hasAttribute('download') ? '' : null,
          text: (el.innerText || el.textContent || '').trim().slice(0, 200),
          title: el.getAttribute('title') || ''};
})
"""


# 글자 조각을 화면 위치로 배치하는 변환 뷰어(사이냅식·PDF.js 글자 층 등)용: 글자마다 화면 좌표를 모은다
_JS_LAYOUT = r"""
() => {
  const out = []; let positioned = 0, total = 0;
  if (!document.body) return {items: out, positioned: 0, total: 0};
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    const t = n.textContent; if (!t || !t.trim()) continue;
    const el = n.parentElement; if (!el) continue;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || ['SCRIPT','STYLE','NOSCRIPT'].includes(el.tagName)) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    const b = r.getBoundingClientRect(); if (!b.width && !b.height) continue;
    total++;
    let p = el, abs = false;
    for (let i = 0; i < 2 && p; i++, p = p.parentElement) { const ps = getComputedStyle(p).position; if (ps === 'absolute' || ps === 'fixed') { abs = true; break; } }
    if (abs) positioned++;
    out.push({t: t, x: b.left + scrollX, y: b.top + scrollY, w: b.width, h: b.height});
  }
  return {items: out, positioned: positioned, total: total};
}
"""

_JS_PDF_SOURCES = r"""
() => Array.from(document.querySelectorAll('embed, object, iframe')).map(e => e.src || e.data || '')
     .filter(s => /\.pdf(\?|#|$)/i.test(s) || /application\/pdf/i.test(s))
"""


def _in_pdf(frame) -> bool:
    """PDF 문서 프레임이거나 그 안(PDF 뷰어가 만든 about:blank 프레임)인지."""
    f = frame
    for _ in range(6):
        if f is None:
            return False
        if re.search(r"\.pdf(\?|#|$)", f.url or "", re.I):
            return True
        try:
            f = f.parent_frame
        except Exception:
            return False
    return False


def layout_text(items: list[dict]) -> str:
    """화면 좌표를 가진 글자 조각을 읽는 순서(위→아래, 왼쪽→오른쪽)로 줄을 만들고,
    조각 사이 간격이 넓으면 띄어쓰기를 넣는다 (띄어쓰기 문자 없이 위치로만 띄운 변환 뷰어 대응)."""
    items = sorted((i for i in items if i["t"].strip()), key=lambda i: (i["y"] + i["h"] / 2, i["x"]))
    lines: list[list[dict]] = []
    for it in items:
        cy = it["y"] + it["h"] / 2
        if lines and abs(cy - lines[-1][0]["_cy"]) < max(4.0, min(it["h"], lines[-1][0]["h"]) * 0.5):
            lines[-1].append(it)
        else:
            it = dict(it)
            it["_cy"] = cy
            lines.append([it])
    out = []
    for ln in lines:
        ln.sort(key=lambda i: i["x"])
        s, right = "", None
        for it in ln:
            t = it["t"]
            if right is not None:
                gap = it["x"] - right
                if gap > it["h"] * 0.22 and not s.endswith((" ", "\t")) and not t.startswith((" ", "\t")):
                    s += " "
            s += t
            right = it["x"] + it["w"]
        out.append(re.sub(r"[ \t]+", " ", s).strip())
    return "\n".join(l for l in out if l)


def fix_mojibake(name: str) -> str:
    """옛 서버가 인코딩 표시 없이 보낸 CP949·UTF-8 파일 이름이 깨져 보이면 복원한다 ('Áý' → '집')."""
    if not name or re.search(r"[가-힣]", name):
        return name
    if not re.search(r"[\u0080-ÿ]", name):
        return name
    try:
        raw = name.encode("latin-1")
    except UnicodeEncodeError:
        return name
    for enc in ("utf-8", "cp949"):
        try:
            fixed = raw.decode(enc)
            if re.search(r"[가-힣]", fixed):
                return fixed
        except UnicodeDecodeError:
            continue
    return name


class BrowserWorker:
    """Playwright는 생성한 스레드에서만 써야 하므로 전용 스레드에서 명령을 처리한다."""

    def __init__(self, profile_dir: Path, channel: str = "", headless: bool = False):
        self.profile_dir = Path(profile_dir)
        self.channel = channel
        self.headless = headless
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._pw = None
        self._ctx = None

    @staticmethod
    def available() -> bool:
        try:
            import playwright.sync_api  # noqa: F401
            return True
        except ImportError:
            return False

    def _loop(self):
        while True:
            fn, fut = self._q.get()
            if fn is None:
                break
            try:
                fut.set_result(fn())
            except Exception as e:  # 작업 오류를 호출자에게 전달
                fut.set_exception(e)
        self._shutdown()

    def _call(self, fn: Callable, timeout: float = 600):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="seomu-browser", daemon=True)
            self._thread.start()
        fut: Future = Future()
        self._q.put((fn, fut))
        return fut.result(timeout=timeout)

    # ---- 아래 메서드는 전용 스레드에서 실행 ----
    def _ensure(self):
        if self._ctx is not None:
            try:
                _ = self._ctx.pages
                return self._ctx
            except Exception:
                self._ctx = None
        from playwright.sync_api import sync_playwright
        if self._pw is None:
            self._pw = sync_playwright().start()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        kwargs = dict(headless=self.headless, accept_downloads=True, viewport=None,
                      args=["--start-maximized"])
        exe = os.environ.get("SEOMU_BROWSER_PATH")
        if exe:
            kwargs["executable_path"] = exe
        channels = [self.channel] if self.channel else (["msedge", "chrome", ""] if not exe else [""])
        last = None
        for ch in channels:
            try:
                if ch:
                    self._ctx = self._pw.chromium.launch_persistent_context(str(self.profile_dir), channel=ch, **kwargs)
                else:
                    self._ctx = self._pw.chromium.launch_persistent_context(str(self.profile_dir), **kwargs)
                break
            except Exception as e:
                last = e
        if self._ctx is None:
            raise RuntimeError(f"브라우저를 실행할 수 없습니다: {last}")
        return self._ctx

    def _shutdown(self):
        try:
            if self._ctx:
                self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = self._pw = None

    def _active_page(self):
        ctx = self._ensure()
        pages = [p for p in ctx.pages if not p.is_closed()]
        if not pages:
            return ctx.new_page()
        real = [p for p in pages if p.url not in ("about:blank", "")]
        return (real or pages)[-1]

    # ---- 공개 API ----
    def open(self, url: str = "") -> dict:
        def _do():
            page = self._active_page()
            if url:
                page.goto(url, wait_until="domcontentloaded")
            try:
                page.bring_to_front()
            except Exception:
                pass
            return {"url": page.url, "title": page.title()}
        return self._call(_do)

    def pages(self) -> list[dict]:
        def _do():
            ctx = self._ensure()
            return [{"index": i, "url": p.url, "title": p.title()} for i, p in enumerate(ctx.pages) if not p.is_closed()]
        return self._call(_do)

    def close(self) -> None:
        if self._thread and self._thread.is_alive():
            fut: Future = Future()
            self._q.put((None, fut))
            self._thread.join(timeout=10)

    def capture(self, root: Path, page_index: int | None = None, title_override: str = "",
                progress: Callable[[str], None] | None = None) -> Captured:
        def _do():
            ctx = self._ensure()
            pages = [p for p in ctx.pages if not p.is_closed()]
            page = pages[page_index] if page_index is not None and 0 <= page_index < len(pages) else self._active_page()
            say = progress or (lambda m: None)
            say("페이지가 다 그려질 때까지 기다리는 중…")
            self._wait_settled(page)
            say("페이지 본문을 읽는 중…")
            html_parts, texts, candidates, pdf_urls, headings, images = [], [], [], [], [], []
            how = "브라우저 화면 글자"
            for fr in page.frames:
                if _in_pdf(fr):                      # PDF 프레임(과 그 안의 뷰어 프레임)은 글자 읽기 명령에 응답하지 않는다
                    if re.search(r"\.pdf(\?|#|$)", fr.url or "", re.I):
                        pdf_urls.append(fr.url)      # → 원본을 받아 읽는다
                    continue
                try:
                    h = fr.content()
                except Exception:
                    continue
                html_parts.append(h)
                pt = post_title(h)                    # 게시물 제목 (사이트·메뉴 이름이 아닌)
                if pt:
                    headings.insert(0, pt)
                try:
                    t = fr.evaluate("() => document.body ? document.body.innerText : ''")
                except Exception:
                    t = html_to_text(h)
                # 메뉴·머리말·꼬리말을 뺀 본문 영역이 충분하면 그것을 쓴다 (업무포털·문서24 화면의 메뉴 글자 제거)
                try:
                    from .parsers import main_text
                    m = main_text(h)
                    if len(m) >= 40 and len(m) >= len(t or "") * 0.4:
                        t = m
                except Exception:
                    pass
                # 변환 뷰어(글자 조각을 위치로 배치)는 화면 좌표로 줄·띄어쓰기를 다시 맞춘다
                try:
                    lay = fr.evaluate(_JS_LAYOUT)
                    if lay["total"] >= 10 and lay["positioned"] >= lay["total"] * 0.5:
                        t = layout_text(lay["items"])
                        how = "변환 뷰어 화면 배치"
                except Exception:
                    pass
                try:
                    headings += [x.strip() for x in fr.evaluate(
                        "() => Array.from(document.querySelectorAll('h1,h2,h3,.subject,.title,.tit')).map(e => e.innerText)") if x]
                    images += [urllib.parse.urljoin(fr.url, u) for u in fr.evaluate(
                        "() => Array.from(document.images).filter(i => i.naturalWidth > 500).map(i => i.currentSrc || i.src)")]
                except Exception:
                    pass
                if t and t.strip():
                    texts.append(t)
                try:
                    pdf_urls += [urllib.parse.urljoin(fr.url, u) for u in fr.evaluate(_JS_PDF_SOURCES)]
                except Exception:
                    pass
                try:
                    for l in fr.evaluate(_JS_LINKS):
                        if is_attachment_link({"href": l["href"], "text": l["text"], "title": l["title"],
                                               "onclick": l["onclick"], "download": l["download"]}):
                            l["frame"] = fr
                            candidates.append(l)
                except Exception:
                    continue
            # 가장 긴 본문 텍스트(공문 본문 iframe)를 앞에 둔다
            texts.sort(key=len, reverse=True)
            text = normalize("\n\n".join(dict.fromkeys(texts)))
            # 화면에 삽입된 PDF 문서(PDF 변환 뷰어): 원본을 받아 글자를 읽는다
            pdf_body = None
            for u in dict.fromkeys(pdf_urls):
                try:
                    resp = page.context.request.get(u, timeout=30000)
                    if resp.ok and resp.body()[:4] == b"%PDF":
                        pdf_body = resp.body()
                        break
                except Exception:
                    continue
            if pdf_body:
                from .parsers import ParseError, parse_pdf
                import tempfile
                tmp = Path(tempfile.gettempdir()) / "seomu_embedded.pdf"
                tmp.write_bytes(pdf_body)
                try:
                    pt = parse_pdf(tmp)
                    if len(pt) > len(text) * 0.5:
                        text = normalize(pt + "\n\n" + text) if len(text) < 200 else normalize(pt)
                        how = "화면에 삽입된 PDF"
                except ParseError:
                    pass
            # 화면 캡처 (그림뿐인 이미지 뷰어면 캡처를 글자 인식)
            import tempfile
            shot_tmp = Path(tempfile.gettempdir()) / f"seomu_shot_{os.getpid()}.png"
            try:
                page.screenshot(path=str(shot_tmp), full_page=True)
            except Exception:
                shot_tmp = None
            if len(re.sub(r"\s", "", text)) < 60:
                say("글자가 없는 화면이라 그림에서 글자를 읽는 중…")
                from .parsers import ParseError, parse_image
                # 화면에 축소돼 보이는 그림보다 원본 그림이 글자 인식이 정확하다
                srcs = []
                for i, u in enumerate(dict.fromkeys(images)):
                    try:
                        resp = page.context.request.get(u, timeout=30000)
                        if resp.ok:
                            p = Path(tempfile.gettempdir()) / f"seomu_page_{os.getpid()}_{i}.png"
                            p.write_bytes(resp.body())
                            srcs.append(p)
                    except Exception:
                        continue
                if not srcs and shot_tmp and shot_tmp.exists():
                    srcs = [shot_tmp]
                parts = []
                for p in srcs[:10]:
                    try:
                        parts.append(parse_image(p))
                    except ParseError:
                        pass
                ocr = "\n\n".join(parts)
                if len(ocr) > len(text):
                    text, how = ocr, "화면 그림 글자 인식(OCR)"
            info = analyze_html(html_parts[0] if html_parts else "", page.url)
            # 제목: 본문의 '제목' 줄 > 화면 안의 제목(h1·h2) > 탭 제목
            heads = [h for h in headings if 8 <= len(h) <= 120]
            title = title_override or extract_title(text, "", heads)
            if title in ("공문", "") or (not re.search(r"^\s*(제\s*목|건\s*명)", text, re.M) and not heads):
                title = title_override or extract_title(text, page.title(), heads) or info["title"]
            folder = make_notice_folder(root, title)
            save_body(folder, title, text, "\n<!-- frame -->\n".join(html_parts), page.url)
            if pdf_body:
                (folder / "본문_원문.pdf").write_bytes(pdf_body)
            shot = ""
            if shot_tmp and shot_tmp.exists():
                shot_path = folder / "본문_화면.png"
                shutil.move(str(shot_tmp), shot_path)
                shot = str(shot_path)
            (folder / "수집기록.txt").write_text(f"본문 읽은 방법: {how}\n주소: {page.url}\n", encoding="utf-8")
            files, seen = [], set()
            for c in candidates:
                key = c["abs"] or (c["text"] + c["onclick"])
                if key in seen:
                    continue
                seen.add(key)
                say(f"붙임 다운로드: {c['text'][:40]}")
                files.append(self._download(page, c, folder / "붙임"))
            return Captured(title, text, "", page.url, folder, files, shot)
        return self._call(_do)

    @staticmethod
    def _wait_settled(page, limit: float = 8.0) -> None:
        """그룹웨어처럼 내용을 나중에 그리는 화면: 통신이 잦아들고 글자 수가 더 늘지 않을 때까지 기다린다."""
        import time as _t
        for state, ms in (("domcontentloaded", 10000), ("networkidle", 5000)):
            try:
                page.wait_for_load_state(state, timeout=ms)
            except Exception:
                pass

        def size() -> int:
            n = 0
            for fr in page.frames:
                if _in_pdf(fr):                                            # PDF 프레임은 응답하지 않는다
                    continue
                try:
                    n += int(fr.evaluate("() => document.body ? document.body.innerText.length : 0"))
                except Exception:
                    pass
            return n
        end, last, stable = _t.time() + limit, -1, 0
        while _t.time() < end:
            cur = size()
            stable = stable + 1 if cur == last and cur > 0 else 0
            if stable >= 2 and not re.search(r"(불러오는|로딩|loading)", page.content()[:20000], re.I):
                return
            last = cur
            _t.sleep(0.4)

    def _download(self, page, c: dict, dest: Path) -> dict:
        name_hint = c["text"] or c["title"] or "붙임파일"
        url = c.get("abs") or ""
        err = ""
        # 1) 일반 링크: 로그인 세션(쿠키)을 그대로 써서 직접 요청 (페이지 이동 없음)
        if url.startswith("http") and not url.lower().startswith("javascript"):
            try:
                resp = page.context.request.get(url, timeout=60000)
                ctype = (resp.headers.get("content-type") or "").lower()
                cd = resp.headers.get("content-disposition")
                if resp.ok and (cd or "text/html" not in ctype):
                    name = filename_from_headers(cd, url, name_hint)
                    if "." not in name and "." in name_hint:
                        name = safe_name(name_hint, 120)
                    path = unique_path(dest / name)
                    path.write_bytes(resp.body())
                    got = checked_download(path, name_hint)
                    if got["ok"]:
                        return got
                    err = got["error"]                 # 웹 페이지가 왔다 → 실제로 눌러 보는 방법으로
                else:
                    err = f"HTTP {resp.status} ({ctype or '알 수 없는 형식'})"
            except Exception as e:
                err = str(e)
        # 2) 스크립트형 다운로드: 실제로 클릭해 다운로드 이벤트를 받는다
        before = page.url
        fr = c["frame"]
        try:
            with page.expect_download(timeout=15000) as dl_info:
                fr.click(f'[data-seomu-idx="{c["idx"]}"]', timeout=5000)
            dl = dl_info.value
            path = unique_path(dest / safe_name(fix_mojibake(dl.suggested_filename) or name_hint, 120))
            dl.save_as(str(path))
            return checked_download(path, name_hint)
        except Exception as e:
            err = err or str(e)
        finally:
            try:
                if page.url != before:
                    page.go_back(wait_until="domcontentloaded", timeout=10000)
            except Exception:
                pass
        return {"name": name_hint, "path": "", "ok": False, "error": err[:200]}

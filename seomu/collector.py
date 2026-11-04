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
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from .parsers import html_to_text, normalize

ATTACH_EXT = ("hwp", "hwpx", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "txt",
              "csv", "jpg", "jpeg", "png", "gif", "odt", "ods", "show", "cell", "egg", "7z")
_EXT_RE = re.compile(r"\.(" + "|".join(ATTACH_EXT) + r")(?:$|[?#&\s\]\)])", re.I)
_DL_HINT = re.compile(r"(download|filedown|file_down|getfile|atchfile|attach|fileid|fileSn|dnld|down\.do)", re.I)
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_name(name: str, limit: int = 80) -> str:
    name = _ILLEGAL.sub("_", name or "").strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    return (name[:limit].rstrip() or "제목없음")


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
        return html_title.strip()[:120]
    for line in text.splitlines():
        line = line.strip()
        if 6 <= len(line) <= 100:
            return line
    return "공문"


def analyze_html(markup: str, base_url: str = "") -> dict:
    lc = _LinkCollector()
    try:
        lc.feed(markup)
    except Exception:
        pass
    text = html_to_text(markup)
    attachments, seen = [], set()
    for l in lc.links:
        if not is_attachment_link(l):
            continue
        href = l["href"]
        url = urllib.parse.urljoin(base_url, href) if href and not href.startswith("javascript") else ""
        key = url or (l["text"] + l["onclick"])
        if key in seen:
            continue
        seen.add(key)
        attachments.append({"name": l["text"] or l["title"] or Path(urllib.parse.urlparse(url).path).name,
                            "url": url, "onclick": l["onclick"]})
    return {"title": extract_title(text, lc.title, lc.h1), "text": text, "attachments": attachments}


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


def _opener():
    # 수집 대상 사이트(내부 그룹웨어 등)에는 시스템 프록시 설정을 그대로 따른다.
    return urllib.request.build_opener()


def download_url(url: str, dest_dir: Path, name_hint: str = "", timeout: float = 60) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SeomuAI"})
    with _opener().open(req, timeout=timeout) as r:
        name = filename_from_headers(r.headers.get("Content-Disposition"), r.geturl(), name_hint)
        if "." not in name and name_hint and "." in name_hint:
            name = safe_name(name_hint, 120)
        path = unique_path(dest_dir / name)
        with open(path, "wb") as f:
            shutil.copyfileobj(r, f)
    return path


def fetch_url(url: str, timeout: float = 30) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SeomuAI"})
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
            files.append({"name": p.name, "path": str(p), "ok": True})
        except Exception as e:  # 네트워크 오류 다양
            files.append({"name": a["name"], "path": "", "ok": False, "error": str(e)[:200]})
    return Captured(title, info["text"], markup, final, folder, files)


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
    except (ParseError, OSError) as e:
        text = f"(본문을 읽지 못했습니다: {e})"
    title = title or extract_title(text) or body_src.stem
    folder = make_notice_folder(root, title)
    save_body(folder, title, text, "", str(body_src))
    files = []
    for f in expanded:
        dest_dir = folder if f == body_src else folder / "붙임"
        dest = unique_path(dest_dir / (("본문_" + f.name) if f == body_src else f.name))
        shutil.copy2(f, dest)
        if f != body_src:
            files.append({"name": dest.name, "path": str(dest), "ok": True})
    return Captured(title, text, "", str(body_src), folder, files)


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
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            say = progress or (lambda m: None)
            say("페이지 본문을 읽는 중…")
            html_parts, texts, candidates = [], [], []
            for fr in page.frames:
                try:
                    h = fr.content()
                except Exception:
                    continue
                html_parts.append(h)
                try:
                    t = fr.evaluate("() => document.body ? document.body.innerText : ''")
                except Exception:
                    t = html_to_text(h)
                if t and t.strip():
                    texts.append(t)
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
            info = analyze_html(html_parts[0] if html_parts else "", page.url)
            title = title_override or extract_title(text, page.title(), [])
            if title in ("공문", "") and info["title"]:
                title = info["title"]
            folder = make_notice_folder(root, title)
            save_body(folder, title, text, "\n<!-- frame -->\n".join(html_parts), page.url)
            shot = ""
            try:
                shot_path = folder / "본문_화면.png"
                page.screenshot(path=str(shot_path), full_page=True)
                shot = str(shot_path)
            except Exception:
                pass
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
                    return {"name": path.name, "path": str(path), "ok": True}
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
            path = unique_path(dest / safe_name(dl.suggested_filename or name_hint, 120))
            dl.save_as(str(path))
            return {"name": path.name, "path": str(path), "ok": True}
        except Exception as e:
            err = err or str(e)
        finally:
            try:
                if page.url != before:
                    page.go_back(wait_until="domcontentloaded", timeout=10000)
            except Exception:
                pass
        return {"name": name_hint, "path": "", "ok": False, "error": err[:200]}

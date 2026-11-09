"""붙임파일 자동 인식 (시스템에 상관없는 범용 방식).

공문서는 본문 끝에 '붙임 1. ○○○ 1부. 2. △△△ 1부. 끝.' 형식으로 붙임 목록을 적는다.
이 목록으로 '모아야 할 파일'을 먼저 알아낸 뒤, PC 안에 이미 생긴 파일(다운로드·임시·캐시 폴더,
최근 문서 목록)에서 이름이 비슷한 파일을 찾아 모은다. 뷰어·그룹웨어 종류와 무관하게 동작한다.
"""
from __future__ import annotations

import hashlib
import ntpath
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DOC_EXT = {".hwp", ".hwpx", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".txt",
           ".csv", ".jpg", ".jpeg", ".png", ".odt", ".ods", ".odp", ".show", ".cell", ".egg", ".7z", ".gul",
           ".hwt", ".hml"}
SKIP_DIRS = {"seomu_work", "microsoft", "google", "mozilla", "packages", "nvidia", "intel", "amd", "crashdumps", "d3dscache",
             "npm-cache", "pip", "node_modules", ".git", "__pycache__", "seomuai", "python", "programs",
             "fontcache", "iconcache", "comms", "connecteddevicesplatform", "cache2", "code cache",
             "gpucache", "service worker", "indexeddb", "webcache", "inetcache"}


# ---------------------------------------------------------------- 붙임 목록 해석
# 줄 머리 기호: 화면 글자 인식(OCR)은 '○'를 '0·o·ㅇ'로, '·'를 '•·ㆍ'로 읽기도 한다.
# '붙임'도 OCR에서 '붙 임'·'붙입'·'불임'으로 읽히는 일이 있다 (공문 본문에 '불임'이 쓰일 일은 거의 없다)
_ATTACH_HEAD = re.compile(r"(?:^|\n)[ \t□■○●◯◦•·ㆍ∙※*\-–0oOㅇ]{0,4}"
                          r"(?:[붙불][ \t]*[임입]|첨[ \t]*부(?:[ \t]*(?:파[ \t]*일|문[ \t]*서))?)"
                          r"(?![가-힣])[ \t]*[:：]?")
# 붙임 목록이 문장 뒤에 이어 붙은 경우 (OCR·본문복사가 줄을 합친 경우): '…바랍니다. 붙임 1. ○○ 1부. 끝.'
_ATTACH_INLINE = re.compile(r"(?<=[.。])[ \t]+(?:붙[ \t]*임|첨[ \t]*부)[ \t]*[:：]?(?=[ \t]*(?:\d{1,2}\s*[.)]|[①②③④⑤⑥⑦⑧⑨⑩]|[^\n]{2,80}?\d+\s*부))")
DOC_NAME = re.compile(r"([^\\/:*?\"<>|\n\t]{1,120}?)\s?\.\s?(hwpx|hwp|pdf|docx|doc|xlsx|xls|pptx|ppt|zip|hwt|cell|show|odt|ods|txt|jpg|jpeg|png|gul|egg|7z)(?![A-Za-z0-9])",
                      re.I)
_COUNT_TAIL = re.compile(r"\s*(?:각\s*)?\d+\s*(?:부|매|권|장|건|식|개)\s*\.?\s*$")


def expected_attachments(body: str) -> list[str]:
    """본문의 '붙임' 표기에서 붙임 문서 이름 목록을 뽑는다."""
    body = body or ""

    def is_own_label(mm) -> bool:
        # 붙임 문서 자신의 이름표: 문서 맨 위(첫 두 줄)의 '붙임1. ○○ 안내서' — 붙임 목록이 아니다
        before = [l for l in body[:mm.start()].splitlines() if l.strip()]
        line_end = body.find("\n", mm.end())
        line = body[mm.end(): line_end if line_end >= 0 else len(body)]
        return len(before) <= 1 and not re.search(r"\d+\s*(?:부|매|권)|끝\s*\.", line)

    m = None
    for mm in _ATTACH_HEAD.finditer(body):
        if not is_own_label(mm):
            m = mm                 # 보통 마지막 '붙임'이 실제 붙임 목록
    if not m:
        for mm in _ATTACH_INLINE.finditer(body):
            if not is_own_label(mm):
                m = mm
    if not m:
        return []
    tail = body[m.end():]
    end = re.search(r"끝\s*\.", tail)
    if end:
        tail = tail[: end.start()]
    else:
        # '끝.'이 없으면 붙임 항목처럼 생긴 줄까지만 ('1. ○○ 1부', '○○.hwp')
        # — 그 아래 본문('< 한눈에 보기 >', '구분', '세션 1' 등)을 붙임 이름으로 읽지 않는다
        lines = tail.splitlines()
        keep = [lines[0]] if lines else []
        item = re.compile(r"^\s*(?:\d{1,2}\s*[.)]|[①②③④⑤⑥⑦⑧⑨⑩]|[-·○]\s)|\d+\s*(?:부|매|권)\s*\.?\s*$|\.[A-Za-z]{2,5}\s*$")
        for l in lines[1:12]:
            if not l.strip():
                if len(keep) > 1:
                    break
                continue
            if not item.search(l) or re.search(r"[가-힣]{2,8}\s*[:：]\s*\S", l):   # '3. 문의처: …' 같은 본문 항목
                break
            keep.append(l)
        first = (keep[0] if keep else "").strip()
        if len(keep) == 1 and first and not item.search(first) and len(first) > 40:
            return []                       # '붙임' 뒤에 문장이 이어진 것 — 붙임 목록이 아님
        tail = "\n".join(keep)
    tail = tail.replace("\t", " ")
    # '1. A 1부. 2. B 1부.' / 줄바꿈 / '①' 형식 모두 나눈다
    parts = re.split(r"(?:^|\s)(?:\d{1,2}\s*[.)]|[①②③④⑤⑥⑦⑧⑨⑩])\s+", "\n" + tail)
    if len(parts) <= 1:
        parts = [tail]
    names: list[str] = []
    for p in parts:
        for line in p.splitlines():
            line = re.sub(r"\s+", " ", line).strip(" .,·-")
            line = _COUNT_TAIL.sub("", line).strip(" .,·-")
            if len(line) >= 2 and not re.fullmatch(r"[\d\s.]+", line):
                names.append(line)
    return list(dict.fromkeys(names))[:20]


def file_names_in(text: str) -> list[str]:
    """글자(화면 글자 인식·목록 항목)에서 '파일이름.hwpx' 꼴의 문서 이름을 뽑는다.
    뷰어의 '붙임목록'·'첨부파일' 칸에 보이는 이름처럼, 본문에 붙임 표기가 없을 때도 붙임을 알아낼 수 있다."""
    out: list[str] = []
    for line in (text or "").splitlines():
        for m in DOC_NAME.finditer(line):
            stem = re.sub(r"^\s*(?:[□○●◦•·ㆍ\-]|\d{1,2}\s*[.)]|붙\s*임\s*\d*\s*[.:]?|첨\s*부\s*[:：]?)\s*", "", m.group(1)).strip(" .,:;·")
            stem = re.sub(r"\s*\(\s*\d+(?:\.\d+)?\s*(?:[KMG]B|bytes?|바이트)\s*\)\s*$", "", stem, flags=re.I)
            if len(re.sub(r"[\W_]", "", stem)) < 2:
                continue
            out.append(f"{stem}.{m.group(2).lower()}")
    return list(dict.fromkeys(out))[:30]


def merge_names(base: list[str], more: list[str], same: float = 0.8) -> list[str]:
    """붙임 이름 목록에 다른 곳(화면 목록 등)에서 찾은 이름을 겹치지 않게 더한다.
    같은 붙임으로 보이면(이름이 비슷하면) 확장자까지 있는 쪽(화면 목록 이름)을 쓴다."""
    out = list(base)
    for n in more:
        hit = next((i for i, b in enumerate(out) if name_score(b, n) >= same), -1)
        if hit < 0:
            out.append(n)
        elif not re.search(r"\.[A-Za-z0-9]{2,5}$", out[hit]):
            out[hit] = n
    return out[:30]


# ---------------------------------------------------------------- 이름 비슷한 정도
def _norm(s: str) -> str:
    s = os.path.splitext(s)[0] if re.search(r"\.[A-Za-z0-9]{2,5}$", s or "") else (s or "")
    s = re.sub(r"\(\d+\)$", "", s.strip())                 # '파일 (1)' 같은 중복 번호
    s = re.sub(r"^[\[(]?\s*붙임\s*\d*\s*[\])]?\s*", "", s)   # '(붙임1) ' 접두어
    return re.sub(r"[\s_\-.,·()\[\]{}「」『』<>~!@#$%^&*+=]", "", s).lower()


def _bigrams(s: str) -> set[str]:
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def name_score(expected: str, filename: str) -> float:
    """0~1. 붙임 표기 이름과 파일 이름이 얼마나 비슷한지 (말줄임 '…' 이름도 지원)."""
    a, b = _norm(expected), _norm(filename.replace("…", "").replace("...", ""))
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(b) >= 4 and (b in a or a in b):
        return 0.9
    if len(b) >= 3 and a.startswith(b):                    # 화면에 잘려 보이는 이름
        return 0.8
    x, y = _bigrams(a), _bigrams(b)
    return 2 * len(x & y) / (len(x) + len(y))


def best_match(expected: str, names: list[str], threshold: float = 0.45) -> tuple[int, float]:
    best, score = -1, 0.0
    for i, n in enumerate(names):
        sc = name_score(expected, n)
        if sc > score:
            best, score = i, sc
    return (best, score) if score >= threshold else (-1, score)


# ---------------------------------------------------------------- PC 안에서 후보 파일 찾기
def search_roots() -> list[tuple[Path, int]]:
    """(폴더, 탐색 깊이) — 붙임이 내려받아지거나 열릴 때 파일이 생기는 곳."""
    home = Path.home()
    roots = [(home / "Downloads", 2), (home / "Desktop", 1), (home / "Documents", 2)]
    for env, depth in (("TEMP", 4), ("LOCALAPPDATA", 5), ("APPDATA", 5)):
        v = os.environ.get(env)
        if v:
            roots.append((Path(v), depth))
    if os.environ.get("USERPROFILE"):
        roots.append((Path(os.environ["USERPROFILE"]) / "AppData" / "LocalLow", 5))
    seen, out = set(), []
    for p, d in roots:
        key = os.path.normcase(str(p))
        if p.exists() and key not in seen:
            seen.add(key)
            out.append((p, d))
    return out


def recent_documents(hours: float = 6) -> list[str]:
    """Windows '최근 항목'에 남은 파일 경로 (붙임을 한글·PDF로 열면 여기에 기록된다)."""
    if not sys.platform.startswith("win"):
        return []
    ps = (f"$s=New-Object -ComObject WScript.Shell; $t=(Get-Date).AddHours(-{hours}); "
          "Get-ChildItem \"$env:APPDATA\\Microsoft\\Windows\\Recent\" -Filter *.lnk -ErrorAction SilentlyContinue | "
          "Where-Object { $_.LastWriteTime -gt $t } | ForEach-Object { $s.CreateShortcut($_.FullName).TargetPath }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                              "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + ps],
                             capture_output=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return [l.strip() for l in out.stdout.decode("utf-8", "ignore").splitlines() if l.strip()]
    except Exception:
        return []


def candidate_files(since: float, roots: list[tuple[Path, int]] | None = None, budget: float = 8.0,
                    exclude: Path | None = None, extra: list[str] | None = None) -> list[dict]:
    """since(유닉스 시각) 이후 생기거나 바뀐 문서 파일 목록. budget초 안에서만 탐색."""
    roots = roots if roots is not None else search_roots()
    deadline = time.time() + budget
    found: dict[str, dict] = {}
    excl = os.path.normcase(str(exclude.resolve())) if exclude else None

    def add(path: str, st):
        key = os.path.normcase(path)
        if excl and key.startswith(excl):
            return
        found[key] = {"path": path, "name": os.path.basename(path), "mtime": st.st_mtime, "size": st.st_size}

    def walk(p: str, depth: int):
        if time.time() > deadline:
            return
        try:
            with os.scandir(p) as it:
                for e in it:
                    try:
                        if e.is_file(follow_symlinks=False):
                            if (os.path.splitext(e.name)[1].lower() in DOC_EXT and not e.name.startswith(("~$", "."))
                                    and not e.name.lower().startswith("seomu_")):
                                st = e.stat()
                                if st.st_mtime >= since and st.st_size > 0:
                                    add(e.path, st)
                        elif depth > 0 and e.is_dir(follow_symlinks=False) and e.name.lower() not in SKIP_DIRS:
                            walk(e.path, depth - 1)
                    except OSError:
                        continue
        except OSError:
            pass

    for root, depth in roots:
        walk(str(root), depth)
    for path in extra or []:
        try:
            st = os.stat(path)
            if os.path.splitext(path)[1].lower() in DOC_EXT and st.st_size > 0:
                add(path, st)
        except OSError:
            continue
    return sorted(found.values(), key=lambda f: -f["mtime"])


_GENERIC_WORDS = {"붙임", "첨부", "서식", "양식", "파일", "자료", "1부", "사본"}


def _words(s: str) -> set[str]:
    s = os.path.splitext(s)[0] if re.search(r"\.[A-Za-z0-9]{2,5}$", s or "") else (s or "")
    ws = set(re.findall(r"[가-힣A-Za-z]{2,}", s))
    return {w for w in ws if w not in _GENERIC_WORDS}


def same_document(expected: str, filename: str) -> bool:
    """PC 안의 파일이 그 붙임이 맞는지 (이름 일부만 같은 다른 문서를 고르지 않게).
    '2026년 하반기 점검 계획' ↔ '2026년 하반기 점검 결과 보고' → 아님 ('계획'이 없다)."""
    if name_score(expected, filename) >= 0.9:
        return True
    want = _words(expected.replace("…", "").replace("...", ""))
    have = _words(filename)
    if len(want) < 2:
        return name_score(expected, filename) >= 0.8
    covered = sum(1 for w in want if w in have or any(w in h or h in w for h in have if len(h) >= 2))
    return covered / len(want) >= 0.8


def meaningless_name(filename: str) -> bool:
    """뷰어가 붙인 관리용 이름인지 ('15684_AT_db6840f3cbd3435fb84962add454f41c.pdf', 'tmp1a2b.hwp' 등)."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    if re.search(r"[0-9a-f]{12,}", stem, re.I) or re.fullmatch(r"(?:tmp|temp|file|download|attach)?[\W_\d]*", stem, re.I):
        return True
    return not re.search(r"[가-힣]", stem) and len(re.findall(r"[A-Za-z]{3,}", stem)) == 0


def match_by_content(text: str, names: list[str]) -> int:
    """파일 내용(앞부분)에 붙임 이름의 낱말이 가장 많이 들어 있는 붙임의 번호. 확실하지 않으면 -1.
    붙임 문서는 보통 첫머리에 제목(=붙임 이름)이 있다."""
    head = re.sub(r"\s+", " ", (text or "")[:3000])
    if len(head) < 10 or not names:
        return -1
    flat = head.replace(" ", "")
    scored = []
    for i, n in enumerate(names):
        want = _words(n)
        if not want:
            continue
        cov = sum(1 for w in want if w in flat) / len(want)
        exact = re.sub(r"\s", "", n) in flat
        scored.append((1.0 if exact else cov, i))
    if not scored:
        return -1
    scored.sort(reverse=True)
    best, i = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    return i if best >= 0.75 and best - second >= 0.15 else -1


def match_files(expected: list[str], files: list[dict], threshold: float = 0.45,
                strict: bool = False) -> dict[str, dict]:
    """붙임 이름 → 가장 비슷한(같으면 최신) 파일. 같은 파일을 두 번 쓰지 않는다.
    strict=True면 붙임 이름의 낱말이 파일 이름에 거의 다 있어야 한다 (PC 안 파일을 찾을 때)."""
    out: dict[str, dict] = {}
    used: set[str] = set()
    names = [f["name"] for f in files]
    pairs = []
    for e in expected:
        for i, n in enumerate(names):
            sc = name_score(e, n)
            if sc >= threshold and (not strict or same_document(e, n)):
                pairs.append((sc, files[i]["mtime"], e, i))
    for sc, _mt, e, i in sorted(pairs, key=lambda x: (-x[0], -x[1])):
        if e in out or files[i]["path"] in used:
            continue
        out[e] = dict(files[i], score=round(sc, 2))
        used.add(files[i]["path"])
    return out


def file_hash(path: str | Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_TITLE_PATH = re.compile(r"(?P<name>[^\[\]\\/:*?\"<>|]+\.[A-Za-z0-9]{2,5})\s*\[(?P<dir>[A-Za-z]:\\[^\]]*)\]")
_FULL_PATH = re.compile(r"(?P<path>[A-Za-z]:\\[^\[\]*?\"<>|]+?\.[A-Za-z0-9]{2,5})(?=\s|$|\s-\s)")


def path_from_title(title: str) -> str:
    """'파일.hwpx [C:\\폴더\\] - 한글' 또는 'C:\\폴더\\파일.pdf - 뷰어' 같은 창 제목에서 파일 경로를 얻는다."""
    m = _TITLE_PATH.search(title or "")
    if m:
        return ntpath.join(m.group("dir"), m.group("name").strip())
    m = _FULL_PATH.search(title or "")
    return m.group("path") if m else ""


def name_from_title(title: str) -> str:
    """경로가 없는 창 제목에서 파일 이름만 (예: '계약서.pdf - Adobe Acrobat')."""
    m = re.search(r"([^\\/:*?\"<>|\[\]]+\.(?:hwpx?|pdf|docx?|xlsx?|pptx?|zip|txt|cell|show))", title or "", re.I)
    return m.group(1).strip() if m else ""

"""모든 공문 처리 환경 종합 검증.

실제 공공기관·공기업의 공문 처리 환경을 흉내 낸 모의 환경(tools/mock_env/)과 형식별 예시 공문(sample_data/verify/)을
실제 앱 API로 하나씩 수집하고, 제목·기한·제출물·붙임·요약 문장 품질을 자동 판정해 docs/검증결과.md를 만든다.

  파일        : HWPX·DOCX·ODT·RTF·PDF·사진·스캔 PDF·MHT·EML+ZIP·HTML·TXT·CP949·HWX·손상 파일 …
  붙여넣기    : 웹에서 복사한 글자·웹 서식·빈 내용
  주소        : 홈페이지 게시판·옛 EUC-KR 페이지·문서24형·잘못된 주소
  브라우저 연동: 온나라 2.0형·문서24형·K-에듀파인형·그룹웨어 전자결재(SPA)·사이냅식 변환 뷰어·PDF.js식 뷰어·
                이미지 뷰어·PDF 삽입형 (화면 없이 실행)
  열린 창     : 데스크톱 전자문서 뷰어 4종 (화면 밖에 활성화 없이 띄움)

검증하는 동안 사용자 화면을 가로채지 않는지도 판정한다: 앞에 있는 창(포그라운드)이 바뀌거나
화면 안에 새 창이 나타나면 실패로 기록한다.

    python tools/verify_all.py                 # 전체 (Windows)
    python tools/verify_all.py --no-window     # 데스크톱 뷰어 생략
    python tools/verify_all.py --no-browser    # 브라우저 연동 생략

데이터는 임시 폴더에만 저장되며 실제 다운로드 폴더·설정은 건드리지 않는다.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
SAMPLES = ROOT / "sample_data"
OUT = SAMPLES / "verify"
TODAY = date.today()
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)      # 콘솔 창이 깜빡이지 않게

from mock_env.notices import N1, N2, N3, N4, N5, N6, N7, html_of, text_of  # noqa: E402


# ---------------------------------------------------------------- 형식별 파일 만들기
def make_hwpx(path: Path, n: dict) -> None:
    ns = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
    paras = "".join(f"<hp:p><hp:run><hp:t>{l}</hp:t></hp:run></hp:p>" for l in n["lines"])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", f'<?xml version="1.0" encoding="UTF-8"?><hs:sec {ns}>{paras}</hs:sec>')


def make_docx(path: Path, n: dict) -> None:
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    paras = "".join(f"<w:p><w:r><w:t>{l}</w:t></w:r></w:p>" for l in n["lines"])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {w}><w:body>{paras}</w:body></w:document>')


def make_odt(path: Path, n: dict) -> None:
    t = 'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
    paras = "".join(f"<text:p>{l}</text:p>" for l in n["lines"])
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", f'<office:document-content {t}><office:body><office:text>{paras}</office:text></office:body></office:document-content>')


def make_rtf(path: Path, n: dict) -> None:
    def enc(s: str) -> str:
        return "".join(c if ord(c) < 128 else f"\\u{ord(c) if ord(c) < 32768 else ord(c) - 65536}?" for c in s)
    body = "\\par\n".join(enc(l) for l in n["lines"])
    path.write_text("{\\rtf1\\ansi\\ansicpg949{\\fonttbl{\\f0 Malgun Gothic;}}\\f0 " + body + "\\par}", encoding="ascii")


def make_xlsx(path: Path, title: str = "현황표") -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    ws.append(["부서", "예산액", "집행액", "잔액"])
    ws.append(["총무과", 1000000, 800000, 200000])
    wb.save(path)


def _ps(script: str, *args: str) -> None:
    f = Path(tempfile.gettempdir()) / "seomu_verify.ps1"
    f.write_text(script, encoding="utf-8-sig")            # PowerShell 5.1은 BOM이 있어야 한글을 UTF-8로 읽는다
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(f), *args],
                   capture_output=True, timeout=120, creationflags=NO_WINDOW)


def make_png(path: Path, n: dict) -> None:
    lines = "".join(f'"{l}",' for l in n["lines"]).rstrip(",")
    _ps(r"""param([string]$Out)
Add-Type -AssemblyName System.Drawing
$lines = @(%s)
$bmp = New-Object System.Drawing.Bitmap 1500, (80 + 80 * $lines.Count)
$g = [System.Drawing.Graphics]::FromImage($bmp); $g.Clear([System.Drawing.Color]::White)
$font = New-Object System.Drawing.Font("Malgun Gothic", 20); $y = 40
foreach ($l in $lines) { $g.DrawString($l, $font, [System.Drawing.Brushes]::Black, 40, $y); $y += 80 }
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)""" % lines, str(path))


def edge_path() -> str:
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES")):
        p = Path(base or "") / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if p.exists():
            return str(p)
    return ""


def html_to_pdf(html: Path, pdf: Path) -> bool:
    exe = edge_path()
    if not exe:
        return False
    prof = Path(tempfile.mkdtemp(prefix="seomu_edge_"))
    subprocess.run([exe, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={prof}",
                    f"--print-to-pdf={pdf}", html.as_uri()], capture_output=True, timeout=120, creationflags=NO_WINDOW)
    shutil.rmtree(prof, ignore_errors=True)
    return pdf.exists() and pdf.stat().st_size > 500


def build_samples() -> dict:
    """sample_data/verify/ 에 형식별 예시를 만든다. {이름: 경로}"""
    OUT.mkdir(parents=True, exist_ok=True)
    for old in ("11_메모장_공문.txt",):
        (OUT / old).unlink(missing_ok=True)
    s = {}
    s["hwpx"] = OUT / "01_온나라_공문.hwpx"
    make_hwpx(s["hwpx"], N1)
    s["docx"] = OUT / "02_교육안내.docx"
    make_docx(s["docx"], N2)
    s["odt"] = OUT / "03_협조메모.odt"
    make_odt(s["odt"], N3)
    s["rtf"] = OUT / "04_교육안내.rtf"
    make_rtf(s["rtf"], N2)
    s["txt_two"] = OUT / "05_기한두개.txt"
    s["txt_two"].write_text(text_of(N4), encoding="utf-8")
    s["txt_none"] = OUT / "06_기한없는_안내.txt"
    s["txt_none"].write_text(text_of(N5), encoding="cp949")              # 옛 PC의 ANSI(CP949) 저장 파일
    s["xlsx"] = OUT / "붙임_집행잔액_현황표.xlsx"
    make_xlsx(s["xlsx"])
    h = OUT / "07_공문.html"
    h.write_text(html_of(N1), encoding="utf-8")
    s["pdf"] = OUT / "07_문서24_공문.pdf"
    s["pdf_ok"] = html_to_pdf(h, s["pdf"])
    h.unlink()
    s["png"] = OUT / "08_사진_공문.png"
    make_png(s["png"], N2)
    if s["png"].exists():
        hi = OUT / "09_scan.html"
        hi.write_text(f'<html><body style="margin:0"><img src="{s["png"].name}" style="width:100%"></body></html>', encoding="utf-8")
        s["scan_pdf"] = OUT / "09_스캔_공문.pdf"
        s["scan_ok"] = html_to_pdf(hi, s["scan_pdf"])
        hi.unlink()
    s["bad"] = OUT / "10_손상된_파일.hwpx"
    s["bad"].write_bytes(b"PK\x03\x04 broken")
    from mock_env.hwp5 import write_hwp
    s["hwp"] = OUT / "12_한글5_공문.hwp"                                      # 한글 5.0 바이너리 (OLE 복합 문서)
    write_hwp(s["hwp"], N6["lines"])
    s["hwp_attach"] = OUT / "붙임_안전교육_실적_보고서.hwp"
    write_hwp(s["hwp_attach"], ["안전교육 실적 보고서", "학교명\t교육 일자\t참여 인원", "○○초등학교\t2026. 11. 20.\t320명"])
    s["hwx"] = OUT / "11_전자결재_문서.hwx"                                  # 확장자로 알 수 없는 전자결재 문서
    s["hwx"].write_text(f'<?xml version="1.0" encoding="utf-8"?><HWX><BODY>{"".join(f"<P>{l}</P>" for l in N7["lines"])}</BODY></HWX>',
                        encoding="utf-8")
    return s


# ---------------------------------------------------------------- 화면 가로채기 감시 (포그라운드·새 창)
class ScreenWatch:
    """검증하는 동안 앞에 있는 창이 바뀌거나 화면 안에 새 창이 나타나는지 지켜본다."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.u = ctypes.windll.user32
        self.u.GetForegroundWindow.restype = wintypes.HWND
        self.wintypes, self.ctypes = wintypes, ctypes
        self.w = self.u.GetSystemMetrics(78) or self.u.GetSystemMetrics(0)     # 가상 화면 (여러 모니터)
        self.h = self.u.GetSystemMetrics(79) or self.u.GetSystemMetrics(1)
        self.x0, self.y0 = self.u.GetSystemMetrics(76), self.u.GetSystemMetrics(77)

    def descendants(self) -> set[int]:
        """이 검증 프로세스가 띄운 프로그램들(자식·손자 프로세스)의 PID. 사용자가 직접 바꾼 창은 판정하지 않는다."""
        ct, w = self.ctypes, self.wintypes

        class PE(ct.Structure):
            _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                        ("th32DefaultHeapID", ct.c_void_p), ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                        ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", ct.c_long), ("dwFlags", w.DWORD),
                        ("szExeFile", ct.c_wchar * 260)]
        k = ct.windll.kernel32
        k.CreateToolhelp32Snapshot.restype = w.HANDLE
        snap = k.CreateToolhelp32Snapshot(0x2, 0)
        parent: dict[int, int] = {}
        pe = PE()
        pe.dwSize = ct.sizeof(PE)
        ok = k.Process32FirstW(snap, ct.byref(pe))
        while ok:
            parent[pe.th32ProcessID] = pe.th32ParentProcessID
            ok = k.Process32NextW(snap, ct.byref(pe))
        k.CloseHandle(snap)
        mine, grew = {os.getpid()}, True
        while grew:
            grew = False
            for pid, pp in parent.items():
                if pp in mine and pid not in mine:
                    mine.add(pid)
                    grew = True
        return mine

    def on_screen(self, pids: set[int] | None = None) -> dict[int, str]:
        from seomu import winwindow
        out = {}
        for w in winwindow.list_windows():
            if pids is not None and w["pid"] not in pids:
                continue
            r = self.wintypes.RECT()
            self.u.GetWindowRect(w["hwnd"], self.ctypes.byref(r))
            vis_w = min(r.right, self.x0 + self.w) - max(r.left, self.x0)
            vis_h = min(r.bottom, self.y0 + self.h) - max(r.top, self.y0)
            if vis_w > 80 and vis_h > 80 and not self.u.IsIconic(w["hwnd"]):
                out[w["hwnd"]] = w["title"]
        return out

    def run(self, fn):
        fg0 = int(self.u.GetForegroundWindow() or 0)
        before = self.on_screen()
        events: list[str] = []
        stop = threading.Event()

        def poll():
            from seomu import winwindow
            n, mine = 0, self.descendants()
            while not stop.is_set():
                if n % 10 == 0:
                    mine = self.descendants()                     # 새로 띄운 프로그램도 포함
                fg = int(self.u.GetForegroundWindow() or 0)
                if fg and fg != fg0 and winwindow._pid(fg) in mine:
                    t = winwindow._text(fg) or "(제목 없음)"
                    msg = f"앞에 있는 창이 바뀜 → '{t[:40]}'"
                    if msg not in events:
                        events.append(msg)
                n += 1
                if n % 10 == 0:                                   # 0.5초마다 화면 안에 새 창이 떴는지
                    for h, t in self.on_screen(mine).items():
                        msg = f"화면에 새 창이 나타남 → '{t[:40]}'"
                        if h not in before and msg not in events:
                            events.append(msg)
                time.sleep(0.05)
        th = threading.Thread(target=poll, daemon=True)
        th.start()
        try:
            return fn(), events
        finally:
            stop.set()
            th.join(2)


# ---------------------------------------------------------------- 판정
BAD_SUMMARY = ("하오니", "바랍니다", "귀 기관", "무궁한", "다음과 같이", "아래와 같이", "하고자", "바랍l", "주시기",
               "에서는", "요청 — 협조 요청", "대비하여", "참고 요청", "'26.", "본문을 읽지 못했습니다", "불러오는")


def judge(case: dict, n: dict | None, err: str = "") -> list[str]:
    exp = case.get("expect") or {}
    if exp.get("error"):
        return [] if err and exp["error"] in err else [f"오류 안내가 나와야 함 (받은 것: {err or '오류 없음'})"]
    if err:
        return [f"수집 실패: {err}"]
    probs = []
    a = n.get("analysis") or {}
    body = n.get("body") or ""
    if exp.get("title") and exp["title"] not in n.get("title", ""):
        probs.append(f"제목: '{n.get('title')}'")
    dates = [d["date"] for d in a.get("deadlines") or []]
    if "dates" in exp and dates != exp["dates"]:
        probs.append(f"기한 {dates} (기대 {exp['dates']})")
    items = " / ".join(s["item"] for s in a.get("submissions") or [])
    for sub in exp.get("subs", []):
        if sub not in items:
            probs.append(f"제출물에 '{sub}' 없음 ({items or '없음'})")
    for sub in exp.get("no_subs", []):
        if sub in items:
            probs.append(f"참고 자료 '{sub}'가 제출물에 들어감")
    if exp.get("event") and exp["event"] not in str(a.get("event")):
        probs.append(f"행사 일시 없음 ({a.get('event')})")
    summ = a.get("summary") or ""
    if not summ.strip():
        probs.append("요약이 비어 있음")
    for w in BAD_SUMMARY:
        if w in summ:
            probs.append(f"요약에 '{w}'")
    whats = [d["what"] for d in a.get("deadlines") or []]
    if "whats" in exp and not case.get("ocr") and whats != exp["whats"]:
        probs.append(f"할 일 문구 {whats} (기대 {exp['whats']})")
    for d in a.get("deadlines") or []:
        if re.search(r"\(\s*\)|\(서식\)|에서는|기한$", d["what"]):
            probs.append(f"할 일 문구 이상: {d['what']}")
    if re.search(r"[\u200b\u00a0\u3000\ue000-\uf8ff]", body):
        probs.append("본문에 특수 공백·아이콘 글자가 남음")
    if "\n\n\n" in body:
        probs.append("본문에 빈 줄이 겹침")
    if body != unicodedata.normalize("NFC", body):
        probs.append("본문 한글 자모 분리")
    for menu in ("로그인", "로그아웃", "사이트맵", "개인정보처리방침", "열린시정", "불러오는 중", "URL 복사", "홍길동"):
        if menu in body:
            probs.append(f"본문에 화면 메뉴 글자 '{menu}'")
    for phrase in exp.get("phrases", []):            # 변환 뷰어: 줄 순서·띄어쓰기가 되살아났는지
        if phrase not in body:
            probs.append(f"본문에 '{phrase}' 없음 (줄·띄어쓰기 복원 실패)")
    files = n.get("attachments") or []
    ok_att = [f["name"] for f in files if f.get("ok")]
    if len(ok_att) < exp.get("att_ok", 0):
        probs.append(f"붙임 {len(ok_att)}개 받음 (기대 {exp['att_ok']}개 이상)")
    for name in exp.get("att_names", []):
        if not any(name in x for x in ok_att):
            probs.append(f"붙임 '{name}' 없음 (받은 것: {ok_att or '없음'})")
    return probs


# ---------------------------------------------------------------- 실행
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(folder: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(folder)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _expect_error(fn, *a):
    try:
        fn(*a)
    except Exception as e:
        return None, str(e)
    return None, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--report", default=str(ROOT / "docs" / "검증결과.md"))
    args = ap.parse_args()

    print("예시 만드는 중…")
    s = build_samples()
    work = Path(tempfile.mkdtemp(prefix="seomu_verify_"))
    os.environ["SEOMU_DOWNLOADS"] = str(work / "dl")
    os.environ["SEOMU_NO_FOREGROUND"] = "1"            # 검증 중에는 어떤 경우에도 창을 앞으로 가져오지 않는다
    from seomu.api import Api
    from mock_env import desktop, web_systems
    api = Api(work / "home")
    api.save_settings({"ollama_url": "http://127.0.0.1:9", "browser_headless": True, "capture_foreground": False})

    # 홈페이지 게시판(주소 수집)용 정적 서버
    site = work / "site"
    (site / "files").mkdir(parents=True)
    shutil.copy2(s["hwpx"], site / "files" / "현황표 서식.hwpx")
    (site / "board.html").write_text(html_of(N1, board=True, links=[("현황표 서식.hwpx", "files/%ED%98%84%ED%99%A9%ED%91%9C%20%EC%84%9C%EC%8B%9D.hwpx")]),
                                     encoding="utf-8")
    httpd, base = serve(site)
    # 웹 공문 시스템 모의 서버
    wf = work / "webfiles"
    wf.mkdir()
    make_hwpx(wf / "onnara_form.hwpx", N1)
    shutil.copy2(s["pdf"] if s.get("pdf_ok") else s["hwpx"], wf / "onnara_guide.pdf")
    make_xlsx(wf / "doc24_list.xlsx", "명단")
    shutil.copy2(s["hwp_attach"], wf / "edu_form.hwp")
    make_xlsx(wf / "gw_form.xlsx", "추진과제")
    if s["png"].exists():
        shutil.copy2(s["png"], wf / "page1.png")
    if s.get("pdf_ok"):
        shutil.copy2(s["pdf"], wf / "doc.pdf")
    websrv, web = web_systems.start(wf)

    def job(name, *a):
        j = getattr(api, name)(*a)
        for _ in range(2400):
            st = api.job_status(j["job_id"])
            if st["status"] != "running":
                return (st["result"], "") if st["status"] == "done" else (None, st["error"])
            time.sleep(0.1)
        return None, "시간 초과"

    def files(*paths):
        return lambda: job("collect_files", [str(p) for p in paths], "", 0, False)

    def browser(path: str, wait: float = 0.5):
        def run():
            api.browser_open(web + path)
            time.sleep(wait)
            return job("capture_browser", None, "", False)
        return run

    web_copy = unicodedata.normalize("NFD", text_of(N1)).replace(" ", "\u00a0", 3).replace("\n", "\n\n") + "\u200b"
    F = "파일"
    cases = [
        {"path": F, "fmt": "HWPX (한글, 온나라)", "run": files(s["hwpx"]), "expect": {**N1}},
        {"path": F, "fmt": "DOCX (워드)", "run": files(s["docx"]), "expect": {**N2}},
        {"path": F, "fmt": "ODT (오픈오피스)", "run": files(s["odt"]), "expect": {**N3}},
        {"path": F, "fmt": "RTF", "run": files(s["rtf"]), "expect": {**N2}},
        {"path": F, "fmt": "PDF (문서24 출력)", "run": files(s["pdf"]), "expect": {**N1}, "skip": None if s.get("pdf_ok") else "Edge 없음"},
        {"path": F, "fmt": "PNG (사진 공문, OCR)", "run": files(s["png"]), "expect": {"dates": N2["dates"], "subs": N2["subs"]},
         "skip": None if s["png"].exists() else "이미지 생성 불가", "ocr": True},
        {"path": F, "fmt": "스캔 PDF (OCR)", "run": files(s["scan_pdf"]) if s.get("scan_ok") else None,
         "expect": {"dates": N2["dates"]}, "skip": None if s.get("scan_ok") else "Edge 없음", "ocr": True},
        {"path": F, "fmt": "MHT (에듀파인 웹 저장)", "run": files(SAMPLES / "formats" / "에듀파인_웹공문.mht"),
         "expect": {"title": "학교폭력 예방교육", "dates": ["2026-12-04"]}},
        {"path": F, "fmt": "EML (메일) + ZIP 붙임", "run": files(SAMPLES / "formats" / "메일_공문.eml"),
         "expect": {"dates": ["2026-11-19"], "att_ok": 4}},
        {"path": F, "fmt": "HTML (홈페이지 게시판 저장)", "run": files(SAMPLES / "formats" / "홈페이지_게시판_공지.html"),
         "expect": {"title": "정책제안 공모전", "dates": ["2026-11-30"]}},
        {"path": F, "fmt": "TXT (기업 전자결재 협조전)", "run": files(SAMPLES / "formats" / "회사_전자결재_협조문.txt"),
         "expect": {"dates": ["2026-11-19"]}},
        {"path": F, "fmt": "HWX (전자결재 문서, 내용으로 형식 판별)", "run": files(s["hwx"]), "expect": {**N7}},
        {"path": F, "fmt": "HWP (한글 5.0 바이너리, 압축 본문)", "run": files(s["hwp"]), "expect": {**N6}},
        {"path": F, "fmt": "본문 HWPX + 붙임 HWP (한글 뷰어 없이 붙임 미리보기)", "run": files(s["hwpx"], s["hwp_attach"]),
         "expect": {"dates": N1["dates"], "att_ok": 1}, "preview_ext": (".hwp", "320명")},
        {"path": F, "fmt": "TXT (기한 두 개)", "run": files(s["txt_two"]), "expect": N4},
        {"path": F, "fmt": "TXT (기한 없는 안내, CP949)", "run": files(s["txt_none"]), "expect": {**N5}},
        {"path": F, "fmt": "본문 + 붙임 여러 개 (XLSX 미리보기)", "run": files(s["hwpx"], s["xlsx"], s["docx"]),
         "expect": {"dates": N1["dates"], "att_ok": 2}, "preview": True},
        {"path": F, "fmt": "손상된 파일", "run": files(s["bad"]), "expect": {"dates": [], "title": "손상된 파일"}, "lenient": True},
        {"path": "붙여넣기", "fmt": "웹에서 복사한 글자 (자모 분리·특수 공백·빈 줄)",
         "run": lambda: job("collect_text", web_copy, "", False, ""), "expect": {**N1}},
        {"path": "붙여넣기", "fmt": "웹 HTML 서식 함께 복사",
         "run": lambda: job("collect_text", "열린시정알림마당\n" + text_of(N2), "", False, html_of(N2, board=True)), "expect": {**N2}},
        {"path": "붙여넣기", "fmt": "빈 내용", "run": lambda: _expect_error(api.collect_text, "  ", "", False),
         "expect": {"error": "붙여 넣은 본문이 없습니다"}},
        {"path": "주소", "fmt": "홈페이지 게시판 + 붙임 내려받기", "run": lambda: job("collect_url", base + "/board.html", "", False),
         "expect": {**N1, "att_ok": 1}},
        {"path": "주소", "fmt": "문서24형 + UTF-8 파일 이름 붙임", "run": lambda: job("collect_url", web + "/doc24/view", "", False),
         "expect": {**N2, "att_names": ["참석자 명단 서식.xlsx"]}},
        {"path": "주소", "fmt": "옛 EUC-KR 인코딩 페이지", "run": lambda: job("collect_url", web + "/euckr/notice", "", False),
         "expect": {**N1}},
        {"path": "주소", "fmt": "지자체·교육청 게시판형 (쿠키 리디렉션·메뉴 속 제목·기간 표·겹친 붙임 링크)",
         "run": lambda: job("collect_url", web + "/board/view", "", False),
         "expect": {"title": "2026학년도 기간제 교원 채용 서류 제출 안내",
                    "dates": ["2026-11-20", "2026-11-25", "2026-12-02"],
                    "whats": ["채용 서류 제출", "1차 교과 신청", "2차 비교과 신청"],
                    "att_names": ["채용 서류 제출 서식.hwpx"], "phrases": ["가. 제출 기간"]}},
        {"path": "주소", "fmt": "잘못된 주소", "run": lambda: _expect_error(api.collect_url, "ftp://x", "", False),
         "expect": {"error": "http:// 또는 https://"}},
    ]
    if not args.no_browser:
        B = "브라우저 연동"
        cases += [
            {"path": B, "fmt": "온나라 2.0형 (편집기 iframe·스크립트 붙임·CP949 파일 이름)", "run": browser("/onnara/view"),
             "expect": {**N1, "att_names": ["집행잔액 현황표 서식.hwpx", "결산 일정 안내문.pdf"]}},
            {"path": B, "fmt": "문서24형 (머리 표·UTF-8 붙임)", "run": browser("/doc24/view"),
             "expect": {**N2, "att_names": ["참석자 명단 서식.xlsx"]}},
            {"path": B, "fmt": "K-에듀파인형 (iframe 3단·POST 붙임)", "run": browser("/edufine/view"),
             "expect": {**N6, "att_names": ["안전교육 실적 보고서 서식.hwp"]}, "preview_ext": (".hwp", "320명")},
            {"path": B, "fmt": "그룹웨어 전자결재 (늦게 그려지는 화면·로그인 쿠키 붙임)", "run": browser("/groupware/view", 0.0),
             "expect": {**N7, "att_names": ["부서별 추진과제 작성표.xlsx"]}},
            {"path": B, "fmt": "사이냅식 변환 뷰어 (위치로 배치한 낱말·뒤섞인 순서)", "run": browser("/synap/view"),
             "expect": {**N3, "phrases": ["각 부서에서는 변경된 연락처를", "부서별 비상연락망 정비 협조"]}},
            {"path": B, "fmt": "PDF.js식 뷰어 (캔버스 위 글자 층)", "run": browser("/pdfjs/view"),
             "expect": {**N1, "phrases": ["가. 제출 기한: 2026. 12. 4.(금) 17:00까지"]}},
            {"path": B, "fmt": "이미지 뷰어 (그림뿐인 화면, OCR)", "run": browser("/image/view"),
             "expect": {"dates": N2["dates"]}, "ocr": True, "skip": None if s["png"].exists() else "이미지 없음"},
            {"path": B, "fmt": "PDF 삽입형 문서보기", "run": browser("/pdfembed/view"),
             "expect": {**N1}, "skip": None if s.get("pdf_ok") else "Edge 없음"},
        ]
    if not args.no_window:
        dv = work / "desktop"
        att = dv / "attach"
        att.mkdir(parents=True)
        make_hwpx(att / "집행잔액 현황표 서식.hwpx", N1)
        make_hwpx(att / "교육 이수 결과 보고서.hwpx", N4)
        drop = Path(tempfile.gettempdir()) / "seomu_mock_viewer_saves"        # 옛 뷰어가 바로 저장하는 폴더 (감시 대상: 임시 폴더)

        def viewer(mode, n, attach, env=None):
            def run():
                for k, v in (env or {}).items():
                    os.environ[k] = v
                proc, hwnd = desktop.launch(mode, n["title"] + " - 전자문서 뷰어", text_of(n), attach, dv, drop if mode == "legacy" else dv / "save")
                try:
                    return job("capture_window", hwnd, "", False, 20)
                finally:
                    desktop.close(proc)
                    for k in (env or {}):
                        os.environ.pop(k, None)
            return run
        W = "열린 창"
        cases += [
            {"path": W, "fmt": "온나라 전자문서 뷰어형 (본문복사 버튼·붙임은 PC에 받아진 파일에서)", "run": viewer("onnara", N1, [att / "집행잔액 현황표 서식.hwpx"]),
             "expect": {**N1, "att_names": ["집행잔액 현황표 서식.hwpx"]}},
            {"path": W, "fmt": "옛 Win32 뷰어형 (도구모음 메시지로 본문복사)", "run": viewer("legacy", N4, [att / "교육 이수 결과 보고서.hwpx"]),
             "expect": {**N4}},
            {"path": W, "fmt": "그림으로만 그리는 뷰어 (화면 글자 인식)", "run": viewer("canvas", N3, []),
             "expect": {"dates": N3["dates"]}, "ocr": True},
            {"path": W, "fmt": "UI Automation 없는 PC (편집 칸 직접 읽기)", "run": viewer("onnara", N1, [], {"SEOMU_DISABLE_UIA": "1"}),
             "expect": {**N1}},
        ]

    watch = ScreenWatch()
    results = []
    for c in cases:
        label = f"{c['path']} · {c['fmt']}"
        if c.get("skip") or c["run"] is None:
            results.append((c, None, "", ["건너뜀: " + (c.get("skip") or "")], 0.0, []))
            print(f"  ⏭  {label} (건너뜀)")
            continue
        t0 = time.time()
        try:
            (n, err), screen = watch.run(c["run"])
        except Exception as e:  # 검증 도구 자체 오류도 결과에 남긴다
            n, err, screen = None, f"{type(e).__name__}: {e}", []
        probs = judge(c, n, err)
        if c.get("lenient") and n:
            probs = [p for p in probs if not p.startswith("요약")]
            if "본문을 읽지 못했습니다" not in (n.get("body") or ""):
                probs.append("손상 파일 안내 문구 없음")
        if (c.get("preview") or c.get("preview_ext")) and n:
            ext, word = c.get("preview_ext") or (".xlsx", "총무과")
            x = next((f for f in n["attachments"] if f["name"].endswith(ext)), None)
            pv = api.preview_file(x["path"]) if x else {"text": ""}
            if word not in pv.get("text", ""):
                probs.append(f"{ext} 붙임 미리보기 실패")
        probs += [f"화면 가로챔: {e}" for e in screen]
        sec = time.time() - t0
        results.append((c, n, err, probs, sec, screen))
        print(f"  {'✅' if not probs else '❌'} {label} ({sec:.1f}초)" + ("" if not probs else " — " + "; ".join(probs)))

    try:
        api.shutdown()
    finally:
        httpd.shutdown()
        websrv.shutdown()
    write_report(results, Path(args.report))
    passed = sum(1 for r in results if not r[3])
    skipped = sum(1 for r in results if r[3] and r[3][0].startswith("건너뜀"))
    print(f"\n통과 {passed} / 실패 {len(results) - passed - skipped} / 건너뜀 {skipped}  → {args.report}")
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(Path(tempfile.gettempdir()) / "seomu_mock_viewer_saves", ignore_errors=True)
    return 0 if passed + skipped == len(results) else 1


def write_report(results, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for r in results if not r[3])
    grabbed = sum(1 for r in results if r[5])
    lines = ["# 서무비서 AI 종합 검증 결과", "",
             f"- 검증일: {TODAY.isoformat()} · 실행: `python tools/verify_all.py`",
             f"- 결과: **{passed} / {len(results)} 통과** · 화면을 가로챈 경우: **{grabbed}건**",
             "- 예시·모의 환경: `sample_data/verify/`, `sample_data/formats/`, `tools/mock_env/` (웹 공문 시스템 9종, 데스크톱 뷰어 3종)", "",
             "| # | 수집 경로 | 환경·형식 | 결과 | 제목 | 기한 · 할 일 | 요약(첫 줄) | 붙임 |", "|---|---|---|---|---|---|---|---|"]
    cell = lambda x: str(x).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    for i, (c, n, err, probs, sec, screen) in enumerate(results, 1):
        a = (n or {}).get("analysis") or {}
        mark = "✅" if not probs else ("⏭" if probs[0].startswith("건너뜀") else "❌ " + "; ".join(probs))
        if not n and err and not probs:
            title, dl, summ, att = "-", "-", f"오류 안내: {err[:40]}", "-"
        else:
            title = (n or {}).get("title", "-")
            dl = ", ".join(f"{d['date'][5:]} {d['what']}" for d in a.get("deadlines") or []) or "없음"
            summ = (a.get("summary") or "-").splitlines()[0]
            att = ", ".join(f["name"] for f in (n or {}).get("attachments") or [] if f.get("ok")) or "-"
        lines.append(f"| {i} | {c['path']} | {cell(c['fmt'])} | {cell(mark)} | {cell(title)} | {cell(dl)} | {cell(summ)} | {cell(att)} |")
    lines += ["", "판정 기준: 제목·기한 날짜·할 일 문구·제출물(참고 자료 제외)·행사 정보·붙임 파일 이름, 요약에 공문 어미 없음,",
              "본문에 특수 공백·겹친 빈 줄·자모 분리·화면 메뉴 글자 없음, 변환 뷰어는 줄·띄어쓰기 복원,",
              "그리고 수집하는 동안 앞에 있는 창이 바뀌거나 화면 안에 새 창이 나타나지 않을 것 (OCR 항목은 할 일 문구 비교 제외)."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())

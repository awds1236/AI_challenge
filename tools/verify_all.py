"""모든 공문 수집 경로·형식 종합 검증.

예시 공문을 형식별로 만들고(sample_data/verify/), 실제 앱 API로 하나씩 수집해
제목·기한·제출물·요약 품질(공문 어미·빈 괄호·특수 공백·빈 줄)을 자동 판정한 뒤 결과표를 만든다.

    python tools/verify_all.py                 # 전체 (열린 창·브라우저 연동 포함, Windows)
    python tools/verify_all.py --no-window     # 메모장 창 수집 생략
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
SAMPLES = ROOT / "sample_data"
OUT = SAMPLES / "verify"
TODAY = date.today()

# ---------------------------------------------------------------- 예시 공문 (서로 다른 문장 모양)
N1 = {  # 온나라·업무관리시스템형 표준 공문
    "title": "2026회계연도 집행잔액 현황 제출 요청",
    "lines": ["수신 수신자 참조", "(경유)", "제목 2026회계연도 집행잔액 현황 제출 요청",
              "1. 귀 기관의 무궁한 발전을 기원합니다.",
              "2. 2026회계연도 결산에 대비하여 부서별 집행잔액 현황을 아래와 같이 취합하오니 기한 내 제출하여 주시기 바랍니다.",
              "가. 제출 기한: 2026. 12. 4.(금) 17:00까지",
              "나. 제출 서류: 집행잔액 현황표(붙임 1 서식) 1부",
              "다. 제출 방법: 업무관리시스템 공문으로 제출",
              "3. 문의처: 재무과 결산팀 박○○ 주무관(☎ 031-000-4100)",
              "붙임 1. 집행잔액 현황표 서식 1부.", "2. 결산 일정 안내문 1부. 끝."],
    "dates": ["2026-12-04"], "subs": ["집행잔액 현황표"], "no_subs": ["결산 일정 안내문"], "whats": ["집행잔액 현황표 제출"],
}
N2 = {  # 행사·교육 안내형
    "title": "2026년 하반기 직원 역량강화 교육 참석 안내",
    "lines": ["제목 2026년 하반기 직원 역량강화 교육 참석 안내",
              "1. 직원 역량강화를 위하여 하반기 교육을 다음과 같이 실시하오니 해당 직원이 참석할 수 있도록 협조하여 주시기 바랍니다.",
              "가. 교육명: 공공 데이터 활용 실무 과정",
              "나. 일시: 2026. 11. 26.(목) 14:00 ~ 17:00",
              "다. 장소: 본관 3층 대회의실",
              "라. 대상: 부서별 서무 담당자 1명",
              "마. 신청 기한: 2026. 11. 20.(금)까지",
              "바. 제출 서류: 참석자 명단 1부",
              "붙임 교육 세부 일정 1부. 끝."],
    "dates": ["2026-11-20"], "subs": ["참석자 명단"], "event": "2026. 11. 26.", "whats": ["참석자 명단 제출"],
}
N3 = {  # 짧은 날짜 표기·번호 없는 협조 메모형 (붙임 없음)
    "title": "부서별 비상연락망 정비 협조",
    "lines": ["제목: 부서별 비상연락망 정비 협조",
              "연말 재난 대비 훈련을 위해 부서별 비상연락망을 새로 정비하고자 합니다.",
              "각 부서에서는 변경된 연락처를 반영하여 '26. 11. 25.까지 총무팀으로 회신하여 주시기 바랍니다.",
              "- 회신 자료: 비상연락망 1부",
              "- 문의: 총무팀 이○○ (내선 2201)"],
    "dates": ["2026-11-25"], "subs": ["비상연락망"], "whats": ["비상연락망 회신"],
}
N4 = {  # 기한이 두 개인 공문
    "title": "청렴 교육 이수 및 결과 보고 요청",
    "lines": ["제목 청렴 교육 이수 및 결과 보고 요청",
              "1. 청렴 교육 이수를 아래와 같이 요청하오니 협조하여 주시기 바랍니다.",
              "가. 이수 기한: 2026. 11. 28.(토)까지",
              "나. 결과 보고 기한: 2026. 12. 2.(수)까지",
              "다. 보고 자료: 교육 이수 결과 보고서 1부", "끝."],
    "dates": ["2026-11-28", "2026-12-02"], "subs": ["교육 이수 결과 보고서"], "whats": ["청렴 교육 이수", "교육 이수 결과 보고서 제출"],
}
N5 = {  # 기한 없는 단순 안내
    "title": "청사 주차장 도색 공사 안내",
    "lines": ["제목 청사 주차장 도색 공사 안내",
              "1. 청사 주차장 바닥 도색 공사를 실시하오니 업무에 참고하시기 바랍니다.",
              "가. 공사 기간: 2026. 11. 14.(토) ~ 11. 15.(일)",
              "나. 공사 장소: 본관 지하 주차장", "끝."],
    "dates": [], "subs": [],
}


def text_of(n: dict) -> str:
    return "\n".join(n["lines"])


def html_of(n: dict, board: bool = False, links: list[tuple[str, str]] | None = None) -> str:
    body = "".join(f"<p>{l}</p>" for l in n["lines"])
    files = "".join(f'<a href="{h}">{t}</a> ' for t, h in (links or []))
    if not board:
        return f'<html><head><meta charset="utf-8"><title>{n["title"]}</title></head><body style="font-family:Malgun Gothic">{body}{files}</body></html>'
    return ('<html><head><meta charset="utf-8"><title>공지사항 상세보기 | ○○시청</title></head><body>'
            '<div id="header"><a href="/login">로그인</a><a href="/sitemap">사이트맵</a><ul id="gnb"><li><a>열린시정</a></li><li><a>알림마당</a></li></ul></div>'
            '<div id="lnb"><a>공지사항</a><a>고시공고</a></div><div id="contents"><div class="location">홈 &gt; 알림마당 &gt; 공지사항</div>'
            f'<div class="board_view"><h3>{n["title"]}</h3><div class="file_area">첨부파일 {files}</div>'
            f'<div class="view_cont">{body}</div></div><a href="/list">목록</a></div>'
            '<div id="footer">개인정보처리방침 Copyright © City</div></body></html>')


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


def make_xlsx(path: Path) -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "현황표"
    ws.append(["부서", "예산액", "집행액", "잔액"])
    ws.append(["총무과", 1000000, 800000, 200000])
    wb.save(path)


def _ps(script: str, *args: str) -> None:
    f = Path(tempfile.gettempdir()) / "seomu_verify.ps1"
    f.write_text(script, encoding="utf-8-sig")            # PowerShell 5.1은 BOM이 있어야 한글을 UTF-8로 읽는다
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(f), *args],
                   capture_output=True, timeout=120)


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
                    f"--print-to-pdf={pdf}", html.as_uri()], capture_output=True, timeout=120)
    shutil.rmtree(prof, ignore_errors=True)
    return pdf.exists() and pdf.stat().st_size > 500


def build_samples() -> dict:
    """sample_data/verify/ 에 형식별 예시를 만든다. {이름: 경로}"""
    OUT.mkdir(parents=True, exist_ok=True)
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
    bad = OUT / "10_손상된_파일.hwpx"
    bad.write_bytes(b"PK\x03\x04 broken")
    s["bad"] = bad
    s["notepad_txt"] = OUT / "11_메모장_공문.txt"
    s["notepad_txt"].write_text(text_of(N3), encoding="utf-8")
    return s


# ---------------------------------------------------------------- 판정
BAD_SUMMARY = ("하오니", "바랍니다", "귀 기관", "무궁한", "다음과 같이", "아래와 같이", "하고자", "바랍l", "주시기",
               "에서는", "요청 — 협조 요청", "대비하여", "참고 요청", "'26.", "본문을 읽지 못했습니다")


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
            probs.append(f"요약에 공문 어미 '{w}'")
    whats = [d["what"] for d in a.get("deadlines") or []]
    if "whats" in exp and whats != exp["whats"]:
        probs.append(f"할 일 문구 {whats} (기대 {exp['whats']})")
    for d in a.get("deadlines") or []:
        if re.search(r"\(\s*\)|\(서식\)|에서는|기한$", d["what"]):
            probs.append(f"할 일 문구에 빈 괄호: {d['what']}")
    if re.search(r"[\u200b\u00a0\u3000]", body):
        probs.append("본문에 특수 공백이 남음")
    if "\n\n\n" in body:
        probs.append("본문에 빈 줄이 겹침")
    if body != unicodedata.normalize("NFC", body):
        probs.append("본문 한글 자모 분리")
    for menu in ("로그인", "사이트맵", "개인정보처리방침", "열린시정"):
        if menu in body:
            probs.append(f"본문에 웹 메뉴 글자 '{menu}'")
    ok_att = sum(1 for f in n.get("attachments") or [] if f.get("ok"))
    if ok_att < exp.get("att_ok", 0):
        probs.append(f"붙임 {ok_att}개 받음 (기대 {exp['att_ok']}개 이상)")
    return probs


# ---------------------------------------------------------------- 실행
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(folder: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(folder)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


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
    from seomu.api import Api
    api = Api(work / "home")
    api.save_settings({"ollama_url": "http://127.0.0.1:9", "browser_headless": True})

    # 주소·브라우저 연동용 로컬 웹 서버 (홈페이지 게시판 + iframe 공문 뷰어)
    site = work / "site"
    (site / "files").mkdir(parents=True)
    shutil.copy2(s["hwpx"], site / "files" / "현황표 서식.hwpx")
    shutil.copy2(s["xlsx"], site / "files" / "집행잔액_현황표.xlsx")
    links = [("현황표 서식.hwpx", "files/%ED%98%84%ED%99%A9%ED%91%9C%20%EC%84%9C%EC%8B%9D.hwpx"),
             ("집행잔액_현황표.xlsx", "files/download.do?f=x")]
    (site / "board.html").write_text(html_of(N1, board=True, links=links[:1]), encoding="utf-8")
    (site / "viewer.html").write_text('<html><head><meta charset="utf-8"><title>문서보기 - 온나라</title></head><body>'
                                      '<div id="toolbar"><button>본문복사</button><button>인쇄</button></div>'
                                      '<iframe src="doc.html" style="width:100%;height:600px"></iframe></body></html>', encoding="utf-8")
    (site / "doc.html").write_text(html_of(N2), encoding="utf-8")
    httpd, base = serve(site)

    def job(name, *a):
        j = getattr(api, name)(*a)
        for _ in range(1200):
            st = api.job_status(j["job_id"])
            if st["status"] != "running":
                return (st["result"], "") if st["status"] == "done" else (None, st["error"])
            time.sleep(0.1)
        return None, "시간 초과"

    def files(*paths):
        return lambda: job("collect_files", [str(p) for p in paths], "", 0, False)

    web_copy = unicodedata.normalize("NFD", text_of(N1)).replace(" ", "\u00a0", 3).replace("\n", "\n\n") + "\u200b"
    cases = [
        {"path": "파일", "fmt": "HWPX (한글, 온나라)", "run": files(s["hwpx"]), "expect": {**N1, "title": N1["title"]}},
        {"path": "파일", "fmt": "DOCX (워드)", "run": files(s["docx"]), "expect": {**N2, "title": N2["title"]}},
        {"path": "파일", "fmt": "ODT (오픈오피스)", "run": files(s["odt"]), "expect": {**N3, "title": N3["title"]}},
        {"path": "파일", "fmt": "RTF", "run": files(s["rtf"]), "expect": {**N2, "title": N2["title"]}},
        {"path": "파일", "fmt": "PDF (문서24 출력)", "run": files(s["pdf"]), "expect": {**N1, "title": N1["title"]},
         "skip": None if s.get("pdf_ok") else "Edge 없음"},
        {"path": "파일", "fmt": "PNG (사진 공문, OCR)", "run": files(s["png"]), "expect": {"dates": N2["dates"], "subs": N2["subs"]},
         "skip": None if s["png"].exists() else "이미지 생성 불가"},
        {"path": "파일", "fmt": "스캔 PDF (OCR)", "run": files(s["scan_pdf"]) if s.get("scan_ok") else None,
         "expect": {"dates": N2["dates"]}, "skip": None if s.get("scan_ok") else "Edge 없음"},
        {"path": "파일", "fmt": "MHT (에듀파인 웹 저장)", "run": files(SAMPLES / "formats" / "에듀파인_웹공문.mht"),
         "expect": {"title": "학교폭력 예방교육", "dates": ["2026-12-04"]}},
        {"path": "파일", "fmt": "EML (메일) + ZIP 붙임", "run": files(SAMPLES / "formats" / "메일_공문.eml"),
         "expect": {"dates": ["2026-11-19"], "att_ok": 4}},
        {"path": "파일", "fmt": "HTML (홈페이지 게시판 저장)", "run": files(SAMPLES / "formats" / "홈페이지_게시판_공지.html"),
         "expect": {"title": "정책제안 공모전", "dates": ["2026-11-30"]}},
        {"path": "파일", "fmt": "TXT (기업 전자결재 협조전)", "run": files(SAMPLES / "formats" / "회사_전자결재_협조문.txt"),
         "expect": {"dates": ["2026-11-19"]}},
        {"path": "파일", "fmt": "TXT (기한 두 개)", "run": files(s["txt_two"]), "expect": N4},
        {"path": "파일", "fmt": "TXT (기한 없는 안내, CP949)", "run": files(s["txt_none"]), "expect": {**N5, "title": N5["title"]}},
        {"path": "파일", "fmt": "본문 + 붙임 여러 개 (XLSX 미리보기)", "run": files(s["hwpx"], s["xlsx"], s["docx"]),
         "expect": {"dates": N1["dates"], "att_ok": 2}, "preview": True},
        {"path": "파일", "fmt": "손상된 파일", "run": files(s["bad"]), "expect": {"dates": [], "title": "손상된 파일"}, "lenient": True},
        {"path": "붙여넣기", "fmt": "웹에서 복사한 글자 (자모 분리·특수 공백·빈 줄)",
         "run": lambda: job("collect_text", web_copy, "", False, ""), "expect": {**N1, "title": N1["title"]}},
        {"path": "붙여넣기", "fmt": "웹 HTML 서식 함께 복사",
         "run": lambda: job("collect_text", "열린시정알림마당\n" + text_of(N2), "", False, html_of(N2, board=True)),
         "expect": {**N2, "title": N2["title"]}},
        {"path": "붙여넣기", "fmt": "빈 내용", "run": lambda: _expect_error(api.collect_text, "  ", "", False),
         "expect": {"error": "붙여 넣은 본문이 없습니다"}},
        {"path": "주소", "fmt": "홈페이지 게시판 + 붙임 내려받기", "run": lambda: job("collect_url", base + "/board.html", "", False),
         "expect": {**N1, "title": N1["title"], "att_ok": 1}},
        {"path": "주소", "fmt": "잘못된 주소", "run": lambda: _expect_error(api.collect_url, "ftp://x", "", False),
         "expect": {"error": "http:// 또는 https://"}},
    ]
    if not args.no_browser:
        def browser():
            api.browser_open(base + "/viewer.html")
            time.sleep(1.5)
            return job("capture_browser", None, "", False)
        cases.append({"path": "브라우저 연동", "fmt": "공문 뷰어 (iframe 안 본문)", "run": browser,
                      "expect": {**N2, "title": N2["title"]}})
    if not args.no_window:
        cases.append({"path": "열린 창", "fmt": "메모장에 띄운 공문", "run": lambda: notepad_case(api, job, s["notepad_txt"]),
                      "expect": {**N3}})

    results = []
    for c in cases:
        label = f"{c['path']} · {c['fmt']}"
        if c.get("skip") or c["run"] is None:
            results.append((c, None, "", ["건너뜀: " + (c.get("skip") or "")], 0.0))
            print(f"  ⏭  {label} (건너뜀)")
            continue
        t0 = time.time()
        try:
            n, err = c["run"]()
        except Exception as e:  # 검증 도구 자체 오류도 결과에 남긴다
            n, err = None, f"{type(e).__name__}: {e}"
        probs = judge(c, n, err)
        if c.get("lenient") and n:
            probs = [p for p in probs if not p.startswith("요약")]
            if "본문을 읽지 못했습니다" not in (n.get("body") or ""):
                probs.append("손상 파일 안내 문구 없음")
        if c.get("preview") and n:
            x = next((f for f in n["attachments"] if f["name"].endswith(".xlsx")), None)
            pv = api.preview_file(x["path"]) if x else {"text": ""}
            if "총무과" not in pv.get("text", ""):
                probs.append("XLSX 붙임 미리보기 실패")
        results.append((c, n, err, probs, time.time() - t0))
        print(f"  {'✅' if not probs else '❌'} {label} ({time.time() - t0:.1f}초)" + ("" if not probs else " — " + "; ".join(probs)))

    try:
        api.shutdown()
    finally:
        httpd.shutdown()
    write_report(results, Path(args.report))
    passed = sum(1 for r in results if not r[3])
    skipped = sum(1 for r in results if r[3] and r[3][0].startswith("건너뜀"))
    print(f"\n통과 {passed} / 실패 {len(results) - passed - skipped} / 건너뜀 {skipped}  → {args.report}")
    shutil.rmtree(work, ignore_errors=True)
    return 0 if passed + skipped == len(results) else 1


def _expect_error(fn, *a):
    try:
        fn(*a)
    except Exception as e:
        return None, str(e)
    return None, ""


def notepad_case(api, job, path: Path):
    """메모장에 공문을 띄우고 '열린 창에서 수집'으로 읽는다. 끝나면 그 창만 닫고 클립보드를 되돌린다."""
    import ctypes
    from seomu import winwindow
    if not winwindow.available():
        raise RuntimeError("Windows 전용")
    clip = winwindow.get_clipboard()
    subprocess.Popen(["notepad.exe", str(path)])
    win = None
    for _ in range(40):
        time.sleep(0.5)
        win = next((w for w in winwindow.list_windows() if path.stem in w["title"]), None)
        if win:
            break
    if not win:
        raise RuntimeError("메모장 창을 찾지 못함")
    try:
        return job("capture_window", win["hwnd"], "", False, 20)
    finally:
        ctypes.windll.user32.PostMessageW(win["hwnd"], 0x0010, 0, 0)    # WM_CLOSE (이 창만)
        if clip:
            winwindow.set_clipboard(clip)


def write_report(results, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for r in results if not r[3])
    lines = [f"# 서무비서 AI 종합 검증 결과", "",
             f"- 검증일: {TODAY.isoformat()} · 실행: `python tools/verify_all.py`",
             f"- 결과: **{passed} / {len(results)} 통과** (예시 파일: `sample_data/verify/`, `sample_data/formats/`)", "",
             "| # | 수집 경로 | 형식·상황 | 결과 | 제목 | 기한 | 요약(첫 줄) |", "|---|---|---|---|---|---|---|"]
    for i, (c, n, err, probs, sec) in enumerate(results, 1):
        a = (n or {}).get("analysis") or {}
        mark = "✅" if not probs else ("⏭" if probs[0].startswith("건너뜀") else "❌ " + "; ".join(probs))
        if not n and err and not probs:
            mark, title, dl, summ = "✅", "-", "-", f"오류 안내: {err[:40]}"
        else:
            title = (n or {}).get("title", "-")
            dl = ", ".join(f"{d['date'][5:]} {d['what']}" for d in a.get("deadlines") or []) or "없음"
            summ = (a.get("summary") or "-").splitlines()[0]
        cell = lambda x: str(x).replace("|", "\\|")  # noqa: E731
        lines.append(f"| {i} | {c['path']} | {cell(c['fmt'])} | {cell(mark)} | {cell(title)} | {cell(dl)} | {cell(summ)} |")
    lines += ["", "판정 기준: 제목·기한 날짜·제출물(참고 자료 제외)·행사 정보, 요약에 공문 어미(하오니·바랍니다 등) 없음,",
              "할 일 문구에 빈 괄호 없음, 본문에 특수 공백·겹친 빈 줄·자모 분리·웹 메뉴 글자 없음, 붙임 내려받기 개수."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())

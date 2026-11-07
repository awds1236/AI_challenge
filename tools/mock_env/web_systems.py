"""웹 기반 공문 시스템 모의 서버 (127.0.0.1 전용, 검증용).

실제 시스템에서 볼 수 있는 화면 구조와 붙임 내려받기 방식을 흉내 낸다.
  /onnara/view     온나라 2.0형: 도구모음 + 편집기(iframe, contenteditable) 본문 + 스크립트형 붙임 링크,
                   붙임 파일 이름을 옛 서버처럼 CP949 원시 바이트로 보냄
  /doc24/view      문서24형: 머리 표(수신·제목) + filename*=UTF-8 붙임
  /edufine/view    K-에듀파인형: iframe 3단 중첩 + POST 양식으로 붙임 받기
  /groupware/view  그룹웨어 전자결재형: 내용이 나중에 그려지는 화면(SPA) + 결재선 표 + 로그인 쿠키가 있어야 받히는 붙임
  /synap/view      사이냅식 변환 뷰어: 글자 조각을 화면 위치로 배치, 띄어쓰기 문자 없음, 소스상 줄 순서 뒤섞임
  /pdfjs/view      PDF.js식 뷰어: 캔버스 + 투명 글자 층(낱말마다 위치 지정)
  /image/view      이미지 뷰어: 페이지가 그림뿐
  /pdfembed/view   PDF 삽입형: 화면 안에 PDF를 삽입
  /euckr/notice    옛 EUC-KR 인코딩 페이지
files_dir 안의 파일(붙임·page1.png·doc.pdf)을 내보낸다.
"""
from __future__ import annotations

import html
import json
import random
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .notices import N1, N2, N3, N6, N7

ATTACH = {   # 붙임 id → (보여 줄 이름, files_dir 안의 파일)
    "a1": ("집행잔액 현황표 서식.hwpx", "onnara_form.hwpx"),
    "a2": ("결산 일정 안내문.pdf", "onnara_guide.pdf"),
    "d1": ("참석자 명단 서식.xlsx", "doc24_list.xlsx"),
    "e1": ("안전교육 실적 보고서 서식.hwp", "edu_form.hwp"),      # 학교 공문 붙임은 한글 5.0 파일이 흔하다
    "g1": ("부서별 추진과제 작성표.xlsx", "gw_form.xlsx"),
}


def _p(lines: list[str]) -> str:
    return "".join(f"<p>{html.escape(l)}</p>" for l in lines)


def _layout_page(lines: list[str], kind: str) -> str:
    """변환 뷰어: 줄마다 화면 위치를 정하고 낱말을 띄어쓰기 문자 없이 따로 배치한다 (소스 순서는 섞는다)."""
    items, y = [], 40
    for line in lines:
        x = 50
        for word in line.split(" "):
            w = len(word) * 15 + 4
            items.append(f'<span style="position:absolute;left:{x}px;top:{y}px;font-size:15px;white-space:pre">'
                         f'{html.escape(word)}</span>')
            x += w + 9                          # 낱말 사이 간격은 위치로만 표현 (띄어쓰기 문자 없음)
        y += 26
    random.Random(7).shuffle(items)            # 소스상 순서는 읽는 순서와 다르다
    layer = "".join(items)
    if kind == "pdfjs":
        return ('<html><head><meta charset="utf-8"><title>PDF.js viewer</title></head><body style="margin:0">'
                '<div id="viewer"><div class="page" style="position:relative;width:1100px;height:420px">'
                '<canvas width="1100" height="420"></canvas>'
                f'<div class="textLayer" style="position:absolute;inset:0;color:transparent">{layer}</div></div></div></body></html>')
    return ('<html><head><meta charset="utf-8"><title>문서 변환 뷰어</title></head><body style="margin:0;font-family:Malgun Gothic">'
            f'<div id="docViewer" style="position:relative;width:1100px;height:420px">{layer}</div></body></html>')


class Handler(BaseHTTPRequestHandler):
    files_dir: Path = Path(".")

    def log_message(self, *a):
        pass

    def _send(self, body: bytes | str, ctype="text/html; charset=utf-8", code=200, headers=None):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _file(self, fid: str, raw_cp949: bool = False):
        name, fn = ATTACH[fid]
        data = (self.files_dir / fn).read_bytes()
        if raw_cp949:     # 옛 서버: 파일 이름을 인코딩 표시 없이 CP949 바이트 그대로
            cd = 'attachment; filename="' + name.encode("cp949").decode("latin-1") + '"'
        else:
            cd = "attachment; filename*=UTF-8''" + urllib.parse.quote(name)
        self._send(data, "application/octet-stream", headers={"Content-Disposition": cd})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(n).decode())
        if self.path.startswith("/edufine/dl"):
            return self._file(form.get("fileId", ["e1"])[0])
        self._send("not found", code=404)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        p = u.path
        # ---- 온나라 2.0형
        if p == "/onnara/view":
            links = "".join(f'<li><a href="javascript:fnFileDown(\'{k}\')">{html.escape(ATTACH[k][0])}</a></li>' for k in ("a1", "a2"))
            return self._send(
                '<html><head><meta charset="utf-8"><title>문서보기 - 온나라</title>'
                '<script>function fnFileDown(id){location.href="/onnara/dn?id="+id;}</script></head><body>'
                '<div id="toolbar"><button>본문복사</button><button>PC저장</button><button>인쇄</button><button>닫기</button></div>'
                '<table class="approval"><tr><th>기안</th><th>검토</th><th>결재</th></tr><tr><td>주무관 박○○</td><td>팀장 김○○</td><td>과장 이○○</td></tr></table>'
                '<iframe id="docFrame" src="/onnara/body" style="width:100%;height:520px;border:0"></iframe>'
                f'<div class="attach"><b>붙임파일</b><ul>{links}</ul></div></body></html>')
        if p == "/onnara/body":
            return self._send('<html><head><meta charset="utf-8"></head><body contenteditable="true" class="pe_editor">'
                              f'<div class="hwp_body">{_p(N1["lines"])}</div></body></html>')
        if p == "/onnara/dn":
            return self._file(q.get("id", ["a1"])[0], raw_cp949=True)
        # ---- 문서24형
        if p == "/doc24/view":
            rows = "".join(f"<p>{html.escape(l)}</p>" for l in N2["lines"][1:])
            return self._send(
                '<html><head><meta charset="utf-8"><title>문서24 - 받은문서 상세</title></head><body>'
                '<div class="gnb"><a>보낸문서</a><a>받은문서</a><a>로그아웃</a></div>'
                f'<table class="doc_head"><tr><th>수신</th><td>각 부서장</td></tr><tr><th>제목</th><td>{html.escape(N2["title"])}</td></tr></table>'
                f'<div class="doc_cont">{rows}</div>'
                f'<div class="file_list"><a href="/doc24/download?fileId=d1">{html.escape(ATTACH["d1"][0])}</a></div></body></html>')
        if p == "/doc24/download":
            return self._file("d1")
        # ---- K-에듀파인형 (iframe 3단)
        if p == "/edufine/view":
            return self._send('<html><head><meta charset="utf-8"><title>K-에듀파인 업무관리</title></head><body>'
                              '<div id="topMenu">업무관리 문서관리 일정</div><iframe src="/edufine/f1" style="width:100%;height:700px"></iframe></body></html>')
        if p == "/edufine/f1":
            return self._send('<html><head><meta charset="utf-8"></head><body><iframe src="/edufine/f2" style="width:100%;height:650px"></iframe></body></html>')
        if p == "/edufine/f2":
            return self._send(
                '<html><head><meta charset="utf-8"></head><body>'
                '<form name="dlform" method="post" action="/edufine/dl"><input type="hidden" name="fileId" value="e1"></form>'
                '<iframe src="/edufine/doc" style="width:100%;height:500px"></iframe>'
                f'<div class="fileArea"><button type="button" onclick="document.dlform.submit()">{html.escape(ATTACH["e1"][0])}</button></div></body></html>')
        if p == "/edufine/doc":
            return self._send(f'<html><head><meta charset="utf-8"></head><body>{_p(N6["lines"])}</body></html>')
        # ---- 그룹웨어 전자결재형 (SPA)
        if p == "/groupware/view":
            return self._send(
                '<html><head><meta charset="utf-8"><title>전자결재 - 그룹웨어</title></head><body>'
                '<div id="lnb">결재대기 결재진행 완료문서</div><div id="app">불러오는 중…</div><script>'
                'document.cookie="gw_session=ok; path=/";'
                'setTimeout(function(){fetch("/groupware/api/doc").then(r=>r.json()).then(function(d){'
                'var h="<table class=sign><tr><th>기안</th><th>합의</th><th>승인</th></tr><tr><td>"+d.sign.join("</td><td>")+"</td></tr></table>";'
                'h+="<h2>"+d.title+"</h2>"+d.body.map(function(l){return "<p>"+l+"</p>"}).join("");'
                'h+="<div class=files><a href=\\"/groupware/file/g1\\" download>"+d.file+"</a></div>";'
                'document.getElementById("app").innerHTML=h;});},1200);</script></body></html>')
        if p == "/groupware/api/doc":
            return self._send(json.dumps({"title": N7["title"], "body": N7["lines"][1:], "file": ATTACH["g1"][0],
                                          "sign": ["대리 최○○ 11/05", "차장 정○○ 11/05", "부장 한○○ 11/06"]}, ensure_ascii=False),
                              "application/json; charset=utf-8")
        if p.startswith("/groupware/file/"):
            if "gw_session=ok" not in (self.headers.get("Cookie") or ""):
                return self._send("로그인이 필요합니다", code=403)
            return self._file("g1")
        # ---- 변환 뷰어들
        if p == "/synap/view":
            return self._send(_layout_page(N3["lines"], "synap"))
        if p == "/pdfjs/view":
            return self._send(_layout_page(N1["lines"], "pdfjs"))
        if p == "/image/view":
            return self._send('<html><head><meta charset="utf-8"><title>문서 이미지 뷰어</title></head><body>'
                              '<div class="pageView"><img src="/files/page1.png" style="width:1200px"></div></body></html>')
        if p == "/pdfembed/view":
            return self._send('<html><head><meta charset="utf-8"><title>PDF 문서보기</title></head><body>'
                              '<div class="viewerTop">문서보기 · 인쇄 · 저장</div>'
                              '<iframe src="/files/doc.pdf" style="width:100%;height:600px"></iframe></body></html>')
        if p == "/euckr/notice":
            page = ('<html><head><meta http-equiv="Content-Type" content="text/html; charset=euc-kr"><title>공지</title></head>'
                    f'<body><div class="view_cont">{_p(N1["lines"])}</div></body></html>')
            return self._send(page.encode("cp949"), "text/html; charset=euc-kr")
        if p.startswith("/files/"):
            f = self.files_dir / urllib.parse.unquote(p[len("/files/"):])
            if f.is_file():
                ctype = {".pdf": "application/pdf", ".png": "image/png"}.get(f.suffix.lower(), "application/octet-stream")
                return self._send(f.read_bytes(), ctype)
        self._send("not found", code=404)


def start(files_dir: Path) -> tuple[ThreadingHTTPServer, str]:
    handler = type("H", (Handler,), {"files_dir": Path(files_dir)})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"

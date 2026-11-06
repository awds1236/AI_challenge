"""웹뷰를 쓸 수 없는 환경을 위한 로컬 전용 HTTP 브리지.

- 127.0.0.1 에만 바인딩하여 다른 PC에서 접근할 수 없다.
- 실행마다 무작위 토큰을 발급해, 같은 PC의 다른 웹페이지가 API를 호출하지 못하게 한다.
"""
from __future__ import annotations

import inspect
import json
import logging
import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UI_DIR = Path(__file__).parent / "ui"


def make_handler(api, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SeomuAI"

        def log_message(self, fmt, *args):  # 조용히
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                html = (UI_DIR / "index.html").read_text(encoding="utf-8")
                html = html.replace("<!--SEOMU_BOOT-->",
                                    f'<script>window.SEOMU_TOKEN="{token}";</script>')
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            target = (UI_DIR / path.lstrip("/")).resolve()
            if UI_DIR.resolve() in target.parents and target.is_file():
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype.endswith("javascript"):
                    ctype += "; charset=utf-8"
                return self._send(200, target.read_bytes(), ctype)
            self._send(404, b'{"error":"not found"}')

        def do_POST(self):
            if self.headers.get("X-Seomu-Token") != token:
                return self._send(403, b'{"error":"forbidden"}')
            if not self.path.startswith("/api/"):
                return self._send(404, b'{"error":"not found"}')
            name = self.path[5:].split("?", 1)[0]
            fn = getattr(api, name, None)
            if name.startswith("_") or not callable(fn) or not inspect.ismethod(fn):
                return self._send(404, json.dumps({"error": f"unknown method {name}"}).encode())
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
                result = fn(*payload.get("args", []))
                body = json.dumps({"ok": True, "result": result}, ensure_ascii=False, default=str)
                self._send(200, body.encode("utf-8"))
            except Exception as e:  # API 오류를 화면에 전달
                logging.getLogger("seomu.api").warning("API %s 오류", name, exc_info=True)
                body = json.dumps({"ok": False, "error": str(e) or e.__class__.__name__}, ensure_ascii=False)
                self._send(200, body.encode("utf-8"))

    return Handler


class _Server(ThreadingHTTPServer):
    # Windows는 대기 중인 연결이 큐(기본 5개)를 넘으면 바로 거절한다 → 화면이 여러 요청을 동시에 보내면
    # 일부가 'Failed to fetch'로 실패했다. 큐를 넉넉히 둔다.
    request_queue_size = 128
    daemon_threads = True

    def handle_error(self, request, client_address):
        # pythonw로 실행하면 콘솔(stderr)이 없어 기본 처리기가 다시 오류를 낸다 → 로그로만 남긴다
        logging.getLogger("seomu.server").warning("요청 처리 중 연결 오류", exc_info=True)


def start_server(api, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    token = secrets.token_urlsafe(24)
    httpd = _Server(("127.0.0.1", port), make_handler(api, token))
    threading.Thread(target=httpd.serve_forever, daemon=True, name="seomu-http").start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"

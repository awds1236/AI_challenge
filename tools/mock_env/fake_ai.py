"""검증용 가짜 AI 엔진 (Ollama 방식 API, 127.0.0.1 전용).

실제 모델(수 GB)을 받지 않고도 앱의 AI 경로 — 규정 질문 답변(스트리밍), 공문 AI 보완 분석(JSON),
보고서 AI 작성(JSON), 메일 다듬기, 의미 검색 임베딩 — 를 끝까지 실행해 보기 위한 서버.
응답 내용은 받은 요청(근거·힌트·초안)에서 만든다.

    python tools/mock_env/fake_ai.py --port 11999
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = ["gemma4:e2b-it-qat", "embeddinggemma"]


def _vec(text: str, n: int = 16) -> list[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    return [b / 255.0 for b in h[:n]]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            return self._json({"models": [{"name": m} for m in MODELS]})
        self._json({"status": "ok"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/generate":
            return self._json({"done": True})
        if self.path == "/api/embed":
            return self._json({"embeddings": [_vec(t) for t in body.get("input", [])]})
        if self.path == "/api/embeddings":
            return self._json({"embedding": _vec(body.get("prompt", ""))})
        if self.path != "/api/chat":
            return self._json({})
        msgs = body.get("messages") or []
        user = msgs[-1]["content"] if msgs else ""
        time.sleep(0.2)
        fmt = body.get("format")
        if isinstance(fmt, dict):
            props = fmt.get("properties", {})
            if "sections" in props:                                        # 보고서 개요
                title = re.search(r"제목[^:：]*[:：]\s*(.+)", user)
                return self._reply({"title": (title.group(1).strip() if title else "공문 관련 보고")[:60],
                                    "summary": "공문 요청 사항을 검토하여 기한 내 조치하고자 함",
                                    "sections": [{"heading": "추진 배경", "items": [{"head": "근거", "text": "관련 공문 접수"}]},
                                                 {"heading": "조치 계획", "items": [{"text": "부서별 자료 취합 후 기한 내 제출"}]}]})
            # 공문 분석: 규칙이 찾은 기한 후보를 받아 정리한 것처럼 답한다
            dls = [{"date": d, "time": "", "what": w.strip()[:30]}
                   for d, w in re.findall(r"기한 후보:\s*(\d{4}-\d{2}-\d{2})\s+(.+)", user)]
            title = re.search(r"^제목\s*[:：]?\s*(.+)$", user, re.M)
            return self._reply({"folder_name": (title.group(1).strip() if title else "공문")[:25],
                                "summary": "AI 요약: 요청 사항을 확인하고 기한 내 제출해야 합니다.",
                                "deadlines": dls, "submissions": [{"item": "회신 자료", "how": "공문", "to": ""}],
                                "actions": [f"{d['what']} ({d['date'][5:]}까지)" for d in dls][:3] or ["공문 내용 확인"]})
        if body.get("stream"):                                             # 규정 질문 답변
            cite = re.search(r"\[1\][^\n]*\n([^\n]{0,80})", user)
            text = f"근거에 따르면 {cite.group(1).strip() if cite else '관련 조문을 확인해야 합니다'} [1]"
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for i in range(0, len(text), 6):
                self.wfile.write((json.dumps({"message": {"content": text[i:i + 6]}, "done": False}, ensure_ascii=False) + "\n").encode())
                self.wfile.flush()
                time.sleep(0.02)
            self.wfile.write((json.dumps({"message": {"content": ""}, "done": True}) + "\n").encode())
            return
        draft = user.split("[초안]", 1)[-1].strip() or user            # 메일 다듬기
        return self._json({"message": {"content": draft.replace("부탁드립니다", "부탁드리겠습니다")}, "done": True})

    def _reply(self, obj):
        return self._json({"message": {"content": json.dumps(obj, ensure_ascii=False)}, "done": True})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=11999)
    a = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()

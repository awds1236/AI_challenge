#!/usr/bin/env python3
"""테스트용 가짜 llama-server: -m 모델 --port 포트 [--embedding]"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

args = sys.argv[1:]
port = int(args[args.index("--port") + 1])
model = args[args.index("-m") + 1]
embedding = "--embedding" in args


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._json({"status": "ok"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/v1/embeddings":
            return self._json({"data": [{"index": i, "embedding": [float(len(t)), 1.0]} for i, t in enumerate(body["input"])]})
        if body.get("response_format"):
            content = json.dumps({"folder_name": "테스트", "summary": "내장 엔진 요약", "deadlines": [],
                                  "submissions": [], "actions": []}, ensure_ascii=False)
            return self._json({"choices": [{"message": {"content": content}}]})
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for tok in ["내장 ", "엔진 ", "답변"]:
                self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": tok}}]}, ensure_ascii=False) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        self._json({"choices": [{"message": {"content": "모델:" + model.split("/")[-1]}}]})


HTTPServer(("127.0.0.1", port), H).serve_forever()

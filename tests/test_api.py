"""API 통합 테스트 (가짜 로컬 Ollama 서버 사용)."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._json({"models": [{"name": "gemma3:4b"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body.get("format"):
            self._json({"message": {"content": json.dumps({
                "folder_name": "청렴 교육 행사 참여 요청", "summary": "청렴 교육 참여 인원 회신 요청",
                "event": {"name": "청렴 교육", "date": "2026-11-20 14:00", "place": "대회의실"},
                "deadlines": [{"date": "2026-11-13", "time": "18:00", "what": "참가 신청서 회신"}],
                "submissions": [{"item": "참가 신청서", "how": "전자우편", "to": "청렴팀"}],
                "actions": ["부서 참석자 2명 선정", "신청서 작성 후 메일 회신"], "contact": "청렴팀"},
                ensure_ascii=False)}})
            return
        if body.get("stream"):
            self.send_response(200)
            self.end_headers()
            prompt = body["messages"][-1]["content"]
            toks = ["다듬은 ", "메일"] if "[초안]" in prompt else ["연가는 ", "사용 3일 전까지 ", "신청합니다 [1]."]
            for tok in toks:
                self.wfile.write((json.dumps({"message": {"content": tok}, "done": False}) + "\n").encode())
            self.wfile.write((json.dumps({"done": True}) + "\n").encode())
            return
        self._json({"message": {"content": "다듬은 메일"}})


@pytest.fixture()
def api(tmp_path, monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("SEOMU_DOWNLOADS", str(tmp_path / "dl"))
    from seomu.api import Api
    a = Api(tmp_path / "home")
    a.save_settings({"ollama_url": f"http://127.0.0.1:{srv.server_address[1]}",
                     "regulation_dirs": [str(ROOT / "sample_data" / "regulations")]})
    yield a
    a.shutdown()
    srv.shutdown()


def wait(a, job):
    for _ in range(200):
        st = a.job_status(job["job_id"])
        if st["status"] != "running":
            assert st["status"] == "done", st["error"]
            return st["result"]
        time.sleep(0.05)
    raise TimeoutError


def test_full_flow(api):
    assert api.llm_status()["chat_model"] == "gemma3:4b"
    res = wait(api, api.reindex(False))
    assert res["added"] == 1
    ans = wait(api, api.ask("연가 신청은 언제까지?"))
    assert ans["mode"] == "llm" and "3일 전" in ans["answer"]
    assert "제5조" in ans["sources"][0]["heading"]

    notice_dir = ROOT / "sample_data" / "notice"
    n = wait(api, api.collect_files([str(notice_dir / "예시_공문.html"), str(notice_dir / "files" / "참가신청서.txt")]))
    folder = Path(n["folder"])
    assert folder.name.endswith("청렴 교육 행사 참여 요청")
    assert (folder / "요약.md").exists() and (folder / "붙임" / "참가신청서.txt").exists()
    assert n["analysis"]["deadlines"][0]["date"] == "2026-11-13"
    tasks = api.list_tasks()
    assert any(t["due"] == "2026-11-13" for t in tasks)

    tpl = api.list_templates()["templates"][0]
    mail = api.render_mail(tpl["id"], n["id"])
    assert "청렴" in mail["subject"] and "참가 신청서" in mail["body"]
    assert wait(api, api.polish_mail(mail["body"]))["body"] == "다듬은 메일"
    assert Path(api.export_ics()).exists()

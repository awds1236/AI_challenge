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

    installed = ["gemma3:4b"]
    blobs: set = set()

    def do_GET(self):
        self._json({"models": [{"name": n} for n in self.installed]})

    def do_HEAD(self):
        self.send_response(200 if self.path.split("/")[-1] in self.blobs else 404)
        self.end_headers()

    def do_DELETE(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.installed.remove(body["model"])
        self._json({})

    def _lines(self, objs):
        self.send_response(200)
        self.end_headers()
        for o in objs:
            self.wfile.write((json.dumps(o) + "\n").encode())

    def do_POST(self):
        if self.path.startswith("/api/blobs/"):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.blobs.add(self.path.split("/")[-1])
            self.send_response(201)
            self.end_headers()
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/pull":
            self.installed.append(body["model"])
            return self._lines([{"status": "pulling manifest"}, {"status": "downloading", "total": 10, "completed": 10},
                                {"status": "success"}])
        if self.path == "/api/copy":
            self.installed.append(body["destination"])
            return self._json({})
        if self.path == "/api/create":
            assert all(d in self.blobs for d in body["files"].values())
            self.installed.append(body["model"])
            return self._lines([{"status": "success"}])
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
    FakeOllama.installed[:] = ["gemma3:4b"]
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
    assert n["analysis"]["ai_status"] == "running"          # 규칙 기반 결과는 즉시, AI는 백그라운드
    for _ in range(100):
        a = api.get_notice(n["id"])["analysis"]
        if a["ai_status"] != "running":
            break
        time.sleep(0.05)
    assert a["ai_status"] == "done" and a["mode"] == "llm" and a["summary"] == "청렴 교육 참여 인원 회신 요청"
    tasks = api.list_tasks()
    assert sum(1 for t in tasks if t["due"] == "2026-11-13" and t["notice_id"] == n["id"]) == 1   # 중복 없음
    assert any(t["due"] == "2026-11-13" for t in tasks)

    tpl = api.list_templates()["templates"][0]
    mail = api.render_mail(tpl["id"], n["id"])
    assert "청렴" in mail["subject"] and "참가 신청서" in mail["body"]
    assert wait(api, api.polish_mail(mail["body"]))["body"] == "다듬은 메일"
    assert Path(api.export_ics()).exists()


def test_model_management(api, tmp_path):
    FakeOllama.installed[:] = ["gemma3:4b"]
    cat = api.model_catalog()
    assert cat["engine_ok"] and cat["recommend"]["model"]
    ids = [m["id"] for m in cat["models"]]
    assert {"gemma4:e2b-it-qat", "gemma4:e4b-it-qat", "kanana-2:3b", "kanana-2:1.3b"} <= set(ids)
    assert cat["others"] == ["gemma3:4b"]

    # 일반판(gemma4:e2b)만 받아도 E2B 카드가 설치됨으로 표시되고 그 이름으로 사용
    FakeOllama.installed.append("gemma4:e2b")
    card = next(m for m in api.model_catalog()["models"] if m["id"] == "gemma4:e2b-it-qat")
    assert card["installed"] and card["installed_id"] == "gemma4:e2b"
    assert "gemma4:e2b" not in api.model_catalog()["others"]
    assert api.use_model("gemma4:e2b")["active_chat"] == "gemma4:e2b"
    assert next(m for m in api.model_catalog()["models"] if m["id"] == "gemma4:e2b-it-qat")["active"]
    FakeOllama.installed.remove("gemma4:e2b")

    cat = wait(api, api.pull_model("gemma4:e2b-it-qat"))
    assert next(m for m in cat["models"] if m["id"] == "gemma4:e2b-it-qat")["installed"]
    cat = api.use_model("gemma4:e2b-it-qat")
    assert cat["active_chat"] == "gemma4:e2b-it-qat" and api.get_settings()["chat_model"] == "gemma4:e2b-it-qat"

    gguf = tmp_path / "kanana-2-3b-instruct-Q4_K_M.gguf"
    gguf.write_bytes(b"GGUF" + b"0" * 100)
    cat = wait(api, api.import_gguf(str(gguf), "kanana-2:3b"))
    assert next(m for m in cat["models"] if m["id"] == "kanana-2:3b")["installed"]

    cat = wait(api, api.pull_model("hf.co/someone/kanana-2-1.3b-GGUF:Q4_K_M", "kanana-2:1.3b"))
    assert next(m for m in cat["models"] if m["id"] == "kanana-2:1.3b")["installed"]
    assert "hf.co/someone/kanana-2-1.3b-GGUF:Q4_K_M" not in FakeOllama.installed

    api.delete_model("gemma4:e2b-it-qat")
    assert api.get_settings()["chat_model"] == ""
    with pytest.raises(ValueError):
        api.import_gguf(str(tmp_path / "nope.txt"), "x")


def test_capture_window_simulated(api, tmp_path, monkeypatch):
    """Windows 창 수집 흐름을 흉내 내어 검증 (본문 읽기 → 붙임 감시 → 분석·할 일 등록)."""
    from seomu import winwindow
    dl = tmp_path / "Downloads"
    dl.mkdir()
    body = ("제   목   2026년도 회계마감에 따른 협조사항 알림\n"
            "구 분\t추진기한\n계약심의위원회 심사 대상사업 의뢰\t2026.11.13한\n"
            "연간용역 계약의뢰\t2026.11. 27한\n집행잔액 반납\t2026.12.28한\n"
            "붙임  1. 계약심의위원회 운영 내규 1부.  끝.")
    win = {"hwnd": 101, "title": "2026년도 회계마감에 따른 협조사항 알림", "process": "viewer.exe", "cls": "X", "pid": 1}
    monkeypatch.setattr(winwindow, "available", lambda: True)
    monkeypatch.setattr(winwindow, "uia_available", lambda: False)
    monkeypatch.setattr(winwindow, "list_windows", lambda: [win])
    monkeypatch.setattr(winwindow, "extract_text", lambda h, log=None, trace=None: (body, "본문복사 버튼"))
    monkeypatch.setattr(winwindow, "save_window_image", lambda h, p: False)
    monkeypatch.setattr(winwindow, "get_clipboard", lambda: "")
    monkeypatch.setattr(winwindow, "watch_dirs", lambda extra=None: [dl])

    job = api.capture_window(101, "", False, 30)
    for _ in range(40):                       # 감시 단계에 들어갈 때까지 대기
        st = api.job_status(job["job_id"])
        if st["text"] and '"watch"' in st["text"]:
            break
        time.sleep(0.05)
    (dl / "계약심의위원회 운영 내규.hwp").write_bytes(b"hwp-data")   # 사용자가 붙임을 저장
    time.sleep(2.6)
    api.job_signal(job["job_id"], "done")
    n = wait(api, job)
    folder = Path(n["folder"])
    assert folder.name.endswith("2026년도 회계마감에 따른 협조사항 알림")
    assert (folder / "붙임" / "계약심의위원회 운영 내규.hwp").exists()
    assert not (dl / "계약심의위원회 운영 내규.hwp").exists()   # 다운로드 폴더에서 옮겨 정리
    assert [d["date"] for d in n["analysis"]["deadlines"]] == ["2026-11-13", "2026-11-27", "2026-12-28"]
    assert n["capture_method"] == "본문복사 버튼"
    assert (folder / "수집기록.txt").exists()


def test_capture_window_harvests_existing_attachment(api, tmp_path, monkeypatch):
    """뷰어가 이미 임시·캐시 폴더에 내려받아 둔 붙임을 이름으로 찾아 자동 수집하고 바로 끝난다."""
    from seomu import attach, winwindow
    cache = tmp_path / "AppData" / "Viewer" / "temp"
    cache.mkdir(parents=True)
    (cache / "공공체육시설 문화체육프로그램 추첨제 현황 조사표.hwp").write_bytes(b"form")
    (cache / "다른문서.hwp").write_bytes(b"other")
    body = ("제   목   추첨제 현황 조사 협조 요청\n2. 운영현황을 조사하오니 협조하여 주시기 바랍니다.\n"
            "  마. 회신기한 : 2026. 11. 13.(금)\n첨부  공공체육시설 문화체육프로그램 추첨제 현황 조사표 1부.  끝.")
    win = {"hwnd": 7, "title": "추첨제 현황 조사 협조 요청", "process": "viewer.exe", "cls": "X", "pid": 1}
    monkeypatch.setattr(winwindow, "available", lambda: True)
    monkeypatch.setattr(winwindow, "list_windows", lambda: [win])
    monkeypatch.setattr(winwindow, "extract_text", lambda h, log=None, trace=None: (body, "전체 선택·복사"))
    monkeypatch.setattr(winwindow, "save_window_image", lambda h, p, **k: False)
    monkeypatch.setattr(winwindow, "get_clipboard", lambda: "")
    monkeypatch.setattr(winwindow, "watch_dirs", lambda extra=None: [tmp_path / "none"])
    monkeypatch.setattr(attach, "search_roots", lambda: [(tmp_path / "AppData", 4)])
    t0 = time.time()
    n = wait(api, api.capture_window(7, "", False, 60))
    assert time.time() - t0 < 10                       # 다 모았으니 기다리지 않고 끝남
    assert n["attach_summary"] == {"expected": 1, "found": 1, "extra": 0}
    assert (Path(n["folder"]) / "붙임" / "공공체육시설 문화체육프로그램 추첨제 현황 조사표.hwp").exists()
    assert n["analysis"]["deadlines"][0]["what"] == "조사표 회신" or n["analysis"]["deadlines"][0]["date"] == "2026-11-13"

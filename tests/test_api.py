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
    a.save_settings({"engine": "ollama", "ollama_url": f"http://127.0.0.1:{srv.server_address[1]}",
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
    monkeypatch.setattr(winwindow, "extract_text", lambda h, log=None, trace=None, found=None: (body, "본문복사 버튼"))
    monkeypatch.setattr(winwindow, "save_window_image", lambda h, p, **k: False)
    monkeypatch.setattr(winwindow, "get_clipboard", lambda: "")
    monkeypatch.setattr(winwindow, "watch_dirs", lambda extra=None: [dl])
    from seomu import attach
    monkeypatch.setattr(attach, "candidate_files", lambda *a, **k: [])   # 실제 PC 파일은 훑지 않는다
    monkeypatch.setattr(attach, "recent_documents", lambda *a, **k: [])
    monkeypatch.setattr(winwindow, "open_named_on_screen", lambda *a, **k: [])
    monkeypatch.setattr(winwindow, "try_save_attachments", lambda *a, **k: "")

    job = api.capture_window(101, "", False, 30)
    for _ in range(600):                      # 감시 단계에 들어갈 때까지 대기 (PC 파일 탐색은 최대 수 초)
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
    assert (dl / "계약심의위원회 운영 내규.hwp").exists()       # 원본 보호: 다운로드 폴더의 원본은 그대로 둔다
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
    monkeypatch.setattr(winwindow, "extract_text", lambda h, log=None, trace=None, found=None: (body, "전체 선택·복사"))
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


def test_capture_window_uses_screen_attachment_list(api, tmp_path, monkeypatch):
    """본문을 화면 글자 인식으로 읽어 붙임 표기가 없어도(본문 단만 읽음), 뷰어 화면의 붙임 목록 칸에 보이는
    파일 이름으로 붙임을 알아내 뷰어가 받아 둔 파일을 모은다."""
    from seomu import attach, winwindow
    cache = tmp_path / "AppData" / "XSAppr" / "temp"
    cache.mkdir(parents=True)
    (cache / "자체점검표(공중이용시설).hwpx").write_bytes(b"form")
    body = ("중대재해처벌법에 따라 2026년도 하반기 안전·보건 의무 이행사항에 대하여 점검 실시\n"
            "해당 관리기관에서는 자체점검 후 자체점검표(공중이용시설)를 작\n성하여 제출하여 주시기 바랍니다.\n"
            "□ 점검개요\n0 기간: 2026. 11. 9.(월) ~ 11. 20.(금)\n0 방법: 관리기관 제출 (11월 11일(수)까지)")
    win = {"hwnd": 9, "title": "2026년 하반기 중대시민재해 점검계획 알림 및 자체점검표 제출 요청",
           "process": "XSAppr.exe", "cls": "X", "pid": 1}
    monkeypatch.setattr(winwindow, "available", lambda: True)
    monkeypatch.setattr(winwindow, "list_windows", lambda: [win])
    monkeypatch.setattr(winwindow, "extract_text", lambda h, log=None, trace=None, found=None: (body, "화면 글자 인식(OCR)"))
    monkeypatch.setattr(winwindow, "save_window_image", lambda h, p, **k: False)
    monkeypatch.setattr(winwindow, "screen_attachment_names",
                        lambda h, trace=None, use_ocr=True: ["자체점검표(공중이용시설).hwpx"])
    monkeypatch.setattr(winwindow, "get_clipboard", lambda: "")
    monkeypatch.setattr(winwindow, "watch_dirs", lambda extra=None: [tmp_path / "none"])
    monkeypatch.setattr(attach, "search_roots", lambda: [(tmp_path / "AppData", 4)])
    monkeypatch.setattr(attach, "recent_documents", lambda *a, **k: [])
    n = wait(api, api.capture_window(9, "", False, 60))
    assert n["attach_summary"] == {"expected": 1, "found": 1, "extra": 0}
    assert (Path(n["folder"]) / "붙임" / "자체점검표(공중이용시설).hwpx").exists()


def _fake_window(monkeypatch, tmp_path, body, win, extra_windows=(), found_html="", names=()):
    from seomu import attach, winwindow

    def extract(h, log=None, trace=None, found=None):
        if found is not None and found_html:
            found["html"] = found_html
        return body, "전체 선택·복사"
    monkeypatch.setattr(winwindow, "available", lambda: True)
    monkeypatch.setattr(winwindow, "list_windows", lambda: [win, *extra_windows])
    monkeypatch.setattr(winwindow, "extract_text", extract)
    monkeypatch.setattr(winwindow, "save_window_image", lambda h, p, **k: False)
    monkeypatch.setattr(winwindow, "screen_attachment_names", lambda h, trace=None, use_ocr=True: list(names))
    monkeypatch.setattr(winwindow, "get_clipboard", lambda: "")
    monkeypatch.setattr(winwindow, "watch_dirs", lambda extra=None: [tmp_path / "none"])
    monkeypatch.setattr(winwindow, "open_named_on_screen", lambda *a, **k: [])
    monkeypatch.setattr(winwindow, "try_save_attachments", lambda *a, **k: "")
    monkeypatch.setattr(attach, "search_roots", lambda: [(tmp_path / "AppData", 4)])
    monkeypatch.setattr(attach, "recent_documents", lambda *a, **k: [])


def test_capture_window_does_not_collect_unrelated_files(api, tmp_path, monkeypatch):
    """붙임 이름을 모르면 PC 안의 아무 파일이나 붙임으로 모으지 않는다 (뷰어 캐시·다운로드 폴더의 다른 문서)."""
    cache = tmp_path / "AppData" / "XSAppr" / "temp"
    cache.mkdir(parents=True)
    (cache / "점검표.hwp").write_bytes(b"form")
    body = "자체점검 후 결과를 제출하여 주시기 바랍니다. 기한: 2026. 11. 20.(금)까지 회신 바랍니다. 담당자 확인 요망."
    _fake_window(monkeypatch, tmp_path, body, {"hwnd": 10, "title": "점검 요청", "process": "XSAppr.exe", "cls": "X", "pid": 1})
    job = api.capture_window(10, "", False, 20)
    time.sleep(0.5)
    api.job_signal(job["job_id"], "done")
    n = wait(api, job)
    assert list((Path(n["folder"]) / "붙임").iterdir()) == []
    assert n["need_upload"] == [] and n["maybe_attach"] is False


def test_capture_window_skips_documents_open_in_other_windows(api, tmp_path, monkeypatch):
    """지금 한글로 열어 둔 내 문서는 이름이 비슷해도 붙임으로 모으지 않고, 못 받은 붙임은 업로드를 요청한다."""
    dl = tmp_path / "AppData" / "Downloads"
    dl.mkdir(parents=True)
    (dl / "2026년 공공 AI 대전환 챌린지 참가 안내서.hwpx").write_bytes(b"mine")       # 사용자가 열어 둔 문서
    (dl / "2026년 하반기 점검 결과 보고.hwpx").write_bytes(b"other")                    # 앞부분만 비슷한 문서
    body = ("2026년 하반기 시설 점검 계획 알림\n점검 결과를 2026. 11. 20.(금)까지 제출하여 주시기 바랍니다.\n"
            "붙임  1. 2026년 공공 AI 대전환 챌린지 참가 안내 1부.\n 2. 2026년 하반기 점검 계획 1부.  끝.")
    hwp = {"hwnd": 11, "title": "2026년 공공 AI 대전환 챌린지 참가 안내서.hwpx [C:\\x\\] - 한글", "process": "Hwp.exe",
           "cls": "HwpFrame", "pid": 2}
    _fake_window(monkeypatch, tmp_path, body, {"hwnd": 12, "title": "시설 점검 계획 알림", "process": "XSAppr.exe",
                                                "cls": "X", "pid": 1}, extra_windows=[hwp])
    job = api.capture_window(12, "", False, 20)
    time.sleep(0.5)
    api.job_signal(job["job_id"], "done")
    n = wait(api, job)
    assert list((Path(n["folder"]) / "붙임").iterdir()) == []
    assert n["need_upload"] == ["2026년 공공 AI 대전환 챌린지 참가 안내", "2026년 하반기 점검 계획"]
    # 사용자가 받아서 올리면 '받지 못함' 칸이 채워진다 (원본은 그대로)
    up = tmp_path / "받은 붙임"
    up.mkdir()
    (up / "2026년 하반기 점검 계획.hwpx").write_bytes(b"plan")
    m = api.add_notice_attachments(n["id"], [str(up / "2026년 하반기 점검 계획.hwpx")])
    names = {f["name"]: f["ok"] for f in m["attachments"]}
    assert names.get("2026년 하반기 점검 계획.hwpx") is True and (up / "2026년 하반기 점검 계획.hwpx").exists()
    assert sum(1 for f in m["attachments"] if not f["ok"]) == 1
    with pytest.raises(ValueError):
        api.add_notice_attachments(n["id"], [])


def test_capture_window_downloads_attachment_links_from_copied_html(api, tmp_path, monkeypatch):
    """전체 선택·복사로 받은 HTML에 붙임 링크가 있으면 내려받는다."""
    import http.server
    import socketserver
    import threading
    site = tmp_path / "site"
    site.mkdir()
    (site / "form.hwpx").write_bytes(b"PK\x03\x04hwpx-data" + b"x" * 200)

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(site), **k)

        def log_message(self, *a):
            pass
    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/form.hwpx"
    html = f'<!--source:http://127.0.0.1/--><p>본문</p><a href="{url}">현황 조사표.hwpx</a>'
    body = "현황 조사 협조\n현황을 2026. 11. 20.(금)까지 제출하여 주시기 바랍니다.\n붙임 현황 조사표 1부. 끝."
    _fake_window(monkeypatch, tmp_path, body, {"hwnd": 13, "title": "현황 조사 협조", "process": "XSAppr.exe",
                                                "cls": "X", "pid": 1}, found_html=html)
    try:
        n = wait(api, api.capture_window(13, "", False, 30))
    finally:
        srv.shutdown()
    assert n["attach_summary"]["found"] == 1 and n["need_upload"] == []
    assert [p.name for p in (Path(n["folder"]) / "붙임").iterdir()] == ["현황 조사표.hwpx"]


def test_recollecting_same_notice_does_not_duplicate(api, tmp_path):
    """같은 공문을 다시 수집하면 공문·할 일이 겹쳐 생기지 않고, 완료 표시는 남고, 새 붙임만 더해진다."""
    body = ("제목 청사 소방시설 점검 협조\n1. 청사 소방시설 정기 점검을 실시하오니 협조하여 주시기 바랍니다.\n"
            "2. 점검 결과 확인서를 2026. 12. 20.(일)까지 회신하여 주시기 바랍니다.\n붙임 결과 확인서 서식 1부. 끝.")
    first = wait(api, api.collect_text(body, "", False))
    tasks = [t for t in api.list_tasks() if t["notice_id"] == first["id"]]
    assert tasks
    api.update_task(tasks[0]["id"], {"done": True})
    src = tmp_path / "src"
    src.mkdir()
    (src / "공문.txt").write_text(body, encoding="utf-8")
    (src / "결과 확인서 서식.txt").write_text("결과 확인서\n부서: ", encoding="utf-8")
    again = wait(api, api.collect_files([str(src / "공문.txt"), str(src / "결과 확인서 서식.txt")], "", 0, False))
    assert again["id"] == first["id"] and again["duplicate"] and again["added_files"] == 1
    assert len(api.list_notices()) == 1
    tasks2 = [t for t in api.list_tasks() if t["notice_id"] == first["id"]]
    assert len(tasks2) == len(tasks) and any(t["done"] for t in tasks2)
    assert any(f["ok"] and "결과 확인서" in f["name"] for f in again["attachments"])
    folders = [p for p in (tmp_path / "dl" / "서무비서").iterdir() if p.is_dir()]
    assert len(folders) == 1                                    # 다시 수집하며 만든 폴더는 지워진다
    # 다른 공문은 그대로 새로 만든다
    other = wait(api, api.collect_text(body.replace("12. 20.", "12. 21."), "", False))
    assert other["id"] != first["id"] and not other.get("duplicate")


def test_open_mail_uses_shell_and_drops_long_body(api, monkeypatch):
    """[메일 앱으로]: 앱 안에서 mailto:로 연다. 한글 본문이 길면 주소 길이 제한 때문에 제목만 넘긴다. (실제 창은 열지 않음)"""
    import os
    import seomu.api as api_mod
    opened = []
    monkeypatch.setattr(os, "startfile", lambda u: opened.append(u), raising=False)
    monkeypatch.setattr(api_mod.sys, "platform", "win32")        # Windows 방식(ShellExecute)을 흉내 낸다
    assert api.open_mail("[회신] 점검", "짧은 본문")["with_body"]
    assert opened[-1].startswith("mailto:?subject=") and "&body=" in opened[-1]
    assert not api.open_mail("[회신] 점검", "가" * 500)["with_body"]
    assert "&body=" not in opened[-1] and len(opened[-1]) < 1900

    def boom(u):
        raise OSError("연결된 프로그램 없음")
    monkeypatch.setattr(os, "startfile", boom, raising=False)
    with pytest.raises(RuntimeError, match="전체 복사"):
        api.open_mail("제목", "본문")


def test_open_path_explains_missing_program(api, tmp_path, monkeypatch):
    """여는 프로그램이 없는 파일(한글이 없는 PC의 .hwpx)은 Windows의 '어떤 앱으로' 창 대신 이유를 알려 준다."""
    import os
    import seomu.api as api_mod
    opened = []
    monkeypatch.setattr(os, "startfile", lambda *a, **k: opened.append(a), raising=False)
    monkeypatch.setattr(api_mod.sys, "platform", "win32")
    monkeypatch.setattr(api_mod, "_has_open_program", lambda ext: ext != ".hwpx")
    f = tmp_path / "보고서.hwpx"
    f.write_bytes(b"PK")
    with pytest.raises(ValueError, match="한글"):
        api.open_path(str(f))
    assert not opened
    t = tmp_path / "메모.txt"
    t.write_text("x", encoding="utf-8")
    assert api.open_path(str(t)) and opened
    assert api.open_path(str(tmp_path / "없는 파일.txt")) is False


def test_capture_window_matches_viewer_saved_files_by_content(api, tmp_path, monkeypatch):
    """뷰어의 'PC저장'이 관리용 번호 이름으로 공문 폴더에 바로 저장한 붙임을 내용으로 알아보고 붙임 이름으로 바꾼다.
    프로그램이 쓰는 화면 캡처(seomu_*.png)와 임시 폴더의 다른 프로그램 파일은 붙임으로 모으지 않는다."""
    from seomu import winwindow
    temp = tmp_path / "Temp"
    temp.mkdir()
    monkeypatch.setenv("TEMP", str(temp))
    body = ("2026년 하반기 중대시민재해 점검계획 알림\n자체점검표를 2026. 11. 11.(수)까지 제출하여 주시기 바랍니다.\n"
            "붙임  1. 중대재해 예방을 위한 2026년 하반기 안전보건 확보의무 이행사항 점검계획 1부.\n"
            "      2. 2026년 하반기 안전보건 확보의무 이행사항 자체점검표(공중이용시설) 1부.  끝.")
    _fake_window(monkeypatch, tmp_path, body, {"hwnd": 14, "title": "중대시민재해 점검계획 알림", "process": "XSAppr.exe",
                                                "cls": "X", "pid": 1})
    monkeypatch.setattr(winwindow, "watch_dirs", lambda extra=None: [temp])

    def save(hwnd, folder, log=None, trace=None):
        # 뷰어가 저장 창 두 개를 띄워 공문 폴더에 관리용 이름으로 저장한다 + 그 사이 임시 폴더에 다른 파일이 생긴다
        (folder / "15684_AT_db6840f3cbd3435fb84962add454f41c.txt").write_text(
            "중대재해 예방을 위한 2026년 하반기 안전보건 확보의무 이행사항 점검계획\n1. 목적 ...", encoding="utf-8")
        (folder / "15685_AT_aa11bb22cc33dd44ee55ff6600112233.txt").write_text(
            "2026년 하반기 안전보건 확보의무 이행사항 자체점검표(공중이용시설)\n시설명 | 점검일 ...", encoding="utf-8")
        (temp / "seomu_toolbar.png").write_bytes(b"png")
        (temp / "other_app_cache.png").write_bytes(b"png")
        return "saved"
    monkeypatch.setattr(winwindow, "try_save_attachments", save)
    job = api.capture_window(14, "", False, 20)
    for _ in range(200):
        st = api.job_status(job["job_id"])
        if st["status"] != "running":
            break
        time.sleep(0.1)
    if st["status"] == "running":
        api.job_signal(job["job_id"], "done")
    n = wait(api, job)
    files = sorted(p.name for p in (Path(n["folder"]) / "붙임").iterdir())
    assert files == ["2026년 하반기 안전보건 확보의무 이행사항 자체점검표(공중이용시설).txt",
                     "중대재해 예방을 위한 2026년 하반기 안전보건 확보의무 이행사항 점검계획.txt"]
    assert n["attach_summary"] == {"expected": 2, "found": 2, "extra": 0} and n["need_upload"] == []


def test_old_bogus_body_attachments_are_cleaned_when_opened(api, tmp_path):
    """예전 규칙으로 붙임 문서 자체의 본문을 붙임 목록으로 읽어 저장한 '받지 못함' 항목은 공문을 열 때 정리된다."""
    doc = tmp_path / "붙임1_안내서.txt"
    doc.write_text("붙임1. 2026년 공공 AI 대전환 챌린지(AI경진) 참가 안내서\n< 한눈에 보기 >\n구분\n세션 1\n"
                   + "제출 기한은 2026. 11. 11.(수)까지입니다. 참가 신청서를 메일로 제출하여 주시기 바랍니다.\n" * 8,
                   encoding="utf-8")
    n = wait(api, api.collect_files([str(doc)], "", 0, False))
    assert [f for f in n["attachments"] if not f["ok"]] == []           # 새 규칙: 처음부터 생기지 않는다
    bogus = [{"name": x, "path": "", "ok": False, "error": "본문에 적힌 붙임입니다 — 파일을 공문 폴더의 '붙임'에 넣으면 자동으로 연결됩니다"}
             for x in ("< 한눈에 보기 >", "구분", "세션 1")]
    api._store.update_notice_attachments(n["id"], bogus)                # 예전 버전이 저장한 상태를 흉내
    assert [f for f in api.get_notice(n["id"])["attachments"] if not f["ok"]] == []


def test_recollecting_same_notice_read_differently_is_not_duplicated(api, tmp_path):
    """같은 공문을 한 번은 글자 인식(잡글자 섞임), 한 번은 본문복사(깨끗함)로 읽어도 하나로 합치고 본문은 깨끗한 쪽으로."""
    clean = ("2026년 하반기 중대시민재해 점검계획 알림 및 자체점검표 제출 요청\n"
             "1. 귀 기관의 무궁한 발전을 기원합니다.\n"
             "2. 중대재해처벌법에 따라 2026년도 하반기 안전·보건 의무 이행사항에 대하여 점검을 실시하고자 하오니 "
             "해당 관리기관에서는 자체점검 후 자체점검표(공중이용시설)를 작성하여 2026. 11. 11.(수)까지 제출하여 주시기 바랍니다.\n"
             "붙임 1. 자체점검표(공중이용시설) 1부. 끝.")
    ocr = ("E RP\n회니기한 공람지정 내배부\n붙임문서 본문복사 PCIdLY 새미름 임,니저장 인쇄\n"
           "2026년\n하반기 중대시민재해 점검계획 알림 및 자체점검표 제출 요제목\n1. 귀 기관의 무궁한 발전을 기원합니다.\n"
           "2. 중대재해처벌법에\n따라 2026년도 하반기안전 보건 의무 이행사항에 대하여 점검을\n실시하고자 하오니 해당 관리기관에서는")
    title = "2026년 하반기 중대시민재해 점검계획 알림 및 자체점검표 제출 요청"
    first = wait(api, api.collect_text(ocr, title, False))
    again = wait(api, api.collect_text(clean, title, False))
    assert again["id"] == first["id"] and again["duplicate"] and again["body_updated"]
    assert len(api.list_notices()) == 1
    n = api.get_notice(first["id"])
    assert "PCIdLY" not in n["body"] and "자체점검표(공중이용시설)를 작성하여" in n["body"]
    assert [d["date"] for d in n["analysis"]["deadlines"]] == ["2026-11-11"]
    # 다른 공문은 합치지 않는다
    other = wait(api, api.collect_text("시민체감 서비스 개선과제 발굴\n각 부서에서는 개선과제를 발굴하여 2026. 11. 20.(금)까지 "
                                       "제출하여 주시기 바랍니다. 우수 과제는 포상할 예정입니다.", "시민체감 서비스 개선과제 발굴", False))
    assert other["id"] != first["id"] and len(api.list_notices()) == 2


def test_capture_window_twice_while_running_is_refused(api, monkeypatch):
    from seomu import winwindow
    from seomu.api import Job
    monkeypatch.setattr(winwindow, "available", lambda: True)
    j = Job("capture_window")
    api._jobs[j.id] = j                                      # 수집이 진행 중인 상태
    with pytest.raises(ValueError, match="수집하는 중"):
        api.capture_window(1, "", False, 20)
    j.status = "done"


def test_unreadable_body_is_not_analyzed_by_ai(api, tmp_path, monkeypatch):
    """본문 파일을 읽지 못하면(HWP에 olefile 없음 등) AI 분석을 하지 않고 이유를 보여 준다 (AI가 내용을 지어내지 않게)."""
    from seomu import parsers
    doc = tmp_path / "교육안내.hwp"
    doc.write_bytes(b"\xd0\xcf\x11\xe0not-really-hwp")
    att = tmp_path / "교육 추진계획.pdf"
    att.write_bytes(b"%PDF-1.4 x")
    real = parsers.parse_file

    def fail(p, *a, **k):
        if str(p).endswith(".hwp"):
            raise parsers.ParseError("HWP 파일을 읽으려면 olefile 패키지가 필요합니다 (pip install olefile)")
        return real(p, *a, **k)
    monkeypatch.setattr(parsers, "parse_file", fail)
    n = wait(api, api.collect_files([str(doc), str(att)], "", 0, True))
    a = n["analysis"]
    assert a["ai_status"] == "off" and "olefile" in a["body_error"] and a["summary"].startswith("본문을 읽지 못해")
    assert a["deadlines"] == [] and any(f["ok"] and f["name"].endswith(".pdf") for f in n["attachments"])
    assert {m["package"] for m in api.missing_packages()} <= {"olefile", "pypdf", "openpyxl", "lxml"}
    assert "missing_packages" in api.app_info()


def test_unreadable_hwp_body_falls_back_to_body_pdf(api, tmp_path, monkeypatch):
    """배포용(암호화) HWP 본문을 못 읽어도, 붙임에 '[본문] 제목.pdf'(같은 본문의 PDF)가 있으면 그것으로 분석한다.
    다른 붙임(계획서 등)은 본문으로 쓰지 않는다."""
    from seomu import parsers
    doc = tmp_path / "2026년 모의훈련 실시 알림.hwp"
    doc.write_bytes(b"\xd0\xcf\x11\xe0")
    body_pdf = tmp_path / "[본문] 2026년 모의훈련 실시 알림.pdf"
    body_pdf.write_bytes(b"%PDF-1.4 x")
    plan = tmp_path / "모의훈련 계획(기후부).hwpx"
    plan.write_bytes(b"PK")
    body = ("2026년 초미세먼지 재난대응 모의훈련 실시 알림\n1. 관련: 기후부 공문\n"
            "2. 모의훈련을 실시하니 각 부서는 결과 보고서를 2026. 12. 1.까지 제출하여 주시기 바랍니다.")

    def fake(p, *a, **k):
        p = str(p)
        if p.endswith(".hwp"):
            raise parsers.ParseError("배포용(암호화) HWP 문서는 읽을 수 없습니다")
        if p.endswith(".pdf"):
            return body
        return "모의훈련 세부 계획 " * 10
    monkeypatch.setattr(parsers, "parse_file", fake)
    n = wait(api, api.collect_files([str(doc), str(body_pdf), str(plan)], "", 0, False))
    a = n["analysis"]
    assert "body_error" not in a and "모의훈련" in n["body"] and "세부 계획" not in n["body"]
    assert any(d["date"] == "2026-12-01" for d in a["deadlines"])


def test_body_from_attachments_ignores_other_files(tmp_path):
    from seomu.collector import body_from_attachments
    f = tmp_path / "계획.txt"
    f.write_text("이것은 다른 붙임 문서입니다. " * 5, encoding="utf-8")
    assert body_from_attachments([{"name": f.name, "path": str(f), "ok": True}], "공문.hwp") is None
    g = tmp_path / "공문.txt"
    g.write_text("같은 본문을 텍스트로 저장한 파일입니다. " * 5, encoding="utf-8")
    got = body_from_attachments([{"name": f.name, "path": str(f), "ok": True},
                                 {"name": g.name, "path": str(g), "ok": True}], "본문_공문.hwp")
    assert got and got[1]["name"] == "공문.txt"

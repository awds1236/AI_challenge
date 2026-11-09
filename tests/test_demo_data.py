"""시연용 예시 공문(sample_data/시연/)이 기대한 결과로 분석되는지 — 시연 중에 틀린 결과가 나오지 않게."""
import time
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parent.parent / "sample_data" / "시연"


def _collect(api, folder: Path) -> dict:
    files = sorted(folder.iterdir(), key=lambda p: ("붙임" in p.name, p.name))      # 본문이 먼저
    job = api.collect_files([str(f) for f in files], "", 0, False)
    for _ in range(400):
        st = api.job_status(job["job_id"])
        if st["status"] != "running":
            assert st["status"] == "done", st
            return st["result"]
        time.sleep(0.05)
    raise AssertionError("시간 초과")


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SEOMU_DOWNLOADS", str(tmp_path / "dl"))
    from seomu.api import Api
    a = Api(tmp_path / "home")
    yield a
    a.shutdown()


def test_demo_submission_request(api):
    pytest.importorskip("pypdf")
    n = _collect(api, DEMO / "1_제출요청")
    a = n["analysis"]
    assert n["title"] == "2026년 동절기 시설물 안전점검 실시 및 결과 제출 요청"
    assert [(d["date"], d["time"]) for d in a["deadlines"]] == [("2026-11-27", "18:00")]
    assert any("안전점검 결과 보고서" in s["item"] for s in a["submissions"])
    assert sorted(f["name"] for f in n["attachments"] if f["ok"]) == [
        "붙임1. 2026년 동절기 시설물 안전점검 계획.hwpx", "붙임2. 안전점검 결과 보고서(서식).xlsx"]


def test_demo_training_notice(api):
    n = _collect(api, DEMO / "2_교육안내")
    a = n["analysis"]
    assert n["title"] == "2026년 하반기 청렴·적극행정 교육 참석 안내"
    assert [d["date"] for d in a["deadlines"]] == ["2026-11-20"]
    assert a["event"]["place"] == "본사 3층 대회의실" and "2026. 11. 25." in a["event"]["date"]
    assert len([f for f in n["attachments"] if f["ok"]]) == 2


def test_demo_memos_differ_by_kind():
    from seomu import polish
    memo = (DEMO / "문서다듬기_예시메모.txt").read_text(encoding="utf-8")
    assert "[공문]" in memo and "[보고]" in memo
    d = "체육관 동절기 운영시간 변경 안내\n12월 1일부터 2월 28일까지 평일 운영시간 06:00~21:00으로 변경\n변경 사항 회원 안내문 게시 협조해줘"
    off = polish.rule_polish(d, "official", {})["body"]
    assert "  가. 12월 1일부터 2월 28일까지 평일 운영시간" in off        # 기간만 있는 줄은 요청이 아니라 내용
    assert "협조하여 주시기 바랍니다" in off and "회신" not in off

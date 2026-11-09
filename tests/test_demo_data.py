"""시연용 예시 공문 10건(sample_data/시연/)이 기대한 결과로 분석되고, 붙임 서식이 채워지는지.
시연 중에 틀린 결과가 나오지 않게 한다. (10번 스캔 공문은 Windows 글자 인식이 있어야 읽으므로 본문 분석은 빼고 본다)"""
import time
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parent.parent / "sample_data" / "시연"
PROFILE = {"user_name": "안성균", "user_dept": "체육시설사업팀", "user_phone": "042-123-4700"}

# 폴더: (제목, [(기한 날짜, 시각)], 제출물에 들어갈 말, 붙임 수, 채울 서식 이름 일부, 채워져야 할 칸)
EXPECT = {
    "01_예산요구": ("2027년도 부서별 예산 요구서 제출 요청", [("2026-11-27", "17:00")], "예산 요구서", 2,
                 "예산 요구서", {"부 서 명", "작 성 자", "연 락 처", "작 성 일"}),
    "02_개인정보점검": ("2026년 하반기 개인정보 보호 실태 자체점검 실시", [("2026-12-04", "")], "점검 결과 보고서", 2,
                   "점검 결과 보고서", {"소  속", "작 성 자", "연 락 처", "점검 기간", "점검 대상", "작 성 일"}),
    "03_가족문화의날": ("한빛 가족 문화의 날 운영 협조 요청", [("2026-11-25", "")], "자원봉사자 신청서", 3,
                   "자원봉사자 신청서", {"성  명", "소  속", "연 락 처", "신 청 일"}),
    "04_교육수요조사": ("2027년 직무교육 수요조사 실시", [("2026-11-20", "")], "수요조사서", 2,
                   "수요조사서", {"부 서 명", "작 성 자", "작 성 일"}),
    "05_공용차량점검": ("공용차량 운행일지 점검 결과 통보 및 개선 요청", [("2026-11-30", "")], "개선 조치 계획서", 2,
                   "개선 조치 계획서", {"부서명", "작성자", "연락처", "작성일"}),
    "06_연말연시당직": ("2026~2027년 연말연시 당직근무 편성 안내", [("2026-11-18", "")], None, 2, None, None),
    "07_건강검진": ("2026년 직원 일반건강검진 미수검자 수검 안내", [("2026-12-15", ""), ("2026-12-18", "")], "수검 확인서", 2,
                 None, None),
    "08_메일_만족도조사": ("[협조] 2026년 시민 만족도 조사 설문 문항 검토 의견 요청", [("2026-11-19", "18:00")], "의견 회신서", 5,
                     "의견 회신서", {"부 서 명", "작 성 자", "연 락 처", "작 성 일"}),
    "09_청렴서약": ("2026년 임직원 청렴 서약서 제출 안내", [("2026-11-27", "")], "청렴 서약서", 2,
                 "청렴 서약서", {"작성일", "소속", "성명"}),
}


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    import os
    tmp = tmp_path_factory.mktemp("demo")
    old = os.environ.get("SEOMU_DOWNLOADS")
    os.environ["SEOMU_DOWNLOADS"] = str(tmp / "dl")
    from seomu.api import Api
    a = Api(tmp / "home")
    a.save_settings(PROFILE)
    yield a
    a.shutdown()
    if old is None:
        os.environ.pop("SEOMU_DOWNLOADS", None)
    else:
        os.environ["SEOMU_DOWNLOADS"] = old


def _collect(api, folder: Path) -> dict:
    files = sorted(folder.iterdir(), key=lambda p: (p.name.startswith("붙임"), p.name))      # 본문이 먼저
    job = api.collect_files([str(f) for f in files], "", 0, False)
    for _ in range(600):
        st = api.job_status(job["job_id"])
        if st["status"] != "running":
            assert st["status"] == "done", st
            return st["result"]
        time.sleep(0.05)
    raise AssertionError("시간 초과")


def test_ten_demo_notices_exist():
    dirs = sorted(p.name for p in DEMO.iterdir() if p.is_dir())
    assert len(dirs) == 10
    exts = {f.suffix.lower() for f in DEMO.rglob("*") if f.is_file()}
    # 공공기관에서 주고받는 형식을 고르게 담았다
    assert {".hwpx", ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".odt", ".ods", ".odp",
            ".rtf", ".txt", ".csv", ".html", ".mht", ".eml", ".png"} <= exts


@pytest.mark.parametrize("folder", sorted(EXPECT))
def test_demo_notice_analysis_and_form(api, folder):
    pytest.importorskip("pypdf")
    pytest.importorskip("xlrd")
    title, dls, sub, n_att, form, must = EXPECT[folder]
    n = _collect(api, DEMO / folder)
    a = n["analysis"]
    assert n["title"] == title
    assert "body_error" not in a
    assert [(d["date"], d["time"]) for d in a["deadlines"]] == dls
    if sub:
        assert any(sub in s["item"] for s in a["submissions"]), a["submissions"]
    assert all("목록" not in s["item"] and "초안" not in s["item"] for s in a["submissions"])   # 참고용 붙임은 제출물이 아니다
    ok = [f for f in n["attachments"] if f["ok"]]
    assert len(ok) == n_att, [f["name"] for f in n["attachments"]]
    if form:
        f = next(x for x in ok if form in x["name"] and "서식" in x["name"])
        r = api.fill_notice_form(n["id"], f["path"])
        assert must <= set(r["filled"]), r
        assert Path(r["path"]).is_file() and Path(r["path"]).parent.name == "작성"
        from seomu.parsers import parse_file
        text = parse_file(r["path"])
        assert "안성균" in text or "체육시설사업팀" in text


def test_demo_event_and_summary(api):
    n = _collect(api, DEMO / "03_가족문화의날")
    ev = n["analysis"]["event"]
    assert ev["place"] == "공단 본사 앞 열린광장" and ev["date"].startswith("2026. 12. 12.")
    # 기한이 둘인 공문: 요약 문장에는 그 문장의 기한(확인서 제출 12/18)이 붙는다
    n = _collect(api, DEMO / "07_건강검진")
    assert "12월 18일" in n["analysis"]["summary"].splitlines()[0]


def test_demo_scanned_notice_title_and_reply_form(api):
    """스캔 공문: 글자 인식이 없는 PC에서는 본문을 못 읽어도 제목은 파일 이름에서 '[스캔]'을 떼고, 회신서는 채운다."""
    n = _collect(api, DEMO / "10_스캔_합동점검")
    assert n["title"] == "공공시설 안전 합동점검 일정 통보"
    f = next(x for x in n["attachments"] if "회신서" in x["name"])
    r = api.fill_notice_form(n["id"], f["path"])
    assert {"부서명", "담당자", "연락처", "작성일"} <= set(r["filled"])


def test_fill_notice_form_rejects_outside_files(api, tmp_path):
    n = _collect(api, DEMO / "09_청렴서약")
    other = tmp_path / "남의파일.hwpx"
    other.write_bytes(b"PK")
    with pytest.raises(ValueError):
        api.fill_notice_form(n["id"], str(other))


def test_demo_memos_differ_by_kind():
    from seomu import polish
    memo = (DEMO / "문서다듬기_예시메모.txt").read_text(encoding="utf-8")
    assert all(k in memo for k in ("[메일]", "[공문]", "[보고]", "[메시지]"))
    d = "체육관 동절기 운영시간 변경 안내\n12월 1일부터 2월 28일까지 평일 운영시간 06:00~21:00으로 변경\n변경 사항 회원 안내문 게시 협조해줘"
    off = polish.rule_polish(d, "official", {})["body"]
    assert "  가. 12월 1일부터 2월 28일까지 평일 운영시간" in off        # 기간만 있는 줄은 요청이 아니라 내용
    assert "협조하여 주시기 바랍니다" in off and "회신" not in off

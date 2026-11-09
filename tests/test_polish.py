"""문서 다듬기: 메모 → 메일·공문·보고·메시지, 내 양식 따르기, AI가 숫자·날짜를 바꾸면 규칙 결과."""
import json
import socket
import time

import pytest

from seomu import polish

DRAFT = "11월 체육관 대관 일정 공유\n다음주 화요일(11/18) 오전 10시 점검 있음\n대관 신청은 11월 14일까지 회신해줘\n문의는 내선 1234"
PROFILE = {"user_name": "안성균", "user_dept": "체육시설사업팀", "user_phone": "042-000-1234", "user_email": ""}


@pytest.mark.parametrize("kind", list(polish.KINDS))
def test_rule_polish_keeps_every_number(kind):
    r = polish.rule_polish(DRAFT, kind, PROFILE)
    assert r["subject"] == "11월 체육관 대관 일정 공유"
    assert polish.facts_kept(DRAFT, r["subject"] + r["body"]) == []


def test_rule_polish_formats():
    mail = polish.rule_polish(DRAFT, "mail", PROFILE)["body"]
    assert mail.startswith("안녕하세요. 체육시설사업팀 안성균입니다.")
    assert "점검이 있습니다." in mail and "회신 부탁드립니다." in mail and mail.rstrip().endswith("체육시설사업팀 | 042-000-1234")
    off = polish.rule_polish(DRAFT, "official", PROFILE)["body"]
    assert off.startswith("제목: 11월 체육관 대관 일정 공유") and "  가. " in off and off.rstrip().endswith("끝.")
    rep = polish.rule_polish(DRAFT, "report", PROFILE)["body"]
    assert rep.splitlines()[0] == "□ 11월 체육관 대관 일정 공유" and " ○ 대관 신청은 11월 14일까지 회신 요청" in rep
    msg = polish.rule_polish(DRAFT, "message", PROFILE)["body"]
    assert msg.startswith("[체육시설사업팀 안성균] ") and "\n" not in msg
    with pytest.raises(ValueError):
        polish.rule_polish("  ", "mail", PROFILE)


def test_my_template_from_example_and_follow_it():
    t = polish.template_from_example("제목: [협조] 자료 요청\n안녕하세요. 체육시설사업팀 안성균입니다.\n\n{{본문}}\n\n"
                                     "감사합니다.\n안성균 드림 042-000-1234", PROFILE)
    assert t["subject"] == "[협조] 자료 요청" and "{{내부서}} {{내이름}}입니다" in t["body"] and "{{내연락처}}" in t["body"]
    v = {"내이름": "안성균", "내부서": "체육시설사업팀", "내연락처": "042-000-1234"}
    r = polish.rule_polish(DRAFT, "mail", PROFILE, t, v)
    assert r["subject"] == "[협조] 자료 요청"
    assert r["body"].startswith("안녕하세요. 체육시설사업팀 안성균입니다.\n\n다음주 화요일(11/18)")
    assert r["body"].rstrip().endswith("안성균 드림 042-000-1234")
    # 본문 자리가 없는 양식: 첫 문단(인사) 다음에 넣는다
    r2 = polish.rule_polish(DRAFT, "mail", PROFILE, {"subject": "공유", "body": "안녕하세요.\n\n감사합니다."}, v)
    assert r2["body"].splitlines()[0] == "안녕하세요." and "점검이 있습니다." in r2["body"]


class FakeAI:
    def __init__(self, body):
        self.body = body

    def chat(self, messages, model, **kw):
        return json.dumps({"subject": "체육관 대관 일정 안내", "body": self.body}, ensure_ascii=False)


def test_ai_polish_rejects_changed_numbers():
    rule = polish.rule_polish(DRAFT, "mail", PROFILE)
    good = "안녕하세요.\n11/18 오전 10시에 점검이 있습니다. 대관 신청은 11월 14일까지 회신 부탁드립니다. 문의: 내선 1234\n감사합니다."
    r = polish.ai_polish(FakeAI(good), "m", DRAFT, "mail", rule)
    assert r["subject"] == "체육관 대관 일정 안내" and "11월 14일" in r["body"]
    bad = good.replace("11월 14일", "11월 15일")                         # 날짜를 바꿈
    with pytest.raises(polish.LLMError, match="14"):
        polish.ai_polish(FakeAI(bad), "m", DRAFT, "mail", rule)


def _closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_api_polish_draft_and_template(tmp_path, monkeypatch):
    monkeypatch.setenv("SEOMU_DOWNLOADS", str(tmp_path / "dl"))
    from seomu.api import Api
    api = Api(tmp_path / "home")
    try:
        api.save_settings({"engine": "ollama", "ollama_url": f"http://127.0.0.1:{_closed_port()}", **PROFILE})
        job = api.polish_draft(DRAFT, "mail", None, None, True)
        for _ in range(100):
            st = api.job_status(job["job_id"])
            if st["status"] != "running":
                break
            time.sleep(0.05)
        assert st["status"] == "done", st["error"]
        r = st["result"]
        assert r["mode"] == "rule" and r["warning"] and r["body"].startswith("안녕하세요. 체육시설사업팀 안성균입니다.")
        t = api.template_from_example("제목: 주간 일정 공유\n안녕하세요. 체육시설사업팀 안성균입니다.\n{{본문}}\n감사합니다.")
        assert t["name"] == "주간 일정 공유" and any(x["id"] == t["id"] for x in api.list_templates()["templates"])
        with pytest.raises(ValueError):
            api.polish_draft("내용", "poem")
    finally:
        api.shutdown()

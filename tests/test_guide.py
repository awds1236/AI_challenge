"""상황 안내 (서무비서): 상황 → 규정 근거의 절차·기한 계산·서식 초안·다음 할 일."""
import json
import socket
import time
import zipfile
from datetime import date
from pathlib import Path

import pytest

from seomu import guide

ROOT = Path(__file__).resolve().parents[1]
REF = date(2026, 11, 9)          # 월요일


# ---------------------------------------------------------------- 상황 해석
@pytest.mark.parametrize("text,start,end", [
    ("다음 주 수요일부터 목요일까지 대전 출장", "2026-11-18", "2026-11-19"),
    ("11월 20일 금요일에 연가", "2026-11-20", "2026-11-20"),
    ("11/27 연가", "2026-11-27", "2026-11-27"),
    ("내일 반차 써요", "2026-11-10", "2026-11-10"),
    ("다음 달 3일 간담회 개최", "2026-12-03", "2026-12-03"),
    ("11월 18일~20일 교육 참석", "2026-11-18", "2026-11-20"),
    ("이번 주 목요일 출장", "2026-11-12", "2026-11-12"),
    ("물품 구매해야 해요", "", ""),
])
def test_parse_situation_dates(text, start, end):
    s = guide.parse_situation(text, REF)
    assert (s["start"], s["end"]) == (start, end)


def test_parse_situation_fields():
    s = guide.parse_situation("다음 주 수요일 대전으로 관외 출장, 시설 안전 워크숍 참석", REF)
    assert s["kind"] == "출장" and s["place"] == "대전" and "워크숍 참석" in s["purpose"]
    s = guide.parse_situation("프린터 토너 5개 구매해야 해요 약 30만원", REF)
    assert s["kind"] == "물품 구매" and s["item"] == "프린터 토너" and s["amount"] == 300000
    assert guide.parse_situation("독감으로 내일 쉬어야 해요", REF)["kind"] == "병가"
    assert guide.parse_situation("오늘 야근 3시간", REF)["hours"] == 3.0
    assert guide.parse_situation("점심 메뉴 추천", REF)["kind"] == ""


def test_relative_due_and_weekends():
    sit = {"start": "2026-11-16", "end": "2026-11-19", "today": "2026-11-09"}     # 월~목
    assert guide.relative_due("사용 3일 전까지 신청하여야 한다", sit) == ("2026-11-13", "3일 전까지")
    # 출발 전날이 일요일 → 금요일로 당김
    due, phrase = guide.relative_due("출발 전날까지 출장명령을 받아야 한다", sit)
    assert due == "2026-11-13" and "금요일로 당김" in phrase
    # 마친 날(목) + 3일 = 일요일 → 월요일까지 (민법 제161조)
    due, phrase = guide.relative_due("마친 날부터 3일 이내에 복명서를 보고하여야 한다", sit)
    assert due == "2026-11-23" and "월요일까지" in phrase
    assert guide.relative_due("복명서 제출 후 7일 이내에 정산을 신청한다", sit, "2026-11-23")[0] == "2026-11-30"
    assert guide.relative_due("근무 다음 날까지 입력하여야 한다", {"start": "2026-11-10", "end": "2026-11-10"})[0] == "2026-11-11"
    assert guide.relative_due("부서장의 사전 승인을 받아야 한다", {"start": "2026-11-10", "end": "2026-11-10"})[0] == "2026-11-10"
    assert guide.relative_due("출발 전날까지 받아야 한다", {"start": "", "end": ""}) == ("", "전날까지")
    assert guide.relative_due("목적을 명시하여 결재를 받는다", sit) == ("", "")


def test_not_applicable_conditions():
    five = {"start": "2026-11-16", "end": "2026-11-20", "text": ""}
    assert "해당 없음" in guide.not_applicable("병가가 연속하여 7일을 초과하는 경우 진단서를 첨부하여야 한다", five)
    eight = {"start": "2026-11-16", "end": "2026-11-23", "text": ""}
    assert guide.not_applicable("병가가 연속하여 7일을 초과하는 경우 진단서를 첨부하여야 한다", eight) == ""
    assert guide.not_applicable("관외 출장의 경우 결재를 받는다", {"text": "관내 출장"}) == "해당 없음 (관내 출장)"
    assert guide.not_applicable("추정가격 2천만원 초과 시 입찰에 부쳐야 한다", {"amount": 300000}) .startswith("해당 없음")


def test_draft_forms_fill_known_fields_and_mark_blanks():
    sit = guide.parse_situation("다음 주 수요일부터 목요일까지 대전으로 관외 출장, 시설 안전 워크숍 참석", REF)
    d = guide.draft_form("복명서", sit, "「복무 내규」 제8조(복명)")
    assert d["name"] == "출장 복명서"
    assert "2026. 11. 18.(수) ~ 2026. 11. 19.(목)" in d["body"] and "대전" in d["body"]
    assert "제8조(복명)" in d["body"] and d["blanks"] > 0
    buy = guide.draft_form("구매요구서", guide.parse_situation("프린터 토너 구매 30만원", REF))
    assert "프린터 토너" in buy["body"] and "300,000원" in buy["body"]
    assert guide.draft_form("기안문", {"text": "무언가"})["name"] == "기안문"


# ---------------------------------------------------------------- 규정 저장소를 쓰는 전체 흐름 (AI 없음)
def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SEOMU_DOWNLOADS", str(tmp_path / "dl"))
    from seomu.api import Api
    a = Api(tmp_path / "home")
    # AI 없음: 꺼진 Ollama 주소 → 규칙만으로 안내해야 한다
    a.save_settings({"engine": "ollama", "ollama_url": f"http://127.0.0.1:{_closed_port()}",
                     "regulation_dirs": [str(ROOT / "sample_data" / "regulations")]})
    a._rag.reindex(True)
    yield a
    a.shutdown()


def wait(a, job):
    for _ in range(400):
        st = a.job_status(job["job_id"])
        if st["status"] != "running":
            assert st["status"] == "done", st["error"]
            return st["result"]
        time.sleep(0.05)
    raise TimeoutError


def _guide(api, text, monkeypatch):
    real = guide.parse_situation
    monkeypatch.setattr(guide, "parse_situation", lambda t, ref=None: real(t, REF))
    return wait(api, api.guide(text))


def test_trip_guide_end_to_end(api, monkeypatch):
    r = _guide(api, "다음 주 수요일부터 목요일까지 대전으로 관외 출장 가요, 시설 안전 워크숍 참석", monkeypatch)
    assert r["mode"] == "rule" and r["situation"]["kind"] == "출장"
    # 수(11/18)~목(11/19): 출발 전날 11/17, 마친 날+3일=일요일 → 월요일 11/23, 복명서 제출 후 7일 → 11/30
    assert [s["due"] for s in r["steps"]] == ["2026-11-17", "", "2026-11-23", "2026-11-30"]
    assert all("제7조" in s["basis"] or "제8조" in s["basis"] for s in r["steps"])       # 연가·물품 조문이 섞이지 않는다
    assert {"영수증", "교통비 내역"} <= set(r["prep"])
    names = [f["name"] for f in r["forms"]]
    assert set(names) == {"출장 복명서", "출장 신청(출장명령 요청)"}
    apply_form = next(f for f in r["forms"] if f["name"].startswith("출장 신청"))
    assert "제7조(출장 신청)" in apply_form["body"]                     # 근거 조문이 초안에 들어간다
    # 준비 서류는 출발 전이 아니라 여비 정산 때
    prep_task = next(t for t in r["tasks"] if t["title"].startswith("준비 서류"))
    assert prep_task["due"] == "2026-11-30"
    # 관외 출장 결재(기한 없음)는 같은 조문의 기한(출장명령 전날)을 이어받는다
    assert next(t for t in r["tasks"] if "관외" in t["title"])["due"] == "2026-11-17"
    # 기록 → 다시 열기 → 할 일 등록(중복 방지) → 삭제
    hist = api.guide_history()
    assert hist[0]["id"] == r["id"] and hist[0]["kind"] == "출장"
    assert api.get_guide(r["id"])["steps"] == r["steps"]
    assert api.guide_add_tasks(r["tasks"])["added"] == len(r["tasks"])
    assert api.guide_add_tasks(r["tasks"])["added"] == 0
    titles = {t["title"]: t["due"] for t in api.list_tasks()}
    assert titles[r["tasks"][0]["title"]] == (r["tasks"][0]["due"] or None)
    api.delete_guide(r["id"])
    assert api.guide_history() == []


def test_leave_guide_late_and_unrelated_articles(api, monkeypatch):
    r = _guide(api, "11월 10일 연가 쓰려고 해요", monkeypatch)
    assert r["situation"]["kind"] == "연가"
    assert all("제5조" in s["basis"] for s in r["steps"])               # 같은 장의 병가(진단서)는 섞이지 않는다
    assert r["steps"][0]["late"] and "부득이한" in r["notice"]          # 3일 전 기한이 이미 지났다
    assert "진단서" not in r["prep"]


def test_sick_leave_condition_not_applicable(api, monkeypatch):
    r = _guide(api, "독감으로 다음 주 월요일부터 금요일까지 쉬어야 해요", monkeypatch)
    assert r["situation"]["kind"] == "병가"
    assert r["steps"] and all(s["skip"] for s in r["steps"])            # 5일 병가: '7일 초과 시 진단서' 해당 없음
    assert r["prep"] == [] and "해당하지 않습니다" in r["summary"]
    assert [f["name"] for f in r["forms"]] == ["병가 신청"]


def test_purchase_and_overtime(api, monkeypatch):
    r = _guide(api, "프린터 토너 5개 구매해야 해요, 약 30만원", monkeypatch)
    assert "구매요구서" in r["steps"][0]["title"] and "견적서" in r["prep"]
    assert any("수의계약" in c["text"] for c in r["checks"])
    assert {"구매요구서", "예산 집행 품의서"} <= {f["name"] for f in r["forms"]}
    assert "날짜" not in (r.get("notice") or "")                       # 기한 표현이 없는 절차는 날짜 경고를 하지 않는다
    r = _guide(api, "오늘 시간외근무 3시간 해야 해요", monkeypatch)
    assert [s["due"] for s in r["steps"]] == ["2026-11-09", "2026-11-10"]
    assert any("57시간" in c["text"] for c in r["checks"])
    assert "18:00 ~ 21:00 (3시간)" in r["forms"][0]["body"]


def test_no_regulation_for_situation(api, monkeypatch):
    r = _guide(api, "다음 달 3일 부서 간담회 개최", monkeypatch)
    assert r["steps"] == [] and r["sources"] == []                     # 엉뚱한 조문을 절차로 보여 주지 않는다
    assert "찾지 못했습니다" in r["summary"]
    assert r["forms"][0]["name"] == "개최 계획(기안)" and "2026. 12. 3.(목)" in r["forms"][0]["body"]
    assert r["tasks"] and r["tasks"][0]["due"] == ""                   # 근거 없는 기한은 만들지 않는다
    with pytest.raises(ValueError):
        api.guide(" ")


def test_save_guide_form_txt_and_hwpx(api, tmp_path):
    body = "출장 복명서\n\n1. 출장 기간: 2026. 11. 18.(수)\n2. 출장지: 대전\n3. 주요 내용\n  가. 워크숍 참석"
    t = api.save_guide_form("출장 복명서", body, "txt")
    assert Path(t["path"]).read_text(encoding="utf-8").startswith("출장 복명서")
    h = api.save_guide_form("출장 복명서", body, "hwpx")
    assert h["path"].endswith(".hwpx")
    with zipfile.ZipFile(h["path"]) as z:
        xml = "".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))
    assert "대전" in xml
    with pytest.raises(ValueError):
        api.save_guide_form("x", "  ")


# ---------------------------------------------------------------- AI 보완 (가짜 모델)
class FakeClient:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def chat(self, messages, model, **kw):
        self.calls += 1
        return self.reply(messages) if callable(self.reply) else self.reply


def _search_sample():
    from seomu.rag import Hit
    text = (ROOT / "sample_data" / "regulations").glob("*.txt").__next__().read_text(encoding="utf-8")
    art7 = text[text.index("제7조"):text.index("제8조")].strip()
    art8 = text[text.index("제8조"):text.index("제5장")].strip()
    hits = [Hit(1, "복무 내규", "제4장 출장 > 제7조(출장 신청)", art7, "x", "내규", 2.0),
            Hit(2, "복무 내규", "제4장 출장 > 제8조(복명)", art8, "x", "내규", 1.5)]
    return lambda q: hits


def test_ai_polish_keeps_rule_dates():
    def reply(messages):
        rule = json.loads(messages[-1]["content"].split("[규칙 분석]\n", 1)[1])
        forms = [{"name": f["name"], "body": f["body"] + "\n(AI 보완: 워크숍 자료 지참)"} for f in rule["forms"]]
        forms.append({"name": "없는 서식", "body": "무시돼야 함"})
        forms[0]["body"] = forms[0]["body"].replace("2026. 11. 18.", "2026. 12. 25.")     # 날짜를 바꾼 초안은 버린다
        return json.dumps({"summary": "대전 출장: 전날까지 출장명령, 복귀 후 3일 안에 복명서를 내세요.",
                           "forms": forms, "tips": ["여비 영수증을 모아 두세요", "", 3]}, ensure_ascii=False)
    c = FakeClient(reply)
    r = guide.make_guide("다음 주 수요일 대전으로 관외 출장", _search_sample(), c, "m", ref=REF)
    assert c.calls == 1 and r["mode"] == "llm"
    assert r["summary"].startswith("대전 출장")
    assert r["tips"] == ["여비 영수증을 모아 두세요"]
    assert "AI 보완" not in r["forms"][0]["body"] and "AI 보완" in r["forms"][1]["body"]
    assert [s["due"] for s in r["steps"]][0] == "2026-11-17"            # 날짜는 규칙 계산 그대로


def test_ai_failure_falls_back_to_rule():
    r = guide.make_guide("다음 주 수요일 대전으로 출장", _search_sample(), FakeClient("이건 JSON이 아님"), "m", ref=REF)
    assert r["mode"] == "rule" and r["ai_error"] and r["steps"]
    with pytest.raises(ValueError):
        guide.make_guide("", _search_sample())


def test_after_trip_settlement_like_contest_example(api, monkeypatch):
    """공고문 예시 '출장 다녀와서 정산해야 해요': 출발 전 절차는 지난 단계로, 복명서·정산 기한은 날짜로."""
    r = _guide(api, "출장 다녀와서 정산해야 해요", monkeypatch)
    sit = r["situation"]
    assert sit["phase"] == "after" and sit["end"] == "2026-11-09" and "오늘 마친 것으로" in r["notice"]
    assert r["summary"].startswith("출장 후속 처리")
    live = [s for s in r["steps"] if not s["skip"]]
    assert [s["due"] for s in live] == ["2026-11-12", "2026-11-19"]          # 복명서 3일, 정산 7일
    assert all("이미 지난 단계" in s["skip"] for s in r["steps"] if "제7조" in s["basis"])
    assert [f["name"] for f in r["forms"]] == ["출장 복명서"]                 # 출장 신청서는 내지 않는다
    assert not any("출장명령" in t["title"] for t in r["tasks"])
    r = _guide(api, "어제까지 대전 출장 다녀왔는데 정산해야 해요", monkeypatch)
    assert r["situation"]["end"] == "2026-11-08" and not r.get("notice", "").startswith("오늘")
    assert guide.parse_situation("지난주 목요일에 출장 다녀왔어요", REF)["start"] == "2026-11-05"
    assert guide.parse_situation("그저께 행사 끝났어요", REF)["start"] == "2026-11-07"

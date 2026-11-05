"""보고서 양식(HWPX) 채우기와 AI 속도 최적화 관련 테스트."""
import io
import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("lxml")
from lxml import etree  # noqa: E402

from seomu import report as rp  # noqa: E402
from seomu.analyzer import SCHEMA, ai_schema, analyze  # noqa: E402
from seomu.collector import iri_to_uri  # noqa: E402
from seomu.llm import OllamaClient  # noqa: E402
from seomu.rag import RAGEngine  # noqa: E402

TPL = rp.builtin_template()
OUTLINE = {
    "title": "청렴 교육 참여 계획 보고",
    "summary": "11. 13.까지 참가신청서를 제출하고자 함",
    "sections": [
        {"heading": "추진 배경", "items": [
            {"head": "요청 기관", "text": "감사관 청렴 교육 참여 요청",
             "subs": [{"head": "관련", "text": "감사관-1234"}], "notes": ["부서별 2명 이상"]},
            {"head": "", "text": "○ 기호를 또 붙인 항목"}]},
        {"heading": "제출 기한", "items": [{"head": "제출물", "text": "참가신청서"}],
         "table": [["기한", "할 일"], ["11. 13.", "신청서 제출"], ["11. 20.", "교육 참석"], ["11. 27.", "결과 회신"]]},
    ],
}


def _section(data: bytes):
    z = zipfile.ZipFile(io.BytesIO(data))
    return z, etree.fromstring(z.read(rp.SECTION))


def _L(e):
    return etree.QName(e.tag).localname if isinstance(e.tag, str) else ""


def test_builtin_template_structure():
    t = rp.load_template(TPL)
    info = t.info()
    assert {0, 1, 2, 9} <= set(info["levels"])
    assert info["title_box"] and info["summary_box"] and info["has_table"]
    assert info["headings"] == ["추진 배경", "주요 내용", "향후 계획"]
    assert t.protos[1].has_head and t.protos[1].cp_head != t.protos[1].cp_body   # 소제목은 굵게


def test_fill_keeps_format_and_writes_content():
    t = rp.load_template(TPL)
    data = rp.fill(t, OUTLINE, dept="총무과", today=date(2026, 11, 5))
    z, sec = _section(data)
    assert z.namelist()[0] == "mimetype" and z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
    text = "\n".join("".join(p.itertext()) for p in sec if _L(p) == "p")
    assert "[총무과] 청렴 교육 참여 계획 보고" in text
    assert "▹ 11. 13.까지 참가신청서를 제출하고자 함" in text          # 요약 상자의 장식 기호 유지
    assert " ○ (요청 기관) 감사관 청렴 교육 참여 요청" in text
    assert "   - (관련) 감사관-1234" in text and "※ 부서별 2명 이상" in text
    assert "○ ○" not in text                                          # 중복 기호 제거
    assert "향후 계획" not in text and "항목 내용" not in text          # 양식 예시 문구는 사라짐
    tbl = next(x for x in sec.iter() if _L(x) == "tbl" and x.get("colCnt") == "2")
    assert tbl.get("rowCnt") == "4"                                    # 3행 양식 → 4행
    rows = [x.get("rowAddr") for x in tbl.iter() if _L(x) == "cellAddr"]
    assert rows == ["0", "0", "1", "1", "2", "2", "3", "3"]
    # 글자를 바꾼 문단에는 줄 배치 캐시가 없어야 한다 (남으면 한글에서 글자가 겹친다)
    for p in sec.iter():
        if _L(p) == "p" and "".join(p.itertext()).strip():
            assert not any(_L(c) == "linesegarray" for c in p), "".join(p.itertext())[:30]
    assert "청렴 교육" in z.read("Preview/PrvText.txt").decode("utf-8")


def test_template_without_header_and_unknown_levels(tmp_path):
    """머리 상자 없이 □로 시작하는 양식, 양식에 없는 수준(-, ※)도 처리."""
    t = rp.load_template(TPL)
    sec = t.sec
    kids = [c for c in sec if _L(c) == "p"]
    first_heading = next(i for i, p in enumerate(kids) if rp._own_text(p).startswith("□"))
    # 첫 문단(구역 정의)에 □ 글자를 넣어 머리 없는 양식을 흉내 낸다
    for p in kids[1:first_heading + 1]:
        sec.remove(p)
    run = kids[0].find("{*}run")
    t_el = etree.SubElement(run, run.tag.replace("run", "t"))
    t_el.text = "□ 개요"
    for p in [p for p in sec if _L(p) == "p" and rp._own_text(p).lstrip().startswith(("-", "※"))]:
        sec.remove(p)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in t.order:
            z.writestr(n, etree.tostring(t.tree, xml_declaration=True, encoding="UTF-8") if n == rp.SECTION else t.files[n])
    path = tmp_path / "머리없음.hwpx"
    path.write_bytes(buf.getvalue())
    t2 = rp.load_template(path)
    assert not t2.boxes and set(t2.protos) >= {0, 1}
    _, sec2 = _section(rp.fill(t2, OUTLINE))
    assert any(_L(x) == "secPr" for x in sec2.iter())                  # 구역 정의는 남는다
    text = "\n".join("".join(p.itertext()) for p in sec2 if _L(p) == "p")
    assert "(관련) 감사관-1234" in text and "※ 부서별 2명 이상" in text


def test_bad_templates(tmp_path):
    (tmp_path / "a.hwp").write_bytes(b"x")
    with pytest.raises(rp.ReportError, match="HWPX"):
        rp.load_template(tmp_path / "a.hwp")
    (tmp_path / "b.hwpx").write_bytes(b"not a zip")
    with pytest.raises(rp.ReportError):
        rp.load_template(tmp_path / "b.hwpx")


def test_outline_from_notice_and_text():
    notice = {"title": "청렴 교육 참여 요청", "body": "", "analysis": {
        "folder_name": "청렴 교육 참여 요청", "summary": "요약",
        "event": {"name": "청렴 교육", "date": "11. 20."}, "contact": "감사관 031-000-0000",
        "deadlines": [{"date": "2026-11-13", "time": "18:00", "what": "신청서 제출"},
                      {"date": "2026-11-27", "time": "", "what": "결과 회신"}],
        "submissions": [{"item": "참가신청서", "how": "전자우편", "to": "감사관"}],
        "actions": ["참석자 파악", "신청서 제출"]}}
    o = rp.outline_from_notice(notice)
    assert o["title"] == "청렴 교육 참여 요청 관련 보고"
    heads = [s["heading"] for s in o["sections"]]
    assert heads == ["개요", "제출 기한 및 제출물", "조치 계획"]
    assert o["sections"][1]["table"][1] == ["11. 13.(금) 18:00", "신청서 제출"]
    o2 = rp.outline_from_text("주간 업무 보고\n1. 회의 개최\n- 예산 집행 점검", "")
    assert o2["title"] == "주간 업무 보고"
    assert [i["text"] for i in o2["sections"][0]["items"]] == ["회의 개최", "예산 집행 점검"]


def test_api_make_report_rule_based(tmp_path, monkeypatch):
    monkeypatch.setenv("SEOMU_DOWNLOADS", str(tmp_path / "dl"))
    from seomu.api import Api
    api = Api(tmp_path / "home")
    api.save_settings({"engine": "ollama", "ollama_url": "http://127.0.0.1:9"})   # AI 없음 → 규칙 기반
    assert any(t["builtin"] and t["ok"] for t in api.report_templates()["templates"])
    res = api.add_report_templates([str(TPL), str(tmp_path / "없음.hwpx")])
    assert res["errors"] and len([t for t in res["templates"] if t["name"] == TPL.stem]) == 1
    with pytest.raises(ValueError):
        api.make_report(TPL.stem)
    job = api.make_report(TPL.stem, None, "주간 업무 보고\n회의 개최\n예산 점검", "주간 업무 보고", True)
    import time
    for _ in range(100):
        st = api.job_status(job["job_id"])
        if st["status"] != "running":
            break
        time.sleep(0.05)
    assert st["status"] == "done", st
    r = st["result"]
    assert r["mode"] == "rule" and r["llm_error"] and Path(r["path"]).exists()
    assert "□ 주요 내용" in r["preview"]
    api.shutdown()


# ---------------------------------------------------------------- 속도 최적화
def test_ai_schema_skips_fields_rules_already_found():
    assert set(ai_schema({})["properties"]) == set(SCHEMA["properties"])
    s = ai_schema({"contact": "감사관", "event": {"name": "교육", "date": "11. 20."}})
    assert "contact" not in s["properties"] and "event" not in s["properties"]
    assert set(s["required"]) <= set(s["properties"])


def test_analyze_prompt_is_cache_friendly():
    calls = []

    class C:
        def pick_chat_model(self, c=""):
            return "m"

        def chat(self, messages, model, **kw):
            calls.append((messages, kw))
            return json.dumps({"folder_name": "청렴 교육", "summary": "요약", "deadlines": [], "submissions": [], "actions": []})
    body = "1. 행사명: 청렴 교육\n2. 제출 기한: 2026. 11. 13.(금)까지\n3. 문의처: 감사관(031-000-0000)"
    analyze("청렴 교육", body, [], C(), "m", 8192, date(2026, 11, 5))
    analyze("다른 공문", body.replace("13", "20"), [], C(), "m", 8192, date(2026, 11, 6))
    (m1, kw1), (m2, _) = calls
    assert m1[0]["role"] == "system" and m1[0]["content"] == m2[0]["content"]   # 고정 지시문 → 캐시 재사용
    assert "2026-11-05" not in m1[0]["content"] and "2026-11-05" in m1[1]["content"]
    assert kw1["max_tokens"] <= 800 and kw1["num_ctx"] == 8192


def test_rag_context_budget_keeps_relevant_lines():
    long = "제8조(복명) ① 출장자는 출장을 마친 날부터 5일 이내에 복명서를 제출하여야 한다.\n" + \
           "\n".join(f"② 관련 없는 내용 {i} " + "가나다 " * 40 + "한다." for i in range(30)) + \
           "\n⑨ 복명서에는 출장 결과를 적는다."
    ex = RAGEngine.excerpt(long, "복명서 언제까지 제출", 600)
    assert len(ex) <= 650 and "5일 이내" in ex and "복명서에는" in ex and "…" in ex
    assert RAGEngine.excerpt("짧은 조문", "질문", 600) == "짧은 조문"


def test_ollama_uses_one_context_size_and_no_thinking(monkeypatch):
    sent = []
    c = OllamaClient(num_ctx=8192)
    monkeypatch.setattr(c, "_json", lambda path, payload=None, timeout=None: sent.append(payload) or {"message": {"content": "ok"}})
    c.preload("gemma4")
    c.chat([{"role": "user", "content": "x"}], "gemma4", num_ctx=6144, max_tokens=300)
    assert sent[0]["options"]["num_ctx"] == 8192 and sent[1]["options"]["num_ctx"] == 8192   # 다시 불러오기 방지
    assert sent[1]["options"]["num_predict"] == 300 and sent[1]["think"] is False


def test_ollama_retries_without_think_on_old_versions(monkeypatch):
    from seomu.llm import LLMError
    sent = []
    c = OllamaClient()

    def fake(path, payload=None, timeout=None):
        sent.append(dict(payload))
        if "think" in payload:
            raise LLMError('Ollama 오류 400: {"error":"\\"m\\" does not support thinking"}')
        return {"message": {"content": "ok"}}
    monkeypatch.setattr(c, "_json", fake)
    assert c.chat([{"role": "user", "content": "x"}], "m") == "ok" and "think" not in sent[-1]


def test_iri_to_uri_encodes_korean_paths():
    u = iri_to_uri("http://127.0.0.1:8765/files/참가신청서.hwp?name=붙임 1&x=%20")
    assert u.isascii() and "%EC%B0%B8" in u and u.endswith("x=%20")
    assert iri_to_uri("https://a.go.kr/x.do?id=1&b=2") == "https://a.go.kr/x.do?id=1&b=2"


def test_engine_speed_args_only_when_supported(tmp_path, monkeypatch):
    from seomu.engine import LocalEngine
    e = LocalEngine(tmp_path)
    monkeypatch.setattr(e, "_help", lambda server: "")
    assert e._speed_args("x", "chat", 8192) == []                       # 옛 엔진: 아무 옵션도 붙이지 않음
    monkeypatch.setattr(e, "_help", lambda server: "--cache-reuse N\n--ubatch-size N\n--no-webui")
    assert e._speed_args("x", "chat", 8192) == ["--cache-reuse", "256", "--no-webui"]
    assert e._speed_args("x", "embed", 2048)[:4] == ["-b", "2048", "-ub", "2048"]

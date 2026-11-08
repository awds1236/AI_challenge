import zipfile
from datetime import date
from pathlib import Path

import pytest

from seomu.analyzer import analyze, rule_analysis
from seomu.collector import analyze_html, collect_from_files, filename_from_headers, safe_name
from seomu.deadlines import best_deadlines, find_dates, find_submissions
from seomu.llm import LLMError, OllamaClient, extract_json, is_loopback_url
from seomu.mail import build_variables, clean_polished, render, tasks_to_ics
from seomu.parsers import html_to_text, parse_file
from seomu.rag import Index, chunk_document, tokenize

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / "sample_data" / "regulations" / "예시_○○시_복무_내규.txt"
NOTICE = ROOT / "sample_data" / "notice" / "예시_공문.html"
REF = date(2026, 11, 4)


def test_loopback_policy():
    assert is_loopback_url("http://127.0.0.1:11434")
    assert is_loopback_url("http://localhost:11434")
    assert is_loopback_url("http://[::1]:11434")
    assert not is_loopback_url("http://10.0.0.5:11434")
    assert not is_loopback_url("https://api.example.com")
    with pytest.raises(LLMError):
        OllamaClient("http://203.0.113.1:11434").list_models()


def test_extract_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json("설명 {\"b\": [1,2]} 끝") == {"b": [1, 2]}


def test_dates_and_deadlines():
    text = ("시행일자 2026. 11. 3.\n가. 제출 기한: 2026. 11. 13.(금) 18:00까지\n"
            "나. 일시: 11. 20.(금) 14:00\n결과 보고는 '26.12.1.까지 회신\n신청자 목록을 공문 제출(11.11까지)")
    ds = find_dates(text, REF)
    iso = [d["date"] for d in ds]
    assert "2026-11-13" in iso and "2026-11-20" in iso and "2026-12-01" in iso and "2026-11-11" in iso
    best = [d["date"] for d in best_deadlines(text, REF)]
    assert best == ["2026-11-11", "2026-11-13", "2026-12-01"]
    t13 = next(d for d in ds if d["date"] == "2026-11-13")
    assert t13["time"] == "18:00"


def test_year_rollover_and_range():
    ds = find_dates("1월 5일까지 제출", date(2026, 11, 20))
    assert ds[0]["date"] == "2027-01-05"
    ds = find_dates("심사 11. 13. ~ 17.", REF)
    assert ds[0]["end_date"] == "2026-11-17"


def test_submissions():
    text = "제출 서류: 참가 신청서 1부 제출\n붙임 1. 참가 신청서 1부.\n2. 행사 안내문 1부. 끝."
    subs = find_submissions(text)
    assert "[붙임] 참가 신청서" in subs and "[붙임] 행사 안내문" in subs


def test_chunk_by_article_and_search():
    text = parse_file(REG)
    chunks = chunk_document(text, REG.stem)
    heads = [c["heading"] for c in chunks]
    assert any("제5조(연가)" in h for h in heads)
    assert any(h.startswith("제4장") and "제8조(복명)" in h for h in heads)
    rows = [{"id": i, "tokens": " ".join(c["tokens"]), "title": REG.stem, "heading": c["heading"],
             "text": c["text"], "path": str(REG), "category": "내규", "embedding": None}
            for i, c in enumerate(chunks)]
    idx = Index(rows)
    hit = idx.search("출장 다녀와서 복명서는 언제까지 내야 하나요?", 3)[0]
    assert "제8조" in hit.heading
    hit = idx.search("연가를 쓰려면 며칠 전에 신청해?", 3)[0]
    assert "제5조" in hit.heading


def test_tokenize_josa():
    toks = tokenize("연가를 신청하려면")
    assert "연가" in toks


def test_hwpx_and_docx(tmp_path):
    hwpx = tmp_path / "a.hwpx"
    with zipfile.ZipFile(hwpx, "w") as z:
        z.writestr("Contents/section0.xml",
                   '<hs:sec xmlns:hs="h" xmlns:hp="p"><hp:p><hp:run><hp:t>제1조(목적)</hp:t></hp:run></hp:p>'
                   '<hp:p><hp:run><hp:t>둘째 줄</hp:t></hp:run></hp:p></hs:sec>')
    assert parse_file(hwpx) == "제1조(목적)\n둘째 줄"
    docx = tmp_path / "b.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml",
                   '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>안녕</w:t></w:r></w:p>'
                   '<w:p><w:r><w:t>하세요</w:t></w:r></w:p></w:body></w:document>')
    assert parse_file(docx) == "안녕\n하세요"


def test_html_notice_analysis():
    info = analyze_html(NOTICE.read_text(encoding="utf-8"), "http://intra.example/doc/1")
    assert info["title"] == "2026년 ○○시 청렴 교육 행사 참여 요청"
    names = [a["name"] for a in info["attachments"]]
    assert "참가신청서.hwp" in names and "행사안내문.pdf" in names
    a = rule_analysis(info["title"], info["text"], [], REF)
    assert a["deadlines"][0]["date"] == "2026-11-13"
    assert a["deadlines"][0]["time"] == "18:00"


def test_collect_from_files(tmp_path):
    files = [str(NOTICE), str(NOTICE.parent / "files" / "참가신청서.txt")]
    cap = collect_from_files(files, tmp_path)
    assert cap.folder.name.endswith("2026년 ○○시 청렴 교육 행사 참여 요청")
    assert (cap.folder / "본문.txt").exists()
    assert (cap.folder / "붙임" / "참가신청서.txt").exists()
    res = analyze(cap.title, cap.text, cap.files, None, ref=REF)
    assert res["mode"] == "rule" and res["deadlines"]


def test_filename_headers():
    assert filename_from_headers("attachment; filename*=UTF-8''%EC%8B%A0%EC%B2%AD%EC%84%9C.hwp", "http://x/d") == "신청서.hwp"
    raw = "신청서.hwp".encode("utf-8").decode("latin-1")
    assert filename_from_headers(f'attachment; filename="{raw}"', "http://x/d") == "신청서.hwp"
    assert safe_name('a/b:c*?"<>|') == "a_b_c______"


def test_mail_render():
    class S:
        user_name, user_dept, user_phone, user_email = "홍길동", "총무과", "02-1", ""
    notice = {"title": "청렴 교육", "analysis": {
        "summary": "요약", "deadlines": [{"date": "2026-11-13", "time": "18:00", "what": "회신"}],
        "submissions": [{"item": "참가 신청서"}], "event": {"name": "청렴 교육"}, "contact": "청렴팀"}}
    v = build_variables(notice, S(), REF)
    assert v["제출기한"] == "2026. 11. 13.(금)" and v["디데이"] == "D-9"
    out, missing = render("{{공문제목}} {{제출기한_전체}} {{내메일}}", v)
    assert out == "청렴 교육 2026. 11. 13.(금) 18:00까지 [내메일]"
    assert missing == ["내메일"]
    # 중괄호를 한 겹만 쓴 변수도 채우고, 모르는 이름은 [빈칸]으로 표시해 알려 준다
    out, missing = render("{내이름} 드림, {공문제목}과 {내메일} {담당자} {x}", v)
    assert out == "홍길동 드림, 청렴 교육과 [내메일] [담당자] {x}" and missing == ["내메일", "담당자"]
    # AI 다듬기가 문장 속에 지어 넣은 빈칸(+조사)은 지우고, 초안에 있던 빈칸은 남긴다
    draft = "[담당자]님 안녕하세요.\n[기한]까지 제출 바랍니다.\n홍길동 드림"
    polished = "[담당자]님께,\n\n[서류명]을 [기한]까지 제출하여 주시기 바랍니다.\n\n홍길동 드림"
    assert clean_polished(polished, draft) == "[담당자]님께,\n\n[기한]까지 제출하여 주시기 바랍니다.\n\n홍길동 드림"
    # 메일은 서식 없는 글: 마크다운 굵게·제목 기호는 지운다
    md = "## 안내\n**■ 제출 기한:** 2026. 11. 20.까지\n__■ 제출 자료__: 결과 확인서\n홍길동 드림"
    assert clean_polished(md, "■ 제출 기한: 2026. 11. 20.까지\n■ 제출 자료: 결과 확인서\n홍길동 드림") == \
        "안내\n■ 제출 기한: 2026. 11. 20.까지\n■ 제출 자료: 결과 확인서\n홍길동 드림"
    ics = tasks_to_ics([{"id": 1, "title": "제출; 확인", "due": "2026-11-13", "done": 0}])
    assert "DTSTART;VALUE=DATE:20261113" in ics and "제출\\; 확인" in ics


def test_html_to_text_skips_script():
    assert html_to_text("<p>a</p><script>x()</script><p>b</p>") == "a\n\nb"


def test_recommend_by_spec():
    from seomu.models import recommend
    r = recommend({"ram_total_gb": 16, "ram_avail_gb": 2.9, "gpu_usable": False})
    assert r["model"] == "gemma4:e2b-it-qat" and r["warn"]          # 여유 메모리가 순간적으로 적어도 E2B
    assert recommend({"ram_total_gb": 16, "ram_avail_gb": 10, "gpu_usable": False})["model"] == "gemma4:e2b-it-qat"
    assert recommend({"ram_total_gb": 32, "ram_avail_gb": 20, "gpu_usable": False})["model"] == "gemma4:e4b-it-qat"
    assert recommend({"ram_total_gb": 8, "ram_avail_gb": 3, "gpu_usable": False})["model"] == "gemma4:e2b-it-qat"
    assert recommend({"ram_total_gb": 6, "ram_avail_gb": 3, "gpu_usable": False})["model"] == "kanana-2:3b"
    assert recommend({"ram_total_gb": 4, "ram_avail_gb": 2, "gpu_usable": False})["model"] == "kanana-2:1.3b"


def test_model_family_alias():
    from seomu.models import find, installed_id, is_installed
    e2b = find("gemma4:e2b-it-qat")
    assert installed_id(e2b, ["gemma4:e2b", "embeddinggemma:latest"]) == "gemma4:e2b"
    assert installed_id(e2b, ["gemma4:e2b", "gemma4:e2b-it-qat"]) == "gemma4:e2b-it-qat"
    assert is_installed("embeddinggemma", ["embeddinggemma:latest"])
    assert not is_installed("gemma4:e4b-it-qat", ["gemma4:e2b"])


def test_file_watcher(tmp_path):
    import time as _t
    from seomu.winwindow import FileWatcher
    src, dest = tmp_path / "Desktop", tmp_path / "notice" / "붙임"
    src.mkdir()
    (src / "old.pdf").write_bytes(b"old")
    w = FileWatcher([src], dest)
    (src / "새 붙임.hwpx").write_bytes(b"x" * 10)
    (src / "download.crdownload").write_bytes(b"x")
    (src / "memo.exe").write_bytes(b"x")
    assert w.poll() == []            # 첫 확인: 크기 안정 대기
    _t.sleep(1.1)
    got = w.poll()
    assert [g["name"] for g in got] == ["새 붙임.hwpx"]
    assert (dest / "새 붙임.hwpx").exists() and (src / "새 붙임.hwpx").exists()   # 바탕화면 파일은 복사
    _t.sleep(1.1)
    assert w.poll() == []            # 같은 파일 중복 수집 안 함


def test_png_writer(tmp_path):
    from seomu.winwindow import _png
    p = tmp_path / "a.png"
    _png(p, 2, 1, bytes([0, 0, 255, 255, 255, 0, 0, 255]))
    assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_trim_body_keeps_deadline_lines():
    from seomu.analyzer import trim_body
    body = "\n".join(["본문 내용 " * 20] * 40) + "\n제출 기한: 2026. 12. 1.까지 회신"
    out = trim_body(body, 3000)
    assert len(out) <= 3100 and "2026. 12. 1.까지" in out


NOTICE_SURVEY = """행복한 구민, 신뢰받는 공기업!

○○시설관리공단


수 신
수신자 참조
(경유)

제 목
공공체육시설 문화체육프로그램 추첨제 현황 조사 협조 요청
1. 귀 기관의 무궁한 발전을 기원합니다.

2. 공공체육시설 수강신청 제도의 공정성 제고를 위한 검토자료로 활용하고자 다음과 같이 문화체육프로그램 수강신청 운영현황을 조사하오니 협조하여 주시기 바랍니다.

  가. 조 사 명 : 공공체육시설 문화체육프로그램 추첨제 운영현황 조사
  나. 대    상 : 공공체육시설 문화체육프로그램 운영기관
  라. 회신자료 : 붙임 조사표 1부
  마. 회신기한 : 2026. 11. 13.(금)
  바. 회신방법 : 공문 또는 담당자 이메일(contact@example.go.kr)

3. 조사 결과는 회신 기관과 공유할 예정이오니 적극적인 협조를 부탁드립니다.

첨부  공공체육시설 문화체육프로그램 추첨제 현황 조사표 1부.  끝.


○○시설관리공단이사장
"""


def test_rule_analysis_skips_boilerplate():
    from seomu.analyzer import rule_analysis
    a = rule_analysis("공공체육시설 문화체육프로그램 추첨제 현황 조사 협조 요청", NOTICE_SURVEY, [], REF)
    # 요약: 목적절·공문 어미를 걷어낸 '무엇을 — 무엇을 해 달라 (언제까지)' 한 줄 + 대상
    assert a["summary"].startswith("문화체육프로그램 수강신청 운영현황 조사 — 협조 요청 (11월 13일(금)까지)")
    assert "행복한" not in a["summary"] and "무궁한 발전" not in a["summary"]
    assert "하오니" not in a["summary"] and "활용하고자" not in a["summary"]
    assert "대상 공공체육시설" in a["summary"]
    assert a["deadlines"] == [{"date": "2026-11-13", "time": "", "what": "조사표 회신", "source": "규칙"}]
    assert len(a["submissions"]) == 1
    assert a["submissions"][0]["item"] == "공공체육시설 문화체육프로그램 추첨제 현황 조사표 (붙임 서식)"
    assert a["submissions"][0]["how"].startswith("공문 또는 담당자 이메일")
    assert a["actions"][0] == "조사표 회신 (11/13까지)"


def test_expected_attachments_and_matching():
    from seomu.attach import expected_attachments, match_files, name_score, path_from_title
    assert expected_attachments(NOTICE_SURVEY) == ["공공체육시설 문화체육프로그램 추첨제 현황 조사표"]
    body = "붙임  1. 과업지시서(샘플) 및 모델가이드라인 체크리스트 각 1부.\n      2. 계약심의위원회 운영 내규 1부.  끝."
    exp = expected_attachments(body)
    assert exp == ["과업지시서(샘플) 및 모델가이드라인 체크리스트", "계약심의위원회 운영 내규"]
    assert name_score(exp[0], "과업지시...") >= 0.8                       # 화면에 잘려 보이는 이름
    assert name_score(exp[1], "(붙임2) 계약심의위원회 운영 내규 (1).hwpx") == 1.0
    files = [{"name": "회의록.hwp", "path": "a", "mtime": 3}, {"name": "계약심의위원회 운영 내규.hwpx", "path": "b", "mtime": 2},
             {"name": "1.과업지시서(샘플) 및 모델가이드라인 체크리스트.hwp", "path": "c", "mtime": 1}]
    m = match_files(exp, files)
    assert m[exp[0]]["path"] == "c" and m[exp[1]]["path"] == "b"
    assert path_from_title("(붙임1) 안내서.hwpx [C:\\\\Users\\\\u\\\\Downloads\\\\] - 한글") == "C:\\\\Users\\\\u\\\\Downloads\\\\(붙임1) 안내서.hwpx"


def test_candidate_files(tmp_path):
    import time as _t
    from seomu.attach import candidate_files
    (tmp_path / "cache" / "sub").mkdir(parents=True)
    (tmp_path / "cache" / "sub" / "조사표.hwp").write_bytes(b"x")
    (tmp_path / "cache" / "app.exe").write_bytes(b"x")
    got = candidate_files(_t.time() - 60, roots=[(tmp_path, 3)])
    assert [g["name"] for g in got] == ["조사표.hwp"]


def test_settings_number_fields(tmp_path):
    """숫자 칸을 비우면 원래 값을 두고, 숫자가 아니면 한국어로 알려 주며 다른 칸도 바꾸지 않는다."""
    from seomu.config import Config
    c = Config(tmp_path)
    assert c.update({"top_k": "", "temperature": "0.5"}).top_k == 6
    assert c.settings.temperature == 0.5
    with pytest.raises(ValueError, match="검색 결과 수"):
        c.update({"user_name": "바뀌면 안 됨", "top_k": "abc"})
    assert c.settings.user_name == "" and Config(tmp_path).settings.user_name == ""


def test_rule_analysis_last_sentence_with_end_mark():
    """마지막 문장에 공문 끝 표시('끝.')가 붙어도 할 일은 짧게, 조사가 붙은 서류 이름('목록을')도 제출물로."""
    from seomu.analyzer import rule_analysis
    body = ("1. 연말을 맞아 사무실 대청소를 실시하오니 협조 바랍니다.\n  가. 일시: 2026. 12. 18.(금) 15:00\n"
            "2. 부서별 폐기 물품 목록을 2026. 12. 11.(금)까지 총무과로 제출하여 주시기 바랍니다. 끝.")
    a = rule_analysis("연말 사무실 대청소 실시 안내", body, [], REF)
    assert [d["what"] for d in a["deadlines"]] == ["부서별 폐기 물품 목록 제출"]
    assert [s["item"] for s in a["submissions"]] == ["부서별 폐기 물품 목록"]
    a = rule_analysis("교육 결과 제출", "1. 개인정보 보호 교육 이수 결과를 2026. 11. 25.(수)까지 제출하여 주시기 바랍니다.  끝.", [], REF)
    assert a["actions"][0] == "개인정보 보호 교육 이수 결과 제출 (11/25까지)"
    # 붙임 서식이 있으면 문장에서 뽑은 이름보다 붙임의 이름·서식 표시를 쓴다
    a = rule_analysis("점검 협조", "1. 점검 결과 확인서를 2026. 11. 20.(금)까지 회신하여 주시기 바랍니다.\n"
                      "붙임 1. 점검 일정표 1부.\n     2. 결과 확인서 서식 1부. 끝.", [], REF)
    assert [s["item"] for s in a["submissions"]] == ["결과 확인서 (붙임 서식)"]


def test_ai_folder_name_must_keep_title_subject():
    """AI가 지은 공문 이름이 제목의 핵심어를 빼면(무엇에 관한 공문인지 모르게) 원래 제목을 쓴다."""
    from seomu.analyzer import _keeps_subject
    assert not _keeps_subject("부서별 참석 인원 회신 요청", "2026년 송년 행사 참석 조사")
    assert not _keeps_subject("교육 참석 안내", "2026년 하반기 직원 역량강화 교육 참석 안내")
    assert _keeps_subject("송년 행사 참석 조사", "2026년 송년 행사 참석 조사")
    assert _keeps_subject("집행잔액 현황표 제출", "2026회계연도 집행잔액 현황 제출 요청")
    assert _keeps_subject("청렴 교육 이수 결과 보고", "청렴 교육 이수 및 결과 보고 요청")

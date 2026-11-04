import zipfile
from datetime import date
from pathlib import Path

import pytest

from seomu.analyzer import analyze, rule_analysis
from seomu.collector import analyze_html, collect_from_files, filename_from_headers, safe_name
from seomu.deadlines import best_deadlines, find_dates, find_submissions
from seomu.llm import LLMError, OllamaClient, extract_json, is_loopback_url
from seomu.mail import build_variables, render, tasks_to_ics
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
    ics = tasks_to_ics([{"id": 1, "title": "제출; 확인", "due": "2026-11-13", "done": 0}])
    assert "DTSTART;VALUE=DATE:20261113" in ics and "제출\; 확인" in ics


def test_html_to_text_skips_script():
    assert html_to_text("<p>a</p><script>x()</script><p>b</p>") == "a\n\nb"


def test_recommend_by_spec():
    from seomu.models import recommend
    assert recommend({"ram_total_gb": 16, "ram_avail_gb": 7, "gpu_usable": False})["model"] == "gemma4:e2b-it-qat"
    assert recommend({"ram_total_gb": 16, "ram_avail_gb": 10, "gpu_usable": False})["model"] == "gemma4:e4b-it-qat"
    assert recommend({"ram_total_gb": 8, "ram_avail_gb": 3, "gpu_usable": False})["model"] == "kanana-2:3b"
    assert recommend({"ram_total_gb": 4, "ram_avail_gb": 2, "gpu_usable": False})["model"] == "kanana-2:1.3b"

"""여러 공문 시스템 형식 지원 테스트.

온나라 HTML, 문서24 텍스트, K-에듀파인 웹 저장(.mht), 기관 홈페이지 게시판, 메일(.eml)·zip 붙임,
기업 전자결재 협조문, 붙여넣기, PDF식 강제 줄바꿈 본문을 같은 규칙으로 정리·분석하는지 확인한다.
"""
import io
import time
import unicodedata
import zipfile
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FORMATS = ROOT / "sample_data" / "formats"
REF = date(2026, 11, 7)


def analyze_file(name: str) -> tuple[str, dict]:
    from seomu.analyzer import rule_analysis
    from seomu.collector import extract_title
    from seomu.notice_text import tidy_text
    from seomu.parsers import parse_file
    text = tidy_text(parse_file(FORMATS / name))
    title = extract_title(text)
    return title, rule_analysis(title, text, [], REF)


# ---------------------------------------------------------------- 본문 다듬기
def test_tidy_text_unicode_and_spaces():
    from seomu.notice_text import tidy_text
    nfd = unicodedata.normalize("NFD", "제출 기한")                      # 맥에서 온 '자모 분리' 한글
    t = tidy_text(f"{nfd}: 2026.​ 11.　 13.까지")
    assert t == "제출 기한: 2026. 11. 13.까지"


def test_tidy_text_removes_blank_line_doubling_and_label_spacing():
    from seomu.notice_text import tidy_text
    t = tidy_text("수   신    수신자 참조\n\n제   목    청렴 교육 안내\n\n1. 관련 문서\n\n2. 참석 바랍니다.\n\n가. 일시: 11. 20.")
    assert t.splitlines() == ["수신 수신자 참조", "제목 청렴 교육 안내", "1. 관련 문서", "2. 참석 바랍니다.", "가. 일시: 11. 20."]


def test_tidy_text_drops_web_menu_lines():
    from seomu.notice_text import tidy_text
    t = tidy_text("본문 바로가기\n홈 > 알림마당 > 공지사항\n공모전 안내\n조회수 : 1,234\n목록\n이전글\nCopyright © City")
    assert t == "공모전 안내"


def test_tidy_text_rejoins_hard_wrapped_pdf_lines():
    from seomu.notice_text import tidy_text
    wrapped = ("2. 위 호와 관련하여 2026년 하반기 학교 시설물 안전점검을 다음과 같이 실\n"
               "시하오니, 각 학교에서는 점검 결과를 붙임 서식에 따라 작성하여 기한 내 제\n"
               "출하여 주시기 바랍니다. 점검 결과는 교육청 누리집에 공개될 예정이오니 참\n"
               "고하시기 바랍니다. 아울러 지적 사항은 즉시 조치하고 그 결과를 함께 보고\n"
               "하여 주시기 바랍니다. 학교별 담당자는 점검 일정을 미리 확인하여 주시기 바\n"
               "랍니다.\n"
               "  가. 점검 기간: 2026. 11. 2.(월) ~ 11. 20.(금)\n"
               "  나. 제출 기한: 2026. 11. 24.(화) 17:00까지")
    t = tidy_text(wrapped)
    lines = t.splitlines()
    assert lines[0].startswith("2. 위 호와 관련하여")
    for word in ("실시하오니", "제출하여", "참고하시기", "보고하여 주시기", "주시기 바랍니다."):   # 글자 단위로 끊긴 단어는 붙여 쓰고
        assert word in lines[0], word
    assert "기한 내 제출하여" in lines[0] and "예정이오니 참고" in lines[0]               # 어절 경계는 띄어 쓴다
    assert lines[1] == "가. 점검 기간: 2026. 11. 2.(월) ~ 11. 20.(금)"   # 번호 항목은 잇지 않는다
    assert len(lines) == 3


# ---------------------------------------------------------------- 형식별 파서
def test_html_links_not_glued_and_main_area_only():
    from seomu.parsers import html_to_text, main_text
    assert "본문 바로가기 주메뉴 바로가기" in html_to_text('<a href="#c">본문 바로가기</a><a href="#g">주메뉴 바로가기</a>')
    text = main_text((FORMATS / "홈페이지_게시판_공지.html").read_text(encoding="utf-8"))
    assert "시민 정책제안 공모전" in text and "신청 기한" in text
    for noise in ("주메뉴", "로그인", "열린시정", "개인정보처리방침", "이전글", "만족하십니까"):
        assert noise not in text, noise


@pytest.mark.parametrize("name,title,due,what", [
    ("문서24_공문.txt", "2026년 하반기 학교 안전점검 결과 제출 요청", "2026-11-24", "안전점검 결과 보고서·점검 사진 대지 제출"),
    ("에듀파인_웹공문.mht", "2026학년도 학교폭력 예방교육 실적 제출 안내", "2026-12-04", "학교폭력 예방교육 실적 보고서 제출"),
    ("홈페이지_게시판_공지.html", "2026년 시민 정책제안 공모전 참가 신청 안내", "2026-11-30", "참가신청서·제안서 제출"),
    ("회사_전자결재_협조문.txt", "[협조전] 2027년도 부서별 교육훈련 수요조사 협조 요청", "2026-11-19", "교육훈련 수요조사표 회신"),
    ("메일_공문.eml", "[인사팀] 2027년도 교육훈련 수요조사 협조 요청 (11/19까지)", "2026-11-19", "수요조사표 작성·회신"),
])
def test_each_system_format(name, title, due, what):
    t, a = analyze_file(name)
    assert t == title
    assert [d["date"] for d in a["deadlines"]] == [due]          # 같은 날 기한은 하나로
    assert a["deadlines"][0]["what"] == what
    assert "()" not in a["deadlines"][0]["what"] and "(서식)" not in a["deadlines"][0]["what"]


def test_summaries_are_short_noun_phrases():
    expect = {
        "문서24_공문.txt": "2026년 하반기 학교 시설물 안전점검 실시 — 점검 결과 작성·제출 요청 (11월 24일(화) 17:00까지)",
        "에듀파인_웹공문.mht": "2026학년도 학교폭력 예방교육 실적 취합 — 제출 요청 (12월 4일(금)까지)",
        "홈페이지_게시판_공지.html": "「2026년 시민 정책제안 공모전」 개최 — 참여 요청 (11월 30일(월) 18:00까지)",
        "메일_공문.eml": "부서별 교육 수요 조사 — 수요조사표 작성·회신 요청 (11월 19일(목) 15:00까지)",
    }
    for name, first in expect.items():
        _t, a = analyze_file(name)
        line = a["summary"].splitlines()[0]
        assert line == first, name
        for bad in ("하오니", "바랍니다", "위 호와", "귀 기관", "다음과 같이", "하고자"):
            assert bad not in a["summary"], (name, bad)


def test_reference_attachments_are_not_submissions():
    _t, a = analyze_file("문서24_공문.txt")
    items = [s["item"] for s in a["submissions"]]
    assert items == ["안전점검 결과 보고서 (붙임 서식)", "점검 사진 대지"]      # '안전점검 계획'은 참고 자료


def test_sample_notice_submissions_split_and_deduplicated():
    from seomu.analyzer import rule_analysis
    from seomu.collector import analyze_html
    info = analyze_html((ROOT / "sample_data" / "notice" / "예시_공문.html").read_text(encoding="utf-8"))
    a = rule_analysis(info["title"], info["text"], [], REF)
    assert [s["item"] for s in a["submissions"]] == ["참가 신청서 (붙임 서식)", "부서별 참석자 명단"]
    assert a["summary"].startswith("「2026년 청렴 교육 행사」 개최 — 부서별 참여 인원 회신 요청 (11월 13일(금) 18:00까지)")
    assert "행사명" not in a["summary"]                      # 행사 정보는 따로 보여 주므로 되풀이하지 않는다
    assert a["actions"][-1] == "전자우편(clean@example.go.kr)으로 제출"


def test_odt_pptx_rtf(tmp_path):
    from seomu.parsers import parse_file
    odt = tmp_path / "공문.odt"
    with zipfile.ZipFile(odt, "w") as z:
        z.writestr("content.xml", '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                   'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>'
                   '<text:p>제목: 회의 개최 안내</text:p><text:p>일시<text:tab/>11. 20.</text:p></office:text></office:body>'
                   '</office:document-content>')
    assert parse_file(odt) == "제목: 회의 개최 안내\n일시\t11. 20."
    pptx = tmp_path / "자료.pptx"
    with zipfile.ZipFile(pptx, "w") as z:
        z.writestr("ppt/slides/slide1.xml", '<p:sld xmlns:p="p" xmlns:a="a"><a:p><a:r><a:t>추진 계획</a:t></a:r></a:p></p:sld>')
    assert "추진 계획" in parse_file(pptx)
    rtf = tmp_path / "문서.rtf"
    rtf.write_bytes(b"{\\rtf1\\ansi\\ansicpg949{\\fonttbl{\\f0 Gulim;}}\\f0 \\'c1\\'a6\\'b8\\'f1: \\u54665?\\u49324? \\par end}")
    assert parse_file(rtf) == "제목: 행사\nend"


# ---------------------------------------------------------------- 수집 흐름
def test_eml_attachments_and_zip_expand(tmp_path):
    from seomu.collector import collect_from_files, expand_archives
    cap = collect_from_files([str(FORMATS / "메일_공문.eml")], tmp_path)
    names = [f["name"] for f in cap.files]
    assert "2027 교육훈련 수요조사표.txt" in names and "참고자료.zip" in names
    files = expand_archives(cap.files)
    inner = [f for f in files if f.get("from") == "참고자료.zip"]
    assert sorted(f["name"] for f in inner) == ["참고자료/붙임1_수요조사표 작성 요령.txt", "참고자료/붙임2_교육과정 목록.txt"]
    assert all(Path(f["path"]).exists() for f in inner)


def test_zip_cp949_names_and_no_escape(tmp_path):
    from seomu.collector import expand_archives
    z = tmp_path / "붙임.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("AAAA.hwp", b"hwp")
        zf.writestr("../../밖으로.txt", b"x")                                 # 상위 폴더로 빠져나가는 이름
    # 한국 PC에서 만든 zip처럼 이름을 cp949 바이트로, UTF-8 표시 없이 (같은 길이라 위치 정보는 그대로)
    z.write_bytes(buf.getvalue().replace(b"AAAA.hwp", "서식.hwp".encode("cp949")))
    out = expand_archives([{"name": z.name, "path": str(z), "ok": True}])
    names = sorted(f["name"] for f in out[1:])
    assert names == ["붙임/밖으로.txt", "붙임/서식.hwp"]
    assert all(tmp_path in Path(f["path"]).parents for f in out[1:])


def test_collect_from_pasted_web_html(tmp_path):
    from seomu.collector import collect_from_text
    html = ('<div id="gnb"><a>열린시정</a><a>알림마당</a></div><div class="board_view"><h3>불용품 매각 수요조사 협조 요청</h3>'
            '<div class="view_cont"><p>1. 부서별 불용품 현황을 조사하오니 제출하여 주시기 바랍니다.</p>'
            '<p>가. 제출 기한: 2026. 11. 18.(수)까지</p><p><a href="/files/a.hwp">현황표.hwp</a></p></div></div>')
    cap = collect_from_text("열린시정알림마당\n불용품 매각 수요조사 협조 요청\n1. 부서별 …", tmp_path, "", html)
    assert "열린시정" not in cap.text and "제출 기한" in cap.text
    assert cap.title == "불용품 매각 수요조사 협조 요청"
    assert cap.files[0]["name"] == "현황표.hwp" and not cap.files[0]["ok"]     # 상대 주소는 직접 저장 안내
    with pytest.raises(ValueError):
        collect_from_text("   ", tmp_path)


@pytest.mark.parametrize("raw,clean", [
    ("2026년 회계마감 협조사항 알림 - 개인 - Microsoft​ Edge", "2026년 회계마감 협조사항 알림"),
    ("청렴 교육 행사 참여 요청 - 온나라", "청렴 교육 행사 참여 요청"),
    ("안전점검 결과 제출 요청 - 문서24 - Chrome", "안전점검 결과 제출 요청"),
    ("공지사항 상세보기 | 정책제안 공모전 안내 | ○○시청", "정책제안 공모전 안내"),
    ("학교폭력 예방교육 실적 제출.pdf - Adobe Acrobat Reader", "학교폭력 예방교육 실적 제출.pdf"),
])
def test_clean_title(raw, clean):
    from seomu.collector import clean_title
    assert clean_title(raw) == clean


# ---------------------------------------------------------------- 메일 양식 문장 다듬기
def test_mail_particles_follow_title():
    from seomu.mail import josa, render
    tpl = "「{{공문제목}}」과 관련하여 {{행사명}}을 안내하며 {{장소}}으로 오십시오."
    out, _ = render(tpl, {"공문제목": "공모전 참가 신청 안내", "행사명": "청렴 교육", "장소": "대회의실"})
    assert out == "「공모전 참가 신청 안내」와 관련하여 청렴 교육을 안내하며 대회의실로 오십시오."
    out, _ = render(tpl, {"공문제목": "자료 제출 요청", "행사명": "체육대회", "장소": "본관 강당"})
    assert out == "「자료 제출 요청」과 관련하여 체육대회를 안내하며 본관 강당으로 오십시오."
    assert josa("2027", "은") == "은" and josa("2026", "는") == "은" and josa("제2", "가") == "가"
    out, missing = render("{{없는값}}을 확인", {})
    assert out == "[없는값]을 확인" and missing == ["없는값"]


def test_mail_summary_lines_become_bullets():
    from seomu.mail import build_variables
    from seomu.config import Settings
    v = build_variables({"title": "t", "analysis": {"summary": "행사 개최 — 회신 요청\n대상 전 부서"}}, Settings())
    assert v["요약"] == "  - 행사 개최 — 회신 요청\n  - 대상 전 부서"


# ---------------------------------------------------------------- API (붙여넣기 수집, 미리보기)
@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SEOMU_DOWNLOADS", str(tmp_path / "dl"))
    from seomu.api import Api
    a = Api(tmp_path / "home")
    a.save_settings({"ollama_url": "http://127.0.0.1:9"})
    yield a
    a.shutdown()


def _wait(a, job):
    for _ in range(200):
        st = a.job_status(job["job_id"])
        if st["status"] != "running":
            assert st["status"] == "done", st["error"]
            return st["result"]
        time.sleep(0.05)
    raise TimeoutError


def test_api_collect_text_and_preview(api, tmp_path):
    body = (FORMATS / "문서24_공문.txt").read_text(encoding="utf-8").replace("\n", "\n\n")   # 웹 복사처럼 빈 줄이 낀 본문
    n = _wait(api, api.collect_text(body, "", False))
    assert "\n\n" not in n["body"]                              # 저장된 본문은 빈 줄이 정리되어 있다
    assert n["analysis"]["deadlines"][0]["date"] == "2026-11-24"
    saved = Path(n["folder"]) / "본문.txt"
    pv = api.preview_file(str(saved))
    assert pv["error"] == "" and "안전점검" in pv["text"]
    outside = tmp_path / "outside.txt"
    outside.write_text("비밀", encoding="utf-8")
    with pytest.raises(ValueError):
        api.preview_file(str(outside))                           # 공문 폴더 밖 파일은 읽지 않는다
    with pytest.raises(ValueError):
        api.collect_text("  ", "", False)


def test_api_collect_eml_unpacks_attachments(api):
    n = _wait(api, api.collect_files([str(FORMATS / "메일_공문.eml")], "", 0, False))
    names = [f["name"] for f in n["attachments"]]
    assert "참고자료/붙임1_수요조사표 작성 요령.txt" in names
    assert n["analysis"]["submissions"][0]["item"] == "2027 교육훈련 수요조사표"

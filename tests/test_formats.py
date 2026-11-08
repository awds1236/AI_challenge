"""여러 공문 시스템 형식 지원 테스트.

온나라 HTML, 문서24 텍스트, K-에듀파인 웹 저장(.mht), 기관 홈페이지 게시판, 메일(.eml)·zip 붙임,
기업 전자결재 협조문, 붙여넣기, PDF식 강제 줄바꿈 본문을 같은 규칙으로 정리·분석하는지 확인한다.
"""
import io
import sys
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
    ("메일_공문.eml", "[인사팀] 2027년도 교육훈련 수요조사 협조 요청 (11/19까지)", "2026-11-19", "교육훈련 수요조사표 회신"),
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


def test_wording_edge_cases():
    """종합 검증(tools/verify_all.py)에서 찾은 어색한 문구가 다시 생기지 않게."""
    from seomu.analyzer import rule_analysis
    memo = ("제목: 부서별 비상연락망 정비 협조\n연말 재난 대비 훈련을 위해 부서별 비상연락망을 새로 정비하고자 합니다.\n"
            "각 부서에서는 변경된 연락처를 반영하여 '26. 11. 25.까지 총무팀으로 회신하여 주시기 바랍니다.\n"
            "- 회신 자료: 비상연락망 1부")
    a = rule_analysis("부서별 비상연락망 정비 협조", memo, [], REF)
    assert a["deadlines"][0]["what"] == "비상연락망 회신"                       # '서에서는 …'으로 잘리지 않는다
    assert a["summary"].startswith("부서별 비상연락망 새로 정비 — ")
    assert "'26." not in a["summary"] and "(11월 25일(수)까지)" in a["summary"]
    two = ("제목 청렴 교육 이수 및 결과 보고 요청\n1. 청렴 교육 이수를 아래와 같이 요청하오니 협조하여 주시기 바랍니다.\n"
           "가. 이수 기한: 2026. 11. 28.(토)까지\n나. 결과 보고 기한: 2026. 12. 2.(수)까지\n다. 보고 자료: 교육 이수 결과 보고서 1부")
    a = rule_analysis("청렴 교육 이수 및 결과 보고 요청", two, [], REF)
    assert [d["what"] for d in a["deadlines"]] == ["청렴 교육 이수", "교육 이수 결과 보고서 제출"]
    assert a["summary"].startswith("청렴 교육 이수 요청 (11월 28일(토)까지)")
    info = rule_analysis("주차장 공사 안내", "1. 청사 주차장 도색 공사를 실시하오니 업무에 참고하시기 바랍니다.", [], REF)
    assert info["summary"] == "청사 주차장 도색 공사 실시 — 업무 참고"
    fin = rule_analysis("집행잔액 제출", "1. 결산에 대비하여 부서별 집행잔액 현황을 취합하오니 제출하여 주시기 바랍니다.", [], REF)
    assert fin["summary"] == "부서별 집행잔액 현황 취합 — 제출 요청"


def test_ocr_request_ending_and_corrupt_title(tmp_path):
    from seomu.collector import collect_from_files
    from seomu.parsers import fix_ocr_text
    assert fix_ocr_text("협조하여 주시기 바랍l\n불임 서식 1부") == "협조하여 주시기 바랍니다.\n붙임 서식 1부"
    bad = tmp_path / "10_손상된_파일.hwpx"
    bad.write_bytes(b"PK broken")
    cap = collect_from_files([str(bad)], tmp_path / "out")
    assert cap.title == "10 손상된 파일" and "본문을 읽지 못했습니다" in cap.text


def test_layout_text_rebuilds_lines_and_spaces():
    """변환 뷰어·PDF.js 글자 층: 위치로만 띄운 낱말, 뒤섞인 순서를 읽는 순서·띄어쓰기로 되살린다."""
    from seomu.collector import layout_text
    items = [{"t": "협조", "x": 140, "y": 40, "w": 30, "h": 15}, {"t": "제목:", "x": 50, "y": 40, "w": 34, "h": 15},
             {"t": "바랍니다.", "x": 120, "y": 66, "w": 60, "h": 15}, {"t": "비상연락망", "x": 93, "y": 40, "w": 40, "h": 15},
             {"t": "주시기", "x": 50, "y": 66, "w": 45, "h": 15}]
    assert layout_text(items) == "제목: 비상연락망 협조\n주시기 바랍니다."
    assert layout_text([{"t": "제", "x": 0, "y": 0, "w": 15, "h": 15}, {"t": "출", "x": 15, "y": 0, "w": 15, "h": 15}]) == "제출"


def test_mojibake_filename_and_sniffed_formats(tmp_path):
    from seomu.collector import fix_mojibake
    from seomu.parsers import parse_file
    assert fix_mojibake("집행잔액 서식.hwpx".encode("cp949").decode("latin-1")) == "집행잔액 서식.hwpx"
    assert fix_mojibake("참석자 명단.xlsx".encode("utf-8").decode("latin-1")) == "참석자 명단.xlsx"
    assert fix_mojibake("report.pdf") == "report.pdf"
    hwx = tmp_path / "결재문서.hwx"
    hwx.write_text('<?xml version="1.0"?><HWX><BODY><P>제목: 자료 제출 요청</P></BODY></HWX>', encoding="utf-8")
    assert "제목: 자료 제출 요청" in parse_file(hwx)
    noext = tmp_path / "download.do"                       # 확장자 없이 받은 HWPX
    with zipfile.ZipFile(noext, "w") as z:
        z.writestr("Contents/section0.xml", '<hs:sec xmlns:hs="s" xmlns:hp="p"><hp:p><hp:run><hp:t>붙임 서식</hp:t></hp:run></hp:p></hs:sec>')
    assert parse_file(noext) == "붙임 서식"


def test_hwp5_binary(tmp_path):
    """한글 5.0(.hwp, OLE 복합 문서): 압축·비압축, 미니 스트림·일반 섹터 모두 읽는다."""
    sys.path.insert(0, str(ROOT / "tools"))
    from mock_env.hwp5 import write_hwp
    from seomu.parsers import parse_file
    lines = ["제목 안전교육 실적 제출", "가. 제출 기한: 2026. 12. 9.(수)까지", "학교명\t인원"]
    p = tmp_path / "공문.hwp"
    write_hwp(p, lines)
    assert parse_file(p) == "\n".join(lines)
    write_hwp(p, lines * 60, compressed=False)            # 4096바이트를 넘는 본문 스트림
    assert parse_file(p).count("제출 기한") == 60
    renamed = tmp_path / "download.do"                    # 확장자 없이 받은 HWP도 내용으로 판별
    renamed.write_bytes(p.read_bytes())
    assert parse_file(renamed).count("제출 기한") == 60


def test_real_board_structures():
    """실제 공개 게시판에서 본 구조: 사이트·메뉴 이름이 아닌 게시물 제목, 겹친 붙임 링크, 화면 글자 정리."""
    from seomu.collector import analyze_html, post_title
    page = ('<html><head><title> | ○○교육청</title></head><body><div id="gnb"><h2>민원/참여</h2></div>'
            '<div class="page-title-wrap"><h2>보도자료</h2><button>URL 복사</button></div>'
            '<div class="modal"><h2 class="modal-title">맞춤형 콘텐츠</h2></div>'
            '<div class="bbs_ViewA"><h3>2026학년도 채용 서류 제출 안내</h3><ul><li>작성자</li><li>홍길동</li>'
            '<li>작성일자 2026.11.02</li></ul><div class="cont"><p>서류를 제출하여 주시기 바랍니다.</p></div>'
            '<a href="/f?id=1">다운로드</a><a href="/f?id=1">채용 서식.hwpx</a></div></body></html>')
    assert post_title(page) == "2026학년도 채용 서류 제출 안내"
    info = analyze_html(page, "https://x.go.kr/")
    assert info["title"] == "2026학년도 채용 서류 제출 안내"
    assert [a["name"] for a in info["attachments"]] == ["채용 서식.hwpx"]
    # 제목 상자 안의 분류 표시('일반', '일부')와 영어 병기는 뗀다
    assert post_title('<div class="board-view"><div class="header"><div class="subject"><span>일반</span>'
                      '<strong>자비유학 신청 안내 / Application Guide</strong></div></div></div>') == "자비유학 신청 안내"
    assert post_title('<div class="subjectHead"><p class="subjectHead_tit">시행규칙 일부개정령안 입법예고<span>일부</span>'
                      '</p></div>') == "시행규칙 일부개정령안 입법예고"
    from seomu.notice_text import tidy_text
    assert tidy_text("열기\nURL 복사현재 URL 복사 버튼\n작성자\n홍길동\n작성일자2026.01.28\n조회수3,250회\n본문") == "본문"


def test_period_end_is_deadline():
    from seomu.analyzer import rule_analysis
    body = ("1. 채용 서류 제출\n가. 제출 기간: 2026.11.16.(월) 09:00 ~ 2026.11.20.(금) 18:00\n"
            "나. 기타: 신체검사서 제출 가능(기준일: 2027. 3. 1.)\n차수\t유형\t신청 기간\n"
            "1차\t교과\t2026.11.23.(월) ~ 2026.11.25.(수)\n마. 접수 마감\n2026년 12월 7일(월)\n"
            "다. 일시: 2026. 11. 26.(목) 14:00 ~ 17:00")
    a = rule_analysis("채용 서류 제출 안내", body, [], REF)
    assert [(d["date"], d["time"], d["what"]) for d in a["deadlines"]] == [
        ("2026-11-20", "18:00", "채용 서류 제출"), ("2026-11-25", "", "1차 교과 신청"), ("2026-12-07", "", "접수 마감")]
    long = ("1. 일부개정안에 대하여 의견이 있는 단체 또는 개인은 2026. 12. 9.까지 온라인으로 의견을 제출하시거나, "
            "다음 사항을 기재한 의견서룰 장관에게 제출하여 주시기 바랍니다.")
    a = rule_analysis("시행규칙 일부개정령안 입법예고", long, [], REF)
    assert a["deadlines"][0]["what"] == "의견서 제출"
    assert a["summary"].startswith("시행규칙 일부개정령안 입법예고 — 의견서 제출 요청 (12월 9일(수)까지)")


def test_url_fetch_keeps_cookies_and_windows_certs():
    """쿠키를 심고 같은 주소로 다시 보내는 사이트(무한 리디렉션 방지), 중간 인증서 누락 사이트(Windows 저장소로 검증)."""
    import urllib.request
    from seomu import collector
    opener = collector._opener()
    kinds = {type(h).__name__ for h in opener.handlers}
    assert "HTTPCookieProcessor" in kinds and "HTTPSHandler" in kinds
    ctx = collector._ssl_context()
    assert ctx.verify_mode != 0                     # 검증을 끄지 않는다
    sys.path.insert(0, str(ROOT / "tools"))
    from mock_env import web_systems
    srv, base = web_systems.start(ROOT / "sample_data")
    try:
        markup, final = collector.fetch_url(base + "/board/view", timeout=10)
        assert "2026학년도 기간제 교원 채용 서류 제출 안내" in markup and final.endswith("/board/view")
    finally:
        srv.shutdown()


def test_found_while_using_the_app(api, tmp_path):
    """실제 앱을 써 보며 찾은 문제: PDF 띄어쓰기(NUL), 일시만 있는 '행사', 지난 기한 할 일, 직접 넣은 붙임, 홈 순서, 보고서 괄호."""
    from datetime import date, timedelta
    from seomu.analyzer import event_info
    from seomu.parsers import normalize
    from seomu.report import outline_from_notice
    assert normalize("2026학년도\x00겨울계절\x00및\x00\x0c다음") == "2026학년도 겨울계절 및\n다음"
    assert event_info({"일시": "2026.2.10.(화) 17:00 예정"}) == {}
    assert event_info({"교육명": "실무 과정", "일시": "11. 26."})["name"] == "실무 과정"
    old = (date.today() - timedelta(days=60)).strftime("%Y. %m. %d.")
    soon = (date.today() + timedelta(days=5)).strftime("%Y. %m. %d.")
    body = f"제목 자료 제출\n1. 자료를 제출하여 주시기 바랍니다.\n가. 1차 제출 기한: {old}까지\n나. 2차 제출 기한: {soon}까지\n붙임 제출 서식 1부. 끝."
    n = _wait(api, api.collect_text(body, "", False))
    titles = [t["due"] for t in api.list_tasks(True) if t["notice_id"] == n["id"]]
    assert titles == [(date.today() + timedelta(days=5)).isoformat()]          # 60일 전 기한은 할 일로 만들지 않는다
    assert api.dashboard()["tasks"][0]["due"] == titles[0]
    (Path(n["folder"]) / "붙임" / "제출 서식.hwpx").write_bytes(b"PK")          # 사용자가 직접 넣은 붙임
    att = api.get_notice(n["id"])["attachments"]
    assert [(f["name"], f["ok"]) for f in att] == [("제출 서식.hwpx", True)]
    rep = outline_from_notice(api.get_notice(n["id"]))
    texts = [it.get("text", "") for s in rep["sections"] for it in s["items"]]
    assert any(t.endswith("까지 2차 제출") or "까지" in t for t in texts)
    for s in rep["sections"]:
        for it in s["items"]:
            assert (it.get("head") or "").count("(") == (it.get("head") or "").count(")")
    assert "\n" not in rep["summary"]


def test_ai_result_guards():
    """AI 결과 방어: 비워 둔 마감 시각은 규칙 결과로 채우고, 양식 소제목 나열 같은 보고서 제목은 쓰지 않는다."""
    import json
    from seomu.analyzer import analyze
    from seomu.report import plausible_title

    class FakeClient:
        def pick_chat_model(self, m=""):
            return "fake"

        def chat(self, messages, model, **kw):
            return json.dumps({"folder_name": "안전점검", "summary": "AI 요약", "submissions": [], "actions": [],
                               "deadlines": [{"date": "2026-11-24", "time": "", "what": ""}]}, ensure_ascii=False)
    body = (FORMATS / "문서24_공문.txt").read_text(encoding="utf-8")
    a = analyze("2026년 하반기 학교 안전점검 결과 제출 요청", body, [], FakeClient(), ref=REF)
    assert a["mode"] == "llm" and a["deadlines"][0]["time"] == "17:00" and a["deadlines"][0]["what"]
    assert a["folder_name"] == "안전점검"                       # 제목과 겹치는 AI 이름은 받는다

    class OddName(FakeClient):
        def chat(self, messages, model, **kw):
            return json.dumps({"folder_name": "테스트", "summary": "s", "deadlines": [], "submissions": [], "actions": []})
    b = analyze("2026년 하반기 학교 안전점검 결과 제출 요청", body, [], OddName(), ref=REF)
    assert b["folder_name"] == "2026년 하반기 학교 안전점검 결과 제출 요청"   # 지어낸 이름은 버린다
    assert [d["date"] for d in b["deadlines"]] == ["2026-11-24"]               # AI가 놓친 기한은 규칙 결과로 보존
    heads = ["추진 배경", "주요 내용", "향후 계획"]
    assert not plausible_title("추진 배경, 주요 내용, 향후 계획", "안전점검 결과 제출 요청 관련 보고", heads)
    assert not plausible_title("회의록", "안전점검 결과 제출 요청 관련 보고", heads)
    assert plausible_title("학교 안전점검 결과 보고", "2026년 하반기 학교 안전점검 결과 제출 요청 관련 보고", heads)


def test_tidy_real_model_output():
    """실제 Gemma 4 E2B 출력에서 본 어색한 문장: 공문 어미가 남은 요약, 들쭉날쭉한 할 일, 서식 표시가 남은 제출물."""
    from seomu.analyzer import tidy_ai_action, tidy_ai_item, tidy_ai_summary
    assert tidy_ai_summary("안전점검을 실시하오니, 각 학교는 결과를 제출해야 합니다.") == "안전점검을 실시하므로 각 학교는 결과를 제출해야 합니다."
    assert tidy_ai_summary("교육 수요를 조사하고자 합니다.") == "교육 수요를 조사합니다."
    assert tidy_ai_action("부서별 집행잔액 현황을 취합합니다.") == "부서별 집행잔액 현황 취합"
    assert tidy_ai_action("2026-12-02까지 보고서를 제출합니다.") == "12. 2.까지 보고서 제출"
    assert tidy_ai_action("1. 명단 작성") == "명단 작성"
    assert tidy_ai_item("집행잔액 현황표(붙임 1 서식) 1부") == "집행잔액 현황표 (붙임 서식)"
    assert tidy_ai_item("참석자 명단 1부") == "참석자 명단"


def test_polished_mail_drops_invented_headers():
    """실제 모델이 '본문만' 지시에도 붙인 '제목: …', '수신: [관련 부서 또는 대상]' 줄은 걷어낸다."""
    from seomu.mail import clean_polished
    draft = "안녕하세요, 총무과 홍길동입니다.\n참석자 명단을 [내부서]로 제출 부탁드립니다.\n감사합니다."
    out = ("제목: 「교육 참석자 명단 제출 요청」\n\n수신: [관련 부서 또는 대상]\n\n안녕하십니까. 총무과 홍길동입니다.\n"
           "참석자 명단을 [내부서]로 제출하여 주시기 바랍니다.\n감사합니다.")
    assert clean_polished(out, draft) == ("안녕하십니까. 총무과 홍길동입니다.\n참석자 명단을 [내부서]로 제출하여 주시기 바랍니다.\n"
                                          "감사합니다.")
    assert clean_polished("짧음", draft * 3) == "짧음"            # 거의 다 지워지면 원래 결과를 그대로 둔다


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


def test_fix_ocr_text():
    from seomu.parsers import fix_ocr_text
    raw = "나. 제출 서류 점검표(붙임 서식) 1丁\n다. 문의세 총무과(ß 02-000-1234)\n붙임 점검표 1丁\n曰 그"
    assert fix_ocr_text(raw).splitlines() == ["나. 제출 서류: 점검표(붙임 서식) 1부", "다. 문의처: 총무과(☎ 02-000-1234)",
                                              "붙임 점검표 1부  끝."]


def test_scanned_pdf_jpeg_without_pillow(tmp_path):
    """Pillow가 없어도 스캔 PDF 속 JPEG 그림 바이트를 그대로 꺼낸다."""
    from pypdf import PdfReader
    from seomu.parsers import _raw_jpegs
    jpeg = b"\xff\xd8\xff\xe0" + b"JFIF-test-data" + b"\xff\xd9"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << /XObject << /Im0 4 0 R >> >> >>",
            b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 "
            b"/Filter /DCTDecode /Length " + str(len(jpeg)).encode() + b" >>\nstream\n" + jpeg + b"\nendstream"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(bytes(out))
    assert _raw_jpegs(PdfReader(str(pdf)).pages[0]) == [(".jpg", jpeg)]


_DRAW_PS = r"""param([string]$Out)
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap 1400, 420
$g = [System.Drawing.Graphics]::FromImage($bmp); $g.Clear([System.Drawing.Color]::White)
$font = New-Object System.Drawing.Font("Malgun Gothic", 22); $y = 30
foreach ($l in @("제목 에너지 절약 점검 결과 제출 요청", "가. 제출 기한: 2026. 11. 27.(금) 18:00까지",
                 "나. 제출 서류: 에너지 절약 점검표 1부", "붙임 에너지 절약 점검표 1부. 끝.")) {
  $g.DrawString($l, $font, [System.Drawing.Brushes]::Black, 40, $y); $y += 90 }
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
"""


def test_scanned_image_notice_ocr(tmp_path):
    """사진·스캔 공문: Windows 내장 한국어 OCR로 읽어 기한을 찾는다 (Windows가 아니거나 OCR이 없으면 건너뜀)."""
    import subprocess
    import sys
    from seomu.analyzer import rule_analysis
    from seomu.parsers import ParseError, parse_file
    if not sys.platform.startswith("win"):
        pytest.skip("Windows 전용")
    ps, img = tmp_path / "draw.ps1", tmp_path / "scan.png"
    ps.write_text(_DRAW_PS, encoding="utf-8-sig")        # PowerShell 5.1은 BOM이 없으면 한글을 CP949로 읽는다
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps), str(img)],
                   capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if not img.exists():
        pytest.skip("이미지를 만들 수 없음 (System.Drawing 없음)")
    try:
        text = parse_file(img)
    except ParseError as e:
        if "OCR" in str(e):
            pytest.skip(f"한국어 OCR 기능 없음: {e}")
        raise
    assert "제출 기한" in text and "점검표" in text
    a = rule_analysis("에너지 절약 점검 결과 제출 요청", text, [], REF)
    assert [(d["date"], d["time"]) for d in a["deadlines"]] == [("2026-11-27", "18:00")]


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
    a.save_settings({"engine": "ollama", "ollama_url": "http://127.0.0.1:9"})
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


def test_checked_download_fixes_wrong_extension_and_rejects_web_pages(tmp_path):
    """링크 글자는 '신청서.hwp'인데 내용은 글자 파일 → .txt로 바로잡고, 파일 대신 웹 페이지(로그인 화면)는 받지 못함으로."""
    from seomu.collector import checked_download
    a = tmp_path / "참가신청서.hwp"
    a.write_text("참가 신청서\n부서명:\n성명:", encoding="utf-8")
    r = checked_download(a, "참가신청서.hwp")
    assert r["ok"] and r["name"] == "참가신청서.txt" and not a.exists()
    b = tmp_path / "안내문.hwp"
    b.write_bytes(b"<!DOCTYPE html><html><body>\xeb\xa1\x9c\xea\xb7\xb8\xec\x9d\xb8</body></html>")
    r = checked_download(b, "안내문.hwp")
    assert not r["ok"] and "웹 페이지" in r["error"] and not b.exists()
    c = tmp_path / "진짜.pdf"
    c.write_bytes(b"%PDF-1.4\n%")
    assert checked_download(c)["name"] == "진짜.pdf"

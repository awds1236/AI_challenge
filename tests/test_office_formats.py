"""공공기관에서 주고받는 문서 형식 읽기: 옛 오피스(DOC·XLS·PPT)·ODF(ODS·ODP)·RTF·HML·한셀/한쇼 안내·압축 안내."""
from pathlib import Path

import pytest

from seomu import parsers

DEMO = Path(__file__).resolve().parent.parent / "sample_data" / "시연"


def test_legacy_word_doc():
    t = parsers.parse_file(DEMO / "04_교육수요조사" / "2027년 직무교육 수요조사 실시.doc")
    assert "제목 2027년 직무교육 수요조사 실시" in t and "2026. 11. 20.(금)까지" in t


def test_legacy_excel_xls():
    pytest.importorskip("xlrd")
    t = parsers.parse_file(DEMO / "04_교육수요조사" / "붙임1. 직무교육 수요조사서(서식).xls")
    assert "[시트: 수요조사]" in t and "희망 교육 분야" in t


def test_legacy_powerpoint_ppt_without_master_text():
    t = parsers.parse_file(DEMO / "04_교육수요조사" / "붙임2. 2026년 교육과정 운영 결과.ppt")
    assert "집합교육 14과정" in t and "Click to edit" not in t and "Outline Level" not in t


def test_odf_spreadsheet_and_slides():
    ods = parsers.parse_file(DEMO / "05_공용차량점검" / "붙임1. 운행일지 점검 결과표.ods")
    assert "연번\t차량번호\t관리부서" in ods                      # 표의 한 행은 한 줄
    odp = parsers.parse_file(DEMO / "09_청렴서약" / "붙임2. 청렴 교육 자료.odp")
    assert "청탁금지법 핵심" in odp


def test_rtf_with_nested_groups():
    """LibreOffice·워드가 만드는 RTF(글꼴표·스타일이 여러 겹)에서도 본문 글자만."""
    t = parsers.parse_file(DEMO / "07_건강검진" / "붙임2. 건강검진 문진표.rtf")
    assert t.startswith("일반건강검진 문진표") and "Times New Roman" not in t


def test_cp949_text_and_csv():
    t = parsers.parse_file(DEMO / "06_연말연시당직" / "2026~2027년 연말연시 당직근무 편성 안내.txt")
    assert "당직근무를 아래와 같이 편성하오니" in t
    c = parsers.parse_file(DEMO / "06_연말연시당직" / "붙임1. 당직근무 편성표(초안).csv")
    assert "2026-12-24,목" in c


def test_hml(tmp_path):
    p = tmp_path / "공문.hml"
    p.write_text('<?xml version="1.0" encoding="UTF-8"?><HWPML><BODY><SECTION>'
                 '<P><TEXT><CHAR>제출 기한: 2026. 12. 1.까지</CHAR></TEXT></P>'
                 '<P><TEXT><CHAR>문의: 총무팀</CHAR><TAB/><CHAR>내선 1234</CHAR></TEXT></P></SECTION></BODY></HWPML>',
                 encoding="utf-8")
    assert parsers.parse_file(p) == "제출 기한: 2026. 12. 1.까지\n문의: 총무팀\t내선 1234"


def test_ooxml_variants_and_sniffing(tmp_path):
    src = DEMO / "01_예산요구" / "붙임2. 예산 요구서(서식).xlsx"
    for ext in (".xlsm", ".xltx"):
        p = tmp_path / ("서식" + ext)
        p.write_bytes(src.read_bytes())
        assert "예산 요구서" in parsers.parse_file(p)
    cell = tmp_path / "한셀문서.cell"                   # 한셀이 XLSX와 같은 짜임으로 저장한 경우
    cell.write_bytes(src.read_bytes())
    assert "예산 요구서" in parsers.parse_file(cell)
    doc = tmp_path / "옛문서.dot"                       # 확장자가 달라도 OLE 안의 스트림으로 Word를 알아본다
    doc.write_bytes((DEMO / "04_교육수요조사" / "2027년 직무교육 수요조사 실시.doc").read_bytes())
    assert "직무교육 수요조사" in parsers.parse_file(doc)


def test_unreadable_formats_explain_what_to_do(tmp_path):
    for name, word in (("자료.alz", "풀어서"), ("자료.egg", "풀어서"), ("옛문서.gul", "훈민정음")):
        p = tmp_path / name
        p.write_bytes(b"\x00" * 10)
        with pytest.raises(parsers.ParseError, match=word):
            parsers.parse_file(p)
    show = tmp_path / "발표.show"
    show.write_bytes(b"\x00" * 10)
    with pytest.raises(parsers.ParseError):
        parsers.parse_file(show)


def test_supported_extensions_cover_public_sector_formats():
    for ext in (".hwp", ".hwpx", ".hwt", ".hml", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods",
                ".odp", ".pdf", ".rtf", ".txt", ".csv", ".html", ".mht", ".eml", ".msg", ".cell", ".show", ".png", ".jpg"):
        assert ext in parsers.SUPPORTED, ext

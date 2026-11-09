"""뷰어가 아닌 프로그램 창에서도 본문을 얻는 대체 경로."""
import sys
import zipfile

import pytest

from seomu import attach, winwindow as ww


def test_merge_pages_drops_overlap_even_with_ocr_noise():
    a = ["제목 예산 집행 현황 제출", "1. 관련 근거", "가. 제출 기한: 2026. 12. 4.", "나. 제출 서류: 현황표 1부"]
    b = ["가. 제출 기한: 2026. 12 4.", "나. 제출 서류: 현황표 1부", "3. 문의처: 재무과", "붙임 1. 현황표 서식 1부. 끝."]
    assert ww.merge_pages(a, b) == a + b[2:]
    assert ww.merge_pages(a, ["전혀 다른 줄입니다"]) == a + ["전혀 다른 줄입니다"]
    assert ww.merge_pages([], b) == b


def test_split_command_line_keeps_quoted_paths():
    args = ww.split_command_line(r'"C:\Program Files\Hnc\Hwp.exe" "C:\공문 폴더\협조 공문.hwpx" -silent')
    assert args[1] == r"C:\공문 폴더\협조 공문.hwpx" and args[2] == "-silent"


def test_title_mentions_without_extension():
    assert ww._title_mentions("협조 공문 - Word", r"C:\x\협조_공문.docx")
    assert ww._title_mentions("협조공문.hwpx - 한글", r"C:\x\협조공문.hwpx")
    assert not ww._title_mentions("다른 문서 - Word", r"C:\x\협조공문.docx")


def test_best_partial_prefers_prose_over_menu_labels():
    trace = []
    menus = ("파일\n편집\n보기\n도구\n도움말\n" * 6, "화면 글자 정보 (일부)")
    prose = ("2026. 12. 4.까지 집행잔액 현황표를 제출하여 주시기 바랍니다.\n담당자는 기한 내 회신해 주십시오.", "OCR (일부)")
    assert ww._best([menus, prose], trace) == (prose[0], prose[1])
    assert ww._best([], trace) == ("", "")


def _hwpx(path, lines):
    paras = "".join(f"<hp:p><hp:run><hp:t>{l}</hp:t></hp:run></hp:p>" for l in lines)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml",
                   '<hs:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
                   f'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section">{paras}</hs:sec>')


LINES = ["제목 청렴교육 이수 협조", "1. 각 부서에서는 청렴교육을 이수하고 2026. 11. 28.(금)까지 결과를 제출하여 주시기 바랍니다.",
         "2. 문의: 감사팀 (☎ 031-000-0000)"]


def test_window_document_from_command_line(tmp_path, monkeypatch):
    doc = tmp_path / "청렴교육 이수 협조.hwpx"
    _hwpx(doc, LINES)
    monkeypatch.setattr(ww, "_pid", lambda h: 1)
    monkeypatch.setattr(ww, "process_command_line", lambda pid: ["editor.exe", str(doc)])
    monkeypatch.setattr(attach, "recent_documents", lambda *a, **k: [])
    # 제목에 확장자 없이 이름만 있어도 실행 인자의 문서와 짝짓는다
    assert ww.window_document(1, "청렴교육 이수 협조 - 문서 편집기") == str(doc)
    # 제목이 다른 문서를 가리키면 실행 인자의 문서를 쓰지 않는다 (한 프로그램에 여러 문서)
    assert ww.window_document(1, "다른 공문 - 문서 편집기", deep=False) == ""
    # 제목이 없는 창은 연 문서가 하나뿐이면 그것
    assert ww.window_document(1, ww.UNTITLED, deep=False) == str(doc)


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows 전용")
def test_extract_text_falls_back_to_open_document(tmp_path, monkeypatch):
    """본문복사 버튼·글자 정보·편집 칸이 모두 없는 창 → 창에 열린 문서 파일을 읽는다."""
    doc = tmp_path / "협조.hwpx"
    _hwpx(doc, LINES)
    for name, value in {"get_clipboard": lambda: "", "set_clipboard": lambda t: None,
                        "click_any": lambda *a, **k: "", "uia_available": lambda: False,
                        "edit_text": lambda h: "", "_text": lambda h: f"{doc.name} [{tmp_path}\\] - 편집기",
                        "scroll_ocr_body": lambda *a, **k: pytest.fail("문서 파일을 찾았으면 OCR까지 갈 필요 없음")}.items():
        monkeypatch.setattr(ww, name, value)
    found, trace = {}, []
    text, how = ww.extract_text(123, trace=trace, found=found)
    assert "2026. 11. 28." in text and "문서 파일" in how and found["document"] == str(doc)


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows 전용")
def test_extract_text_returns_best_partial_instead_of_nothing(monkeypatch):
    for name, value in {"get_clipboard": lambda: "", "set_clipboard": lambda t: None,
                        "click_any": lambda *a, **k: "", "uia_available": lambda: False,
                        "edit_text": lambda h: "", "window_document": lambda *a, **k: "",
                        "scroll_ocr_body": lambda *a, **k: "제출 기한 2026. 12. 1."}.items():
        monkeypatch.setattr(ww, name, value)
    monkeypatch.setenv("SEOMU_NO_FOREGROUND", "1")
    text, how = ww.extract_text(123)
    assert text == "제출 기한 2026. 12. 1." and "일부" in how


def test_editor_unsaved_marker_and_browser_file_url():
    """메모장의 '*공문.txt - 메모장' 표시는 제목에서 빼고, 브라우저 주소창의 file:/// 주소는 PC 경로로 바꾼다."""
    from seomu.collector import clean_title
    assert clean_title("*청렴교육 이수 협조.txt - 메모장") == "청렴교육 이수 협조.txt"
    assert clean_title("● 공문.hwpx - 한글") == "공문.hwpx"
    assert ww._path_from_url("file:///C:/Users/a/%EA%B3%B5%EB%AC%B8.pdf") == r"C:\Users\a\공문.pdf"
    assert ww._path_from_url("C:/Users/a/공문.pdf#page=2") == r"C:\Users\a\공문.pdf"
    assert ww._path_from_url("https://example.go.kr/a.pdf") == ""


def test_copy_needs_foreground_permission(monkeypatch):
    """전체 선택·복사는 키보드 입력이라 창이 맨 앞에 있어야 한다 → 기본(뒤에서만 읽기)에서는 하지 않는다."""
    monkeypatch.delenv("SEOMU_NO_FOREGROUND", raising=False)
    ww.set_foreground_allowed(False)
    assert not ww.copy_allowed()
    ww.set_foreground_allowed(True)
    assert ww.copy_allowed()
    monkeypatch.setenv("SEOMU_NO_FOREGROUND", "1")
    assert not ww.copy_allowed()
    ww.set_foreground_allowed(False)

"""기관 서식 채우기, 규정 추가·삭제·교체 관리, 공통기반 모델(EXAONE) 목록."""
import shutil
import socket
import time
import zipfile
from datetime import date
from pathlib import Path

import pytest

from seomu import forms, guide, models
from seomu.parsers import parse_hwpx

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "sample_data" / "forms"
REF = date(2026, 11, 9)


def _trip():
    sit = guide.parse_situation("다음 주 수요일부터 목요일까지 대전으로 관외 출장, 시설 안전 워크숍 참석", REF)
    body = guide.draft_form("복명서", sit)["body"]
    return sit, body


# ---------------------------------------------------------------- 기관 서식 채우기
def test_fill_hwpx_table_form_with_situation_profile_and_edits(tmp_path):
    sit, body = _trip()
    body = body.replace("교통비 ○○○원, 숙박비 ○○○원 (증빙 첨부)", "교통비 45,000원 (영수증 첨부)")
    vals = forms.Values(forms.situation_values(sit, {"user_name": "홍길동", "user_dept": "총무팀"}), forms.body_values(body))
    src = SAMPLES / "출장복명서(예시).hwpx"
    before = src.read_bytes()
    out = tmp_path / "out.hwpx"
    r = forms.fill_file(src, vals, out)
    assert src.read_bytes() == before                                   # 원본 서식은 그대로
    text = parse_hwpx(out)
    lines = [l.strip() for l in text.splitlines()]
    after = lambda label: lines[lines.index(label) + 1]                 # noqa: E731  표: 항목 칸 다음이 값 칸
    assert after("출장자 성명") == "홍길동" and after("소 속") == "총무팀"
    assert after("출장기간") == "2026. 11. 18.(수) ~ 2026. 11. 19.(목)"
    assert after("출장지") == "대전" and after("출장목적") == "시설 안전 워크숍 참석"
    assert after("여비 정산") == "교통비 45,000원 (영수증 첨부)"          # 화면에서 고친 초안 값
    assert after("작성일") == "2026. 11. 9.(월)"
    assert "주요 내용" in r["missing"]                                   # 모르는 칸은 지어내지 않고 비워 둔다
    with zipfile.ZipFile(out) as z:
        assert z.namelist()[0] == "mimetype" and z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert z.testzip() is None


def test_fill_txt_placeholders_and_label_lines(tmp_path):
    sit = guide.parse_situation("11월 27일 금요일에 연가 쓰려고 해요", REF)
    body = "연가 신청\n\n1. 사유: 가족 행사\n2. 업무 대행자: 김대리\n3. 비상 연락처: ○○○-○○○○"
    vals = forms.Values(forms.situation_values(sit, {"user_name": "홍길동", "user_dept": "총무팀"}), forms.body_values(body))
    out = tmp_path / "o.txt"
    r = forms.fill_file(SAMPLES / "연가신청서(예시).txt", vals, out)
    t = out.read_text(encoding="utf-8")
    assert "성명 : 홍길동" in t and "사용 기간 : 2026. 11. 27.(금)" in t and "사유: 가족 행사" in t
    assert "업무 대행자: 김대리" in t and "신청일 : 2026. 11. 9.(월)" in t
    assert "비상 연락처 : " in t and "연락처" in r["missing"]           # ○○가 남은 값은 쓰지 않는다
    assert "{{" not in t


def _docx(path: Path) -> None:
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    cell = lambda t: f"<w:tc><w:p><w:r><w:t>{t}</w:t></w:r></w:p></w:tc>"   # noqa: E731
    body = (f'<w:document {w}><w:body><w:p><w:r><w:t>구매요구서</w:t></w:r></w:p>'
            f"<w:tbl><w:tr>{cell('품명')}{cell('')}</w:tr><w:tr>{cell('추정금액')}{cell('원')}</w:tr>"
            f"<w:tr>{cell('일시')}{cell('    년   월   일')}</w:tr></w:tbl>"
            f"<w:p><w:r><w:t>요구자: {{{{성명}}}}</w:t></w:r></w:p></w:body></w:document>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", body)


def test_fill_docx_table(tmp_path):
    src = tmp_path / "구매요구서.docx"
    _docx(src)
    sit = guide.parse_situation("프린터 토너 5개 구매해야 해요 약 30만원", REF)
    out = tmp_path / "o.docx"
    r = forms.fill_file(src, forms.Values(forms.situation_values(sit, {"user_name": "홍길동"}), {}), out)
    xml = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
    assert "프린터 토너" in xml and "300,000원" in xml and "요구자: 홍길동" in xml
    assert set(r["filled"]) == {"품명", "추정금액", "성명"}
    assert r["missing"] == ["일시"]                                       # '일시' 칸도 항목으로 알아본다 (날짜를 모름)
    sit2 = guide.parse_situation("11월 20일 물품 납품", REF)
    forms.fill_file(src, forms.Values(forms.situation_values(sit2), {}), out)
    assert "2026. 11. 20.(금)" in zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")


def test_form_store_add_match_delete(tmp_path):
    store = forms.FormStore(tmp_path / "forms")
    assert store.add([str(SAMPLES / "출장복명서(예시).hwpx"), str(SAMPLES / "연가신청서(예시).txt")]) == \
        ["출장복명서(예시)", "연가신청서(예시)"]
    assert store.match("출장 복명서") == "출장복명서(예시)"
    assert store.match("연가 신청") == "연가신청서(예시)"
    assert store.match("구매요구서") == ""
    assert "출장기간" in next(f for f in store.list() if f["ext"] == "hwpx")["fields"]
    with pytest.raises(ValueError):
        store.add([str(tmp_path / "x.hwp")]) if (tmp_path / "x.hwp").write_bytes(b"x") else None
    store.delete("연가신청서(예시)")
    assert [f["name"] for f in store.list()] == ["출장복명서(예시)"]
    assert (SAMPLES / "연가신청서(예시).txt").exists()                   # 올린 원본은 그대로


# ---------------------------------------------------------------- API (규정·서식)
def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SEOMU_DOWNLOADS", str(tmp_path / "dl"))
    from seomu.api import Api
    a = Api(tmp_path / "home")
    a.save_settings({"engine": "ollama", "ollama_url": f"http://127.0.0.1:{_closed_port()}",
                     "user_name": "홍길동", "user_dept": "총무팀"})
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


def test_guide_fills_uploaded_org_form(api, monkeypatch):
    api.add_forms([str(SAMPLES / "출장복명서(예시).hwpx")])
    real = guide.parse_situation
    monkeypatch.setattr(guide, "parse_situation", lambda t, ref=None: real(t, REF))
    r = wait(api, api.guide("다음 주 수요일부터 목요일까지 대전으로 관외 출장, 시설 안전 워크숍 참석"))
    rep = next(i for i, f in enumerate(r["forms"]) if f["name"] == "출장 복명서")
    assert r["forms"][rep]["template"] == "출장복명서(예시)"              # 이름이 맞는 기관 서식을 골라 둔다
    edited = r["forms"][rep]["body"].replace("교통비 ○○○원, 숙박비 ○○○원 (증빙 첨부)", "교통비 45,000원")
    out = api.fill_guide_form(r["id"], rep, edited, "")
    assert out["path"].endswith(".hwpx") and Path(out["path"]).parent.name == "서식 초안"
    text = parse_hwpx(Path(out["path"]))
    assert "홍길동" in text and "총무팀" in text and "2026. 11. 18.(수)" in text and "교통비 45,000원" in text
    with pytest.raises(ValueError):
        api.fill_guide_form(r["id"], rep, edited, "없는 서식")
    assert api.delete_form("출장복명서(예시)")["forms"] == []


def test_regulation_add_delete_replace_category_restore(api, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    reg = src / "복무 내규.txt"
    shutil.copy2(next((ROOT / "sample_data" / "regulations").glob("*.txt")), reg)
    wait(api, api.import_regulations([str(reg)]))
    docs = api.list_documents()["documents"]
    assert len(docs) == 1 and docs[0]["managed"]
    p = docs[0]["path"]
    # 분류 바꾸기 → 다시 색인해도 유지
    api.set_regulation_category(p, "지침")
    wait(api, api.reindex(True))
    assert api.list_documents()["documents"][0]["category"] == "지침"
    with pytest.raises(ValueError):
        api.set_regulation_category(p, "아무거나")
    # 개정본으로 교체: 다른 이름의 새 파일 → 예전 사본은 지우고 새 규정만
    new = src / "복무 내규(2027 개정).txt"
    new.write_text(reg.read_text(encoding="utf-8").replace("3일 이내에 복명서", "5일 이내에 복명서"), encoding="utf-8")
    wait(api, api.replace_regulation(p, str(new)))
    docs = api.list_documents()["documents"]
    assert [d["title"] for d in docs] == ["복무 내규(2027 개정)"] and not Path(p).exists()
    assert any("5일 이내에 복명서" in h["text"] for h in api.search("복명서 제출 기한"))
    # 삭제: 화면에서 추가한 사본만 지운다 (처음 고른 원본은 그대로)
    r = api.delete_regulation(docs[0]["path"])
    assert r["mode"] == "deleted" and api.list_documents()["documents"] == [] and new.exists() and reg.exists()
    # 연결한 폴더의 규정은 원본을 지우지 않고 제외 → 다시 포함
    api.add_regulation_dir(str(src))
    wait(api, api.reindex(False))
    ext = next(d for d in api.list_documents()["documents"] if d["title"] == "복무 내규")
    assert not ext["managed"]
    api.set_regulation_category(ext["path"], "법령")
    r = api.delete_regulation(ext["path"])
    assert r["mode"] == "excluded" and reg.exists()
    wait(api, api.reindex(False))                                        # 다시 색인해도 제외 유지
    lst = api.list_documents()
    assert "복무 내규" not in [d["title"] for d in lst["documents"]]
    assert [x["name"] for x in lst["excluded"]] == ["복무 내규.txt"]
    wait(api, api.restore_regulation(lst["excluded"][0]["path"]))
    back = next(d for d in api.list_documents()["documents"] if d["title"] == "복무 내규")
    assert back["category"] == "법령"                                     # 제외 전에 정한 분류가 되살아난다
    with pytest.raises(ValueError):
        api.delete_regulation(str(tmp_path / "없음.txt"))


# ---------------------------------------------------------------- 공통기반 모델
def test_exaone_in_catalog_for_both_engines():
    m = models.find("exaone3.5:2.4b")
    assert m and m["gov"] and m["kind"] == "chat" and "NC" in m["license"]
    assert m["dl"]["repo"] == "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct-GGUF"
    assert m["dl"]["file"] == "EXAONE-3.5-2.4B-Instruct-Q4_K_M.gguf"
    # 내장 엔진: 받은 GGUF 파일 이름으로, Ollama: 공식 이름으로 설치 여부를 알아본다
    assert models.installed_id(m, ["EXAONE-3.5-2.4B-Instruct-Q4_K_M"]) == "EXAONE-3.5-2.4B-Instruct-Q4_K_M"
    assert models.installed_id(m, ["exaone3.5:2.4b"]) == "exaone3.5:2.4b"
    from seomu.engine import is_embed_name
    assert not is_embed_name("EXAONE-3.5-2.4B-Instruct-Q4_K_M")          # 답변용 모델로 고른다
    assert sum(1 for x in models.CATALOG if x.get("gov")) >= 3            # Gemma 4 2종 + EXAONE


def test_builtin_engine_picks_exaone_when_only_model(tmp_path):
    from seomu.engine import LocalClient, LocalEngine
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "EXAONE-3.5-2.4B-Instruct-Q4_K_M.gguf").write_bytes(b"GGUF")
    c = LocalClient(LocalEngine(tmp_path))
    assert c.pick_chat_model("") == "EXAONE-3.5-2.4B-Instruct-Q4_K_M"

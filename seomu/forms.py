"""기관 서식 채우기: 기관이 쓰는 서식 파일(HWPX·DOCX·XLSX·TXT)을 올려 두면 그 서식 그대로 내용을 채운다.

채우는 곳 (서식을 따로 고칠 필요 없음)
  1) 표의 항목 칸: '출장기간'·'성명' 같은 항목 이름 칸의 오른쪽(또는 아래) 빈칸
  2) 본문의 항목 줄: '출장 기간 : ○○○' / '성명:' 처럼 쌍점 뒤가 비어 있는 줄
  3) 자리표시: 서식에 {{성명}}·{{기간}}처럼 적어 둔 곳 (어떤 위치든)

채울 값: 상황 안내의 상황(날짜·장소·목적·품목·금액), 설정의 내 정보(이름·부서·연락처),
화면에서 고친 초안의 '항목: 값' 줄. 값을 모르는 칸은 비워 둔다(지어내지 않는다).
원본 서식 파일은 읽기만 하고, 채운 결과는 새 파일로 만든다.
"""
from __future__ import annotations

import io
import re
import shutil
import zipfile
from datetime import date
from pathlib import Path

FORM_EXT = {".hwpx", ".docx", ".xlsx", ".txt"}

# 항목 이름 → 표준 항목 (서식마다 같은 뜻을 다르게 적는다)
SYNONYMS: dict[str, tuple[str, ...]] = {
    "기간": ("출장기간", "기간", "사용기간", "휴가기간", "연가기간", "병가기간", "출장일정", "출장일시", "출장일자",
           "근무일", "근무일자", "근무일시", "일시", "일자", "날짜", "개최일시", "행사일시", "회의일시", "교육기간",
           "납품희망일", "납기", "사용일", "사용일자"),
    "장소": ("출장지", "장소", "행선지", "목적지", "출장장소", "개최장소", "행사장소", "회의장소", "방문지", "방문처", "출장처"),
    "목적": ("목적", "출장목적", "용무", "방문목적", "사유", "신청사유", "구매사유", "근무사유", "출장사유", "휴가사유",
           "개최목적"),
    "성명": ("성명", "이름", "출장자", "신청자", "신청인", "보고자", "작성자", "요구자", "근무자", "출장자성명", "신청자성명",
           "점검자", "담당자", "작성자성명", "서약자", "응답자"),
    "소속": ("소속", "부서", "소속부서", "부서명", "요구부서", "신청부서", "소속팀"),
    "직급": ("직급", "직위", "직책", "직급직위"),
    "연락처": ("연락처", "전화", "전화번호", "휴대폰", "휴대전화", "비상연락처", "연락처전화"),
    "작성일": ("작성일", "신청일", "보고일", "작성일자", "신청일자", "보고일자", "요구일", "요구일자"),
    "품명": ("품명", "품목", "물품명", "품명및규격", "품명규격", "구매품목"),
    "금액": ("금액", "추정금액", "예산", "소요예산", "예정금액", "구매금액", "추정가격", "소요금액"),
    "수량": ("수량",),
    "시간": ("시간", "근무시간", "시간외근무시간", "초과근무시간"),
    "제목": ("제목", "건명"),
}
_CANON = {syn: key for key, syns in SYNONYMS.items() for syn in syns}
_EMPTYISH = re.compile(r"^[\s○◯●_\-~∼～:：.·/년월일시분원부개명()\d]*$")
_PLACEHOLDER = re.compile(r"\{\{\s*([^{}]{1,20}?)\s*\}\}")
_LINE_LABEL = re.compile(r"^(?P<head>\s*(?:\d{1,2}\s*[.)]\s*|[가-하]\s*[.)]\s*|[-○□·◦•]\s*)?)"
                         r"(?P<label>[가-힣][가-힣 ()/·]{0,18}?)\s*(?P<colon>[:：])\s*(?P<rest>.*)$")
WEEKDAYS = "월화수목금토일"


def norm_label(s: str) -> str:
    """'출장 기간 :' / '출장자(성명)' / '성 명' → 비교용 이름."""
    s = re.sub(r"\([^)]*\)", "", s or "")
    s = re.sub(r"[\s·:：*※\-]", "", s)
    return s.rstrip("란")


def canon(label: str) -> str:
    n = norm_label(label)
    return _CANON.get(n, "")


def _d(iso: str) -> str:
    if not iso:
        return ""
    d = date.fromisoformat(iso)
    return f"{d.year}. {d.month}. {d.day}.({WEEKDAYS[d.weekday()]})"


def body_values(body: str) -> dict[str, str]:
    """초안의 '항목: 값' 줄 → {이름: 값}. ○○가 남은 칸(아직 안 채운 칸)은 넣지 않는다."""
    out: dict[str, str] = {}
    for line in (body or "").splitlines():
        m = _LINE_LABEL.match(line)
        if not m:
            continue
        val = m.group("rest").strip()
        if not val or re.search(r"○{2,}", val):
            continue
        out[norm_label(m.group("label"))] = val
    return out


def situation_values(sit: dict, profile: dict | None = None) -> dict[str, str]:
    """상황·내 정보 → 표준 항목 값 (모르는 값은 넣지 않는다)."""
    profile = profile or {}
    v: dict[str, str] = {}
    if sit.get("start"):
        v["기간"] = (f"{_d(sit['start'])} ~ {_d(sit['end'])}" if sit.get("end") and sit["end"] != sit["start"]
                   else _d(sit["start"]))
    for key, src in (("장소", "place"), ("목적", "purpose"), ("품명", "item")):
        if sit.get(src):
            v[key] = str(sit[src])
    if sit.get("amount"):
        v["금액"] = f"{int(sit['amount']):,}원"
    if sit.get("hours"):
        v["시간"] = f"{sit['hours']:g}시간"
    if sit.get("today"):
        v["작성일"] = _d(sit["today"])
    for key, src in (("성명", "user_name"), ("소속", "user_dept"), ("연락처", "user_phone")):
        if profile.get(src):
            v[key] = str(profile[src])
    return v


def notice_values(notice: dict, profile: dict | None = None, today: date | None = None) -> dict[str, str]:
    """공문 분석 결과 + 내 정보 → 표준 항목 값 (공문에 붙은 서식을 채울 때). 모르는 값은 넣지 않는다."""
    profile = profile or {}
    a = notice.get("analysis") or {}
    v: dict[str, str] = {"제목": notice.get("title", ""), "작성일": _d((today or date.today()).isoformat())}
    ev = a.get("event") or {}
    if ev.get("date"):
        v["기간"] = ev["date"]
    if ev.get("place"):
        v["장소"] = ev["place"]
    for key, src in (("성명", "user_name"), ("소속", "user_dept"), ("연락처", "user_phone")):
        if profile.get(src):
            v[key] = str(profile[src])
    return {k: val for k, val in v.items() if val}


class Values:
    """항목 이름으로 값을 찾는다: ① 초안에 같은 이름의 줄 ② 같은 뜻(표준 항목)의 값."""

    def __init__(self, sit_vals: dict[str, str], body_vals: dict[str, str]):
        self.exact = dict(body_vals)
        self.canon: dict[str, str] = dict(sit_vals)
        for k, val in body_vals.items():          # 고친 초안이 상황에서 뽑은 값보다 우선
            c = _CANON.get(k)
            if c:
                self.canon[c] = val

    def get(self, label: str) -> str:
        n = norm_label(label)
        if not n:
            return ""
        if n in self.exact:
            return self.exact[n]
        c = _CANON.get(n)
        return self.canon.get(c, "") if c else self.canon.get(n, "")


# ---------------------------------------------------------------- XML 서식 (HWPX·DOCX 공통: 태그 이름으로만 다룬다)
def _L(e) -> str:
    return e.tag.rsplit("}", 1)[-1] if isinstance(e.tag, str) else ""


def _own_ts(p) -> list:
    """문단에 직접 속한 글자 조각 (문단 안 표의 글자는 빼고)."""
    out = []
    for r in p:
        if _L(r) in ("run", "r"):
            out += [t for t in r if _L(t) == "t"]
    return out


def _p_text(p) -> str:
    return "".join(t.text or "" for t in _own_ts(p))


def _cell_paras(tc) -> list:
    # 셀 안의 셀(중첩 표)은 제외: 이 셀이 가장 가까운 칸(tc)인 문단만
    return [p for p in tc.iter() if _L(p) == "p"
            and next((a for a in p.iterancestors() if _L(a) == "tc"), None) is tc]


def _cell_text(tc) -> str:
    return "\n".join(_p_text(p) for p in _cell_paras(tc)).strip()


def _drop_lineseg(p) -> None:
    for c in list(p):
        if _L(c) == "linesegarray":
            p.remove(c)


def _set_para_text(p, text: str) -> bool:
    ts = _own_ts(p)
    if not ts:
        runs = [r for r in p if _L(r) in ("run", "r")]
        if not runs:
            return False
        ns = runs[0].tag.rsplit("}", 1)[0] + "}" if "}" in runs[0].tag else ""
        from lxml import etree
        t = etree.SubElement(runs[0], ns + "t")
        ts = [t]
    ts[0].text = text
    for t in ts[1:]:
        t.text = ""
    _drop_lineseg(p)
    return True


def _set_cell(tc, text: str) -> bool:
    ps = _cell_paras(tc)
    if not ps:
        return False
    for p in ps[1:]:
        p.getparent().remove(p)
    return _set_para_text(ps[0], text)


def _fill_tree(root, vals: Values, filled: list, missing: list) -> None:
    # 1) 자리표시 {{항목}}
    for p in root.iter():
        if _L(p) != "p":
            continue
        txt = _p_text(p)
        if "{{" in txt and _PLACEHOLDER.search(txt):
            def rep(m):
                v = vals.get(m.group(1))
                (filled if v else missing).append(m.group(1))
                return v
            _set_para_text(p, _PLACEHOLDER.sub(rep, txt))
    # 2) 표의 항목 칸 → 오른쪽(없으면 아래) 빈칸
    for tbl in [t for t in root.iter() if _L(t) == "tbl"]:
        rows = [[tc for tc in tr if _L(tc) == "tc"] for tr in tbl if _L(tr) == "tr"]
        for ri, row in enumerate(rows):
            for ci, tc in enumerate(row):
                label = _cell_text(tc)
                if not label or len(label) > 20 or "\n" in label or (_EMPTYISH.match(label) and not canon(label)):
                    continue
                if not (canon(label) or norm_label(label) in vals.exact):
                    # 모르는 항목('결과 및 조치' 등): 오른쪽이 빈칸이면 직접 채울 칸으로 알려만 준다
                    if (re.fullmatch(r"[가-힣][가-힣 ·()/]{0,14}", label) and ci + 1 < len(row)
                            and not _cell_text(row[ci + 1]).strip()):
                        missing.append(label)
                    continue
                value = vals.get(label)
                target = None
                if ci + 1 < len(row) and _EMPTYISH.match(_cell_text(row[ci + 1])) and not canon(_cell_text(row[ci + 1])):
                    target = row[ci + 1]
                elif ri + 1 < len(rows) and ci < len(rows[ri + 1]) and _EMPTYISH.match(_cell_text(rows[ri + 1][ci])):
                    target = rows[ri + 1][ci]
                if target is None:
                    continue
                if value:
                    _set_cell(target, value)
                    filled.append(label)
                else:
                    missing.append(label)
    # 3) 본문의 '항목 : (빈칸)' 줄
    for p in root.iter():
        if _L(p) != "p":
            continue
        txt = _p_text(p)
        m = _LINE_LABEL.match(txt)
        if not m or not _EMPTYISH.match(m.group("rest")) or len(m.group("label")) > 15:
            continue
        label = m.group("label")
        if not (canon(label) or norm_label(label) in vals.exact):
            continue
        value = vals.get(label)
        if value:
            _set_para_text(p, f"{m.group('head')}{label}{m.group('colon')} {value}")
            filled.append(label)
        else:
            missing.append(label)


def _xml_parts(names: list[str], kind: str) -> list[str]:
    if kind == "hwpx":
        return sorted(n for n in names if re.match(r"Contents/section\d+\.xml$", n))
    return [n for n in names if n in ("word/document.xml",) or re.match(r"word/(header|footer)\d*\.xml$", n)]


def fill_file(template: Path, values: Values, out: Path) -> dict:
    """서식 파일을 채워 out에 쓴다. {'filled': [...], 'missing': [...]} (같은 이름은 한 번만)."""
    template, out = Path(template), Path(out)
    ext = template.suffix.lower()
    filled: list[str] = []
    missing: list[str] = []
    if ext == ".txt":
        from .parsers import read_text_file
        lines = []
        for line in read_text_file(template).splitlines():
            if "{{" in line:
                def rep(m):
                    v = values.get(m.group(1))
                    (filled if v else missing).append(m.group(1))
                    return v
                line = _PLACEHOLDER.sub(rep, line)
            else:
                m = _LINE_LABEL.match(line)
                if m and _EMPTYISH.match(m.group("rest")) and (canon(m.group("label")) or norm_label(m.group("label")) in values.exact):
                    v = values.get(m.group("label"))
                    if v:
                        line = f"{m.group('head')}{m.group('label')}{m.group('colon')} {v}"
                        filled.append(m.group("label"))
                    else:
                        missing.append(m.group("label"))
            lines.append(line)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif ext in (".hwpx", ".docx"):
        from lxml import etree
        kind = ext[1:]
        with zipfile.ZipFile(template) as zin:
            names = zin.namelist()
            parts = _xml_parts(names, kind)
            if not parts:
                raise ValueError("서식 파일 안에서 본문을 찾지 못했습니다 (손상되었거나 다른 형식일 수 있습니다)")
            data = {n: zin.read(n) for n in names}
            infos = {n: zin.getinfo(n) for n in names}
        for n in parts:
            tree = etree.parse(io.BytesIO(data[n]))
            _fill_tree(tree.getroot(), values, filled, missing)
            data[n] = etree.tostring(tree, xml_declaration=True, encoding=tree.docinfo.encoding or "UTF-8",
                                     standalone=tree.docinfo.standalone)
        if kind == "hwpx" and "Preview/PrvText.txt" in data:
            data["Preview/PrvText.txt"] = b""          # 한글이 열 때 다시 만든다
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zout:
            order = (["mimetype"] if "mimetype" in data else []) + [n for n in names if n != "mimetype"]
            for n in order:
                comp = zipfile.ZIP_STORED if n == "mimetype" else zipfile.ZIP_DEFLATED
                zi = zipfile.ZipInfo(n, date_time=infos[n].date_time)
                zi.compress_type = comp
                zout.writestr(zi, data[n])
        out.write_bytes(buf.getvalue())
        with zipfile.ZipFile(out) as z:                 # 다시 열어 손상이 없는지 확인
            if z.testzip() is not None:
                raise ValueError("채운 서식 파일을 저장하지 못했습니다")
    elif ext == ".xlsx":
        _fill_xlsx(template, values, out, filled, missing)
    else:
        raise ValueError("HWPX·DOCX·XLSX·TXT 서식만 채울 수 있습니다 (HWP는 한글에서 'HWPX로 저장', "
                         "XLS는 엑셀에서 'XLSX로 저장' 후 올려 주세요)")
    return {"filled": list(dict.fromkeys(filled)), "missing": [m for m in dict.fromkeys(missing) if m not in filled]}


def xls_to_xlsx(src: Path, dst: Path) -> None:
    """옛 엑셀(.xls) 서식을 XLSX로 옮긴다 (값·병합·열 너비. 글꼴·테두리 같은 꾸밈은 옮기지 않는다)."""
    try:
        import openpyxl  # type: ignore
        import xlrd  # type: ignore
    except ImportError as e:
        raise ValueError("XLS 서식을 채우려면 xlrd·openpyxl 패키지가 필요합니다 (또는 엑셀에서 XLSX로 저장해 올려 주세요)") from e
    book = xlrd.open_workbook(str(src), formatting_info=False)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sh in book.sheets():
        ws = wb.create_sheet(sh.name[:31] or "Sheet")
        for r in range(sh.nrows):
            for c in range(sh.ncols):
                v = sh.cell_value(r, c)
                if v not in ("", None):
                    ws.cell(r + 1, c + 1, int(v) if isinstance(v, float) and v == int(v) else v)
        for r0, r1, c0, c1 in getattr(sh, "merged_cells", []) or []:
            ws.merge_cells(start_row=r0 + 1, end_row=r1, start_column=c0 + 1, end_column=c1)
        for c in range(sh.ncols):
            width = max((len(str(sh.cell_value(r, c))) for r in range(sh.nrows)), default=8)
            ws.column_dimensions[openpyxl.utils.get_column_letter(c + 1)].width = min(40, max(8, width * 1.6))
    wb.save(str(dst))


def _fill_xlsx(template: Path, values: Values, out: Path, filled: list, missing: list) -> None:
    """엑셀 서식: ① {{항목}} ② '부 서 명 :'처럼 쌍점 뒤가 빈 칸 ③ 항목 칸 오른쪽의 빈칸."""
    try:
        import openpyxl  # type: ignore
        from openpyxl.cell.cell import MergedCell  # type: ignore
    except ImportError as e:
        raise ValueError("엑셀 서식을 채우려면 openpyxl 패키지가 필요합니다") from e
    wb = openpyxl.load_workbook(str(template))
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell, MergedCell) or not isinstance(cell.value, str):
                    continue
                txt = cell.value.strip()
                if "{{" in txt and _PLACEHOLDER.search(txt):
                    def rep(m):
                        v = values.get(m.group(1))
                        (filled if v else missing).append(m.group(1))
                        return v
                    cell.value = _PLACEHOLDER.sub(rep, cell.value)
                    continue
                m = _LINE_LABEL.match(txt)
                if m and _EMPTYISH.match(m.group("rest")) and len(m.group("label")) <= 15:
                    label = m.group("label")
                    if canon(label) or norm_label(label) in values.exact:
                        v = values.get(label)
                        if v:
                            cell.value = f"{m.group('head')}{label}{m.group('colon')} {v}"
                            filled.append(label)
                        else:
                            missing.append(label)
                    continue
                if len(txt) > 20 or not (canon(txt) or norm_label(txt) in values.exact):
                    continue
                right = ws.cell(row=cell.row, column=cell.column + 1)
                if isinstance(right, MergedCell) or (right.value not in (None, "") and
                                                     not (isinstance(right.value, str) and _EMPTYISH.match(right.value))):
                    continue                        # 오른쪽이 다른 항목 이름이면 표의 머리글이다
                below = ws.cell(row=cell.row + 1, column=cell.column)
                if below.value in (None, "") and right.value in (None, "") and ws.cell(row=cell.row, column=cell.column + 2).value:
                    continue                        # 머리글 줄(성명|직급|…)의 가운데가 빈 경우는 건드리지 않는다
                v = values.get(txt)
                if v:
                    right.value = v
                    filled.append(txt)
                else:
                    missing.append(txt)
    wb.save(str(out))


def form_fields(template: Path) -> list[str]:
    """서식에서 채울 수 있는 항목 이름 (미리 보기용)."""
    empty = Values({}, {})
    tmp = Path(template).with_name(".fields_probe" + Path(template).suffix)
    try:
        r = fill_file(template, empty, tmp)
        return r["missing"]
    except Exception:
        return []
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- 서식 보관함
class FormStore:
    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def list(self) -> list[dict]:
        if not self.folder.exists():
            return []
        out = []
        for f in sorted(self.folder.iterdir()):
            if f.is_file() and f.suffix.lower() in FORM_EXT and not f.name.startswith("."):
                out.append({"name": f.stem, "file": f.name, "path": str(f), "ext": f.suffix.lower()[1:],
                            "fields": form_fields(f)})
        return out

    def add(self, paths: list[str]) -> list[str]:
        self.folder.mkdir(parents=True, exist_ok=True)
        added, bad = [], []
        for p in paths or []:
            src = Path(p)
            if not src.is_file():
                continue
            if src.suffix.lower() not in FORM_EXT:
                bad.append(src.name)
                continue
            dest = self.folder / src.name
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)           # 원본은 그대로 두고 사본을 보관
            added.append(src.stem)
        if bad and not added:
            raise ValueError("HWPX·DOCX·TXT 서식만 올릴 수 있습니다 (HWP는 한글에서 'HWPX로 저장' 후 올려 주세요): "
                             + ", ".join(bad[:3]))
        return added

    def delete(self, name: str) -> None:
        for f in self.folder.glob("*"):
            if f.stem == name and f.suffix.lower() in FORM_EXT:
                f.unlink()
                return
        raise ValueError("서식을 찾을 수 없습니다")

    def path(self, name: str) -> Path | None:
        return next((f for f in self.folder.glob("*") if f.stem == name and f.suffix.lower() in FORM_EXT), None) \
            if self.folder.exists() else None

    def match(self, draft_name: str) -> str:
        """초안 이름('출장 복명서')에 맞는 기관 서식 이름 (없으면 '')."""
        from .attach import name_score

        def core(s: str) -> str:
            return re.sub(r"(양식|서식|\(.*?\)|\[.*?\]|_?\d{6,8}|기관|공단|본청|최종|수정본?|v\d+)", "", s)
        best, score = "", 0.0
        for f in self.list():
            sc = max(name_score(core(draft_name), core(f["name"])), name_score(core(f["name"]), core(draft_name)))
            if sc > score:
                best, score = f["name"], sc
        return best if score >= 0.55 else ""

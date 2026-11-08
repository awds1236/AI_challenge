"""보고서 양식(HWPX) 자동 작성.

사용자가 넣은 한글 보고서 양식(.hwpx)의 모양은 그대로 두고 내용만 바꿔 새 보고서를 만든다.

- 양식에서 제목 상자·요약 상자, □(대제목)·○(항목)·-(세부)·※(참고) 문단, 본문 표의 '모양 견본'을 찾는다.
- 내용(개요)은 공문 분석 결과로 규칙 기반으로 만들거나, 로컬 AI가 개조식으로 작성한다.
- 견본 문단을 복제해 글자만 바꾸므로 글꼴·크기·들여쓰기·줄 간격이 양식과 같다.
- 글자를 바꾼 문단은 줄 배치 정보(linesegarray)를 지워 한글이 열 때 다시 계산하게 한다.

HWPX는 ZIP 안에 XML(Contents/section0.xml 등)이 든 형식이다. 바이너리 HWP는 지원하지 않는다
(한글에서 '다른 이름으로 저장 → HWPX'로 저장하면 된다).
"""
from __future__ import annotations

import copy
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

try:
    from lxml import etree
    HAVE_LXML = True
except ImportError:  # lxml이 없어도 Python 기본 XML 기능으로 동작한다
    import xml.etree.ElementTree as etree  # type: ignore[no-redef]
    HAVE_LXML = False

_XML_DECL = re.compile(rb"^\s*<\?xml[^>]*\?>")
_ROOT_TAG = re.compile(rb"<(?![?!])[^>]*>")


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _parse(data: bytes):
    """XML을 읽는다. 기본 XML 기능을 쓸 때는 원래 접두어(hp:, hs: 등)를 등록해 그대로 쓰게 한다."""
    if HAVE_LXML:
        return etree.parse(io.BytesIO(data), etree.XMLParser(remove_blank_text=False, huge_tree=True))
    for _ev, (prefix, uri) in etree.iterparse(io.BytesIO(data), events=("start-ns",)):
        if prefix and not re.fullmatch(r"ns\d+", prefix):
            try:
                etree.register_namespace(prefix, uri)
            except ValueError:
                pass
    return etree.ElementTree(etree.fromstring(data))


def _serialize(tree, original: bytes) -> bytes:
    """XML을 쓴다. 원본의 XML 선언과 루트 태그(이름공간 선언 전부)를 그대로 살린다."""
    if HAVE_LXML:
        return etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=tree.docinfo.standalone)
    body = etree.tostring(tree.getroot(), encoding="unicode").encode("utf-8")
    decl = _XML_DECL.match(original)
    head = decl.group(0).strip() if decl else b'<?xml version="1.0" encoding="UTF-8"?>'
    m_orig = _ROOT_TAG.search(original, decl.end() if decl else 0)
    m_new = _ROOT_TAG.search(body)
    if m_orig and m_new and not m_orig.group(0).endswith(b"/>"):
        kept = m_orig.group(0) + body[m_new.end():]   # 쓰지 않는 이름공간 선언도 원본대로 남긴다
        try:
            etree.fromstring(kept)
            body = kept
        except etree.ParseError:
            pass                                      # 원본 루트로 바꿀 수 없으면 기본 출력 그대로
    return head + body


def _insert_after(parent, anchor, el) -> None:
    parent.insert(list(parent).index(anchor) + 1, el)

SECTION = "Contents/section0.xml"

# 문단 앞 기호 → 수준. 0: 대제목, 1: 항목, 2: 세부, 3: 세세부, 9: 참고(※)
_MARKERS = [
    (0, ("□", "■", "◆", "◇", "▣", "Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ")),
    (1, ("○", "ㅇ", "●", "◦", "❍", "◎")),
    (2, ("-", "―", "–", "—", "‐")),
    (3, ("․", "·", "•", "∙", "ㆍ")),
    (9, ("※", "*")),
]
DEFAULT_MARK = {0: "□", 1: "○", 2: "-", 3: "․", 9: "※"}


class ReportError(RuntimeError):
    pass


def builtin_template() -> Path | None:
    """프로그램에 들어 있는 기본 보고서 양식 (양식을 따로 넣지 않아도 바로 쓸 수 있게)."""
    p = Path(__file__).resolve().parent / "assets" / "기본_보고서_양식.hwpx"
    return p if p.exists() else None


def _L(e) -> str:
    return _local(e.tag)


def _kids(e, name: str) -> list:
    return [c for c in e if _L(c) == name]


def _drop_lineseg(p) -> None:
    for c in list(p):
        if _L(c) == "linesegarray":
            p.remove(c)


def _has_tbl(p) -> bool:
    return any(_L(x) == "tbl" for x in p.iter())


def _own_text(p) -> str:
    """문단 자신의 글자 (안에 든 표의 글자는 빼고)."""
    out = []
    for r in _kids(p, "run"):
        for t in _kids(r, "t"):
            out.append("".join(t.itertext()))
    return "".join(out)


def _level(text: str) -> tuple[int, str] | None:
    s = text.lstrip()
    if not s:
        return None
    for lv, marks in _MARKERS:
        for m in marks:
            if s.startswith(m):
                if m == "o" or (lv == 2 and len(s) > 1 and s[1].isdigit()):
                    continue      # '-1' 같은 숫자는 기호가 아니다
                return lv, m
    if re.match(r"o\s", s):       # 영문 o를 ○ 대신 쓰는 양식
        return 1, "o"
    return None


# ---------------------------------------------------------------- 견본 문단
@dataclass
class Proto:
    """한 수준의 견본 문단과 글자 모양(charPr) 배치."""
    p: object
    level: int
    marker: str
    prefix: str            # 기호 앞뒤 공백까지 (예: '  - ')
    cp_mark: str           # 기호 글자 모양
    cp_open: str           # '(' 글자 모양
    cp_head: str           # 소제목 글자 모양
    cp_close: str          # ')' 글자 모양
    cp_body: str           # 본문 글자 모양
    has_head: bool

    @classmethod
    def from_p(cls, p, level: int, marker: str) -> "Proto":
        runs = _kids(p, "run")
        pos: list[str] = []          # 글자마다 charPr
        text = ""
        for r in runs:
            t = "".join("".join(x.itertext()) for x in _kids(r, "t"))
            text += t
            pos += [r.get("charPrIDRef", "0")] * len(t)
        i = len(text) - len(text.lstrip())
        j = i + len(marker)
        k = j
        while k < len(text) and text[k] == " ":
            k += 1
        cp = lambda n: pos[min(max(n, 0), len(pos) - 1)] if pos else (runs[0].get("charPrIDRef", "0") if runs else "0")  # noqa: E731
        has_head = k < len(text) and text[k] == "("
        close = text.find(")", k) if has_head else -1
        body_at = close + 1 if close > 0 else k
        while body_at < len(text) and text[body_at] == " ":
            body_at += 1
        return cls(p=p, level=level, marker=marker, prefix=text[:k] if k > j else text[:j] + " ",
                   cp_mark=cp(i), cp_open=cp(k), cp_head=cp(k + 1), cp_close=cp(close) if close > 0 else cp(k),
                   cp_body=cp(body_at if body_at < len(text) else len(text) - 1), has_head=has_head)

    def build(self, text: str, head: str = "", marker: str | None = None):
        """견본을 복제해 [기호][(소제목)] 본문 문단을 만든다."""
        p = copy.deepcopy(self.p)
        _drop_lineseg(p)
        runs = _kids(p, "run")
        proto_run = runs[0] if runs else None
        for r in runs:
            p.remove(r)
        prefix = self.prefix if marker is None else self.prefix.replace(self.marker, marker, 1)
        parts: list[tuple[str, str]] = [(self.cp_mark, prefix)]
        if head:
            parts += [(self.cp_open, "("), (self.cp_head, head), (self.cp_close, ")"), (self.cp_body, " " + text)]
        else:
            parts.append((self.cp_body, text))
        merged: list[list[str]] = []
        for cpid, s in parts:
            if merged and merged[-1][0] == cpid:
                merged[-1][1] += s
            else:
                merged.append([cpid, s])
        for cpid, s in merged:
            p.append(_make_run(proto_run, p, cpid, s))
        return p


def _make_run(proto_run, p, cpid: str, text: str):
    ns = _ns(p.tag)
    if proto_run is not None:
        r = copy.deepcopy(proto_run)
        for c in list(r):
            r.remove(c)
        r.text = None
    else:
        r = etree.SubElement(p, f"{{{ns}}}run")
        p.remove(r)
    r.set("charPrIDRef", cpid)
    t = etree.SubElement(r, f"{{{ns}}}t")
    t.text = text
    return r


def _blank_from(p):
    """빈 줄 견본 (글자만 비운 복제)."""
    b = copy.deepcopy(p)
    _drop_lineseg(b)
    for r in _kids(b, "run"):
        for t in _kids(r, "t"):
            r.remove(t)
    return b


# ---------------------------------------------------------------- 표
def _cells(tbl) -> list[list]:
    return [[tc for tc in _kids(tr, "tc")] for tr in _kids(tbl, "tr")]


def set_cell_text(tc, text: str) -> None:
    """칸의 첫 글자 자리에 text를 넣고 나머지 글자는 비운다 (칸 서식은 유지)."""
    ps = [p for p in tc.iter() if _L(p) == "p"]
    first = True
    for p in ps:
        for r in _kids(p, "run"):
            for t in _kids(r, "t"):
                if first:
                    for c in list(t):
                        t.remove(c)
                    t.text = text
                    first = False
                else:
                    r.remove(t)
        _drop_lineseg(p)
    if first and ps:                       # 글자 자리가 없는 빈 칸
        p = ps[0]
        runs = _kids(p, "run")
        ns = _ns(p.tag)
        r = runs[0] if runs else etree.SubElement(p, f"{{{ns}}}run")
        t = etree.SubElement(r, f"{{{ns}}}t")
        t.text = text


def _keep_symbol(old: str, new: str) -> str:
    """양식 칸 앞의 장식 기호(▹, ◈ 등)는 살린다."""
    m = re.match(r"^\s*([^\w\s\[\(「<])\s*", old or "")
    if m and not new.startswith(m.group(1)):
        return m.group(0) + new
    return new


def fill_table(tbl_p, rows: list[list[str]]):
    """표 견본을 복제해 rows(첫 줄은 머리글)로 채운다. 행 수가 다르면 마지막 행을 복제/삭제."""
    p = copy.deepcopy(tbl_p)
    _drop_lineseg(p)
    tbl = next(x for x in p.iter() if _L(x) == "tbl")
    trs = _kids(tbl, "tr")
    if not trs:
        return p
    data_proto = trs[1] if len(trs) > 1 else trs[0]
    for tr in trs[1:]:
        tbl.remove(tr)
    want = rows[1:] if len(rows) > 1 else []
    anchor = trs[0]
    for i, _ in enumerate(want, 1):
        tr = copy.deepcopy(data_proto)
        for ca in tr.iter():
            if _L(ca) == "cellAddr":
                ca.set("rowAddr", str(i))
        _insert_after(tbl, anchor, tr)
        anchor = tr
    tbl.set("rowCnt", str(1 + len(want)))
    # 표 전체 높이 = 행 높이 합 (한글이 열 때 다시 맞추지만, 값이 크게 틀리면 빈 공간이 생긴다)
    total = 0
    for tr in _kids(tbl, "tr"):
        hs = [int(x.get("height", "0")) for x in tr.iter() if _L(x) == "cellSz"]
        total += max(hs) if hs else 0
    for sz in _kids(tbl, "sz"):
        if total:
            sz.set("height", str(total))
    for r, tr in enumerate(_kids(tbl, "tr")):
        vals = list(rows[r]) if r < len(rows) else []
        tcs = _kids(tr, "tc")
        if len(vals) > len(tcs) and tcs:   # 칸보다 값이 많으면 마지막 칸에 합친다
            vals = vals[:len(tcs) - 1] + [" / ".join(v for v in vals[len(tcs) - 1:] if v)]
        vals += [""] * (len(tcs) - len(vals))
        for tc, v in zip(tcs, vals):
            set_cell_text(tc, (" " + v) if r > 0 and tcs.index(tc) > 0 and v else v)
    return p


# ---------------------------------------------------------------- 양식 분석
@dataclass
class Template:
    path: Path
    files: dict[str, bytes]
    order: list[str]
    tree: object
    sec: object
    header: list                      # 첫 □ 앞 문단들 (제목·요약 상자 등, 그대로 둔다)
    tail: list                        # 본문 뒤에 남길 문단 (붙임·끝 표시 등)
    boxes: list                       # 머리 부분의 1칸 표 (제목, 요약 순)
    title_p: object | None            # 상자가 없을 때 제목 문단
    protos: dict[int, Proto] = field(default_factory=dict)
    table: object | None = None
    gap_after_heading: object | None = None
    gap_between_items: object | None = None
    gap_before_heading: object | None = None
    headings: list[str] = field(default_factory=list)   # 양식에 있던 □ 제목 (AI 참고용)

    def info(self) -> dict:
        return {"name": self.path.stem, "path": str(self.path),
                "levels": sorted(k for k in self.protos), "has_table": self.table is not None,
                "title_box": bool(self.boxes), "summary_box": len(self.boxes) > 1, "headings": self.headings}


def _read_zip(path: Path) -> tuple[dict[str, bytes], list[str]]:
    try:
        with zipfile.ZipFile(path) as z:
            order = z.namelist()
            return {n: z.read(n) for n in order}, order
    except zipfile.BadZipFile as e:
        raise ReportError("HWPX 파일이 아닙니다. 한글에서 '다른 이름으로 저장 → HWPX(*.hwpx)'로 저장해 넣어 주세요.") from e


def load_template(path: str | Path) -> Template:
    path = Path(path)
    if path.suffix.lower() == ".hwp":
        raise ReportError("HWP 파일은 지원하지 않습니다. 한글에서 '다른 이름으로 저장 → HWPX'로 저장해 넣어 주세요.")
    files, order = _read_zip(path)
    if SECTION not in files:
        raise ReportError("양식에서 본문(Contents/section0.xml)을 찾지 못했습니다.")
    try:
        tree = _parse(files[SECTION])
    except etree.ParseError as e:
        raise ReportError(f"양식 본문을 읽지 못했습니다: {e}") from e
    sec = tree.getroot()
    if _L(sec) != "sec":
        sec = next((e for e in sec.iter() if _L(e) == "sec"), None)
        if sec is None:
            raise ReportError("양식 본문 구조를 해석하지 못했습니다.")
    kids = [c for c in sec if _L(c) == "p"]
    info = []
    for p in kids:
        txt = _own_text(p)
        info.append({"p": p, "text": txt, "tbl": _has_tbl(p), "lv": _level(txt), "blank": not txt.strip() and not _has_tbl(p)})
    first = next((i for i, x in enumerate(info) if x["lv"] and x["lv"][0] == 0), None)
    if first is None:
        first = next((i for i, x in enumerate(info) if x["lv"]), None)
    if first is None:
        raise ReportError("양식에서 □, ○ 같은 항목 기호를 찾지 못했습니다. 개조식 보고서 양식을 넣어 주세요.")
    last = max(i for i, x in enumerate(info) if x["lv"] or (x["tbl"] and i >= first))
    t = Template(path=path, files=files, order=order, tree=tree, sec=sec,
                 header=kids[:first], tail=[x["p"] for x in info[last + 1:] if not x["blank"]],
                 boxes=[], title_p=None)
    for x in info[:first]:
        for tbl in (e for e in x["p"].iter() if _L(e) == "tbl"):
            if tbl.get("rowCnt") == "1" and tbl.get("colCnt") == "1":
                t.boxes.append(tbl)
    if not t.boxes:
        t.title_p = next((x["p"] for x in info[:first] if x["text"].strip()), None)
    body = info[first:last + 1]
    for i, x in enumerate(body):
        if x["lv"]:
            lv, mk = x["lv"]
            if lv not in t.protos:
                t.protos[lv] = Proto.from_p(x["p"], lv, mk)
            if lv == 0:
                t.headings.append(re.sub(r"^\s*\S\s*", "", x["text"]).strip()[:30])
        elif x["tbl"] and t.table is None:
            tbls = [e for e in x["p"].iter() if _L(e) == "tbl"]
            if tbls and int(tbls[0].get("colCnt", "1")) >= 2:
                t.table = x["p"]
        elif x["blank"]:
            prev = body[i - 1]["lv"] if i > 0 else None
            nxt = body[i + 1]["lv"] if i + 1 < len(body) else None
            if prev and prev[0] == 0 and t.gap_after_heading is None:
                t.gap_after_heading = x["p"]
            elif nxt and nxt[0] == 0 and t.gap_before_heading is None:
                t.gap_before_heading = x["p"]
            elif prev and nxt and prev[0] >= 1 and nxt[0] >= 1 and t.gap_between_items is None:
                t.gap_between_items = x["p"]
    if 0 not in t.protos and 1 in t.protos:          # □ 없이 ○부터 쓰는 양식
        t.protos[0] = t.protos[1]
    if 1 not in t.protos:
        t.protos[1] = t.protos.get(2) or t.protos[0]
    return t


# ---------------------------------------------------------------- 채우기
def _proto(t: Template, level: int) -> tuple[Proto, str | None]:
    """수준에 맞는 견본. 양식에 없는 수준은 가까운 견본에 기호만 바꿔 쓴다."""
    if level in t.protos:
        return t.protos[level], None
    for alt in ((2, 1) if level in (3, 9) else (1, 0)):
        if alt in t.protos:
            return t.protos[alt], DEFAULT_MARK[level]
    return t.protos[1], DEFAULT_MARK.get(level)


def clean_outline(o: dict) -> dict:
    """AI·규칙이 만든 개요를 안전한 모양으로 정리한다."""
    def s(v, n=300):
        return re.sub(r"\s+", " ", str(v or "")).strip()[:n]

    def strip_mark(v):   # 내용 앞에 기호를 또 붙인 경우 제거
        return re.sub(r"^[□■◆◇○ㅇ●◦\-―–—․·•※*\s]+", "", v)
    out = {"title": strip_mark(s(o.get("title"), 80)), "summary": strip_mark(s(o.get("summary"), 300)), "sections": []}
    for sec in (o.get("sections") or [])[:8]:
        if not isinstance(sec, dict) or not s(sec.get("heading")):
            continue
        items = []
        for it in (sec.get("items") or [])[:8]:
            if isinstance(it, str):
                it = {"text": it}
            if not isinstance(it, dict) or not (s(it.get("text")) or s(it.get("head"))):
                continue
            subs = []
            for sb in (it.get("subs") or [])[:6]:
                if isinstance(sb, str):
                    sb = {"text": sb}
                if isinstance(sb, dict) and s(sb.get("text")):
                    subs.append({"head": strip_mark(s(sb.get("head"), 30)), "text": strip_mark(s(sb.get("text")))})
            notes = [strip_mark(s(n)) for n in (it.get("notes") or [])[:3] if s(n)]
            items.append({"head": strip_mark(s(it.get("head"), 30)).strip("()"), "text": strip_mark(s(it.get("text"))),
                          "subs": subs, "notes": notes})
        table = None
        tb = sec.get("table")
        if isinstance(tb, list) and len(tb) >= 2 and all(isinstance(r, list) for r in tb):
            table = [[s(c, 120) for c in r][:6] for r in tb[:12]]
        out["sections"].append({"heading": strip_mark(s(sec.get("heading"), 40)), "items": items, "table": table})
    return out


def fill(t: Template, outline: dict, dept: str = "", today: date | None = None) -> bytes:
    """개요를 양식에 채워 새 HWPX 파일 내용을 돌려준다."""
    o = clean_outline(outline)
    if not o["sections"]:
        raise ReportError("보고서에 넣을 내용이 없습니다.")
    tree = copy.deepcopy(t.tree)
    # 복제한 트리에서 같은 위치의 요소를 다시 찾는다 (원본 양식 객체는 그대로 둔다)
    src_root, dst_root = t.tree.getroot(), tree.getroot()
    path_of = {e: i for i, e in enumerate(src_root.iter())}
    dst_all = list(dst_root.iter())
    mapped = lambda e: dst_all[path_of[e]] if e is not None else None  # noqa: E731
    sec = mapped(t.sec)
    header = [mapped(p) for p in t.header]
    tail = [mapped(p) for p in t.tail]

    # ① 머리 부분: 제목·요약 상자, 날짜
    title = o["title"] or o["sections"][0]["heading"]
    boxes = [mapped(b) for b in t.boxes]
    if boxes:
        old = "".join(boxes[0].itertext()).strip()
        if dept and old.startswith("[") and not title.startswith("["):
            title = f"[{dept}] {title}"
        for tc in (x for x in boxes[0].iter() if _L(x) == "tc"):
            set_cell_text(tc, title)
            break
        if len(boxes) > 1:
            for tc in (x for x in boxes[1].iter() if _L(x) == "tc"):
                old = "".join(tc.itertext())
                set_cell_text(tc, _keep_symbol(old, o["summary"] or title))
                break
    elif t.title_p is not None:
        tp = mapped(t.title_p)
        runs = _kids(tp, "run")
        for r in runs:
            for tt in _kids(r, "t"):
                tt.text = ""
        if runs:
            ts = _kids(runs[0], "t")
            if ts:
                ts[0].text = title
        _drop_lineseg(tp)
    today = today or date.today()
    for p in header:            # 머리의 날짜(2026. 7. 1.)는 오늘 날짜로
        for x in p.iter():
            if _L(x) == "t" and x.text and re.search(r"20\d{2}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?", x.text):
                x.text = re.sub(r"20\d{2}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?",
                                f"{today.year}. {today.month}. {today.day}.", x.text)
                _drop_lineseg(p)

    # ② 본문: 견본 문단으로 새로 만든다
    remap = lambda p: mapped(p) if p is not None else None  # noqa: E731
    gap_h, gap_i, gap_b = remap(t.gap_after_heading), remap(t.gap_between_items), remap(t.gap_before_heading)
    tbl_proto = remap(t.table)
    protos = {}
    for lv in (0, 1, 2, 3, 9):
        pr, mk = _proto(t, lv)
        protos[lv] = (Proto(**{**pr.__dict__, "p": mapped(pr.p)}), mk)

    def para(lv: int, text: str, head: str = ""):
        pr, mk = protos[lv]
        if head and not pr.has_head and lv == 0:
            text, head = f"{head} {text}", ""
        return pr.build(text, head, mk)

    body = []
    for si, s in enumerate(o["sections"]):
        if si and gap_b is not None:
            body.append(_blank_from(gap_b))
        body.append(para(0, s["heading"]))
        if gap_h is not None:
            body.append(_blank_from(gap_h))
        for ii, it in enumerate(s["items"]):
            if ii and gap_i is not None:
                body.append(_blank_from(gap_i))
            body.append(para(1, it["text"], it["head"]))
            for sb in it["subs"]:
                body.append(para(2, sb["text"], sb["head"]))
            for n in it["notes"]:
                body.append(para(9, n))
        if s.get("table"):
            if tbl_proto is not None:
                body.append(fill_table(tbl_proto, s["table"]))
            else:                       # 양식에 표가 없으면 ○ 항목으로 푼다
                for row in s["table"][1:]:
                    body.append(para(1, " / ".join(c for c in row[1:] if c), row[0]))

    # 첫 문단(구역 정의 secPr)이 본문이면 그 정의만 남긴 빈 문단을 맨 앞에 둔다
    keep = set(id(p) for p in header + tail)
    secpr_holder = None
    for p in [c for c in sec if _L(c) == "p"]:
        if id(p) not in keep and any(_L(x) == "secPr" for x in p.iter()) and secpr_holder is None:
            secpr_holder = copy.deepcopy(p)
            for r in _kids(secpr_holder, "run"):
                if not any(_L(x) in ("secPr", "ctrl") for x in r.iter()):
                    secpr_holder.remove(r)
                else:
                    for tt in _kids(r, "t"):
                        r.remove(tt)
            _drop_lineseg(secpr_holder)
    for c in [c for c in sec if _L(c) == "p"]:
        sec.remove(c)
    for p in ([secpr_holder] if secpr_holder is not None else []) + header + body + tail:
        sec.append(p)

    xml = _serialize(tree, t.files[SECTION])
    preview = "\r\n".join(_own_text(p) or " ".join(x.text or "" for x in p.iter() if _L(x) == "t")
                          for p in [c for c in sec if _L(c) == "p"])
    return _pack(t, {SECTION: xml, "Preview/PrvText.txt": preview.encode("utf-8")})


def _pack(t: Template, replace: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        names = t.order
        if "mimetype" in names:     # mimetype은 맨 앞, 압축하지 않음 (HWPX/OCF 규칙)
            z.writestr(zipfile.ZipInfo("mimetype"), t.files["mimetype"], compress_type=zipfile.ZIP_STORED)
        for n in names:
            if n == "mimetype":
                continue
            if n == "Preview/PrvText.txt" and n not in replace:
                continue
            data = replace.get(n, t.files[n])
            z.writestr(n, data, compress_type=zipfile.ZIP_DEFLATED)
    data = buf.getvalue()
    with zipfile.ZipFile(io.BytesIO(data)) as z:   # 검증
        if z.testzip() is not None:
            raise ReportError("보고서 파일을 만드는 중 오류가 났습니다.")
        etree.fromstring(z.read(SECTION))
    return data


def outline_text(o: dict) -> str:
    """화면 미리보기용 개조식 텍스트."""
    o = clean_outline(o)
    lines = [o["title"]]
    if o["summary"]:
        lines.append("▹ " + o["summary"])
    for s in o["sections"]:
        lines += ["", "□ " + s["heading"]]
        for it in s["items"]:
            lines.append(" ○ " + (f"({it['head']}) " if it["head"] else "") + it["text"])
            lines += ["   - " + (f"({sb['head']}) " if sb["head"] else "") + sb["text"] for sb in it["subs"]]
            lines += ["     ※ " + n for n in it["notes"]]
        if s.get("table"):
            lines += ["   | " + " | ".join(r) for r in s["table"]]
    return "\n".join(lines)


# ---------------------------------------------------------------- 내용(개요) 만들기
def _md(d: str) -> str:
    try:
        y, m, dd = (int(x) for x in d.split("-"))
        wd = "월화수목금토일"[date(y, m, dd).weekday()]
        return f"{m}. {dd}.({wd})"
    except (ValueError, AttributeError):
        return d


def plausible_title(title: str, reference: str, headings: list | None = None) -> bool:
    """AI가 낸 보고서 제목이 쓸 만한지: 비어 있지 않고, 양식 소제목을 늘어놓은 것이 아니며,
    공문 제목(규칙 제목)과 두 글자 이상 낱말을 하나라도 함께 쓴다."""
    t = (title or "").strip()
    if len(t) < 4:
        return False
    heads = set()
    for h in headings or []:
        text = h.get("text", "") if isinstance(h, dict) else str(h)
        heads.update(w for w in re.split(r"[\s,·/]+", re.sub(r"^[□○\-※\s]+", "", text)) if len(w) >= 2)
    words = [w for w in re.split(r"[\s,·/()「」]+", t) if len(w) >= 2]
    if words and heads and sum(w in heads for w in words) >= len(words) * 0.6:
        return False                                  # '추진 배경, 주요 내용, 향후 계획'
    ref = {w for w in re.split(r"[\s,·/()「」\[\]]+", reference or "") if len(w) >= 2}
    return not ref or any(w in ref or any(w in r or r in w for r in ref) for w in words)


def outline_from_notice(notice: dict, purpose: str = "") -> dict:
    """공문 분석 결과로 규칙 기반 보고서 개요를 만든다 (AI 없이도 동작)."""
    a = notice.get("analysis") or {}
    name = a.get("folder_name") or notice.get("title") or "공문"
    title = purpose.strip() or f"{name} 관련 보고"
    overview = [{"head": "공문명", "text": notice.get("title") or name}]
    ev = a.get("event") or {}
    for k, label in (("name", "행사명"), ("date", "일시"), ("place", "장소")):
        if ev.get(k):
            overview.append({"head": label, "text": ev[k]})
    target = next((v for k, v in (a.get("fields") or {}).items() if k.endswith("대상")), "")
    if target:
        overview.append({"head": "대상", "text": target})
    if a.get("contact"):
        overview.append({"head": "문의처", "text": a["contact"]})
    sections = [{"heading": "개요", "items": overview}]
    dl = a.get("deadlines") or []
    subs = a.get("submissions") or []
    # 날짜에도 요일 괄호가 있어 '(11. 20.(금))'처럼 겹치지 않게, 머리는 '(기한)'으로 두고 날짜는 본문에 쓴다
    items = [{"head": "기한", "text": f"{_md(d['date'])}{(' ' + d['time']) if d.get('time') else ''}까지 {d['what']}"}
             for d in dl[:4]]
    for s in subs[:4]:
        extra = ", ".join(x for x in (s.get("how"), s.get("to")) if x)
        items.append({"head": "제출물", "text": s["item"] + (f" ({extra})" if extra else "")})
    if items:
        sec = {"heading": "제출 기한 및 제출물", "items": items}
        if len(dl) >= 2:
            sec["table"] = [["기한", "할 일"]] + [[_md(d["date"]) + (" " + d["time"] if d.get("time") else ""), d["what"]]
                                               for d in dl[:6]]
            sec["items"] = [it for it in items if it["head"] == "제출물"] or items[:1]
        sections.append(sec)
    acts = [x for x in (a.get("actions") or []) if x][:5]
    if acts:
        sections.append({"heading": "조치 계획", "items": [{"text": x} for x in acts]})
    # 요약 상자는 한 문장: 둘째 줄(대상 등)은 개요 항목으로 옮겼다
    summary = (a.get("summary") or "").splitlines()[0] if a.get("summary") else ""
    return {"title": title, "summary": summary, "sections": sections}


def outline_from_text(material: str, purpose: str = "") -> dict:
    """AI 없이 자유 자료를 개조식으로 옮긴다 (줄 → ○ 항목)."""
    lines = [re.sub(r"^\s*([0-9]+[.)]|[가-하][.)]|[□○ㅇ\-―•·※*])\s*", "", l).strip()
             for l in material.splitlines()]
    lines = [l for l in lines if l]
    if not lines:
        raise ReportError("자료 내용을 입력해 주세요.")
    title = purpose.strip() or lines[0][:60]
    body = lines[1:] if not purpose.strip() and len(lines) > 1 else lines
    return {"title": title, "summary": "", "sections": [{"heading": "주요 내용", "items": [{"text": l} for l in body[:12]]}]}


OUTLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "sections": {"type": "array", "items": {"type": "object", "properties": {
            "heading": {"type": "string"},
            "items": {"type": "array", "items": {"type": "object", "properties": {
                "head": {"type": "string"}, "text": {"type": "string"},
                "subs": {"type": "array", "items": {"type": "object", "properties": {
                    "head": {"type": "string"}, "text": {"type": "string"}}, "required": ["text"]}}},
                "required": ["head", "text"]}}},
            "required": ["heading", "items"]}},
    },
    "required": ["title", "summary", "sections"],
}

OUTLINE_SYSTEM = """당신은 공공기관 보고서를 쓰는 서무 담당자입니다. 주어진 자료로 1페이지 개조식 보고서의 개요를 JSON으로 쓰세요.
- title: 보고서 제목 (30자 이내, '~ 계획 보고', '~ 결과 보고', '~ 관련 보고' 등)
- summary: 보고 요지 한 문장 (~하고자 함 / ~임)
- sections: 대제목(□) 3~4개. 각 대제목의 items(○)는 2~3개.
  item의 head는 괄호 안에 넣을 2~8자 소제목(예: 추진 배경, 제출 기한), text는 한 줄 내용.
  subs(-)는 꼭 필요할 때만 0~2개.
- 문장은 개조식 명사형으로 끝내세요 (~함, ~임, ~ 예정, ~ 필요). 기호(□, ○, -)는 쓰지 마세요.
- 자료에 없는 사실·숫자·날짜는 만들지 마세요. 짧고 정확하게 쓰세요."""


def notice_material(notice: dict, limit: int = 1800) -> str:
    """AI에게 줄 공문 자료 (분석 결과 + 본문 앞부분). 입력이 짧을수록 빠르다."""
    a = notice.get("analysis") or {}
    lines = [f"공문 제목: {notice.get('title', '')}"]
    if a.get("summary"):
        lines.append(f"요약: {a['summary']}")
    for d in (a.get("deadlines") or [])[:5]:
        lines.append(f"기한: {d['date']} {d.get('time') or ''} {d['what']}".strip())
    for s in (a.get("submissions") or [])[:5]:
        lines.append(f"제출물: {s['item']} {s.get('how') or ''} {s.get('to') or ''}".strip())
    ev = a.get("event") or {}
    if ev:
        lines.append("행사: " + ", ".join(f"{k}={v}" for k, v in ev.items()))
    if a.get("contact"):
        lines.append(f"문의처: {a['contact']}")
    body = re.sub(r"\n{2,}", "\n", notice.get("body") or "").strip()
    lines += ["", "[본문 발췌]", body[:limit]]
    return "\n".join(lines)


def ai_outline(client, model: str, material: str, purpose: str, headings: list[str], num_ctx: int) -> dict:
    from .llm import LLMError, extract_json
    ref = f"양식에 있던 대제목(참고): {', '.join(h for h in headings if h)}\n" if headings else ""
    user = (f"{ref}보고 목적: {purpose.strip() or '자료 내용 보고'}\n\n[자료]\n{material.strip()[:3000]}")
    raw = client.chat([{"role": "system", "content": OUTLINE_SYSTEM}, {"role": "user", "content": user}],
                      model, temperature=0.2, num_ctx=num_ctx, fmt=OUTLINE_SCHEMA, max_tokens=900)
    data = extract_json(raw)
    if not isinstance(data, dict) or not data.get("sections"):
        raise LLMError("AI 응답을 해석할 수 없습니다")
    return data

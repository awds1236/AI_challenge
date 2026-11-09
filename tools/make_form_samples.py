"""예시 기관 서식 만들기 (sample_data/forms/) — '기관 서식 채우기' 시연·시험용.

    python tools/make_form_samples.py

- 출장복명서(예시).hwpx : 기본 보고서 양식의 '구분|내용' 표를 늘려 만든 표 서식 (항목 칸 옆 빈칸을 채운다)
- 연가신청서(예시).txt  : {{항목}} 자리표시와 '항목 :' 줄을 쓰는 글자 서식
"""
from __future__ import annotations

import copy
import io
import sys
import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "seomu" / "assets" / "기본_보고서_양식.hwpx"
OUT = ROOT / "sample_data" / "forms"


def L(e):
    return etree.QName(e.tag).localname


def _texts(e):
    return [t for t in e.iter() if L(t) == "t"]


def _set(p_or_tc, text):
    ts = _texts(p_or_tc)
    ts[0].text = text
    for t in ts[1:]:
        t.text = ""
    for p in p_or_tc.iter():
        if L(p) == "p":
            for c in list(p):
                if L(c) == "linesegarray":
                    p.remove(c)


def make_trip_report() -> Path:
    with zipfile.ZipFile(SRC) as z:
        names = z.namelist()
        data = {n: z.read(n) for n in names}
    tree = etree.parse(io.BytesIO(data["Contents/section0.xml"]))
    sec = next(e for e in tree.getroot().iter() if L(e) == "sec")
    kids = list(sec)
    title_p = kids[1]
    table_p = next(k for k in kids if any(L(x) == "tbl" and x.get("rowCnt") == "3" for x in k.iter()))
    for k in kids:
        if k is not title_p and k is not table_p and k is not kids[0]:
            sec.remove(k)
    # 제목 상자: '출장 복명서'
    tts = [t for t in _texts(title_p) if (t.text or "").strip()]
    tts[0].text = "출장 복명서"
    for t in tts[1:]:
        t.text = ""
    for c in list(title_p):
        if L(c) == "linesegarray":
            title_p.remove(c)
    # 표: 항목 | (빈칸) 여러 줄
    tbl = next(x for x in table_p.iter() if L(x) == "tbl" and x.get("rowCnt") == "3")
    rows = [r for r in tbl if L(r) == "tr"]
    head, proto = rows[0], rows[1]
    for r in rows[1:]:
        tbl.remove(r)
    _set([tc for tc in head if L(tc) == "tc"][0], "항  목")
    _set([tc for tc in head if L(tc) == "tc"][1], "내  용")
    labels = ["출장자 성명", "소  속", "출장기간", "출장지", "출장목적", "주요 내용", "결과 및 조치", "여비 정산", "작성일"]
    for i, lab in enumerate(labels, start=1):
        r = copy.deepcopy(proto)
        tcs = [tc for tc in r if L(tc) == "tc"]
        _set(tcs[0], lab)
        _set(tcs[1], "")
        for tc in tcs:
            addr = next(x for x in tc if L(x) == "cellAddr")
            addr.set("rowAddr", str(i))
        tbl.append(r)
    tbl.set("rowCnt", str(len(labels) + 1))
    for sz in tbl:
        if L(sz) == "sz":
            sz.set("height", str(int(sz.get("height", "0")) * (len(labels) + 1) // 3))
    for c in list(table_p):
        if L(c) == "linesegarray":
            table_p.remove(c)
    data["Contents/section0.xml"] = etree.tostring(tree, xml_declaration=True, encoding="UTF-8",
                                                   standalone=tree.docinfo.standalone)
    data["Preview/PrvText.txt"] = b""
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "출장복명서(예시).hwpx"
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), data["mimetype"], compress_type=zipfile.ZIP_STORED)
        for n in names:
            if n != "mimetype":
                z.writestr(n, data[n], compress_type=zipfile.ZIP_DEFLATED)
    return out


def make_leave_form() -> Path:
    out = OUT / "연가신청서(예시).txt"
    out.write_text(
        "연 가 신 청 서\n\n"
        "소속 : {{소속}}\n"
        "성명 : {{성명}}\n"
        "사용 기간 : {{기간}}\n"
        "사유 :\n"
        "업무 대행자 :\n"
        "비상 연락처 : {{연락처}}\n\n"
        "위와 같이 연가를 신청합니다.\n\n"
        "신청일 : {{작성일}}\n"
        "신청인 :            (서명)\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    for p in (make_trip_report(), make_leave_form()):
        print("만듦:", p)

"""시연용 예시 공문 만들기 (sample_data/시연/) — 개발용.

    pip install python-hwpx playwright openpyxl
    python tools/make_demo_data.py

가상의 기관 '한빛시설관리공단'의 공문 2건(본문 + 붙임)과 문서 다듬기용 메모를 만든다.
  1_제출요청 : 본문 PDF + 붙임1 계획(HWPX) + 붙임2 결과 보고서 서식(XLSX)   → 제출 기한·제출물·붙임 연결 시연
  2_교육안내 : 본문 HWPX + 붙임1 참석자 명단 서식(XLSX) + 붙임2 장소 안내도(PDF) → 행사 일시·장소·회신 기한 시연
기관·사람·연락처는 모두 지어낸 것이다 (도메인은 예시용 .example).
"""
from __future__ import annotations

import html
import shutil
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sample_data" / "시연"
ORG = "한빛시설관리공단"
F = "맑은 고딕"

A_TITLE = "2026년 동절기 시설물 안전점검 실시 및 결과 제출 요청"
A_ATT1 = "2026년 동절기 시설물 안전점검 계획"
A_ATT2 = "안전점검 결과 보고서(서식)"
A_BODY = [
    ("수신", "수신자 참조"),
    ("(경유)", ""),
    ("제목", A_TITLE),
    "",
    "1. 관련: 안전관리팀-3402(2026. 11. 6.) 「2026년 동절기 안전관리 대책」",
    "2. 동절기 한파·대설에 대비하여 사업장별 시설물 안전점검을 아래와 같이 실시하오니, 각 부서에서는 소관 시설을 "
    "점검하고 결과를 2026. 11. 27.(금) 18:00까지 안전관리팀으로 제출하여 주시기 바랍니다.",
    "  가. 점검 기간: 2026. 11. 16.(월) ~ 11. 25.(수)",
    "  나. 점검 대상: 전 사업장 전기·가스·소방·난방 설비 및 옥외 시설물",
    "  다. 점검 방법: 붙임 1의 점검 항목에 따라 부서 자체 점검",
    "  라. 제출 자료: 안전점검 결과 보고서(붙임 2 서식) 1부, 지적 사항 조치 사진",
    "  마. 제출 방법: 전자문서 회신 및 담당자 메일(safety@hanbit.example) 송부",
    "3. 점검 중 긴급 보수가 필요한 사항은 즉시 안전관리팀(☎ 042-123-4567)으로 연락하여 주시기 바랍니다.",
    "",
    f"붙임  1. {A_ATT1} 1부.",
    f"      2. {A_ATT2} 1부.  끝.",
]
A_FOOT = ["주무관 김서무    안전관리팀장 박안전    전결 11/09",
          "시행 안전관리팀-3418 (2026. 11. 9.)    접수",
          "우 34123  한빛시 중앙로 100 / https://www.hanbit.example",
          "전화 042-123-4567 / 전송 042-123-4568 / safety@hanbit.example / 공개"]

B_TITLE = "2026년 하반기 청렴·적극행정 교육 참석 안내"
B_ATT1 = "교육 참석자 명단(서식)"
B_ATT2 = "교육 장소 안내도"
B_BODY = [
    ("수신", "수신자 참조"),
    ("(경유)", ""),
    ("제목", B_TITLE),
    "",
    "1. 관련: 감사실-1187(2026. 11. 2.)",
    "2. 공직 가치 확립과 적극행정 문화 확산을 위하여 2026년 하반기 청렴·적극행정 교육을 아래와 같이 실시하오니, "
    "부서별 대상자가 빠짐없이 참석할 수 있도록 협조하여 주시기 바랍니다.",
    "  가. 교육명: 2026년 하반기 청렴·적극행정 교육",
    "  나. 일시: 2026. 11. 25.(수) 14:00 ~ 16:00",
    "  다. 장소: 본사 3층 대회의실",
    "  라. 대상: 전 직원(부서별 2명 이상 필수 참석)",
    "  마. 내용: 청탁금지법 주요 사례, 적극행정 면책 제도 안내",
    "3. 부서별 참석자 명단(붙임 1 서식)을 2026. 11. 20.(금)까지 감사실로 제출하여 주시기 바랍니다.",
    "4. 교육 이수 시간(2시간)은 상시학습 시간으로 인정합니다.",
    "",
    f"붙임  1. {B_ATT1} 1부.",
    f"      2. {B_ATT2} 1부.  끝.",
]
B_FOOT = ["주무관 이청렴    감사실장 최감사    전결 11/09",
          "시행 감사실-1203 (2026. 11. 9.)    접수",
          "우 34123  한빛시 중앙로 100 / https://www.hanbit.example",
          "전화 042-123-4600 / 전송 042-123-4601 / audit@hanbit.example / 공개"]

MEMOS = """문서 다듬기 시연용 메모 — 아래 메모를 '대충 쓴 내용'에 붙여 넣고 형식을 골라 [다듬기]를 누르세요.
(내용 없이 [다듬기]를 누르면 고른 형식의 기본 양식이 나옵니다)

[메일] ─────────────────────────────
동절기 안전점검 결과 제출 요청
점검 기간 11월 16일부터 11월 25일까지
결과 보고서 11월 27일 18시까지 회신해줘
조치 사진도 같이 보내줘
문의는 내선 4567

[공문] ─────────────────────────────
체육관 동절기 운영시간 변경 안내
12월 1일부터 2월 28일까지 평일 운영시간 06:00~21:00으로 변경
주말 운영시간은 기존과 같음
변경 사항 회원 안내문 게시 협조해줘
붙임: 운영시간 변경 안내문, 회원 공지 게시용 포스터

[보고] ─────────────────────────────
체육관 냉난방기 고장 조치 결과 보고
11월 5일 냉난방기 2대 고장 접수
11월 7일 업체 수리 완료 했습니다
수리비 450,000원 집행
12월 중 전체 설비 점검 예정

[메시지] ───────────────────────────
내일 오전 소방훈련 안내
11월 20일(목) 10시 사이렌 울리면 1층 주차장으로 대피
참석 인원 오늘 17시까지 알려줘
"""

README = f"""# 시연용 예시 데이터

가상의 기관 **{ORG}**의 공문 2건과 문서 다듬기용 메모입니다. 기관·사람·연락처는 모두 지어낸 것입니다.

## 1_제출요청 — {A_TITLE}
| 구분 | 파일 |
|---|---|
| 본문 | `[본문] {A_TITLE}.pdf` |
| 붙임 1 | `붙임1. {A_ATT1}.hwpx` |
| 붙임 2 | `붙임2. {A_ATT2}.xlsx` |

공문 수집에서 본문 칸에 PDF를, 붙임 칸에 나머지 두 파일을 올립니다.
기대 결과: 제출 기한 **2026. 11. 27.(금) 18:00**, 제출물 '안전점검 결과 보고서', 붙임 2건 연결.

## 2_교육안내 — {B_TITLE}
| 구분 | 파일 |
|---|---|
| 본문 | `{B_TITLE}.hwpx` |
| 붙임 1 | `붙임1. {B_ATT1}.xlsx` |
| 붙임 2 | `붙임2. {B_ATT2}.pdf` |

기대 결과: 교육 일시 **2026. 11. 25.(수) 14:00**, 장소 본사 3층 대회의실, 명단 제출 기한 **2026. 11. 20.(금)**.

## 문서다듬기_예시메모.txt
메일·공문·보고·메시지 형식별 메모입니다. 같은 메모라도 형식을 바꾸면 짜임이 다르게 나옵니다.

다시 만들기: `python tools/make_demo_data.py` (python-hwpx, playwright, openpyxl 필요)
"""


# ---------------------------------------------------------------- HWPX (python-hwpx)
def _hwpx_notice(path: Path, title: str, body: list, foot: list[str], sender: str) -> None:
    from hwpx import HwpxDocument
    d = HwpxDocument.new()
    org = d.ensure_run_style(bold=True, size=20, font=F)
    lab = d.ensure_run_style(bold=True, size=11, font=F)
    txt = d.ensure_run_style(size=11, font=F)
    ttl = d.ensure_run_style(bold=True, size=12, font=F)
    snd = d.ensure_run_style(bold=True, size=16, font=F)
    small = d.ensure_run_style(size=9, font=F, color="#333333")

    def last():
        return len(d.paragraphs) - 1

    def para(runs, **fmt):
        p = d.add_paragraph("", char_pr_id_ref=runs[0][0], include_run=False)
        for cp, t in runs:
            p.add_run(t, char_pr_id_ref=cp)
        if fmt:
            d.set_paragraph_format(paragraph_index=last(), **fmt)

    para([(org, ORG)], alignment="CENTER", spacing_after_pt=10, bottom_border=True, border_color="#000000")
    for item in body:
        if isinstance(item, tuple):
            k, v = item
            para([(lab, f"{k}  "), (ttl if k == "제목" else txt, v)], line_spacing_percent=160)
        elif not item:
            para([(txt, "")])
        else:
            para([(txt, item)], line_spacing_percent=160)
    para([(txt, "")])
    para([(snd, sender)], alignment="CENTER", spacing_before_pt=16, spacing_after_pt=16)
    for i, f in enumerate(foot):
        para([(small, f)], line_spacing_percent=130, **({"bottom_border": True, "border_color": "#000000"} if i == 0 else {}))
    d.save_to_path(str(path))


def _hwpx_plan(path: Path) -> None:
    from hwpx import HwpxDocument
    d = HwpxDocument.new()
    title = d.ensure_run_style(bold=True, size=16, font=F)
    box = d.ensure_run_style(size=11, font=F)
    h0 = d.ensure_run_style(bold=True, size=13, font=F)
    body = d.ensure_run_style(size=11, font=F)
    bold = d.ensure_run_style(bold=True, size=11, font=F)
    note = d.ensure_run_style(size=10, font=F, color="#444444")

    def last():
        return len(d.paragraphs) - 1

    def para(runs, **fmt):
        p = d.add_paragraph("", char_pr_id_ref=runs[0][0], include_run=False)
        for cp, t in runs:
            p.add_run(t, char_pr_id_ref=cp)
        d.set_paragraph_format(paragraph_index=last(), line_spacing_percent=160, **fmt)

    def onebox(text, cs, fill):
        t = d.add_table(1, 1, char_pr_id_ref=cs)
        t.set_cell_text(0, 0, text)
        t.set_cell_shading(0, 0, fill)

    def grid(rows, widths=None):
        t = d.add_table(len(rows), len(rows[0]), char_pr_id_ref=body)
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                t.set_cell_text(r, c, v)
                if r == 0:
                    t.set_cell_shading(r, c, "#E8EEF7")
        if widths:
            t.set_column_widths(widths)

    onebox(f"[안전관리팀] {A_ATT1}", title, "#DCE6F2")
    para([(body, "")])
    onebox("▹ 한파·대설에 대비해 11. 16.~11. 25. 전 사업장 시설물을 자체 점검하고 11. 27.까지 결과를 제출함", box, "#F7F7F7")
    para([(body, "")])
    para([(h0, "□ 추진 배경")])
    para([(body, " ○ 동절기 한파·대설로 인한 시설물 동파·화재·낙상 사고 예방")])
    para([(body, " ○ 「2026년 동절기 안전관리 대책」(안전관리팀-3402)에 따른 사업장별 자체 점검")])
    para([(h0, "□ 점검 개요")], spacing_before_pt=6)
    grid([["구  분", "내  용"],
          ["점검 기간", "2026. 11. 16.(월) ~ 11. 25.(수)"],
          ["점검 대상", "전 사업장 전기·가스·소방·난방 설비 및 옥외 시설물"],
          ["점검 방법", "부서 자체 점검 (점검표 작성, 지적 사항 사진 첨부)"],
          ["결과 제출", "2026. 11. 27.(금) 18:00까지 안전관리팀"]], [40, 130])
    para([(body, "")])
    para([(h0, "□ 분야별 점검 항목")])
    for k, v in (("(전기)", " 분전반 누전차단기 작동, 전열기구 문어발식 사용 여부"),
                 ("(가스)", " 배관 동파 방지 보온재 상태, 가스누설경보기 작동"),
                 ("(소방)", " 소화기 압력·비치 위치, 피난 통로 적치물"),
                 ("(난방)", " 보일러 가동 상태, 동파 우려 배관 열선 작동"),
                 ("(옥외)", " 제설함·제설제 비치, 경사로 미끄럼 방지 시설")):
        para([(body, " ○ "), (bold, k), (body, v)])
    para([(note, "     ※ 지적 사항은 조치 전·후 사진을 결과 보고서에 붙임")])
    para([(h0, "□ 추진 일정")], spacing_before_pt=6)
    grid([["일  정", "내  용", "담  당"],
          ["11. 9.(월)", "점검 계획 시행", "안전관리팀"],
          ["11. 16. ~ 11. 25.", "부서별 자체 점검", "각 부서"],
          ["11. 27.(금)", "점검 결과 제출", "각 부서 → 안전관리팀"],
          ["12. 4.(금)", "지적 사항 조치 확인", "안전관리팀"]], [40, 80, 50])
    d.save_to_path(str(path))


# ---------------------------------------------------------------- XLSX (openpyxl)
def _xlsx_form(path: Path, title: str, info: list[str], head: list[str], rows: int, widths: list[int]) -> None:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "서식"
    thin = Side(style="thin", color="000000")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    n = len(head)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n)
    ws.cell(1, 1, title).font = Font(name=F, size=16, bold=True)
    ws.cell(1, 1).alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 34
    r = 3
    for line in info:
        ws.cell(r, 1, line).font = Font(name=F, size=11)
        r += 1
    r += 1
    for c, h in enumerate(head, 1):
        cell = ws.cell(r, c, h)
        cell.font = Font(name=F, size=11, bold=True)
        cell.fill = PatternFill("solid", fgColor="E8EEF7")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = box
    for i in range(1, rows + 1):
        for c in range(1, n + 1):
            cell = ws.cell(r + i, c, i if c == 1 else None)
            cell.border = box
            cell.font = Font(name=F, size=11)
            cell.alignment = Alignment(horizontal="center" if c == 1 else "left", vertical="center")
        ws.row_dimensions[r + i].height = 24
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = w
    wb.save(path)


# ---------------------------------------------------------------- PDF (Chromium으로 HTML 인쇄)
CSS = """
@page { size: A4; margin: 22mm 20mm; }
body { font-family: 'Malgun Gothic', 'Noto Sans CJK KR', 'WenQuanYi Zen Hei', sans-serif; font-size: 11.5pt; color: #000; }
.org { text-align: center; font-size: 22pt; font-weight: 700; padding-bottom: 8px; border-bottom: 2px solid #000; margin-bottom: 14px; }
p { margin: 0; line-height: 1.75; white-space: pre-wrap; word-break: keep-all; }
.k { font-weight: 700; display: inline-block; width: 52px; }
.ttl { font-weight: 700; }
.sender { text-align: center; font-size: 17pt; font-weight: 700; margin: 34px 0 26px; letter-spacing: 2px; }
.foot { border-top: 2px solid #000; padding-top: 6px; font-size: 9pt; color: #222; }
.foot p { line-height: 1.6; }
"""


def _notice_html(body: list, foot: list[str], sender: str) -> str:
    out = [f'<div class="org">{ORG}</div>']
    for item in body:
        if isinstance(item, tuple):
            k, v = item
            out.append(f'<p><span class="k">{html.escape(k)}</span><span class="{"ttl" if k == "제목" else ""}">{html.escape(v)}</span></p>')
        else:
            out.append(f"<p>{html.escape(item) or '&nbsp;'}</p>")
    out.append(f'<div class="sender">{html.escape(sender)}</div>')
    out.append('<div class="foot">' + "".join(f"<p>{html.escape(f)}</p>" for f in foot) + "</div>")
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>{"".join(out)}</body></html>'


MAP_HTML = f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}
h1 {{ font-size: 18pt; text-align: center; margin: 0 0 18px; }}
.map {{ position: relative; height: 430px; border: 2px solid #333; border-radius: 6px; background: #fafafa; }}
.b {{ position: absolute; border: 2px solid #333; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-weight: 700; background: #fff; }}
.road {{ position: absolute; background: #d9d9d9; }}
.hl {{ background: #fff2cc; border-color: #c00; color: #c00; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 18px; }} td, th {{ border: 1px solid #333; padding: 7px 10px; text-align: left; }}
th {{ background: #e8eef7; width: 22%; }}
</style></head><body>
<h1>{B_ATT2}</h1>
<div class="map">
  <div class="road" style="left:0;right:0;top:190px;height:46px"></div>
  <div class="road" style="left:300px;width:46px;top:0;bottom:0"></div>
  <div style="position:absolute;left:12px;top:200px;font-size:10pt">중앙로</div>
  <div class="b hl" style="left:390px;top:40px;width:200px;height:120px">본사 (3층 대회의실)</div>
  <div class="b" style="left:40px;top:40px;width:200px;height:110px">한빛시 체육관</div>
  <div class="b" style="left:40px;top:270px;width:200px;height:110px">지하철 시청역 2번 출구</div>
  <div class="b" style="left:390px;top:270px;width:200px;height:110px">본사 주차장 (지하 1~2층)</div>
</div>
<table>
  <tr><th>장소</th><td>{ORG} 본사 3층 대회의실 (한빛시 중앙로 100)</td></tr>
  <tr><th>대중교통</th><td>지하철 시청역 2번 출구에서 도보 5분</td></tr>
  <tr><th>주차</th><td>본사 지하 주차장 이용 (교육 참석자 2시간 무료)</td></tr>
  <tr><th>문의</th><td>감사실 ☎ 042-123-4600</td></tr>
</table>
</body></html>"""


_NODE_PDF = """const { chromium } = require('playwright');
(async () => { const b = await chromium.launch(); const p = await b.newPage();
  await p.goto(process.argv[2]); await p.pdf({ path: process.argv[3], format: 'A4', printBackground: true, preferCSSPageSize: true });
  await b.close(); })();"""


def _pdf(html_text: str, out: Path) -> None:
    """Python playwright가 있으면 그것으로, 없으면 Node playwright로 HTML을 PDF로 인쇄한다."""
    import subprocess
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "page.html"
        src.write_text(html_text, encoding="utf-8")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            js = Path(td) / "pdf.js"
            js.write_text(_NODE_PDF, encoding="utf-8")
            subprocess.run(["node", str(js), src.as_uri(), str(out)], check=True)
            return
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto(src.as_uri())
            pg.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
            b.close()


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    a, b = OUT / "1_제출요청", OUT / "2_교육안내"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    _pdf(_notice_html(A_BODY, A_FOOT, f"{ORG}이사장"), a / f"[본문] {A_TITLE}.pdf")
    _hwpx_plan(a / f"붙임1. {A_ATT1}.hwpx")
    _xlsx_form(a / f"붙임2. {A_ATT2}.xlsx", "2026년 동절기 시설물 안전점검 결과 보고서",
               ["부 서 명 :", "점 검 일 :", "점 검 자 :          (서명)"],
               ["연번", "시설명", "점검 분야", "점검 결과\n(양호/불량)", "지적 사항", "조치 내용", "조치 예정일"],
               12, [6, 20, 12, 13, 28, 28, 13])
    _hwpx_notice(b / f"{B_TITLE}.hwpx", B_TITLE, B_BODY, B_FOOT, f"{ORG}이사장")
    _xlsx_form(b / f"붙임1. {B_ATT1}.xlsx", "2026년 하반기 청렴·적극행정 교육 참석자 명단",
               ["부 서 명 :", "작 성 자 :", "※ 부서별 2명 이상, 2026. 11. 20.(금)까지 감사실 제출"],
               ["연번", "성명", "직급", "부서", "연락처", "비고"], 10, [6, 14, 12, 18, 18, 20])
    _pdf(MAP_HTML, b / f"붙임2. {B_ATT2}.pdf")
    (OUT / "문서다듬기_예시메모.txt").write_text(MEMOS, encoding="utf-8")
    (OUT / "README.md").write_text(README, encoding="utf-8")
    for f in sorted(OUT.rglob("*")):
        if f.is_file():
            print(f"{f.relative_to(ROOT)}  ({f.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

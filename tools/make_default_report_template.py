"""기본 보고서 양식(seomu/assets/기본_보고서_양식.hwpx) 만들기 — 개발용 (pip install python-hwpx).

제목 상자, 요약 상자, □/○/-/※ 개조식 문단, 2칸 표가 든 1페이지 보고서 양식을 만든다.
"""
import sys
import warnings
from pathlib import Path

from hwpx import HwpxDocument

warnings.filterwarnings("ignore", category=DeprecationWarning)
out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "seomu" / "assets" / "기본_보고서_양식.hwpx")
d = HwpxDocument.new()
F = "맑은 고딕"
title = d.ensure_run_style(bold=True, size=16, font=F)
box = d.ensure_run_style(size=11, font=F)
h0 = d.ensure_run_style(bold=True, size=13, font=F)
body = d.ensure_run_style(size=11, font=F)
bold = d.ensure_run_style(bold=True, size=11, font=F)
note = d.ensure_run_style(size=10, font=F, color="#444444")
gap = d.ensure_run_style(size=6, font=F)


def last():
    return len(d.paragraphs) - 1


def para(runs, **fmt):
    p = d.add_paragraph("", char_pr_id_ref=runs[0][0], include_run=False)
    for cp, text in runs:
        p.add_run(text, char_pr_id_ref=cp)
    d.set_paragraph_format(paragraph_index=last(), **fmt)
    return p


def blank(size=gap):
    p = d.add_paragraph("", char_pr_id_ref=size)
    d.set_paragraph_format(paragraph_index=last(), line_spacing_percent=100)
    return p


def onebox(text, cs, fill):
    t = d.add_table(1, 1, char_pr_id_ref=cs)
    t.set_cell_text(0, 0, text)
    t.set_cell_shading(0, 0, fill)
    return t


onebox("[부서명] 보고서 제목", title, "#DCE6F2")
blank()
onebox("▹ 보고 요지를 한 문장으로 적습니다", box, "#F7F7F7")
blank(body)
L = dict(line_spacing_percent=160)
para([(h0, "□ 추진 배경")], spacing_before_pt=4, **L)
blank()
para([(body, " ○ "), (bold, "(소제목)"), (body, " 항목 내용을 한 줄로 적습니다")], **L)
para([(body, "   - "), (bold, "(세부)"), (body, " 세부 내용을 적습니다")], **L)
para([(note, "     ※ 참고 사항을 적습니다")], **L)
blank(body)
para([(h0, "□ 주요 내용")], **L)
blank()
para([(body, " ○ "), (bold, "(소제목)"), (body, " 항목 내용을 적습니다")], **L)
t = d.add_table(3, 2, char_pr_id_ref=body)
t.set_column_widths([25, 75])
for r, (a, b) in enumerate([("구  분", "내  용"), ("항목", " 내용"), ("항목", " 내용")]):
    t.set_cell_text(r, 0, a)
    t.set_cell_text(r, 1, b)
t.set_cell_shading(0, 0, "#DCE6F2")
t.set_cell_shading(0, 1, "#DCE6F2")
blank(body)
para([(h0, "□ 향후 계획")], **L)
blank()
para([(body, " ○ "), (bold, "(일정)"), (body, " 향후 추진 일정을 적습니다")], **L)
out.parent.mkdir(parents=True, exist_ok=True)
d.save_to_path(str(out))
print(out, d.validate())

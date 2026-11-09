"""시연용 예시 공문 10건 만들기 (sample_data/시연/) — 개발용.

    pip install python-hwpx python-docx python-pptx openpyxl pillow
    (+ LibreOffice: .doc·.xls·.ppt·.odt·.ods·.odp·.rtf 변환, Node playwright: PDF·그림)
    python tools/make_demo_data.py

가상의 기관 '한빛시설관리공단'(과 '한빛시청')이 보낸 새 공문 10건. 공문마다 본문 + 붙임으로 이루어지고,
공공기관에서 주고받는 문서 형식을 고르게 쓴다:
  한글 HWPX · PDF(글자/스캔) · Word DOCX·DOC · Excel XLSX·XLS · PowerPoint PPTX·PPT · ODT·ODS·ODP ·
  RTF · TXT(CP949) · CSV · HTML · MHT · EML(첨부 + ZIP) · PNG
기관·사람·연락처·번호는 모두 지어낸 것이다 (메일·홈페이지 주소는 예시용 .example).
"""
from __future__ import annotations

import csv
import html
import shutil
import subprocess
import sys
import tempfile
import warnings
import zipfile
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sample_data" / "시연"
ORG = "한빛시설관리공단"
CITY = "한빛시"
F = "맑은 고딕"
WD = "월화수목금토일"
ADDR = "우 34123  한빛시 중앙로 100 / https://www.hanbit.example"


def d(m: int, dd: int, y: int = 2026) -> str:
    """'2026. 11. 27.(금)' (요일은 계산해서 붙인다)."""
    return f"{y}. {m}. {dd}.({WD[date(y, m, dd).weekday()]})"


def s(m: int, dd: int, y: int = 2026) -> str:
    """'11. 27.(금)'"""
    return f"{m}. {dd}.({WD[date(y, m, dd).weekday()]})"


# ================================================================ 공문 10건
N: list[dict] = [
    {
        "dir": "01_예산요구", "title": "2027년도 부서별 예산 요구서 제출 요청", "body": "hwpx", "dept": "기획예산팀",
        "lines": [
            "1. 관련: 기획예산팀-2207(2026. 10. 15.) 「2027년도 예산 편성 기본 방향」",
            "2. 2027년도 예산 편성을 위하여 부서별 예산 요구서를 아래와 같이 받고자 하오니, 각 부서에서는 붙임 지침에 따라 "
            f"작성하여 {d(11, 27)} 17:00까지 기획예산팀으로 제출하여 주시기 바랍니다.",
            "  가. 요구 대상: 2027년도 경상경비, 사업비, 시설 유지보수비",
            "  나. 작성 방법: 붙임 2 서식의 항목별 산출 근거를 빠짐없이 기재",
            "  다. 제출 자료: 예산 요구서(붙임 2 서식) 1부, 견적서 등 산출 근거 자료",
            "  라. 제출 방법: 전자문서 회신 및 담당자 메일(budget@hanbit.example) 송부",
            "3. 기한 이후 제출된 요구서는 예산 심의에 반영되지 않을 수 있으니 유의하여 주시기 바랍니다.",
        ],
        "att": [("2027년도 예산 편성 지침", "pdf_guide_budget"), ("예산 요구서(서식)", "xlsx_budget")],
        "sign": ("주무관 정예산", "기획예산팀장 한기획", "기획예산팀-2301", "042-123-4210", "budget@hanbit.example"),
        "result": "예산 요구서(XLSX) 서식 채우기 · 보고서 작성 · 할 일 '예산 요구서 제출(11/27 17:00)'",
    },
    {
        "dir": "02_개인정보점검", "title": "2026년 하반기 개인정보 보호 실태 자체점검 실시", "body": "pdf", "dept": "정보보안팀",
        "lines": [
            "1. 관련: 「개인정보 보호법」 제29조 및 공단 개인정보 보호 지침 제18조",
            "2. 개인정보 처리 실태를 점검하여 유출 사고를 예방하고자 하반기 자체점검을 아래와 같이 실시하오니, "
            f"각 부서에서는 점검 결과를 {d(12, 4)}까지 정보보안팀으로 제출하여 주시기 바랍니다.",
            f"  가. 점검 기간: {d(11, 16)} ~ {s(11, 30)}",
            "  나. 점검 대상: 개인정보를 처리하는 전 부서(업무용 PC, 문서 보관함, 회원 관리 시스템)",
            "  다. 점검 방법: 붙임 1 점검표에 따른 부서 자체 점검",
            "  라. 제출 자료: 개인정보 보호 점검 결과 보고서(붙임 2 서식) 1부",
            "3. 점검 결과 미흡 사항은 개선 계획을 함께 적어 주시고, 문의는 정보보안팀(☎ 042-123-4330)으로 하여 주시기 바랍니다.",
        ],
        "att": [("개인정보 자체점검표", "docx_checklist"), ("개인정보 보호 점검 결과 보고서(서식)", "hwpx_privacy_form")],
        "sign": ("주무관 오보안", "정보보안팀장 서정보", "정보보안팀-1188", "042-123-4330", "privacy@hanbit.example"),
        "result": "결과 보고서(HWPX)·점검표(DOCX) 서식 채우기 · 문서 다듬기(부서 안내 메일) · 할 일 '점검 결과 제출(12/4)'",
    },
    {
        "dir": "03_가족문화의날", "title": "한빛 가족 문화의 날 운영 협조 요청", "body": "docx", "dept": "고객홍보팀",
        "lines": [
            "1. 관련: 고객홍보팀-904(2026. 10. 28.) 「2026년 시민 참여 행사 추진 계획」",
            "2. 시민과 함께하는 공단 행사인 '한빛 가족 문화의 날'을 아래와 같이 운영하오니, 부서별 체험 부스 운영과 "
            "자원봉사자 참여에 협조하여 주시기 바랍니다.",
            "  가. 행사명: 2026 한빛 가족 문화의 날",
            f"  나. 일시: {d(12, 12)} 10:00 ~ 16:00",
            "  다. 장소: 공단 본사 앞 열린광장",
            "  라. 대상: 시민 및 공단 임직원 가족 약 1,500명",
            "  마. 내용: 부서별 체험 부스 8개, 시설 견학, 공연",
            f"3. 자원봉사자 신청서(붙임 3 서식)를 {d(11, 25)}까지 고객홍보팀으로 제출하여 주시기 바랍니다.",
        ],
        "att": [("행사 운영 계획", "pptx_event"), ("부스 배치도", "png_booth"), ("자원봉사자 신청서(서식)", "hwpx_volunteer")],
        "sign": ("주무관 윤홍보", "고객홍보팀장 장고객", "고객홍보팀-951", "042-123-4450", "pr@hanbit.example"),
        "result": "행사 일시·장소 정리(12/12) · 자원봉사자 신청서(HWPX) 채우기 · 문서 다듬기(메신저 알림)",
    },
    {
        "dir": "04_교육수요조사", "title": "2027년 직무교육 수요조사 실시", "body": "doc", "dept": "인재개발팀",
        "lines": [
            "1. 관련: 인재개발팀-512(2026. 10. 20.)",
            "2. 2027년 직무교육 과정을 직원 수요에 맞게 편성하고자 수요조사를 아래와 같이 실시하오니, 부서별로 취합하여 "
            f"{d(11, 20)}까지 인재개발팀으로 제출하여 주시기 바랍니다.",
            "  가. 조사 대상: 전 직원",
            "  나. 조사 내용: 희망 교육 분야, 희망 시기, 교육 방식(집합·온라인)",
            "  다. 제출 자료: 직무교육 수요조사서(붙임 1 서식) 1부",
            "3. 2026년 교육과정 운영 결과(붙임 2)를 참고하시기 바랍니다.",
        ],
        "att": [("직무교육 수요조사서(서식)", "xls_survey"), ("2026년 교육과정 운영 결과", "ppt_training")],
        "sign": ("주무관 배교육", "인재개발팀장 노인재", "인재개발팀-640", "042-123-4520", "hrd@hanbit.example"),
        "result": "옛 오피스 형식(DOC·XLS·PPT) 읽기 · 할 일 '수요조사서 제출(11/20)' · 문서 다듬기(부서 취합 요청 메일)",
    },
    {
        "dir": "05_공용차량점검", "title": "공용차량 운행일지 점검 결과 통보 및 개선 요청", "body": "odt", "dept": "총무팀",
        "lines": [
            "1. 관련: 총무팀-3015(2026. 10. 30.) 「공용차량 관리 실태 점검 계획」",
            "2. 10월 공용차량 운행일지 점검 결과를 붙임과 같이 통보하오니, 지적 사항이 있는 부서에서는 개선 조치 계획서를 "
            f"작성하여 {d(11, 30)}까지 총무팀으로 제출하여 주시기 바랍니다.",
            "  가. 점검 기간: 2026. 10. 1. ~ 10. 31.",
            "  나. 점검 대상: 공용차량 12대 운행일지 및 유류 사용 대장",
            "  다. 주요 지적: 운행 목적 미기재 7건, 주행거리 불일치 3건, 유류 영수증 누락 2건",
            "  라. 제출 자료: 개선 조치 계획서(붙임 2 서식) 1부",
        ],
        "att": [("운행일지 점검 결과표", "ods_vehicle"), ("개선 조치 계획서(서식)", "docx_improve_form")],
        "sign": ("주무관 마총무", "총무팀장 심차량", "총무팀-3102", "042-123-4120", "admin@hanbit.example"),
        "result": "ODF(ODT·ODS) 읽기 · 개선 조치 계획서(DOCX) 채우기 · 보고서 작성(조치 결과 보고)",
    },
    {
        "dir": "06_연말연시당직", "title": "2026~2027년 연말연시 당직근무 편성 안내", "body": "txt", "dept": "총무팀",
        "lines": [
            "1. 관련: 총무팀-3110(2026. 11. 5.)",
            "2. 연말연시 시설 안전과 민원 대응을 위하여 당직근무를 아래와 같이 편성하오니, 각 부서에서는 근무 가능 일자를 "
            f"{d(11, 18)}까지 회신하여 주시기 바랍니다.",
            f"  가. 근무 기간: {d(12, 24)} ~ {d(1, 4, 2027)}",
            "  나. 근무 시간: 평일 18:00 ~ 익일 09:00, 휴일 09:00 ~ 익일 09:00",
            "  다. 근무 장소: 본사 1층 종합상황실",
            "  라. 회신 방법: 붙임 1 편성표(초안)에 근무 가능 일자 표시 후 메일 회신",
            "3. 비상연락망(붙임 2)을 확인하시고 변경 사항이 있으면 함께 알려 주시기 바랍니다.",
        ],
        "att": [("당직근무 편성표(초안)", "csv_duty"), ("비상연락망", "xlsx_contacts")],
        "sign": ("주무관 마총무", "총무팀장 심차량", "총무팀-3121", "042-123-4120", "admin@hanbit.example"),
        "result": "문서24 저장 텍스트(CP949)·CSV 읽기 · 할 일 '근무 가능 일자 회신(11/18)' · 문서 다듬기(메신저 알림)",
    },
    {
        "dir": "07_건강검진", "title": "2026년 직원 일반건강검진 미수검자 수검 안내", "body": "html", "dept": "인사팀",
        "lines": [
            "1. 2026년 직원 일반건강검진 미수검자에게 아래와 같이 수검을 안내드립니다.",
            f"  가. 수검 기한: {d(12, 15)}까지",
            "  나. 대상: 2026년 일반건강검진 미수검 직원 23명(부서별 명단은 개별 통보)",
            "  다. 검진 기관: 붙임 1 지정 검진기관 목록 참고(사전 예약 필수)",
            "  라. 준비 사항: 검진 전날 21시 이후 금식, 붙임 2 문진표 작성 후 지참",
            f"2. 검진을 마친 직원은 수검 확인서를 {d(12, 18)}까지 인사팀으로 제출하여 주시기 바랍니다.",
            "3. 기한 내 미수검 시 「산업안전보건법」에 따라 과태료가 부과될 수 있습니다.",
        ],
        "att": [("지정 검진기관 목록", "pdf_hospitals"), ("건강검진 문진표", "rtf_questionnaire")],
        "sign": ("주무관 권인사", "인사팀장 남건강", "인사팀-2290", "042-123-4150", "hr@hanbit.example"),
        "result": "홈페이지 게시글(HTML)·RTF 읽기 · 기한 2개(수검 12/15, 확인서 12/18) · 할 일 등록",
    },
    {
        "dir": "08_메일_만족도조사", "title": "[협조] 2026년 시민 만족도 조사 설문 문항 검토 의견 요청", "body": "eml",
        "dept": "경영평가팀",
        "lines": [
            "안녕하세요. 경영평가팀 하평가입니다.",
            "",
            "2026년 시민 만족도 조사를 앞두고 설문 문항(초안)을 첨부와 같이 보내드립니다.",
            "소관 시설과 관련된 문항을 검토하시고, 수정·추가 의견을 의견 회신서(서식)에 적어 "
            f"{d(11, 19)} 18:00까지 회신 부탁드립니다.",
            "",
            "■ 조사 기간: 2026. 12. 1. ~ 12. 20.",
            "■ 조사 대상: 공단 시설 이용 시민 1,200명",
            "■ 첨부: 설문지(초안), 의견 회신서(서식), 참고자료(압축 파일: 2025년 조사 결과 요약, 조사 일정표)",
            "",
            "의견이 없는 부서도 '의견 없음'으로 회신해 주시기 바랍니다.",
            "",
            "감사합니다.",
            "경영평가팀 하평가 드림 / ☎ 042-123-4610",
        ],
        "att": [("시민 만족도 조사 설문지(초안)", "docx_questionnaire"), ("의견 회신서(서식)", "hwpx_opinion_form"),
                ("참고자료", "zip_reference")],
        "sign": ("", "", "", "042-123-4610", "eval@hanbit.example"),
        "result": "메일(EML) 첨부 꺼내기·ZIP 자동 풀기 · 의견 회신서(HWPX) 채우기 · 문서 다듬기(회신 메일)",
    },
    {
        "dir": "09_청렴서약", "title": "2026년 임직원 청렴 서약서 제출 안내", "body": "mht", "dept": "감사실",
        "lines": [
            "1. 관련: 감사실-1201(2026. 11. 2.) 「2026년 반부패·청렴 추진 계획」",
            "2. 청렴한 조직 문화를 만들고자 전 임직원 청렴 서약을 아래와 같이 실시하오니, "
            f"각 부서에서는 소속 직원의 서약서를 받아 {d(11, 27)}까지 감사실로 제출하여 주시기 바랍니다.",
            "  가. 대상: 전 임직원(기간제 근로자 포함)",
            "  나. 제출 자료: 청렴 서약서(붙임 1 서식) 각 1부",
            "  다. 참고: 청렴 교육 자료(붙임 2)를 부서 회의 때 함께 안내",
        ],
        "att": [("청렴 서약서(서식)", "hwpx_pledge"), ("청렴 교육 자료", "odp_integrity")],
        "sign": ("주무관 이청렴", "감사실장 최감사", "감사실-1240", "042-123-4600", "audit@hanbit.example"),
        "result": "웹 공문 저장 파일(MHT)·ODP 읽기 · 청렴 서약서({{자리표시}} HWPX) 채우기",
    },
    {
        "dir": "10_스캔_합동점검", "title": "공공시설 안전 합동점검 일정 통보", "body": "scan", "dept": "시설안전과",
        "sender": f"{CITY}장", "org": CITY,
        "lines": [
            "1. 관련: 한빛시 시설안전과-4410(2026. 11. 3.)",
            "2. 겨울철 공공시설 안전사고 예방을 위하여 관계기관 합동점검을 아래와 같이 실시하오니, "
            f"점검 대상 시설의 관리자가 입회할 수 있도록 협조하여 주시고 회신서를 {d(11, 24)}까지 제출하여 주시기 바랍니다.",
            f"  가. 점검 일시: {d(12, 2)} 10:00 ~ 17:00",
            "  나. 점검 대상: 한빛시 체육관, 시민수영장, 공영주차장 3곳",
            "  다. 점검 반: 시 시설안전과, 소방서, 전기안전공사(합동)",
            "  라. 회신 자료: 합동점검 회신서(붙임 서식) 1부",
        ],
        "att": [("합동점검 회신서(서식)", "docx_reply_form")],
        "sign": ("주무관 고시설", "시설안전과장 문안전", "시설안전과-4498", "042-270-3510", "safety@hanbitcity.example"),
        "result": "스캔 공문(그림 PDF) 글자 읽기(Windows 글자 인식) · 회신서(DOCX) 채우기 · 점검 일정(12/2)",
    },
]


# ================================================================ 공통: 공문 머리·꼬리
def head_lines(n: dict) -> list:
    return [("수신", "수신자 참조"), ("(경유)", ""), ("제목", n["title"]), ""]


def tail_lines(n: dict) -> list[str]:
    att = [a for a, _ in n["att"]]
    out = [""]
    if len(att) == 1:
        out.append(f"붙임  {att[0]} 1부.  끝.")
    else:
        for i, a in enumerate(att, 1):
            out.append(("붙임  " if i == 1 else "      ") + f"{i}. {a} 1부." + ("  끝." if i == len(att) else ""))
    return out


def foot_lines(n: dict) -> list[str]:
    a, b, no, tel, mail = n["sign"]
    return [f"{a}    {b}    전결 11/09", f"시행 {no} (2026. 11. 9.)    접수",
            ADDR if n.get("org", ORG) == ORG else "우 34100  한빛시 시청로 1 / https://www.hanbitcity.example",
            f"전화 {tel} / 전송 {tel[:-1]}9 / {mail} / 공개"]


def plain_text(n: dict) -> str:
    out = [n.get("org", ORG), ""]
    for x in head_lines(n) + n["lines"] + tail_lines(n):
        out.append(f"{x[0]}  {x[1]}".rstrip() if isinstance(x, tuple) else x)
    out += ["", n.get("sender", f"{ORG}이사장"), ""] + foot_lines(n)
    return "\n".join(out)


# ================================================================ 도구
def soffice(src: Path, fmt: str, out_dir: Path) -> Path:
    subprocess.run(["soffice", "--headless", "--convert-to", fmt, "--outdir", str(out_dir), str(src)],
                   check=True, capture_output=True, timeout=180)
    out = out_dir / (src.stem + "." + fmt.split(":")[0])
    if not out.exists():
        raise RuntimeError(f"LibreOffice 변환 실패: {src.name} → {fmt}")
    return out


_NODE = r"""const { chromium } = require('playwright');
(async () => { const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1000, height: 1300 } });
  await p.goto(process.argv[2]);
  if (process.argv[4] === 'png') await p.screenshot({ path: process.argv[3], fullPage: true });
  else await p.pdf({ path: process.argv[3], format: 'A4', printBackground: true, preferCSSPageSize: true });
  await b.close(); })();"""


def render(html_text: str, out: Path, kind: str = "pdf") -> None:
    """HTML을 PDF(또는 PNG)로 (Chromium 인쇄)."""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "page.html"
        src.write_text(html_text, encoding="utf-8")
        js = Path(td) / "r.js"
        js.write_text(_NODE, encoding="utf-8")
        subprocess.run(["node", str(js), src.as_uri(), str(out), kind], check=True, timeout=120)


CSS = """
@page { size: A4; margin: 20mm 20mm; }
body { font-family: 'Malgun Gothic', 'Noto Sans CJK KR', 'WenQuanYi Zen Hei', sans-serif; font-size: 11.5pt; color: #000; margin: 0; }
.org { text-align: center; font-size: 21pt; font-weight: 700; padding-bottom: 8px; border-bottom: 2px solid #000; margin-bottom: 14px; }
p { margin: 0; line-height: 1.75; white-space: pre-wrap; word-break: keep-all; }
.k { font-weight: 700; display: inline-block; width: 52px; }
.ttl { font-weight: 700; }
.sender { text-align: center; font-size: 17pt; font-weight: 700; margin: 30px 0 22px; letter-spacing: 2px; }
.foot { border-top: 2px solid #000; padding-top: 6px; font-size: 9pt; }
.foot p { line-height: 1.6; }
table { width: 100%; border-collapse: collapse; margin: 8px 0; } td, th { border: 1px solid #333; padding: 6px 8px; font-size: 10.5pt; }
th { background: #e8eef7; }
h1 { font-size: 17pt; text-align: center; margin: 0 0 16px; }
"""


def notice_html(n: dict, scan: bool = False) -> str:
    out = [f'<div class="org">{html.escape(n.get("org", ORG))}</div>']
    for item in head_lines(n) + n["lines"] + tail_lines(n):
        if isinstance(item, tuple):
            k, v = item
            out.append(f'<p><span class="k">{html.escape(k)}</span><span class="{"ttl" if k == "제목" else ""}">{html.escape(v)}</span></p>')
        else:
            out.append(f"<p>{html.escape(item) or '&nbsp;'}</p>")
    out.append(f'<div class="sender">{html.escape(n.get("sender", ORG + "이사장"))}</div>')
    out.append('<div class="foot">' + "".join(f"<p>{html.escape(x)}</p>" for x in foot_lines(n)) + "</div>")
    extra = "body { padding: 50px 60px; background: #fbfaf6; }" if scan else ""
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}{extra}</style></head><body>{"".join(out)}</body></html>'


def doc_html(title: str, inner: str) -> str:
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body><h1>{html.escape(title)}</h1>{inner}</body></html>'


def table_html(rows: list[list[str]]) -> str:
    h = "".join(f"<th>{html.escape(c)}</th>" for c in rows[0])
    b = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows[1:])
    return f"<table><tr>{h}</tr>{b}</table>"


# ---- 한글 HWPX (python-hwpx)
def _hdoc():
    from hwpx import HwpxDocument
    doc = HwpxDocument.new()
    st = {k: doc.ensure_run_style(font=F, **kw) for k, kw in {
        "org": dict(bold=True, size=20), "lab": dict(bold=True, size=11), "txt": dict(size=11), "ttl": dict(bold=True, size=12),
        "snd": dict(bold=True, size=16), "small": dict(size=9, color="#333333"), "h": dict(bold=True, size=15),
        "h0": dict(bold=True, size=13)}.items()}
    return doc, st


def _para(doc, runs, **fmt):
    p = doc.add_paragraph("", char_pr_id_ref=runs[0][0], include_run=False)
    for cp, t in runs:
        p.add_run(t, char_pr_id_ref=cp)
    if fmt:
        doc.set_paragraph_format(paragraph_index=len(doc.paragraphs) - 1, **fmt)


def _grid(doc, st, rows, widths=None):
    t = doc.add_table(len(rows), len(rows[0]), char_pr_id_ref=st["txt"])
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            t.set_cell_text(r, c, v)
            if c == 0:
                t.set_cell_shading(r, c, "#F2F2F2")
    if widths:
        t.set_column_widths(widths)


def hwpx_notice(n: dict, path: Path) -> None:
    doc, st = _hdoc()
    _para(doc, [(st["org"], n.get("org", ORG))], alignment="CENTER", spacing_after_pt=10, bottom_border=True, border_color="#000000")
    for item in head_lines(n) + n["lines"] + tail_lines(n):
        if isinstance(item, tuple):
            k, v = item
            _para(doc, [(st["lab"], f"{k}  "), (st["ttl"] if k == "제목" else st["txt"], v)], line_spacing_percent=160)
        else:
            _para(doc, [(st["txt"], item)], line_spacing_percent=160)
    _para(doc, [(st["snd"], n.get("sender", ORG + "이사장"))], alignment="CENTER", spacing_before_pt=16, spacing_after_pt=16)
    for i, x in enumerate(foot_lines(n)):
        _para(doc, [(st["small"], x)], line_spacing_percent=130, **({"bottom_border": True, "border_color": "#000000"} if i == 0 else {}))
    doc.save_to_path(str(path))


def hwpx_form(path: Path, title: str, labels: list[str], note: str = "", sign: bool = True) -> None:
    """'항목 | 빈칸' 표 서식 (서식 채우기가 항목 이름 오른쪽 빈칸을 채운다)."""
    doc, st = _hdoc()
    _para(doc, [(st["h"], title)], alignment="CENTER", spacing_after_pt=12)
    _grid(doc, st, [[lab, ""] for lab in labels], [45, 125])
    if note:
        _para(doc, [(st["small"], note)], line_spacing_percent=150, spacing_before_pt=6)
    if sign:
        _para(doc, [(st["txt"], "위와 같이 제출합니다.")], alignment="CENTER", spacing_before_pt=16)
    doc.save_to_path(str(path))


def hwpx_pledge(path: Path) -> None:
    doc, st = _hdoc()
    _para(doc, [(st["h"], "청 렴 서 약 서")], alignment="CENTER", spacing_after_pt=16)
    for t in (f"본인은 {ORG} 임직원으로서 공정하고 청렴하게 직무를 수행할 것을 다짐하며, 다음 사항을 성실히 지킬 것을 서약합니다.",
              "",
              "1. 직무와 관련하여 금품·향응·편의를 받거나 요구하지 않겠습니다.",
              "2. 알선·청탁을 하거나 받지 않고, 부정청탁을 받은 경우 신고하겠습니다.",
              "3. 직무상 알게 된 정보를 사적인 이익을 위해 쓰지 않겠습니다.",
              "4. 이해충돌이 생길 수 있는 직무는 미리 신고하고 회피하겠습니다.",
              "", "작성일: {{작성일}}", "", "소속: {{소속}}", "성명: {{성명}}              (서명)"):
        _para(doc, [(st["txt"], t)], line_spacing_percent=180)
    _para(doc, [(st["h0"], f"{ORG}이사장 귀하")], alignment="CENTER", spacing_before_pt=24)
    doc.save_to_path(str(path))


# ---- Word DOCX (python-docx)
def _docx():
    import docx
    from docx.shared import Pt
    dd = docx.Document()
    stl = dd.styles["Normal"]
    stl.font.name = F
    stl.font.size = Pt(11)
    stl.element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia", F)
    return dd


def docx_notice(n: dict, path: Path) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    dd = _docx()
    p = dd.add_paragraph()
    r = p.add_run(n.get("org", ORG))
    r.bold, r.font.size = True, Pt(20)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for item in head_lines(n) + n["lines"] + tail_lines(n):
        p = dd.add_paragraph()
        if isinstance(item, tuple):
            p.add_run(f"{item[0]}  ").bold = True
            p.add_run(item[1]).bold = item[0] == "제목"
        else:
            p.add_run(item)
    p = dd.add_paragraph()
    r = p.add_run(n.get("sender", ORG + "이사장"))
    r.bold, r.font.size = True, Pt(16)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for x in foot_lines(n):
        dd.add_paragraph().add_run(x).font.size = Pt(9)
    dd.save(path)


def docx_table_form(path: Path, title: str, rows: list[tuple[str, str]], extra: list[str] | None = None,
                    table2: list[list[str]] | None = None) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    dd = _docx()
    p = dd.add_paragraph()
    r = p.add_run(title)
    r.bold, r.font.size = True, Pt(16)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    t = dd.add_table(rows=len(rows), cols=2)
    t.style = "Table Grid"
    for i, (a, b) in enumerate(rows):
        t.cell(i, 0).text, t.cell(i, 1).text = a, b
    for x in extra or []:
        dd.add_paragraph(x)
    if table2:
        t2 = dd.add_table(rows=len(table2), cols=len(table2[0]))
        t2.style = "Table Grid"
        for i, row in enumerate(table2):
            for j, v in enumerate(row):
                t2.cell(i, j).text = v
    dd.save(path)


def pptx_slides(path: Path, slides: list[tuple[str, str]]) -> None:
    import pptx
    pr = pptx.Presentation()
    for title, body in slides:
        sl = pr.slides.add_slide(pr.slide_layouts[1])
        sl.shapes.title.text = title
        sl.placeholders[1].text = body
    pr.save(path)


# ---- Excel XLSX (openpyxl)
def xlsx_form(path: Path, title: str, info: list[str], head: list[str], rows: list[list] | int, widths: list[int],
              sheet: str = "서식") -> None:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    thin = Side(style="thin", color="000000")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    n = len(head)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n)
    ws.cell(1, 1, title).font = Font(name=F, size=16, bold=True)
    ws.cell(1, 1).alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32
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
    data = rows if isinstance(rows, list) else [[i] + [None] * (n - 1) for i in range(1, rows + 1)]
    for i, row in enumerate(data, 1):
        for c in range(1, n + 1):
            cell = ws.cell(r + i, c, row[c - 1] if c - 1 < len(row) else None)
            cell.border = box
            cell.font = Font(name=F, size=11)
            if isinstance(cell.value, (int, float)) and c > 1:
                cell.number_format = "#,##0"
        ws.row_dimensions[r + i].height = 22
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = w
    wb.save(path)


# ================================================================ 붙임 만들기
def make_attachment(kind: str, name: str, folder: Path, tmp: Path) -> Path:
    base = folder / name
    if kind == "pdf_guide_budget":
        out = (base.parent / (base.name + ".pdf"))
        render(doc_html("2027년도 예산 편성 지침",
               "<p><b>1. 편성 원칙</b></p><p>  ○ 경상경비는 2026년 대비 5% 이내로 요구</p>"
               "<p>  ○ 신규 사업은 사업 계획서와 산출 근거를 함께 제출</p><p>  ○ 시설 유지보수비는 노후도 조사 결과 우선순위에 따라 요구</p>"
               "<p><b>2. 비목별 작성 요령</b></p>" + table_html([["비목", "작성 요령", "산출 근거"],
               ["일반수용비", "사무용품·인쇄비 등", "단가 × 수량"], ["시설장비유지비", "정기 점검·소규모 수선", "견적서 2곳 이상"],
               ["여비", "국내 출장 여비", "인원 × 횟수 × 단가"], ["업무추진비", "부서 운영 경비", "전년 집행 실적"]]) +
               f"<p><b>3. 제출 일정</b></p><p>  ○ 부서 요구서 제출: {d(11, 27)} 17:00까지</p><p>  ○ 예산 심의: 2026. 12. 7. ~ 12. 11.</p>"), out)
    elif kind == "xlsx_budget":
        out = (base.parent / (base.name + ".xlsx"))
        xlsx_form(out, "2027년도 예산 요구서", ["부 서 명 :", "작 성 자 :", "연 락 처 :", "작 성 일 :"],
                  ["연번", "비목", "사업명(세부 내용)", "2026년 예산(원)", "2027년 요구(원)", "증감(원)", "산출 근거"], 10,
                  [6, 14, 30, 16, 16, 14, 30])
    elif kind == "docx_checklist":
        out = (base.parent / (base.name + ".docx"))
        docx_table_form(out, "개인정보 보호 자체점검표", [("부서명", ""), ("점검자", ""), ("점검일", "")],
                        ["", "※ 항목마다 '적합 / 부적합'을 적고, 부적합이면 조치 내용을 적습니다."],
                        [["연번", "점검 항목", "적합 여부", "조치 내용"],
                         ["1", "업무용 PC 화면보호기(10분) 및 부팅 암호 설정", "", ""],
                         ["2", "개인정보 파일 암호 설정 및 보유 기간 경과 파일 파기", "", ""],
                         ["3", "출력물·서류 잠금장치 보관함 보관", "", ""],
                         ["4", "회원 관리 시스템 접속 기록 월 1회 이상 확인", "", ""],
                         ["5", "개인정보 처리 위탁 계약서 보호 조항 포함", "", ""]])
    elif kind == "hwpx_privacy_form":
        out = (base.parent / (base.name + ".hwpx"))
        hwpx_form(out, "개인정보 보호 점검 결과 보고서",
                  ["소  속", "작 성 자", "연 락 처", "점검 기간", "점검 대상", "점검 결과", "미흡 사항", "개선 계획", "작 성 일"],
                  "※ 점검표(붙임 1)를 함께 제출합니다.")
    elif kind == "pptx_event":
        out = (base.parent / (base.name + ".pptx"))
        pptx_slides(out, [("2026 한빛 가족 문화의 날 운영 계획", f"{d(12, 12)} 10:00 ~ 16:00 · 공단 본사 앞 열린광장\n고객홍보팀"),
                          ("행사 개요", "목적: 시민과 함께하는 공단 문화 행사\n대상: 시민 및 임직원 가족 약 1,500명\n예산: 12,000,000원"),
                          ("부서별 체험 부스", "체육시설사업팀: 가족 줄넘기 체험\n안전관리팀: 심폐소생술 체험\n정보보안팀: 개인정보 지키기 퀴즈\n고객홍보팀: 포토존·기념품"),
                          ("추진 일정", f"자원봉사자 모집: ~ {s(11, 25)}\n부스 배치 확정: {s(12, 1)}\n사전 점검: {s(12, 11)}\n행사 당일: {s(12, 12)}")])
    elif kind == "png_booth":
        out = (base.parent / (base.name + ".png"))
        boxes = "".join(f'<div class="b" style="left:{x}px;top:{y}px">{t}</div>' for x, y, t in (
            (30, 80, "① 가족 줄넘기"), (240, 80, "② 심폐소생술"), (450, 80, "③ 개인정보 퀴즈"), (660, 80, "④ 포토존"),
            (30, 320, "⑤ 시설 견학 접수"), (240, 320, "⑥ 공연 무대"), (450, 320, "⑦ 기념품"), (660, 320, "⑧ 안내·분실물")))
        render(f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}
            body {{ width: 900px; padding: 24px; }} .m {{ position: relative; height: 500px; border: 2px solid #333; background: #f6f8fb; }}
            .b {{ position: absolute; width: 180px; height: 120px; border: 2px solid #1f4e79; background: #fff; display: flex;
                 align-items: center; justify-content: center; font-weight: 700; font-size: 15pt; }}
            .road {{ position: absolute; left: 0; right: 0; top: 230px; height: 50px; background: #ddd; text-align: center; line-height: 50px; }}
            </style></head><body><h1>한빛 가족 문화의 날 부스 배치도 (본사 앞 열린광장)</h1>
            <div class="m"><div class="road">관람 동선 (입구 → 출구)</div>{boxes}</div></body></html>""", out, "png")
    elif kind == "hwpx_volunteer":
        out = (base.parent / (base.name + ".hwpx"))
        hwpx_form(out, "자원봉사자 신청서", ["성  명", "소  속", "직  급", "연 락 처", "희망 부스", "참여 가능 시간", "신 청 일"],
                  f"※ 행사: 2026 한빛 가족 문화의 날({d(12, 12)}) · 신청 기한 {d(11, 25)}")
    elif kind == "xls_survey":
        x = tmp / f"{name}.xlsx"
        xlsx_form(x, "2027년 직무교육 수요조사서", ["부 서 명 :", "작 성 자 :", "작 성 일 :"],
                  ["연번", "성명", "직급", "희망 교육 분야", "희망 시기", "교육 방식(집합/온라인)", "비고"], 12,
                  [6, 12, 10, 26, 12, 20, 16], "수요조사")
        out = Path(shutil.move(str(soffice(x, "xls", tmp)), str((base.parent / (base.name + ".xls")))))
    elif kind == "ppt_training":
        x = tmp / f"{name}.pptx"
        pptx_slides(x, [("2026년 교육과정 운영 결과", "인재개발팀 · 2026. 11."),
                        ("운영 실적", "집합교육 14과정 · 수료 412명\n온라인교육 31과정 · 수료 1,026명\n교육 만족도 4.3점(5점 만점)"),
                        ("개선 의견", "실무 사례 중심 과정 확대 요청\n온라인 과정 모바일 수강 편의 개선\n신규 직원 직무 입문 과정 신설 건의")])
        out = Path(shutil.move(str(soffice(x, "ppt", tmp)), str((base.parent / (base.name + ".ppt")))))
    elif kind == "ods_vehicle":
        x = tmp / f"{name}.xlsx"
        xlsx_form(x, "10월 공용차량 운행일지 점검 결과표", ["점검 기간: 2026. 10. 1. ~ 10. 31.", "점검자: 총무팀 마총무"],
                  ["연번", "차량번호", "관리부서", "운행 목적 미기재", "주행거리 불일치", "영수증 누락", "조치 요구"],
                  [[1, "12가 3456", "체육시설사업팀", 3, 1, 0, "개선 계획 제출"], [2, "34나 5678", "안전관리팀", 2, 0, 1, "개선 계획 제출"],
                   [3, "56다 7890", "고객홍보팀", 0, 2, 0, "개선 계획 제출"], [4, "78라 1234", "총무팀", 2, 0, 1, "개선 계획 제출"],
                   [5, "90마 2345", "정보보안팀", 0, 0, 0, "-"]], [6, 12, 16, 14, 14, 12, 16], "점검결과")
        out = Path(shutil.move(str(soffice(x, "ods", tmp)), str((base.parent / (base.name + ".ods")))))
    elif kind == "docx_improve_form":
        out = (base.parent / (base.name + ".docx"))
        docx_table_form(out, "공용차량 운행 관리 개선 조치 계획서",
                        [("부서명", ""), ("작성자", ""), ("연락처", ""), ("차량번호", ""), ("지적 사항", ""),
                         ("원인", ""), ("개선 조치 내용", ""), ("조치 완료 예정일", ""), ("작성일", "")])
    elif kind == "csv_duty":
        out = (base.parent / (base.name + ".csv"))
        rows = [["일자", "요일", "근무 시간", "근무자(부서)", "근무 가능 여부(O/X)"]]
        cur = date(2026, 12, 24)
        holidays = {date(2026, 12, 25), date(2027, 1, 1)}
        while cur <= date(2027, 1, 4):
            rows.append([cur.strftime("%Y-%m-%d"), WD[cur.weekday()],
                         "09:00~익일 09:00" if cur.weekday() >= 5 or cur in holidays else "18:00~익일 09:00", "", ""])
            cur = date.fromordinal(cur.toordinal() + 1)
        with open(out, "w", encoding="cp949", newline="") as f:
            csv.writer(f).writerows(rows)
    elif kind == "xlsx_contacts":
        out = (base.parent / (base.name + ".xlsx"))
        xlsx_form(out, "연말연시 비상연락망", ["※ 변경 사항은 총무팀(☎ 042-123-4120)으로 알려 주십시오."],
                  ["연번", "부서", "직위", "성명", "사무실", "휴대전화"],
                  [[1, "총무팀", "팀장", "심차량", "042-123-4120", "010-0000-4120"], [2, "안전관리팀", "팀장", "박안전", "042-123-4567", "010-0000-4567"],
                   [3, "체육시설사업팀", "팀장", "유체육", "042-123-4700", "010-0000-4700"], [4, "고객홍보팀", "팀장", "장고객", "042-123-4450", "010-0000-4450"],
                   [5, "정보보안팀", "팀장", "서정보", "042-123-4330", "010-0000-4330"]], [6, 16, 8, 10, 16, 16], "연락망")
    elif kind == "pdf_hospitals":
        out = (base.parent / (base.name + ".pdf"))
        render(doc_html("2026년 일반건강검진 지정 검진기관 목록", table_html([
            ["기관명", "주소", "예약 전화", "검진 시간"],
            ["한빛중앙병원 건강검진센터", "한빛시 중앙로 210", "042-555-1001", "평일 07:30~11:30"],
            ["한빛의료원", "한빛시 시청로 45", "042-555-2002", "평일 08:00~12:00, 토 08:00~10:00"],
            ["새한빛내과의원", "한빛시 강변로 18", "042-555-3003", "평일 08:00~11:00"],
            ["한빛여성의원", "한빛시 꽃길 7", "042-555-4004", "평일 08:30~11:30"]]) +
            "<p>※ 검진 결과는 국민건강보험공단 '수검 확인서'로 출력해 인사팀에 제출합니다.</p>"), out)
    elif kind == "rtf_questionnaire":
        dd = _docx()
        dd.add_paragraph("일반건강검진 문진표").runs[0].bold = True
        for q in ("성명:", "생년월일:", "소속:", "1. 현재 치료 중인 질환이 있습니까? (예 / 아니오)",
                  "2. 최근 1년간 흡연한 적이 있습니까? (예 / 아니오)", "3. 일주일에 30분 이상 운동하는 날은 며칠입니까? (   일)",
                  "4. 검진 전날 21시 이후 금식하였습니까? (예 / 아니오)"):
            dd.add_paragraph(q)
        x = tmp / f"{name}.docx"
        dd.save(x)
        out = Path(shutil.move(str(soffice(x, "rtf", tmp)), str((base.parent / (base.name + ".rtf")))))
    elif kind == "docx_questionnaire":
        out = (base.parent / (base.name + ".docx"))
        dd = _docx()
        dd.add_paragraph("2026년 시민 만족도 조사 설문지(초안)").runs[0].bold = True
        for q in (f"안녕하십니까? {ORG}은 더 나은 서비스를 위해 시민 만족도 조사를 실시합니다.",
                  "1. 최근 1년간 이용한 공단 시설을 모두 골라 주십시오. (체육관 / 수영장 / 공영주차장 / 기타)",
                  "2. 시설의 청결 상태에 얼마나 만족하십니까? (매우 만족 ~ 매우 불만족, 5점)",
                  "3. 직원의 친절도에 얼마나 만족하십니까? (5점)",
                  "4. 예약·결제 등 이용 절차는 편리하였습니까? (5점)",
                  "5. 개선이 필요한 점을 자유롭게 적어 주십시오."):
            dd.add_paragraph(q)
        dd.save(out)
    elif kind == "hwpx_opinion_form":
        out = (base.parent / (base.name + ".hwpx"))
        hwpx_form(out, "시민 만족도 조사 문항 검토 의견 회신서",
                  ["부 서 명", "작 성 자", "연 락 처", "검토 문항", "수정 의견", "추가 문항", "작 성 일"],
                  f"※ 의견이 없으면 '의견 없음'으로 적어 {d(11, 19)} 18:00까지 회신", sign=False)
    elif kind == "zip_reference":
        out = (base.parent / (base.name + ".zip"))
        p1 = tmp / "2025년 조사 결과 요약.pdf"
        render(doc_html("2025년 시민 만족도 조사 결과 요약", table_html([
            ["구분", "2024년", "2025년", "증감"], ["종합 만족도", "78.2점", "81.5점", "+3.3"],
            ["청결", "80.1점", "83.0점", "+2.9"], ["친절", "82.4점", "84.7점", "+2.3"], ["이용 편의", "72.0점", "76.8점", "+4.8"]]) +
            "<p>○ 이용 편의(예약·결제) 항목이 가장 낮아 2026년 조사에서 세부 문항을 늘릴 필요가 있음</p>"), p1)
        p2 = tmp / "조사 일정표.xlsx"
        xlsx_form(p2, "2026년 시민 만족도 조사 일정", [], ["단계", "기간", "담당"],
                  [["문항 검토 의견 회신", f"~ {s(11, 19)}", "각 부서"], ["문항 확정", s(11, 24), "경영평가팀"],
                   ["조사 실시", "12. 1. ~ 12. 20.", "조사 기관"], ["결과 보고", "2027. 1. 중", "경영평가팀"]], [24, 18, 14], "일정")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in (p1, p2):
                z.write(p, p.name)
    elif kind == "hwpx_pledge":
        out = (base.parent / (base.name + ".hwpx"))
        hwpx_pledge(out)
    elif kind == "odp_integrity":
        x = tmp / f"{name}.pptx"
        pptx_slides(x, [("2026 청렴 교육 자료", "감사실"),
                        ("청탁금지법 핵심", "직무 관련자에게 금품 등을 받지 않기\n부정청탁을 받으면 거절하고 신고하기\n외부강의는 사전 신고"),
                        ("이해충돌 방지", "사적 이해관계자 신고·회피\n직무상 비밀 이용 금지\n가족 채용 제한")])
        out = Path(shutil.move(str(soffice(x, "odp", tmp)), str((base.parent / (base.name + ".odp")))))
    elif kind == "docx_reply_form":
        out = (base.parent / (base.name + ".docx"))
        docx_table_form(out, "공공시설 안전 합동점검 회신서",
                        [("기관명", ORG), ("부서명", ""), ("담당자", ""), ("연락처", ""), ("점검 대상 시설", ""),
                         ("입회 관리자", ""), ("입회자 연락처", ""), ("특이 사항", ""), ("작성일", "")])
    else:
        raise ValueError(kind)
    return out


# ================================================================ 본문 만들기
def make_body(n: dict, folder: Path, tmp: Path, att_paths: list[Path]) -> Path:
    t, kind = n["title"], n["body"]
    if kind == "hwpx":
        out = folder / f"{t}.hwpx"
        hwpx_notice(n, out)
    elif kind == "pdf":
        out = folder / f"[본문] {t}.pdf"
        render(notice_html(n), out)
    elif kind == "docx":
        out = folder / f"{t}.docx"
        docx_notice(n, out)
    elif kind in ("doc", "odt"):
        x = tmp / f"{t}.docx"
        docx_notice(n, x)
        out = Path(shutil.move(str(soffice(x, kind, tmp)), str(folder / f"{t}.{kind}")))
    elif kind == "txt":                                   # 문서24에서 '본문 저장(텍스트)'한 파일 (CP949)
        out = folder / f"{t}.txt"
        out.write_text(plain_text(n).replace("\n", "\r\n"), encoding="cp949")
    elif kind == "html":                                  # 기관 홈페이지 공지 게시판 글을 저장한 파일
        out = folder / f"{t}.html"
        items = "".join(f"<p>{html.escape(x) or '&nbsp;'}</p>" for x in n["lines"])
        files = "".join(f'<li><a href="/board/download.do?fileNo={i}">{html.escape(p.name)}</a></li>' for i, p in enumerate(att_paths, 1))
        out.write_text(f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{html.escape(t)} | 공지사항 | {ORG}</title></head>
<body><header><nav><a href="/">홈</a> &gt; <a href="/board">알림마당</a> &gt; 공지사항</nav></header>
<main><div class="board-view"><h2 class="subject">{html.escape(t)}</h2>
<dl class="info"><dt>작성부서</dt><dd>{n['dept']}</dd><dt>작성일</dt><dd>2026-11-09</dd><dt>조회수</dt><dd>128</dd></dl>
<div class="content">{items}<p>&nbsp;</p><p>문의: {n['dept']} ☎ {n['sign'][3]}</p></div>
<div class="file"><strong>첨부파일</strong><ul>{files}</ul></div></div></main>
<footer>Copyright © {ORG}. All rights reserved.</footer></body></html>""", encoding="utf-8")
    elif kind == "mht":                                   # 웹 전자문서 시스템에서 '다른 이름으로 저장(MHT)'
        out = folder / f"{t}.mht"
        out.write_text("From: <Saved by Microsoft Edge>\r\nSubject: " + t + "\r\nMIME-Version: 1.0\r\n"
                       "Content-Type: multipart/related; type=\"text/html\"; boundary=\"----=_NextPart_seomu\"\r\n\r\n"
                       "------=_NextPart_seomu\r\nContent-Type: text/html; charset=\"utf-8\"\r\n"
                       "Content-Transfer-Encoding: 8bit\r\nContent-Location: https://docs.hanbit.example/view.do?docId=1240\r\n\r\n"
                       + notice_html(n) + "\r\n------=_NextPart_seomu--\r\n", encoding="utf-8")
    elif kind == "eml":                                   # 업무 메일 (첨부 포함)
        out = folder / f"{t}.eml"
        m = EmailMessage()
        m["Subject"] = t
        m["From"] = "경영평가팀 하평가 <eval@hanbit.example>"
        m["To"] = "각 부서 서무 담당자 <all-dept@hanbit.example>"
        m["Date"] = format_datetime(datetime(2026, 11, 9, 10, 30))
        m.set_content("\n".join(n["lines"]))
        for p in att_paths:
            ctype = {".docx": ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
                     ".hwpx": ("application", "haansofthwpx"), ".zip": ("application", "zip")}.get(p.suffix, ("application", "octet-stream"))
            m.add_attachment(p.read_bytes(), maintype=ctype[0], subtype=ctype[1], filename=p.name)
        out.write_bytes(bytes(m))
    elif kind == "scan":                                  # 우편으로 받은 공문을 복합기로 스캔한 PDF (글자 없이 그림만)
        png = tmp / "scan.png"
        render(notice_html(n, scan=True), png, "png")
        from PIL import Image, ImageFilter
        im = Image.open(png).convert("L").filter(ImageFilter.GaussianBlur(0.4)).rotate(0.5, fillcolor=245, expand=False)
        out = folder / f"[스캔] {t}.pdf"
        im.convert("RGB").save(out, "PDF", resolution=110)
    else:
        raise ValueError(kind)
    return out


MEMOS = """문서 다듬기 시연용 메모 — 아래 메모를 '대충 쓴 내용'에 붙여 넣고 형식을 골라 [다듬기]를 누르세요.
(내용 없이 [다듬기]를 누르면 고른 형식의 기본 양식이 나옵니다. '관련 공문'에 시연 공문을 고르면 공문 내용도 씁니다)

[메일] ─────────────────────────────
개인정보 자체점검 결과 제출 요청
점검 기간 11월 16일부터 11월 30일까지
점검 결과 보고서 12월 4일까지 회신해줘
점검표도 같이 보내줘
문의는 내선 4330

[공문] ─────────────────────────────
체육관 동절기 운영시간 변경 안내
12월 1일부터 2월 28일까지 평일 운영시간 06:00~21:00으로 변경
주말 운영시간은 기존과 같음
변경 사항 회원 안내문 게시 협조해줘
붙임: 운영시간 변경 안내문, 회원 공지 게시용 포스터

[보고] ─────────────────────────────
공용차량 운행일지 개선 조치 결과 보고
10월 점검에서 운행 목적 미기재 3건 지적
11월 20일 운행일지 작성 교육 실시 했습니다
11월부터 운행 목적 필수 입력으로 변경
12월 중 재점검 예정

[메시지] ───────────────────────────
가족 문화의 날 자원봉사자 모집
12월 12일(토) 10시부터 16시까지 본사 앞 열린광장
부스별 2명씩 필요
11월 25일까지 신청서 보내줘
"""

README_HEAD = f"""# 시연용 예시 공문 10건

가상의 기관 **{ORG}**(10번은 **{CITY}청**)의 새 공문 10건입니다. 공문마다 **본문 + 붙임**으로 되어 있고,
공공기관에서 주고받는 문서 형식을 고르게 썼습니다. 기관·사람·연락처·문서번호는 모두 지어낸 것입니다.

**쓰는 법**
1. 설정 → 내 정보(이름·부서·연락처)를 먼저 넣어 둡니다 (서식 채우기에 쓰입니다).
2. 공문 수집 → 본문 칸에 '본문' 파일, 붙임 칸에 나머지 파일 → [수집].
   메일(.eml)은 본문 칸에만 올리면 첨부가 붙임으로 들어가고, ZIP은 자동으로 풀립니다.
3. 분석 결과(요약·제출 기한·제출물·행사·붙임)를 확인합니다.
4. 결과물 만들기: 붙임 서식의 **[서식 채우기]** → 공문 폴더의 '작성'에 채운 파일,
   **보고서 작성**·**문서 다듬기**에서 '관련 공문'으로 이 공문을 고르기.

| # | 공문 | 본문 | 붙임 | 시연에서 보여 줄 결과물 |
|---|---|---|---|---|
"""

README_TAIL = """

## 형식별 메모
- **HWP(한글 5.0·배포용)**: 이 개발 환경에서는 HWP 파일을 새로 만들 수 없어 넣지 않았습니다. HWPX 공문(01)을 한글에서 열어
  'HWP로 저장' 또는 '배포용 문서로 저장'하면 HWP 시연 파일이 됩니다 (프로그램은 일반·배포용 HWP를 모두 읽습니다).
- **스캔 공문(10)**: 글자가 없는 그림 PDF입니다. Windows 글자 인식(OCR)으로 읽으므로 Windows에서만 분석됩니다.
- **부스 배치도(03, PNG)**: 그림 붙임입니다. 미리보기는 되고, 글자는 Windows 글자 인식으로 읽습니다.
- **XLS 서식(04)**: 옛 엑셀 형식이라 읽기만 됩니다. 채우려면 엑셀에서 XLSX로 저장해 올립니다.

## 문서다듬기_예시메모.txt
메일·공문·보고·메시지 형식별 메모입니다. 같은 메모라도 형식을 바꾸면 짜임이 다르게 나옵니다.

다시 만들기: `python tools/make_demo_data.py` (python-hwpx·python-docx·python-pptx·openpyxl·pillow, LibreOffice, Node playwright 필요)
"""


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    rows = []
    with tempfile.TemporaryDirectory() as td:
        for i, n in enumerate(N, 1):
            folder = OUT / n["dir"]
            folder.mkdir()
            tmp = Path(td) / n["dir"]
            tmp.mkdir()
            mail = n["body"] == "eml"
            att_dir = tmp if mail else folder                 # 메일은 첨부가 메일 안에 들어간다
            atts = [make_attachment(kind, name if mail else f"붙임{j}. {name}", att_dir, tmp)
                    for j, (name, kind) in enumerate(n["att"], 1)]
            body = make_body(n, folder, tmp, atts)
            files = ("메일 첨부: " + ", ".join(f"`{p.name}`" for p in atts)) if mail else " · ".join(f"`{p.name}`" for p in atts)
            rows.append(f"| {i} | {n['title']} | `{body.name}` | {files} | {n['result']} |")
    (OUT / "README.md").write_text(README_HEAD + "\n".join(rows) + README_TAIL, encoding="utf-8")
    (OUT / "문서다듬기_예시메모.txt").write_text(MEMOS, encoding="utf-8")
    for f in sorted(OUT.rglob("*")):
        if f.is_file():
            print(f"{f.relative_to(OUT)}  ({f.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

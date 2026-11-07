"""여러 공문 시스템 형식의 시연·테스트용 예시 파일 만들기 (.mht 웹 공문, .eml 메일 공문, .zip 붙임).

    python tools/make_format_samples.py
"""
from __future__ import annotations

import io
import zipfile
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "sample_data" / "formats"

MHT_HTML = """<html><head><meta charset="utf-8"><title>K-에듀파인 문서보기</title></head><body>
<table class="tbl_doc"><tr><td colspan="2" class="slogan">배움이 즐거운 학교, 함께 성장하는 교육</td></tr>
<tr><td colspan="2" class="org"><b>○○교육지원청</b></td></tr>
<tr><th>수신</th><td>관내 초·중학교장</td></tr><tr><th>(경유)</th><td></td></tr>
<tr><th>제목</th><td>2026학년도 학교폭력 예방교육 실적 제출 안내</td></tr></table>
<div id="docBody">
<p>1. 귀 교의 무궁한 발전을 기원합니다.</p>
<p>2. 2026학년도 학교폭력 예방교육 실적을 아래와 같이 취합하고자 하오니, 각 학교에서는 기한 내 제출하여 주시기 바랍니다.</p>
<p>&nbsp;&nbsp;가. 제출 기한: 2026. 12. 4.(금)까지</p>
<p>&nbsp;&nbsp;나. 제출 자료: 학교폭력 예방교육 실적 보고서(붙임 서식) 1부</p>
<p>&nbsp;&nbsp;다. 제출 방법: K-에듀파인 업무관리 공문 회신</p>
<p>붙임&nbsp;&nbsp;학교폭력 예방교육 실적 보고서 서식 1부.&nbsp;&nbsp;끝.</p>
</div>
<p>○○교육지원청교육장</p>
<p>장학사 김○○ 교육지원과장 전결 11/4</p>
<p>시행 교육지원과-3301 (2026. 11. 4.) 접수</p>
<p>우 31000 ○○시 ○○로 45 / http://www.example.kr 전화 041-000-3300 / 전송 041-000-3399 / edu@example.kr / 부분공개(6)</p>
</body></html>"""


def make_mht() -> None:
    msg = MIMEMultipart("related", type="text/html")
    msg["Subject"] = "K-에듀파인 문서보기"
    msg["MIME-Version"] = "1.0"
    part = MIMEText(MHT_HTML, "html", "utf-8")
    part["Content-Location"] = "file:///C:/doc/view.htm"
    msg.attach(part)
    (OUT / "에듀파인_웹공문.mht").write_bytes(msg.as_bytes())


def make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("붙임1_수요조사표 작성 요령.txt", "교육훈련 수요조사표 작성 요령\n1. 팀 단위로 취합합니다.\n2. 필수 교육은 별도 표기합니다.\n")
        z.writestr("붙임2_교육과정 목록.txt", "2027 교육과정 목록\n- 리더십 과정\n- 직무 전문 과정\n")
    return buf.getvalue()


def make_eml() -> None:
    msg = EmailMessage()
    msg["Subject"] = "[인사팀] 2027년도 교육훈련 수요조사 협조 요청 (11/19까지)"
    msg["From"] = "인사팀 <hr@example.co.kr>"
    msg["To"] = "부서장 <leaders@example.co.kr>"
    msg["Date"] = "Thu, 05 Nov 2026 09:12:00 +0900"
    msg.set_content(
        "각 부서장님께\n\n안녕하십니까. 인사팀입니다.\n"
        "2027년도 교육훈련 계획 수립을 위해 부서별 교육 수요를 조사하고자 합니다.\n"
        "첨부한 수요조사표를 작성하시어 11월 19일(목) 15시까지 회신 부탁드립니다.\n\n"
        "- 회신 자료 : 교육훈련 수요조사표 1부\n- 회신 방법 : 이 메일로 회신\n"
        "- 문의 : 인사팀 최○○ 대리 (내선 1234)\n\n감사합니다.\n")
    msg.add_attachment("교육훈련 수요조사표\n부서명\t교육명\t인원\n".encode("utf-8"), maintype="text",
                       subtype="plain", filename="2027 교육훈련 수요조사표.txt")
    msg.add_attachment(make_zip(), maintype="application", subtype="zip", filename="참고자료.zip")
    (OUT / "메일_공문.eml").write_bytes(bytes(msg))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    make_mht()
    make_eml()
    print("만들었습니다:", OUT)

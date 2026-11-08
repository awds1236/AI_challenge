"""자주 쓰는 메일 양식 관리 및 공문 기반 메일 초안 생성."""
from __future__ import annotations

import re
from datetime import date, datetime

WEEKDAY = "월화수목금토일"

DEFAULT_TEMPLATES = [
    {
        "name": "부서 제출 요청 (공문 전달)",
        "subject": "[협조요청] {{공문제목}} 관련 자료 제출 요청 ({{제출기한}}까지)",
        "body": """안녕하세요, {{내부서}} {{내이름}}입니다.

「{{공문제목}}」 공문이 접수되어 아래와 같이 협조를 요청드립니다.

■ 주요 내용
{{요약}}

■ 제출 기한: {{제출기한_전체}}
■ 제출 자료
{{제출물}}

■ 제출 방법: 회신 메일로 제출 부탁드립니다.

관련 공문과 붙임 서식을 첨부하오니 업무에 참고하시기 바랍니다.
기한 내 제출이 어려우신 경우 미리 연락 주시면 감사하겠습니다.

감사합니다.

{{내부서}} {{내이름}} 드림
☎ {{내연락처}} / {{내메일}}""",
    },
    {
        "name": "상급기관 자료 제출",
        "subject": "[제출] {{공문제목}} 관련 자료 제출 ({{내부서}})",
        "body": """안녕하십니까, {{내부서}} {{내이름}}입니다.

「{{공문제목}}」과 관련하여 요청하신 자료를 아래와 같이 제출합니다.

■ 제출 자료
{{제출물}}

검토 후 보완이 필요한 사항이 있으면 연락 부탁드립니다.
감사합니다.

{{내부서}} {{내이름}} 드림
☎ {{내연락처}}""",
    },
    {
        "name": "제출 기한 임박 안내 (리마인드)",
        "subject": "[재안내] {{공문제목}} 제출 기한 안내 ({{제출기한}}, {{디데이}})",
        "body": """안녕하세요, {{내부서}} {{내이름}}입니다.

앞서 안내드린 「{{공문제목}}」 자료 제출 기한이 {{제출기한_전체}}({{디데이}})로 다가와 다시 안내드립니다.

■ 제출 자료
{{제출물}}

아직 제출하지 않으신 경우 기한 내 제출 부탁드립니다.
이미 제출하셨다면 이 메일은 무시하셔도 됩니다.

감사합니다.
{{내부서}} {{내이름}} (☎ {{내연락처}})""",
    },
    {
        "name": "행사 참석 안내",
        "subject": "[안내] {{행사명}} 참석 안내",
        "body": """안녕하세요, {{내부서}} {{내이름}}입니다.

「{{공문제목}}」에 따라 아래 행사를 안내드립니다.

■ 행사명: {{행사명}}
■ 일시: {{행사일시}}
■ 장소: {{행사장소}}
■ 참석 신청 기한: {{제출기한_전체}}

참석을 희망하시는 분은 기한 내 회신 부탁드립니다.
문의: {{문의처}}

감사합니다.""",
    },
]

VARIABLES = ["공문제목", "요약", "제출기한", "제출기한_전체", "디데이", "제출물", "할일", "행사명", "행사일시",
             "행사장소", "문의처", "내이름", "내부서", "내연락처", "내메일", "오늘"]

_VAR = re.compile(r"\{\{\s*([^{}\s]+)\s*\}\}")


def _fmt_date(iso: str, with_wd: bool = True) -> str:
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return iso or ""
    s = f"{d.year}. {d.month}. {d.day}."
    return s + f"({WEEKDAY[d.weekday()]})" if with_wd else s


def build_variables(notice: dict | None, settings, today: date | None = None) -> dict[str, str]:
    today = today or date.today()
    v = {
        "내이름": settings.user_name, "내부서": settings.user_dept,
        "내연락처": settings.user_phone, "내메일": settings.user_email,
        "오늘": _fmt_date(today.isoformat()),
    }
    if not notice:
        return v
    a = notice.get("analysis") or {}
    v["공문제목"] = notice.get("title", "")
    lines = [l.strip() for l in (a.get("summary") or "").splitlines() if l.strip()]
    v["요약"] = "\n".join(f"  - {l}" for l in lines) if len(lines) > 1 else (lines[0] if lines else "")
    dls = a.get("deadlines") or []
    upcoming = [d for d in dls if d.get("date", "") >= today.isoformat()] or dls
    if upcoming:
        d0 = upcoming[0]
        v["제출기한"] = _fmt_date(d0["date"])
        v["제출기한_전체"] = (_fmt_date(d0["date"]) + (f" {d0['time']}" if d0.get("time") else "") + "까지")
        try:
            n = (datetime.strptime(d0["date"], "%Y-%m-%d").date() - today).days
            v["디데이"] = "D-Day" if n == 0 else (f"D-{n}" if n > 0 else f"D+{-n}")
        except ValueError:
            pass
    subs = a.get("submissions") or []
    v["제출물"] = "\n".join(f"  {i}. {s['item']}" for i, s in enumerate(subs, 1)) if subs else ""
    v["할일"] = "\n".join(f"  - {x}" for x in a.get("actions") or [])
    ev = a.get("event") or {}
    v["행사명"] = ev.get("name") or notice.get("title", "")
    v["행사일시"] = ev.get("date", "")
    v["행사장소"] = ev.get("place", "")
    v["문의처"] = a.get("contact", "")
    return v


_PARTICLES = {"과": ("과", "와"), "와": ("과", "와"), "을": ("을", "를"), "를": ("을", "를"), "이": ("이", "가"),
              "가": ("이", "가"), "은": ("은", "는"), "는": ("은", "는"), "으로": ("으로", "로"), "로": ("으로", "로")}
# 변수 바로 뒤의 조사: 「{{공문제목}}」과 / {{행사명}}을 …
_VAR_PARTICLE = re.compile(r"(「?\{\{\s*([^{}\s]+)\s*\}\}[」』\"']?)(으로|과|와|을|를|이|가|은|는|로)(?![가-힣])")


def josa(word: str, particle: str) -> str:
    """앞말의 받침에 맞는 조사: josa('행사 안내', '과') → '와', josa('제출 요청', '와') → '과'."""
    pair = _PARTICLES.get(particle)
    last = next((c for c in reversed(word or "") if "가" <= c <= "힣" or c.isdigit()), "")
    if not pair or not last:
        return particle
    if last.isdigit():          # 숫자는 읽는 소리로: 1 일·7 칠·8 팔(ㄹ받침), 0 영·3 삼·6 육(받침), 나머지 받침 없음
        jong = 8 if last in "178" else 1 if last in "036" else 0
    else:
        jong = (ord(last) - 0xAC00) % 28
    if particle in ("으로", "로"):
        return "로" if jong in (0, 8) else "으로"         # 받침 없음·ㄹ받침 → 로
    return pair[0] if jong else pair[1]


def render(template: str, variables: dict[str, str]) -> tuple[str, list[str]]:
    """양식의 {{변수}}를 채운다. 값이 없는 변수는 [변수] 표시로 남기고 목록으로 반환.
    변수 바로 뒤의 조사는 채운 값의 받침에 맞춘다 (「…안내」와 / 「…요청」과)."""
    missing: list[str] = []

    def rep(m):
        key = m.group(1)
        val = variables.get(key, "")
        if val:
            return val
        if key not in missing:
            missing.append(key)
        return f"[{key}]"

    def fix_particle(m):
        val = variables.get(m.group(2), "")
        return m.group(1) + (josa(val, m.group(3)) if val else m.group(3))

    return _VAR.sub(rep, _VAR_PARTICLE.sub(fix_particle, template)), missing


POLISH_PROMPT = """다음은 공공기관 직원이 보낼 업무 메일 초안입니다.
사실관계(날짜, 서류명, 연락처, 대괄호 [ ] 표시)는 절대 바꾸지 말고, 정중하고 간결한 공공기관 업무 메일 문체로 다듬어 주세요.
결과는 메일 본문만 출력하세요.

[초안]
{body}"""


def clean_polished(out: str, draft: str) -> str:
    """AI가 다듬은 메일에서 본문이 아닌 것을 걷어낸다.
    작은 모델은 '본문만'이라고 해도 '제목: …', '수신: [관련 부서]' 같은 머리줄이나 초안에 없던 [빈칸]을 지어 붙인다."""
    lines = (out or "").replace("```", "").strip().splitlines()
    while lines and (not lines[0].strip() or re.match(r"^\s*(제목|수신|발신|참조|받는\s*사람|보내는\s*사람|Subject|To)\s*[:：]",
                                                      lines[0], re.I)):
        lines.pop(0)
    keep = []
    for l in lines:
        new_slots = [x for x in re.findall(r"\[[^\]]{1,30}\]", l) if x not in draft]
        if new_slots and len(re.sub(r"\[[^\]]*\]|\s", "", l)) < 8:      # 지어낸 빈칸만 있는 줄
            continue
        keep.append(l)
    text = "\n".join(keep).strip()
    return text if len(text) >= len(draft) * 0.4 else (out or "").strip()


def ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def tasks_to_ics(tasks: list[dict]) -> str:
    now = datetime.now().strftime("%Y%m%dT%H%M%S")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SeomuAI//KR", "CALSCALE:GREGORIAN"]
    for t in tasks:
        if not t.get("due") or t.get("done"):
            continue
        d = t["due"][:10].replace("-", "")
        out += ["BEGIN:VEVENT", f"UID:seomu-task-{t['id']}@local", f"DTSTAMP:{now}",
                f"DTSTART;VALUE=DATE:{d}", f"SUMMARY:{ics_escape(t['title'])}",
                f"DESCRIPTION:{ics_escape(t.get('detail') or '')}",
                "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY", f"DESCRIPTION:{ics_escape(t['title'])}", "END:VALARM",
                "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"

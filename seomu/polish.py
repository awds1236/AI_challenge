"""문서 다듬기: 대충 쓴 메모를 업무 메일·공문(기안)·보고·알림 메시지 형식으로 다듬는다.

- AI 없이도 규칙으로 형식을 갖춘다 (인사·본문·맺음말·서명 / 번호 항목·'끝.' / □·○ 개조식 / 짧은 메시지).
- '내 양식'을 고르면 그 양식의 짜임(인사말·항목·맺음말)과 문체를 따른다. 양식의 {{본문}}·{{내용}} 자리에 메모가 들어간다.
- AI가 있으면 문장을 다듬되, 메모의 숫자·날짜·금액이 결과에 그대로 있는지 확인하고 하나라도 빠지거나 바뀌면
  AI 결과를 쓰지 않고 규칙 결과를 쓴다 (작은 모델이 날짜·숫자를 바꾸는 것을 막는다).
"""
from __future__ import annotations

import json
import re

from .llm import LLMError
from .mail import clean_polished, render

KINDS = {
    "mail": "업무 메일",
    "official": "공문(기안문)",
    "report": "보고(개조식)",
    "message": "알림 메시지",
}
_BODY_SLOTS = ("본문", "내용", "메모", "요약")


def _lines(draft: str) -> list[str]:
    out = []
    for l in (draft or "").replace("\r", "").splitlines():
        l = re.sub(r"\s+", " ", l).strip()
        if l:
            out.append(l)
    return out


def _sentence(l: str) -> str:
    """메모 줄을 존댓말 문장으로: '자료 내일까지 보내주세요' 그대로, '회의 3시' → '회의 3시.' 정도만 (뜻은 바꾸지 않는다)."""
    l = re.sub(r"^[-·*•]\s*", "", l).strip()
    l = re.sub(r"\s*(해\s*줘|해줘요?|해\s*주라|좀\s*해)\s*\.?$", " 부탁드립니다.", l)
    l = re.sub(r"\s*(보내\s*줘|보내줘요?)\s*\.?$", " 보내 주시기 바랍니다.", l)
    l = re.sub(r"([가-힣]+)\s*줘요?\s*\.?$", r"\1 주시기 바랍니다.", l)          # 알려줘 → 알려 주시기 바랍니다.
    l = re.sub(r"까지\s*$", "까지입니다.", l)
    l = re.sub(r"\s+있음\s*\.?$", "이 있습니다.", l) if re.search(r"[가-힣]\s+있음\s*\.?$", l) else l
    l = re.sub(r"\s+없음\s*\.?$", "이 없습니다.", l) if re.search(r"[가-힣]\s+없음\s*\.?$", l) else l
    l = re.sub(r"(임|함|음)\s*\.?$", lambda m: {"임": "입니다.", "함": "합니다.", "음": "습니다."}[m.group(1)], l) \
        if re.search(r"[가-힣](임|함)\s*\.?$", l) else l
    if not re.search(r"[.!?。)]$|[다요]$", l):
        l += "."
    return l


def _nominal(l: str) -> str:
    """보고서 개조식: '~합니다/입니다' → '~함/임'."""
    l = re.sub(r"^[-·*•]\s*", "", l).strip().rstrip(".")
    l = re.sub(r"\s*했습니다$", "함", l)
    l = re.sub(r"\s*(?:합니다|하겠습니다)$", "함", l)
    l = re.sub(r"입니다$", "임", l)
    l = re.sub(r"됩니다$", "됨", l)
    l = re.sub(r"(부탁드립니다|바랍니다)$", "요청", l)
    l = re.sub(r"\s*(?:해\s*줘|해\s*주세요|해주세요|해\s*주시기\s*바람)$", " 요청", l)
    l = re.sub(r"\s*보내\s*(?:줘|주세요)$", " 송부 요청", l)
    l = re.sub(r"\s*알려\s*(?:줘|주세요)$", " 회신 요청", l)
    l = re.sub(r"\s*(?:줘|주세요)$", " 요청", l)
    return l


def _subject(lines: list[str]) -> str:
    if not lines:
        return ""
    m = re.match(r"^(?:제목|건명)\s*[:：]\s*(.+)$", lines[0])
    if m:
        return m.group(1).strip()
    first = re.sub(r"[.。]$", "", lines[0])
    first = re.sub(r"\s*(부탁드립니다|바랍니다|요청드립니다|해\s*주세요|해주세요|해\s*줘)$", "", first)
    return first if len(first) <= 40 else first[:38].rstrip() + "…"


def _signature(profile: dict) -> str:
    name, dept = profile.get("user_name", ""), profile.get("user_dept", "")
    contact = " | ".join(x for x in (dept, profile.get("user_phone", ""), profile.get("user_email", "")) if x)
    return "\n".join(x for x in ((f"{name} 드림" if name else ""), contact) if x)


def rule_polish(draft: str, kind: str, profile: dict | None = None, template: dict | None = None,
                variables: dict | None = None) -> dict:
    """AI 없이 형식을 갖춘다. {'subject', 'body'}"""
    profile = profile or {}
    lines = _lines(draft)
    if not lines:
        raise ValueError("다듬을 내용을 입력하세요")
    subject = _subject(lines)
    rest = lines[1:] if re.match(r"^(?:제목|건명)\s*[:：]", lines[0]) or (len(lines) > 1 and len(lines[0]) <= 40) else lines
    rest = rest or lines
    name, dept = profile.get("user_name", ""), profile.get("user_dept", "")

    if template:
        # 내 양식: {{본문}}·{{내용}} 자리에 메모를 넣고, 나머지 변수는 공문·내 정보로 채운다
        vars_ = dict(variables or {})
        filled = "\n".join(_sentence(l) for l in rest)
        for slot in _BODY_SLOTS:
            vars_.setdefault(slot, filled)
        vars_.setdefault("제목", subject)
        tsub, _m1 = render(template.get("subject") or "", vars_)
        tbody, _m2 = render(template.get("body") or "", vars_)
        tb = template.get("body") or ""
        if not any(re.search(r"\{\{?\s*" + s + r"\s*\}?\}", tb) for s in _BODY_SLOTS):
            # 양식에 본문 자리가 없으면 첫 문단(인사말) 다음에 넣는다
            parts = tbody.split("\n\n", 1)
            tbody = parts[0] + "\n\n" + filled + ("\n\n" + parts[1] if len(parts) > 1 else "")
        return {"subject": tsub.strip() or subject, "body": tbody.strip()}

    return _by_kind(kind, subject, rest, profile)


# ---- 메모 나누기: 주요 내용 / 요청 사항 / 문의 / 붙임 (형식마다 이 짜임을 다르게 배치한다)
# 요청 줄: 해 달라는 말이 있어야 한다 ('12월 1일부터 2월 28일까지 변경'처럼 기간만 있는 줄은 내용)
_REQ = re.compile(r"회신|제출|신청|부탁|요청|바람|바랍니다|해\s*줘|해\s*주세요|주세요|협조|참석\s*바|알려\s*줘|보내\s*줘|"
                  r"줘\s*\.?$|주라\s*\.?$")
_CONTACT = re.compile(r"문의|연락처|내선|☎|\d{2,4}-\d{3,4}-\d{4}|@")
_ATTACH = re.compile(r"^(?:붙임|첨부)\s*[:：]?\s*")
_ACT = re.compile(r"\s*(공유|안내|요청|알림|보고|협조\s*요청|협조|통보|제출\s*요청|회신\s*요청|변경\s*안내|변경)$")
_WD = "월화수목금토일"


def split_memo(lines: list[str]) -> dict:
    out = {"info": [], "requests": [], "contacts": [], "attach": []}
    for l in lines:
        if _ATTACH.match(l):
            out["attach"].extend(x.strip() for x in re.split(r"[,，]|\s{2,}", _ATTACH.sub("", l)) if x.strip())
        elif _CONTACT.search(l) and not _REQ.search(re.sub(r"문의", "", l)):
            out["contacts"].append(re.sub(r"^(?:문의|연락처)\s*(?:는|은)?\s*[:：]?\s*", "", l).strip())
        elif _REQ.search(l):
            out["requests"].append(l)
        else:
            out["info"].append(l)
    return out


def _core_act(subject: str, requests: bool) -> tuple[str, str]:
    """'11월 체육관 대관 일정 공유' → ('11월 체육관 대관 일정', '공유')."""
    m = _ACT.search(subject)
    if m and m.start() > 0:
        return subject[:m.start()].strip(), re.sub(r"\s+", " ", m.group(1))
    return subject, ("요청" if requests else "안내")


def _today_str() -> str:
    from datetime import date
    d = date.today()
    return f"{d.year}. {d.month}. {d.day}.({_WD[d.weekday()]})"


def _by_kind(kind: str, subject: str, rest: list[str], profile: dict) -> dict:
    from .mail import josa
    name, dept = profile.get("user_name", ""), profile.get("user_dept", "")
    m = split_memo([l for l in rest if l != subject] or rest)
    core, act = _core_act(subject, bool(m["requests"]))
    if " " in act:                         # '제출 요청' → '… 결과 제출을 요청', '변경 안내' → '… 운영시간 변경을 안내'
        first, act = act.rsplit(" ", 1)
        core = f"{core} {first}"
    obj = core + josa(core, "을")
    contact = ", ".join(m["contacts"])
    attach = m["attach"]

    if kind == "official":
        # 기안문: 수신·(경유)·제목 → 1. 관련 → 2. 목적 문장 + 가.나.다. 개조식 → 요청 기한 → 문의 → 붙임 … 끝.
        reqs = " ".join(m["requests"])
        ask = ("기한 내 회신하여 주시기 바랍니다" if re.search(r"회신|제출|알려|보내|신청", reqs) else
               "협조하여 주시기 바랍니다" if m["requests"] else "업무에 참고하시기 바랍니다")
        verb = ("협조를 요청하오니" if act.startswith("협조") else "요청하오니" if act.endswith("요청") else
                f"{act}하오니" if act.endswith(("안내", "통보", "보고")) else "알려 드리오니")
        body = ["수신  수신자 참조", "(경유)", f"제목  {subject}", "", "1. 관련: ○○○",
                f"2. {obj} 다음과 같이 {verb} {ask}."]
        items = [_nominal(l) for l in m["info"]]
        for i, it in enumerate(items):
            body.append(f"  {'가나다라마바사아자차카타파하'[i % 14]}. {it}")
        n = 3
        for r in m["requests"]:
            body.append(f"{n}. {_nominal(r)}")
            n += 1
        if contact:
            body.append(f"{n}. 문의: {contact}")
        if attach:
            body += ["", "붙임  " + "\n      ".join(f"{i}. {a} 1부." for i, a in enumerate(attach, 1)) + "  끝."]
        else:
            body[-1] = body[-1].rstrip() + "  끝."          # 붙임이 없으면 마지막 줄 끝에 '끝.'
        return {"subject": subject, "body": "\n".join(body)}

    if kind == "report":
        # 보고서(개조식): 제목 · 날짜/부서 → □ 개요 → □ 주요 내용 → □ 요청 및 향후 계획 (문장은 ~함/~임)
        plan = [l for l in m["info"] if re.search(r"예정|계획|향후|추진할|할 것", l)]
        info = [l for l in m["info"] if l not in plan]
        overview = info[:1] if len(info) > 1 else []        # 첫 줄(경위)은 개요, 나머지는 주요 내용
        body = [subject, f"{_today_str()}  {dept}".rstrip(), "", "□ 개요"]
        body += [f" ○ {_nominal(l)}" for l in overview] or [f" ○ {core} {act}"]
        if info[len(overview):]:
            body += ["", "□ 주요 내용"] + [f" ○ {_nominal(l)}" for l in info[len(overview):]]
        tail = [f" ○ {_nominal(l)}" for l in plan + m["requests"]]
        if contact:
            tail.append(f" ○ 문의: {contact}")
        if attach:
            tail.append(" ※ 붙임: " + ", ".join(attach))
        if tail:
            body += ["", "□ 향후 계획" if not m["requests"] else "□ 요청 사항 및 향후 계획"] + tail
        return {"subject": subject, "body": "\n".join(body)}

    if kind == "message":
        # 알림 메시지(메신저): [부서 이름] 한 줄 머리 + ▶ 핵심만, 인사 없이 짧게
        who = " ".join(x for x in (dept, name) if x)
        head = (f"[{who}] " if who else "") + f"{obj} {act}드립니다."
        lines = [head] + [f"▶ {_sentence(l)}" for l in m["info"] + m["requests"]]
        if contact:
            lines.append(f"(문의: {contact})")
        return {"subject": "", "body": "\n".join(lines)}

    # 업무 메일: 인사 → 목적 한 문장 → ■ 주요 내용 / ■ 요청 사항 / ■ 문의 → 맺음말 → 서명
    who = " ".join(x for x in (dept, name) if x)
    explicit = bool(_ACT.search(subject)) and _ACT.search(subject).start() > 0
    tag = (f"[{act.replace(' ', '')}]" if explicit and act in ("공유", "안내", "요청", "협조", "알림", "보고")
           else "[요청]" if m["requests"] else "[안내]")
    mail_subject = subject if subject.startswith("[") else f"{tag} {subject}"
    body = [f"안녕하세요. {who}입니다." if who else "안녕하세요.", "",
            f"{obj} 아래와 같이 {act}드립니다."]
    if m["info"]:
        body += ["", "■ 주요 내용"] + [f"  - {_sentence(l)}" for l in m["info"]]
    if m["requests"]:
        body += ["", "■ 요청 사항"] + [f"  - {_sentence(l)}" for l in m["requests"]]
    if contact:
        body += ["", f"■ 문의: {contact}"]
    if attach:
        body += ["", "■ 첨부: " + ", ".join(attach)]
    body += ["", "확인 부탁드립니다." if m["requests"] else "업무에 참고하시기 바랍니다.", "", "감사합니다."]
    sig = _signature(profile)
    if sig:
        body += ["", sig]
    return {"subject": mail_subject, "body": "\n".join(body)}


# ---- 기본 양식: 내용 없이 형식만 고르면 그 형식의 빈 초안(○○○ 자리)을 보여 준다
def skeleton(kind: str, profile: dict | None = None) -> dict:
    profile = profile or {}
    who = " ".join(x for x in (profile.get("user_dept", ""), profile.get("user_name", "")) if x) or "○○팀 ○○○"
    sig = _signature(profile) or "○○팀 ○○○ 드림\n☎ ○○○-○○○-○○○○"
    if kind == "official":
        body = ("수신  수신자 참조\n(경유)\n제목  ○○○ 안내\n\n1. 관련: ○○○-○○○(20○○. ○. ○.)\n"
                "2. ○○○을 다음과 같이 안내하오니 업무에 참고하시기 바랍니다.\n"
                "  가. 일시: 20○○. ○. ○.(○) ○○:○○\n  나. 장소: ○○○\n  다. 대상: ○○○\n  라. 내용: ○○○\n"
                "3. 제출 기한: 20○○. ○. ○.(○)까지\n4. 문의: ○○팀 ○○○(☎ ○○○-○○○○)\n\n"
                "붙임  1. ○○○ 1부.\n      2. ○○○ 1부.  끝.")
        return {"subject": "○○○ 안내", "body": body}
    if kind == "report":
        body = (f"○○○ 추진 결과 보고\n{_today_str()}  {profile.get('user_dept', '') or '○○팀'}\n\n"
                "□ 개요\n ○ 목적: ○○○\n ○ 기간: 20○○. ○. ○. ~ ○. ○.\n ○ 대상: ○○○\n\n"
                "□ 추진 내용\n ○ ○○○ 실시\n  - 세부: ○○○\n\n"
                "□ 추진 결과\n ○ ○○○ 완료(○건)\n\n"
                "□ 향후 계획\n ○ ○○○ 예정(20○○. ○.)\n ※ 붙임: ○○○")
        return {"subject": "○○○ 추진 결과 보고", "body": body}
    if kind == "message":
        return {"subject": "", "body": f"[{who}] ○○○ 안내드립니다.\n▶ 일시: ○월 ○일(○) ○○:○○\n"
                                       "▶ 장소: ○○○\n▶ ○월 ○일까지 회신 부탁드립니다.\n(문의: 내선 ○○○○)"}
    body = (f"안녕하세요. {who}입니다.\n\n○○○ 관련하여 아래와 같이 안내드립니다.\n\n"
            "■ 주요 내용\n  - ○○○\n\n■ 요청 사항\n  - ○월 ○일(○)까지 ○○○ 회신 부탁드립니다.\n\n"
            f"■ 문의: ○○○\n\n확인 부탁드립니다.\n\n감사합니다.\n\n{sig}")
    return {"subject": "[안내] ○○○", "body": body}


# 원문의 숫자·날짜·금액·전화번호 — 다듬은 글에 그대로 있어야 한다
_FACT = re.compile(r"\d[\d,.:\-/~]*\d|\d+")


def facts_kept(draft: str, out: str) -> list[str]:
    """원문에 있는데 다듬은 글에서 빠진 숫자들 (비어 있으면 모두 그대로)."""
    flat = re.sub(r"\s", "", out or "")
    return [f for f in dict.fromkeys(_FACT.findall(draft or "")) if re.sub(r"\s", "", f) not in flat]


AI_SYSTEM = """당신은 공공기관 직원의 글을 다듬는 비서입니다. 사용자가 대충 쓴 메모를 요청한 형식의 글로 다듬어 JSON으로만 답하세요.
- subject: 제목 (40자 이내)
- body: 다듬은 본문 (요청한 형식에 맞게, 정중하고 간결하게)
규칙: 메모에 없는 사실·날짜·숫자·이름·장소를 만들지 마세요. 메모의 숫자·날짜·금액·연락처는 한 글자도 바꾸지 마세요.
모르는 내용은 ○○○로 남기세요. 마크다운 기호(**, #)는 쓰지 마세요."""

KIND_GUIDE = {
    "mail": "업무 메일: 인사(안녕하세요. 부서 이름입니다.) → 목적 한 문장 → ■ 주요 내용 / ■ 요청 사항 / ■ 문의 → "
            "맺음말(감사합니다.) 순서. 존댓말 문장(~습니다/~드립니다). 서명은 쓰지 마세요. 제목은 [안내]·[요청]·[공유] 같은 머리표로 시작.",
    "official": "공문(기안문): 수신 / (경유) / 제목 줄 → 1. 관련 → 2. 목적 문장('~하오니 ~하여 주시기 바랍니다.') 아래 "
                "가. 나. 다. 개조식 항목 → 3. 이후 요청·문의 → 붙임 … 1부.  끝. 항목은 명사형으로 짧게.",
    "report": "보고서(개조식): 첫 줄 제목, 둘째 줄 날짜·부서, □ 개요 / □ 주요 내용 / □ 요청 사항 및 향후 계획, "
              "○ 항목, - 세부. 모든 문장은 '~함', '~임', '~예정'으로 끝냄. 인사말·존댓말 금지.",
    "message": "알림 메시지(메신저): 첫 줄 '[부서 이름] ~드립니다.' 뒤에 ▶ 로 시작하는 핵심 2~4줄, 필요하면 (문의: …). "
               "제목은 빈 문자열. 인사·맺음말 없이 짧게.",
}


def ai_polish(client, model: str, draft: str, kind: str, rule: dict, example: str = "", num_ctx: int = 4096) -> dict:
    """AI로 다듬는다. 숫자·날짜가 바뀌면 LLMError (호출하는 쪽이 규칙 결과를 쓴다)."""
    ex = f"\n[따라 할 내 양식 (짜임·문체만 참고, 내용은 쓰지 말 것)]\n{example[:1200]}\n" if example else ""
    user = (f"[형식]\n{KIND_GUIDE.get(kind, KIND_GUIDE['mail'])}\n{ex}\n[메모]\n{draft[:2000]}\n\n"
            f"[규칙으로 만든 초안 — 이 짜임(항목 순서·기호·줄 나눔)을 그대로 두고 문장만 자연스럽게 다듬으세요]\n{rule['body'][:1500]}")
    schema = {"type": "object", "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
              "required": ["subject", "body"]}
    limit = min(1200, int(len(rule["body"]) * 1.3) + 200)
    raw = client.chat([{"role": "system", "content": AI_SYSTEM}, {"role": "user", "content": user}], model,
                      temperature=0.3, num_ctx=num_ctx, fmt=schema, max_tokens=limit)
    try:
        data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except ValueError as e:
        raise LLMError("AI 응답을 해석하지 못했습니다") from e
    body = clean_polished(str(data.get("body") or ""), draft)
    subject = "" if kind == "message" else (re.sub(r"\s+", " ", str(data.get("subject") or "")).strip()[:60] or rule["subject"])
    lost = facts_kept(draft, subject + "\n" + body)
    if len(body) < 10 or lost:
        raise LLMError("AI가 원문의 숫자·날짜를 바꾸거나 빠뜨려 규칙으로 다듬은 결과를 보여 줍니다"
                       + (f" (빠진 값: {', '.join(lost[:3])})" if lost else ""))
    return {"subject": subject, "body": body}


def template_from_example(text: str, profile: dict | None = None) -> dict:
    """보낸 메일을 붙여 넣으면 내 양식으로: 내 이름·부서·연락처·메일은 변수로, '제목:' 줄은 메일 제목으로."""
    profile = profile or {}
    lines = (text or "").replace("\r", "").strip().splitlines()
    if not lines:
        raise ValueError("양식으로 만들 메일 내용을 붙여 넣으세요")
    subject = ""
    if re.match(r"^\s*(?:제목|Subject)\s*[:：]", lines[0], re.I):
        subject = re.sub(r"^\s*(?:제목|Subject)\s*[:：]\s*", "", lines.pop(0), flags=re.I).strip()
    body = "\n".join(lines).strip()
    for key, var in (("user_name", "내이름"), ("user_dept", "내부서"), ("user_phone", "내연락처"), ("user_email", "내메일")):
        v = (profile.get(key) or "").strip()
        if len(v) >= 2:
            body = body.replace(v, "{{" + var + "}}")
            subject = subject.replace(v, "{{" + var + "}}")
    return {"subject": subject, "body": body}

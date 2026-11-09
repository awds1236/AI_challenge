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
    l = re.sub(r"했습니다$", "함", l)
    l = re.sub(r"합니다$|하겠습니다$", "함", l)
    l = re.sub(r"입니다$", "임", l)
    l = re.sub(r"됩니다$", "됨", l)
    l = re.sub(r"(부탁드립니다|바랍니다)$", "요청", l)
    l = re.sub(r"\s*(?:해\s*줘|해\s*주세요|해주세요|해\s*주시기\s*바람)$", " 요청", l)
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

    if kind == "official":
        items = [_sentence(l) for l in rest]
        body = [f"제목: {subject}", "", "1. 관련: ○○○", f"2. {items[0]}" if items else "2. ○○○"]
        for i, l in enumerate(items[1:]):
            body.append(f"  {'가나다라마바사아자차카타파하'[i % 14]}. {l}")
        body += ["", "붙임 ○○○ 1부.  끝."]
        return {"subject": subject, "body": "\n".join(body)}
    if kind == "report":
        body = [f"□ {subject}"] + [f" ○ {_nominal(l)}" for l in rest if _nominal(l) != subject]
        return {"subject": subject, "body": "\n".join(body)}
    if kind == "message":
        head = f"[{dept} {name}] ".replace("[ ", "[").replace(" ]", "]") if (dept or name) else ""
        return {"subject": subject, "body": head + " ".join(_sentence(l) for l in rest)}
    # 업무 메일
    who = " ".join(x for x in (dept, name) if x)
    greet = f"안녕하세요. {who}입니다." if who else "안녕하세요."
    paras = [_sentence(l) for l in rest]
    closing = "" if re.search(r"(감사합니다|부탁드립니다|바랍니다)\.?$", paras[-1]) else "확인 부탁드립니다."
    body = [greet, ""] + paras + ([""] + [closing] if closing else []) + ["", "감사합니다."]
    sig = _signature(profile)
    if sig:
        body += ["", sig]
    return {"subject": subject, "body": "\n".join(body)}


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
    "mail": "업무 메일: 인사(안녕하세요. 부서 이름입니다.) → 용건 → 요청 사항 → 맺음말(감사합니다.) 순서. 서명은 쓰지 마세요.",
    "official": "공문(기안문): '제목:' 다음 1. 관련, 2. 본문 항목(가. 나. 다.)으로 개조식, 마지막에 '끝.'.",
    "report": "보고(개조식): □ 대제목, ○ 항목, - 세부. 문장은 '~함', '~임'으로 끝냄.",
    "message": "알림 메시지(메신저): 2~4문장의 짧은 존댓말. 인사와 핵심만.",
}


def ai_polish(client, model: str, draft: str, kind: str, rule: dict, example: str = "", num_ctx: int = 4096) -> dict:
    """AI로 다듬는다. 숫자·날짜가 바뀌면 LLMError (호출하는 쪽이 규칙 결과를 쓴다)."""
    ex = f"\n[따라 할 내 양식 (짜임·문체만 참고, 내용은 쓰지 말 것)]\n{example[:1200]}\n" if example else ""
    user = (f"[형식]\n{KIND_GUIDE.get(kind, KIND_GUIDE['mail'])}\n{ex}\n[메모]\n{draft[:2000]}\n\n"
            f"[규칙으로 만든 초안 (참고)]\n{rule['body'][:1500]}")
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
    subject = re.sub(r"\s+", " ", str(data.get("subject") or "")).strip()[:60] or rule["subject"]
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

"""공문 본문 정리: 군더더기 제거, '가. 항목 : 값' 해석, 규칙 기반 요약·할 일 문장 만들기.

공공기관 공문은 행정업무운영규정에 따른 공통 서식(수신·제목·본문 1./가./1)·붙임·끝.)을 쓰므로
기관이 달라도 같은 규칙으로 핵심을 뽑을 수 있다.
"""
from __future__ import annotations

import re

_HEADER = re.compile(r"^\s*(수\s*신(\s*자)?(\s*참\s*조)?|\(?\s*경\s*유\s*\)?|제\s*목|발\s*신|참\s*조)\s*[:：]?\s*$")
_HEADER_INLINE = re.compile(r"^\s*(수\s*신|\(\s*경\s*유\s*\)|참\s*조)\s+\S")
_GREETING = re.compile(r"(무궁한\s*발전|발전을\s*기원|건승|노고에\s*(깊이\s*)?감사|평안하시|귀\s*기관의\s*(무궁한\s*)?발전|"
                       r"늘\s*협조해\s*주셔서|감사드립니다\s*\.?$)")
_FOOTER = re.compile(r"^\s*(기안자|검토자|결재권자|협조자|시행|접수|우\s*\d{5}|우편번호|공개구분|전결|대결|"
                     r"직인생략|담당|팀장|과장|부장|국장)\b")
_ENUM = re.compile(r"^\s*(?:\d{1,2}\s*[.)]|[가-하]\s*[.)]|\(\s*\w\s*\)|[①-⑳]|[-·○◦•※□■▶])\s*")
_FIELD = re.compile(r"^\s*(?:[가-하]\s*[.)]|\d{1,2}\s*[.)]|\(\s*\w\s*\)|[-·○◦•□])?\s*"
                    r"(?P<label>[가-힣][가-힣 ·/]{0,14}?)\s*[:：]\s*(?P<value>\S.*)$")
_PHONE_OR_MAIL = re.compile(r"(0\d{1,2}[-)\s.]?\d{3,4}[-\s.]\d{4}|[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,})")


def clean_body(body: str, title: str = "") -> str:
    """슬로건·기관명·수신/경유·인사말·결재란 등을 뺀 본문."""
    lines = [l.rstrip() for l in (body or "").splitlines()]
    # 앞부분 슬로건·기관명: '수신' 줄이 앞쪽에 있으면 그 앞은 버린다
    for i, l in enumerate(lines[:20]):
        if re.match(r"^\s*수\s*신", l):
            lines = lines[i:]
            break
    out, after_end = [], False
    for l in lines:
        s = l.strip()
        if not s:
            continue
        if after_end:      # '끝.' 뒤(발신 명의·결재란)는 연락처 줄만 남긴다
            if _PHONE_OR_MAIL.search(s):
                out.append(s)
            continue
        if _HEADER.match(s) or _HEADER_INLINE.match(s) or s in ("수신자 참조", "내부결재"):
            continue
        if title and s.replace(" ", "") == title.replace(" ", ""):
            continue
        if re.match(r"^\s*제\s*목\s*[:：]?\s*\S", s):
            continue
        if _GREETING.search(s) and len(s) < 80:
            continue
        if _FOOTER.match(s) and len(s) < 120:
            continue
        out.append(s)
        if re.search(r"끝\s*\.\s*$", s):
            after_end = True
    return "\n".join(out)


def extract_fields(body: str) -> dict[str, str]:
    """'가. 조 사 명 : ○○' 같은 항목을 {'조사명': '○○'}으로."""
    fields: dict[str, str] = {}
    for line in (body or "").splitlines():
        m = _FIELD.match(line)
        if not m:
            continue
        label = re.sub(r"[\s·]", "", m.group("label"))
        if 2 <= len(label) <= 8 and label not in fields:
            fields[label] = m.group("value").strip()
    return fields


def _get(fields: dict, *keys: str) -> tuple[str, str]:
    for k in keys:
        for label, v in fields.items():
            if label == k or label.endswith(k):
                return label, v
    return "", ""


def _simplify(sentence: str) -> str:
    s = _ENUM.sub("", sentence).strip()
    s = re.sub(r"\s*(다음과|아래와)\s*같이\s*", " ", s)
    s = re.sub(r"하오니\s*(적극\s*)?(협조|회신|참여|제출)\s*하여\s*주시기\s*바랍니다\s*\.?", r"하니 \2 요청", s)
    s = re.sub(r"(하여|해)\s*주시기\s*바랍니다\s*\.?", " 요청", s)
    s = re.sub(r"(알려\s*드리오니|알려드리니|안내\s*드리오니).*$", "안내", s)
    s = re.sub(r"\s*바랍니다\s*\.?$", " 요청", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" .")
    return s[:160]


def purpose_sentence(clean: str) -> str:
    """번호 문단(1., 2. …) 중 요청·안내 내용을 담은 첫 문단."""
    paras, cur = [], ""
    for line in clean.splitlines():
        if re.match(r"^\s*\d{1,2}\s*[.)]\s*\S", line):
            if cur:
                paras.append(cur)
            cur = line.strip()
        elif cur and not re.match(r"^\s*([가-하]\s*[.)]|[-·○※□])", line) and len(cur) < 400:
            cur += " " + line.strip()
        elif cur:
            paras.append(cur)
            cur = ""
    if cur:
        paras.append(cur)
    for p in paras:
        if re.search(r"(관련\s*[:：]|^\s*\d+\s*[.)]\s*관련)", p):
            continue
        if re.search(r"(요청|협조|바랍니다|알려|안내|제출|회신|개최|시행|신청|조사|통보|추천|참석)", p):
            return _simplify(p)
    return _simplify(paras[0]) if paras else ""


DETAIL_KEYS = [("조사명",), ("행사명", "교육명", "회의명", "사업명"), ("일시", "기간"), ("장소",),
               ("대상",), ("회신자료", "제출서류", "제출자료", "신청서류", "제출물"),
               ("회신기한", "제출기한", "신청기한", "접수기한", "기한"), ("회신방법", "제출방법", "신청방법", "접수방법")]


def rule_summary(title: str, clean: str, fields: dict) -> str:
    purpose = purpose_sentence(clean) or title
    details = []
    for keys in DETAIL_KEYS:
        label, v = _get(fields, *keys)
        if v:
            details.append(f"{label}: {v[:80]}")
    s = purpose if purpose.endswith(("요청", "안내", "알림", "협조")) else purpose
    return s + (" — " + " / ".join(details[:5]) if details else "")


def clean_what(context: str, raw_date: str, fields: dict, title: str) -> str:
    """기한 줄을 '조사표 회신' 같은 할 일 문장으로."""
    s = _ENUM.sub("", context or "").strip()
    m = re.match(r"^(회신|제출|신청|접수|보고|등록|추천|통보)\s*기\s*한\s*[:：]?", s.replace(" ", "")[:12])
    if m or re.match(r"^(회\s*신|제\s*출|신\s*청|접\s*수|보\s*고|등\s*록|추\s*천|통\s*보)\s*기\s*한", s):
        verb = re.sub(r"\s", "", s)[:2]
        _l, obj = _get(fields, f"{verb}자료", f"{verb}서류", "제출서류", "제출자료", "회신자료", "제출물")
        obj = re.sub(r"(붙\s*임|첨\s*부)\s*\d*\s*", "", obj)
        obj = re.sub(r"\s*(각\s*)?\d+\s*부\.?", "", obj).strip(" .,")
        return f"{obj} {verb}".strip() if obj else f"{title} {verb}".strip()
    if raw_date:
        s = s.replace(raw_date, " ")
    s = re.sub(r"^\s*(까지|한)\b", "", re.sub(r"(?<=\s)(까지|한)(?=\s|$)", "", s))
    s = re.sub(r"\t+", " · ", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" ·.,:")
    return s[:120] or title


# ---------------------------------------------------------------- 할 일 제목
_PURPOSE = re.compile(r"^.*?(?:을|를)?\s*(?:위해서?|위하여|위한|관련하여|관련|에\s*따라|에\s*의거하여|에\s*의거|하고자)\s+")
_SUBJECT = re.compile(r"^(?:각|귀|해당)?\s*[^\s]{0,12}?(?:에서는|에서|께서는)\s+")
_YEAR = re.compile(r"(?:20\d{2}|'\d{2})\s*년\s*(?:도)?\s*(?:부터|까지|에|중)?\s*")
_ENDING = re.compile(r"\s*(?:하여|해)\s*주(?:시기\s*바랍니다|시기\s*바람|십시오|시기|시고|길|시)?\s*\.?\s*$"
                     r"|\s*(?:하시기\s*)?(?:바랍니다|바람|요망)\.?\s*$")


def short_task(text: str, limit: int = 34) -> str:
    """공문 문장을 '서비스 개선과제 발굴·작성·제출'처럼 짧은 할 일 제목으로 줄인다.
    목적절(~을 위해), 주어(각 처·실에서는), 연도, 공문 어미(~하여 주시기 바랍니다), 붙임 표시를 뺀다."""
    s = re.sub(r"^\[[^\]]{1,60}\]\s*", "", (text or "").strip())          # 앞의 [공문 이름]
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\(\s*(?:붙\s*임|첨\s*부|별\s*첨|서\s*식)\s*\d*\s*(?:서식)?\s*\)", "", s)
    s = re.sub(r"(?:붙\s*임|별\s*첨)\s*\d*\s*(?=\S*서식)", "", s)
    before = s
    s = _PURPOSE.sub("", s)
    if len(s) < 6:
        s = before
    s = _SUBJECT.sub("", s)
    s = _YEAR.sub("", s)
    s = re.sub(r"^(?:추진|제출|작성|시행|실시|개최|운영)(?:할|한|될|된)\s+", "", s)     # '추진할 서비스…'
    s = _ENDING.sub("", s)
    s = re.sub(r"(?:을|를)\s+(발굴|작성|검토|취합|파악|조사|정리|확인)하여\s+", r" \1·", s)
    s = re.sub(r"\S*서식(?:으로|에)\s*", "", s)
    s = re.sub(r"\s*,\s*", "·", s)
    s = re.sub(r"(?:하여|하고)\s+(제출|회신|보고|신청|통보)$", r"·\1", s)
    s = re.sub(r"·+", "·", s).strip(" ·.,:")
    if len(s) > limit:                       # 단어 중간에서 자르지 않는다
        cut = s[:limit]
        sp = max(cut.rfind(" "), cut.rfind("·"))
        s = (cut[:sp] if sp > limit // 2 else cut).rstrip(" ·,") + "…"
    return s or (text or "").strip()[:limit]

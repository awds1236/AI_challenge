"""공문 분석기: 제출 기한·제출물·해야 할 일 정리 (로컬 LLM + 규칙 기반 보완)."""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from .deadlines import clean_contact_text, find_dates, best_deadlines, find_contacts, find_methods, find_submissions
from .llm import LLMError, OllamaClient, extract_json
from .notice_text import clean_body, clean_what, extract_fields, item_names, object_phrase, rule_summary, _get
from .parsers import READABLE_EXT, ParseError, parse_file

SCHEMA = {
    "type": "object",
    "properties": {
        "folder_name": {"type": "string"},
        "summary": {"type": "string"},
        "event": {"type": "object", "properties": {
            "name": {"type": "string"}, "date": {"type": "string"}, "place": {"type": "string"}}},
        "deadlines": {"type": "array", "items": {"type": "object", "properties": {
            "date": {"type": "string"}, "time": {"type": "string"}, "what": {"type": "string"}},
            "required": ["date", "what"]}},
        "submissions": {"type": "array", "items": {"type": "object", "properties": {
            "item": {"type": "string"}, "how": {"type": "string"}, "to": {"type": "string"}},
            "required": ["item"]}},
        "actions": {"type": "array", "items": {"type": "string"}},
        "contact": {"type": "string"},
    },
    "required": ["folder_name", "summary", "deadlines", "submissions", "actions"],
}

# 고정 지시문은 system 메시지로 둔다: 내용이 매번 같아 엔진이 계산 결과를 재사용한다(프롬프트 캐시).
SYSTEM = """당신은 공공기관 서무 직원을 돕는 비서입니다. 사용자가 주는 공문 본문과 붙임 발췌를 읽고 JSON으로 정리하세요.

- folder_name: 폴더 이름으로 쓸 짧은 제목 (예: "OO행사 참여 요청", 25자 이내, 특수문자 금지)
- summary: 이 공문이 '무엇을 요청·안내하는지'를 중심으로 2문장. 무엇을, 언제까지, 어떻게 해야 하는지 포함.
  공문 어미('~하오니', '~하고자 합니다', '~바랍니다')를 쓰지 말고 '~해야 합니다' 문체로 쓰세요.
  기관 슬로건, 인사말('귀 기관의 무궁한 발전을…'), 수신·경유·발신 명의는 절대 넣지 마세요.
- event: 행사/교육이 있으면 이름(name), 일시(date), 장소(place)
- deadlines: 우리 기관(수신자)이 지켜야 할 제출·회신·신청 기한. date는 YYYY-MM-DD, time은 HH:MM(없으면 빈 문자열),
  what은 '조사표 회신', '참가신청서 제출'처럼 짧은 할 일 문장 (항목 번호·'회신기한 :' 같은 표기 제외)
- submissions: 제출해야 할 문서/자료. item(서류명), how(제출 방법: 공문, 전자우편 등), to(제출처)
- actions: 담당자가 해야 할 일을 순서대로, '○○ 작성', '○○ 제출'처럼 명사형으로 짧게 (5개 이내, 날짜는 넣지 마세요)
- contact: 문의처 (부서, 전화, 메일)

본문에 없는 내용은 만들지 말고 빈 값으로 두세요. 날짜에 연도가 없으면 오늘 기준으로 가장 가까운 미래 연도를 쓰세요.
요청한 항목만 짧게 쓰세요."""

PROMPT = """오늘 날짜: {today}

[규칙으로 먼저 찾은 기한 (참고)]
{hints}

[공문 본문]
{body}

[붙임 문서 발췌]
{attach}
"""

# 규칙 기반 추출로 이미 정확히 얻은 항목은 AI에게 다시 쓰게 하지 않는다 (생성 토큰 = 시간)
_HINT_KEYS = ("제출기한", "회신기한", "신청기한", "제출서류", "회신자료", "제출자료")


def ai_schema(base: dict, body: str = "", title: str = "") -> dict:
    """AI가 꼭 채워야 할 항목만 담은 스키마 (생성하는 글자 수 = CPU에서 걸리는 시간).
    문의처·할 일 목록은 규칙으로 만들고, 행사 정보는 행사·교육 공문일 때만, 폴더 이름은 제목이 길 때만 묻는다."""
    props = dict(SCHEMA["properties"])
    props.pop("contact", None)                    # 규칙이 더 정확하다 (AI는 꼬리말 주소까지 넣는다)
    props.pop("actions", None)                    # 기한·제출물에서 만든다
    ev = base.get("event") or {}
    if (ev.get("name") and ev.get("date")) or not re.search(r"(행사|교육|연수|설명회|간담회|회의|대회|축제|개최|일시)", body):
        props.pop("event", None)
    if title and len(title) <= 30 and not re.search(r"^(?:\[|붙임|제목)", title):
        props.pop("folder_name", None)
    return {"type": "object", "properties": props,
            "required": [k for k in SCHEMA["required"] if k in props]}


# AI에게 붙임 내용을 줄 때는 글자로 된 문서만 (그림·스캔 PDF는 글자 인식에 수십 초가 걸린다)
_FAST_ATTACH_EXT = {".hwp", ".hwpx", ".docx", ".txt", ".xlsx", ".odt"}


def read_attachments(files: list[dict], max_files: int = 2, max_chars: int = 700) -> list[dict]:
    out = []
    for f in files:
        if not f.get("ok") or not f.get("path"):
            continue
        p = Path(f["path"])
        if p.suffix.lower() not in READABLE_EXT or p.suffix.lower() not in _FAST_ATTACH_EXT:
            continue
        try:
            t = parse_file(p)
        except (ParseError, OSError, ValueError, KeyError):
            continue
        out.append({"name": p.name, "text": t[:max_chars]})
        if len(out) >= max_files:
            break
    return out


def trim_body(body: str, limit: int = 3000) -> str:
    """공문 본문을 limit자 안으로 줄인다: 빈 줄·결재란 등 군더더기를 빼고 앞부분(핵심)을 남긴다."""
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in body.splitlines()]
    lines = [l for l in lines if l and not re.fullmatch(r"[-=_·.\s]+", l)]
    text = "\n".join(lines)
    if len(text) <= limit:
        return text
    # 기한·제출과 관련된 줄은 뒤쪽에 있어도 살린다
    head = text[: int(limit * 0.75)]
    key = [l for l in lines[len(head.splitlines()):] if re.search(r"(까지|기한|제출|회신|붙임|문의)", l)]
    return head + "\n…\n" + "\n".join(key)[: limit - len(head)]


def _norm_date(s: str) -> str | None:
    if not s:
        return None
    m = re.search(r"(20\d{2})\D{1,3}(\d{1,2})\D{1,3}(\d{1,2})", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


# 붙임 중 '작성해서 내야 하는 서류'로 볼 만한 이름 / 참고용 자료로 볼 이름
_FORM_WORDS = re.compile(r"(서식|양식|신청서|조사표|계획서|명단|확인서|동의서|보고서|제출서|현황표|점검표|체크리스트|"
                         r"작성표|명세서|목록|카드|이력서|추천서|제안서|응답지|설문지|대장|실적)")
_REFERENCE_WORDS = re.compile(r"(안내문|안내서|안내|계획(?:\(안\))?$|공고문?|내규|지침|매뉴얼|가이드|리플릿|포스터|홍보물|"
                              r"요령|규정|법령|사례집|참고|목록\s*$|일정표|프로그램|\(초안\)|초안$)")


def _core(s: str) -> str:
    s = re.sub(r"^\[붙임\]\s*", "", s)
    s = re.sub(r"(서식|양식|\(.*?\)|\d+\s*부|붙\s*임|첨\s*부|각|\s|\.\w{2,5}$)", "", s)
    return s


def _merge_deadlines(deadlines: list[dict]) -> list[dict]:
    """같은 날짜의 기한은 하나로 (시각이 있고 할 일 문장이 짧은 쪽을 남긴다)."""
    best: dict[str, dict] = {}
    for d in deadlines:
        cur = best.get(d["date"])
        if cur is None or (bool(d["time"]), -len(d["what"])) > (bool(cur["time"]), -len(cur["what"])):
            best[d["date"]] = d
    return sorted(best.values(), key=lambda d: (d["date"], d["time"]))


def event_info(fields: dict) -> dict:
    """행사·교육 정보. '일시' 하나만 있으면(발표 일시·접수 일시 등) 행사로 보지 않는다 — 행사명이나 장소가 있어야 한다."""
    ev = {k: v for k, v in (("name", _get(fields, "행사명", "교육명", "회의명", "설명회명", "연수명")[1]),
                            ("date", _get(fields, "일시")[1]), ("place", _get(fields, "장소")[1])) if v}
    return ev if (ev.get("name") or ev.get("place")) else {}


def rule_analysis(title: str, body: str, attach_texts: list[dict], ref: date | None = None) -> dict:
    clean = clean_body(body, title)
    fields = extract_fields(clean)
    deadlines = []
    for d in best_deadlines(clean, ref):
        before = clean[:d["pos"]].splitlines()[-12:]
        # 위쪽 번호 제목('1. … 등록 원서 제출')과 표 머리글의 동사('신청 기간' → 신청)
        heading = next((l for l in reversed(before[:-1]) if re.match(r"^\s*\d{1,2}\s*[.)]\s*\S", l)), "")
        tv = next((m.group(1) for l in reversed(before[-8:]) for m in [re.search(r"(신청|제출|접수|모집|공모|응모)\s*기\s*간", l)] if m), "")
        ln = clean.count("\n", 0, d["pos"])
        prev = clean.splitlines()[ln - 1] if ln > 0 else ""
        deadlines.append({"date": d["date"], "time": d["time"] or "",
                          "what": clean_what(d["context"], d["raw"], fields, title, heading, tv, prev), "source": "규칙"})
    # '관리기관 제출'처럼 받는 곳만 남은 할 일: 본문의 '○○를 … 제출하여 주시기 바랍니다'에서 무엇을 내는지 채운다
    for d in deadlines:
        m = re.fullmatch(r"(?:\S+\s+)?\S*(?:기관|과|팀|처|실|청|부서|센터|학교)\s*(?:으로|로|에)?\s*(제출|회신|송부|보고)", d["what"])
        if m:
            obj = next((o for line in clean.splitlines() if m.group(1) in line
                        for o in [object_phrase(line)] if o), "")
            if obj:
                d["what"] = f"{obj} {m.group(1)}"
    deadlines = _merge_deadlines(deadlines)
    _ml, method = _get(fields, "회신방법", "제출방법", "신청방법", "접수방법")
    _tl, to = _get(fields, "제출처", "회신처", "접수처", "신청처")
    subs: list[dict] = []
    _il, item = _get(fields, "회신자료", "제출서류", "제출자료", "신청서류", "제출물", "보고자료", "보고서류", "회신서류")
    # '참가 신청서(붙임 1 서식) 1부, 명단 1부' → 서류마다 한 줄. 붙임 서식 표시는 이름 옆에 남긴다
    word = re.search(r"(붙\s*임|첨\s*부|별\s*첨)", item or "")
    word = re.sub(r"\s", "", word.group(1)) if word else "붙임"
    for i, name in enumerate(item_names(item)):
        piece = next((p for p in re.split(r"\s*[,，]\s*", item) if name in p), "")
        mark = f" ({word} 서식)" if re.search(r"(붙\s*임|첨\s*부|별\s*첨|서식|양식)", piece) else ""
        subs.append({"item": name + mark, "how": method if i == 0 else "", "to": to if i == 0 else ""})
    cores = {_core(s["item"]) for s in subs}
    late: list[str] = []
    for s in find_submissions(clean):
        core = _core(s)
        if not core or re.search(r"[:：]", s):
            continue
        hit = next((x for x in subs if _core(x["item"]) and (_core(x["item"]) in core or core in _core(x["item"]))), None)
        if hit or any(core in c or c in core for c in cores if c):
            # '회신자료 : 붙임 조사표'와 '[붙임] ○○ 현황 조사표'는 같은 서류 → 붙임의 정식 이름으로
            if hit and s.startswith("[붙임]") and len(core) > len(_core(hit["item"])) and "," not in s:
                full = re.sub(r"\.(hwpx?|pdf|docx?|xlsx?|txt|zip|pptx?|odt|cell|show)$", "", s.replace("[붙임] ", ""), flags=re.I)
                full = re.sub(r"\s*(서식|양식)$", "", full)
                hit["item"] = full + (" (" + hit["item"].split("(", 1)[1] if "(" in hit["item"] else "")
            continue
        if s.startswith("[붙임]"):
            name = s.replace("[붙임] ", "")
            stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", name)        # '지정 검진기관 목록.pdf' → 확장자를 떼고 본다
            # 참고용 붙임(안내문·계획·지침·검토용 초안)은 제출물이 아니다. 서식·신청서·조사표만 남긴다
            if not _FORM_WORDS.search(stem) or (_REFERENCE_WORDS.search(stem) and not re.search(r"(서식|양식)", stem)):
                continue
            s = re.sub(r"\s*\(?(서식|양식)\)?$", "", stem) + " (붙임 서식)"
        elif len(s) > 40 or re.search(r"(바랍니다|주시기|요청|부탁|드립니다|합니다|십시오|하여|바람)", s):
            # 요청 문장은 그대로 제출물 이름이 아니다 → '무엇을 제출'의 '무엇'만 ('부서별 폐기 물품 목록').
            # 붙임 목록·서류 항목을 다 본 뒤에 겹치지 않을 때만 더한다 (붙임의 정식 이름·서식 표시를 살린다)
            obj = object_phrase(s)
            if obj and re.search(r"(서|목록|명단|계획|결과|현황|자료|양식|서식|사본|증빙|파일|표)(?:\([^)]{1,30}\))?$", obj):
                late.append(obj)
            continue
        cores.add(core)
        subs.append({"item": s, "how": method if not subs else "", "to": ""})
    for obj in late:
        core = _core(obj)
        if core and not any(core in c or c in core for c in cores if c):
            cores.add(core)
            subs.append({"item": obj, "how": method if not subs else "", "to": ""})
    actions = [f"{d['what']} ({int(d['date'][5:7])}/{int(d['date'][8:10])}까지)" for d in deadlines][:5]
    if method:
        actions.append(method if re.search(r"(제출|회신|신청|접수|등록)\s*$", method) else f"제출 방법: {method}")
    contacts = [c for c in find_contacts(body) if not re.search(r"(회신|제출|신청)\s*방\s*법", c)]
    _ql, ask = _get(fields, "문의처", "문의", "담당자", "연락처")
    return {
        "folder_name": title,
        "summary": rule_summary(title, clean, fields, deadlines),
        "event": event_info(fields),
        "deadlines": deadlines,
        "submissions": subs,
        "actions": actions,
        "contact": clean_contact_text(ask) if ask else "\n".join(contacts[:2]),
        "methods": [method] if method else find_methods(clean),
        "fields": fields,
        "attachments_read": [a["name"] for a in attach_texts],
        "mode": "rule",
    }


# ---------------------------------------------------------------- AI 결과 다듬기 (작은 모델은 문체가 들쭉날쭉하다)
def tidy_ai_summary(s: str) -> str:
    """AI 요약에 남은 공문 어미를 정리한다: '실시하오니, 각 학교는' → '실시하므로 각 학교는'."""
    s = re.sub(r"하오니\s*,?\s*", "하므로 ", s or "")
    s = re.sub(r"(?:하고자|하려고)\s*합니다", "합니다", s)
    s = re.sub(r"하여\s*주시기\s*바랍니다", "해야 합니다", s)
    s = re.sub(r"\s*바랍니다\.", "해야 합니다.", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def _iso_to_short(m) -> str:
    return f"{int(m.group(2))}. {int(m.group(3))}."


def tidy_ai_action(a: str) -> str:
    """'교육 이수 결과 보고서를 작성합니다.' → '교육 이수 결과 보고서 작성', '2026-12-02까지' → '12. 2.까지'."""
    a = re.sub(r"^\d+\s*[.)]\s+", "", (a or "").strip())           # 목록 번호 (날짜로 바꾸기 전에)
    a = re.sub(r"(20\d{2})-(\d{2})-(\d{2})", _iso_to_short, a)
    a = re.sub(r"\s*(?:해야\s*)?(?:합니다|됩니다|입니다)\.?$", "", a)
    a = re.sub(r"(?:을|를)\s+(\S+?)(?:하|해)?$", r" \1", a)          # '보고서를 작성' → '보고서 작성'
    a = re.sub(r"(작성|제출|회신|확인|취합|검토|신청|등록|보고|이수|참석|변경|실시|완료)(?:하기|함)$", r"\1", a)
    return a.strip(" .")


def tidy_ai_item(item: str) -> str:
    """AI 제출물 이름을 규칙 분석과 같은 모양으로: '현황표(붙임 1 서식) 1부' → '현황표 (붙임 서식)'."""
    word = re.search(r"(붙\s*임|첨\s*부|별\s*첨)", item or "")
    names = item_names(item or "")
    if not names:
        return (item or "").strip()
    label = re.sub(r"\s", "", word.group(1)) if word else "붙임"
    mark = f" ({label} 서식)" if word or re.search(r"(서식|양식)", item) else ""
    return " · ".join(names) + mark


# 공문 제목에 흔한 말 (이것만 겹치면 같은 공문 이름이라고 볼 수 없다)
_GENERIC_WORDS = {"요청", "안내", "협조", "제출", "조사", "회신", "참석", "참여", "관련", "알림", "통보", "개최", "실시",
                  "계획", "결과", "보고", "부서별", "부서", "시행", "추진", "신청", "접수", "공문", "자료", "현황", "대한",
                  "위한", "건", "및", "년", "년도", "연도", "회계연도", "학년도", "상반기", "하반기"}


def _keeps_subject(name: str, title: str) -> bool:
    """AI가 지은 이름이 공문 제목의 핵심어(흔한 말·연도를 뺀 낱말)를 지키는지.
    '2026년 송년 행사 참석 조사' → '부서별 참석 인원 회신 요청'처럼 무엇에 관한 공문인지가 빠진 이름은 쓰지 않는다."""
    def words(s: str) -> list[str]:
        out = []
        for w in re.split(r"[\s,·/()「」\[\]_\-]+", s or ""):
            w = re.sub(r"^\d+(?:회계)?(?:년도|년|학년도)?", "", w)       # '2026년' '2026회계연도' 앞의 숫자
            w = re.sub(r"(?:을|를|의|에|과|와|및)$", "", w)
            if len(w) >= 2 and w not in _GENERIC_WORDS:
                out.append(w)
        return out
    key = words(title)
    if not key:
        return True
    have = words(name)
    hit = sum(1 for k in key if any(k in h or h in k for h in have))
    return hit >= max(1, (len(key) + 1) // 2)


def _shares_word(name: str, title: str) -> bool:
    """두 글자 이상 낱말(또는 그 일부)을 하나라도 함께 쓰는지."""
    words = [w for w in re.split(r"[\s,·/()「」\[\]_]+", name or "") if len(w) >= 2]
    ref = [w for w in re.split(r"[\s,·/()「」\[\]_]+", title or "") if len(w) >= 2]
    if not ref:
        return True
    return any(w in r or r in w for w in words for r in ref)


def in_body_dates(body: str, ref: date) -> set[str]:
    found = find_dates(body or "", ref)
    return {x["date"] for x in found} | {x["end_date"] for x in found if x.get("end_date")}


def analyze(title: str, body: str, files: list[dict], client: OllamaClient | None,
            chat_model: str = "", num_ctx: int = 8192, ref: date | None = None) -> dict:
    ref = ref or date.today()
    if client is None:
        # 규칙 분석은 붙임 내용을 쓰지 않는다 → 붙임(스캔 PDF는 글자 인식에 수십 초)을 읽지 않아 수집이 바로 끝난다
        return rule_analysis(title, body, [], ref)
    clean = clean_body(body, title)
    # 본문이 짧을 때만 붙임 발췌를 함께 준다 (입력이 길수록 CPU에서 오래 걸린다)
    attach = read_attachments(files, max_files=1, max_chars=600) if len(clean) < 800 else []
    base = rule_analysis(title, body, attach, ref)
    try:
        model = client.pick_chat_model(chat_model)
        attach_txt = "\n\n".join(f"<{a['name']}>\n{a['text']}" for a in attach) or "(없음)"
        # CPU에서는 '입력 읽기'가 가장 오래 걸린다: 본문에 이미 있는 항목은 다시 넣지 않고,
        # 기한 후보와 핵심 항목 몇 줄만 힌트로 준다
        fields = base.get("fields", {})
        hints = "\n".join([f"- {k}: {v}" for k, v in fields.items() if k in _HINT_KEYS][:4] +
                          [f"- 기한 후보: {d['date']} {d['what']}" for d in base["deadlines"][:5]]) or "(없음)"
        prompt = PROMPT.format(today=ref.isoformat(), body=trim_body(clean, 1800),
                               attach=attach_txt[:600], hints=hints)
        raw = client.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], model,
                          temperature=0.1, num_ctx=num_ctx, fmt=ai_schema(base, clean, title), max_tokens=400)
        data = extract_json(raw)
        if not isinstance(data, dict):
            raise LLMError("AI 응답을 해석할 수 없습니다")
    except LLMError as e:
        base["llm_error"] = str(e)
        return base

    result = dict(base)
    result["mode"] = "llm"
    result["model"] = model
    s_ai = data.get("summary") if isinstance(data.get("summary"), str) else ""
    s_dates = {x["date"] for x in find_dates(s_ai, ref)}
    if (s_ai.strip() and not re.search(r"(?<![가-힣A-Za-z])(OO|ＯＯ|○○)", s_ai)
            and s_dates <= in_body_dates(body, ref)):
        result["summary"] = s_ai.strip()            # 예시 글('OO 행사')을 베꼈거나 본문에 없는 날짜를 쓴 요약은 버린다
    elif s_ai.strip():
        result["ai_note"] = "AI 요약이 본문과 맞지 않아 규칙으로 만든 요약을 보여 줍니다"
    result["summary"] = tidy_ai_summary(result["summary"])
    fn = data.get("folder_name")
    if isinstance(fn, str) and 2 <= len(fn.strip()) <= 40 and _shares_word(fn, title) and _keeps_subject(fn, title):
        # 공문 제목과 겹치는 낱말이 없거나('테스트' 등 AI가 지어낸 이름), 무엇에 관한 공문인지(핵심어)가 빠진 이름은 쓰지 않는다
        result["folder_name"] = fn.strip()
    if isinstance(data.get("event"), dict):
        result["event"] = {k: str(v) for k, v in data["event"].items() if v}
    llm_dl = []
    in_body = in_body_dates(body, ref)
    for d in data.get("deadlines") or []:
        if not isinstance(d, dict):
            continue
        nd = _norm_date(str(d.get("date", "")))
        if not nd or nd not in in_body:          # 본문에 없는 날짜(오늘 날짜 등)를 기한으로 지어내지 않게
            continue
        llm_dl.append({"date": nd, "time": str(d.get("time") or "")[:5], "what": str(d.get("what") or "")[:160],
                       "source": "AI"})
    # 같은 날짜면 AI가 비워 둔 시각·문구를 규칙 결과로 채운다 (AI는 '17:00' 같은 시각을 자주 빠뜨린다)
    rule_by_date = {d["date"]: d for d in base["deadlines"]}
    for d in llm_dl:
        r = rule_by_date.get(d["date"])
        if r:
            d["time"] = d["time"] or r.get("time", "")
            d["what"] = d["what"] or r.get("what", "")
    # 규칙 기반으로 찾았지만 AI가 놓친 기한은 보존
    have = {d["date"] for d in llm_dl}
    llm_dl.extend(d for d in base["deadlines"] if d["date"] not in have)
    result["deadlines"] = sorted(llm_dl, key=lambda d: (d["date"], d["time"]))
    subs = []
    for s in data.get("submissions") or []:
        if isinstance(s, dict) and s.get("item"):
            subs.append({"item": tidy_ai_item(str(s["item"]))[:160], "how": str(s.get("how") or ""),
                         "to": str(s.get("to") or "")})
    if subs:
        result["submissions"] = subs
    acts = [tidy_ai_action(str(a))[:160] for a in (data.get("actions") or []) if str(a).strip()]
    if not acts:          # 할 일은 기한에서 만든다 (AI에게 따로 쓰게 하면 시간만 더 든다)
        acts = [f"{d['what']} ({int(d['date'][5:7])}/{int(d['date'][8:10])}까지)" for d in result["deadlines"] if d.get("what")][:5]
        acts += [a for a in base.get("actions", []) if not re.search(r"\(\d{1,2}/\d{1,2}까지\)$", a)]
    acts = [a for i, a in enumerate(acts) if a and a not in acts[:i]]
    if acts:
        result["actions"] = acts
    return result


def summary_markdown(title: str, url: str, analysis: dict, files: list[dict]) -> str:
    lines = [f"# {title}", "", f"- 출처: {url}", f"- 정리일시: {datetime.now():%Y-%m-%d %H:%M}",
             f"- 분석 방식: {'로컬 AI (' + analysis.get('model', '') + ')' if analysis.get('mode') == 'llm' else '규칙 기반'}",
             "", "## 요약", analysis.get("summary") or "-", ""]
    ev = analysis.get("event") or {}
    if ev:
        lines += ["## 행사 정보"] + [f"- {k}: {v}" for k, v in ev.items()] + [""]
    lines.append("## 제출 기한")
    for d in analysis.get("deadlines") or []:
        lines.append(f"- **{d['date']} {d.get('time') or ''}** — {d['what']}")
    if not analysis.get("deadlines"):
        lines.append("- 확인된 기한 없음")
    lines += ["", "## 제출물"]
    for s in analysis.get("submissions") or []:
        extra = " / ".join(x for x in (s.get("how"), s.get("to")) if x)
        lines.append(f"- {s['item']}" + (f" ({extra})" if extra else ""))
    if not analysis.get("submissions"):
        lines.append("- 확인된 제출물 없음")
    lines += ["", "## 할 일"] + [f"{i}. {a}" for i, a in enumerate(analysis.get("actions") or [], 1)]
    if analysis.get("contact"):
        lines += ["", "## 문의처", analysis["contact"]]
    lines += ["", "## 붙임 파일"]
    for f in files:
        lines.append(f"- {'✅' if f.get('ok') else '❌'} {f['name']}" + ("" if f.get("ok") else f" ({f.get('error', '')})"))
    return "\n".join(lines) + "\n"

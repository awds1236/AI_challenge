"""공문 분석기: 제출 기한·제출물·해야 할 일 정리 (로컬 LLM + 규칙 기반 보완)."""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from .deadlines import best_deadlines, find_contacts, find_methods, find_submissions
from .llm import LLMError, OllamaClient, extract_json
from .notice_text import clean_body, clean_what, extract_fields, item_names, rule_summary, _get
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
  기관 슬로건, 인사말('귀 기관의 무궁한 발전을…'), 수신·경유·발신 명의는 절대 넣지 마세요.
- event: 행사/교육이 있으면 이름(name), 일시(date), 장소(place)
- deadlines: 우리 기관(수신자)이 지켜야 할 제출·회신·신청 기한. date는 YYYY-MM-DD, time은 HH:MM(없으면 빈 문자열),
  what은 '조사표 회신', '참가신청서 제출'처럼 짧은 할 일 문장 (항목 번호·'회신기한 :' 같은 표기 제외)
- submissions: 제출해야 할 문서/자료. item(서류명), how(제출 방법: 공문, 전자우편 등), to(제출처)
- actions: 담당자가 해야 할 일을 순서대로 (짧은 문장, 5개 이내)
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


def ai_schema(base: dict) -> dict:
    """규칙으로 이미 찾은 문의처·행사 정보는 빼고, AI가 채워야 할 항목만 담은 스키마."""
    props = dict(SCHEMA["properties"])
    if base.get("contact"):
        props.pop("contact", None)
    ev = base.get("event") or {}
    if ev.get("name") and ev.get("date"):
        props.pop("event", None)
    return {"type": "object", "properties": props,
            "required": [k for k in SCHEMA["required"] if k in props]}


def read_attachments(files: list[dict], max_files: int = 2, max_chars: int = 700) -> list[dict]:
    out = []
    for f in files:
        if not f.get("ok") or not f.get("path"):
            continue
        p = Path(f["path"])
        if p.suffix.lower() not in READABLE_EXT:
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
                              r"요령|규정|법령|사례집|참고|목록\s*$|일정표|프로그램)")


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
            # 참고용 붙임(안내문·계획·지침)은 제출물이 아니다. 서식·신청서·조사표만 남긴다
            if not _FORM_WORDS.search(name) or (_REFERENCE_WORDS.search(name) and not re.search(r"(서식|양식)", name)):
                continue
            s = re.sub(r"\s*(서식|양식)$", "", name) + " (붙임 서식)"
        elif len(s) > 40:                       # 긴 문장은 제출물 이름이 아니다
            continue
        cores.add(core)
        subs.append({"item": s, "how": method if not subs else "", "to": ""})
    actions = [f"{d['what']} ({int(d['date'][5:7])}/{int(d['date'][8:10])}까지)" for d in deadlines][:5]
    if method:
        actions.append(method if re.search(r"(제출|회신|신청|접수|등록)\s*$", method) else f"제출 방법: {method}")
    contacts = [c for c in find_contacts(clean) if not re.search(r"(회신|제출|신청)\s*방\s*법", c)]
    _ql, ask = _get(fields, "문의처", "문의", "담당자", "연락처")
    return {
        "folder_name": title,
        "summary": rule_summary(title, clean, fields, deadlines),
        "event": event_info(fields),
        "deadlines": deadlines,
        "submissions": subs,
        "actions": actions,
        "contact": ask or " / ".join(contacts[:2]),
        "methods": [method] if method else find_methods(clean),
        "fields": fields,
        "attachments_read": [a["name"] for a in attach_texts],
        "mode": "rule",
    }


def _shares_word(name: str, title: str) -> bool:
    """두 글자 이상 낱말(또는 그 일부)을 하나라도 함께 쓰는지."""
    words = [w for w in re.split(r"[\s,·/()「」\[\]_]+", name or "") if len(w) >= 2]
    ref = [w for w in re.split(r"[\s,·/()「」\[\]_]+", title or "") if len(w) >= 2]
    if not ref:
        return True
    return any(w in r or r in w for w in words for r in ref)


def analyze(title: str, body: str, files: list[dict], client: OllamaClient | None,
            chat_model: str = "", num_ctx: int = 8192, ref: date | None = None) -> dict:
    ref = ref or date.today()
    if client is None:
        # 규칙 분석은 붙임 내용을 쓰지 않는다 → 붙임(스캔 PDF는 글자 인식에 수십 초)을 읽지 않아 수집이 바로 끝난다
        return rule_analysis(title, body, [], ref)
    attach = read_attachments(files)
    base = rule_analysis(title, body, attach, ref)
    try:
        model = client.pick_chat_model(chat_model)
        attach_txt = "\n\n".join(f"<{a['name']}>\n{a['text']}" for a in attach) or "(없음)"
        # CPU에서는 '입력 읽기'가 가장 오래 걸린다: 본문에 이미 있는 항목은 다시 넣지 않고,
        # 기한 후보와 핵심 항목 몇 줄만 힌트로 준다
        fields = base.get("fields", {})
        hints = "\n".join([f"- {k}: {v}" for k, v in fields.items() if k in _HINT_KEYS][:4] +
                          [f"- 기한 후보: {d['date']} {d['what']}" for d in base["deadlines"][:5]]) or "(없음)"
        prompt = PROMPT.format(today=ref.isoformat(), body=trim_body(clean_body(body, title), 3000),
                               attach=attach_txt[:1400], hints=hints)
        raw = client.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], model,
                          temperature=0.1, num_ctx=num_ctx, fmt=ai_schema(base), max_tokens=700)
        data = extract_json(raw)
        if not isinstance(data, dict):
            raise LLMError("AI 응답을 해석할 수 없습니다")
    except LLMError as e:
        base["llm_error"] = str(e)
        return base

    result = dict(base)
    result["mode"] = "llm"
    result["model"] = model
    for k in ("summary", "contact"):
        if isinstance(data.get(k), str) and data[k].strip():
            result[k] = data[k].strip()
    fn = data.get("folder_name")
    if isinstance(fn, str) and 2 <= len(fn.strip()) <= 40 and _shares_word(fn, title):
        # 공문 제목과 겹치는 낱말이 없는 이름('테스트' 등 AI가 지어낸 이름)은 쓰지 않는다
        result["folder_name"] = fn.strip()
    if isinstance(data.get("event"), dict):
        result["event"] = {k: str(v) for k, v in data["event"].items() if v}
    llm_dl = []
    for d in data.get("deadlines") or []:
        if not isinstance(d, dict):
            continue
        nd = _norm_date(str(d.get("date", "")))
        if not nd:
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
            subs.append({"item": str(s["item"])[:160], "how": str(s.get("how") or ""), "to": str(s.get("to") or "")})
    if subs:
        result["submissions"] = subs
    acts = [str(a)[:160] for a in (data.get("actions") or []) if str(a).strip()]
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

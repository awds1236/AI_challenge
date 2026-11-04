"""공문 분석기: 제출 기한·제출물·해야 할 일 정리 (로컬 LLM + 규칙 기반 보완)."""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from .deadlines import best_deadlines, find_contacts, find_methods, find_submissions
from .llm import LLMError, OllamaClient, extract_json
from .parsers import SUPPORTED, ParseError, parse_file

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

PROMPT = """다음은 공공기관에서 받은 공문 본문과 붙임 문서 일부입니다.
담당 서무 직원이 놓치지 않도록 아래 항목을 JSON으로 정리하세요. 오늘 날짜: {today}

- folder_name: 폴더 이름으로 쓸 짧은 제목 (예: "OO행사 참여 요청", 25자 이내, 특수문자 금지)
- summary: 공문 핵심 요약 2~3문장
- event: 행사/교육이 있으면 이름(name), 일시(date), 장소(place)
- deadlines: 우리 기관(수신자)이 지켜야 할 제출·회신·신청 기한. date는 YYYY-MM-DD, time은 HH:MM(없으면 빈 문자열), what은 무엇을 해야 하는지
- submissions: 제출해야 할 문서/자료. item(서류명), how(제출 방법: 공문, 전자우편 등), to(제출처)
- actions: 담당자가 해야 할 일을 순서대로 (짧은 문장)
- contact: 문의처 (부서, 전화, 메일)

본문에 없는 내용은 만들지 말고 빈 값으로 두세요. 날짜에 연도가 없으면 오늘 기준으로 가장 가까운 미래 연도를 쓰세요.

[공문 본문]
{body}

[붙임 문서 발췌]
{attach}
"""


def read_attachments(files: list[dict], max_files: int = 2, max_chars: int = 700) -> list[dict]:
    out = []
    for f in files:
        if not f.get("ok") or not f.get("path"):
            continue
        p = Path(f["path"])
        if p.suffix.lower() not in SUPPORTED:
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


def rule_analysis(title: str, body: str, attach_texts: list[dict], ref: date | None = None) -> dict:
    deadlines = []
    for d in best_deadlines(body, ref):
        deadlines.append({"date": d["date"], "time": d["time"] or "", "what": d["context"][:120], "source": "규칙"})
    subs = [{"item": s, "how": "", "to": ""} for s in find_submissions(body)]
    first_lines = [l.strip() for l in body.splitlines() if len(l.strip()) > 15][:3]
    return {
        "folder_name": title,
        "summary": " ".join(first_lines)[:300],
        "event": {},
        "deadlines": deadlines,
        "submissions": subs,
        "actions": [f"{d['date']}까지 {d['what'][:60]}" for d in deadlines][:5],
        "contact": " / ".join(find_contacts(body)[:2]),
        "methods": find_methods(body),
        "attachments_read": [a["name"] for a in attach_texts],
        "mode": "rule",
    }


def analyze(title: str, body: str, files: list[dict], client: OllamaClient | None,
            chat_model: str = "", num_ctx: int = 8192, ref: date | None = None) -> dict:
    ref = ref or date.today()
    attach = read_attachments(files)
    base = rule_analysis(title, body, attach, ref)
    if client is None:
        return base
    try:
        model = client.pick_chat_model(chat_model)
        attach_txt = "\n\n".join(f"<{a['name']}>\n{a['text']}" for a in attach) or "(없음)"
        # CPU에서는 '입력 읽기'가 가장 오래 걸리므로 본문 핵심과 붙임 발췌만 넣는다
        prompt = PROMPT.format(today=ref.isoformat(), body=trim_body(body, 3000), attach=attach_txt[:1400])
        raw = client.chat([{"role": "user", "content": prompt}], model, temperature=0.1,
                          num_ctx=min(num_ctx, 6144), fmt=SCHEMA)
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
    if isinstance(fn, str) and 2 <= len(fn.strip()) <= 40:
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

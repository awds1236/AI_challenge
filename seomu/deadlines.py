"""공문 본문에서 날짜·기한·제출물·연락처를 찾아내는 규칙 기반 추출기.

LLM이 없어도 동작하며, LLM 결과를 검증·보완하는 데에도 쓰인다.
"""
from __future__ import annotations

import re
from datetime import date, datetime

_Y4 = r"(?P<y>20\d{2})"
_Y2 = r"[\'‘’`]\s*(?P<yy>\d{2})"
_M = r"(?P<m>1[0-2]|0?[1-9])"
_D = r"(?P<d>3[01]|[12]\d|0?[1-9])"
_WD = r"(?:[ \t]*\([ \t]*[월화수목금토일][ \t]*\))?"
_TIME = (r"(?:[ \t]*(?:(?P<ampm>오전|오후)[ \t]*)?(?P<hh>[01]?\d|2[0-3])[ \t]*(?::|시)[ \t]*(?P<mm>[0-5]\d)?(?:[ \t]*분)?)?")

DATE_PATTERNS = [
    re.compile(_Y4 + r"\s*년\s*" + _M + r"\s*월\s*" + _D + r"\s*일" + _WD + _TIME),
    re.compile(_Y4 + r"\s*[.\-/]\s*" + _M + r"\s*[.\-/]\s*" + _D + r"(?!\d)\.?" + _WD + _TIME),
    re.compile(_Y2 + r"\s*[.\-/]\s*" + _M + r"\s*[.\-/]\s*" + _D + r"(?!\d)\.?" + _WD + _TIME),
    re.compile(r"(?<![\d.])" + _M + r"\s*월\s*" + _D + r"\s*일" + _WD + _TIME),
    re.compile(r"(?<![\d.\-/])" + _M + r"\s*\.\s*" + _D + r"\s*\.(?![ \t]*\d{1,2}[ \t]*\.)" + _WD + _TIME),
    re.compile(r"(?<![\d.\-/])" + _M + r"\s*\.\s*" + _D + r"(?=\s*(?:까지|\)|\(\s*[월화수목금토일]))" + _WD + _TIME),
]

DEADLINE_WORDS = ("까지", "기한", "마감", "한정", "기일", "내로", "이내")
SUBMIT_WORDS = ("제출", "회신", "신청", "보고", "송부", "등록", "접수", "통보", "입력", "참가 신청")
# '11. 13. ~ 17.'처럼 짧게 적은 끝날. '~ 2026. 2. 3.'처럼 연도부터 적은 끝 날짜는 따로 찾는다 (20을 20일로 읽지 않게)
RANGE_TAIL = re.compile(r"\s*[~∼～\-]\s*(?!20\d{2}|[\'‘’`]\s*\d{2}\s*[.\-/])"
                        r"(?:(?P<m2>1[0-2]|0?[1-9])\s*[.월]\s*)?(?P<d2>3[01]|[12]\d|0?[1-9])(?!\d)\s*[.일]?" + _WD)
PHONE = re.compile(r"(?<!\d)(0\d{1,2})[-)\s.]?(\d{3,4})[-\s.](\d{4})(?!\d)")
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _infer_year(m: int, d: int, ref: date) -> int:
    y = ref.year
    try:
        cand = date(y, m, d)
    except ValueError:
        return y
    # 기준일보다 6개월 이상 과거면 다음 해로 본다 (연말에 받은 1월 기한 등)
    if (ref - cand).days > 180:
        return y + 1
    return y


def _line_of(text: str, start: int, end: int) -> str:
    ls = text.rfind("\n", 0, start) + 1
    le = text.find("\n", end)
    return text[ls: le if le != -1 else len(text)].strip()


def find_dates(text: str, ref: date | None = None) -> list[dict]:
    ref = ref or date.today()
    found: list[dict] = []
    taken: list[tuple[int, int]] = []
    for pat in DATE_PATTERNS:
        for m in pat.finditer(text):
            s, e = m.span()
            if any(s < te and e > ts for ts, te in taken):
                continue
            g = m.groupdict()
            mo, dd = int(g["m"]), int(g["d"])
            if g.get("y"):
                y = int(g["y"])
            elif g.get("yy"):
                y = 2000 + int(g["yy"])
            else:
                y = _infer_year(mo, dd, ref)
            try:
                dt = date(y, mo, dd)
            except ValueError:
                continue
            tm = None
            if g.get("hh"):
                hh = int(g["hh"])
                if g.get("ampm") == "오후" and hh < 12:
                    hh += 12
                tm = f"{hh:02d}:{int(g['mm'] or 0):02d}"
            # 기간 표기(11. 13. ~ 17.)는 종료일을 함께 기록
            end_date = None
            rt = RANGE_TAIL.match(text, e)
            if rt:
                m2 = int(rt.group("m2")) if rt.group("m2") else mo
                try:
                    end_date = date(y if m2 >= mo else y + 1, m2, int(rt.group("d2")))
                    e = rt.end()
                except ValueError:
                    end_date = None
            taken.append((s, e))
            line = _line_of(text, s, e)
            after = text[e:e + 14]
            before = text[max(0, s - 30):s]
            score = 0
            if re.match(r"\s*\)?\s*(까지|한)", after):
                score += 3
            if any(w in line for w in DEADLINE_WORDS):
                score += 1
            if any(w in line for w in SUBMIT_WORDS):
                score += 2
            if re.search(r"(기한|마감|제출일|회신일)\s*[:：]?\s*$", before):
                score += 3
            if re.search(r"(시행|생산|접수|작성|공고|등록|게시|수정)\s*(일자|일)?\s*[:：]?\s*$", before):
                score -= 3
            if re.search(r"(기준\s*일?|발급\s*일?|기준\s*시점)\s*[:：]?\s*$", before):
                score -= 4                    # '(기준일: 2026. 3. 1.)'은 기한이 아니다
            found.append({
                "date": dt.isoformat(),
                "end_date": end_date.isoformat() if end_date else None,
                "time": tm,
                "raw": text[s:e].strip(),
                "context": line[:200],
                "score": score,
                "is_deadline": score >= 3,
                "pos": s,
            })
    found.sort(key=lambda x: x["pos"])
    # '제출 기간: 2026. 1. 28.(수) 10:00 ~ 2026. 2. 3.(화) 18:00'처럼 시작~끝 날짜가 따로 적힌 기간은
    # 끝 날짜가 기한이다 (신청·접수·제출·공모 기간일 때). 시작 날짜는 기한에서 뺀다.
    lines = text.splitlines()
    for a, b in zip(found, found[1:]):
        gap = text[a["pos"] + len(a["raw"]):b["pos"]]
        if not re.fullmatch(r"[\s.)]*(?:\d{1,2}:\d{2})?[\s.)]*[~∼～\-–][\s(]*", gap):
            continue
        a["score"] -= 4
        a["is_deadline"] = a["score"] >= 3
        ln = text.count("\n", 0, b["pos"])
        around = " ".join(lines[max(0, ln - 8):ln + 1])        # 표의 머리글(예: '신청 기간')까지 본다
        if re.search(r"(기간|기한|접수|신청|제출|마감|모집|공모|응모|의견)", around):
            b["score"] = max(b["score"], 3) + 1
            b["is_deadline"] = True
            b["context"] = b["context"] or lines[ln][:200]
    return found


def best_deadlines(text: str, ref: date | None = None) -> list[dict]:
    """제출 기한일 가능성이 높은 날짜만 (중복 제거) 반환."""
    out, seen = [], set()
    for d in sorted(find_dates(text, ref), key=lambda x: -x["score"]):
        if not d["is_deadline"]:
            continue
        key = (d["date"], d["time"])
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return sorted(out, key=lambda x: (x["date"], x["time"] or ""))


def find_submissions(text: str) -> list[str]:
    """제출해야 할 서류/항목 후보 추출."""
    items: list[str] = []
    lines = [l.strip() for l in text.splitlines()]
    in_attach = False
    for l in lines:
        if not l:
            in_attach = False
            continue
        if re.match(r"^(□\s*)?(붙\s*임|첨\s*부)(?![가-힣])", l):
            in_attach = True
            rest = re.sub(r"^(□\s*)?(붙\s*임|첨\s*부)\s*[:：]?\s*", "", l)
            if rest:
                items.extend(_split_attach(rest))
            continue
        if in_attach:
            if re.match(r"^(\d+[.)]|[-·○◦•]\s*)", l):
                items.extend(_split_attach(l))
                continue
            in_attach = False
        if any(w in l for w in ("제출", "회신", "송부")) and re.search(
                # 한글은 조사가 바로 붙어('목록을') 단어 경계(\b)가 생기지 않는다 → 뒤에 조사·끝이 오는지로 본다
                r"(서|목록|명단|계획|결과|현황|자료|양식|서식|사본|증빙|파일|표)"
                r"(?=$|[\s,.)(]|을|를|과|와|및|은|는|이|가|도)", l):
            items.append(re.sub(r"^[\s□○◦•\-·※\d.)]+", "", l)[:160])
    uniq, seen = [], set()
    for it in items:
        it = it.strip(" .")
        if it and it not in seen and len(it) > 2:
            seen.add(it)
            uniq.append(it)
    return uniq[:15]


def _split_attach(s: str) -> list[str]:
    parts = re.split(r"\s+(?=\d+\s*[.)]\s)", s)
    # 메일·게시판의 '첨부: 가.hwp, 나.pdf'처럼 쉼표로 이어진 파일 이름은 하나씩
    if len(parts) == 1 and re.search(r"\.\w{2,5}\s*,", s):
        parts = [p for p in re.split(r"\s*,\s*", s) if p.strip()]
    out = []
    for p in parts:
        p = re.sub(r"^\d+\s*[.)]\s*", "", p).strip()
        p = re.sub(r"\s*\d+\s*부\.?\s*(끝\.?)?$", "", p).strip()
        p = re.sub(r"\s*끝\.?$", "", p).strip()
        if p:
            out.append("[붙임] " + p)
    return out


def find_contacts(text: str) -> list[str]:
    out = []
    for l in text.splitlines():
        if PHONE.search(l) or EMAIL.search(l):
            if re.search(r"(문의|담당|연락|☎|전화|메일|e-?mail|주무관|사무관|팀장)", l, re.I) or len(l) < 80:
                out.append(l.strip(" □○-·")[:160])
    seen, uniq = set(), []
    for o in out:
        if o not in seen:
            seen.add(o)
            uniq.append(o)
    return uniq[:6]


def find_methods(text: str) -> list[str]:
    out = []
    for l in text.splitlines():
        if re.search(r"(전자우편|이메일|e-?mail|메일|온나라|문서24|업무관리시스템|공문으로|우편|방문|팩스|FAX|시스템에\s*등록|제출처|회신처)", l, re.I) \
                and any(w in l for w in SUBMIT_WORDS + ("제출처", "회신처")):
            out.append(l.strip(" □○-·")[:160])
    return list(dict.fromkeys(out))[:5]


def dday(due: str, today: date | None = None) -> int | None:
    try:
        d = datetime.strptime(due[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return (d - (today or date.today())).days

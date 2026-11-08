"""공문 본문 정리: 군더더기 제거, '가. 항목 : 값' 해석, 규칙 기반 요약·할 일 문장 만들기.

공공기관 공문은 행정업무운영규정에 따른 공통 서식(수신·제목·본문 1./가./1)·붙임·끝.)을 쓰므로
기관이 달라도 같은 규칙으로 핵심을 뽑을 수 있다.
"""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- 본문 다듬기 (모든 수집 경로 공통)
# 공문 시스템마다(온나라·문서24·K-에듀파인·업무포털·홈페이지 게시판·메일·PDF) 글자 모양이 달라
# 화면에 그대로 보여 주면 빈 줄이 줄마다 끼거나, 단어 중간에서 줄이 바뀌거나, 메뉴 글자가 섞인다.
_ZERO_WIDTH = re.compile(r"[​-‏‪-‮⁠-⁤﻿­-]")   # 끝: 아이콘 글꼴 글자
_ODD_SPACE = re.compile(r"[  -   　]")
_LABEL_SPACED = re.compile(r"^(?P<a>수|제|발|경|참|붙|시|접|첨|건|문|담)[ \t]+(?P<b>신|목|신|유|조|임|행|수|부|명|의|당)"
                           r"(?P<c>[ \t]+자)?(?=[ \t]*[:：]|[ \t]{2,}|\t|[ \t]*$)")
_LABEL_WORDS = {"수신", "제목", "발신", "경유", "참조", "붙임", "시행", "접수", "첨부", "건명", "문의", "담당"}
_WEB_NOISE = re.compile(
    r"^(?:본문\s*바로\s*가기|주\s*메뉴\s*바로\s*가기|메뉴\s*바로\s*가기|바로\s*가기|로그인|로그아웃|회원\s*가입|사이트\s*맵|"
    r"전체\s*메뉴|메뉴\s*(?:열기|닫기)?|홈|HOME|목록|목록\s*보기|목록으로|이전\s*글|다음\s*글|인쇄|프린트|출력|공유|"
    r"공유하기|스크랩|TOP|맨\s*위로|위로|검색|통합\s*검색|닫기|글자\s*크기|확대|축소|미리\s*보기|바로\s*보기|"
    r"내려\s*받기|다운\s*로드|첨부\s*파일\s*없음|개인정보\s*처리\s*방침|이용\s*약관|저작권\s*정책|"
    r"이메일\s*무단\s*수집\s*거부|뷰어\s*다운로드|(?:copyright|ⓒ|©).*|(?:조회\s*수?|추천\s*수?)\s*[:：]?\s*[\d,]*\s*회?|"
    r"열기|URL\s*복사.*|주소\s*복사.*|화면\s*크기\s*(?:축소|확대|초기화)|메인\s*페이지\s*(?:이동|로)?|"
    r"(?:작성|등록|게시|수정)\s*(?:일|일자|일시)\s*[:：]?\s*[\d.\-: ]*|인쇄하기|공유\s*하기|SNS\s*공유|"
    r"(?:본문|첨부)\s*보기|이전\s*페이지|맨\s*위로\s*가기)$",
    re.I)
_BREADCRUMB = re.compile(r"^(?:홈|HOME|Home|처음)\s*[>›»∙·/]\s*\S")
_ENUM_START = re.compile(r"^\s*(?:\d{1,2}\s*[.)]|[가-하]\s*[.)]|\(\s*[\w가-힣]{1,2}\s*\)|[①-⑳]|[-·○◦•※□■▶◆◇▷►*]|"
                         r"붙\s*임|첨\s*부|끝\s*\.|제\s*\d+\s*조)")
# 한글 줄바꿈이 '글자 단위'라 단어 중간에서 끊긴 줄을 이을 때, 다음 줄이 이 조각으로 시작하면 붙여 쓴다
_JOIN_TIGHT = re.compile(r"^(?:은|는|이|가|을|를|의|에|에서|에게|께|로|으로|와|과|도|만|까지|부터|및|하여|하고|하며|하오니|"
                         r"하니|합니다|니다|습니다|ㅂ니다|시기|바랍니다|랍니다|한다|된다|되어|되며|드립니다|"
                         r"[가-힣]{1,2}(?=[.,)」』]))")


def _fix_label_spacing(line: str) -> str:
    """'제   목    ○○' → '제목  ○○' (양식 칸 맞춤용 글자 사이 공백 제거)."""
    m = _LABEL_SPACED.match(line)
    if m and (m.group("a") + m.group("b")) in _LABEL_WORDS:
        return m.group("a") + m.group("b") + ("자" if m.group("c") else "") + line[m.end():]
    return line


def _is_hard_wrapped(lines: list[str]) -> int:
    """PDF·스캔 글자처럼 줄 길이가 일정하게 끊긴 본문이면 그 폭(글자 수)을, 아니면 0."""
    lens = sorted(len(l) for l in lines if len(l) >= 15)
    if len(lens) < 6:
        return 0
    width = lens[int(len(lens) * 0.9) - 1]
    full = sum(1 for n in lens if n >= width * 0.85)
    return width if full >= max(4, len(lens) * 0.45) else 0


def tidy_text(text: str) -> str:
    """수집한 본문을 화면·분석에 알맞게 다듬는다.

    - 유니코드 정규화(NFC): 맥·일부 웹에서 온 '자모 분리' 한글을 붙인다
    - 폭 없는 공백·줄 바꿈 없는 공백·전각 공백을 일반 공백으로
    - 모든 줄 사이에 빈 줄이 끼는 HTML 복사 본문의 빈 줄을 정리
    - '제   목' 같은 양식용 글자 간격을 붙인다
    - 홈페이지 메뉴·바로가기·저작권 줄 등 웹 화면 글자를 뺀다
    - PDF처럼 일정한 폭에서 끊긴 줄을 문장으로 다시 잇는다
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFC", text)
    t = _ZERO_WIDTH.sub("", t)
    t = _ODD_SPACE.sub(" ", t)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    raw = [re.sub(r"[ \t]+$", "", l) for l in t.split("\n")]
    lines = []
    skip_next = False
    for l in raw:
        l = re.sub(r"^[ \t]+", "", l)
        l = re.sub(r"\t{2,}", "\t", l)
        l = _fix_label_spacing(l)
        l = re.sub(r" {2,}", " ", l)
        s = l.strip()
        if skip_next and s:
            skip_next = False
            if len(s) <= 10:                 # 게시판 정보 칸 '작성자' 다음 줄의 이름
                continue
        if _WEB_NOISE.match(s) or _BREADCRUMB.match(s):
            continue
        if re.fullmatch(r"(?:작성자|글쓴이|작성부서|담당자명)\s*[:：]?", s):
            skip_next = True
            continue
        lines.append(l)
    # 빈 줄이 거의 모든 줄 사이에 끼어 있으면(웹 복사) 한 줄 빈 줄은 없앤다
    nonblank = [l for l in lines if l.strip()]
    singles = sum(1 for i in range(1, len(lines) - 1)
                  if not lines[i].strip() and lines[i - 1].strip() and lines[i + 1].strip())
    if nonblank and singles >= len(nonblank) * 0.4:
        lines = [l for l in lines if l.strip()]
    # 일정한 폭에서 끊긴 줄 다시 잇기
    width = _is_hard_wrapped([l for l in lines if l.strip()])
    if width:
        joined: list[str] = []
        for l in lines:
            prev = joined[-1] if joined else ""
            if (prev and l.strip() and len(prev) >= width * 0.8 and not re.search(r"[.。!?:：」』)]\s*$", prev)
                    and not _ENUM_START.match(l) and not re.match(r"^\s*[가-힣 ]{1,12}\s*[:：]", l)):
                # 한글끼리 이어질 때: 줄 끝 어절이 한 글자 조각('실'·'제')이거나 다음 줄이 어미·조사로 시작하면 붙여 쓴다
                tight = bool(re.search(r"[가-힣]$", prev) and re.match(r"^[가-힣]", l.strip())
                             and (re.search(r"(?:^|\s)[가-힣]$", prev) or _JOIN_TIGHT.match(l.strip())))
                joined[-1] = prev + ("" if tight else " ") + l.strip()
            else:
                joined.append(l)
        lines = joined
    out: list[str] = []
    for l in lines:
        if out and l.strip() and l == out[-1]:          # 같은 줄이 연달아 나오면 하나만
            continue
        out.append(l)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


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


# 요약 문장: '배경(무엇을 하니)' + '요청(무엇을 해 달라)'을 공문 어미 없이 개조식으로
_CONNECTOR = re.compile(r"\s*(?:하고자\s*하오니|하고자\s*하니|하고자\s*하므로|하오니|하니|하므로|하오며|하였으니|"
                        r"되었으니|되었으므로|예정이오니|예정이니|이오니|이므로|합니다만)\s*,?\s*")
_LEAD = re.compile(r"^(?:위\s*(?:호|문서)와?\s*관련하여|위\s*호에\s*따라|관련\s*근거에\s*따라|"
                   # '각 부서에서는'의 '각 부'처럼 낱말 일부를 기관 이름으로 지우지 않게 뒤를 확인한다
                   r"(?:우리|귀|각)\s*(?:시|군|구|도|청|기관|교|학교|부|처|원|회사|사|본부|팀)(?=에서|는|의|\s|,|$)"
                   r"(?:에서는|에서|는|의)?)\s*,?\s*")
_NOUN_VERB = (r"개최|실시|시행|추진|운영|안내|조사|공모|모집|접수|진행|점검|평가|취합|파악|선정|변경|"
              r"회신|제출|신청|통보|보고|추천|참석|참여|협조|작성|등록|입력|검토|확인|수립|구축|교육|홍보|발굴|"
              r"반영|정비|수정|보완|갱신|요청|이수|정리|제공|공유")
_DUE_WORDS = re.compile(r"\s*(?:[\'‘’]?\d{2,4}\s*[.\-/]\s*)?\d{1,2}\s*(?:월|[.\-/])\s*\d{1,2}\s*(?:일|\.)?\s*"
                        r"(?:\([월화수목금토일]\))?\s*(?:\d{1,2}\s*(?:시|:\d{2})\s*)?(?:까지|한)\s*")
_SEND_TO = re.compile(r"(?:\S+(?:팀|과|부|실|처)\s+)?\S*(?:메일|우편)\([^)]*\)\s*(?:로|으로)\s+")


def _strip_due(s: str) -> str:
    """요청 문장에서 날짜(기한은 따로 붙인다)·메일 주소 표기를 뺀다."""
    return re.sub(r"\s{2,}", " ", _SEND_TO.sub("", _DUE_WORDS.sub(" ", s))).strip()


def _nounize(s: str) -> str:
    """'행사를 개최' → '행사 개최', '인원을 회신하여 주시기 바랍니다' → '인원 회신 요청'."""
    s = re.sub(r"\s*(다음과|아래와)\s*같이\s*", " ", s)
    s = re.sub(r"\s*(붙임|별첨|첨부)\s*(서식|양식|파일)?\s*\d*\s*(에\s*따라|을\s*참고하여|과\s*같이)\s*", " ", s)
    s = re.sub(r"\s*기한\s*내(에)?\s*", " ", s)
    s = re.sub(r"(?:을|를)\s*((?:새로|다시|일괄|즉시|적극|모두|함께|별도로)\s+)?(" + _NOUN_VERB + r")", r" \1\2", s)
    s = re.sub(r"\s*(?:업무에\s*)?참고하시기\s*바랍니다\.?$", " 업무 참고", s)      # 참고 안내는 '요청'이 아니다
    s = re.sub(r"\s*(?:하여|해)\s*주시기\s*바랍니다\.?$|\s*(?:하여|해)\s*주시기\s*바람\.?$", " 요청", s)
    s = re.sub(r"\s*(?:하여|해)\s*(?:주시면|주시길)\s*(?:감사하겠습니다|바랍니다)\.?$", " 요청", s)
    s = re.sub(r"\s*(?:하시기|하시길)\s*바랍니다\.?$|\s*부탁\s*드립니다\.?$|\s*바랍니다\.?$", " 요청", s)
    if s.endswith("요청"):     # '작성하시어 회신 요청' → '작성·회신 요청' (관련하여·위하여 등은 그대로)
        s = re.sub(r"(\S+?)(?:하시어|하여|해서)\s+",
                   lambda m: m.group(0) if re.search(r"(관련|위|의|대|인|통|말미암|따라)$", m.group(1))
                   else m.group(1) + "·", s)
    s = re.sub(r"\s*(?:하고자|하려고)\s*(?:합니다|함)\.?$", "", s)
    s = re.sub(r"\s*(?:알려|안내해)\s*드립니다\.?$|\s*알려드립니다\.?$|\s*안내합니다\.?$", " 안내", s)
    s = re.sub(r"\s*(?:합니다|입니다)\.?$", "", s)
    s = re.sub(r"\s*많은\s+참여\s*요청$", " 참여 요청", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" .,·")
    return s


def summary_sentence(paragraph: str) -> str:
    """공문 문단 하나를 '「○○ 행사」 개최 — 부서별 참여 인원 회신 요청' 같은 한 줄로 줄인다."""
    p = _ENUM.sub("", paragraph).strip()
    p = re.sub(r"\s+", " ", p)
    parts = _CONNECTOR.split(p, maxsplit=1)
    bg, req = (parts[0], parts[1]) if len(parts) == 2 else ("", parts[0])
    bg = _LEAD.sub("", bg).strip()
    req = _LEAD.sub("", req).strip()
    req = re.sub(r"^(?:각\s*)?\S{1,10}(?:에서는|께서는)\s+", "", req)
    # 목적절(~을 위하여)은 배경이 충분히 길 때만 뺀다
    for pat in (r"^.{2,60}?(?:을|를)?\s*(?:위하여|위해서?|위한)\s+", r"^.{2,60}?(?:하고자|고자)\s+",
                r"^.{2,60}?(?:에\s*)?(?:대비하여|대비해|대비한)\s+"):
        trimmed = re.sub(pat, "", bg)
        if len(trimmed) >= 8:
            bg = trimmed
    bg, req = _nounize(bg), _nounize(req)
    # '이수 요청 — 협조 요청'처럼 뒤가 빈 인사 요청이면 앞만 쓴다
    if bg.endswith(("요청", "안내")) and re.fullmatch(r"(?:적극\s*)?(?:협조|참여|참석)\s*요청", req):
        req = ""
    if bg and req:
        out = f"{bg} — {req}"
    else:
        out = bg or req
    return out[:180]


def purpose_paragraph(clean: str) -> str:
    """번호 문단 중 요청·안내 내용을 담은 첫 문단 (번호가 없는 메일·게시판 글은 첫 요청 문장)."""
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
    req = re.compile(r"(요청|협조|바랍니다|부탁|알려|안내|제출|회신|개최|시행|신청|조사|통보|추천|참석|모집|공모)")
    strong = re.compile(r"(바랍니다|주시기|요청\s*드|부탁|하오니|협조하여|알려\s*드리|안내\s*드리|안내합니다|알립니다)")
    lines = clean.splitlines()
    first_num = next((i for i, l in enumerate(lines) if re.match(r"^\s*\d{1,2}\s*[.)]\s*\S", l)), len(lines))
    cands = [p for p in paras if not (re.search(r"(관련\s*[:：]|^\s*\d+\s*[.)]\s*관련)", p) or _GREETING.search(p))]
    # 번호 문단 앞의 안내 문장(게시판 글은 번호 없이 '…안내하오니 …바랍니다'로 시작하는 경우가 많다)
    lead = []
    for line in lines[:first_num]:
        s = line.strip()
        if len(s) < 15 or _GREETING.search(s) or re.match(r"^(안녕하|수고|감사합니다|축하)", s):
            continue
        if re.match(r"^[^:：]{1,12}[:：]", s) or _ENUM_START.match(s):
            continue
        lead.append(s)
    ordered = lead + cands
    for pat in (strong, req):                 # 요청 어미가 분명한 문장을 먼저
        for p in ordered:
            if pat.search(p):
                return p
    return paras[0] if paras else ""


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


_WD = "월화수목금토일"


def _due_phrase(d: dict) -> str:
    """{'date': '2026-11-13', 'time': '18:00'} → '11월 13일(금) 18:00까지'"""
    from datetime import date as _date
    try:
        dt = _date.fromisoformat(d["date"])
    except (KeyError, ValueError):
        return ""
    return f"{dt.month}월 {dt.day}일({_WD[dt.weekday()]})" + (f" {d['time']}" if d.get("time") else "") + "까지"


def rule_summary(title: str, clean: str, fields: dict, deadlines: list[dict] | None = None) -> str:
    """한두 줄 요약. 첫 줄: 무엇을 하니 무엇을 해 달라(언제까지). 둘째 줄: 대상·기간 등 다른 칸에 없는 정보.
    행사명·일시·장소·제출 서류는 화면의 '행사 정보'·'제출물' 칸에 따로 나오므로 되풀이하지 않는다."""
    para = purpose_paragraph(clean)
    first = summary_sentence(_strip_due(para)) if para else ""
    # 메일·협조문처럼 '배경 문장. 요청 문장.'으로 나뉜 글은 두 문장을 이어 한 줄로
    lines = [l.strip() for l in clean.splitlines()]
    is_req = lambda l: bool(re.search(r"(바랍니다|부탁|주시기|요청)", l))  # noqa: E731
    # 문장인 줄: 'X: 값' 항목이나 번호·기호 목록이 아닌 것 ('첨부한 ○○를 …'처럼 '첨부'로 시작하는 문장은 포함)
    plain = lambda l: (len(l) >= 15 and not re.match(r"^[^:：]{1,12}[:：]", l)  # noqa: E731
                       and not re.match(r"^\s*(?:\d{1,2}\s*[.)]|[가-하]\s*[.)]|\(\s*\w{1,2}\s*\)|[①-⑳]|[-·○◦•※□■▶*])", l))
    bg_line = req_line = ""
    if para and para.strip() in lines:
        i = lines.index(para.strip())
        if not re.search(r"(요청|바랍니다|부탁|주시기|하오니|하니)", para):      # 배경 문장 → 다음 줄이 요청
            bg_line = para
            req_line = next((l for l in lines[i + 1:i + 5] if is_req(l) and plain(l)), "")
        elif i > 0 and plain(lines[i - 1]) and re.search(r"(합니다|입니다|하고자\s*합니다)\.?$", lines[i - 1]) \
                and not _GREETING.search(lines[i - 1]) and not re.match(r"^(안녕하|수고)", lines[i - 1]):
            bg_line, req_line = lines[i - 1], para                               # 요청 문장 앞의 배경 문장
    if bg_line and req_line:
        bg = summary_sentence(bg_line)
        bg = re.sub(r"^.{2,60}?(?:을|를)?\s*(?:위하여|위해서?|위한)\s+", "", bg)
        req = summary_sentence(_strip_due(req_line))
        if " — " in req:                  # 요청 문장에도 '배경 — 요청'이 있으면 요청 부분만 (— 가 두 번 나오지 않게)
            req = req.split(" — ")[-1]
        req = re.sub(r"^\S*(?:첨부한|붙임의?|별첨)\s+", "", req)
        first = f"{bg} — {re.sub(r'  +', ' ', req).strip()}"
    if len(first) < 6:
        first = re.sub(r"^\[[^\]]{1,20}\]\s*", "", title).strip()
    elif len(first) > 100 or (" — " not in first and len(first) > 70):
        # 법령 입법예고처럼 요청 문장이 아주 길면 '제목 — 의견 제출 요청'으로 줄인다
        ov = _last_obj_verb(_strip_due(para or ""))
        core = re.sub(r"\s*(?:안내|알림)$", "", re.sub(r"^\[[^\]]{1,20}\]\s*", "", title)).strip()
        if ov and core:
            first = f"{core} — {ov} 요청"
    due = next((d for d in (deadlines or []) if d.get("date")), None)
    if due and "까지" not in first and re.search(r"(요청|제출|회신|신청|등록|보고|접수)", first):
        first += f" ({_due_phrase(due)})"
    extra = []
    for keys in (("대상", "참가대상", "조사대상", "점검대상", "교육대상"), ("기간", "공모기간", "점검기간", "조사기간", "신청기간")):
        label, v = _get(fields, *keys)
        if v and label not in ("일시",):
            extra.append(f"{label} {v[:60]}")
    return first + ("\n" + " · ".join(extra) if extra else "")


_OBJ_VERB = re.compile(r"([가-힣A-Za-z0-9·]{2,20}?)(?:을|를)\s+(?:\S+\s+){0,5}?(제출|회신|신청|보고|등록|통보|참석|접수|작성)")
_VERB = re.compile(r"(제출|회신|신청|보고|등록|통보|참석|접수|작성)")


def _last_obj_verb(s: str) -> str:
    """문장의 마지막 '무엇을 … 제출'에서 동사 바로 앞의 목적어를 고른다.
    '다음 사항을 기재한 의견서를 장관에게 제출' → '의견서 제출' (흔한 오타 '룰'도 목적격 조사로 본다)"""
    verbs = list(_VERB.finditer(s))
    if not verbs:
        return ""
    v = verbs[-1]
    window = s[max(0, v.start() - 60):v.start()]
    objs = re.findall(r"([가-힣A-Za-z0-9·]{2,20}?)(?:을|를|룰)\s", window)
    return f"{objs[-1]} {v.group(1)}" if objs else ""


def _heading_task(heading: str, verb: str) -> str:
    """'1. [경기도교육청] 2026학년도 초등학교 교사 등록 원서 제출' → '초등학교 교사 등록 원서 제출'"""
    h = _ENUM.sub("", heading or "").strip()
    h = re.sub(r"^\[[^\]]{1,30}\]\s*", "", h)
    h = re.sub(r"^(?:20\d{2}|'\d{2})\s*(?:학년도|년도|년)\s*", "", h)
    h = re.sub(r"\s*(?:안내|알림|요청|협조)$", "", h).strip(" .:")
    if not h:
        return ""
    return h if re.search(r"(제출|회신|신청|접수|보고|등록|추천|통보|모집|응모)$", h) else f"{h} {verb}"


def clean_what(context: str, raw_date: str, fields: dict, title: str, heading: str = "", table_verb: str = "",
               prev: str = "") -> str:
    """기한 줄을 '조사표 회신' 같은 할 일 문장으로.
    heading: 그 줄 위의 번호 제목('1. … 등록 원서 제출'), table_verb: 표 머리글의 동사('신청 기간' → '신청')."""
    s = _ENUM.sub("", context or "").strip()
    m = re.match(r"^(회신|제출|신청|접수|보고|등록|추천|통보)\s*기\s*[한간]\s*[:：]?", s.replace(" ", "")[:12])
    if m or re.match(r"^(회\s*신|제\s*출|신\s*청|접\s*수|보\s*고|등\s*록|추\s*천|통\s*보)\s*기\s*[한간]", s):
        verb = re.sub(r"\s", "", s)[:2]
        _l, obj = _get(fields, f"{verb}자료", f"{verb}서류", "제출서류", "제출자료", "회신자료", "제출물", "보고자료")
        obj = item_names(obj)
        if obj and verb in ("신청", "접수"):        # '신청서 신청'처럼 어색해지지 않게 서류는 '제출'
            verb = "제출"
        if obj:
            return f"{'·'.join(obj)} {verb}".strip()
        return _heading_task(heading, verb) or f"{title} {verb}".strip()
    # '이수 기한: …', '결과 보고 기한: …'처럼 목록에 없는 '○○ 기한' 항목
    g = re.match(r"^([가-힣 ]{1,12}?)\s*기\s*한\s*[:：]", s)
    if g:
        label = re.sub(r"\s+", " ", g.group(1)).strip()
        word = label.split()[-1]
        _l, obj = _get(fields, f"{word}자료", "보고자료", "제출서류", "제출자료", "회신자료")
        if obj and word in ("보고", "제출", "회신"):
            return f"{'·'.join(item_names(obj))} {'제출' if word == '보고' else word}"
        core = re.sub(r"\s*(요청|안내|알림|협조|통보)$", "", re.sub(r"^\[[^\]]{1,20}\]\s*", "", title))
        hit = re.search(r"((?:\S+\s+){0,2}" + re.escape(word) + r")", core)      # 제목에서 그 말이 든 구절
        return hit.group(1) if hit else label
    # 문장 속 기한: 제출 서류 항목이 있으면 '비상연락망 회신'처럼
    verb = re.findall(r"(제출|회신|신청|보고|등록|통보)", s)
    _l, obj = _get(fields, "회신자료", "제출서류", "제출자료", "신청서류", "보고자료", "제출물")
    if verb and obj and re.search(r"(바랍니다|부탁|주시기|요청)", s):
        v = verb[-1] if verb[-1] not in ("신청",) else "제출"
        return f"{'·'.join(item_names(obj))} {v}"
    if raw_date:
        s = s.replace(raw_date, " ")
    # 기간의 다른 날짜·'~'·시각 조각을 뺀다 ('1차 계절학기 2026.06.08.(월) ~' → '1차 계절학기')
    from .deadlines import DATE_PATTERNS
    for pat in DATE_PATTERNS:
        s = pat.sub(" ", s)
    s = re.sub(r"\(\s*[월화수목금토일]\s*\)|\b\d{1,2}:\d{2}\b|[~∼～]", " ", s)
    s = re.sub(r"^\s*(까지|한)\b", "", re.sub(r"(?<=\s)(까지|한)(?=\s|$)", "", s))
    s = re.sub(r"\t+", " · ", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" ·.,:")
    if not s and prev:       # 날짜만 있는 줄: 바로 위의 짧은 항목 이름 ('마. 접수 마감' → '접수 마감')
        label = _ENUM.sub("", prev).strip(" :：")
        if 2 <= len(label) <= 15 and not re.search(r"\d", label):
            return label
    if s and table_verb and not re.search(r"(제출|회신|신청|접수|보고|등록|모집|응모)", s) and len(s) <= 40:
        return f"{s.replace(' · ', ' ')} {table_verb}".strip()        # 표의 행: '1차 계절학기 신청'
    if len(s) > 40:                     # 긴 문장: 동사 바로 앞의 '무엇을 … 제출' ('의견서를 … 제출하여' → '의견서 제출')
        ov = _last_obj_verb(s)
        if ov:
            return ov
    if len(s) > 18 and re.search(r"(바랍니다|부탁드립니다|주시기|하시어|하여)", s):
        s = _nounize(_LEAD.sub("", s))          # 긴 문장은 '수요조사표 작성 · 회신 요청'처럼 줄인다
        s = re.sub(r"\s*요청$", "", s)
        s = re.sub(r"^\S*(?:첨부한|붙임의?|별첨)\s+", "", s)
        s = re.sub(r"\S+(?:메일|우편)\([^)]*\)\s*(?:로|으로)\s+", "", s)
    return s[:120] or title


def item_names(value: str) -> list[str]:
    """'참가 신청서(붙임 1 서식) 1부, 부서별 참석자 명단 1부' → ['참가 신청서', '부서별 참석자 명단']"""
    v = re.sub(r"\(\s*(?:붙\s*임|첨\s*부|별\s*첨)?\s*\d*\s*(?:서식|양식)?\s*\)", "", value or "")
    v = re.sub(r"(?:붙\s*임|첨\s*부|별\s*첨)\s*\d*\s*(?:서식|양식)?\s*", "", v)
    v = re.sub(r"\s*(?:각\s*)?\d+\s*부\.?", "", v)
    names = []
    for part in re.split(r"\s*(?:,|，|및|/|ㆍ|;)\s*", v):
        part = part.strip(" .,:()")
        if len(part) >= 2 and part not in names:
            names.append(part)
    return names


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

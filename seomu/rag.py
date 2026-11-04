"""로컬 RAG: 조례·법령·내규 저장소 색인 및 근거 기반 질의응답.

- 조문(제N조) 단위 청크 분할로 인용 정확도를 높인다.
- 한국어 조사 변형에 강한 BM25(단어 + 음절 바이그램) 검색을 기본으로 하고,
  로컬 임베딩 모델이 있으면 벡터 검색을 결합(하이브리드)한다.
"""
from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .llm import LLMError, OllamaClient, pack_vec, unpack_vec
from .parsers import SUPPORTED, ParseError, guess_category, parse_file
from .storage import Store

# ---------------------------------------------------------------- 토큰화
_WORD = re.compile(r"[가-힣]+|[A-Za-z]+|\d+")
_HANGUL = re.compile(r"^[가-힣]+$")
_STOP = {"및", "등", "또는", "그", "이", "저", "것", "수", "때", "의", "를", "을", "은", "는", "에", "가"}
_JOSA = ("에서는", "으로서", "으로써", "에게서", "에서", "에게", "으로", "부터", "까지", "에는", "이나",
         "이며", "하고", "하여", "한다", "된다", "이다", "와", "과", "을", "를", "은", "는", "이", "가",
         "의", "에", "로", "도", "만")


def _strip_josa(w: str) -> str:
    for j in _JOSA:
        if len(w) > len(j) + 1 and w.endswith(j):
            return w[: -len(j)]
    return w


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for w in _WORD.findall(text.lower()):
        if w in _STOP:
            continue
        if _HANGUL.match(w):
            base = _strip_josa(w)
            out.append(base)
            if len(w) >= 3:
                out.extend(w[i:i + 2] for i in range(len(w) - 1))
        else:
            out.append(w)
    return out


# ---------------------------------------------------------------- 청크 분할
_ARTICLE = re.compile(r"^[ \t]*(제\s*\d+\s*조(?:\s*의\s*\d+)?)\s*(\([^)\n]{1,40}\))?", re.M)
_CHAPTER = re.compile(r"^[ \t]*(제\s*\d+\s*(?:장|절|편)\s*[^\n]{0,40})$", re.M)


def _split_long(text: str, size: int = 1000, overlap: int = 150) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    parts, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = max(text.rfind("\n", start + size // 2, end), text.rfind(". ", start + size // 2, end))
            if cut > start:
                end = cut + 1
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [p for p in parts if p]


def chunk_document(text: str, title: str) -> list[dict]:
    """조문 구조가 있으면 조문 단위로, 없으면 문단 묶음 단위로 분할."""
    matches = list(_ARTICLE.finditer(text))
    chunks: list[dict] = []
    if len(matches) >= 2:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            for p in _split_long(preamble):
                chunks.append({"heading": "머리말", "text": p})
        chapter = ""
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[m.start():end].strip()
            # 본문 끝에 붙은 다음 '장' 제목은 다음 조문의 장 정보로 넘김
            ch_found = list(_CHAPTER.finditer(body))
            next_chapter = ch_found[-1].group(1).strip() if ch_found else None
            if ch_found:
                body = body[: ch_found[-1].start()].strip()
            art = re.sub(r"\s+", "", m.group(1))
            heading = art + (m.group(2) or "")
            if chapter:
                heading = f"{chapter} > {heading}"
            for j, p in enumerate(_split_long(body, size=1400)):
                chunks.append({"heading": heading + (f" ({j + 1})" if j else ""), "text": p})
            if next_chapter:
                chapter = next_chapter
    else:
        buf, size = "", 900
        for para in re.split(r"\n\s*\n", text):
            para = para.strip()
            if not para:
                continue
            if len(buf) + len(para) > size and buf:
                chunks.append({"heading": "", "text": buf.strip()})
                buf = buf[-120:] + "\n"
            buf += para + "\n\n"
            if len(buf) > size * 2:
                for p in _split_long(buf, size):
                    chunks.append({"heading": "", "text": p})
                buf = ""
        if buf.strip():
            chunks.append({"heading": "", "text": buf.strip()})
    for c in chunks:
        c["tokens"] = tokenize(f"{title} {c['heading']} {c['text']}")
    return chunks


# ---------------------------------------------------------------- 검색 인덱스
@dataclass
class Hit:
    chunk_id: int
    title: str
    heading: str
    text: str
    path: str
    category: str
    score: float

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id, "title": self.title, "heading": self.heading,
            "text": self.text, "path": self.path, "category": self.category,
            "score": round(self.score, 4),
        }


class Index:
    k1, b = 1.5, 0.75

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.docs = [r["tokens"].split() for r in rows]
        self.tf = [Counter(d) for d in self.docs]
        self.dl = [len(d) for d in self.docs]
        self.avgdl = (sum(self.dl) / len(self.dl)) if self.dl else 0
        df: Counter = Counter()
        for d in self.tf:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.vecs = [unpack_vec(r.get("embedding")) for r in rows]
        self.has_vecs = any(v for v in self.vecs)

    def bm25(self, q_tokens: list[str]) -> list[float]:
        scores = [0.0] * len(self.docs)
        q = Counter(q_tokens)
        for i, tf in enumerate(self.tf):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * self.dl[i] / (self.avgdl or 1))
            for t, qf in q.items():
                f = tf.get(t)
                if f:
                    s += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + norm)
            scores[i] = s
        return scores

    @staticmethod
    def _cos(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    def search(self, query: str, k: int = 6, q_vec: list[float] | None = None,
               category: str | None = None) -> list[Hit]:
        if not self.rows:
            return []
        bm = self.bm25(tokenize(query))
        mx = max(bm) or 1.0
        scores = [s / mx for s in bm]
        if q_vec and self.has_vecs:
            cos = [self._cos(q_vec, v) if v else 0.0 for v in self.vecs]
            scores = [0.45 * s + 0.55 * max(c, 0) for s, c in zip(scores, cos)]
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        hits: list[Hit] = []
        for i in order:
            if scores[i] <= 0:
                break
            r = self.rows[i]
            if category and category != "전체" and r["category"] != category:
                continue
            hits.append(Hit(r["id"], r["title"], r["heading"], r["text"], r["path"], r["category"], scores[i]))
            if len(hits) >= k:
                break
        return hits


# ---------------------------------------------------------------- RAG 엔진
SYSTEM_PROMPT = """당신은 지방자치단체·공공기관의 서무 업무를 돕는 'AI 서무비서'입니다.
반드시 아래 [근거] 안의 조례·법령·내규 내용만을 바탕으로 한국어로 답하세요.
규칙:
1. 근거에 없는 내용은 추측하지 말고 "저장된 규정에서 확인되지 않습니다"라고 말하세요.
2. 문장 끝에 사용한 근거 번호를 [1], [2]처럼 표시하세요.
3. 조문명(예: 「○○ 조례」 제5조)을 함께 밝히세요.
4. 절차를 묻는 경우 단계별 번호 목록으로, 필요한 서식·제출처·기한이 있으면 따로 정리하세요.
5. 공문서 어투(~함, ~임)가 아닌 정중한 설명체로 간결하게 답하세요."""


class RAGEngine:
    def __init__(self, store: Store, client_factory: Callable[[], OllamaClient], settings_getter):
        self.store = store
        self.client_factory = client_factory
        self.settings = settings_getter
        self._index: Index | None = None
        self._lock = threading.Lock()
        self.progress = {"running": False, "done": 0, "total": 0, "current": "", "errors": []}

    def invalidate(self) -> None:
        with self._lock:
            self._index = None

    def index(self) -> Index:
        with self._lock:
            if self._index is None:
                self._index = Index(self.store.all_chunks())
            return self._index

    # ---------- 색인 ----------
    def scan_files(self) -> list[Path]:
        files: list[Path] = []
        for d in self.settings().regulation_dirs:
            p = Path(d).expanduser()
            if p.is_file() and p.suffix.lower() in SUPPORTED:
                files.append(p)
            elif p.is_dir():
                files.extend(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED
                             and not f.name.startswith(("~$", ".")))
        return sorted(set(files))

    def reindex(self, force: bool = False) -> dict:
        if self.progress["running"]:
            return {"ok": False, "error": "이미 색인 중입니다"}
        files = self.scan_files()
        self.progress = {"running": True, "done": 0, "total": len(files), "current": "", "errors": []}
        added = skipped = 0
        try:
            s = self.settings()
            client = self.client_factory()
            embed_model = client.pick_embed_model(s.embed_model)
            seen = set()
            for f in files:
                key = str(f.resolve())
                seen.add(key)
                self.progress["current"] = f.name
                st = f.stat()
                old = self.store.get_document(key)
                if (not force and old and abs(old["mtime"] - st.st_mtime) < 1e-6 and old["size"] == st.st_size):
                    skipped += 1
                    self.progress["done"] += 1
                    continue
                try:
                    text = parse_file(f)
                except (ParseError, OSError, ValueError) as e:
                    self.progress["errors"].append(f"{f.name}: {e}")
                    self.progress["done"] += 1
                    continue
                title = f.stem
                chunks = chunk_document(text, title)
                if embed_model and chunks:
                    try:
                        for i in range(0, len(chunks), 16):
                            batch = chunks[i:i + 16]
                            vecs = client.embed([f"{title} {c['heading']}\n{c['text']}" for c in batch], embed_model)
                            for c, v in zip(batch, vecs):
                                c["embedding"] = pack_vec(v) if v else None
                    except LLMError as e:
                        self.progress["errors"].append(f"{f.name}: 임베딩 생략 ({e})")
                self.store.replace_document(key, title, guess_category(f, text), st.st_mtime, st.st_size, chunks)
                added += 1
                self.progress["done"] += 1
            for doc in self.store.list_documents():
                if doc["path"] not in seen:
                    self.store.delete_document(doc["path"])
        finally:
            self.progress["running"] = False
            self.progress["current"] = ""
            self.invalidate()
        return {"ok": True, "added": added, "skipped": skipped, "total": len(files),
                "errors": self.progress["errors"]}

    # ---------- 검색/응답 ----------
    def search(self, query: str, k: int | None = None, category: str | None = None) -> list[Hit]:
        s = self.settings()
        idx = self.index()
        q_vec = None
        if idx.has_vecs:
            try:
                client = self.client_factory()
                em = client.pick_embed_model(s.embed_model)
                if em:
                    q_vec = client.embed([query], em)[0]
            except (LLMError, IndexError):
                q_vec = None
        return idx.search(query, k or s.top_k, q_vec=q_vec, category=category)

    @staticmethod
    def build_context(hits: list[Hit]) -> str:
        blocks = []
        for i, h in enumerate(hits, 1):
            head = f"「{h.title}」" + (f" {h.heading}" if h.heading else "")
            blocks.append(f"[{i}] {head}\n{h.text[:1800]}")
        return "\n\n".join(blocks)

    def answer(self, question: str, category: str | None = None,
               on_token: Callable[[str], None] | None = None, history: list[dict] | None = None) -> dict:
        hits = self.search(question, category=category)
        sources = [h.to_dict() for h in hits]
        if not hits:
            msg = ("저장소에서 관련 규정을 찾지 못했습니다. '규정 저장소'에 조례·법령·내규 파일을 추가하고 "
                   "색인을 갱신해 주세요.")
            if on_token:
                on_token(msg)
            return {"answer": msg, "sources": [], "mode": "none"}
        s = self.settings()
        client = self.client_factory()
        try:
            model = client.pick_chat_model(s.chat_model)
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            for h in (history or [])[-4:]:
                messages.append({"role": "user", "content": h["question"]})
                messages.append({"role": "assistant", "content": h["answer"][:800]})
            messages.append({"role": "user", "content": f"[근거]\n{self.build_context(hits)}\n\n[질문]\n{question}"})
            text = client.chat(messages, model, temperature=s.temperature, num_ctx=s.num_ctx, on_token=on_token)
            return {"answer": text.strip(), "sources": sources, "mode": "llm", "model": model}
        except LLMError as e:
            lines = [f"⚠️ 로컬 AI 모델을 사용할 수 없어 관련 조문만 찾아 보여드립니다.\n({e})\n"]
            for i, h in enumerate(hits[:4], 1):
                head = f"「{h.title}」 {h.heading}".strip()
                lines.append(f"[{i}] {head}\n{h.text[:400]}{'…' if len(h.text) > 400 else ''}\n")
            msg = "\n".join(lines)
            if on_token:
                on_token(msg)
            return {"answer": msg, "sources": sources, "mode": "search"}

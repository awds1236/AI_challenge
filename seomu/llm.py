"""로컬 LLM(Ollama) 클라이언트.

- 기본적으로 루프백 주소(127.0.0.1, localhost, ::1)만 허용하여
  프롬프트·문서 내용이 PC 밖으로 나가지 않도록 차단한다.
- 시스템 프록시 설정을 무시(직접 연결)하여 프록시 서버로의 유출도 막는다.
"""
from __future__ import annotations

import ipaddress
import json
import struct
import urllib.error
import urllib.request
from typing import Callable, Iterable
from urllib.parse import urlparse

PREFERRED_CHAT = ("gemma4", "gemma3n", "gemma3", "gemma2", "gemma", "qwen", "exaone", "llama")
PREFERRED_EMBED = ("bge-m3", "nomic-embed", "mxbai-embed", "embeddinggemma", "snowflake-arctic-embed", "embed")


class LLMError(RuntimeError):
    pass


def is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").strip("[]").lower()
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", allow_remote: bool = False,
                 timeout: float = 600.0):
        self.base_url = base_url.rstrip("/")
        self.allow_remote = allow_remote
        self.timeout = timeout

    # ---------- 저수준 ----------
    def _check(self) -> None:
        if not self.allow_remote and not is_loopback_url(self.base_url):
            raise LLMError(
                f"보안 정책: 로컬 주소만 허용됩니다 (현재 {self.base_url}). "
                "설정에서 '외부 LLM 주소 허용'을 켜지 않는 한 PC 밖으로 데이터를 보내지 않습니다."
            )

    def _request(self, path: str, payload: dict | None = None, timeout: float | None = None):
        self._check()
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data is not None else "GET",
        )
        try:
            return _opener.open(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:300]
            raise LLMError(f"Ollama 오류 {e.code}: {body}") from e
        except (urllib.error.URLError, OSError) as e:
            raise LLMError(
                "로컬 AI 엔진(Ollama)에 연결할 수 없습니다. Ollama가 실행 중인지 확인하세요. "
                f"({e})"
            ) from e

    def _json(self, path: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        with self._request(path, payload, timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    # ---------- 상태 ----------
    def list_models(self) -> list[str]:
        data = self._json("/api/tags", timeout=5)
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]

    def status(self) -> dict:
        try:
            models = self.list_models()
            return {"ok": True, "models": models}
        except LLMError as e:
            return {"ok": False, "models": [], "error": str(e)}

    @staticmethod
    def _pick(models: Iterable[str], prefs: tuple[str, ...], exclude_embed: bool) -> str:
        models = list(models)
        cand = [m for m in models if not exclude_embed or "embed" not in m.lower()]
        for p in prefs:
            for m in cand:
                if p in m.lower():
                    return m
        return cand[0] if cand and exclude_embed else ""

    def pick_chat_model(self, configured: str = "") -> str:
        if configured:
            return configured
        try:
            m = self._pick(self.list_models(), PREFERRED_CHAT, exclude_embed=True)
        except LLMError:
            m = ""
        if not m:
            raise LLMError("설치된 AI 모델이 없습니다. 예: `ollama pull gemma3:4b` 실행 후 다시 시도하세요.")
        return m

    def pick_embed_model(self, configured: str = "") -> str:
        if configured:
            return configured
        try:
            models = self.list_models()
        except LLMError:
            return ""
        embeds = [m for m in models if "embed" in m.lower() or "bge" in m.lower()]
        return self._pick(embeds, PREFERRED_EMBED, exclude_embed=False) if embeds else ""

    # ---------- 생성 ----------
    def chat(self, messages: list[dict], model: str, temperature: float = 0.2, num_ctx: int = 8192,
             fmt: str | dict | None = None, on_token: Callable[[str], None] | None = None) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "stream": on_token is not None,
            "options": {"temperature": temperature, "num_ctx": num_ctx},
        }
        if fmt:
            payload["format"] = fmt
        if on_token is None:
            data = self._json("/api/chat", payload)
            return data.get("message", {}).get("content", "")
        out = []
        with self._request("/api/chat", payload) as r:
            for line in r:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                if obj.get("error"):
                    raise LLMError(obj["error"])
                tok = obj.get("message", {}).get("content", "")
                if tok:
                    out.append(tok)
                    on_token(tok)
                if obj.get("done"):
                    break
        return "".join(out)

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        if not texts:
            return []
        try:
            data = self._json("/api/embed", {"model": model, "input": texts})
            embs = data.get("embeddings")
            if embs:
                return embs
        except LLMError:
            pass
        # 구버전 Ollama 호환
        return [self._json("/api/embeddings", {"model": model, "prompt": t}).get("embedding", []) for t in texts]


def pack_vec(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack_vec(blob: bytes | None) -> list[float] | None:
    if not blob:
        return None
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def extract_json(text: str) -> dict | list | None:
    """LLM 응답에서 JSON 부분만 안전하게 추출."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    for opener, closer in (("{", "}"), ("[", "]")):
        s, e = text.find(opener), text.rfind(closer)
        if s != -1 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except json.JSONDecodeError:
                continue
    return None

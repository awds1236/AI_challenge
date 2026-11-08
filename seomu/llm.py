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

PREFERRED_CHAT = ("gemma4", "kanana", "gemma3n", "gemma3", "gemma2", "gemma", "exaone", "llama")
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
                 timeout: float = 900.0, keep_alive: str = "30m", num_ctx: int = 0):
        self.base_url = base_url.rstrip("/")
        self.allow_remote = allow_remote
        self.timeout = timeout
        self.keep_alive = keep_alive   # 사용 후에도 모델을 메모리에 유지 (다음 요청 시 다시 불러오지 않음)
        # Ollama는 num_ctx가 바뀌면 모델을 다시 불러온다(수 초~수십 초). 모든 요청에 같은 값을 쓴다.
        self.num_ctx = int(num_ctx or 0)

    # ---------- 저수준 ----------
    def _check(self) -> None:
        if not self.allow_remote and not is_loopback_url(self.base_url):
            raise LLMError(
                f"보안 정책: 로컬 주소만 허용됩니다 (현재 {self.base_url}). "
                "설정에서 '외부 LLM 주소 허용'을 켜지 않는 한 PC 밖으로 데이터를 보내지 않습니다."
            )

    def _request(self, path: str, payload: dict | None = None, timeout: float | None = None,
                 method: str | None = None, raw=None, headers: dict | None = None):
        self._check()
        data = raw if raw is not None else (json.dumps(payload).encode("utf-8") if payload is not None else None)
        req = urllib.request.Request(
            self.base_url + path, data=data,
            headers=headers or {"Content-Type": "application/json"},
            method=method or ("POST" if data is not None else "GET"),
        )
        try:
            return _opener.open(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:300]
            raise LLMError(f"Ollama 오류 {e.code}: {body}") from e
        except (urllib.error.URLError, OSError) as e:
            import logging
            logging.getLogger("seomu.llm").info("Ollama 연결 실패: %s", e)      # 기술적인 원인은 기록에만
            raise LLMError(
                "AI 엔진이 연결되어 있지 않습니다. 설정 → AI 모델에서 [받기]를 누르면 내장 AI 엔진과 모델을 받아 "
                "Ollama 없이 쓸 수 있습니다 (Ollama를 쓰신다면 Ollama를 실행해 주세요)."
            ) from e

    def _json(self, path: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        with self._request(path, payload, timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    # ---------- 상태 ----------
    def list_models(self) -> list[str]:
        data = self._json("/api/tags", timeout=10)
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
            raise LLMError("설치된 AI 모델이 없습니다. 설정 → AI 모델에서 [받기]를 누르면 AI 답변을 쓸 수 있습니다.")
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
             fmt: str | dict | None = None, on_token: Callable[[str], None] | None = None,
             max_tokens: int = 0) -> str:
        options = {"temperature": temperature, "num_ctx": self.num_ctx or num_ctx}
        if max_tokens:
            options["num_predict"] = int(max_tokens)   # 답변 길이 상한 → 생성 시간 상한
        payload = {
            "model": model,
            "messages": messages,
            "stream": on_token is not None,
            "options": options,
            "keep_alive": self.keep_alive,
            "think": False,          # 생각(추론) 모드를 끈다: 숨은 토큰 생성 시간을 없앤다
        }
        if fmt:
            payload["format"] = fmt
        try:
            return self._chat(payload, on_token)
        except LLMError as e:
            if "think" not in str(e).lower():
                raise
            payload.pop("think", None)   # 생각 모드 옵션을 모르는 구버전/모델
            return self._chat(payload, on_token)

    def _chat(self, payload: dict, on_token: Callable[[str], None] | None) -> str:
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

    def preload(self, model: str) -> None:
        """모델을 미리 메모리에 올린다 (프롬프트 없이 요청하면 로드만 한다)."""
        payload = {"model": model, "keep_alive": self.keep_alive}
        if self.num_ctx:   # 실제 요청과 같은 num_ctx로 올려야 첫 요청에서 다시 불러오지 않는다
            payload["options"] = {"num_ctx": self.num_ctx}
        self._json("/api/generate", payload, timeout=600)

    def unload(self, model: str) -> None:
        self._json("/api/generate", {"model": model, "keep_alive": 0}, timeout=5)

    # ---------- 모델 관리 ----------
    def _stream(self, path: str, payload: dict, on_progress: Callable[[dict], None] | None,
                timeout: float = 3600) -> dict:
        last: dict = {}
        with self._request(path, payload, timeout=timeout) as r:
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
                last = obj
                if on_progress:
                    on_progress(obj)
        return last

    def pull(self, model: str, on_progress: Callable[[dict], None] | None = None) -> dict:
        """모델 다운로드 (Ollama 공식 저장소 또는 hf.co/... GGUF)."""
        return self._stream("/api/pull", {"model": model, "stream": True}, on_progress)

    def copy(self, source: str, destination: str) -> None:
        with self._request("/api/copy", {"source": source, "destination": destination}):
            pass

    def delete(self, model: str) -> None:
        with self._request("/api/delete", {"model": model}, method="DELETE"):
            pass

    def push_blob(self, path: str, on_progress: Callable[[dict], None] | None = None) -> str:
        """GGUF 파일을 Ollama에 올리고 sha256 다이제스트를 돌려준다 (인터넷 불필요)."""
        import hashlib
        import os
        h = hashlib.sha256()
        size = os.path.getsize(path)
        done = 0
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress({"status": "파일 검사 중", "total": size, "completed": done})
        digest = "sha256:" + h.hexdigest()
        try:
            with self._request(f"/api/blobs/{digest}", method="HEAD", timeout=10):
                return digest  # 이미 있음
        except LLMError:
            pass
        if on_progress:
            on_progress({"status": "AI 엔진에 등록 중", "total": size, "completed": 0})
        with open(path, "rb") as f:
            with self._request(f"/api/blobs/{digest}", raw=f, method="POST",
                               headers={"Content-Length": str(size),
                                        "Content-Type": "application/octet-stream"}, timeout=3600):
                pass
        return digest

    def create_from_gguf(self, name: str, path: str, on_progress: Callable[[dict], None] | None = None) -> dict:
        import os
        digest = self.push_blob(path, on_progress)
        return self._stream("/api/create", {"model": name, "files": {os.path.basename(path): digest},
                                            "stream": True}, on_progress)

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

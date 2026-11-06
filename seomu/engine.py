"""내장 AI 엔진 (llama.cpp llama-server) — Ollama 없이 동작.

- 프로그램 폴더의 engine/llama-server(.exe)를 프로그램이 직접 실행·종료한다 (설치 불필요).
- models/ 폴더의 .gguf 모델 파일을 그대로 사용한다. 인터넷이 없는 업무망에서도 동작한다.
- 127.0.0.1(이 PC)에서만 접속을 받고, 시스템 프록시를 거치지 않는다.

OllamaClient와 같은 메서드(status, pick_chat_model, chat, embed …)를 제공해 나머지 코드는 그대로 쓴다.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .llm import PREFERRED_CHAT, PREFERRED_EMBED, LLMError

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
EMBED_HINTS = ("embed", "bge", "e5-", "gte-")


def app_dir() -> Path:
    """프로그램 폴더 (exe로 묶었으면 exe가 있는 폴더)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def is_embed_name(name: str) -> bool:
    n = name.lower()
    return any(h in n for h in EMBED_HINTS)


class LocalEngine:
    """llama-server 프로세스 관리 (답변용 1개 + 검색용 임베딩 1개)."""

    def __init__(self, home: Path):
        self.home = Path(home)
        self._procs: dict[str, dict] = {}      # kind → {"proc", "model", "port"}
        self._lock = threading.RLock()
        self.log_path = self.home / "engine.log"

    # ---------- 위치 ----------
    def server_path(self) -> str:
        exe = "llama-server.exe" if sys.platform.startswith("win") else "llama-server"
        for d in (app_dir() / "engine", self.home / "engine", app_dir()):
            p = d / exe
            if p.exists():
                return str(p)
            if d.exists():                     # 압축을 풀면 하위 폴더에 들어가는 경우
                for sub in d.glob(f"*/{exe}"):
                    return str(sub)
        return shutil.which("llama-server") or ""

    def model_dirs(self) -> list[Path]:
        return [app_dir() / "models", self.home / "models"]

    def writable_model_dir(self) -> Path:
        d = app_dir() / "models"
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".write_test"
            probe.write_text("ok")
            probe.unlink()
            return d
        except OSError:
            d = self.home / "models"
            d.mkdir(parents=True, exist_ok=True)
            return d

    def writable_engine_dir(self) -> Path:
        """엔진을 받아 둘 폴더: 프로그램 폴더의 engine (쓸 수 없으면 앱 데이터 폴더)."""
        d = app_dir() / "engine"
        try:
            d.parent.mkdir(parents=True, exist_ok=True)
            probe = d.parent / ".write_test"
            probe.write_text("ok")
            probe.unlink()
            return d
        except OSError:
            return self.home / "engine"

    def models(self) -> dict[str, Path]:
        """{모델 이름(파일 이름에서 .gguf 뺀 것): 경로}. 이미지용 보조 파일(mmproj)은 제외."""
        out: dict[str, Path] = {}
        for d in self.model_dirs():
            if d.exists():
                for p in sorted(d.rglob("*.gguf")):
                    if "mmproj" in p.name.lower():
                        continue
                    out.setdefault(p.stem, p)
        return out

    def available(self) -> bool:
        return bool(self.server_path()) and bool(self.models())

    # ---------- 실행 ----------
    def _alive(self, info: dict) -> bool:
        return info["proc"].poll() is None

    def ensure(self, model: str, kind: str = "chat", ctx: int = 8192, threads: int = 0,
               wait: float = 300) -> str:
        """model을 띄운 서버 주소를 돌려준다. 다른 모델이 떠 있으면 바꿔 띄운다."""
        with self._lock:
            info = self._procs.get(kind)
            if info and info["model"] == model and self._alive(info):
                return f"http://127.0.0.1:{info['port']}"
            self.stop(kind)
            server = self.server_path()
            if not server:
                raise LLMError("내장 AI 엔진(engine\\llama-server.exe)이 없습니다. 설치 안내를 확인하세요.")
            path = self.models().get(model)
            if not path:
                raise LLMError(f"모델 파일을 찾을 수 없습니다: {model}.gguf (models 폴더 확인)")
            port = _free_port()
            args = [server, "-m", str(path), "--host", "127.0.0.1", "--port", str(port),
                    "-c", str(ctx), "--jinja"] + self._speed_args(server, kind, ctx)
            if threads and threads > 0:
                args += ["-t", str(threads)]
            if kind == "embed":
                args += ["--embedding"]
            self.home.mkdir(parents=True, exist_ok=True)
            log = open(self.log_path, "ab")
            try:
                proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        cwd=str(Path(server).parent),
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError as e:
                log.close()
                raise LLMError(f"내장 AI 엔진을 실행하지 못했습니다: {e}") from e
            info = {"proc": proc, "model": model, "port": port, "log": log}
            self._procs[kind] = info
        url = f"http://127.0.0.1:{port}"
        end = time.time() + wait
        while time.time() < end:               # 모델 로드가 끝날 때까지 대기
            if proc.poll() is not None:
                raise LLMError("내장 AI 엔진이 종료되었습니다. engine.log를 확인하세요 "
                               "(엔진 버전이 모델을 지원하지 않거나 메모리가 부족할 수 있습니다).")
            try:
                with _opener.open(url + "/health", timeout=2) as r:
                    if json.loads(r.read() or b"{}").get("status") in ("ok", "no slot available"):
                        return url
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(0.5)
        raise LLMError("내장 AI 엔진이 시간 안에 준비되지 않았습니다.")

    def _help(self, server: str) -> str:
        """llama-server가 아는 옵션 목록 (버전마다 다르므로 실행 파일에 물어본다)."""
        cache = self.__dict__.setdefault("_help_cache", {})
        if server not in cache:
            try:
                r = subprocess.run(
                    [server, "--help"], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL,
                    encoding="utf-8", errors="ignore", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                cache[server] = (r.stdout or "") + (r.stderr or "")   # 버전에 따라 도움말이 stderr로 나온다
            except (OSError, subprocess.SubprocessError):
                cache[server] = ""
        return cache[server]

    def _speed_args(self, server: str, kind: str, ctx: int) -> list[str]:
        """속도 옵션 — 엔진이 지원하는 것만 붙인다 (모르는 옵션을 주면 엔진이 켜지지 않는다)."""
        h = self._help(server)
        args: list[str] = []
        if kind == "embed":
            # 임베딩은 문단 하나를 한 번에 처리해야 한다: 배치를 문맥 길이만큼 키우면 긴 조문도 한 번에 계산
            if "--ubatch-size" in h:
                args += ["-b", str(ctx), "-ub", str(ctx)]
        else:
            # 앞부분이 같은 프롬프트(고정 지시문·대화 기록)는 계산해 둔 결과를 다시 쓴다
            if "--cache-reuse" in h:
                args += ["--cache-reuse", "256"]
        if "--no-webui" in h:
            args += ["--no-webui"]
        return args

    def stop(self, kind: str | None = None) -> None:
        with self._lock:
            for k in ([kind] if kind else list(self._procs)):
                info = self._procs.pop(k, None)
                if not info:
                    continue
                try:
                    info["proc"].terminate()
                    info["proc"].wait(timeout=5)
                except Exception:
                    try:
                        info["proc"].kill()
                    except Exception:
                        pass
                try:
                    info["log"].close()
                except Exception:
                    pass

    def running(self) -> dict[str, str]:
        return {k: v["model"] for k, v in self._procs.items() if self._alive(v)}


class LocalClient:
    """내장 엔진용 클라이언트 (OllamaClient와 같은 사용법)."""

    def __init__(self, engine: LocalEngine, ctx: int = 8192, threads: int = 0, timeout: float = 900):
        self.engine = engine
        self.ctx = ctx
        self.threads = threads
        self.timeout = timeout
        self.base_url = "내장 엔진"

    # ---------- 상태 ----------
    def list_models(self) -> list[str]:
        return list(self.engine.models())

    def status(self) -> dict:
        if not self.engine.server_path():
            return {"ok": False, "models": self.list_models(), "engine": "builtin",
                    "error": "내장 AI 엔진 파일(engine\\llama-server.exe)이 없습니다."}
        models = self.list_models()
        if not models:
            return {"ok": False, "models": [], "engine": "builtin",
                    "error": "models 폴더에 모델 파일(.gguf)이 없습니다."}
        return {"ok": True, "models": models, "engine": "builtin", "running": self.engine.running()}

    def pick_chat_model(self, configured: str = "") -> str:
        models = self.list_models()
        if configured and configured in models:
            return configured
        chat = [m for m in models if not is_embed_name(m)]
        for p in PREFERRED_CHAT:
            for m in chat:
                if p.replace("gemma4", "gemma-4") in m.lower() or p in m.lower():
                    return m
        if chat:
            return chat[0]
        raise LLMError("models 폴더에 답변용 모델 파일(.gguf)이 없습니다.")

    def pick_embed_model(self, configured: str = "") -> str:
        models = self.list_models()
        if configured and configured in models:
            return configured
        emb = [m for m in models if is_embed_name(m)]
        for p in PREFERRED_EMBED:
            for m in emb:
                if p in m.lower():
                    return m
        return emb[0] if emb else ""

    # ---------- 요청 ----------
    def _post(self, url: str, payload: dict, stream: bool = False):
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            return _opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raise LLMError(f"내장 AI 엔진 오류 {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}") from e
        except (urllib.error.URLError, OSError) as e:
            raise LLMError(f"내장 AI 엔진에 연결할 수 없습니다: {e}") from e

    def chat(self, messages: list[dict], model: str, temperature: float = 0.2, num_ctx: int = 8192,
             fmt: str | dict | None = None, on_token: Callable[[str], None] | None = None,
             max_tokens: int = 0) -> str:
        url = self.engine.ensure(model, "chat", ctx=max(self.ctx, 4096), threads=self.threads)
        payload: dict = {"messages": messages, "temperature": temperature, "stream": on_token is not None,
                         "max_tokens": int(max_tokens or 1536), "cache_prompt": True,
                         # 생각(추론) 모드를 끈다: 답 전에 숨은 토큰을 만드느라 걸리는 시간을 없앤다
                         "chat_template_kwargs": {"enable_thinking": False}}
        if isinstance(fmt, dict):
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "result", "schema": fmt}}
        elif fmt:
            payload["response_format"] = {"type": "json_object"}
        if on_token is None:
            with self._post(url + "/v1/chat/completions", payload) as r:
                data = json.loads(r.read().decode("utf-8"))
            return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        out = []
        with self._post(url + "/v1/chat/completions", payload, stream=True) as r:
            for line in r:
                line = line.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    break
                try:
                    obj = json.loads(body)
                except json.JSONDecodeError:
                    continue
                tok = ((obj.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                if tok:
                    out.append(tok)
                    on_token(tok)
        return "".join(out)

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        if not texts:
            return []
        url = self.engine.ensure(model, "embed", ctx=2048, threads=self.threads)
        with self._post(url + "/v1/embeddings", {"input": texts, "model": model}) as r:
            data = json.loads(r.read().decode("utf-8"))
        items = sorted(data.get("data") or [], key=lambda d: d.get("index", 0))
        return [d.get("embedding") or [] for d in items]

    def preload(self, model: str) -> None:
        self.engine.ensure(model, "chat", ctx=max(self.ctx, 4096), threads=self.threads)

    def unload(self, model: str) -> None:
        self.engine.stop()

    # ---------- 모델 관리 (Ollama 전용 기능은 안내) ----------
    def pull(self, model: str, on_progress=None):
        raise LLMError("내장 엔진은 모델을 내려받지 않습니다. 모델 파일(.gguf)을 '파일 추가'로 넣어 주세요.")

    def delete(self, model: str) -> None:
        path = self.engine.models().get(model)
        if not path:
            raise LLMError("모델 파일을 찾을 수 없습니다.")
        self.engine.stop()
        path.unlink()

    def copy(self, source: str, destination: str) -> None:
        raise LLMError("내장 엔진에서는 지원하지 않습니다.")

    def create_from_gguf(self, name: str, path: str, on_progress=None) -> dict:
        add_model_file(self.engine, path, name, on_progress)
        return {"status": "success"}


def add_model_file(engine: LocalEngine, src: str, name: str = "", on_progress=None) -> Path:
    """GGUF 파일을 models 폴더로 복사한다 (진행률 표시)."""
    srcp = Path(src)
    if not srcp.is_file():
        raise LLMError("모델 파일을 찾을 수 없습니다.")
    stem = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in (name or srcp.stem)).strip("-.")
    dest = engine.writable_model_dir() / f"{stem}.gguf"
    if dest.exists() and dest.stat().st_size == srcp.stat().st_size:
        return dest
    total, done = srcp.stat().st_size, 0
    tmp = dest.with_suffix(".part")
    with open(srcp, "rb") as fi, open(tmp, "wb") as fo:
        for chunk in iter(lambda: fi.read(8 << 20), b""):
            fo.write(chunk)
            done += len(chunk)
            if on_progress:
                on_progress({"status": "모델 파일 복사 중", "total": total, "completed": done})
    tmp.replace(dest)
    return dest


def ollama_model_blob(name: str) -> Path | None:
    """Ollama로 받아 둔 모델의 GGUF 파일 위치 (Ollama가 꺼져 있어도 찾을 수 있다)."""
    root = Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")
    model, _, tag = name.partition(":")
    tag = tag or "latest"
    parts = model.split("/")
    if len(parts) == 1:
        parts = ["registry.ollama.ai", "library", parts[0]]
    elif len(parts) == 2:
        parts = ["registry.ollama.ai"] + parts
    manifest = root / "manifests" / Path(*parts) / tag
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for layer in data.get("layers", []):
        if layer.get("mediaType") == "application/vnd.ollama.image.model":
            blob = root / "blobs" / layer["digest"].replace(":", "-")
            return blob if blob.exists() else None
    return None

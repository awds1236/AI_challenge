"""내장 AI 엔진(llama.cpp)과 모델 파일(.gguf) 자동 받기.

설정의 모델 카드에서 [받기]를 누르면:
1) 내장 엔진(llama-server)이 없으면 llama.cpp 공식 배포본(GitHub Releases)을 받아 engine 폴더에 풉니다.
2) 모델 파일을 Hugging Face 공식 저장소에서 받아 models 폴더에 넣습니다.
   - 끊기면 이어 받기(Range), 받은 뒤 크기·SHA-256을 확인합니다.

받기는 인터넷이 필요하며 시스템 프록시 설정을 따릅니다. (AI 추론 자체는 이 PC 안에서만 합니다)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from .llm import LLMError

HF_BASE = "https://huggingface.co"
GH_RELEASE_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
UA = {"User-Agent": "SeomuAI"}
Progress = Callable[[dict], None] | None


def _opener():
    # 내려받기는 일반 인터넷 접속이라 시스템 프록시를 따른다 (AI 엔진 통신과 다름)
    return urllib.request.build_opener()


def _get_json(url: str, timeout: float = 30) -> dict | list:
    req = urllib.request.Request(url, headers={**UA, "Accept": "application/json"})
    try:
        with _opener().open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise LLMError(f"인터넷에서 정보를 받지 못했습니다 ({url.split('/')[2]}): {e}") from e


def download(url: str, dest: Path, on_progress: Progress = None, label: str = "받는 중",
             size: int = 0, sha256: str = "", timeout: float = 60) -> Path:
    """url을 dest로 받는다. dest.part가 있으면 이어 받는다. 크기·해시가 주어지면 확인한다."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    if size and have > size:
        part.unlink()
        have = 0
    headers = dict(UA)
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        r = _opener().open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 416 and size and have == size:      # 이미 다 받음
            r = None
        else:
            raise LLMError(f"내려받기 실패 ({e.code}): {url.split('?')[0]}") from e
    except (urllib.error.URLError, OSError) as e:
        raise LLMError(f"인터넷에 연결할 수 없습니다: {e}") from e
    if r is not None:
        with r:
            if have and r.status != 206:                   # 서버가 이어 받기를 지원하지 않음
                have = 0
            total = size or (have + int(r.headers.get("Content-Length") or 0))
            with open(part, "ab" if have else "wb") as f:
                done = have
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress({"status": label, "total": total, "completed": done})
    got = part.stat().st_size
    if size and got != size:
        raise LLMError(f"내려받기가 중간에 끊겼습니다 ({got:,}/{size:,} 바이트). 다시 누르면 이어서 받습니다.")
    if sha256:
        if on_progress:
            on_progress({"status": "파일 확인 중", "total": got, "completed": 0})
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for i, chunk in enumerate(iter(lambda: f.read(8 << 20), b"")):
                h.update(chunk)
                if on_progress and i % 16 == 0:
                    on_progress({"status": "파일 확인 중", "total": got, "completed": min(got, (i + 1) * (8 << 20))})
        if h.hexdigest().lower() != sha256.lower():
            part.unlink()
            raise LLMError("받은 파일이 원본과 다릅니다(손상). 다시 받아 주세요.")
    part.replace(dest)
    return dest


# ---------------------------------------------------------------- 모델
def hf_file_info(repo: str, filename: str) -> dict:
    """Hugging Face 파일의 크기와 SHA-256 (확인용). 못 얻으면 빈 값."""
    try:
        info = _get_json(f"{HF_BASE}/api/models/{repo}?blobs=true")
    except LLMError:
        return {}
    siblings = (info.get("siblings") or []) if isinstance(info, dict) else []
    for s in siblings:
        if s.get("rfilename") == filename:
            return {"size": int(s.get("size") or 0), "sha256": (s.get("lfs") or {}).get("sha256", "")}
    return {}


def download_model(spec: dict, model_dir: Path, on_progress: Progress = None) -> Path:
    """spec = {"repo", "file", "as"} → model_dir/<as>.gguf"""
    dest = Path(model_dir) / f"{spec['as']}.gguf"
    if dest.exists():
        return dest
    meta = hf_file_info(spec["repo"], spec["file"])
    url = f"{HF_BASE}/{spec['repo']}/resolve/main/{spec['file']}"
    return download(url, dest, on_progress, "AI 모델 받는 중", meta.get("size", 0), meta.get("sha256", ""),
                    timeout=120)


# ---------------------------------------------------------------- 엔진
def _engine_asset_pattern() -> str:
    if sys.platform.startswith("win"):
        return r"bin-win-cpu-x64\.zip$"
    if sys.platform == "darwin":
        return r"bin-macos-(arm64|x64)\.(zip|tar\.gz)$"
    return r"bin-ubuntu-x64\.(zip|tar\.gz)$"


def pick_engine_asset(release: dict) -> dict | None:
    pat = re.compile(_engine_asset_pattern())
    arm = sys.platform == "darwin" and os.uname().machine == "arm64"
    assets = [a for a in release.get("assets") or [] if pat.search(a.get("name", ""))]
    if sys.platform == "darwin":
        assets.sort(key=lambda a: ("arm64" in a["name"]) != arm)
    return assets[0] if assets else None


def _extract(archive: Path, dest: Path) -> None:
    dest_r = dest.resolve()

    def safe(name: str) -> Path:                 # 압축 파일 밖으로 풀리는 경로 차단
        p = (dest / name).resolve()
        if dest_r not in p.parents and p != dest_r:
            raise LLMError("엔진 압축 파일의 경로가 올바르지 않습니다.")
        return p
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                safe(n)
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            for m in t.getmembers():
                safe(m.name)
            try:      # 'data' 필터: 링크·권한 등 위험한 항목을 막는다 (Python 3.12+, 보안 패치된 3.10/3.11)
                t.extractall(dest, filter="data")
            except TypeError:
                t.extractall(dest)


def install_engine(engine_dir: Path, on_progress: Progress = None) -> Path:
    """llama.cpp 최신 공식 빌드(CPU)를 받아 engine_dir에 푼다. llama-server 경로를 돌려준다."""
    if on_progress:
        on_progress({"status": "AI 엔진 정보 확인 중"})
    rel = _get_json(GH_RELEASE_API)
    asset = pick_engine_asset(rel if isinstance(rel, dict) else {})
    if not asset:
        raise LLMError("이 PC에 맞는 AI 엔진(llama.cpp) 파일을 찾지 못했습니다.")
    engine_dir = Path(engine_dir)
    with tempfile.TemporaryDirectory() as tmp:
        archive = download(asset["browser_download_url"], Path(tmp) / asset["name"], on_progress,
                           "AI 엔진 받는 중", int(asset.get("size") or 0))
        staging = Path(tmp) / "x"
        staging.mkdir()
        _extract(archive, staging)
        exe = "llama-server.exe" if sys.platform.startswith("win") else "llama-server"
        found = next(staging.rglob(exe), None)
        if not found:
            raise LLMError("받은 엔진 파일에 llama-server가 없습니다.")
        if engine_dir.exists():
            shutil.rmtree(engine_dir, ignore_errors=True)
        shutil.copytree(found.parent, engine_dir)
    server = engine_dir / exe
    if not sys.platform.startswith("win"):
        for p in engine_dir.iterdir():
            if p.is_file() and (p.name.startswith("llama-") or p.suffix in ("", ".so", ".dylib")):
                p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return server

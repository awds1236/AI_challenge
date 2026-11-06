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
GH_RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10"
GH_REPO_URL = "https://github.com/ggml-org/llama.cpp"
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
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:300]
        if "rate limit" in body.lower():
            raise LLMError("GitHub 조회 한도 초과 — 같은 인터넷 주소를 쓰는 PC가 많으면 생깁니다") from e
        raise LLMError(f"인터넷에서 정보를 받지 못했습니다 ({url.split('/')[2]}, {e.code})") from e
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
_GPU_ONLY = ("cuda", "cudart", "vulkan", "hip", "rocm", "radeon", "sycl", "opencl", "kompute", "musa",
             "openvino", "cann", "npu", "metal-")


def _platform() -> tuple[str, str]:
    plat = "win" if sys.platform.startswith("win") else "mac" if sys.platform == "darwin" else "linux"
    try:
        machine = os.uname().machine.lower() if hasattr(os, "uname") else (os.environ.get("PROCESSOR_ARCHITECTURE") or "").lower()
    except OSError:
        machine = ""
    return plat, "arm64" if machine in ("arm64", "aarch64") else "x64"


def engine_asset_score(name: str, plat: str, arch: str) -> int | None:
    """llama.cpp 배포 파일 이름이 이 PC용 CPU 빌드인지 점수로 판단 (아니면 None).
    파일 이름 규칙이 바뀌어도 찾을 수 있게 운영체제·CPU 종류·GPU 전용 여부로 고른다."""
    n = name.lower()
    if not (n.endswith(".zip") or n.endswith(".tar.gz")) or "bin" not in n:
        return None
    if plat == "win" and ("win" not in n or not n.endswith(".zip")):
        return None
    if plat == "mac" and not any(k in n for k in ("macos", "osx", "darwin")):
        return None
    if plat == "linux" and not any(k in n for k in ("ubuntu", "linux")):
        return None
    if any(k in n for k in _GPU_ONLY):
        return None
    is_arm = "arm64" in n or "aarch64" in n
    if (arch == "arm64") != is_arm and not (plat == "mac" and not is_arm and "x64" not in n):
        return None
    score = 1
    if "cpu" in n:
        score += 4
    if "avx2" in n:
        score += 1
    if n.endswith(".zip"):
        score += 1
    return score


def pick_engine_asset(release: dict, plat: str | None = None, arch: str | None = None) -> dict | None:
    if plat is None or arch is None:
        plat, arch = _platform()
    scored = []
    for a in release.get("assets") or []:
        sc = engine_asset_score(a.get("name", ""), plat, arch)
        if sc is not None:
            scored.append((sc, a))
    scored.sort(key=lambda x: -x[0])
    return scored[0][1] if scored else None


def _page_assets(tag: str) -> list[str]:
    """배포 페이지에서 한 버전의 파일 이름 목록 (API 조회 한도와 무관)."""
    req = urllib.request.Request(f"{GH_REPO_URL}/releases/expanded_assets/{tag}", headers=UA)
    with _opener().open(req, timeout=30) as r:
        html = r.read().decode("utf-8", "ignore")
    return sorted(set(re.findall(rf"/releases/download/{re.escape(tag)}/([^\"'<>\s]+)", html)))


def _releases_from_page(limit: int = 6) -> list[dict]:
    """API 조회 한도(시간당 60회)에 걸렸을 때: 공개 배포 페이지에서 최근 버전들과 파일 목록을 읽는다."""
    tags: list[str] = []
    try:
        req = urllib.request.Request(f"{GH_REPO_URL}/releases", headers=UA)
        with _opener().open(req, timeout=30) as r:
            html = r.read().decode("utf-8", "ignore")
        for t in re.findall(r"/releases/tag/([^/?#\"'<>\s]+)", html):
            if t not in tags:
                tags.append(t)
    except (urllib.error.URLError, OSError):
        pass
    if not tags:
        req = urllib.request.Request(f"{GH_REPO_URL}/releases/latest", headers=UA)
        with _opener().open(req, timeout=30) as r:
            m = re.search(r"/releases/tag/([^/?#]+)", r.geturl())
        if not m:
            raise LLMError("최신 엔진 버전을 확인하지 못했습니다.")
        tags = [m.group(1)]
    out = []
    for tag in tags[:limit]:
        try:
            names = _page_assets(tag)
        except (urllib.error.URLError, OSError):
            names = []
        if not names and tag == tags[0]:     # 목록도 못 읽으면 흔한 이름을 직접 시도
            names = [f"llama-{tag}-bin-win-cpu-x64.zip", f"llama-{tag}-bin-win-x64.zip",
                     f"llama-{tag}-bin-ubuntu-x64.zip", f"llama-{tag}-bin-ubuntu-x64.tar.gz",
                     f"llama-{tag}-bin-macos-arm64.zip", f"llama-{tag}-bin-macos-arm64.tar.gz",
                     f"llama-{tag}-bin-macos-x64.zip"]
        out.append({"tag_name": tag, "assets": [
            {"name": n, "size": 0, "browser_download_url": f"{GH_REPO_URL}/releases/download/{tag}/{n}"}
            for n in names]})
    return out


def find_engine_candidates() -> tuple[list[dict], str, list[str]]:
    """최근 버전부터 이 PC용 엔진 파일을 찾는다. (후보, 실패 이유, 최신 버전에서 본 파일 이름)
    llama.cpp는 하루에도 여러 번 새 버전을 내고 파일은 몇십 분에 걸쳐 올라오므로, 최신 버전에 아직
    Windows 파일이 없으면 그 전 버전을 쓴다."""
    plat, arch = _platform()
    why, seen = "", []

    def search(releases: list) -> list[dict]:
        for rel in releases:
            if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
                continue
            if not seen:
                seen.extend(a.get("name", "") for a in rel.get("assets") or [])
            scored = sorted(((engine_asset_score(a.get("name", ""), plat, arch), a) for a in rel.get("assets") or []),
                            key=lambda x: -(x[0] or 0))
            found = [a for sc, a in scored if sc is not None]
            if found:
                return found
        return []
    try:
        data = _get_json(GH_RELEASES_API)
        if isinstance(data, list):
            cands = search(data)
            if cands:
                return cands, "", seen
            why = "최근 버전에 이 PC용 파일이 없음" if data else "배포 목록이 비어 있음"
        else:
            why = (data.get("message") if isinstance(data, dict) else "") or "배포 목록을 읽지 못함"
    except LLMError as e:
        why = str(e)
    try:                                       # API 한도 초과·차단 → 배포 페이지에서 직접 찾기
        cands = search(_releases_from_page())
        if cands:
            return cands, "", seen
    except (LLMError, urllib.error.URLError, OSError) as e:
        why = why or str(e)
    return [], why, seen


MANUAL_ENGINE = ("직접 넣는 방법: {repo}/releases 에서 이름에 'bin-win-cpu-x64'가 들어간 zip 파일을 받아 "
                 "압축을 풀고, 안의 파일을 프로그램 폴더의 engine 폴더({dir})에 넣은 뒤 다시 확인을 누르세요.")


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
    engine_dir = Path(engine_dir)
    manual = MANUAL_ENGINE.format(repo=GH_REPO_URL, dir=engine_dir)
    if on_progress:
        on_progress({"status": "AI 엔진 정보 확인 중"})
    candidates, why, seen = find_engine_candidates()
    if not candidates:
        shown = [n for n in seen if "win" in n.lower()][:6] or seen[:6]
        detail = "; ".join(x for x in (why, f"찾은 파일: {', '.join(shown)}" if shown else "") if x)
        raise LLMError(f"이 PC에 맞는 AI 엔진(llama.cpp) 파일을 찾지 못했습니다{f' ({detail})' if detail else ''}. {manual}")
    exe = "llama-server.exe" if sys.platform.startswith("win") else "llama-server"
    last = ""
    with tempfile.TemporaryDirectory() as tmp:
        for asset in candidates[:4]:
            try:
                archive = download(asset["browser_download_url"], Path(tmp) / asset["name"], on_progress,
                                   "AI 엔진 받는 중", int(asset.get("size") or 0))
            except LLMError as e:
                last = str(e)
                continue
            staging = Path(tmp) / "x"
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir()
            _extract(archive, staging)
            found = next(staging.rglob(exe), None)
            if not found:
                last = f"{asset['name']}에 llama-server가 없습니다"
                continue
            if engine_dir.exists():
                shutil.rmtree(engine_dir, ignore_errors=True)
            shutil.copytree(found.parent, engine_dir)
            break
        else:
            raise LLMError(f"AI 엔진을 받지 못했습니다 ({last}). {manual}")
    server = engine_dir / exe
    if not sys.platform.startswith("win"):
        for p in engine_dir.iterdir():
            if p.is_file() and (p.name.startswith("llama-") or p.suffix in ("", ".so", ".dylib")):
                p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return server

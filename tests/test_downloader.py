"""[받기] 자동 다운로드 테스트 — 가짜 GitHub/Hugging Face 서버 사용."""
import hashlib
import io
import json
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from seomu import downloader
from seomu.llm import LLMError

HERE = Path(__file__).parent
MODEL = b"GGUF" + bytes(range(256)) * 4000          # 약 1MB 가짜 모델


def _engine_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("build/bin/llama-server", f"#!/bin/sh\nexec {sys.executable} {HERE / 'fake_llama_server.py'} \"$@\"\n")
        z.writestr("build/bin/libllama.so", b"lib")
    return buf.getvalue()


def _asset_name():
    return {"win32": "llama-b1-bin-win-cpu-x64.zip", "darwin": "llama-b1-bin-macos-arm64.zip"}.get(
        sys.platform, "llama-b1-bin-ubuntu-x64.zip")


class Fake(BaseHTTPRequestHandler):
    hits: list = []
    corrupt = False
    cut = 0           # 0이 아니면 그 바이트에서 연결을 끊는다 (이어 받기 시험)
    api_limited = False   # GitHub API 조회 한도 초과 흉내
    page_list = True      # 배포 페이지 파일 목록 제공 여부

    def log_message(self, *a):
        pass

    def _send(self, body: bytes, code=200, ctype="application/octet-stream", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        Fake.hits.append((self.path, self.headers.get("Range")))
        port = self.server.server_address[1]
        if self.path == "/gh/releases":
            if Fake.api_limited:
                return self._send(json.dumps({"message": "API rate limit exceeded for 1.2.3.4."}).encode(), 403,
                                  ctype="application/json")
            z = _engine_zip()
            return self._send(json.dumps([
                # 최신 버전: 파일이 아직 다 올라오지 않음 (CPU 빌드 없음)
                {"tag_name": "b2", "assets": [{"name": "llama-b2-bin-win-cuda-12.4-x64.zip", "size": 1,
                                               "browser_download_url": "x"}]},
                {"tag_name": "b1", "assets": [
                    {"name": "llama-b1-bin-win-cuda-12.4-x64.zip", "size": 1, "browser_download_url": "x"},
                    {"name": _asset_name(), "size": len(z), "browser_download_url": f"http://127.0.0.1:{port}/engine.zip"}]},
            ]).encode(), ctype="application/json")
        if self.path == "/repo/releases":
            if not Fake.page_list:
                return self._send(b"no", 404)
            return self._send(b'<a href="/ggml-org/llama.cpp/releases/tag/b2">b2</a>'
                              b'<a href="/ggml-org/llama.cpp/releases/tag/b1">b1</a>', ctype="text/html")
        if self.path == "/repo/releases/latest":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{port}/repo/releases/tag/b1")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/repo/releases/tag/"):
            return self._send(b"<html>release</html>", ctype="text/html")
        if self.path == "/repo/releases/expanded_assets/b2":
            return self._send(b'<a href="/ggml-org/llama.cpp/releases/download/b2/llama-b2-bin-win-cuda-12.4-x64.zip">x</a>',
                              ctype="text/html")
        if self.path == "/repo/releases/expanded_assets/b1":
            if not Fake.page_list:
                return self._send(b"no", 404)
            links = "".join(f'<a href="/ggml-org/llama.cpp/releases/download/b1/{n}">{n}</a>' for n in
                            ["llama-b1-bin-win-cuda-12.4-x64.zip", "llama-b1-bin-win-vulkan-x64.zip", _asset_name()])
            return self._send(links.encode(), ctype="text/html")
        if self.path == "/repo/releases/download/b1/" + _asset_name():
            return self._send(_engine_zip())
        if self.path == "/engine.zip":
            return self._send(_engine_zip())
        if self.path.startswith("/api/models/"):
            return self._send(json.dumps({"siblings": [{"rfilename": "m.gguf", "size": len(MODEL),
                                                        "lfs": {"sha256": hashlib.sha256(MODEL).hexdigest()}}]}).encode(),
                              ctype="application/json")
        if self.path.endswith("/resolve/main/m.gguf"):
            data = MODEL[:-1] + b"X" if Fake.corrupt else MODEL
            rng = self.headers.get("Range")
            start = int(rng.split("=")[1].rstrip("-")) if rng else 0
            body = data[start:]
            if Fake.cut and not rng:                       # 첫 요청은 중간에 끊는다
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body[:Fake.cut])
                self.wfile.flush()
                self.connection.close()
                return
            return self._send(body, 206 if rng else 200,
                              extra={"Content-Range": f"bytes {start}-{len(data) - 1}/{len(data)}"} if rng else None)
        self._send(b"no", 404)


@pytest.fixture()
def server(monkeypatch):
    Fake.hits, Fake.corrupt, Fake.cut, Fake.api_limited, Fake.page_list = [], False, 0, False, True
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setattr(downloader, "HF_BASE", base)
    monkeypatch.setattr(downloader, "GH_RELEASES_API", base + "/gh/releases")
    monkeypatch.setattr(downloader, "GH_REPO_URL", base + "/repo")
    yield base
    srv.shutdown()


SPEC = {"repo": "google/x", "file": "m.gguf", "as": "gemma-4-E2B-it-QAT-Q4_0"}


def test_download_model_checks_and_progress(server, tmp_path):
    seen = []
    p = downloader.download_model(SPEC, tmp_path, seen.append)
    assert p.name == "gemma-4-E2B-it-QAT-Q4_0.gguf" and p.read_bytes() == MODEL
    assert seen[-1]["status"] == "파일 확인 중" and any(x["status"] == "AI 모델 받는 중" for x in seen)
    assert not list(tmp_path.glob("*.part"))
    n = len(Fake.hits)
    downloader.download_model(SPEC, tmp_path)                 # 이미 있으면 다시 받지 않는다
    assert len(Fake.hits) == n


def test_download_resumes_after_cut(server, tmp_path):
    Fake.cut = 300_000
    with pytest.raises(LLMError, match="이어서"):
        downloader.download_model(SPEC, tmp_path)
    part = tmp_path / "gemma-4-E2B-it-QAT-Q4_0.gguf.part"
    assert part.exists() and part.stat().st_size == 300_000
    p = downloader.download_model(SPEC, tmp_path)
    assert p.read_bytes() == MODEL
    assert Fake.hits[-1][1] == "bytes=300000-"                # 받은 곳부터 이어서 요청


def test_corrupt_download_is_rejected(server, tmp_path):
    Fake.corrupt = True
    with pytest.raises(LLMError, match="손상"):
        downloader.download_model(SPEC, tmp_path)
    assert not list(tmp_path.glob("*"))


@pytest.mark.skipif(sys.platform.startswith("win"), reason="가짜 엔진은 POSIX 셸 스크립트")
def test_install_engine(server, tmp_path):
    exe = downloader.install_engine(tmp_path / "engine")
    assert exe == tmp_path / "engine" / "llama-server" and exe.exists()
    assert exe.stat().st_mode & 0o100 and (tmp_path / "engine" / "libllama.so").exists()


def test_extract_blocks_path_traversal(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil.txt", "x")
    a = tmp_path / "a.zip"
    a.write_bytes(buf.getvalue())
    (tmp_path / "d").mkdir()
    with pytest.raises(LLMError):
        downloader._extract(a, tmp_path / "d")
    assert not (tmp_path / "evil.txt").exists()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="가짜 엔진은 POSIX 셸 스크립트")
def test_api_download_without_ollama(server, tmp_path, monkeypatch):
    """Ollama가 꺼진 PC에서 [받기] → 엔진+모델을 받고 내장 엔진으로 바로 동작."""
    from seomu import engine as engine_mod
    from seomu import models as catalog
    from seomu.api import Api
    monkeypatch.setattr(engine_mod, "app_dir", lambda: tmp_path / "app")
    entry = catalog.find("gemma4:e2b-it-qat")
    monkeypatch.setitem(entry, "dl", {**entry["dl"], "repo": "google/x", "file": "m.gguf"})
    api = Api(tmp_path / "home")
    api.save_settings({"engine": "ollama", "ollama_url": "http://127.0.0.1:9"})
    c = api.model_catalog()
    assert not c["engine_ok"] and next(m for m in c["models"] if m["id"] == "gemma4:e2b-it-qat")["can_download"]
    job = api.download_model("gemma4:e2b-it-qat")
    for _ in range(200):
        st = api.job_status(job["job_id"])
        if st["status"] != "running":
            break
        time.sleep(0.05)
    assert st["status"] == "done", st
    assert (tmp_path / "app" / "engine" / "llama-server").exists()
    assert (tmp_path / "app" / "models" / "gemma-4-E2B-it-QAT-Q4_0.gguf").exists()
    s = api.get_settings()
    assert s["engine"] == "auto" and s["chat_model"] == "gemma-4-E2B-it-QAT-Q4_0"
    cat = st["result"]
    assert cat["engine"]["kind"] == "builtin" and cat["engine_ok"]
    m = next(m for m in cat["models"] if m["id"] == "gemma4:e2b-it-qat")
    assert m["installed"] and m["active"]
    assert api.llm_status()["ok"] and api.llm_status()["engine"] == "builtin"
    with pytest.raises(ValueError):
        api.download_model("없는-모델")
    api.shutdown()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="가짜 엔진은 POSIX 셸 스크립트")
@pytest.mark.parametrize("page_list", [True, False])
def test_install_engine_when_api_rate_limited(server, tmp_path, page_list):
    """GitHub API 한도 초과(기관망 공용 주소에서 흔함) → 배포 페이지 목록, 그것도 없으면 흔한 이름으로 받는다."""
    Fake.api_limited, Fake.page_list = True, page_list
    exe = downloader.install_engine(tmp_path / "engine")
    assert exe.exists()
    paths = [h[0] for h in Fake.hits]
    assert "/repo/releases/download/b1/" + _asset_name() in paths
    assert not any("cuda" in p or "vulkan" in p for p in paths)          # GPU 전용 빌드는 받지 않는다


def test_install_engine_failure_explains_manual_steps(server, tmp_path, monkeypatch):
    Fake.api_limited = True
    monkeypatch.setattr(downloader, "GH_REPO_URL", "http://127.0.0.1:9/repo")       # 배포 페이지도 접속 불가
    with pytest.raises(LLMError) as e:
        downloader.install_engine(tmp_path / "engine")
    msg = str(e.value)
    assert "조회 한도 초과" in msg and "bin-win-cpu-x64" in msg and str(tmp_path / "engine") in msg


def test_engine_asset_choice_by_platform():
    rel = {"assets": [{"name": n} for n in [
        "cudart-llama-bin-win-cuda-12.4-x64.zip", "llama-b9-bin-win-vulkan-x64.zip", "llama-b9-bin-win-cpu-arm64.zip",
        "llama-b9-bin-win-x64.zip", "llama-b9-bin-win-cpu-x64.zip", "llama-b9-bin-ubuntu-x64.zip",
        "llama-b9-bin-ubuntu-vulkan-x64.zip", "llama-b9-bin-macos-arm64.zip", "llama-b9-bin-macos-x64.zip"]]}
    assert downloader.pick_engine_asset(rel, "win", "x64")["name"] == "llama-b9-bin-win-cpu-x64.zip"
    assert downloader.pick_engine_asset(rel, "win", "arm64")["name"] == "llama-b9-bin-win-cpu-arm64.zip"
    assert downloader.pick_engine_asset(rel, "linux", "x64")["name"] == "llama-b9-bin-ubuntu-x64.zip"
    assert downloader.pick_engine_asset(rel, "mac", "arm64")["name"] == "llama-b9-bin-macos-arm64.zip"
    # 이름 규칙이 바뀌어 cpu 표시가 없어도 Windows x64 빌드를 찾는다
    rel2 = {"assets": [{"name": "llama-b9-bin-win-cuda-x64.zip"}, {"name": "llama-b9-bin-win-x64.zip"}]}
    assert downloader.pick_engine_asset(rel2, "win", "x64")["name"] == "llama-b9-bin-win-x64.zip"
    assert downloader.pick_engine_asset({"message": "rate limit"}, "win", "x64") is None


@pytest.mark.skipif(sys.platform.startswith("win"), reason="가짜 엔진은 POSIX 셸 스크립트")
def test_install_engine_skips_release_still_uploading(server, tmp_path):
    """최신 버전에 이 PC용 파일이 아직 안 올라왔으면 바로 전 버전을 받는다."""
    exe = downloader.install_engine(tmp_path / "engine")
    assert exe.exists() and "/engine.zip" in [h[0] for h in Fake.hits]


def test_engine_not_found_message_lists_seen_files(server, tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "engine_asset_score", lambda n, p, a: None)   # 어떤 이름도 안 맞는 경우
    monkeypatch.setattr(downloader, "GH_REPO_URL", "http://127.0.0.1:9/repo")
    with pytest.raises(LLMError) as e:
        downloader.install_engine(tmp_path / "engine")
    assert "찾은 파일: llama-b2-bin-win-cuda-12.4-x64.zip" in str(e.value)

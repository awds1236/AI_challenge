"""내장 엔진(llama-server) 관리·클라이언트 테스트 — 가짜 서버 실행 파일 사용."""
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from fake_engine import make_server
from seomu.engine import LocalClient, LocalEngine, add_model_file, ollama_model_blob

HERE = Path(__file__).parent


@pytest.fixture()
def engine(tmp_path):
    make_server(tmp_path / "engine")          # Windows: 가짜 llama-server.exe / POSIX: 셸 스크립트
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "gemma-4-E2B-it-QAT-Q4_0.gguf").write_bytes(b"GGUF")
    (tmp_path / "models" / "embeddinggemma-300m-Q8_0.gguf").write_bytes(b"GGUF")
    (tmp_path / "models" / "mmproj-gemma.gguf").write_bytes(b"GGUF")
    e = LocalEngine(tmp_path)
    yield e
    e.stop()


def test_launch_blocked_by_windows_policy_message():
    """스마트 앱 컨트롤·보안 정책이 서명 없는 엔진을 막으면 보안 설정을 끄라고 하지 않고 대안을 안내한다."""
    from seomu.engine import launch_error_message
    e = OSError(22, "blocked")
    e.winerror = 4551
    msg = launch_error_message(e)
    assert "스마트 앱 컨트롤" in msg and "Ollama" in msg and "끄" not in msg
    assert "실행하지 못했습니다" in launch_error_message(OSError(2, "없음"))


def test_engine_chat_stream_embed(engine):
    c = LocalClient(engine, ctx=4096)
    st = c.status()
    assert st["ok"] and set(st["models"]) == {"gemma-4-E2B-it-QAT-Q4_0", "embeddinggemma-300m-Q8_0"}
    m = c.pick_chat_model("")
    assert m == "gemma-4-E2B-it-QAT-Q4_0" and c.pick_embed_model("") == "embeddinggemma-300m-Q8_0"
    assert c.chat([{"role": "user", "content": "안녕"}], m) == "모델:gemma-4-E2B-it-QAT-Q4_0.gguf"
    toks = []
    assert c.chat([{"role": "user", "content": "x"}], m, on_token=toks.append) == "내장 엔진 답변"
    assert toks == ["내장 ", "엔진 ", "답변"]
    out = json.loads(c.chat([{"role": "user", "content": "x"}], m, fmt={"type": "object"}))
    assert out["summary"] == "내장 엔진 요약"
    assert c.embed(["가나", "가나다"], c.pick_embed_model("")) == [[2.0, 1.0], [3.0, 1.0]]
    assert set(engine.running()) == {"chat", "embed"}
    engine.stop()
    assert engine.running() == {}


def test_api_uses_builtin_engine(engine, tmp_path, monkeypatch):
    monkeypatch.setenv("SEOMU_DOWNLOADS", str(tmp_path / "dl"))
    from seomu.api import Api
    api = Api(tmp_path)                       # home = tmp_path → engine/·models/ 사용
    try:
        assert api.engine_info()["kind"] == "builtin"
        st = api.llm_status()
        assert st["ok"] and st["engine"] == "builtin" and st["chat_model"] == "gemma-4-E2B-it-QAT-Q4_0"
        cat = api.model_catalog()
        card = next(m for m in cat["models"] if m["id"] == "gemma4:e2b-it-qat")
        assert card["installed"] and card["installed_id"] == "gemma-4-E2B-it-QAT-Q4_0" and card["active"]
        emb = next(m for m in cat["models"] if m["id"] == "embeddinggemma")
        assert emb["installed"] and emb["active"]
        api.set_engine("ollama")
        assert api.engine_info()["kind"] == "ollama"
    finally:
        api.shutdown()


def test_add_model_file_and_ollama_blob(tmp_path, monkeypatch):
    e = LocalEngine(tmp_path)
    monkeypatch.setattr(e, "writable_model_dir", lambda: tmp_path / "models")
    (tmp_path / "models").mkdir()
    src = tmp_path / "kanana-2-3b-instruct-Q4_K_M.gguf"
    src.write_bytes(b"G" * 1000)
    dest = add_model_file(e, str(src))
    assert dest.name == "kanana-2-3b-instruct-Q4_K_M.gguf" and dest.stat().st_size == 1000
    # Ollama 저장소 구조에서 GGUF 위치 찾기
    root = tmp_path / "ollama"
    (root / "manifests/registry.ollama.ai/library/gemma4").mkdir(parents=True)
    (root / "blobs").mkdir()
    (root / "blobs" / "sha256-abc").write_bytes(b"GGUF")
    (root / "manifests/registry.ollama.ai/library/gemma4/e2b-it-qat").write_text(json.dumps(
        {"layers": [{"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:abc"}]}))
    monkeypatch.setenv("OLLAMA_MODELS", str(root))
    assert ollama_model_blob("gemma4:e2b-it-qat") == root / "blobs" / "sha256-abc"
    assert ollama_model_blob("gemma4:e4b") is None

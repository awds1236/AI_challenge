"""모델 파일은 있는데 실행 엔진(llama-server)만 없을 때: '모델 없음'으로 잘못 알리지 않고, 엔진을 찾거나 넣을 수 있어야 한다."""
import shutil
import zipfile
from pathlib import Path

import pytest

from fake_engine import EXE_NAME, make_server
from seomu import downloader
from seomu.engine import ENGINE_MISSING, LocalClient, LocalEngine


def _models(home: Path) -> None:
    (home / "models").mkdir(parents=True, exist_ok=True)
    (home / "models" / "gemma-4-E2B-it-QAT-Q4_0.gguf").write_bytes(b"GGUF")


def test_models_without_engine_reports_engine_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)     # 이 PC PATH의 진짜 엔진은 쓰지 않는다
    _models(tmp_path)
    e = LocalEngine(tmp_path)
    assert e.missing_engine()
    st = LocalClient(e).status()
    assert not st["ok"] and st["need_engine"] and st["error"] == ENGINE_MISSING
    assert "모델 파일은 있지만" in st["error"] and st["models"] == ["gemma-4-E2B-it-QAT-Q4_0"]


@pytest.mark.parametrize("rel", ["engine/llama-b6000-bin-win-cpu-x64/build/bin",   # 압축이 여러 단계로 풀린 경우
                                 "llama-b6000-bin-win-cpu-x64"])                    # 프로그램 폴더에 그대로 푼 경우
def test_engine_found_in_nested_folders(tmp_path, monkeypatch, rel):
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    _models(tmp_path)
    make_server(tmp_path / rel)
    e = LocalEngine(tmp_path)
    assert Path(e.server_path()) == tmp_path / rel / EXE_NAME
    assert not e.missing_engine()


def test_install_engine_from_zip_and_exe(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    _models(tmp_path)
    src = tmp_path / "usb" / "llama-b6000-bin-win-cpu-x64"
    make_server(src)
    (src / "ggml.dll").write_bytes(b"dll")
    z = tmp_path / "usb" / "llama.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in src.iterdir():
            zf.write(f, f"llama-b6000-bin-win-cpu-x64/{f.name}")
    e = LocalEngine(tmp_path)
    assert e.missing_engine()
    server = downloader.install_engine_from(z, e.writable_engine_dir())
    assert server.is_file() and (server.parent / "ggml.dll").is_file()     # 함께 쓰는 DLL도 같이 넣는다
    e.forget_server()
    assert not e.missing_engine()
    # 실행 파일을 직접 지정해도 된다
    shutil.rmtree(e.writable_engine_dir())
    e.forget_server()
    downloader.install_engine_from(src / EXE_NAME, e.writable_engine_dir())
    e.forget_server()
    assert e.server_path()
    with pytest.raises(Exception):
        downloader.install_engine_from(tmp_path / "models" / "gemma-4-E2B-it-QAT-Q4_0.gguf", e.writable_engine_dir())


def test_api_status_and_import_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setenv("SEOMU_DOWNLOADS", str(tmp_path / "dl"))
    _models(tmp_path)
    from seomu.api import Api
    api = Api(tmp_path)
    try:
        api.save_settings({"engine": "builtin"})
        st = api.llm_status()
        assert not st["ok"] and st["need_engine"] and "AI 실행 엔진" in st["error"]
        info = api.engine_info()
        assert info["need_engine"] and info["engine_dir"]
        src = tmp_path / "usb"
        make_server(src)
        job = api.import_engine(str(src / EXE_NAME))
        import time
        for _ in range(100):
            j = api.job_status(job["job_id"])
            if j["status"] != "running":
                break
            time.sleep(0.05)
        assert j["status"] == "done", j
        st = api.llm_status()
        assert not st["need_engine"] and st["ok"] and st["chat_model"] == "gemma-4-E2B-it-QAT-Q4_0"
    finally:
        api.shutdown()

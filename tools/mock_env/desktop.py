"""데스크톱 전자문서 뷰어 모의 프로그램 실행기 (desktop_viewer.ps1).

콘솔 창 없이(CREATE_NO_WINDOW) 실행하고, 뷰어 창은 화면 밖에 활성화 없이 뜬다.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

SCRIPT = Path(__file__).with_name("desktop_viewer.ps1")


def _script_with_bom() -> Path:
    """PowerShell 5.1은 BOM이 없으면 한글이 든 스크립트를 CP949로 읽는다 → BOM 붙인 사본으로 실행."""
    out = Path(tempfile.gettempdir()) / "seomu_mock_viewer.ps1"
    out.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8-sig")
    return out


def launch(mode: str, title: str, body: str, attach: list[Path], workdir: Path, save_dir: Path,
           lifetime: float = 120) -> tuple[subprocess.Popen, int]:
    """뷰어를 띄우고 (프로세스, 창 핸들)을 돌려준다."""
    workdir.mkdir(parents=True, exist_ok=True)
    save_dir.mkdir(parents=True, exist_ok=True)
    body_file = workdir / f"{mode}_body.txt"
    body_file.write_text(body, encoding="utf-8")
    ready = workdir / f"{mode}_ready.txt"
    ready.unlink(missing_ok=True)
    cfg = workdir / f"{mode}.json"
    cfg.write_text(json.dumps({"mode": mode, "title": title, "body_file": str(body_file),
                               "attach": [a.name for a in attach], "attach_dir": str(attach[0].parent) if attach else str(workdir),
                               "save_dir": str(save_dir), "ready_file": str(ready),
                               "lifetime_ms": int(lifetime * 1000)}, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.Popen(["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
                             "-File", str(_script_with_bom()), str(cfg)],
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for _ in range(150):
        time.sleep(0.2)
        if ready.exists() and ready.read_text(encoding="ascii", errors="ignore").strip():
            time.sleep(0.8)                         # 창이 실제로 그려질 때까지
            return proc, int(ready.read_text(encoding="ascii").strip())
        if proc.poll() is not None:
            raise RuntimeError("모의 뷰어 실행 실패: " + proc.stderr.read().decode("utf-8", "ignore")[-500:])
    proc.kill()
    raise RuntimeError("모의 뷰어가 뜨지 않음")


def close(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except Exception:
        pass

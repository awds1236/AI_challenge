"""서무비서 AI 실행 파일(exe) 만들기 — Windows 전용.

    .venv\\Scripts\\python.exe -m pip install pyinstaller
    .venv\\Scripts\\python.exe tools\\build_exe.py            # dist\\SeomuAI\\SeomuAI.exe + 배포용 zip

결과
  dist/SeomuAI/SeomuAI.exe       더블클릭으로 실행 (Python 설치 불필요)
  dist/SeomuAI/engine/           내장 AI 엔진 (프로젝트의 engine 폴더가 있으면 함께 넣는다)
  dist/SeomuAI/models/           AI 모델(.gguf)을 넣는 곳 — 앱의 [받기]로 받거나 직접 복사
  dist/SeomuAI-windows-x64.zip   배포용 압축 파일 (모델 파일은 크기 때문에 넣지 않는다)

폴더형으로 만드는 이유: 한 파일형(onefile)은 실행할 때마다 수백 MB를 임시 폴더에 풀어 느리고
백신 프로그램이 의심하는 경우가 많다. 압축을 풀고 SeomuAI.exe를 누르면 된다.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
NAME = "SeomuAI"

# 엔진 폴더에서 실제로 쓰는 것만 넣는다 (llama-server와 그 DLL). 나머지 도구 exe는 필요 없다
ENGINE_KEEP = ("llama-server.exe", "llama-server-impl.dll", "LICENSE")


def run(cmd: list[str]) -> None:
    print(">", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def build(with_playwright: bool) -> Path:
    from seomu import __version__
    sep = ";"
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", NAME,
            "--distpath", str(DIST), "--workpath", str(BUILD), "--specpath", str(BUILD),
            "--add-data", f"{ROOT / 'seomu' / 'ui'}{sep}seomu/ui",
            "--add-data", f"{ROOT / 'seomu' / 'assets'}{sep}seomu/assets",
            "--collect-all", "uiautomation",          # UI Automation DLL
            "--collect-all", "webview",               # pywebview(WebView2) DLL·JS
            "--hidden-import", "clr", "--hidden-import", "webview.platforms.winforms",
            "--hidden-import", "webview.platforms.edgechromium",
            "--collect-submodules", "seomu"]
    if with_playwright:
        args += ["--collect-all", "playwright"]       # 브라우저 연동 (Edge/Chrome을 그대로 쓴다)
    else:
        args += ["--exclude-module", "playwright"]
    icon = ROOT / "seomu" / "assets" / "app.ico"
    if icon.exists():
        args += ["--icon", str(icon)]
    args.append(str(ROOT / "run.py"))
    run(args)
    out = DIST / NAME
    (out / "models").mkdir(exist_ok=True)
    (out / "models" / "모델 파일(.gguf)을 여기에 넣으세요.txt").write_text(
        "AI 모델 파일(.gguf)을 이 폴더에 넣으면 자동으로 인식합니다.\n"
        "인터넷이 되는 PC라면 프로그램의 설정 → AI 모델에서 [받기]를 누르면 알아서 받습니다.\n"
        "기본 모델: gemma-4-E2B-it-QAT-Q4_0.gguf (약 3.3GB)\n", encoding="utf-8")
    engine = ROOT / "engine"
    if (engine / "llama-server.exe").exists():
        dest = out / "engine"
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir()
        for f in engine.iterdir():
            if not f.is_file():
                continue
            # llama-server.exe와 그것이 불러 쓰는 DLL(ggml·llama·mtmd·libomp 등), 라이선스만.
            # 다른 도구 전용 '-impl.dll'(llama-cli-impl 등)과 도구 exe는 뺀다
            name = f.name
            keep = (name.startswith(ENGINE_KEEP)
                    or (f.suffix.lower() == ".dll" and not name.endswith("-impl.dll")))
            if keep:
                shutil.copy2(f, dest / name)
        print(f"내장 AI 엔진을 함께 넣었습니다: {dest}")
    else:
        print("※ engine 폴더가 없어 내장 AI 엔진은 넣지 않았습니다 (앱의 [받기]가 엔진도 함께 받습니다).")
    (out / "사용 안내.txt").write_text(
        f"서무비서 AI {__version__}\n\n"
        "1. SeomuAI.exe 를 더블클릭하면 실행됩니다 (Python 설치 불필요).\n"
        "2. 처음 실행하면 설정 → AI 모델에서 [받기]를 눌러 AI 모델(약 3.3GB)을 받으세요.\n"
        "   인터넷이 안 되는 PC는 models 폴더에 .gguf 모델 파일을 직접 넣으면 됩니다.\n"
        "3. 데이터(공문 목록·설정)는 %LOCALAPPDATA%\\SeomuAI, 수집한 공문은 다운로드\\서무비서 폴더에 저장됩니다.\n\n"
        "Windows에서 '알 수 없는 게시자' 경고가 뜨면 [추가 정보] → [실행]을 누르세요.\n", encoding="utf-8")
    return out


def make_zip(folder: Path) -> Path:
    z = DIST / f"{NAME}-windows-x64.zip"
    z.unlink(missing_ok=True)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(folder.rglob("*")):
            if f.is_file() and f.suffix.lower() != ".gguf":     # 모델 파일은 너무 커서 넣지 않는다
                zf.write(f, Path(folder.name) / f.relative_to(folder))
    print(f"배포용 압축 파일: {z} ({z.stat().st_size / 1e6:.0f}MB)")
    return z


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-playwright", action="store_true", help="브라우저 연동을 빼고 작게 만든다")
    ap.add_argument("--no-zip", action="store_true")
    a = ap.parse_args()
    if not sys.platform.startswith("win"):
        print("Windows에서만 만들 수 있습니다.")
        return 1
    sys.path.insert(0, str(ROOT))
    out = build(not a.no_playwright)
    if not a.no_zip:
        make_zip(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

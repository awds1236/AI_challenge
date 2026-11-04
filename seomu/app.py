"""서무비서 AI 실행 진입점.

화면은 아래 순서로 '프로그램 창'을 띄운다 (주소창·탭 없는 독립 창).
1) pywebview (Edge WebView2 내장 창)
2) Edge / Chrome 앱 모드 (--app) : 별도 프로필로 띄워 창을 닫으면 프로그램도 종료
3) 위 둘 다 불가하면 기본 브라우저 (--browser 로 강제 가능)
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from . import APP_NAME
from .api import Api
from .server import start_server


def find_app_browser() -> str:
    """앱 모드로 띄울 수 있는 Chromium 계열 브라우저 경로."""
    cands: list[str] = []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"),
                     os.environ.get("LOCALAPPDATA")):
            if not base:
                continue
            cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                      os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                      os.path.join(base, "Naver", "Naver Whale", "Application", "whale.exe")]
    elif sys.platform == "darwin":
        cands += ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    for name in ("msedge", "microsoft-edge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            cands.append(p)
    return next((c for c in cands if c and os.path.exists(c)), "")


def run_app_window(url: str, profile: Path) -> bool:
    """브라우저 앱 모드로 독립 창을 띄우고, 창이 닫힐 때까지 기다린다."""
    exe = find_app_browser()
    if not exe:
        return False
    profile.mkdir(parents=True, exist_ok=True)
    args = [exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1280,840",
            "--no-first-run", "--no-default-browser-check", "--disable-features=Translate",
            "--lang=ko-KR"]
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(args, creationflags=flags)
    except OSError:
        return False
    proc.wait()  # 전용 프로필이라 이 창만의 프로세스 → 창을 닫으면 종료
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="seomu", description=f"{APP_NAME} - 로컬 경량 AI 서무 보조 프로그램")
    ap.add_argument("--browser", action="store_true", help="프로그램 창 대신 기본 브라우저로 실행")
    ap.add_argument("--app-window", action="store_true", help="pywebview 대신 Edge/Chrome 앱 모드 창 사용")
    ap.add_argument("--port", type=int, default=0, help="내부 화면 서버 포트 (기본: 자동)")
    ap.add_argument("--no-open", action="store_true", help="창을 자동으로 열지 않음 (개발용)")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    api = Api()
    api.preload_model()          # 답변 모델을 미리 메모리에 올려 첫 분석·질문을 빠르게
    httpd, url = start_server(api, args.port)

    try:
        if args.no_open:
            print(f"{APP_NAME} 실행 중: {url}  (종료: Ctrl+C)")
            while True:
                time.sleep(1)
        opened = False
        if not args.browser and not args.app_window:
            try:
                import webview  # type: ignore
                window = webview.create_window(APP_NAME, url, width=1280, height=820,
                                               min_size=(980, 640), background_color="#F5F5F7",
                                               text_select=True)
                api._window = window
                webview.start(debug=args.debug, private_mode=False)
                opened = True
            except Exception as e:  # 설치 안 됨 / WebView2 문제 등 → 앱 모드로
                print(f"내장 창을 열 수 없어 앱 모드 창으로 실행합니다: {e}")
        if not opened and not args.browser:
            opened = run_app_window(url, api._cfg.home / "app_window")
        if not opened:
            print(f"{APP_NAME} 실행 중: {url}  (종료: Ctrl+C)")
            webbrowser.open(url)
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        api.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

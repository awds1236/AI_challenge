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


def wait_for_window(proc, last_seen, started: float, first_wait: float = 90, idle: float = 180,
                    tick: float = 1.0) -> None:
    """앱 창이 닫힐 때까지 기다린다.

    Edge/Chrome이 이미 실행 중이면(이전 창, 백그라운드 실행) 새로 띄운 프로세스는 기존 프로세스에 창을 넘기고
    바로 끝난다. 프로세스 종료만 보고 서버를 끄면 창은 남았는데 화면이 'Failed to fetch'가 된다.
    그래서 화면이 보내는 신호(heartbeat)가 끊길 때까지 기다린다. 최소화한 창은 브라우저가 타이머를
    1분에 한 번 정도로 늦추므로, 신호가 3분 동안 없을 때 닫힌 것으로 본다.
    """
    while True:
        time.sleep(tick)
        if proc.poll() is None:
            continue                                    # 창 프로세스가 살아 있음
        seen = last_seen()
        now = time.time()
        if seen:
            if now - seen < idle:
                continue                                # 다른 브라우저 프로세스 안에서 창이 열려 있음
        elif now - started < first_wait:
            continue                                    # 아직 첫 신호 전 (창이 뜨는 중)
        return


def run_app_window(url: str, profile: Path, last_seen=lambda: 0.0) -> bool:
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
    wait_for_window(proc, last_seen, time.time())
    return True


def setup_logging() -> Path:
    """오류 기록 파일(앱 데이터 폴더의 seomu.log). pythonw로 실행하면 콘솔이 없어 오류가 사라지기 때문."""
    import faulthandler
    import logging
    import logging.handlers
    import threading
    from .config import default_home
    home = default_home()
    home.mkdir(parents=True, exist_ok=True)
    path = home / "seomu.log"
    h = logging.handlers.RotatingFileHandler(path, maxBytes=1 << 20, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(h)
    root.setLevel(logging.INFO)
    if sys.stderr is None or sys.stdout is None:          # pythonw: print·traceback이 오류를 내지 않도록
        stream = open(path.with_suffix(".out.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    try:
        faulthandler.enable(open(path.with_suffix(".crash.log"), "a", encoding="utf-8"))  # 비정상 종료 기록
    except OSError:
        pass
    sys.excepthook = lambda t, v, tb: logging.getLogger("seomu").critical("처리되지 않은 오류", exc_info=(t, v, tb))
    threading.excepthook = lambda a: logging.getLogger("seomu").error(
        "작업 스레드 오류 (%s)", a.thread.name if a.thread else "?", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    logging.getLogger("seomu").info("시작 (Python %s, %s)", sys.version.split()[0], sys.platform)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="seomu", description=f"{APP_NAME} - 로컬 경량 AI 서무 보조 프로그램")
    ap.add_argument("--browser", action="store_true", help="프로그램 창 대신 기본 브라우저로 실행")
    ap.add_argument("--app-window", action="store_true", help="pywebview 대신 Edge/Chrome 앱 모드 창 사용")
    ap.add_argument("--port", type=int, default=0, help="내부 화면 서버 포트 (기본: 자동)")
    ap.add_argument("--no-open", action="store_true", help="창을 자동으로 열지 않음 (개발용)")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    setup_logging()
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
            opened = run_app_window(url, api._cfg.home / "app_window", api.last_heartbeat)
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

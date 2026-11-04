"""서무비서 AI 실행 진입점.

- pywebview가 있으면 네이티브 창(Windows: Edge WebView2)으로 실행
- 없으면 로컬 전용 서버를 띄우고 기본 브라우저로 화면을 연다 (--browser 로 강제 가능)
"""
from __future__ import annotations

import argparse
import sys
import time
import webbrowser

from . import APP_NAME
from .api import Api
from .server import start_server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="seomu", description=f"{APP_NAME} - 로컬 경량 AI 서무 보조 프로그램")
    ap.add_argument("--browser", action="store_true", help="네이티브 창 대신 기본 브라우저로 실행")
    ap.add_argument("--port", type=int, default=0, help="브라우저 모드 포트 (기본: 자동)")
    ap.add_argument("--no-open", action="store_true", help="브라우저 모드에서 창을 자동으로 열지 않음")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    api = Api()
    httpd, url = start_server(api, args.port)

    use_native = not args.browser
    if use_native:
        try:
            import webview  # type: ignore
        except ImportError:
            print("pywebview가 없어 브라우저 모드로 실행합니다. (pip install pywebview)")
            use_native = False

    try:
        if use_native:
            window = webview.create_window(APP_NAME, url, width=1280, height=820,
                                           min_size=(980, 640), background_color="#F5F5F7",
                                           text_select=True)
            api._window = window
            webview.start(debug=args.debug, private_mode=False)
        else:
            print(f"{APP_NAME} 실행 중: {url}  (종료: Ctrl+C)")
            if not args.no_open:
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

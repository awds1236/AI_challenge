"""열려 있는 Windows 프로그램 창(공문 뷰어 등)에서 공문을 수집한다.

흐름
1) 창 목록에서 공문 창을 고른다 (EnumWindows).
2) 본문 읽기: ① 뷰어의 '본문복사' 버튼 → 클립보드  ② UI Automation으로 화면 글자 읽기
   ③ Ctrl+A, Ctrl+C  순서로 시도한다.
3) 붙임 저장: 'PC저장'/'붙임문서' 버튼을 눌러 보고, 저장 대화상자가 뜨면 공문 폴더 경로를 넣는다.
4) 감시: 정해진 시간 동안 다운로드·바탕화면·문서·임시 폴더에 새로 생기는 문서 파일을
   공문 폴더로 모은다. 사용자가 직접 저장해도 자동으로 정리된다.

Windows 전용 기능이다. 다른 OS에서는 available()이 False를 돌려준다.
"""
from __future__ import annotations

import ntpath
import os
import re
import shutil
import struct
import sys
import threading
import time
import zlib
from pathlib import Path
from typing import Callable

IS_WIN = sys.platform.startswith("win")

DOC_EXT = {".hwp", ".hwpx", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".txt",
           ".csv", ".jpg", ".jpeg", ".png", ".odt", ".ods", ".show", ".cell", ".egg", ".7z", ".gul"}
PARTIAL_EXT = {".crdownload", ".part", ".tmp", ".download", ".partial"}
BODY_COPY_NAMES = ("본문복사", "본문 복사")
SAVE_NAMES = ("PC저장", "PC 저장", "일괄저장", "일괄 저장", "모두 저장", "전체 저장", "붙임저장", "첨부저장",
              "전체 다운로드", "일괄 다운로드", "모두 다운로드", "다운로드", "Download")
SELF_TITLES = ("서무비서 AI",)


def available() -> bool:
    return IS_WIN


# 창을 앞으로 가져오거나 실제 마우스·키보드를 쓰는 방법(최후 수단)을 허용할지.
# 기본은 '허용 안 함': 사용자가 보던 화면(영상·문서)을 가로채지 않고 뒤에 있는 창에서 바로 읽는다.
# 환경 변수 SEOMU_NO_FOREGROUND=1 이면 설정과 상관없이 항상 막는다 (검증·테스트용).
_FOREGROUND_OK = False


def set_foreground_allowed(value: bool) -> None:
    global _FOREGROUND_OK
    _FOREGROUND_OK = bool(value) and not os.environ.get("SEOMU_NO_FOREGROUND")


def foreground_allowed() -> bool:
    return _FOREGROUND_OK and not os.environ.get("SEOMU_NO_FOREGROUND")


WORK_DIR_NAME = "seomu_work"


def work_dir() -> Path:
    """글자 인식용 화면 캡처 등 프로그램이 잠깐 쓰는 파일을 두는 곳 (붙임 감시·검색에서 항상 뺀다)."""
    import tempfile
    d = Path(tempfile.gettempdir()) / WORK_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_own_temp(path: str | Path) -> bool:
    p = Path(path)
    return p.name.lower().startswith("seomu_") or WORK_DIR_NAME in {x.lower() for x in p.parts}


def copy_allowed() -> bool:
    """전체 선택·복사(Ctrl+A/C)는 키보드 입력이라 그 창이 맨 앞에 있어야만 된다 (뒤에서는 할 수 없다).
    그래서 '창을 앞으로 가져오기'를 허용했을 때만 쓴다. 기본은 뒤에서 되는 방법(본문복사 버튼·열린 문서 파일·
    UI Automation 글자 읽기·화면 글자 인식)만 쓴다."""
    return foreground_allowed()


# ---------------------------------------------------------------- Win32 (ctypes)
if IS_WIN:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
    except OSError:  # pragma: no cover
        dwmapi = None

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [ctypes.c_uint, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.GetWindowDC.restype = wintypes.HDC
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_uint]
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowExW.restype = wintypes.HWND
    user32.SendMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetDlgItem.restype = wintypes.HWND
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    # 64비트에서 핸들 값이 크면 형식 선언 없이는 'int too long to convert'로 캡처가 운에 따라 실패했다
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
                                ctypes.c_void_p, ctypes.c_uint]
    gdi32.GetDIBits.restype = ctypes.c_int
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    GW_OWNER = 4
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    WM_SETTEXT = 0x000C
    WM_COMMAND = 0x0111
    IDOK = 1
    VK_CONTROL, VK_MENU = 0x11, 0x12
    KEYEVENTF_KEYUP = 0x0002
    WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE = 0x0201, 0x0202, 0x0200
    BM_CLICK = 0x00F5
    TB_GETBUTTON, TB_BUTTONCOUNT, TB_GETITEMRECT, TB_GETBUTTONTEXTW = 0x0417, 0x0418, 0x041D, 0x044B

    user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetAncestor.restype = wintypes.HWND
    user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM,
                                           ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD,
                                        wintypes.DWORD]
    kernel32.VirtualAllocEx.restype = wintypes.LPVOID
    kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD]
    kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID, ctypes.c_size_t,
                                           ctypes.POINTER(ctypes.c_size_t)]
    kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.restype = ctypes.c_size_t

    # 고해상도 화면에서 좌표·캡처가 어긋나지 않도록 DPI 인식 설정
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        except Exception:
            pass


def _text(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _pid(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _process_name(pid: int) -> str:
    if not IS_WIN:
        return ""
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(h)


def _cloaked(hwnd) -> bool:
    if not dwmapi:
        return False
    val = ctypes.c_int(0)
    dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(val), ctypes.sizeof(val))
    return bool(val.value)


UNTITLED = "(제목 없는 창)"


def _size(hwnd) -> tuple[int, int]:
    l, t, r, b = _rect(hwnd)
    return max(0, r - l), max(0, b - t)


def _big(hwnd, w: int = 320, h: int = 200) -> bool:
    sw, sh = _size(hwnd)
    return sw >= w and sh >= h


def list_windows() -> list[dict]:
    """수집할 수 있는 최상위 창 목록.

    작업 표시줄의 창뿐 아니라, 뷰어가 아닌 프로그램이 흔히 쓰는 모양도 넣는다:
    - 다른 창에 딸린(owned) 큰 창: 옛 델파이 프로그램의 주 창, 그룹웨어가 띄운 문서 창
    - 제목 없는 큰 창: 제목을 비워 둔 업무 프로그램
    크기가 0인 껍데기 창(작업 표시줄 단추만 가진 창)은 실제 내용 창으로 바꿔서 보여 준다.
    """
    if not IS_WIN:
        return []
    out: list[dict] = []
    me = os.getpid()

    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd) or _cloaked(hwnd):
                return True
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            owned = bool(user32.GetWindow(hwnd, GW_OWNER))
            cls = _class(hwnd)
            iconic = bool(user32.IsIconic(hwnd))
            if ex & WS_EX_TOOLWINDOW and not (_big(hwnd, 500, 300) and _text(hwnd).strip()):
                return True
            if owned and (cls == "#32770" or not _big(hwnd)):        # 딸린 창은 대화상자가 아닌 큰 창만
                return True
            if not iconic and not _big(hwnd, 60, 40):              # 껍데기 창은 아래에서 내용 창으로 바꾼다
                return True
            title = _text(hwnd).strip()
            if title in ("Program Manager", "설정", "Settings"):
                return True
            if not title:
                if not _big(hwnd, 320, 240) or cls in ("Shell_TrayWnd", "Progman", "WorkerW"):
                    return True
                title = UNTITLED
            pid = _pid(hwnd)
            if pid == me or any(title.startswith(t) for t in SELF_TITLES):
                return True
            out.append({"hwnd": int(hwnd), "title": title, "process": _process_name(pid),
                        "cls": cls, "pid": pid, "owned": owned})
        except Exception:
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def window_info(hwnd: int) -> dict | None:
    """창 하나의 정보 (목록에 없던 창도)."""
    if not IS_WIN or not user32.IsWindow(hwnd):
        return None
    pid = _pid(hwnd)
    return {"hwnd": int(hwnd), "title": _text(hwnd).strip() or UNTITLED, "process": _process_name(pid),
            "cls": _class(hwnd), "pid": pid, "owned": bool(user32.GetWindow(hwnd, GW_OWNER))}


def resolve_window(hwnd: int) -> int:
    """고른 창이 크기가 없는 껍데기(작업 표시줄 단추용 창 등)면, 같은 프로그램의 가장 큰 내용 창을 돌려준다."""
    if not IS_WIN or not user32.IsWindow(hwnd):
        return hwnd
    if user32.IsIconic(hwnd) or _big(hwnd, 120, 80):
        return hwnd
    pid, best, area = _pid(hwnd), 0, 0

    def cb(h, _):
        nonlocal best, area
        try:
            if h != hwnd and user32.IsWindowVisible(h) and _pid(h) == pid and _class(h) != "#32770":
                w, ht = _size(h)
                if w * ht > area:
                    best, area = int(h), w * ht
        except Exception:
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return best if best and area >= 120 * 80 else hwnd


def activate(hwnd: int) -> bool:
    """창을 맨 앞으로 가져온다. Windows의 포그라운드 전환 제한을 우회한다."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    fg = user32.GetForegroundWindow()
    if int(fg or 0) == int(hwnd):
        return True
    cur_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    attached = []
    for tid in {fg_tid, target_tid}:
        if tid and tid != cur_tid and user32.AttachThreadInput(cur_tid, tid, True):
            attached.append(tid)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        for tid in attached:
            user32.AttachThreadInput(cur_tid, tid, False)
    time.sleep(0.4)
    return int(user32.GetForegroundWindow() or 0) == int(hwnd)


# ---------------------------------------------------------------- 클립보드
def get_clipboard() -> str:
    if not IS_WIN:
        return ""
    for _ in range(10):
        if user32.OpenClipboard(0):
            break
        time.sleep(0.05)
    else:
        return ""
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if h:
            p = kernel32.GlobalLock(h)
            try:
                if p:
                    return ctypes.wstring_at(p)
            finally:
                kernel32.GlobalUnlock(h)
        # 일부 프로그램은 텍스트 없이 HTML 형식으로만 복사한다
        fmt = user32.RegisterClipboardFormatW("HTML Format")
        h = user32.GetClipboardData(fmt) if fmt else None
        if h:
            p = kernel32.GlobalLock(h)
            try:
                raw = ctypes.string_at(p, kernel32.GlobalSize(h)) if p else b""
            finally:
                kernel32.GlobalUnlock(h)
            html = raw.split(b"\x00", 1)[0].decode("utf-8", "ignore")
            i = html.find("<")
            from .parsers import html_to_text
            return html_to_text(html[i:]) if i >= 0 else ""
        return ""
    finally:
        user32.CloseClipboard()


def get_clipboard_html() -> str:
    """클립보드의 HTML 조각 (웹·전자문서 뷰어에서 복사하면 붙임 링크가 들어 있다). 없으면 ""."""
    if not IS_WIN:
        return ""
    for _ in range(10):
        if user32.OpenClipboard(0):
            break
        time.sleep(0.05)
    else:
        return ""
    try:
        fmt = user32.RegisterClipboardFormatW("HTML Format")
        h = user32.GetClipboardData(fmt) if fmt else None
        if not h:
            return ""
        p = kernel32.GlobalLock(h)
        try:
            raw = ctypes.string_at(p, kernel32.GlobalSize(h)) if p else b""
        finally:
            kernel32.GlobalUnlock(h)
        head = raw.split(b"\x00", 1)[0].decode("utf-8", "ignore")
        m = re.search(r"SourceURL:(\S+)", head)
        i = head.find("<")
        html = head[i:] if i >= 0 else ""
        return (f"<!--source:{m.group(1)}-->" if m else "") + html
    finally:
        user32.CloseClipboard()


def html_source_url(html: str) -> str:
    m = re.match(r"<!--source:(\S+?)-->", html or "")
    return m.group(1) if m else ""


def set_clipboard(text: str) -> None:
    if not IS_WIN:
        return
    data = (text or "").encode("utf-16-le") + b"\x00\x00"
    for _ in range(10):
        if user32.OpenClipboard(0):
            break
        time.sleep(0.05)
    else:
        return
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        user32.SetClipboardData(CF_UNICODETEXT, h)
    finally:
        user32.CloseClipboard()


def _hotkey(*vks: int) -> None:
    for vk in vks:
        user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


# ---------------------------------------------------------------- 창 이미지 저장 (PNG)
def _png(path: Path, width: int, height: int, bgra: bytes) -> None:
    rows = []
    stride = width * 4
    for y in range(height):
        row = bgra[y * stride:(y + 1) * stride]
        rgb = bytearray(width * 3)
        rgb[0::3] = row[2::4]
        rgb[1::3] = row[1::4]
        rgb[2::3] = row[0::4]
        rows.append(b"\x00" + bytes(rgb))
    raw = zlib.compress(b"".join(rows), 6)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def save_window_image(hwnd: int, path: Path, crop: tuple[float, float] | None = None, scale: int = 1,
                      client: bool = False) -> bool:
    """창을 PNG로 저장. crop=(위쪽 비율, 아래쪽 비율)로 세로 일부만, scale배 확대 가능.
    client=True면 제목줄·테두리를 뺀 안쪽 영역만 (본문 글자 인식용)."""
    grab = _grab(hwnd, client)
    if not grab:
        return False
    w, h, data = grab
    if crop:
        y0, y1 = int(h * crop[0]), max(int(h * crop[0]) + 1, int(h * crop[1]))
        data, h = data[y0 * w * 4:y1 * w * 4], y1 - y0
    if scale > 1:
        rows = []
        for y in range(h):
            row = data[y * w * 4:(y + 1) * w * 4]
            wide = b"".join(row[x * 4:x * 4 + 4] * scale for x in range(w))
            rows.extend([wide] * scale)
        data, w, h = b"".join(rows), w * scale, h * scale
    try:
        _png(path, w, h, data)
        return True
    except OSError:
        return False


def capture_png(hwnd: int) -> bytes | None:
    """창 전체 그림(PNG 바이트). 공문 폴더를 만들기 전에 찍어 둘 때 쓴다."""
    tmp = work_dir() / f"seomu_shot_{os.getpid()}.png"
    try:
        if save_window_image(hwnd, tmp):
            return tmp.read_bytes()
    except OSError:
        pass
    finally:
        tmp.unlink(missing_ok=True)
    return None


def _grab(hwnd: int, client: bool = False):
    """(너비, 높이, BGRA 바이트) — 창이 가려져 있거나 화면 밖에 있어도 PrintWindow로 그린다 (앞으로 가져오지 않음)."""
    if not IS_WIN:
        return None
    rect = wintypes.RECT()
    if client:
        user32.GetClientRect(hwnd, ctypes.byref(rect))
    else:
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = w, -h, 1, 32
        buf = ctypes.create_string_buffer(w * h * 4)
        # ① 화면 합성 결과(PW_RENDERFULLCONTENT: 브라우저·GPU 그리기 창도 됨)
        # ② 비어 있으면 프로그램이 직접 그리게(WM_PRINT): 화면 밖·아직 합성 전인 창도 됨
        for flags in ((3, 1) if client else (2, 0)):
            user32.PrintWindow(hwnd, mdc, flags)
            gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
            raw = buf.raw
            step = max(4, (len(raw) // 4000) // 4 * 4)          # 일부 화소만 훑어 한 가지 색뿐인지 확인
            if len({raw[i:i + 3] for i in range(0, len(raw), step)}) > 1:
                return w, h, raw
        return w, h, buf.raw
    except Exception:
        return None
    finally:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hwnd, hdc)


# ---------------------------------------------------------------- UI Automation (선택: uiautomation 패키지)
def _uia():
    if os.environ.get("SEOMU_DISABLE_UIA"):          # UI Automation이 없는 PC를 흉내 낼 때
        return None
    try:
        import uiautomation as auto  # type: ignore
    except Exception:
        return None
    try:   # 이 라이브러리는 기본으로 실행 폴더에 @AutomationLog.txt를 만든다 → 임시 폴더로
        import tempfile
        auto.Logger.SetLogFile(os.path.join(tempfile.gettempdir(), "seomu_uia.log"))
    except Exception:
        pass
    return auto


def uia_available() -> bool:
    return IS_WIN and _uia() is not None


def _find_control(auto, root, names: tuple[str, ...]):
    for name in names:
        for kind in ("ButtonControl", "MenuItemControl", "SplitButtonControl", "ListItemControl", "Control"):
            try:
                c = getattr(root, kind)(searchDepth=14, SubName=name)
                if c.Exists(0.3, 0.1):
                    return c
            except Exception:
                continue
    return None


def _press(control, timeout: float = 4.0) -> bool:
    """버튼을 누른다. 모달 대화상자 때문에 멈추지 않도록 별도 스레드에서 실행."""
    done = threading.Event()

    def run():
        auto = _uia()
        try:
            with auto.UIAutomationInitializerInThread():
                try:
                    control.GetInvokePattern().Invoke()          # 창을 앞으로 가져오지 않고 누른다
                except Exception:
                    if foreground_allowed():                     # 실제 마우스 클릭은 허용했을 때만
                        control.Click(simulateMove=False)
        except Exception:
            pass
        finally:
            done.set()

    threading.Thread(target=run, daemon=True).start()
    done.wait(timeout)
    return True


def click_named(hwnd: int, names: tuple[str, ...]) -> bool:
    auto = _uia()
    if not auto:
        return False
    try:
        with auto.UIAutomationInitializerInThread():
            root = auto.ControlFromHandle(hwnd)
            c = _find_control(auto, root, names)
            if not c:
                return False
            return _press(c)
    except Exception:          # 찾는 도중 창이 닫혀 UI Automation 연결이 끊김 → 버튼 없음으로 본다
        return False


def uia_text(hwnd: int, limit: int = 20000) -> str:
    """화면에 보이는 글자를 UI Automation으로 읽는다 (문서 영역 TextPattern 우선)."""
    return uia_text_ex(hwnd, limit)[0]


def uia_text_ex(hwnd: int, limit: int = 20000) -> tuple[str, str]:
    """(글자, 종류). 종류: 'doc'(문서·편집 영역 전체 글자) / 'labels'(글자 조각을 이어 붙임) / ''."""
    auto = _uia()
    if not auto:
        return "", ""
    docs: list[str] = []          # 문서·편집 영역 전체 글자 (TextPattern)
    labels: list[str] = []        # 그 밖의 글자 조각 (탭 이름·상태 표시줄·메뉴가 섞일 수 있음)
    try:
        with auto.UIAutomationInitializerInThread():
            root = auto.ControlFromHandle(hwnd)
            for c, _depth in auto.WalkControl(root, maxDepth=25):
                try:
                    if c.ControlTypeName in ("DocumentControl", "EditControl", "PaneControl", "CustomControl"):
                        tp = c.GetPattern(auto.PatternId.TextPattern)
                        if tp:
                            t = tp.DocumentRange.GetText(-1)
                            if t and len(t.strip()) > 30:
                                docs.append(t)
                                continue
                    if c.ControlTypeName in ("TextControl", "DataItemControl", "HyperlinkControl") and c.Name:
                        labels.append(c.Name)
                except Exception:
                    continue
                if sum(len(p) for p in docs + labels) > limit:
                    break
    except Exception:
        # 읽는 도중 창이 닫히면 UI Automation 연결이 끊겨 COM 오류가 난다 → 그때까지 읽은 글자로 계속
        pass
    # 문서 영역 글자가 있으면 그것만 쓴다 (짧아도). 없을 때만 글자 조각을 이어 붙인다
    best = max(docs, key=len) if docs else "\n".join(dict.fromkeys(labels))
    kind = "doc" if docs else ("labels" if labels else "")
    best = best.replace("\r\n", "\n").replace("\r", "\n")      # 편집기는 줄을 CR(\r)만으로 구분한다
    best = re.sub(r"[-]", "", best)                 # 아이콘 글꼴용 글자
    return best.strip(), kind


def attachment_names(hwnd: int) -> list[str]:
    """뷰어의 '붙임목록' 같은 목록 항목 이름 (확장자가 있거나 '붙임' 영역 항목)."""
    auto = _uia()
    if not auto:
        return []
    names = []
    try:
        with auto.UIAutomationInitializerInThread():
            root = auto.ControlFromHandle(hwnd)
            for c, _ in auto.WalkControl(root, maxDepth=20):
                try:
                    if c.ControlTypeName in ("ListItemControl", "TreeItemControl") and c.Name:
                        names.append(c.Name.strip())
                except Exception:
                    continue
    except Exception:          # 창이 닫혀 UI Automation 연결이 끊김
        pass
    return list(dict.fromkeys(n for n in names if n))[:30]


def screen_attachment_names(hwnd: int, trace: list | None = None, use_ocr: bool = True) -> list[str]:
    """뷰어 화면의 '붙임목록'·'첨부파일' 칸에 보이는 문서 이름 (확장자가 있는 이름만).

    본문 영역만 읽는 본문 글자 인식은 옆·위 패널의 붙임 목록을 빼 버리므로, 창 전체를 따로 살핀다.
    ① UI Automation 목록 항목 → ② 창 전체 글자 인식(OCR, 창을 앞으로 가져오지 않음) 순서."""
    from . import attach
    trace = trace if trace is not None else []
    if not IS_WIN:
        return []
    names: list[str] = []
    try:
        listed = attachment_names(hwnd)
        names = attach.file_names_in("\n".join(listed))
        if listed:
            trace.append(f"화면 목록 항목 {len(listed)}개 중 문서 이름 {len(names)}개: {names}")
    except Exception as e:
        trace.append(f"화면 목록 항목 읽기 오류: {e}")
    if use_ocr:
        try:
            img = work_dir() / "seomu_attach_list.png"
            # 확대는 글자 인식 쪽(OCR 스크립트)에 맡긴다 (큰 창을 파이썬으로 키우면 느리다)
            lines = ocr_image(img, timeout=90, scale=2) if save_window_image(hwnd, img) else []
            found = attach.file_names_in("\n".join(l.get("text", "") for l in lines))
            trace.append(f"창 전체 글자 인식 {len(lines)}줄 중 문서 이름 {len(found)}개: {found}")
            names = attach.merge_names(names, found)
        except Exception as e:
            trace.append(f"창 전체 글자 인식 오류: {e}")
    return names


# ---------------------------------------------------------------- 일반 Win32 컨트롤 (추가 패키지 불필요)
def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "") if not ch.isspace() and ch not in "&.…").lower()


def _matches(text: str, names: tuple[str, ...]) -> bool:
    t = _norm(text)
    return bool(t) and any(_norm(n) in t for n in names)


def children(hwnd: int) -> list[int]:
    out: list[int] = []

    def cb(h, _):
        out.append(int(h))
        return True

    user32.EnumChildWindows(hwnd, WNDENUMPROC(cb), 0)
    return out


def _rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def toolbar_buttons(hwnd: int) -> list[dict]:
    """창 안의 표준 도구모음(ToolbarWindow32) 버튼 목록: 글자, 명령 ID, 위치."""
    out: list[dict] = []
    is64 = sys.maxsize > 2**32
    for tb in children(hwnd):
        # WinForms·MFC 등은 'WindowsForms10.ToolbarWindow32.app…'처럼 이름을 감싼다
        if "ToolbarWindow32" not in _class(tb) or not user32.IsWindowVisible(tb):
            continue
        h = kernel32.OpenProcess(0x0008 | 0x0010 | 0x0020 | 0x0400, False, _pid(tb))
        if not h:
            continue
        mem = None
        try:
            wow = wintypes.BOOL()
            kernel32.IsWow64Process(h, ctypes.byref(wow))
            size = 20 if (wow.value or not is64) else 32       # TBBUTTON 크기 (32/64비트 프로그램)
            mem = kernel32.VirtualAllocEx(h, None, 4096, 0x3000, 0x04)
            if not mem:
                continue
            got = ctypes.c_size_t()
            n = user32.SendMessageW(tb, TB_BUTTONCOUNT, 0, 0)
            for i in range(min(int(n), 200)):
                if not user32.SendMessageW(tb, TB_GETBUTTON, i, mem):
                    continue
                raw = ctypes.create_string_buffer(size)
                kernel32.ReadProcessMemory(h, mem, raw, size, ctypes.byref(got))
                cmd = struct.unpack_from("<i", raw.raw, 4)[0]
                if raw.raw[9] & 0x01:          # 구분선
                    continue
                text = ""
                ln = user32.SendMessageW(tb, TB_GETBUTTONTEXTW, cmd, mem)
                if 0 < ln < 1000:
                    tbuf = ctypes.create_string_buffer((ln + 1) * 2)
                    kernel32.ReadProcessMemory(h, mem, tbuf, (ln + 1) * 2, ctypes.byref(got))
                    text = tbuf.raw.decode("utf-16-le", "ignore").split("\x00", 1)[0]
                rect = (0, 0, 0, 0)
                if user32.SendMessageW(tb, TB_GETITEMRECT, i, mem):
                    rb = ctypes.create_string_buffer(16)
                    kernel32.ReadProcessMemory(h, mem, rb, 16, ctypes.byref(got))
                    rect = struct.unpack("<4i", rb.raw)
                out.append({"tb": tb, "index": i, "cmd": cmd, "text": text, "rect": rect})
        except Exception:
            continue
        finally:
            if mem:
                kernel32.VirtualFreeEx(h, mem, 0, 0x8000)
            kernel32.CloseHandle(h)
    return out


def _lparam(x: int, y: int) -> int:
    return (y & 0xFFFF) << 16 | (x & 0xFFFF)


def real_click(x: int, y: int) -> None:
    """실제 마우스 클릭(화면 좌표). 끝나면 마우스를 원래 위치로 돌려놓는다."""
    old = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(old))
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
    time.sleep(0.05)
    user32.SetCursorPos(old.x, old.y)


def _wait(check: Callable[[], bool] | None, seconds: float) -> bool:
    if check is None:
        return True
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.15)
    return False


# ---------------------------------------------------------------- Windows 내장 OCR (PowerShell + WinRT)
_OCR_PS = r"""
param([string]$Path, [double]$Scale = 1)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$max = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension
$Scale = [Math]::Max(1, [Math]::Min($Scale, [Math]::Min($max / $dec.PixelWidth, $max / $dec.PixelHeight)))
if ($Scale -gt 1.01) {
  # 작은 글자는 키워서 읽어야 정확하다 (좌표는 아래에서 원래 크기로 되돌린다)
  $tf = New-Object Windows.Graphics.Imaging.BitmapTransform
  $tf.ScaledWidth = [uint32]($dec.PixelWidth * $Scale); $tf.ScaledHeight = [uint32]($dec.PixelHeight * $Scale)
  $tf.InterpolationMode = [Windows.Graphics.Imaging.BitmapInterpolationMode]::Fant
  $bmp = Await ($dec.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
    [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied, $tf,
    [Windows.Graphics.Imaging.ExifOrientationMode]::IgnoreExifOrientation,
    [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])
} else {
  $Scale = 1
  $bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language 'ko'))
if ($engine -eq $null) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if ($engine -eq $null) { Write-Output '[]'; exit }
$res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
$lines = @()
foreach ($l in $res.Lines) {
  $r = $l.Words | ForEach-Object { $_.BoundingRect }
  $x = ($r | Measure-Object -Property X -Minimum).Minimum
  $y = ($r | Measure-Object -Property Y -Minimum).Minimum
  $x2 = ($r | ForEach-Object { $_.X + $_.Width } | Measure-Object -Maximum).Maximum
  $y2 = ($r | ForEach-Object { $_.Y + $_.Height } | Measure-Object -Maximum).Maximum
  $words = @($l.Words | ForEach-Object { @{ t = $_.Text; x = $_.BoundingRect.X / $Scale; y = $_.BoundingRect.Y / $Scale;
             w = $_.BoundingRect.Width / $Scale; h = $_.BoundingRect.Height / $Scale } })
  $lines += @{ text = $l.Text; x = $x / $Scale; y = $y / $Scale; w = ($x2 - $x) / $Scale; h = ($y2 - $y) / $Scale; words = $words }
}
ConvertTo-Json -InputObject @($lines) -Depth 5 -Compress
"""


_PDF_RENDER_PS = r"""
param([string]$Path, [string]$OutDir, [int]$Max)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFolder, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
$methods = [System.WindowsRuntimeSystemExtensions].GetMethods()
$asTaskOp = ($methods | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asTaskAct = ($methods | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
function Await($op, $type) { $t = $asTaskOp.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
function AwaitAction($op) { $t = $asTaskAct.Invoke($null, @($op)); $t.Wait(-1) | Out-Null }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
$folder = Await ([Windows.Storage.StorageFolder]::GetFolderFromPathAsync($OutDir)) ([Windows.Storage.StorageFolder])
$n = [Math]::Min([int]$doc.PageCount, $Max)
for ($i = 0; $i -lt $n; $i++) {
  $page = $doc.GetPage($i)
  $out = Await ($folder.CreateFileAsync("p$i.png", [Windows.Storage.CreationCollisionOption]::ReplaceExisting)) ([Windows.Storage.StorageFile])
  $stream = Await ($out.OpenAsync([Windows.Storage.FileAccessMode]::ReadWrite)) ([Windows.Storage.Streams.IRandomAccessStream])
  $opt = New-Object Windows.Data.Pdf.PdfPageRenderOptions
  $opt.DestinationWidth = 1800
  AwaitAction ($page.RenderToStreamAsync($stream, $opt))
  $stream.Dispose(); $page.Dispose()
}
Write-Output $n
"""


def render_pdf_pages(path: Path, out_dir: Path, max_pages: int = 8, timeout: float = 120) -> list[Path]:
    """Windows 내장 PDF 기능(Windows.Data.Pdf)으로 PDF 페이지를 그림으로 그린다 (인터넷·추가 프로그램 불필요).
    글자를 선으로 바꿔 저장한 PDF·스캔 PDF를 글자 인식할 때 쓴다."""
    if not IS_WIN:
        return []
    import subprocess
    script = work_dir() / "seomu_pdf_render.ps1"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        script.write_text(_PDF_RENDER_PS, encoding="utf-8-sig")
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                        str(Path(path).resolve()), str(out_dir.resolve()), str(max_pages)],
                       capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return []
    return sorted(out_dir.glob("p*.png"), key=lambda p: int(re.findall(r"\d+", p.stem)[0]))


def ocr_image(path: Path, timeout: float = 60, scale: float = 1) -> list[dict]:
    """Windows 내장 OCR로 이미지의 글자 줄을 읽는다. [{text,x,y,w,h,words}] (인터넷 불필요)
    scale>1이면 키워서 읽는다 (좌표는 원래 그림 기준)."""
    if not IS_WIN:
        return []
    import json
    import subprocess
    script = work_dir() / "seomu_ocr.ps1"
    try:
        script.write_text(_OCR_PS, encoding="utf-8-sig")
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                              "-File", str(script), str(path), str(scale)], capture_output=True, timeout=timeout,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        txt = out.stdout.decode("utf-8", "ignore").strip()
        data = json.loads(txt) if txt.startswith("[") else []
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def _ocr_find(hwnd: int, names: tuple[str, ...]) -> tuple[int, int] | None:
    """창 위쪽(도구모음)을 2배 확대해 OCR한 뒤 버튼 글자의 화면 좌표를 찾는다."""
    left, top, right, bottom = _rect(hwnd)
    img = work_dir() / "seomu_toolbar.png"
    if not save_window_image(hwnd, img, crop=(0.0, 0.18), scale=2):
        return None
    targets = [_norm(n) for n in names]
    for line in ocr_image(img, timeout=40):
        words = line.get("words") or []
        joined = ""
        for i, w in enumerate(words):        # 띄어 쓴 단어("본문 복사")도 이어 붙여 비교
            joined = _norm(w.get("t", ""))
            for j in range(i, min(i + 3, len(words))):
                if j > i:
                    joined += _norm(words[j].get("t", ""))
                if any(t in joined for t in targets):
                    x0 = words[i]["x"]
                    x1 = words[j]["x"] + words[j]["w"]
                    y = (words[i]["y"] + words[i]["h"] / 2)
                    return int(left + (x0 + x1) / 4), int(top + y / 2)
        if any(t in _norm(line.get("text", "")) for t in targets):
            return int(left + (line["x"] + line["w"] / 2) / 2), int(top + (line["y"] + line["h"] / 2) / 2)
    return None


def ocr_body(hwnd: int, image: Path | None = None) -> str:
    """최후 수단: 창 화면을 OCR해 본문 글자를 읽는다 (화면에 보이는 부분만)."""
    img = image or work_dir() / "seomu_body.png"
    if image is None and not _shot(hwnd, img):       # 제목줄 글자는 빼고, 다 그려진 그림으로
        return ""
    lines = ocr_image(img, scale=2)          # 업무 프로그램은 글자가 작은 경우가 많아 키워서 읽는다
    if not lines:
        return ""
    long_lines = [l for l in lines if len(l.get("text", "")) >= 12]
    if long_lines:   # 본문 단(段)의 좌우 범위 안의 줄만 남겨 도구모음·옆 패널 글자를 뺀다
        x0 = min(l["x"] for l in long_lines) - 60
        x1 = max(l["x"] + l["w"] for l in long_lines) + 60
        y0 = min(l["y"] for l in long_lines) - 80
        lines = [l for l in lines if l["x"] >= x0 and l["x"] + l["w"] <= x1 and l["y"] >= y0]
    lines.sort(key=lambda l: (round(l["y"] / 8), l["x"]))
    return "\n".join(l["text"] for l in lines).strip()


# ---------------------------------------------------------------- 뷰어가 아닌 일반 프로그램 창 대응
# 본문복사·PC저장 같은 뷰어 기능이 없는 창(한글·워드·메모장·메신저·그룹웨어 화면·자체 프로그램)도
# ① 창에 열린 문서 파일을 찾아 직접 읽고 ② 화면을 넘겨 가며 글자를 인식해서 어떻게든 본문을 얻는다.
if IS_WIN:
    class WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT), ("showCmd", wintypes.UINT),
                    ("ptMinPosition", wintypes.POINT), ("ptMaxPosition", wintypes.POINT),
                    ("rcNormalPosition", wintypes.RECT)]

    user32.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
    user32.SetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_uint]


class capturable:
    """최소화된 창은 그릴 화면이 없어 글자 인식·캡처가 안 된다.
    → 완전히 투명하게 만든 채 활성화 없이 펼쳐 화면 밖으로 옮겨 읽고, 끝나면 원래 모양·위치로 최소화한다.
    (펼치는 위치를 Windows가 모니터 안으로 당기는 경우가 있어 위치만으로는 숨길 수 없다 → 투명하게)"""

    WS_EX_LAYERED, LWA_ALPHA = 0x00080000, 0x2

    def __init__(self, hwnd: int, trace: list | None = None):
        self.hwnd, self.trace, self.orig, self.ex = hwnd, trace, None, None

    def __enter__(self):
        if not IS_WIN or not user32.IsIconic(self.hwnd):
            return self
        try:
            wp = WINDOWPLACEMENT()
            wp.length = ctypes.sizeof(WINDOWPLACEMENT)
            if not user32.GetWindowPlacement(self.hwnd, ctypes.byref(wp)):
                return self
            ex = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
            if ex & self.WS_EX_LAYERED:                     # 이미 투명도를 쓰는 창은 숨길 수 없어 펼치지 않는다
                if self.trace is not None:
                    self.trace.append("최소화된 창: 투명 처리할 수 없는 창이라 펼치지 않음")
                return self
            self.orig = WINDOWPLACEMENT.from_buffer_copy(wp)
            self.ex = ex
            user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, ex | self.WS_EX_LAYERED)
            user32.SetLayeredWindowAttributes(self.hwnd, 0, 0, self.LWA_ALPHA)      # 완전히 투명
            user32.ShowWindow(self.hwnd, 4)                    # SW_SHOWNOACTIVATE: 포커스를 가져가지 않는다
            user32.SetWindowPos(self.hwnd, None, -28000, -28000, 0, 0, 0x0001 | 0x0004 | 0x0010)  # 화면 밖으로
            time.sleep(0.6)                                   # 프로그램이 다시 그릴 시간
            if self.trace is not None:
                self.trace.append("최소화된 창: 투명하게 화면 밖에서 잠깐 펼쳐 읽음")
        except Exception:
            self.__exit__()
        return self

    def __exit__(self, *exc):
        if self.orig is not None:
            try:
                self.orig.showCmd = 7                          # SW_SHOWMINNOACTIVE: 원래 위치 기록 그대로 최소화
                user32.SetWindowPlacement(self.hwnd, ctypes.byref(self.orig))
            except Exception:
                pass
            self.orig = None
        if self.ex is not None:
            try:
                user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, self.ex)                 # 투명 처리를 되돌린다
            except Exception:
                pass
            self.ex = None
        return False


def process_command_line(pid: int) -> list[str]:
    """프로그램을 실행할 때 넘긴 인자 (한글·워드·메모장 등은 연 문서 경로가 여기에 있다)."""
    if not IS_WIN or not pid:
        return []
    try:
        ntdll = ctypes.WinDLL("ntdll")
        h = kernel32.OpenProcess(0x1000, False, pid)       # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return []
        try:
            size = ctypes.c_ulong(0)
            ntdll.NtQueryInformationProcess(wintypes.HANDLE(h), 60, None, 0, ctypes.byref(size))   # ProcessCommandLineInformation
            if not size.value or size.value > 1 << 20:
                return []
            buf = ctypes.create_string_buffer(size.value)
            if ntdll.NtQueryInformationProcess(wintypes.HANDLE(h), 60, buf, size, ctypes.byref(size)) != 0:
                return []

            class US(ctypes.Structure):
                _fields_ = [("Length", ctypes.c_ushort), ("MaximumLength", ctypes.c_ushort), ("Buffer", ctypes.c_void_p)]
            us = US.from_buffer(buf)
            line = ctypes.wstring_at(us.Buffer, us.Length // 2) if us.Buffer and us.Length else ""
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        return []
    return split_command_line(line)


def split_command_line(line: str) -> list[str]:
    if not line:
        return []
    if IS_WIN:
        try:
            shell32 = ctypes.WinDLL("shell32")
            shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
            shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
            n = ctypes.c_int(0)
            argv = shell32.CommandLineToArgvW(line, ctypes.byref(n))
            if argv:
                try:
                    return [argv[i] for i in range(n.value)]
                finally:
                    kernel32.LocalFree(argv)
        except Exception:
            pass
    return [a or b for a, b in re.findall(r'"([^"]*)"|(\S+)', line)]


def _stem_key(s: str) -> str:
    return re.sub(r"[\s_\-.()\[\]·]", "", (s or "")).lower()


def _title_mentions(title: str, path: str) -> bool:
    """창 제목에 파일 이름(확장자 없이도)이 들어 있는지. 예: '공문 - Word', '공문.hwpx - 한글'."""
    # 창에 열린 문서 경로는 Windows 경로다: 어느 OS에서 실행해도(테스트 포함) Windows 규칙으로 나눈다
    stem = _stem_key(ntpath.splitext(ntpath.basename(path or ""))[0])
    return len(stem) >= 2 and stem in _stem_key(title)


BROWSER_PROCS = ("msedge.exe", "chrome.exe", "whale.exe", "brave.exe", "firefox.exe", "opera.exe")


def browser_url(hwnd: int, limit: int = 400) -> str:
    """브라우저 창 주소창의 주소 (UI Automation). 화면에 띄운 PDF·문서 파일의 실제 위치를 알아낼 때 쓴다."""
    auto = _uia()
    if not auto:
        return ""
    try:
        with auto.UIAutomationInitializerInThread():
            root = auto.ControlFromHandle(hwnd)
            n = 0
            for c, _depth in auto.WalkControl(root, maxDepth=14):
                n += 1
                if n > limit:
                    break
                if c.ControlTypeName != "EditControl":
                    continue
                try:
                    v = (c.GetValuePattern().Value or "").strip()
                except Exception:
                    continue
                if re.match(r"^(?:file|https?)://|^[A-Za-z]:[\\/]", v):
                    return v
    except Exception:
        return ""
    return ""


def _path_from_url(url: str) -> str:
    """'file:///C:/Users/a/공문.pdf' 또는 'C:/Users/a/공문.pdf' → 'C:\\Users\\a\\공문.pdf'."""
    import urllib.parse
    u = url.strip()
    if u.lower().startswith("file:"):
        u = urllib.parse.unquote(urllib.parse.urlparse(u).path)
        u = u.lstrip("/") if re.match(r"^/[A-Za-z]:", u) else u
    elif not re.match(r"^[A-Za-z]:[\\/]", u):
        return ""
    return ntpath.normpath(u.split("#")[0].split("?")[0])


def window_document(hwnd: int, title: str | None = None, trace: list | None = None,
                    deep: bool = True) -> str:
    """창에 열려 있는 문서 파일의 경로를 찾는다 ('' = 못 찾음).
    ① 창 제목의 경로  ② 프로그램 실행 인자  ③ 최근 문서·다운로드 폴더에서 제목과 이름이 같은 파일."""
    from . import attach
    from .parsers import SUPPORTED
    trace = trace if trace is not None else []
    title = title if title is not None else _text(hwnd)
    exts = SUPPORTED | DOC_EXT | {".hwx", ".gul"}

    def ok(p: str) -> bool:
        try:
            return bool(p) and os.path.isfile(p) and Path(p).suffix.lower() in exts and os.path.getsize(p) > 0
        except OSError:
            return False

    p = attach.path_from_title(title)
    if ok(p):
        trace.append(f"열린 문서: 창 제목의 경로 {p}")
        return p
    if _process_name(_pid(hwnd)).lower() in BROWSER_PROCS:
        # 브라우저로 띄운 PDF·문서: 창 제목에는 이름만 있고 경로는 주소창에 있다 (file:///C:/…/공문.pdf)
        url = browser_url(hwnd)
        p = _path_from_url(url) if url else ""
        if ok(p):
            trace.append(f"열린 문서: 브라우저 주소창의 파일 {p}")
            return p
        if url:
            trace.append(f"브라우저 주소: {url[:120]} (PC 안의 파일이 아님)")
    args = [a for a in process_command_line(_pid(hwnd))[1:] if ok(a.strip('"'))]
    named = attach.name_from_title(title)
    for a in args:
        if (named and os.path.basename(a).lower() == named.lower()) or _title_mentions(title, a):
            trace.append(f"열린 문서: 프로그램 실행 인자 {a}")
            return a
    # 제목이 비어 있으면(이름을 보여 주지 않는 프로그램) 연 문서가 하나뿐일 때 그것으로 본다.
    # 제목이 있으면 다른 문서일 수 있어(한 프로그램에 여러 문서) 이름이 맞을 때만 쓴다.
    if len(args) == 1 and (not title.strip() or title == UNTITLED):
        trace.append(f"열린 문서: 프로그램 실행 인자(하나뿐) {args[0]}")
        return args[0]
    if not deep:
        return ""
    recent = [r for r in attach.recent_documents(hours=72) if ok(r)]
    for r in recent:
        if (named and os.path.basename(r).lower() == named.lower()) or _title_mentions(title, r):
            trace.append(f"열린 문서: 최근 문서 {r}")
            return r
    if named:                                              # 다운로드·바탕화면·문서·임시 폴더에서 이름이 같은 파일
        for f in attach.candidate_files(0, budget=5):
            if f["name"].lower() == named.lower() and ok(f["path"]):
                trace.append(f"열린 문서: 같은 이름의 파일 {f['path']}")
                return f["path"]
    trace.append(f"열린 문서 파일을 찾지 못함 (제목의 파일 이름: {named or '없음'}, 실행 인자 문서 {len(args)}개)")
    return ""


def read_document(path: str) -> str:
    from .parsers import parse_file
    try:
        return (parse_file(path) or "").strip()
    except Exception:
        return ""


# 스크롤: 창을 앞으로 가져오지 않고 메시지로 넘긴다 (스크롤 막대 → 마우스 휠 → PageDown 키 순서)
WM_VSCROLL, WM_MOUSEWHEEL, WM_KEYDOWN, WM_KEYUP = 0x0115, 0x020A, 0x0100, 0x0101
SB_PAGEDOWN, SB_TOP = 3, 6
WS_VSCROLL = 0x00200000


def _scroll_targets(hwnd: int) -> list[int]:
    """스크롤을 받을 만한 창: 세로 스크롤 막대가 있는 하위 창(큰 것부터) → 가장 큰 하위 창 → 창 자신."""
    scrollable, plain = [], []
    for c in children(hwnd):
        if not user32.IsWindowVisible(c):
            continue
        w, h = _size(c)
        if w < 150 or h < 100:
            continue
        style = user32.GetWindowLongW(c, -16)
        (scrollable if style & WS_VSCROLL else plain).append((w * h, c))
    out = [c for _, c in sorted(scrollable, reverse=True)]
    big = max(plain, default=(0, 0))[1]
    out += [c for c in (big, hwnd) if c and c not in out]
    return out


def _scroll_once(target: int, how: str) -> None:
    if how == "bar":
        user32.PostMessageW(target, WM_VSCROLL, SB_PAGEDOWN, 0)
    elif how == "wheel":
        l, t, r, b = _rect(target)
        delta = (-120 * 5) & 0xFFFF
        user32.PostMessageW(target, WM_MOUSEWHEEL, delta << 16, _lparam((l + r) // 2, (t + b) // 2))
    else:
        user32.PostMessageW(target, WM_KEYDOWN, 0x22, 0x01510001)       # VK_NEXT(PageDown)
        user32.PostMessageW(target, WM_KEYUP, 0x22, 0xC1510001)


def _scroll_home(target: int, how: str, times: int) -> None:
    if how == "bar":
        user32.PostMessageW(target, WM_VSCROLL, SB_TOP, 0)
    elif how == "wheel":
        l, t, r, b = _rect(target)
        for _ in range(times):
            user32.PostMessageW(target, WM_MOUSEWHEEL, (120 * 5) << 16, _lparam((l + r) // 2, (t + b) // 2))
    else:
        for _ in range(times):
            user32.PostMessageW(target, WM_KEYDOWN, 0x21, 0x01490001)   # VK_PRIOR(PageUp)
            user32.PostMessageW(target, WM_KEYUP, 0x21, 0xC1490001)


def _sample(w: int, h: int, data: bytes) -> bytes:
    step = max(1, (w * h) // 40000) * 4                # 화소 약 4만 개만 추려 비교한다
    return bytes(data[i] for i in range(0, len(data), step))


def _ink(sample: bytes) -> int:
    """배경(가장 흔한 값)과 다른 화소 수 = 그려진 글자·그림의 양."""
    if not sample:
        return 0
    from collections import Counter
    bg = Counter(sample).most_common(1)[0][0]
    return sum(1 for v in sample if abs(v - bg) > 40)


def _shot(hwnd: int, path: Path, tries: int = 4) -> bytes:
    """창 안쪽을 그려 저장하고, 비교용으로 화소 일부를 추린 값을 돌려준다 (b"" = 실패).

    화면 밖·뒤에 있는 창은 다시 그리는 도중의 그림(아래쪽 줄이 빠진 그림)이 찍히기도 해서,
    여러 장을 찍어 그려진 양이 가장 많은 그림을 쓴다 (덜 그려진 그림은 언제나 글자가 더 적다)."""
    best = None
    for i in range(max(1, tries)):
        grab = _grab(hwnd, True)
        if grab:
            sm = _sample(*grab)
            ink = _ink(sm)
            if best is None or ink > best[0]:
                best = (ink, grab, sm)
        if i + 1 < tries:
            time.sleep(0.12)
    if not best:
        return b""
    _ink_, (w, h, data), sm = best
    try:
        _png(path, w, h, data)
    except OSError:
        return b""
    return sm


def _same_picture(a: bytes, b: bytes, tolerance: float = 0.004) -> bool:
    """거의 같은 그림인지. 글자 가장자리 번짐·커서 깜빡임 정도의 차이는 같은 화면으로 본다."""
    if not a or not b or len(a) != len(b):
        return False
    diff = sum(1 for x, y in zip(a, b) if abs(x - y) > 24)
    return diff <= len(a) * tolerance


def merge_pages(acc: list[str], new: list[str]) -> list[str]:
    """앞 화면의 끝과 겹치는 줄을 빼고 이어 붙인다 (글자 인식이 조금 달라도 같은 줄로 본다)."""
    from difflib import SequenceMatcher
    a = [_stem_key(x) for x in acc]
    b = [_stem_key(x) for x in new]

    def same(x: str, y: str) -> bool:
        return x == y or (len(x) > 3 and SequenceMatcher(None, x, y).ratio() >= 0.8)

    for k in range(min(len(a), len(b)), 0, -1):
        if all(same(a[len(a) - k + i], b[i]) for i in range(k)):
            return acc + new[k:]
    tail = a[-12:]                                   # 겹치는 부분 중간에 인식 오류가 있는 경우
    for j in range(len(b) - 1, -1, -1):
        if any(same(b[j], t) for t in tail):
            return acc + new[j + 1:]
    return acc + new


def scroll_ocr_body(hwnd: int, log: Callable[[str], None] = lambda m: None, trace: list | None = None,
                    max_pages: int = 12, budget: float = 120) -> str:
    """화면에 다 안 보이는 긴 본문: 글자 인식 → 한 화면 넘기기를 반복해 끝까지 읽고, 맨 위로 되돌린다."""
    trace = trace if trace is not None else []
    img = work_dir() / "seomu_scroll.png"

    def settled(limit: float = 2.5) -> str:
        """프로그램이 다 그릴 때까지(연속 두 번 같은 그림) 기다렸다가 찍는다."""
        last, stop = _shot(hwnd, img), time.time() + limit
        while last and time.time() < stop:
            time.sleep(0.3)
            now = _shot(hwnd, img)
            if _same_picture(now, last):
                return now
            last = now
        return last

    first = settled()
    if not first:
        trace.append("화면 넘김 글자 인식: 창을 그리지 못함")
        return ""
    lines = [l for l in ocr_body(hwnd, img).split("\n") if l.strip()]
    seen, pages, end = [first], 1, time.time() + budget
    way, target, moved_total = "", 0, 0
    while pages < max_pages and time.time() < end:
        moved = b""
        for tg in ([target] if target else _scroll_targets(hwnd)):
            for how in ([way] if way else ("bar", "wheel", "key")):
                _scroll_once(tg, how)
                time.sleep(0.45)
                digest = settled()
                if digest and not any(_same_picture(digest, x) for x in seen):
                    moved, target, way = digest, tg, how
                    break
            if moved:
                break
        if not moved:
            break
        seen.append(moved)
        moved_total += 1
        merged = merge_pages(lines, [l for l in ocr_body(hwnd, img).split("\n") if l.strip()])
        if len(merged) == len(lines):            # 그림만 바뀌고 새 줄이 없다 (깜빡임·애니메이션) → 끝
            break
        lines = merged
        pages += 1
        log(f"화면을 넘겨 가며 글자를 읽는 중… ({pages}쪽)")
    if moved_total:
        _scroll_home(target, way, moved_total + 1)
    trace.append(f"화면 넘김 글자 인식: {pages}화면 ({'넘김 방법 ' + way if way else '넘길 내용 없음'}), {len(lines)}줄")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------- 버튼 누르기 (여러 방법 순서대로)
def click_any(hwnd: int, names: tuple[str, ...], check: Callable[[], bool] | None = None,
              log: Callable[[str], None] = lambda m: None, trace: list | None = None,
              use_ocr: bool = True) -> str:
    """이름이 맞는 버튼을 누르고 check()가 참이 되면 사용한 방법을 돌려준다. 실패 시 ""."""
    trace = trace if trace is not None else []
    if not IS_WIN:
        return ""
    # ① 표준 도구모음 버튼
    buttons = toolbar_buttons(hwnd)
    trace.append(f"도구모음 버튼 {len(buttons)}개: " + ", ".join(b["text"] for b in buttons if b["text"])[:300])
    for b in buttons:
        if not _matches(b["text"], names):
            continue
        l, t, r, bt = b["rect"]
        x, y = (l + r) // 2, (t + bt) // 2
        user32.PostMessageW(b["tb"], WM_MOUSEMOVE, 0, _lparam(x, y))
        user32.PostMessageW(b["tb"], WM_LBUTTONDOWN, 1, _lparam(x, y))
        user32.PostMessageW(b["tb"], WM_LBUTTONUP, 0, _lparam(x, y))
        if _wait(check, 2.5):
            return f"도구모음 '{b['text']}' 클릭"
        root = user32.GetAncestor(b["tb"], 2)  # GA_ROOT
        for target in (user32.GetParent(b["tb"]), root):
            user32.PostMessageW(target, WM_COMMAND, b["cmd"] & 0xFFFF, b["tb"])
            if _wait(check, 2.0):
                return f"도구모음 '{b['text']}' 명령"
        trace.append(f"'{b['text']}' 버튼을 눌렀지만 반응 없음")
    # ② 일반 버튼 컨트롤
    for c in children(hwnd):
        if "button" in _class(c).lower() and _matches(_text(c), names):
            user32.PostMessageW(c, BM_CLICK, 0, 0)
            if _wait(check, 2.5):
                return f"버튼 '{_text(c)}'"
    # ③ UI Automation
    if uia_available():
        try:
            if click_named(hwnd, names) and _wait(check, 2.5):
                return "UI Automation"
            trace.append("UI Automation: 버튼을 찾지 못함")
        except Exception as e:
            trace.append(f"UI Automation 오류: {e}")
    else:
        trace.append("UI Automation: uiautomation 패키지 없음")
    # ④ 화면 글자 인식(OCR)으로 버튼 위치를 찾아 실제 클릭 (창을 앞으로 가져와야 하므로 허용했을 때만)
    if use_ocr and not foreground_allowed():
        trace.append("화면 클릭 생략: 창을 앞으로 가져오지 않는 설정")
    elif use_ocr:
        log(f"화면에서 '{names[0]}' 버튼 글자를 찾는 중… (글자 인식)")
        pos = _ocr_find(hwnd, names)
        trace.append(f"OCR 버튼 위치: {pos}")
        if pos:
            activate(hwnd)
            real_click(*pos)
            if _wait(check, 3.0):
                return "글자 인식 후 클릭"
    return ""


def _largest_child(hwnd: int) -> int:
    best, area = 0, 0
    for c in children(hwnd):
        if not user32.IsWindowVisible(c) or any(k in _class(c) for k in ("ToolbarWindow32", "ReBarWindow32", "msctls_statusbar32")):
            continue
        l, t, r, b = _rect(c)
        a = max(0, r - l) * max(0, b - t)
        if a > area:
            best, area = c, a
    return best


def _prose_lines(text: str) -> int:
    """문장처럼 긴 줄 수 (메뉴·탭 이름 같은 짧은 조각과 본문을 가른다)."""
    return sum(1 for l in (text or "").split("\n") if len(l.strip()) >= 15)


def extract_text(hwnd: int, log: Callable[[str], None] = lambda m: None,
                 trace: list | None = None, found: dict | None = None) -> tuple[str, str]:
    """(본문, 사용한 방법). trace에 단계별 기록을 남긴다.

    모두 창을 앞으로 가져오지 않고 뒤에서 읽는다 (사용자 작업을 방해하지 않는다):
    본문복사 버튼 → 창에 열린 문서 파일 → UI Automation 글자 정보 → 편집 칸 → 문서 파일 찾기 → 화면 넘김 글자 인식(OCR).
    '창을 앞으로 가져오기'를 허용했을 때만 OCR 전에 전체 선택·복사(Ctrl+A/C)를 한다 (키보드 입력은 맨 앞 창에만 들어간다).
    found["html"]에는 복사한 HTML(붙임 링크 포함)을 넣어 준다 (있을 때).
    어느 방법도 충분하지 않으면 그중 가장 긴 결과라도 돌려준다 (빈손으로 끝내지 않는다).
    found["document"]에는 창에 열려 있던 문서 파일 경로를 넣어 준다 (찾았을 때)."""
    trace = trace if trace is not None else []
    found = found if found is not None else {}
    if not IS_WIN:
        return "", ""
    previous = get_clipboard()
    marker = f"__seomu_{time.time()}__"
    partial: list[tuple[str, str]] = []           # 기준에 못 미친 결과 (마지막에 가장 나은 것을 쓴다)

    def fresh() -> str:
        t = get_clipboard()
        return t if t and t != marker and len(t.strip()) > 20 else ""

    def keep(t: str, how: str) -> None:
        if t and t.strip():
            partial.append((t.strip(), how))

    def from_document(deep: bool) -> tuple[str, str]:
        path = found.get("document") or window_document(hwnd, trace=trace, deep=deep)
        if not path:
            return "", ""
        found["document"] = path
        t = read_document(path)
        trace.append(f"열린 문서 파일 글자: {len(t)}자 ({Path(path).name})")
        return t, f"창에 열린 문서 파일 읽기 ({Path(path).name})"

    try:
        # 창을 앞으로 가져오지 않는 방법부터 (사용자가 보던 화면을 가로채지 않는다)
        # ① 본문복사 버튼 (도구모음·버튼 메시지, UI Automation 호출 — 모두 창이 뒤에 있어도 동작)
        log("'본문복사' 버튼을 찾는 중…")
        set_clipboard(marker)
        how = click_any(hwnd, BODY_COPY_NAMES, check=lambda: bool(fresh()), log=log, trace=trace)
        if how:
            return fresh(), f"본문복사 ({how})"
        trace.append("본문복사 버튼 없음 → 뷰어가 아닌 일반 프로그램 창으로 보고 다른 방법을 이어서 시도")
        # ② 창 제목·실행 인자에 문서 경로가 있으면 그 파일이 가장 정확하다 (한글·워드·메모장·PDF 프로그램 등)
        t, how = from_document(deep=False)
        if len(t) > 80:
            return t, how
        keep(t, how)
        # ③ UI Automation 글자 읽기
        if uia_available():
            log("화면의 글자 정보를 읽는 중…")
            t, kind = uia_text_ex(hwnd)
            trace.append(f"UI Automation 글자: {len(t)}자 ({'문서 영역' if kind == 'doc' else '글자 조각'})")
            # 글자 조각만 있을 때는 메뉴·탭 이름일 수 있어 문장 같은 줄이 여럿일 때만 본문으로 본다
            if len(t) > 80 and (kind == "doc" or _prose_lines(t) >= 3):
                return t, "화면 글자 정보"
            keep(t, "화면 글자 정보 (일부)")
        # ④ 표준 편집 칸(Edit·RichEdit)의 글자를 메시지로 읽기
        t = edit_text(hwnd)
        trace.append(f"편집 칸 글자: {len(t)}자")
        if len(t) > 80:
            return t, "편집 칸 글자"
        keep(t, "편집 칸 글자 (일부)")
        # ⑤ 최근 문서·다운로드 폴더에서 창 제목과 같은 이름의 문서 파일 찾기
        if not found.get("document"):
            log("창에 열린 문서 파일을 PC에서 찾는 중…")
            t, how = from_document(deep=True)
            if len(t) > 80:
                return t, how
            keep(t, how)
        # ⑥ 전체 선택·복사 (Ctrl+A, Ctrl+C) — 글자를 그대로 가져오므로 OCR보다 정확하다.
        #    창을 잠깐 앞으로 가져왔다가 원래 보던 창으로 되돌린다. 복사된 HTML(붙임 링크)도 함께 받아 둔다
        if copy_allowed():
            log("문서를 전체 선택·복사하는 중… (허용한 설정이라 잠깐 그 창이 앞에 뜹니다)")
            t, html = copy_all(hwnd, trace, fresh, marker)
            if html:
                found["html"] = html
            if len(t) > 80 and _prose_lines(t) >= 2:
                return t, "전체 선택·복사"
            keep(t, "전체 선택·복사 (일부)")
        else:
            trace.append("전체 선택·복사 생략: 창을 앞으로 가져오지 않는 설정 (뒤에서 되는 방법만 사용)")
        # ⑦ 마지막: 창 화면을 그려 받아(PrintWindow, 가려져 있어도 됨) 글자 인식 — 화면을 넘겨 가며 끝까지
        log("화면 글자 인식(OCR)으로 본문을 읽는 중…")
        t = scroll_ocr_body(hwnd, log, trace)
        trace.append(f"OCR 본문: {len(t)}자")
        if len(t) > 80:
            return t, "화면 글자 인식(OCR)"
        keep(t, "화면 글자 인식(OCR) (일부)")
        return _best(partial, trace)
    finally:
        if previous:
            set_clipboard(previous)


def _is_front(hwnd: int) -> bool:
    """맨 앞(키보드 입력을 받는) 창이 그 창(또는 그 창과 같은 프로그램의 창)이고, 서무비서 자신이 아닌지."""
    fg = int(user32.GetForegroundWindow() or 0)
    if not fg:
        return False
    if _pid(fg) == os.getpid() or _process_name(_pid(fg)).lower() in ("seomuai.exe", "python.exe", "pythonw.exe"):
        return False
    root = int(user32.GetAncestor(fg, 2) or fg)        # GA_ROOT
    return fg == int(hwnd) or root == int(hwnd) or _pid(fg) == _pid(hwnd)


def copy_all(hwnd: int, trace: list, fresh: Callable[[], str], marker: str) -> tuple[str, str]:
    """창을 잠깐 앞으로 가져와 전체 선택·복사하고, 원래 앞에 있던 창으로 되돌린다. (글자, HTML)"""
    prev = int(user32.GetForegroundWindow() or 0)
    set_clipboard(marker)
    try:
        activate(hwnd)
        if not _is_front(hwnd):
            # Windows가 창 전환을 막았다 → 지금 맨 앞 창(서무비서 등)에 Ctrl+A/C가 들어가지 않게 키를 보내지 않는다
            trace.append("전체 선택·복사 생략: 그 창을 앞으로 가져오지 못함 (Windows 창 전환 제한)")
            return "", ""
        trace.append("전체 선택·복사: 그 창이 맨 앞에 있음을 확인")
        _hotkey(VK_CONTROL, 0x41)                     # 먼저 클릭 없이 (링크를 잘못 누르지 않게)
        time.sleep(0.3)
        _hotkey(VK_CONTROL, 0x43)
        if not _wait(lambda: bool(fresh()), 1.5) and _is_front(hwnd):
            doc = _largest_child(hwnd) or hwnd          # 글자 영역에 초점이 없으면 왼쪽 여백을 눌러 초점을 준다
            l, t, r, b = _rect(doc)
            if r - l > 50 and b - t > 50:
                real_click(l + 6, t + (b - t) // 2)
                time.sleep(0.2)
                _hotkey(VK_CONTROL, 0x41)
                time.sleep(0.3)
                _hotkey(VK_CONTROL, 0x43)
                _wait(lambda: bool(fresh()), 2.0)
        text = fresh()
        html = get_clipboard_html() if text else ""
        trace.append(f"전체 선택·복사: 글자 {len(text)}자, HTML {'있음' if html else '없음'}")
        return text, html
    finally:
        if prev and prev != int(hwnd) and user32.IsWindow(prev):
            activate(prev)                                # 보던 창으로 되돌린다


def _best(partial: list[tuple[str, str]], trace: list) -> tuple[str, str]:
    """충분한 결과가 없을 때: 문장 같은 줄이 많은 것 → 긴 것 순으로 가장 나은 부분 결과."""
    if not partial:
        trace.append("본문을 읽을 수 있는 방법이 없음")
        return "", ""
    t, how = max(partial, key=lambda p: (_prose_lines(p[0]), len(p[0])))
    trace.append(f"충분한 본문을 얻지 못해 가장 나은 부분 결과를 씀: {how} ({len(t)}자)")
    return t, how


def edit_text(hwnd: int) -> str:
    """창 안의 표준 편집 칸(Edit·RichEdit·WinForms TextBox)에서 가장 긴 글자를 읽는다 (창이 뒤에 있어도 됨)."""
    best = ""
    res = ctypes.c_size_t()

    def send(c, msg, wp, lp) -> int:
        # 응답 없는 프로그램에 막히지 않도록 1초 제한 (SMTO_ABORTIFHUNG)
        ok = user32.SendMessageTimeoutW(c, msg, wp, lp, 0x0002, 1000, ctypes.byref(res))
        return int(res.value) if ok else 0
    for c in children(hwnd):
        if not re.search(r"(edit|richedit|textbox)", _class(c), re.I):
            continue
        n = send(c, 0x000E, 0, 0)                                      # WM_GETTEXTLENGTH
        if n <= len(best) or n > 2_000_000:
            continue
        buf = ctypes.create_unicode_buffer(n + 1)
        send(c, 0x000D, n + 1, ctypes.cast(buf, ctypes.c_void_p).value)   # WM_GETTEXT
        if len(buf.value) > len(best):
            best = buf.value
    return best.replace("\r\n", "\n").replace("\r", "\n").strip()


def diagnose(hwnd: int) -> str:
    """수집이 안 될 때 뷰어 구조를 확인하는 진단 보고서."""
    lines = [f"창: {_text(hwnd)}", f"클래스: {_class(hwnd)} / 프로세스: {_process_name(_pid(hwnd))}",
             f"UI Automation 사용 가능: {uia_available()}"]
    from collections import Counter
    kids = children(hwnd)
    lines.append(f"하위 창 {len(kids)}개: " + ", ".join(f"{k}×{v}" for k, v in Counter(_class(c) for c in kids).most_common(25)))
    for c in kids:
        t = _text(c)
        if t:
            lines.append(f"  - [{_class(c)}] {t[:60]}")
    for b in toolbar_buttons(hwnd):
        lines.append(f"  도구모음 버튼: '{b['text']}' (명령 {b['cmd']}, 위치 {b['rect']})")
    return "\n".join(lines)


def _dialogs_of(pid: int) -> list[int]:
    found = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and _class(hwnd) == "#32770" and _pid(hwnd) == pid:
            found.append(int(hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def _find_edit(hwnd) -> int:
    """저장/폴더 대화상자의 경로 입력칸."""
    for path in (("DUIViewWndClassName", "DirectUIHWND", "FloatNotifySink", "ComboBox", "Edit"),
                 ("ComboBoxEx32", "ComboBox", "Edit"), ("Edit",)):
        h = hwnd
        for cls in path:
            h = user32.FindWindowExW(h, None, cls, None)
            if not h:
                break
        if h:
            return int(h)
    return 0


def try_save_attachments(hwnd: int, folder: Path, log: Callable[[str], None] = lambda m: None,
                         trace: list | None = None) -> str:
    """'PC저장'/'붙임문서' 버튼을 누르고, 저장 대화상자가 뜨면 공문 폴더를 지정한다.

    반환: "saved"(대화상자에 경로 입력 완료), "clicked"(버튼만 누름), ""(버튼 없음)
    """
    if not IS_WIN:
        return ""
    pid = _pid(hwnd)
    before = set(_dialogs_of(pid))
    log("뷰어의 'PC저장' 버튼을 누르는 중…")       # 창을 앞으로 가져오지 않고 버튼 메시지·UI Automation으로
    if not click_any(hwnd, SAVE_NAMES, check=lambda: bool(set(_dialogs_of(pid)) - before), log=log, trace=trace):
        return ""
    # 붙임이 여러 개면 저장 창이 하나씩 이어서 뜬다 → 더 뜨지 않을 때까지 모두 공문 폴더로 저장한다
    handled: set[int] = set()
    saved, waited_for_user = 0, False
    quiet_until = time.time() + 5.0                  # 첫 창은 5초까지 기다리고, 이후에는 마지막 창 뒤 4초
    while time.time() < quiet_until:
        time.sleep(0.2)
        new = [d for d in _dialogs_of(pid) if d not in before and d not in handled]
        if not new:
            continue
        dlg = new[0]
        handled.add(dlg)
        edit = _find_edit(dlg)
        if edit:
            cur = ctypes.create_unicode_buffer(1024)
            user32.SendMessageW(edit, 0x000D, 1024, ctypes.cast(cur, ctypes.c_void_p).value)  # WM_GETTEXT
            name = os.path.basename(cur.value.strip().strip('"'))
            # 파일 저장 창이면 '폴더\파일명', 폴더 선택 창이면 폴더 경로만 넣는다
            target = str(folder / name) if name and os.path.splitext(name)[1] else str(folder)
            path = ctypes.create_unicode_buffer(target)
            user32.SendMessageW(edit, WM_SETTEXT, 0, ctypes.cast(path, ctypes.c_void_p).value)
            time.sleep(0.2)
            user32.SendMessageW(dlg, WM_COMMAND, IDOK, 0)
            saved += 1
            trace.append(f"저장 창 {saved}: {name or '(폴더 선택)'} → 공문 폴더") if trace is not None else None
            log(f"붙임 {saved}개를 공문 폴더에 저장하는 중…")
        else:
            msg = " ".join(_text(c) for c in children(dlg))
            if re.search(r"(바꾸시겠|덮어|이미 있|already exists|replace)", msg, re.I):
                user32.SendMessageW(dlg, WM_COMMAND, 6, 0)          # IDYES: 같은 이름 덮어쓰기 (공문 폴더 안)
            else:
                waited_for_user = True
                log("뷰어가 확인 창을 띄웠습니다. 그 창에서 확인해 주세요.")
        quiet_until = time.time() + 4.0
    if saved:
        return "saved"
    return "clicked" if handled or waited_for_user else "clicked"


# ---------------------------------------------------------------- 새 파일 감시
def watch_dirs(extra: list[Path] | None = None) -> list[Path]:
    home = Path.home()
    dirs = [home / "Downloads", home / "Desktop", home / "Documents"]
    tmp = os.environ.get("TEMP") or os.environ.get("TMP")
    if tmp:
        dirs.append(Path(tmp))
    for d in extra or []:
        dirs.append(Path(d))
    return [d for d in dict.fromkeys(dirs) if d.exists()]


def _scan(dirs: list[Path], depth: int = 1) -> dict[str, tuple[float, int]]:
    out: dict[str, tuple[float, int]] = {}

    def walk(p: Path, level: int):
        try:
            with os.scandir(p) as it:
                for e in it:
                    try:
                        if e.is_file(follow_symlinks=False):
                            st = e.stat()
                            out[e.path] = (st.st_mtime, st.st_size)
                        elif level < depth and e.is_dir(follow_symlinks=False) and not e.name.startswith("."):
                            walk(Path(e.path), level + 1)
                    except OSError:
                        continue
        except OSError:
            pass

    for d in dirs:
        walk(d, 0)
    return out


class FileWatcher:
    """시작 이후 새로 생기거나 바뀐 문서 파일을 찾아 대상 폴더로 모은다."""

    def __init__(self, dirs: list[Path], dest: Path, ignore: set[str] | None = None):
        self.dirs = dirs
        self.dest = dest
        self.ignore = {os.path.normcase(os.path.abspath(p)) for p in (ignore or set())}
        self.base = _scan(dirs)
        self.started = time.time()
        self.pending: dict[str, tuple[float, int, float]] = {}
        self.collected: list[dict] = []
        self._seen: set[str] = set()

    def _wanted(self, path: str) -> bool:
        p = Path(path)
        ext = p.suffix.lower()
        if ext in PARTIAL_EXT or ext not in DOC_EXT or p.name.startswith(("~$", ".")) or is_own_temp(p):
            return False
        norm = os.path.normcase(os.path.abspath(path))
        if norm in self.ignore or norm in self._seen:
            return False
        try:
            Path(path).resolve().relative_to(self.dest.resolve())
            return False  # 이미 공문 폴더 안
        except ValueError:
            return True

    def poll(self) -> list[dict]:
        """한 번 검사. 크기가 2회 연속 같으면(다운로드 완료) 복사한다. 새로 모은 항목을 반환."""
        now = time.time()
        new_items = []
        for path, (mtime, size) in _scan(self.dirs).items():
            old = self.base.get(path)
            if old and old == (mtime, size):
                continue
            if mtime < self.started - 2 or size == 0 or not self._wanted(path):
                continue
            prev = self.pending.get(path)
            if prev and prev[1] == size and now - prev[2] >= 1.0:
                item = self._take(path)
                if item:
                    new_items.append(item)
                self.pending.pop(path, None)
            elif not prev or prev[1] != size:
                self.pending[path] = (mtime, size, now)
        return new_items

    def _take(self, path: str) -> dict | None:
        from .collector import safe_name, unique_path
        src = Path(path)
        self._seen.add(os.path.normcase(os.path.abspath(path)))
        self.dest.mkdir(parents=True, exist_ok=True)
        target = unique_path(self.dest / safe_name(src.name, 150))
        try:
            # 원본 보호: 사용자 PC의 파일은 옮기거나 지우지 않고 복사만 한다 (공문 폴더에 사본을 모은다)
            shutil.copy2(src, target)
        except OSError as e:
            return {"name": src.name, "path": "", "ok": False, "error": str(e)[:200]}
        item = {"name": target.name, "path": str(target), "ok": True, "from": str(src.parent)}
        self.collected.append(item)
        return item

    def idle_for(self) -> float:
        last = max([self.started] + [p[2] for p in self.pending.values()])
        return time.time() - last


if __name__ == "__main__":  # 진단:  python -m seomu.winwindow [창 제목 일부]
    if not IS_WIN:
        print("Windows에서만 동작합니다.")
        sys.exit(0)
    wins = list_windows()
    if len(sys.argv) < 2:
        for w in wins:
            print(f"{w['hwnd']:>10}  {w['process']:<20} {w['title']}")
        sys.exit(0)
    key = " ".join(sys.argv[1:])
    target = next((w for w in wins if key in w["title"]), None)
    if not target:
        print("해당 제목의 창이 없습니다.")
        sys.exit(1)
    report = diagnose(target["hwnd"])
    print(report)
    out = Path.home() / "Downloads" / "서무비서_진단.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\n진단 결과를 저장했습니다: {out}")


# ---------------------------------------------------------------- 화면에 보이는 붙임 이름을 찾아 열기 (범용)
def real_double_click(x: int, y: int) -> None:
    old = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(old))
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    for _ in range(2):
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.06)
    time.sleep(0.05)
    user32.SetCursorPos(old.x, old.y)


def ocr_window(hwnd: int, scale: int = 2) -> list[dict]:
    """창 전체를 확대해 OCR. 좌표는 창 기준(확대 전) 픽셀로 돌려준다."""
    img = work_dir() / "seomu_window.png"
    if not save_window_image(hwnd, img, scale=scale):
        return []
    lines = ocr_image(img, timeout=90)
    for l in lines:
        for k in ("x", "y", "w", "h"):
            l[k] = l.get(k, 0) / scale
    return lines


def open_named_on_screen(hwnd: int, names: list[str], log: Callable[[str], None] = lambda m: None,
                         trace: list | None = None, per_item: float = 8.0) -> list[dict]:
    """화면에서 붙임 이름(목록·패널·링크)을 OCR로 찾아 더블클릭하고, 열린 파일의 경로를 알아낸다.

    반환: [{"expected": 붙임 이름, "path": 파일 경로 또는 "", "title": 열린 창 제목}]
    열린 창(한글·PDF 뷰어 등)은 경로를 확인한 뒤 닫는다.
    """
    from . import attach
    trace = trace if trace is not None else []
    if not IS_WIN or not names:
        return []
    if not foreground_allowed():           # 실제 더블클릭이 필요하므로 허용했을 때만
        trace.append("화면의 붙임 이름 더블클릭 생략: 창을 앞으로 가져오지 않는 설정 (폴더 감시로 수집)")
        return []
    log("화면에서 붙임 이름을 찾는 중… (글자 인식)")
    lines = ocr_window(hwnd)
    trace.append(f"화면 OCR 줄 {len(lines)}개")
    left, top, _r, _b = _rect(hwnd)
    viewer_pid = _pid(hwnd)
    me = os.getpid()
    results = []
    for name in names:
        # 본문 속 '붙임 1. ○○ 1부.' 줄이 아니라 목록·패널·링크에 보이는 이름을 고른다
        best, score = None, 0.0
        for l in lines:
            t = l.get("text", "")
            if not t or re.search(r"(붙\s*임|\d\s*부\s*\.?$|끝\s*\.)", t):
                continue
            sc = attach.name_score(name, t)
            if sc > score:
                best, score = l, sc
        if not best or score < 0.5:
            trace.append(f"'{name}': 화면에서 이름을 찾지 못함 (최고 {score:.2f})")
            continue
        before = {w["hwnd"] for w in list_windows()}
        x, y = left + best["x"] + min(best["w"] / 2, 60), top + best["y"] + best["h"] / 2
        activate(hwnd)
        real_double_click(int(x), int(y))
        trace.append(f"'{name}': 화면의 '{best['text']}' 더블클릭 ({score:.2f})")
        opened = None
        end = time.time() + per_item
        while time.time() < end and not opened:
            time.sleep(0.5)
            for w in list_windows():
                if w["hwnd"] not in before and w["pid"] not in (me,) and w["hwnd"] != hwnd:
                    if attach.path_from_title(w["title"]) or attach.name_from_title(w["title"]) or w["pid"] != viewer_pid:
                        opened = w
                        break
        if not opened:
            results.append({"expected": name, "path": "", "title": ""})
            trace.append(f"'{name}': 새 창이 열리지 않음 (다운로드됐다면 폴더 감시로 수집)")
            continue
        time.sleep(1.0)
        title = _text(opened["hwnd"]) or opened["title"]
        path = attach.path_from_title(title)
        results.append({"expected": name, "path": path if path and os.path.exists(path) else "",
                        "title": title, "file_name": attach.name_from_title(title)})
        trace.append(f"'{name}': 열린 창 '{title[:80]}' → 경로 {path or '없음'}")
        if opened["pid"] != viewer_pid:      # 붙임을 연 프로그램 창(한글·PDF 등)은 닫는다
            user32.PostMessageW(opened["hwnd"], 0x0010, 0, 0)  # WM_CLOSE
            time.sleep(0.8)
    return results

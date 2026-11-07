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


def list_windows() -> list[dict]:
    """작업 표시줄에 보이는 최상위 창 목록."""
    if not IS_WIN:
        return []
    out: list[dict] = []
    me = os.getpid()

    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
                return True
            if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW or _cloaked(hwnd):
                return True
            title = _text(hwnd).strip()
            if not title or title in ("Program Manager", "설정", "Settings"):
                return True
            pid = _pid(hwnd)
            if pid == me or any(title.startswith(t) for t in SELF_TITLES):
                return True
            out.append({"hwnd": int(hwnd), "title": title, "process": _process_name(pid),
                        "cls": _class(hwnd), "pid": pid})
        except Exception:
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


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
    with auto.UIAutomationInitializerInThread():
        root = auto.ControlFromHandle(hwnd)
        c = _find_control(auto, root, names)
        if not c:
            return False
        return _press(c)


def uia_text(hwnd: int, limit: int = 20000) -> str:
    """화면에 보이는 글자를 UI Automation으로 읽는다 (문서 영역 TextPattern 우선)."""
    auto = _uia()
    if not auto:
        return ""
    docs: list[str] = []          # 문서·편집 영역 전체 글자 (TextPattern)
    labels: list[str] = []        # 그 밖의 글자 조각 (탭 이름·상태 표시줄·메뉴가 섞일 수 있음)
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
    # 문서 영역 글자가 있으면 그것만 쓴다 (짧아도). 없을 때만 글자 조각을 이어 붙인다
    best = max(docs, key=len) if docs else "\n".join(dict.fromkeys(labels))
    best = best.replace("\r\n", "\n").replace("\r", "\n")      # 편집기는 줄을 CR(\r)만으로 구분한다
    best = re.sub(r"[-]", "", best)                 # 아이콘 글꼴용 글자
    return best.strip()


def attachment_names(hwnd: int) -> list[str]:
    """뷰어의 '붙임목록' 같은 목록 항목 이름 (확장자가 있거나 '붙임' 영역 항목)."""
    auto = _uia()
    if not auto:
        return []
    names = []
    with auto.UIAutomationInitializerInThread():
        root = auto.ControlFromHandle(hwnd)
        for c, _ in auto.WalkControl(root, maxDepth=20):
            try:
                if c.ControlTypeName in ("ListItemControl", "TreeItemControl") and c.Name:
                    names.append(c.Name.strip())
            except Exception:
                continue
    return list(dict.fromkeys(n for n in names if n))[:30]


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
param([string]$Path)
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
$bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
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
  $words = @($l.Words | ForEach-Object { @{ t = $_.Text; x = $_.BoundingRect.X; y = $_.BoundingRect.Y;
             w = $_.BoundingRect.Width; h = $_.BoundingRect.Height } })
  $lines += @{ text = $l.Text; x = $x; y = $y; w = $x2 - $x; h = $y2 - $y; words = $words }
}
ConvertTo-Json -InputObject @($lines) -Depth 5 -Compress
"""


def ocr_image(path: Path, timeout: float = 60) -> list[dict]:
    """Windows 내장 OCR로 이미지의 글자 줄을 읽는다. [{text,x,y,w,h,words}] (인터넷 불필요)"""
    if not IS_WIN:
        return []
    import json
    import subprocess
    import tempfile
    script = Path(tempfile.gettempdir()) / "seomu_ocr.ps1"
    try:
        script.write_text(_OCR_PS, encoding="utf-8-sig")
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                              "-File", str(script), str(path)], capture_output=True, timeout=timeout,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        txt = out.stdout.decode("utf-8", "ignore").strip()
        data = json.loads(txt) if txt.startswith("[") else []
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def _ocr_find(hwnd: int, names: tuple[str, ...]) -> tuple[int, int] | None:
    """창 위쪽(도구모음)을 2배 확대해 OCR한 뒤 버튼 글자의 화면 좌표를 찾는다."""
    import tempfile
    left, top, right, bottom = _rect(hwnd)
    img = Path(tempfile.gettempdir()) / "seomu_toolbar.png"
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
    import tempfile
    img = image or Path(tempfile.gettempdir()) / "seomu_body.png"
    if image is None and not save_window_image(hwnd, img, client=True):       # 제목줄 글자는 빼고
        return ""
    lines = ocr_image(img)
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


def extract_text(hwnd: int, log: Callable[[str], None] = lambda m: None,
                 trace: list | None = None) -> tuple[str, str]:
    """(본문, 사용한 방법). trace에 단계별 기록을 남긴다."""
    trace = trace if trace is not None else []
    if not IS_WIN:
        return "", ""
    previous = get_clipboard()
    marker = f"__seomu_{time.time()}__"

    def fresh() -> str:
        t = get_clipboard()
        return t if t and t != marker and len(t.strip()) > 20 else ""

    try:
        # 창을 앞으로 가져오지 않는 방법부터 (사용자가 보던 화면을 가로채지 않는다)
        # ① 본문복사 버튼 (도구모음·버튼 메시지, UI Automation 호출 — 모두 창이 뒤에 있어도 동작)
        log("뷰어의 '본문복사' 버튼을 누르는 중…")
        set_clipboard(marker)
        how = click_any(hwnd, BODY_COPY_NAMES, check=lambda: bool(fresh()), log=log, trace=trace)
        if how:
            return fresh(), f"본문복사 ({how})"
        # ② UI Automation 글자 읽기
        if uia_available():
            log("화면의 글자 정보를 읽는 중…")
            t = uia_text(hwnd)
            trace.append(f"UI Automation 글자: {len(t)}자")
            if len(t) > 80:
                return t, "화면 글자 정보"
        # ③ 표준 편집 칸(Edit·RichEdit)의 글자를 메시지로 읽기
        t = edit_text(hwnd)
        trace.append(f"편집 칸 글자: {len(t)}자")
        if len(t) > 80:
            return t, "편집 칸 글자"
        # ④ 창 화면을 그려 받아(PrintWindow, 가려져 있어도 됨) 글자 인식
        log("화면 글자 인식(OCR)으로 본문을 읽는 중…")
        t = ocr_body(hwnd)
        trace.append(f"OCR 본문: {len(t)}자")
        if len(t) > 80:
            return t, "화면 글자 인식(OCR) — 보이는 부분만"
        # ⑤ 최후 수단: 창을 앞으로 가져와 전체 선택·복사 (설정에서 허용했을 때만)
        if not foreground_allowed():
            trace.append("전체 선택·복사 생략: 창을 앞으로 가져오지 않는 설정")
            return "", ""
        log("문서를 전체 선택·복사하는 중…")
        set_clipboard(marker)
        trace.append(f"창 맨 앞으로: {activate(hwnd)}")
        doc = _largest_child(hwnd) or hwnd
        l, t, r, b = _rect(doc)
        if r - l > 50 and b - t > 50:
            real_click((l + r) // 2, t + (b - t) // 3)
            time.sleep(0.2)
        _hotkey(VK_CONTROL, 0x41)
        time.sleep(0.3)
        _hotkey(VK_CONTROL, 0x43)
        if _wait(lambda: bool(fresh()), 2.5):
            return fresh(), "전체 선택·복사"
        trace.append(f"전체 선택·복사 실패 (문서 영역 클래스: {_class(doc)})")
        return "", ""
    finally:
        if previous:
            set_clipboard(previous)


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
    for _ in range(25):
        time.sleep(0.2)
        new = [d for d in _dialogs_of(pid) if d not in before]
        if not new:
            continue
        dlg = new[0]
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
            log("저장 위치를 공문 폴더로 지정했습니다.")
            return "saved"
        log("저장 창이 열렸습니다. 저장 위치를 지정해 주세요.")
        return "clicked"
    return "clicked"


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
        if ext in PARTIAL_EXT or ext not in DOC_EXT or p.name.startswith(("~$", ".")):
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
            if src.parent.name.lower() == "downloads":
                shutil.move(str(src), target)  # 다운로드 폴더 파일은 옮겨서 정리
            else:
                shutil.copy2(src, target)       # 바탕화면·문서·임시 폴더 파일은 복사
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
    import tempfile
    img = Path(tempfile.gettempdir()) / "seomu_window.png"
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

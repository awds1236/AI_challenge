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
SAVE_NAMES = ("PC저장", "PC 저장", "붙임문서", "붙임 저장", "일괄저장", "모두 저장")
SELF_TITLES = ("서무비서 AI",)


def available() -> bool:
    return IS_WIN


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


def activate(hwnd: int) -> None:
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # 포그라운드 전환 제한 우회: Alt 키를 한 번 눌렀다 뗀다
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.4)


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
        if not h:
            return ""
        p = kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else ""
        finally:
            kernel32.GlobalUnlock(h)
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


def save_window_image(hwnd: int, path: Path) -> bool:
    if not IS_WIN:
        return False
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return False
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        user32.PrintWindow(hwnd, mdc, 2)  # PW_RENDERFULLCONTENT

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
        gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        _png(path, w, h, buf.raw)
        return True
    except Exception:
        return False
    finally:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hwnd, hdc)


# ---------------------------------------------------------------- UI Automation (선택: uiautomation 패키지)
def _uia():
    try:
        import uiautomation as auto  # type: ignore
        return auto
    except Exception:
        return None


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
                    control.GetInvokePattern().Invoke()
                except Exception:
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
    parts: list[str] = []
    with auto.UIAutomationInitializerInThread():
        root = auto.ControlFromHandle(hwnd)
        for c, _depth in auto.WalkControl(root, maxDepth=25):
            try:
                if c.ControlTypeName in ("DocumentControl", "EditControl", "PaneControl", "CustomControl"):
                    tp = c.GetPattern(auto.PatternId.TextPattern)
                    if tp:
                        t = tp.DocumentRange.GetText(-1)
                        if t and len(t.strip()) > 30:
                            parts.append(t)
                            continue
                if c.ControlTypeName in ("TextControl", "DataItemControl", "HyperlinkControl") and c.Name:
                    parts.append(c.Name)
            except Exception:
                continue
            if sum(len(p) for p in parts) > limit:
                break
    # 가장 긴 문서 텍스트를 우선
    parts.sort(key=len, reverse=True)
    best = parts[0] if parts and len(parts[0]) > 200 else "\n".join(dict.fromkeys(parts))
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


def extract_text(hwnd: int, log: Callable[[str], None] = lambda m: None) -> tuple[str, str]:
    """(본문, 사용한 방법)"""
    if not IS_WIN:
        return "", ""
    previous = get_clipboard()
    marker = f"__seomu_{time.time()}__"
    set_clipboard(marker)
    try:
        activate(hwnd)
        # ① 본문복사 버튼
        log("뷰어의 '본문복사' 버튼을 찾는 중…")
        if click_named(hwnd, BODY_COPY_NAMES):
            for _ in range(20):
                time.sleep(0.15)
                t = get_clipboard()
                if t and t != marker and len(t.strip()) > 20:
                    return t, "본문복사 버튼"
        # ② UI Automation
        log("화면의 글자를 읽는 중…")
        t = uia_text(hwnd)
        if len(t) > 80:
            return t, "화면 글자 읽기"
        # ③ Ctrl+A / Ctrl+C
        log("전체 선택·복사로 읽는 중…")
        activate(hwnd)
        _hotkey(VK_CONTROL, 0x41)
        time.sleep(0.2)
        _hotkey(VK_CONTROL, 0x43)
        for _ in range(15):
            time.sleep(0.15)
            t = get_clipboard()
            if t and t != marker and len(t.strip()) > 20:
                return t, "전체 선택·복사"
        return "", ""
    finally:
        if previous:
            set_clipboard(previous)


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


def try_save_attachments(hwnd: int, folder: Path, log: Callable[[str], None] = lambda m: None) -> str:
    """'PC저장'/'붙임문서' 버튼을 누르고, 저장 대화상자가 뜨면 공문 폴더를 지정한다.

    반환: "saved"(대화상자에 경로 입력 완료), "clicked"(버튼만 누름), ""(버튼 없음)
    """
    if not IS_WIN:
        return ""
    pid = _pid(hwnd)
    before = set(_dialogs_of(pid))
    activate(hwnd)
    log("뷰어의 'PC저장/붙임문서' 버튼을 찾는 중…")
    if not click_named(hwnd, SAVE_NAMES):
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

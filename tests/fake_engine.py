"""테스트용 가짜 내장 엔진 실행 파일 (llama-server / llama-server.exe).

POSIX: fake_llama_server.py를 실행하는 셸 스크립트.
Windows: Windows에 기본으로 있는 C# 컴파일러(PowerShell Add-Type)로 작은 llama-server.exe를 만든다.
  이 실행 파일은 fake_llama_server.py를 실행하고, Windows 작업 개체(Job Object)에 넣어
  엔진을 끄면(프로세스 종료) 자식 Python 프로세스도 함께 정리된다.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
IS_WIN = sys.platform.startswith("win")
EXE_NAME = "llama-server.exe" if IS_WIN else "llama-server"

_CS = r"""
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
public static class FakeLlama {
    [DllImport("kernel32.dll")] static extern IntPtr CreateJobObject(IntPtr a, string n);
    [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr j, int c, IntPtr i, uint l);
    [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr j, IntPtr p);
    [StructLayout(LayoutKind.Sequential)] struct BASIC { public long a; public long b; public uint LimitFlags;
        public UIntPtr c; public UIntPtr d; public uint e; public UIntPtr f; public uint g; public uint h; }
    [StructLayout(LayoutKind.Sequential)] struct IOC { public ulong a, b, c, d, e, f; }
    [StructLayout(LayoutKind.Sequential)] struct EXT { public BASIC basic; public IOC io;
        public UIntPtr pm; public UIntPtr jm; public UIntPtr ppm; public UIntPtr pjm; }
    static string Q(string s) { return s.IndexOf(' ') >= 0 || s.Length == 0 ? "\"" + s + "\"" : s; }
    public static int Main(string[] args) {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        EXT ext = new EXT(); ext.basic.LimitFlags = 0x2000;            // 작업 개체가 닫히면 자식도 종료
        int len = Marshal.SizeOf(typeof(EXT)); IntPtr p = Marshal.AllocHGlobal(len);
        Marshal.StructureToPtr(ext, p, false); SetInformationJobObject(job, 9, p, (uint)len);
        StringBuilder sb = new StringBuilder(Q(@"__SCRIPT__"));
        foreach (string a in args) { sb.Append(' '); sb.Append(Q(a)); }
        ProcessStartInfo psi = new ProcessStartInfo(@"__PYTHON__", sb.ToString());
        psi.UseShellExecute = false; psi.CreateNoWindow = true;
        Process proc = Process.Start(psi); AssignProcessToJobObject(job, proc.Handle);
        proc.WaitForExit(); return proc.ExitCode;
    }
}
"""


def _build_exe(out: Path) -> Path:
    src = _CS.replace("__SCRIPT__", str(HERE / "fake_llama_server.py")).replace("__PYTHON__", sys.executable)
    cs = Path(tempfile.gettempdir()) / "seomu_fake_llama.cs"
    cs.write_text(src, encoding="utf-8")
    ps = (f"$src = Get-Content -Raw -Encoding UTF8 '{cs}'; "
          f"Add-Type -TypeDefinition $src -OutputAssembly '{out}' -OutputType ConsoleApplication")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, timeout=120,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if not out.exists():
        raise RuntimeError("가짜 llama-server.exe를 만들 수 없습니다 (C# 컴파일러 없음)")
    return out


_CACHE: dict[str, bytes] = {}


def server_bytes() -> bytes:
    """가짜 엔진 실행 파일의 내용 (압축 파일에 넣을 때)."""
    if "b" not in _CACHE:
        if IS_WIN:
            _CACHE["b"] = _build_exe(Path(tempfile.mkdtemp(prefix="seomu_fake_engine_")) / EXE_NAME).read_bytes()
        else:
            _CACHE["b"] = f"#!/bin/sh\nexec {sys.executable} {HERE / 'fake_llama_server.py'} \"$@\"\n".encode()
    return _CACHE["b"]


def make_server(folder: Path) -> Path:
    """folder 안에 가짜 엔진 실행 파일을 만든다."""
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / EXE_NAME
    exe.write_bytes(server_bytes())
    if not IS_WIN:
        exe.chmod(exe.stat().st_mode | 0o111)
    else:
        _skip_if_blocked(exe)
    return exe


def smart_app_control_on() -> bool:
    """Windows 11 스마트 앱 컨트롤이 켜져 있는지 (1 = 적용 중). 켜져 있으면 서명 없는 실행 파일을 막고 알림을 띄운다."""
    if not IS_WIN:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\CI\Policy") as k:
            return winreg.QueryValueEx(k, "VerifiedAndReputablePolicyState")[0] == 1
    except OSError:
        return False


def _skip_if_blocked(exe: Path) -> None:
    """Windows 스마트 앱 컨트롤·보안 정책이 테스트용(서명 없는) 실행 파일을 막으면 실패 대신 건너뛴다.
    스마트 앱 컨트롤이 켜져 있으면 실행을 시도하지도 않는다: 막힐 때마다 화면에 'Windows 보안' 알림이 뜨기 때문."""
    import pytest
    if smart_app_control_on():
        pytest.skip("스마트 앱 컨트롤이 켜져 있어 테스트용(서명 없는) llama-server.exe를 실행하지 않음 (보안 알림 방지)")
    try:
        subprocess.run([str(exe), "--version"], capture_output=True, timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        if getattr(e, "winerror", None) in (4551, 4552, 1260, 225):
            pytest.skip(f"Windows 보안 정책이 테스트용 llama-server.exe 실행을 막음 (WinError {e.winerror})")
        raise

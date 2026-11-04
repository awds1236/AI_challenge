"""사용 가능한 로컬 AI 모델 목록과 PC 사양에 따른 추천."""
from __future__ import annotations

import ctypes
import os
import platform
import re
import shutil
import subprocess
import sys

# install: "pull" = Ollama 저장소에서 내려받기, "gguf" = GGUF 파일을 받아 등록
CATALOG: list[dict] = [
    {
        "id": "gemma4:e2b-it-qat", "name": "Gemma 4 E2B", "vendor": "Google", "kind": "chat",
        "install": "pull", "download_gb": 4.5, "min_ram_gb": 8, "license": "Apache 2.0",
        "badge": "기본 · 추천", "korean": "다국어", "variant": "QAT 경량판",
        "alt": ["gemma4:e2b", "gemma4:e2b-it-q4_K_M"],
        "desc": "일반 사무용 PC(RAM 8GB 이상)용 기본 모델. 품질 손실을 줄인 4비트 경량판(QAT)으로 "
                "같은 4비트 크기에서 품질 손실이 가장 적습니다. 라이선스가 명확해 기관 배포에 적합합니다. "
                "(일반판 gemma4:e2b를 받아도 사용할 수 있습니다)",
    },
    {
        "id": "gemma4:e4b-it-qat", "name": "Gemma 4 E4B", "vendor": "Google", "kind": "chat",
        "install": "pull", "download_gb": 6.1, "min_ram_gb": 16, "license": "Apache 2.0",
        "badge": "고성능", "korean": "다국어", "variant": "QAT 경량판",
        "alt": ["gemma4:e4b", "gemma4:latest", "gemma4:e4b-it-q4_K_M"],
        "desc": "답변 품질이 더 좋은 상위 모델(QAT 경량판). 여유 메모리 8GB 이상 권장. "
                "구형 CPU에서는 답변이 느릴 수 있습니다.",
    },
    {
        "id": "kanana-2:3b", "name": "Kanana-2 3B", "vendor": "Kakao", "kind": "chat",
        "install": "gguf", "download_gb": 2.0, "min_ram_gb": 6, "license": "Kanana Open License",
        "badge": "국산 · 한국어 특화", "korean": "한국어 특화",
        "hf": "https://huggingface.co/models?search=kanana-2-3b-instruct%20gguf",
        "desc": "한국어 대화 성능이 높은 국산 경량 모델. GGUF 파일(Q4_K_M)을 받아 등록합니다. "
                "기관 배포 전 라이선스 원문을 확인하세요.",
    },
    {
        "id": "kanana-2:1.3b", "name": "Kanana-2 1.3B", "vendor": "Kakao", "kind": "chat",
        "install": "gguf", "download_gb": 1.0, "min_ram_gb": 4, "license": "Kanana Open License",
        "badge": "국산 · 초경량", "korean": "한국어 특화",
        "hf": "https://huggingface.co/models?search=kanana-2-1.3b-instruct%20gguf",
        "desc": "가장 가벼운 한국어 모델. 저사양 PC에서 빠르게 동작합니다.",
    },
    {
        "id": "embeddinggemma", "name": "EmbeddingGemma", "vendor": "Google", "kind": "embed",
        "install": "pull", "download_gb": 0.6, "min_ram_gb": 2, "license": "Gemma Terms",
        "badge": "검색 보조", "korean": "다국어",
        "desc": "규정 검색 정확도를 높이는 의미 검색용 모델 (선택). 설치 후 '전체 재색인'을 실행하세요.",
    },
]


def find(model_id: str) -> dict | None:
    return next((m for m in CATALOG if m["id"] == model_id), None)


def names(entry: dict) -> list[str]:
    """카드 하나에 해당하는 모든 모델 이름 (QAT판·일반판 등 같은 계열 포함)."""
    out = []
    for n in [entry["id"], *entry.get("alt", [])]:
        out.append(n)
        if ":" not in n:
            out.append(n + ":latest")
    return out


def installed_id(entry: dict, installed: list[str]) -> str:
    """설치된 이름을 돌려준다 (기본 이름 우선). 없으면 빈 문자열."""
    for n in names(entry):
        if n in installed:
            return n
    return ""


def is_installed(model_id: str, installed: list[str]) -> bool:
    entry = find(model_id) or {"id": model_id}
    return bool(installed_id(entry, installed))


# ---------------------------------------------------------------- PC 사양
def _memory_gb() -> tuple[float, float]:
    """(전체, 사용 가능) GB"""
    try:
        if sys.platform.startswith("win"):
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))  # type: ignore[attr-defined]
            return st.ullTotalPhys / 2**30, st.ullAvailPhys / 2**30
        if os.path.exists("/proc/meminfo"):
            info = {}
            for line in open("/proc/meminfo"):
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
            return info["MemTotal"] / 2**30, info.get("MemAvailable", info["MemFree"]) / 2**30
        if sys.platform == "darwin":
            total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
            return total / 2**30, total / 2**30 * 0.5
    except Exception:
        pass
    return 0.0, 0.0


def _cpu_name() -> str:
    try:
        if sys.platform.startswith("win"):
            import winreg  # type: ignore
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        if os.path.exists("/proc/cpuinfo"):
            for line in open("/proc/cpuinfo"):
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "알 수 없음"


def _gpu() -> str:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return ""
    try:
        out = subprocess.check_output([exe, "--query-gpu=name,memory.total,compute_cap", "--format=csv,noheader"],
                                      timeout=5, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.strip().splitlines()[0]
    except Exception:
        return ""


def system_info() -> dict:
    total, avail = _memory_gb()
    gpu = _gpu()
    usable_gpu = False
    m = re.search(r",\s*(\d+)\s*MiB,\s*([\d.]+)", gpu)
    if m and float(m.group(2)) >= 5.0 and int(m.group(1)) >= 4000:
        usable_gpu = True
    try:
        free_disk = shutil.disk_usage(os.path.expanduser("~")).free / 2**30
    except OSError:
        free_disk = 0.0
    return {"cpu": _cpu_name(), "cores": os.cpu_count() or 0, "ram_total_gb": round(total, 1),
            "ram_avail_gb": round(avail, 1), "gpu": gpu, "gpu_usable": usable_gpu,
            "disk_free_gb": round(free_disk, 1)}


def recommend(info: dict) -> dict:
    """PC 사양으로 답변 모델을 추천한다.

    순간 여유 메모리는 다운로드·다른 프로그램에 따라 크게 바뀌므로 추천은 전체 메모리로 정하고,
    여유 메모리는 경고에만 쓴다.
    """
    total, avail = info.get("ram_total_gb", 0), info.get("ram_avail_gb", 0)
    if info.get("gpu_usable") or total >= 24:
        mid, why = "gemma4:e4b-it-qat", "메모리가 넉넉해 고성능 모델(E4B)을 쓸 수 있습니다."
    elif total >= 7.5:
        mid, why = "gemma4:e2b-it-qat", "일반 사무용 PC 사양입니다. 기본 모델(E2B)을 권장합니다."
        if total >= 15:
            why += " 다른 프로그램을 닫아 여유 메모리가 8GB 이상이면 E4B도 시도할 수 있습니다."
    elif total >= 5.5:
        mid, why = "kanana-2:3b", "메모리가 적어 가벼운 한국어 모델을 권장합니다."
    else:
        mid, why = "kanana-2:1.3b", "저사양 PC입니다. 초경량 모델을 권장합니다."
    if not info.get("gpu_usable"):
        why += " AI는 CPU로 동작합니다."
    warn = ""
    if total and avail < 4:
        warn = (f"현재 여유 메모리가 {avail}GB로 적습니다. AI 사용 전에 다른 프로그램(브라우저 탭 등)을 "
                "닫으면 답변이 빨라집니다.")
    return {"model": mid, "reason": why, "warn": warn}

"""설정 및 로컬 데이터 경로 관리.

모든 데이터는 사용자 PC 안(앱 데이터 폴더, 다운로드 폴더)에만 저장된다.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def default_home() -> Path:
    env = os.environ.get("SEOMU_HOME")
    if env:
        return Path(env).expanduser()
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "SeomuAI"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SeomuAI"
    return Path.home() / ".seomu_ai"


def default_downloads() -> Path:
    env = os.environ.get("SEOMU_DOWNLOADS")
    if env:
        return Path(env).expanduser()
    return Path.home() / "Downloads"


@dataclass
class Settings:
    # 로컬 AI 엔진: auto(내장 엔진+모델 파일이 있으면 내장, 없으면 Ollama) / builtin / ollama
    engine: str = "auto"
    threads: int = 0              # 내장 엔진 CPU 스레드 수 (0 = 자동)

    # 로컬 LLM (Ollama) 설정
    ollama_url: str = "http://127.0.0.1:11434"
    chat_model: str = ""          # 비워두면 설치된 gemma 계열 모델을 자동 선택
    embed_model: str = ""         # 비워두면 키워드(BM25) 검색만 사용
    temperature: float = 0.2
    num_ctx: int = 8192
    allow_remote_llm: bool = False  # True가 아니면 루프백(127.0.0.1/localhost) 주소만 허용

    # 저장소
    regulation_dirs: list[str] = field(default_factory=list)
    excluded_docs: list[str] = field(default_factory=list)      # 저장소에서 뺀 규정 (외부 폴더 원본은 지우지 않는다)
    doc_categories: dict = field(default_factory=dict)          # 규정별로 직접 정한 분류 {경로: 조례/법령/내규/지침/서식/기타}
    download_root: str = ""       # 비워두면 <다운로드>/서무비서
    top_k: int = 6

    # 공문 수집
    browser_channel: str = ""     # "msedge" / "chrome" / "" (내장 Chromium)
    browser_headless: bool = False
    # 열린 창 수집에서 본문을 못 읽었을 때 창을 앞으로 가져와 전체 선택·복사·화면 클릭까지 시도할지
    # (기본: 하지 않음 — 보고 있던 화면을 가로채지 않고 뒤에 있는 창에서만 읽는다)
    capture_foreground: bool = True
    # 본문을 화면 글자 인식(OCR)으로 읽을지 (기본 끔: 도구모음·메뉴 글자가 섞이고 틀린 글자가 생긴다.
    # 본문복사 버튼 → 전체 선택·복사로 글자를 그대로 가져온다)
    capture_ocr_body: bool = False

    # 사용자 정보 (메일 서명 등)
    user_name: str = ""
    user_dept: str = ""
    user_phone: str = ""
    user_email: str = ""

    theme: str = "system"         # system / light / dark

    def resolved_download_root(self) -> Path:
        if self.download_root:
            return Path(self.download_root).expanduser()
        return default_downloads() / "서무비서"


NUMBER_LABELS = {"top_k": "검색 결과 수", "temperature": "답변 창의성(temperature)", "num_ctx": "문맥 길이",
                 "threads": "CPU 스레드 수"}


class Config:
    """settings.json 읽기/쓰기 (스레드 안전)."""

    def __init__(self, home: Path | None = None):
        self.home = Path(home) if home else default_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "settings.json"
        self.db_path = self.home / "seomu.db"
        self.browser_profile = self.home / "browser_profile"
        self._lock = threading.Lock()
        self.settings = self._load()

    def _load(self) -> Settings:
        s = Settings()
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                names = {f.name for f in fields(Settings)}
                for k, v in data.items():
                    if k in names:
                        setattr(s, k, v)
            except (OSError, json.JSONDecodeError):
                pass
        if not s.regulation_dirs:
            default_repo = self.home / "regulations"
            default_repo.mkdir(parents=True, exist_ok=True)
            s.regulation_dirs = [str(default_repo)]
        return s

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self.settings), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def update(self, values: dict) -> Settings:
        names = {f.name: f for f in fields(Settings)}
        new: dict = {}
        for k, v in values.items():
            if k not in names:
                continue
            cur = getattr(self.settings, k)
            if isinstance(cur, bool):
                v = bool(v)
            elif isinstance(cur, (int, float)):
                if v is None or str(v).strip() == "":
                    continue                      # 숫자 칸을 비워 두면 원래 값을 그대로 둔다
                try:
                    v = int(float(v)) if isinstance(cur, int) else float(v)
                except (TypeError, ValueError):
                    raise ValueError(f"'{NUMBER_LABELS.get(k, k)}' 칸에는 숫자를 입력하세요 (입력한 값: {v})") from None
            elif isinstance(cur, list):
                v = [str(x) for x in (v or []) if str(x).strip()]
            elif isinstance(cur, dict):
                v = {str(a): str(b) for a, b in dict(v or {}).items() if str(a).strip() and str(b).strip()}
            else:
                v = "" if v is None else str(v)
            new[k] = v
        for k, v in new.items():               # 모든 값을 확인한 뒤에 한꺼번에 바꾼다 (중간 오류로 일부만 바뀌지 않게)
            setattr(self.settings, k, v)
        self.save()
        return self.settings

    def as_dict(self) -> dict:
        d = asdict(self.settings)
        d["_home"] = str(self.home)
        d["_download_root"] = str(self.settings.resolved_download_root())
        return d

"""GUI(웹뷰)에서 호출하는 애플리케이션 API.

오래 걸리는 작업(AI 답변, 색인, 공문 수집)은 '작업(job)'으로 실행하고
화면은 job_status()로 진행 상황과 스트리밍 텍스트를 받아 간다.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from . import APP_NAME, __version__
from .analyzer import analyze, summary_markdown
from .collector import (BrowserWorker, Captured, analyze_html, checked_download, clean_title, collect_from_files,
                        collect_from_text, collect_from_url, download_url, expand_archives, make_notice_folder,
                        safe_name, save_body, unique_path)
from .config import Config
from .deadlines import dday
from .notice_text import short_task, tidy_text
from .engine import ENGINE_MISSING, LocalClient, LocalEngine, add_model_file, ollama_model_blob
from .llm import LLMError, OllamaClient
from . import models as model_catalog
from . import attach, downloader, forms as forms_mod, guide as guide_mod, polish as polish_mod, winwindow
from .mail import DEFAULT_TEMPLATES, POLISH_PROMPT, VARIABLES, build_variables, clean_polished, render, tasks_to_ics
from .parsers import READABLE_EXT
from .rag import RAGEngine
from . import report as report_mod
from .storage import Store


def _has_open_program(ext: str) -> bool:
    """이 확장자를 여는 프로그램이 Windows에 연결돼 있는지 (알 수 없으면 있다고 본다)."""
    if not sys.platform.startswith("win") or not ext:
        return True
    try:
        import ctypes
        from ctypes import wintypes
        shlwapi = ctypes.WinDLL("shlwapi")
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        # ASSOCF_INIT_IGNOREUNKNOWN(0x400): 연결이 없으면 '알 수 없는 형식' 대신 실패를 돌려준다 / ASSOCSTR_EXECUTABLE(2)
        hr = shlwapi.AssocQueryStringW(0x400, 2, ext, "open", buf, ctypes.byref(size))
        return hr == 0 and bool(buf.value)
    except Exception:
        return True


class Job:
    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.status = "running"     # running / done / error
        self.message = ""
        self.text = ""              # 스트리밍 누적 텍스트
        self.result = None
        self.error = ""
        self.started = datetime.now()
        self.flags: dict = {}       # 화면에서 보내는 신호 (예: 붙임 수집 완료)

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status, "message": self.message,
                "text": self.text, "result": self.result, "error": self.error}


class Api:
    def __init__(self, home: Path | None = None):
        self._cfg = Config(home)
        self._engine = LocalEngine(self._cfg.home)
        self._engine_install: dict = {"state": "", "message": ""}    # 엔진 자동 받기 상태 (화면 표시용)
        self._engine_install_lock = threading.Lock()
        self._store = Store(self._cfg.db_path)
        self._rag = RAGEngine(self._store, self._client, lambda: self._cfg.settings)
        self._jobs: dict[str, Job] = {}
        self._browser: BrowserWorker | None = None
        self._window = None
        self._tidy_task_titles()
        if not self._store.list_templates():
            for t in DEFAULT_TEMPLATES:
                self._store.save_template(t["name"], t["subject"], t["body"])

    def _tidy_task_titles(self) -> None:
        """예전 형식('[공문 이름] 긴 문장')으로 자동 등록된 할 일 제목을 짧은 제목으로 바꾼다 (한 번만 바뀐다)."""
        try:
            for t in self._store.list_tasks():
                title = t.get("title") or ""
                if t.get("notice_id") and title.startswith("["):
                    self._store.update_task(t["id"], title=short_task(title),
                                            detail=(t.get("detail") or "") + f"\n내용: {title}")
        except Exception:  # 정리 실패가 시작을 막지 않게
            logging.getLogger("seomu").warning("할 일 제목 정리 실패", exc_info=True)

    # ------------------------------------------------------------ 내부 유틸
    def _engine_kind(self) -> str:
        e = self._cfg.settings.engine
        if e in ("builtin", "ollama"):
            return e
        return "builtin" if self._engine.available() else "ollama"

    def _client(self):
        s = self._cfg.settings
        if self._engine_kind() == "builtin":
            return LocalClient(self._engine, ctx=s.num_ctx, threads=s.threads)
        return OllamaClient(s.ollama_url, allow_remote=s.allow_remote_llm, num_ctx=s.num_ctx)

    def engine_info(self) -> dict:
        return {"kind": self._engine_kind(), "setting": self._cfg.settings.engine,
                "server": self._engine.server_path(), "models": list(self._engine.models()),
                "model_dir": str(self._engine.writable_model_dir()), "running": self._engine.running(),
                "engine_dir": str(self._engine.writable_engine_dir()),
                "need_engine": self._engine.missing_engine(), "install": dict(self._engine_install)}

    def _run_job(self, kind: str, fn: Callable[[Job], object]) -> dict:
        job = Job(kind)
        self._jobs[job.id] = job

        def runner():
            try:
                job.result = fn(job)
                job.status = "done"
            except Exception as e:  # 모든 오류를 화면에 전달
                job.error = str(e) or e.__class__.__name__
                job.status = "error"
                logging.getLogger("seomu.job").warning("작업 %s 오류", kind, exc_info=True)
        threading.Thread(target=runner, daemon=True, name=f"job-{kind}").start()
        # 오래된 작업 정리
        if len(self._jobs) > 50:
            for k in sorted(self._jobs, key=lambda k: self._jobs[k].started)[:-50]:
                if self._jobs[k].status != "running":
                    self._jobs.pop(k, None)
        return {"job_id": job.id}

    def heartbeat(self) -> bool:
        """화면이 몇 초마다 보내는 신호 (앱 창이 열려 있는지 판단)."""
        self._heartbeat = time.time()
        return True

    def last_heartbeat(self) -> float:
        return getattr(self, "_heartbeat", 0.0)

    def job_status(self, job_id: str) -> dict:
        job = self._jobs.get(job_id)
        return job.to_dict() if job else {"status": "error", "error": "작업을 찾을 수 없습니다"}

    @staticmethod
    def _open_os(path: str) -> None:
        if sys.platform.startswith("win"):
            if os.environ.get("SEOMU_OPEN_MINIMIZED"):
                # 시험용: 연 프로그램을 최소화·비활성으로 띄워 사용자가 보던 화면을 가리지 않는다
                os.startfile(path, "open", show_cmd=7)  # type: ignore[attr-defined]  # SW_SHOWMINNOACTIVE
            else:
                os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    # ------------------------------------------------------------ 상태/설정
    def app_info(self) -> dict:
        return {"name": APP_NAME, "version": __version__, "home": str(self._cfg.home),
                "browser_available": BrowserWorker.available(),
                "windows_available": winwindow.available(), "uia_available": winwindow.uia_available(),
                "native": self._window is not None}

    def get_settings(self) -> dict:
        return self._cfg.as_dict()

    def save_settings(self, values: dict) -> dict:
        old_dirs = list(self._cfg.settings.regulation_dirs)
        self._cfg.update(values or {})
        if self._browser and ("browser_channel" in values or "browser_headless" in values):
            self._browser.close()
            self._browser = None
        if old_dirs != self._cfg.settings.regulation_dirs:
            self._rag.invalidate()
        return self._cfg.as_dict()

    def llm_status(self) -> dict:
        c = self._client()
        st = c.status()
        s = self._cfg.settings
        if st["ok"]:
            try:
                st["chat_model"] = c.pick_chat_model(s.chat_model)
            except LLMError as e:
                st["chat_model"] = ""
                st["error"] = str(e)
            st["embed_model"] = c.pick_embed_model(s.embed_model)
        st["local_only"] = not s.allow_remote_llm or self._engine_kind() == "builtin"
        st["engine"] = self._engine_kind()
        # 모델 파일은 있는데 실행 엔진(llama-server)만 없다 → '모델 없음'이 아니라 '엔진 없음'으로 알린다
        st["need_engine"] = not st["ok"] and s.engine != "ollama" and self._engine.missing_engine()
        st["engine_install"] = dict(self._engine_install)
        if st["need_engine"]:
            st["error"] = ENGINE_MISSING
            if self._engine_install["state"] == "running":
                st["error"] = "모델 파일은 있고, AI 실행 엔진(llama-server)을 받는 중입니다. 잠시 뒤 자동으로 AI 분석을 씁니다."
            elif self._engine_install["state"] == "error":
                st["error"] = ENGINE_MISSING + f" (자동 받기 실패: {self._engine_install['message']})"
        if not st["ok"] and st["engine"] == "ollama" and self._engine.available():
            # Ollama를 골랐는데 꺼져 있다: 이 PC에는 내장 엔진·모델이 있으니 받을 필요 없이 바꾸기만 하면 된다
            st["error"] = ("Ollama가 실행 중이 아닙니다. 이 PC에는 내장 AI 엔진과 모델이 이미 있으니, 설정 → AI 엔진을 "
                           "[자동] 또는 [내장 엔진]으로 바꾸면 바로 쓸 수 있습니다 (Ollama를 쓰시려면 Ollama를 실행해 주세요).")
        return st

    # ------------------------------------------------------------ 모델 관리
    def model_catalog(self) -> dict:
        client = self._client()
        st = client.status()
        installed = st.get("models", [])
        s = self._cfg.settings
        info = model_catalog.system_info()
        try:
            active_chat = client.pick_chat_model(s.chat_model) if st["ok"] else s.chat_model
        except LLMError:
            active_chat = s.chat_model
        active_embed = client.pick_embed_model(s.embed_model) if st["ok"] else s.embed_model
        items, known = [], set()
        for m in model_catalog.CATALOG:
            d = dict(m)
            all_names = model_catalog.names(m)
            known.update(all_names)
            d["installed_id"] = model_catalog.installed_id(m, installed)
            d["installed"] = bool(d["installed_id"])
            d["active"] = any(n in (active_chat, active_embed) for n in all_names) or \
                (bool(d["installed_id"]) and d["installed_id"] in (active_chat, active_embed))
            d["fits"] = info["ram_total_gb"] == 0 or info["ram_total_gb"] >= m["min_ram_gb"] * 0.9
            d["can_download"] = bool(m.get("dl"))
            items.append(d)
        if self._engine_kind() == "builtin":
            for d in items:            # Ollama에 받아 둔 모델이면 내장 엔진으로 옮겨올 수 있다
                d["ollama_blob"] = next((n for n in model_catalog.names(d) if ollama_model_blob(n)), "")
        known.update(n for d in items if d["installed_id"] for n in [d["installed_id"]])
        if self._engine_kind() == "builtin" or not st["ok"]:
            # 내장 엔진(또는 Ollama가 꺼져 있어 내장 엔진으로 받을 때)은 이 PC의 모델 파일로 설치 여부를 본다
            files = list(self._engine.models())
            for d in items:
                d["file_installed"] = model_catalog.installed_id(model_catalog.find(d["id"]) or d, files)
        return {"engine_ok": st["ok"], "engine_error": st.get("error", ""), "models": items,
                "engine": self.engine_info(),
                "others": [m for m in installed if m not in known], "active_chat": active_chat,
                "active_embed": active_embed, "system": info, "recommend": model_catalog.recommend(info)}

    def use_model(self, model_id: str) -> dict:
        m = model_catalog.find(model_id)
        key = "embed_model" if (m and m["kind"] == "embed") or "embed" in model_id else "chat_model"
        self.save_settings({key: model_id})
        if key == "embed_model":
            self._rag.invalidate()
        return self.model_catalog()

    def _progress(self, job: Job):
        def cb(obj: dict):
            total, done = obj.get("total"), obj.get("completed")
            pct = f" {done / total * 100:.0f}%" if total and done is not None else ""
            if total and done is not None and total > 50 << 20:   # 큰 파일은 받은 용량도 보여 준다
                pct += f" ({done / (1 << 30):.1f}/{total / (1 << 30):.1f}GB)"
            job.message = f"{obj.get('status', '진행 중')}{pct}"
            job.text = f"{done or 0}/{total or 0}"
        return cb

    def pull_model(self, model_id: str, alias: str = "") -> dict:
        """모델 다운로드. alias를 주면(예: hf.co/... → kanana-2:3b) 그 이름으로도 등록한다."""
        model_id = (model_id or "").strip()
        if not model_id:
            raise ValueError("모델 이름을 입력하세요")

        def work(job: Job):
            job.message = "다운로드 준비 중…"
            client = self._client()
            client.pull(model_id, self._progress(job))
            if alias and alias != model_id:
                client.copy(model_id, alias)
                client.delete(model_id)
            return self.model_catalog()
        return self._run_job("pull", work)

    def download_model(self, model_id: str) -> dict:
        """[받기]: 내장 엔진이 없으면 엔진부터 받고, 모델 공식 파일(GGUF)을 받아 바로 쓰게 한다 (Ollama 불필요)."""
        m = model_catalog.find(model_id)
        if not m or not m.get("dl"):
            raise ValueError("자동으로 받을 수 없는 모델입니다. '파일 추가'로 GGUF 파일을 지정해 주세요.")

        def work(job: Job):
            cb = self._progress(job)
            self._engine.stop()
            if not self._engine.server_path():
                job.message = "AI 엔진 받는 중…"
                downloader.install_engine(self._engine.writable_engine_dir(), cb)
                self._engine.forget_server()
            path = downloader.download_model(m["dl"], self._engine.writable_model_dir(), cb)
            values = {"embed_model" if m["kind"] == "embed" else "chat_model": path.stem}
            if self._cfg.settings.engine == "ollama":
                values["engine"] = "auto"        # 받은 내장 엔진을 바로 쓰도록
            self.save_settings(values)
            if m["kind"] == "embed":
                self._rag.invalidate()
            return self.model_catalog()
        return self._run_job("download", work)

    def import_gguf(self, path: str, model_id: str) -> dict:
        p = Path(path or "")
        if not p.is_file() or p.suffix.lower() != ".gguf":
            raise ValueError("GGUF(.gguf) 파일을 선택하세요")
        name = (model_id or p.stem).strip().lower()
        if self._engine_kind() == "builtin":
            entry = model_catalog.find(model_id) or {}
            keep = model_catalog.installed_id(entry, [p.stem]) if entry else p.stem
            name = keep or (model_id or p.stem).replace(":", "-")

        def work(job: Job):
            self._client().create_from_gguf(name, str(p), self._progress(job))
            return self.model_catalog()
        return self._run_job("import", work)

    def import_from_ollama(self, model_id: str) -> dict:
        """Ollama로 받아 둔 모델 파일을 내장 엔진 models 폴더로 복사 (Ollama가 꺼져 있어도 됨)."""
        entry = model_catalog.find(model_id) or {"id": model_id}
        src_name = next((n for n in model_catalog.names(entry) if ollama_model_blob(n)), "")
        if not src_name:
            raise ValueError("Ollama에 받아 둔 이 모델을 찾을 수 없습니다.")
        blob = ollama_model_blob(src_name)

        def work(job: Job):
            add_model_file(self._engine, str(blob), src_name.replace(":", "-"), self._progress(job))
            return self.model_catalog()
        return self._run_job("import", work)

    def install_engine(self) -> dict:
        """[AI 엔진 받기]: 모델 파일은 그대로 두고 실행 엔진(llama.cpp llama-server)만 받는다."""
        def work(job: Job):
            job.message = "AI 엔진 받는 중…"
            self._install_engine_now(self._progress(job))
            return self.model_catalog()
        return self._run_job("engine", work)

    def import_engine(self, path: str) -> dict:
        """[엔진 파일 지정]: 받아 둔 llama.cpp 압축 파일(.zip)이나 llama-server.exe로 엔진을 넣는다 (인터넷 불필요)."""
        if not (path or "").strip():
            raise ValueError("llama.cpp 압축 파일(.zip)이나 llama-server.exe를 지정하세요")

        def work(job: Job):
            job.message = "AI 엔진 파일을 넣는 중…"
            self._engine.stop()
            downloader.install_engine_from(path, self._engine.writable_engine_dir())
            self._engine.forget_server()
            self._engine_install = {"state": "done", "message": ""}
            if self._cfg.settings.engine == "ollama":
                self.save_settings({"engine": "auto"})
            return self.model_catalog()
        return self._run_job("engine", work)

    def _install_engine_now(self, on_progress=None) -> None:
        with self._engine_install_lock:
            self._engine.forget_server()
            if self._engine.server_path():
                self._engine_install = {"state": "done", "message": ""}
                return
            self._engine_install = {"state": "running", "message": ""}
            try:
                self._engine.stop()
                downloader.install_engine(self._engine.writable_engine_dir(), on_progress)
            except Exception as e:
                self._engine_install = {"state": "error", "message": (str(e) or e.__class__.__name__)[:300]}
                raise
            finally:
                self._engine.forget_server()
            self._engine_install = {"state": "done", "message": ""}
            if self._cfg.settings.engine == "ollama":
                self.save_settings({"engine": "auto"})

    def set_engine(self, kind: str) -> dict:
        if kind not in ("auto", "builtin", "ollama"):
            raise ValueError("엔진 종류가 올바르지 않습니다")
        self._engine.stop()
        self.save_settings({"engine": kind})
        return self.model_catalog()

    def delete_model(self, model_id: str) -> dict:
        self._client().delete(model_id)
        s = self._cfg.settings
        if model_id in (s.chat_model, s.embed_model):
            self.save_settings({"chat_model" if model_id == s.chat_model else "embed_model": ""})
        return self.model_catalog()

    def dashboard(self) -> dict:
        today = date.today()
        tasks = self._store.list_tasks(include_done=False)
        for t in tasks:
            t["dday"] = dday(t["due"]) if t.get("due") else None
        upcoming = [t for t in tasks if t["dday"] is not None]
        week_end = (today + timedelta(days=7)).isoformat()
        # '다가오는 기한': 일주일 안에 지난 일 → 다가오는 일 → 기한 없는 일 → 오래 지난 일 순서
        rank = lambda t: (0 if t["dday"] is not None and -7 <= t["dday"] < 0 else  # noqa: E731
                          1 if t["dday"] is not None and t["dday"] >= 0 else 2 if t["dday"] is None else 3,
                          t.get("due") or "9999")
        return {
            "today": today.isoformat(),
            "weekday": "월화수목금토일"[today.weekday()],
            "tasks": sorted(tasks, key=rank)[:20],
            "overdue": sum(1 for t in upcoming if t["dday"] < 0),
            "due_today": sum(1 for t in upcoming if t["dday"] == 0),
            "due_week": sum(1 for t in upcoming if 0 <= t["dday"] and t["due"] <= week_end),
            "open_tasks": len(tasks),
            "documents": len(self._store.list_documents()),
            "notices": self._store.list_notices()[:5],
        }

    # ------------------------------------------------------------ 파일 선택 / 업로드
    def pick_files(self, multiple: bool = True) -> list[str]:
        if not self._window:
            return []
        import webview  # type: ignore
        res = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=bool(multiple))
        return list(res or [])

    def pick_folder(self) -> str:
        if not self._window:
            return ""
        import webview  # type: ignore
        res = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return (res[0] if isinstance(res, (list, tuple)) else res) or ""

    def upload_files(self, files: list[dict]) -> list[str]:
        """드래그&드롭한 파일(base64)을 앱 폴더에 임시 저장하고 경로를 돌려준다."""
        dest = self._cfg.home / "uploads" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dest.mkdir(parents=True, exist_ok=True)
        paths = []
        for f in files or []:
            data = f.get("data", "")
            if "," in data[:100]:
                data = data.split(",", 1)[1]
            p = unique_path(dest / safe_name(f.get("name") or "file", 150))
            p.write_bytes(base64.b64decode(data))
            paths.append(str(p))
        return paths

    def open_path(self, path: str) -> bool:
        if not path or not Path(path).exists():
            return False
        p = Path(path)
        if p.is_file() and sys.platform.startswith("win") and not _has_open_program(p.suffix):
            # 연결 프로그램이 없으면 Windows가 '어떤 앱으로 열까요' 창만 띄운다 → 무엇이 없는지와 대안을 알려 준다
            what = "한글(HWP) 문서를 여는 프로그램(한글·한컴오피스 뷰어)" if p.suffix.lower() in (".hwp", ".hwpx", ".hwx")                 else f"'{p.suffix or '확장자 없는'}' 파일을 여는 프로그램"
            raise ValueError(f"이 PC에는 {what}이 없어 열 수 없습니다. 앱 안의 미리보기로 내용을 보거나, "
                             "공문 폴더에서 파일을 다른 PC로 옮겨 여세요.")
        self._open_os(path)
        return True

    def preview_file(self, path: str, limit: int = 60000) -> dict:
        """붙임·본문 파일의 글자를 앱 안에서 보여 준다 (한글·PDF 뷰어가 없는 PC에서도 내용 확인).
        공문 다운로드 폴더·앱 데이터 폴더·규정 저장소 안의 파일만 읽는다."""
        from .parsers import ParseError, parse_file
        from .notice_text import tidy_text
        p = Path(path or "")
        s = self._cfg.settings
        roots = [s.resolved_download_root(), self._cfg.home] + [Path(d) for d in s.regulation_dirs]
        try:
            rp = p.resolve()
            allowed = p.is_file() and any(rp.is_relative_to(r.resolve()) for r in roots)
        except (OSError, ValueError):
            allowed = False
        if not allowed:
            raise ValueError("미리 볼 수 없는 파일입니다 (공문 폴더 안의 파일만 볼 수 있습니다)")
        try:
            text = tidy_text(parse_file(p))
            err = ""
        except ParseError as e:
            text, err = "", str(e)
        except (OSError, ValueError, KeyError) as e:
            text, err = "", f"파일을 읽을 수 없습니다: {e}"
        if not text and not err:
            err = "글자가 없는 파일입니다"
        return {"name": p.name, "path": str(p), "text": text[:limit], "truncated": len(text) > limit,
                "chars": len(text), "error": err,
                "hint": "" if not err else "이 형식은 내용을 미리 볼 수 없습니다. [파일 열기]로 PC의 프로그램에서 열어 보세요."}

    # ------------------------------------------------------------ 규정 저장소 (RAG)
    REG_CATEGORIES = ("법령", "조례", "내규", "지침", "서식", "기타")

    def _managed_reg_dir(self) -> Path:
        """화면에서 추가한 규정의 사본을 두는 프로그램 전용 폴더 (여기 있는 사본만 삭제한다)."""
        d = self._cfg.home / "regulations"
        d.mkdir(parents=True, exist_ok=True)
        if str(d) not in self._cfg.settings.regulation_dirs:
            self.save_settings({"regulation_dirs": [str(d)] + list(self._cfg.settings.regulation_dirs)})
        return d

    def _is_managed(self, path: str | Path) -> bool:
        try:
            Path(path).resolve().relative_to((self._cfg.home / "regulations").resolve())
            return True
        except ValueError:
            return False

    def list_documents(self) -> dict:
        docs = self._store.list_documents()
        for d in docs:
            d["managed"] = self._is_managed(d["path"])
        excluded = [{"path": p, "name": Path(p).name, "exists": Path(p).exists()}
                    for p in self._cfg.settings.excluded_docs]
        return {"documents": docs, "dirs": self._cfg.settings.regulation_dirs, "progress": self._rag.progress,
                "excluded": excluded, "categories": list(self.REG_CATEGORIES),
                "managed_dir": str(self._cfg.home / "regulations")}

    def delete_regulation(self, path: str) -> dict:
        """규정을 저장소에서 뺀다. 화면에서 추가한 사본은 지우고, 연결한 폴더의 원본 파일은 지우지 않고 제외 목록에 넣는다."""
        p = Path(path or "")
        key = str(p.resolve()) if str(path or "").strip() else ""
        if not key or not self._store.get_document(key) and not p.exists():
            raise ValueError("저장소에 없는 규정입니다")
        if self._is_managed(p):
            p.unlink(missing_ok=True)
            mode = "deleted"
        else:
            ex = [x for x in self._cfg.settings.excluded_docs if x != key] + [key]
            self.save_settings({"excluded_docs": ex})
            mode = "excluded"
        cats = dict(self._cfg.settings.doc_categories or {})
        if mode == "deleted" and cats.pop(key, None) is not None:     # 제외만 한 규정은 다시 넣을 때 분류를 되살린다
            self.save_settings({"doc_categories": cats})
        self._store.delete_document(key)
        self._rag.invalidate()
        return {"mode": mode, "name": p.name}

    def restore_regulation(self, path: str) -> dict:
        """제외했던 규정을 다시 저장소에 넣는다 (다시 색인)."""
        ex = [x for x in self._cfg.settings.excluded_docs if x != path]
        self.save_settings({"excluded_docs": ex})
        return self.reindex(False)

    def set_regulation_category(self, path: str, category: str) -> bool:
        if category not in self.REG_CATEGORIES:
            raise ValueError("분류는 " + "·".join(self.REG_CATEGORIES) + " 중에서 고르세요")
        key = str(Path(path).resolve())
        cats = dict(self._cfg.settings.doc_categories or {})
        cats[key] = category
        self.save_settings({"doc_categories": cats})
        self._store.set_document_category(key, category)
        self._rag.invalidate()
        return True

    def replace_regulation(self, path: str, new_file: str) -> dict:
        """개정된 규정으로 바꾼다: 새 파일을 추가하고 예전 규정은 저장소에서 뺀다."""
        src = Path(new_file or "")
        if not src.is_file() or src.suffix.lower() not in READABLE_EXT:
            raise ValueError("규정 파일(HWP·HWPX·PDF·DOCX·XLSX·TXT 등)을 고르세요")
        old = Path(path)
        if old.resolve() != src.resolve():
            same_place = self._is_managed(old) and old.name == src.name
            if not same_place:                 # 같은 이름이면 사본을 덮어쓰므로 지우지 않는다
                self.delete_regulation(path)
        return self.import_regulations([str(src)])

    def add_regulation_dir(self, path: str) -> dict:
        if not path or not Path(path).exists():
            raise ValueError("존재하지 않는 경로입니다")
        dirs = list(self._cfg.settings.regulation_dirs)
        if path not in dirs:
            dirs.append(path)
        return self.save_settings({"regulation_dirs": dirs})

    def remove_regulation_dir(self, path: str) -> dict:
        dirs = [d for d in self._cfg.settings.regulation_dirs if d != path]
        return self.save_settings({"regulation_dirs": dirs})

    def import_regulations(self, paths: list[str]) -> dict:
        """파일을 프로그램 전용 규정 폴더로 복사한 뒤 색인 (원본은 그대로 둔다)."""
        target = self._managed_reg_dir()
        copied = []
        for p in paths or []:
            src = Path(p)
            if src.is_file() and src.suffix.lower() in READABLE_EXT:
                dest = target / src.name
                if src.resolve() != dest.resolve():
                    shutil.copy2(src, dest)
                copied.append(dest.name)
                key = str(dest.resolve())          # 예전에 뺐던 같은 규정을 다시 넣으면 제외 목록에서 푼다
                if key in self._cfg.settings.excluded_docs:
                    self.save_settings({"excluded_docs": [x for x in self._cfg.settings.excluded_docs if x != key]})
        return {"copied": copied, **self.reindex(False)}

    def reindex(self, force: bool = False) -> dict:
        def work(job: Job):
            job.message = "색인 중…"
            return self._rag.reindex(force=bool(force))
        return self._run_job("reindex", work)

    def search(self, query: str, category: str = "") -> list[dict]:
        return [h.to_dict() for h in self._rag.search(query, category=category or None)]

    def ask(self, question: str, category: str = "") -> dict:
        question = (question or "").strip()
        if not question:
            raise ValueError("질문을 입력하세요")

        def work(job: Job):
            job.message = "관련 규정을 찾는 중…"
            history = self._store.list_chat(4)

            def on_token(t: str):
                job.message = "답변 작성 중…"
                job.text += t
            res = self._rag.answer(question, category=category or None, on_token=on_token, history=history)
            self._store.add_chat(question, res["answer"], res["sources"])
            return res
        return self._run_job("ask", work)

    def chat_history(self) -> list[dict]:
        return self._store.list_chat(30)

    def clear_chat(self) -> bool:
        self._store.clear_chat()
        return True

    # ------------------------------------------------------------ 상황 안내 (서무비서)
    def guide(self, situation: str, use_ai: bool = True) -> dict:
        """상황을 말하면 규정으로 절차·서식 초안·다음 할 일을 안내한다 (AI가 없어도 규칙으로 동작)."""
        situation = (situation or "").strip()
        if len(situation) < 2:
            raise ValueError("상황을 입력하세요 (예: 다음 주 수요일 대전으로 출장 가요)")

        def work(job: Job):
            job.message = "관련 규정을 찾는 중…"
            client, model = None, ""
            if use_ai:
                try:
                    c = self._client()
                    if c.status().get("ok"):
                        client, model = c, c.pick_chat_model(self._cfg.settings.chat_model)
                except LLMError:
                    client = None
            if client is not None:
                job.message = "절차를 정리하고 로컬 AI가 서식 초안을 다듬는 중…"
            res = guide_mod.make_guide(situation, lambda q: self._rag.search(q), client, model,
                                       num_ctx=self._cfg.settings.num_ctx)
            self._match_org_forms(res)
            res["id"] = self._store.add_guide(situation, res)
            return res
        return self._run_job("guide", work)

    # ---- 기관 서식 (올려 둔 서식 그대로 채우기)
    def _forms(self) -> forms_mod.FormStore:
        return forms_mod.FormStore(self._cfg.home / "forms")

    def _match_org_forms(self, res: dict) -> None:
        store = self._forms()
        for f in res.get("forms") or []:
            f["template"] = store.match(f["name"])

    def list_forms(self) -> dict:
        return {"forms": self._forms().list(), "folder": str(self._cfg.home / "forms")}

    def add_forms(self, paths: list[str]) -> dict:
        """기관 서식(HWPX·DOCX·TXT)을 올린다. 원본은 그대로 두고 프로그램 폴더에 사본을 둔다."""
        added = self._forms().add(paths)
        return dict(self.list_forms(), added=added)

    def delete_form(self, name: str) -> dict:
        self._forms().delete(name)
        return self.list_forms()

    def fill_guide_form(self, guide_id: int, form_index: int, body: str = "", template: str = "") -> dict:
        """상황 안내의 서식 초안을 올려 둔 기관 서식에 채워 새 파일로 저장한다."""
        g = self._store.get_guide(int(guide_id))
        if not g:
            raise ValueError("안내 기록을 찾을 수 없습니다. 상황 안내를 다시 받아 주세요.")
        res = g["result"]
        drafts = res.get("forms") or []
        draft = drafts[int(form_index)] if 0 <= int(form_index) < len(drafts) else {"name": "서식", "body": ""}
        name = (template or draft.get("template") or "").strip()
        path = self._forms().path(name) if name else None
        if not path:
            raise ValueError("채울 기관 서식을 고르세요 (상황 안내 화면의 '기관 서식'에서 서식 파일을 올릴 수 있습니다)")
        s = self._cfg.settings
        profile = {"user_name": s.user_name, "user_dept": s.user_dept, "user_phone": s.user_phone}
        vals = forms_mod.Values(forms_mod.situation_values(res.get("situation") or {}, profile),
                                forms_mod.body_values(body or draft.get("body", "")))
        folder = s.resolved_download_root() / "서식 초안"
        folder.mkdir(parents=True, exist_ok=True)
        out = unique_path(folder / f"{safe_name(path.stem, 60)}_{datetime.now().strftime('%Y%m%d')}{path.suffix.lower()}")
        r = forms_mod.fill_file(path, vals, out)
        return {"path": str(out), "folder": str(folder), "template": path.stem, **r}

    def guide_history(self) -> list[dict]:
        return [{"id": g["id"], "situation": g["situation"], "created_at": g["created_at"],
                 "kind": (g["result"].get("situation") or {}).get("kind", "")} for g in self._store.list_guides(20)]

    def get_guide(self, guide_id: int) -> dict | None:
        g = self._store.get_guide(int(guide_id))
        if not g:
            return None
        return dict(g["result"], id=g["id"])

    def delete_guide(self, guide_id: int) -> bool:
        self._store.delete_guide(int(guide_id))
        return True

    def guide_add_tasks(self, tasks: list[dict]) -> dict:
        """안내의 '다음 할 일'을 할 일 목록에 넣는다 (같은 제목·기한이 이미 있으면 건너뛴다)."""
        have = {(t["title"], t.get("due") or "") for t in self._store.list_tasks(True)}
        added = 0
        for t in tasks or []:
            title = (t.get("title") or "").strip()
            due = (t.get("due") or "").strip()
            if not title or (title, due) in have:
                continue
            if due and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
                due = ""
            self._store.add_task(title, t.get("detail") or "", due or None)
            have.add((title, due))
            added += 1
        return {"added": added}

    def save_guide_form(self, name: str, body: str, fmt: str = "txt") -> dict:
        """서식 초안을 파일로 저장한다 (txt 또는 한글 hwpx). 저장한 경로를 돌려준다."""
        body = (body or "").strip()
        if not body:
            raise ValueError("저장할 초안 내용이 없습니다")
        folder = self._cfg.settings.resolved_download_root() / "서식 초안"
        folder.mkdir(parents=True, exist_ok=True)
        stem = safe_name((name or "서식 초안").strip(), 60) + "_" + datetime.now().strftime("%Y%m%d")
        if fmt == "hwpx":
            tpath = report_mod.builtin_template()
            if not tpath:
                raise ValueError("한글 양식 파일이 없어 hwpx로 저장할 수 없습니다. txt로 저장해 주세요.")
            tpl = report_mod.load_template(tpath)
            outline = report_mod.outline_from_text(body, name or "")
            out = unique_path(folder / f"{stem}.hwpx")
            out.write_bytes(report_mod.fill(tpl, outline, dept=self._cfg.settings.user_dept))
        else:
            out = unique_path(folder / f"{stem}.txt")
            out.write_text(body + "\n", encoding="utf-8")
        return {"path": str(out), "folder": str(folder)}

    # ------------------------------------------------------------ 공문 수집
    def _browser_worker(self) -> BrowserWorker:
        if not BrowserWorker.available():
            raise RuntimeError("브라우저 연동 기능을 쓰려면 `pip install playwright` 후 "
                               "`playwright install chromium`(또는 Edge 사용)을 실행하세요.")
        if self._browser is None:
            s = self._cfg.settings
            self._browser = BrowserWorker(self._cfg.browser_profile, s.browser_channel, s.browser_headless)
        return self._browser

    def browser_open(self, url: str = "") -> dict:
        return self._browser_worker().open(url.strip())

    def browser_pages(self) -> list[dict]:
        if self._browser is None:
            return []
        try:
            return self._browser.pages()
        except Exception:
            return []

    def _sync_tasks(self, nid: int, title: str, analysis: dict) -> None:
        """공문에서 자동 등록한 '진행 중' 할 일을 분석 결과에 맞게 다시 만든다 (완료한 일은 유지)."""
        tasks = [t for t in self._store.list_tasks() if t.get("notice_id") == nid]
        done = {t["due"] for t in tasks if t.get("done")}
        for t in tasks:
            if not t.get("done"):
                self._store.delete_task(t["id"])
        stale = (date.today() - timedelta(days=14)).isoformat()
        for d in analysis.get("deadlines") or []:
            if d["date"] in done:
                continue
            if d["date"] < stale:     # 지난 공문을 뒤늦게 모은 경우: 2주 넘게 지난 기한은 할 일로 만들지 않는다
                continue
            # 제목은 '무엇을 할지'만 짧게 (공문 이름은 화면에서 따로 보여 준다), 원문은 상세에 둔다
            self._store.add_task(short_task(d["what"]),
                                 detail=f"공문: {title}\n내용: {d['what']}" + (f"\n시각: {d['time']}" if d.get("time") else ""),
                                 due=d["date"], notice_id=nid)

    @staticmethod
    def _body_key(text: str) -> str:
        return re.sub(r"\s+", "", text or "")

    def _same_notice(self, text: str) -> dict | None:
        """이미 수집한 공문 중 본문이 똑같은 것 (같은 공문을 다시 수집하면 공문·할 일이 겹쳐 생기던 문제).
        본문을 읽지 못했거나 아주 짧으면 다른 공문일 수 있어 비교하지 않는다."""
        key = self._body_key(text)
        if len(key) < 60 or "본문을읽지못했습니다" in key:
            return None
        for r in self._store.query("SELECT id, body, folder FROM notices ORDER BY id DESC"):
            if self._body_key(r.get("body")) == key and Path(r.get("folder") or "").is_dir():
                return r
        return None

    def _merge_into(self, job: Job, dup: dict, cap: Captured) -> dict:
        """같은 공문을 다시 수집했을 때: 새 공문을 만들지 않고, 이번에 새로 받은 붙임만 기존 공문 폴더에 더한다.
        (완료 표시한 할 일·다시 분석한 결과는 그대로 둔다)"""
        job.message = "이미 수집한 공문입니다 — 새 붙임만 더하는 중…"
        dest = Path(dup["folder"]) / "붙임"
        known = set()
        if dest.is_dir():
            for p in dest.rglob("*"):
                if p.is_file():
                    try:
                        known.add(attach.file_hash(p))
                    except OSError:
                        pass
        added = 0
        for f in cap.files:
            src = Path(f.get("path") or "")
            if not f.get("ok") or not src.is_file():
                continue
            try:
                h = attach.file_hash(src)
            except OSError:
                continue
            if h in known:
                continue
            known.add(h)
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, unique_path(dest / src.name))
            added += 1
        # 이번 수집이 새로 만든 폴더는 지운다 (다운로드 폴더 안, 방금 만든 폴더일 때만)
        try:
            root = self._cfg.settings.resolved_download_root().resolve()
            if cap.folder.exists() and root in cap.folder.resolve().parents \
                    and cap.folder.resolve() != Path(dup["folder"]).resolve():
                shutil.rmtree(cap.folder, ignore_errors=True)
        except OSError:
            pass
        n = self.get_notice(dup["id"]) or {}            # 새로 넣은 붙임을 목록에 반영
        n["duplicate"] = True
        n["added_files"] = added
        job.message = "완료"
        return n

    def _finish_capture(self, job: Job, cap: Captured, use_ai: bool) -> dict:
        """① 규칙 기반 분석으로 바로 저장·표시 → ② 로컬 AI 보완 분석은 백그라운드에서."""
        job.message = "기한·제출물을 찾는 중…"
        # 어느 공문 시스템에서 왔든 같은 모양으로: 빈 줄·특수 공백·메뉴 글자·끊긴 줄 정리
        tidy = tidy_text(cap.text)
        if tidy and tidy != cap.text:
            cap.text = tidy
            save_body(cap.folder, cap.title, tidy, "", cap.url)
        cap.title = clean_title(cap.title)
        dup = self._same_notice(cap.text)
        if dup:
            return self._merge_into(job, dup, cap)
        cap.files = expand_archives(cap.files)          # zip 붙임은 풀어서 함께 읽는다
        if not cap.files:
            # 붙여넣기·주소 수집 등으로 파일이 따라오지 않았어도, 본문에 적힌 붙임은 '받지 못함'으로 알려 준다
            # (나중에 공문 폴더의 '붙임'에 넣으면 이름을 맞춰 자동으로 연결된다)
            cap.files = [{"name": e, "path": "", "ok": False,
                          "error": "본문에 적힌 붙임입니다 — 파일을 공문 폴더의 '붙임'에 넣으면 자동으로 연결됩니다"}
                         for e in attach.expected_attachments(cap.text)]
        analysis = analyze(cap.title, cap.text, cap.files, None)
        analysis["ai_status"] = "running" if use_ai else "off"
        folder = cap.folder
        (folder / "요약.md").write_text(summary_markdown(cap.title, cap.url, analysis, cap.files), encoding="utf-8")
        nid = self._store.add_notice(cap.title, cap.url, str(folder), cap.text, cap.files, analysis)
        self._sync_tasks(nid, cap.title, analysis)
        if use_ai:
            threading.Thread(target=self._ai_refine, args=(nid,), daemon=True, name="ai-refine").start()
        job.message = "완료"
        return self._store.get_notice(nid) or {}

    def _ai_refine(self, nid: int) -> None:
        """로컬 AI로 요약·제출물·할 일을 보완하고 할 일·요약.md를 갱신한다."""
        n = self._store.get_notice(nid)
        if not n:
            return
        s = self._cfg.settings
        started = time.time()
        if s.engine != "ollama" and self._engine.missing_engine() and self._engine_install["state"] != "error":
            try:                       # 모델은 있는데 엔진만 없다 → 엔진을 받고 이어서 AI 분석 (받는 중이면 기다린다)
                self._install_engine_now()
            except Exception:
                pass
        a = analyze(n["title"], n["body"], n["attachments"], self._client(), s.chat_model, s.num_ctx)
        if a.get("mode") == "llm":
            a["ai_status"] = "done"
        else:
            err = a.get("llm_error") or ""          # 새 분석의 오류 원인 (이전 결과로 덮어쓰기 전에 받아 둔다)
            a = dict(n.get("analysis") or a)
            a["ai_status"] = "error"
            a["llm_error"] = err or "로컬 AI가 응답하지 않았습니다"
        a["ai_seconds"] = round(time.time() - started)
        if not self._store.get_notice(nid):   # 그사이 삭제됨
            return
        self._store.update_notice_analysis(nid, a)
        if a["ai_status"] == "done":
            self._sync_tasks(nid, n["title"], a)
        folder = Path(n["folder"])
        if folder.exists():
            (folder / "요약.md").write_text(summary_markdown(n["title"], n["source"], a, n["attachments"]),
                                            encoding="utf-8")

    def preload_model(self) -> None:
        """앱 시작 시 답변 모델을 미리 메모리에 올려 첫 질문·분석을 빠르게 한다."""
        def run():
            # 모델 파일은 있는데 엔진만 없으면(엔진 폴더를 빠뜨리고 복사·백신이 지움 등) 엔진을 알아서 받아 둔다
            if self._cfg.settings.engine != "ollama" and self._engine.missing_engine():
                try:
                    self._install_engine_now()
                    logging.getLogger("seomu").info("AI 엔진을 자동으로 받았습니다: %s", self._engine.server_path())
                except Exception as e:          # 인터넷이 안 되는 PC 등: 화면에서 [엔진 파일 지정]을 안내
                    logging.getLogger("seomu").warning("AI 엔진 자동 받기 실패: %s", e)
                    return
            try:
                c = self._client()
                c.preload(c.pick_chat_model(self._cfg.settings.chat_model))
            except Exception:
                pass
            try:   # 의미 검색을 쓰면 검색 모델도 미리 올려 첫 질문의 대기 시간을 줄인다
                if self._rag.index().has_vecs:
                    c = self._client()
                    em = c.pick_embed_model(self._cfg.settings.embed_model)
                    if em:
                        c.embed(["준비"], em)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True, name="preload").start()

    def capture_browser(self, page_index: int | None = None, title: str = "", use_ai: bool = True) -> dict:
        root = self._cfg.settings.resolved_download_root()

        def work(job: Job):
            job.message = "브라우저 페이지를 읽는 중…"
            cap = self._browser_worker().capture(root, page_index, title.strip(),
                                                 progress=lambda m: setattr(job, "message", m))
            return self._finish_capture(job, cap, use_ai)
        return self._run_job("capture", work)

    def collect_url(self, url: str, title: str = "", use_ai: bool = True) -> dict:
        if not (url or "").strip().lower().startswith(("http://", "https://")):
            raise ValueError("http:// 또는 https:// 로 시작하는 주소를 입력하세요")
        root = self._cfg.settings.resolved_download_root()

        def work(job: Job):
            job.message = "페이지와 붙임파일을 내려받는 중…"
            cap = collect_from_url(url.strip(), root, title.strip())
            return self._finish_capture(job, cap, use_ai)
        return self._run_job("collect", work)

    def collect_files(self, paths: list[str], title: str = "", body_index: int = 0, use_ai: bool = True) -> dict:
        root = self._cfg.settings.resolved_download_root()

        def work(job: Job):
            job.message = "파일을 정리하는 중…"
            cap = collect_from_files(paths, root, title.strip(), int(body_index or 0))
            return self._finish_capture(job, cap, use_ai)
        return self._run_job("collect", work)

    def collect_text(self, text: str, title: str = "", use_ai: bool = True, html: str = "") -> dict:
        """복사해 붙여 넣은 공문 본문으로 수집 (어떤 공문 시스템·웹 페이지·메일에서든 동작)."""
        if len(re.sub(r"\s", "", text or "")) < 10 and not (html or "").strip():
            raise ValueError("붙여 넣은 본문이 없습니다. 공문 본문을 복사(Ctrl+A, Ctrl+C)한 뒤 붙여 넣어 주세요.")
        root = self._cfg.settings.resolved_download_root()

        def work(job: Job):
            job.message = "붙여 넣은 본문을 정리하는 중…"
            cap = collect_from_text(text or "", root, title.strip(), html or "")
            return self._finish_capture(job, cap, use_ai)
        return self._run_job("collect", work)

    # ---- 열린 프로그램 창에서 수집 (Windows) ----
    def list_windows(self) -> list[dict]:
        return winwindow.list_windows()

    def install_uia(self) -> dict:
        """뒤에서 화면 글자를 읽는 데 필요한 uiautomation 패키지를 설치한다 (소스 실행일 때, 인터넷 필요)."""
        if winwindow.uia_available():
            return {"job_id": self._run_job("uia", lambda job: {"ok": True, "already": True})["job_id"]}
        if getattr(sys, "frozen", False):
            raise RuntimeError("실행 파일(exe)에는 이미 들어 있어야 합니다. 최신 실행 파일로 다시 받아 주세요.")

        def work(job: Job):
            job.message = "uiautomation 설치 중… (1분 정도)"
            r = subprocess.run([sys.executable, "-m", "pip", "install", "uiautomation"], capture_output=True,
                               text=True, timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode != 0:
                raise RuntimeError("설치하지 못했습니다 (인터넷 연결 또는 pip 확인): " + (r.stderr or r.stdout)[-300:])
            import importlib
            importlib.invalidate_caches()
            return {"ok": winwindow.uia_available()}
        return self._run_job("uia", work)

    def job_signal(self, job_id: str, name: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job.flags[name] = True
        return True

    def capture_window(self, hwnd: int, title: str = "", use_ai: bool = True, wait_seconds: int = 180) -> dict:
        if not winwindow.available():
            raise RuntimeError("열린 창 수집은 Windows에서만 사용할 수 있습니다.")
        root = self._cfg.settings.resolved_download_root()
        picked = int(hwnd)
        real = winwindow.resolve_window(picked)     # 크기 없는 껍데기 창(작업 표시줄 단추용)을 고르면 내용 창으로
        win = (next((w for w in winwindow.list_windows() if w["hwnd"] == real), None)
               or winwindow.window_info(real))     # 목록 기준에 안 맞는 창이라도 살아 있으면 수집한다
        if not win:
            raise ValueError("선택한 창을 찾을 수 없습니다. 창 목록을 새로고침하세요.")
        if real != picked:
            win = dict(win, title=win["title"] if win["title"] != winwindow.UNTITLED else
                       ((winwindow.window_info(picked) or {}).get("title") or win["title"]))

        winwindow.set_foreground_allowed(self._cfg.settings.capture_foreground)
        winwindow.set_ocr_body_allowed(self._cfg.settings.capture_ocr_body)

        def work(job: Job):
            say = lambda m: setattr(job, "message", m)  # noqa: E731
            trace: list[str] = [f"창을 앞으로 가져오는 방법 허용: {winwindow.foreground_allowed()}",
                                f"창: {win['title']} / 프로그램 {win['process']} / 클래스 {win['cls']}"
                                + (f" (고른 창 {picked} → 내용 창 {real})" if real != picked else "")]
            hwnd_ = win["hwnd"]
            started = time.time()
            found: dict = {}
            # 최소화된 창: 앞으로 가져와도 되면 보이게 펼쳐 버튼·복사를 하고, 아니면 투명하게 펼쳐 뒤에서 읽는다
            with winwindow.capturable(hwnd_, trace, visible=winwindow.foreground_allowed()):
                text, how = winwindow.extract_text(hwnd_, say, trace, found)
                shot = winwindow.capture_png(hwnd_)
                # 뷰어의 '붙임목록'·'첨부파일' 칸 (본문 글자 인식은 본문 단만 읽어 옆·위 패널의 붙임 이름을 놓친다)
                say("화면에서 붙임 목록을 찾는 중…")
                try:
                    screen_names = winwindow.screen_attachment_names(hwnd_, trace)
                except Exception as e:             # 화면 읽기 실패가 수집을 막지 않게
                    trace.append(f"화면 붙임 목록 오류: {e}")
                    screen_names = []
            text = (text or "").replace("\r\n", "\n").replace("\r", "\n")   # 프로그램마다 줄 구분이 다르다
            win_title = clean_title(win["title"])
            # 폴더 이름: 직접 입력 > 본문의 '제목' 줄 > 창 제목
            m = re.search(r"^[ \t]*(?:제\s*목|건\s*명)[ \t]*[:：]?[ \t]*(\S.{2,120})$", text or "", re.M)
            name = title.strip() or (m.group(1).strip() if m else "") or win_title
            if name == winwindow.UNTITLED and found.get("document"):
                name = Path(found["document"]).stem
            folder = make_notice_folder(root, name)
            dest = folder / "붙임"
            if shot:
                (folder / "본문_화면.png").write_bytes(shot)
            if found.get("document"):                       # 창에 열려 있던 문서 원본도 공문 폴더에 남긴다
                try:
                    shutil.copy2(found["document"], unique_path(folder / ("원문_" + safe_name(Path(found["document"]).name, 150))))
                    trace.append(f"창에 열린 문서 원본 보관: {found['document']}")
                except OSError as e:
                    trace.append(f"문서 원본 보관 실패: {e}")

            # 전체 선택·복사로 받은 HTML의 붙임 링크 (이름은 붙임 목록에, 주소는 내려받기에 쓴다)
            links: list[dict] = []
            if found.get("html"):
                try:
                    html = found["html"]
                    links = analyze_html(html, winwindow.html_source_url(html))["attachments"][:15]
                    trace.append(f"복사한 본문의 붙임 링크 {len(links)}개: {[a['name'] for a in links]}")
                except Exception as e:
                    trace.append(f"붙임 링크 해석 오류: {e}")
            # ---- 붙임: 본문의 '붙임/첨부' 목록으로 모아야 할 파일을 먼저 알아낸다
            expected = attach.expected_attachments(text)
            trace.append(f"본문의 붙임 목록 {len(expected)}개: {expected}")
            # 창 제목·창에 열린 문서 자체(한글로 연 공문 등)는 붙임이 아니다
            own = [x for x in (attach.name_from_title(win["title"]), Path(found.get("document") or "").name) if x]
            screen_names = [n for n in screen_names if not any(attach.name_score(n, o) >= 1.0 for o in own)]
            if screen_names:
                expected = attach.merge_names(expected, screen_names)
                trace.append(f"화면의 붙임 이름을 더한 붙임 목록 {len(expected)}개: {expected}")
            link_names = [a["name"] for a in links if a.get("name") and attach.file_names_in(a["name"])]
            if link_names:
                expected = attach.merge_names(expected, link_names)
            got: dict[str, dict] = {}          # 붙임 이름 → 모은 파일
            extras: list[dict] = []            # 목록과 이름이 안 맞지만 새로 생긴 파일
            hashes: set[str] = set()

            def take(src: str, label: str | None) -> dict | None:
                try:
                    h = attach.file_hash(src)
                except OSError:
                    return None
                if h in hashes:
                    return None
                hashes.add(h)
                dest.mkdir(parents=True, exist_ok=True)
                target = unique_path(dest / safe_name(Path(src).name, 150))
                try:
                    shutil.copy2(src, target)
                except OSError as e:
                    trace.append(f"복사 실패 {src}: {e}")
                    return None
                item = {"name": target.name, "path": str(target), "ok": True, "from": str(Path(src).parent)}
                if label:
                    got[label] = item
                else:
                    extras.append(item)
                return item

            def missing() -> list[str]:
                return [e for e in expected if e not in got]

            # 지금 다른 창(한글·PDF 등)에 열려 있는 문서는 사용자가 작업 중인 파일이지 이 공문의 붙임이 아니다
            open_docs = [n for n in (attach.name_from_title(w["title"]) for w in winwindow.list_windows()
                                     if w["hwnd"] != hwnd_) if n] if winwindow.available() else []

            def not_open_elsewhere(f: dict) -> bool:
                return not any(attach.name_score(f["name"], o) >= 0.9 for o in open_docs)

            def harvest(since: float, budget: float = 8.0) -> None:
                if not missing():
                    return
                files = attach.candidate_files(since, exclude=folder, budget=budget,
                                               extra=attach.recent_documents() if winwindow.available() else [])
                files = [f for f in files if not_open_elsewhere(f)]
                # 이름이 충분히 비슷할 때만 (앞부분 '2026년 …'만 같은 다른 문서를 붙임으로 잘못 모으지 않게)
                for e, f in attach.match_files(missing(), files, threshold=0.6, strict=True).items():
                    if take(f["path"], e):
                        trace.append(f"'{e}' ← PC 안의 파일 {f['path']} (일치도 {f['score']})")

            watcher = winwindow.FileWatcher(winwindow.watch_dirs(), dest)

            tmp_root = os.path.normcase(os.path.abspath(os.environ.get("TEMP") or os.environ.get("TMP") or "~none~"))

            def assign(item: dict, how: str, from_temp: bool = False) -> None:
                """새로 들어온 파일을 붙임 이름에 짝짓는다: 이름 → (이름이 관리용 번호면) 내용.
                내용으로 맞춘 파일은 붙임 이름으로 바꾼다. 임시 폴더의 짝 없는 파일은 버린다(다른 프로그램 파일)."""
                p = Path(item["path"])
                i, sc = attach.best_match(item["name"], missing()) if missing() else (-1, 0)
                if i >= 0 and attach.meaningless_name(item["name"]):
                    i = -1                                  # 번호 이름이 우연히 비슷한 것은 믿지 않는다
                if i < 0 and missing():
                    try:
                        from .parsers import parse_file
                        i = attach.match_by_content(parse_file(p), missing())
                    except Exception as e:                 # 읽을 수 없는 형식 → 이름만으로
                        trace.append(f"'{p.name}' 내용 읽기 실패: {e}")
                        i = -1
                    if i >= 0:
                        label = missing()[i]
                        if attach.meaningless_name(p.name) or attach.name_score(label, p.name) < 0.6:
                            new = unique_path(p.with_name(safe_name(label, 120) + p.suffix.lower()))
                            try:
                                p.rename(new)
                                trace.append(f"'{p.name}' → '{new.name}' (내용으로 확인한 붙임 이름으로 바꿈)")
                                item = dict(item, name=new.name, path=str(new))
                            except OSError as e:
                                trace.append(f"이름 바꾸기 실패 {p.name}: {e}")
                        how += " · 내용으로 확인"
                if i >= 0:
                    got[missing()[i]] = item
                    trace.append(f"'{item['name']}' ← {how}")
                elif from_temp:
                    p.unlink(missing_ok=True)               # 임시 폴더의 다른 프로그램 파일: 붙임이 아니다
                    trace.append(f"임시 폴더의 관계없는 파일 제외: {item['name']}")
                else:
                    extras.append(item)

            def absorb() -> None:
                """폴더 감시로 새로 들어온 파일과 공문 폴더에 바로 저장된 파일을 붙임 목록에 짝지어 준다."""
                for item in watcher.poll():
                    try:
                        h = attach.file_hash(item["path"])
                    except OSError:
                        continue
                    if h in hashes:          # 이미 모은 파일과 같은 내용 → 중복 제거
                        Path(item["path"]).unlink(missing_ok=True)
                        continue
                    hashes.add(h)
                    src = os.path.normcase(os.path.abspath(item.get("from") or ""))
                    assign(item, "폴더 감시", from_temp=src.startswith(tmp_root))
                # 뷰어의 저장 창에서 공문 폴더로 바로 저장한 파일 (폴더 감시는 공문 폴더 안을 보지 않는다)
                known = {os.path.normcase(str(Path(f["path"]).resolve())) for f in list(got.values()) + extras}
                for f in sorted(dest.iterdir()) if dest.is_dir() else []:
                    if not f.is_file() or f.name.startswith(("~$", ".")) or f.suffix.lower() in winwindow.PARTIAL_EXT:
                        continue
                    key = os.path.normcase(str(f.resolve()))
                    if key in known or key in claimed:
                        continue
                    try:
                        size = f.stat().st_size
                        h = attach.file_hash(f)
                    except OSError:
                        continue
                    if size == 0 or claimed_size.get(key) != size:  # 쓰는 중 → 크기가 그대로일 때 다음 번에
                        claimed_size[key] = size
                        continue
                    claimed.add(key)
                    if h in hashes:
                        continue
                    hashes.add(h)
                    assign({"name": f.name, "path": str(f), "ok": True, "from": "뷰어 저장"}, "뷰어 'PC저장'")

            claimed: set[str] = set()
            claimed_size: dict[str, int] = {}

            # ① 이미 PC에 있는 파일 (뷰어가 열 때 내려받은 임시·캐시 파일, 최근 문서 등)
            say("PC에 이미 내려받아진 붙임파일을 찾는 중…")
            harvest(started - 3 * 3600)
            # ①-2 복사한 본문(HTML)에 붙임 링크가 있으면 바로 내려받는다 (로그인이 필요 없는 주소일 때)
            for a in links:
                if not missing() and expected:
                    break
                if not a.get("url", "").lower().startswith(("http://", "https://")):
                    continue
                say(f"붙임 내려받는 중: {a['name'][:40]}")
                try:
                    fp = download_url(a["url"], dest, a["name"], timeout=30)
                    item = checked_download(fp, a["name"])
                except Exception as e:                  # 세션이 필요한 주소 등 → 다음 방법으로
                    trace.append(f"붙임 링크 내려받기 실패 {a['name']}: {e}")
                    continue
                if not item.get("ok"):
                    trace.append(f"붙임 링크 '{a['name']}': {item.get('error', '')[:80]}")
                    continue
                try:
                    hashes.add(attach.file_hash(item["path"]))
                except OSError:
                    pass
                i, sc = attach.best_match(item["name"], missing()) if missing() else (-1, 0)
                if i < 0 and missing():
                    i, sc = attach.best_match(a["name"], missing())
                if i >= 0:
                    got[missing()[i]] = item
                else:
                    extras.append(item)
                trace.append(f"'{item['name']}' ← 본문의 붙임 링크 내려받기")
            # ② 뷰어의 'PC저장' 버튼 (버튼 메시지·UI Automation으로 누르고, 뜨는 저장 창에 공문 폴더를 지정한다)
            #    받아야 할 붙임 이름을 알 때만 누른다 (이름 없이 누르면 본문 파일까지 붙임으로 저장될 수 있다)
            state = ""
            if missing():
                try:
                    state = winwindow.try_save_attachments(hwnd_, dest, say, trace)
                except Exception as e:          # 뷰어마다 화면이 달라 실패할 수 있다 → 다음 단계로
                    logging.getLogger("seomu").warning("붙임 저장 버튼 단계 실패: %s", e)
                    trace.append(f"저장 버튼 단계 오류: {e}")
                    state = ""
                trace.append(f"저장 버튼: {state or '찾지 못함'}")
                end = time.time() + (8 if state else 0)
                while time.time() < end and missing():
                    absorb()
                    time.sleep(0.5)
            # ③ 화면에 보이는 붙임 이름을 찾아 열기
            if missing() and winwindow.available():
                try:
                    opened = winwindow.open_named_on_screen(hwnd_, missing(), say, trace)
                except Exception as e:
                    logging.getLogger("seomu").warning("화면의 붙임 이름 찾기 실패: %s", e)
                    trace.append(f"화면 붙임 찾기 오류: {e}")
                    opened = []
                for r in opened:
                    if r["path"]:
                        take(r["path"], r["expected"])
                    absorb()
                harvest(started - 120, budget=6)       # 열면서 임시 폴더에 생긴 파일
            absorb()

            # ④ 남은 것은 폴더 감시 (사용자가 직접 저장해도 자동 수집). 모두 모이면 자동 종료
            clip_before = winwindow.get_clipboard()
            deadline = time.time() + max(20, int(wait_seconds))
            quiet_since = time.time()
            while time.time() < deadline and not job.flags.get("done"):
                n_before = len(got) + len(extras)
                absorb()
                if len(got) + len(extras) != n_before:
                    quiet_since = time.time()
                if not text:
                    clip = winwindow.get_clipboard()
                    if clip and clip != clip_before and len(clip.strip()) > 50:
                        text, how = clip, "본문복사(직접)"
                        expected = expected or attach.expected_attachments(text)
                if expected and not missing() and text:
                    break                                  # 붙임을 다 모았다
                if not expected and text and time.time() - quiet_since > 15:
                    break                                  # 붙임 표기가 없는 공문
                left = missing()
                hint = (f"붙임 {len(got)}/{len(expected)}개를 모았습니다. 남은 붙임은 그 창에서 저장하면 자동으로 모읍니다."
                        if expected else "새로 저장되는 붙임파일을 기다리는 중…")
                if left and not winwindow.foreground_allowed():
                    hint += " ('PC저장 자동 누르기'를 켜면 뷰어의 저장 버튼을 대신 누릅니다)"
                hint += f" (최대 {max(0, int(deadline - time.time()))}초 더 기다림 · [붙임 수집 완료]를 누르면 바로 정리)"
                if not text:
                    hint += " 본문을 읽지 못했습니다. 그 창에서 본문을 복사(Ctrl+A, Ctrl+C 또는 [본문복사])하면 바로 받습니다."
                job.message = hint
                job.text = json.dumps({
                    "phase": "watch", "has_text": bool(text), "how": how, "folder": str(folder),
                    "expected": [{"name": e, "file": (got.get(e) or {}).get("name", "")} for e in expected],
                    "files": [f["name"] for f in list(got.values()) + extras], "listed": [],
                    "missing": left}, ensure_ascii=False)
                time.sleep(1.0)
            absorb()
            trace.append(f"본문: {how or '읽지 못함'} ({len(text)}자) / 붙임 {len(got)}/{len(expected)}개 + 기타 {len(extras)}개")
            (folder / "수집기록.txt").write_text("\n".join(trace), encoding="utf-8")
            body = text or "(본문을 읽지 못했습니다. 본문_화면.png를 확인하세요.)"
            save_body(folder, name, body, "", f"창: {win['title']} ({win['process']})")
            files = list(got.values()) + extras
            for e in missing():
                files.append({"name": e, "path": "", "ok": False,
                              "error": "자동으로 찾지 못함 — 그 창에서 저장해 공문 폴더의 '붙임'에 넣으면 다음에 열 때 자동으로 반영됩니다"})
            cap = Captured(name, body, "", f"창: {win['title']}", folder, files, str(folder / "본문_화면.png"))
            result = self._finish_capture(job, cap, use_ai)
            result["capture_method"] = how
            result["attach_summary"] = {"expected": len(expected), "found": len(got), "extra": len(extras)}
            # 끝내 받지 못한 붙임: 화면에서 '붙임 문서를 받아 올려 주세요' 창을 띄운다
            result["need_upload"] = missing()
            result["maybe_attach"] = (not expected and not got and not extras
                                      and bool(re.search(r"(붙\s*임|첨\s*부)", text or "")))
            return result
        return self._run_job("capture_window", work)

    def list_notices(self) -> list[dict]:
        return self._store.list_notices()

    def get_notice(self, notice_id: int) -> dict | None:
        n = self._store.get_notice(int(notice_id))
        if n:
            n = self._rescan_attachments(n)
            n["tasks"] = [t for t in self._store.list_tasks() if t.get("notice_id") == n["id"]]
        return n

    def add_notice_attachments(self, notice_id: int, paths: list[str]) -> dict:
        """받지 못한 붙임을 사용자가 직접 올린다: 공문 폴더의 '붙임'에 복사하고 이름이 맞는 '받지 못함' 칸을 채운다.
        올린 원본 파일은 그대로 둔다."""
        n = self._store.get_notice(int(notice_id))
        if not n:
            raise ValueError("공문을 찾을 수 없습니다")
        dest = Path(n["folder"]) / "붙임"
        dest.mkdir(parents=True, exist_ok=True)
        added = 0
        for p in paths or []:
            src = Path(p)
            if not src.is_file():
                continue
            shutil.copy2(src, unique_path(dest / safe_name(src.name, 150)))
            added += 1
        if not added:
            raise ValueError("올릴 파일을 고르세요")
        n = self.get_notice(n["id"]) or n                 # 붙임 폴더를 다시 살펴 목록에 반영
        n["added_files"] = added
        return n

    def _rescan_attachments(self, n: dict) -> dict:
        """공문 폴더의 '붙임'에 사용자가 나중에 넣은 파일을 붙임 목록에 더한다.
        이름이 맞으면 '받지 못함'으로 남아 있던 항목을 채운다 (뷰어에서 직접 저장한 붙임을 넣는 경우)."""
        files = list(n.get("attachments") or [])
        # 예전 규칙으로 본문을 잘못 읽어 생긴 '받지 못함' 붙임(문서 첫머리 '붙임1.' 아래 본문 등)은 정리한다
        expected = set(attach.expected_attachments(n.get("body") or ""))
        cleaned = [f for f in files if f.get("ok") or not str(f.get("error", "")).startswith("본문에 적힌 붙임")
                   or f.get("name") in expected]
        if len(cleaned) != len(files):
            files = cleaned
            self._store.update_notice_attachments(n["id"], files)
            n["attachments"] = files
        dest = Path(n.get("folder") or "") / "붙임"
        if not dest.is_dir():
            return n
        known = {os.path.normcase(str(Path(f["path"]).resolve())) for f in files if f.get("path")}
        new = [p for p in sorted(dest.rglob("*")) if p.is_file() and not p.name.startswith(("~$", "."))
               and os.path.normcase(str(p.resolve())) not in known]
        if not new:
            return n
        for p in new:
            item = {"name": str(p.relative_to(dest)).replace("\\", "/"), "path": str(p), "ok": True, "from": "직접 넣은 파일"}
            missing = [i for i, f in enumerate(files) if not f.get("ok")]
            j, sc = attach.best_match(p.name, [files[i]["name"] for i in missing]) if missing else (-1, 0)
            if j >= 0:
                files[missing[j]] = item          # '받지 못함' 자리를 채운다
            else:
                files.append(item)
        self._store.update_notice_attachments(n["id"], files)
        n["attachments"] = files
        return n

    def reanalyze(self, notice_id: int) -> dict:
        n = self._store.get_notice(int(notice_id))
        if not n:
            raise ValueError("공문을 찾을 수 없습니다")

        def work(job: Job):
            job.message = "다시 분석하는 중…"
            s = self._cfg.settings
            a = analyze(n["title"], n["body"], n["attachments"], self._client(), s.chat_model, s.num_ctx)
            a["folder_name"] = (n.get("analysis") or {}).get("folder_name") or a.get("folder_name")
            a["ai_status"] = "done" if a.get("mode") == "llm" else "error"
            self._store.update_notice_analysis(n["id"], a)
            self._sync_tasks(n["id"], n["title"], a)
            folder = Path(n["folder"])
            if folder.exists():
                (folder / "요약.md").write_text(summary_markdown(n["title"], n["source"], a, n["attachments"]),
                                                encoding="utf-8")
            return self.get_notice(n["id"])
        return self._run_job("analyze", work)

    def delete_notice(self, notice_id: int, delete_folder: bool = False) -> bool:
        n = self._store.get_notice(int(notice_id))
        if n and delete_folder:
            folder = Path(n["folder"])
            root = self._cfg.settings.resolved_download_root().resolve()
            if folder.exists() and root in folder.resolve().parents:
                shutil.rmtree(folder, ignore_errors=True)
        self._store.delete_notice(int(notice_id))
        return True

    def open_notice_folder(self, notice_id: int) -> bool:
        n = self._store.get_notice(int(notice_id))
        return self.open_path(n["folder"]) if n else False

    # ------------------------------------------------------------ 할 일
    def list_tasks(self, include_done: bool = True) -> list[dict]:
        tasks = self._store.list_tasks(bool(include_done))
        for t in tasks:
            t["dday"] = dday(t["due"]) if t.get("due") else None
        return tasks

    def add_task(self, title: str, due: str = "", detail: str = "") -> int:
        if not (title or "").strip():
            raise ValueError("할 일을 입력하세요")
        return self._store.add_task(title.strip(), detail or "", due or None)

    def update_task(self, task_id: int, values: dict) -> bool:
        self._store.update_task(int(task_id), **(values or {}))
        return True

    def delete_task(self, task_id: int) -> bool:
        self._store.delete_task(int(task_id))
        return True

    def export_ics(self) -> str:
        path = self._cfg.settings.resolved_download_root() / "서무비서_일정.ics"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tasks_to_ics(self._store.list_tasks(False)), encoding="utf-8")
        return str(path)

    # ------------------------------------------------------------ 메일 양식
    def list_templates(self) -> dict:
        return {"templates": self._store.list_templates(), "variables": VARIABLES}

    def save_template(self, name: str, subject: str, body: str, template_id: int | None = None) -> int:
        if not (name or "").strip():
            raise ValueError("양식 이름을 입력하세요")
        return self._store.save_template(name.strip(), subject or "", body or "", template_id or None)

    def delete_template(self, template_id: int) -> bool:
        self._store.delete_template(int(template_id))
        return True

    def render_mail(self, template_id: int, notice_id: int | None = None, extra: dict | None = None) -> dict:
        t = self._store.get_template(int(template_id))
        if not t:
            raise ValueError("양식을 찾을 수 없습니다")
        notice = self._store.get_notice(int(notice_id)) if notice_id else None
        variables = build_variables(notice, self._cfg.settings)
        variables.update({k: v for k, v in (extra or {}).items() if v})
        subject, m1 = render(t["subject"], variables)
        body, m2 = render(t["body"], variables)
        attachments = []
        if notice:
            folder = Path(notice["folder"])
            # 앱이 만든 내부 파일(요약·수집 기록·메일 초안·화면 캡처)은 받는 사람에게 보낼 파일이 아니다
            attachments = [str(p) for p in sorted(folder.rglob("*")) if p.is_file()
                           and p.name not in ("본문.html", "본문_화면.png", "요약.md", "수집기록.txt")
                           and not p.name.startswith(("메일초안", "~$", "."))]
        return {"subject": subject, "body": body, "missing": list(dict.fromkeys(m1 + m2)),
                "attachments": attachments}

    # ---- 문서 다듬기: 대충 쓴 메모 → 메일·공문·보고·메시지
    def _profile(self) -> dict:
        s = self._cfg.settings
        return {"user_name": s.user_name, "user_dept": s.user_dept, "user_phone": s.user_phone,
                "user_email": s.user_email}

    def polish_draft(self, draft: str, kind: str = "mail", template_id: int | None = None,
                     notice_id: int | None = None, use_ai: bool = True) -> dict:
        """메모를 고른 형식(또는 내 양식)으로 다듬는다. AI가 없거나 숫자·날짜를 바꾸면 규칙 결과."""
        if kind not in polish_mod.KINDS:
            raise ValueError("형식을 고르세요")
        if not (draft or "").strip():
            raise ValueError("다듬을 내용을 입력하세요 (메모처럼 대충 써도 됩니다)")
        template = self._store.get_template(int(template_id)) if template_id else None
        notice = self._store.get_notice(int(notice_id)) if notice_id else None
        variables = build_variables(notice, self._cfg.settings)
        rule = polish_mod.rule_polish(draft, kind, self._profile(), template, variables)

        def work(job: Job):
            res = dict(rule, mode="rule", warning="")
            if use_ai:
                job.message = "로컬 AI가 다듬는 중…"
                try:
                    c = self._client()
                    model = c.pick_chat_model(self._cfg.settings.chat_model)
                    ai = polish_mod.ai_polish(c, model, draft, kind, rule,
                                              (template or {}).get("body", ""), self._cfg.settings.num_ctx)
                    if kind == "mail" and not template:      # 서명은 규칙으로 (AI가 이름·연락처를 지어내지 않게)
                        sig = polish_mod._signature(self._profile())
                        if sig and sig.splitlines()[0] not in ai["body"]:
                            ai["body"] = ai["body"].rstrip() + "\n\n" + sig
                    res = dict(ai, mode="llm", model=model, warning="")
                except LLMError as e:
                    res["warning"] = str(e)
            return res
        return self._run_job("polish_draft", work)

    def template_from_example(self, text: str, name: str = "") -> dict:
        """보낸 메일을 붙여 넣으면 내 양식으로 저장한다 (내 이름·부서·연락처·메일은 변수로)."""
        t = polish_mod.template_from_example(text, self._profile())
        name = (name or "").strip() or (t["subject"][:20] if t["subject"] else "내 메일 양식")
        tid = self._store.save_template(name, t["subject"], t["body"], None)
        return {"id": tid, "name": name, **t}

    def polish_mail(self, body: str) -> dict:
        def work(job: Job):
            job.message = "AI가 문장을 다듬는 중…"
            c = self._client()
            s = self._cfg.settings
            model = c.pick_chat_model(s.chat_model)
            # 다듬은 글은 초안과 길이가 비슷하다: 생성 길이 상한을 초안 길이에 맞춰 군더더기 생성을 막는다
            limit = min(1536, int(len(body) * 1.1) + 160)
            out = c.chat([{"role": "user", "content": POLISH_PROMPT.format(body=body)}], model,
                         temperature=0.3, num_ctx=s.num_ctx, max_tokens=limit,
                         on_token=lambda t: setattr(job, "text", job.text + t)).strip()
            return {"body": clean_polished(out, body)}
        return self._run_job("polish", work)

    def open_mail(self, subject: str, body: str = "") -> dict:
        """기본 메일 프로그램(Outlook 등)의 새 메일 창을 연다 (Windows 표준 방식: ShellExecute로 mailto: 주소).
        화면(WebView2)에서 mailto로 이동하면 막히거나 확인 창이 뜨는 경우가 있어 앱 안에서 연다.
        Windows의 mailto 주소 길이 제한(약 2,000자) 때문에 본문이 길면 제목만 넘긴다 (본문은 화면에서 복사해 둔다)."""
        import urllib.parse
        q = urllib.parse.quote
        url = f"mailto:?subject={q(subject or '')}&body={q(body or '')}"
        with_body = len(url) <= 1900
        if not with_body:
            url = f"mailto:?subject={q(subject or '')}"
        try:
            if sys.platform.startswith("win"):
                self._open_os(url)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", url])
            else:
                subprocess.Popen(["xdg-open", url])
        except OSError as e:
            raise RuntimeError("기본 메일 프로그램을 열 수 없습니다. [전체 복사]로 복사한 뒤 메일 프로그램에 붙여 넣으세요. "
                               f"({e})") from e
        return {"with_body": with_body}

    def save_mail_draft(self, subject: str, body: str, notice_id: int | None = None) -> str:
        """메일 초안을 공문 폴더(또는 다운로드 폴더)에 텍스트로 저장."""
        folder = None
        if notice_id:
            n = self._store.get_notice(int(notice_id))
            folder = Path(n["folder"]) if n else None
        folder = folder or self._cfg.settings.resolved_download_root()
        folder.mkdir(parents=True, exist_ok=True)
        p = unique_path(folder / "메일초안.txt")
        p.write_text(f"제목: {subject}\n\n{body}\n", encoding="utf-8")
        return str(p)

    # ------------------------------------------------------------ 보고서 작성 (HWPX 양식)
    def _report_dir(self) -> Path:
        d = self._cfg.home / "report_templates"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _report_files(self) -> list[Path]:
        files = sorted(self._report_dir().glob("*.hwpx"))
        builtin = report_mod.builtin_template()
        if builtin and not any(f.name == builtin.name for f in files):
            files.append(builtin)
        return files

    def report_templates(self) -> dict:
        items = []
        for f in self._report_files():
            try:
                info = report_mod.load_template(f).info()
                info["ok"] = True
            except report_mod.ReportError as e:
                info = {"name": f.stem, "path": str(f), "ok": False, "error": str(e)}
            info["builtin"] = f.parent != self._report_dir()
            items.append(info)
        return {"templates": items}

    def add_report_templates(self, paths: list[str]) -> dict:
        """보고서 양식(.hwpx)을 등록한다. 해석할 수 없는 양식은 이유를 알려 준다."""
        errors = []
        for p in paths or []:
            src = Path(p)
            try:
                report_mod.load_template(src)
            except (report_mod.ReportError, OSError) as e:
                errors.append(f"{src.name}: {e}")
                continue
            dest = self._report_dir() / safe_name(src.name, 120)
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)
        res = self.report_templates()
        res["errors"] = errors
        return res

    def delete_report_template(self, name: str) -> dict:
        p = self._report_dir() / f"{name}.hwpx"
        if p.exists():
            p.unlink()
        return self.report_templates()

    def make_report(self, template: str, notice_id: int | None = None, material: str = "",
                    purpose: str = "", use_ai: bool = True) -> dict:
        """양식에 맞춰 보고서를 만든다. 공문을 고르면 분석 결과로, 아니면 입력한 자료로 쓴다."""
        tpath = next((f for f in self._report_files() if f.stem == template or str(f) == template), None)
        if not tpath:
            raise ValueError("보고서 양식을 먼저 골라 주세요")
        notice = self._store.get_notice(int(notice_id)) if notice_id else None
        material = (material or "").strip()
        if not notice and not material:
            raise ValueError("관련 공문을 고르거나 보고서에 넣을 자료를 입력해 주세요")

        def work(job: Job):
            started = time.time()
            job.message = "양식을 읽는 중…"
            tpl = report_mod.load_template(tpath)
            s = self._cfg.settings
            outline, mode, err = None, "rule", ""
            if use_ai:
                job.message = "로컬 AI가 보고서 내용을 쓰는 중…"
                src = report_mod.notice_material(notice) if notice else ""
                if material:
                    src = (src + "\n\n[추가 자료]\n" + material) if src else material
                try:
                    c = self._client()
                    outline = report_mod.ai_outline(c, c.pick_chat_model(s.chat_model), src, purpose,
                                                    tpl.headings, s.num_ctx)
                    mode = "llm"
                except LLMError as e:
                    err = str(e)
            rule = (report_mod.outline_from_notice(notice, purpose) if notice
                    else report_mod.outline_from_text(material, purpose))
            if outline is None:
                outline = rule
            elif not report_mod.plausible_title(outline.get("title", ""), rule["title"], tpl.headings):
                # AI가 양식의 소제목 나열이나 공문과 무관한 제목을 내면 (파일 이름도 되므로) 규칙 제목을 쓴다
                outline["title"] = rule["title"]
            job.message = "양식에 채우는 중…"
            data = report_mod.fill(tpl, outline, dept=s.user_dept)
            clean = report_mod.clean_outline(outline)
            folder = Path(notice["folder"]) if notice and Path(notice["folder"]).exists() \
                else self._cfg.settings.resolved_download_root() / "보고서"
            folder.mkdir(parents=True, exist_ok=True)
            out = unique_path(folder / f"{safe_name(clean['title'] or '보고서', 60)}.hwpx")
            out.write_bytes(data)
            return {"path": str(out), "folder": str(folder), "outline": clean,
                    "preview": report_mod.outline_text(clean), "mode": mode, "llm_error": err,
                    "template": tpath.stem, "seconds": round(time.time() - started, 1)}
        return self._run_job("report", work)

    # ------------------------------------------------------------ 종료
    def shutdown(self) -> None:
        try:
            self._engine.stop()
        except Exception:
            pass
        try:   # 앱을 닫으면 AI 모델이 차지하던 메모리를 바로 돌려준다
            c = self._client()
            c.unload(c.pick_chat_model(self._cfg.settings.chat_model))
        except Exception:
            pass
        if self._browser:
            self._browser.close()
        self._store.close()

"""GUI(웹뷰)에서 호출하는 애플리케이션 API.

오래 걸리는 작업(AI 답변, 색인, 공문 수집)은 '작업(job)'으로 실행하고
화면은 job_status()로 진행 상황과 스트리밍 텍스트를 받아 간다.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from . import APP_NAME, __version__
from .analyzer import analyze, summary_markdown
from .collector import (BrowserWorker, Captured, collect_from_files, collect_from_url,
                        make_notice_folder, safe_name, save_body, unique_path)
from .config import Config
from .deadlines import dday
from .llm import LLMError, OllamaClient
from . import models as model_catalog
from . import attach, winwindow
from .mail import DEFAULT_TEMPLATES, POLISH_PROMPT, VARIABLES, build_variables, render, tasks_to_ics
from .parsers import SUPPORTED
from .rag import RAGEngine
from .storage import Store


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
        self._store = Store(self._cfg.db_path)
        self._rag = RAGEngine(self._store, self._client, lambda: self._cfg.settings)
        self._jobs: dict[str, Job] = {}
        self._browser: BrowserWorker | None = None
        self._window = None
        if not self._store.list_templates():
            for t in DEFAULT_TEMPLATES:
                self._store.save_template(t["name"], t["subject"], t["body"])

    # ------------------------------------------------------------ 내부 유틸
    def _client(self) -> OllamaClient:
        s = self._cfg.settings
        return OllamaClient(s.ollama_url, allow_remote=s.allow_remote_llm)

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
                traceback.print_exc()
        threading.Thread(target=runner, daemon=True, name=f"job-{kind}").start()
        # 오래된 작업 정리
        if len(self._jobs) > 50:
            for k in sorted(self._jobs, key=lambda k: self._jobs[k].started)[:-50]:
                if self._jobs[k].status != "running":
                    self._jobs.pop(k, None)
        return {"job_id": job.id}

    def job_status(self, job_id: str) -> dict:
        job = self._jobs.get(job_id)
        return job.to_dict() if job else {"status": "error", "error": "작업을 찾을 수 없습니다"}

    @staticmethod
    def _open_os(path: str) -> None:
        if sys.platform.startswith("win"):
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
        st["local_only"] = not s.allow_remote_llm
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
            d["active"] = any(n in (active_chat, active_embed) for n in all_names)
            d["fits"] = info["ram_total_gb"] == 0 or info["ram_total_gb"] >= m["min_ram_gb"] * 0.9
            items.append(d)
        return {"engine_ok": st["ok"], "engine_error": st.get("error", ""), "models": items,
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

    def import_gguf(self, path: str, model_id: str) -> dict:
        p = Path(path or "")
        if not p.is_file() or p.suffix.lower() != ".gguf":
            raise ValueError("GGUF(.gguf) 파일을 선택하세요")
        name = (model_id or p.stem).strip().lower()

        def work(job: Job):
            self._client().create_from_gguf(name, str(p), self._progress(job))
            return self.model_catalog()
        return self._run_job("import", work)

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
        return {
            "today": today.isoformat(),
            "weekday": "월화수목금토일"[today.weekday()],
            "tasks": tasks[:20],
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
        if path and Path(path).exists():
            self._open_os(path)
            return True
        return False

    # ------------------------------------------------------------ 규정 저장소 (RAG)
    def list_documents(self) -> dict:
        return {"documents": self._store.list_documents(), "dirs": self._cfg.settings.regulation_dirs,
                "progress": self._rag.progress}

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
        """파일을 기본 규정 폴더로 복사한 뒤 색인."""
        target = Path(self._cfg.settings.regulation_dirs[0]) if self._cfg.settings.regulation_dirs \
            else self._cfg.home / "regulations"
        target.mkdir(parents=True, exist_ok=True)
        copied = []
        for p in paths or []:
            src = Path(p)
            if src.is_file() and src.suffix.lower() in SUPPORTED:
                dest = target / src.name
                if src.resolve() != dest.resolve():
                    shutil.copy2(src, dest)
                copied.append(dest.name)
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
        label = analysis.get("folder_name") or title
        for d in analysis.get("deadlines") or []:
            if d["date"] in done:
                continue
            self._store.add_task(f"[{label}] {d['what'][:80]}",
                                 detail=f"공문: {title}" + (f"\n시각: {d['time']}" if d.get("time") else ""),
                                 due=d["date"], notice_id=nid)

    def _finish_capture(self, job: Job, cap: Captured, use_ai: bool) -> dict:
        """① 규칙 기반 분석으로 바로 저장·표시 → ② 로컬 AI 보완 분석은 백그라운드에서."""
        job.message = "기한·제출물을 찾는 중…"
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
        a = analyze(n["title"], n["body"], n["attachments"], self._client(), s.chat_model, s.num_ctx)
        if a.get("mode") == "llm":
            a["ai_status"] = "done"
        else:
            a = dict(n.get("analysis") or a)
            a["ai_status"] = "error"
            a["llm_error"] = a.get("llm_error") or "AI 분석 실패"
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
            try:
                c = self._client()
                c.preload(c.pick_chat_model(self._cfg.settings.chat_model))
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

    # ---- 열린 프로그램 창에서 수집 (Windows) ----
    def list_windows(self) -> list[dict]:
        return winwindow.list_windows()

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
        win = next((w for w in winwindow.list_windows() if w["hwnd"] == int(hwnd)), None)
        if not win:
            raise ValueError("선택한 창을 찾을 수 없습니다. 창 목록을 새로고침하세요.")

        def work(job: Job):
            say = lambda m: setattr(job, "message", m)  # noqa: E731
            trace: list[str] = []
            hwnd_ = win["hwnd"]
            started = time.time()
            text, how = winwindow.extract_text(hwnd_, say, trace)
            win_title = win["title"]
            for suffix in (" - 온나라", " - 문서", " - Microsoft Edge", " - Chrome", " - Whale"):
                win_title = win_title.replace(suffix, "")
            # 폴더 이름: 직접 입력 > 본문의 '제목' 줄 > 창 제목
            m = re.search(r"^[ \t]*(?:제\s*목|건\s*명)[ \t]*[:：]?[ \t]*(\S.{2,120})$", text or "", re.M)
            name = title.strip() or (m.group(1).strip() if m else "") or win_title
            folder = make_notice_folder(root, name)
            dest = folder / "붙임"
            winwindow.save_window_image(hwnd_, folder / "본문_화면.png")

            # ---- 붙임: 본문의 '붙임/첨부' 목록으로 모아야 할 파일을 먼저 알아낸다
            expected = attach.expected_attachments(text)
            trace.append(f"본문의 붙임 목록 {len(expected)}개: {expected}")
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

            def harvest(since: float, budget: float = 8.0) -> None:
                if not missing():
                    return
                files = attach.candidate_files(since, exclude=folder, budget=budget,
                                               extra=attach.recent_documents() if winwindow.available() else [])
                for e, f in attach.match_files(missing(), files).items():
                    if take(f["path"], e):
                        trace.append(f"'{e}' ← PC 안의 파일 {f['path']} (일치도 {f['score']})")

            watcher = winwindow.FileWatcher(winwindow.watch_dirs(), dest)

            def absorb() -> None:
                """폴더 감시로 새로 들어온 파일을 붙임 목록에 짝지어 준다."""
                for item in watcher.poll():
                    try:
                        h = attach.file_hash(item["path"])
                    except OSError:
                        continue
                    if h in hashes:          # 이미 모은 파일과 같은 내용 → 중복 제거
                        Path(item["path"]).unlink(missing_ok=True)
                        continue
                    hashes.add(h)
                    i, sc = attach.best_match(item["name"], missing()) if missing() else (-1, 0)
                    if i >= 0:
                        got[missing()[i]] = item
                        trace.append(f"'{item['name']}' ← 폴더 감시 (일치도 {sc:.2f})")
                    else:
                        extras.append(item)

            # ① 이미 PC에 있는 파일 (뷰어가 열 때 내려받은 임시·캐시 파일, 최근 문서 등)
            say("PC에 이미 내려받아진 붙임파일을 찾는 중…")
            harvest(started - 3 * 3600)
            # ② 저장/다운로드 버튼
            state = ""
            if missing() or not expected:
                state = winwindow.try_save_attachments(hwnd_, dest, say, trace)
                trace.append(f"저장 버튼: {state or '찾지 못함'}")
                end = time.time() + (6 if state else 0)
                while time.time() < end and missing():
                    absorb()
                    time.sleep(0.5)
            # ③ 화면에 보이는 붙임 이름을 찾아 열기
            if missing() and winwindow.available():
                for r in winwindow.open_named_on_screen(hwnd_, missing(), say, trace):
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
                hint = (f"붙임 {len(got)}/{len(expected)}개를 모았습니다. 남은 붙임은 뷰어에서 저장하면 자동으로 모읍니다."
                        if expected else "새로 저장되는 붙임파일을 기다리는 중…")
                if not text:
                    hint += " 본문을 읽지 못했습니다. 뷰어의 [본문복사]를 눌러 주세요."
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
                              "error": "자동으로 찾지 못함 — 뷰어에서 저장한 뒤 공문 폴더의 '붙임'에 넣어 주세요"})
            cap = Captured(name, body, "", f"창: {win['title']}", folder, files, str(folder / "본문_화면.png"))
            result = self._finish_capture(job, cap, use_ai)
            result["capture_method"] = how
            result["attach_summary"] = {"expected": len(expected), "found": len(got), "extra": len(extras)}
            return result
        return self._run_job("capture_window", work)

    def list_notices(self) -> list[dict]:
        return self._store.list_notices()

    def get_notice(self, notice_id: int) -> dict | None:
        n = self._store.get_notice(int(notice_id))
        if n:
            n["tasks"] = [t for t in self._store.list_tasks() if t.get("notice_id") == n["id"]]
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
            attachments = [str(p) for p in sorted(folder.rglob("*")) if p.is_file()
                           and p.name not in ("본문.html", "본문_화면.png")]
        return {"subject": subject, "body": body, "missing": list(dict.fromkeys(m1 + m2)),
                "attachments": attachments}

    def polish_mail(self, body: str) -> dict:
        def work(job: Job):
            job.message = "AI가 문장을 다듬는 중…"
            c = self._client()
            s = self._cfg.settings
            model = c.pick_chat_model(s.chat_model)
            return {"body": c.chat([{"role": "user", "content": POLISH_PROMPT.format(body=body)}], model,
                                   temperature=0.3, num_ctx=s.num_ctx,
                                   on_token=lambda t: setattr(job, "text", job.text + t)).strip()}
        return self._run_job("polish", work)

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

    # ------------------------------------------------------------ 종료
    def shutdown(self) -> None:
        try:   # 앱을 닫으면 AI 모델이 차지하던 메모리를 바로 돌려준다
            c = self._client()
            c.unload(c.pick_chat_model(self._cfg.settings.chat_model))
        except Exception:
            pass
        if self._browser:
            self._browser.close()
        self._store.close()

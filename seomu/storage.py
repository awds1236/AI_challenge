"""SQLite 기반 로컬 저장소 (문서 색인, 공문, 할 일, 메일 양식)."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '기타',
    mtime REAL NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    n_chunks INTEGER NOT NULL DEFAULT 0,
    indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    heading TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    tokens TEXT NOT NULL,
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

CREATE TABLE IF NOT EXISTS notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    folder TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    attachments TEXT NOT NULL DEFAULT '[]',
    analysis TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id INTEGER REFERENCES notices(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    due TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mail_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    situation TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- 공통 ----------
    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def query(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ---------- 문서/청크 ----------
    def get_document(self, path: str) -> dict | None:
        rows = self.query("SELECT * FROM documents WHERE path=?", (path,))
        return rows[0] if rows else None

    def replace_document(self, path: str, title: str, category: str, mtime: float, size: int,
                         chunks: list[dict]) -> int:
        with self._lock:
            c = self.conn
            c.execute("DELETE FROM documents WHERE path=?", (path,))
            cur = c.execute(
                "INSERT INTO documents(path,title,category,mtime,size,n_chunks,indexed_at) VALUES(?,?,?,?,?,?,?)",
                (path, title, category, mtime, size, len(chunks), now_iso()),
            )
            doc_id = cur.lastrowid
            c.executemany(
                "INSERT INTO chunks(doc_id,ord,heading,text,tokens,embedding) VALUES(?,?,?,?,?,?)",
                [(doc_id, i, ch.get("heading", ""), ch["text"], " ".join(ch["tokens"]), ch.get("embedding"))
                 for i, ch in enumerate(chunks)],
            )
            c.commit()
            return doc_id

    def set_document_category(self, path: str, category: str) -> None:
        self.execute("UPDATE documents SET category=? WHERE path=?", (category, path))

    def delete_document(self, path: str) -> None:
        self.execute("DELETE FROM documents WHERE path=?", (path,))

    def list_documents(self) -> list[dict]:
        return self.query("SELECT id,path,title,category,size,n_chunks,indexed_at FROM documents ORDER BY category,title")

    def all_chunks(self) -> list[dict]:
        return self.query(
            "SELECT c.id,c.doc_id,c.ord,c.heading,c.text,c.tokens,c.embedding,d.title,d.path,d.category "
            "FROM chunks c JOIN documents d ON d.id=c.doc_id"
        )

    # ---------- 공문 ----------
    def add_notice(self, title: str, source: str, folder: str, body: str,
                   attachments: list, analysis: dict) -> int:
        cur = self.execute(
            "INSERT INTO notices(title,source,folder,body,attachments,analysis,created_at) VALUES(?,?,?,?,?,?,?)",
            (title, source, folder, body, json.dumps(attachments, ensure_ascii=False),
             json.dumps(analysis, ensure_ascii=False), now_iso()),
        )
        return cur.lastrowid

    def update_notice_analysis(self, notice_id: int, analysis: dict) -> None:
        self.execute("UPDATE notices SET analysis=? WHERE id=?",
                     (json.dumps(analysis, ensure_ascii=False), notice_id))

    def update_notice_attachments(self, notice_id: int, attachments: list) -> None:
        self.execute("UPDATE notices SET attachments=? WHERE id=?",
                     (json.dumps(attachments, ensure_ascii=False), notice_id))

    def _notice_row(self, r: dict) -> dict:
        r["attachments"] = json.loads(r.get("attachments") or "[]")
        r["analysis"] = json.loads(r.get("analysis") or "{}")
        return r

    def get_notice(self, notice_id: int) -> dict | None:
        rows = self.query("SELECT * FROM notices WHERE id=?", (notice_id,))
        return self._notice_row(rows[0]) if rows else None

    def list_notices(self) -> list[dict]:
        rows = self.query("SELECT * FROM notices ORDER BY id DESC")
        out = []
        for r in rows:
            r = self._notice_row(r)
            r.pop("body", None)
            out.append(r)
        return out

    def delete_notice(self, notice_id: int) -> None:
        self.execute("DELETE FROM tasks WHERE notice_id=?", (notice_id,))
        self.execute("DELETE FROM notices WHERE id=?", (notice_id,))

    # ---------- 할 일 ----------
    def add_task(self, title: str, detail: str = "", due: str | None = None,
                 notice_id: int | None = None) -> int:
        cur = self.execute(
            "INSERT INTO tasks(notice_id,title,detail,due,done,created_at) VALUES(?,?,?,?,0,?)",
            (notice_id, title, detail, due or None, now_iso()),
        )
        return cur.lastrowid

    def list_tasks(self, include_done: bool = True) -> list[dict]:
        sql = ("SELECT t.*, n.title AS notice_title, n.folder AS notice_folder FROM tasks t "
               "LEFT JOIN notices n ON n.id=t.notice_id")
        if not include_done:
            sql += " WHERE t.done=0"
        sql += " ORDER BY t.done ASC, CASE WHEN t.due IS NULL THEN 1 ELSE 0 END, t.due ASC, t.id DESC"
        return self.query(sql)

    def update_task(self, task_id: int, **values) -> None:
        allowed = {"title", "detail", "due", "done"}
        sets, params = [], []
        for k, v in values.items():
            if k in allowed:
                sets.append(f"{k}=?")
                params.append(int(bool(v)) if k == "done" else (v or None if k == "due" else v))
        if sets:
            params.append(task_id)
            self.execute(f"UPDATE tasks SET {','.join(sets)} WHERE id=?", params)

    def delete_task(self, task_id: int) -> None:
        self.execute("DELETE FROM tasks WHERE id=?", (task_id,))

    # ---------- 메일 양식 ----------
    def list_templates(self) -> list[dict]:
        return self.query("SELECT * FROM mail_templates ORDER BY id")

    def get_template(self, tid: int) -> dict | None:
        rows = self.query("SELECT * FROM mail_templates WHERE id=?", (tid,))
        return rows[0] if rows else None

    def save_template(self, name: str, subject: str, body: str, tid: int | None = None) -> int:
        if tid:
            self.execute("UPDATE mail_templates SET name=?,subject=?,body=?,updated_at=? WHERE id=?",
                         (name, subject, body, now_iso(), tid))
            return int(tid)
        cur = self.execute("INSERT INTO mail_templates(name,subject,body,updated_at) VALUES(?,?,?,?)",
                           (name, subject, body, now_iso()))
        return cur.lastrowid

    def delete_template(self, tid: int) -> None:
        self.execute("DELETE FROM mail_templates WHERE id=?", (tid,))

    # ---------- 대화 기록 ----------
    def add_chat(self, q: str, a: str, sources: list) -> None:
        self.execute("INSERT INTO chat_history(question,answer,sources,created_at) VALUES(?,?,?,?)",
                     (q, a, json.dumps(sources, ensure_ascii=False), now_iso()))

    def list_chat(self, limit: int = 30) -> list[dict]:
        rows = self.query("SELECT * FROM chat_history ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["sources"] = json.loads(r["sources"] or "[]")
        return list(reversed(rows))

    # ---------- 상황 안내 기록
    def add_guide(self, situation: str, result: dict) -> int:
        cur = self.execute("INSERT INTO guides(situation,result,created_at) VALUES(?,?,?)",
                           (situation, json.dumps(result, ensure_ascii=False), now_iso()))
        return cur.lastrowid

    def list_guides(self, limit: int = 20) -> list[dict]:
        rows = self.query("SELECT id, situation, result, created_at FROM guides ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["result"] = json.loads(r["result"] or "{}")
        return rows

    def get_guide(self, guide_id: int) -> dict | None:
        rows = self.query("SELECT * FROM guides WHERE id=?", (guide_id,))
        if not rows:
            return None
        rows[0]["result"] = json.loads(rows[0]["result"] or "{}")
        return rows[0]

    def delete_guide(self, guide_id: int) -> None:
        self.execute("DELETE FROM guides WHERE id=?", (guide_id,))

    def clear_chat(self) -> None:
        self.execute("DELETE FROM chat_history")

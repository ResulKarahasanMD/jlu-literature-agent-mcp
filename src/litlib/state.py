"""SQLite 状态层：任务队列、work 表、去重键、审计日志。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from litlib.config import paths
from litlib.logging_setup import sanitize
from litlib.models import (
    TaskState,
    Work,
    dedupe_keys_for,
    normalize_doi,
    parse_input_line,
    transition_allowed,
)

PRAGMAS = (
    "PRAGMA journal_mode=WAL;",
    "PRAGMA foreign_keys=ON;",
    "PRAGMA busy_timeout=5000;",
    "PRAGMA temp_store=FILE;",
    "PRAGMA cache_size=-32768;",
    "PRAGMA journal_size_limit=67108864;",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_id TEXT NOT NULL,
  source TEXT NOT NULL,
  raw_input TEXT NOT NULL,
  state TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS works (
  work_id TEXT PRIMARY KEY,
  doi TEXT, pmid TEXT, pmcid TEXT, arxiv TEXT,
  title TEXT, year INTEGER, journal TEXT, volume TEXT, issue TEXT, pages TEXT,
  authors TEXT, publisher TEXT,
  is_version_of TEXT,
  extra TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_id TEXT NOT NULL REFERENCES works(work_id),
  path TEXT NOT NULL,
  sha256 TEXT,
  size_bytes INTEGER,
  channel TEXT,
  verified_at TEXT,
  UNIQUE(work_id, path)
);
CREATE TABLE IF NOT EXISTS dedupe_keys (
  key_type TEXT NOT NULL,
  key_value TEXT NOT NULL,
  work_id TEXT NOT NULL REFERENCES works(work_id),
  PRIMARY KEY (key_type, key_value)
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  action TEXT NOT NULL,
  work_id TEXT,
  detail TEXT
);
CREATE TABLE IF NOT EXISTS route_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id),
  route TEXT NOT NULL,
  url TEXT,
  outcome TEXT NOT NULL,
  error TEXT,
  size_bytes INTEGER,
  started_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS zotero_map (
  work_id TEXT PRIMARY KEY REFERENCES works(work_id),
  zotero_key TEXT,
  import_batch TEXT,
  imported_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
CREATE INDEX IF NOT EXISTS idx_files_work ON files(work_id);
CREATE INDEX IF NOT EXISTS idx_route_attempts_task ON route_attempts(task_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DedupeConflictError(ValueError):
    """Raised when newly resolved metadata points at an existing work."""


class State:
    def __init__(self, db_path: Path | str = paths.sqlite_db, *, readonly: bool = False):
        self.db_path = Path(db_path)
        self.readonly = readonly
        if readonly:
            if not self.db_path.exists():
                raise FileNotFoundError(f"状态库不存在: {self.db_path}")
            uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True)
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        if readonly:
            self._conn.execute("PRAGMA query_only=ON;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
        else:
            for pragma in PRAGMAS:
                self._conn.execute(pragma)
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _audit(self, action: str, work_id: str | None, detail: str | None = None) -> None:
        self._conn.execute(
            "INSERT INTO audit_log (ts, action, work_id, detail) VALUES (?, ?, ?, ?)",
            (_now(), action, work_id, detail),
        )

    def queue_add(self, lines: list[str], source: str = "csv") -> tuple[int, int]:
        """返回 (新增任务数, 因重复跳过数)。"""
        added = 0
        skipped = 0
        for line in lines:
            parsed = parse_input_line(line)
            if parsed is None:
                continue
            kind, value = parsed
            if self._dedupe_exists(kind, value):
                skipped += 1
                continue
            work = Work()
            setattr(work, kind, value)
            work.created_at = _now()
            work.updated_at = work.created_at
            self._conn.execute(
                "INSERT INTO works (work_id, doi, pmid, pmcid, arxiv, title, year, journal,"
                " volume, issue, pages, authors, publisher, is_version_of, extra, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    work.work_id, work.doi, work.pmid, work.pmcid, work.arxiv,
                    work.title, work.year, work.journal, work.volume, work.issue,
                    work.pages, json.dumps(work.authors, ensure_ascii=False), work.publisher,
                    work.is_version_of, json.dumps(work.extra), work.created_at, work.updated_at,
                ),
            )
            for k, v in dedupe_keys_for(work).items():
                self._conn.execute(
                    "INSERT INTO dedupe_keys (key_type, key_value, work_id) VALUES (?, ?, ?)",
                    (k, v, work.work_id),
                )
            self._conn.execute(
                "INSERT INTO tasks (work_id, source, raw_input, state, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (work.work_id, source, sanitize(line.strip())[:500],
                 TaskState.QUEUED.value, _now(), _now()),
            )
            self._audit("queue_add", work.work_id, sanitize(f"{kind}={value}"))
            added += 1
        self._conn.commit()
        return added, skipped

    def _dedupe_exists(self, kind: str, value: str) -> bool:
        value = normalize_doi(value) if kind == "doi" else value.upper() if kind == "pmcid" else value
        row = self._conn.execute(
            "SELECT 1 FROM dedupe_keys WHERE key_type=? AND key_value=?", (kind, value)
        ).fetchone()
        return row is not None

    def set_state(self, task_id: int, new_state: TaskState, error: str | None = None) -> bool:
        row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise ValueError(f"task {task_id} 不存在")
        old = TaskState(row["state"])
        error = sanitize(error) if error else None
        now = _now()
        if old is new_state:
            # 同状态：仅更新错误信息（幂等），便于失败重试时刷新 last_error
            self._conn.execute(
                "UPDATE tasks SET last_error=?, updated_at=? WHERE id=?",
                (error, now, task_id),
            )
            self._conn.commit()
            return True
        if not transition_allowed(old, new_state):
            raise ValueError(f"非法状态迁移: {old.value} -> {new_state.value}")
        self._conn.execute(
            "UPDATE tasks SET state=?, last_error=?, updated_at=? WHERE id=?",
            (new_state.value, error, now, task_id),
        )
        self._audit("state_change", row["work_id"], f"{old.value}->{new_state.value}")
        self._conn.commit()
        return True

    def get_task(self, task_id: int) -> dict:
        row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else {}

    def get_work(self, work_id: str) -> Work | None:
        row = self._conn.execute("SELECT * FROM works WHERE work_id=?", (work_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["authors"] = json.loads(data["authors"] or "[]")
        data["extra"] = json.loads(data["extra"] or "{}")
        return Work(**data)

    def update_work(self, work: Work) -> None:
        keys = dedupe_keys_for(work)
        for key_type, key_value in keys.items():
            existing = self._conn.execute(
                "SELECT work_id FROM dedupe_keys WHERE key_type=? AND key_value=?",
                (key_type, key_value),
            ).fetchone()
            if existing and existing["work_id"] != work.work_id:
                raise DedupeConflictError(
                    f"去重冲突: {key_type}={key_value} 已属于 work {existing['work_id']}"
                )
        work.updated_at = _now()
        self._conn.execute(
            "UPDATE works SET doi=?, pmid=?, pmcid=?, arxiv=?, title=?, year=?, journal=?,"
            " volume=?, issue=?, pages=?, authors=?, publisher=?, is_version_of=?, extra=?, updated_at=?"
            " WHERE work_id=?",
            (
                work.doi, work.pmid, work.pmcid, work.arxiv, work.title, work.year,
                work.journal, work.volume, work.issue, work.pages,
                json.dumps(work.authors, ensure_ascii=False), work.publisher,
                work.is_version_of, json.dumps(work.extra), work.updated_at, work.work_id,
            ),
        )
        for k, v in keys.items():
            self._conn.execute(
                "INSERT OR IGNORE INTO dedupe_keys (key_type, key_value, work_id) VALUES (?, ?, ?)",
                (k, v, work.work_id),
            )
        self._conn.commit()

    def add_file(self, work_id: str, path: str, sha256: str, size_bytes: int, channel: str) -> None:
        if sha256:
            existing = self._conn.execute(
                "SELECT work_id FROM dedupe_keys WHERE key_type='sha256' AND key_value=?",
                (sha256,),
            ).fetchone()
            if existing and existing["work_id"] != work_id:
                raise DedupeConflictError(
                    f"PDF SHA-256 已属于 work {existing['work_id']}，拒绝登记到 {work_id}"
                )
        self._conn.execute(
            "INSERT INTO files (work_id, path, sha256, size_bytes, channel, verified_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(work_id, path) DO UPDATE SET sha256=excluded.sha256, "
            "size_bytes=excluded.size_bytes, channel=excluded.channel, verified_at=excluded.verified_at",
            (work_id, path, sha256, size_bytes, channel, _now()),
        )
        if sha256:
            self._conn.execute(
                "INSERT INTO dedupe_keys (key_type, key_value, work_id) VALUES ('sha256', ?, ?) "
                "ON CONFLICT(key_type, key_value) DO NOTHING",
                (sha256, work_id),
            )
        self._audit("file_added", work_id, f"channel={channel} sha256={sha256[:12]}...")
        self._conn.commit()

    def dedupe_owner(self, key_type: str, key_value: str) -> str | None:
        row = self._conn.execute(
            "SELECT work_id FROM dedupe_keys WHERE key_type=? AND key_value=?",
            (key_type, key_value),
        ).fetchone()
        return str(row["work_id"]) if row else None

    def get_files(self, work_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM files WHERE work_id=? ORDER BY id", (work_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_reviewed(self, task_id: int) -> bool:
        """提案审阅完成：PROPOSAL_GENERATED → USER_REVIEWED。"""
        return self.set_state(task_id, TaskState.USER_REVIEWED)

    def mark_proposal_generated(self, task_ids: list[int]) -> None:
        """Atomically mark validated READY tasks after both proposal files are durable."""
        now = _now()
        with self._conn:
            for task_id in task_ids:
                row = self._conn.execute(
                    "SELECT work_id, state FROM tasks WHERE id=?", (task_id,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"task {task_id} 不存在")
                state = TaskState(row["state"])
                if state is TaskState.PROPOSAL_GENERATED:
                    continue
                if state is not TaskState.READY:
                    raise ValueError(f"task {task_id} 不是 READY: {state.value}")
                self._conn.execute(
                    "UPDATE tasks SET state=?, last_error=NULL, updated_at=? WHERE id=?",
                    (TaskState.PROPOSAL_GENERATED.value, now, task_id),
                )
                self._audit(
                    "state_change", row["work_id"],
                    f"{TaskState.READY.value}->{TaskState.PROPOSAL_GENERATED.value}",
                )

    def mark_imported(self, work_id: str, zotero_key: str | None, batch: str) -> None:
        """记录 Zotero 导入映射并标记任务 IMPORTED。"""
        if not zotero_key:
            raise ValueError("缺少已验证的 Zotero item key，不能标记 IMPORTED")
        row = self._conn.execute(
            "SELECT id FROM tasks WHERE work_id=? ORDER BY id LIMIT 1", (work_id,)
        ).fetchone()
        if row is not None:
            task = self.get_task(row["id"])
            state = TaskState(task["state"])
            if state is not TaskState.IMPORTED:
                if state is not TaskState.USER_REVIEWED:
                    raise ValueError(f"只有 USER_REVIEWED 可确认导入，当前为 {state.value}")
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO zotero_map (work_id, zotero_key, import_batch, imported_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(work_id) DO UPDATE SET zotero_key=excluded.zotero_key, "
                "import_batch=excluded.import_batch, imported_at=excluded.imported_at",
                (work_id, zotero_key, batch, now),
            )
            if row is not None and state is not TaskState.IMPORTED:
                self._conn.execute(
                    "UPDATE tasks SET state=?, last_error=NULL, updated_at=? WHERE id=?",
                    (TaskState.IMPORTED.value, now, row["id"]),
                )
                self._audit(
                    "state_change", work_id,
                    f"{TaskState.USER_REVIEWED.value}->{TaskState.IMPORTED.value}",
                )
            self._audit("zotero_import", work_id, f"batch={batch} key={zotero_key}")

    def get_zotero_map(self, work_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM zotero_map WHERE work_id=?", (work_id,)
        ).fetchone()
        return dict(row) if row else None

    def search_works(self, query: str, limit: int = 20) -> list[dict]:
        normalized_doi = normalize_doi(query)
        like = f"%{query.casefold()}%"
        rows = self._conn.execute(
            "SELECT work_id, title, year, doi, authors FROM works "
            "WHERE LOWER(COALESCE(doi, ''))=? "
            "OR LOWER(COALESCE(title, '')) LIKE ? "
            "OR LOWER(COALESCE(authors, '')) LIKE ? "
            "ORDER BY CASE WHEN LOWER(COALESCE(doi, ''))=? THEN 0 ELSE 1 END, year DESC "
            "LIMIT ?",
            (normalized_doi, like, like, normalized_doi, limit),
        ).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            result["authors"] = json.loads(result.get("authors") or "[]")
            results.append(result)
        return results

    def find_work_by_doi(self, doi: str) -> Work | None:
        row = self._conn.execute(
            "SELECT work_id FROM works WHERE LOWER(doi)=?", (normalize_doi(doi),)
        ).fetchone()
        return self.get_work(row["work_id"]) if row else None

    def get_task_for_work(self, work_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE work_id=? ORDER BY id LIMIT 1", (work_id,)
        ).fetchone()
        return dict(row) if row else {}

    def state_counts(self) -> dict[str, int]:
        rows = self._conn.execute("SELECT state, COUNT(*) c FROM tasks GROUP BY state").fetchall()
        return {r["state"]: r["c"] for r in rows}

    def recover_incomplete(self, include_failed: bool = False,
                           include_paused: bool = False) -> tuple[int, int]:
        """将崩溃遗留的中间状态重新排队；返回 (已恢复, 达重试上限跳过)。"""
        states = [
            TaskState.METADATA_FETCH.value,
            TaskState.OA_OK.value,
            TaskState.INST_QUEUED.value,
            TaskState.DOWNLOADING.value,
            TaskState.VERIFYING.value,
        ]
        if include_failed:
            states.append(TaskState.FAILED.value)
        if include_paused:
            states.extend((TaskState.HUMAN_REQUIRED.value, TaskState.RATE_LIMITED.value))
        placeholders = ",".join("?" for _ in states)
        rows = self._conn.execute(
            f"SELECT * FROM tasks WHERE state IN ({placeholders}) ORDER BY id", states
        ).fetchall()
        recovered = 0
        skipped = 0
        for row in rows:
            if row["attempt_count"] >= row["max_attempts"]:
                skipped += 1
                continue
            old = row["state"]
            self._conn.execute(
                "UPDATE tasks SET state=?, last_error=?, updated_at=? WHERE id=?",
                (TaskState.QUEUED.value, f"recovered from {old}", _now(), row["id"]),
            )
            self._audit("task_recover", row["work_id"], f"{old}->QUEUED")
            recovered += 1
        self._conn.commit()
        return recovered, skipped

    def begin_attempt(self, task_id: int) -> bool:
        """递增任务尝试次数；达到上限返回 False。"""
        row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise ValueError(f"task {task_id} 不存在")
        if row["attempt_count"] >= row["max_attempts"]:
            return False
        self._conn.execute(
            "UPDATE tasks SET attempt_count=attempt_count+1, updated_at=? WHERE id=?",
            (_now(), task_id),
        )
        self._audit("attempt_begin", row["work_id"], f"attempt={row['attempt_count'] + 1}")
        self._conn.commit()
        return True

    def start_route_attempt(self, task_id: int, route: str, url: str = "") -> int:
        now = _now()
        cur = self._conn.execute(
            "INSERT INTO route_attempts (task_id, route, url, outcome, started_at) "
            "VALUES (?, ?, ?, 'RUNNING', ?)",
            (task_id, route, sanitize(url)[:1000], now),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def finish_route_attempt(self, attempt_id: int, outcome: str, error: str = "",
                             size_bytes: int | None = None) -> None:
        self._conn.execute(
            "UPDATE route_attempts SET outcome=?, error=?, size_bytes=?, finished_at=? WHERE id=?",
            (outcome, sanitize(error)[:1000] or None, size_bytes, _now(), attempt_id),
        )
        self._conn.commit()

    def get_route_attempts(self, task_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM route_attempts WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def list_tasks(self, state: TaskState | None = None, limit: int = 100) -> list[dict]:
        if state is None:
            rows = self._conn.execute("SELECT * FROM tasks ORDER BY id LIMIT ?", (limit,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE state=? ORDER BY id LIMIT ?", (state.value, limit)
            ).fetchall()
        return [dict(r) for r in rows]

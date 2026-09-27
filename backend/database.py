import os
from pathlib import Path
import json
import re
import sqlite3
from datetime import datetime
from typing import Any


BASE_DIR = Path(os.getenv("HEALTH_VAULT_HOME", Path(__file__).resolve().parent.parent)).resolve()
REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "data" / "log"
MOCK_DB_PATH = REPO_ROOT / "tests" / "fixtures" / "health_mock.db"

WRITE_SQL_RE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)
TABLE_PATTERNS = (
    re.compile(r"^\s*INSERT\s+(?:OR\s+\w+\s+)?INTO\s+([^\s(]+)", re.IGNORECASE),
    re.compile(r"^\s*REPLACE\s+(?:OR\s+\w+\s+)?INTO\s+([^\s(]+)", re.IGNORECASE),
    re.compile(r"^\s*UPDATE\s+([^\s]+)", re.IGNORECASE),
    re.compile(r"^\s*DELETE\s+FROM\s+([^\s]+)", re.IGNORECASE),
)


def is_mock_mode() -> bool:
    return os.getenv("HEALTH_MOCK_MODE", "").lower() in {"1", "true", "yes", "on"}


def _default_db_path() -> Path:
    if is_mock_mode():
        # 模拟库是随仓库分发的测试夹具，不跟随 HEALTH_VAULT_HOME。
        return MOCK_DB_PATH
    return BASE_DIR / "data" / "health.db"


DB_PATH = Path(os.getenv("HEALTH_DB_PATH", _default_db_path())).resolve()
SCHEMA_VERSION = 2

# 记事 kind 白名单（唯一定义）。启动迁移与写入校验共用，改这里一处即可。
PET_CARE_KINDS = ("驱虫", "洗澡", "换猫砂")


def database_needs_migration() -> bool:
    """Whether an existing database needs a schema upgrade backup before startup."""
    if not DB_PATH.is_file():
        return False
    try:
        with sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True) as conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0]) < SCHEMA_VERSION
    except sqlite3.Error:
        # init_db will surface a more useful error for an unreadable database.
        return False


def _compact_sql(sql: str) -> str:
    return " ".join(sql.strip().split())


def _write_action(sql: str) -> str | None:
    match = WRITE_SQL_RE.match(sql)
    return match.group(1).upper() if match else None


def _write_table(sql: str) -> str | None:
    for pattern in TABLE_PATTERNS:
        match = pattern.match(sql)
        if match:
            return match.group(1).strip('"`[]')
    return None


def _append_operation_log(entry: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"db_operations_{datetime.now().strftime('%Y-%m')}.jsonl"
    with log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


class LoggedConnection(sqlite3.Connection):
    def __init__(self, *args: Any, log_writes: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._log_writes = log_writes
        self._change_start = self.total_changes
        self._write_statements: list[dict[str, Any]] = []

    def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
        cursor = super().execute(sql, parameters)
        self._track_write(sql, cursor)
        return cursor

    def executemany(self, sql: str, parameters: Any, /) -> sqlite3.Cursor:
        cursor = super().executemany(sql, parameters)
        self._track_write(sql, cursor)
        return cursor

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        try:
            result = super().__exit__(exc_type, exc_value, traceback)
            if exc_type is None:
                self._log_committed_writes()
            return result
        finally:
            self.close()

    def _track_write(self, sql: str, cursor: sqlite3.Cursor) -> None:
        if not self._log_writes:
            return
        action = _write_action(sql)
        if not action:
            return
        self._write_statements.append(
            {
                "action": action,
                "table": _write_table(sql),
                "rowcount": cursor.rowcount,
                "lastrowid": cursor.lastrowid,
                "sql": _compact_sql(sql),
            }
        )

    def _log_committed_writes(self) -> None:
        change_count = self.total_changes - self._change_start
        if not self._write_statements or change_count <= 0:
            return
        _append_operation_log(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "db_path": str(DB_PATH),
                "mock_mode": is_mock_mode(),
                "pid": os.getpid(),
                "change_count": change_count,
                "statements": self._write_statements,
            }
        )
        self._write_statements = []
        self._change_start = self.total_changes


def get_conn(log_writes: bool = True) -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        DB_PATH,
        factory=lambda *args, **kwargs: LoggedConnection(*args, log_writes=log_writes, **kwargs),
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    with get_conn(log_writes=False) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS members (
              key         TEXT PRIMARY KEY,
              name        TEXT NOT NULL,
              full_name   TEXT,
              initial     TEXT,
              birth_date  TEXT,
              sex         TEXT,
              blood_type  TEXT,
              role        TEXT,
              species     TEXT NOT NULL DEFAULT 'human',
              species_detail TEXT,
              sort_order  INTEGER DEFAULT 0,
              breed       TEXT,
              home_date   TEXT,
              chip_id     TEXT,
              doctor      TEXT,
              allergies   TEXT DEFAULT '[]',
              chronic     TEXT DEFAULT '[]',
              notes       TEXT,
              archived_at TEXT,
              created_at  TEXT DEFAULT (datetime('now','localtime')),
              updated_at  TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS visits (
              id              INTEGER PRIMARY KEY AUTOINCREMENT,
              member_key      TEXT NOT NULL REFERENCES members(key),
              date            TEXT NOT NULL,
              type            TEXT,
              hospital        TEXT,
              department      TEXT,
              doctor          TEXT,
              chief_complaint TEXT,
              severity        TEXT CHECK (severity IS NULL OR severity IN ('严重', '轻微', '一般')),
              diagnosis       TEXT DEFAULT '[]',
              notes           TEXT,
              note_full       TEXT,
              source_file     TEXT,
              created_at      TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS lab_results (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              member_key  TEXT NOT NULL REFERENCES members(key),
              visit_id    INTEGER REFERENCES visits(id),
              date        TEXT NOT NULL,
              panel       TEXT NOT NULL,
              test_name   TEXT NOT NULL,
              value       TEXT,
              unit        TEXT,
              ref_low     TEXT,
              ref_high    TEXT,
              status      TEXT,
              source_file TEXT,
              created_at  TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS meds (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              member_key  TEXT NOT NULL REFERENCES members(key),
              visit_id    INTEGER REFERENCES visits(id),
              name        TEXT NOT NULL,
              dose        TEXT,
              freq        TEXT,
              route       TEXT,
              start_date  TEXT,
              end_date    TEXT,
              ongoing     INTEGER NOT NULL DEFAULT 0,
              notes       TEXT,
              created_at  TEXT DEFAULT (datetime('now','localtime')),
              updated_at  TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS weight_log (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              member_key  TEXT NOT NULL REFERENCES members(key),
              date        TEXT NOT NULL,
              weight_kg   REAL NOT NULL,
              notes       TEXT,
              created_at  TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS pet_care_logs (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              member_key  TEXT NOT NULL REFERENCES members(key),
              date        TEXT NOT NULL,
              kind        TEXT NOT NULL,
              notes       TEXT,
              created_at  TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS attachments (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              member_key  TEXT NOT NULL REFERENCES members(key),
              visit_id    INTEGER REFERENCES visits(id),
              date        TEXT NOT NULL,
              title       TEXT NOT NULL,
              org         TEXT,
              tag         TEXT,
              filename    TEXT,
              file_path   TEXT,
              notes       TEXT,
              created_at  TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS agent_change_log (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              tool        TEXT NOT NULL,
              table_name  TEXT NOT NULL,
              row_id      TEXT NOT NULL,
              action      TEXT NOT NULL CHECK (action IN ('create', 'update', 'delete')),
              before_json TEXT,
              after_json  TEXT,
              undone_at   TEXT,
              created_at  TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS agent_messages (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id  TEXT NOT NULL DEFAULT 'default',
              role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
              content     TEXT NOT NULL,
              created_at  TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE INDEX IF NOT EXISTS idx_visits_member       ON visits(member_key, date);
            CREATE INDEX IF NOT EXISTS idx_labs_member         ON lab_results(member_key, test_name, date);
            CREATE INDEX IF NOT EXISTS idx_labs_panel          ON lab_results(member_key, panel);
            CREATE INDEX IF NOT EXISTS idx_meds_member         ON meds(member_key);
            CREATE INDEX IF NOT EXISTS idx_weight_member       ON weight_log(member_key, date);
            CREATE INDEX IF NOT EXISTS idx_pet_care_member    ON pet_care_logs(member_key, date);
            CREATE INDEX IF NOT EXISTS idx_attachments_member  ON attachments(member_key, date);
            CREATE INDEX IF NOT EXISTS idx_agent_messages_session ON agent_messages(session_id, id);
            """
        )
        pet_care_cols = {row[1] for row in conn.execute("PRAGMA table_info(pet_care_logs)").fetchall()}
        if pet_care_cols:
            # 记事只保留 kind：删除非法 kind 的测试行，title 差异信息回填 notes 后删 title 列。
            # 记事只保留白名单 kind，见 PET_CARE_KINDS。
            conn.execute(
                f"DELETE FROM pet_care_logs WHERE kind NOT IN ({','.join('?' for _ in PET_CARE_KINDS)})",
                tuple(PET_CARE_KINDS),
            )
            if "title" in pet_care_cols:
                for care_row in conn.execute("SELECT id, kind, title, notes FROM pet_care_logs").fetchall():
                    care_title = (care_row["title"] or "").strip()
                    care_notes = care_row["notes"] or ""
                    if care_title and care_title != care_row["kind"] and care_title not in care_notes:
                        merged_notes = f"{care_title} · {care_notes}" if care_notes else care_title
                        conn.execute(
                            "UPDATE pet_care_logs SET notes = ? WHERE id = ?",
                            (merged_notes, care_row["id"]),
                        )
                conn.execute("ALTER TABLE pet_care_logs DROP COLUMN title")
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(meds)").fetchall()}
        if "category" not in existing_cols:
            conn.execute("ALTER TABLE meds ADD COLUMN category TEXT")

        visit_cols = {row[1] for row in conn.execute("PRAGMA table_info(visits)").fetchall()}
        if "type" not in visit_cols:
            conn.execute("ALTER TABLE visits ADD COLUMN type TEXT")
        if "severity" not in visit_cols:
            conn.execute("ALTER TABLE visits ADD COLUMN severity TEXT")
        if "note_full" not in visit_cols:
            conn.execute("ALTER TABLE visits ADD COLUMN note_full TEXT")
        conn.execute(
            """
            UPDATE visits
            SET type = CASE
              WHEN chief_complaint LIKE '%体检%'
                   OR EXISTS (
                     SELECT 1
                     FROM attachments
                     WHERE attachments.visit_id = visits.id
                       AND attachments.tag IN ('体检', '体检报告')
                   )
                THEN '体检'
              ELSE '就医'
            END
            WHERE type IS NULL OR type = ''
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_visits_member_type ON visits(member_key, type, date)")

        member_cols = {row[1] for row in conn.execute("PRAGMA table_info(members)").fetchall()}
        if "breed" not in member_cols:
            conn.execute("ALTER TABLE members ADD COLUMN breed TEXT")
        if "home_date" not in member_cols:
            conn.execute("ALTER TABLE members ADD COLUMN home_date TEXT")
        if "species_detail" not in member_cols:
            conn.execute("ALTER TABLE members ADD COLUMN species_detail TEXT")
        if "sort_order" not in member_cols:
            conn.execute("ALTER TABLE members ADD COLUMN sort_order INTEGER")
        if "archived_at" not in member_cols:
            conn.execute("ALTER TABLE members ADD COLUMN archived_at TEXT")
        max_sort_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS value FROM members WHERE sort_order IS NOT NULL AND sort_order > 0"
        ).fetchone()["value"]
        rows = conn.execute(
            """
            SELECT key
            FROM members
            WHERE sort_order IS NULL OR sort_order = 0
            ORDER BY created_at, key
            """
        ).fetchall()
        for index, row in enumerate(rows, start=1):
            conn.execute(
                "UPDATE members SET sort_order = ? WHERE key = ?",
                (max_sort_order + index * 10, row["key"]),
            )

        # v2: reminders → pet_care_logs。只迁已完成的宠物行；人类提醒和未完成的未来提醒随旧表一起删除。
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
        if "reminders" in tables:
            # 非白名单 kind 归入“记事”，原 kind 并入 notes 保留信息。
            kind_list = ",".join("?" for _ in PET_CARE_KINDS)
            conn.execute(
                f"""
                INSERT OR IGNORE INTO pet_care_logs (id, member_key, date, kind, notes)
                SELECT r.id, r.member_key, r.date,
                       CASE WHEN r.kind IN ({kind_list}) THEN r.kind ELSE '记事' END,
                       CASE WHEN r.kind IN ({kind_list}) THEN r.notes
                            ELSE COALESCE(r.kind, '') || CASE WHEN r.notes IS NULL OR r.notes = '' THEN '' ELSE '｜' || r.notes END END
                FROM reminders r
                JOIN members m ON m.key = r.member_key
                WHERE r.done = 1 AND m.species != 'human'
                """,
                tuple(PET_CARE_KINDS) + tuple(PET_CARE_KINDS),
            )
            conn.execute("DROP TABLE IF EXISTS reminders")
        conn.execute("DROP INDEX IF EXISTS idx_reminders_auto_key")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

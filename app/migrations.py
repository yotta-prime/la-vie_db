"""Schema migrations for an existing SQLite database.

A fresh database is created straight from the models and stamped with the latest version.
An existing one gets each pending migration in order, inside one transaction, after a
copy of the file is saved next to it (`<db>.pre-v<N>.bak`).
"""

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db import Base

log = logging.getLogger(__name__)


def _create_table_sql(engine: Engine, name: str) -> list[str]:
    table = Base.metadata.tables[name]
    stmts = [str(CreateTable(table).compile(engine))]
    stmts += [str(CreateIndex(ix).compile(engine)) for ix in table.indexes]
    return stmts


def _m001_courses(cur: sqlite3.Cursor, engine: Engine) -> None:
    """Paths contain courses; hobby elements become projects; links on routines."""
    for table in ("learning_path", "path_step", "flashcard", "hobby_element", "schedule_rule"):
        (n,) = cur.execute(f"SELECT count(*) FROM {table}").fetchone()
        if n:
            raise RuntimeError(f"migration 1 expects {table} to be empty (found {n} rows)")
    for table in ("flashcard", "path_step", "hobby_element", "schedule_rule", "learning_path"):
        cur.execute(f"DROP TABLE {table}")

    cur.execute("ALTER TABLE routine ADD COLUMN url VARCHAR(500)")
    cur.execute("ALTER TABLE routine ADD COLUMN notes TEXT")
    cur.execute("ALTER TABLE routine_step ADD COLUMN url VARCHAR(500)")

    # log_entry swaps path/element columns for course/project ones: rebuild, keeping rows.
    keep = "id, created_at, area, prompt_id, label, routine_id, hobby_id, outcome, duration_min, rating, note"
    cur.execute("DROP INDEX IF EXISTS ix_log_entry_created_at")
    cur.execute("ALTER TABLE log_entry RENAME TO log_entry_v0")
    for sql in _create_table_sql(engine, "log_entry"):
        cur.execute(sql)
    cur.execute(f"INSERT INTO log_entry ({keep}) SELECT {keep} FROM log_entry_v0")
    cur.execute("DROP TABLE log_entry_v0")
    # New tables (course, course_step, hobby_project, ...) are created by create_all afterwards.


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Cursor, Engine], None]]] = [
    (1, _m001_courses),
]
LATEST = MIGRATIONS[-1][0]


def _version(cur: sqlite3.Cursor) -> int:
    cur.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = cur.execute("SELECT version FROM schema_version").fetchone()
    return row[0] if row else 0


def _stamp(cur: sqlite3.Cursor, version: int) -> None:
    cur.execute("DELETE FROM schema_version")
    cur.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))


def migrate(engine: Engine) -> None:
    from app import models  # noqa: F401  (register tables)

    fresh = "routine" not in inspect(engine).get_table_names()
    db_file = Path(engine.url.database)

    raw = sqlite3.connect(db_file, isolation_level=None)
    try:
        cur = raw.cursor()
        current = LATEST if fresh else _version(cur)
        pending = [(v, fn) for v, fn in MIGRATIONS if v > current]
        if pending:
            backup = db_file.with_name(f"{db_file.name}.pre-v{pending[-1][0]}.bak")
            with sqlite3.connect(backup) as dst:
                raw.backup(dst)
            log.info("Migrating schema v%d -> v%d (backup: %s)", current, LATEST, backup.name)

            cur.execute("PRAGMA foreign_keys=OFF")
            cur.execute("BEGIN")
            try:
                for version, fn in pending:
                    fn(cur, engine)
                    _stamp(cur, version)
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
            finally:
                cur.execute("PRAGMA foreign_keys=ON")
    finally:
        raw.close()

    Base.metadata.create_all(engine)

    if fresh:
        raw = sqlite3.connect(db_file, isolation_level=None)
        try:
            cur = raw.cursor()
            _version(cur)
            _stamp(cur, LATEST)
        finally:
            raw.close()

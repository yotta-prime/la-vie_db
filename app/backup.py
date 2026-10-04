"""Nightly SQLite online backup with rotation. Hyper Backup covers the backup folder."""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def backup_sqlite(db_path: Path, backup_dir: Path, keep: int) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"lavie-{datetime.now():%Y%m%d-%H%M%S}.db"

    # The backup API copies a consistent snapshot even while the app is writing.
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(target)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()

    old = sorted(backup_dir.glob("lavie-*.db"))[:-keep] if keep > 0 else []
    for f in old:
        f.unlink()

    log.info("Backup written to %s (%d old removed)", target, len(old))
    return target

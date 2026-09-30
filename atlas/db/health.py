"""Database health check and repair.

The classic failure on a laptop install: a new ``atlas.db`` is unzipped next to
an old ``atlas.db-wal`` / ``atlas.db-shm`` pair (or the machine went down while
a job was writing). SQLite then reports "database disk image is malformed" and
every page of the web app becomes a 500. ``check()`` runs before the UI or a
pipeline starts and returns a readable diagnosis; ``repair()`` fixes the
common cases automatically:

  1. stale WAL/SHM  -> move them aside (``*.stale``) and re-check
  2. still corrupt  -> recover every readable row into a fresh file
                       (the old one is kept as ``atlas.db.corrupt-<timestamp>``)
  3. nothing usable -> start with an empty database and tell the user how to
                       rebuild from ``data/input`` (one pipeline run)

Nothing here needs SQLAlchemy - it works on the file with the sqlite3 module.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DbHealth:
    ok: bool
    path: Path
    problems: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    tables: int = 0
    objects: int = 0

    def summary(self) -> str:
        if self.ok:
            return f"Database OK - {self.tables} tables, {self.objects} objects ({self.path})"
        return "Database problem: " + "; ".join(self.problems)


def _quick_check(path: Path) -> tuple[bool, str]:
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute("PRAGMA quick_check").fetchone()
            tables = con.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            if row and row[0] == "ok":
                return True, f"{tables}"
            return False, str(row[0] if row else "quick_check returned nothing")
        finally:
            con.close()
    except sqlite3.DatabaseError as error:
        return False, str(error)


def _shipped_in_rollback_mode(db_path: Path) -> bool:
    """A database whose header says 'rollback journal' cannot have a valid WAL - any atlas.db-wal/-shm
    next to it is left over from another file and would corrupt this one on first open."""
    try:
        with open(db_path, "rb") as fh:
            head = fh.read(100)
        return len(head) >= 20 and head[:16] == b"SQLite format 3\x00" and head[18] == 1 and head[19] == 1
    except OSError:
        return False


def quarantine_stale_logs(db_path: Path) -> list[str]:
    """Move atlas.db-wal / -shm aside when they cannot belong to this database. Safe to call always."""
    db_path = Path(db_path)
    actions: list[str] = []
    if not db_path.exists() or not _shipped_in_rollback_mode(db_path):
        return actions
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for suffix in ("-wal", "-shm"):
        side = db_path.with_name(db_path.name + suffix)
        if not side.exists():
            continue
        target = side.with_name(side.name + f".stale-{stamp}")
        try:
            shutil.move(str(side), str(target))
        except OSError:
            # held open by a running Beacon (web app in another window) - that log is live, leave it alone
            actions.append(f"{side.name} is in use by a running ABAP Beacon - left in place (stop the web app before db-check / db-repair)")
            continue
        actions.append(f"moved stale {side.name} aside -> {target.name} (it belonged to a previous database)")
    return actions


def check(db_path: Path) -> DbHealth:
    db_path = Path(db_path)
    if not db_path.exists():
        return DbHealth(True, db_path, tables=0)
    ok, info = _quick_check(db_path)
    if not ok:
        h = DbHealth(False, db_path, [f"{db_path.name}: {info}"])
        if (db_path.with_name(db_path.name + "-wal")).exists() or (db_path.with_name(db_path.name + "-shm")).exists():
            h.problems.append("a write-ahead log (atlas.db-wal / -shm) sits next to the database - probably left over from a previous version or an interrupted run")
        return h
    h = DbHealth(True, db_path, tables=int(info))
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5)
        try:
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='objects'").fetchone():
                h.objects = con.execute("SELECT count(*) FROM objects").fetchone()[0]
        finally:
            con.close()
    except sqlite3.DatabaseError:
        pass
    return h


def repair(db_path: Path) -> DbHealth:
    """Fix what can be fixed; always leaves a usable (possibly empty) database behind."""
    db_path = Path(db_path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    actions: list[str] = []
    health = check(db_path)
    if health.ok:
        return health

    # 1 stale WAL / SHM
    moved = False
    for suffix in ("-wal", "-shm", "-journal"):
        side = db_path.with_name(db_path.name + suffix)
        if side.exists():
            target = side.with_name(side.name + f".stale-{stamp}")
            try:
                shutil.move(str(side), str(target))
            except OSError:
                actions.append(f"{side.name} is in use by a running ABAP Beacon - stop the web app and run db-repair again")
                return DbHealth(False, db_path, ["database is open in another ABAP Beacon window"], actions)
            actions.append(f"moved {side.name} aside -> {target.name}")
            moved = True
    if moved:
        health = check(db_path)
        if health.ok:
            health.actions = actions + ["database is healthy again (the stale log was the problem; the .stale files can be deleted)"]
            return health

    # 2 recover readable rows into a fresh file
    corrupt = db_path.with_name(db_path.name + f".corrupt-{stamp}")
    shutil.move(str(db_path), str(corrupt))
    actions.append(f"kept the damaged file as {corrupt.name}")
    recovered_tables = 0
    try:
        src = sqlite3.connect(f"file:{corrupt.as_posix()}?mode=ro", uri=True, timeout=5)
        dst = sqlite3.connect(db_path.as_posix())
        try:
            rows = src.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END").fetchall()
            for kind, name, sql in rows:
                try:
                    dst.execute(sql)
                    if kind == "table":
                        cur = src.execute(f'SELECT * FROM "{name}"')
                        cols = len(cur.description)
                        dst.executemany(f'INSERT OR IGNORE INTO "{name}" VALUES ({",".join("?" * cols)})', cur)
                        recovered_tables += 1
                except sqlite3.DatabaseError as error:
                    actions.append(f"could not recover {kind} {name}: {error}")
            dst.commit()
        finally:
            src.close()
            dst.close()
    except sqlite3.DatabaseError as error:
        actions.append(f"recovery read failed: {error}")
    for suffix in ("-wal", "-shm", "-journal"):          # side files SQLite created while reading the damaged copy
        side = corrupt.with_name(corrupt.name + suffix)
        if side.exists():
            side.unlink()
    if recovered_tables:
        actions.append(f"recovered {recovered_tables} table(s) into a fresh {db_path.name}")
    else:
        actions.append("no usable content in the damaged file - starting with an empty database")
    health = check(db_path) if db_path.exists() else DbHealth(True, db_path)
    if not health.ok:
        # 3 give up on the content, keep the product usable
        if db_path.exists():
            shutil.move(str(db_path), str(db_path.with_name(db_path.name + f".unrecoverable-{stamp}")))
        actions.append("no usable content - starting with an empty database")
        health = DbHealth(True, db_path)
    health.actions = actions + ["if objects are missing, rebuild from data/input with one pipeline run: run.bat  (or: atlas run)"]
    return health


def ensure_healthy(db_path: Path, auto_repair: bool = True) -> DbHealth:
    """Used at start-up: quarantine logs that cannot belong to this file, check, repair when allowed."""
    pre = quarantine_stale_logs(db_path) if auto_repair else []
    health = check(db_path)
    if not health.ok and auto_repair:
        health = repair(db_path)
    health.actions = pre + health.actions
    return health

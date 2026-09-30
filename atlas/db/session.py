"""Engine and session management.

`get_engine()` is cached per database URL. SQLite is opened in WAL mode with
foreign keys on, which makes it safe for a background job writing while the
UI reads.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from atlas.config import Settings, get_settings
from atlas.db.models import Base


@lru_cache(maxsize=8)
def get_engine(database_url: str) -> Engine:
    engine = create_engine(database_url, future=True)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def init_db(settings: Settings | None = None) -> Engine:
    """Create the data folders and all tables (no-op if they exist)."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    engine = get_engine(settings.database_url)
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    return engine


def _add_missing_columns(engine: Engine) -> None:
    """Additive schema upgrade: a newer release may add columns to existing tables; create_all does not
    add them, so an older atlas.db is upgraded in place (SQLite ALTER TABLE ... ADD COLUMN). Never drops."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as con:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ctype = col.type.compile(engine.dialect)
                default = ""
                if col.default is not None and getattr(col.default, "arg", None) is not None and not callable(col.default.arg):
                    v = col.default.arg
                    default = f" DEFAULT {v!r}" if isinstance(v, str) else f" DEFAULT {int(v) if isinstance(v, bool) else v}"
                con.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ctype}{default}'))


@contextmanager
def session_scope(settings: Settings | None = None) -> Iterator[Session]:
    """Transactional scope: commits on success, rolls back on error."""
    engine = init_db(settings)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

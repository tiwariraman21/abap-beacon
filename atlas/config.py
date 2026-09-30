"""Runtime configuration for ABAP Beacon (package name: atlas).

Resolution order: explicit argument > environment variable > default.
Everything lives under one data directory so a whole installation can be
backed up, moved or deleted as a unit (client off-boarding requirement).

    ATLAS_DATA_DIR   where the database, indexes and staged inputs live
                     (default: ./data next to the project root)
    ATLAS_DB_URL     SQLAlchemy URL; default is SQLite inside the data dir.
                     Switching to PostgreSQL later is this one variable.
    ATLAS_LOG_LEVEL  DEBUG / INFO / WARNING (default INFO)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("ATLAS_DATA_DIR", PROJECT_ROOT / "data")))
    db_url: str | None = field(default_factory=lambda: os.environ.get("ATLAS_DB_URL"))
    log_level: str = field(default_factory=lambda: os.environ.get("ATLAS_LOG_LEVEL", "INFO"))

    @property
    def input_dir(self) -> Path:
        return self.data_dir / "input"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "atlas.db"

    @property
    def database_url(self) -> str:
        if self.db_url:
            return self.db_url
        return f"sqlite:///{self.db_path.as_posix()}"

    def ensure_dirs(self) -> None:
        for folder in (self.data_dir, self.input_dir, self.output_dir, self.index_dir):
            folder.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()

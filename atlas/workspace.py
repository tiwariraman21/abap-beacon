"""Workspaces - one isolated data set per customer (or the InfraBeat internal library).

The reviewers' question "is this a product for customers or InfraBeat's own repository?" is answered
by data separation, not by two products: the same engine runs on one workspace at a time.

  data/                          the default workspace (kept for compatibility: the demo repository)
  data/workspaces/<slug>/        every other workspace: its own atlas.db, index, input, output, config
  data/workspaces/<slug>/workspace.json

      {"name": "ACME Retail", "kind": "customer" | "internal", "customer": "ACME Retail",
       "ai_mode": "normal" | "strict",          strict = AI completely off for this workspace
       "target_release": "2023" | "cloud",      assessment rule variant (like ATC check variants)
       "deployment": "onprem" | "cloud", "notes": ""}

FSD matching, search, assessments and the executive numbers only ever see the active workspace, so
five customers' ageing reports never meet. They only meet in an *internal* workspace, where every
object carries its origin, and reuse across customers is a licensing question, not a search result.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from atlas.config import Settings

DEFAULT = "default"


@dataclass
class WorkspaceInfo:
    slug: str
    name: str
    kind: str = "customer"            # customer | internal
    customer: str = ""
    ai_mode: str = "normal"           # normal | strict
    target_release: str = "2023"      # 1709..2025 | cloud
    deployment: str = "onprem"        # onprem | cloud
    notes: str = ""
    origin: str = ""                  # for internal libraries: project / customer the code came from
    extra: dict = field(default_factory=dict)

    @property
    def strict(self) -> bool:
        return self.ai_mode == "strict"

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("extra", None)
        return d


def root_dir(base: Settings | None = None) -> Path:
    base = base or Settings()
    return Path(os.environ.get("ATLAS_WORKSPACE_ROOT", base.data_dir))


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name.strip()).strip("-").lower()
    return s[:40] or "workspace"


def workspace_dir(slug: str, base: Settings | None = None) -> Path:
    r = root_dir(base)
    return r if slug == DEFAULT else r / "workspaces" / slug


def info_path(slug: str, base: Settings | None = None) -> Path:
    return workspace_dir(slug, base) / ("workspace.json" if slug != DEFAULT else "config/workspace.json")


def load_info(slug: str, base: Settings | None = None) -> WorkspaceInfo:
    p = info_path(slug, base)
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    known = {k: v for k, v in data.items() if k in WorkspaceInfo.__dataclass_fields__ and k != "extra"}
    extra = {k: v for k, v in data.items() if k not in WorkspaceInfo.__dataclass_fields__}
    known.setdefault("slug", slug)
    known.setdefault("name", "Demo repository" if slug == DEFAULT else slug)
    return WorkspaceInfo(**known, extra=extra)


def save_info(info: WorkspaceInfo, base: Settings | None = None) -> Path:
    p = info_path(info.slug, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({**info.as_dict(), **info.extra}, indent=2), encoding="utf-8")
    return p


def list_workspaces(base: Settings | None = None) -> list[WorkspaceInfo]:
    out = [load_info(DEFAULT, base)]
    wdir = root_dir(base) / "workspaces"
    if wdir.exists():
        for d in sorted(p for p in wdir.iterdir() if p.is_dir()):
            out.append(load_info(d.name, base))
    return out


def create_workspace(name: str, kind: str = "customer", customer: str = "", ai_mode: str = "normal", target_release: str = "2023",
                     deployment: str = "onprem", base: Settings | None = None) -> WorkspaceInfo:
    slug = slugify(name)
    if slug == DEFAULT:
        raise ValueError("'default' is reserved for the demo repository")
    d = workspace_dir(slug, base)
    for sub in ("config", "input", "output", "index"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    info = WorkspaceInfo(slug=slug, name=name.strip() or slug, kind=kind, customer=customer or (name if kind == "customer" else ""),
                         ai_mode=ai_mode, target_release=target_release, deployment=deployment)
    save_info(info, base)
    return info


def settings_for(slug: str, base: Settings | None = None) -> Settings:
    """Settings object pointing at the workspace's own data folder."""
    base = base or Settings()
    if slug == DEFAULT:
        return Settings(data_dir=root_dir(base), db_url=base.db_url, log_level=base.log_level)
    return Settings(data_dir=workspace_dir(slug, base), log_level=base.log_level)


def current_slug() -> str:
    return os.environ.get("ATLAS_WORKSPACE", "") or DEFAULT

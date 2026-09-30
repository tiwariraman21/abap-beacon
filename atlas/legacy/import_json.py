"""Import the v0.6 POC data (data/output/objects.json + ai_descriptions.json).

AI descriptions written by Claude for the demo are carried over to the
matching objects (by name) and marked `described_by = ai`. Offline
descriptions from the POC are ignored - the new offline enrichment is better.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas.db.models import SapObject, System


@dataclass
class LegacyImportSummary:
    ai_descriptions_found: int = 0
    applied: int = 0
    unmatched: list[str] = field(default_factory=list)


def _load_json(path: Path) -> dict:
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def collect_legacy_descriptions(folder: Path) -> dict[str, dict]:
    """Merge ai_descriptions.json and any `ai`-described entries in objects.json."""
    descriptions: dict[str, dict] = {}

    ai_file = folder / "ai_descriptions.json"
    if ai_file.exists():
        for name, entry in _load_json(ai_file).items():
            if isinstance(entry, dict) and entry.get("description"):
                descriptions[name.upper()] = {"description": entry["description"], "tags": entry.get("tags", [])}

    objects_file = folder / "objects.json"
    if objects_file.exists():
        data = _load_json(objects_file)
        for obj in data.get("objects", data if isinstance(data, list) else []):
            if obj.get("described_by") == "ai" and obj.get("description"):
                descriptions.setdefault(obj["name"].upper(), {"description": obj["description"], "tags": obj.get("tags", [])})

    return descriptions


def import_legacy(session: Session, folder: Path, system_sid: str) -> LegacyImportSummary:
    descriptions = collect_legacy_descriptions(folder)
    summary = LegacyImportSummary(ai_descriptions_found=len(descriptions))

    objects = list(
        session.scalars(select(SapObject).join(System).where(System.sid == system_sid.upper()))
    )
    by_name: dict[str, list[SapObject]] = {}
    for o in objects:
        by_name.setdefault(o.name.upper(), []).append(o)

    for name, entry in descriptions.items():
        matches = by_name.get(name)
        if not matches:
            summary.unmatched.append(name)
            continue
        # prefer code objects when a name is shared by e.g. a table and a table type
        matches.sort(key=lambda o: 0 if o.obj_type in ("CLAS", "PROG", "FUGR", "INTF", "DDLS") else 1)
        target = matches[0]
        target.description = entry["description"]
        merged = list(entry.get("tags") or [])
        for t in target.tags or []:
            if t not in merged:
                merged.append(t)
        target.tags = merged
        target.described_by = "ai"
        target.review_status = "draft"
        summary.applied += 1

    return summary

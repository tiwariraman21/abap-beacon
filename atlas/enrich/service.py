"""Run offline enrichment over stored objects.

Rules:
- objects described by AI or a human keep their description; only module,
  complexity and tags (merged) are refreshed
- everything else gets the offline description
- pass `only_ids` to restrict to objects an ingest run just changed
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from atlas.db.models import SapObject
from atlas.enrich.offline import describe


@dataclass
class EnrichSummary:
    described: int = 0
    refreshed_only: int = 0
    total: int = 0

    def as_dict(self) -> dict:
        return {"described": self.described, "refreshed_only": self.refreshed_only, "total": self.total}


_MODULE_CODES = {"FI", "SD", "MM", "PP", "CO", "HCM", "HR", "PM", "QM", "PS", "WM", "EWM", "AIF", "BC", "CRM", "SRM", "TR", "FSCM"}


def _module_from_tags(tags: list[str]) -> str:
    for t in tags:
        if t.upper() in _MODULE_CODES:
            return "HCM" if t.upper() == "HR" else t.upper()
    return ""


def enrich_offline(session: Session, only_ids: list[int] | None = None, system_sid: str | None = None) -> EnrichSummary:
    query = select(SapObject).options(selectinload(SapObject.files), selectinload(SapObject.components))
    if only_ids is not None:
        if not only_ids:
            return EnrichSummary()
        query = query.where(SapObject.id.in_(only_ids))
    if system_sid:
        from atlas.db.models import System

        query = query.join(System).where(System.sid == system_sid.upper())

    summary = EnrichSummary()
    for obj in session.scalars(query):
        summary.total += 1
        result = describe(
            name=obj.name,
            type_key=obj.obj_type,
            source=obj.source,
            short_text=obj.short_text,
            components=[(c.kind, c.name, c.short_text) for c in obj.components],
            attributes=obj.attributes or {},
            source_lines=obj.source_lines,
        )

        obj.module = obj.module or result.module or _module_from_tags(obj.tags or [])
        obj.complexity = result.complexity
        obj.attributes = {**(obj.attributes or {}), "tables": result.tables}

        if obj.described_by in ("ai", "human"):
            # keep curated text, merge in any technical tags the rules found
            merged = list(obj.tags or [])
            for t in result.tags:
                if t not in merged:
                    merged.append(t)
            obj.tags = merged
            summary.refreshed_only += 1
        else:
            obj.description = result.description
            obj.tags = result.tags
            obj.described_by = "offline"
            summary.described += 1

    return summary

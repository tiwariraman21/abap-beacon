"""Write a parsed export into the database.

Change detection is by content hash at object level: unchanged objects are
counted but not rewritten, so re-ingesting a 20k-object export after a small
transport is cheap and downstream steps (enrichment, indexing) can skip them.

Descriptions written by AI or a human are never overwritten here; only the
raw material (source, metadata, components) is refreshed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas.db.models import Component, ObjectFile, Package, SapObject, System
from atlas.ingest.abapgit import ExportReport, RawObject


@dataclass
class IngestSummary:
    system: str
    source: str
    objects_total: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    files: int = 0
    packages: int = 0
    skipped_files: list[str] = field(default_factory=list)
    changed_object_ids: list[int] = field(default_factory=list)
    by_type: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "system": self.system,
            "source": self.source,
            "objects_total": self.objects_total,
            "added": self.added,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "files": self.files,
            "packages": self.packages,
            "skipped_files": len(self.skipped_files),
            "by_type": self.by_type,
        }


def get_or_create_system(session: Session, sid: str, description: str = "") -> System:
    sid = sid.upper()
    system = session.scalar(select(System).where(System.sid == sid))
    if system is None:
        system = System(sid=sid, description=description)
        session.add(system)
        session.flush()
    return system


def _ensure_packages(session: Session, system: System, report: ExportReport, root_name: str | None) -> dict[str, Package]:
    """Create one Package row per folder seen in the export."""
    paths = {obj.package_path for obj in report.objects} | set(report.packages)
    packages: dict[str, Package] = {}

    existing = {p.path: p for p in session.scalars(select(Package).where(Package.system_id == system.id))}
    root = report.starting_folder.strip("/")

    for path in sorted(paths, key=lambda p: (p.count("/"), p)):
        is_root = path in (".", "", root)
        name = (root_name or "$ROOT").upper() if is_root else path.split("/")[-1].upper()
        short_text = report.packages.get(path, "")

        pkg = existing.get(path)
        if pkg is None:
            pkg = Package(system_id=system.id, path=path, name=name, short_text=short_text)
            session.add(pkg)
            session.flush()
            existing[path] = pkg
        else:
            if root_name and is_root:
                pkg.name = name
            if short_text:
                pkg.short_text = short_text

        parent_path = "/".join(path.split("/")[:-1])
        if parent_path and parent_path in existing and parent_path != path:
            pkg.parent_id = existing[parent_path].id

        packages[path] = pkg

    return packages


def ingest_report(
    session: Session,
    report: ExportReport,
    system_sid: str,
    root_package_name: str | None = None,
) -> IngestSummary:
    system = get_or_create_system(session, system_sid)
    summary = IngestSummary(system=system.sid, source=report.source_label, skipped_files=list(report.skipped_files))

    packages = _ensure_packages(session, system, report, root_package_name)
    summary.packages = len(packages)
    root_path = next((p for p in packages if p in (".", "", report.starting_folder.strip("/"))), None)
    root_name = packages[root_path].name if root_path else (root_package_name or "$ROOT").upper()

    existing: dict[tuple[str, str], SapObject] = {
        (o.obj_type, o.name): o
        for o in session.scalars(select(SapObject).where(SapObject.system_id == system.id))
    }

    for raw in report.objects:
        if raw.type_key == "DEVC" and raw.name == "$ROOT":
            raw.name = root_name

        summary.objects_total += 1
        summary.files += len(raw.files)
        summary.by_type[raw.type_key] = summary.by_type.get(raw.type_key, 0) + 1

        new_hash = raw.content_hash
        record = existing.get((raw.type_key, raw.name))

        if record is None:
            record = SapObject(system_id=system.id, obj_type=raw.type_key, name=raw.name)
            session.add(record)
            existing[(raw.type_key, raw.name)] = record
            summary.added += 1
        elif record.content_hash == new_hash:
            summary.unchanged += 1
            continue
        else:
            summary.updated += 1

        _apply_raw(session, record, raw, packages, new_hash)
        session.flush()
        summary.changed_object_ids.append(record.id)

    return summary


def _apply_raw(session: Session, record: SapObject, raw: RawObject, packages: dict[str, Package], new_hash: str) -> None:
    record.package_id = packages[raw.package_path].id if raw.package_path in packages else None
    record.short_text = raw.meta.short_text or record.short_text
    record.content_hash = new_hash
    record.source_chars = raw.source_chars
    record.source_lines = raw.source_lines
    record.file_count = len(raw.files)
    record.attributes = {**(record.attributes or {}), **raw.meta.attributes}

    # Files: replace wholesale (they are the raw material, not curated data).
    # Delete first and flush, otherwise SQLAlchemy inserts the new rows before
    # removing the orphans and trips the (object_id, path) unique constraint.
    old_summaries = {(c.kind, c.name): c.summary for c in record.components if c.summary}
    for f in list(record.files):
        session.delete(f)
    for c in list(record.components):
        session.delete(c)
    record.files.clear()
    record.components.clear()
    session.flush()
    for f in raw.files:
        record.files.append(
            ObjectFile(
                path=f.path,
                kind=f.kind,
                sub_file=f.sub_file,
                content=f.content,
                content_hash=f.content_hash,
                line_count=f.line_count,
            )
        )

    # Components: refresh metadata-derived ones, keep AI summaries where the
    # component still exists.
    seen: set[tuple[str, str]] = set()
    for comp in raw.meta.components:
        key = (comp.kind, comp.name)
        if key in seen:
            continue
        seen.add(key)
        record.components.append(
            Component(
                kind=comp.kind,
                name=comp.name,
                short_text=comp.short_text[:255],
                signature=comp.signature,
                summary=old_summaries.get(key, ""),
            )
        )

"""Run the structural parser over stored objects and persist the results.

- components get line ranges (and methods missing from metadata are added)
- references are rewritten for the object
- code metrics land in object.attributes (code_lines, comment_lines, max_nesting)

`dependencies()` and `impact()` answer the architect questions on top of the
stored edges.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from atlas.db.models import Component, ObjectReference, SapObject, System
from atlas.ingest.types import get_type
from atlas.parse.abap import parse_abap
from atlas.reference.sap_objects import TABLES


@dataclass
class ParseSummary:
    parsed: int = 0
    references: int = 0
    components_added: int = 0

    def as_dict(self) -> dict:
        return {"parsed": self.parsed, "references": self.references, "components_added": self.components_added}


CDS_TYPES = {"DDLS", "DCLS", "DDLX", "BDEF"}


def parse_objects(session: Session, only_ids: list[int] | None = None, system_sid: str | None = None) -> ParseSummary:
    query = select(SapObject).options(selectinload(SapObject.files), selectinload(SapObject.components), selectinload(SapObject.references))
    if only_ids is not None:
        if not only_ids:
            return ParseSummary()
        query = query.where(SapObject.id.in_(only_ids))
    if system_sid:
        query = query.join(System).where(System.sid == system_sid.upper())

    summary = ParseSummary()
    for obj in session.scalars(query):
        if not obj.source_files:
            continue
        summary.parsed += 1
        parsed = _parse_object(obj)

        # metrics
        obj.attributes = {
            **(obj.attributes or {}),
            "code_lines": parsed.code_lines,
            "comment_lines": parsed.comment_lines,
            "max_nesting": parsed.max_nesting,
            "method_count": sum(1 for c in parsed.components if c.kind == "method"),
        }

        # components: line ranges + missing methods/forms
        by_key = {(c.kind, c.name): c for c in obj.components}
        for pc in parsed.components:
            if pc.kind in ("class", "interface"):
                continue
            kind = pc.kind if pc.kind != "cds" else "entity"
            row = by_key.get((kind, pc.name))
            if row is None:
                row = Component(kind=kind, name=pc.name)
                obj.components.append(row)
                by_key[(kind, pc.name)] = row
                summary.components_added += 1
            row.line_start, row.line_end = pc.line_start, pc.line_end

        # references: replace, aggregated by (kind, target, component)
        for r in list(obj.references):
            session.delete(r)
        obj.references.clear()
        session.flush()
        agg: dict[tuple[str, str, str], dict] = {}
        for ref in parsed.references:
            key = (ref.kind, ref.target, ref.component)
            if key in agg:
                agg[key]["count"] += 1
            else:
                agg[key] = {"kind": ref.kind, "target": ref.target, "target_type": ref.target_type, "component": ref.component, "line": ref.line, "count": 1, "is_custom": ref.is_custom}
        for a in agg.values():
            obj.references.append(
                ObjectReference(kind=a["kind"], target_name=a["target"], target_type=a["target_type"], is_custom=a["is_custom"], component=a["component"], line=a["line"], count=a["count"])
            )
        summary.references += len(agg)

    return summary


def _parse_object(obj: SapObject):
    """Parse every source file of the object and merge; line numbers refer to the
    concatenated `obj.source` (files joined in stored order), which is what the UI shows."""
    return parse_abap(obj.source, is_cds=obj.obj_type in CDS_TYPES)


# --- queries -------------------------------------------------------------------------------

@dataclass
class DependencyView:
    outgoing: list[dict] = field(default_factory=list)      # what this object uses
    incoming: list[dict] = field(default_factory=list)      # who uses this object
    tables: list[dict] = field(default_factory=list)


def _resolve_names(session: Session, names: set[str]) -> dict[str, dict]:
    if not names:
        return {}
    rows = session.execute(
        select(SapObject.id, SapObject.name, SapObject.obj_type, SapObject.short_text).where(SapObject.name.in_(list(names)))
    ).all()
    out: dict[str, dict] = {}
    for oid, name, otype, short in rows:
        # prefer code objects when a name is shared (e.g. a table and its table type)
        if name not in out or get_type(otype).category == "code":
            out[name] = {"id": oid, "type": get_type(otype).label, "type_key": otype, "short_text": short}
    return out


def dependencies(session: Session, object_id: int) -> DependencyView:
    obj = session.get(SapObject, object_id, options=[selectinload(SapObject.references)])
    view = DependencyView()
    if obj is None:
        return view

    targets = {r.target_name for r in obj.references}
    resolved = _resolve_names(session, targets)
    # names the object itself declares (function modules, includes...) so self-references are skipped
    own = {obj.name} | {c.name for c in obj.components}

    grouped: dict[tuple[str, str], dict] = {}
    for r in sorted(obj.references, key=lambda x: (x.kind, x.target_name, x.line)):
        if r.target_name in own and r.kind in ("calls_class", "includes"):
            continue
        key = (r.kind, r.target_name)
        if key in grouped:
            grouped[key]["count"] += r.count
            if r.component and r.component not in grouped[key]["components"]:
                grouped[key]["components"].append(r.component)
            continue
        std = TABLES.get(r.target_name)
        grouped[key] = {
            "kind": r.kind, "name": r.target_name, "target_type": r.target_type, "count": r.count, "line": r.line,
            "components": [r.component] if r.component else [],
            "is_custom": r.is_custom, "resolved": resolved.get(r.target_name),
            "std_text": std.text if std else "", "std_module": std.module if std else "", "s4_status": std.s4_status if std else "",
        }
    for entry in grouped.values():
        if entry["target_type"] in ("table", "cds_or_table"):
            view.tables.append(entry)
        else:
            view.outgoing.append(entry)

    # incoming: any reference whose target is this object's name or one of its function modules / includes
    my_names = {obj.name} | {c.name for c in obj.components if c.kind in ("function", "include", "entity")}
    rows = session.execute(
        select(ObjectReference, SapObject.id, SapObject.name, SapObject.obj_type, SapObject.short_text)
        .join(SapObject, ObjectReference.object_id == SapObject.id)
        .where(ObjectReference.target_name.in_(list(my_names)), SapObject.id != obj.id)
        .order_by(SapObject.name)
    ).all()
    for ref, oid, name, otype, short in rows:
        view.incoming.append({"kind": ref.kind, "name": name, "id": oid, "type": get_type(otype).label, "short_text": short, "count": ref.count, "line": ref.line, "component": ref.component})
    return view


def impact(session: Session, name: str, depth: int = 3) -> dict:
    """Who depends (directly or transitively) on `name` - an object, table, FM or include."""
    name = name.upper()
    levels: list[list[dict]] = []
    seen: set[str] = {name}
    frontier = {name}
    for level in range(depth):
        if not frontier:
            break
        rows = session.execute(
            select(ObjectReference.kind, ObjectReference.target_name, SapObject.id, SapObject.name, SapObject.obj_type, SapObject.short_text)
            .join(SapObject, ObjectReference.object_id == SapObject.id)
            .where(ObjectReference.target_name.in_(list(frontier)))
        ).all()
        this_level: list[dict] = []
        next_frontier: set[str] = set()
        for kind, target, oid, oname, otype, short in rows:
            if oname in seen:
                continue
            seen.add(oname)
            this_level.append({"id": oid, "name": oname, "type": get_type(otype).label, "short_text": short, "via": target, "kind": kind, "level": level + 1})
            next_frontier.add(oname)
            # a class's function modules / includes are reachable through the object name only; good enough for now
        if this_level:
            levels.append(this_level)
        frontier = next_frontier
    total = sum(len(l) for l in levels)
    return {"root": name, "levels": levels, "total": total}


def where_used_tables(session: Session, system_sid: str | None = None, limit: int = 40) -> list[dict]:
    """Most-used tables across the custom estate, with S/4 status - the migration lead's first question."""
    q = (
        select(ObjectReference.target_name, func.count(func.distinct(ObjectReference.object_id)), func.sum(ObjectReference.count))
        .join(SapObject, ObjectReference.object_id == SapObject.id)
        .where(ObjectReference.target_type.in_(["table", "cds_or_table"]))
        .group_by(ObjectReference.target_name)
        .order_by(func.count(func.distinct(ObjectReference.object_id)).desc())
        .limit(limit)
    )
    if system_sid:
        q = q.join(System).where(System.sid == system_sid.upper())
    out = []
    for name, objects, refs in session.execute(q).all():
        std = TABLES.get(name)
        out.append({"name": name, "objects": objects, "references": int(refs or 0), "is_custom": name.startswith(("Z", "Y")), "text": std.text if std else "", "module": std.module if std else "", "s4_status": std.s4_status if std else ("custom" if name.startswith(("Z", "Y")) else ""), "successor": std.successor if std else ""})
    return out


def graph_data(session: Session, system_sid: str | None = None, max_nodes: int = 150) -> dict:
    """Nodes/links for the dependency map (custom objects + the standard tables they touch)."""
    q = select(SapObject).options(selectinload(SapObject.references))
    if system_sid:
        q = q.join(System).where(System.sid == system_sid.upper())
    objects = list(session.scalars(q))
    names = {o.name: o for o in objects}
    nodes: dict[str, dict] = {}
    links: list[dict] = []
    degree: defaultdict[str, int] = defaultdict(int)

    def node(name: str, category: str, label: str = "", oid: int | None = None) -> None:
        if name not in nodes:
            nodes[name] = {"name": name, "category": category, "label": label, "id": oid}

    for o in objects:
        if not o.references:
            continue
        node(o.name, get_type(o.obj_type).category if get_type(o.obj_type).category != "code" else o.obj_type, get_type(o.obj_type).label, o.id)
        for r in o.references:
            if r.kind in ("catches", "message_class", "authority_check", "includes") or r.target_name == o.name:
                continue
            if r.target_name in names:
                t = names[r.target_name]
                node(t.name, t.obj_type if get_type(t.obj_type).category == "code" else get_type(t.obj_type).category, get_type(t.obj_type).label, t.id)
            elif r.target_type in ("table", "cds_or_table"):
                std = TABLES.get(r.target_name)
                node(r.target_name, "std_table", std.text if std else "SAP table")
            elif r.kind in ("calls_function", "calls_class", "inherits", "implements", "raises"):
                if not r.is_custom and r.kind in ("calls_class",):
                    continue     # skip CL_ABAP_* noise
                node(r.target_name, "std_object", r.target_type)
            else:
                continue
            links.append({"source": o.name, "target": r.target_name, "kind": r.kind, "value": r.count})
            degree[o.name] += 1
            degree[r.target_name] += 1

    if len(nodes) > max_nodes:
        keep = set(sorted(nodes, key=lambda n: -degree[n])[:max_nodes])
        nodes = {n: v for n, v in nodes.items() if n in keep}
        links = [l for l in links if l["source"] in keep and l["target"] in keep]
    for n in nodes.values():
        n["degree"] = degree[n["name"]]
    return {"nodes": list(nodes.values()), "links": links}

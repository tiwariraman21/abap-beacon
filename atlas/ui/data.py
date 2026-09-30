"""Read-side services for the UI. Everything returns plain dicts, never ORM
objects, so pages are independent of session lifetime."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from atlas.config import Settings, get_settings
from atlas.db.models import AICall, Job, Package, SapObject, System
from atlas.db.session import session_scope
from atlas.ingest.types import get_type
from atlas.search.engine import SearchEngine, SearchFilters, relevance_label

settings: Settings = get_settings()
_BASE_SETTINGS: Settings = settings


def active_workspace():
    from atlas.workspace import current_slug, load_info

    return load_info(current_slug(), _BASE_SETTINGS)


def workspaces() -> list:
    from atlas.workspace import list_workspaces

    return list_workspaces(_BASE_SETTINGS)


def switch_workspace(slug: str) -> None:
    """Point every data function at another workspace's data folder (single-user tool: process-wide)."""
    global settings
    import os

    from atlas.db.health import ensure_healthy
    from atlas.db.session import init_db
    from atlas.workspace import settings_for

    new = settings_for(slug, _BASE_SETTINGS)
    new.data_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("config", "input", "output", "index"):
        (new.data_dir / sub).mkdir(parents=True, exist_ok=True)
    os.environ["ATLAS_WORKSPACE"] = slug
    ensure_healthy(new.db_path)
    init_db(new)
    settings = new
    from atlas.guard.policy import invalidate as guard_invalidate

    guard_invalidate()
    invalidate()


def create_workspace(name: str, kind: str, customer: str, ai_mode: str, target_release: str, deployment: str):
    from atlas.workspace import create_workspace as _create

    info = _create(name, kind, customer, ai_mode, target_release, deployment, _BASE_SETTINGS)
    switch_workspace(info.slug)
    return info


def update_workspace(**changes) -> None:
    from atlas.workspace import save_info

    info = active_workspace()
    for k, v in changes.items():
        if hasattr(info, k):
            setattr(info, k, v)
    save_info(info, _BASE_SETTINGS)
    invalidate()


def ai_enabled() -> bool:
    return not active_workspace().strict

# --- display masking (guardrails) -------------------------------------------------------------

_NO_MASK_KEYS = {"id", "object_id", "name", "object", "path", "kind", "type", "type_key", "rule_id", "status", "obj_type", "severity",
                 "category", "url", "sub_file", "module", "system", "package", "backend", "described_by", "review_status", "verdict",
                 "fingerprint", "action", "label", "target_type", "filename", "provider", "model", "created", "created_at", "updated_at",
                 "detected_terms", "entities", "fsd_blocks", "matched_terms", "components", "intents"}
_SOURCE_KEYS = {"content", "source", "snippet"}


def mask(text: str) -> str:
    """Apply the display guardrail to a piece of text."""
    from atlas.guard.policy import get_guard

    return get_guard(settings).mask_for_display(text or "")


def masked(payload, _guard=None):
    """Recursively mask free text in a result payload; identifiers and source code stay as they are
    (source code is only masked when the policy says so)."""
    from atlas.guard.policy import get_guard

    g = _guard or get_guard(settings)
    if not g.policy.mask_in_ui:
        return payload
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            if k in _NO_MASK_KEYS:
                out[k] = v
            elif k in _SOURCE_KEYS:
                out[k] = g.mask_for_display(v) if (isinstance(v, str) and getattr(g.policy, "mask_source", False)) else v
            else:
                out[k] = masked(v, g)
        return out
    if isinstance(payload, list):
        return [masked(x, g) for x in payload]
    if isinstance(payload, str):
        return g.mask_for_display(payload)
    return payload


# --- search engine cache ---------------------------------------------------------------

@dataclass
class _EngineCache:
    key: tuple = ()
    engine: SearchEngine | None = None
    session = None


_cache = _EngineCache()


def _store_key() -> tuple:
    def mtime(p: Path) -> float:
        return p.stat().st_mtime if p.exists() else 0.0

    return (mtime(settings.db_path), mtime(settings.index_dir / "semantic.npz"))


def get_engine() -> SearchEngine:
    """SearchEngine is rebuilt whenever the database or index file changes."""
    key = _store_key()
    if _cache.engine is None or _cache.key != key:
        if _cache.session is not None:
            _cache.session.close()
        from sqlalchemy.orm import sessionmaker

        from atlas.db.session import init_db

        engine = init_db(settings)
        session = sessionmaker(bind=engine, expire_on_commit=False)()
        _cache.engine = SearchEngine(session, settings.index_dir)
        _cache.session = session
        _cache.key = key
    return _cache.engine


def invalidate() -> None:
    _cache.key = ()


# --- overview ---------------------------------------------------------------------------

def overview() -> dict:
    with session_scope(settings) as s:
        total = s.scalar(select(func.count(SapObject.id))) or 0
        if total == 0:
            return {"empty": True}
        lines = s.scalar(select(func.coalesce(func.sum(SapObject.source_lines), 0))) or 0
        by_type = dict(s.execute(select(SapObject.obj_type, func.count()).group_by(SapObject.obj_type)).all())
        by_module = dict(s.execute(select(SapObject.module, func.count()).group_by(SapObject.module)).all())
        by_desc = dict(s.execute(select(SapObject.described_by, func.count()).group_by(SapObject.described_by)).all())
        by_cx = dict(s.execute(select(SapObject.complexity, func.count()).where(SapObject.source_lines > 0).group_by(SapObject.complexity)).all())
        systems = [x.sid for x in s.scalars(select(System))]
        pkgs = s.scalar(select(func.count(Package.id))) or 0
        jobs = list(s.scalars(select(Job).options(selectinload(Job.steps)).order_by(Job.id.desc()).limit(5)))
        code_objects = sum(n for t, n in by_type.items() if get_type(t).category == "code")
        from atlas.assess.service import findings_overview

        findings = findings_overview(s)
        largest = list(
            s.execute(select(SapObject.id, SapObject.name, SapObject.obj_type, SapObject.source_lines, SapObject.short_text)
                      .order_by(SapObject.source_lines.desc()).limit(8)).all()
        )
    return {
        "empty": False,
        "total": total,
        "lines": lines,
        "code_objects": code_objects,
        "by_type": {k: v for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])},
        "by_module": {(k or "unassigned"): v for k, v in sorted(by_module.items(), key=lambda kv: -kv[1])},
        "by_desc": by_desc,
        "by_cx": by_cx,
        "systems": systems,
        "packages": pkgs,
        "ai_share": round(100 * by_desc.get("ai", 0) / total) if total else 0,
        "jobs": [_job_dict(j) for j in jobs],
        "findings": findings,
        "largest": [dict(id=i, name=n, type=get_type(t).label, lines=l, short_text=st) for i, n, t, l, st in largest],
    }


# --- search -----------------------------------------------------------------------------

def _search_raw(query: str, mode: str = "hybrid", limit: int = 15, types: list[str] | None = None, module: str | None = None, category: str | None = None) -> dict:
    engine = get_engine()
    if engine.size == 0:
        return {"results": [], "backend": "none", "empty": True}
    results = engine.search(query, limit=limit, mode=mode, filters=SearchFilters(types=types or None, module=module or None, category=category or None))
    out = []
    for r in results:
        o = r.object
        out.append(
            {
                "id": o.id,
                "name": o.name,
                "type": get_type(o.obj_type).label,
                "type_key": o.obj_type,
                "module": o.module,
                "lines": o.source_lines,
                "short_text": o.short_text,
                "description": o.description,
                "tags": list(o.tags or []),
                "described_by": o.described_by,
                "score": r.score,
                "label": relevance_label(r.score),
                "similarity": r.similarity,
                "matched": r.matched_terms,
                "hits": [dict(kind=h.kind, name=h.name, short_text=h.short_text) for h in r.component_hits],
            }
        )
    return {"results": out, "backend": engine.semantic.backend if engine.semantic else "none", "empty": False}



def search(query: str, mode: str = "hybrid", limit: int = 15, types: list[str] | None = None, module: str | None = None, category: str | None = None) -> dict:
    return masked(_search_raw(query, mode, limit, types, module, category))

def filter_options() -> dict:
    with session_scope(settings) as s:
        types = [t for (t,) in s.execute(select(SapObject.obj_type).distinct().order_by(SapObject.obj_type)).all()]
        modules = [m for (m,) in s.execute(select(SapObject.module).distinct().order_by(SapObject.module)).all() if m]
    return {"types": {t: f"{get_type(t).label} ({t})" for t in types}, "modules": modules}


# --- object page -------------------------------------------------------------------------

def _get_object_raw(object_id: int) -> dict | None:
    with session_scope(settings) as s:
        o = s.get(SapObject, object_id, options=[selectinload(SapObject.files), selectinload(SapObject.components), selectinload(SapObject.package), selectinload(SapObject.system)])
        if o is None:
            return None
        return {
            "id": o.id,
            "name": o.name,
            "type": get_type(o.obj_type).label,
            "type_key": o.obj_type,
            "category": get_type(o.obj_type).category,
            "system": o.system.sid,
            "package": o.package.name if o.package else "",
            "package_text": o.package.short_text if o.package else "",
            "short_text": o.short_text,
            "description": o.description,
            "tags": list(o.tags or []),
            "module": o.module,
            "complexity": o.complexity,
            "clean_core_tier": o.clean_core_tier,
            "s4_status": o.s4_status,
            "described_by": o.described_by,
            "review_status": o.review_status,
            "lines": o.source_lines,
            "chars": o.source_chars,
            "attributes": {k: v for k, v in (o.attributes or {}).items() if k != "tables"},
            "tables": (o.attributes or {}).get("tables", []),
            "updated_at": o.updated_at.strftime("%Y-%m-%d %H:%M") if o.updated_at else "",
            "files": [dict(path=f.path, kind=f.kind, sub_file=f.sub_file, lines=f.line_count, content=f.content) for f in o.files],
            "components": [dict(kind=c.kind, name=c.name, short_text=c.short_text, signature=c.signature or {}) for c in o.components],
        }



def get_object(object_id: int) -> dict | None:
    return masked(_get_object_raw(object_id))

def _related_objects_raw(name: str, object_id: int, limit: int = 8) -> list[dict]:
    """Cheap 'related' list until the dependency graph lands: same prefix or mentioned in source."""
    with session_scope(settings) as s:
        stem = "_".join(name.split("_")[:3])
        rows = s.execute(
            select(SapObject.id, SapObject.name, SapObject.obj_type, SapObject.short_text)
            .where(SapObject.name.like(f"{stem}%"), SapObject.id != object_id)
            .limit(limit)
        ).all()
    return [dict(id=i, name=n, type=get_type(t).label, short_text=st) for i, n, t, st in rows]



def related_objects(name: str, object_id: int, limit: int = 8) -> list[dict]:
    return masked(_related_objects_raw(name, object_id, limit))

# --- inventory ----------------------------------------------------------------------------

def _inventory_raw(types: list[str] | None = None, module: str | None = None, described_by: str | None = None, text: str = "") -> list[dict]:
    with session_scope(settings) as s:
        q = select(SapObject).options(selectinload(SapObject.package)).order_by(SapObject.obj_type, SapObject.name)
        if types:
            q = q.where(SapObject.obj_type.in_(types))
        if module:
            q = q.where(SapObject.module == module)
        if described_by:
            q = q.where(SapObject.described_by == described_by)
        if text:
            like = f"%{text}%"
            q = q.where((SapObject.name.like(like)) | (SapObject.short_text.like(like)) | (SapObject.description.like(like)))
        rows = list(s.scalars(q))
        return [
            dict(
                id=o.id, name=o.name, type=get_type(o.obj_type).label, type_key=o.obj_type, module=o.module or "",
                package=o.package.name if o.package else "", lines=o.source_lines, complexity=o.complexity,
                described_by=o.described_by, short_text=o.short_text, tags=", ".join((o.tags or [])[:6]),
            )
            for o in rows
        ]



def inventory(types: list[str] | None = None, module: str | None = None, described_by: str | None = None, text: str = "") -> list[dict]:
    return masked(_inventory_raw(types, module, described_by, text))

def inventory_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["name", "type", "module", "package", "lines", "complexity", "described_by", "short_text", "tags"], extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


# --- jobs -----------------------------------------------------------------------------------

def _job_dict(j: Job) -> dict:
    duration = (j.finished_at - j.started_at).total_seconds() if j.finished_at and j.started_at else 0.0
    return {
        "id": j.id,
        "kind": j.kind,
        "status": j.status,
        "source": Path(j.source).name if j.source else "",
        "started": j.started_at.strftime("%Y-%m-%d %H:%M:%S") if j.started_at else "",
        "seconds": round(duration, 1),
        "error": (j.error or "").strip().splitlines()[0] if j.error else "",
        "summary": j.summary or {},
        "steps": [dict(name=s.name, status=s.status, detail={k: v for k, v in (s.detail or {}).items() if k != "by_type"}) for s in j.steps],
    }


def jobs(limit: int = 20) -> list[dict]:
    with session_scope(settings) as s:
        rows = list(s.scalars(select(Job).options(selectinload(Job.steps)).order_by(Job.id.desc()).limit(limit)))
        return [_job_dict(j) for j in rows]


def systems() -> list[str]:
    with session_scope(settings) as s:
        return [x.sid for x in s.scalars(select(System).order_by(System.sid))]


# --- analysis -----------------------------------------------------------------------------

def _object_dependencies_raw(object_id: int) -> dict:
    from atlas.parse.service import dependencies

    with session_scope(settings) as s:
        v = dependencies(s, object_id)
        return {"outgoing": v.outgoing, "incoming": v.incoming, "tables": v.tables}



def object_dependencies(object_id: int) -> dict:
    return masked(_object_dependencies_raw(object_id))

def _object_findings_raw(object_id: int) -> list[dict]:
    from atlas.assess.service import list_findings

    with session_scope(settings) as s:
        return list_findings(s, status="all", object_id=object_id)



def object_findings(object_id: int) -> list[dict]:
    return masked(_object_findings_raw(object_id))

def impact(name: str, depth: int = 3) -> dict:
    from atlas.parse.service import impact as _impact

    with session_scope(settings) as s:
        return _impact(s, name, depth)


def _assessment_overview_raw() -> dict:
    from atlas.assess.service import findings_overview

    with session_scope(settings) as s:
        return findings_overview(s)



def assessment_overview() -> dict:
    return masked(_assessment_overview_raw())

def _findings_raw(category: str | None = None, severity: str | None = None, rule_id: str | None = None, status: str | None = "open", text: str = "") -> list[dict]:
    from atlas.assess.service import list_findings

    with session_scope(settings) as s:
        return list_findings(s, category or None, severity or None, rule_id or None, status, text=text)



def findings(category: str | None = None, severity: str | None = None, rule_id: str | None = None, status: str | None = "open", text: str = "") -> list[dict]:
    return masked(_findings_raw(category, severity, rule_id, status, text))

def update_finding_status(finding_id: int, status: str) -> None:
    from atlas.assess.service import set_finding_status

    with session_scope(settings) as s:
        set_finding_status(s, finding_id, status)


def findings_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["object", "type", "rule", "category", "severity", "title", "message", "component", "line", "effort_h", "status", "remediation"])
    for r in rows:
        w.writerow([r["object"], r["type"], r["rule_id"], r["category"], r["severity"], r["title"], r["message"], r["component"], r["line"], r["effort"], r["status"], r["remediation"]])
    return buf.getvalue().encode("utf-8-sig")


def table_usage(limit: int = 40) -> list[dict]:
    from atlas.parse.service import where_used_tables

    with session_scope(settings) as s:
        return where_used_tables(s, limit=limit)


def graph() -> dict:
    from atlas.parse.service import graph_data

    with session_scope(settings) as s:
        return graph_data(s)


def object_id_by_name(name: str) -> int | None:
    with session_scope(settings) as s:
        return s.scalar(select(SapObject.id).where(SapObject.name == name.upper()).order_by(SapObject.source_lines.desc()))


# --- AI -----------------------------------------------------------------------------------

def ai_status() -> dict:
    from atlas.ai.provider import provider_status

    st = provider_status()
    with session_scope(settings) as s:
        calls = s.scalar(select(func.count(AICall.id))) or 0
        cost = s.scalar(select(func.coalesce(func.sum(AICall.cost_usd), 0.0))) or 0.0
        tokens_in = s.scalar(select(func.coalesce(func.sum(AICall.input_tokens), 0))) or 0
        tokens_out = s.scalar(select(func.coalesce(func.sum(AICall.output_tokens), 0))) or 0
        limits = s.scalar(select(func.count(AICall.id)).where(AICall.status == "limit")) or 0
        pending = s.scalar(select(func.count(SapObject.id)).where(SapObject.described_by.notin_(["ai", "human"]), SapObject.source_lines > 0)) or 0
    st.update(calls=calls, cost_usd=round(float(cost), 4), tokens_in=tokens_in, tokens_out=tokens_out, limit_hits=limits, pending=pending)
    return st


def run_ai_enrich(limit: int | None, force: bool = False) -> dict:
    """Blocking; call via run.io_bound."""
    from atlas.ai.enrich import enrich_ai
    from atlas.ai.provider import AIError, get_provider
    from atlas.pipeline.runner import rebuild_semantic_index

    try:
        provider = get_provider(output_dir=settings.output_dir / "prompts")
    except AIError as error:
        return {"error": str(error)}
    with session_scope(settings) as s:
        summary = enrich_ai(s, provider, limit=limit, force=force)
    if summary.described:
        with session_scope(settings) as s:
            rebuild_semantic_index(s, settings)
    return summary.as_dict()


def _ask_raw(question: str, k: int = 5) -> dict:
    """Blocking; call via run.io_bound."""
    from atlas.ai.ask import ask as _ask, citations
    from atlas.ai.provider import AIError, get_provider

    try:
        provider = get_provider(output_dir=settings.output_dir / "prompts")
    except AIError as error:
        return {"error": str(error), "answer": "", "sources": []}
    engine = get_engine()
    with session_scope(settings) as s:
        a = _ask(s, engine, provider, question, k)
    return {
        "answer": a.answer, "error": a.error, "provider": a.provider, "model": a.model,
        "tokens": f"{a.input_tokens} in / {a.output_tokens} out", "cost": a.cost_usd, "redactions": a.redactions,
        "sources": [dict(id=x.object_id, name=x.name, type=x.type, short_text=x.short_text, excerpts=x.excerpts) for x in a.sources],
        "citations": citations(a.answer),
    }



def ask(question: str, k: int = 5) -> dict:
    return masked(_ask_raw(question, k))

# --- FSD ----------------------------------------------------------------------------------

def analyse_fsd(path: str) -> dict:
    """Blocking; call via run.io_bound. Never raises for a bad document - returns {"error": ...}."""
    from atlas.fsd.reader import FsdReadError
    from atlas.fsd.service import analyse_file

    try:
        engine = get_engine()
        with session_scope(settings) as s:
            a = analyse_file(s, engine, path)
            s.flush()
            return {"id": a.id, "title": a.title, "verdict": a.verdict, "coverage": a.coverage_pct, "detected_terms": list(a.result.get("detected_terms") or [])}
    except FsdReadError as error:
        return {"error": str(error)}
    except Exception as error:
        import logging

        logging.getLogger("atlas.ui").exception("FSD analysis failed for %s", path)
        return {"error": f"Analysis failed: {error.__class__.__name__}: {error}"}


def _title_guard(result: dict | None):
    from atlas.guard.policy import guard_with_terms

    return guard_with_terms(list((result or {}).get("detected_terms") or []), settings)


def fsd_analyses() -> list[dict]:
    from atlas.fsd.service import list_analyses

    with session_scope(settings) as s:
        rows = []
        for a in list_analyses(s):
            g = _title_guard(a.result)
            rows.append(dict(id=a.id, title=g.mask_for_display(a.title), filename=a.filename, verdict=a.verdict, coverage=a.coverage_pct, requirements=a.requirement_count,
                             effort=a.effort_hours, ai=a.ai_reviewed, created=a.created_at.strftime("%Y-%m-%d %H:%M")))
        return rows


def fsd_techspec(analysis_id: int) -> tuple[bytes, str]:
    """The Technical Specification .docx for one analysis (masked like the report)."""
    from atlas.db.models import FsdAnalysis
    from atlas.fsd.techspec import build_technical_spec

    with session_scope(settings) as s:
        a = s.get(FsdAnalysis, analysis_id)
        if a is None:
            raise ValueError("Analysis not found")
        payload = dict(a.result)
        payload["filename"] = a.filename
        g = _title_guard(a.result)
        return build_technical_spec(payload, g.mask_for_display), Path(a.filename).stem + "_Technical_Spec.docx"


def ask_fsd(analysis_id: int, question: str) -> dict:
    """Blocking; call via run.io_bound. Returns {"answer": ...} or {"error": ...}."""
    from atlas.ai.provider import get_provider
    from atlas.fsd.service import ask_analysis

    from atlas.db.models import FsdAnalysis

    try:
        provider = get_provider()
        with session_scope(settings) as s:
            a = s.get(FsdAnalysis, analysis_id)
            if a is None:
                return {"error": "Analysis not found"}
            text = ask_analysis(s, a, question, provider)
            g = _title_guard(a.result)
            return {"answer": g.mask_for_display(text), "provider": provider.name}
    except Exception as error:      # noqa: BLE001
        return {"error": f"{error.__class__.__name__}: {error}"}


AI_USES = [
    ("describe", "Object descriptions", "Explains what each custom object does in business language (enrichment). Source is chunked, masked and hashed so an unchanged object is never sent twice."),
    ("ask", "Ask the codebase", "Answers questions about the repository from retrieved source with line citations (RAG)."),
    ("fsd_review", "FSD architect review", "Reviews an FSD analysis: challenges the plan, points out missed requirements, proposes alternatives."),
    ("fsd_ask", "Ask about an analysis", "Developer questions on one FSD analysis, answered from its facts (steps, objects, feasibility)."),
]


def ai_usage() -> dict:
    """Where the LLM is used, with live counts from the egress ledger."""
    from atlas.db.models import AICall

    with session_scope(settings) as s:
        rows = s.execute(select(AICall.purpose, func.count(), func.sum(AICall.input_chars), func.max(AICall.created_at)).group_by(AICall.purpose)).all()
        described = s.scalar(select(func.count(SapObject.id)).where(SapObject.described_by == "ai")) or 0
    by = {r[0]: {"calls": r[1], "chars": int(r[2] or 0), "last": r[3].strftime("%Y-%m-%d %H:%M") if r[3] else ""} for r in rows}
    uses = [{"key": k, "title": t, "text": d, **by.get(k, {"calls": 0, "chars": 0, "last": ""})} for k, t, d in AI_USES]
    return {"uses": uses, "described": described, "total_calls": sum(u["calls"] for u in uses),
            "deterministic": ["Ingestion, parsing and the dependency graph", "Search ranking (BM25 + local embedding model)", "Assessment rules (S/4HANA, Clean Core, security, quality)",
                              "FSD statement extraction, matching with evidence, plan and effort", "Feasibility, complexity and FSD quality scoring", "Guardrail masking of everything before it leaves the machine"]}


def freshness() -> dict:
    """When the code in the repository was last ingested."""
    with session_scope(settings) as s:
        job = s.scalars(select(Job).where(Job.status == "done").order_by(Job.id.desc()).limit(1)).first()
        objects = s.scalar(select(func.count(SapObject.id))) or 0
        if job is None:
            return {"as_of": None, "job_id": None, "objects": int(objects), "source": ""}
        return {"as_of": (job.finished_at or job.started_at), "job_id": job.id, "objects": int(objects), "source": Path(job.source).name if job.source else "",
                "changed": ((job.summary or {}).get("ingest") or {}).get("changed") or ((job.summary or {}).get("ingest") or {}).get("updated")}


def add_guard_terms(terms: list[str]) -> list[str]:
    from atlas.guard.policy import add_terms

    return add_terms(terms, settings)


def _fsd_analysis_raw(analysis_id: int) -> dict | None:
    from atlas.db.models import FsdAnalysis

    with session_scope(settings) as s:
        a = s.get(FsdAnalysis, analysis_id)
        if a is None:
            return None
        return dict(id=a.id, title=a.title, filename=a.filename, verdict=a.verdict, coverage=a.coverage_pct, effort=a.effort_hours,
                    ai=a.ai_reviewed, created=a.created_at.strftime("%Y-%m-%d %H:%M"), result=a.result, report=a.report_md)



def fsd_analysis(analysis_id: int) -> dict | None:
    raw = _fsd_analysis_raw(analysis_id)
    if raw is None:
        return None
    g = _title_guard(raw.get("result"))
    out = masked(raw, g)
    out["title"] = g.mask_for_display(raw["title"])
    # names that come out of the FSD (planned objects, building blocks, entities) can carry a customer code
    # (ZSCM_<client>_VEN_ST) - unlike repository object names they are masked too
    plan = (out.get("result") or {}).get("plan") or {}
    for o in plan.get("objects") or []:
        if o.get("action") != "reuse":
            o["name"] = g.mask_for_display(o.get("name", ""))
    for b in plan.get("fsd_blocks") or []:
        b["name"] = g.mask_for_display(b.get("name", ""))
    for st in plan.get("steps") or []:
        for b in st.get("blocks") or []:
            b["name"] = g.mask_for_display(b.get("name", ""))
    ents = (out.get("result") or {}).get("entities") or {}
    for k, vals in ents.items():
        ents[k] = [g.mask_for_display(v) for v in vals]
    snap = (out.get("result") or {}).get("repo_snapshot") or {}
    now = freshness()
    out["stale"] = bool(snap.get("job_id") and now.get("job_id") and now["job_id"] != snap["job_id"])
    out["snapshot"] = {"as_of": (snap.get("as_of") or "")[:16].replace("T", " "), "objects": snap.get("objects"),
                       "now": now["as_of"].strftime("%Y-%m-%d %H:%M") if now.get("as_of") else "", "now_objects": now.get("objects")}
    return out

def fsd_ai_review(analysis_id: int) -> dict:
    """Blocking; call via run.io_bound."""
    from atlas.ai.provider import AIError, get_provider
    from atlas.db.models import FsdAnalysis
    from atlas.fsd.service import refine_with_ai

    with session_scope(settings) as s:
        a = s.get(FsdAnalysis, analysis_id)
        if a is None:
            return {"error": "analysis not found"}
        try:
            provider = get_provider(output_dir=settings.output_dir / "prompts")
            refine_with_ai(s, a, provider)
        except AIError as error:
            return {"error": str(error)}
        return {"ok": True}


# --- settings pages -----------------------------------------------------------------------

def ai_config() -> dict:
    from atlas.ai.provider import load_config, provider_status

    st = provider_status()
    cfg = load_config()
    return {"status": st, "config": {k: v for k, v in cfg.items() if k != "api_key"}, "has_key": bool(cfg.get("api_key"))}


def save_ai_config(provider: str, base_url: str, api_key: str, model: str, keep_key: bool) -> None:
    from atlas.ai.provider import load_config, save_config

    cfg = load_config()
    new = {"provider": provider, "base_url": base_url.strip(), "model": model.strip(), "api_key": (cfg.get("api_key", "") if keep_key else api_key.strip())}
    save_config(new)


def test_ai(provider: str, base_url: str, api_key: str, model: str) -> dict:
    """Blocking; call via run.io_bound."""
    from atlas.ai.provider import load_config, test_provider

    if not api_key:
        api_key = load_config().get("api_key", "") if load_config().get("provider") == provider else ""
    return test_provider(provider, base_url, api_key, model)


def guard_policy() -> dict:
    from dataclasses import asdict

    from atlas.guard.policy import GuardPolicy, policy_path

    return asdict(GuardPolicy.load(policy_path(settings)))


def save_guard_policy(values: dict) -> None:
    from atlas.guard.policy import GuardPolicy, invalidate, policy_path

    p = GuardPolicy(**{k: v for k, v in values.items() if k in GuardPolicy.__dataclass_fields__})
    p.save(policy_path(settings))
    invalidate()


def guard_preview(text: str) -> dict:
    from atlas.ai.redact import redact
    from atlas.guard.policy import get_guard, invalidate

    invalidate()
    r = redact(text)
    return {"ai": r.text, "kinds": r.kinds, "display": get_guard(settings).mask_for_display(text)}


def egress_log(limit: int = 30) -> list[dict]:
    with session_scope(settings) as s:
        rows = s.scalars(select(AICall).order_by(AICall.id.desc()).limit(limit)).all()
        return [dict(id=c.id, when=c.created_at.strftime("%Y-%m-%d %H:%M"), purpose=c.purpose, provider=c.provider, model=c.model, status=c.status,
                     objects=len(c.object_ids or []), chars=c.input_chars, redactions=c.redactions, tokens=f"{c.input_tokens}/{c.output_tokens}", cost=c.cost_usd) for c in rows]


# --- value engine ------------------------------------------------------------------------------------

def value_view(hourly_rate: float = 60.0, team_size: int = 4, currency: str = "USD") -> dict:
    from atlas.value.business_case import CaseParams, conversion_case, portfolio_value
    from atlas.value.retirement import decide

    params = CaseParams(hourly_rate=hourly_rate, team_size=team_size, currency=currency)
    with session_scope(settings) as s:
        case = conversion_case(s, params)
        pf = portfolio_value(s, params)
        ret = decide(s, hourly_rate)
    return {"case": case, "portfolio": pf, "retirement": ret, "params": params.__dict__.copy()}


def business_case_file(hourly_rate: float = 60.0, team_size: int = 4, currency: str = "USD", customer: str = "the customer") -> tuple[bytes, str]:
    from atlas.value.business_case import CaseParams, business_case_docx, conversion_case, portfolio_value

    params = CaseParams(hourly_rate=hourly_rate, team_size=team_size, currency=currency)
    with session_scope(settings) as s:
        case = conversion_case(s, params)
        pf = portfolio_value(s, params)
    return business_case_docx(case, pf, customer=customer), "S4HANA_Custom_Code_Business_Case.docx"


def import_usage_file(path: str, source: str = "ST03N", period_days: int = 365, period_from: str = "", period_to: str = "") -> dict:
    from atlas.value.retirement import import_usage

    try:
        with session_scope(settings) as s:
            res = import_usage(s, Path(path), source, period_days, period_from, period_to)
        invalidate()
        return res.as_dict()
    except Exception as error:      # noqa: BLE001
        return {"error": f"{error.__class__.__name__}: {error}"}


def fsd_code_package(analysis_id: int) -> tuple[bytes, str, list[str]]:
    from atlas.db.models import FsdAnalysis
    from atlas.fsd.codegen import build_code_package

    with session_scope(settings) as s:
        a = s.get(FsdAnalysis, analysis_id)
        if a is None:
            raise ValueError("Analysis not found")
        g = _title_guard(a.result)
        blob, names = build_code_package(a.result, g.mask_for_display)
        return blob, Path(a.filename).stem + "_code_skeletons.zip", names


# --- workspace-related documents and views ----------------------------------------------------------

def protection_sheet() -> tuple[bytes, str]:
    from atlas.value.protection import protection_facts, protection_sheet_docx

    info = active_workspace()
    with session_scope(settings) as s:
        facts = protection_facts(s, settings, info)
    return protection_sheet_docx(facts), f"Data_Protection_Sheet_{info.slug}.docx"


def compare_candidates_for(analysis_id: int) -> list[dict]:
    from atlas.db.models import FsdAnalysis
    from atlas.value.protection import compare_candidates

    with session_scope(settings) as s:
        a = s.get(FsdAnalysis, analysis_id)
        if a is None:
            return []
        g = _title_guard(a.result)
        rows = compare_candidates(s, a.result)
        for r in rows:
            r["name"] = g.mask_for_display(r["name"])
        return rows


def usage_window() -> dict:
    from atlas.value.retirement import usage_window as _uw

    with session_scope(settings) as s:
        return _uw(s)

"""ABAP Beacon (Custom Code Intelligence for SAP) command line.

    atlas run  export.zip --system DEV        full pipeline (ingest -> enrich -> index)
    atlas search "report that ages vendor open items"
    atlas show ZCL_ZSD_SALESORDER
    atlas stats / objects / jobs
    atlas watch data/input --system DEV       automation: process every new ZIP
    atlas assess / findings / deps NAME / impact NAME / tables
    atlas enrich-ai --limit 10                AI descriptions via Claude Code (no API key)
    atlas ask "how does the sales order service validate the reference?"
    atlas ui                                  web app
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from atlas import __version__
from atlas.config import get_settings
from atlas.db.models import Job, Package, SapObject, System
from atlas.db.session import init_db, session_scope
from atlas.enrich.service import enrich_offline
from atlas.ingest.abapgit import find_latest_zip, read_export
from atlas.ingest.service import ingest_report
from atlas.ingest.types import get_type
from atlas.legacy.import_json import import_legacy
from atlas.pipeline.runner import PipelineOptions, rebuild_semantic_index, run_pipeline, watch_folder
from atlas.search import semantic
from atlas.search.engine import SearchEngine, SearchFilters, relevance_label

def _m(text: str) -> str:
    """Display guardrail for CLI output."""
    from atlas.guard.policy import mask_display

    return mask_display(text or "")


app = typer.Typer(add_completion=False, no_args_is_help=True, help="ABAP Beacon by InfraBeat - custom code intelligence for SAP (CLI name: atlas).")
console = Console()
settings = get_settings()
if os.environ.get("ATLAS_WORKSPACE") and os.environ["ATLAS_WORKSPACE"] != "default":
    from atlas.workspace import settings_for as _ws_settings

    settings = _ws_settings(os.environ["ATLAS_WORKSPACE"], settings)


def _setup_logging() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=True)],
    )


def _check_database(auto_repair: bool = True) -> None:
    """Every command starts here: a damaged SQLite file is repaired (stale WAL, recoverable rows)
    or replaced by an empty one, and the user is told exactly what happened - never a stack trace."""
    if settings.db_url and not settings.db_url.startswith("sqlite"):
        return
    from atlas.db.health import ensure_healthy

    try:
        health = ensure_healthy(settings.db_path, auto_repair=auto_repair)
    except Exception as error:      # noqa: BLE001 - never block a command on the health check itself
        console.print(f"[yellow]Database check skipped: {error}[/yellow]")
        return
    if health.actions:
        console.print("[yellow]Database check: the database file was damaged and has been repaired.[/yellow]")
        for a in health.actions:
            console.print(f"  - {a}")
    elif not health.ok:
        console.print(f"[red]{health.summary()}[/red]")
        console.print("Run:  atlas db-repair   (or .\\run.bat db-repair on Windows)")
        raise typer.Exit(1)


@app.callback()
def _main(ctx: typer.Context) -> None:
    _setup_logging()
    if ctx.invoked_subcommand not in ("db-check", "db-repair", "version"):
        _check_database()


@app.command(name="db-check")
def db_check() -> None:
    """Check the database file (PRAGMA quick_check) and report its state."""
    from atlas.db.health import check, quarantine_stale_logs

    for a in quarantine_stale_logs(settings.db_path):
        console.print(f"  - {a}")
    h = check(settings.db_path)
    console.print(("[green]" if h.ok else "[red]") + h.summary() + ("[/green]" if h.ok else "[/red]"))


@app.command(name="db-repair")
def db_repair() -> None:
    """Repair a damaged database: remove a stale write-ahead log, recover readable rows, or start fresh."""
    from atlas.db.health import repair

    h = repair(settings.db_path)
    for a in h.actions:
        console.print(f"  - {a}")
    console.print(("[green]" if h.ok else "[red]") + h.summary() + ("[/green]" if h.ok else "[/red]"))


@app.command()
def version() -> None:
    """Show version and data location."""
    console.print(f"ABAP Beacon - Custom Code Intelligence for SAP  v{__version__}  (InfraBeat)")
    console.print(f"data dir : {settings.data_dir}")
    console.print(f"database : {settings.database_url}")


@app.command()
def init() -> None:
    """Create the data folders and database schema."""
    init_db(settings)
    console.print(f"[green]Ready.[/green] Database at {settings.db_path}")


def _resolve_source(source: Optional[str]) -> Path:
    if source:
        return Path(source)
    latest = find_latest_zip(settings.input_dir)
    if latest is None:
        console.print(f"[red]No export given and no .zip in {settings.input_dir}[/red]")
        raise typer.Exit(1)
    console.print(f"Using newest ZIP in input folder: {latest.name}")
    return latest


@app.command()
def run(
    source: Optional[str] = typer.Argument(None, help="abapGit ZIP or folder (default: newest ZIP in data/input)"),
    system: str = typer.Option("DEV", "--system", "-s", help="SAP system ID the export came from"),
    package: Optional[str] = typer.Option(None, "--package", "-p", help="Name of the root package (not stored in the export)"),
    no_semantic: bool = typer.Option(False, "--no-semantic", help="Skip building the meaning index"),
    ai: bool = typer.Option(False, "--ai", help="Also run AI descriptions for changed objects (Claude Code / API)"),
    ai_limit: Optional[int] = typer.Option(None, "--ai-limit", help="Max objects to describe with AI in this run"),
) -> None:
    """Run the full pipeline: acquire -> ingest -> parse -> enrich -> assess -> [ai] -> index."""
    path = _resolve_source(source)

    def progress(step: str, status: str) -> None:
        colour = {"started": "cyan", "done": "green", "skipped": "yellow", "failed": "red"}[status]
        console.print(f"  [{colour}]{status:8}[/{colour}] {step}")

    console.print(Panel.fit(f"Pipeline for [bold]{path.name}[/bold] -> system [bold]{system.upper()}[/bold]", border_style="blue"))
    job = run_pipeline(PipelineOptions(source=str(path), system=system, root_package=package, build_semantic=not no_semantic, ai_enrich=ai, ai_limit=ai_limit, progress=progress), settings)
    _print_job(job)
    if job.status != "done":
        raise typer.Exit(1)


@app.command()
def ingest(
    source: Optional[str] = typer.Argument(None),
    system: str = typer.Option("DEV", "--system", "-s"),
    package: Optional[str] = typer.Option(None, "--package", "-p"),
) -> None:
    """Ingest only (no enrichment, no index)."""
    path = _resolve_source(source)
    report = read_export(path)
    with session_scope(settings) as session:
        summary = ingest_report(session, report, system, package)
    table = Table(title="Ingest", box=box.SIMPLE)
    for k, v in summary.as_dict().items():
        if k != "by_type":
            table.add_row(k, str(v))
    console.print(table)
    _print_by_type(summary.by_type)


@app.command()
def enrich(system: Optional[str] = typer.Option(None, "--system", "-s")) -> None:
    """Re-run offline enrichment for all objects (AI/human descriptions are kept)."""
    with session_scope(settings) as session:
        summary = enrich_offline(session, system_sid=system)
    console.print(summary.as_dict())


@app.command()
def index(
    system: Optional[str] = typer.Option(None, "--system", "-s"),
    builtin: bool = typer.Option(False, "--builtin", help="Force the numpy fallback even if MiniLM is installed"),
) -> None:
    """(Re)build the meaning index."""
    backend = semantic.best_backend(not builtin)
    if backend == "minilm":
        console.print("Using local MiniLM model (first run downloads ~90 MB).")
    elif backend == "model2vec":
        console.print("Using local model2vec static embeddings (first run downloads ~30 MB).")
    else:
        console.print("[yellow]Using built-in TF-IDF/SVD fallback.[/yellow] pip install model2vec  (works on Python 3.14) for real meaning search.")
    with session_scope(settings) as session:
        result = rebuild_semantic_index(session, settings, system, prefer_minilm=not builtin)
    console.print(result)


@app.command()
def search(
    query: str = typer.Argument(..., help="Plain-English requirement"),
    mode: str = typer.Option("hybrid", "--mode", "-m", help="hybrid | keyword | semantic"),
    limit: int = typer.Option(10, "--limit", "-n"),
    type_: Optional[str] = typer.Option(None, "--type", "-t", help="Object type filter, e.g. CLAS,PROG"),
    module: Optional[str] = typer.Option(None, "--module"),
    system: Optional[str] = typer.Option(None, "--system", "-s"),
    source: bool = typer.Option(False, "--source", help="Print the first 40 lines of source per result"),
) -> None:
    """Search the repository."""
    with session_scope(settings) as session:
        engine = SearchEngine(session, settings.index_dir, system)
        if engine.size == 0:
            console.print("[red]Nothing ingested yet. Run: atlas run <export.zip>[/red]")
            raise typer.Exit(1)
        filters = SearchFilters(types=type_.split(",") if type_ else None, module=module)
        results = engine.search(query, limit=limit, mode=mode, filters=filters)

        backend = engine.semantic.backend if engine.semantic else "none"
        console.print(f'\n[bold]{len(results)} result(s)[/bold] for "{query}"  [dim](mode {mode}, semantic backend {backend})[/dim]\n')
        if not results:
            console.print("No matches. Try business words (what it does) rather than technical names.")
            return

        for i, r in enumerate(results, start=1):
            o = r.object
            head = f"[bold cyan]{o.name}[/bold cyan]  [dim]{r.type_label}"
            if o.module:
                head += f" · {o.module}"
            head += f" · {o.source_lines} lines · {o.described_by}[/dim]"
            label = relevance_label(r.score)
            colour = {"strong": "green", "good": "yellow", "weak": "grey62"}[label]
            console.print(f"{i:>2}. {head}   [{colour}]{r.score:5.1f} {label}[/{colour}]")
            if o.short_text:
                console.print(f"    [italic]{_m(o.short_text)}[/italic]")
            console.print(f"    {_m(o.description[:420])}{'...' if len(o.description) > 420 else ''}")
            if o.tags:
                console.print(f"    [dim]tags:[/dim] {_m(', '.join(o.tags[:10]))}")
            for hit in r.component_hits:
                console.print(f"    [dim]  ↳ {hit.kind} {hit.name}[/dim] {_m(hit.short_text)}")
            if r.matched_terms:
                console.print(f"    [dim]matched: {', '.join(r.matched_terms)}[/dim]")
            if source and o.source:
                console.print(Panel("\n".join(o.source.splitlines()[:40]), title=o.name, border_style="grey37"))
            console.print()


@app.command()
def show(name: str, system: Optional[str] = typer.Option(None, "--system", "-s"), lines: int = typer.Option(60, "--lines")) -> None:
    """Show one object: metadata, components, description and the start of its source."""
    with session_scope(settings) as session:
        query = select(SapObject).options(selectinload(SapObject.files), selectinload(SapObject.components), selectinload(SapObject.package)).where(SapObject.name == name.upper())
        if system:
            query = query.join(System).where(System.sid == system.upper())
        found = list(session.scalars(query))
        if not found:
            console.print(f"[red]No object named {name.upper()}[/red]")
            raise typer.Exit(1)
        for o in found:
            console.print(Panel.fit(f"[bold]{o.name}[/bold]  {get_type(o.obj_type).label} ({o.obj_type})", border_style="cyan"))
            table = Table(box=box.SIMPLE, show_header=False)
            table.add_row("short text", _m(o.short_text) or "-")
            table.add_row("package", o.package.name if o.package else "-")
            table.add_row("module", o.module or "-")
            table.add_row("complexity", o.complexity or "-")
            table.add_row("source", f"{o.source_lines} lines in {len(o.source_files)} file(s); {o.file_count} files total")
            table.add_row("described by", f"{o.described_by} ({o.review_status})")
            table.add_row("tags", _m(", ".join(o.tags or [])) or "-")
            table.add_row("attributes", ", ".join(f"{k}={v}" for k, v in (o.attributes or {}).items() if k != "tables") or "-")
            table.add_row("tables", ", ".join((o.attributes or {}).get("tables", [])) or "-")
            console.print(table)
            console.print(_m(o.description))
            comps = [c for c in o.components if c.kind not in ("parameter",)]
            if comps:
                ct = Table(title=f"{len(comps)} components", box=box.SIMPLE)
                ct.add_column("kind"); ct.add_column("name"); ct.add_column("short text")
                for c in comps[:40]:
                    ct.add_row(c.kind, c.name, _m(c.short_text))
                if len(comps) > 40:
                    ct.add_row("...", f"+{len(comps) - 40} more", "")
                console.print(ct)
            for f in o.source_files[:1]:
                console.print(Panel("\n".join(f.content.splitlines()[:lines]), title=f.path, border_style="grey37"))


@app.command()
def objects(
    type_: Optional[str] = typer.Option(None, "--type", "-t"),
    system: Optional[str] = typer.Option(None, "--system", "-s"),
    limit: int = typer.Option(200, "--limit", "-n"),
) -> None:
    """List objects in the repository."""
    with session_scope(settings) as session:
        query = select(SapObject).options(selectinload(SapObject.package)).order_by(SapObject.obj_type, SapObject.name)
        if type_:
            query = query.where(SapObject.obj_type.in_([t.upper() for t in type_.split(",")]))
        if system:
            query = query.join(System).where(System.sid == system.upper())
        rows = list(session.scalars(query.limit(limit)))
        table = Table(box=box.SIMPLE_HEAD)
        for col in ("type", "name", "module", "lines", "cx", "desc", "short text"):
            table.add_column(col)
        for o in rows:
            table.add_row(o.obj_type, o.name, o.module, str(o.source_lines), o.complexity, o.described_by, _m((o.short_text or "")[:60]))
        console.print(table)
        console.print(f"{len(rows)} object(s)")


@app.command()
def stats() -> None:
    """Repository statistics."""
    with session_scope(settings) as session:
        systems = list(session.scalars(select(System)))
        if not systems:
            console.print("Empty repository. Run: atlas run <export.zip>")
            return
        for sys_ in systems:
            total = session.scalar(select(func.count(SapObject.id)).where(SapObject.system_id == sys_.id))
            lines = session.scalar(select(func.coalesce(func.sum(SapObject.source_lines), 0)).where(SapObject.system_id == sys_.id))
            pkgs = session.scalar(select(func.count(Package.id)).where(Package.system_id == sys_.id))
            console.print(Panel.fit(f"[bold]{sys_.sid}[/bold]  {total} objects · {lines:,} lines of source · {pkgs} package(s)", border_style="blue"))
            by_type = dict(session.execute(select(SapObject.obj_type, func.count()).where(SapObject.system_id == sys_.id).group_by(SapObject.obj_type)).all())
            _print_by_type(by_type)
            by_desc = dict(session.execute(select(SapObject.described_by, func.count()).where(SapObject.system_id == sys_.id).group_by(SapObject.described_by)).all())
            console.print(f"descriptions: {by_desc}")
        idx = semantic.load_index(settings.index_dir)
        console.print(f"semantic index: {semantic.describe_backend(idx.backend) if idx else 'not built'}")


@app.command()
def jobs(limit: int = typer.Option(10, "--limit", "-n")) -> None:
    """Recent pipeline runs."""
    with session_scope(settings) as session:
        rows = list(session.scalars(select(Job).options(selectinload(Job.steps)).order_by(Job.id.desc()).limit(limit)))
        if not rows:
            console.print("No jobs yet.")
            return
        for job in rows:
            _print_job(job)


@app.command()
def watch(
    folder: Optional[str] = typer.Argument(None, help="Folder to watch (default data/input)"),
    system: str = typer.Option("DEV", "--system", "-s"),
    interval: int = typer.Option(10, "--interval", help="Seconds between scans"),
) -> None:
    """Automation: process every new or changed ZIP dropped into a folder."""
    target = Path(folder) if folder else settings.input_dir
    console.print(f"Watching [bold]{target}[/bold] every {interval}s. Ctrl+C to stop.")
    try:
        watch_folder(target, system, settings, interval=interval)
    except KeyboardInterrupt:
        console.print("stopped.")


# --- analysis ------------------------------------------------------------------------

@app.command()
def parse(system: Optional[str] = typer.Option(None, "--system", "-s")) -> None:
    """(Re)parse source: components with line ranges, references, metrics."""
    from atlas.parse.service import parse_objects

    with session_scope(settings) as session:
        console.print(parse_objects(session, system_sid=system).as_dict())


@app.command()
def assess(system: Optional[str] = typer.Option(None, "--system", "-s")) -> None:
    """Run the rule engine (S/4HANA, security, quality, Clean Core) over all objects."""
    from atlas.assess.service import assess_objects, findings_overview

    with session_scope(settings) as session:
        summary = assess_objects(session, system_sid=system)
    console.print(summary.as_dict())
    with session_scope(settings) as session:
        ov = findings_overview(session, system)
    table = Table(title="Findings by rule", box=box.SIMPLE_HEAD)
    for col in ("rule", "sev", "findings", "objects", "effort h", "title"):
        table.add_column(col)
    for r in ov["rules"]:
        table.add_row(r["rule_id"], r["severity"], str(r["findings"]), str(r["objects"]), str(r["effort"]), r["title"])
    console.print(table)
    console.print(f"Clean Core tiers: {ov['tiers']}   S/4 status: {ov['s4_status']}   remediation estimate: {ov['effort_hours']} h")


@app.command()
def findings(
    category: Optional[str] = typer.Option(None, "--category", "-c", help="s4hana | security | quality | cleancore"),
    severity: Optional[str] = typer.Option(None, "--severity"),
    rule_id: Optional[str] = typer.Option(None, "--rule"),
    object_name: Optional[str] = typer.Option(None, "--object", "-o"),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """List findings."""
    from atlas.assess.service import list_findings

    with session_scope(settings) as session:
        oid = None
        if object_name:
            oid = session.scalar(select(SapObject.id).where(SapObject.name == object_name.upper()))
        rows = list_findings(session, category, severity, rule_id, "open", oid, limit=limit)
    for f in rows:
        colour = {"high": "red", "medium": "yellow", "low": "cyan", "info": "grey62"}[f["severity"]]
        console.print(f"[{colour}]{f['severity']:6}[/{colour}] {f['rule_id']:8} [bold]{f['object']}[/bold] L{f['line']}  {f['title']}")
        console.print(f"         {f['message'][:160]}")
        if f["snippet"]:
            console.print(f"         [dim]{f['snippet'][:120]}[/dim]")
    console.print(f"{len(rows)} finding(s)")


@app.command()
def deps(name: str) -> None:
    """Dependencies of an object: what it uses and who uses it."""
    from atlas.parse.service import dependencies

    with session_scope(settings) as session:
        oid = session.scalar(select(SapObject.id).where(SapObject.name == name.upper()).order_by(SapObject.source_lines.desc()))
        if oid is None:
            console.print(f"[red]No object {name.upper()}[/red]")
            raise typer.Exit(1)
        view = dependencies(session, oid)
    console.print(Panel.fit(f"[bold]{name.upper()}[/bold]", border_style="cyan"))
    if view.tables:
        t = Table(title="Tables / views", box=box.SIMPLE_HEAD)
        for col in ("access", "table", "text", "S/4", "in"):
            t.add_column(col)
        for e in view.tables:
            t.add_row(e["kind"], e["name"], e["std_text"] or ("custom" if e["is_custom"] else ""), e["s4_status"], ", ".join(e["components"])[:40])
        console.print(t)
    if view.outgoing:
        t = Table(title="Uses", box=box.SIMPLE_HEAD)
        for col in ("kind", "target", "type", "custom", "in"):
            t.add_column(col)
        for e in view.outgoing:
            t.add_row(e["kind"], e["name"], e["target_type"], "yes" if e["is_custom"] else "", ", ".join(e["components"])[:40])
        console.print(t)
    if view.incoming:
        t = Table(title="Used by", box=box.SIMPLE_HEAD)
        for col in ("object", "type", "kind", "in"):
            t.add_column(col)
        for e in view.incoming:
            t.add_row(e["name"], e["type"], e["kind"], e["component"])
        console.print(t)
    if not (view.tables or view.outgoing or view.incoming):
        console.print("No references recorded. Run `atlas parse` first.")


@app.command()
def impact(name: str, depth: int = typer.Option(3, "--depth")) -> None:
    """Who depends on this object / table / function module, transitively."""
    from atlas.parse.service import impact as _impact

    with session_scope(settings) as session:
        result = _impact(session, name, depth)
    console.print(f"[bold]{result['root']}[/bold]: {result['total']} dependent object(s)")
    for level in result["levels"]:
        for e in level:
            console.print(f"  {'  ' * (e['level'] - 1)}L{e['level']} {e['name']}  [dim]{e['type']} · {e['kind']} {e['via']}[/dim]")


@app.command()
def tables(limit: int = typer.Option(30, "--limit", "-n")) -> None:
    """Most-used tables across the custom code with S/4HANA status."""
    from atlas.parse.service import where_used_tables

    with session_scope(settings) as session:
        rows = where_used_tables(session, limit=limit)
    t = Table(box=box.SIMPLE_HEAD)
    for col in ("table", "objects", "refs", "module", "S/4", "successor", "text"):
        t.add_column(col)
    for r in rows:
        t.add_row(r["name"], str(r["objects"]), str(r["references"]), r["module"], r["s4_status"], r["successor"][:30], r["text"][:40])
    console.print(t)


# --- AI ---------------------------------------------------------------------------------

@app.command("ai-status")
def ai_status() -> None:
    """Which AI provider will be used."""
    from atlas.ai.provider import provider_status

    st = provider_status()
    console.print(f"selected: [bold]{st['selected']}[/bold]  model: {st['model'] or '-'}  ready: {st['ready']}  ({st['reason']})")
    console.print("options: claude-code, anthropic, " + ", ".join(o["id"] for o in st["options"]) + ", manual")
    console.print("configure: web app → Settings → AI provider, or env ATLAS_AI_PROVIDER / ATLAS_AI_API_KEY / ATLAS_AI_BASE_URL / ATLAS_AI_MODEL")
    if not st["ready"]:
        console.print("[yellow]Free options: Ollama (local, offline), Groq / OpenRouter / Gemini / Mistral (free API keys). Manual mode always works: atlas enrich-ai --export[/yellow]")


@app.command("enrich-ai")
def enrich_ai_cmd(
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Max objects this run"),
    force: bool = typer.Option(False, "--force", help="Re-describe objects that already have AI descriptions"),
    system: Optional[str] = typer.Option(None, "--system", "-s"),
    provider: Optional[str] = typer.Option(None, "--provider", help="claude-code | anthropic | manual"),
    export: bool = typer.Option(False, "--export", help="Manual mode: write prompt pack files instead of calling anything"),
    ddic: bool = typer.Option(False, "--ddic", help="Also describe tables, table types, data elements, messages"),
) -> None:
    """Generate AI descriptions (default provider: Claude Code headless, using your subscription)."""
    from atlas.ai.enrich import enrich_ai, export_prompt_pack
    from atlas.ai.provider import AIError, get_provider

    prompts_dir = settings.output_dir / "prompts"
    if export:
        with session_scope(settings) as session:
            paths = export_prompt_pack(session, prompts_dir, system_sid=system, force=force)
        console.print(f"{len(paths)} prompt pack file(s) written to {prompts_dir}. Paste each into Claude, save the JSON reply next to it, then: atlas ai-import <file.json>")
        return
    try:
        prov = get_provider(provider, prompts_dir)
    except AIError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1)
    console.print(f"Provider: [bold]{prov.name}[/bold]")
    with session_scope(settings) as session:
        summary = enrich_ai(session, prov, system_sid=system, limit=limit, force=force, include_ddic=ddic, progress=lambda m: console.print(f"  [dim]{m}[/dim]"))
    console.print(summary.as_dict())
    if summary.stopped_reason:
        console.print(f"[yellow]Stopped: {summary.stopped_reason}[/yellow]  Re-run later; described objects are kept, nothing is sent twice.")
    if summary.described:
        console.print("Rebuilding meaning index...")
        with session_scope(settings) as session:
            rebuild_semantic_index(session, settings, system)


@app.command("ai-import")
def ai_import(path: str, system: Optional[str] = typer.Option(None, "--system", "-s")) -> None:
    """Import a JSON reply saved from Claude (manual mode)."""
    from atlas.ai.enrich import import_reply

    with session_scope(settings) as session:
        applied, unmatched = import_reply(session, path, system)
    console.print(f"applied: {applied}" + (f"  unmatched: {', '.join(unmatched)}" if unmatched else ""))


@app.command()
def ask(
    question: str = typer.Argument(..., help="Question about the code base"),
    k: int = typer.Option(5, "--k", help="Objects to retrieve as context"),
    provider: Optional[str] = typer.Option(None, "--provider"),
) -> None:
    """Ask the codebase - answers grounded in retrieved source with line citations."""
    from atlas.ai.ask import ask as _ask
    from atlas.ai.provider import AIError, get_provider

    try:
        prov = get_provider(provider, settings.output_dir / "prompts")
    except AIError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1)
    with session_scope(settings) as session:
        engine = SearchEngine(session, settings.index_dir)
        answer = _ask(session, engine, prov, question, k)
    if answer.error:
        console.print(f"[red]{answer.error}[/red]")
        raise typer.Exit(1)
    from atlas.guard.policy import mask_display

    console.print(Panel(mask_display(answer.answer), title=question, border_style="cyan"))
    console.print("[dim]context: " + ", ".join(f"{s.name} L{'/'.join(f'{a}-{b}' for a, b in s.excerpts)}" for s in answer.sources) + f"  · provider {answer.provider} · {answer.input_tokens} in / {answer.output_tokens} out tokens · redactions {answer.redactions}[/dim]")


# --- FSD ---------------------------------------------------------------------------------

@app.command()
def fsd(
    path: str = typer.Argument(..., help="Functional specification (.docx, .md, .txt)"),
    ai: bool = typer.Option(False, "--ai", help="Add an AI review of the analysis (Claude Code / API)"),
    out: Optional[str] = typer.Option(None, "--out", "-o", help="Write the Markdown report here (default: data/output/fsd/<name>.md)"),
    no_store: bool = typer.Option(False, "--no-store", help="Do not save the analysis in the repository"),
    docx: bool = typer.Option(False, "--docx", help="Also write the Technical Specification (.docx) next to the report"),
) -> None:
    """Analyse an FSD: what is already covered by existing objects, what to change, and how to build the rest."""
    from atlas.fsd.reader import FsdReadError
    from atlas.fsd.service import analyse_file, display_guard, refine_with_ai

    with session_scope(settings) as session:
        engine = SearchEngine(session, settings.index_dir)
        try:
            analysis = analyse_file(session, engine, path, store=not no_store)
        except FsdReadError as error:
            console.print(f"[red]{error}[/red]")
            raise typer.Exit(1)
        guard = display_guard(analysis, settings)
        detected = list(analysis.result.get("detected_terms") or [])
        if ai:
            from atlas.ai.provider import AIError, get_provider

            try:
                console.print("Asking the AI provider for a review...")
                refine_with_ai(session, analysis, get_provider(output_dir=settings.output_dir / "prompts"))
            except AIError as error:
                console.print(f"[yellow]AI review skipped: {error}[/yellow]")
        result = analysis.result
        report = guard.mask_for_display(analysis.report_md)
        title, cov, verdict, effort = guard.mask_for_display(analysis.title), analysis.coverage_pct, analysis.verdict, analysis.effort_hours
    if detected:
        console.print(f"[yellow]Guardrails: names detected in the document and masked: {', '.join(detected)} - add them permanently with:  atlas guard-add {' '.join(repr(t) for t in detected)}[/yellow]")

    colour = {"reuse": "green", "extend": "yellow", "build": "cyan"}[verdict]
    st = result["stats"]
    console.print(Panel.fit(f"[bold]{title}[/bold]\n[{colour}]{verdict.upper()}[/{colour}] · coverage {cov}% · {st['requirements']} requirements "
                            f"({st['covered']} covered / {st['partial']} partial / {st['missing']} missing) · remaining effort ~{effort} h", border_style=colour))
    if result["reuse"]:
        t = Table(title="Existing objects to reuse", box=box.SIMPLE_HEAD)
        for col in ("object", "type", "covers", "covered", "partial", "missing"):
            t.add_column(col)
        for c in result["reuse"]:
            t.add_row(c["name"], c["type"], f"{c['coverage_pct']}%", ", ".join(c["covered"]) or "-", ", ".join(c["partial"]) or "-", ", ".join(c["missing"]) or "-")
        console.print(t)
    t = Table(title="Requirements", box=box.SIMPLE_HEAD, show_lines=False)
    for col in ("#", "kind", "status", "best match", "what to do"):
        t.add_column(col)
    for r in result["requirements"]:
        b = r["best"]
        sc = {"covered": "green", "partial": "yellow", "missing": "red"}[r["status"]]
        t.add_row(r["id"], r["kind"], f"[{sc}]{r['status']}[/{sc}]", (b["name"] if b else "-"), guard.mask_for_display(r["change"])[:140])
    console.print(t)
    plan = result["plan"]
    console.print(f"[bold]Solution pattern:[/bold] {plan['pattern']}")
    for step in plan["steps"]:
        blocks = ", ".join(b["name"] for b in step["blocks"][:3])
        console.print(f"  {step['n']}. {step['title']}" + (f"  [dim]{blocks}[/dim]" if blocks else "") + (f"  [green]reuse {step['reuse']}[/green]" if step["reuse"] else ""))
    console.print("[bold]Objects:[/bold] " + "; ".join(f"{o['action']} {o['name']} ({o['type']})" for o in plan["objects"]))

    if plan.get("alternatives"):
        console.print("[bold]Design alternatives to raise:[/bold]")
        for alt in plan["alternatives"]:
            console.print(f"  - {alt}")

    out_path = Path(out) if out else settings.output_dir / "fsd" / (Path(path).stem + ".md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    if docx:
        from atlas.fsd.techspec import build_technical_spec

        payload = dict(result)
        payload["filename"] = Path(path).name
        ts_path = out_path.with_name(Path(path).stem + "_Technical_Spec.docx")
        ts_path.write_bytes(build_technical_spec(payload, guard.mask_for_display))
        console.print(f"Technical Spec written to {ts_path}")
    fz = result.get("feasibility") or {}
    if fz:
        console.print(f"[bold]Feasibility:[/bold] {fz['verdict']} · complexity {fz['complexity']['band']} · FSD quality {fz['quality']['score']}/100 · {fz['rice']}")
        for q in fz.get("questions", [])[:6]:
            console.print(f"  ? {q}")
    console.print(f"Report written to {out_path}")


@app.command("fsd-list")
def fsd_list() -> None:
    """Previously analysed FSDs."""
    from atlas.fsd.service import display_guard, list_analyses

    with session_scope(settings) as session:
        rows = list_analyses(session)
        t = Table(box=box.SIMPLE_HEAD)
        for col in ("id", "title", "verdict", "coverage", "reqs", "effort h", "ai", "when"):
            t.add_column(col)
        for a in rows:
            t.add_row(str(a.id), display_guard(a, settings).mask_for_display(a.title)[:60], a.verdict, f"{a.coverage_pct}%", str(a.requirement_count), str(a.effort_hours), "yes" if a.ai_reviewed else "", a.created_at.strftime("%Y-%m-%d %H:%M"))
    console.print(t)


@app.command(name="usage-import")
def usage_import(path: str, source: str = typer.Option("ST03N", "--source", help="ST03N | SCMON | SUSG | manual"), days: int = typer.Option(90, "--days", help="Length of the usage period in days when --from/--to are not given"),
                 period_from: str = typer.Option("", "--from", help="First day the export covers, YYYY-MM-DD"), period_to: str = typer.Option("", "--to", help="Last day the export covers, YYYY-MM-DD"),
                 replace: bool = typer.Option(False, "--replace", help="Discard earlier imports from the same source")) -> None:
    """Import production usage (CSV/TSV with object name and calls). Imports ACCUMULATE: upload each quarter's export with its period."""
    from atlas.value.retirement import import_usage, usage_window

    with session_scope(settings) as session:
        res = import_usage(session, Path(path), source, days, period_from, period_to, replace)
        win = usage_window(session)
    console.print(f"Imported {res.rows} rows - {res.matched} matched repository objects, {res.unknown} unknown names ({source})")
    console.print(f"Usage window now: {win['from']} to {win['to']} = {win['months']} months from {win['imports']} import(s)" + ("" if win["enough"] else "  (below 12 months: no object is marked 'retire' yet)"))


@app.command()
def workspace(action: str = typer.Argument("list", help="list | create | show"), name: str = typer.Argument("", help="Workspace name (create)"),
              kind: str = typer.Option("customer", "--kind", help="customer | internal"), ai_mode: str = typer.Option("normal", "--ai", help="normal | strict"),
              release: str = typer.Option("2023", "--release", help="Assessment target release: 1709..2025 or cloud")) -> None:
    """Workspaces: one isolated data set per customer. Activate one with the environment variable ATLAS_WORKSPACE=<slug> (or the Workspaces page)."""
    from atlas.workspace import create_workspace, current_slug, list_workspaces, load_info

    if action == "create":
        info = create_workspace(name, kind, name if kind == "customer" else "", ai_mode, "cloud" if release == "cloud" else release, "cloud" if release == "cloud" else "onprem")
        console.print(f"Created workspace '{info.name}' (slug {info.slug}). Activate it with:  set ATLAS_WORKSPACE={info.slug}   (PowerShell: $env:ATLAS_WORKSPACE='{info.slug}')")
        return
    if action == "show":
        console.print(load_info(current_slug()).as_dict())
        return
    cur = current_slug()
    for w in list_workspaces():
        console.print(("* " if w.slug == cur else "  ") + f"{w.slug:20} {w.name:30} {w.kind:9} AI {w.ai_mode:7} target {w.target_release}")


@app.command(name="protection-sheet")
def protection_sheet_cmd(out: Optional[str] = typer.Option(None, "--out", "-o")) -> None:
    """Write the Data Protection Sheet (.docx) for the active workspace."""
    from atlas.value.protection import protection_facts, protection_sheet_docx
    from atlas.workspace import current_slug, load_info

    info = load_info(current_slug())
    with session_scope(settings) as session:
        facts = protection_facts(session, settings, info)
    target = Path(out) if out else settings.output_dir / f"Data_Protection_Sheet_{info.slug}.docx"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(protection_sheet_docx(facts))
    console.print(f"Data Protection Sheet written to {target}  (AI mode: {facts['ai_mode']}, provider: {facts['provider']})")


@app.command()
def value(rate: float = typer.Option(60.0, "--rate"), team: int = typer.Option(4, "--team"), currency: str = typer.Option("USD", "--currency"),
          docx: bool = typer.Option(False, "--docx", help="Write the executive business case (.docx) to data/output"), customer: str = typer.Option("the customer", "--customer")) -> None:
    """Executive numbers: remediation programme, retirement savings, reuse savings, Clean Core swaps."""
    from atlas.value.business_case import CaseParams, business_case_docx, conversion_case, portfolio_value
    from atlas.value.retirement import decide

    params = CaseParams(hourly_rate=rate, team_size=team, currency=currency)
    with session_scope(settings) as session:
        case = conversion_case(session, params)
        pf = portfolio_value(session, params)
        ret = decide(session, rate)
    m = lambda x: f"{currency} {x:,.0f}"      # noqa: E731
    console.print(f"[bold]S/4HANA remediation programme:[/bold] {case['total_h']:,.0f} h · {m(case['total_money'])} · {case['weeks']:,.0f} weeks with {team} developers")
    console.print(f"[bold]Retirement:[/bold] retire {ret['totals']['retire']} · review {ret['totals']['review']} · keep {ret['totals']['keep']} → {m(case['saving_money'])} saved" + ("" if ret["have_usage"] else "  (no usage data - import ST03N/SCMON to confirm)"))
    console.print(f"[bold]Reuse savings from FSD analyses:[/bold] {pf['saved_h']:,.0f} h · {m(pf['saved_money'])} across {pf['count']} specifications")
    for w in case["waves"]:
        console.print(f"  wave {w['wave']}: {w['title']} - {w['objects']} objects, {w['hours']:,.0f} h, {m(w['money'])}")
    for sw in case["swaps"][:6]:
        console.print(f"  replace {sw['classic']} → {sw['successor']} ({sw['objects']} objects)")
    if docx:
        out = settings.output_dir / "S4HANA_Custom_Code_Business_Case.docx"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(business_case_docx(case, pf, customer=customer))
        console.print(f"Business case written to {out}")


@app.command()
def codegen(analysis_id: int, out: Optional[str] = typer.Option(None, "--out", "-o")) -> None:
    """Generate ABAP skeletons (classes, tests, tables, program, messages) for a stored FSD analysis."""
    from atlas.db.models import FsdAnalysis
    from atlas.fsd.codegen import build_code_package
    from atlas.fsd.service import display_guard

    with session_scope(settings) as session:
        a = session.get(FsdAnalysis, analysis_id)
        if a is None:
            console.print(f"[red]No analysis with id {analysis_id} (see: atlas fsd-list)[/red]")
            raise typer.Exit(1)
        blob, names = build_code_package(a.result, display_guard(a, settings).mask_for_display)
        target = Path(out) if out else settings.output_dir / "code" / (Path(a.filename).stem + "_code_skeletons.zip")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    console.print(f"{len(names)} files written to {target}:")
    for n in names:
        console.print(f"  {n}")


@app.command()
def audit() -> None:
    """Scan the installed dependencies for known vulnerabilities (pip-audit)."""
    import subprocess
    import sys

    try:
        import pip_audit  # noqa: F401
    except ImportError:
        console.print("Installing pip-audit (one-time)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "pip-audit"], check=False)
    proc = subprocess.run([sys.executable, "-m", "pip_audit", "--progress-spinner", "off"], check=False, capture_output=True, text=True)
    console.print(proc.stdout or proc.stderr or "pip-audit produced no output")
    if proc.returncode == 0:
        console.print("[green]No known vulnerabilities in the installed dependencies.[/green]")
    else:
        console.print("[yellow]Review the findings above; bump the affected pins in pyproject.toml and reinstall.[/yellow]")


@app.command(name="guard-add")
def guard_add(terms: list[str] = typer.Argument(..., help="Customer / project / system names to add to the guardrail term list")) -> None:
    """Add names to the guardrail term list (data/config/guardrails.json)."""
    from atlas.guard.policy import add_terms

    added = add_terms(terms, settings)
    console.print(f"Added: {', '.join(added)}" if added else "Nothing to add - all names are already on the list.")


@app.command()
def ui(
    port: int = typer.Option(8080, "--port"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not open the browser automatically"),
) -> None:
    """Start the web app (NiceGUI) at http://localhost:<port>."""
    try:
        from atlas.ui.app import start
    except ImportError as error:
        console.print(f"[red]The web app needs nicegui: pip install nicegui[/red] ({error})")
        raise typer.Exit(1)
    init_db(settings)
    console.print(f"ABAP Beacon UI -> http://localhost:{port}   (Ctrl+C to stop)")
    start(port=port, open_browser=not no_browser)


@app.command("import-legacy")
def import_legacy_cmd(
    folder: str = typer.Argument(..., help="POC data/output folder containing objects.json / ai_descriptions.json"),
    system: str = typer.Option("DEV", "--system", "-s"),
) -> None:
    """Carry AI descriptions from the v0.6 prototype over to the database."""
    with session_scope(settings) as session:
        summary = import_legacy(session, Path(folder), system)
    console.print(f"AI descriptions found: {summary.ai_descriptions_found}, applied: {summary.applied}")
    if summary.unmatched:
        console.print(f"[yellow]unmatched:[/yellow] {', '.join(summary.unmatched)}")
    if summary.applied:
        with session_scope(settings) as session:
            rebuild_semantic_index(session, settings, system)
        console.print("Meaning index rebuilt with the imported descriptions.")


# --- helpers -------------------------------------------------------------------

def _print_by_type(by_type: dict) -> None:
    table = Table(box=box.SIMPLE_HEAD)
    table.add_column("type"); table.add_column("label"); table.add_column("count", justify="right")
    for key in sorted(by_type, key=lambda k: (-by_type[k], k)):
        table.add_row(key, get_type(key).label, str(by_type[key]))
    console.print(table)


def _print_job(job: Job) -> None:
    colour = {"done": "green", "failed": "red", "running": "cyan"}.get(job.status, "white")
    duration = (job.finished_at - job.started_at).total_seconds() if job.finished_at and job.started_at else 0
    console.print(f"[bold]Job #{job.id}[/bold] {job.kind}  [{colour}]{job.status}[/{colour}]  {duration:.1f}s  {job.source}")
    table = Table(box=box.SIMPLE, show_header=False)
    for step in job.steps:
        detail = {k: v for k, v in (step.detail or {}).items() if k not in ("by_type",)}
        table.add_row(step.name, step.status, str(detail)[:140])
    console.print(table)
    if job.error:
        console.print(Panel(job.error.strip().splitlines()[0], title="error", border_style="red"))


if __name__ == "__main__":
    app()

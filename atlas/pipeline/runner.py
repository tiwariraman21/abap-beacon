"""End-to-end pipeline as a recorded job.

    acquire -> ingest -> parse -> enrich_offline -> assess -> [ai_enrich] -> index_semantic

Each step writes its status and a detail dict to the database as it goes, so
the Jobs screen (and `atlas jobs`) can show progress and failures with the
exact step that broke. Later phases add steps (ai_enrich, rules, clones,
docs) to the same list without changing the mechanics.
"""

from __future__ import annotations

import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from atlas.config import Settings, get_settings
from atlas.db.models import Job, JobStep, SapObject, System
from atlas.db.session import session_scope
from atlas.assess.service import assess_objects
from atlas.enrich.service import enrich_offline
from atlas.parse.service import parse_objects
from atlas.ingest.abapgit import read_export
from atlas.ingest.service import ingest_report
from atlas.search import semantic
from atlas.search.engine import object_text

log = logging.getLogger("atlas.pipeline")


@dataclass
class PipelineOptions:
    source: str
    system: str = "DEV"
    root_package: str | None = None
    build_semantic: bool = True
    prefer_minilm: bool = True
    ai_enrich: bool = False          # call the AI provider for changed objects
    ai_limit: int | None = None
    kind: str = "full"
    progress: Callable[[str, str], None] | None = None  # (step, message)
    extra: dict = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StepRunner:
    """Context helper: marks a JobStep running/done/failed with timing."""

    def __init__(self, session: Session, job: Job, name: str, progress: Callable | None):
        self.session, self.job, self.name, self.progress = session, job, name, progress
        self.step = JobStep(job_id=job.id, name=name)
        session.add(self.step)
        session.flush()
        self.t0 = time.perf_counter()

    def __enter__(self) -> "StepRunner":
        if self.progress:
            self.progress(self.name, "started")
        return self

    def done(self, detail: dict | None = None, status: str = "done") -> None:
        self.step.status = status
        self.step.finished_at = _now()
        self.step.detail = {**(detail or {}), "seconds": round(time.perf_counter() - self.t0, 2)}
        self.session.flush()
        if self.progress:
            self.progress(self.name, status)

    def __exit__(self, exc_type, exc, _tb) -> bool:
        if exc is not None:
            self.step.status = "failed"
            self.step.finished_at = _now()
            self.step.detail = {"error": f"{exc_type.__name__}: {exc}", "seconds": round(time.perf_counter() - self.t0, 2)}
            self.session.flush()
            if self.progress:
                self.progress(self.name, "failed")
        return False


def run_pipeline(options: PipelineOptions, settings: Settings | None = None) -> Job:
    settings = settings or get_settings()
    with session_scope(settings) as session:
        job = Job(kind=options.kind, source=str(options.source))
        session.add(job)
        session.flush()
        job_id = job.id
        summary: dict = {}
        try:
            # 1. acquire ---------------------------------------------------
            with StepRunner(session, job, "acquire", options.progress) as step:
                report = read_export(options.source)
                step.done({"objects": len(report.objects), "files": report.file_count, "skipped": len(report.skipped_files)})

            # 2. ingest -----------------------------------------------------
            with StepRunner(session, job, "ingest", options.progress) as step:
                ingest = ingest_report(session, report, options.system, options.root_package)
                summary["ingest"] = ingest.as_dict()
                step.done(ingest.as_dict())

            changed = ingest.changed_object_ids

            # 3. structural parse (components, references, metrics) ----------
            with StepRunner(session, job, "parse", options.progress) as step:
                parsed = parse_objects(session, only_ids=changed)
                summary["parse"] = parsed.as_dict()
                step.done(parsed.as_dict(), status="done" if changed else "skipped")

            # 4. offline enrichment (changed objects only) ---------------------
            with StepRunner(session, job, "enrich_offline", options.progress) as step:
                enrich = enrich_offline(session, only_ids=changed)
                summary["enrich_offline"] = enrich.as_dict()
                step.done(enrich.as_dict(), status="done" if changed else "skipped")

            # 5. assessments ---------------------------------------------------
            with StepRunner(session, job, "assess", options.progress) as step:
                assessed = assess_objects(session, only_ids=changed)
                summary["assess"] = assessed.as_dict()
                step.done(assessed.as_dict(), status="done" if changed else "skipped")

            # 6. AI enrichment (optional) --------------------------------------
            with StepRunner(session, job, "ai_enrich", options.progress) as step:
                if not options.ai_enrich:
                    step.done({"reason": "disabled (run with --ai or `atlas enrich-ai`)"}, status="skipped")
                else:
                    from atlas.ai.enrich import enrich_ai
                    from atlas.ai.provider import get_provider

                    provider = get_provider(output_dir=settings.output_dir / "prompts")
                    ai = enrich_ai(session, provider, only_ids=changed if changed else None, limit=options.ai_limit)
                    summary["ai_enrich"] = ai.as_dict()
                    step.done(ai.as_dict(), status="done" if not ai.stopped_reason else "failed" if ai.failed and not ai.described else "done")

            # 7. semantic index --------------------------------------------------
            with StepRunner(session, job, "index_semantic", options.progress) as step:
                needs = bool(changed) or (options.ai_enrich and summary.get("ai_enrich", {}).get("described"))
                if not options.build_semantic:
                    step.done({"reason": "disabled"}, status="skipped")
                elif not needs and semantic.load_index(settings.index_dir) is not None:
                    step.done({"reason": "no changes"}, status="skipped")
                else:
                    result = rebuild_semantic_index(session, settings, options.system, options.prefer_minilm)
                    summary["index_semantic"] = result
                    step.done(result)

            job.status = "done"
        except Exception as error:  # noqa: BLE001 - recorded, then re-raised for the CLI
            job.status = "failed"
            job.error = f"{type(error).__name__}: {error}\n{traceback.format_exc()}"
            log.exception("pipeline failed")
        finally:
            job.finished_at = _now()
            job.summary = summary
            session.flush()

    with session_scope(settings) as session:
        return session.get(Job, job_id, options=[selectinload(Job.steps)])


def rebuild_semantic_index(session: Session, settings: Settings, system: str | None = None, prefer_minilm: bool = True) -> dict:
    query = select(SapObject).options(selectinload(SapObject.components))
    if system:
        query = query.join(System).where(System.sid == system.upper())
    docs = [(o.id, object_text(o)) for o in session.scalars(query)]
    if not docs:
        return {"count": 0, "backend": "none"}
    return semantic.build_index(docs, settings.index_dir, prefer_minilm=prefer_minilm)


def watch_folder(folder: Path, system: str, settings: Settings | None = None, interval: int = 10, once: bool = False) -> None:
    """Poll a folder; run the pipeline for every new or modified ZIP.

    Pure polling on purpose: works on any Windows share or OneDrive folder
    without extra dependencies. Processed files are tracked by (name, mtime).
    """
    seen: dict[str, float] = {}
    folder.mkdir(parents=True, exist_ok=True)
    log.info("watching %s for abapGit ZIPs (system %s)", folder, system)
    while True:
        for zip_path in sorted(folder.glob("*.zip")):
            mtime = zip_path.stat().st_mtime
            if seen.get(zip_path.name) == mtime:
                continue
            # wait for the copy to finish (size stable for one interval)
            size = zip_path.stat().st_size
            time.sleep(1)
            if zip_path.stat().st_size != size:
                continue
            seen[zip_path.name] = mtime
            log.info("new export detected: %s", zip_path.name)
            run_pipeline(PipelineOptions(source=str(zip_path), system=system), settings)
        if once:
            return
        time.sleep(interval)

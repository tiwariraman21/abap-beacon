"""Automated AI descriptions.

    select objects -> build batches -> redact -> (cache?) -> provider -> parse JSON -> apply

Every call is recorded in `ai_calls` with the input hash, so re-running never
sends the same content twice, and the Jobs screen can show tokens/cost. When
the provider reports a usage limit, the run stops cleanly and reports what is
left; the next run continues where it stopped.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from atlas.ai import prompts
from atlas.ai.provider import AIError, AILimitReached, AIResponse
from atlas.ai.redact import redact
from atlas.db.models import AICall, SapObject, System
from atlas.ingest.types import get_type

MAX_OBJECT_CHARS = 14000
MAX_BATCH_CHARS = 60000
HEAD_CHARS = 9000
TAIL_CHARS = 2500


@dataclass
class AIEnrichSummary:
    candidates: int = 0
    described: int = 0
    cached: int = 0
    calls: int = 0
    failed: int = 0
    remaining: int = 0
    redactions: int = 0
    input_chars: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    stopped_reason: str = ""
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "errors"}
        d["cost_usd"] = round(self.cost_usd, 4)
        if self.errors:
            d["errors"] = self.errors[:5]
        return d


def _trim(source: str) -> str:
    try:
        from atlas.guard.policy import get_guard

        max_lines = get_guard().policy.max_source_lines_to_ai
    except Exception:
        max_lines = 400
    lines = source.splitlines()
    if max_lines and len(lines) > max_lines:
        source = "\n".join(lines[:max_lines]) + f"\n\n*** [{len(lines) - max_lines} more lines withheld by the data-protection policy] ***"
    if len(source) <= MAX_OBJECT_CHARS:
        return source
    skipped = len(source) - HEAD_CHARS - TAIL_CHARS
    return f"{source[:HEAD_CHARS]}\n\n*** [{skipped:,} characters omitted from the middle - generated or repetitive code] ***\n\n{source[-TAIL_CHARS:]}"


def object_block(obj: SapObject, dependencies: list[str] | None = None) -> str:
    comps = [c for c in obj.components if c.kind in ("method", "function", "field", "entity") and c.short_text]
    comp_lines = "\n".join(f"  - {c.kind} {c.name}: {c.short_text}" for c in comps[:40])
    deps = f"\nDEPENDENCIES: {', '.join(dependencies[:25])}" if dependencies else ""
    tables = (obj.attributes or {}).get("tables", [])
    tables_line = f"\nTABLES: {', '.join(t.upper() for t in tables[:15])}" if tables else ""
    header = (
        f"\n{'=' * 72}\nOBJECT: {obj.name}\nTYPE: {get_type(obj.obj_type).label} ({obj.obj_type})\n"
        f"SAP SHORT TEXT: {obj.short_text or '-'}\nPACKAGE: {obj.package.name if obj.package else '-'}{tables_line}{deps}\n"
    )
    if comp_lines:
        header += f"SAP COMPONENT TEXTS:\n{comp_lines}\n"
    source = _trim(obj.source) if obj.source else "(no source - dictionary/configuration object; describe from metadata)"
    return f"{header}--- SOURCE ---\n{source}\n"


def make_batches(objects: list[SapObject], max_chars: int = MAX_BATCH_CHARS) -> list[list[SapObject]]:
    batches: list[list[SapObject]] = []
    current: list[SapObject] = []
    size = 0
    for obj in objects:
        est = min(len(obj.source), MAX_OBJECT_CHARS) + 800
        if current and size + est > max_chars:
            batches.append(current)
            current, size = [], 0
        current.append(obj)
        size += est
    if current:
        batches.append(current)
    return batches


def parse_reply(text: str) -> dict[str, dict]:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise AIError("Reply contained no JSON object.")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise AIError("Reply JSON is not an object keyed by object name.")
    return {k.upper(): v for k, v in data.items() if isinstance(v, dict)}


def apply_entry(obj: SapObject, entry: dict) -> None:
    description = (entry.get("description") or "").strip()
    if description:
        obj.description = description
        obj.described_by = "ai"
        obj.review_status = "draft"
    tags = [t for t in (entry.get("tags") or []) if isinstance(t, str) and t.strip()]
    merged = list(tags)
    for t in obj.tags or []:
        if t not in merged:
            merged.append(t)
    obj.tags = merged[:16]
    module = (entry.get("module") or "").strip().upper()
    if module and len(module) <= 5:
        obj.module = module
    attrs = dict(obj.attributes or {})
    for key in ("technical_summary", "business_process", "risks"):
        if entry.get(key):
            attrs[key] = entry[key]
    attrs["ai_prompt_version"] = prompts.PROMPT_VERSION
    obj.attributes = attrs


def candidates(session: Session, only_ids: list[int] | None = None, system_sid: str | None = None, force: bool = False, include_ddic: bool = False) -> list[SapObject]:
    q = select(SapObject).options(selectinload(SapObject.components), selectinload(SapObject.package), selectinload(SapObject.files)).order_by(SapObject.source_lines.desc())
    if only_ids is not None:
        if not only_ids:
            return []
        q = q.where(SapObject.id.in_(only_ids))
    if system_sid:
        q = q.join(System).where(System.sid == system_sid.upper())
    if not force:
        q = q.where(SapObject.described_by.notin_(["ai", "human"]))
    out = []
    for o in session.scalars(q):
        cat = get_type(o.obj_type).category
        if cat == "code" and o.source_lines > 0:
            out.append(o)
        elif include_ddic and cat in ("ddic", "config") and o.obj_type in ("TABL", "TTYP", "DTEL", "MSAG", "TRAN"):
            out.append(o)
    return out


def enrich_ai(session: Session, provider, only_ids: list[int] | None = None, system_sid: str | None = None, limit: int | None = None, force: bool = False, include_ddic: bool = False, progress=None) -> AIEnrichSummary:
    summary = AIEnrichSummary()
    objs = candidates(session, only_ids, system_sid, force, include_ddic)
    summary.candidates = len(objs)
    if limit:
        objs = objs[:limit]
    summary.remaining = len(objs)

    for batch in make_batches(objs, getattr(provider, "max_input_chars", MAX_BATCH_CHARS)):
        body = "".join(object_block(o) for o in batch)
        red = redact(body)
        prompt = prompts.DESCRIBE_INSTRUCTIONS + red.text
        input_hash = hashlib.sha1((prompts.PROMPT_VERSION + prompt).encode("utf-8", "replace")).hexdigest()
        summary.redactions += red.count
        summary.input_chars += len(prompt)

        cached = session.scalar(select(AICall).where(AICall.input_hash == input_hash, AICall.status == "ok", AICall.purpose == "describe").order_by(AICall.id.desc()))
        if cached and cached.response:
            response = AIResponse(text=cached.response, model=cached.model)
            summary.cached += 1
        else:
            call = AICall(purpose="describe", provider=provider.name, prompt_version=prompts.PROMPT_VERSION, input_hash=input_hash,
                          object_ids=[o.id for o in batch], input_chars=len(prompt), redactions=red.count)
            session.add(call)
            try:
                if progress:
                    progress(f"describing {len(batch)} object(s): {', '.join(o.name for o in batch[:3])}{'...' if len(batch) > 3 else ''}")
                response = provider.complete(prompt, prompts.DESCRIBE_SYSTEM)
                call.status, call.model, call.response = "ok", response.model, response.text
                call.input_tokens, call.output_tokens, call.cost_usd, call.output_chars = response.input_tokens, response.output_tokens, response.cost_usd, len(response.text)
                summary.calls += 1
                summary.input_tokens += response.input_tokens
                summary.output_tokens += response.output_tokens
                summary.cost_usd += response.cost_usd
            except AILimitReached as error:
                call.status, call.error = "limit", str(error)[:500]
                summary.stopped_reason = f"usage limit reached: {str(error)[:120]}"
                session.flush()
                break
            except AIError as error:
                call.status, call.error = "error", str(error)[:500]
                summary.failed += len(batch)
                summary.errors.append(str(error)[:200])
                session.flush()
                if provider.name == "manual":
                    summary.stopped_reason = str(error)
                    break
                continue
            session.flush()

        try:
            entries = parse_reply(response.text)
        except (AIError, json.JSONDecodeError) as error:
            summary.failed += len(batch)
            summary.errors.append(f"unparseable reply: {str(error)[:120]}")
            continue
        for obj in batch:
            entry = entries.get(obj.name.upper())
            if entry:
                apply_entry(obj, entry)
                summary.described += 1
                summary.remaining -= 1
            else:
                summary.failed += 1
        session.flush()

    return summary


def export_prompt_pack(session: Session, output_dir, only_ids=None, system_sid=None, force=False) -> list[str]:
    """Manual mode: one prompt file per batch, to paste into Claude."""
    from pathlib import Path

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    objs = candidates(session, only_ids, system_sid, force)
    paths = []
    for n, batch in enumerate(make_batches(objs), start=1):
        body = redact("".join(object_block(o) for o in batch)).text
        path = output_dir / f"prompt_pack_{n:03d}.txt"
        path.write_text(prompts.DESCRIBE_SYSTEM + "\n\n" + prompts.DESCRIBE_INSTRUCTIONS + body, encoding="utf-8")
        paths.append(str(path))
    return paths


def import_reply(session: Session, path, system_sid: str | None = None) -> tuple[int, list[str]]:
    from pathlib import Path

    entries = parse_reply(Path(path).read_text(encoding="utf-8"))
    q = select(SapObject)
    if system_sid:
        q = q.join(System).where(System.sid == system_sid.upper())
    by_name: dict[str, SapObject] = {}
    for o in session.scalars(q):
        if o.name not in by_name or get_type(o.obj_type).category == "code":
            by_name[o.name] = o
    applied, unmatched = 0, []
    for name, entry in entries.items():
        obj = by_name.get(name)
        if obj is None:
            unmatched.append(name)
            continue
        apply_entry(obj, entry)
        applied += 1
    return applied, unmatched

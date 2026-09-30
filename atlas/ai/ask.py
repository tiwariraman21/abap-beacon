"""Ask the codebase.

    question -> hybrid search (top objects) -> pick the most relevant methods /
    lines of each -> redact -> provider -> answer with [OBJECT:lines] citations

Excerpts are chosen per object: methods whose name or SAP short text matches
the question come first (their exact line ranges are known from the parser),
then the object header. Everything is numbered so the model can cite lines.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from atlas.ai import prompts
from atlas.ai.provider import AIError, AILimitReached
from atlas.ai.redact import redact
from atlas.db.models import AICall, SapObject
from atlas.ingest.types import get_type
from atlas.search.engine import SearchEngine, stem, tokenise

MAX_CONTEXT_CHARS = 45000
EXCERPT_LINES = 90


@dataclass
class Source:
    object_id: int
    name: str
    type: str
    short_text: str
    score: float
    excerpts: list[tuple[int, int]] = field(default_factory=list)   # (line_start, line_end)


@dataclass
class Answer:
    question: str
    answer: str
    sources: list[Source]
    provider: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    redactions: int = 0
    error: str = ""


def _numbered(lines: list[str], start: int, end: int) -> str:
    start = max(1, start)
    end = min(len(lines), end)
    return "\n".join(f"{i:>5} | {lines[i - 1]}" for i in range(start, end + 1))


def build_context(session: Session, engine: SearchEngine, question: str, k: int = 5) -> tuple[str, list[Source]]:
    results = engine.search(question, limit=k, mode="hybrid")
    q_stems = {stem(t) for t in tokenise(question)}
    blocks: list[str] = []
    sources: list[Source] = []
    budget = MAX_CONTEXT_CHARS

    for rank, r in enumerate(results, start=1):
        obj = session.get(SapObject, r.object.id, options=[selectinload(SapObject.files), selectinload(SapObject.components), selectinload(SapObject.references)])
        if obj is None:
            continue
        src = Source(obj.id, obj.name, get_type(obj.obj_type).label, obj.short_text, r.score)
        lines = obj.source.splitlines()
        tables = sorted({x.target_name for x in obj.references if x.target_type in ("table", "cds_or_table")})[:15]
        fms = sorted({x.target_name for x in obj.references if x.kind == "calls_function"})[:15]
        header = (
            f"\n### [{rank}] {obj.name}  ({src.type}; {obj.source_lines} lines)\n"
            f"Short text: {obj.short_text or '-'}\nDescription: {obj.description[:600]}\n"
            + (f"Tables: {', '.join(tables)}\n" if tables else "")
            + (f"Function modules: {', '.join(fms)}\n" if fms else "")
        )
        comps = [c for c in obj.components if c.kind in ("method", "function", "form") and c.line_start]
        if comps:
            header += "Components: " + "; ".join(f"{c.name} (L{c.line_start}-{c.line_end}){' - ' + c.short_text if c.short_text else ''}" for c in comps[:30]) + "\n"

        # choose excerpts: matching components first, then the top of the source
        chosen: list[tuple[int, int]] = []
        for c in comps:
            text_stems = {stem(t) for t in tokenise(f"{c.name} {c.short_text}")}
            if q_stems & text_stems and len(chosen) < 3:
                chosen.append((c.line_start, min(c.line_end, c.line_start + EXCERPT_LINES)))
        if not chosen and lines:
            chosen.append((1, min(len(lines), EXCERPT_LINES)))
        excerpt_text = ""
        for a, b in chosen:
            excerpt_text += f"\n--- {obj.name} lines {a}-{b} ---\n{_numbered(lines, a, b)}\n"
        src.excerpts = chosen
        block = header + excerpt_text
        if len(block) > budget:
            block = block[:budget]
        budget -= len(block)
        blocks.append(block)
        sources.append(src)
        if budget <= 2000:
            break
    return "".join(blocks), sources


def ask(session: Session, engine: SearchEngine, provider, question: str, k: int = 5) -> Answer:
    context, sources = build_context(session, engine, question, k)
    if not sources:
        return Answer(question, "Nothing in the repository matches this question. Try different business terms or check that the relevant package was ingested.", [], provider.name)
    red = redact(context)
    prompt = prompts.ASK_TEMPLATE.format(question=question, context=red.text)
    input_hash = hashlib.sha1((prompts.PROMPT_VERSION + prompt).encode("utf-8", "replace")).hexdigest()
    call = AICall(purpose="ask", provider=provider.name, prompt_version=prompts.PROMPT_VERSION, input_hash=input_hash, object_ids=[s.object_id for s in sources], input_chars=len(prompt), redactions=red.count)
    session.add(call)
    try:
        response = provider.complete(prompt, prompts.ASK_SYSTEM)
    except AILimitReached as error:
        call.status, call.error = "limit", str(error)[:500]
        return Answer(question, "", sources, provider.name, error=f"Usage limit reached: {str(error)[:200]}", redactions=red.count)
    except AIError as error:
        call.status, call.error = "error", str(error)[:500]
        return Answer(question, "", sources, provider.name, error=str(error)[:400], redactions=red.count)
    call.status, call.model, call.response = "ok", response.model, response.text
    call.input_tokens, call.output_tokens, call.cost_usd, call.output_chars = response.input_tokens, response.output_tokens, response.cost_usd, len(response.text)
    return Answer(question, response.text.strip(), sources, provider.name, response.model, response.input_tokens, response.output_tokens, response.cost_usd, red.count)


def citations(answer: str) -> list[tuple[str, str]]:
    """Extract [OBJECT] / [OBJECT:12-40] citations from the answer text."""
    out = []
    for m in re.finditer(r"\[([A-Z][A-Z0-9_/ ]{2,}?)(?::(\d+(?:-\d+)?))?\]", answer):
        out.append((m.group(1).strip(), m.group(2) or ""))
    return out

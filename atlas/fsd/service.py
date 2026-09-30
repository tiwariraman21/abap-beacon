"""FSD analysis end to end.

    read document -> requirements -> match against repository -> plan -> report

The result is stored (JSON + Markdown) so it appears in the UI and can be
re-opened; the Markdown report is the hand-over document for the ABAPer.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from atlas.db.models import Finding, FsdAnalysis, SapObject
from atlas.fsd.knowledge import INTENTS
from atlas.fsd.matcher import Matcher, ReqResult
from atlas.fsd.planner import build_plan
from atlas.fsd.reader import detect_module, document_entities, extract_requirements, read_document, summarize_document
from atlas.guard.detect import detect_sensitive_terms
from atlas.search.engine import SearchEngine

INTENT_BY_ID = {i.id: i for i in INTENTS}
SECURITY_RULES = {"SEC-001", "SEC-002", "SEC-007"}


def _cross_check_findings(session: Session, results: list[ReqResult]) -> None:
    """A requirement that asks for secure configuration is not covered by an object that
    hard-codes credentials/URLs - use the assessment findings to downgrade and explain."""
    ids = {r.best.object_id for r in results if r.best}
    if not ids:
        return
    rows = session.execute(
        select(Finding.object_id, Finding.rule_id, Finding.title, Finding.line).where(Finding.object_id.in_(list(ids)), Finding.status.in_(["open", "accepted"]))
    ).all()
    by_obj: dict[int, list[tuple[str, str, int]]] = {}
    for oid, rule, title, line in rows:
        by_obj.setdefault(oid, []).append((rule, title, line))
    for r in results:
        if not r.best or r.best.object_id not in by_obj:
            continue
        findings = by_obj[r.best.object_id]
        sec = [f for f in findings if f[0] in SECURITY_RULES]
        low = r.text.lower()
        if sec and any(k in low for k in ("secure", "credential", "secret", "configuration", "not in the program", "endpoint", "hard-coded", "hardcoded")):
            if r.status == "covered":
                r.status = "partial"
                r.effort_hours = round(r.effort_hours + 2.0, 1)
            r.change = f"Extend {r.best.name}: the object currently has {', '.join(f'{x[0]} ({x[1]}, line {x[2]})' for x in sec[:2])} - move endpoint/credentials to SM59 / secure store as the FSD requires. " + r.change
        elif findings and r.status in ("covered", "partial"):
            worst = sorted(findings, key=lambda f: ("S4-" not in f[0], f[0]))[:2]
            r.change += f" Note: {r.best.name} has open findings {', '.join(f'{x[0]}' for x in worst)} - address while touching it."


def _detect_new_names(blocks, title: str, session: Session) -> list[str]:
    try:
        from atlas.guard.policy import get_guard

        guard = get_guard(session=session)
        if not guard.policy.auto_detect_names:
            return []
        known = [t for t, _ in guard._terms]
    except Exception:
        known = []
    try:
        return detect_sensitive_terms(blocks, title, known)
    except Exception:
        return []


def analyse_file(session: Session, engine: SearchEngine, path: str | Path, store: bool = True) -> FsdAnalysis:
    path = Path(path)
    title, blocks = read_document(path)
    requirements = extract_requirements(blocks)
    module = detect_module(blocks)
    entities = document_entities(blocks)
    detected = _detect_new_names(blocks, title, session)      # customer / project / system names not yet on the guardrail list
    matcher = Matcher(session, engine, module)
    results, reuse, coverage, verdict = matcher.analyse(requirements)
    _cross_check_findings(session, results)
    if not module:
        from atlas.fsd.planner import _module
        module = _module(results, "")
        module = "" if module == "CA" else module
    plan = build_plan(title, results, reuse, verdict, engine, module, entities, detected)
    step_of: dict[str, str] = {}
    for st in plan.steps:
        for rid in st.requirements:
            step_of.setdefault(rid, f"{st.n}. {st.title}")
    for r in results:
        if r.status == "missing" and r.id in step_of:
            r.change = f"New development - see plan step {step_of[r.id]}."
        elif r.status == "partial" and r.id in step_of:
            r.change = r.change.split(" Building blocks:")[0] + f" See plan step {step_of[r.id]}."
    summary = summarize_document(blocks)

    stats = {
        "requirements": len(results),
        "covered": sum(1 for r in results if r.status == "covered"),
        "partial": sum(1 for r in results if r.status == "partial"),
        "missing": sum(1 for r in results if r.status == "missing"),
        "effort_hours": plan.effort_hours,
        "module": module,
    }
    payload = {
        "title": title, "summary": summary, "module": module, "coverage_pct": coverage, "verdict": verdict, "stats": stats,
        "requirements": [_req_dict(r) for r in results],
        "reuse": [asdict(c) for c in reuse],
        "plan": asdict(plan),
        "entities": entities,
        "detected_terms": detected,
        "repo_snapshot": _repo_snapshot(session),
    }
    from atlas.fsd.feasibility import assess as assess_feasibility

    payload["feasibility"] = assess_feasibility(payload)
    report = render_markdown(payload)
    row = FsdAnalysis(
        title=title, filename=path.name, module=module, coverage_pct=coverage, verdict=verdict,
        requirement_count=len(results), effort_hours=plan.effort_hours, result=payload, report_md=report,
        content_hash=hashlib.sha1(path.read_bytes()).hexdigest()[:20],
    )
    if store:
        session.add(row)
        session.flush()
    return row


def _req_dict(r: ReqResult) -> dict:
    d = asdict(r)
    d["intents"] = [{"id": i, "title": INTENT_BY_ID[i].title} for i in r.intents if i in INTENT_BY_ID]
    return d


# ------------------------------------------------------------------------------ report

VERDICT_TEXT = {
    "reuse": "REUSE - an existing object covers most of this FSD. Extend it for the partial/missing points instead of building new.",
    "extend": "EXTEND - existing objects cover part of this FSD. Plan the development as an extension plus the gaps listed below.",
    "build": "NEW DEVELOPMENT - nothing in the repository covers this FSD meaningfully. Follow the build plan below.",
}


def render_markdown(p: dict) -> str:
    s = p["stats"]
    out = [f"# FSD analysis - {p['title']}", ""]
    out.append(f"**Verdict: {VERDICT_TEXT[p['verdict']]}**")
    out.append("")
    out.append(f"- Weighted coverage by existing objects: **{p['coverage_pct']}%**")
    out.append(f"- Requirements: {s['requirements']} ({s['covered']} covered · {s['partial']} partial · {s['missing']} missing)")
    out.append(f"- Estimated remaining effort: **{s['effort_hours']} h** (design + unit tests included)")
    if p["module"]:
        out.append(f"- Module: {p['module']}")
    out.append("")
    if p["summary"]:
        out.append(f"> {p['summary'][:600]}")
        out.append("")

    if p["reuse"]:
        out.append("## Existing objects to reuse")
        out.append("")
        out.append("| Object | Type | Covers | Covered | Partial | Missing |")
        out.append("|---|---|---|---|---|---|")
        for c in p["reuse"]:
            out.append(f"| {c['name']} | {c['type']} | {c['coverage_pct']}% | {', '.join(c['covered']) or '-'} | {', '.join(c['partial']) or '-'} | {', '.join(c['missing']) or '-'} |")
        out.append("")
        for c in p["reuse"][:2]:
            if c["lines"] < 60:
                out.append(f"> {c['name']} has only {c['lines']} lines of code - its coverage is based on its description; verify before relying on it.")
        out.append("")

    def requirement_table() -> None:
        out.append("## FSD statements one by one")
        out.append("")
        out.append("Every sentence, bullet and table row of the specification that describes what the solution must do, in document order. "
                   "*Scope* rows summarise the detailed rows below them and carry no effort of their own.")
        out.append("")
        out.append("| # | Kind | Statement in the FSD | Existing code | Best match | Conf. | Addressed by | Effort h |")
        out.append("|---|---|---|---|---|---|---|---|")
        for r in p["requirements"]:
            b = r["best"]
            best = f"{b['name']}" + (f" ({', '.join(b['components'][:2])})" if b and b["components"] else "") if b else "-"
            conf = f"{b['confidence']:.2f}" if b else "-"
            out.append(f"| {r['id']} | {r['kind']} | {_md(r['text'])} | {r['status']} | {best} | {conf} | {_md(r['change'])} | {r['effort_hours']} |")
        out.append("")

    def development_plan() -> None:
        plan = p["plan"]
        out.append("## Development plan - what to build")
        out.append("")
        out.append(f"**Solution pattern:** {plan['pattern']}  ")
        out.append(f"_{plan['pattern_reason']}_")
        out.append("")
        if plan.get("alternatives"):
            out.append("### Before building - design alternatives to raise")
            for alt in plan["alternatives"]:
                out.append(f"- {alt}")
            out.append("")
        out.append("Each step is one piece of work for the ABAPer. The FSD statements it addresses are listed under it, and every "
                   "BAPI, table or class appears in the step where it is first needed - once.")
        out.append("")
        for st in plan["steps"]:
            out.append(f"### {st['n']}. {st['title']}")
            out.append(st["detail"])
            if st["reuse"]:
                out.append(f"- Already available: **{st['reuse']}** - reuse instead of rewriting.")
            if st["blocks"]:
                out.append("")
                out.append("Building blocks:")
                for b in st["blocks"]:
                    out.append(f"- `{b['name']}` ({b['kind']}): {b['purpose']}")
            addressed = st.get("addresses") or []
            if addressed:
                out.append("")
                out.append(f"Addresses {len(addressed)} FSD statement(s):")
                for a in addressed:
                    out.append(f"- {a['id']} ({a['kind']}): {_md(a['text'])}")
            out.append("")
        if plan.get("fsd_blocks"):
            out.append("### Building blocks the FSD names - and where they are used")
            out.append("")
            out.append("| Named in the FSD | Kind | Note | Used in |")
            out.append("|---|---|---|---|")
            for b in plan["fsd_blocks"]:
                out.append(f"| `{b['name']}` | {b['kind'].replace(' (named in the FSD)', '')} | {_md(b['purpose'])} | {b.get('used_in') or 'not needed'} |")
            out.append("")

    fz = p.get("feasibility") or {}
    if fz:
        out.append("## Feasibility and complexity")
        out.append("")
        out.append(f"**Feasibility: {fz['verdict']}** · complexity **{fz['complexity']['band']}** · FSD quality **{fz['quality']['score']}/100** · classification **{fz['rice']}** · estimate confidence **{fz['confidence']['band']}** ({fz['confidence']['pct']} %)")
        out.append("")
        for title, items in (("Blocking as written", fz.get("blockers")), ("Changes needed", fz.get("changes")), ("Risks to raise", fz.get("risks")), ("Not specified in the FSD", fz.get("missing_nfr"))):
            if items:
                out.append(f"**{title}**")
                for it in items:
                    out.append(f"- {_md(it)}")
                out.append("")
        out.append("**Complexity drivers:** " + "; ".join(fz["complexity"]["drivers"]))
        out.append("")
        covered = [k for k, v in fz["quality"]["topics"].items() if v]
        gaps = [k for k, v in fz["quality"]["topics"].items() if not v]
        out.append(f"**FSD quality:** covers {', '.join(covered) or 'nothing'}; missing {', '.join(gaps) or 'nothing'}; {fz['quality']['testable']} of {fz['quality']['detailed']} detailed statements are testable (shall/must/will or a named SAP object); {len(fz['quality']['vague'])} use open wording.")
        out.append("")
        if fz.get("questions"):
            out.append("**Clarification questions for the functional consultant**")
            for i, q in enumerate(fz["questions"], 1):
                out.append(f"{i}. {_md(q)}")
            out.append("")
    if p["verdict"] == "build":
        development_plan()          # nothing to reuse: the reader wants the work list first
        requirement_table()
    else:
        requirement_table()         # something exists: the per-statement status is the point
        development_plan()
    plan = p["plan"]
    out.append("## Objects")
    out.append("")
    out.append("| Action | Object | Type | Purpose | Uses (BAPIs / FMs / classes / tables) | Plan steps |")
    out.append("|---|---|---|---|---|---|")
    for o in plan["objects"]:
        uses = ", ".join(f"`{b}`" for b in (o.get("blocks") or [])) or "-"
        steps_ = ", ".join(str(n) for n in (o.get("steps") or [])) or "-"
        out.append(f"| {o['action']} | {o['name']} | {o['type']} | {_md(o['purpose'])} | {_md(uses)} | {steps_} |")
    out.append("")
    if plan["utilities"]:
        out.append("Reusable utilities already in the repository: " + ", ".join(f"{u['name']} ({u['purpose']})" for u in plan["utilities"]))
        out.append("")

    out.append("## Effort estimate")
    out.append("")
    for k, v in plan["effort_breakdown"].items():
        out.append(f"- {k}: {v} h")
    out.append(f"- **Total: {plan['effort_hours']} h**")
    out.append("")
    if plan["s4_notes"]:
        out.append("## S/4HANA and Clean Core notes")
        out.append("")
        for n in plan["s4_notes"]:
            out.append(f"- {n}")
        out.append("")
    if plan["test_scenarios"]:
        out.append("## Test scenarios to cover")
        out.append("")
        for t in plan["test_scenarios"]:
            out.append(f"- {t}")
        out.append("")
    if p.get("qa"):
        out.append("## Questions asked about this analysis (AI)")
        out.append("")
        for item in p["qa"]:
            out.append(f"**Q: {_md(item['q'])}**  ")
            out.append(item["a"])
            out.append("")
    if p.get("ai_notes"):
        out.append("## AI review")
        out.append("")
        out.append(p["ai_notes"])
        out.append("")
    if p.get("detected_terms"):
        out.append(f"_Guardrails: {len(p['detected_terms'])} name(s) detected in the document were masked in this report._")
        out.append("")
    out.append(f"_Generated by ABAP Beacon on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. Coverage and effort are estimates from deterministic matching; review before committing._")
    return "\n".join(out)


def _md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


# ------------------------------------------------------------------------------ AI refinement

AI_REVIEW_INSTRUCTIONS = """\
You are a senior SAP ABAP solution architect. Below is a functional specification broken into requirements, the
deterministic match against the customer's custom-code repository, and a draft development plan.
Review it and reply in Markdown (no JSON, no preamble) with these sections:

### Verdict check
Do you agree with the verdict and coverage? Say what the matcher may have over- or under-estimated and why.
### Reuse and required changes
For each partial/missing requirement, state concretely what has to change in the matched object (method-level if possible) or what to build.
### Build steps and standard APIs
Confirm or correct the recommended BAPIs/FMs/classes; add anything important that is missing (S/4HANA and Clean Core aware).
### Risks and open questions
Questions to raise with the functional consultant before development starts.

Be specific, cite objects by name, keep it under 700 words.
"""


def refine_with_ai(session: Session, analysis: FsdAnalysis, provider) -> str:
    from atlas.ai.provider import AIError, AILimitReached
    from atlas.ai.redact import redact
    from atlas.db.models import AICall

    p = analysis.result
    lines = [f"FSD: {p['title']}  (module {p['module'] or '?'})", f"Verdict: {p['verdict']} - weighted coverage {p['coverage_pct']}%", "", "REQUIREMENTS AND MATCHES:"]
    for r in p["requirements"]:
        b = r["best"]
        lines.append(f"{r['id']} [{r['kind']}] {r['text']}")
        lines.append(f"    status={r['status']} best={b['name'] if b else '-'} conf={b['confidence'] if b else 0} components={b['components'] if b else []} entities={b['entities'] if b else []}")
        lines.append(f"    plan: {r['change']}")
    lines.append("")
    lines.append("EXISTING OBJECTS (reuse candidates):")
    for c in p["reuse"]:
        obj = session.get(SapObject, c["object_id"])
        comps = "; ".join(f"{x.name}: {x.short_text}" for x in (obj.components if obj else [])[:25] if x.kind in ("method", "function"))
        lines.append(f"- {c['name']} ({c['type']}, {c['lines']} lines) covers {c['coverage_pct']}%: {c['description']}")
        if comps:
            lines.append(f"  methods: {comps}")
    lines.append("")
    lines.append(f"DRAFT PLAN: pattern = {p['plan']['pattern']}")
    for st in p["plan"]["steps"]:
        lines.append(f"{st['n']}. {st['title']}: {st['detail'][:200]} blocks={[b['name'] for b in st['blocks']]}")
    # names detected in this document are masked before the text leaves the machine, even if not on the list yet
    pre = display_guard(analysis).mask_for_ai("\n".join(lines)).text
    prompt = AI_REVIEW_INSTRUCTIONS + "\n" + redact(pre).text
    call = AICall(purpose="fsd_review", provider=provider.name, input_hash=hashlib.sha1(prompt.encode("utf-8", "replace")).hexdigest(), object_ids=[c["object_id"] for c in p["reuse"]], input_chars=len(prompt))
    session.add(call)
    try:
        response = provider.complete(prompt, "You review SAP ABAP development plans. Reply in Markdown only.")
    except AILimitReached as error:
        call.status, call.error = "limit", str(error)[:500]
        raise
    except AIError as error:
        call.status, call.error = "error", str(error)[:500]
        raise
    call.status, call.model, call.response = "ok", response.model, response.text
    call.input_tokens, call.output_tokens, call.cost_usd, call.output_chars = response.input_tokens, response.output_tokens, response.cost_usd, len(response.text)
    payload = dict(p)
    payload["ai_notes"] = response.text.strip()
    analysis.result = payload
    analysis.report_md = render_markdown(payload)
    analysis.ai_reviewed = True
    return response.text


ASK_INSTRUCTIONS = """You are a senior SAP S/4HANA solution architect helping an ABAP developer with one functional
specification. You are given ABAP Beacon's analysis of that specification: verdict, coverage, feasibility,
the development plan (steps with building blocks) and the objects to build. Answer the developer's
question from these facts. Be concrete: name the BAPIs, tables, classes and steps from the analysis;
if the analysis does not contain the information, say so and suggest what to clarify with the functional
consultant. Do not invent SAP objects that are not in the analysis or well known standard APIs.
Reply in Markdown, at most 250 words."""


def analysis_context(analysis: FsdAnalysis, session: Session) -> str:
    """Compact, masked description of an analysis for an LLM prompt."""
    p = analysis.result
    fz = p.get("feasibility") or {}
    lines = [f"FSD: {p['title']} (module {p.get('module') or '?'})", f"Verdict: {p['verdict']} - weighted coverage {p['coverage_pct']}% - effort {p['plan']['effort_hours']} h",
             f"Feasibility: {fz.get('verdict', '?')}; complexity {fz.get('complexity', {}).get('band', '?')}; FSD quality {fz.get('quality', {}).get('score', '?')}/100"]
    for c in fz.get("changes", []) + fz.get("blockers", []) + fz.get("risks", []):
        lines.append(f"- {c}")
    lines.append(f"Pattern: {p['plan']['pattern']}")
    for alt in p["plan"].get("alternatives", []):
        lines.append(f"Alternative: {alt}")
    lines.append("PLAN STEPS:")
    for st in p["plan"]["steps"]:
        lines.append(f"{st['n']}. {st['title']} - {st['detail'][:220]} | blocks: {', '.join(b['name'] for b in st['blocks'])} | addresses: {', '.join(st['requirements'])}")
    lines.append("OBJECTS:")
    for o in p["plan"]["objects"]:
        lines.append(f"- {o['action']} {o['name']} ({o['type']}): {o['purpose']} | uses: {', '.join(o.get('blocks') or [])}")
    lines.append("FSD STATEMENTS:")
    for r in p["requirements"]:
        b = r["best"]
        lines.append(f"{r['id']} [{r['kind']}/{r['status']}] {r['text']}" + (f" -> existing {b['name']}" if b else ""))
    if p.get("reuse"):
        lines.append("EXISTING OBJECTS: " + "; ".join(f"{c['name']} covers {c['coverage_pct']}%: {c['description'][:150]}" for c in p["reuse"]))
    return display_guard(analysis).mask_for_ai("\n".join(lines)).text


def ask_analysis(session: Session, analysis: FsdAnalysis, question: str, provider) -> str:
    """Answer a developer's question about one analysis with the configured AI provider.
    Everything sent out is masked (guardrails) and logged in the egress ledger."""
    from atlas.ai.provider import AIError, AILimitReached
    from atlas.ai.redact import redact
    from atlas.db.models import AICall

    question = (question or "").strip()
    if not question:
        raise ValueError("Please type a question.")
    prompt = ASK_INSTRUCTIONS + "\n\nANALYSIS:\n" + redact(analysis_context(analysis, session)).text + "\n\nQUESTION: " + redact(display_guard(analysis).mask_for_ai(question).text).text
    call = AICall(purpose="fsd_ask", provider=provider.name, input_hash=hashlib.sha1(prompt.encode("utf-8", "replace")).hexdigest(), object_ids=[c["object_id"] for c in analysis.result.get("reuse", [])], input_chars=len(prompt))
    session.add(call)
    try:
        response = provider.complete(prompt, "You are an SAP solution architect. Reply in Markdown only.")
    except AILimitReached as error:
        call.status, call.error = "limit", str(error)[:500]
        raise
    except AIError as error:
        call.status, call.error = "error", str(error)[:500]
        raise
    call.status, call.model, call.response = "ok", response.model, response.text
    call.input_tokens, call.output_tokens, call.cost_usd, call.output_chars = response.input_tokens, response.output_tokens, response.cost_usd, len(response.text)
    payload = dict(analysis.result)
    qa = list(payload.get("qa") or [])
    qa.append({"q": question, "a": response.text.strip(), "provider": provider.name, "model": response.model})
    payload["qa"] = qa[-10:]
    analysis.result = payload
    return response.text


def _repo_snapshot(session: Session) -> dict:
    """What the repository looked like when the analysis ran - so a later change to the code can flag it stale."""
    from atlas.db.models import Job

    job = session.scalars(select(Job).where(Job.status == "done").order_by(Job.id.desc()).limit(1)).first()
    objects = session.scalar(select(func.count(SapObject.id))) or 0
    return {"job_id": job.id if job else None, "as_of": (job.finished_at or job.started_at).isoformat() if job else None, "objects": int(objects)}


def display_guard(analysis: FsdAnalysis, settings=None):
    """Guard for showing this analysis: configured terms plus the names detected in its document."""
    from atlas.guard.policy import guard_with_terms

    return guard_with_terms(list((analysis.result or {}).get("detected_terms") or []), settings)


def list_analyses(session: Session, limit: int = 30) -> list[FsdAnalysis]:
    return list(session.scalars(select(FsdAnalysis).order_by(FsdAnalysis.id.desc()).limit(limit)))

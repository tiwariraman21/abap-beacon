"""Data Protection Sheet - one page a customer's security officer can read.

Generated from the *actual* configuration of the active workspace (AI mode, provider, guardrail policy,
egress counts), not from a template, so it is always true for the installation it describes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from atlas.db.models import AICall


def protection_facts(session: Session, settings, info) -> dict:
    from atlas.ai.provider import get_provider, provider_ready
    from atlas.guard.policy import get_guard

    guard = get_guard(settings, session)
    pol = guard.policy
    prov = get_provider()
    ready, note = provider_ready(prov)
    calls = session.scalar(select(func.count(AICall.id))) or 0
    chars = session.scalar(select(func.sum(AICall.input_chars))) or 0
    local = prov.name in ("ollama", "lmstudio", "disabled", "manual")
    return {
        "workspace": info.name, "kind": info.kind, "customer": info.customer or info.name, "ai_mode": "strict (AI switched off)" if info.strict else "normal (AI optional, masked)",
        "provider": prov.name, "provider_ready": ready, "provider_note": note, "local_only": local,
        "terms": len(guard._terms), "rules": {
            "Customer / partner / project names": True, "SAP system IDs, clients, transports": pol.mask_system_ids, "Business keys (customer, vendor, document, material numbers)": pol.mask_numbers,
            "SAP user names": pol.mask_users, "Organisations by suffix (Bank, Ltd, GmbH …)": pol.mask_org_suffix, "Company codes and plants": pol.mask_org_units,
            "Auto-detection of names in uploaded documents": pol.auto_detect_names, "Stable pseudonyms instead of flat placeholders": pol.pseudonyms,
            "Masking also in the web app and in generated reports": pol.mask_in_ui, "Credentials, hosts, e-mails, tokens, bank accounts (always)": True,
        }, "max_lines": pol.max_source_lines_to_ai, "calls": int(calls), "chars": int(chars),
        "data_dir": str(settings.data_dir), "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def protection_sheet_docx(f: dict, product: str = "ABAP Beacon") -> bytes:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.shared import Cm, Pt, RGBColor

    brand = RGBColor(0x0A, 0x6E, 0xD1)
    doc = Document()
    for st, size in (("Normal", 10), ("Heading 1", 15), ("Heading 2", 12)):
        doc.styles[st].font.size = Pt(size)
        if st != "Normal":
            doc.styles[st].font.color.rgb = brand

    def table(headers, rows, widths):
        t = doc.add_table(rows=1, cols=len(headers)); t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, h in enumerate(headers):
            c = t.rows[0].cells[i]; c.text = ""; r = c.paragraphs[0].add_run(h); r.bold = True; r.font.size = Pt(9)
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ""; cells[i].paragraphs[0].add_run(str(v)).font.size = Pt(9)
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
        doc.add_paragraph()

    p = doc.add_paragraph(); r = p.add_run(f"{product} - Data Protection Sheet"); r.font.size = Pt(20); r.bold = True; r.font.color.rgb = brand
    doc.add_paragraph(f"Workspace: {f['workspace']} ({f['kind']}) · Customer: {f['customer']} · Generated {f['generated']} from the live configuration")
    doc.add_heading("1. Where the data is", level=1)
    doc.add_paragraph(f"All source code, analyses and documents are stored locally in {f['data_dir']} (SQLite file and folders). {product} binds to 127.0.0.1 only, has no accounts, "
                      "no inbound network access and no telemetry. Nothing is stored or processed outside this folder.")
    doc.add_heading("2. AI usage in this workspace", level=1)
    doc.add_paragraph(f"AI mode: {f['ai_mode']}. Provider: {f['provider']}" + (" (runs locally - no data leaves the machine)" if f["local_only"] else "") + f". Status: {f['provider_note']}.")
    if f["ai_mode"].startswith("strict"):
        doc.add_paragraph("With AI switched off, every analysis, verdict, estimate, business case and document is produced by deterministic rules. No text is ever sent to any AI service.")
    else:
        doc.add_paragraph("AI is optional and used only for: object descriptions, questions about the code, review of and questions about an FSD analysis. Everything sent to the provider "
                          "passes the guardrails below first; the amount of source per object is capped; every call is written to the egress ledger with what was masked.")
    doc.add_paragraph(f"Egress ledger so far: {f['calls']} AI calls, {f['chars']:,} characters (all masked). Maximum source lines per object sent: {f['max_lines']}.")
    doc.add_heading("3. What is masked before anything leaves the machine", level=1)
    table(["Protection", "Active"], [[k, "yes" if v else "no"] for k, v in f["rules"].items()], [12, 3])
    doc.add_paragraph(f"Term list: {f['terms']} customer / partner / system names, maintained by the administrator; names found in uploaded documents are detected and masked automatically.")
    doc.add_heading("4. Provider options", level=1)
    doc.add_paragraph("Local model (Ollama / LM Studio): zero egress. Customer's own enterprise endpoint (Azure OpenAI, AWS Bedrock, Anthropic enterprise): data stays in the customer's tenant. "
                      "Vendor API under business terms: no training on submitted data per the vendor's published terms. Strict mode: no AI at all.")
    doc.add_heading("5. Controls", level=1)
    doc.add_paragraph("Guardrails page: term list, rules, preview of 'sent to AI' versus 'shown', egress log. AI provider page: provider selection and connection test. "
                      "Workspaces: one isolated data set per customer; code, analyses and searches never cross workspaces.")
    buf = BytesIO(); doc.save(buf)
    return buf.getvalue()


def compare_candidates(session: Session, result: dict) -> list[dict]:
    """Side-by-side facts for the reuse candidates of one analysis - the answer to 'which of the five
    ageing reports?' is a table of evidence, ranked deterministically, never an opinion."""
    from atlas.db.models import Finding, ObjectUsage, SapObject

    cands = result.get("reuse") or []
    if not cands:
        return []
    ids = [c["object_id"] for c in cands]
    objs = {o.id: o for o in session.scalars(select(SapObject).where(SapObject.id.in_(ids)))}
    findings = {oid: (n, h) for oid, n, h in session.execute(select(Finding.object_id, func.count(), func.sum(Finding.effort_hours)).where(Finding.object_id.in_(ids), Finding.status == "open").group_by(Finding.object_id)).all()}
    usage = {n: c for n, c in session.execute(select(ObjectUsage.name, func.sum(ObjectUsage.calls)).group_by(ObjectUsage.name)).all()}
    reqs = result.get("requirements") or []
    rows = []
    for c in cands:
        o = objs.get(c["object_id"])
        covered = [r["id"] for r in reqs if r.get("best") and r["best"]["object_id"] == c["object_id"] and r["status"] == "covered"]
        partial = [r["id"] for r in reqs if r.get("best") and r["best"]["object_id"] == c["object_id"] and r["status"] == "partial"]
        n_find, h_find = findings.get(c["object_id"], (0, 0.0))
        tier = (o.clean_core_tier if o is not None else "") or ""
        score = c["coverage_pct"] - 2.0 * n_find + (5.0 if usage.get(c["name"]) else 0.0)
        rows.append({"object_id": c["object_id"], "name": c["name"], "type": c["type"], "coverage": c["coverage_pct"], "covered": covered, "partial": partial,
                     "findings": int(n_find), "findings_h": round(float(h_find or 0), 1), "complexity": (o.complexity if o is not None else ""), "lines": (o.source_lines if o is not None else 0),
                     "calls": int(usage.get(c["name"]) or 0), "tier": tier or "-", "module": (o.module if o is not None else ""), "score": round(score, 1)})
    rows.sort(key=lambda r: -r["score"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows

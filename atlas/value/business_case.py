"""Business case engine - the numbers an executive signs off on.

Three sources of hard value, all from data Beacon already holds:

  conversion   remediation effort per object from the open findings, grouped into waves by module and
               severity, priced with a day rate and sized into a team and a timeline
  retirement   objects that can be decommissioned before the conversion (retirement engine) - their
               remediation, test and documentation effort is avoided
  reuse        every FSD analysis where existing code covered requirements: the hours of the "build
               from scratch" baseline that were not spent

The result feeds the Executive view and an executive business-case document (.docx) that a presales
team can take into a steering committee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from atlas.db.models import Finding, FsdAnalysis, SapObject
from atlas.value.cleancore import successor
from atlas.value.retirement import decide


@dataclass
class CaseParams:
    hourly_rate: float = 60.0          # blended ABAP rate
    hours_per_day: float = 8.0
    team_size: int = 4
    currency: str = "USD"
    test_factor: float = 0.35          # regression test on top of remediation
    pm_factor: float = 0.15            # management, cutover, documentation
    contingency: float = 0.15


def _money(v: float, cur: str) -> str:
    return f"{cur} {v:,.0f}"


def portfolio_value(session: Session, params: CaseParams) -> dict:
    """What the FSD analyses have saved so far: baseline build effort minus remaining effort."""
    rows = []
    for a in session.scalars(select(FsdAnalysis).order_by(FsdAnalysis.id.desc())):
        p = a.result or {}
        remaining = float(a.effort_hours or 0)
        # baseline = what the same statements would cost as a new build: remaining effort scaled by the uncovered share
        cov = float(a.coverage_pct or 0) / 100.0
        baseline = remaining / max(0.15, 1.0 - cov) if cov > 0 else remaining
        saved = max(0.0, baseline - remaining)
        fz = p.get("feasibility") or {}
        rows.append({"id": a.id, "title": a.title, "verdict": a.verdict, "coverage": a.coverage_pct, "remaining_h": round(remaining, 1), "baseline_h": round(baseline, 1),
                     "saved_h": round(saved, 1), "saved_money": round(saved * params.hourly_rate), "feasibility": fz.get("verdict", ""), "complexity": (fz.get("complexity") or {}).get("band", ""),
                     "created": a.created_at.strftime("%Y-%m-%d")})
    saved_h = round(sum(r["saved_h"] for r in rows), 1)
    return {"rows": rows, "saved_h": saved_h, "saved_money": round(saved_h * params.hourly_rate), "count": len(rows),
            "reuse_count": sum(1 for r in rows if r["verdict"] in ("reuse", "extend")), "remaining_h": round(sum(r["remaining_h"] for r in rows), 1)}


def conversion_case(session: Session, params: CaseParams) -> dict:
    ret = decide(session, params.hourly_rate)
    retire_names = {r["name"] for r in ret["rows"] if r["decision"] == "retire"}
    findings = list(session.execute(
        select(Finding.object_id, SapObject.name, SapObject.module, SapObject.obj_type, Finding.rule_id, Finding.category, Finding.severity, Finding.effort_hours, Finding.title)
        .join(SapObject, SapObject.id == Finding.object_id).where(Finding.status == "open")).all())
    by_obj: dict[str, dict] = {}
    for oid, name, module, otype, rule, cat, sev, hours, title in findings:
        d = by_obj.setdefault(name, {"id": oid, "name": name, "module": module or "unassigned", "type": otype, "hours": 0.0, "findings": 0, "high": 0, "s4": 0, "cc": 0, "sec": 0, "retire": name in retire_names})
        d["hours"] += float(hours or 0)
        d["findings"] += 1
        d["high"] += sev == "high"
        d["s4"] += cat == "s4hana"
        d["cc"] += cat == "cleancore"
        d["sec"] += cat == "security"
    objs = sorted(by_obj.values(), key=lambda d: -d["hours"])
    gross_h = sum(d["hours"] for d in objs)
    retired_h = sum(d["hours"] for d in objs if d["retire"])
    retired_avoided_h = ret["hours"]["retire"]
    net_h = gross_h - retired_h
    test_h = net_h * params.test_factor
    pm_h = (net_h + test_h) * params.pm_factor
    cont_h = (net_h + test_h + pm_h) * params.contingency
    total_h = net_h + test_h + pm_h + cont_h
    days = total_h / params.hours_per_day
    weeks = days / (params.team_size * 5) if params.team_size else 0
    # waves: 1 = security + high S/4 blockers, 2 = S/4HANA + Clean Core medium, 3 = quality / low
    waves = {1: [], 2: [], 3: []}
    for d in objs:
        if d["retire"]:
            continue
        w = 1 if d["sec"] or d["high"] else 2 if d["s4"] or d["cc"] else 3
        waves[w].append(d)
    wave_rows = [{"wave": w, "title": t, "objects": len(v), "hours": round(sum(x["hours"] for x in v), 1), "money": round(sum(x["hours"] for x in v) * params.hourly_rate)}
                 for w, t, v in ((1, "Security and blocking S/4HANA findings", waves[1]), (2, "S/4HANA simplification and Clean Core", waves[2]), (3, "Quality and maintainability", waves[3]))]
    # by module
    mods: dict[str, dict] = {}
    for d in objs:
        m = mods.setdefault(d["module"], {"module": d["module"], "objects": 0, "hours": 0.0, "retire": 0})
        m["objects"] += 1
        m["hours"] += 0 if d["retire"] else d["hours"]
        m["retire"] += d["retire"]
    # clean core advisor: which classic blocks appear how often and what replaces them
    from atlas.db.models import ObjectReference
    swaps: dict[str, dict] = {}
    for tgt, n in session.execute(select(ObjectReference.target_name, func.count(func.distinct(ObjectReference.object_id))).where(ObjectReference.is_custom.is_(False)).group_by(ObjectReference.target_name)).all():
        sc = successor(tgt)
        if sc:
            key = sc["successor"]
            e = swaps.setdefault(key, {"successor": key, "classic": set(), "objects": 0, "tier": sc["tier"], "note": sc["note"]})
            e["classic"].add(tgt)
            e["objects"] += n
    swap_rows = sorted(({**v, "classic": ", ".join(sorted(v["classic"]))} for v in swaps.values()), key=lambda v: -v["objects"])
    total_objects = session.scalar(select(func.count(SapObject.id))) or 0
    return {
        "params": params.__dict__.copy(), "objects_total": total_objects, "objects_with_findings": len(objs),
        "gross_h": round(gross_h, 1), "retired_objects": len(retire_names), "retired_h": round(retired_avoided_h, 1), "net_h": round(net_h, 1),
        "test_h": round(test_h, 1), "pm_h": round(pm_h, 1), "contingency_h": round(cont_h, 1), "total_h": round(total_h, 1),
        "total_money": round(total_h * params.hourly_rate), "gross_money": round((gross_h * (1 + params.test_factor) * (1 + params.pm_factor) * (1 + params.contingency)) * params.hourly_rate),
        "saving_money": ret["saving"],                    # same basis as the retirement table: remediation + test/documentation baseline per retired object
        "person_days": round(days, 1), "weeks": round(weeks, 1), "waves": wave_rows, "modules": sorted(mods.values(), key=lambda m: -m["hours"]),
        "top_objects": objs[:15], "swaps": swap_rows[:12], "retirement": {"totals": ret["totals"], "hours": ret["hours"], "have_usage": ret["have_usage"]},
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def business_case_docx(case: dict, portfolio: dict, product: str = "ABAP Beacon", customer: str = "the customer") -> bytes:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.shared import Pt, RGBColor

    cur = case["params"]["currency"]
    doc = Document()
    brand = RGBColor(0x0A, 0x6E, 0xD1)
    for st, size in (("Normal", 10), ("Heading 1", 15), ("Heading 2", 12)):
        doc.styles[st].font.size = Pt(size)
        if st != "Normal":
            doc.styles[st].font.color.rgb = brand

    def table(headers, rows, widths=None):
        from docx.shared import Cm
        t = doc.add_table(rows=1, cols=len(headers)); t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, h in enumerate(headers):
            c = t.rows[0].cells[i]; c.text = ""; r = c.paragraphs[0].add_run(h); r.bold = True; r.font.size = Pt(9)
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ""; cells[i].paragraphs[0].add_run(str(v)).font.size = Pt(9)
        if widths:
            for row in t.rows:
                for i, w in enumerate(widths):
                    row.cells[i].width = Cm(w)
        doc.add_paragraph()

    p = doc.add_paragraph(); r = p.add_run("S/4HANA Custom Code Business Case"); r.font.size = Pt(22); r.bold = True; r.font.color.rgb = brand
    doc.add_paragraph(f"Prepared for {customer} · generated by {product} on {case['generated']} · draft for the steering committee")
    doc.add_heading("1. Executive summary", level=1)
    doc.add_paragraph(f"The custom code base holds {case['objects_total']} objects; {case['objects_with_findings']} carry open S/4HANA, Clean Core, security or quality findings "
                      f"worth {case['gross_h']:,.0f} h of remediation. {case['retired_objects']} objects qualify for retirement, removing {case['retired_h']:,.0f} h. "
                      f"The remaining programme is {case['total_h']:,.0f} h including test, management and contingency - about {case['person_days']:,.0f} person-days, "
                      f"or {case['weeks']:,.0f} weeks with a team of {case['params']['team_size']} - at an estimated {_money(case['total_money'], cur)}.")
    doc.add_paragraph(f"Compared with remediating everything ({_money(case['gross_money'], cur)}), retiring unused code saves {_money(case['saving_money'], cur)}. "
                      f"Reuse of existing code found by the FSD analyses has already avoided {portfolio['saved_h']:,.0f} h ({_money(portfolio['saved_money'], cur)}) of new development across {portfolio['count']} specifications.")
    table(["Key figure", "Value"], [
        ["Custom objects", case["objects_total"]], ["Objects with open findings", case["objects_with_findings"]],
        ["Gross remediation effort", f"{case['gross_h']:,.0f} h"], ["Objects to retire", case["retired_objects"]], ["Effort avoided by retirement", f"{case['retired_h']:,.0f} h"],
        ["Net remediation", f"{case['net_h']:,.0f} h"], [f"Regression test ({int(case['params']['test_factor']*100)} %)", f"{case['test_h']:,.0f} h"],
        [f"Management, cutover, documentation ({int(case['params']['pm_factor']*100)} %)", f"{case['pm_h']:,.0f} h"], [f"Contingency ({int(case['params']['contingency']*100)} %)", f"{case['contingency_h']:,.0f} h"],
        ["Total programme", f"{case['total_h']:,.0f} h · {_money(case['total_money'], cur)}"], ["Timeline", f"{case['weeks']:,.0f} weeks with {case['params']['team_size']} developers"],
        ["Reuse savings from FSD analyses to date", f"{portfolio['saved_h']:,.0f} h · {_money(portfolio['saved_money'], cur)}"],
    ], [9, 7])
    doc.add_heading("2. Retirement of unused code", level=1)
    rt = case["retirement"]
    doc.add_paragraph(("Decisions are based on imported production usage statistics. " if rt["have_usage"] else "No production usage statistics were imported yet - decisions below are based on the dependency graph only; import ST03N / SCMON data to firm them up. ")
                      + f"Retire: {rt['totals']['retire']} objects ({rt['hours']['retire']:,.0f} h avoided). Review: {rt['totals']['review']} objects ({rt['hours']['review']:,.0f} h). Keep: {rt['totals']['keep']}.")
    doc.add_heading("3. Remediation waves", level=1)
    table(["Wave", "Scope", "Objects", "Hours", "Cost"], [[w["wave"], w["title"], w["objects"], f"{w['hours']:,.0f}", _money(w["money"], cur)] for w in case["waves"]], [1.5, 8, 2, 2, 3])
    doc.add_heading("4. Effort by module", level=1)
    table(["Module", "Objects with findings", "Hours (after retirement)", "Retired"], [[m["module"], m["objects"], f"{m['hours']:,.0f}", m["retire"]] for m in case["modules"]], [4, 4, 4, 3])
    doc.add_heading("5. Largest remediation items", level=1)
    table(["Object", "Module", "Findings", "Hours", "Decision"], [[o["name"], o["module"], o["findings"], f"{o['hours']:,.1f}", "retire" if o["retire"] else "remediate"] for o in case["top_objects"]], [5, 2.5, 2, 2, 3])
    if case["swaps"]:
        doc.add_heading("6. Clean Core advisor - classic building blocks and their released successors", level=1)
        table(["Classic", "Replace with", "Objects", "Tier"], [[s["classic"], s["successor"], s["objects"], s["tier"]] for s in case["swaps"]], [4, 8, 2, 1.5])
    doc.add_heading("7. Value already delivered by reuse", level=1)
    table(["Specification", "Verdict", "Coverage", "Remaining h", "Baseline h", "Saved h", "Saved"], [[r["title"][:60], r["verdict"], f"{r['coverage']} %", r["remaining_h"], r["baseline_h"], r["saved_h"], _money(r["saved_money"], cur)] for r in portfolio["rows"]], [6, 2, 1.8, 2, 2, 1.8, 2.5])
    doc.add_heading("Assumptions", level=1)
    doc.add_paragraph(f"Blended rate {_money(case['params']['hourly_rate'], cur)}/h, {case['params']['hours_per_day']} h per day, team of {case['params']['team_size']}. Effort per finding comes from the assessment rules; "
                      "retirement avoids remediation plus a size-based test and documentation baseline; reuse savings compare the remaining effort with a new-build baseline scaled by the uncovered share. "
                      "All figures are estimates to be validated with the delivery team.")
    buf = BytesIO(); doc.save(buf)
    return buf.getvalue()

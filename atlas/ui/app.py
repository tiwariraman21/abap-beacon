"""The ABAP Beacon web app (NiceGUI).

Start with `atlas ui` or `python -m atlas.ui.app`. Pages:
  /             Overview - KPIs, distributions, recent jobs
  /discover     Search in business language, filters, method-level hits
  /object/{id}  Object page - description, components, dependencies, findings, source, files
  /ask          Ask the codebase - grounded answers with line citations (Claude Code / API)
  /assessments  S/4HANA readiness, Clean Core tiers, security & quality findings
  /fsd          Upload a functional spec: coverage by existing objects, changes needed, build plan
  /dependencies Dependency map, table usage with S/4 status, impact analysis
  /inventory    Filterable table of every object, CSV export
  /jobs         Pipeline runs; upload an abapGit ZIP, run it, run AI enrichment
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from urllib.parse import quote

from nicegui import app, run, ui

from atlas.pipeline.runner import PipelineOptions, rebuild_semantic_index, run_pipeline
from atlas.ui import data
from atlas.ui.theme import badge, escape, frame, kpi, severity_badge, source_block, tags_html

log = logging.getLogger("atlas.ui")

EXAMPLES = [
    "report that ages vendor open items",
    "register a beneficiary with the bank",
    "check whether a sales order already exists",
    "reusable application log wrapper",
    "purchase order header CDS view",
    "structure for sales order item pricing",
]


def _system_label() -> str:
    sids = data.systems()
    return " / ".join(sids) if sids else ""


# ==================================================================================== Overview

@ui.page("/")
def overview_page() -> None:
    with frame("Overview", _system_label()):
        ov = data.overview()
        ui.html('<h1 class="page-title">Overview</h1><div class="page-sub">What is in the repository and how well it is understood.</div>')

        if ov.get("empty"):
            with ui.element("div").classes("tile w-full"):
                ui.label("Nothing ingested yet.").classes("section-title")
                ui.label("Go to Jobs & Pipeline, upload an abapGit ZIP and run the pipeline.").classes("meta")
                ui.button("Open Jobs & Pipeline", on_click=lambda: ui.navigate.to("/jobs")).props("unelevated")
            return

        with ui.row().classes("w-full gap-4 no-wrap flex-wrap"):
            kpi("Objects", f"{ov['total']:,}", f"{ov['code_objects']} code · {ov['total'] - ov['code_objects']} dictionary / config", "inventory_2")
            kpi("Lines of ABAP", f"{ov['lines']:,}", f"{ov['packages']} package(s) · {', '.join(ov['systems'])}", "code")
            kpi("AI-described", f"{ov['ai_share']}%", f"{ov['by_desc'].get('ai', 0)} AI · {ov['by_desc'].get('offline', 0)} rule-based", "auto_awesome")
            fo = ov["findings"]
            kpi("Open findings", fo["total"], f"{fo['by_severity'].get('high', 0)} high · {fo['effort_hours']:.0f} h to remediate", "fact_check")
            kpi("S/4HANA readiness", f"{fo['s4_status'].get('ok', 0)} ok", f"{fo['s4_status'].get('review', 0)} review · {fo['s4_status'].get('remediate', 0)} remediate", "upgrade")
            fresh = data.freshness()
            kpi("Code as of", fresh["as_of"].strftime("%d %b %Y") if fresh.get("as_of") else "-",
                (f"{fresh['as_of'].strftime('%H:%M')} · {fresh['objects']} objects · {fresh['source']}" if fresh.get("source") else "no ingestion yet - upload an abapGit export on Jobs & Pipeline"), "update")

        with ui.row().classes("w-full gap-4 no-wrap flex-wrap"):
            with ui.element("div").classes("tile flex-1 min-w-[22rem]"):
                ui.label("Objects by type").classes("section-title")
                types = list(ov["by_type"].items())[:12]
                ui.echart({
                    "grid": {"left": 150, "right": 20, "top": 10, "bottom": 20},
                    "xAxis": {"type": "value", "splitLine": {"lineStyle": {"color": "#E5E5E5"}}},
                    "yAxis": {"type": "category", "inverse": True, "data": [f"{data_label(k)}" for k, _ in types], "axisLabel": {"color": "#556B82"}},
                    "series": [{"type": "bar", "data": [v for _, v in types], "itemStyle": {"color": "#0070F2", "borderRadius": [0, 4, 4, 0]}, "barWidth": 14, "label": {"show": True, "position": "right", "color": "#1D2D3E"}}],
                    "tooltip": {},
                }).classes("w-full h-72")
            with ui.element("div").classes("tile flex-1 min-w-[18rem]"):
                ui.label("By SAP module").classes("section-title")
                ui.echart({
                    "tooltip": {"trigger": "item"},
                    "legend": {"bottom": 0, "textStyle": {"color": "#556B82"}},
                    "color": ["#0070F2", "#5B738B", "#256F3A", "#E76500", "#8B47D7", "#049F9A", "#AA0808", "#C87B00"],
                    "series": [{"type": "pie", "radius": ["45%", "70%"], "center": ["50%", "45%"], "data": [{"name": k, "value": v} for k, v in ov["by_module"].items()], "label": {"show": False}, "emphasis": {"label": {"show": True, "formatter": "{b}: {c}", "color": "#1D2D3E"}}}],
                }).classes("w-full h-72")
            with ui.element("div").classes("tile flex-1 min-w-[18rem]"):
                ui.label("Description coverage").classes("section-title")
                ui.echart({
                    "tooltip": {"trigger": "item"},
                    "legend": {"bottom": 0, "textStyle": {"color": "#556B82"}},
                    "color": ["#256F3A", "#5B738B", "#0070F2", "#E5E5E5"],
                    "series": [{"type": "pie", "radius": ["45%", "70%"], "center": ["50%", "45%"], "data": [{"name": {"ai": "AI (draft)", "offline": "Rule-based", "human": "Reviewed", "none": "None"}.get(k, k), "value": v} for k, v in ov["by_desc"].items()], "label": {"show": False}, "emphasis": {"label": {"show": True, "formatter": "{b}: {c}", "color": "#1D2D3E"}}}],
                }).classes("w-full h-72")

        with ui.row().classes("w-full gap-4 no-wrap flex-wrap"):
            with ui.element("div").classes("tile flex-1 min-w-[28rem]"):
                ui.label("Try a business question").classes("section-title")
                with ui.row().classes("gap-2 mt-2 flex-wrap"):
                    for ex in EXAMPLES:
                        ui.html(f'<span class="tag example">{escape(ex)}</span>').on("click", lambda e=ex: ui.navigate.to(f"/discover?q={quote(e)}"))
                ui.label("Largest objects").classes("section-title mt-4")
                for row in ov["largest"]:
                    with ui.row().classes("items-center gap-3 no-wrap w-full"):
                        ui.link(row["name"], f"/object/{row['id']}").classes("obj-name")
                        ui.label(row["type"]).classes("meta")
                        ui.label(row["short_text"]).classes("meta truncate flex-1")
                        ui.label(f"{row['lines']:,} lines").classes("meta")
            with ui.element("div").classes("tile flex-1 min-w-[24rem]"):
                ai = data.ai_usage()
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.icon("auto_awesome", size="sm").style("color: var(--sapBrand)")
                    ui.label("Where AI is used").classes("section-title")
                ui.label(f"{ai['total_calls']} AI calls so far · {ai['described']} objects described by AI · every call masked by the guardrails and logged").classes("meta")
                for u in ai["uses"]:
                    with ui.row().classes("items-start gap-2 no-wrap w-full mt-1"):
                        shown = f"{ai['described']} objects" if u["key"] == "describe" and ai["described"] else f"{u['calls']} calls"
                        ui.html(f'<span class="tag">{escape(shown)}</span>')
                        with ui.column().classes("gap-0 min-w-0"):
                            ui.label(u["title"]).classes("text-sm").style("font-weight:600")
                            ui.label(u["text"]).classes("meta")
                with ui.expansion("Deterministic by design (no AI, fully auditable)", icon="rule").classes("w-full mt-2").props("dense"):
                    for d in ai["deterministic"]:
                        ui.label("• " + d).classes("text-sm")
                ui.label("Recent pipeline runs").classes("section-title mt-4")
                if not ov["jobs"]:
                    ui.label("No runs yet.").classes("meta")
                for job in ov["jobs"]:
                    with ui.row().classes("items-center gap-3 no-wrap w-full mt-1"):
                        ui.html(badge(job["status"], job["status"]))
                        ui.label(f"#{job['id']} {job['kind']}").classes("mono")
                        ui.label(job["source"]).classes("meta truncate flex-1")
                        ui.label(f"{job['started']} · {job['seconds']}s").classes("meta")
                ui.button("Jobs & Pipeline", on_click=lambda: ui.navigate.to("/jobs")).props("flat").classes("mt-2")


def data_label(type_key: str) -> str:
    from atlas.ingest.types import get_type

    return get_type(type_key).label


# ==================================================================================== Discover

@ui.page("/discover")
def discover_page(q: str = "", mode: str = "hybrid", types: str = "", module: str = "") -> None:
    with frame("Discover", _system_label()):
        options = data.filter_options()
        ui.html('<h1 class="page-title">Discover</h1><div class="page-sub">Describe the business need. If it already exists, it is below - down to the method.</div>')

        state = {"q": q, "mode": mode, "types": [t for t in types.split(",") if t], "module": module or None}
        results_box = ui.column().classes("w-full gap-3")

        with ui.element("div").classes("tile w-full"):
            with ui.row().classes("w-full items-center gap-3 no-wrap"):
                query_input = ui.input(value=q, placeholder="e.g. report that ages vendor open items").props("outlined dense clearable autofocus").classes("flex-1")
                mode_toggle = ui.toggle({"hybrid": "Hybrid", "keyword": "Keyword", "semantic": "Meaning"}, value=mode).props("dense unelevated toggle-color=primary")
                ui.button("Search", icon="search", on_click=lambda: do_search()).props("unelevated")
            with ui.row().classes("w-full items-center gap-3 no-wrap flex-wrap mt-2"):
                type_select = ui.select(options["types"], multiple=True, value=state["types"], label="Object type").props("outlined dense use-chips clearable").classes("w-[26rem]")
                module_select = ui.select(["", *options["modules"]], value=module, label="Module").props("outlined dense").classes("w-40")
                ui.space()
                with ui.row().classes("gap-1 flex-wrap"):
                    for ex in EXAMPLES[:4]:
                        ui.html(f'<span class="tag example">{escape(ex)}</span>').on("click", lambda e=ex: (query_input.set_value(e), do_search()))
            query_input.on("keydown.enter", lambda: do_search())

        def do_search() -> None:
            query = (query_input.value or "").strip()
            results_box.clear()
            if not query:
                with results_box:
                    ui.label("Type a requirement above, or pick an example.").classes("meta")
                return
            found = data.search(query, mode=mode_toggle.value, limit=20, types=type_select.value or None, module=module_select.value or None)
            with results_box:
                if found.get("empty"):
                    ui.label("Nothing ingested yet.").classes("meta")
                    return
                ui.label(f"{len(found['results'])} result(s) · mode {mode_toggle.value} · meaning backend {found['backend']}").classes("meta")
                if not found["results"]:
                    ui.label("No match. Try describing what the code does in business terms, or clear the filters.").classes("meta")
                for r in found["results"]:
                    render_result(r)

        def render_result(r: dict) -> None:
            with ui.element("div").classes("result w-full" + (" weak" if r["label"] == "weak" else "")):
                with ui.row().classes("items-center gap-3 no-wrap w-full"):
                    ui.link(r["name"], f"/object/{r['id']}").classes("obj-name")
                    meta = f"{r['type']}" + (f" · {r['module']}" if r["module"] else "") + (f" · {r['lines']:,} lines" if r["lines"] else "")
                    ui.label(meta).classes("meta")
                    ui.space()
                    ui.html(badge(r["described_by"], r["described_by"]))
                    ui.html(badge(f"{r['score']:.0f} · {r['label']}", r["label"]))
                if r["short_text"]:
                    ui.label(r["short_text"]).classes("meta italic")
                desc = r["description"]
                ui.label(desc[:520] + ("..." if len(desc) > 520 else "")).classes("desc")
                for h in r["hits"]:
                    ui.html(f'<div class="hit">↳ {escape(h["kind"])} <b>{escape(h["name"])}</b> {escape(h["short_text"])}</div>')
                with ui.row().classes("items-center gap-2 mt-1 w-full no-wrap"):
                    ui.html(tags_html(r["tags"], limit=8))
                    ui.space()
                    if r["matched"]:
                        ui.label("matched: " + ", ".join(r["matched"][:10])).classes("meta")

        if q:
            do_search()
        else:
            with results_box:
                ui.label("Type a requirement above, or pick an example.").classes("meta")


# ==================================================================================== Object page

@ui.page("/object/{object_id}")
def object_page(object_id: int, line: int = 0) -> None:
    with frame("Discover", _system_label()):
        o = data.get_object(object_id)
        if o is None:
            ui.label("Object not found.").classes("meta")
            return

        # --- object header (Fiori object page header)
        with ui.element("div").classes("tile w-full"):
            with ui.row().classes("items-center gap-3 no-wrap w-full"):
                ui.html(f'<span class="obj-name" style="font-size:1.4rem">{escape(o["name"])}</span>')
                ui.html(f'<span class="tag">{escape(o["type"])}</span>')
                if o["module"]:
                    ui.html(f'<span class="tag">{escape(o["module"])}</span>')
                ui.space()
                ui.html(badge(f"{o['described_by']} · {o['review_status']}", o["described_by"]))
            if o["short_text"]:
                ui.label(o["short_text"]).classes("page-sub italic")
            with ui.row().classes("gap-8 mt-3 flex-wrap"):
                for label, value in (
                    ("System", o["system"]), ("Package", f"{o['package']} {('- ' + o['package_text']) if o['package_text'] else ''}"),
                    ("Complexity", o["complexity"] or "-"), ("Source", f"{o['lines']:,} lines · {o['chars']:,} chars"),
                    ("Files", str(len(o["files"]))), ("Components", str(len([c for c in o["components"] if c["kind"] != "parameter"]))),
                    ("Updated", o["updated_at"]),
                ):
                    with ui.column().classes("gap-0"):
                        ui.label(label).classes("kpi-label")
                        ui.label(value).classes("text-sm")
            ui.html(tags_html(o["tags"], limit=16)).classes("mt-2")

        with ui.tabs().classes("w-full").props("align=left active-color=primary indicator-color=primary") as tabs:
            deps = data.object_dependencies(o["id"])
            found = data.object_findings(o["id"])
            open_findings = [f for f in found if f["status"] in ("open", "accepted")]
            t_desc = ui.tab("Description")
            t_comp = ui.tab(f"Components ({len([c for c in o['components'] if c['kind'] != 'parameter'])})")
            t_deps = ui.tab(f"Dependencies ({len(deps['tables']) + len(deps['outgoing'])} / {len(deps['incoming'])})")
            t_find = ui.tab(f"Findings ({len(open_findings)})")
            t_src = ui.tab("Source")
            t_files = ui.tab(f"Files ({len(o['files'])})")
            t_attr = ui.tab("Attributes")

        finding_lines = {f["line"] for f in open_findings if f["line"]}
        with ui.tab_panels(tabs, value=t_src if line else t_desc).classes("w-full bg-transparent"):
            with ui.tab_panel(t_desc).classes("p-0"):
                with ui.element("div").classes("tile w-full"):
                    ui.label(o["description"] or "No description yet.").classes("desc")
                    if o["tables"]:
                        ui.label("Tables accessed").classes("section-title mt-3")
                        ui.html("".join(f'<span class="tag neutral mono">{escape(t.upper())}</span>' for t in o["tables"]))
                    related = data.related_objects(o["name"], o["id"])
                    if related:
                        ui.label("Related by name").classes("section-title mt-3")
                        for r in related:
                            with ui.row().classes("items-center gap-3 no-wrap"):
                                ui.link(r["name"], f"/object/{r['id']}").classes("obj-name")
                                ui.label(r["type"]).classes("meta")
                                ui.label(r["short_text"]).classes("meta")
                    attrs = o["attributes"] or {}
                    if attrs.get("technical_summary") or attrs.get("business_process") or attrs.get("risks"):
                        ui.label("AI technical summary").classes("section-title mt-3")
                        if attrs.get("business_process"):
                            ui.label(f"Business process: {attrs['business_process']}").classes("text-sm")
                        if attrs.get("technical_summary"):
                            ui.label(attrs["technical_summary"]).classes("text-sm")
                        if attrs.get("risks"):
                            ui.label("Risks noted by AI").classes("kpi-label mt-2")
                            for r in attrs["risks"]:
                                ui.label(f"• {r}").classes("text-sm")
                    with ui.row().classes("gap-6 mt-4 flex-wrap"):
                        for label, value in (("Clean Core tier", o.get("clean_core_tier") or "-"), ("S/4HANA status", o.get("s4_status") or "-"), ("Open findings", str(len(open_findings)))):
                            with ui.column().classes("gap-0"):
                                ui.label(label).classes("kpi-label")
                                ui.label(value).classes("text-sm")
                    if attrs.get("clean_core_reason"):
                        ui.label(attrs["clean_core_reason"]).classes("meta")

            with ui.tab_panel(t_comp).classes("p-0"):
                comps = [c for c in o["components"] if c["kind"] != "parameter"]
                with ui.element("div").classes("tile w-full"):
                    if not comps:
                        ui.label("No components recorded for this object type.").classes("meta")
                    else:
                        rows = []
                        for c in comps:
                            sig = c["signature"] or {}
                            extra = ""
                            if c["kind"] == "function":
                                extra = f"IMPORTING {len(sig.get('importing', []))} · EXPORTING {len(sig.get('exporting', []))} · TABLES {len(sig.get('tables', []))} · EXCEPTIONS {len(sig.get('exceptions', []))}"
                            elif c["kind"] == "field":
                                extra = " ".join(x for x in [sig.get("data_element", ""), f"{sig.get('datatype', '')} {sig.get('length', '')}".strip(), "KEY" if sig.get("key") else ""] if x)
                            rows.append(dict(kind=c["kind"], name=c["name"], short_text=c["short_text"], extra=extra))
                        ui.table(
                            columns=[
                                {"name": "kind", "label": "Kind", "field": "kind", "align": "left", "sortable": True},
                                {"name": "name", "label": "Name", "field": "name", "align": "left", "sortable": True, "classes": "mono"},
                                {"name": "short_text", "label": "SAP short text", "field": "short_text", "align": "left"},
                                {"name": "extra", "label": "Details", "field": "extra", "align": "left", "classes": "meta"},
                            ],
                            rows=rows, row_key="name", pagination=25,
                        ).classes("w-full").props("flat dense")


            with ui.tab_panel(t_deps).classes("p-0"):
                with ui.row().classes("w-full gap-4 no-wrap flex-wrap items-start"):
                    with ui.element("div").classes("tile flex-1 min-w-[24rem]"):
                        ui.label("Tables and views").classes("section-title")
                        if not deps["tables"]:
                            ui.label("No table access found in source.").classes("meta")
                        for e in deps["tables"]:
                            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                                ui.html(f'<span class="tag neutral">{escape(e["kind"])}</span>')
                                if e["resolved"]:
                                    ui.link(e["name"], f"/object/{e['resolved']['id']}").classes("obj-name")
                                else:
                                    ui.label(e["name"]).classes("obj-name")
                                ui.label(e["std_text"] or ("custom" if e["is_custom"] else "")).classes("meta")
                                if e["s4_status"] and e["s4_status"] != "ok":
                                    ui.html(severity_badge({"replaced": "high", "compat": "medium", "changed": "low"}.get(e["s4_status"], "info")).replace(f'>{e["s4_status"]}<', f'>S/4: {e["s4_status"]}<'))
                                ui.space()
                                ui.label(", ".join(e["components"])[:60]).classes("meta")
                        ui.label("Uses").classes("section-title mt-4")
                        if not deps["outgoing"]:
                            ui.label("No calls found in source.").classes("meta")
                        for e in deps["outgoing"]:
                            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                                ui.html(f'<span class="tag neutral">{escape(e["kind"])}</span>')
                                if e["resolved"]:
                                    ui.link(e["name"], f"/object/{e['resolved']['id']}").classes("obj-name")
                                else:
                                    ui.label(e["name"]).classes("obj-name" if e["is_custom"] else "mono text-sm")
                                ui.label(e["target_type"]).classes("meta")
                                ui.space()
                                ui.label(", ".join(e["components"])[:60]).classes("meta")
                    with ui.element("div").classes("tile flex-1 min-w-[24rem]"):
                        ui.label("Used by").classes("section-title")
                        if not deps["incoming"]:
                            ui.label("No custom object references this one (within the ingested packages).").classes("meta")
                        for e in deps["incoming"]:
                            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                                ui.link(e["name"], f"/object/{e['id']}").classes("obj-name")
                                ui.label(e["type"]).classes("meta")
                                ui.html(f'<span class="tag neutral">{escape(e["kind"])}</span>')
                                ui.space()
                                ui.label(e["component"]).classes("meta")
                        ui.button("Impact analysis", icon="account_tree", on_click=lambda: ui.navigate.to(f"/dependencies?impact={quote(o['name'])}")).props("flat").classes("mt-3")

            with ui.tab_panel(t_find).classes("p-0"):
                with ui.element("div").classes("tile w-full"):
                    if not found:
                        ui.label("No findings - or the assessment has not run yet (Jobs → run pipeline, or `atlas assess`).").classes("meta")
                    for f in found:
                        with ui.element("div").classes("w-full py-2").style("border-bottom:1px solid var(--sapShellBorder)"):
                            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                                ui.html(severity_badge(f["severity"]))
                                ui.label(f["rule_id"]).classes("mono text-sm")
                                ui.label(f["title"]).classes("section-title")
                                ui.space()
                                if f["line"]:
                                    ui.link(f"line {f['line']}", f"/object/{o['id']}?line={f['line']}").classes("cite")
                                if f["status"] != "open":
                                    ui.html(badge(f["status"], "offline"))
                            ui.label(f["message"]).classes("text-sm")
                            if f["snippet"]:
                                ui.html(f'<code class="mono text-xs">{escape(f["snippet"])}</code>')
                            ui.label(f"Fix: {f['remediation']}").classes("meta")

            with ui.tab_panel(t_src).classes("p-0"):
                sources = [f for f in o["files"] if f["kind"] == "source"]
                with ui.element("div").classes("tile w-full"):
                    if not sources:
                        ui.label("This object type has no source code; see Attributes and Components.").classes("meta")
                    else:
                        with ui.row().classes("items-center gap-3 w-full no-wrap"):
                            file_select = ui.select({i: f"{f['path']}  ({f['lines']} lines)" for i, f in enumerate(sources)}, value=0).props("outlined dense").classes("flex-1")
                            ui.button("Download", icon="download", on_click=lambda: ui.download.content(sources[file_select.value]["content"].encode("utf-8"), Path(sources[file_select.value]["path"]).name)).props("flat")
                        # findings/citations refer to the concatenated source; show the whole object in one view when a line is requested
                        if line or len(sources) > 1:
                            full = "\n".join(f["content"] for f in sources)
                            start = max(1, line - 12) if line else 1
                            code_box = ui.html(source_block(full, max_lines=400 if not line else 120, highlight=finding_lines | ({line} if line else set()), start=start)).classes("w-full")
                            ui.label("Showing the object's files concatenated (line numbers as used by findings and citations). Pick a file above to view it alone.").classes("meta")
                            file_select.on_value_change(lambda e: code_box.set_content(source_block(sources[e.value]["content"])))
                        else:
                            code_box = ui.html(source_block(sources[0]["content"], highlight=finding_lines)).classes("w-full")
                            file_select.on_value_change(lambda e: code_box.set_content(source_block(sources[e.value]["content"], highlight=finding_lines)))

            with ui.tab_panel(t_files).classes("p-0"):
                with ui.element("div").classes("tile w-full"):
                    ui.table(
                        columns=[
                            {"name": "path", "label": "Path", "field": "path", "align": "left", "classes": "mono"},
                            {"name": "kind", "label": "Kind", "field": "kind", "align": "left"},
                            {"name": "sub_file", "label": "Sub-file", "field": "sub_file", "align": "left"},
                            {"name": "lines", "label": "Lines", "field": "lines", "align": "right"},
                        ],
                        rows=[{k: v for k, v in f.items() if k != "content"} for f in o["files"]], row_key="path",
                    ).classes("w-full").props("flat dense")

            with ui.tab_panel(t_attr).classes("p-0"):
                with ui.element("div").classes("tile w-full"):
                    if not o["attributes"]:
                        ui.label("No attributes.").classes("meta")
                    for k, v in o["attributes"].items():
                        with ui.row().classes("gap-4 no-wrap"):
                            ui.label(k).classes("kpi-label w-40")
                            ui.label(", ".join(v) if isinstance(v, list) else str(v)).classes("text-sm mono")


# ==================================================================================== Ask

ASK_EXAMPLES = [
    "How does the sales order OData service check whether an order already exists?",
    "Which objects read vendor open items and what must change for S/4HANA?",
    "Where are bank API credentials handled and is anything hard-coded?",
    "Explain the application log wrapper class and how to use it.",
]


@ui.page("/ask")
def ask_page(q: str = "") -> None:
    with frame("Ask the codebase", _system_label()):
        ui.html('<h1 class="page-title">Ask the codebase</h1><div class="page-sub">Questions in plain language; answers grounded in retrieved source with line citations. Nothing but redacted excerpts of the relevant objects leaves this machine.</div>')
        if not data.ai_enabled():
            with ui.element("div").classes("tile w-full").style("border-left:6px solid #B35A00;background:#FFF8EE"):
                ui.label("AI is switched off for this workspace (strict mode)").classes("section-title")
                ui.label("No text is sent to any AI provider. Every analysis, number and document still works. Change the mode on the Workspaces page if this customer allows AI.").classes("text-sm")
        status = data.ai_status()
        with ui.element("div").classes("tile w-full"):
            with ui.row().classes("items-center gap-3 no-wrap w-full"):
                question = ui.input(value=q, placeholder="e.g. how does the sales order service validate the Salesforce reference?").props("outlined dense clearable").classes("flex-1")
                k = ui.select({3: "3 objects", 5: "5 objects", 8: "8 objects"}, value=5).props("outlined dense").classes("w-32")
                go = ui.button("Ask", icon="forum").props("unelevated")
            with ui.row().classes("gap-2 flex-wrap mt-2"):
                for ex in ASK_EXAMPLES:
                    ui.button(ex, on_click=lambda ex=ex: (question.set_value(ex), asyncio.ensure_future(run_ask()))).props("flat dense no-caps").classes("text-xs")
            prov = status["selected"]
            ok = status["claude-code"] or status["anthropic"]
            ui.label(f"Provider: {prov}" + ("" if ok else " - no Claude Code / API key found; answers cannot be generated (retrieval still works)") + f" · {status['calls']} AI calls so far · ${status['cost_usd']}").classes("meta mt-2")

        out = ui.column().classes("w-full gap-4")

        async def run_ask() -> None:
            text = (question.value or "").strip()
            if not text:
                return
            out.clear()
            with out:
                ui.label("Retrieving relevant objects and asking Claude...").classes("meta")
                bar = ui.linear_progress(show_value=False).props("indeterminate").classes("w-full")
            result = await run.io_bound(data.ask, text, k.value)
            out.clear()
            with out:
                if result.get("error"):
                    with ui.element("div").classes("tile w-full"):
                        ui.label(result["error"]).classes("text-negative")
                        ui.label("Retrieval still worked - the objects below are the best matches. Install Claude Code (npm install -g @anthropic-ai/claude-code, then `claude` once to log in) or set ANTHROPIC_API_KEY to get answers.").classes("meta")
                else:
                    with ui.element("div").classes("tile w-full"):
                        ui.label("Answer").classes("section-title")
                        ui.html(_render_answer(result["answer"], result["sources"])).classes("answer w-full")
                        ui.label(f"{result['provider']} {result['model']} · {result['tokens']} tokens · redactions {result['redactions']}").classes("meta mt-2")
                with ui.element("div").classes("tile w-full"):
                    ui.label("Context used (retrieved objects)").classes("section-title")
                    for src in result["sources"]:
                        with ui.row().classes("items-center gap-3 no-wrap w-full"):
                            ui.link(src["name"], f"/object/{src['id']}").classes("obj-name")
                            ui.label(src["type"]).classes("meta")
                            ui.label(src["short_text"]).classes("meta")
                            ui.space()
                            for a, b in src["excerpts"]:
                                ui.link(f"L{a}-{b}", f"/object/{src['id']}?line={a}").classes("cite")

        go.on_click(run_ask)
        question.on("keydown.enter", run_ask)
        if q:
            ui.timer(0.1, run_ask, once=True)


def _render_answer(text: str, sources: list[dict]) -> str:
    """Minimal markdown-ish rendering + clickable [OBJECT:lines] citations."""
    import re

    by_name = {s["name"]: s["id"] for s in sources}
    html = escape(text)

    def cite(m):
        name, lines = m.group(1).strip(), m.group(2) or ""
        oid = by_name.get(name) or data.object_id_by_name(name)
        label = f"{name}{':' + lines if lines else ''}"
        if oid is None:
            return f"[{label}]"
        first = lines.split("-")[0] if lines else ""
        return f'<a class="cite" href="/object/{oid}{"?line=" + first if first else ""}">[{label}]</a>'

    html = re.sub(r"\[([A-Z][A-Z0-9_/ ]{2,}?)(?::(\d+(?:-\d+)?))?\]", cite, html)
    html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)
    html = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", html)
    paragraphs = []
    for block in re.split(r"\n\s*\n", html):
        lines = block.splitlines()
        if lines and all(re.match(r"^\s*[-*•] ", l) for l in lines if l.strip()):
            items = [re.sub(r"^\s*[-*•] ", "", l) for l in lines if l.strip()]
            paragraphs.append("<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>")
        else:
            paragraphs.append("<p>" + "<br>".join(lines) + "</p>")
    return "".join(paragraphs)


# ==================================================================================== Assessments

CATEGORY_LABEL = {"s4hana": "S/4HANA readiness", "security": "Security", "quality": "Quality & performance", "cleancore": "Clean Core"}


@ui.page("/assessments")
def assessments_page(category: str = "", severity: str = "", rule: str = "") -> None:
    with frame("Assessments", _system_label()):
        ui.html('<h1 class="page-title">Assessments</h1><div class="page-sub">Deterministic rules over every object: S/4HANA simplification items, Clean Core tiering, security and quality. Each finding points at a line and says how to fix it.</div>')
        try:
            from atlas.assess.rules import RELEASE_LABELS, RULES, rules_for
            _w = data.active_workspace()
            _n = len(rules_for(_w.target_release, _w.deployment))
            with ui.row().classes("items-center gap-2 mb-2"):
                ui.html(f'<span class="tag">Rule variant: {escape(RELEASE_LABELS.get(_w.target_release, _w.target_release))}</span>')
                ui.label(f"{_n} of {len(RULES)} rules apply to this target (like an ATC check variant) - change the target on the Workspaces page, then re-run Assess.").classes("meta")
        except Exception:      # noqa: BLE001
            pass
        ov = data.assessment_overview()
        if not ov["total"] and not ov["tiers"]:
            ui.label("No findings yet. Run the pipeline (Jobs) or `atlas assess`.").classes("meta")
            return

        with ui.row().classes("w-full gap-4 flex-wrap"):
            kpi("Open findings", ov["total"], f"{ov['by_severity'].get('high', 0)} high · {ov['by_severity'].get('medium', 0)} medium", "fact_check")
            kpi("Remediation estimate", f"{ov['effort_hours']:.0f} h", "sum of per-finding defaults; edit per project", "schedule")
            kpi("S/4HANA", f"{ov['s4_status'].get('remediate', 0) + ov['s4_status'].get('review', 0)} objects", f"{ov['s4_status'].get('remediate', 0)} remediate · {ov['s4_status'].get('review', 0)} review · {ov['s4_status'].get('ok', 0)} ok", "upgrade")
            kpi("Clean Core", " / ".join(f"T{t}: {n}" for t, n in ov["tiers"].items() if t != "-") or "-", f"{ov['tiers'].get('-', 0)} DDIC/config objects not tiered", "verified")

        with ui.row().classes("w-full gap-4 no-wrap flex-wrap items-stretch"):
            with ui.element("div").classes("tile flex-1 min-w-[22rem]"):
                ui.label("Findings by category").classes("section-title")
                ui.echart({
                    "tooltip": {}, "series": [{"type": "pie", "radius": ["45%", "75%"], "label": {"formatter": "{b}: {c}"},
                                              "data": [{"name": CATEGORY_LABEL.get(k, k), "value": v} for k, v in ov["by_category"].items()]}],
                }).classes("h-56 w-full")
            with ui.element("div").classes("tile flex-1 min-w-[22rem]"):
                ui.label("Objects with the most remediation effort").classes("section-title")
                for t in ov["top_objects"]:
                    with ui.row().classes("items-center gap-3 no-wrap w-full"):
                        ui.link(t["name"], f"/object/{t['id']}").classes("obj-name")
                        ui.label(t["type"]).classes("meta")
                        ui.space()
                        ui.label(f"{t['findings']} findings · {t['effort']} h").classes("meta")

        with ui.element("div").classes("tile w-full"):
            ui.label("Rules triggered").classes("section-title")
            rule_rows = [dict(r, category_label=CATEGORY_LABEL.get(r["category"], r["category"])) for r in ov["rules"]]
            rt = ui.table(
                columns=[
                    {"name": "rule_id", "label": "Rule", "field": "rule_id", "align": "left", "classes": "mono"},
                    {"name": "severity", "label": "Severity", "field": "severity", "align": "left"},
                    {"name": "category_label", "label": "Category", "field": "category_label", "align": "left"},
                    {"name": "title", "label": "Title", "field": "title", "align": "left"},
                    {"name": "findings", "label": "Findings", "field": "findings", "align": "right", "sortable": True},
                    {"name": "objects", "label": "Objects", "field": "objects", "align": "right", "sortable": True},
                    {"name": "effort", "label": "Effort h", "field": "effort", "align": "right", "sortable": True},
                ],
                rows=rule_rows, row_key="rule_id", pagination=15,
            ).classes("w-full").props("flat dense")
            rt.on("rowClick", lambda e: rule_filter.set_value(e.args[1]["rule_id"]))

        with ui.element("div").classes("tile w-full"):
            with ui.row().classes("items-center gap-3 no-wrap flex-wrap w-full"):
                ui.label("Findings").classes("section-title")
                cat_filter = ui.select({"": "All categories", **CATEGORY_LABEL}, value=category).props("outlined dense").classes("w-52")
                sev_filter = ui.select({"": "All severities", "high": "high", "medium": "medium", "low": "low", "info": "info"}, value=severity).props("outlined dense").classes("w-40")
                rule_filter = ui.input(value=rule, placeholder="rule id").props("outlined dense clearable").classes("w-32")
                status_filter = ui.select({"open": "open", "accepted": "accepted", "fixed": "fixed", "false_positive": "false positive", "all": "all"}, value="open").props("outlined dense").classes("w-40")
                text_filter = ui.input(placeholder="object or text").props("outlined dense clearable").classes("w-56")
                ui.space()
                ui.button("Export CSV", icon="download", on_click=lambda: ui.download.content(data.findings_csv(current_rows()), "atlas_findings.csv")).props("flat")
            list_box = ui.column().classes("w-full gap-0 mt-2")

            def current_rows() -> list[dict]:
                return data.findings(cat_filter.value, sev_filter.value, (rule_filter.value or "").upper(), status_filter.value, text_filter.value or "")

            def render() -> None:
                rows = current_rows()
                list_box.clear()
                with list_box:
                    ui.label(f"{len(rows)} finding(s)").classes("meta")
                    for f in rows[:300]:
                        with ui.element("div").classes("w-full py-2").style("border-bottom:1px solid var(--sapShellBorder)"):
                            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                                ui.html(severity_badge(f["severity"]))
                                ui.label(f["rule_id"]).classes("mono text-sm w-16")
                                ui.link(f["object"], f"/object/{f['object_id']}").classes("obj-name")
                                ui.label(f["type"]).classes("meta")
                                if f["component"]:
                                    ui.label(f["component"]).classes("meta mono")
                                if f["line"]:
                                    ui.link(f"L{f['line']}", f"/object/{f['object_id']}?line={f['line']}").classes("cite")
                                ui.space()
                                ui.label(f"{f['effort']} h").classes("meta")
                                st = ui.select(["open", "accepted", "fixed", "false_positive"], value=f["status"]).props("dense borderless options-dense").classes("w-36 text-xs")
                                st.on_value_change(lambda e, fid=f["id"]: (data.update_finding_status(fid, e.value), ui.notify("Status saved")))
                            ui.label(f"{f['title']} - {f['message']}").classes("text-sm")
                            if f["snippet"]:
                                ui.html(f'<code class="mono text-xs">{escape(f["snippet"][:160])}</code>')
                            ui.label(f"Fix: {f['remediation']}").classes("meta")

            for w in (cat_filter, sev_filter, status_filter):
                w.on_value_change(lambda e: render())
            rule_filter.on_value_change(lambda e: render())
            text_filter.on("keydown.enter", render)
            render()


# ==================================================================================== FSD

VERDICT_STYLE = {"reuse": ("Reuse existing object", "#256F3A", "#E9F7EC"), "extend": ("Extend existing objects", "#B35A00", "#FFF3E0"), "build": ("New development", "#0A6ED1", "#E6F2FF")}
STATUS_STYLE = {"covered": "high", "partial": "medium", "missing": "info"}


def _verdict_badge(verdict: str) -> str:
    label, fg, bg = VERDICT_STYLE.get(verdict, (verdict, "#5B738B", "#F5F6F7"))
    return f'<span class="badge" style="background:{bg};color:{fg}">{escape(label)}</span>'


def _status_badge(status: str) -> str:
    colours = {"covered": ("#E9F7EC", "#256F3A"), "partial": ("#FFF3E0", "#B35A00"), "missing": ("#FFEAEA", "#AA0808")}
    bg, fg = colours[status]
    return f'<span class="badge" style="background:{bg};color:{fg}">{status}</span>'


@ui.page("/fsd")
def fsd_page(id: int = 0) -> None:
    with frame("FSD analysis", _system_label()):
        ui.html('<h1 class="page-title">FSD analysis</h1><div class="page-sub">Upload a functional specification (.docx, .pdf, .md, .txt). ABAP Beacon splits it into requirements, checks which existing objects already cover them, says what has to change, and plans the rest with the right BAPIs, function modules and classes. Customer, project and system names found in the document are masked automatically.</div>')

        result_box = ui.column().classes("w-full gap-4")

        async def analyse(path: Path) -> None:
            # the caller may be a button that lives inside result_box (Re-run), which is cleared below -
            # so every UI call after the clear runs in result_box's own context, never in the caller's
            result_box.clear()
            with result_box:
                ui.label(f"Analysing {path.name}...").classes("meta")
                ui.linear_progress(show_value=False).props("indeterminate").classes("w-full")
            try:
                res = await run.io_bound(data.analyse_fsd, str(path))
            except Exception as error:      # noqa: BLE001 - never leave the user with a stack trace
                res = {"error": f"Analysis failed: {error}"}
            with result_box:
                if res.get("error"):
                    result_box.clear()
                    with ui.element("div").classes("tile w-full").style("border-left:6px solid #AA0808"):
                        ui.label("This file could not be analysed").classes("section-title")
                        ui.label(res["error"]).classes("text-sm")
                        ui.label("Supported: Word .docx (not .doc), PDF with selectable text, Markdown and plain text. Save the specification again in one of these formats and drop it here.").classes("meta mt-1")
                    ui.notify(res["error"], type="negative", timeout=8000)
                    return
                ui.navigate.to(f"/fsd?id={res['id']}")

        with ui.row().classes("w-full gap-4 no-wrap flex-wrap items-stretch"):
            with ui.element("div").classes("tile flex-1 min-w-[26rem]"):
                ui.label("Analyse a specification").classes("section-title")

                async def on_upload(e) -> None:
                    try:
                        safe = re.sub(r"[^A-Za-z0-9._ \-()]+", "_", e.file.name or "fsd.docx").strip() or "fsd.docx"
                        target = data.settings.input_dir / "fsd" / safe
                        target.parent.mkdir(parents=True, exist_ok=True)
                        await e.file.save(target)
                    except Exception as error:
                        ui.notify(f"Upload failed: {error}", type="negative", timeout=8000)
                        return
                    await analyse(target)

                ui.upload(label="Drop an FSD here (.docx / .pdf / .md / .txt)", on_upload=on_upload, auto_upload=True, max_file_size=50 * 1024 * 1024).props("accept=.docx,.pdf,.md,.txt,.markdown,.text flat bordered").classes("w-full mt-2")
                samples = sorted((Path(__file__).resolve().parents[2] / "samples" / "fsd").glob("FSD_*")) if (Path(__file__).resolve().parents[2] / "samples" / "fsd").exists() else []
                if samples:
                    ui.label("Or try a sample:").classes("meta mt-3")
                    with ui.row().classes("gap-2 flex-wrap"):
                        for smp in samples:
                            ui.button(smp.stem.replace("_", " "), on_click=lambda p=smp: analyse(p)).props("flat dense no-caps").classes("text-xs")
            with ui.element("div").classes("tile flex-1 min-w-[26rem]"):
                ui.label("Previous analyses").classes("section-title")
                rows = data.fsd_analyses()
                if not rows:
                    ui.label("Nothing analysed yet.").classes("meta")
                for a in rows[:12]:
                    label, fg, bg = VERDICT_STYLE[a["verdict"]]
                    with ui.row().classes("items-center gap-3 no-wrap w-full"):
                        ui.html(f'<span class="badge" style="background:{bg};color:{fg}">{escape(label)}</span>')
                        ui.link(a["title"], f"/fsd?id={a['id']}").classes("obj-name")
                        ui.space()
                        ui.label(f"{a['coverage']}% · {a['requirements']} reqs · {a['effort']} h · {a['created']}").classes("meta")

        if not id:
            return
        a = data.fsd_analysis(id)
        if a is None:
            ui.label("Analysis not found.").classes("meta")
            return
        r = a["result"]
        st = r["stats"]
        label, fg, bg = VERDICT_STYLE[a["verdict"]]

        with result_box:
            with ui.element("div").classes("tile w-full").style(f"border-left:6px solid {fg}"):
                with ui.row().classes("items-center gap-3 no-wrap w-full"):
                    ui.html(f'<span class="badge" style="background:{bg};color:{fg};font-size:.9rem">{escape(label)}</span>')
                    ui.label(a["title"]).classes("section-title")
                    ui.space()
                    ui.button("Download report (.md)", icon="download", on_click=lambda: ui.download.content(a["report"].encode("utf-8"), Path(a["filename"]).stem + "_analysis.md")).props("flat")

                    async def download_ts() -> None:
                        try:
                            content, name = await run.io_bound(data.fsd_techspec, id)
                            ui.download.content(content, name)
                        except Exception as error:      # noqa: BLE001
                            ui.notify(f"Could not build the Technical Spec: {error}", type="negative", timeout=8000)

                    ui.button("Technical Spec (.docx)", icon="description", on_click=download_ts).props("flat")

                    async def download_code() -> None:
                        try:
                            blob, name, names = await run.io_bound(data.fsd_code_package, id)
                            ui.download.content(blob, name)
                            ui.notify(f"{len(names)} files: class skeletons with one method per plan step, ABAP Unit tests per FSD statement, tables, program, messages", type="positive", timeout=6000)
                        except Exception as error:      # noqa: BLE001
                            ui.notify(f"Could not generate code: {error}", type="negative", timeout=8000)

                    ui.button("ABAP skeletons (.zip)", icon="code", on_click=download_code).props("flat")

                    async def ai_review() -> None:
                        ui.notify("Asking the AI provider for a review...")
                        res = await run.io_bound(data.fsd_ai_review, id)
                        if res.get("error"):
                            ui.notify(res["error"], type="negative", timeout=8000)
                        else:
                            ui.navigate.to(f"/fsd?id={id}")

                    if data.ai_enabled():
                        ui.button("AI review" if not a["ai"] else "Refresh AI review", icon="auto_awesome", on_click=ai_review).props("flat").set_enabled(data.ai_status()["claude-code"] or data.ai_status()["anthropic"])
                ui.label(r["summary"][:500]).classes("meta mt-1")
                with ui.row().classes("w-full gap-4 flex-wrap mt-3"):
                    kpi("Coverage by existing code", f"{a['coverage']}%", "weighted by requirement importance", "pie_chart")
                    kpi("Requirements", st["requirements"], f"{st['covered']} covered · {st['partial']} partial · {st['missing']} missing", "checklist")
                    kpi("Remaining effort", f"{a['effort']} h", "incl. design & unit tests", "schedule")
                    pattern_short = re.split(r"[:(]", r["plan"]["pattern"])[0].strip()
                    kpi("Solution pattern", pattern_short[:40], r["plan"]["pattern_reason"][:90] + ("…" if len(r["plan"]["pattern_reason"]) > 90 else ""), "architecture")
                    fz = r.get("feasibility") or {}
                    if fz:
                        kpi("Feasibility", fz["verdict"], f"complexity {fz['complexity']['band']} · FSD quality {fz['quality']['score']}/100 · {fz['rice']}", "verified")
                snap = a.get("snapshot") or {}
                if a.get("stale"):
                    with ui.row().classes("items-center gap-2 mt-2 no-wrap flex-wrap").style("color:#B35A00"):
                        ui.icon("update", size="sm")
                        ui.label(f"The repository changed after this analysis (analysed on code as of {snap.get('as_of')}, {snap.get('objects')} objects; now {snap.get('now')}, {snap.get('now_objects')} objects). Re-run to refresh the matches.").classes("text-sm")
                        async def rerun(fname=a["filename"]) -> None:
                            cands = [data.settings.input_dir / "fsd" / fname, Path(__file__).resolve().parents[2] / "samples" / "fsd" / fname]
                            src = next((c for c in cands if c.exists()), None)
                            if src is None:
                                with result_box:
                                    ui.notify(f"Original file {fname} is no longer available - upload it again.", type="warning", timeout=6000)
                                return
                            await analyse(src)

                        ui.button("Re-run", icon="refresh", on_click=rerun).props("dense flat").mark("rerun-btn")
                elif snap.get("as_of"):
                    ui.label(f"Matched against the repository as of {snap['as_of']} ({snap.get('objects')} objects).").classes("meta mt-1")

            detected = [t for t in (r.get("detected_terms") or []) if t.lower() not in {x.lower() for x in data.guard_policy()["terms"]}]
            if detected:
                banner = ui.element("div").classes("tile w-full").style("border-left:6px solid #B35A00;background:#FFF8EE")
                with banner:
                    with ui.row().classes("items-center gap-3 no-wrap w-full flex-wrap"):
                        ui.icon("shield", size="sm").style("color:#B35A00")
                        ui.label("Guardrails: names found in this document and masked automatically").classes("section-title")
                        ui.space()

                        def add_terms(terms=detected, box=banner) -> None:
                            added = data.add_guard_terms(terms)
                            data.invalidate()
                            box.clear()
                            with box:
                                ui.label(f"{len(added)} name(s) added to the guardrail list." if added else "Nothing new to add - all names were already on the list.").classes("text-sm")
                                ui.label("They stay masked in the UI, in reports and in everything sent to an AI provider. The list is on Settings → Guardrails.").classes("meta")
                            ui.notify("Guardrails updated", type="positive")

                        ui.button("Add to guardrails", icon="add_moderator", on_click=add_terms).props("unelevated dense")
                        ui.link("Edit the list", "/guardrails").classes("meta")
                    with ui.expansion(f"Show the {len(detected)} detected name(s)", icon="visibility").classes("w-full").props("dense"):
                        ui.label(", ".join(detected)).classes("mono text-sm")
                    ui.label("They are masked in this analysis already. Add them so future analyses, searches and AI calls mask them too; ignore the ones that are not sensitive. This box is for the administrator - it disappears once the names are on the list.").classes("meta")

            if r["reuse"]:
                with ui.element("div").classes("tile w-full"):
                    ui.label("Existing objects to reuse").classes("section-title")
                    for c in r["reuse"]:
                        with ui.row().classes("items-center gap-3 no-wrap w-full"):
                            ui.link(c["name"], f"/object/{c['object_id']}").classes("obj-name")
                            ui.label(c["type"]).classes("meta")
                            ui.label(f"{c['lines']} lines").classes("meta")
                            ui.html(f'<span class="tag">covers {c["coverage_pct"]}%</span>')
                            ui.space()
                            ui.label(f"covered {len(c['covered'])} · partial {len(c['partial'])} · missing {len(c['missing'])}").classes("meta")
                        ui.label(c["description"][:220]).classes("meta")
                        if c["lines"] < 60:
                            ui.label("Small object - coverage is based on its description; verify before relying on it.").classes("text-warning text-xs")

            plan = r["plan"]
            is_build = a["verdict"] == "build"
            fz = r.get("feasibility") or {}
            if fz:
                colour = {"positive": "#256F3A", "warning": "#B35A00", "negative": "#AA0808"}.get(fz.get("colour"), "#5B738B")
                with ui.element("div").classes("tile w-full").style(f"border-left:6px solid {colour}"):
                    ui.label("Feasibility and complexity").classes("section-title")
                    with ui.row().classes("gap-2 flex-wrap items-center"):
                        ui.html(f'<span class="tag" style="background:{colour};color:#fff">{escape(fz["verdict"])}</span>')
                        ui.html(f'<span class="tag neutral">complexity {escape(fz["complexity"]["band"])}</span>')
                        ui.html(f'<span class="tag neutral">FSD quality {fz["quality"]["score"]}/100</span>')
                        ui.html(f'<span class="tag neutral">{escape(fz["rice"])}</span>')
                        ui.html(f'<span class="tag neutral">estimate confidence {escape(fz["confidence"]["band"])} ({fz["confidence"]["pct"]} %)</span>')
                    grid = "grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr)); column-gap:1.5rem; row-gap:.5rem; align-items:start"
                    with ui.element("div").classes("grid w-full mt-2").style(grid):
                        for title, items in (("Blocking as written", fz.get("blockers")), ("Changes needed", fz.get("changes")), ("Risks to raise", fz.get("risks")), ("Not specified in the FSD", fz.get("missing_nfr"))):
                            if items:
                                with ui.column().classes("gap-1 min-w-0"):
                                    ui.label(title).classes("kpi-label")
                                    for it in items:
                                        ui.label("• " + it).classes("text-sm")
                        with ui.column().classes("gap-1 min-w-0"):
                            ui.label("Complexity drivers").classes("kpi-label")
                            for d in fz["complexity"]["drivers"]:
                                ui.label("• " + d).classes("text-sm")
                        with ui.column().classes("gap-1 min-w-0"):
                            ui.label("What the FSD covers").classes("kpi-label")
                            with ui.row().classes("gap-1 flex-wrap"):
                                for k, v in fz["quality"]["topics"].items():
                                    ui.html(f'<span class="tag {"" if v else "neutral"}">{"✓" if v else "–"} {escape(k)}</span>')
                            ui.label(f"{fz['quality']['testable']} of {fz['quality']['detailed']} detailed statements are testable; {len(fz['quality']['vague'])} use open wording ({', '.join(fz['quality']['vague'][:6])}).").classes("meta")
                            ui.label(fz["confidence"]["text"]).classes("meta")
                    if fz.get("questions"):
                        with ui.expansion(f"Clarification questions for the functional consultant ({len(fz['questions'])})", icon="help_outline").classes("w-full mt-2").props("dense"):
                            for i, q in enumerate(fz["questions"], 1):
                                ui.label(f"{i}. {q}").classes("text-sm")

            def requirement_list() -> None:
                title = f"FSD statements one by one ({len(r['requirements'])})"
                box = ui.expansion(title, icon="format_list_numbered", value=not is_build).classes("w-full tile") if is_build else ui.element("div").classes("tile w-full")
                with box:
                    if not is_build:
                        ui.label(title).classes("section-title")
                    ui.label("Every sentence, bullet and table row of the specification, in document order, with the existing code that covers it. "
                             "Scope rows summarise the detailed rows and carry no effort of their own." if is_build else
                             "Every sentence, bullet and table row of the specification, in document order, with the existing code that covers it and what has to change.").classes("meta")
                    grid_cols = "grid-template-columns: 3rem 5.5rem 8rem minmax(0,1fr) 4.5rem; column-gap:.75rem; align-items:start"
                    with ui.element("div").classes("grid w-full mt-2").style(grid_cols + "; border-bottom:1px solid var(--sapShellBorder); padding-bottom:.25rem"):
                        for h in ("#", "Existing", "Kind", "Statement in the FSD", "Effort"):
                            ui.label(h).classes("kpi-label")
                    for req in r["requirements"]:
                        b = req["best"]
                        with ui.element("div").classes("grid w-full py-2").style(grid_cols + "; border-bottom:1px solid var(--sapShellBorder)"):
                            ui.label(req["id"]).classes("mono text-sm")
                            ui.html(_status_badge(req["status"]))
                            ui.html(f'<span class="tag neutral">{escape(req["kind"])}</span>')
                            with ui.column().classes("gap-1 min-w-0"):
                                ui.label(req["text"]).classes("text-sm")
                                with ui.row().classes("items-center gap-2 flex-wrap"):
                                    if b:
                                        ui.label("existing code:").classes("meta")
                                        ui.link(b["name"], f"/object/{b['object_id']}").classes("obj-name text-sm")
                                        if b["components"]:
                                            ui.label("→ " + ", ".join(b["components"][:3])).classes("mono text-xs meta")
                                        ui.label(f"confidence {b['confidence']:.2f}").classes("meta")
                                        if b.get("evidence"):
                                            ui.label(b["evidence"]).classes("meta")
                                    ui.label(req["change"]).classes("text-sm").style("color: var(--sapText2)")
                            ui.label(f"{req['effort_hours']} h").classes("meta text-right")

            def development_plan() -> None:
                with ui.element("div").classes("tile w-full"):
                    ui.label("Development plan - what to build").classes("section-title")
                    ui.label(f"{plan['pattern']} - {plan['pattern_reason']}").classes("text-sm")
                    if plan.get("alternatives"):
                        with ui.expansion("Before building - design alternatives to raise with the functional consultant", icon="lightbulb").classes("w-full").props("dense"):
                            for alt in plan["alternatives"]:
                                ui.label("• " + alt).classes("text-sm")
                    ui.label("Each step is one piece of work. The FSD statements it addresses are listed inside it; every BAPI, table or class appears in the step where it is first needed - once.").classes("meta mt-2")
                    for step in plan["steps"]:
                        n_addr = len(step.get("addresses") or step["requirements"])
                        head = f"{step['n']}. {step['title']}" + (f"   ·   {n_addr} FSD statement(s)" if n_addr else "") + (f"   ·   reuse {step['reuse']}" if step["reuse"] else "")
                        with ui.expansion(head, icon="check_circle" if step["reuse"] else "radio_button_unchecked").classes("w-full").props("dense"):
                            ui.label(step["detail"]).classes("text-sm")
                            if step["blocks"]:
                                ui.label("Building blocks").classes("kpi-label mt-2")
                                with ui.element("div").classes("grid w-full").style("grid-template-columns: 7rem minmax(12rem,22rem) minmax(0,1fr); column-gap:.75rem; row-gap:.25rem; align-items:start"):
                                    for bl in step["blocks"]:
                                        ui.html(f'<span class="tag neutral">{escape(bl["kind"].replace(" (named in the FSD)", " · FSD"))}</span>')
                                        ui.label(bl["name"]).classes("mono text-sm")
                                        ui.label(bl["purpose"]).classes("meta")
                            addressed = step.get("addresses") or []
                            if addressed:
                                ui.label("Addresses these FSD statements").classes("kpi-label mt-2")
                                with ui.element("div").classes("grid w-full").style("grid-template-columns: 3rem 8rem minmax(0,1fr); column-gap:.75rem; row-gap:.25rem; align-items:start"):
                                    for ad in addressed:
                                        ui.label(ad["id"]).classes("mono text-sm")
                                        ui.html(f'<span class="tag neutral">{escape(ad["kind"])}</span>')
                                        ui.label(ad["text"]).classes("text-sm")
                            elif step["requirements"]:
                                ui.label("Serves " + ", ".join(step["requirements"])).classes("meta")
                    if plan.get("fsd_blocks"):
                        with ui.expansion(f"Building blocks the FSD names ({len(plan['fsd_blocks'])}) and where they are used", icon="fact_check").classes("w-full mt-2").props("dense"):
                            with ui.element("div").classes("grid w-full").style("grid-template-columns: 5rem minmax(12rem,20rem) minmax(0,1fr) 5rem; column-gap:.75rem; row-gap:.25rem; align-items:start"):
                                for bl in plan["fsd_blocks"]:
                                    ui.html(f'<span class="tag neutral">{escape(bl["kind"].replace(" (named in the FSD)", ""))}</span>')
                                    ui.label(bl["name"]).classes("mono text-sm")
                                    ui.label(bl["purpose"]).classes("meta")
                                    ui.html(f'<span class="tag">{escape(bl.get("used_in") or "not needed")}</span>')

            if is_build:
                development_plan()          # nothing to reuse: the work list comes first
                requirement_list()
            else:
                requirement_list()          # something exists: per-statement status is the point
                development_plan()

            cmp_rows = data.compare_candidates_for(id) if len(r.get("reuse") or []) >= 2 else []
            if cmp_rows:
                with ui.element("div").classes("tile w-full"):
                    ui.label("Compare the reuse candidates").classes("section-title")
                    ui.label("Ranked by facts, not opinion: coverage of this FSD, open findings, production usage, Clean Core tier, size. A person chooses; the table is the evidence.").classes("meta")
                    grid = "grid-template-columns: 2.5rem 15rem 6rem 8rem 7rem 6rem 5rem 6rem 5rem; column-gap:.75rem; align-items:start"
                    with ui.element("div").classes("grid w-full mt-2").style(grid + "; border-bottom:1px solid var(--sapShellBorder); padding-bottom:.25rem"):
                        for h in ("#", "Object", "Coverage", "Covers", "Findings", "Usage", "Tier", "Size", "Score"):
                            ui.label(h).classes("kpi-label")
                    for c in cmp_rows:
                        with ui.element("div").classes("grid w-full py-1").style(grid + "; border-bottom:1px solid var(--sapShellBorder)"):
                            ui.label(str(c["rank"])).classes("mono text-sm"); ui.link(c["name"], f"/object/{c['object_id']}").classes("obj-name text-sm")
                            ui.label(f"{c['coverage']} %").classes("mono text-sm"); ui.label(f"{len(c['covered'])} covered · {len(c['partial'])} partial").classes("text-sm")
                            ui.label(f"{c['findings']} ({c['findings_h']} h)").classes("mono text-sm"); ui.label(f"{c['calls']:,} calls" if c["calls"] else "no data").classes("text-sm")
                            ui.label(c["tier"]).classes("mono text-sm"); ui.label(f"{c['lines']:,} lines · {c['complexity']}").classes("meta"); ui.label(str(c["score"])).classes("mono text-sm")

            if data.ai_enabled():
              with ui.element("div").classes("tile w-full"):
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.icon("auto_awesome", size="sm").style("color: var(--sapBrand)")
                    ui.label("Ask the architect (AI)").classes("section-title")
                ui.label("Ask anything about this analysis - why a step, which BAPI, what to clarify. The answer is grounded in the facts above; everything sent to the AI provider is masked by the guardrails and logged.").classes("meta")
                qa_box = ui.column().classes("w-full gap-2 mt-1")
                with qa_box:
                    for item in (r.get("qa") or [])[-3:]:
                        ui.label("Q: " + item["q"]).classes("text-sm").style("font-weight:600")
                        ui.markdown(item["a"]).classes("text-sm")
                with ui.row().classes("items-center gap-2 w-full no-wrap mt-1"):
                    q_in = ui.input(placeholder="e.g. Why is BAPI_BUPA_CHANGE not used? What must the functional consultant confirm first?").classes("flex-1").props("outlined dense")

                    async def ask_now() -> None:
                        q = (q_in.value or "").strip()
                        if not q:
                            ui.notify("Type a question first", type="warning")
                            return
                        ask_btn.set_enabled(False)
                        with qa_box:
                            ui.label("Q: " + q).classes("text-sm").style("font-weight:600")
                            spinner = ui.spinner(size="sm")
                        res = await run.io_bound(data.ask_fsd, id, q)
                        spinner.delete()
                        with qa_box:
                            if res.get("error"):
                                ui.label("The AI provider could not answer: " + res["error"] + " - check Settings → AI provider.").classes("text-sm").style("color:#AA0808")
                            else:
                                ui.markdown(res["answer"]).classes("text-sm")
                                ui.label(f"answered by {res.get('provider')} · masked by guardrails · logged in the egress ledger").classes("meta")
                        q_in.value = ""
                        ask_btn.set_enabled(True)

                    ask_btn = ui.button("Ask", icon="send", on_click=ask_now).props("unelevated dense")
                    for ex in ("Which step should I start with and why?", "What must the functional consultant confirm before build?", "Why is the coverage what it is?"):
                        ui.html(f'<span class="tag example">{escape(ex)}</span>').on("click", lambda e=ex: q_in.set_value(e))

            with ui.element("div").classes("tile w-full"):
                ui.label("Objects to create, extend or reuse").classes("section-title")
                ui.label("One row per development object, with the BAPIs, function modules, classes and tables it uses and the plan steps it implements.").classes("meta")
                obj_cols = "grid-template-columns: 4.5rem 15rem 11rem minmax(0,1.2fr) minmax(0,1fr) 4rem; column-gap:.75rem; align-items:start"
                with ui.element("div").classes("grid w-full mt-2").style(obj_cols + "; border-bottom:1px solid var(--sapShellBorder); padding-bottom:.25rem"):
                    for h in ("Action", "Object", "Type", "Purpose", "Uses", "Steps"):
                        ui.label(h).classes("kpi-label")
                for o in plan["objects"]:
                    with ui.element("div").classes("grid w-full py-2").style(obj_cols + "; border-bottom:1px solid var(--sapShellBorder)"):
                        ui.html(badge(o["action"], {"create": "ai", "extend": "offline", "reuse": "human"}.get(o["action"], "offline")))
                        ui.label(o["name"]).classes("mono text-sm").style("word-break: break-all")
                        ui.label(o["type"]).classes("text-sm")
                        ui.label(o["purpose"]).classes("text-sm")
                        with ui.column().classes("gap-0 min-w-0"):
                            for bname in (o.get("blocks") or []):
                                ui.label(bname).classes("mono text-xs")
                            if not o.get("blocks"):
                                ui.label("-").classes("meta")
                        ui.label(", ".join(str(n) for n in (o.get("steps") or [])) or "-").classes("mono text-sm")

            with ui.row().classes("w-full gap-4 no-wrap flex-wrap items-start"):
                with ui.element("div").classes("tile flex-1 min-w-[24rem]"):
                    ui.label("Effort estimate").classes("section-title")
                    with ui.element("div").classes("grid w-full").style("grid-template-columns: minmax(0,1fr) 5rem; column-gap:.75rem; row-gap:.25rem"):
                        for k, v in plan["effort_breakdown"].items():
                            ui.label(k.replace("_", " ")).classes("text-sm")
                            ui.label(f"{v} h").classes("text-sm mono text-right")
                    ui.label(f"Total {plan['effort_hours']} h").classes("section-title mt-2")
                with ui.element("div").classes("tile flex-1 min-w-[24rem]"):
                    ui.label("S/4HANA & Clean Core notes").classes("section-title")
                    if plan["s4_notes"]:
                        for n in plan["s4_notes"]:
                            ui.label(f"• {n}").classes("text-sm")
                    else:
                        ui.label("Nothing specific.").classes("meta")
                    if plan["test_scenarios"]:
                        ui.label("Test scenarios to cover").classes("section-title mt-3")
                        for t in plan["test_scenarios"]:
                            ui.label(f"• {t}").classes("text-sm")

            if r.get("ai_notes"):
                with ui.element("div").classes("tile w-full"):
                    ui.label("AI review").classes("section-title")
                    ui.markdown(r["ai_notes"]).classes("answer w-full")


# ==================================================================================== Dependencies

@ui.page("/dependencies")
def dependencies_page(impact: str = "") -> None:
    with frame("Dependency map", _system_label()):
        ui.html('<h1 class="page-title">Dependency map</h1><div class="page-sub">What the custom code reads, writes and calls - and who depends on what. Built from parsed source, not documentation.</div>')

        with ui.element("div").classes("tile w-full"):
            with ui.row().classes("items-center gap-3 no-wrap w-full"):
                ui.label("Impact analysis").classes("section-title")
                target = ui.input(value=impact, placeholder="object, table or function module name, e.g. BSIK or ZCL_ZCA_APPLOG").props("outlined dense clearable").classes("flex-1 mono")
                depth = ui.select({1: "1 level", 2: "2 levels", 3: "3 levels", 5: "5 levels"}, value=3).props("outlined dense").classes("w-32")
                run_btn = ui.button("Analyse", icon="account_tree").props("unelevated")
            impact_box = ui.column().classes("w-full gap-1 mt-2")

            def run_impact() -> None:
                impact_box.clear()
                name = (target.value or "").strip().upper()
                if not name:
                    return
                res = data.impact(name, depth.value)
                with impact_box:
                    ui.label(f"{res['total']} object(s) depend on {name}" + (" - if it changes, these are affected." if res["total"] else ". Nothing in the ingested packages references it.")).classes("text-sm")
                    for level in res["levels"]:
                        for e in level:
                            with ui.row().classes("items-center gap-2 no-wrap").style(f"padding-left:{(e['level'] - 1) * 1.5}rem"):
                                ui.html(f'<span class="tag neutral">L{e["level"]}</span>')
                                ui.link(e["name"], f"/object/{e['id']}").classes("obj-name")
                                ui.label(e["type"]).classes("meta")
                                ui.label(f"{e['kind']} {e['via']}").classes("meta mono")

            run_btn.on_click(run_impact)
            target.on("keydown.enter", run_impact)
            if impact:
                run_impact()

        with ui.row().classes("w-full gap-4 no-wrap flex-wrap items-start"):
            with ui.element("div").classes("tile flex-1 min-w-[30rem]"):
                ui.label("Table usage across the custom estate").classes("section-title")
                ui.label("Which SAP tables the custom code touches, how often, and their S/4HANA status.").classes("meta")
                rows = data.table_usage()
                ui.table(
                    columns=[
                        {"name": "name", "label": "Table", "field": "name", "align": "left", "classes": "mono"},
                        {"name": "text", "label": "Text", "field": "text", "align": "left"},
                        {"name": "module", "label": "Module", "field": "module", "align": "left"},
                        {"name": "objects", "label": "Objects", "field": "objects", "align": "right", "sortable": True},
                        {"name": "references", "label": "Refs", "field": "references", "align": "right", "sortable": True},
                        {"name": "s4_status", "label": "S/4 status", "field": "s4_status", "align": "left", "sortable": True},
                        {"name": "successor", "label": "Successor", "field": "successor", "align": "left"},
                    ],
                    rows=rows, row_key="name", pagination=15,
                ).classes("w-full").props("flat dense").on("rowClick", lambda e: (target.set_value(e.args[1]["name"]), run_impact()))

        with ui.element("div").classes("tile w-full"):
            ui.label("Graph").classes("section-title")
            ui.label("Custom objects (blue) with the tables (grey) and custom/standard objects they use. Drag to explore; click a node to open it.").classes("meta")
            g = data.graph()
            if not g["nodes"]:
                ui.label("No references yet - run the pipeline or `atlas parse`.").classes("meta")
            else:
                cats = ["CLAS", "PROG", "FUGR", "INTF", "DDLS", "ddic", "config", "other", "std_table", "std_object"]
                colours = {"CLAS": "#0070F2", "PROG": "#1B90FF", "FUGR": "#5DC122", "INTF": "#7858FF", "DDLS": "#00A18D", "ddic": "#A9B4BE", "config": "#C0C0C0", "other": "#D5DADF", "std_table": "#8396A8", "std_object": "#E76500"}
                nodes = [{"name": n["name"], "category": cats.index(n["category"]) if n["category"] in cats else cats.index("other"),
                          "symbolSize": 10 + min(30, n["degree"] * 3), "value": n["label"], "id_": n["id"]} for n in g["nodes"]]
                chart = ui.echart({
                    "tooltip": {"formatter": "{b}<br/>{c}"},
                    "legend": {"data": ["Class", "Program", "Function group", "Interface", "CDS", "DDIC", "Config", "Other", "SAP table", "SAP object"], "bottom": 0, "type": "scroll"},
                    "series": [{
                        "type": "graph", "layout": "force", "roam": True, "draggable": True,
                        "force": {"repulsion": 260, "edgeLength": [60, 140], "gravity": 0.08},
                        "label": {"show": True, "position": "right", "fontSize": 10, "formatter": "{b}"},
                        "categories": [{"name": lbl, "itemStyle": {"color": colours[c]}} for c, lbl in zip(cats, ["Class", "Program", "Function group", "Interface", "CDS", "DDIC", "Config", "Other", "SAP table", "SAP object"])],
                        "data": nodes,
                        "links": [{"source": l["source"], "target": l["target"], "value": l["kind"], "lineStyle": {"width": 1, "curveness": 0.15, "color": "#C33" if l["kind"] == "writes" else "#A9B4BE"}} for l in g["links"]],
                        "lineStyle": {"opacity": 0.7},
                        "emphasis": {"focus": "adjacency", "lineStyle": {"width": 3}},
                    }],
                }).classes("w-full").style("height:640px")
                chart.on_point_click(lambda e: ui.navigate.to(f"/object/{e.data['id_']}") if e.data and e.data.get("id_") else None)


# ==================================================================================== Inventory

@ui.page("/inventory")
def inventory_page() -> None:
    with frame("Inventory", _system_label()):
        options = data.filter_options()
        ui.html('<h1 class="page-title">Inventory</h1><div class="page-sub">Every object in the repository. Filter, sort, export.</div>')

        with ui.element("div").classes("tile w-full"):
            with ui.row().classes("w-full items-center gap-3 no-wrap flex-wrap"):
                text = ui.input(placeholder="Filter by name / short text / description").props("outlined dense clearable").classes("flex-1")
                type_select = ui.select(options["types"], multiple=True, label="Object type").props("outlined dense use-chips clearable").classes("w-[24rem]")
                module_select = ui.select(["", *options["modules"]], value="", label="Module").props("outlined dense").classes("w-36")
                desc_select = ui.select({"": "Any", "ai": "AI", "offline": "Rule-based", "human": "Reviewed"}, value="", label="Described by").props("outlined dense").classes("w-40")
                ui.button("Export CSV", icon="download", on_click=lambda: ui.download.content(data.inventory_csv(current["rows"]), "abap_atlas_inventory.csv", "text/csv")).props("flat")

        current: dict = {"rows": []}
        count_label = ui.label("").classes("meta")
        columns = [
            {"name": "name", "label": "Object", "field": "name", "align": "left", "sortable": True, "classes": "mono"},
            {"name": "type", "label": "Type", "field": "type", "align": "left", "sortable": True},
            {"name": "module", "label": "Module", "field": "module", "align": "left", "sortable": True},
            {"name": "package", "label": "Package", "field": "package", "align": "left", "sortable": True},
            {"name": "short_text", "label": "SAP short text", "field": "short_text", "align": "left"},
            {"name": "lines", "label": "Lines", "field": "lines", "align": "right", "sortable": True},
            {"name": "complexity", "label": "Complexity", "field": "complexity", "align": "left", "sortable": True},
            {"name": "described_by", "label": "Described", "field": "described_by", "align": "left", "sortable": True},
        ]
        with ui.element("div").classes("tile w-full p-0"):
            table = ui.table(columns=columns, rows=[], row_key="id", pagination=25).classes("w-full").props("flat dense")
            table.on("rowClick", lambda e: ui.navigate.to(f"/object/{e.args[1]['id']}"))

        def refresh() -> None:
            rows = data.inventory(types=type_select.value or None, module=module_select.value or None, described_by=desc_select.value or None, text=text.value or "")
            current["rows"] = rows
            table.rows = rows
            table.update()
            count_label.set_text(f"{len(rows)} object(s) · {sum(r['lines'] for r in rows):,} lines")

        for w in (type_select, module_select, desc_select):
            w.on_value_change(lambda _: refresh())
        text.on("keydown.enter", lambda: refresh())
        text.on_value_change(lambda _: refresh())
        refresh()


# ==================================================================================== Jobs & Pipeline

@ui.page("/jobs")
def jobs_page() -> None:
    with frame("Jobs & Pipeline", _system_label()):
        ui.html('<h1 class="page-title">Jobs & Pipeline</h1><div class="page-sub">Ingest an abapGit export end to end: acquire → ingest → parse → enrich → assess → index. Unchanged objects are skipped.</div>')

        systems = data.systems() or ["DEV"]
        log_box = ui.column().classes("w-full gap-1")
        jobs_box = ui.column().classes("w-full gap-3")

        def render_jobs() -> None:
            jobs_box.clear()
            with jobs_box:
                rows = data.jobs()
                if not rows:
                    ui.label("No pipeline runs yet.").classes("meta")
                for job in rows:
                    with ui.element("div").classes("tile w-full"):
                        with ui.row().classes("items-center gap-3 no-wrap w-full"):
                            ui.html(badge(job["status"], job["status"]))
                            ui.label(f"Job #{job['id']} · {job['kind']}").classes("section-title")
                            ui.label(job["source"]).classes("mono meta")
                            ui.space()
                            ui.label(f"{job['started']} · {job['seconds']}s").classes("meta")
                        ing = job["summary"].get("ingest", {})
                        if ing:
                            ui.label(f"objects {ing.get('objects_total', 0)} · added {ing.get('added', 0)} · updated {ing.get('updated', 0)} · unchanged {ing.get('unchanged', 0)} · files {ing.get('files', 0)}").classes("meta")
                        with ui.row().classes("gap-2 flex-wrap mt-1"):
                            for step in job["steps"]:
                                detail = step["detail"]
                                secs = detail.get("seconds", "")
                                ui.html(f'{badge(step["name"] + (f" {secs}s" if secs != "" else ""), step["status"])}')
                        if job["error"]:
                            ui.label(job["error"]).classes("text-negative text-sm")

        async def launch(source: Path, system: str, package: str) -> None:
            log_box.clear()
            with log_box:
                ui.label(f"Running pipeline for {source.name} → {system}...").classes("meta")
                progress = ui.linear_progress(show_value=False).props("indeterminate").classes("w-full")

            # The pipeline runs in a worker thread; UI elements are only touched from here.
            job = await run.io_bound(run_pipeline, PipelineOptions(source=str(source), system=system, root_package=package or None))
            data.invalidate()
            progress.delete()
            with log_box:
                if job.status == "done":
                    ui.notify(f"Job #{job.id} finished", type="positive")
                    ui.label(f"Job #{job.id} done. The repository is refreshed.").classes("text-positive")
                else:
                    ui.notify("Pipeline failed - see job details", type="negative")
            render_jobs()

        with ui.row().classes("w-full gap-4 no-wrap flex-wrap"):
            with ui.element("div").classes("tile flex-1 min-w-[26rem]"):
                ui.label("Run the pipeline").classes("section-title")
                ui.label("Upload an abapGit ZIP export, or pick one already in the input folder.").classes("meta")
                with ui.row().classes("items-center gap-3 mt-2 no-wrap flex-wrap"):
                    system_input = ui.select(systems, value=systems[0], label="System", new_value_mode="add-unique").props("outlined dense use-input").classes("w-32")
                    package_input = ui.input(label="Root package (optional)", placeholder="e.g. ZAD").props("outlined dense").classes("w-56")

                async def on_upload(e) -> None:
                    target = data.settings.input_dir / e.file.name
                    await e.file.save(target)
                    ui.notify(f"Saved {e.file.name}")
                    await launch(target, system_input.value, package_input.value)

                ui.upload(label="Drop an abapGit ZIP here", on_upload=on_upload, auto_upload=True, max_file_size=500 * 1024 * 1024).props("accept=.zip flat bordered").classes("w-full mt-2")

                existing = sorted(data.settings.input_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
                if existing:
                    with ui.row().classes("items-center gap-3 mt-3 no-wrap w-full"):
                        pick = ui.select({str(p): p.name for p in existing}, value=str(existing[0]), label="Existing export").props("outlined dense").classes("flex-1")
                        ui.button("Run", icon="play_arrow", on_click=lambda: launch(Path(pick.value), system_input.value, package_input.value)).props("unelevated")

            with ui.element("div").classes("tile min-w-[22rem]"):
                ui.label("AI enrichment").classes("section-title")
                st = data.ai_status()
                ok = st["claude-code"] or st["anthropic"]
                ui.label(f"Provider: {st['selected']}" + (" (ready)" if ok else " - not available")).classes("text-sm")
                ui.label(f"{st['pending']} code objects without AI description · {st['calls']} calls · {st['tokens_in']:,} in / {st['tokens_out']:,} out tokens · ${st['cost_usd']}" + (f" · {st['limit_hits']} usage-limit stops" if st["limit_hits"] else "")).classes("meta")
                if not ok:
                    ui.label("Install Claude Code (npm install -g @anthropic-ai/claude-code; run `claude` once to log in with your subscription) or set ANTHROPIC_API_KEY, then restart the UI.").classes("meta")
                ai_log = ui.column().classes("w-full gap-1")
                with ui.row().classes("items-center gap-3 mt-2 no-wrap"):
                    ai_limit = ui.select({5: "5 objects", 10: "10 objects", 25: "25 objects", 0: "all pending"}, value=10).props("outlined dense").classes("w-36")

                    async def run_ai() -> None:
                        ai_log.clear()
                        with ai_log:
                            ui.label("Describing objects with AI (redacted source, batched)...").classes("meta")
                            bar = ui.linear_progress(show_value=False).props("indeterminate").classes("w-full")
                        result = await run.io_bound(data.run_ai_enrich, ai_limit.value or None)
                        data.invalidate()
                        ai_log.clear()
                        with ai_log:
                            if result.get("error"):
                                ui.label(result["error"]).classes("text-negative text-sm")
                            else:
                                ui.label(f"described {result['described']} · cached {result['cached']} · calls {result['calls']} · redactions {result['redactions']} · tokens {result['input_tokens']:,}/{result['output_tokens']:,} · ${result['cost_usd']}").classes("text-sm text-positive")
                                if result.get("stopped_reason"):
                                    ui.label(f"Stopped: {result['stopped_reason']} - run again later, progress is kept.").classes("text-warning text-sm")
                                if result.get("errors"):
                                    ui.label("; ".join(result["errors"])).classes("text-negative text-sm")

                    ui.button("Describe with AI", icon="auto_awesome", on_click=run_ai).props("unelevated").set_enabled(ok and data.ai_enabled())

            with ui.element("div").classes("tile min-w-[20rem]"):
                ui.label("Maintenance").classes("section-title")

                async def reindex() -> None:
                    from atlas.db.session import session_scope

                    def _do() -> dict:
                        with session_scope(data.settings) as s:
                            return rebuild_semantic_index(s, data.settings)

                    result = await run.io_bound(_do)
                    data.invalidate()
                    ui.notify(f"Index rebuilt: {result.get('count', 0)} objects, backend {result.get('backend')}", type="positive")

                ui.button("Rebuild meaning index", icon="refresh", on_click=reindex).props("flat").classes("mt-2")
                ui.label("Watch-folder automation: run `atlas watch` in a terminal and drop ZIPs into data/input.").classes("meta mt-3")
                ui.label(f"Input folder: {data.settings.input_dir}").classes("meta mono")

        ui.label("Recent runs").classes("section-title")
        render_jobs()


# ==================================================================================== Settings: AI provider

@ui.page("/ai")
def ai_page() -> None:
    with frame("AI provider", _system_label()):
        ui.html('<h1 class="page-title">AI provider</h1><div class="page-sub">Choose what powers "Describe with AI", "Ask the codebase" and FSD reviews. Everything else in the product works without AI. Whatever you pick, text is redacted by the guardrails before it leaves this machine - local providers keep it on the machine entirely.</div>')
        if not data.ai_enabled():
            with ui.element("div").classes("tile w-full").style("border-left:6px solid #B35A00;background:#FFF8EE"):
                ui.label("AI is switched off for this workspace (strict mode)").classes("section-title")
                ui.label("No text is sent to any AI provider. Every analysis, number and document still works. Change the mode on the Workspaces page if this customer allows AI.").classes("text-sm")
        info = data.ai_config()
        st, cfg = info["status"], info["config"]

        with ui.element("div").classes("tile w-full"):
            with ui.row().classes("items-center gap-3 no-wrap"):
                ui.html(badge("ready" if st["ready"] else "not ready", "done" if st["ready"] else "failed"))
                ui.label(f"Currently selected: {st['selected']}" + (f" · model {st['model']}" if st["model"] else "")).classes("section-title")
            ui.label(st["reason"]).classes("meta")

        options = {"auto": "Auto-detect (Claude Code → Anthropic API → local Ollama → any key found)", "claude-code": "Claude Code (Claude subscription, no API key)", "anthropic": "Anthropic API (ANTHROPIC_API_KEY)"}
        options.update({o["id"]: o["label"] for o in st["options"]})
        options["manual"] = "Manual - write prompt files to paste into any chat"
        presets = {o["id"]: o for o in st["options"]}

        with ui.element("div").classes("tile w-full"):
            ui.label("Configure").classes("section-title")
            current = cfg.get("provider") or "auto"
            provider_sel = ui.select(options, value=current, label="Provider").props("outlined dense").classes("w-full max-w-[40rem]")
            note = ui.label("").classes("meta")
            base_url = ui.input(label="Base URL", value=cfg.get("base_url", "")).props("outlined dense").classes("w-full max-w-[40rem] mono")
            model = ui.input(label="Model", value=cfg.get("model", "")).props("outlined dense").classes("w-full max-w-[40rem] mono")
            api_key = ui.input(label="API key" + (" (saved - leave empty to keep)" if info["has_key"] else ""), password=True, password_toggle_button=True).props("outlined dense").classes("w-full max-w-[40rem]")
            key_link = ui.html("").classes("meta")

            def refresh(_=None) -> None:
                pid = provider_sel.value
                p = presets.get(pid)
                if p:
                    note.set_text(p["note"] or "")
                    if not base_url.value or base_url.value == presets.get(current, {}).get("base_url", "") and pid != current:
                        base_url.set_value(p["base_url"])
                    if not model.value or pid != current:
                        model.set_value(p["default_model"])
                    api_key.set_visibility(p["needs_key"] or pid == "custom")
                    base_url.set_visibility(True)
                    model.set_visibility(True)
                    key_link.set_content(f'Get a key: <a href="{p["key_url"]}" target="_blank">{p["key_url"]}</a>' if p["key_url"] and p["needs_key"] else "")
                else:
                    note.set_text({"claude-code": "Uses the `claude` CLI installed on this machine.", "anthropic": "Set ANTHROPIC_API_KEY in the environment.", "manual": "No connectivity needed.", "auto": ""}.get(pid, ""))
                    for w in (base_url, model, api_key):
                        w.set_visibility(False)
                    key_link.set_content("")

            provider_sel.on_value_change(refresh)
            refresh()
            result = ui.label("").classes("text-sm mt-2")

            async def test() -> None:
                result.set_text("Testing...")
                res = await run.io_bound(data.test_ai, provider_sel.value, base_url.value or "", api_key.value or "", model.value or "")
                result.set_text(("✓ " if res["ok"] else "✗ ") + res["message"])
                result.classes(remove="text-negative text-positive", add="text-positive" if res["ok"] else "text-negative")

            def save() -> None:
                data.save_ai_config(provider_sel.value, base_url.value or "", api_key.value or "", model.value or "", keep_key=not (api_key.value or "").strip())
                ui.notify("AI provider saved", type="positive")
                ui.navigate.to("/ai")

            with ui.row().classes("gap-3 mt-3"):
                ui.button("Test connection", icon="network_check", on_click=test).props("flat")
                ui.button("Save", icon="save", on_click=save).props("unelevated")
            ui.label("The key is stored in data/config/ai.json on this machine only. Environment variables (ATLAS_AI_PROVIDER, ATLAS_AI_API_KEY, ATLAS_AI_BASE_URL, ATLAS_AI_MODEL) override the saved values.").classes("meta mt-2")

        with ui.element("div").classes("tile w-full"):
            ui.label("Free and open-source options").classes("section-title")
            for o in st["options"]:
                if o["id"] in ("custom", "openai"):
                    continue
                with ui.row().classes("items-center gap-3 no-wrap w-full"):
                    ui.html(f'<span class="tag {"" if o["local"] else "neutral"}">{"local · free · offline" if o["local"] else "hosted · free tier"}</span>')
                    ui.label(o["label"]).classes("text-sm w-64")
                    ui.label(o["note"] or f"default model {o['default_model']}").classes("meta")


# ==================================================================================== Settings: Guardrails

@ui.page("/guardrails")
def guardrails_page() -> None:
    with frame("Guardrails", _system_label()):
        ui.html('<h1 class="page-title">Guardrails - data protection</h1><div class="page-sub">What must never leave this machine or appear in generated text: customer and partner names, SAP system IDs, business keys such as customer or document numbers, user names - on top of the always-on technical redaction of credentials, hosts, e-mails, bank accounts and tokens.</div>')
        with ui.row().classes("items-center gap-3 mb-2 flex-wrap"):
            async def dl_sheet() -> None:
                blob, name = await run.io_bound(data.protection_sheet)
                ui.download.content(blob, name)

            ui.button("Data Protection Sheet (.docx)", icon="verified_user", on_click=dl_sheet).props("unelevated")
            ui.label("One page for the customer's security officer, generated from this workspace's live configuration: where data is, AI mode and provider, what is masked, egress so far.").classes("meta")
        if not data.ai_enabled():
            with ui.element("div").classes("tile w-full").style("border-left:6px solid #B35A00;background:#FFF8EE"):
                ui.label("AI is switched off for this workspace (strict mode)").classes("section-title")
                ui.label("No text is sent to any AI provider. Every analysis, number and document still works. Change the mode on the Workspaces page if this customer allows AI.").classes("text-sm")
        pol = data.guard_policy()

        with ui.row().classes("w-full gap-4 no-wrap flex-wrap items-start"):
            with ui.element("div").classes("tile flex-1 min-w-[26rem]"):
                ui.label("Sensitive terms (one per line)").classes("section-title")
                ui.label("Customer, partner, project and system names. Matching is case-insensitive and tolerates spaces/underscores. System IDs known to the repository are added automatically.").classes("meta")
                terms = ui.textarea(value="\n".join(pol["terms"])).props("outlined").classes("w-full mono").style("min-height:14rem")
                ui.label("Rules").classes("section-title mt-3")
                toggles = {}
                for key, label in (
                    ("mask_system_ids", "Mask SAP system IDs, clients and transport numbers (ER6/100, client 100, ER6K900123)"),
                    ("mask_numbers", "Mask business keys - customer / vendor / document / material numbers"),
                    ("mask_users", "Mask SAP user names (created by, sy-uname)"),
                    ("mask_org_suffix", "Mask organisations by pattern (<Name> Bank / Ltd / GmbH / Inc ...)"),
                    ("auto_detect_names", "Auto-detect customer / project / system names in uploaded FSDs, mask them at once and offer to add them to this list"),
                    ("mask_org_units", "Mask company codes and plants (usually not secret)"),
                    ("pseudonyms", "Use stable pseudonyms (<customer-737>) instead of a flat <customer>, so the AI can still tell values apart"),
                    ("mask_in_ui", "Also mask in the web app and in generated reports (recommended for demos and shared screens)"),
                    ("mask_source", "Also mask inside displayed source code and finding snippets"),
                ):
                    toggles[key] = ui.switch(label, value=bool(pol[key])).props("dense")
                max_lines = ui.number(label="Max source lines sent to AI per object", value=pol["max_source_lines_to_ai"], min=50, max=5000, step=50).props("outlined dense").classes("w-72")

                def save() -> None:
                    values = {k: w.value for k, w in toggles.items()}
                    values["terms"] = [t.strip() for t in (terms.value or "").splitlines() if t.strip()]
                    values["max_source_lines_to_ai"] = int(max_lines.value or 400)
                    data.save_guard_policy(values)
                    data.invalidate()
                    ui.notify("Guardrails saved", type="positive")

                ui.button("Save", icon="save", on_click=save).props("unelevated").classes("mt-3")
                ui.label("Stored in data/config/guardrails.json. Egress masking is always on and cannot be switched off; these settings only extend it.").classes("meta mt-2")

            with ui.element("div").classes("tile flex-1 min-w-[26rem]"):
                ui.label("Preview").classes("section-title")
                ui.label("Paste any text (a description, a code line, an FSD sentence) to see exactly what an AI provider would receive and what the UI shows.").classes("meta")
                sample = ui.textarea(value="Sales orders for the ADNOC business are created on ER6/100 by user JSMITH01; customer 0001000123 uses https://sakshamuat.axisbank.co.in with client_secret = 'abc123'.").props("outlined").classes("w-full").style("min-height:6rem")
                out_ai = ui.html("").classes("w-full")
                out_ui = ui.html("").classes("w-full")

                def preview() -> None:
                    res = data.guard_preview(sample.value or "")
                    out_ai.set_content(f'<div class="kpi-label mt-2">Sent to AI</div><pre class="src wrap">{escape(res["ai"])}</pre><div class="meta">masked: {", ".join(f"{k} ×{v}" for k, v in res["kinds"].items()) or "nothing"}</div>')
                    out_ui.set_content(f'<div class="kpi-label mt-2">Shown in UI / reports</div><pre class="src wrap">{escape(res["display"])}</pre>')

                ui.button("Preview", icon="visibility", on_click=preview).props("flat")
                preview()

        with ui.element("div").classes("tile w-full"):
            ui.label("Egress log - every AI call").classes("section-title")
            rows = data.egress_log()
            if not rows:
                ui.label("No AI calls yet.").classes("meta")
            else:
                ui.table(columns=[
                    {"name": "when", "label": "When", "field": "when", "align": "left"},
                    {"name": "purpose", "label": "Purpose", "field": "purpose", "align": "left"},
                    {"name": "provider", "label": "Provider", "field": "provider", "align": "left"},
                    {"name": "model", "label": "Model", "field": "model", "align": "left"},
                    {"name": "status", "label": "Status", "field": "status", "align": "left"},
                    {"name": "objects", "label": "Objects", "field": "objects", "align": "right"},
                    {"name": "chars", "label": "Chars sent", "field": "chars", "align": "right"},
                    {"name": "redactions", "label": "Redactions", "field": "redactions", "align": "right"},
                    {"name": "tokens", "label": "Tokens in/out", "field": "tokens", "align": "right"},
                ], rows=rows, row_key="id", pagination=15).classes("w-full").props("flat dense")


# ==================================================================================== entry point

def start(port: int = 8080, open_browser: bool = True, reload: bool = False) -> None:
    from atlas.ui.theme import ASSETS_DIR, FAVICON_SVG, PRODUCT_NAME, PRODUCT_TAGLINE

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    app.add_static_files("/assets", str(ASSETS_DIR))

    try:                                           # never start on a damaged database - repair first
        from atlas.db.health import ensure_healthy

        if not (data.settings.db_url and not data.settings.db_url.startswith("sqlite")):
            health = ensure_healthy(data.settings.db_path)
            for a in health.actions:
                logging.getLogger("atlas.ui").warning("database repair: %s", a)
    except Exception:      # noqa: BLE001
        logging.getLogger("atlas.ui").exception("database check failed")

    ui.run(title=f"{PRODUCT_NAME} · {PRODUCT_TAGLINE}", port=port, show=open_browser, reload=reload, favicon=FAVICON_SVG, dark=False, show_welcome_message=False)


if __name__ in {"__main__", "__mp_main__"}:
    start()


@ui.page("/value")
def value_page(rate: float = 60.0, team: int = 4, cur: str = "USD") -> None:
    with frame("Executive view", _system_label()):
        ui.html('<h1 class="page-title">Executive view - what the custom code costs, what it saves</h1><div class="page-sub">Hard numbers from the repository: what an S/4HANA remediation programme costs after retiring unused code, which classic building blocks must be replaced for Clean Core, and how many hours the FSD analyses have already saved by finding code that exists. All figures are estimates from the assessment rules and the dependency graph; import production usage statistics to firm up the retirement decisions.</div>')
        v = data.value_view(rate, team, cur)
        case, pf, ret = v["case"], v["portfolio"], v["retirement"]
        money = lambda x: f"{cur} {x:,.0f}"      # noqa: E731

        with ui.row().classes("w-full gap-4 no-wrap flex-wrap items-end"):
            r_in = ui.number("Blended rate per hour", value=rate, min=10, max=500, step=5).props("outlined dense").classes("w-40")
            t_in = ui.number("Team size", value=team, min=1, max=40, step=1).props("outlined dense").classes("w-32")
            c_in = ui.select(["USD", "EUR", "INR", "AED", "SAR", "GBP"], value=cur, label="Currency").props("outlined dense").classes("w-32")
            ui.button("Recalculate", icon="calculate", on_click=lambda: ui.navigate.to(f"/value?rate={r_in.value}&team={int(t_in.value)}&cur={c_in.value}")).props("unelevated")

            async def dl_case() -> None:
                blob, name = await run.io_bound(data.business_case_file, float(r_in.value), int(t_in.value), c_in.value)
                ui.download.content(blob, name)

            ui.button("Business case (.docx)", icon="description", on_click=dl_case).props("flat")

        with ui.row().classes("w-full gap-4 no-wrap flex-wrap mt-2"):
            kpi("S/4HANA remediation programme", money(case["total_money"]), f"{case['total_h']:,.0f} h incl. test, PM, contingency · {case['weeks']:,.0f} weeks with {team} developers", "engineering")
            kpi("Saved by retiring unused code", money(case["saving_money"]), f"{case['retired_objects']} objects · {case['retired_h']:,.0f} h remediation avoided" + ("" if ret["have_usage"] else " · import usage data to confirm"), "delete_sweep")
            kpi("Saved by reuse (FSD analyses)", money(pf["saved_money"]), f"{pf['saved_h']:,.0f} h not built again across {pf['count']} specifications ({pf['reuse_count']} reuse/extend)", "recycling")
            kpi("Retirement potential", money(ret["potential"]), f"retire {ret['totals']['retire']} · review {ret['totals']['review']} · keep {ret['totals']['keep']} of {sum(ret['totals'].values())} code objects", "inventory")

        with ui.row().classes("w-full gap-4 no-wrap flex-wrap items-start"):
            with ui.element("div").classes("tile flex-1 min-w-[26rem]"):
                ui.label("Remediation waves").classes("section-title")
                grid = "grid-template-columns: 3rem minmax(0,1fr) 4rem 5rem 6rem; column-gap:.75rem; row-gap:.3rem"
                with ui.element("div").classes("grid w-full mt-2").style(grid):
                    for h in ("Wave", "Scope", "Objects", "Hours", "Cost"):
                        ui.label(h).classes("kpi-label")
                    for w in case["waves"]:
                        ui.label(str(w["wave"])).classes("mono text-sm"); ui.label(w["title"]).classes("text-sm"); ui.label(str(w["objects"])).classes("text-sm mono")
                        ui.label(f"{w['hours']:,.0f}").classes("text-sm mono"); ui.label(money(w["money"])).classes("text-sm mono")
                ui.label("Effort by module (after retirement)").classes("section-title mt-3")
                with ui.element("div").classes("grid w-full mt-1").style("grid-template-columns: minmax(0,1fr) 5rem 5rem 5rem; column-gap:.75rem; row-gap:.3rem"):
                    for h in ("Module", "Objects", "Hours", "Retired"):
                        ui.label(h).classes("kpi-label")
                    for m in case["modules"]:
                        ui.label(m["module"]).classes("text-sm"); ui.label(str(m["objects"])).classes("text-sm mono"); ui.label(f"{m['hours']:,.0f}").classes("text-sm mono"); ui.label(str(m["retire"])).classes("text-sm mono")
            with ui.element("div").classes("tile flex-1 min-w-[26rem]"):
                ui.label("Clean Core advisor - classic building blocks in use and their released successors").classes("section-title")
                if not case["swaps"]:
                    ui.label("No classic building blocks with a known successor found.").classes("meta")
                with ui.element("div").classes("grid w-full mt-2").style("grid-template-columns: minmax(8rem,12rem) minmax(0,1fr) 4rem 3rem; column-gap:.75rem; row-gap:.4rem; align-items:start"):
                    for sw in case["swaps"]:
                        ui.label(sw["classic"]).classes("mono text-sm").style("word-break: break-all"); ui.label(sw["successor"]).classes("text-sm"); ui.label(f"{sw['objects']} obj").classes("meta"); ui.html(f'<span class="tag neutral">{escape(sw["tier"])}</span>')

        with ui.element("div").classes("tile w-full"):
            with ui.row().classes("items-center gap-3 no-wrap flex-wrap w-full"):
                ui.label("Custom code retirement").classes("section-title")
                ui.space()
                ui.label("Import production usage (ST03N workload / SCMON-SUSG export as CSV or TSV with object name and calls)").classes("meta")

                p_from = ui.input("Period from (YYYY-MM-DD)").props("outlined dense").classes("w-40")
                p_to = ui.input("Period to (YYYY-MM-DD)").props("outlined dense").classes("w-40")

                async def on_usage(e) -> None:
                    target = data.settings.input_dir / "usage" / re.sub(r"[^A-Za-z0-9._ \-()]+", "_", e.file.name or "usage.csv")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    await e.file.save(target)
                    res = await run.io_bound(data.import_usage_file, str(target), "ST03N", 365, (p_from.value or "").strip(), (p_to.value or "").strip())
                    if res.get("error"):
                        ui.notify(res["error"], type="negative", timeout=8000)
                    else:
                        ui.notify(f"Imported {res['rows']} rows - {res['matched']} matched repository objects, {res['unknown']} unknown names", type="positive", timeout=6000)
                        ui.navigate.to(f"/value?rate={rate}&team={team}&cur={cur}")

                ui.upload(on_upload=on_usage, auto_upload=True, max_file_size=20 * 1024 * 1024).props("accept=.csv,.tsv,.txt flat bordered dense label='Upload usage CSV'").classes("w-64")
            _w = ret.get("window") or {}
            ui.label((f"Usage data covers {_w.get('from')} to {_w.get('to')} - {_w.get('months')} months from {_w.get('imports')} import(s) ({', '.join(_w.get('sources') or [])}). "
                      + ("" if _w.get("enough") else "Fewer than 12 months: nothing is marked 'retire' yet - import further periods (SAP keeps ~3 months of ST03N detail; monthly aggregates and SCMON/SUSG cover a year or more). ")
                      if ret["have_usage"] else "No usage data yet - decisions below rest on the dependency graph only (no custom caller = review). Imports accumulate: upload each quarter's export with its period.")
                     + f" Retiring the {ret['totals']['retire']} objects marked 'retire' avoids {ret['hours']['retire']:,.0f} h ({money(ret['saving'])}).").classes("meta")
            grid = "grid-template-columns: 4.5rem 14rem 3.5rem 4rem 4rem 4.5rem 4rem 5rem minmax(0,1fr); column-gap:.75rem; align-items:start"
            with ui.element("div").classes("grid w-full mt-2").style(grid + "; border-bottom:1px solid var(--sapShellBorder); padding-bottom:.25rem"):
                for h in ("Decision", "Object", "Type", "Module", "Lines", "Callers", "Calls", "Avoided h", "Why"):
                    ui.label(h).classes("kpi-label")
            for row in ret["rows"][:60]:
                with ui.element("div").classes("grid w-full py-1").style(grid + "; border-bottom:1px solid var(--sapShellBorder)"):
                    ui.html(badge(row["decision"], {"retire": "human", "review": "offline", "keep": "ai"}[row["decision"]]))
                    ui.link(row["name"], f"/object/{row['id']}").classes("obj-name text-sm")
                    ui.label(row["type"]).classes("text-sm"); ui.label(row["module"] or "-").classes("text-sm"); ui.label(f"{row['lines']:,}").classes("text-sm mono")
                    ui.label(str(row["callers"])).classes("text-sm mono"); ui.label("-" if row["calls"] is None else f"{row['calls']:,}").classes("text-sm mono"); ui.label(f"{row['avoided_h']}").classes("text-sm mono")
                    ui.label("; ".join(row["reasons"])).classes("meta")
            if len(ret["rows"]) > 60:
                ui.label(f"… {len(ret['rows']) - 60} more objects in the business case document").classes("meta mt-1")

        with ui.element("div").classes("tile w-full"):
            ui.label("Value delivered by the FSD analyses").classes("section-title")
            ui.label("For each specification: the effort that remains after reuse versus the new-build baseline. The difference is development that was not paid for twice.").classes("meta")
            grid = "grid-template-columns: minmax(0,1fr) 7rem 5rem 6rem 6rem 6rem 7rem 8rem; column-gap:.75rem; align-items:start"
            with ui.element("div").classes("grid w-full mt-2").style(grid + "; border-bottom:1px solid var(--sapShellBorder); padding-bottom:.25rem"):
                for h in ("Specification", "Verdict", "Coverage", "Remaining h", "Baseline h", "Saved h", "Saved", "Feasibility"):
                    ui.label(h).classes("kpi-label")
            for r_ in pf["rows"]:
                with ui.element("div").classes("grid w-full py-1").style(grid + "; border-bottom:1px solid var(--sapShellBorder)"):
                    ui.link(r_["title"], f"/fsd?id={r_['id']}").classes("text-sm")
                    ui.html(_verdict_badge(r_["verdict"]))
                    ui.label(f"{r_['coverage']} %").classes("text-sm mono"); ui.label(f"{r_['remaining_h']}").classes("text-sm mono"); ui.label(f"{r_['baseline_h']}").classes("text-sm mono")
                    ui.label(f"{r_['saved_h']}").classes("text-sm mono"); ui.label(money(r_["saved_money"])).classes("text-sm mono"); ui.label(f"{r_['feasibility']} · {r_['complexity']}".strip(" ·")).classes("meta")


@ui.page("/workspaces")
def workspaces_page() -> None:
    from atlas.assess.rules import RELEASE_LABELS

    with frame("Workspaces", _system_label()):
        ui.html('<h1 class="page-title">Workspaces</h1><div class="page-sub">One isolated data set per customer - code, analyses, searches and numbers never cross workspaces. '
                'A <b>customer</b> workspace is the product as the customer uses it; an <b>internal</b> workspace is InfraBeat\'s own accelerator library, where every object carries its origin. '
                'Each workspace has its own AI mode (normal or strict = AI off) and its own S/4HANA target release for the assessment rules.</div>')
        active = data.active_workspace()
        with ui.row().classes("w-full gap-4 no-wrap flex-wrap items-start"):
            with ui.element("div").classes("tile flex-1 min-w-[26rem]"):
                ui.label("Active workspace").classes("section-title")
                ui.label(active.name).classes("kpi-value")
                ui.label(f"{active.kind} · AI {active.ai_mode} · target {RELEASE_LABELS.get(active.target_release, active.target_release)} · {active.deployment}").classes("meta")
                ui.label("Settings for this workspace").classes("kpi-label mt-3")
                kind = ui.select({"customer": "Customer workspace (product)", "internal": "Internal library (InfraBeat)"}, value=active.kind, label="Kind").props("outlined dense").classes("w-full")
                cust = ui.input("Customer / origin", value=active.customer).props("outlined dense").classes("w-full")
                mode = ui.select({"normal": "Normal - AI optional, everything masked", "strict": "Strict - AI switched off entirely"}, value=active.ai_mode, label="AI mode").props("outlined dense").classes("w-full")
                rel = ui.select(RELEASE_LABELS, value=active.target_release if active.target_release in RELEASE_LABELS else "2023", label="Assessment target release (rule variant)").props("outlined dense").classes("w-full")
                dep = ui.select({"onprem": "On-premise / private cloud", "cloud": "S/4HANA Cloud (Clean Core mandatory)"}, value=active.deployment, label="Deployment").props("outlined dense").classes("w-full")

                def save() -> None:
                    data.update_workspace(kind=kind.value, customer=cust.value, ai_mode=mode.value, target_release=("cloud" if rel.value == "cloud" else rel.value), deployment=("cloud" if rel.value == "cloud" else dep.value))
                    ui.notify("Workspace settings saved. Re-run Assess (Jobs & Pipeline) to apply a changed target release.", type="positive", timeout=6000)
                    ui.navigate.to("/workspaces")

                ui.button("Save", icon="save", on_click=save).props("unelevated").classes("mt-2")
                with ui.expansion("Strict mode - what it means", icon="lock").classes("w-full mt-2").props("dense"):
                    ui.label("No provider is ever constructed; the Ask, Review and Describe-with-AI functions are hidden; the egress ledger stays empty. Every analysis, verdict, estimate, business case and document still works - they never needed AI.").classes("text-sm")
            with ui.element("div").classes("tile flex-1 min-w-[26rem]"):
                ui.label("Switch workspace").classes("section-title")
                grid = "grid-template-columns: minmax(0,1fr) 6rem 5rem 8rem 6rem; column-gap:.75rem; row-gap:.4rem; align-items:center"
                with ui.element("div").classes("grid w-full mt-2").style(grid):
                    for h in ("Workspace", "Kind", "AI", "Target", ""):
                        ui.label(h).classes("kpi-label")
                    for w in data.workspaces():
                        ui.label(w.name + ("  ← active" if w.slug == active.slug else "")).classes("text-sm" + (" font-bold" if w.slug == active.slug else ""))
                        ui.label(w.kind).classes("text-sm"); ui.html(f'<span class="tag {"" if w.strict else "neutral"}">{escape(w.ai_mode)}</span>'); ui.label(RELEASE_LABELS.get(w.target_release, w.target_release)).classes("meta")
                        if w.slug != active.slug:
                            def _sw(slug=w.slug) -> None:
                                data.switch_workspace(slug)
                                ui.notify(f"Switched to {slug}", type="positive")
                                ui.navigate.to("/")
                            ui.button("Use", on_click=_sw).props("dense flat")
                        else:
                            ui.label("")
                ui.label("Create a workspace").classes("section-title mt-4")
                nname = ui.input("Name (e.g. ACME Retail)").props("outlined dense").classes("w-full")
                nkind = ui.select({"customer": "Customer workspace", "internal": "Internal library"}, value="customer", label="Kind").props("outlined dense").classes("w-full")
                nmode = ui.select({"normal": "Normal AI mode", "strict": "Strict - AI off"}, value="normal", label="AI mode").props("outlined dense").classes("w-full")
                nrel = ui.select(RELEASE_LABELS, value="2023", label="Target release").props("outlined dense").classes("w-full")

                def create() -> None:
                    if not (nname.value or "").strip():
                        ui.notify("Give the workspace a name", type="warning")
                        return
                    try:
                        info = data.create_workspace(nname.value, nkind.value, nname.value if nkind.value == "customer" else "", nmode.value, "cloud" if nrel.value == "cloud" else nrel.value, "cloud" if nrel.value == "cloud" else "onprem")
                    except Exception as error:      # noqa: BLE001
                        ui.notify(str(error), type="negative")
                        return
                    ui.notify(f"Workspace {info.name} created and activated - upload an abapGit export on Jobs & Pipeline", type="positive", timeout=6000)
                    ui.navigate.to("/jobs")

                ui.button("Create and switch", icon="add", on_click=create).props("unelevated").classes("mt-2")

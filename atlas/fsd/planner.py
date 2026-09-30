"""Plan the development that the FSD still needs.

Three outputs, all deterministic and explainable:
  pattern     the solution shape (ALV report, OData/RAP service, BAPI wrapper
              class, workflow, background job...) derived from the requirement
              mix and the knowledge-base intents
  flow        ordered implementation steps, each with the SAP building blocks
              (BAPIs, FMs, classes, CDS, tables) and the requirements it serves
  objects     suggested objects to create/extend with naming, plus utilities
              already in the repository that should be reused

Building blocks the FSD itself names (BAPIs, tables, custom objects) come
first in every step and are marked "named in the FSD"; the knowledge base only
adds what the FSD does not say. Design alternatives a senior architect would
raise (standard replication instead of custom code, bgRFC instead of a
hand-written queue...) are listed separately so the ABAPer can challenge the
FSD before building.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from atlas.fsd.knowledge import INTENTS
from atlas.fsd.matcher import ReqResult, ReuseCandidate
from atlas.search.engine import SearchEngine

INTENT_BY_ID = {i.id: i for i in INTENTS}


@dataclass
class Step:
    n: int
    title: str
    detail: str
    blocks: list[dict] = field(default_factory=list)      # {name, kind, purpose} - each block appears in ONE step only
    requirements: list[str] = field(default_factory=list)
    reuse: str = ""                                        # existing object that already does this
    addresses: list[dict] = field(default_factory=list)   # {id, text, kind} - the FSD statements this step implements


@dataclass
class PlannedObject:
    name: str
    type: str
    purpose: str
    action: str          # create | extend | reuse
    steps: list[int] = field(default_factory=list)      # plan steps this object implements
    blocks: list[str] = field(default_factory=list)     # BAPIs / FMs / classes / tables it uses (from those steps)


@dataclass
class Plan:
    pattern: str
    pattern_reason: str
    steps: list[Step]
    objects: list[PlannedObject]
    utilities: list[dict]              # existing helpers found in the repository
    effort_hours: float
    effort_breakdown: dict[str, float]
    s4_notes: list[str]
    test_scenarios: list[str]
    alternatives: list[str] = field(default_factory=list)   # design options to raise before building
    fsd_blocks: list[dict] = field(default_factory=list)    # BAPIs / tables / objects the FSD names


# (search query, purpose, trigger words in the FSD, tag/description words the object must carry)
UTILITY_QUERIES = [
    ("application log wrapper", "logging", ("log", "error"), ("application log", "logging", "bal_")),
    ("exception class", "exceptions", ("error", "exception", "validation"), ("exception",)),
    ("http client rest api call", "outbound HTTP/REST", ("http", "rest", "bank api", "web service"), ("http", "rest", "api")),
    ("send email attachment", "e-mail", ("email", "e-mail", "notif"), ("email", "e-mail", "mail", "bcs")),
    ("excel download upload", "Excel / file", ("excel", "xlsx", "file"), ("excel", "file", "xlsx")),
    ("date conversion utility", "date helpers", ("date", "due"), ("date",)),
]


def _module(results: list[ReqResult], fsd_module: str) -> str:
    if fsd_module:
        return fsd_module
    mods = Counter()
    for r in results:
        for i in r.intents:
            it = INTENT_BY_ID.get(i)
            if it and it.module not in ("BC",):
                mods[it.module[:2]] += r.weight
    return mods.most_common(1)[0][0] if mods else "CA"


_TITLE_STOP = {"fsd", "functional", "specification", "document", "for", "the", "and", "with", "from", "of", "a", "an", "to", "in", "on", "enhancement", "requirement",
               "requirements", "interface", "api", "bapi", "using", "via", "system", "systems", "new", "sap", "s", "4hana", "s4hana", "hana", "master", "data", "management"}


def _topic(title: str, business_intents: list[str], exclude: list[str] | None = None) -> str:
    """Short business name for planned objects: the dominant intent's topic (BP_CHANGE, SO_CREATE...),
    else two meaningful words from the title (never a customer/system name)."""
    for i in business_intents:
        it = INTENT_BY_ID.get(i)
        if it and it.topic:
            return it.topic
    bad = {w.lower() for term in (exclude or []) for w in re.findall(r"[A-Za-z]+", term)}
    words = [w for w in re.findall(r"[A-Za-z]+", title) if w.lower() not in _TITLE_STOP and w.lower() not in bad and len(w) > 1]
    words = words[:2]
    return "_".join(w.upper()[:8] for w in words) or "SOLUTION"


def _pattern(results: list[ReqResult], intents: Counter) -> tuple[str, str]:
    kinds = Counter(r.kind for r in results)
    top = [i for i, _ in intents.most_common(4)]
    ids = set(intents)
    text = " ".join(r.text.lower() for r in results)
    sync_hits = sum(1 for r in results if any(i in r.intents for i in ("bp_change", "tech_replication", "tech_change_trigger")))
    if ("bp_change" in ids or "tech_replication" in ids) and (sync_hits >= 2 or kinds["integration"] >= 3) and "tech_workflow" not in top:
        return ("Change replication: trigger (BAdI / change documents) → outbound API class (proxy / OData) → status table with retry job → reconciliation report",
                "The FSD keeps master data in sync between two systems: detect the change, call the target's standard API, make failures visible and retryable, and prove consistency with a reconciliation report.")
    workflow_reqs = sum(1 for r in results if "tech_workflow" in r.intents or "mm_po_release" in r.intents)
    if workflow_reqs >= 2 and ("tech_workflow" in top or "mm_po_release" in top):
        return ("SAP Business Workflow (flexible workflow scenario) + approval class + history report",
                "The FSD describes approvals, work items, escalation and rejection - that is a workflow, not a report.")
    outbound = sum(text.count(k) for k in ("call the", "calls the", "bank api", "rest api", "consume", "send to", "third party", "external api", "host-to-host", "response shall"))
    inbound = sum(text.count(k) for k in ("exposed as", "expose", "odata service", "calls in real time", "inbound", "payload will", "sap must return", "return to"))
    if kinds["integration"] >= 2 and outbound > inbound:
        return ("Outbound integration class (CL_HTTP_CLIENT via SM59 destination) + configuration table + background job + monitoring ALV",
                "The FSD consumes an external API: isolate the HTTP call, encryption and mapping in one class, keep endpoint and credentials in SM59/secure store, schedule it and give support a monitor.")
    if "tech_odata" in ids or kinds["integration"] >= 3:
        return ("API class (business logic) + OData service (RAP or SEGW) + configuration table",
                "Several integration requirements: expose the logic as a service and keep mapping/config outside code.")
    if kinds["output"] >= 3 or "tech_alv" in ids:
        if "tech_batch" in ids or kinds["scheduling"]:
            return ("ALV report (CL_SALV_TABLE) with e-mail/background mode + configuration table",
                    "Output-heavy requirements with a scheduled run: one report that displays online and sends in background.")
        return ("ALV report (CL_SALV_TABLE) with selection screen", "Output-heavy requirements with a selection screen.")
    if any(i.startswith(("sd_", "mm_", "fi_")) and "read" not in i for i in ids):
        return ("Utility class wrapping the standard BAPI(s) + calling program/service",
                "The core requirement posts or changes SAP documents; wrap the BAPI once and call it from the entry point.")
    return ("ABAP class with a thin program/service entry point", "Default structure: logic in a class, UI/trigger separate.")


_KB_ADVICE = {   # what the knowledge base says about BAPIs an FSD tends to name
    "BAPI_BUPA_CHANGE": "Does not exist as such - the change BAPIs are per data area: BAPI_BUPA_CENTRAL_CHANGE, BAPI_BUPA_ADDRESS_CHANGE, BAPI_BUPA_BANKDETAIL_CHANGE",
    "BAPI_BUPA_GETDETAIL": "Use BAPI_BUPA_CENTRAL_GETDETAIL / BAPI_BUPA_ADDRESSES_GET / BAPI_BUPA_ROLES_GET (no single GETDETAIL exists)",
    "BAPI_BUPA_GETLIST": "Use BAPI_BUPA_SEARCH_2 or a CDS/SELECT on BUT000 with change date",
    "BAPI_BUPA_ROLE_ASSIGN": "Does not exist - use BAPI_BUPA_ROLE_ADD_2 (check with BAPI_BUPA_ROLE_EXISTENCE_CHECK first)",
    "BAPI_BUPA_ADDRESS_CHANGE": "Needs the ADDRESSGUID from BAPI_BUPA_ADDRESSES_GET; fill ADDRESSDATA_X",
    "CDHDR": "Change document header - filter OBJECTCLAS = 'BUPA' and UDATE/UTIME greater than the last run",
    "CDPOS": "Changed fields per change document - decide which fields trigger replication",
    "API_BUSINESS_PARTNER": "Released OData V2 API on the target; PATCH A_BusinessPartner / A_BusinessPartnerAddress, use ETag / If-Match",
}


def fsd_named_blocks(doc_entities: dict[str, list[str]]) -> list[dict]:
    """Blocks for everything the FSD names itself, with the knowledge base's comment where it has one."""
    out: list[dict] = []
    for name in doc_entities.get("functions", []):
        kind = "BAPI" if name.startswith("BAPI_") else "API" if name.startswith("API_") else "FM"
        out.append({"name": name, "kind": f"{kind} (named in the FSD)", "purpose": _KB_ADVICE.get(name, "Specified by the FSD - verify signature and release status (SE37 / API Business Hub)")})
    for name in doc_entities.get("tables", []):
        out.append({"name": name, "kind": "table (named in the FSD)", "purpose": _KB_ADVICE.get(name, "Read/written per the FSD")})
    for name in doc_entities.get("custom_objects", []):
        out.append({"name": name, "kind": "custom object (named in the FSD)", "purpose": "Object name given by the FSD - create it under this name unless the naming standard says otherwise"})
    return out


def build_plan(title: str, results: list[ReqResult], reuse: list[ReuseCandidate], verdict: str, engine: SearchEngine, fsd_module: str = "",
               doc_entities: dict[str, list[str]] | None = None, exclude_terms: list[str] | None = None) -> Plan:
    doc_entities = doc_entities or {}
    intents: Counter = Counter()
    for r in results:
        for i in r.intents:
            intents[i] += r.weight
    pattern, reason = _pattern(results, intents)
    module = _module(results, fsd_module)
    by_kind: dict[str, list[ReqResult]] = {}
    for r in results:
        by_kind.setdefault(r.kind, []).append(r)
    named = fsd_named_blocks(doc_entities)
    named_fns = [b for b in named if "FSD" in b["kind"] and b["kind"].startswith(("BAPI", "API", "FM"))]
    named_tabs = [b for b in named if b["kind"].startswith("table")]
    named_custom = [b for b in named if b["kind"].startswith("custom")]

    def _base(name: str) -> str:
        m = re.match(r"([A-Z][A-Z0-9_]{3,})", name)             # "CL_BCS e-mail / ..." and "CL_BCS" are the same block
        return m.group(1) if m else re.split(r"\s*[(/]", name)[0].strip().upper()

    def blocks_for(*intent_ids: str, limit: int = 4, named_first: list[dict] | None = None, only=None) -> list[dict]:
        out, seen = [], set()
        for b in named_first or []:
            if _base(b["name"]) not in seen:
                seen.add(_base(b["name"]))
                out.append(b)
        for iid in intent_ids:
            it = INTENT_BY_ID.get(iid)
            if not it:
                continue
            for b in it.blocks:
                if b.purpose.lower().startswith("legacy"):
                    continue                                   # "legacy - avoid" entries are warnings, not blocks to build with
                if _base(b.name) not in seen and (only is None or only(b.name)):
                    seen.add(_base(b.name))
                    out.append({"name": b.name, "kind": b.kind, "purpose": b.purpose})
        return out[:limit]

    def is_read(n: str) -> bool:
        return any(f in n for f in ("GET", "SEARCH", "READ", "I_Business"))

    def named_matching(*fragments: str) -> list[dict]:
        return [b for b in named_fns if any(f in b["name"] for f in fragments)]

    def reuse_for(kind: str) -> str:
        for r in results:
            if r.kind == kind and r.status == "covered" and r.best:
                return r.best.name
        return ""

    business_intents = [i for i, _ in intents.most_common() if not i.startswith("tech_")]
    topic = _topic(title, business_intents, exclude_terms)
    if topic.startswith(module + "_"):          # ZCL_BP_CHANGE_SYNC, not ZCL_BP_BP_CHANGE_SYNC
        topic = topic[len(module) + 1:]

    steps: list[Step] = []
    used_blocks: set[str] = set()          # a building block is listed where it is first needed and nowhere else
    served: set[str] = set()               # a requirement is addressed by one step only

    def add(title: str, detail: str, blocks: list[dict], reqs: list[ReqResult], reuse_name: str = "") -> None:
        fresh = []
        for b in blocks:
            if _base(b["name"]) not in used_blocks:
                used_blocks.add(_base(b["name"]))
                fresh.append(b)
        mine = [r for r in reqs if r.id not in served]
        served.update(r.id for r in mine)
        steps.append(Step(len(steps) + 1, title, detail, fresh, [r.id for r in mine], reuse_name,
                          [{"id": r.id, "text": r.text, "kind": r.kind, "status": r.status} for r in mine]))

    def reqs_with(*intent_ids: str, words: tuple[str, ...] = ()) -> list[ReqResult]:
        return [r for r in results if any(i in r.intents for i in intent_ids) or any(w in r.text.lower() for w in words)]

    alternatives: list[str] = []

    # ---------------------------------------------------------------- replication pattern (own step list)
    if "Change replication" in pattern:
        # every requirement belongs to exactly ONE step: the most specific rule wins
        rules = [
            ("recon", ("tech_reconciliation",), ("reconcil", "compare", "discrepanc", "uniqueness", "consistency check")),
            ("retry", ("tech_retry",), ("retry", "attempt", "notify", "alert", "support team", "if failed")),
            ("tables", (), ("custom table", "status table", "mapping table", "z table")),
            ("schedule", (), ()),                                             # kind = scheduling without change-detection wording
            ("log", (), ("log the", "log success", "maintain logs", "logging", "slg1", "st22", "monitor", "error message", "error handling")),
            ("read", (), ("getdetail", "getlist", "extract current", "read ", "map to", "name fields", "custom fields", "classification", "direct mapping")),
            ("trigger", ("tech_change_trigger",), ("trigger", "detect", "delta", "on save", "real-time", "batch", "periodic", "event", "user updates", "is changed")),
            ("auth", (), ("authoriz", "authoris", "authentic", "oauth", "saml", "basic auth")),
            ("change", (), ()),                                               # everything else: the outbound change itself
        ]
        assigned: dict[str, list[ReqResult]] = {k: [] for k, _, _ in rules}
        for r in results:
            if r.kind == "scope":
                continue
            low = " " + r.text.lower() + " "
            for key, intent_ids, words in rules:
                by_kind_rule = (r.kind == "authorization" and key == "auth") or (r.kind == "data_model" and key == "tables") \
                    or (r.kind == "scheduling" and key == "schedule" and "detect" not in low and "reconcil" not in low)
                if by_kind_rule or any(i in r.intents for i in intent_ids) or any(w in low for w in words) or key == "change":
                    assigned[key].append(r)
                    break
        alternatives += [
            "Standard before custom: DRF replication model for BP (DRFOUT) or MDG-BP with the SOA service BusinessPartnerSUITEBulkReplicateRequest gives filters, change pointers, monitoring and key mapping without ABAP - ask why it is out of scope.",
            "If both systems are S/4HANA 1709+, the released OData API API_BUSINESS_PARTNER on the target (PATCH) is simpler to consume than a SOAP proxy and is ABAP-Cloud compatible.",
            "Do not call the target synchronously inside the BP save: record the change and send from a bgRFC/qRFC unit or a job so a network failure never blocks the user in transaction BP.",
            "Same BP number in both systems requires external numbering on the target or a key-mapping table - confirm with the functional consultant before design.",
        ]
        add("Change trigger in the source system",
            "Detect the BP change without touching the save transaction time: either a BAdI in the BP save sequence that writes the BP key into the status table, or a periodic delta read of CDHDR/CDPOS (OBJECTCLAS 'BUPA') since the last run. Real-time mode -> BAdI + bgRFC; batch/delta mode -> job over change documents. Only fields listed in the mapping table (4.2) should trigger.",
            blocks_for("tech_change_trigger", limit=6, named_first=named_tabs), assigned["trigger"])
        add("Authentication and authorization",
            "Source side: AUTHORITY-CHECK for the job user (B_BUPA_RLT / B_BUPA_GRP). Target side: technical user with the BP maintenance roles; credentials, OAuth/SAML/basic auth live in the SM59 destination / SOAMANAGER logical port, never in code.",
            blocks_for("tech_auth", "tech_proxy", limit=5), assigned["auth"], reuse_for("authorization"))
        add("Status / mapping tables",
            "Status table (BP key, changed fields hash, status, attempt count, last message, timestamps) drives retry and monitoring; mapping table for values that differ between systems (account groups, classifications, partner roles). SM30 views for both; change documents on the mapping table.",
            blocks_for("tech_custom_table", "tech_retry", limit=5, named_first=named_custom), assigned["tables"])
        add("Read the changed BP in the source",
            "Read only what changed: central data, addresses, roles and bank details via the BP read BAPIs (or CDS I_BusinessPartner / I_BusinessPartnerAddress). Build the outbound message from the mapping table; validate mandatory target fields before sending.",
            blocks_for("bp_change", limit=6, named_first=named_matching("GETDETAIL", "GETLIST", "SEARCH", "GET"), only=is_read), assigned["read"])
        add("Change the BP in the target",
            "One class method per data area calling the target's change API through the proxy / OData client: central data, address (needs ADDRESSGUID), roles (add only if missing), bank details; fill the *_X structures; COMMIT once; map BAPIRET2 back into the status table.",
            blocks_for("bp_change", "tech_proxy", limit=9, named_first=named_matching("CHANGE", "ROLE", "ADDRESS", "API_BUSINESS"), only=lambda n: not is_read(n) or "API_BUSINESS" in n), assigned["change"])
        add("Retry and alerting",
            "Technical failures (timeout, connection, HTTP 5xx) -> status 'retry', attempt+1, next run with back-off; application errors (E/A messages) -> status 'error', no automatic retry. After the last attempt e-mail the support distribution list with the BP key and message.",
            blocks_for("tech_retry", "tech_email", limit=6), assigned["retry"])
        add("Application log and monitoring",
            "Every attempt writes to the application log (SLG1 object/sub-object per the FSD) and updates the status table; a monitor ALV over the status table lets support see, filter and re-trigger items.",
            blocks_for("tech_log", "tech_alv", limit=5), assigned["log"], reuse_for("error_handling"))
        add("Reconciliation report",
            "Daily job: read the compared fields for the BPs changed in the period in both systems (remote read via RFC-enabled function or the released API), compare per field or by hash, list differences in ALV and e-mail them; write the run result to the application log for audit.",
            blocks_for("tech_reconciliation", "tech_batch", limit=6), assigned["recon"])
        add("Scheduling",
            "Jobs: delta/retry processor every N minutes (variant-driven, TVARVC last-run timestamp), reconciliation daily; Application Jobs catalogue entry in S/4.",
            blocks_for("tech_batch"), assigned["schedule"], reuse_for("scheduling"))
        add("Unit tests and handover",
            "ABAP Unit for the field mapping and the status transitions (test doubles for the proxy/BAPI calls); end-to-end test per sync mode; document object list, destinations, job variants and the support runbook (how to re-trigger a failed BP).", [], [])

    # 1 trigger / selection / entry point
    elif "Workflow" in pattern:
        add("Workflow trigger", "Raise the workflow from the document's change event (BAdI / class event on create-change) when the threshold condition is met; read thresholds and approvers from the configuration table; deadline monitoring for escalation.",
            blocks_for("tech_workflow", "mm_po_release", limit=6), [r for r in results if "tech_workflow" in r.intents or "mm_po_release" in r.intents][:4])
    if "Change replication" not in pattern:
        if by_kind.get("selection") or "tech_selection" in intents:
            add("Selection screen / entry point", "SELECT-OPTIONS and PARAMETERS per the FSD with OBLIGATORY where required, defaults in INITIALIZATION, validations in AT SELECTION-SCREEN. Keep everything variant-capable for the background run.",
                blocks_for("tech_selection"), by_kind.get("selection", []), reuse_for("selection"))
        elif "Workflow" not in pattern and by_kind.get("integration"):
            if "Outbound" in pattern:
                add("Integration entry point", "One class method per API operation: build request from SAP data, sign/encrypt, call via CL_HTTP_CLIENT with an SM59 destination (credentials there, not in code), parse the response into a typed structure.",
                    blocks_for("tech_odata", "fi_bank", limit=5), by_kind.get("integration", []), reuse_for("integration"))
            else:
                add("Service entry point", "Define the service (entity model, request/response structures) and keep the handler thin: parse payload → call the API class → map BAPIRET2 to the response.",
                    blocks_for("tech_odata"), by_kind.get("integration", []), reuse_for("integration"))
        elif "Workflow" not in pattern:
            add("Entry point", "Program or class method that receives the input and orchestrates the steps below.", [], [])

        # 2 authorization
        add("Authorization check", "AUTHORITY-CHECK before any data access; per org unit in the selection. Reject early with a clear message.",
            blocks_for("tech_auth"), by_kind.get("authorization", []), reuse_for("authorization"))

        # 3 configuration / data model
        if by_kind.get("data_model"):
            add("Configuration / custom table", "Create the Z table(s) the FSD asks for (MANDT key, data elements, delivery class C) with an SM30 maintenance view; read them once at start.",
                blocks_for("tech_custom_table", "tech_change_docs"), by_kind["data_model"], reuse_for("data_model"))

        # 4 data retrieval
        read_intents = [i for i in business_intents if i.endswith(("_read", "_open_items", "_items"))] or business_intents[:1]
        tables = sorted({t for r in results for t in r.entities.get("tables", [])} | {d for i in read_intents for d in INTENT_BY_ID[i].data[:3]})
        add("Data retrieval", "Read with ABAP SQL / CDS in one pass (no SELECT in LOOP), FOR ALL ENTRIES guarded by an emptiness check, only the fields needed. " + (f"Tables/views: {', '.join(tables[:10])}." if tables else ""),
            blocks_for(*read_intents[:2], named_first=named_matching("GET", "READ", "LIST", "SEARCH") + named_tabs), [r for r in results if r.kind in ("processing",) and any(k in r.text.lower() for k in ("read", "select", "fetch", "retrieve", "open items", "master"))], reuse_for("processing"))

        # 5 business logic / validations
        proc = [r for r in results if r.kind in ("processing", "validation") and r.id not in steps[-1].requirements]
        add("Business logic and validations", "One method per rule in the FSD (validations return BAPIRET2 / raise typed exceptions, never MESSAGE inside the class). Implement: " + "; ".join(f"{r.id} {r.text[:70]}…" if len(r.text) > 70 else f"{r.id} {r.text}" for r in proc[:6]) + ".",
            blocks_for("tech_validation", *business_intents[:1]), proc, reuse_for("processing") or reuse_for("validation"))

        # 6 posting / integration
        post_intents = [i for i in business_intents if not i.endswith(("_read", "_open_items"))]
        if post_intents or by_kind.get("integration"):
            add("Posting / integration", "Call the standard BAPI/API, evaluate RETURN (E/A = failure → BAPI_TRANSACTION_ROLLBACK), COMMIT once at the end; map custom fields via extension structures; log request/response.",
                blocks_for(*post_intents[:2], limit=8, named_first=[b for b in named_fns if not any(f in b["name"] for f in ("GET", "READ", "LIST", "SEARCH"))]), by_kind.get("integration", []) + [r for r in results if r.kind == "processing" and r not in proc], reuse_for("integration"))

        # 7 output
        if by_kind.get("output") or "tech_alv" in intents or "tech_email" in intents:
            blocks = blocks_for("tech_alv", "tech_email", "tech_excel_file", "tech_form", limit=6)
            add("Output", "ALV via CL_SALV_TABLE (layout, totals, Excel export come free); e-mail via CL_BCS with the list converted by CL_BCS_CONVERT; when running in background skip the display and send.",
                blocks, by_kind.get("output", []), reuse_for("output"))

        # 8 errors & log
        add("Error handling and application log", "Collect all messages, write to the application log (SLG1 object/sub-object) and return/display them; retries for technical failures where the FSD asks for them.",
            blocks_for("tech_log"), by_kind.get("error_handling", []), reuse_for("error_handling"))

        # 9 scheduling
        if by_kind.get("scheduling") or "tech_batch" in intents:
            add("Scheduling", "Variant with TVARVC/dynamic dates; job in SM36 (or Application Jobs catalogue in S/4); e-mail option forced in background.",
                blocks_for("tech_batch"), by_kind.get("scheduling", []), reuse_for("scheduling"))

        # 10 tests
        add("Unit tests and handover", "ABAP Unit for validations and mapping (test doubles for the BAPI calls); document the object list, transport and job variants.", [], [])


    # objects ---------------------------------------------------------------------------------
    objects: list[PlannedObject] = []
    for c in reuse[:2]:
        if c.coverage_pct >= 25:
            objects.append(PlannedObject(c.name, c.type, f"Covers {c.coverage_pct}% of the FSD (weighted); extend for the partial/missing requirements listed in the analysis.", "extend"))
    if verdict == "build" or not objects:
        if "Change replication" in pattern:
            objects += [PlannedObject(f"ZCL_{module}_{topic}_SYNC", "Class", "Outbound API: read changed BP, map, call the target's change BAPIs/API via proxy or OData client, return BAPIRET2", "create"),
                        PlannedObject(f"ZCL_{module}_{topic}_TRIGGER", "Class (BAdI implementation)", "Records the changed BP key/fields into the status table from the BP save sequence (or delta read of CDHDR/CDPOS)", "create"),
                        PlannedObject(f"ZCO_{module}_{topic}", "Consumer proxy (SPROXY) or HTTP client wrapper", "Generated from the target service; logical port in SOAMANAGER / destination in SM59", "create"),
                        PlannedObject(f"Z{module}_T_{topic}_STAT", "Table + SM30 view", "Status, attempt count, last message, next run per BP change", "create"),
                        PlannedObject(f"Z{module}_T_{topic}_MAP", "Table + SM30 view", "Value mapping between systems (account group, classification, roles)", "create"),
                        PlannedObject(f"Z{module}_{topic}_PROC", "Program (job)", "Delta / retry processor over the status table", "create"),
                        PlannedObject(f"Z{module}_{topic}_MON", "Program (ALV)", "Monitor: filter by status, re-trigger, show last message", "create"),
                        PlannedObject(f"Z{module}_{topic}_RECON", "Program (ALV, job)", "Reconciliation: compare source and target, e-mail differences", "create"),
                        PlannedObject(f"ZCX_{module}_{topic}", "Exception class", "Typed errors (technical vs application) with T100 messages", "create")]
        elif "Workflow" in pattern:
            objects += [PlannedObject(f"ZCL_{module}_{topic}_WF", "Class", "Workflow object class (IF_WORKFLOW): events, approver determination, release/reject methods", "create"),
                        PlannedObject(f"WS9{module[:1]}{topic[:4]}", "Workflow template / flexible scenario", "Approval steps, deadline (escalation) and notifications", "create"),
                        PlannedObject(f"Z{module}_T_{topic}_CFG", "Table + SM30 view", "Thresholds and approver determination", "create"),
                        PlannedObject(f"Z{module}_T_{topic}_LOG", "Table", "Approval decisions for audit (or use change documents)", "create"),
                        PlannedObject(f"Z{module}_{topic}_HIST", "Program (ALV)", "Approval history report with selection screen and Excel export", "create")]
        elif "Outbound integration" in pattern:
            objects += [PlannedObject(f"ZCL_{module}_{topic}", "Class", "Build request, encrypt/sign, call via CL_HTTP_CLIENT (SM59 destination), parse response, return messages", "create"),
                        PlannedObject(f"Z{module}_{topic}_JOB", "Program", "Background run over pending items with retry and application log", "create"),
                        PlannedObject(f"Z{module}_T_{topic}_STAT", "Table + SM30 view", "Status / retry count per item", "create"),
                        PlannedObject(f"Z{module}_{topic}_MON", "Program (ALV)", "Monitoring report", "create"),
                        PlannedObject(f"ZCX_{module}_{topic}", "Exception class", "Typed errors", "create")]
        elif "OData" in pattern:
            objects += [PlannedObject(f"ZCL_{module}_{topic}", "Class", "Business logic: validation, mapping, BAPI call, commit, return messages", "create"),
                        PlannedObject(f"Z{module}_{topic}_SRV", "OData service (RAP service definition/binding or SEGW project)", "Entity model + handler calling the class", "create"),
                        PlannedObject(f"Z{module}_T_{topic}_MAP", "Table + SM30 view", "Value mapping / configuration", "create"),
                        PlannedObject(f"ZCX_{module}_{topic}", "Exception class", "Typed errors with T100 messages", "create")]
        elif "ALV" in pattern:
            objects += [PlannedObject(f"Z{module}_{topic}", "Program (ALV report)", "Selection screen, authorization, ALV/e-mail output; logic delegated to the class", "create"),
                        PlannedObject(f"ZCL_{module}_{topic}", "Class", "Data retrieval, calculations (buckets/totals), e-mail sending", "create"),
                        PlannedObject(f"Z{module}_T_{topic}_CFG", "Table + SM30 view", "Configuration (buckets, distribution list...)", "create")]
        else:
            objects += [PlannedObject(f"ZCL_{module}_{topic}", "Class", "Business logic and BAPI wrapper", "create"),
                        PlannedObject(f"Z{module}_{topic}", "Program", "Entry point / test harness", "create")]
        objects.append(PlannedObject(f"Z{module}_{topic[:8]}_MSG", "Message class", "All user-facing messages (translatable)", "create"))
        for name in doc_entities.get("custom_objects", []):
            if not any(o.name == name for o in objects):
                kind = "Table" if re.search(r"_(ST|STAT|LOG|T|TAB|CFG|MAP)\d*$", name) or "_T_" in name else "Object"
                objects.append(PlannedObject(name, f"{kind} (named in the FSD)", "Name given by the FSD - use it (or map it to the object above that plays this role) so the FSD and the build stay aligned", "create"))

    # utilities already in the repo ---------------------------------------------------------------
    utilities = []
    wanted_text = " ".join(r.text.lower() for r in results)
    candidate_names = {c.name for c in reuse}
    for query, purpose, triggers, markers in UTILITY_QUERIES:
        if not any(t in wanted_text for t in triggers):
            continue
        for hit in engine.search(query, limit=3, mode="keyword"):
            o = hit.object
            haystack = (" ".join(o.tags or []) + " " + o.short_text).lower()
            if o.obj_type in ("CLAS", "FUGR", "INTF") and o.name not in candidate_names and hit.score >= 60 and any(m in haystack for m in markers):
                utilities.append({"id": o.id, "name": o.name, "type": hit.type_label, "purpose": purpose, "short_text": o.short_text or o.description[:90]})
                break
    seen = set()
    utilities = [u for u in utilities if not (u["name"] in seen or seen.add(u["name"]))]
    for u in utilities:
        objects.append(PlannedObject(u["name"], u["type"], f"Reuse for {u['purpose']}", "reuse"))

    # which steps (and therefore which BAPIs / tables / classes) each planned object implements ------
    def steps_titled(*words: str) -> list[int]:
        return [st.n for st in steps if any(w.lower() in st.title.lower() for w in words)]

    role_steps = {
        "_SYNC": steps_titled("Read the changed", "Change the BP"), "_TRIGGER": steps_titled("Change trigger"), "ZCO_": steps_titled("Authentication"),
        "_STAT": steps_titled("Status / mapping"), "_MAP": steps_titled("Status / mapping", "Configuration"), "_PROC": steps_titled("Retry", "Scheduling"),
        "_MON": steps_titled("Application log"), "_RECON": steps_titled("Reconciliation"), "ZCX_": steps_titled("Application log", "Error handling"),
        "_MSG": [], "_SRV": steps_titled("Service entry", "Integration entry"), "_JOB": steps_titled("Scheduling", "Posting"), "_HIST": steps_titled("Output"),
        "_CFG": steps_titled("Configuration", "Workflow trigger"), "_LOG": steps_titled("Error handling"), "_WF": steps_titled("Workflow trigger", "Business logic"),
        "WS9": steps_titled("Workflow trigger"),
    }
    by_n = {st.n: st for st in steps}
    # for the replication pattern the ABAPer gets the exact API list per object; other patterns derive it from the steps
    explicit = {
        "_SYNC": ["BAPI_BUPA_CENTRAL_GETDETAIL", "BAPI_BUPA_ADDRESSES_GET", "BAPI_BUPA_ROLES_GET", "BAPI_BUPA_CENTRAL_CHANGE", "BAPI_BUPA_ADDRESS_CHANGE",
                  "BAPI_BUPA_ROLE_ADD_2", "BAPI_BUPA_ROLE_EXISTENCE_CHECK", "BAPI_TRANSACTION_COMMIT", f"ZCO_{module}_{topic} (or API_BUSINESS_PARTNER via CL_HTTP_CLIENT)"],
        "_TRIGGER": ["BAdI BUPA_GENERAL_UPDATE / BUPA_FURTHER_CHECKS", "CDHDR / CDPOS (OBJECTCLAS 'BUPA') delta read", "event BUS1006.CHANGED (SWEC)", f"Z{module}_T_{topic}_STAT (insert key)"],
        "ZCO_": ["SPROXY consumer proxy from the target WSDL", "SOAMANAGER logical port", "SM59 destination (type G/H)", "CL_HTTP_CLIENT + /UI2/CL_JSON if the target exposes API_BUSINESS_PARTNER"],
        "_STAT": ["SE11 table + SM30 view (SE54)", "CHANGEDOCUMENT_* for audit", "TVARVC last-run timestamp"],
        "_MAP": ["SE11 table + SM30 view (SE54)"],
        "_PROC": [f"Z{module}_T_{topic}_STAT (SELECT status = retry / new)", f"ZCL_{module}_{topic}_SYNC", "CL_BCS (alert mail after last attempt)", "SM36 job with variant / TVARVC"],
        "_MON": [f"Z{module}_T_{topic}_STAT", "CL_SALV_TABLE", f"ZCL_{module}_{topic}_SYNC (re-trigger)", "BAL_DSP_LOG_DISPLAY"],
        "_RECON": ["BAPI_BUPA_CENTRAL_GETDETAIL (local)", f"ZCO_{module}_{topic} / RFC read of the target", "CL_ABAP_MESSAGE_DIGEST (hash compare)", "CL_SALV_TABLE", "CL_BCS", "BAL_LOG_CREATE / BAL_LOG_MSG_ADD / BAL_DB_SAVE"],
        "ZCX_": ["CX_STATIC_CHECK", "IF_T100_MESSAGE", f"Z{module}_{topic[:8]}_MSG"],
        "_MSG": ["SE91 message class"],
    }
    for o in objects:
        if o.action == "reuse" or o.steps:
            continue
        key = next((k for k in role_steps if (o.name.startswith(k) if k.endswith("_") else o.name.endswith(k))), None)
        hit = role_steps.get(key, []) if key else []
        if not hit:
            if o.type.startswith("Class"):
                hit = steps_titled("Data retrieval", "Business logic", "Posting", "Change the BP", "Read the changed")
            elif "ALV" in o.type or "report" in o.type.lower():
                hit = steps_titled("Selection", "Output")
            elif o.type.startswith("Table"):
                hit = steps_titled("Configuration", "Status / mapping")
        o.steps = sorted(set(hit))
        if "Change replication" in pattern and key in explicit:
            o.blocks = explicit[key]
        elif "Change replication" in pattern and "named in the FSD" in o.type:
            o.blocks = [f"same role as Z{module}_T_{topic}_STAT - the FSD's name for the status/log table"]
        elif o.type.startswith("Table"):
            o.blocks = ["SE11 table + SM30 maintenance view (SE54)", "CHANGEDOCUMENT_* if the content must be audited"]
        elif o.type.startswith("Message"):
            o.blocks = ["SE91 message class"]
        elif o.type.startswith("Exception"):
            o.blocks = ["CX_STATIC_CHECK", "IF_T100_MESSAGE"]
        else:
            names: list[str] = []
            for n in o.steps:
                for b in by_n[n].blocks:
                    if b["kind"].split(" (")[0] in ("BAPI", "FM", "class", "table", "CDS", "BAdI", "API") and b["name"] not in names:
                        names.append(b["name"])
            o.blocks = names[:8]

    # effort ------------------------------------------------------------------------------------
    breakdown: dict[str, float] = {}
    for r in results:
        breakdown[r.kind] = round(breakdown.get(r.kind, 0.0) + r.effort_hours, 1)
    breakdown = {k: v for k, v in breakdown.items() if v > 0}
    dev = sum(breakdown.values())
    breakdown["technical design & unit tests (20%)"] = round(dev * 0.2, 1)
    if "Workflow" in pattern:
        breakdown["workflow template & agent determination"] = 12.0
    if "Change replication" in pattern:
        breakdown["proxy generation, destinations & connectivity test"] = 8.0
    total = round(sum(breakdown.values()), 1)

    s4_notes = sorted({rm for i in intents for rm in INTENT_BY_ID[i].remarks if i in INTENT_BY_ID})[:8]
    tests = [f"{r.id}: {r.text[:90]}" for r in results if r.kind in ("validation", "processing", "integration")][:8]
    if alternatives:
        s4_notes = [n for n in s4_notes if not n.startswith(("Before building", "Check the standard"))]   # said once, in the alternatives
    where: dict[str, str] = {}
    for st in steps:
        for b in st.blocks:
            where.setdefault(_base(b["name"]), f"step {st.n}")
    for b in named:
        b["used_in"] = where.get(_base(b["name"]), "")
    return Plan(pattern, reason, steps, objects, utilities, total, breakdown, s4_notes, tests, list(dict.fromkeys(alternatives)), named)

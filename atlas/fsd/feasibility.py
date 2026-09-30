"""Feasibility and complexity of a specification, from what the analysis already knows.

The verdict (reuse / extend / build) says whether code exists. This module answers the
questions an architecture board asks next:

  complexity   S / M / L / XL from measurable drivers (detailed statements, integration
               steps, systems involved, distinct SAP intents, custom tables, mapping rows,
               workflow / replication patterns)
  feasibility  Feasible / Feasible with changes / Needs clarification / Not feasible as
               written - with the reasons: named objects that do not exist in standard SAP,
               synchronous remote calls inside a save, direct updates of standard tables,
               modifications of SAP objects, missing non-functional data
  quality      0-100 score for the FSD itself: which topics it covers (authorization, error
               handling, volumes/performance, scheduling, mapping, acceptance/test data),
               how many statements are testable (shall/must/will), how many are vague
  questions    the clarification list for the functional consultant, generated from the gaps
  confidence   how much of the estimate rests on recognised SAP patterns
  rice         RICEFW classification (Report / Interface / Conversion / Enhancement /
               Form / Workflow)

Everything is deterministic and explainable - each line carries the statement or fact it
comes from - so the card can be defended in front of a client. The AI review can
elaborate on it but never changes it.
"""

from __future__ import annotations

import re

VAGUE = re.compile(r"\b(etc\.?|e\.g\.|as needed|as required|appropriate|properly|correctly|relevant|necessary|some|various|and so on|tbd|to be decided|to be defined)\b", re.I)
MODAL = re.compile(r"\b(shall|must|will|should|needs? to|required|has to|have to)\b", re.I)

_STANDARD_TABLES_WRITE = re.compile(r"\b(update|insert|modify|delete|write|change)\b[^.]{0,40}\b(KNA1|LFA1|BUT000|BUT020|ADRC|MARA|VBAK|VBAP|EKKO|EKPO|BKPF|BSEG|ACDOCA|LIKP|LIPS|VBRK|VBRP|MSEG|MKPF|T001|T001W)\b", re.I)
_MODIFICATION = re.compile(r"\b(modif(?:y|ication)|change)\b[^.]{0,30}\b(standard (?:program|report|function|class|include|code|table|object)|sap standard|sap (?:program|report|class|function module))\b", re.I)
_SYNC_ON_SAVE = re.compile(r"\b(on save|when saved|after save|during save|in the save|upon save|immediately (?:on|after|when) sav)\b", re.I)
_REALTIME = re.compile(r"\b(real[- ]time|on save|when saved|event[- ]driven|immediately)\b", re.I)
_REMOTE = re.compile(r"\b(api|bapi|proxy|odata|rfc|web service|soap|http|target system|remote|external system|third[- ]party|salesforce|bank)\b", re.I)
_OUTBOUND = re.compile(r"\b(call|calls|send|sends|push|propagate|transfer|post to|trigger(?:s|ed)? an? (?:api|bapi|call)|sync(?:hroni[sz]e)? .* to)\b", re.I)
_INTERFACE_INTENTS = {"tech_http", "tech_odata", "tech_proxy", "tech_idoc", "tech_replication", "fi_bank", "bp_change", "tech_file"}


def _band(score: float, bands: tuple[int, int, int]) -> str:
    s, m, l = bands
    return "S" if score < s else "M" if score < m else "L" if score < l else "XL"


def assess(payload: dict) -> dict:
    reqs = payload.get("requirements") or []
    plan = payload.get("plan") or {}
    detailed = [r for r in reqs if r.get("kind") != "scope"]
    kinds = {}
    for r in detailed:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    texts = " ".join(r["text"] for r in reqs)
    low = texts.lower()
    intents = {(i["id"] if isinstance(i, dict) else i) for r in reqs for i in (r.get("intents") or [])}
    steps = plan.get("steps") or []
    pattern = plan.get("pattern", "")
    entities = payload.get("entities") or {}

    # ------------------------------------------------------------------ complexity
    drivers: list[tuple[str, int]] = []
    n = len(detailed)
    drivers.append((f"{n} detailed statements", 3 if n > 25 else 2 if n > 15 else 1 if n > 8 else 0))
    integ = kinds.get("integration", 0)
    drivers.append((f"{integ} integration statements", 3 if integ > 8 else 2 if integ > 4 else 1 if integ > 1 else 0))
    systems = len({m.group(0).lower() for m in re.finditer(r"\b(source system|target system|salesforce|bank|third[- ]party|external system|pi/po|cpi|event mesh)\b", low)})
    drivers.append((f"{systems} external system(s) / boundaries", min(3, systems)))
    drivers.append((f"{len(intents)} distinct SAP topics", 2 if len(intents) > 8 else 1 if len(intents) > 4 else 0))
    custom = len(entities.get("custom_objects") or [])
    drivers.append((f"{custom} custom object(s) named", 1 if custom else 0))
    mapping = kinds.get("mapping", 0)
    drivers.append((f"{mapping} field-mapping rows", 1 if mapping > 3 else 0))
    if "replication" in pattern.lower():
        drivers.append(("cross-system replication with retry and reconciliation", 3))
    elif "workflow" in pattern.lower():
        drivers.append(("workflow with agent determination and deadlines", 2))
    elif "api" in pattern.lower() or "odata" in pattern.lower() or "service" in pattern.lower():
        drivers.append(("exposed / consumed service", 1))
    if kinds.get("authorization", 0) and "oauth" in low or "saml" in low or "certificate" in low:
        drivers.append(("federated authentication (OAuth / SAML / certificates)", 1))
    score = sum(p for _, p in drivers)
    complexity = {"band": _band(score, (4, 9, 18)), "score": score, "drivers": [d for d, p in drivers if p > 0]}

    # ------------------------------------------------------------------ feasibility
    blockers: list[str] = []      # -> not feasible as written
    changes: list[str] = []       # -> feasible with changes
    risks: list[str] = []
    for b in plan.get("fsd_blocks") or []:
        purpose = (b.get("purpose") or "")
        if purpose.lower().startswith(("does not exist", "use bapi_bupa_central_getdetail", "use bapi_bupa_search")):
            changes.append(f"The FSD names `{b['name']}`, which does not exist in standard SAP - {purpose.split(' - ')[-1] if ' - ' in purpose else purpose}")
    for r in detailed:
        t = r["text"]
        if _MODIFICATION.search(t):
            blockers.append(f"{r['id']}: modification of SAP standard objects is requested - not Clean-Core compliant; use enhancement/BAdI or a copy under Z")
        if _STANDARD_TABLES_WRITE.search(t):
            blockers.append(f"{r['id']}: direct write to a standard table - only through the released API / BAPI")
        if _SYNC_ON_SAVE.search(t) and _REMOTE.search(t) and _OUTBOUND.search(t):
            changes.append(f"{r['id']}: remote call inside the save / real-time path - decouple with bgRFC, qRFC or a queue so a network failure never blocks the user")
    if "replication" in pattern.lower():
        risks.append("Same keys in two systems need external numbering or key mapping - confirm before design")
        risks.append("SAP standard replication (DRF / MDG / SOA) covers this scenario - custom build must justify why it is not used")
    if integ and not kinds.get("error_handling"):
        risks.append("Integration without an error-handling section: define retry, alerting and reprocessing")
    nfr_missing: list[str] = []
    if not kinds.get("performance") and not re.search(r"\b(\d[\d,.]*\s*(records|bps?|business partners|orders|documents|items|messages|per (day|hour|minute))|volume|throughput|sla|response time)\b", low):
        nfr_missing.append("expected volumes and response-time / SLA expectations")
    if not kinds.get("authorization"):
        nfr_missing.append("authorization objects / roles for users and technical users")
    if not kinds.get("error_handling"):
        nfr_missing.append("error handling, monitoring and reprocessing")
    if integ and not kinds.get("scheduling") and not _REALTIME.search(texts):
        nfr_missing.append("trigger / frequency (real-time, scheduled, event)")

    # ------------------------------------------------------------------ FSD quality
    topics = {
        "authorization": bool(kinds.get("authorization")),
        "error handling": bool(kinds.get("error_handling")),
        "volumes / performance": "expected volumes" not in " ".join(nfr_missing),
        "trigger / scheduling": bool(kinds.get("scheduling")) or bool(_REALTIME.search(texts)) or not integ,
        "field mapping": bool(kinds.get("mapping")) or not integ,
        "validation rules": bool(kinds.get("validation")),
        "acceptance / test data": bool(re.search(r"\b(test (data|case|scenario)|acceptance|uat|expected result)\b", low)),
        "named SAP objects": bool(entities.get("functions") or entities.get("tables")),
    }
    testable = sum(1 for r in detailed if MODAL.search(r["text"]) or r.get("entities", {}).get("functions") or r.get("entities", {}).get("tables"))
    vague = [r for r in detailed if VAGUE.search(r["text"])]
    scope_share = (len(reqs) - len(detailed)) / max(1, len(reqs))
    quality = round(100 * (0.5 * sum(topics.values()) / len(topics) + 0.3 * (testable / max(1, n)) + 0.2 * (1 - len(vague) / max(1, n)))) if n else 0
    quality = max(0, min(100, quality - (10 if scope_share > 0.4 else 0)))

    # ------------------------------------------------------------------ questions
    questions: list[str] = []
    for miss in nfr_missing:
        questions.append(f"Please specify {miss}.")
    missing_apis = [c.split("`")[1] for c in changes if "does not exist" in c and "`" in c]
    if missing_apis:
        questions.append(f"The FSD names APIs that do not exist in standard SAP ({', '.join(missing_apis)}) - confirm the replacements proposed in the plan are acceptable.")
    for c in changes:
        if c.startswith("R") and "decouple" in c:
            questions.append(f"{c.split(':')[0]}: is a real-time call acceptable if it is asynchronous (queued within seconds), or must the user wait for the target's confirmation?")
    for r in vague[:5]:
        questions.append(f"{r['id']} uses open wording (\"{VAGUE.search(r['text']).group(0)}\") - please list the exact values / cases: \"{r['text'][:90]}\"")
    if scope_share > 0.3:
        questions.append("Several statements are scope-level only; confirm the detailed rows cover everything the scope implies (nothing hidden behind 'etc.').")
    if "replication" in pattern.lower():
        questions.append("Should the standard replication (DRF / MDG / SOA) be evaluated first, and why is it out of scope?")
        questions.append("Are BP numbers identical in both systems (external numbering), or is a key mapping needed?")
    if any("workflow" in i for i in intents):
        questions.append("Who are the approvers per level (org unit, role, amount limit) and what happens on deadline (escalate / auto-approve / reject)?")

    # ------------------------------------------------------------------ verdict
    if blockers:
        verdict, colour = "Not feasible as written", "negative"
    elif changes:
        verdict, colour = "Feasible with changes", "warning"
    elif len(nfr_missing) >= 3 or scope_share > 0.4 or quality < 45:
        verdict, colour = "Needs clarification", "warning"
    else:
        verdict, colour = "Feasible", "positive"

    # ------------------------------------------------------------------ confidence & RICEFW
    recognised = sum(1 for r in detailed if r.get("intents"))
    conf_pct = round(100 * recognised / max(1, n))
    confidence = {"pct": conf_pct, "band": "high" if conf_pct >= 75 else "medium" if conf_pct >= 45 else "low",
                  "text": f"{recognised} of {n} detailed statements map to known SAP patterns; the effort for the rest is estimated from their kind only"}
    p = pattern.lower()
    if "workflow" in p:
        rice = "W - Workflow"
    elif "replication" in p or "interface" in p or "api" in p or "odata" in p or "http" in p or "proxy" in p or integ >= max(3, n // 3) or intents & _INTERFACE_INTENTS:
        rice = "I - Interface"
    elif "report" in p or "alv" in p or kinds.get("output", 0) >= 2:
        rice = "R - Report"
    elif "form" in p:
        rice = "F - Form"
    elif payload.get("verdict") in ("extend", "reuse"):
        rice = "E - Enhancement"
    else:
        rice = "E - Enhancement"

    return {
        "verdict": verdict, "colour": colour,
        "blockers": blockers, "changes": changes, "risks": risks, "missing_nfr": nfr_missing,
        "complexity": complexity,
        "quality": {"score": quality, "topics": topics, "testable": testable, "detailed": n, "vague": [r["id"] for r in vague], "scope_share": round(100 * scope_share)},
        "questions": list(dict.fromkeys(questions))[:12],
        "confidence": confidence,
        "rice": rice,
    }

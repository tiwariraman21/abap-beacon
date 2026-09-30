"""Match FSD requirements against the custom code repository.

For every requirement the hybrid search engine proposes candidate objects;
each candidate gets a confidence built from four signals that are all
explainable to the ABAPer:

  term coverage   how many of the requirement's meaningful words the object's
                  name / short text / description / components / tables contain
  semantic        embedding similarity from the meaning index
  entities        tables, BAPIs/FMs, custom objects the requirement names that
                  the object actually references (from the parser)
  component       a method / FM / field of the object matches the requirement

Requirements are then covered (>= 0.55), partial (>= 0.30) or missing, and
the objects that cover the most weighted requirements become the reuse
candidates. Coverage % is weighted by requirement kind (processing and
integration count more than a selection field).

A match needs a SPECIFIC signal before it can be partial or covered: an entity
the object really references (table / BAPI / custom object named in the
requirement), a matching method/FM, a hit on the object's name, or at least
one distinctive matched term (a word that fewer than a quarter of the
repository's objects use). Overlap on generic integration vocabulary alone
("system", "API", "call", "log", "change") never makes a match.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from atlas.db.models import SapObject
from atlas.fsd.knowledge import INTENTS, Intent, match_intents
from atlas.fsd.reader import Requirement
from atlas.ingest.types import get_type
from atlas.search.engine import SearchEngine, stem, tokenise

COVERED, PARTIAL = 0.55, 0.30

FSD_STOP = {
    "system", "shall", "should", "must", "will", "need", "needs", "required", "requirement", "user", "users", "able", "allow",
    "report", "data", "value", "values", "field", "fields", "table", "sap", "screen", "option", "options", "via", "per", "based",
    "following", "relevant", "selected", "selection", "set", "case", "shown", "show", "display", "displayed", "otherwise",
    "return", "returned", "error", "errors", "message", "messages", "also", "instead", "each", "every", "new", "existing",
    "current", "custom", "program", "logic", "process", "processing", "business", "team", "today", "manually", "automatically",
    "maintained", "maintainable", "details", "detail", "information", "result", "results", "list", "number", "numbers", "date",
    "time", "day", "days", "type", "status", "step", "steps", "well", "provided", "support", "supported",
    # generic integration / spec vocabulary - present in every interface FSD and every interface class
    "systems", "api", "apis", "bapi", "bapis", "change", "changes", "changed", "changing", "target", "source", "call", "calls", "called",
    "log", "logs", "logged", "logging", "integration", "integrate", "integrated", "interface", "interfaces", "sync", "synchronize", "synchronise",
    "synchronization", "synchronisation", "standard", "use", "used", "using", "uses", "exchange", "service", "services", "module", "modules",
    "e.g", "eg", "ensure", "appropriate", "proper", "properly", "correctly", "both", "across", "transaction", "code", "method", "function",
    "run", "runs", "daily", "mode", "modes", "real", "save", "saved", "saves", "immediately", "trigger", "triggered", "triggers", "extract", "master", "management", "manage",
    "related", "downstream", "same", "mapped", "direct", "directly", "successful", "failed", "fails", "failure", "failures", "if", "then",
    "when", "where", "which", "while", "with", "within", "without", "into", "onto", "from", "for", "and", "or", "not", "are", "is", "be",
    "the", "a", "an", "to", "of", "in", "on", "at", "by", "as", "it", "its", "this", "that", "these", "those", "s/4hana", "s4hana", "hana", "erp",
}
# generic terms that count as matched words but never as the *specific* signal
GENERIC_SIGNAL = {"customer", "vendor", "supplier", "partner", "document", "order", "item", "items", "header", "name", "address", "role", "roles",
                  "check", "checks", "create", "created", "update", "updated", "delete", "read", "send", "sent", "receive", "received", "post", "posted",
                  "valid", "validate", "validation", "mapping", "map", "job", "jobs", "batch", "background", "email", "mail", "file", "files"}
WEIGHTS = {"processing": 3, "integration": 3, "validation": 2, "output": 2, "data_model": 2, "selection": 1, "authorization": 1, "error_handling": 1, "performance": 1, "scheduling": 1, "mapping": 1, "scope": 1}


@dataclass
class Match:
    object_id: int
    name: str
    type: str
    short_text: str
    confidence: float
    term_coverage: float
    similarity: float
    entities: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    specific: bool = True            # has a signal beyond generic word overlap
    evidence: str = ""               # one line: why this object matched


@dataclass
class ReqResult:
    id: str
    text: str
    section: str
    kind: str
    weight: int
    entities: dict
    status: str                      # covered | partial | missing
    best: Match | None
    candidates: list[Match]
    intents: list[str]               # knowledge-base intent ids
    change: str                      # what the ABAPer has to do
    effort_hours: float


@dataclass
class ReuseCandidate:
    object_id: int
    name: str
    type: str
    short_text: str
    description: str
    coverage_pct: float
    covered: list[str]
    partial: list[str]
    missing: list[str]
    lines: int


def _key_stems(req: Requirement) -> list[str]:
    toks = [t for t in tokenise(req.search_text) if t not in FSD_STOP and not t.isdigit() and len(t) > 2]
    return list(dict.fromkeys(stem(t) for t in toks))


class Matcher:
    def __init__(self, session: Session, engine: SearchEngine, fsd_module: str = ""):
        self.session = session
        self.engine = engine
        self.fsd_module = fsd_module.upper()[:2] if fsd_module else ""
        self._docs = {o.id: d for o, d in zip(engine.objects, engine.docs)}
        self._objs = {o.id: o for o in engine.objects}
        # document frequency per stem -> "distinctive" = used by less than a quarter of the objects
        df: dict[str, int] = {}
        for d in engine.docs:
            for st in getattr(d, "all_stems", ()):
                df[st] = df.get(st, 0) + 1
        n = max(1, len(engine.docs))
        self._distinctive = {st for st, c in df.items() if c / n <= 0.25 and len(st) >= 4}
        self._stop_stems = {stem(t) for t in FSD_STOP}
        self._generic_stems = {stem(t) for t in GENERIC_SIGNAL} | self._stop_stems

    # ------------------------------------------------------------------ per requirement

    def _entity_hits(self, req: Requirement, obj: SapObject) -> list[str]:
        wanted = {v.upper() for key in ("tables", "functions", "custom_objects") for v in req.entities.get(key, [])}
        if not wanted:
            return []
        have = {r.target_name for r in obj.references} | {obj.name} | {c.name for c in obj.components} | {t.upper() for t in (obj.attributes or {}).get("tables", [])}
        return sorted(wanted & have)

    def _component_hits(self, key_stems: set[str], obj: SapObject) -> list[str]:
        out = []
        for c in obj.components:
            if c.kind in ("parameter", "include"):
                continue
            # words in the component NAME count as they are (a method CHECK_..._EXISTS is a real signal);
            # description words are filtered like the requirement's own words
            name_stems = {stem(t) for t in tokenise(c.name) if len(t) > 2}
            desc_stems = {stem(t) for t in tokenise(c.short_text or "") if len(t) > 2} - self._stop_stems
            overlap = key_stems & (name_stems | desc_stems)
            single = next(iter(overlap)) if len(overlap) == 1 else ""
            single_ok = bool(single) and len(key_stems) <= 3 and single in self._distinctive and single not in self._generic_stems
            if (len(overlap) >= 2 and any(len(o) >= 4 for o in overlap)) or single_ok:
                out.append(c.name)
        return out[:5]

    def score(self, req: Requirement, obj: SapObject, similarity: float) -> Match:
        key = _key_stems(req)
        key_set = set(key)
        doc = self._docs.get(obj.id)
        all_stems = doc.all_stems if doc else set()
        matched = [k for k in key if k in all_stems or any(p in all_stems for p in self.engine._parts(k))]
        tc = len(matched) / len(key) if key else 0.0
        ents = self._entity_hits(req, obj)
        comps = self._component_hits(key_set, obj)
        sim_norm = min(1.0, max(0.0, (similarity - 0.1) / 0.5)) if similarity else 0.0
        conf = 0.55 * tc + 0.2 * sim_norm + (0.25 if ents else 0.0) + (0.15 if comps else 0.0)
        # name hit on the requirement's key noun phrase is a strong signal
        name_stems = doc.name_stems if doc else set()
        if len(key_set & name_stems) >= 2:
            conf += 0.1
        # different SAP module and only loose word overlap -> probably a false friend
        if self.fsd_module and obj.module and obj.module[:2] != self.fsd_module and tc < 0.6 and not ents:
            conf *= 0.7
        # specific signal: entity reference, component, name hit, or a distinctive matched term
        distinct = [k for k in matched if k in self._distinctive and k not in self._generic_stems]
        name_hit = len(key_set & name_stems) >= 1 and any(len(k) >= 4 and k not in self._generic_stems for k in key_set & name_stems)
        specific = bool(ents or comps or name_hit or (distinct and len(matched) >= 2))
        if not specific:
            conf = min(conf, PARTIAL - 0.01)        # can rank as a weak candidate, never as partial/covered
        evidence = "; ".join(x for x in (
            f"references {', '.join(ents)}" if ents else "",
            f"method/FM {', '.join(comps[:2])}" if comps else "",
            "name matches" if name_hit else "",
            f"distinctive terms {', '.join(distinct[:3])}" if distinct else "",
            "generic word overlap only" if not specific else "",
        ) if x)
        return Match(obj.id, obj.name, get_type(obj.obj_type).label, obj.short_text, round(min(1.0, conf), 3), round(tc, 2), round(similarity, 3), ents, comps, matched, specific, evidence)

    def candidates_for(self, req: Requirement, limit: int = 8) -> list[Match]:
        results = self.engine.search(req.search_text, limit=limit, mode="hybrid")
        out = []
        for r in results:
            obj = self._objs.get(r.object.id)
            if obj is None:
                continue
            m = self.score(req, obj, r.similarity)
            if m.confidence >= 0.12:
                out.append(m)
        out.sort(key=lambda m: -m.confidence)
        return out

    # ------------------------------------------------------------------ whole document

    def analyse(self, requirements: list[Requirement]) -> tuple[list[ReqResult], list[ReuseCandidate], float, str]:
        per_req: dict[str, list[Match]] = {r.id: self.candidates_for(r) for r in requirements}
        by_id = {r.id: r for r in requirements}
        doc_intents = [i for i, _ in match_intents(" ".join(r.text for r in requirements), 5)]
        doc_business = [i for i in doc_intents if not i.id.startswith("tech_")]

        # object-level aggregation -> reuse candidates (family aware: prefer the object with the most code)
        agg: dict[int, float] = {}
        for rid, matches in per_req.items():
            w = by_id[rid].weight
            for m in matches[:5]:
                agg[m.object_id] = agg.get(m.object_id, 0.0) + w * m.confidence
        top_ids = [oid for oid, _ in sorted(agg.items(), key=lambda kv: -kv[1])[:4]]

        results: list[ReqResult] = []
        for req in requirements:
            matches = per_req[req.id]
            best = matches[0] if matches else None
            # prefer a top candidate when it is close to the best, to keep the reuse set small
            for m in matches:
                if m.object_id in top_ids[:2] and best and m.confidence >= best.confidence - 0.08:
                    best = m
                    break
            status = "covered" if best and best.confidence >= COVERED else "partial" if best and best.confidence >= PARTIAL and best.term_coverage >= 0.3 else "missing"
            if status == "missing" and best and not best.entities:
                best = None                                  # a missing requirement shows a match only when the object really references what the FSD names
            req_intents = _stable_intents(req, doc_intents, doc_business)
            intents = [i.id for i in req_intents]
            change, effort = describe_change(req, status, best, req_intents)
            results.append(ReqResult(req.id, req.text, req.section, req.kind, req.weight, req.entities, status, best, matches[:4], intents, change, effort))

        total_w = sum(r.weight for r in results) or 1
        score = sum(r.weight * (1.0 if r.status == "covered" else 0.5 if r.status == "partial" else 0.0) for r in results)
        coverage = round(100 * score / total_w, 1)

        reuse: list[ReuseCandidate] = []
        for oid in top_ids[:3]:
            obj = self._objs[oid]
            cov, par, mis = [], [], []
            w_score = 0.0
            for req in requirements:
                m = next((x for x in per_req[req.id] if x.object_id == oid), None)
                if m and m.confidence >= COVERED:
                    cov.append(req.id); w_score += req.weight
                elif m and m.confidence >= PARTIAL:
                    par.append(req.id); w_score += 0.5 * req.weight
                else:
                    mis.append(req.id)
            pct = round(100 * w_score / total_w, 1)
            if pct >= 10:
                reuse.append(ReuseCandidate(oid, obj.name, get_type(obj.obj_type).label, obj.short_text, obj.description[:400], pct, cov, par, mis, obj.source_lines))
        reuse.sort(key=lambda c: -c.coverage_pct)

        verdict = "reuse" if coverage >= 65 else "extend" if coverage >= 35 else "build"
        return results, reuse, coverage, verdict


def _stable_intents(req: Requirement, doc_intents: list[Intent], doc_business: list[Intent]) -> list[Intent]:
    """Requirement-level intents, but a single weak keyword hit on a business intent is
    replaced by the document's dominant business intent (a PO-approval FSD mentioning
    'cost centre manager' is not a CO posting requirement)."""
    scored = match_intents(req.text, 3)
    doc_ids = {i.id for i in doc_intents}
    out: list[Intent] = []
    for intent, hits in scored:
        if intent.id.startswith("tech_") or hits >= 2 or intent.id in doc_ids:
            out.append(intent)
    if req.kind == "validation" and not any(i.id == "tech_validation" for i in out):
        out.insert(0, next(i for i in INTENTS if i.id == "tech_validation"))
    if not any(not i.id.startswith("tech_") for i in out) and doc_business and req.kind in ("processing", "integration"):
        out.append(doc_business[0])
    return out[:2]


# ---------------------------------------------------------------------- change recommendations

EFFORT = {"processing": 8, "integration": 12, "validation": 2.5, "output": 4, "data_model": 4, "selection": 1, "authorization": 1, "error_handling": 2, "performance": 3, "scheduling": 2, "mapping": 1.5, "scope": 0}


def describe_change(req: Requirement, status: str, best: Match | None, intents: list[Intent]) -> tuple[str, float]:
    base = EFFORT.get(req.kind, 4)
    if req.kind == "scope":
        return "Scope statement - realised by the plan as a whole, no separate effort.", 0.0
    usable = [i for i in intents if i.id != "tech_replication"] or intents      # replication options are alternatives, not building blocks
    blocks = "; ".join(f"{b.name} ({b.purpose})" for i in usable[:1] for b in i.blocks[:3])
    if usable and usable[0].id == "tech_replication":
        blocks = "check the SAP standard first - " + blocks
    where = f"{best.name}" + (f" → {', '.join(best.components[:2])}" if best and best.components else "") if best else ""
    if status == "covered":
        text = f"Reuse {where}. Verify the behaviour matches: \"{_short(req.text)}\"."
        if best and best.entities:
            text += f" Already references {', '.join(best.entities)}."
        return text, round(base * 0.15, 1)
    if status == "partial":
        lead = f"Extend {where}: "
        if req.kind == "selection":
            text = lead + f"add selection field(s) {', '.join(req.entities.get('fields', [])) or 'per the FSD'} and pass them into the data retrieval."
        elif req.kind == "output":
            text = lead + f"add the output element(s) described (column/total/attachment) - {_short(req.text)}."
        elif req.kind == "validation":
            text = lead + f"add a validation method returning a BAPIRET2/exception - {_short(req.text)}."
        elif req.kind == "integration":
            text = lead + f"extend the interface mapping / payload handling - {_short(req.text)}."
        elif req.kind == "error_handling":
            text = lead + "route messages through the existing log/return handling - " + _short(req.text) + "."
        elif req.kind == "scheduling":
            text = lead + "make the run variant-driven (TVARVC dates) so it can be scheduled - " + _short(req.text) + "."
        elif req.kind == "data_model":
            text = lead + "add the custom table / fields and read them in the existing flow - " + _short(req.text) + "."
        elif req.kind == "mapping":
            text = lead + "add the field mapping / value conversion - " + _short(req.text) + "."
        elif req.kind == "authorization":
            text = lead + "add AUTHORITY-CHECK for the object named in the FSD before data access."
        else:
            text = lead + f"add the logic (new method / form) implementing \"{_short(req.text)}\"."
        if blocks:
            text += f" Building blocks: {blocks}."
        return text, round(base * 0.55, 1)
    names = ", ".join(b.name for i in usable[:1] for b in i.blocks[:3])
    text = "New development."
    if names:
        text += (" Check the SAP standard first: " if usable and usable[0].id == "tech_replication" else " Building blocks: ") + names + "."
    return text, float(base)


def _short(text: str, n: int = 110) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"

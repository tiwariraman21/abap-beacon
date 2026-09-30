"""Run the rule engine and persist findings.

Findings are replaced per object on every run, but a finding whose fingerprint
(rule + component + normalised snippet) already exists keeps its status, so
`accepted` / `false_positive` decisions survive re-ingestion.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from atlas.assess.rules import RULES, RuleContext, clean_core_tier, rules_for, s4_status
from atlas.db.models import Finding, SapObject, System
from atlas.ingest.types import get_type
from atlas.parse.abap import parse_abap
from atlas.parse.service import CDS_TYPES


@dataclass
class AssessSummary:
    objects: int = 0
    findings: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)
    effort_hours: float = 0.0

    def as_dict(self) -> dict:
        return {"objects": self.objects, "findings": self.findings, "by_category": self.by_category, "by_severity": self.by_severity, "effort_hours": round(self.effort_hours, 1)}


def _fingerprint(rule_id: str, component: str, snippet: str, message: str) -> str:
    norm = re.sub(r"\s+", " ", snippet.strip().lower())
    return hashlib.sha1(f"{rule_id}|{component}|{norm}|{message[:80]}".encode("utf-8", "replace")).hexdigest()[:20]


def active_rules() -> list:
    """The rule variant for the active workspace's target release (like an ATC check variant)."""
    try:
        from atlas.workspace import current_slug, load_info

        info = load_info(current_slug())
        return rules_for(info.target_release, info.deployment)
    except Exception:      # noqa: BLE001
        return list(RULES)


def assess_objects(session: Session, only_ids: list[int] | None = None, system_sid: str | None = None) -> AssessSummary:
    query = select(SapObject).options(selectinload(SapObject.files), selectinload(SapObject.findings))
    if only_ids is not None:
        if not only_ids:
            return AssessSummary()
        query = query.where(SapObject.id.in_(only_ids))
    if system_sid:
        query = query.join(System).where(System.sid == system_sid.upper())

    summary = AssessSummary()
    for obj in session.scalars(query):
        summary.objects += 1
        source = obj.source
        parsed = parse_abap(source, is_cds=obj.obj_type in CDS_TYPES) if source else parse_abap("")
        ctx = RuleContext(obj.name, obj.obj_type, obj.short_text or "", obj.attributes or {}, source, parsed, source.splitlines())
        _merge_includes(session, obj, ctx)

        hits: list[tuple] = []
        for rule in active_rules():
            try:
                for h in rule.check(ctx):
                    hits.append((rule, h))
            except Exception as error:  # a broken rule must never stop the run
                hits.append((rule, None))
                obj.attributes = {**(obj.attributes or {}), f"rule_error_{rule.id}": f"{type(error).__name__}: {error}"[:120]}
        hits = [(r, h) for r, h in hits if h is not None]

        previous = {f.fingerprint: f for f in obj.findings}
        keep_status = {fp: f.status for fp, f in previous.items() if f.status != "open"}
        for f in list(obj.findings):
            session.delete(f)
        obj.findings.clear()
        session.flush()

        seen: set[str] = set()
        pairs: list[tuple[str, str]] = []
        for rule, hit in hits:
            fp = _fingerprint(rule.id, hit.component, hit.snippet, hit.message)
            if fp in seen:
                continue
            seen.add(fp)
            severity = hit.severity or rule.severity
            effort = hit.effort_hours if hit.effort_hours is not None else rule.effort_hours
            status = keep_status.get(fp, "open")
            obj.findings.append(
                Finding(rule_id=rule.id, category=rule.category, severity=severity, title=rule.title, message=hit.message,
                        remediation=rule.remediation, component=hit.component or "", line=hit.line, snippet=hit.snippet[:300],
                        effort_hours=effort, status=status, fingerprint=fp)
            )
            pairs.append((rule.id, severity))
            if status in ("open", "accepted"):
                summary.findings += 1
                summary.by_category[rule.category] = summary.by_category.get(rule.category, 0) + 1
                summary.by_severity[severity] = summary.by_severity.get(severity, 0) + 1
                summary.effort_hours += effort

        tier, reason = clean_core_tier(ctx, pairs)
        obj.clean_core_tier = tier
        obj.s4_status = s4_status(pairs, ctx.is_code)
        obj.attributes = {**(obj.attributes or {}), "clean_core_reason": reason}

    return summary


def _merge_includes(session: Session, obj: SapObject, ctx: RuleContext) -> None:
    """An executable program's checks (AUTHORITY-CHECK, SELECTs) often sit in its
    includes. Pull the includes' references into the program's context so
    program-level rules see the whole picture. Findings on the includes' own
    statements stay with the include objects."""
    if not ctx.is_executable:
        return
    names = [r.target for r in ctx.parsed.references if r.kind == "includes"]
    if not names:
        return
    rows = session.scalars(
        select(SapObject).options(selectinload(SapObject.files))
        .where(SapObject.system_id == obj.system_id, SapObject.name.in_(names), SapObject.obj_type == "PROG")
    )
    for inc in rows:
        if inc.id == obj.id:
            continue
        inc_parsed = parse_abap(inc.source)
        ctx.include_references.extend(inc_parsed.references)


# --- queries -------------------------------------------------------------------------------

def findings_overview(session: Session, system_sid: str | None = None) -> dict:
    base = select(Finding).join(SapObject)
    if system_sid:
        base = base.join(System).where(System.sid == system_sid.upper())
    open_filter = Finding.status.in_(["open", "accepted"])

    by_cat = dict(session.execute(select(Finding.category, func.count()).select_from(Finding).join(SapObject).where(open_filter).group_by(Finding.category)).all())
    by_sev = dict(session.execute(select(Finding.severity, func.count()).select_from(Finding).join(SapObject).where(open_filter).group_by(Finding.severity)).all())
    effort = session.scalar(select(func.coalesce(func.sum(Finding.effort_hours), 0.0)).select_from(Finding).where(open_filter)) or 0.0
    by_rule = session.execute(
        select(Finding.rule_id, Finding.title, Finding.category, Finding.severity, func.count(), func.count(func.distinct(Finding.object_id)), func.sum(Finding.effort_hours))
        .where(open_filter).group_by(Finding.rule_id, Finding.title, Finding.category, Finding.severity).order_by(func.count().desc())
    ).all()
    tiers = dict(session.execute(select(SapObject.clean_core_tier, func.count()).where(SapObject.clean_core_tier != "").group_by(SapObject.clean_core_tier)).all())
    s4 = dict(session.execute(select(SapObject.s4_status, func.count()).where(SapObject.s4_status != "").group_by(SapObject.s4_status)).all())
    top_objects = session.execute(
        select(SapObject.id, SapObject.name, SapObject.obj_type, func.count(Finding.id), func.sum(Finding.effort_hours))
        .join(Finding, Finding.object_id == SapObject.id).where(open_filter)
        .group_by(SapObject.id, SapObject.name, SapObject.obj_type).order_by(func.sum(Finding.effort_hours).desc()).limit(10)
    ).all()
    return {
        "by_category": by_cat,
        "by_severity": by_sev,
        "effort_hours": round(float(effort), 1),
        "total": sum(by_cat.values()),
        "rules": [dict(rule_id=r, title=t, category=c, severity=s, findings=n, objects=o, effort=round(float(e or 0), 1)) for r, t, c, s, n, o, e in by_rule],
        "tiers": {k: v for k, v in sorted(tiers.items())},
        "s4_status": s4,
        "top_objects": [dict(id=i, name=n, type=get_type(t).label, findings=c, effort=round(float(e or 0), 1)) for i, n, t, c, e in top_objects],
    }


def list_findings(session: Session, category: str | None = None, severity: str | None = None, rule_id: str | None = None, status: str | None = "open", object_id: int | None = None, text: str = "", limit: int = 500) -> list[dict]:
    q = select(Finding, SapObject.name, SapObject.obj_type).join(SapObject).order_by(
        # high first
        func.instr("high,medium,low,info", Finding.severity), SapObject.name, Finding.line
    )
    if category:
        q = q.where(Finding.category == category)
    if severity:
        q = q.where(Finding.severity == severity)
    if rule_id:
        q = q.where(Finding.rule_id == rule_id)
    if status and status != "all":
        q = q.where(Finding.status == status)
    if object_id:
        q = q.where(Finding.object_id == object_id)
    if text:
        like = f"%{text}%"
        q = q.where((SapObject.name.like(like)) | (Finding.message.like(like)) | (Finding.title.like(like)))
    rows = session.execute(q.limit(limit)).all()
    return [
        dict(id=f.id, object_id=f.object_id, object=name, type=get_type(t).label, rule_id=f.rule_id, category=f.category, severity=f.severity,
             title=f.title, message=f.message, remediation=f.remediation, component=f.component, line=f.line, snippet=f.snippet,
             effort=f.effort_hours, status=f.status)
        for f, name, t in rows
    ]


def set_finding_status(session: Session, finding_id: int, status: str) -> None:
    f = session.get(Finding, finding_id)
    if f is not None and status in ("open", "accepted", "fixed", "false_positive"):
        f.status = status

"""Custom-code retirement: which objects can be decommissioned before a conversion.

SAP's own numbers: in most systems 30-60 % of custom code has not run for years. Every retired
object saves its remediation, testing and documentation effort - the single biggest lever in an
S/4HANA conversion budget. Beacon combines three facts per object:

  usage       executions in production (ST03N / SCMON / SUSG export, imported as CSV)
  callers     inbound references from other custom objects (dependency graph)
  findings    open remediation effort from the assessment

and decides:  retire (no usage in the period and no custom caller)  /  review (no usage data or only
one weak signal)  /  keep (used) - with the hours and money each retirement saves.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from atlas.db.models import Finding, ObjectReference, ObjectUsage, SapObject

_NAME_COLS = ("object", "object_name", "name", "program", "report", "obj_name", "entry_id", "objname", "tcode_program")
_CALLS_COLS = ("calls", "count", "executions", "steps", "dialog_steps", "hits", "number_of_calls", "usage", "total")
_USERS_COLS = ("users", "user_count", "distinct_users", "unique_users")
_LAST_COLS = ("last_used", "last_call", "last_execution", "last", "date", "last_date")
_TYPE_COLS = ("type", "obj_type", "object_type", "program_type")


@dataclass
class ImportResult:
    rows: int = 0
    matched: int = 0
    unknown: int = 0
    source: str = ""
    period_days: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _pick(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    low = {h.lower().strip(): h for h in headers}
    for c in candidates:
        if c in low:
            return low[c]
    for h in headers:
        if any(c in h.lower() for c in candidates):
            return h
    return None


def import_usage(session: Session, path_or_text: str | Path, source: str = "ST03N", period_days: int = 365,
                 period_from: str = "", period_to: str = "", replace: bool = False) -> ImportResult:
    """CSV/TSV with at least an object-name column and a calls column (ST03N workload export, SCMON
    'SUSG' aggregate export or a hand-made list). Unknown columns are ignored; names are upper-cased;
    ABAP includes/methods are folded to their main object where possible."""
    text = Path(path_or_text).read_text(encoding="utf-8-sig", errors="replace") if isinstance(path_or_text, Path) or (isinstance(path_or_text, str) and len(path_or_text) < 400 and Path(path_or_text).exists()) else str(path_or_text)
    sample = text[:4096]
    delim = "\t" if sample.count("\t") > sample.count(",") and sample.count("\t") > sample.count(";") else ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    headers = reader.fieldnames or []
    name_col, calls_col = _pick(headers, _NAME_COLS), _pick(headers, _CALLS_COLS)
    if not name_col:
        raise ValueError(f"No object-name column found (looked for {', '.join(_NAME_COLS[:4])}...). Columns: {', '.join(headers)}")
    users_col, last_col, type_col = _pick(headers, _USERS_COLS), _pick(headers, _LAST_COLS), _pick(headers, _TYPE_COLS)
    known = {o.name: o for o in session.scalars(select(SapObject))}
    from datetime import date, timedelta

    if not period_to:
        period_to = date.today().isoformat()
    if not period_from:
        period_from = (date.fromisoformat(period_to) - timedelta(days=period_days)).isoformat()
    period_days = max(1, (date.fromisoformat(period_to) - date.fromisoformat(period_from)).days)
    batch = f"{source}:{period_from}:{period_to}"
    res = ImportResult(source=source, period_days=period_days)
    # imports ACCUMULATE (quarterly ST03N exports build up a year); the same window is replaced, not doubled
    session.execute(ObjectUsage.__table__.delete().where(ObjectUsage.batch == batch))
    if replace:
        session.execute(ObjectUsage.__table__.delete().where(ObjectUsage.source == source))
    agg: dict[str, dict] = {}
    for row in reader:
        raw = (row.get(name_col) or "").strip().upper()
        if not raw:
            continue
        res.rows += 1
        name = re.sub(r"=+CP$|=+CM\d+$|=+CU$|=+CO$", "", raw)          # class pool / method includes -> class
        name = re.sub(r"^SAPL", "", name) if name.startswith("SAPLZ") or name.startswith("SAPLY") else name
        m = re.match(r"^L(Z\w+?)(TOP|U\d+|F\d+|\$\d+)$", name)
        if m:
            name = m.group(1)
        calls = int(float((row.get(calls_col) or "0").replace(",", "") or 0)) if calls_col else 1
        users = int(float((row.get(users_col) or "0").replace(",", "") or 0)) if users_col else 0
        last = (row.get(last_col) or "").strip()[:10] if last_col else ""
        typ = (row.get(type_col) or "").strip().upper()[:8] if type_col else ""
        a = agg.setdefault(name, {"calls": 0, "users": 0, "last": "", "type": typ})
        a["calls"] += calls
        a["users"] = max(a["users"], users)
        a["last"] = max(a["last"], last)
        if name in known:
            res.matched += 1
        else:
            res.unknown += 1
    for name, a in agg.items():
        session.add(ObjectUsage(name=name, obj_type=a["type"] or (known[name].obj_type if name in known else ""), calls=a["calls"], users=a["users"], last_used=a["last"],
                                period_days=period_days, period_from=period_from, period_to=period_to, batch=batch, source=source))
    session.flush()
    return res


def has_usage_data(session: Session) -> bool:
    return bool(session.scalar(select(func.count(ObjectUsage.id))))


def usage_window(session: Session) -> dict:
    """What the imported usage covers: first day, last day, months, sources, number of imports."""
    rows = session.execute(select(ObjectUsage.period_from, ObjectUsage.period_to, ObjectUsage.source, ObjectUsage.batch).distinct()).all()
    if not rows:
        return {"months": 0, "from": "", "to": "", "sources": [], "imports": 0, "enough": False}
    from datetime import date

    starts = [r[0] for r in rows if r[0]]
    ends = [r[1] for r in rows if r[1]]
    d0, d1 = min(starts) if starts else "", max(ends) if ends else ""
    months = 0
    if d0 and d1:
        a, b = date.fromisoformat(d0), date.fromisoformat(d1)
        months = round((b - a).days / 30.4, 1)
    return {"months": months, "from": d0, "to": d1, "sources": sorted({r[2] for r in rows}), "imports": len({r[3] for r in rows}), "enough": months >= 11.5}


MIN_MONTHS_FOR_RETIREMENT = 12
SEASONAL_MAX_CALLS = 4      # up to quarterly runs in a year look seasonal - a person confirms before retiring


ENTRY_TYPES = {"PROG", "FUGR", "CLAS", "INTF", "TABL", "DDLS", "DTEL", "DOMA", "TTYP", "MSAG", "ENHO", "ENHS", "SXCI", "WDYN", "TRAN", "SICF", "SRVD", "SRVB", "BDEF"}
CODE_TYPES = {"PROG", "FUGR", "CLAS", "INTF", "ENHO", "WDYN", "DDLS", "SRVD", "SRVB", "BDEF"}


def decide(session: Session, hourly_rate: float = 60.0) -> dict:
    """Per-object retirement decision plus totals. Deterministic and explainable."""
    objects = list(session.scalars(select(SapObject)))
    usage: dict[str, ObjectUsage] = {}
    for u in session.scalars(select(ObjectUsage)):          # several imports for one object -> one aggregated view
        cur = usage.get(u.name)
        if cur is None:
            usage[u.name] = ObjectUsage(name=u.name, obj_type=u.obj_type, calls=u.calls, users=u.users, last_used=u.last_used, period_days=u.period_days, source=u.source)
        else:
            cur.calls += u.calls
            cur.users = max(cur.users, u.users)
            cur.last_used = max(cur.last_used or "", u.last_used or "")
            cur.period_days += u.period_days
            if u.source not in cur.source:
                cur.source = f"{cur.source}+{u.source}"
    have_usage = bool(usage)
    window = usage_window(session)
    inbound: dict[str, int] = {}
    for tgt, n in session.execute(select(ObjectReference.target_name, func.count()).where(ObjectReference.is_custom.is_(True)).group_by(ObjectReference.target_name)).all():
        inbound[(tgt or "").upper()] = n
    effort = {oid: h for oid, h in session.execute(select(Finding.object_id, func.sum(Finding.effort_hours)).where(Finding.status == "open").group_by(Finding.object_id)).all()}
    findings_n = {oid: n for oid, n in session.execute(select(Finding.object_id, func.count()).where(Finding.status == "open").group_by(Finding.object_id)).all()}
    rows: list[dict] = []
    for o in objects:
        if o.obj_type not in CODE_TYPES:
            continue
        u = usage.get(o.name)
        callers = inbound.get(o.name, 0)
        rem = float(effort.get(o.id) or 0.0)
        # keep / test / doc effort avoided if retired: remediation + regression test + documentation baseline per object size
        base = 2.0 + min(24.0, (o.source_lines or 0) / 150.0)
        avoided = round(rem + base, 1)
        reasons: list[str] = []
        if have_usage:
            win = f"{window['months']} months of usage data" if window["months"] else "the imported usage data"
            if u and u.calls > SEASONAL_MAX_CALLS:
                decision = "keep"
                reasons.append(f"{u.calls} executions" + (f", last {u.last_used}" if u.last_used else "") + f" ({u.source})")
            elif u and u.calls > 0:
                decision = "review"
                reasons.append(f"only {u.calls} execution(s) in {win} - possibly seasonal (period-end); confirm before retiring")
            elif callers:
                decision = "review"
                reasons.append(f"no production usage in {win}, but {callers} custom caller(s) - check whether the callers are used")
            elif not window["enough"]:
                decision = "review"
                reasons.append(f"no production usage, but only {win} - {MIN_MONTHS_FOR_RETIREMENT} months are needed to rule out year-end programs")
            else:
                decision = "retire"
                reasons.append(f"no production usage in {win} and no custom caller")
        else:
            if callers:
                decision = "keep"
                reasons.append(f"{callers} custom caller(s)")
            elif o.obj_type in ("PROG", "FUGR", "CLAS") and (o.source_lines or 0) < 40:
                decision = "review"
                reasons.append("no custom caller and almost no code - stub or leftover?")
            else:
                decision = "review"
                reasons.append("no custom caller; import production usage (ST03N/SCMON) to decide")
        if findings_n.get(o.id):
            reasons.append(f"{findings_n[o.id]} open finding(s), {rem:.1f} h remediation")
        rows.append({"id": o.id, "name": o.name, "type": o.obj_type, "module": o.module or "", "lines": o.source_lines or 0, "callers": callers,
                     "calls": u.calls if u else None, "last_used": u.last_used if u else "", "remediation_h": round(rem, 1), "avoided_h": avoided,
                     "decision": decision, "reasons": reasons, "short_text": o.short_text or o.description[:80]})
    order = {"retire": 0, "review": 1, "keep": 2}
    rows.sort(key=lambda r: (order[r["decision"]], -r["avoided_h"]))
    totals = {d: sum(1 for r in rows if r["decision"] == d) for d in ("retire", "review", "keep")}
    hours = {d: round(sum(r["avoided_h"] for r in rows if r["decision"] == d), 1) for d in ("retire", "review", "keep")}
    return {"rows": rows, "totals": totals, "hours": hours, "have_usage": have_usage, "window": window, "hourly_rate": hourly_rate,
            "saving": round(hours["retire"] * hourly_rate), "potential": round((hours["retire"] + hours["review"]) * hourly_rate),
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}

"""Assessment rules.

Each rule is deterministic and explainable: it points at a line, quotes the
statement, states why it matters and what to do. Rules see a RuleContext
(object + parsed source) and return Hits. Effort hours are rough, editable
defaults used for the remediation estimate in the assessment report.

Categories: s4hana | security | quality | cleancore
Severity:   high | medium | low | info
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from atlas.parse.abap import ParsedSource, Statement, is_custom_name
from atlas.reference.sap_objects import OBSOLETE_STATEMENTS, OBSOLETE_TRANSACTIONS, TABLES


@dataclass
class Hit:
    message: str
    line: int = 0
    snippet: str = ""
    component: str = ""
    severity: str | None = None       # override the rule's default
    effort_hours: float | None = None


@dataclass
class RuleContext:
    name: str
    type_key: str
    short_text: str
    attributes: dict
    source: str
    parsed: ParsedSource
    lines: list[str] = field(default_factory=list)
    include_references: list = field(default_factory=list)   # references found in the program's INCLUDEs

    @property
    def is_executable(self) -> bool:
        return self.type_key == "PROG" and self.attributes.get("program_type", "Executable program") == "Executable program"

    @property
    def is_code(self) -> bool:
        return self.type_key in ("PROG", "CLAS", "INTF", "FUGR", "ENHO", "DDLS", "BDEF")

    def snippet(self, line: int) -> str:
        if 1 <= line <= len(self.lines):
            return self.lines[line - 1].strip()[:200]
        return ""


@dataclass
class Rule:
    id: str
    title: str
    category: str
    severity: str
    remediation: str
    check: Callable[[RuleContext], list[Hit]]
    effort_hours: float = 1.0
    description: str = ""

    @property
    def since(self) -> str:
        """First S/4HANA release for which this rule matters ('1511' = always)."""
        return RULE_RELEASE.get(self.id, "1511")

    @property
    def targets(self) -> tuple[str, ...]:
        return RULE_TARGETS.get(self.id, ("onprem", "cloud"))


RULES: list[Rule] = []

# Target-release variants, like ATC's S4HANA_READINESS_<release> check variants: a rule is applied when the
# customer's target release is >= `since` and the deployment ("onprem" / "cloud") is in its targets.
# Kept as data so a yearly SAP release becomes a table update, not an engine change.
RELEASES = ["1709", "1809", "1909", "2020", "2021", "2022", "2023", "2025"]
RELEASE_LABELS = {"1709": "S/4HANA 1709", "1809": "S/4HANA 1809", "1909": "S/4HANA 1909", "2020": "S/4HANA 2020", "2021": "S/4HANA 2021",
                  "2022": "S/4HANA 2022", "2023": "S/4HANA 2023", "2025": "S/4HANA 2025", "cloud": "S/4HANA Cloud / Clean Core"}
RULE_RELEASE = {
    "S4-001": "1511", "S4-002": "1909", "S4-003": "1511", "S4-004": "1511", "S4-005": "1511", "S4-006": "1809",
    "CC-001": "1909", "CC-002": "2020", "CC-003": "2020", "CC-004": "1909",
}
RULE_TARGETS = {"S4-002": ("onprem", "cloud"), "CC-002": ("cloud",), "CC-003": ("cloud",), "S4-005": ("onprem", "cloud")}


def rules_for(target: str = "2023", deployment: str = "onprem") -> list[Rule]:
    """The rule variant for a target release ('1909'…'2025' or 'cloud')."""
    if target == "cloud":
        rel, deployment = "2025", "cloud"
    else:
        rel = target if target in RELEASES else "2023"
    return [r for r in RULES if r.since <= rel and deployment in r.targets]


def rule(id: str, title: str, category: str, severity: str, remediation: str, effort_hours: float = 1.0, description: str = ""):
    def wrap(fn: Callable[[RuleContext], list[Hit]]) -> Callable[[RuleContext], list[Hit]]:
        RULES.append(Rule(id, title, category, severity, remediation, fn, effort_hours, description or fn.__doc__ or ""))
        return fn
    return wrap


def _stmts(ctx: RuleContext) -> list[Statement]:
    return ctx.parsed.statements


def _hit(ctx: RuleContext, st: Statement, message: str, **kw) -> Hit:
    return Hit(message=message, line=st.line, snippet=ctx.snippet(st.line), component=st.component, **kw)


# ====================================================================================== S/4HANA

@rule("S4-001", "Access to table changed or replaced in S/4HANA", "s4hana", "medium",
      "Move to the successor table / CDS view named in the finding. Writes to compatibility views fail at runtime.", 4.0,
      "Simplification list: FIN data model, KONV/PRCD_ELEMENTS, VBUK/VBUP, MATDOC, Business Partner, credit management.")
def s4_tables(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    for ref in ctx.parsed.references:
        std = TABLES.get(ref.target)
        if not std or std.s4_status == "ok" or ref.kind not in ("reads", "writes", "declares", "uses_cds"):
            continue
        sev = {"replaced": "high", "compat": "medium", "changed": "low"}[std.s4_status]
        effort = {"replaced": 8.0, "compat": 4.0, "changed": 1.0}[std.s4_status]
        if ref.kind == "writes" and std.s4_status in ("compat", "replaced"):
            sev, effort = "high", 12.0
        verb = {"reads": "reads", "writes": "WRITES to", "declares": "declares work area for", "uses_cds": "associates"}[ref.kind]
        msg = f"{verb} {std.name} ({std.text}) - {std.s4_status}"
        if std.successor:
            msg += f"; successor: {std.successor}"
        if std.note:
            msg += f". {std.note}"
        hits.append(Hit(msg, ref.line, ctx.snippet(ref.line), ref.component, sev, effort))
    return hits


@rule("S4-002", "Obsolete or ABAP-Cloud-incompatible statement", "s4hana", "low",
      "Replace with the modern construct given in the finding; obsolete statements block ABAP Cloud and hide HANA performance issues.", 0.5)
def s4_obsolete_statements(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    if ctx.type_key not in ("PROG", "CLAS", "FUGR", "ENHO", "INTF"):
        return hits
    high = ("Native SQL", "Kernel call")
    for st in _stmts(ctx):
        u = st.text.upper()
        for rx, title, fix in OBSOLETE_STATEMENTS:
            if title.startswith(("BREAK-POINT", "Classic list")):
                continue     # handled in quality rules
            if re.search(rx, u):
                sev = "high" if title.startswith(high) else ("medium" if title.startswith(("TABLES", "OCCURS", "Internal table WITH", "FIELD-GROUPS", "Update task")) else "low")
                hits.append(_hit(ctx, st, f"{title}: {fix}", severity=sev, effort_hours=2.0 if sev == "high" else 0.5))
                break
    return hits


@rule("S4-003", "Call of a transaction obsolete in S/4HANA", "s4hana", "medium",
      "Replace with the successor transaction / Fiori app or API named in the finding.", 4.0)
def s4_transactions(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    for ref in ctx.parsed.references:
        if ref.kind == "calls_transaction" and ref.target in OBSOLETE_TRANSACTIONS:
            hits.append(Hit(f"CALL TRANSACTION {ref.target}: {OBSOLETE_TRANSACTIONS[ref.target]}", ref.line, ctx.snippet(ref.line), ref.component))
    return hits


@rule("S4-004", "Result order depends on the database (no ORDER BY)", "s4hana", "medium",
      "Add ORDER BY (PRIMARY KEY or explicit fields) - HANA returns rows in arbitrary order, breaking READ TABLE ... BINARY SEARCH and 'first row' logic.", 1.0)
def s4_order_by(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    stmts = _stmts(ctx)
    for i, st in enumerate(stmts):
        u = st.text.upper()
        if not u.startswith("SELECT") or "ORDER BY" in u:
            continue
        if re.search(r"\bUP\s+TO\s+1\s+ROWS\b", u) and "SINGLE" not in u:
            hits.append(_hit(ctx, st, "SELECT ... UP TO 1 ROWS without ORDER BY returns an arbitrary row on HANA."))
            continue
        m = re.search(r"\bINTO\s+(?:CORRESPONDING\s+FIELDS\s+OF\s+)?TABLE\s+@?([A-Z0-9_]+)", u)
        if not m:
            continue
        itab = m.group(1)
        window = stmts[i + 1: i + 25]
        sorted_after = any(re.match(rf"^SORT\s+{re.escape(itab)}\b", w.text.upper()) for w in window if w.component == st.component)
        binary = any(re.search(rf"\bREAD\s+TABLE\s+{re.escape(itab)}\b.*\bBINARY\s+SEARCH\b", w.text.upper()) for w in window if w.component == st.component)
        if binary and not sorted_after:
            hits.append(_hit(ctx, st, f"{itab} is filled without ORDER BY and read with BINARY SEARCH without SORT - undefined on HANA."))
    return hits


@rule("S4-005", "Material number field shorter than 40 characters", "s4hana", "low",
      "MATNR is 40 characters in S/4HANA. Use TYPE matnr / the data element instead of fixed CHAR18.", 1.0)
def s4_matnr(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    for st in _stmts(ctx):
        u = st.text.upper()
        if re.search(r"\b(MATNR|MATERIAL)\w*\b", u) and re.search(r"\bTYPE\s+C\s+LENGTH\s+18\b|\(18\)\s+TYPE\s+C\b|\bCHAR18\b", u):
            hits.append(_hit(ctx, st, "Material field declared as CHAR 18."))
    return hits


@rule("S4-006", "Classic SD credit management API", "s4hana", "medium",
      "SD-BF-CM is replaced by FSCM Credit Management in S/4HANA; use UKM_* APIs / BAdIs (UKM_R3_ACTIVATE, UKM_FILL) and Documented Credit Decisions.", 6.0)
def s4_credit(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    for ref in ctx.parsed.references:
        if ref.kind == "calls_function" and re.match(r"^(SD_ORDER_CREDIT_|SD_CREDIT_|CREDIT_EXPOSURE|SD_DOCUMENT_CREDIT_)", ref.target):
            hits.append(Hit(f"Calls {ref.target} (classic SD credit management).", ref.line, ctx.snippet(ref.line), ref.component))
        if ref.kind in ("reads", "writes", "declares") and ref.target in ("KNKK", "KNKA", "S066", "S067"):
            hits.append(Hit(f"Uses credit table {ref.target}; data lives in FSCM (UKMBP_CMS*, UKM_ITEM) in S/4HANA.", ref.line, ctx.snippet(ref.line), ref.component))
    return hits


# ====================================================================================== Security

_CRED = re.compile(r"\b[A-Z0-9_]*(PASSWORD|PASSWD|PWD|SECRET|CLIENT_?ID|CLIENT_?SECRET|API_?KEY|ACCESS_?TOKEN|AUTH_?TOKEN|BEARER|CREDENTIAL|ENCRYPTION_?KEY)[A-Z0-9_]*\s*(?:=|VALUE)\s*'§'", re.I)


@rule("SEC-001", "Hard-coded credential in source", "security", "high",
      "Move secrets to a secure store (SSF / STRUST / RFC destination / SM59 OAuth profile) and read them at runtime. Rotate the exposed value.", 2.0)
def sec_credentials(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    literal_by_line: dict[int, list[str]] = {}
    for ln, lit in ctx.parsed.string_literals:
        literal_by_line.setdefault(ln, []).append(lit)
    for st in _stmts(ctx):
        if _CRED.search(st.text):
            lits = [l for ln in range(st.line, st.line_end + 1) for l in literal_by_line.get(ln, []) if l.strip()]
            if lits:
                hits.append(_hit(ctx, st, "Credential-like identifier assigned a literal value."))
    return hits


@rule("SEC-002", "Hard-coded URL or host name", "security", "medium",
      "Use an RFC destination (SM59) or a customizing table so endpoints differ per system and never live in code.", 1.0)
def sec_urls(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    for ln, lit in ctx.parsed.string_literals:
        if re.match(r"^\s*https?://", lit, re.I):
            hits.append(Hit(f"URL literal {lit[:80]!r}", ln, ctx.snippet(ln), ctx.parsed.component_at(ln)))
    return hits


@rule("SEC-003", "Executable program without AUTHORITY-CHECK", "security", "medium",
      "Add AUTHORITY-CHECK on the relevant authorization object (e.g. F_BKPF_BUK, V_VBAK_VKO) before reading or changing data; transaction-level S_TCODE alone is not sufficient.", 2.0)
def sec_no_auth(ctx: RuleContext) -> list[Hit]:
    if not ctx.is_executable:
        return []
    refs = ctx.parsed.references + ctx.include_references
    reads_db = any(r.kind in ("reads", "writes") for r in refs)
    declares = any(r.kind == "declares" for r in refs)
    has_auth = any(r.kind == "authority_check" for r in refs)
    if has_auth:
        return []
    if reads_db:
        return [Hit("Program reads database tables but performs no AUTHORITY-CHECK.", 1, ctx.snippet(1))]
    if declares:
        return [Hit("Program declares database tables / selection screen but performs no AUTHORITY-CHECK.", 1, ctx.snippet(1), severity="low")]
    return []


@rule("SEC-004", "CALL TRANSACTION without authorization check", "security", "medium",
      "Add WITH AUTHORITY-CHECK (7.40+) or an explicit AUTHORITY-CHECK OBJECT 'S_TCODE' before the call.", 1.0)
def sec_call_transaction(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    auth_components = {r.component for r in ctx.parsed.references if r.kind == "authority_check"}
    for st in _stmts(ctx):
        u = st.text.upper()
        if u.startswith("CALL TRANSACTION") and "WITH AUTHORITY-CHECK" not in u and st.component not in auth_components:
            hits.append(_hit(ctx, st, "CALL TRANSACTION without WITH AUTHORITY-CHECK."))
    return hits


@rule("SEC-005", "Dynamic WHERE clause / dynamic SQL", "security", "info",
      "Ensure the dynamic part is built from validated values (CL_ABAP_DYN_PRG) to prevent SQL injection.", 1.0)
def sec_dynamic_sql(ctx: RuleContext) -> list[Hit]:
    return [_hit(ctx, st, "Dynamic WHERE condition.") for st in _stmts(ctx)
            if st.text.upper().startswith(("SELECT", "UPDATE", "DELETE", "MODIFY")) and re.search(r"\bWHERE\s+\(\s*[A-Z0-9_]+\s*\)", st.text.upper())]


@rule("SEC-006", "CLIENT SPECIFIED access", "security", "low",
      "Cross-client access bypasses client separation; justify and restrict, or remove.", 0.5)
def sec_client_specified(ctx: RuleContext) -> list[Hit]:
    return [_hit(ctx, st, "CLIENT SPECIFIED used.") for st in _stmts(ctx) if "CLIENT SPECIFIED" in st.text.upper() or re.search(r"\bUSING\s+CLIENT\b", st.text.upper())]


@rule("SEC-007", "Logic depends on a hard-coded user name", "security", "medium",
      "Replace SY-UNAME checks with authorization objects or roles.", 1.0)
def sec_uname(ctx: RuleContext) -> list[Hit]:
    return [_hit(ctx, st, "Comparison against SY-UNAME literal.") for st in _stmts(ctx) if re.search(r"\bSY-UNAME\s*(=|EQ|<>|NE|IN)\s*'§'", st.text.upper())]


@rule("SEC-008", "File access with hard-coded server path", "security", "low",
      "Use logical file names (FILE transaction) and validate paths against directory traversal.", 1.0)
def sec_dataset(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    literal_by_line: dict[int, list[str]] = {}
    for ln, lit in ctx.parsed.string_literals:
        literal_by_line.setdefault(ln, []).append(lit)
    for st in _stmts(ctx):
        u = st.text.upper()
        if u.startswith(("OPEN DATASET", "DELETE DATASET")) and any("/" in l or "\\" in l for ln in range(st.line, st.line_end + 1) for l in literal_by_line.get(ln, [])):
            hits.append(_hit(ctx, st, "Dataset opened with a literal path."))
    return hits


# ====================================================================================== Quality

@rule("Q-001", "SELECT * (all columns)", "quality", "low",
      "Select only the fields you need - on HANA's column store SELECT * is the single most common performance defect.", 0.5)
def q_select_star(ctx: RuleContext) -> list[Hit]:
    return [_hit(ctx, st, "SELECT * fetches every column.") for st in _stmts(ctx) if re.match(r"^SELECT\s+(SINGLE\s+)?\*\s", st.text.upper())]


def _loop_depth_iter(stmts: list[Statement]):
    """Yield (statement, loop_depth, block_depth) with depth reset per method/form/function."""
    loop_depth = 0
    block_depth = 0
    current = None
    for st in stmts:
        u = st.text.upper()
        if st.component != current:
            current = st.component
            loop_depth = block_depth = 0
        if re.match(r"^(ENDLOOP|ENDDO|ENDWHILE)\b", u):
            loop_depth = max(0, loop_depth - 1)
        if re.match(r"^(ENDLOOP|ENDDO|ENDWHILE|ENDIF|ENDCASE|ENDTRY|ENDPROVIDE)\b", u):
            block_depth = max(0, block_depth - 1)
        yield st, loop_depth, block_depth
        if re.match(r"^(LOOP|DO|WHILE)\b", u):
            loop_depth += 1
        if re.match(r"^(LOOP|DO|WHILE|IF|CASE|TRY|PROVIDE)\b", u):
            block_depth += 1


@rule("Q-002", "Database access inside a loop", "quality", "medium",
      "Read the data once before the loop (FOR ALL ENTRIES / JOIN / range) and look it up in an internal table; N+1 selects dominate runtime.", 2.0)
def q_select_in_loop(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    for st, loops, _ in _loop_depth_iter(_stmts(ctx)):
        u = st.text.upper()
        if loops > 0 and (u.startswith("SELECT") or (u.startswith(("UPDATE", "INSERT", "MODIFY", "DELETE")) and re.search(r"\b(FROM|INTO)\s+(?!TABLE\b)[A-Z]", u) and not re.match(r"^(INSERT|MODIFY|DELETE)\s+(LT|GT|IT|MT|ET|CT|RT)_", u))):
            if u.startswith("SELECT") or re.search(r"\b(?:UPDATE|INSERT INTO|MODIFY|DELETE FROM)\s+[A-Z][A-Z0-9_]{2,}\b", u):
                hits.append(_hit(ctx, st, f"Database statement executed inside a loop (depth {loops})."))
    return hits


@rule("Q-003", "Deeply nested control flow", "quality", "medium",
      "Extract methods / early returns (CHECK, RETURN) so no block nests deeper than 5.", 2.0)
def q_nesting(ctx: RuleContext) -> list[Hit]:
    worst: dict[str, tuple[int, Statement]] = {}
    for st, _, depth in _loop_depth_iter(_stmts(ctx)):
        if depth >= 6 and (st.component not in worst or depth > worst[st.component][0]):
            worst[st.component] = (depth, st)
    return [_hit(ctx, st, f"Nesting depth {d} in {st.component or 'main program'}.") for d, st in worst.values()]


@rule("Q-004", "Very long method / form", "quality", "low",
      "Split into smaller units with single responsibilities; long units resist testing and review.", 3.0)
def q_long_units(ctx: RuleContext) -> list[Hit]:
    return [Hit(f"{c.kind} {c.name} spans {c.lines} lines.", c.line_start, ctx.snippet(c.line_start), c.name)
            for c in ctx.parsed.components if c.kind in ("method", "form", "function", "module") and c.lines > 200]


@rule("Q-005", "Exception swallowed (empty CATCH)", "quality", "medium",
      "Handle, log (e.g. ZCL_ZCA_APPLOG / BAL) or re-raise the exception; empty handlers hide production errors.", 1.0)
def q_empty_catch(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    stmts = _stmts(ctx)
    for i, st in enumerate(stmts[:-1]):
        u = st.text.upper()
        if u.startswith("CATCH") and stmts[i + 1].text.upper().startswith(("ENDTRY", "CATCH", "CLEANUP")):
            hits.append(_hit(ctx, st, "CATCH block has no statements."))
    return hits


@rule("Q-006", "Catch-all exception handler (CX_ROOT)", "quality", "low",
      "Catch the specific exception classes so programming errors are not masked.", 0.5)
def q_cx_root(ctx: RuleContext) -> list[Hit]:
    return [_hit(ctx, st, "CATCH cx_root.") for st in _stmts(ctx) if re.match(r"^CATCH\b.*\bCX_ROOT\b", st.text.upper())]


@rule("Q-007", "Debugging statement left in code", "quality", "high",
      "Remove BREAK-POINT / BREAK user before transport.", 0.25)
def q_breakpoint(ctx: RuleContext) -> list[Hit]:
    return [_hit(ctx, st, "BREAK-POINT / BREAK statement.") for st in _stmts(ctx) if re.match(r"^BREAK(-POINT)?\b", st.text.upper())]


@rule("Q-008", "Message text as literal (not translatable)", "quality", "low",
      "Use a message class (MESSAGE e001(zxx)) or text symbols so texts can be translated and reused.", 0.5)
def q_literal_message(ctx: RuleContext) -> list[Hit]:
    return [_hit(ctx, st, "MESSAGE with literal text.") for st in _stmts(ctx) if re.match(r"^MESSAGE\s+'§'\s+TYPE\b", st.text.upper())]


@rule("Q-009", "Large block of commented-out code", "quality", "info",
      "Delete dead code; version history keeps it.", 0.25)
def q_commented_code(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    run_start, run = 0, 0
    kw = re.compile(r"\b(SELECT|LOOP|ENDLOOP|IF|ENDIF|CALL|METHOD|DATA|MOVE|WRITE|PERFORM|FORM|ENDFORM|CLEAR|APPEND|READ TABLE)\b", re.I)
    for idx, raw in enumerate(ctx.lines, start=1):
        if raw.lstrip().startswith("*") and kw.search(raw):
            if run == 0:
                run_start = idx
            run += 1
        else:
            if run >= 15:
                hits.append(Hit(f"{run} consecutive commented-out code lines.", run_start, ctx.snippet(run_start), ctx.parsed.component_at(run_start)))
            run = 0
    if run >= 15:
        hits.append(Hit(f"{run} consecutive commented-out code lines.", run_start, ctx.snippet(run_start), ctx.parsed.component_at(run_start)))
    return hits


@rule("Q-010", "Object has no SAP short text", "quality", "info",
      "Maintain the short text in SE80/ADT; it feeds search, documentation and the S/4 inventory.", 0.1)
def q_no_short_text(ctx: RuleContext) -> list[Hit]:
    if ctx.is_code and not ctx.short_text.strip():
        return [Hit("Short text is empty.", 1, ctx.snippet(1))]
    return []


@rule("Q-011", "Empty stub / placeholder object", "quality", "info",
      "Implement or delete; stubs inflate the custom code inventory and confuse reuse searches.", 0.5)
def q_stub(ctx: RuleContext) -> list[Hit]:
    if ctx.type_key in ("PROG", "CLAS", "INTF") and ctx.parsed.code_lines <= 3 and ctx.attributes.get("program_type") != "Include":
        return [Hit(f"Only {ctx.parsed.code_lines} line(s) of code.", 1, ctx.snippet(1))]
    if ctx.type_key == "CLAS" and ctx.parsed.code_lines > 3:
        bodies = [c for c in ctx.parsed.components if c.kind == "method" and c.lines <= 2]
        if bodies and len(bodies) == len([c for c in ctx.parsed.components if c.kind == "method"]):
            return [Hit(f"All {len(bodies)} methods are empty.", bodies[0].line_start, ctx.snippet(bodies[0].line_start))]
    return []


@rule("Q-012", "COMMIT WORK inside business logic", "quality", "low",
      "Leave transaction control to the caller / RAP save sequence; commits inside reusable classes break composability and BAPI contracts.", 1.0)
def q_commit_in_class(ctx: RuleContext) -> list[Hit]:
    if ctx.type_key != "CLAS":
        return []
    return [_hit(ctx, st, f"COMMIT WORK in method {st.component}.") for st in _stmts(ctx) if re.match(r"^COMMIT\s+WORK\b", st.text.upper()) and st.component]


@rule("Q-013", "WAIT UP TO ... SECONDS (polling)", "quality", "medium",
      "Replace polling with event/queue based processing (qRFC, bgRFC, RAP) or make the wait configurable and bounded.", 2.0)
def q_wait(ctx: RuleContext) -> list[Hit]:
    return [_hit(ctx, st, "Blocking WAIT statement.") for st in _stmts(ctx) if re.match(r"^WAIT\s+UP\s+TO\b", st.text.upper())]


@rule("Q-014", "Hard-coded organisational value", "quality", "low",
      "Move company code / plant / sales org / currency literals to customizing (TVARVC or a Z-table).", 1.0)
def q_org_literals(ctx: RuleContext) -> list[Hit]:
    return [_hit(ctx, st, "Organisational unit compared to / assigned a literal.")
            for st in _stmts(ctx) if re.search(r"\b(BUKRS|WERKS|VKORG|VTWEG|SPART|EKORG|LGORT|KOKRS|WAERS)\s*(=|EQ|IN|DEFAULT)\s*'§'", st.text.upper()) and not st.text.upper().startswith(("SELECT-OPTIONS", "PARAMETERS"))]


@rule("Q-015", "FOR ALL ENTRIES without emptiness check", "quality", "medium",
      "Guard with IF itab IS NOT INITIAL - an empty driver table selects the whole database table.", 0.5)
def q_fae(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    stmts = _stmts(ctx)
    for i, st in enumerate(stmts):
        u = st.text.upper()
        m = re.search(r"\bFOR\s+ALL\s+ENTRIES\s+IN\s+@?([A-Z0-9_]+)", u)
        if not m:
            continue
        itab = m.group(1)
        guarded = any(re.search(rf"\b{re.escape(itab)}\b.*\bIS\s+NOT\s+INITIAL\b|\bLINES\(\s*{re.escape(itab)}\s*\)|\bCHECK\s+{re.escape(itab)}\s+IS\s+NOT\s+INITIAL", w.text.upper()) for w in stmts[max(0, i - 8):i])
        if not guarded:
            hits.append(_hit(ctx, st, f"FOR ALL ENTRIES IN {itab} without emptiness check."))
    return hits


@rule("Q-016", "Nested loops over internal tables", "quality", "low",
      "Use sorted/hashed keys, READ TABLE ... BINARY SEARCH or table expressions instead of nested LOOP ... WHERE.", 2.0)
def q_nested_loops(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    seen: set[str] = set()
    for st, loops, _ in _loop_depth_iter(_stmts(ctx)):
        if loops >= 2 and st.text.upper().startswith("LOOP") and st.component not in seen:
            seen.add(st.component)
            hits.append(_hit(ctx, st, f"LOOP nested {loops + 1} deep in {st.component or 'main program'}."))
    return hits


# ====================================================================================== Clean Core

@rule("CC-001", "Direct write to an SAP standard table", "cleancore", "high",
      "Never write SAP tables directly: use the released BAPI / API / RAP behaviour; direct writes are Tier-3 and void support.", 8.0)
def cc_std_writes(ctx: RuleContext) -> list[Hit]:
    return [Hit(f"Writes {r.target} directly.", r.line, ctx.snippet(r.line), r.component)
            for r in ctx.parsed.references if r.kind == "writes" and not is_custom_name(r.target)]


@rule("CC-002", "Classic UI technology (dynpro / list / SUBMIT)", "cleancore", "medium",
      "Not available in ABAP Cloud (Tier 1). For Clean Core target Fiori/RAP; otherwise keep in Tier 3 and document.", 6.0)
def cc_classic_ui(ctx: RuleContext) -> list[Hit]:
    hits: list[Hit] = []
    seen: set[str] = set()
    for st in _stmts(ctx):
        u = st.text.upper()
        for rx, label in ((r"^CALL\s+SCREEN\b", "CALL SCREEN"), (r"^(WRITE|ULINE|SKIP)\b", "classic list output (WRITE)"), (r"^SUBMIT\b", "SUBMIT"), (r"^SET\s+PF-STATUS\b", "GUI status"), (r"^SELECTION-SCREEN\b", "selection screen"), (r"\bREUSE_ALV_", "REUSE_ALV function module")):
            if re.search(rx, u) and label not in seen:
                seen.add(label)
                hits.append(_hit(ctx, st, f"Uses {label}."))
    return hits


@rule("CC-003", "Standard function modules used (release status unknown)", "cleancore", "info",
      "In ABAP Cloud only released APIs may be called. Check each FM in the Released Objects list (ADT) and plan replacements.", 0.5)
def cc_std_fms(ctx: RuleContext) -> list[Hit]:
    fms = sorted({r.target for r in ctx.parsed.references if r.kind == "calls_function" and not is_custom_name(r.target)})
    if not fms:
        return []
    first = next(r for r in ctx.parsed.references if r.kind == "calls_function" and not is_custom_name(r.target))
    return [Hit(f"{len(fms)} standard function module(s): {', '.join(fms[:8])}{'...' if len(fms) > 8 else ''}", first.line, ctx.snippet(first.line), first.component, effort_hours=0.5 * len(fms))]


@rule("CC-004", "Enhancement / modification object", "cleancore", "medium",
      "Enhancements are Tier 3. Check whether a released BAdI, RAP extension or key-user extensibility can replace them.", 4.0)
def cc_enhancements(ctx: RuleContext) -> list[Hit]:
    if ctx.type_key in ("ENHO", "ENHS", "SXCI"):
        return [Hit(f"{ctx.type_key} object.", 1, ctx.snippet(1))]
    return []


# ====================================================================================== Tiering

def clean_core_tier(ctx: RuleContext, findings: list[tuple[str, str]]) -> tuple[str, str]:
    """Return (tier, reason). findings: list of (rule_id, severity)."""
    if ctx.type_key in ("TABL", "DTEL", "DOMA", "TTYP", "VIEW", "SHLP", "ENQU", "MSAG", "TRAN", "DEVC", "SUSO", "AUTH", "PARA", "TOBJ", "SMIM", "W3MI", "DOCV", "IWMO", "IWPR", "IWSV", "IWSG", "IWOM", "SUSH", "WEBI", "SPRX"):
        return "-", "Not a code object; tiering applies to its consumers."
    rules = {r for r, _ in findings}
    if ctx.type_key in ("ENHO", "ENHS", "SXCI"):
        return "3", "Enhancement / modification object."
    if "CC-001" in rules:
        return "3", "Writes SAP standard tables directly."
    if any(r in rules for r in ("CC-002",)) or any(re.search(r"^EXEC\s+SQL\b|^CALL\s+'", st.text.upper()) for st in ctx.parsed.statements):
        return "3", "Classic UI / native SQL / kernel calls - not available in ABAP Cloud."
    if ctx.type_key == "DDLS" and re.search(r"define\s+(root\s+)?view\s+entity", ctx.source, re.I):
        return "1", "CDS view entity - ABAP Cloud compatible construct."
    if ctx.type_key in ("BDEF", "SRVD", "DDLX", "DCLS"):
        return "1", "RAP / CDS artefact."
    if ctx.type_key == "DDLS":
        return "2", "Classic CDS view (DDIC-based); migrate to view entity for Tier 1."
    if ctx.type_key in ("CLAS", "INTF", "FUGR", "PROG"):
        std_fms = "CC-003" in rules
        obsolete = "S4-002" in rules
        if obsolete:
            return "3", "Uses obsolete statements."
        if std_fms:
            return "2", "Developer extensibility on-stack; standard FM calls must be checked against the released-API list."
        return "2", "On-stack code with no Tier-3 signals; candidate for ABAP Cloud after API check."
    return "2", "Default on-stack tier."


def s4_status(findings: list[tuple[str, str]], is_code: bool) -> str:
    s4 = [(r, s) for r, s in findings if r.startswith("S4-")]
    if not is_code:
        return ""
    if any(s == "high" for _, s in s4):
        return "remediate"
    if s4:
        return "review"
    return "ok"

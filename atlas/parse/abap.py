"""Structural parser for ABAP and CDS source.

Not a full grammar: a tokenised, statement-aware scan that is good enough to
answer the questions architects ask - which methods exist and where, which
tables are read or written, which function modules / classes / programs are
called, which authorization objects are checked. Every extraction records the
line number so findings and dependency edges point at real code.

Comments and string literals are masked before scanning so a table name in a
comment or a SELECT inside a text literal never produces a false edge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SAP_NAMESPACES = ("/iwbep/", "/ui2/", "/ui5/", "/bobf/", "/scwm/", "/sapsrm/", "/aif/", "/dmo/", "/sdf/", "/ssf/", "/bi0/", "/bic/")


@dataclass
class Component:
    kind: str          # method | function | form | module | class | interface | event
    name: str
    line_start: int
    line_end: int
    parent: str = ""   # class name for methods

    @property
    def lines(self) -> int:
        return self.line_end - self.line_start + 1


@dataclass
class Reference:
    kind: str          # reads | writes | calls_function | calls_class | inherits | implements | raises | includes | submits | calls_transaction | authority_check | uses_cds | message_class
    target: str        # upper-case name
    target_type: str   # table | function | class | interface | program | transaction | auth_object | include | cds | message_class
    line: int
    component: str = ""

    @property
    def is_custom(self) -> bool:
        return is_custom_name(self.target)


@dataclass
class Statement:
    text: str          # normalised, comments/literals masked, single spaces, upper case
    line: int          # first line of the statement
    component: str = ""
    line_end: int = 0  # last line of the statement (>= line)

    def __post_init__(self) -> None:
        if not self.line_end:
            self.line_end = self.line


@dataclass
class ParsedSource:
    components: list[Component] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    statements: list[Statement] = field(default_factory=list)
    string_literals: list[tuple[int, str]] = field(default_factory=list)   # (line, literal) for credential checks
    internal_tables: set[str] = field(default_factory=set)
    total_lines: int = 0
    comment_lines: int = 0
    code_lines: int = 0
    max_nesting: int = 0

    def component_at(self, line: int) -> str:
        for c in self.components:
            if c.kind in ("method", "function", "form", "module") and c.line_start <= line <= c.line_end:
                return c.name
        return ""


def is_custom_name(name: str) -> bool:
    n = name.upper()
    if n.startswith("/"):
        return not any(n.startswith(ns.upper()) for ns in SAP_NAMESPACES)
    return n.startswith(("Z", "Y"))


# --- masking -------------------------------------------------------------------------------

_STRING = re.compile(r"'(?:[^']|'')*'|`(?:[^`]|``)*`")
_INLINE_COMMENT = re.compile(r'"[^\n]*')


def mask_line(line: str, literals: list[str]) -> str:
    """Replace literals by placeholders (keeping their text aside) and drop inline comments."""
    if line.lstrip().startswith("*"):
        return ""

    def _keep(match: re.Match) -> str:
        literals.append(match.group(0)[1:-1])
        return "'§'"

    masked = _STRING.sub(_keep, line)
    return _INLINE_COMMENT.sub("", masked)


# --- parsing -------------------------------------------------------------------------------

_BLOCK_START = {
    "METHOD": "method", "FUNCTION": "function", "FORM": "form", "MODULE": "module",
}
_BLOCK_END = {"ENDMETHOD": "method", "ENDFUNCTION": "function", "ENDFORM": "form", "ENDMODULE": "module"}
_NEST_OPEN = re.compile(r"^(LOOP|DO|WHILE|IF|CASE|TRY|PROVIDE)\b")
_NEST_CLOSE = re.compile(r"^(ENDLOOP|ENDDO|ENDWHILE|ENDIF|ENDCASE|ENDTRY|ENDPROVIDE)\b")

_IT_DECL = re.compile(r"\b(?:DATA|CLASS-DATA|STATICS|FIELD-SYMBOLS)\b[:\s]+(?:<)?([A-Z0-9_/]+)(?:>)?\s+TYPE\s+(?:STANDARD\s+|SORTED\s+|HASHED\s+)?TABLE\s+OF", re.I)
_IT_DECL2 = re.compile(r"\b([A-Z0-9_/]+)\s+TYPE\s+(?:STANDARD\s+|SORTED\s+|HASHED\s+)?TABLE\s+OF", re.I)
_IT_DECL3 = re.compile(r"\b([A-Z0-9_/]+)\s+(?:TYPE|LIKE)\s+[A-Z0-9_/]+\s+OCCURS\b", re.I)


def parse_abap(source: str, is_cds: bool = False) -> ParsedSource:
    parsed = ParsedSource()
    lines = source.splitlines()
    parsed.total_lines = len(lines)

    if is_cds:
        _parse_cds(source, parsed)
        return parsed

    # ---- pass 1: mask, split statements, collect literals -----------------------------
    statements: list[Statement] = []
    buffer: list[str] = []
    start_line = 0
    for idx, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("*"):
            parsed.comment_lines += 1
            continue
        literals: list[str] = []
        masked = mask_line(raw, literals)
        for lit in literals:
            parsed.string_literals.append((idx, lit))
        if not masked.strip():
            parsed.comment_lines += 1
            continue
        parsed.code_lines += 1
        # A line may hold several statements ("IF x. ELSE. ENDIF.") - split on
        # statement-ending periods (literals are already masked to '§').
        pieces = re.split(r"\.(?=\s|$)", masked.strip())
        for n, piece in enumerate(pieces):
            piece = piece.strip()
            is_last = n == len(pieces) - 1
            if piece:
                if not buffer:
                    start_line = idx
                buffer.append(piece)
            if not is_last and buffer:
                statements.extend(_split_chain(" ".join(buffer) + ".", start_line, idx))
                buffer = []
    if buffer:
        statements.extend(_split_chain(" ".join(buffer) + ".", start_line, len(lines)))

    # ---- pass 2: blocks, nesting, internal tables -------------------------------------
    open_blocks: list[Component] = []
    current_class = ""
    depth = 0
    for st in statements:
        upper = st.text.upper()
        first = upper.split(" ", 1)[0].rstrip(".")
        words = upper.rstrip(".").split()

        m = re.match(r"^CLASS\s+([A-Z0-9_/]+)\s+(DEFINITION|IMPLEMENTATION)", upper)
        if m:
            current_class = m.group(1)
            if m.group(2) == "DEFINITION" and "LOAD" not in upper and "DEFERRED" not in upper:
                parsed.components.append(Component("class", current_class, st.line, st.line, ""))
        m = re.match(r"^INTERFACE\s+([A-Z0-9_/]+)", upper)
        if m and "LOAD" not in upper and "DEFERRED" not in upper:
            parsed.components.append(Component("interface", m.group(1), st.line, st.line, ""))

        if first in _BLOCK_START and len(words) > 1 and first != "MODULE" or (first == "MODULE" and len(words) > 1 and words[1] not in ("INPUT", "OUTPUT")):
            name = words[1].strip(".")
            comp = Component(_BLOCK_START[first], name, st.line, st.line, current_class if first == "METHOD" else "")
            open_blocks.append(comp)
            parsed.components.append(comp)
            depth = 0
        elif first in _BLOCK_END and open_blocks:
            comp = open_blocks.pop()
            comp.line_end = st.line
            depth = 0

        st.component = open_blocks[-1].name if open_blocks else ""

        if _NEST_OPEN.match(upper):
            depth += 1
            parsed.max_nesting = max(parsed.max_nesting, depth)
        elif _NEST_CLOSE.match(upper):
            depth = max(0, depth - 1)

        for rx in (_IT_DECL, _IT_DECL2, _IT_DECL3):
            for hit in rx.finditer(upper):
                parsed.internal_tables.add(hit.group(1).strip("<>"))

    for comp in open_blocks:          # unterminated blocks (truncated source)
        comp.line_end = parsed.total_lines

    parsed.statements = statements

    # ---- pass 3: references -------------------------------------------------------------
    for st in statements:
        _extract_references(st, parsed)

    return parsed


def _split_chain(text: str, line: int, line_end: int = 0) -> list[Statement]:
    """`DATA: a, b.` -> two statements sharing the line; anything else -> one."""
    text = re.sub(r"\s+", " ", text).strip()
    line_end = line_end or line
    if ":" in text and not text.upper().startswith(("SELECT", "CONCATENATE")) and re.match(r"^[A-Z\-]+\s*:", text, re.I):
        head, rest = text.split(":", 1)
        head = head.strip()
        parts = [p.strip() for p in re.split(r",(?![^()]*\))", rest.rstrip(".")) if p.strip()]
        return [Statement(f"{head} {p}.", line, "", line_end) for p in parts]
    return [Statement(text, line, "", line_end)]


_TABLE_NAME = r"([A-Z0-9_/]{3,})"
_RX_READ = re.compile(r"\b(?:FROM|JOIN)\s+" + _TABLE_NAME, re.I)
_RX_WRITE = [
    re.compile(r"\bUPDATE\s+" + _TABLE_NAME, re.I),
    re.compile(r"\bINSERT\s+(?:INTO\s+)?" + _TABLE_NAME + r"\b(?!\s+INTO\b)", re.I),
    re.compile(r"\bMODIFY\s+" + _TABLE_NAME + r"\s+(?:FROM|CLIENT)\b", re.I),
    re.compile(r"\bDELETE\s+(?:FROM\s+)?" + _TABLE_NAME + r"\s+(?:FROM|WHERE|CLIENT)\b", re.I),
]
_RX_CALL_FUNCTION = re.compile(r"\bCALL\s+FUNCTION\s+'§'", re.I)
_RX_CLASS_REFS = [
    (re.compile(r"\b(?:TYPE\s+REF\s+TO|CREATE\s+OBJECT\s+[A-Z0-9_\->]+\s+TYPE|NEW)\s+([A-Z0-9_/]+)", re.I), "calls_class"),
    (re.compile(r"\b([A-Z0-9_/]+)=>", re.I), "calls_class"),
    (re.compile(r"\bINHERITING\s+FROM\s+([A-Z0-9_/]+)", re.I), "inherits"),
    (re.compile(r"\bINTERFACES\s+([A-Z0-9_/]+)", re.I), "implements"),
    (re.compile(r"\bRAISE\s+EXCEPTION\s+TYPE\s+([A-Z0-9_/]+)", re.I), "raises"),
    (re.compile(r"\bCATCH\s+((?:[A-Z0-9_/]+\s*)+?)(?:INTO\b|\.)", re.I), "catches"),
]
_RX_AUTH = re.compile(r"\bAUTHORITY-CHECK\s+OBJECT\s+'§'", re.I)
_RX_SUBMIT = re.compile(r"\bSUBMIT\s+([A-Z0-9_/]+)", re.I)
_RX_TRAN = re.compile(r"\bCALL\s+TRANSACTION\s+'§'", re.I)
_RX_INCLUDE = re.compile(r"^INCLUDE\s+(?!STRUCTURE\b|TYPE\b)([A-Z0-9_/]+)", re.I)
_RX_TABLES = re.compile(r"^TABLES\s+([A-Z0-9_/*]+)", re.I)
_RX_FOR_FIELD = re.compile(r"\bFOR\s+([A-Z0-9_/]+)-[A-Z0-9_/]+", re.I)
_RX_PERFORM_EXT = re.compile(r"\bPERFORM\s+[A-Z0-9_/]+(?:\(([A-Z0-9_/]+)\)|\s+IN\s+PROGRAM\s+([A-Z0-9_/]+))", re.I)
_RX_MSGID = re.compile(r"\bMESSAGE-ID\s+([A-Z0-9_/]+)|\bMESSAGE\s+[A-Z]\d{3}\(([A-Z0-9_/]+)\)|\bMESSAGE\s+ID\s+'§'", re.I)

_NOT_TABLES = {"TABLE", "SELECT", "SCREEN", "MEMORY", "DATASET", "TRANSACTION", "DATABASE", "CORRESPONDING", "FIELDS", "INTO", "WHERE", "ORDER", "GROUP", "INNER", "LEFT", "OUTER", "RIGHT", "CROSS", "ON", "AS", "SINGLE", "DISTINCT", "UP", "TO", "ROWS", "CLIENT", "SPECIFIED", "FOR", "ALL", "ENTRIES", "IN", "LINES", "OF", "INDEX", "REPORT", "LIST", "PROGRAM", "TABLES", "LINE", "TEXTPOOL", "DYNPRO", "ADJACENT", "DUPLICATES", "COMPARING", "INITIAL", "APPEND", "DATA", "SHARED", "BUFFER", "OBJECTS", "PARAMETER", "ID", "SEPARATED", "BY", "SPACE", "RESPECTING", "BLANKS", "MODE"}


def _is_table_candidate(name: str, parsed: ParsedSource) -> bool:
    n = name.upper()
    if n in _NOT_TABLES or n in parsed.internal_tables or n.startswith("§"):
        return False
    if re.match(r"^(LT|GT|IT|ET|CT|RT|MT|LS|GS|IS|ES|CS|RS|MS|LR|GR|LO|GO|LV|GV|IV|EV|CV|RV|MV|LI|GI)_", n):
        return False
    if n.startswith(("@", "<")) or n.endswith(">"):
        return False
    if re.match(r"^(CL|CX|IF|ZCL|ZCX|ZIF|YCL|YCX|YIF)_", n):
        return False
    return bool(re.match(r"^[A-Z/][A-Z0-9_/]{2,}$", n))


def _extract_references(st: Statement, parsed: ParsedSource) -> None:
    text = st.text
    upper = text.upper()
    literals_on_line = [lit for (ln, lit) in parsed.string_literals if st.line <= ln <= st.line_end]

    def literal(n: int = 0) -> str:
        return literals_on_line[n].upper() if len(literals_on_line) > n else ""

    def add(kind: str, target: str, target_type: str) -> None:
        target = target.upper().strip()
        if target and target != "§":
            parsed.references.append(Reference(kind, target, target_type, st.line, st.component))

    if upper.startswith(("SELECT", "WITH", "OPEN CURSOR")) or " FROM " in upper and upper.startswith(("SELECT", "OPEN")):
        for m in _RX_READ.finditer(text):
            if _is_table_candidate(m.group(1), parsed):
                add("reads", m.group(1), "table")
    elif upper.startswith(("UPDATE", "INSERT", "MODIFY", "DELETE")):
        for rx in _RX_WRITE:
            m = rx.search(text)
            if m and _is_table_candidate(m.group(1), parsed):
                add("writes", m.group(1), "table")
                break

    m = _RX_TABLES.match(text)
    if m:
        add("declares", m.group(1).lstrip("*"), "table")
    if upper.startswith("SELECT-OPTIONS"):
        m = _RX_FOR_FIELD.search(text)
        if m and _is_table_candidate(m.group(1), parsed):
            add("declares", m.group(1), "table")
    if _RX_CALL_FUNCTION.search(text):
        add("calls_function", literal(0), "function")
    if _RX_AUTH.search(text):
        add("authority_check", literal(0), "auth_object")
    if _RX_TRAN.search(text):
        add("calls_transaction", literal(0), "transaction")
    m = _RX_SUBMIT.search(text)
    if m:
        add("submits", m.group(1), "program")
    m = _RX_INCLUDE.match(text)
    if m:
        add("includes", m.group(1), "include")
    m = _RX_PERFORM_EXT.search(text)
    if m:
        add("calls_program", m.group(1) or m.group(2), "program")
    m = _RX_MSGID.search(text)
    if m:
        add("message_class", m.group(1) or m.group(2) or literal(0), "message_class")

    for rx, kind in _RX_CLASS_REFS:
        for m in rx.finditer(text):
            names = m.group(1).split() if kind == "catches" else [m.group(1)]
            for name in names:
                n = name.upper()
                if re.match(r"^(Z|Y|/|CL_|CX_|IF_|ZCL_|ZCX_|ZIF_|YCL_|YCX_|YIF_|/IWBEP/|/UI2/|/BOBF/)", n) and n not in ("ZERO",):
                    target_type = "interface" if re.match(r"^(Z?Y?IF_|/[A-Z0-9]+/IF_|IF_)", n) else "class"
                    add(kind, n, target_type)


# --- CDS ---------------------------------------------------------------------------------

_CDS_FROM = re.compile(r"\b(?:from|join)\s+([A-Za-z0-9_/]+)", re.I)
_CDS_ASSOC = re.compile(r"\bassociation\b[^\n]*?\bto\s+([A-Za-z0-9_/]+)", re.I)
_CDS_DEFINE = re.compile(r"\bdefine\s+(?:root\s+)?(?:view\s+entity|view|table\s+function|abstract\s+entity|custom\s+entity)\s+([A-Za-z0-9_/]+)", re.I)
_CDS_EXTEND = re.compile(r"\bextend\s+view(?:\s+entity)?\s+([A-Za-z0-9_/]+)", re.I)
_CDS_EXTEND_WITH = re.compile(r"\bextend\s+view(?:\s+entity)?\s+[A-Za-z0-9_/]+\s+with\s+([A-Za-z0-9_/]+)", re.I)


def _parse_cds(source: str, parsed: ParsedSource) -> None:
    for idx, raw in enumerate(source.splitlines(), start=1):
        line = re.sub(r"//.*$", "", raw)
        if not line.strip():
            continue
        if raw.strip().startswith(("//", "@")):
            if raw.strip().startswith("//"):
                parsed.comment_lines += 1
            continue
        parsed.code_lines += 1
        m = _CDS_DEFINE.search(line)
        if m:
            parsed.components.append(Component("cds", m.group(1).upper(), idx, parsed.total_lines))
        m = _CDS_EXTEND.search(line)
        if m:
            parsed.references.append(Reference("extends", m.group(1).upper(), "cds", idx))
        for m in _CDS_FROM.finditer(line):
            name = m.group(1).upper()
            if name not in ("SELECT",):
                parsed.references.append(Reference("reads", name, "cds_or_table", idx))
        for m in _CDS_ASSOC.finditer(line):
            parsed.references.append(Reference("uses_cds", m.group(1).upper(), "cds_or_table", idx))

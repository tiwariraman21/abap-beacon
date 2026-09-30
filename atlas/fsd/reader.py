"""Read a functional specification and turn it into discrete requirements.

Supported inputs: .docx (parsed from the OOXML directly, no extra library),
.md, .txt. The document becomes a list of blocks (heading / paragraph /
bullet / table row); requirements are the statements that describe what the
solution must do, classified by kind (selection, processing, integration,
output, validation, authorization, error handling, performance, data model,
scheduling) with the SAP entities they mention (tables, fields, FMs/BAPIs,
transactions).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from atlas.reference.sap_objects import TABLES

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class Block:
    kind: str          # heading | para | bullet | row
    text: str
    level: int = 0     # heading level, or bullet nesting level
    section: str = ""  # nearest heading text
    list_id: str = ""  # numbering id (docx) - a new id under a "...:" bullet marks sub-items


@dataclass
class Requirement:
    id: str
    text: str
    section: str
    kind: str
    weight: int
    entities: dict[str, list[str]] = field(default_factory=dict)   # tables, fields, functions, tcodes, custom_objects

    @property
    def search_text(self) -> str:
        ents = " ".join(v for vals in self.entities.values() for v in vals)
        return f"{self.text} {ents}".strip()


# --------------------------------------------------------------------------- reading

class FsdReadError(ValueError):
    """The file could not be read as a functional specification (message is user-facing)."""


SUPPORTED = (".docx", ".pdf", ".md", ".markdown", ".txt", ".text")


def read_document(path: str | Path) -> tuple[str, list[Block]]:
    """Return (title, blocks). Never raises anything but FsdReadError for a bad file."""
    path = Path(path)
    if not path.exists():
        raise FsdReadError(f"{path.name} does not exist")
    if path.stat().st_size == 0:
        raise FsdReadError(f"{path.name} is empty")
    suffix = path.suffix.lower()
    try:
        if suffix == ".docx":
            blocks = _read_docx(path)
        elif suffix == ".pdf":
            blocks = _read_pdf(path)
        elif suffix in (".md", ".markdown", ".txt", ".text", ""):
            blocks = _read_markdown(_read_text(path))
        elif suffix == ".doc":
            raise FsdReadError(f"{path.name} is an old binary Word file - open it in Word and save it as .docx, then upload again")
        else:
            raise FsdReadError(f"Unsupported FSD format {suffix!r} - upload .docx, .pdf, .md or .txt")
    except FsdReadError:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as error:
        raise FsdReadError(f"{path.name} is not a valid Word document ({error.__class__.__name__}) - re-save it as .docx and try again") from error
    except Exception as error:
        raise FsdReadError(f"{path.name} could not be read: {error}") from error
    if not any(b.text.strip() for b in blocks):
        raise FsdReadError(f"{path.name} contains no readable text (scanned image or empty document?)")
    return document_title(blocks, path.stem.replace("_", " ")), blocks


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_pdf(path: Path) -> list[Block]:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise FsdReadError("PDF support needs the pypdf package: pip install pypdf") from error
    reader = PdfReader(str(path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return _read_markdown(text)


_TITLE_NOISE = ("document control", "revision history", "version history", "table of contents", "contents", "reviewers", "approvers",
                "distribution", "author", "confidential", "functional specification document", "functional specification", "fsd")


def document_title(blocks: list[Block], fallback: str) -> str:
    """The first real heading: a markdown/Word title that is not document-control noise and
    not a numbered section ("1. Scope"); then the first non-noise heading; then the file name."""
    heads = [b.text.strip() for b in blocks if b.kind == "heading"]
    def clean(t: str) -> str:
        return re.sub(r"^#+\s*", "", t).strip(" :-–")
    def noise(t: str) -> bool:
        low = t.lower()
        return low.strip(" :") in _TITLE_NOISE or any(low.startswith(n) for n in ("document control", "revision history", "version history", "table of contents"))
    for t in heads:
        c = clean(t)
        if c and not noise(c) and not re.match(r"^\d+(\.\d+)*\.?\s", c) and len(c.split()) >= 2:
            return c
    # cover page: a paragraph / table row before the first heading that names the document
    for b in blocks[:6]:
        if b.kind == "heading":
            break
        first = b.text.split("|")[0].strip()
        if 3 <= len(first.split()) <= 20 and not noise(first) and not MODAL.search(first) and not BOILERPLATE.match(first):
            return clean(first)
    for t in heads:
        c = clean(t)
        if c and not noise(c):
            return c
    return fallback


def _iter_body(node):
    """Paragraphs and tables in document order, descending into content controls / other wrappers
    but not into tables (their cells are read as rows)."""
    for child in node:
        if child.tag in (f"{W}p", f"{W}tbl"):
            yield child
        elif child.tag not in (f"{W}sectPr",):
            yield from _iter_body(child)


def _read_docx(path: Path) -> list[Block]:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{W}body")
    if body is None:
        raise FsdReadError(f"{path.name} has no document body")
    blocks: list[Block] = []
    section = ""
    for child in _iter_body(body):
        if child.tag == f"{W}p":
            text = _para_text(child)
            if not text:
                continue
            style = child.find(f"{W}pPr/{W}pStyle")
            style_val = style.get(f"{W}val", "") if style is not None else ""
            num = child.find(f"{W}pPr/{W}numPr")
            ilvl = child.find(f"{W}pPr/{W}numPr/{W}ilvl")
            num_id = child.find(f"{W}pPr/{W}numPr/{W}numId")
            level = int(ilvl.get(f"{W}val", "0") or 0) if ilvl is not None else 0
            list_id = num_id.get(f"{W}val", "") if num_id is not None else ""
            m = re.search(r"(?:heading|berschrift|titre|t[ií]tulo)\s*(\d)", style_val, re.I)
            md = re.match(r"^(#{1,6})\s+(.+)$", text)
            if md:                                             # literal markdown heading pasted into Word
                section = md.group(2).strip()
                blocks.append(Block("heading", section, len(md.group(1)), section))
            elif m or style_val.lower() in ("title", "subtitle"):
                lvl = int(m.group(1)) if m else 0
                section = text
                blocks.append(Block("heading", text, lvl, section))
            elif _looks_like_heading(text):
                section = text
                blocks.append(Block("heading", text, 2, section))
            elif num is not None or style_val.lower().startswith(("list", "bullet")):
                blocks.append(Block("bullet", text, level, section, list_id))
            else:
                blocks.append(Block("para", text, 0, section))
        elif child.tag == f"{W}tbl":
            n = 0
            for row in child.iter(f"{W}tr"):
                cells = [_para_text_all(c) for c in row.findall(f"{W}tc")]
                cells = [c for c in cells if c]
                if cells:
                    blocks.append(Block("row", " | ".join(cells), n, section))     # level = row index (0 = header)
                    n += 1
    return blocks


def _para_text(p) -> str:
    return "".join(t.text or "" for t in p.iter(f"{W}t")).strip()


def _para_text_all(tc) -> str:
    return " ".join(_para_text(p) for p in tc.findall(f"{W}p") if _para_text(p)).strip()


_SMALL = {"and", "or", "of", "the", "for", "to", "in", "on", "with", "a", "an", "by", "from", "vs", "&", "/", "-", "–"}


def _title_case(text: str) -> bool:
    words = re.sub(r"^\d+(\.\d+)*\.?\s+", "", text).replace("/", " ").split()
    return bool(words) and all(w.lower() in _SMALL or w[:1].isupper() or w[:1].isdigit() or not w[:1].isalpha() for w in words)


def _looks_like_heading(text: str) -> bool:
    text = text.strip()
    if len(text) < 60 and text.isupper() and len(text.split()) <= 6:
        return True
    return bool(re.match(r"^\d+(\.\d+)*\.?\s+[A-Z][^.]{2,60}$", text)) and len(text.split()) <= 9 and _title_case(text) and not MODAL.search(text)


def _read_markdown(text: str) -> list[Block]:
    blocks: list[Block] = []
    section = ""
    row_n = 0
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            section = m.group(2).strip()
            blocks.append(Block("heading", section, len(m.group(1)), section))
            row_n = 0
            continue
        if re.match(r"^\s*\|.*\|\s*$", line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
                continue
            blocks.append(Block("row", " | ".join(c for c in cells if c), row_n, section))
            row_n += 1
            continue
        row_n = 0
        if re.match(r"^\d+(\.\d+)*\.?\s+\S", line.strip()) and _looks_like_heading(line.strip()):
            section = line.strip()
            blocks.append(Block("heading", section, 2, section))
            row_n = 0
            continue
        m = re.match(r"^(\s*)(?:[-*+•]|\d+[.)]|[a-z][.)]|R\d+[:.]?|REQ-?\d+[:.]?)\s+(.*)$", line, re.I)
        if m:
            indent = len(m.group(1).replace("\t", "    "))
            blocks.append(Block("bullet", m.group(2).strip(), indent // 2, section))
            continue
        if _looks_like_heading(line.strip()):
            section = line.strip()
            blocks.append(Block("heading", section, 2, section))
            continue
        blocks.append(Block("para", line.strip(), 0, section))
    return blocks


# --------------------------------------------------------------------------- requirements

KIND_RULES: list[tuple[str, int, tuple[str, ...]]] = [
    # (kind, weight, keywords) - evaluated in order, first section match wins, then text match
    ("integration", 3, ("interface", "api", "odata", "rest ", "web service", "idoc", "json", "http", "inbound", "outbound", "middleware", "cpi", "endpoint", "payload", "integration", "exposed as", "call the", "calls the", "response")),
    ("scheduling", 1, ("background job", "batch job", "schedule", "nightly", "daily", "periodic", "hourly", "run automatically", "sm36")),
    ("authorization", 1, ("authorization", "authorisation", "authority", "authorized", "authorised", "permission", "access rights", "access to", "authenticat")),
    ("error_handling", 1, ("error", "log", "exception", "message", "slg1", "notify", "failure", "rollback")),
    ("output", 2, ("output", "display", "alv", "list ", "column", "layout", "download", "excel", "pdf", "print", "email", "e-mail", "notif", "form", "screen shows", "shown", "show ", "total", "subtotal", "attachment")),
    ("selection", 1, ("selection screen", "selection", "select-options", "parameter", "input", "user enters", "user selects", "mandatory", "optional", "default", "range", "filter by", "variant")),
    ("validation", 2, ("validate", "validation", "check", "duplicate", "must exist", "verify", "exists", "not allowed", "reject", "invalid", "mandatory")),
    ("data_model", 2, ("custom table", "z table", "table z", "field", "store", "maintenance", "sm30", "domain", "data element", "structure", "configuration table", "mapping table")),
    ("performance", 1, ("performance", "within seconds", "response time", "volume", "records per", "million", "parallel")),
    ("mapping", 1, ("map to", "mapped to", "direct mapping", "field mapping", "source field", "target field")),
    ("scope", 1, ()),
    ("processing", 3, ()),
]
SCOPE_SECTION = re.compile(r"\b(scope|objective|objectives|purpose|overview|introduction|background|in scope)\b", re.I)
SCOPE_TEXT = re.compile(r"^(the )?(objective|purpose|goal|aim|scope) (of this|is|are)\b", re.I)

SECTION_KIND = {
    "mapping": ("mapping", "field list", "field-level", "field level"),
    "selection": ("selection", "input", "parameters", "criteria"),
    "output": ("output", "display", "layout", "report format", "alv", "columns", "email", "print"),
    "integration": ("interface", "integration", "api", "mapping"),
    "authorization": ("authorization", "authorisation", "security"),
    "error_handling": ("error", "exception", "logging", "messages"),
    "performance": ("performance", "volume", "non-functional"),
    "data_model": ("data model", "table", "custom table", "database"),
    "validation": ("validation", "checks", "business rules"),
    "processing": ("processing", "logic", "process", "flow", "functional requirement", "requirement", "solution", "steps", "business logic", "functionality"),
    "scheduling": ("schedul", "batch", "job"),
}

SKIP_SECTIONS = ("document control", "version history", "revision", "approval", "sign-off", "sign off", "table of contents", "contents", "author", "distribution", "glossary", "abbreviation", "reference document", "purpose of this document", "assumption", "open point", "open issue", "appendix", "test case", "unit test", "test scenario",
                 # not requirements: how the project is run, tested, rolled out or taught
                 "testing", "test strategy", "test plan", "test type", "rollout", "roll-out", "roll out", "cutover", "cut-over", "fallback", "fall-back", "contingency",
                 "training", "documentation", "reviewers", "approvers", "target readership", "readership", "landscape", "key sap objects", "objects and bapis", "objects involved",
                 "timeline", "milestone", "risks", "dependencies", "stakeholder", "cost estimate", "effort estimate")
AS_IS = re.compile(r"^(today|currently|at present|as of now|in the current|the current process|historically)\b", re.I)
MODAL = re.compile(r"\b(shall|should|must|need(s)? to|required|will|has to|have to|is to be|are to be|able to|expected to|can|allow|enable)\b", re.I)
BOILERPLATE = re.compile(r"^(prepared by|reviewed by|approved by|date|version|status|author|page \d|confidential|copyright|table of contents|this document (defines|describes|specifies|outlines|covers|provides|details)|the purpose of this document)\b", re.I)
_SKIP_RX = re.compile(r"\b(" + "|".join(re.escape(t) for t in SKIP_SECTIONS) + r")\b", re.I)


def in_skipped_section(section: str) -> bool:
    return bool(_SKIP_RX.search(section or ""))

_TABLE_RX = re.compile(r"\b([A-Z][A-Z0-9_]{3,15})\b")
_FIELD_RX = re.compile(r"\b(NAME2|LIFNR|KUNNR|BUKRS|WERKS|MATNR|VBELN|EBELN|EBELP|BELNR|GJAHR|BUDAT|BLDAT|ZFBDT|WRBTR|DMBTR|WAERS|VKORG|VTWEG|SPART|EKORG|EKGRP|LGORT|KOSTL|AUFNR|PERNR|POSNR|MEINS|MENGE|NETWR|KNUMV|ERDAT|ERNAM|AEDAT|UNAME|SGTXT|AUGBL|AUGDT|ZTERM|BANKL|BANKN|IBAN|HBKID|HKTID|STCD1|STCD3|REGIO|LAND1|ORT01|PSTLZ|NAME1|EMAIL|SMTP_ADDR)\b")
_FM_RX = re.compile(r"\b((?:BAPI|RFC|Z|Y)_[A-Z0-9_]{4,}|[A-Z]{2,}(?:_[A-Z0-9]+){2,})\b")
_TCODE_RX = re.compile(r"\b([A-Z]{1,4}\d{1,3}[A-Z]?N?|F\.\d{2}|F-\d{2}|ME\d\dN?|MIGO|MIRO|VA0\d|VF0\d|VL0\dN?|FB\d\d|SM3\d|SE\d\d|SLG1|SOST)\b")
_CUSTOM_RX = re.compile(r"\b([ZY][A-Z0-9_]{3,29})\b")


def extract_entities(text: str) -> dict[str, list[str]]:
    up = text.upper()
    tables = sorted({m for m in _TABLE_RX.findall(up) if m in TABLES})
    fields = sorted(set(_FIELD_RX.findall(up)))
    fms = sorted({m for m in _FM_RX.findall(up) if m not in tables and not m.startswith(("ZZ", "YY")) and len(m) > 7 and not _TCODE_RX.fullmatch(m)})
    tcodes = sorted({m for m in _TCODE_RX.findall(up) if m not in tables and m not in fields})
    custom = sorted({m for m in _CUSTOM_RX.findall(up) if "_" in m})
    fms = [f for f in fms if f not in custom]
    out: dict[str, list[str]] = {}
    for key, vals in (("tables", tables), ("fields", fields), ("functions", fms), ("tcodes", tcodes), ("custom_objects", custom)):
        if vals:
            out[key] = vals
    return out


def classify(text: str, section: str) -> tuple[str, int]:
    sec = section.lower()
    if SCOPE_TEXT.match(text) or (SCOPE_SECTION.search(sec) and not MODAL.search(text) and not extract_entities(text)):
        return "scope", 1                           # scope / objective statements restate the detailed requirements - no separate effort
    for kind, words in SECTION_KIND.items():
        if any(w in sec for w in words) and kind != "processing":
            # section decides unless the text clearly says otherwise for integration/validation
            weight = next(w for k, w, _ in KIND_RULES if k == kind)
            return kind, weight
    low = " " + text.lower() + " "
    best, best_hits = ("processing", 3), 0
    for kind, weight, words in KIND_RULES:
        hits = sum(1 for w in words if w in low)
        if hits > best_hits:
            best, best_hits = (kind, weight), hits
    return best


def is_requirement(block: Block) -> bool:
    text = block.text
    if len(text.split()) < 4 or (block.kind != "para" and BOILERPLATE.match(text)):
        return False
    if in_skipped_section(block.section):
        return False
    if block.kind == "heading":
        return False
    if block.kind == "row":
        if not block.section:                      # cover page table (title / logo / project box)
            return False
        cells = [c.strip() for c in text.split("|")]
        if block.level == 0 and len(cells) >= 2:   # header row
            return False
        if any(MODAL.search(c) or len(c.split()) >= 6 for c in cells):
            return True
        # field-mapping / mode tables: "BP Name | Name1/Name2 | Map to appropriate name fields"
        spec_table = any(k in block.section.lower() for k in ("mapping", "field", "synchroni", "mode", "interface", "rule", "logic"))
        return spec_table and len(cells) >= 3 and (max(len(c.split()) for c in cells) >= 3 or bool(extract_entities(text)))
    if block.kind == "bullet":
        return True
    return bool(MODAL.search(text)) or len(text.split()) >= 12 and any(k in block.section.lower() for words in SECTION_KIND.values() for k in words)


ALTERNATIVES = re.compile(r"\b(based on|can be|could be|may be|one of|options?|either|such as|for example|e\.g\.|ensure they are|must be|are:|is:)\s*:?$|\b(based on|can be|could be|may be|one of|either|such as|ensure they are)\b", re.I)


def group_bullets(blocks: list[Block]) -> list[Block]:
    """Merge nested bullets with their "...:" parent.

    A parent bullet that ends with ':' owns the bullets that follow it at a deeper level (or with a
    different numbering id at the same level). When the parent lists alternatives / attributes
    ("Change detection can be based on:" + three options) or the children are short fragments,
    they become ONE requirement; otherwise each child becomes its own requirement carrying the
    parent as context ("If a BAPI call fails: Retry mechanism (3 attempts)")."""
    out: list[Block] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.kind == "bullet" and b.text.rstrip().endswith(":") and i + 1 < len(blocks) and blocks[i + 1].kind == "bullet":
            children: list[Block] = []
            j = i + 1
            while j < len(blocks) and blocks[j].kind == "bullet" and blocks[j].section == b.section and (
                blocks[j].level > b.level or (blocks[j].list_id and blocks[j].list_id != b.list_id and not blocks[j].text.rstrip().endswith(":"))
            ):
                children.append(blocks[j])
                j += 1
            if children:
                parent = b.text.rstrip().rstrip(":").strip()
                short = all(len(c.text.split()) <= 8 and not MODAL.search(c.text) for c in children)
                if ALTERNATIVES.search(b.text) or short:
                    out.append(Block("bullet", parent + ": " + "; ".join(c.text.strip().rstrip(".") for c in children), b.level, b.section, b.list_id))
                else:
                    for c in children:
                        out.append(Block("bullet", f"{parent}: {c.text.strip()}", b.level, b.section, b.list_id))
                i = j
                continue
        out.append(b)
        i += 1
    return out


_DETAIL_SECTION = re.compile(r"\b(functional|requirement|process|logic|design|flow|solution|mapping|validation|selection|output|error|authori|schedul|interface|integration|technical)", re.I)


def _first_detail_index(blocks: list[Block]) -> int:
    """Index of the first heading that opens the detailed part of the FSD; everything requirement-like
    before it (objective, scope, context) is a summary of what follows, whatever the headings are called."""
    for i, b in enumerate(blocks):
        if b.kind == "heading" and _DETAIL_SECTION.search(b.text) and not SCOPE_SECTION.search(b.text) and not re.search(r"\bbusiness requirement", b.text, re.I):
            return i
    return -1


def extract_requirements(blocks: list[Block]) -> list[Requirement]:
    reqs: list[Requirement] = []
    seen: set[str] = set()
    grouped = group_bullets(blocks)
    detail_from = _first_detail_index(grouped)
    intro_sections = {b.section for b in grouped[:detail_from]} if detail_from > 0 else set()
    for b in grouped:
        if not is_requirement(b):
            continue
        sentences = _split_sentences(b.text) if b.kind == "para" else [b.text]
        for sent in sentences:
            norm = re.sub(r"\s+", " ", sent).strip(" .;")
            norm = norm.replace("**", "")
            if len(norm.split()) < 4 or norm.lower() in seen or AS_IS.match(norm) or BOILERPLATE.match(norm):
                continue
            seen.add(norm.lower())
            entities = extract_entities(norm)
            kind, weight = classify(norm, b.section)
            if b.section in intro_sections and not entities and kind != "scope" and not MODAL.search(norm):
                kind, weight = "scope", 1                   # introduction / scope / context statement - summarised later in detail
            reqs.append(Requirement(f"R{len(reqs) + 1}", norm, b.section, kind, weight, entities))
    return reqs


def document_entities(blocks: list[Block]) -> dict[str, list[str]]:
    """Every SAP entity named anywhere in the document (including reference tables and
    appendices that are not requirements) - the planner puts these first."""
    merged: dict[str, set[str]] = {}
    for b in blocks:
        for key, vals in extract_entities(b.text).items():
            merged.setdefault(key, set()).update(vals)
    return {k: sorted(v) for k, v in merged.items()}


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z])", text)
    out = []
    for p in parts:
        if MODAL.search(p) or len(p.split()) >= 10:
            out.append(p)
    return out or [text]


def summarize_document(blocks: list[Block]) -> str:
    """First meaningful paragraphs - used as the overall search text and in prompts."""
    paras = [b.text for b in blocks if b.kind == "para" and not in_skipped_section(b.section) and not re.match(r"^#", b.text)]
    return " ".join(paras[:4])[:1200]


_MODULES = {"SD", "MM", "FI", "CO", "PP", "PM", "QM", "PS", "HR", "HCM", "WM", "EWM", "LE", "TM", "BP", "MD", "MDG", "FSCM", "TR", "CA", "BC", "IM", "AA", "GL", "AP", "AR", "SCM", "CRM", "SRM", "PLM"}


def detect_module(blocks: list[Block], fallback: str = "") -> str:
    """Module from a 'Module | SD', 'SAP Module: SD' or 'Module - SD (Sales)' entry, else fallback."""
    for b in blocks:
        low = b.text.lower()
        if not re.match(r"^(sap\s+)?(functional\s+)?module\b", low):
            continue
        rest = re.split(r"[|:\-–]", b.text, maxsplit=1)
        if len(rest) >= 2:
            m = re.match(r"\s*([A-Za-z]{2,4})\b", rest[1])
            if m and m.group(1).upper() in _MODULES:
                return m.group(1).upper()
    return fallback

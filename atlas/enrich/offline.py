"""Rule-based enrichment that needs no AI and runs in milliseconds.

It combines what SAP itself says (short texts of the object and its methods /
function modules / fields), the developer's own header comments, and a scan of
the code for well-known technical patterns. The result is good enough to
search on immediately; the AI step later replaces the description with a
richer one and never loses this data because tags are merged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from atlas.ingest.types import get_type

# --- pattern tables -----------------------------------------------------------

KEYWORD_TAGS: list[tuple[str, str]] = [
    (r"\bcl_salv|\breuse_alv|\bcl_gui_alv", "ALV"),
    (r"\bbapi_\w+", "BAPI"),
    (r"\bcall function\b", "Function Module Call"),
    (r"\bselect\b", "Database Read"),
    (r"\b(insert|update|modify|delete)\s+\w+\s+(from|client)\b", "Database Write"),
    (r"/iwbep/|\bodata\b|_dpc\b|_mpc\b", "OData"),
    (r"\bidoc\b|\bedidc\b|\bedidd\b|master_idoc_distribute", "IDoc"),
    (r"\bsmartform|ssf_function_module_name", "Smartform"),
    (r"fp_job_open|fp_function_module_name", "Adobe Form"),
    (r"\bbadi\b|cl_exithandler|get_badi", "BAdI"),
    (r"cl_bcs\b|\bso_new_document|send_email", "Email"),
    (r"gui_upload|gui_download|\bopen dataset\b|cl_gui_frontend_services", "File Handling"),
    (r"job_open|job_submit|job_close", "Background Job"),
    (r"\bin update task\b|\benqueue_|\bdequeue_", "Update / Locking"),
    (r"\bauthority-check\b", "Authorisation Check"),
    (r"\bselection-screen\b|\bparameters\b|\bselect-options\b", "Selection Screen"),
    (r"\bcall screen\b|\bmodule\b .*\boutput\b", "Dynpro Screen"),
    (r"cl_http_client|cl_rest_|\bhttp_", "HTTP / REST"),
    (r"/ui2/cl_json|cl_sxml_string_writer|\bjson\b", "JSON"),
    (r"cl_xml_document|call transformation|\bixml\b", "XML"),
    (r"cl_sec_sxml|cl_abap_hmac|cl_abap_message_digest|\bencrypt|\bdecrypt", "Encryption"),
    (r"convert_to_local_currency|convert_to_foreign_currency|\bwaers\b", "Currency"),
    (r"\bswc_|\bswe_event|sap_wapi_", "Workflow"),
    (r"\bfor testing\b|cl_abap_unit", "Unit Test"),
    (r"\bamdp\b|if_amdp_marker", "AMDP"),
    (r"\bexec sql\b|adbc", "Native SQL"),
    (r"bal_log_create|bal_log_msg_add|bal_db_save", "Application Log"),
    (r"\bcommit work\b", "Commit"),
    (r"\bsubmit\b\s+\w+", "Submit Report"),
    (r"\bcall transaction\b", "Call Transaction"),
    (r"cl_proxy|if_proxy_|\bxi\b.*\bproxy\b|sprx", "Proxy / PI"),
    (r"define\s+(root\s+)?view\s+entity", "CDS View Entity"),
    (r"@objectmodel|@ui\.|@consumption", "CDS Annotations (UI/RAP)"),
    (r"define\s+table\s+function|define\s+abstract\s+entity", "CDS Table Function"),
]

# Map object-name prefixes and table usage to an SAP module.
MODULE_BY_NAME: list[tuple[str, str]] = [
    (r"^z?r?fi[_x]|_fi_|^zfi", "FI"),
    (r"^z?r?sd[_x]|_sd_|^zsd", "SD"),
    (r"^z?r?mm[_x]|_mm_|^zmm", "MM"),
    (r"^z?r?pp[_x]|_pp_|^zpp", "PP"),
    (r"^z?r?co[_x]|_co_|^zco", "CO"),
    (r"^z?r?hr[_x]|_hr_|^zhr|^zpa_|^zpy_", "HCM"),
    (r"^z?r?pm[_x]|_pm_|^zpm", "PM"),
    (r"^z?r?qm[_x]|_qm_|^zqm", "QM"),
    (r"^z?r?wm[_x]|_wm_|^zwm|^zewm", "WM/EWM"),
    (r"^z?r?ps[_x]|_ps_|^zps", "PS"),
    (r"^zaif|_aif_", "AIF"),
    (r"^zca[_x]|^zcl_zca|^zcx_zca|^zbc|_bc_", "BC"),
]

MODULE_BY_TABLE: dict[str, str] = {
    "FI": {"bkpf", "bseg", "bsik", "bsid", "bsak", "bsad", "acdoca", "lfa1", "lfb1", "kna1", "knb1", "lfbk", "t001", "skat", "ska1", "bsis", "bsas", "ukmbp_cms", "ukm_item"},
    "SD": {"vbak", "vbap", "vbkd", "vbpa", "vbfa", "likp", "lips", "vbrk", "vbrp", "vbuk", "vbup", "vbep", "kona", "konv", "prcd_elements", "tvko"},
    "MM": {"ekko", "ekpo", "eket", "ekbe", "mara", "marc", "mard", "makt", "mseg", "mkpf", "matdoc", "eban", "lfm1", "mbew", "mvke"},
    "PP": {"afko", "afpo", "afvc", "plko", "plpo", "mast", "stko", "stpo", "resb", "plaf"},
    "CO": {"coep", "cosp", "coss", "cobk", "csks", "cskt", "aufk", "covp", "prps", "proj"},
    "HCM": {"pa0001", "pa0002", "pa0008", "hrp1000", "hrp1001", "pernr"},
}

DECORATION = re.compile(r"^[\s\*&\-_=/\\|<>+#\.\"]*$")
ABAP_COMMENT = re.compile(r"^\s*(?:\*|\")\s?(.*)$")
CDS_COMMENT = re.compile(r"^\s*//\s?(.*)$")

GENERATED_HINTS = (
    "Data Provider Base Class",
    "Model Provider Base Class",
    "Extended Table Maintenance (Generated)",
    "Generated test implementation",
)


@dataclass
class EnrichmentResult:
    description: str
    tags: list[str]
    module: str
    complexity: str
    tables: list[str] = field(default_factory=list)


# --- helpers -----------------------------------------------------------------

def leading_comments(source: str, is_cds: bool, max_lines: int = 6, scan_lines: int = 40) -> list[str]:
    pattern = CDS_COMMENT if is_cds else ABAP_COMMENT
    out: list[str] = []
    for line in source.splitlines()[:scan_lines]:
        if is_cds and line.strip().startswith("@"):
            continue
        m = pattern.match(line)
        if not m:
            continue
        text = m.group(1).strip().lstrip("&*\"-_= ").strip()
        if not text or DECORATION.match(text):
            continue
        # skip SAP's default header noise
        if re.match(r"^(report|include|program)\s+\w+", text, re.I):
            continue
        out.append(text)
        if len(out) >= max_lines:
            break
    return out


def find_tables(source: str, limit: int = 8) -> list[str]:
    found: list[str] = []
    for m in re.finditer(
        r"\b(?:from|join|into table|update|insert(?:\s+into)?|modify|delete from)\s+([a-z_/][a-z0-9_/]{2,})",
        source,
        re.IGNORECASE,
    ):
        name = m.group(1).lower()
        if name in {"table", "select", "screen", "memory", "dataset", "transaction", "database", "corresponding"}:
            continue
        if name.startswith(("lt_", "gt_", "it_", "et_", "ls_", "gs_", "@", "mt_", "ct_", "rt_")):
            continue
        if name.startswith(("cl_", "cx_", "if_", "zcl_", "zcx_", "zif_", "ycl_", "yif_")):
            continue
        if name not in found:
            found.append(name)
        if len(found) >= limit:
            break
    return found


def detect_module(name: str, tables: list[str], short_text: str = "") -> str:
    lname = name.lower()
    for pattern, module in MODULE_BY_NAME:
        if re.search(pattern, lname):
            return module
    hits: dict[str, int] = {}
    for module, module_tables in MODULE_BY_TABLE.items():
        n = sum(1 for t in tables if t in module_tables)
        if n:
            hits[module] = n
    if hits:
        return max(hits, key=hits.get)
    if re.search(r"sales|customer|billing|delivery|quotation", short_text, re.I):
        return "SD"
    if re.search(r"vendor|supplier|payment|invoice|ledger|bank|gl\b", short_text, re.I):
        return "FI"
    if re.search(r"purchase|material|goods|stock", short_text, re.I):
        return "MM"
    return ""


def complexity_bucket(lines: int, component_count: int) -> str:
    if lines == 0:
        return "n/a"
    if lines < 150 and component_count < 10:
        return "low"
    if lines < 1500 and component_count < 60:
        return "medium"
    return "high"


def humanise(name: str) -> str:
    parts = name.lower().split("_")
    if parts and len(parts[0]) <= 4 and parts[0].startswith(("z", "y")):
        parts = parts[1:]
    return " ".join(p for p in parts if p)


def build_tags(name: str, type_key: str, source: str, short_text: str, attributes: dict) -> list[str]:
    tags: list[str] = [get_type(type_key).label]
    lname = name.lower()
    lsrc = source.lower()

    if re.match(r"^z?cx_|^ycx_", lname) or attributes.get("category") == "40":
        tags.append("Exception Class")
    if re.search(r"_dpc(_ext)?$", lname):
        tags.append("OData Data Provider")
    if re.search(r"_mpc(_ext)?$", lname):
        tags.append("OData Model Provider")
    if attributes.get("program_type") == "Include":
        tags.append("Include")
    if attributes.get("with_unit_tests"):
        tags.append("Unit Test")
    if attributes.get("tabclass") == "TRANSP":
        tags.append("Transparent Table")
    elif attributes.get("tabclass") == "INTTAB":
        tags.append("Structure")
    if any(h.lower() in short_text.lower() for h in GENERATED_HINTS):
        tags.append("Generated")
    if type_key == "FUGR" and "table maintenance" in short_text.lower():
        tags.append("Table Maintenance")
    if type_key in ("IWPR", "IWSV", "IWMO", "IWOM", "IWSG"):
        tags.append("OData")

    for pattern, tag in KEYWORD_TAGS:
        if re.search(pattern, lsrc):
            tags.append(tag)

    seen: list[str] = []
    for t in tags:
        if t not in seen:
            seen.append(t)
    return seen


# --- main entry ---------------------------------------------------------------

def describe(
    name: str,
    type_key: str,
    source: str,
    short_text: str = "",
    components: list[tuple[str, str, str]] | None = None,
    attributes: dict | None = None,
    source_lines: int = 0,
) -> EnrichmentResult:
    """Build description/tags/module/complexity for one object.

    components: list of (kind, name, short_text) from metadata.
    """
    attributes = attributes or {}
    components = components or []
    obj_type = get_type(type_key)
    is_cds = type_key in ("DDLS", "DCLS", "DDLX", "BDEF")

    tables = find_tables(source) if source else []
    module = detect_module(name, tables, short_text)
    tags = build_tags(name, type_key, source, short_text, attributes)
    if module:
        tags.insert(1, module)

    sentences: list[str] = []
    opening = f"{obj_type.label} {name}"
    if short_text and short_text.upper() != name.upper():
        opening += f": {short_text.rstrip('.')}"
    elif humanise(name):
        opening += f" (relates to {humanise(name)})"
    sentences.append(opening + ".")

    if attributes.get("program_type") and attributes["program_type"] != "Executable program":
        sentences.append(f"Program type: {attributes['program_type']}.")

    comments = leading_comments(source, is_cds) if source else []
    if comments:
        header = " ".join(comments)
        if len(header) > 300:
            header = header[:300].rsplit(" ", 1)[0] + "..."
        sentences.append(f"Developer comments: {header}")

    named = [(k, n, t) for (k, n, t) in components if t and t.upper() != n.upper()]
    if named:
        kinds = {k for k, _, _ in named}
        label = "methods" if "method" in kinds else "function modules" if "function" in kinds else "fields" if "field" in kinds else "components"
        sample = "; ".join(f"{n} - {t}" for _, n, t in named[:6])
        more = f" (+{len(named) - 6} more)" if len(named) > 6 else ""
        sentences.append(f"Contains {len(named)} documented {label}: {sample}{more}.")

    if tables:
        sentences.append(f"Accesses: {', '.join(t.upper() for t in tables)}.")

    if type_key == "DTEL" and attributes.get("datatype"):
        length = str(attributes.get("leng", "")).lstrip("0")
        dom = attributes.get("domname")
        sentences.append(
            f"Type {attributes['datatype']}{' ' + length if length else ''}" + (f", domain {dom}." if dom else ".")
        )
    if type_key == "TTYP" and attributes.get("rowtype"):
        sentences.append(f"Table type of {attributes['rowtype']}.")
    if type_key == "ENQU" and attributes.get("roottab"):
        sentences.append(f"Lock object on table {attributes['roottab']}.")
    if type_key == "TRAN" and attributes.get("pgmna"):
        sentences.append(f"Starts program {attributes['pgmna']}.")

    description = " ".join(sentences)
    return EnrichmentResult(
        description=description,
        tags=tags,
        module=module,
        complexity=complexity_bucket(source_lines, len(components)),
        tables=tables,
    )

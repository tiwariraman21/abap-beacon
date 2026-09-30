"""SAP object types as abapGit names them in file names.

    zcl_foo.clas.abap            -> name=ZCL_FOO  type=CLAS  ext=abap
    zcl_foo.clas.locals_imp.abap -> sub_file=locals_imp
    zsd_t_x.fugr.saplzsd_t_x.abap-> sub_file=saplzsd_t_x (an include)
    zmm_po_doc.ddls.asddls       -> type=DDLS (CDS view)
    zsd_curr.dtel.xml            -> metadata only (no source file at all)

Unknown type keys are still ingested (category "other"), so an inventory is
never silently incomplete.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote


@dataclass(frozen=True)
class ObjectType:
    key: str
    label: str
    category: str                      # code | ddic | config | other
    source_exts: tuple[str, ...] = ()  # file extensions that contain source


_TYPES: list[ObjectType] = [
    # Code
    ObjectType("PROG", "Program", "code", ("abap",)),
    ObjectType("CLAS", "Class", "code", ("abap",)),
    ObjectType("INTF", "Interface", "code", ("abap",)),
    ObjectType("FUGR", "Function Group", "code", ("abap",)),
    ObjectType("DDLS", "CDS View", "code", ("asddls",)),
    ObjectType("DCLS", "CDS Access Control", "code", ("asdcls",)),
    ObjectType("DDLX", "CDS Metadata Extension", "code", ("asddlxs",)),
    ObjectType("BDEF", "RAP Behavior Definition", "code", ("asbdef",)),
    ObjectType("SRVD", "Service Definition", "code", ("srvdsrv",)),
    ObjectType("ENHO", "Enhancement Implementation", "code", ("abap",)),
    ObjectType("ENHS", "Enhancement Spot", "code", ()),
    ObjectType("SXCI", "Classic BAdI Implementation", "code", ()),
    ObjectType("XSLT", "Transformation", "code", ("xml",)),
    ObjectType("TYPE", "Type Pool", "code", ("abap",)),
    ObjectType("AMSD", "ABAP Managed Service Definition", "code", ()),
    # Dictionary
    ObjectType("TABL", "Table / Structure", "ddic"),
    ObjectType("DTEL", "Data Element", "ddic"),
    ObjectType("DOMA", "Domain", "ddic"),
    ObjectType("TTYP", "Table Type", "ddic"),
    ObjectType("VIEW", "Database View", "ddic"),
    ObjectType("SHLP", "Search Help", "ddic"),
    ObjectType("ENQU", "Lock Object", "ddic"),
    ObjectType("INDX", "Secondary Index", "ddic"),
    # Configuration / framework
    ObjectType("SRVB", "Service Binding", "config"),
    ObjectType("MSAG", "Message Class", "config"),
    ObjectType("TRAN", "Transaction", "config"),
    ObjectType("DEVC", "Package", "config"),
    ObjectType("SUSO", "Authorization Object", "config"),
    ObjectType("AUTH", "Authorization Field", "config"),
    ObjectType("PARA", "SET/GET Parameter", "config"),
    ObjectType("TOBJ", "Table Maintenance Object", "config"),
    ObjectType("SICF", "ICF Service", "config"),
    ObjectType("IWPR", "Gateway Service Builder Project", "config"),
    ObjectType("IWSV", "Gateway Service", "config"),
    ObjectType("IWMO", "Gateway Model", "config"),
    ObjectType("IWOM", "Gateway Model Reference", "config"),
    ObjectType("IWSG", "Gateway Service Group", "config"),
    ObjectType("SMIM", "MIME Repository Object", "other"),
    ObjectType("W3MI", "Web MIME Object", "other"),
    ObjectType("WDYN", "Web Dynpro Component", "code"),
    ObjectType("WEBI", "Web Service", "config"),
    ObjectType("FDT0", "BRFplus Application", "config"),
    ObjectType("DOCV", "Documentation", "other"),
    ObjectType("SPRX", "Proxy Object", "code"),
    ObjectType("SUSH", "Authorization Default Values", "config"),
    ObjectType("NROB", "Number Range Object", "config"),
    ObjectType("SHI3", "Menu Structure", "config"),
    ObjectType("CHAR", "Characteristic", "config"),
    ObjectType("SFPF", "Adobe Form", "code"),
    ObjectType("SFPI", "Adobe Form Interface", "code"),
    ObjectType("SSFO", "Smart Form", "code"),
    ObjectType("SSST", "Smart Style", "config"),
    ObjectType("FORM", "SAPscript Form", "code"),
    ObjectType("IDOC", "IDoc Type", "config"),
    ObjectType("IEXT", "IDoc Extension", "config"),
    ObjectType("APLO", "Application Log Object", "config"),
    ObjectType("ACID", "Checkpoint Group", "config"),
    ObjectType("DSYS", "Chapter of a Book Structure", "other"),
]

TYPES: dict[str, ObjectType] = {t.key: t for t in _TYPES}

# Extensions abapGit uses for anything that is human-readable source.
ALL_SOURCE_EXTS = {"abap", "asddls", "asdcls", "asddlxs", "asbdef", "srvdsrv"}


def get_type(key: str) -> ObjectType:
    key = key.upper()
    return TYPES.get(key, ObjectType(key, key, "other"))


@dataclass
class ParsedFilename:
    name: str          # object name, upper case
    type_key: str      # CLAS, PROG...
    sub_file: str      # locals_imp, testclasses, include name... or ""
    ext: str           # abap, xml, asddls...
    kind: str          # source | metadata | other
    valid: bool = True
    notes: list[str] = field(default_factory=list)


def parse_filename(path: str) -> ParsedFilename:
    """Classify one file inside an abapGit export by its name."""
    base = path.replace("\\", "/").split("/")[-1]
    parts = base.split(".")

    if len(parts) < 3:
        return ParsedFilename(base.upper(), "", "", parts[-1].lower() if parts else "", "other", valid=False)

    # abapGit URL-encodes special characters (%23 for '#', %20 for spaces) and
    # pads versioned Gateway names with spaces; normalise to SAP's own form.
    name = re.sub(r"\s+", " ", unquote(parts[0])).strip().upper()
    type_key = parts[1].upper()
    ext = parts[-1].lower()
    sub_file = ".".join(parts[2:-1]).lower()
    obj_type = get_type(type_key)

    if ext == "xml":
        # XSLT transformations keep their source in <name>.xslt.source.xml
        kind = "source" if (type_key == "XSLT" and sub_file == "source") else "metadata"
    elif ext in obj_type.source_exts or ext in ALL_SOURCE_EXTS:
        kind = "source"
    else:
        kind = "other"  # .baseinfo, .json manifests, binaries

    return ParsedFilename(name, type_key, sub_file, ext, kind)

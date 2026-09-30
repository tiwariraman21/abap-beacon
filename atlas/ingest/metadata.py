"""Read the abapGit `.xml` metadata files.

These carry what SAP itself knows about an object: the short text of a class
and of every method, function module signatures, data element types, table
fields, message texts, package descriptions. It is free, reliable and
bilingual-safe, so it is used before any AI step.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class ComponentMeta:
    kind: str            # method | function | field | message | include | parameter
    name: str
    short_text: str = ""
    signature: dict = field(default_factory=dict)


@dataclass
class ObjectMeta:
    short_text: str = ""
    components: list[ComponentMeta] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)

    def merge(self, other: "ObjectMeta") -> None:
        if not self.short_text and other.short_text:
            self.short_text = other.short_text
        self.components.extend(other.components)
        self.attributes.update(other.attributes)


_FALLBACK_TEXT_TAGS = (
    "DESCRIPT", "DDTEXT", "CTEXT", "STEXT", "TTEXT", "AREAT",
    "SHORT_TEXT", "DESCRIPTION", "TEXT",
)

PROGRAM_TYPES = {
    "1": "Executable program",
    "I": "Include",
    "M": "Module pool",
    "F": "Function group",
    "S": "Subroutine pool",
    "J": "Interface pool",
    "K": "Class pool",
    "T": "Type pool",
    "X": "Transformation",
}


def _text(node: ET.Element | None, tag: str) -> str:
    if node is None:
        return ""
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _scalar_children(node: ET.Element | None, keep: tuple[str, ...]) -> dict:
    if node is None:
        return {}
    return {c.tag.lower(): (c.text or "").strip() for c in node if c.tag in keep and (c.text or "").strip()}


def parse_metadata_xml(text: str, type_key: str) -> ObjectMeta:
    """Parse one metadata file. Never raises on malformed XML; returns empty meta."""
    text = text.lstrip("\ufeff")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return ObjectMeta()

    values = root.find(".//{http://www.sap.com/abapxml}values")
    if values is None:
        values = root

    handler = _HANDLERS.get(type_key.upper(), _parse_generic)
    meta = handler(values)

    if not meta.short_text:
        meta.short_text = _first_fallback_text(values)
    meta.short_text = meta.short_text[:255]
    return meta


def _first_fallback_text(values: ET.Element) -> str:
    for tag in _FALLBACK_TEXT_TAGS:
        node = values.find(f".//{tag}")
        if node is not None and (node.text or "").strip():
            return node.text.strip()
    return ""


# ---- per-type handlers -----------------------------------------------------

def _parse_generic(values: ET.Element) -> ObjectMeta:
    return ObjectMeta()


def _parse_class_like(values: ET.Element, header_tag: str) -> ObjectMeta:
    header = values.find(header_tag)
    meta = ObjectMeta(short_text=_text(header, "DESCRIPT"))
    meta.attributes.update(
        _scalar_children(header, ("STATE", "EXPOSURE", "CLSFINAL", "CLSABSTRCT", "CATEGORY", "WITH_UNIT_TESTS", "REFCLSNAME"))
    )
    for comp in values.findall(".//DESCRIPTIONS/SEOCOMPOTX"):
        name = _text(comp, "CMPNAME")
        if name:
            meta.components.append(ComponentMeta("method", name.upper(), _text(comp, "DESCRIPT")))
    # Sub-component texts (method parameters) are useful search text too.
    for comp in values.findall(".//DESCRIPTIONS_SUB/SEOSUBCOTX"):
        name = _text(comp, "CMPNAME")
        sub = _text(comp, "SCONAME")
        if name and sub:
            meta.components.append(ComponentMeta("parameter", f"{name.upper()}.{sub.upper()}", _text(comp, "DESCRIPT")))
    return meta


def _parse_clas(values: ET.Element) -> ObjectMeta:
    return _parse_class_like(values, "VSEOCLASS")


def _parse_intf(values: ET.Element) -> ObjectMeta:
    return _parse_class_like(values, "VSEOINTERF")


def _parse_prog(values: ET.Element) -> ObjectMeta:
    meta = ObjectMeta()
    progdir = values.find("PROGDIR")
    subc = _text(progdir, "SUBC")
    if subc:
        meta.attributes["program_type"] = PROGRAM_TYPES.get(subc, subc)
    for item in values.findall(".//TPOOL/item"):
        if _text(item, "ID") == "R":
            meta.short_text = _text(item, "ENTRY")
            break
    return meta


def _params(function: ET.Element, group: str, row_tag: str) -> list[dict]:
    out = []
    for row in function.findall(f"{group}/{row_tag}"):
        param = _text(row, "PARAMETER") or _text(row, "EXCEPTION")
        if not param:
            continue
        out.append(
            {
                "name": param,
                "type": _text(row, "TYP") or _text(row, "DBFIELD") or _text(row, "DBSTRUCT"),
                "optional": bool(_text(row, "OPTIONAL")),
                "default": _text(row, "DEFAULT"),
            }
        )
    return out


def _parse_fugr(values: ET.Element) -> ObjectMeta:
    meta = ObjectMeta(short_text=_text(values, "AREAT"))
    includes = [n.text.strip() for n in values.findall(".//INCLUDES/SOBJ_NAME") if n.text]
    if includes:
        meta.attributes["includes"] = includes
        for inc in includes:
            meta.components.append(ComponentMeta("include", inc.upper()))
    for fn in values.findall(".//FUNCTIONS/item"):
        name = _text(fn, "FUNCNAME")
        if not name:
            continue
        signature = {
            "importing": _params(fn, "IMPORT", "RSIMP"),
            "exporting": _params(fn, "EXPORT", "RSEXP"),
            "changing": _params(fn, "CHANGING", "RSCHA"),
            "tables": _params(fn, "TABLES", "RSTBL"),
            "exceptions": [p["name"] for p in _params(fn, "EXCEPTION", "RSEXC")],
            "remote_enabled": bool(_text(fn, "REMOTE_CALL")),
        }
        meta.components.append(ComponentMeta("function", name.upper(), _text(fn, "SHORT_TEXT"), signature))
    return meta


def _parse_ddic(header_tag: str, attr_tags: tuple[str, ...]):
    def handler(values: ET.Element) -> ObjectMeta:
        header = values.find(header_tag)
        meta = ObjectMeta(short_text=_text(header, "DDTEXT"))
        meta.attributes.update(_scalar_children(header, attr_tags))
        return meta

    return handler


def _parse_tabl(values: ET.Element) -> ObjectMeta:
    header = values.find("DD02V")
    meta = ObjectMeta(short_text=_text(header, "DDTEXT"))
    meta.attributes.update(_scalar_children(header, ("TABCLASS", "CONTFLAG", "EXCLASS", "MAINFLAG", "CLIDEP")))
    for fld in values.findall(".//DD03P_TABLE/DD03P"):
        name = _text(fld, "FIELDNAME")
        if not name or name.startswith("."):
            continue
        meta.components.append(
            ComponentMeta(
                "field",
                name.upper(),
                _text(fld, "DDTEXT"),
                {
                    "data_element": _text(fld, "ROLLNAME"),
                    "key": bool(_text(fld, "KEYFLAG")),
                    "datatype": _text(fld, "DATATYPE"),
                    "length": _text(fld, "LENG").lstrip("0"),
                    "include": _text(fld, "PRECFIELD"),
                },
            )
        )
    return meta


def _parse_msag(values: ET.Element) -> ObjectMeta:
    meta = ObjectMeta(short_text=_text(values.find("T100A"), "STEXT"))
    for msg in values.findall(".//T100/T100"):
        number = _text(msg, "MSGNR")
        if number:
            meta.components.append(ComponentMeta("message", number, _text(msg, "TEXT")))
    return meta


def _parse_tran(values: ET.Element) -> ObjectMeta:
    meta = ObjectMeta(short_text=_text(values.find("TSTCT"), "TTEXT"))
    tstc = values.find("TSTC")
    meta.attributes.update(_scalar_children(tstc, ("PGMNA", "DYPNO", "CINFO")))
    return meta


def _parse_devc(values: ET.Element) -> ObjectMeta:
    devc = values.find("DEVC")
    meta = ObjectMeta(short_text=_text(devc, "CTEXT"))
    meta.attributes.update(_scalar_children(devc, ("PARENTCL", "COMPONENT", "DLVUNIT", "APPLICAT")))
    return meta


def _parse_suso(values: ET.Element) -> ObjectMeta:
    meta = ObjectMeta(short_text=_text(values.find("TOBJT"), "TTEXT"))
    tobj = values.find("TOBJ")
    if tobj is not None:
        fields = [(c.text or "").strip() for c in tobj if re.fullmatch(r"FIEL\d+", c.tag) and (c.text or "").strip()]
        if fields:
            meta.attributes["fields"] = fields
    return meta


def _parse_auth(values: ET.Element) -> ObjectMeta:
    authx = values.find("AUTHX")
    meta = ObjectMeta()
    meta.attributes.update(_scalar_children(authx, ("ROLLNAME", "DDTEXT")))
    if meta.attributes.get("rollname"):
        meta.short_text = f"Authorization field on data element {meta.attributes['rollname']}"
    return meta


_HANDLERS = {
    "CLAS": _parse_clas,
    "INTF": _parse_intf,
    "PROG": _parse_prog,
    "FUGR": _parse_fugr,
    "DDLS": _parse_ddic("DDLS", ("SOURCE_TYPE",)),
    "DTEL": _parse_ddic("DD04V", ("DOMNAME", "DATATYPE", "LENG", "DECIMALS", "REFKIND", "REFTYPE")),
    "DOMA": _parse_ddic("DD01V", ("DATATYPE", "LENG", "DECIMALS", "LOWERCASE", "CONVEXIT")),
    "TTYP": _parse_ddic("DD40V", ("ROWTYPE", "ROWKIND", "ACCESSMODE", "KEYDEF")),
    "VIEW": _parse_ddic("DD25V", ("VIEWCLASS", "ROOTTAB")),
    "SHLP": _parse_ddic("DD30V", ("SELMETHOD", "TEXTTAB")),
    "ENQU": _parse_ddic("DD25V", ("ROOTTAB",)),
    "TABL": _parse_tabl,
    "MSAG": _parse_msag,
    "TRAN": _parse_tran,
    "DEVC": _parse_devc,
    "SUSO": _parse_suso,
    "AUTH": _parse_auth,
}

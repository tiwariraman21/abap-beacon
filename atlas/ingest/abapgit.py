"""Read an abapGit export and group its files into SAP objects.

Accepts a ZIP file or an already-extracted folder. Returns `RawObject`s: one
per (type, name), each with all of its source and metadata files, plus the
package folder it came from. Nothing touches the database here.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from atlas.ingest.metadata import ComponentMeta, ObjectMeta, parse_metadata_xml
from atlas.ingest.types import ParsedFilename, get_type, parse_filename


@dataclass
class RawFile:
    path: str
    kind: str                 # source | metadata | other
    sub_file: str
    content: str

    @property
    def content_hash(self) -> str:
        return sha1(self.content)

    @property
    def line_count(self) -> int:
        return self.content.count("\n") + (1 if self.content and not self.content.endswith("\n") else 0)


@dataclass
class RawObject:
    type_key: str
    name: str
    package_path: str
    files: list[RawFile] = field(default_factory=list)
    meta: ObjectMeta = field(default_factory=ObjectMeta)

    @property
    def source_files(self) -> list[RawFile]:
        return [f for f in self.files if f.kind == "source"]

    @property
    def source_chars(self) -> int:
        return sum(len(f.content) for f in self.source_files)

    @property
    def source_lines(self) -> int:
        return sum(f.line_count for f in self.source_files)

    @property
    def content_hash(self) -> str:
        """Hash of every file, so any change in source or metadata is detected."""
        digest = hashlib.sha1()
        for f in sorted(self.files, key=lambda x: x.path):
            digest.update(f.path.encode())
            digest.update(f.content_hash.encode())
        return digest.hexdigest()


@dataclass
class ExportReport:
    source_label: str
    objects: list[RawObject]
    packages: dict[str, str]           # package path -> short text (from package.devc.xml)
    skipped_files: list[str]
    master_language: str = ""
    starting_folder: str = "/src/"

    @property
    def file_count(self) -> int:
        return sum(len(o.files) for o in self.objects)


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace").lstrip("\ufeff")


def _iter_zip(path: Path) -> Iterable[tuple[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            yield entry.filename.replace("\\", "/"), archive.read(entry.filename)


def _iter_folder(path: Path) -> Iterable[tuple[str, bytes]]:
    for file in sorted(path.rglob("*")):
        if file.is_file() and ".git" not in file.parts:
            yield file.relative_to(path).as_posix(), file.read_bytes()


def read_export(path: str | Path) -> ExportReport:
    """Read a ZIP or folder. Raises FileNotFoundError / ValueError with clear text."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Export not found: {path}\nIf the path has spaces, wrap it in double quotes."
        )

    if path.is_dir():
        entries = _iter_folder(path)
    else:
        try:
            with zipfile.ZipFile(path):
                pass
        except zipfile.BadZipFile:
            raise ValueError(f"Not a valid ZIP archive: {path}\nRe-export from abapGit and retry.")
        except OSError as error:
            raise OSError(
                f"Could not read {path}: {error}\n"
                "If the file is in OneDrive, make sure it is available offline."
            )
        entries = _iter_zip(path)

    objects: dict[tuple[str, str, str], RawObject] = {}
    packages: dict[str, str] = {}
    skipped: list[str] = []
    master_language = ""
    starting_folder = "/src/"

    for rel_path, raw in entries:
        base = rel_path.split("/")[-1]

        if base == ".abapgit.xml":
            text = _decode(raw)
            master_language = _find_tag(text, "MASTER_LANGUAGE")
            starting_folder = _find_tag(text, "STARTING_FOLDER") or starting_folder
            continue

        parsed: ParsedFilename = parse_filename(rel_path)
        folder = "/".join(rel_path.split("/")[:-1])
        package_path = folder or "."

        if parsed.type_key == "DEVC":
            text = _decode(raw)
            meta = parse_metadata_xml(text, "DEVC")
            packages[package_path] = meta.short_text
            # The package is also an object in its own right (inventory completeness).
            key = ("DEVC", _package_name_from_path(package_path, starting_folder), package_path)
            obj = objects.setdefault(key, RawObject("DEVC", key[1], package_path))
            obj.files.append(RawFile(rel_path, "metadata", "", text))
            obj.meta.merge(meta)
            continue

        if not parsed.valid or not parsed.type_key:
            skipped.append(rel_path)
            continue

        key = (parsed.type_key, parsed.name, package_path)
        obj = objects.setdefault(key, RawObject(parsed.type_key, parsed.name, package_path))

        if parsed.kind == "other":
            # keep a record of the file, but do not store binary-ish content
            obj.files.append(RawFile(rel_path, "other", parsed.sub_file, ""))
            continue

        text = _decode(raw)
        obj.files.append(RawFile(rel_path, parsed.kind, parsed.sub_file, text))

        if parsed.kind == "metadata":
            obj.meta.merge(parse_metadata_xml(text, parsed.type_key))

    # Sort files inside each object: main source first, then includes, then metadata.
    for obj in objects.values():
        obj.files.sort(key=lambda f: (f.kind != "source", not f.sub_file.startswith("sapl"), f.sub_file != "", f.path))
        if obj.type_key in ("CLAS", "INTF"):
            _refine_class_components(obj)

    ordered = sorted(objects.values(), key=lambda o: (get_type(o.type_key).category, o.type_key, o.name))
    return ExportReport(str(path), ordered, packages, skipped, master_language, starting_folder)


_METHOD_DECL = re.compile(r"^\s*(?:class-)?methods?\s+([a-z0-9_~/]+)", re.IGNORECASE | re.MULTILINE)
_EVENT_DECL = re.compile(r"^\s*(?:class-)?events?\s+([a-z0-9_]+)", re.IGNORECASE | re.MULTILINE)
_TYPE_DECL = re.compile(r"^\s*types?\s*:?\s*(?:begin of\s+)?([a-z0-9_]+)", re.IGNORECASE | re.MULTILINE)


def _refine_class_components(obj: RawObject) -> None:
    """abapGit lists every class component (methods, attributes, events, types)
    under one tag. Use the definition part of the source to tell them apart."""
    main = next((f for f in obj.source_files if not f.sub_file), None)
    if main is None:
        return
    text = main.content
    cut = re.search(r"^\s*(?:class\s+\w+\s+implementation|endinterface)", text, re.IGNORECASE | re.MULTILINE)
    definition = text[: cut.start()] if cut else text
    methods = {m.upper() for m in _METHOD_DECL.findall(definition)}
    events = {e.upper() for e in _EVENT_DECL.findall(definition)}
    types = {t.upper() for t in _TYPE_DECL.findall(definition)}
    # chained declarations "METHODS: a, b IMPORTING ..." - pick up the names after the colon
    for chain in re.finditer(r"^\s*(?:class-)?methods\s*:\s*(.*?)(?=^\s*(?:class-)?(?:methods|data|constants|types|events|interfaces|aliases|private|protected|public|endclass)\b)", definition, re.IGNORECASE | re.MULTILINE | re.DOTALL):
        for name in re.findall(r"(?:^|,)\s*([a-z0-9_~/]+)", chain.group(1), re.IGNORECASE):
            methods.add(name.upper())
    for comp in obj.meta.components:
        if comp.kind != "method":
            continue
        if comp.name in methods:
            comp.kind = "method"
        elif comp.name in events:
            comp.kind = "event"
        elif comp.name in types:
            comp.kind = "type"
        elif re.match(r"^(M[VSTOC]_|G[VSTO]_|C_|MC_|GC_|CO_|CS_)", comp.name):
            comp.kind = "attribute"
        elif methods:
            comp.kind = "attribute"
    # Methods without an SAP short text are absent from the XML; add them from source.
    known = {c.name for c in obj.meta.components}
    for name in sorted(methods - known):
        obj.meta.components.append(ComponentMeta("method", name))


def _package_name_from_path(package_path: str, starting_folder: str) -> str:
    """Folder name = sub-package name under abapGit PREFIX/FULL folder logic.
    The root package name is not stored in the export, so it is marked as such
    and can be renamed via `atlas ingest --package`."""
    root = starting_folder.strip("/")
    if package_path in (".", root, ""):
        return "$ROOT"
    return package_path.split("/")[-1].upper()


def _find_tag(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}>([^<]*)</{tag}>", text)
    return match.group(1).strip() if match else ""


def find_latest_zip(folder: str | Path) -> Path | None:
    folder = Path(folder)
    if not folder.is_dir():
        return None
    zips = list(folder.glob("*.zip"))
    return max(zips, key=lambda p: p.stat().st_mtime) if zips else None

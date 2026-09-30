"""Database schema.

One row per SAP object (not per file). Files, components (methods, function
modules, fields, messages) and later findings/references hang off the object.
Columns that later phases fill (module, s4_status, clean_core_tier,
complexity, review_status) exist already so the schema is stable.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class System(Base):
    """An SAP system (SID). Objects are always scoped to a system."""

    __tablename__ = "systems"

    id: Mapped[int] = mapped_column(primary_key=True)
    sid: Mapped[str] = mapped_column(String(16), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    packages: Mapped[list["Package"]] = relationship(back_populates="system", cascade="all, delete-orphan")
    objects: Mapped[list["SapObject"]] = relationship(back_populates="system", cascade="all, delete-orphan")


class Package(Base):
    """A development package. `path` is the folder inside the abapGit export."""

    __tablename__ = "packages"
    __table_args__ = (UniqueConstraint("system_id", "path", name="uq_package_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    system_id: Mapped[int] = mapped_column(ForeignKey("systems.id"))
    path: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(64))
    short_text: Mapped[str] = mapped_column(String(255), default="")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("packages.id"), nullable=True)

    system: Mapped[System] = relationship(back_populates="packages")
    objects: Mapped[list["SapObject"]] = relationship(back_populates="package")


class SapObject(Base):
    """One SAP repository object: a class, program, table, data element..."""

    __tablename__ = "objects"
    __table_args__ = (
        UniqueConstraint("system_id", "obj_type", "name", name="uq_object_identity"),
        Index("ix_objects_type", "obj_type"),
        Index("ix_objects_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    system_id: Mapped[int] = mapped_column(ForeignKey("systems.id"))
    package_id: Mapped[int | None] = mapped_column(ForeignKey("packages.id"), nullable=True)

    obj_type: Mapped[str] = mapped_column(String(8))          # abapGit key: CLAS, PROG, FUGR...
    name: Mapped[str] = mapped_column(String(64))             # always upper case
    short_text: Mapped[str] = mapped_column(String(255), default="")   # SAP short text from metadata

    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    module: Mapped[str] = mapped_column(String(32), default="")
    described_by: Mapped[str] = mapped_column(String(16), default="none")  # none | offline | ai | human
    review_status: Mapped[str] = mapped_column(String(16), default="n/a")  # n/a | draft | approved

    content_hash: Mapped[str] = mapped_column(String(40), default="")
    source_chars: Mapped[int] = mapped_column(Integer, default=0)
    source_lines: Mapped[int] = mapped_column(Integer, default=0)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    complexity: Mapped[str] = mapped_column(String(16), default="")

    s4_status: Mapped[str] = mapped_column(String(16), default="")
    clean_core_tier: Mapped[str] = mapped_column(String(8), default="")
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    system: Mapped[System] = relationship(back_populates="objects")
    package: Mapped[Package | None] = relationship(back_populates="objects")
    files: Mapped[list["ObjectFile"]] = relationship(
        back_populates="object", cascade="all, delete-orphan", order_by="ObjectFile.path"
    )
    components: Mapped[list["Component"]] = relationship(
        back_populates="object", cascade="all, delete-orphan", order_by="Component.name"
    )
    references: Mapped[list["ObjectReference"]] = relationship(back_populates="object", cascade="all, delete-orphan")
    findings: Mapped[list["Finding"]] = relationship(back_populates="object", cascade="all, delete-orphan")

    @property
    def source_files(self) -> list["ObjectFile"]:
        return [f for f in self.files if f.kind == "source"]

    @property
    def source(self) -> str:
        return "\n".join(f.content for f in self.source_files)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SapObject {self.obj_type} {self.name}>"


class ObjectFile(Base):
    """A file from the export. kind: source | metadata | other."""

    __tablename__ = "object_files"
    __table_args__ = (UniqueConstraint("object_id", "path", name="uq_file_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"))
    path: Mapped[str] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(16))
    sub_file: Mapped[str] = mapped_column(String(128), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(40))
    line_count: Mapped[int] = mapped_column(Integer, default=0)

    object: Mapped[SapObject] = relationship(back_populates="files")


class Component(Base):
    """A named part of an object: method, function module, field, message, include."""

    __tablename__ = "components"
    __table_args__ = (UniqueConstraint("object_id", "kind", "name", name="uq_component"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"))
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    short_text: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    signature: Mapped[dict] = mapped_column(JSON, default=dict)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    object: Mapped[SapObject] = relationship(back_populates="components")


class ObjectReference(Base):
    """A dependency edge found in source: this object reads/writes/calls `target`.
    Targets are stored by name; resolution to an object row happens at query
    time (the target may be SAP standard or live in a package not ingested)."""

    __tablename__ = "references"
    __table_args__ = (
        Index("ix_ref_target", "target_name"),
        Index("ix_ref_object", "object_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"))
    kind: Mapped[str] = mapped_column(String(24))          # reads | writes | calls_function | calls_class | ...
    target_name: Mapped[str] = mapped_column(String(128))
    target_type: Mapped[str] = mapped_column(String(24))
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    component: Mapped[str] = mapped_column(String(128), default="")
    line: Mapped[int] = mapped_column(Integer, default=0)
    count: Mapped[int] = mapped_column(Integer, default=1)

    object: Mapped[SapObject] = relationship(back_populates="references")


class Finding(Base):
    """A rule-engine result attached to an object (S/4, Clean Core, security, quality)."""

    __tablename__ = "findings"
    __table_args__ = (
        Index("ix_finding_object", "object_id"),
        Index("ix_finding_rule", "rule_id"),
        UniqueConstraint("object_id", "fingerprint", name="uq_finding_fingerprint"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"))
    rule_id: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(16))      # s4hana | cleancore | security | quality
    severity: Mapped[str] = mapped_column(String(8))       # high | medium | low | info
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text, default="")
    remediation: Mapped[str] = mapped_column(Text, default="")
    component: Mapped[str] = mapped_column(String(128), default="")
    line: Mapped[int] = mapped_column(Integer, default=0)
    snippet: Mapped[str] = mapped_column(String(300), default="")
    effort_hours: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="open")   # open | accepted | fixed | false_positive
    fingerprint: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    object: Mapped[SapObject] = relationship(back_populates="findings")


class AICall(Base):
    """Audit + cache of every AI request: what was sent (hash), by which provider, cost."""

    __tablename__ = "ai_calls"
    __table_args__ = (Index("ix_ai_hash", "input_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[str] = mapped_column(String(32))          # describe | ask | review
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_version: Mapped[str] = mapped_column(String(16), default="")
    input_hash: Mapped[str] = mapped_column(String(40))
    object_ids: Mapped[list] = mapped_column(JSON, default=list)
    input_chars: Mapped[int] = mapped_column(Integer, default=0)
    output_chars: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    redactions: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ok")     # ok | error | limit
    error: Mapped[str] = mapped_column(Text, default="")
    response: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FsdAnalysis(Base):
    """A functional specification analysed against the repository: coverage, reuse, plan."""

    __tablename__ = "fsd_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    filename: Mapped[str] = mapped_column(String(200))
    module: Mapped[str] = mapped_column(String(8), default="")
    coverage_pct: Mapped[float] = mapped_column(Float, default=0.0)
    verdict: Mapped[str] = mapped_column(String(8), default="build")     # reuse | extend | build
    requirement_count: Mapped[int] = mapped_column(Integer, default=0)
    effort_hours: Mapped[float] = mapped_column(Float, default=0.0)
    ai_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(40), default="")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    report_md: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ObjectUsage(Base):
    """Production usage of a custom object (ST03N / SCMON / SUSG export) - the fact that turns
    'custom code' into 'used code' and 'dead code'."""

    __tablename__ = "object_usage"
    __table_args__ = (Index("ix_usage_name", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))            # object or program name, upper case
    obj_type: Mapped[str] = mapped_column(String(8), default="")
    calls: Mapped[int] = mapped_column(Integer, default=0)   # executions in the period
    users: Mapped[int] = mapped_column(Integer, default=0)
    last_used: Mapped[str] = mapped_column(String(10), default="")   # YYYY-MM-DD
    period_days: Mapped[int] = mapped_column(Integer, default=0)
    period_from: Mapped[str] = mapped_column(String(10), default="")  # YYYY-MM-DD - start of the usage window this row covers
    period_to: Mapped[str] = mapped_column(String(10), default="")
    batch: Mapped[str] = mapped_column(String(64), default="")        # one import = one batch; imports accumulate
    source: Mapped[str] = mapped_column(String(64), default="")      # ST03N | SCMON | SUSG | manual
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    """A pipeline run. Steps record progress so a failed run can be resumed."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | done | failed
    source: Mapped[str] = mapped_column(String(512), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")

    steps: Mapped[list["JobStep"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobStep.id"
    )


class JobStep(Base):
    __tablename__ = "job_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | done | skipped | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    job: Mapped[Job] = relationship(back_populates="steps")


class Setting(Base):
    """Key/value settings edited from the CLI or (later) the Admin UI."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")

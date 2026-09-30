"""End-to-end and unit tests for ABAP Beacon (package atlas).

Run with:  pytest -q
Every test uses a temporary data directory, so the real database is untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from atlas.config import Settings
from atlas.db.models import Job, SapObject
from atlas.db.session import session_scope
from atlas.enrich.offline import describe, detect_module, find_tables
from atlas.ingest.abapgit import read_export
from atlas.ingest.metadata import parse_metadata_xml
from atlas.ingest.service import ingest_report
from atlas.ingest.types import get_type, parse_filename
from atlas.legacy.import_json import import_legacy
from atlas.pipeline.runner import PipelineOptions, run_pipeline, watch_folder
from atlas.search.engine import SearchEngine, SearchFilters, tokenise

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_ZIP = FIXTURES / "sample_abapgit.zip"
LEGACY_DIR = FIXTURES / "legacy"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    s = Settings(data_dir=tmp_path / "data", db_url=f"sqlite:///{(tmp_path / 'data' / 'atlas.db').as_posix()}")
    s.ensure_dirs()
    return s


@pytest.fixture()
def populated(settings: Settings) -> Settings:
    job = run_pipeline(PipelineOptions(source=str(SAMPLE_ZIP), system="DEV", root_package="ZAD", prefer_minilm=False), settings)
    assert job.status == "done", job.error
    return settings


# --- file name classification -----------------------------------------------------

@pytest.mark.parametrize(
    "path, name, type_key, sub, kind",
    [
        ("src/zcl_x.clas.abap", "ZCL_X", "CLAS", "", "source"),
        ("src/zcl_x.clas.locals_imp.abap", "ZCL_X", "CLAS", "locals_imp", "source"),
        ("src/zcl_x.clas.xml", "ZCL_X", "CLAS", "", "metadata"),
        ("src/zfg.fugr.saplzfg.abap", "ZFG", "FUGR", "saplzfg", "source"),
        ("src/zv.ddls.asddls", "ZV", "DDLS", "", "source"),
        ("src/zv.ddls.baseinfo", "ZV", "DDLS", "", "other"),
        ("src/zt.tabl.xml", "ZT", "TABL", "", "metadata"),
        ("src/zx.xslt.source.xml", "ZX", "XSLT", "source", "source"),
        ("src/zsd_mdl       0001.iwmo.xml", "ZSD_MDL 0001", "IWMO", "", "metadata"),
        ("src/%23ns%23obj.clas.abap", "#NS#OBJ", "CLAS", "", "source"),
    ],
)
def test_parse_filename(path, name, type_key, sub, kind):
    parsed = parse_filename(path)
    assert (parsed.name, parsed.type_key, parsed.sub_file, parsed.kind) == (name, type_key, sub, kind)


def test_unknown_type_is_still_typed():
    assert get_type("ZZZZ").label == "ZZZZ"
    assert get_type("clas").label == "Class"


# --- metadata --------------------------------------------------------------------

CLAS_XML = """<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_CLAS" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values>
   <VSEOCLASS><CLSNAME>ZCL_T</CLSNAME><DESCRIPT>Test class</DESCRIPT><STATE>1</STATE></VSEOCLASS>
   <DESCRIPTIONS>
    <SEOCOMPOTX><CMPNAME>DO_IT</CMPNAME><LANGU>E</LANGU><DESCRIPT>Does it</DESCRIPT></SEOCOMPOTX>
   </DESCRIPTIONS>
  </asx:values>
 </asx:abap>
</abapGit>"""


def test_parse_class_metadata():
    meta = parse_metadata_xml(CLAS_XML, "CLAS")
    assert meta.short_text == "Test class"
    assert meta.components[0].name == "DO_IT" and meta.components[0].short_text == "Does it"
    assert meta.attributes["state"] == "1"


def test_malformed_xml_does_not_raise():
    assert parse_metadata_xml("<not xml", "CLAS").short_text == ""


def test_generic_fallback_text():
    xml = '<abapGit><asx:abap xmlns:asx="http://www.sap.com/abapxml"><asx:values><FOO><DDTEXT>Some text</DDTEXT></FOO></asx:values></asx:abap></abapGit>'
    assert parse_metadata_xml(xml, "UNKN").short_text == "Some text"


# --- reader -----------------------------------------------------------------------

def test_read_sample_export_finds_metadata_only_objects():
    report = read_export(SAMPLE_ZIP)
    types = {o.type_key for o in report.objects}
    assert {"CLAS", "PROG", "FUGR", "DDLS", "DTEL", "TABL", "TTYP", "ENQU", "IWSV"} <= types
    assert len(report.objects) > 70  # the POC found 23
    assert report.master_language == "E"
    assert report.packages.get("src") == "AD"

    salesorder = next(o for o in report.objects if o.name == "ZCL_ZSD_SALESORDER")
    assert salesorder.meta.short_text == "Salesorder"
    kinds = {c.kind for c in salesorder.meta.components}
    assert {"method", "attribute"} <= kinds
    method_names = {c.name for c in salesorder.meta.components if c.kind == "method"}
    assert "CHECK_SF_REF_ALREADY_EXISTS" in method_names and "RELEASE_ORDER" in method_names

    fugr = next(o for o in report.objects if o.type_key == "FUGR")
    functions = [c for c in fugr.meta.components if c.kind == "function"]
    assert functions and functions[0].signature["importing"]

    table = next(o for o in report.objects if o.name == "ZSD_S_SO_HEADER")
    assert len([c for c in table.meta.components if c.kind == "field"]) > 50


def test_read_folder_export(tmp_path: Path):
    import zipfile

    zipfile.ZipFile(SAMPLE_ZIP).extractall(tmp_path / "x")
    report = read_export(tmp_path / "x")
    assert len(report.objects) > 70


def test_missing_export_raises():
    with pytest.raises(FileNotFoundError):
        read_export("/nowhere/nothing.zip")


# --- ingest + change detection ----------------------------------------------------

def test_ingest_is_idempotent(settings: Settings):
    report = read_export(SAMPLE_ZIP)
    with session_scope(settings) as session:
        first = ingest_report(session, report, "DEV", "ZAD")
    with session_scope(settings) as session:
        second = ingest_report(session, report, "DEV", "ZAD")
    assert first.added == len(report.objects) and first.unchanged == 0
    assert second.added == 0 and second.updated == 0 and second.unchanged == len(report.objects)
    assert second.changed_object_ids == []


def test_changed_source_is_detected(settings: Settings):
    report = read_export(SAMPLE_ZIP)
    with session_scope(settings) as session:
        ingest_report(session, report, "DEV")
    target = next(o for o in report.objects if o.name == "ZRFI_VENDOR_AGEING")
    target.source_files[0].content += "\n* changed"
    with session_scope(settings) as session:
        summary = ingest_report(session, report, "DEV")
    assert summary.updated == 1 and len(summary.changed_object_ids) == 1


# --- offline enrichment --------------------------------------------------------------

def test_find_tables_and_module():
    src = "SELECT * FROM bsik INTO TABLE lt_x. SELECT single * FROM lfa1 INTO ls_v. INSERT zmytab FROM ls_z."
    tables = find_tables(src)
    assert tables[:2] == ["bsik", "lfa1"] and "zmytab" in tables
    assert detect_module("ZRFI_VENDOR_AGEING", tables) == "FI"
    assert detect_module("ZXYZ", ["vbak", "vbap"]) == "SD"
    assert detect_module("ZXYZ", []) == ""


def test_describe_uses_short_text_and_components():
    result = describe(
        "ZCL_FOO", "CLAS", "CLASS zcl_foo DEFINITION.\n  METHODS run.\nENDCLASS.\nCLASS zcl_foo IMPLEMENTATION.\n METHOD run. SELECT * FROM vbak INTO TABLE @DATA(lt). ENDMETHOD.\nENDCLASS.",
        short_text="Sales helper", components=[("method", "RUN", "Runs the thing")], source_lines=6,
    )
    assert result.description.startswith("Class ZCL_FOO: Sales helper.")
    assert "RUN - Runs the thing" in result.description
    assert "VBAK" in result.description
    assert result.module == "SD" and "Database Read" in result.tags
    assert result.complexity == "low"


# --- pipeline, search, legacy -------------------------------------------------------

def test_pipeline_records_job_and_steps(populated: Settings):
    with session_scope(populated) as session:
        job = session.get(Job, 1)
        assert job.status == "done"
        assert [s.name for s in job.steps] == ["acquire", "ingest", "parse", "enrich_offline", "assess", "ai_enrich", "index_semantic"]
        assert all(s.status == "done" for s in job.steps if s.name != "ai_enrich")
        assert job.summary["assess"]["findings"] > 40 and job.summary["parse"]["references"] > 200
        assert job.summary["ingest"]["added"] > 70
        described = session.query(SapObject).filter(SapObject.described_by == "offline").count()
        assert described == job.summary["ingest"]["added"]


def test_second_run_skips_unchanged(populated: Settings):
    job = run_pipeline(PipelineOptions(source=str(SAMPLE_ZIP), system="DEV", prefer_minilm=False), populated)
    steps = {s.name: s for s in job.steps}
    assert steps["ingest"].detail["unchanged"] > 70
    assert steps["index_semantic"].status == "skipped"


def test_search_hybrid_finds_vendor_ageing(populated: Settings):
    with session_scope(populated) as session:
        engine = SearchEngine(session, populated.index_dir)
        assert engine.semantic is not None
        results = engine.search("report that ages vendor open items", limit=5)
        assert results and results[0].object.name.startswith("ZRFI_VENDOR_AGEING")
        assert "vendor" in results[0].matched_terms


def test_search_reaches_method_short_texts(populated: Settings):
    with session_scope(populated) as session:
        engine = SearchEngine(session, populated.index_dir)
        results = engine.search("check whether sales order already exists", limit=3, mode="keyword")
        assert results[0].object.name == "ZCL_ZSD_SALESORDER"
        assert any(h.name == "CHECK_SF_REF_ALREADY_EXISTS" for h in results[0].component_hits)


def test_search_filters_and_synonyms(populated: Settings):
    with session_scope(populated) as session:
        engine = SearchEngine(session, populated.index_dir)
        only_tables = engine.search("sales order header", limit=5, filters=SearchFilters(types=["TABL"]))
        assert only_tables and all(r.object.obj_type == "TABL" for r in only_tables)
        # "supplier" is not in any text; synonym expansion maps it to vendor/lifnr/bsik
        results = engine.search("supplier overdue", limit=3, mode="keyword")
        assert any("VENDOR_AGEING" in r.object.name for r in results)


def test_search_type_hint_and_compound(populated: Settings):
    """'salesorder interface' must rank sales-order integration objects above the flight-booking INTF."""
    with session_scope(populated) as session:
        engine = SearchEngine(session, populated.index_dir)
        names = [r.object.name for r in engine.search("salesorder interface", limit=5)]
        assert all("FLIGHT" not in n for n in names[:3]), names
        assert any("SALESORDER" in n for n in names[:2]), names
        names2 = [r.object.name for r in engine.search("sales order interface", limit=5)]
        assert names2[0] == "ZCL_ZSD_SALESORDER", names2
        # a pure type word still finds objects of that type
        assert [r.object.name for r in engine.search("interface", limit=2)][0].startswith("ZAIF")


def test_search_empty_query_tokens():
    assert tokenise("the a of") == []


def test_legacy_import_applies_ai_descriptions(populated: Settings):
    with session_scope(populated) as session:
        summary = import_legacy(session, LEGACY_DIR, "DEV")
        assert summary.ai_descriptions_found == 23 and summary.applied == 23 and not summary.unmatched
    with session_scope(populated) as session:
        obj = session.query(SapObject).filter(SapObject.name == "ZCL_AXIS_PAYEE_MGMT").one()
        assert obj.described_by == "ai" and "Axis Bank" in obj.description
        assert "Class" in obj.tags  # offline tags merged in


def test_watch_folder_once(settings: Settings, tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "drop.zip").write_bytes(SAMPLE_ZIP.read_bytes())
    watch_folder(inbox, "QAS", settings, interval=0, once=True)
    with session_scope(settings) as session:
        assert session.query(Job).count() == 1
        assert session.query(SapObject).count() > 70


# --- parser, rules, AI ------------------------------------------------------------------------

def test_parser_components_and_references():
    from atlas.parse.abap import parse_abap

    src = """REPORT ztest.
TABLES: bsik.
DATA: lt_x TYPE TABLE OF bkpf, lv_n TYPE i.
FORM main.
  SELECT * FROM bkpf INTO TABLE lt_x WHERE bukrs = '1000'.  "comment with SELECT FROM vbak
  LOOP AT lt_x INTO DATA(ls).
    SELECT SINGLE * FROM bseg INTO @DATA(ls_b) WHERE belnr = @ls-belnr.
  ENDLOOP.
  CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'.
  IF sy-subrc = 0. ELSE. ENDIF.
  AUTHORITY-CHECK OBJECT 'F_BKPF_BUK' ID 'BUKRS' FIELD '1000'.
  UPDATE zmytab SET flag = 'X' WHERE id = 1.
  MODIFY lt_x FROM ls.
  lo = NEW zcl_helper( ).
ENDFORM."""
    p = parse_abap(src)
    forms = [c for c in p.components if c.kind == "form"]
    assert forms and forms[0].name == "MAIN" and forms[0].line_start == 4 and forms[0].line_end == 15
    kinds = {(r.kind, r.target) for r in p.references}
    assert ("reads", "BKPF") in kinds and ("reads", "BSEG") in kinds and ("declares", "BSIK") in kinds
    assert ("writes", "ZMYTAB") in kinds and ("writes", "LT_X") not in kinds     # internal table excluded
    assert ("calls_function", "BAPI_TRANSACTION_COMMIT") in kinds
    assert ("authority_check", "F_BKPF_BUK") in kinds and ("calls_class", "ZCL_HELPER") in kinds
    assert ("reads", "VBAK") not in kinds                                        # comment ignored
    assert len([s for s in p.statements if s.text.upper().startswith(("IF", "ELSE", "ENDIF"))]) == 3
    assert p.max_nesting == 1


def test_rules_detect_expected_findings(populated: Settings):
    from atlas.assess.service import assess_objects, list_findings

    with session_scope(populated) as session:
        summary = assess_objects(session)
        assert summary.findings > 40
    with session_scope(populated) as session:
        rows = list_findings(session, status="all")
        by_rule = {(f["object"], f["rule_id"]) for f in rows}
        assert ("ZAPI_AES128_BENE_REG", "SEC-001") in by_rule      # hard-coded client secret
        assert ("ZCL_AXIS_PAYEE_MGMT", "SEC-002") in by_rule       # bank URL literal
        assert ("ZRFI_VENDOR_AGEING_NEW_SEL", "S4-001") in by_rule # BSIK
        assert ("ZCL_ZSD_SALESORDER", "S4-006") in by_rule         # SD_ORDER_CREDIT_RELEASE
        tiers = {o.name: o.clean_core_tier for o in session.scalars(select(SapObject))}
        assert tiers["ZRFI_VENDOR_AGEING_NEW_SEL"] == "3" and tiers["ZSD_S_SO_HEADER"] == "-"
        # status survives re-assessment
        fid = next(f["id"] for f in rows if f["rule_id"] == "SEC-002")
        from atlas.assess.service import set_finding_status
        set_finding_status(session, fid, "accepted")
    with session_scope(populated) as session:
        assess_objects(session)
    with session_scope(populated) as session:
        assert any(f["status"] == "accepted" for f in list_findings(session, status="all", rule_id="SEC-002"))


def test_dependencies_and_impact(populated: Settings):
    from atlas.parse.service import dependencies, impact, parse_objects

    with session_scope(populated) as session:
        parse_objects(session)
        oid = session.scalar(select(SapObject.id).where(SapObject.name == "ZCL_ZCA_APPLOG"))
        view = dependencies(session, oid)
        assert any(e["name"] == "ZCL_ZSD_SALESORDER" for e in view.incoming)
        assert any(e["name"].startswith("BAL_LOG") for e in view.outgoing)
        res = impact(session, "BSIK")
        names = [e["name"] for level in res["levels"] for e in level]
        assert names == ["ZRFI_VENDOR_AGEING_NEW_SEL", "ZRFI_VENDOR_AGEING"]


def test_redaction():
    from atlas.ai.redact import redact

    text = "iv_client_secret = 'TEST-CLIENT-SECRET'. lv_url = 'https://api.bank.co.in/v1/payee'. mail = 'ops@example.com'."
    r = redact(text)
    assert "TEST-CLIENT-SECRET" not in r.text and "api.bank.co.in" not in r.text and "ops@example.com" not in r.text
    assert "'<REDACTED>'" in r.text and "/v1/payee" in r.text and r.count == 3


def test_ai_enrich_and_ask_with_fake_claude(populated: Settings, monkeypatch: pytest.MonkeyPatch):
    import os

    from atlas.ai.ask import ask
    from atlas.ai.enrich import enrich_ai
    from atlas.ai.provider import ClaudeCodeProvider, get_provider

    fake_bin = Path(__file__).parent / "fake_bin"
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("ATLAS_AI_PROVIDER", raising=False)
    assert isinstance(get_provider(), ClaudeCodeProvider)
    provider = get_provider()

    with session_scope(populated) as session:
        summary = enrich_ai(session, provider, limit=4)
        assert summary.described == 4 and summary.calls >= 1 and summary.cost_usd > 0
    with session_scope(populated) as session:
        # second run: same content -> served from cache, no new calls
        summary2 = enrich_ai(session, provider, limit=4, force=True)
        assert summary2.cached >= 1 and summary2.calls == 0
        described = session.scalars(select(SapObject).where(SapObject.described_by == "ai")).all()
        assert len(described) >= 4 and all("AI description" in o.description for o in described)
        assert described[0].attributes.get("technical_summary")
    with session_scope(populated) as session:
        engine = SearchEngine(session, populated.index_dir)
        answer = ask(session, engine, provider, "how is the sales order reference checked")
        assert "[ZCL_ZSD_SALESORDER:370-375]" in answer.answer
        assert answer.sources[0].name == "ZCL_ZSD_SALESORDER" and answer.sources[0].excerpts[0] == (370, 375)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "limit")
    with session_scope(populated) as session:
        summary3 = enrich_ai(session, provider, force=True)
        assert "limit" in summary3.stopped_reason and summary3.calls == 0


# --- FSD ----------------------------------------------------------------------------------------

SAMPLES = Path(__file__).parent.parent / "samples" / "fsd"


def test_fsd_reader_docx_and_markdown():
    from atlas.fsd.reader import detect_module, extract_requirements, read_document

    title, blocks = read_document(SAMPLES / "FSD_02_Vendor_Ageing_Report_Enhancement.docx")
    assert "Vendor Ageing" in title and any(b.kind == "row" for b in blocks) and any(b.kind == "bullet" for b in blocks)
    reqs = extract_requirements(blocks)
    assert 12 <= len(reqs) <= 25
    assert detect_module(blocks) == "FI"
    kinds = {r.kind for r in reqs}
    assert {"selection", "output", "processing"} <= kinds
    assert any("BSIK" in r.entities.get("tables", []) for r in reqs)

    title, blocks = read_document(SAMPLES / "FSD_01_Sales_Order_Creation_from_Salesforce.md")
    reqs = extract_requirements(blocks)
    assert any("BAPI_SALESORDER_CREATEFROMDAT2" in r.entities.get("functions", []) for r in reqs)
    assert not any(r.text.startswith("Today") for r in reqs)     # as-is statements are not requirements


def test_fsd_reader_never_leaks_exceptions(tmp_path: Path):
    """A bad upload gives one readable message, never a stack trace."""
    from atlas.fsd.reader import FsdReadError, read_document

    bad_zip = tmp_path / "not_really.docx"
    bad_zip.write_bytes(b"this is not a zip file")
    empty = tmp_path / "empty.docx"
    empty.write_bytes(b"")
    old_word = tmp_path / "spec.doc"
    old_word.write_bytes(b"\xd0\xcf\x11\xe0 binary word")
    weird = tmp_path / "spec.xyz"
    weird.write_text("x")
    no_text = tmp_path / "blank.txt"
    no_text.write_text("   \n\n  ")
    for path, hint in ((bad_zip, "not a valid Word"), (empty, "empty"), (old_word, "save it as .docx"), (weird, "Unsupported"), (no_text, "no readable text")):
        with pytest.raises(FsdReadError) as info:
            read_document(path)
        assert hint in str(info.value)
    # odd encodings and unicode file names are fine
    latin = tmp_path / "Spécification (v2) – draft.txt"
    latin.write_bytes("# Vendor Ageing\n\n- The system shall display overdue items per vendor.\n".encode("cp1252"))
    title, blocks = read_document(latin)
    assert title == "Vendor Ageing" and any(b.kind == "bullet" for b in blocks)
    # PDF with selectable text
    from atlas.fsd.reader import extract_requirements
    title, blocks = read_document(Path(__file__).parent / "fixtures" / "fsd_mini.pdf")
    reqs = extract_requirements(blocks)
    assert title == "FSD - Vendor Ageing Report Enhancement" and len(reqs) == 2 and "BSIK" in reqs[0].entities["tables"]
    assert [b.text for b in blocks if b.kind == "heading"] == ["1. Business Requirement", "2. Processing Logic"]


def test_fsd_name_detection_and_display_masking():
    from atlas.fsd.reader import read_document
    from atlas.guard.detect import detect_sensitive_terms
    from atlas.guard.policy import Guard, GuardPolicy

    title, blocks = read_document(SAMPLES / "FSD_05_Business_Partner_Change_Replication.docx")
    found = detect_sensitive_terms(blocks, title, known=["ADNOC", "Axis Bank"])
    assert "Aramco" in found and "ASMO" in found
    assert not any(t in found for t in ("BAPI", "ODATA", "CDHDR", "SAP", "Business Partner", "Selection Screen"))
    for sample in ("FSD_01_Sales_Order_Creation_from_Salesforce.md", "FSD_02_Vendor_Ageing_Report_Enhancement.docx", "FSD_03_Purchase_Order_Approval_Workflow.md"):
        t, b = read_document(SAMPLES / sample)
        assert detect_sensitive_terms(b, t, known=["ADNOC", "Axis Bank", "Sakshamuat", "InfraBeat"]) == []
    g = Guard(GuardPolicy(), found)
    shown = g.mask_for_display(title)
    assert "Aramco" not in shown and "ASMO" not in shown and shown.startswith("Business Partner Change from <customer-")
    assert "BELLARMX" not in g.mask_for_display("Author | BELLARMX") and "BELLARMX" not in g.mask_for_display("Last Edited | BELLARMX")


def test_fsd_scenarios(populated: Settings, monkeypatch: pytest.MonkeyPatch):
    import os

    from atlas.fsd.service import analyse_file, list_analyses, refine_with_ai

    with session_scope(populated) as session:      # a described repository, as in real use
        import_legacy(session, Path(__file__).parent / "fixtures" / "legacy", "DEV")
    with session_scope(populated) as session:
        from atlas.pipeline.runner import rebuild_semantic_index
        rebuild_semantic_index(session, populated, prefer_minilm=False)
    with session_scope(populated) as session:
        engine = SearchEngine(session, populated.index_dir)
        reuse = analyse_file(session, engine, SAMPLES / "FSD_01_Sales_Order_Creation_from_Salesforce.md")
        assert reuse.verdict == "reuse" and reuse.coverage_pct >= 60
        assert reuse.result["reuse"][0]["name"] == "ZCL_ZSD_SALESORDER"
        dup = next(r for r in reuse.result["requirements"] if "already exists" in r["text"])
        assert dup["status"] == "covered" and "CHECK_SF_REF_ALREADY_EXISTS" in dup["best"]["components"]

        extend = analyse_file(session, engine, SAMPLES / "FSD_02_Vendor_Ageing_Report_Enhancement.docx")
        assert extend.verdict == "extend" and 30 <= extend.coverage_pct <= 65
        assert any("VENDOR_AGEING" in c["name"] for c in extend.result["reuse"])
        assert "ALV" in extend.result["plan"]["pattern"]

        build = analyse_file(session, engine, SAMPLES / "FSD_03_Purchase_Order_Approval_Workflow.md")
        assert build.verdict == "build" and build.coverage_pct < 20
        blocks = {b["name"] for st in build.result["plan"]["steps"] for b in st["blocks"]}
        assert "BAPI_PO_RELEASE" in blocks and "SAP_WAPI_START_WORKFLOW" in blocks and "CL_BCS" in blocks
        assert "Workflow" in build.result["plan"]["pattern"]
        assert any(o["name"] == "ZCL_ZCA_APPLOG" and o["action"] == "reuse" for o in build.result["plan"]["objects"])

        bank = analyse_file(session, engine, SAMPLES / "FSD_04_Bank_Beneficiary_Registration_API.md")
        assert bank.result["reuse"][0]["name"] == "ZCL_AXIS_PAYEE_MGMT"
        secure = next(r for r in bank.result["requirements"] if "client secret" in r["text"])
        assert secure["status"] == "partial" and "SEC-002" in secure["change"]      # findings cross-check
        assert "# FSD analysis" in bank.report_md and "BAPI" in bank.report_md
        # 5th scenario: a real customer FSD (BP change replication) - nothing in the repository does this
        bp = analyse_file(session, engine, SAMPLES / "FSD_05_Business_Partner_Change_Replication.docx")
        assert bp.title.startswith("Business Partner Change")                       # not "Document Control:"
        assert bp.verdict == "build" and bp.coverage_pct <= 5 and not bp.result["reuse"]
        assert 25 <= bp.result["stats"]["requirements"] <= 40                      # testing / rollout / training are not requirements
        assert not any("Train IT" in r["text"] or "Pilot with" in r["text"] for r in bp.result["requirements"])
        assert any(r["text"].startswith("Change detection can be based on:") and "Event-driven" in r["text"] for r in bp.result["requirements"])   # nested bullets merged
        assert any(r["text"].startswith("Users/systems must have appropriate authorizations") for r in bp.result["requirements"])   # "Authorization" section is not skipped
        assert bp.module == "BP" and "Change replication" in bp.result["plan"]["pattern"]
        steps = {st["title"]: [b["name"] for b in st["blocks"]] for st in bp.result["plan"]["steps"]}
        assert "Change trigger in the source system" in steps and "Reconciliation report" in steps and "Retry and alerting" in steps
        assert "BAPI_BUPA_CHANGE" in steps["Change the BP in the target"] and "BAPI_BUPA_CHANGE" in steps["Change the BP in the target"][:5]   # FSD-named BAPIs first
        assert any("BAPI_BUPA_ROLE_ADD_2" in n for n in steps["Change the BP in the target"])
        assert "CDHDR" in steps["Change trigger in the source system"]
        assert not any("BAPI_BUPA_CREATE_FROM_DATA" in n for names in steps.values() for n in names)     # change, not create
        names = [o["name"] for o in bp.result["plan"]["objects"]]
        assert "ZCL_BP_CHANGE_SYNC" in names and "ZSCM_ASMO_VEN_ST" in names and not any("CONTRO" in n for n in names)
        assert bp.result["plan"]["alternatives"] and any("DRF" in a for a in bp.result["plan"]["alternatives"])
        assert set(bp.result["detected_terms"]) >= {"Aramco", "ASMO"}
        assert bp.effort_hours < 300
        # readable rows: every requirement belongs to exactly one plan step, rows carry no block lists, scope rows cost nothing
        served = [rid for st in bp.result["plan"]["steps"] for rid in st["requirements"]]
        assert len(served) == len(set(served))
        rows = bp.result["requirements"]
        assert all(r["best"] is None for r in rows)                       # no unrelated "best match" on a pure build
        assert all("Building blocks" not in r["change"] for r in rows)
        assert sum(1 for r in rows if r["kind"] == "scope") >= 4 and all(r["effort_hours"] == 0 for r in rows if r["kind"] == "scope")
        assert sum(1 for r in rows if r["change"].startswith("New development - see plan step")) >= 25
        retry = next(r for r in rows if "Retry mechanism" in r["text"]); assert "Retry and alerting" in retry["change"]
        recon = next(r for r in rows if "reconciliation reports" in r["text"]); assert "Reconciliation report" in recon["change"]
        assert "AUTHOR<" not in bp.report_md and "AUTHORITY-CHECK" in bp.report_md
        # every object says which APIs it uses and which steps it implements; blocks appear once across the plan
        sync = next(o for o in bp.result["plan"]["objects"] if o["name"] == "ZCL_BP_CHANGE_SYNC")
        assert "BAPI_BUPA_CENTRAL_CHANGE" in sync["blocks"] and sync["steps"] == [4, 5]
        assert all(o["blocks"] for o in bp.result["plan"]["objects"] if o["action"] == "create")
        all_blocks = [b["name"] for st in bp.result["plan"]["steps"] for b in st["blocks"]]
        assert len(all_blocks) == len(set(all_blocks)) and not any("SO_NEW_DOCUMENT" in b or "REUSE_ALV" in b for b in all_blocks)
        assert all(st["addresses"] for st in bp.result["plan"]["steps"] if st["requirements"])
        # feasibility & complexity card
        fz = bp.result["feasibility"]
        assert fz["verdict"] == "Feasible with changes" and fz["complexity"]["band"] == "L" and fz["rice"].startswith("I")
        assert any("BAPI_BUPA_CHANGE" in c for c in fz["changes"]) and any("R14" in c for c in fz["changes"])
        assert any("DRF" in r for r in fz["risks"]) and fz["missing_nfr"] and 40 <= fz["quality"]["score"] <= 85
        assert 3 <= len(fz["questions"]) <= 12 and any("volumes" in q for q in fz["questions"]) and fz["confidence"]["band"] in ("high", "medium")
        assert bp.result["repo_snapshot"]["objects"] == 77 and bp.result["repo_snapshot"]["job_id"]
        # technical specification document
        from atlas.fsd.techspec import build_technical_spec
        from atlas.guard.policy import Guard, GuardPolicy
        g = Guard(GuardPolicy(), bp.result["detected_terms"])
        blob = build_technical_spec(dict(bp.result, filename=bp.filename), g.mask_for_display)
        import zipfile
        from io import BytesIO
        xml = zipfile.ZipFile(BytesIO(blob)).read("word/document.xml").decode("utf-8")
        assert "Technical Specification" in xml and "ZCL_BP_CHANGE_SYNC" in xml and "Requirement traceability" in xml
        assert "Aramco" not in xml and "ASMO" not in xml and "customer-" in xml
        assert "scope: 0" not in bp.report_md
    with session_scope(populated) as session:
        assert len(list_analyses(session)) == 5

    fake_bin = Path(__file__).parent / "fake_bin"
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("ATLAS_AI_PROVIDER", raising=False)
    from atlas.ai.provider import get_provider

    with session_scope(populated) as session:
        a = list_analyses(session)[0]                # the BP replication FSD - contains customer names
        assert a.result["detected_terms"]
        provider = get_provider()
        sent: list[str] = []

        class Recording:                         # what actually leaves the machine
            name = provider.name

            def complete(self, prompt, instruction=""):
                sent.append(prompt)
                return provider.complete(prompt, instruction)

        notes = refine_with_ai(session, a, Recording())
        assert notes and a.ai_reviewed and "AI review" in a.report_md
        # ask the architect about the analysis - same masking, logged, kept with the analysis
        from atlas.fsd.service import ask_analysis
        answer = ask_analysis(session, a, "Which step should I start with?", Recording())
        assert answer and a.result["qa"][-1]["q"].startswith("Which step") and "ASMO" not in sent[-1] and "PLAN STEPS" in sent[-1]
        session.flush()
        from atlas.db.models import AICall
        assert session.scalar(select(func.count(AICall.id)).where(AICall.purpose == "fsd_ask")) == 1
    # masked before egress, including the names detected in the document that are not on the list yet
    assert sent and "Aramco" not in sent[0] and "ASMO" not in sent[0] and "BELLARMX" not in sent[0] and "Business Partner" in sent[0]


# --- guardrails & providers --------------------------------------------------------------------------

def test_guard_masks_customer_system_numbers_users():
    from atlas.guard.policy import Guard, GuardPolicy

    g = Guard(GuardPolicy(terms=["ADNOC", "Axis Bank"]), extra_terms=["ER6"])
    text = "Orders for the ADNOC business on system ER6/100 by user JSMITH01; customer 0001000123; Axis Bank endpoint; transport ER6K900123; Reliance Industries Ltd."
    r = g.mask_for_ai(text)
    for secret in ("ADNOC", "ER6/100", "JSMITH01", "0001000123", "Axis Bank", "ER6K900123", "Reliance Industries"):
        assert secret not in r.text, (secret, r.text)
    assert "<customer-" in r.text and "<system-" in r.text and "<number-" in r.text and "<user-" in r.text
    assert r.kinds["customer"] >= 3
    # pseudonyms are stable and distinct
    assert g.mask_for_ai("ADNOC").text == g.mask_for_ai("adnoc").text != g.mask_for_ai("Axis Bank").text
    # display masking honours the switch
    assert "ADNOC" not in g.mask_for_display(text)
    assert "ADNOC" in Guard(GuardPolicy(terms=["ADNOC"], mask_in_ui=False)).mask_for_display(text)
    # business words and SAP table names survive
    assert "KNKK" in g.mask_for_ai("credit table KNKK with 180 days").text


def test_redact_combines_technical_and_guard(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    from atlas.ai.redact import redact
    from atlas.guard import policy as guard_policy

    guard_policy.invalidate()
    r = redact("client_secret = 'S3CRET'. Call https://sakshamuat.axisbank.co.in/v1 for ADNOC vendor 4500001234 (mail ops@x.com)")
    for secret in ("S3CRET", "sakshamuat.axisbank.co.in", "ADNOC", "4500001234", "ops@x.com"):
        assert secret not in r.text
    assert r.count >= 5


def test_openai_compatible_provider_with_fake_server(monkeypatch: pytest.MonkeyPatch):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from atlas.ai.provider import AILimitReached, OpenAICompatibleProvider

    class Handler(BaseHTTPRequestHandler):
        mode = "ok"

        def log_message(self, *a):  # silence
            pass

        def do_GET(self):
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(b'{"data": [{"id": "fake-model"}]}')

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            assert self.headers.get("Authorization") == "Bearer k123"
            if Handler.mode == "limit":
                self.send_response(429); self.end_headers(); self.wfile.write(b'{"error": "rate limit exceeded"}'); return
            reply = {"id": "x", "model": body["model"], "choices": [{"message": {"role": "assistant", "content": "OK " + body["messages"][-1]["content"][:10]}}], "usage": {"prompt_tokens": 12, "completion_tokens": 3}}
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps(reply).encode())

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}/v1"
        p = OpenAICompatibleProvider("custom", base_url=base, api_key="k123", model="fake-model")
        assert p.available() == (True, "ready")
        r = p.complete("hello there", "sys")
        assert r.text.startswith("OK hello") and r.input_tokens == 12 and r.model == "fake-model"
        Handler.mode = "limit"
        with pytest.raises(AILimitReached):
            p.complete("again")
        # presets carry sensible defaults and the local ones need no key
        groq = OpenAICompatibleProvider("groq", api_key="")
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        assert groq.available()[0] is False and "API key" in groq.available()[1]
        assert OpenAICompatibleProvider("ollama").preset.needs_key is False
    finally:
        server.shutdown()


def test_get_provider_from_config(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    from atlas.ai import provider as prov

    monkeypatch.setattr(prov, "config_path", lambda output_dir=None: settings.data_dir / "config" / "ai.json")
    monkeypatch.delenv("ATLAS_AI_PROVIDER", raising=False)
    prov.save_config({"provider": "groq", "api_key": "abc", "model": "llama-3.3-70b-versatile", "base_url": ""})
    p = prov.get_provider()
    assert p.name == "groq" and p.api_key == "abc" and p.base_url.startswith("https://api.groq.com")
    monkeypatch.setenv("ATLAS_AI_PROVIDER", "ollama")
    assert prov.get_provider().name == "ollama"


# --- database health --------------------------------------------------------------------------------

def test_database_health_repairs_stale_wal_and_corrupt_pages(populated: Settings, tmp_path: Path):
    import sqlite3

    from atlas.db.health import check, repair

    assert check(populated.db_path).ok and check(populated.db_path).objects == 77
    # 1 a stale write-ahead log from another version next to a good database
    work = tmp_path / "atlas.db"
    src, dst = sqlite3.connect(populated.db_path.as_posix()), sqlite3.connect(work.as_posix())
    src.backup(dst)                                  # a complete copy (the live file is in WAL mode)
    src.close(); dst.close()
    assert check(work).objects == 77
    (tmp_path / "atlas.db-wal").write_bytes(b"\x37\x7f\x06\x82" + b"\x00" * 4000)
    (tmp_path / "atlas.db-shm").write_bytes(b"\x00" * 32768)
    # 2 damaged pages inside the file: the root pages of two indexes (data rows stay readable)
    con = sqlite3.connect(work.as_posix())
    roots = [r[0] for r in con.execute("SELECT rootpage FROM sqlite_master WHERE type='index' AND rootpage > 1 ORDER BY rootpage").fetchall()[:3]]
    page_size = con.execute("PRAGMA page_size").fetchone()[0]
    con.close()
    raw = bytearray(work.read_bytes())
    for page in roots:
        off = (page - 1) * page_size
        raw[off + 8: off + page_size - 8] = bytes([0x5A]) * (page_size - 16)
    work.write_bytes(raw)
    before = check(work)
    assert not before.ok and "write-ahead log" in " ".join(before.problems)
    after = repair(work)
    assert after.ok and after.objects == 77, after.actions          # every object recovered into a fresh file
    assert any("stale" in a for a in after.actions) and any("recovered" in a for a in after.actions)
    assert list(tmp_path.glob("atlas.db-wal.stale-*")) and list(tmp_path.glob("atlas.db.corrupt-*"))
    con = sqlite3.connect(work.as_posix())
    assert con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    con.close()
    # 3 a file that is not a database at all -> usable empty database, damaged one kept
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not a database" * 100)
    h = repair(junk)
    assert h.ok and any("empty database" in a or "recovered" in a for a in h.actions) and list(tmp_path.glob("junk.db.*"))


def test_database_health_quarantines_foreign_wal_before_first_open(tmp_path: Path):
    """The exact upgrade failure: a shipped database (rollback mode) unzipped next to the previous
    installation's atlas.db-wal / -shm. The logs are moved aside before SQLite ever sees them."""
    import sqlite3

    from atlas.db.health import ensure_healthy

    db = tmp_path / "atlas.db"
    con = sqlite3.connect(db.as_posix()); con.execute("PRAGMA journal_mode=DELETE"); con.execute("create table objects(x)")
    con.executemany("insert into objects values (?)", [(i,) for i in range(77)]); con.commit(); con.close()
    # a WAL with real (foreign) content, as a running old installation leaves behind
    other = sqlite3.connect((tmp_path / "other.db").as_posix()); other.execute("PRAGMA journal_mode=WAL"); other.execute("create table t(x)")
    other.executemany("insert into t values (?)", [("y" * 300,) for _ in range(500)]); other.commit()
    (tmp_path / "atlas.db-wal").write_bytes((tmp_path / "other.db-wal").read_bytes())
    (tmp_path / "atlas.db-shm").write_bytes((tmp_path / "other.db-shm").read_bytes())
    other.close()
    h = ensure_healthy(db)
    assert h.ok and h.objects == 77 and any("stale" in a for a in h.actions)
    assert not (tmp_path / "atlas.db-wal").exists() and list(tmp_path.glob("atlas.db-wal.stale-*"))
    con = sqlite3.connect(db.as_posix()); assert con.execute("select count(*) from objects").fetchone()[0] == 77; con.close()


def test_feasibility_on_all_samples(populated: Settings):
    """Feasibility, complexity and quality are stable on the five samples."""
    from atlas.fsd.service import analyse_file

    expect = {"FSD_01": ("Feasible", "M", "I"), "FSD_02": ("Feasible", "M", "R"), "FSD_03": ("Feasible", "M", "W"), "FSD_04": ("Feasible", "M", "I"), "FSD_05": ("Feasible with changes", "L", "I")}
    with session_scope(populated) as session:
        engine = SearchEngine(session, populated.index_dir)
        for sample in sorted(SAMPLES.glob("FSD_*")):
            fz = analyse_file(session, engine, sample, store=False).result["feasibility"]
            verdict, band, rice = expect[sample.name[:6]]
            assert (fz["verdict"], fz["complexity"]["band"], fz["rice"][0]) == (verdict, band, rice), (sample.name, fz["verdict"], fz["complexity"], fz["rice"])
            assert 0 <= fz["quality"]["score"] <= 100 and fz["confidence"]["pct"] >= 45


# --- value engine -----------------------------------------------------------------------------------

def test_retirement_business_case_and_codegen(populated: Settings, tmp_path: Path):
    import zipfile
    from io import BytesIO

    from atlas.fsd.codegen import build_code_package
    from atlas.fsd.service import analyse_file
    from atlas.value.business_case import CaseParams, business_case_docx, conversion_case, portfolio_value
    from atlas.value.cleancore import successor
    from atlas.value.retirement import decide, has_usage_data, import_usage

    assert successor("KNA1")["successor"].startswith("I_Customer") and successor("REUSE_ALV_GRID_DISPLAY")["tier"] == "T3" and successor("ZCL_MINE") is None
    with session_scope(populated) as session:
        engine = SearchEngine(session, populated.index_dir)
        analyse_file(session, engine, SAMPLES / "FSD_01_Sales_Order_Creation_from_Salesforce.md")     # a reuse case -> portfolio savings
        bp = analyse_file(session, engine, SAMPLES / "FSD_05_Business_Partner_Change_Replication.docx")
        # without usage data nothing is retired, only reviewed
        d0 = decide(session)
        assert not has_usage_data(session) and d0["totals"]["retire"] == 0 and d0["totals"]["review"] > 0
        # ST03N-style export: class pools and function-group includes fold to their objects
        csv = tmp_path / "st03n.tsv"
        csv.write_text("Program\tCalls\tUsers\tLast used\nZRFI_VENDOR_AGEING\t1200\t14\t2026-08-30\nZCL_ZSD_SALESORDER=======CP\t54000\t3\t2026-09-01\nZCL_AXIS_PAYEE_MGMT=======CP\t320\t2\t2026-05-11\nSAPLZSD_T_API_MAP001\t12\t1\t2026-01-05\nZNOT_IN_REPO\t5\t1\t2026-01-01\n", encoding="utf-8")
        res = import_usage(session, csv, "ST03N", 365)
        assert res.rows == 5 and res.matched == 4 and res.unknown == 1
        d1 = decide(session, hourly_rate=100)
        by = {r["name"]: r for r in d1["rows"]}
        assert by["ZCL_ZSD_SALESORDER"]["decision"] == "keep" and by["ZRFI_VENDOR_AGEING"]["decision"] == "keep"
        assert d1["totals"]["retire"] >= 5 and d1["saving"] == round(d1["hours"]["retire"] * 100)
        assert all(r["reasons"] for r in d1["rows"])
        # business case
        params = CaseParams(hourly_rate=100, team_size=3, currency="EUR")
        case = conversion_case(session, params)
        pf = portfolio_value(session, params)
        assert case["objects_total"] == 77 and case["gross_h"] > 0 and case["total_h"] > case["net_h"] and case["retired_objects"] == d1["totals"]["retire"]
        assert [w["wave"] for w in case["waves"]] == [1, 2, 3] and case["swaps"] and any("VBAK" in sw["classic"] for sw in case["swaps"])
        assert pf["count"] >= 2 and pf["saved_h"] > 0 and any(r["verdict"] in ("reuse", "extend") and r["saved_h"] > 0 for r in pf["rows"])
        doc = business_case_docx(case, pf, customer="ACME")
        xml = zipfile.ZipFile(BytesIO(doc)).read("word/document.xml").decode("utf-8")
        assert "Business Case" in xml and "ACME" in xml and "Retirement" in xml and "EUR" in xml
        # code skeletons for the build case
        blob, names = build_code_package(bp.result)
        z = zipfile.ZipFile(BytesIO(blob))
        assert "src/zcl_bp_change_sync.clas.abap" in names and "src/zcl_bp_change_sync.clas.testclasses.abap" in names and "src/zbp_t_change_stat.tabl.ddl.txt" in names and ".abapgit.xml" in names
        cls = z.read("src/zcl_bp_change_sync.clas.abap").decode("utf-8")
        assert "CLASS zcl_bp_change_sync DEFINITION" in cls and "METHOD read_changed_bp_source" in cls and "BAPI_BUPA_CENTRAL_CHANGE" in cls and "R28" in cls
        tests = z.read("src/zcl_bp_change_sync.clas.testclasses.abap").decode("utf-8")
        assert "FOR TESTING" in tests and "cl_abap_unit_assert" in tests
        assert "status" in z.read("src/zbp_t_change_stat.tabl.ddl.txt").decode("utf-8")


def test_database_health_skips_logs_held_by_a_running_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import shutil as _shutil
    import sqlite3

    from atlas.db import health
    from atlas.db.health import ensure_healthy, quarantine_stale_logs

    db = tmp_path / "atlas.db"
    con = sqlite3.connect(db.as_posix()); con.execute("PRAGMA journal_mode=DELETE"); con.execute("create table objects(x)"); con.commit(); con.close()
    (tmp_path / "atlas.db-wal").write_bytes(b"\x37\x7f\x06\x82" + b"\x00" * 100)

    def locked(src, dst):          # what Windows raises while another process holds the file
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(health.shutil, "move", locked)
    actions = quarantine_stale_logs(db)
    assert actions and "in use by a running ABAP Beacon" in actions[0] and (tmp_path / "atlas.db-wal").exists()
    h = ensure_healthy(db)
    assert h.ok
    monkeypatch.setattr(health.shutil, "move", _shutil.move)


# --- workspaces, strict mode, rule variants, usage windows, protection sheet, compare ---------------------

def test_workspaces_strict_mode_rule_variants_and_usage_window(populated: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import zipfile
    from io import BytesIO

    from atlas.ai.provider import DisabledProvider, get_provider
    from atlas.assess.rules import RULES, rules_for
    from atlas.fsd.service import analyse_file
    from atlas.value.protection import compare_candidates, protection_facts, protection_sheet_docx
    from atlas.value.retirement import decide, import_usage, usage_window
    from atlas.workspace import create_workspace, list_workspaces, load_info, save_info, settings_for

    # rule variants like ATC check variants
    assert len(rules_for("2023")) < len(RULES) or len(rules_for("1809")) < len(rules_for("2023"))
    assert {r.id for r in rules_for("cloud")} >= {"CC-002", "CC-003"} and "CC-002" not in {r.id for r in rules_for("2023")}
    # workspaces are isolated data folders
    monkeypatch.setenv("ATLAS_WORKSPACE_ROOT", str(tmp_path / "root"))
    info = create_workspace("ACME Retail", "customer", ai_mode="strict", target_release="2021")
    assert info.slug == "acme-retail" and info.strict and (tmp_path / "root" / "workspaces" / "acme-retail" / "workspace.json").exists()
    assert [w.slug for w in list_workspaces()] == ["default", "acme-retail"]
    s2 = settings_for("acme-retail")
    assert s2.data_dir != populated.data_dir and s2.db_path.parent == tmp_path / "root" / "workspaces" / "acme-retail"
    # strict mode: no provider is constructed
    monkeypatch.setenv("ATLAS_WORKSPACE", "acme-retail")
    assert isinstance(get_provider(), DisabledProvider)
    with pytest.raises(Exception):
        get_provider().complete("x")
    info.ai_mode = "normal"; save_info(info)
    assert not isinstance(get_provider(), DisabledProvider)
    monkeypatch.delenv("ATLAS_WORKSPACE")
    # usage accumulation: 3 months -> nothing retired; 12 months -> retirements
    with session_scope(populated) as session:
        csv = tmp_path / "q4.tsv"
        csv.write_text("Program\tCalls\tUsers\tLast used\nZRFI_VENDOR_AGEING\t1200\t14\t2025-12-30\nZCL_ZSD_SALESORDER=======CP\t54000\t3\t2025-12-01\nZSD_DATE_FUNC\t2\t1\t2025-12-31\n", encoding="utf-8")
        import_usage(session, csv, "ST03N", period_from="2025-10-01", period_to="2025-12-31")
        d3 = decide(session)
        assert usage_window(session)["months"] == 3.0 and d3["totals"]["retire"] == 0
        import_usage(session, csv, "ST03N", period_from="2026-01-01", period_to="2026-09-30")
        w = usage_window(session)
        assert w["imports"] == 2 and w["enough"] and w["months"] >= 11.5
        d12 = decide(session)
        by = {r["name"]: r for r in d12["rows"]}
        assert d12["totals"]["retire"] > 0 and by["ZCL_ZSD_SALESORDER"]["decision"] == "keep"
        assert by["ZSD_DATE_FUNC"]["decision"] == "review" and "seasonal" in by["ZSD_DATE_FUNC"]["reasons"][0]   # 4 calls in a year: never retire blindly
        # re-importing the same window replaces, does not double
        import_usage(session, csv, "ST03N", period_from="2026-01-01", period_to="2026-09-30")
        assert usage_window(session)["imports"] == 2 and {r["name"]: r for r in decide(session)["rows"]}["ZCL_ZSD_SALESORDER"]["calls"] == 108000
        # protection sheet from live facts
        facts = protection_facts(session, populated, load_info("default"))
        assert facts["calls"] >= 0 and facts["rules"]["SAP user names"] is True
        xml = zipfile.ZipFile(BytesIO(protection_sheet_docx(facts))).read("word/document.xml").decode("utf-8")
        assert "Data Protection Sheet" in xml and "127.0.0.1" in xml and "Egress ledger" in xml
        # compare candidates on a reuse case
        engine = SearchEngine(session, populated.index_dir)
        a = analyse_file(session, engine, SAMPLES / "FSD_01_Sales_Order_Creation_from_Salesforce.md", store=False)
        rows = compare_candidates(session, a.result)
        assert rows and rows[0]["rank"] == 1 and rows[0]["name"] == "ZCL_ZSD_SALESORDER" and all("score" in r and "covered" in r for r in rows)

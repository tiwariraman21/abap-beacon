"""Browser-less UI tests using NiceGUI's simulated user."""

from __future__ import annotations

from pathlib import Path

import pytest
from nicegui.testing import User

from atlas.pipeline.runner import PipelineOptions, run_pipeline
from atlas.ui import data

pytest_plugins = ["nicegui.testing.user_plugin"]

SAMPLE_ZIP = Path(__file__).parent / "fixtures" / "sample_abapgit.zip"


@pytest.fixture(autouse=True)
def ui_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from atlas.config import Settings

    s = Settings(data_dir=tmp_path / "data", db_url=f"sqlite:///{(tmp_path / 'data' / 'atlas.db').as_posix()}")
    s.ensure_dirs()
    monkeypatch.setattr(data, "settings", s)
    data.invalidate()
    run_pipeline(PipelineOptions(source=str(SAMPLE_ZIP), system="DEV", root_package="ZAD", prefer_minilm=False), s)
    import atlas.ui.app  # noqa: F401  registers the pages
    return s


async def test_overview_shows_kpis(user: User) -> None:
    await user.open("/")
    await user.should_see("Overview")
    await user.should_see("Objects by type")
    await user.should_see("77")


async def test_discover_returns_results(user: User) -> None:
    await user.open("/discover?q=report%20that%20ages%20vendor%20open%20items")
    await user.should_see("ZRFI_VENDOR_AGEING")
    await user.should_see("strong")


async def test_object_page_tabs(user: User) -> None:
    from atlas.db.session import session_scope
    from atlas.db.models import SapObject
    from sqlalchemy import select

    with session_scope(data.settings) as s:
        oid = s.scalar(select(SapObject.id).where(SapObject.name == "ZCL_ZSD_SALESORDER"))
    await user.open(f"/object/{oid}")
    await user.should_see("ZCL_ZSD_SALESORDER")
    await user.should_see("Components (")
    await user.should_see("Salesorder")


async def test_inventory_and_jobs(user: User) -> None:
    await user.open("/inventory")
    await user.should_see("object(s)")
    await user.open("/jobs")
    await user.should_see("Recent runs")
    await user.should_see("Job #1")


async def test_assessments_page(user: User) -> None:
    await user.open("/assessments")
    await user.should_see("Open findings")
    await user.should_see("SEC-001")
    await user.should_see("ZAPI_AES128_BENE_REG")


async def test_dependencies_page_impact(user: User) -> None:
    await user.open("/dependencies?impact=BSIK")
    await user.should_see("Table usage")
    await user.should_see("ZRFI_VENDOR_AGEING_NEW_SEL")


async def test_object_page_dependencies_and_findings(user: User) -> None:
    from atlas.db.session import session_scope
    from atlas.db.models import SapObject
    from sqlalchemy import select

    with session_scope(data.settings) as s:
        oid = s.scalar(select(SapObject.id).where(SapObject.name == "ZCL_AXIS_PAYEE_MGMT"))
    await user.open(f"/object/{oid}")
    await user.should_see("Dependencies (")
    await user.should_see("Findings (")
    await user.open(f"/object/{oid}?line=94")
    await user.should_see("concatenated")


async def test_ask_page_with_fake_claude(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    fake_bin = Path(__file__).parent / "fake_bin"
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("ATLAS_AI_PROVIDER", raising=False)
    await user.open("/ask?q=how%20is%20the%20sales%20order%20reference%20checked")
    await user.should_see("Answer", retries=100)
    await user.should_see("ZCL_ZSD_SALESORDER")


async def test_fsd_page_analyses_sample(user: User) -> None:
    from atlas.ui import data as d

    sample = Path(__file__).parent.parent / "samples" / "fsd" / "FSD_01_Sales_Order_Creation_from_Salesforce.md"
    res = d.analyse_fsd(str(sample))
    await user.open(f"/fsd?id={res['id']}")
    await user.should_see("Existing objects to reuse")
    await user.should_see("ZCL_ZSD_SALESORDER")
    await user.should_see("Development plan")


async def test_fsd_page_masks_detected_names_and_offers_guardrails(user: User) -> None:
    from atlas.ui import data as d

    sample = Path(__file__).parent.parent / "samples" / "fsd" / "FSD_05_Business_Partner_Change_Replication.docx"
    res = d.analyse_fsd(str(sample))
    assert "Aramco" in res["detected_terms"]
    # list of previous analyses and the analysis page never show the names
    await user.open("/fsd")
    await user.should_see("Business Partner Change")
    await user.should_not_see("Aramco")
    await user.open(f"/fsd?id={res['id']}")
    await user.should_see("New development")
    await user.should_see("names found in this document and masked automatically")
    await user.should_see("Add to guardrails")
    await user.should_see("Change trigger in the source system")
    await user.should_see("ZCL_BP_CHANGE_SYNC")
    await user.should_not_see("Document Control:")
    await user.should_not_see("ZSCM_ASMO_VEN_ST")            # a custom table named in the FSD carries the client code
    await user.should_see("Objects to create, extend or reuse")
    await user.should_see("BAPI_BUPA_CENTRAL_GETDETAIL")      # the Uses column of ZCL_BP_CHANGE_SYNC
    await user.should_see("Feasibility and complexity")
    await user.should_see("Feasible with changes")
    await user.should_see("Clarification questions for the functional consultant")
    await user.should_see("Ask the architect (AI)")
    await user.should_see("Technical Spec (.docx)")
    content, name = d.fsd_techspec(res["id"])
    assert name.endswith("_Technical_Spec.docx") and len(content) > 20000
    await user.should_not_see("Building blocks:")
    # the report download content is masked too
    a = d.fsd_analysis(res["id"])
    assert "Aramco" not in a["title"] and "Aramco" not in a["report"] and "ASMO" not in a["report"]
    # one click adds them permanently
    user.find("Add to guardrails").click()
    await user.should_see("added to the guardrail list")
    assert {"Aramco", "ASMO"} <= set(d.guard_policy()["terms"])


async def test_fsd_page_renders_every_sample(user: User) -> None:
    from atlas.ui import data as d

    for sample in sorted((Path(__file__).parent.parent / "samples" / "fsd").glob("FSD_*")):
        res = d.analyse_fsd(str(sample))
        assert "error" not in res, res
        await user.open(f"/fsd?id={res['id']}")
        await user.should_see("Development plan")
        await user.should_see("FSD statements one by one")
        await user.should_see("Objects")
    await user.open("/fsd")
    await user.should_see("Previous analyses")


async def test_fsd_rerun_button_navigates_to_the_new_analysis(user: User) -> None:
    from atlas.ui import data as d

    res = d.analyse_fsd(str(Path(__file__).parent.parent / "samples" / "fsd" / "FSD_03_Purchase_Order_Approval_Workflow.md"))
    # make the analysis look stale so the Re-run button is rendered
    from atlas.db.models import FsdAnalysis
    from atlas.db.session import session_scope
    with session_scope(d.settings) as s:
        a = s.get(FsdAnalysis, res["id"])
        payload = dict(a.result); payload["repo_snapshot"] = dict(payload["repo_snapshot"], job_id=-1); a.result = payload
    d.invalidate()
    await user.open(f"/fsd?id={res['id']}")
    await user.should_see("Re-run")
    user.find(marker="rerun-btn").click()
    import asyncio
    for _ in range(40):                                        # the analysis runs in a worker thread
        await asyncio.sleep(0.25)
        d.invalidate()
        if len([r for r in d.fsd_analyses() if "Purchase Order" in r["title"]]) >= 2:
            break
    assert len([r for r in d.fsd_analyses() if "Purchase Order" in r["title"]]) >= 2
    await user.should_see("Development plan")               # navigated to the fresh analysis, no crash
    await user.should_not_see("Re-run")                     # the new analysis matches the current repository


async def test_fsd_page_bad_upload_shows_message_not_traceback(user: User, tmp_path: Path) -> None:
    from atlas.ui import data as d

    bad = tmp_path / "broken.docx"
    bad.write_bytes(b"definitely not a word document")
    res = d.analyse_fsd(str(bad))
    assert "error" in res and "not a valid Word document" in res["error"]
    empty = tmp_path / "empty.txt"
    empty.write_text("")
    assert "empty" in d.analyse_fsd(str(empty))["error"]
    # the page still opens normally afterwards
    await user.open("/fsd")
    await user.should_see("Analyse a specification")


async def test_overview_shows_ai_usage_and_code_freshness(user: User) -> None:
    from atlas.ui import data as d

    await user.open("/")
    await user.should_see("Where AI is used")
    await user.should_see("Code as of")
    await user.should_see("Deterministic by design")
    usage = d.ai_usage()
    assert [u["key"] for u in usage["uses"]] == ["describe", "ask", "fsd_review", "fsd_ask"] and len(usage["deterministic"]) >= 5
    fresh = d.freshness()
    assert fresh["objects"] == 77 and fresh["job_id"]


async def test_executive_view(user: User) -> None:
    from atlas.ui import data as d

    await user.open("/value?rate=80&team=5&cur=EUR")
    await user.should_see("Executive view")
    await user.should_see("S/4HANA remediation programme")
    await user.should_see("Custom code retirement")
    await user.should_see("Clean Core advisor")
    await user.should_see("Value delivered by the FSD analyses")
    v = d.value_view(80, 5, "EUR")
    assert v["case"]["total_h"] > 0 and v["retirement"]["rows"] and v["params"]["currency"] == "EUR"
    blob, name = d.business_case_file(80, 5, "EUR", "ACME")
    assert name.endswith(".docx") and len(blob) > 10000
    res = d.analyse_fsd(str(Path(__file__).parent.parent / "samples" / "fsd" / "FSD_03_Purchase_Order_Approval_Workflow.md"))
    blob, name, names = d.fsd_code_package(res["id"])
    assert name.endswith("_code_skeletons.zip") and any(n.endswith(".clas.abap") for n in names)


async def test_workspaces_page_and_strict_mode(user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from atlas.ui import data as d

    monkeypatch.setenv("ATLAS_WORKSPACE_ROOT", str(tmp_path / "wsroot"))
    monkeypatch.setattr(d, "_BASE_SETTINGS", d.settings)
    await user.open("/workspaces")
    await user.should_see("Active workspace")
    await user.should_see("Create a workspace")
    await user.open("/guardrails")
    await user.should_see("Data Protection Sheet (.docx)")
    blob, name = d.protection_sheet()
    assert name.startswith("Data_Protection_Sheet_") and len(blob) > 8000
    await user.open("/assessments")
    await user.should_see("Rule variant")
    # strict workspace hides every AI entry point
    info = d.create_workspace("Strict Corp", "customer", "Strict Corp", "strict", "2023", "onprem")
    assert info.strict and d.active_workspace().slug == "strict-corp" and not d.ai_enabled()
    await user.open("/ask")
    await user.should_see("AI is switched off for this workspace")
    await user.open("/ai")
    await user.should_see("strict mode")
    d.switch_workspace("default")
    assert d.ai_enabled()


async def test_settings_pages_and_display_masking(user: User) -> None:
    await user.open("/ai")
    await user.should_see("AI provider")
    await user.should_see("Ollama")
    await user.open("/guardrails")
    await user.should_see("Sensitive terms")
    await user.should_see("Egress log")
    # customer names from the sample data are masked in the UI by default
    from atlas.legacy.import_json import import_legacy
    from atlas.db.session import session_scope

    with session_scope(data.settings) as s:
        import_legacy(s, Path(__file__).parent / "fixtures" / "legacy", "DEV")
    data.invalidate()
    await user.open("/discover?q=register%20beneficiary%20bank")
    await user.should_see("ZCL_AXIS_PAYEE_MGMT")
    await user.should_not_see("Axis Bank")

# ABAP Beacon — handover and context document (v0.15.1, September 2026)

This document is written so that a new person — or a new AI assistant session — can pick up ABAP Beacon
without any previous conversation. It explains what the product is, what it does, how it is built, how to run
and test it, every decision that shaped it, and what is still open. Paste it, together with the project zip,
into a fresh session to continue the work.

---

## 1. What ABAP Beacon is

**ABAP Beacon — Custom Code Intelligence for SAP** is a local Python application built by Anjali Dodani
(InfraBeat, SAP consulting) for InfraBeat's AI Innovation Challenge. It turns an SAP customer's custom
ABAP code (Z/Y objects exported with abapGit) into a searchable, assessed, documented repository, and
answers the question every SAP project asks before building anything: **does something like this already
exist?**

It runs entirely on one Windows laptop: Python 3, SQLite, a NiceGUI web app on `http://localhost:8080`, a
Typer command line (`run.bat ...`). No SAP system connection, no Fiori/UI5 deployment, no cloud service and
no API key are required. AI features are optional and go through Claude Code (the user's Claude
subscription, headless `claude -p`), a local Ollama model, or a free OpenAI-compatible API — always behind
data-protection guardrails.

Earlier working names: "ABAP Atlas" (the Python package is still `atlas/`), "Zenith" (rejected). The product
name is **ABAP Beacon**; the project folder is `abap_atlas`.

## 2. What it does — feature by feature

| Area | What the user gets |
|---|---|
| **Ingestion pipeline** (`run.bat` / `atlas run <zip>`) | Reads an abapGit ZIP export; stores objects, files, packages; content-hash change detection so re-runs only touch changed objects; job log with steps. |
| **ABAP structural parser** | Methods with line ranges, function modules, forms, includes, SELECT/UPDATE/INSERT tables, CALL FUNCTION and method calls, AUTHORITY-CHECK, dictionary references — becomes the dependency graph. |
| **Enrichment** | Rule-based ("offline") descriptions for every object, plus optional AI descriptions (chunking, hash cache, cost ledger, review queue). Existing Claude descriptions from an earlier prototype can be imported (`import-legacy`). |
| **Discover (search)** | Business-language search over the repository: BM25 with compound splitting, SAP synonym dictionary, type-hint terms, name/short-text boosts, optional local embedding backend (model2vec by default; MiniLM if Python 3.12). Results explain *why* they matched. |
| **Ask the codebase** | Retrieval-augmented Q&A: answers grounded in retrieved source with line citations; works with any configured provider or in "manual" mode (prompt saved to a file). |
| **Assessments** | 30 rules in Python: S/4HANA readiness (obsolete statements, replaced tables, simplification items), Clean Core tiering (T1/T2/T3), security (hard-coded credentials/URLs, missing AUTHORITY-CHECK), quality (nested SELECTs, empty catches…), with effort estimate and finding lifecycle (open / accepted / fixed / false positive). |
| **Dependency map** | Table usage across the estate, impact analysis to N levels, interactive graph. |
| **Inventory** | Every object with type, module, package, lines, complexity, description source; CSV export. |
| **Object page** | Description, components, dependencies, findings, source with line numbers, attributes. |
| **FSD analysis** (the flagship for the challenge) | Upload a functional specification (.docx/.pdf/.md/.txt). Beacon extracts the requirement statements, matches each against existing objects with evidence, gives a verdict — **REUSE / EXTEND / NEW DEVELOPMENT** — with weighted coverage %, and produces a development plan: solution pattern, ordered steps with the exact BAPIs/FMs/classes/tables (each appearing once), which FSD statements each step addresses, objects to create with the APIs each uses, effort estimate, S/4HANA notes, test scenarios, design alternatives to raise. Downloadable Markdown report; optional AI review. |
| **Guardrails (data protection)** | Policy-driven masking of customer/partner names, SAP system IDs and clients, transport numbers, business keys (customer/vendor/document numbers), user names, organisations by suffix, credentials/hosts/e-mails/tokens. Applied twice: to everything sent to an AI provider and (switchable) to everything shown in the UI or written to reports. Stable pseudonyms (`<customer-737>`). Egress log of every AI call. **Auto-detection**: every uploaded FSD is scanned for new names; they are masked at once and offered for one-click addition to the list. |
| **AI provider settings** | Claude Code (subscription, no key), Ollama (local, free), Groq / OpenRouter / Google Gemini free tiers, Anthropic API, or manual. Test connection button. |
| **Jobs & Pipeline page** | Upload a ZIP and run the pipeline from the browser; job history; AI enrichment controls. |
| **Feasibility & complexity** (v0.13) | Per analysis: feasibility verdict with reasons, complexity band with drivers, FSD quality score, RICEFW class, estimate confidence, clarification questions for the functional consultant (`atlas/fsd/feasibility.py`, deterministic). |
| **Technical Spec .docx** (v0.13) | First version of the technical specification generated from the analysis (`atlas/fsd/techspec.py`, python-docx), masked; UI button and `fsd --docx`. |
| **Ask the architect (AI)** (v0.13) | Q&A on one analysis grounded in its facts; masked, logged (`ask_analysis` in `atlas/fsd/service.py`). |
| **Code freshness** (v0.13) | "Code as of" KPI, repository snapshot stored per analysis, stale warning + re-run button. |
| **Where AI is used** (v0.13) | Overview panel with live counts per LLM use and the deterministic parts. |
| **Executive view** (v0.14) | `/value`: S/4HANA remediation programme (waves, modules, cost, timeline), custom-code retirement with ST03N/SCMON usage import (`atlas/value/retirement.py`, table `object_usage`), Clean Core advisor (`atlas/value/cleancore.py`), reuse-savings portfolio, executive business case .docx (`atlas/value/business_case.py`). CLI `value`, `usage-import`. |
| **ABAP skeletons** (v0.14) | abapGit-layout code package from an analysis: classes with one method per step, ABAP Unit tests per FSD statement, exception, program, table DDL, messages (`atlas/fsd/codegen.py`). CLI `codegen <id>`. |
| **Workspaces** (v0.15) | Isolated data set per customer or internal library (`atlas/workspace.py`, `data/workspaces/<slug>/`), per-workspace AI mode (strict = no provider, AI UI hidden) and assessment target release (rule variant via `rules_for()`); header chip, Settings → Workspaces page, CLI `workspace`. Additive schema upgrade on start (`_add_missing_columns`). |
| **Data Protection Sheet** (v0.15) | One-page .docx from the live configuration (`atlas/value/protection.py`); Guardrails page button, CLI `protection-sheet`. |
| **Usage windows** (v0.15) | Usage imports accumulate per (source, from, to); window shown; < 12 months or ≤ 4 calls → review, never retire. |
| **Compare candidates** (v0.15) | Fact table ranking reuse candidates for one FSD (`compare_candidates`), shown when ≥ 2 candidates. |
| **Database self-healing** | Start-up health check (`PRAGMA quick_check`), quarantine of stale WAL/SHM files that belong to another database, automatic recovery of readable rows into a fresh file, `db-check` / `db-repair` commands. |

## 3. How to run

Windows, Python 3.10+ (3.12 recommended for the optional MiniLM model). Everything through `run.bat`, which
creates `.venv` on first use and installs the package (`pip install -e .`).

```
.\run.bat version          product version and data directory
.\run.bat db-check         database health (expect: 12 tables, 77 objects for the shipped sample)
.\run.bat ui               web app on http://localhost:8080 (Ctrl+C to stop)
.\run.bat                  ingest the newest ZIP in data\input and run the full pipeline
.\run.bat run <zip>        ingest a specific abapGit export
.\run.bat search "..."     search from the command line
.\run.bat show <object>    object details
.\run.bat assess           run the assessment rules
.\run.bat findings         list findings
.\run.bat deps <object>    dependencies;   .\run.bat impact <name>   impact analysis
.\run.bat fsd <file>       analyse a functional specification (add --ai for the AI review)
.\run.bat fsd-list         previous FSD analyses
.\run.bat guard-add "Name" add names to the guardrail list
.\run.bat ask "question"   ask the codebase
.\run.bat db-repair        repair a damaged database
```

Data lives in `data\`: `atlas.db` (SQLite), `index\` (search index), `input\` (uploaded ZIPs),
`output\` (reports, prompts), `config\guardrails.json` (masking policy), `config\ai.json` (provider).
Environment variable `ATLAS_DATA_DIR` moves the data directory.

The zip ships with a ready database: the sample repository (77 objects from `data\input\ZAD_*.zip`,
23 of them with AI descriptions) and the five sample FSD analyses, so the demo works immediately.

**Upgrading**: stop the UI, delete or rename the old folder, extract the new zip so a fresh folder is created.
Never extract on top of a running installation. (Since 0.12.6 leftover `atlas.db-wal`/`-shm` files from an
older install are quarantined automatically, but a clean folder is still the right way.)

## 4. Sample FSDs and expected outcomes (`samples\fsd\`)

| Sample | Verdict | Coverage | What it demonstrates |
|---|---|---|---|
| FSD_01 Sales Order Creation from Salesforce (.md) | REUSE | ~68 % | `ZCL_ZSD_SALESORDER` covers most requirements; the change list names the methods to extend |
| FSD_02 Vendor Ageing Report Enhancement (.docx) | EXTEND | ~42 % | `ZRFI_VENDOR_AGEING` exists; new buckets/fields are the delta |
| FSD_03 Purchase Order Approval Workflow (.md) | NEW DEVELOPMENT | 0 % | Workflow pattern plan (WS template, approval class, history report) |
| FSD_04 Bank Beneficiary Registration API (.md) | REUSE | ~79 % | `ZCL_AXIS_PAYEE_MGMT` covers it, but the "credentials stored securely" requirement is downgraded to *partial* because assessment finding SEC-002 (hard-coded URL) exists in that class |
| FSD_05 Business Partner Change Replication (.docx, real customer layout) | NEW DEVELOPMENT | 0 % | 35 statements (5 scope + 30 detailed), change-replication pattern (BAdI/CDHDR trigger → outbound class via proxy/OData → status table with retry → reconciliation), objects `ZCL_BP_CHANGE_SYNC`, `ZBP_T_CHANGE_STAT`, `ZBP_CHANGE_RECON`…, ~216 h; the customer, project and author names are detected and masked although none is on the guardrail list |

Expected reports are in `samples\fsd\expected_output\`; the test suite asserts these outcomes.

## 5. Architecture (folder `atlas/`)

```
atlas/
  cli.py            Typer command line; every command runs the database health check first
  config.py         Settings (data dir, DB URL, log level)
  db/               SQLAlchemy models (systems, packages, objects, object_files, components, references,
                    findings, jobs, job_steps, ai_calls, fsd_analyses, settings), session, health.py
  ingest/           abapGit ZIP reader, object/file mapping, content hashes
  parse/            ABAP structural parser -> components and reference edges
  enrich/           rule-based descriptions; service orchestrating offline + AI enrichment
  ai/               provider.py (Claude Code / OpenAI-compatible / Anthropic / manual), redact.py,
                    prompts.py, enrich.py, ask.py (RAG)
  search/           engine.py (BM25 + compound splitting + type hints + coverage), semantic.py
                    (model2vec / MiniLM), synonyms.py
  assess/           rules.py (30 rules), service.py (run, lifecycle, effort)
  fsd/              reader.py (docx/pdf/md/txt -> blocks -> requirement statements),
                    matcher.py (requirement-level matching with evidence), knowledge.py (SAP intents:
                    ~45 business/technical intents with BAPIs, tables, remarks), planner.py (pattern,
                    steps, objects, effort), service.py (analyse_file, report, AI review)
  guard/            policy.py (GuardPolicy, Guard: masking for AI egress and display),
                    detect.py (auto-detection of names in uploaded documents)
  reference/        SAP standard object dictionary (tables, BAPIs, tcodes) used by parser and FSD
  legacy/           import of the earlier prototype's JSON descriptions
  pipeline/         runner.py (ingest -> parse -> enrich -> index -> assess), job tracking
  ui/               app.py (all NiceGUI pages), data.py (data access + display masking), theme.py
tests/              test_atlas.py (core, 45 tests), test_ui.py (NiceGUI user simulation, 13 tests),
                    fixtures (sample abapGit zip, legacy descriptions, mini PDF, fake `claude` binary)
docs/               ROADMAP.md, DECISIONS.md (ADR-001 … ADR-016), ABAP_Atlas_Product_Plan.md, this file
samples/fsd/        five sample FSDs and expected reports
data/               shipped database, sample input ZIP, search index, config
```

Key design decisions (see `docs/DECISIONS.md` for the reasoning):

- SQLite behind SQLAlchemy now, PostgreSQL possible later (ADR-001).
- Python-only UI with NiceGUI, SAP Horizon look (ADR-002).
- Metadata first, AI second: everything works without AI; AI adds descriptions and reviews (ADR-004).
- Standard retrieval (BM25 + embeddings) instead of hand-tuned scoring (ADR-005, 007, 008).
- Rules in Python, not YAML, for now (ADR-009).
- Claude Code headless as the default AI provider — no API key, uses the subscription (ADR-003/010);
  one OpenAI-compatible client covers Ollama and the free-tier APIs (ADR-014).
- FSD analysis is deterministic first, AI second (ADR-011).
- Guardrails are policy-driven and applied twice — egress and display (ADR-013); the guard also detects
  names in the documents it protects (ADR-016).
- A requirement match needs specific evidence (referenced table/BAPI, matching method, name hit or a
  distinctive term), never generic word overlap; the planner uses the FSD's own BAPIs first, lists each
  building block once, attaches every FSD statement to exactly one step, and names objects from the
  business topic, never from the title (ADR-015).

## 6. How the FSD analysis works (the part most likely to be extended)

1. **Reader** — `.docx` (Word XML, custom heading styles, literal `## ` headings, numbering levels,
   tables, content controls), `.pdf` (pypdf), `.md/.txt` (any encoding) → blocks (heading / para / bullet
   / row). Non-requirement sections are skipped (document control, testing, rollout, fallback, training,
   landscape, approvals, key-object tables). Nested bullets are merged with their "…based on:" parent or
   prefixed with it. Every sentence/bullet/row that describes what the solution must do becomes a
   statement R1…Rn with a kind (processing, integration, validation, output, data_model, selection,
   authorization, error_handling, performance, scheduling, mapping, scope). Scope/objective/context
   statements (no shall/must/will, no SAP entity, before the detailed part) get kind *scope*, weight 1,
   effort 0. Title comes from the first real heading, module from a "Module | SD" row or from the intents.
2. **Matcher** — for each statement: BM25 + semantic candidates, entity references (tables/BAPIs/custom
   objects the object really uses), component (method/FM) hits, name hits, distinctive-term hits;
   confidence → covered ≥ 0.55 / partial ≥ 0.30 / missing; a match is only shown with a specific signal;
   assessment findings on the matched object can downgrade a covered requirement. Weighted coverage % →
   verdict: reuse ≥ 60 %, extend ≥ 25 %, else build. Reuse candidates = objects covering the most weight.
3. **Knowledge base** — ~45 intents (sales order create/change, delivery, billing, PO create/change/
   release, goods movement, invoice, FI posting, open items, payment, bank API, credit, BP create,
   **BP change/replication**, replication alternatives, change trigger, proxy/SOAP, retry, reconciliation,
   workflow, OData/RAP, ALV, batch, email, application log, custom tables, authorization, …), each with
   keywords, building blocks (name, kind, purpose), tables, remarks, effort and a topic for object naming.
4. **Planner** — chooses a solution pattern (Change replication, Workflow, API/OData, Report/ALV,
   Interface, …), builds ordered steps with blocks (FSD-named first, each block once across the plan,
   "legacy – avoid" entries excluded), assigns every statement to exactly one step, lists objects to
   create/extend/reuse with the APIs each uses and the steps it implements, effort breakdown by kind
   (+20 % design/tests, pattern surcharges), S/4HANA notes, test scenarios, design alternatives.
5. **Service/report** — stores the analysis (JSON payload + Markdown report), detected names, entities;
   the report and the UI put the plan first for a build verdict and the per-statement list first for
   reuse/extend. AI review (optional) receives only masked text.

## 7. Tests

`.\.venv\Scripts\python -m pytest -q` (or `pytest` after `pip install -e ".[dev]"`): 58 tests.
`tests/test_atlas.py` covers pipeline, parser, search, assessments, FSD reader/matcher/planner on all
five samples (including masking, step assignment, once-only blocks, object API lists), guardrails,
providers (with a fake `claude` binary), database health/repair. `tests/test_ui.py` drives every page with
NiceGUI's user simulation, including FSD upload errors, guardrail banner and one-click add.

## 8. Version history (short)

- 0.9.0 search 2.0, Ask, assessments · 0.10.0 FSD analysis · 0.11.0 guardrails, provider choice, product
  name ABAP Beacon · 0.12.0 FSD hardened on a real customer FSD, name auto-detection, PDF input, readable
  upload errors · 0.12.1 start-up database health check and repair · 0.12.2 KPI font, discreet guardrail
  banner · 0.12.3 plan/rows deduplicated, scope statements, step assignment, masking fixes · 0.12.4 plan
  first for builds, statements attached to steps, one block per plan · 0.12.5 objects list their APIs and
  steps, aligned grids, auto-detect toggle · 0.12.6 shipped DB in rollback mode + WAL/SHM quarantine ·
  0.15.1 feasibility & complexity card, Technical Spec .docx, Ask the architect, code freshness, Where-AI
  panel, `audit` command · 0.15.1 Executive view (retirement, business case, Clean Core advisor, reuse
  savings) and ABAP skeleton generation.

## 9. Known limits and next steps (from `docs/ROADMAP.md`)

- Optional MiniLM embedding model needs Python 3.12; on other versions model2vec/BM25 are used.
- AI enrichment quality depends on the provider; Claude Code must be installed and logged in for the
  default provider; otherwise choose Ollama or a free API on the AI provider page.
- Next roadmap items: generated documents (Technical Spec .docx, inventory .xlsx, assessment .pdf),
  clone detection, editable synonym dictionary, YAML rule packs, learning from FSD decisions, PostgreSQL.

## 10. Working with an AI assistant on this project

Give the assistant this document and the zip. Typical instructions that worked well: "run the five sample
FSDs and review the output as an ABAPer would", "every building block once", "each FSD statement in exactly
one step", "never show a customer name on screen", "a bad upload must give one readable message". The test
suite is the contract — every fix should come with an assertion in `tests/`.

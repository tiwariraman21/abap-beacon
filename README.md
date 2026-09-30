# ABAP Beacon - Custom Code Intelligence for SAP

_by InfraBeat. Product name **ABAP Beacon**; the Python package and CLI keep the working name `atlas`._

Custom-code intelligence for SAP. Ingest an abapGit export, understand every
object (including the metadata SAP itself provides), search it in plain
business English, and - in the coming phases - assess it for S/4HANA, Clean
Core, security and duplication, generate documentation, and prove the ROI.

**Status: v0.15.1 - foundation, parser + dependency graph, assessments, AI
enrichment, Ask-the-codebase, FSD analysis, data-protection guardrails and a
choice of AI providers (Claude, local open-source models, free-tier APIs).** Runs entirely on your
machine - no SAP system, Fiori launchpad or UI5 deployment, and no API key: AI
features use Claude Code (your Claude subscription) in headless mode. See
`docs/ROADMAP.md` for status and `docs/DECISIONS.md` for the choices made.

What it does today:

- **Ingest** an abapGit export (60+ object types, SAP short texts, method / FM /
  field metadata), with change detection and recorded pipeline jobs.
- **Search** in business language: BM25 + compound-aware ranking + optional
  local embeddings; results explain why they matched, down to the method.
- **Understand structure**: parsed methods with line ranges, every table
  read/written, FM/class calls, includes, authority checks; dependency view,
  impact analysis (`who breaks if BSIK changes?`), table usage with S/4 status.
- **Assess**: 30 deterministic rules - S/4HANA simplification items, Clean Core
  tiering, security (hard-coded credentials, URLs, missing AUTHORITY-CHECK),
  quality/performance - each finding points at a line, says why and how to fix,
  carries an effort estimate, and keeps its status across re-runs.
- **Describe with AI**: batched, redacted, cached descriptions + technical
  summaries + risks via Claude Code; stops cleanly at usage limits and resumes.
- **Ask the codebase**: retrieval-augmented answers with `[OBJECT:line]`
  citations that open the source at that line.
- **FSD analysis**: upload a functional specification (.docx/.pdf/.md/.txt); ABAP Beacon
  splits it into requirements (skipping testing, rollout, training and other
  non-requirement sections), tells you which existing objects already cover
  them (and how much, requirement by requirement - a match needs real evidence,
  not just shared words like "system" or "API"), what has to change in those
  objects, and - when nothing exists - plans the build starting from the BAPIs
  and tables the FSD itself names, adds what a senior architect would (change
  trigger, proxy/OData client, retry, reconciliation) and lists the design
  alternatives to raise before building. Customer, project and system names
  found in the document are masked immediately and can be added to the
  guardrails with one click.

## Quick start (Windows)

1. Install Python 3.12 or newer (3.14 is fine). `py -0` lists installed versions.
2. Copy an abapGit ZIP into `data\input\`.
3. Double-click `run.bat` (or in PowerShell: `.\run.bat`).

> PowerShell on managed laptops blocks `Activate.ps1` ("running scripts is
> disabled"). You never need it: `.\run.bat <command>` activates internally, or
> call the tools directly: `.\.venv\Scripts\python.exe -m pip install -e .`
> and `.\.venv\Scripts\atlas.exe ui`.

That creates a virtual environment, installs the package and runs the full
pipeline on the newest ZIP. Then start the web app:

    run.bat ui

It opens http://localhost:8080 in your browser (Overview, Discover, Ask the
codebase, object pages with dependencies and findings, Assessments, Dependency
map, Inventory with CSV export, Jobs & Pipeline with upload and AI enrichment).
Ctrl+C in the terminal stops it. The command line stays available:

    run.bat search "report that ages vendor open items"
    run.bat search "check whether a sales order already exists" --type CLAS
    run.bat show ZCL_ZSD_SALESORDER
    run.bat objects --type TABL,DTEL
    run.bat stats
    run.bat jobs
    run.bat watch                     # automation: process every new ZIP dropped into data\input

Manual setup (any OS):

    python -m pip install -e .
    atlas run "path\to\export.zip" --system DEV --package ZAD
    atlas search "register a beneficiary with the bank"

## Carrying over the prototype's Claude descriptions

    atlas import-legacy "..\sap_repo\data\output" --system DEV
    atlas index

The 23 AI descriptions written for the demo are attached to the matching
objects and marked `described_by = ai`; re-ingesting never overwrites them.

## Better meaning-based search (optional)

    .\.venv\Scripts\python.exe -m pip install model2vec
    .\run.bat index

Downloads the potion-base-8M static-embedding model once (~30 MB, from
Hugging Face) and runs it locally with numpy only - works on Python 3.14. On
Python <= 3.12 you can install `sentence-transformers` instead for MiniLM.
If neither is installed (or the download is blocked by a proxy) a TF-IDF/SVD
fallback is used automatically and the reason is recorded in the job.

## AI features - choose your provider (Settings → AI provider)

ABAP Beacon works without AI; the AI features (Describe with AI, Ask the codebase,
FSD review) run on whichever provider you pick:

| Provider | Cost | Data leaves the machine? | Setup |
|---|---|---|---|
| **Ollama** (llama3.1, qwen2.5-coder, mistral...) | free | **no** - fully offline | install from ollama.com, `ollama pull llama3.1` |
| **LM Studio** | free | no | start its local server |
| **Groq** | free tier | yes (redacted) | key from console.groq.com |
| **OpenRouter** (`:free` models) | free | yes (redacted) | key from openrouter.ai |
| **Google Gemini** | free tier | yes (redacted) | key from aistudio.google.com |
| **Mistral** | free tier | yes (redacted) | key from console.mistral.ai |
| **Claude Code** | Claude subscription | yes (redacted) | `npm install -g @anthropic-ai/claude-code`, run `claude` once to log in |
| **Anthropic / OpenAI API** | paid | yes (redacted) | API key |
| **Manual** | free | you decide | prompt files to paste into any chat |

Pick, test and save the provider on the **AI provider** page (stored in
`data\config\ai.json` on this machine), or via environment variables
`ATLAS_AI_PROVIDER` (ollama, groq, openrouter, gemini, mistral, claude-code,
anthropic, openai, custom, manual), `ATLAS_AI_API_KEY`, `ATLAS_AI_BASE_URL`,
`ATLAS_AI_MODEL`. `custom` accepts any OpenAI-compatible endpoint (vLLM,
company gateway). Free tiers have per-minute limits: ABAP Beacon stops cleanly at a
429 and resumes on the next run without re-sending anything.

    .\run.bat ai-status
    .\run.bat enrich-ai --limit 10
    .\run.bat ask "..."
    .\run.bat fsd my_spec.docx --ai

## Guardrails - what never leaves the machine

Everything sent to any AI provider is redacted first, always: credentials,
host names, e-mail addresses, bank accounts, tokens, IP addresses, phone
numbers - plus the data-protection policy on **Settings → Guardrails**:
customer / partner / project names you list, SAP system IDs, clients and
transport numbers, business keys (customer, vendor, document, material
numbers), user names. Values become stable pseudonyms (`<customer-737>`) so
the model can still reason about them. The same masking is applied to what
the web app displays and to generated reports (switch it off per policy), the
number of source lines per object sent to AI is capped, and every AI call is
listed in the egress log with its redaction count. Policy file:
`data\config\guardrails.json`.

The list only protects names it knows, so every uploaded FSD is scanned for
new ones (title, document control, "\<X\> System", "from \<X\> to \<Y\>",
unknown acronyms, author fields). They are masked in that analysis at once -
title, requirement table, report, AI review - and the FSD page offers **Add to
guardrails**; on the command line use `.\run.bat guard-add "Name" "Other"`.
Switch the scan off with the *Auto-detect names* toggle if you prefer to
maintain the list by hand.

Claude Code specifics:

    .\run.bat ai-status                      which provider ABAP Beacon will use
    .\run.bat enrich-ai --limit 10           describe 10 objects (batched, redacted, cached)
    .\run.bat enrich-ai                      describe everything pending
    .\run.bat ask "how does the sales order OData service check the reference?"
    .\run.bat run <zip> --ai                 pipeline including AI for changed objects

the prompt goes to the `claude` CLI on stdin in an empty working directory,
so no project files or tools are involved; usage-limit responses stop the run
and the next run continues where it left off.

## FSD analysis (reuse before you build)

    .\run.bat fsd samples\fsd\FSD_01_Sales_Order_Creation_from_Salesforce.md
    .\run.bat fsd my_spec.docx --ai           adds an AI review of the analysis
    .\run.bat fsd-list

Outcome is one of REUSE (>= 65 % weighted coverage), EXTEND (35-65 %) or NEW
DEVELOPMENT, with a per-requirement table (status, best matching object and
method, confidence, what to do, effort), the reuse candidates, a step-by-step
development plan with standard building blocks, objects to create/extend/reuse,
an effort estimate and S/4HANA notes. The Markdown report lands in
`data\output\fsd\`. Five sample FSDs covering every outcome are in
`samples\fsd\` (see its README); the web app has an **FSD analysis** page
with upload and one-click samples. A file that cannot be read (old .doc,
damaged .docx, scanned PDF, empty file) produces one readable message with the
fix, never a stack trace.

## Source control and releases

The source lives in a Git repository with a protected `main` branch; every change is a pull request reviewed
by the maintainer named in `CODEOWNERS`. Users install **releases** (zip + `SHA256SUMS.txt` on the Releases
page), never a copied source folder. `python release.py` runs the tests and builds the zip, wheel and
checksums. See `CONTRIBUTING.md`, `LICENSE` and `AUTHORS`.

## Product or internal library? Workspaces (v0.15)

Both, on one engine: a **workspace** is an isolated data set (its own database, index, uploads, config).
A *customer* workspace is the product as the customer uses it; an *internal* workspace is InfraBeat's own
accelerator library where every object carries its origin. Code, analyses, searches and numbers never cross
workspaces - five customers' ageing reports never meet in one search. Settings → Workspaces: switch,
create, and set per workspace:

- **AI mode** - *normal* (AI optional, everything masked) or **strict** (AI switched off entirely: no
  provider is constructed, the Ask / Review / Describe-with-AI functions disappear; every analysis, number
  and document still works).
- **Assessment target release** - the rule variant, like ATC's `S4HANA_READINESS_<release>` check
  variants: only rules that matter for the chosen S/4HANA release (1709 … 2025, or Cloud / Clean Core)
  are applied. Rules are tagged with the release they apply from (`atlas/assess/rules.py`,
  `RULE_RELEASE` / `RULE_TARGETS`) - a yearly SAP release is a table update, not an engine change.

Command line: `run.bat workspace list|create|show`; activate one with `$env:ATLAS_WORKSPACE='<slug>'`.

**Data Protection Sheet** - Guardrails page → one-page .docx generated from the live configuration of the
workspace (where data is, AI mode and provider, what is masked, egress so far) for the customer's security
officer. CLI: `run.bat protection-sheet`.

**Usage data accumulates** - SAP keeps detailed ST03N data for a few months; monthly aggregates and
SCMON/SUSG cover a year or more. Upload each period's export with its from/to dates; imports add up (the
same window is replaced, never doubled). The retirement table shows the window actually covered; with
fewer than 12 months, or for objects that ran only a handful of times (period-end programs), Beacon says
*review*, never *retire*.

**Compare the reuse candidates** - when an FSD matches several objects, a table ranks them by facts:
coverage of this FSD, covered/partial statements, open findings, production usage, Clean Core tier, size.
A person chooses; the table is the evidence.

## Branding

The shell shows the product name and a "by InfraBeat" mark. To show the official company logo, download it
once into the assets folder and restart:

    Invoke-WebRequest "https://infrabeat.com/wp-content/uploads/2024/09/IBLogo_Color-01-1-1-1.png" -OutFile "atlas\ui\assets\infrabeat_logo.png"

Any `infrabeat_logo.svg` or `infrabeat_logo.png` (about 120x30 px, transparent) in `atlas\ui\assets\`
is used in the top bar and the sidebar footer. Product name and tagline can be overridden with
`ATLAS_PRODUCT_NAME` / `ATLAS_PRODUCT_TAGLINE`.

## Executive view - the money (v0.14)

The **Executive view** turns the repository into a business case a steering committee can sign:

- **S/4HANA remediation programme** - remediation hours from the open findings, grouped into three waves
  (security/blockers → simplification & Clean Core → quality), by module, priced with a blended rate,
  sized into person-days and a timeline for a given team.
- **Custom code retirement** - import production usage (ST03N workload / SCMON-SUSG export, CSV or TSV)
  and Beacon decides per object *retire / review / keep* from usage, custom callers and open findings,
  with the hours and money each retirement avoids. Without usage data the dependency graph alone marks
  candidates for review. A sample export for the demo repository is in `samples\usage\` (see its README
  for how to take a real one from ST03N / SCMON).
- **Clean Core advisor** - classic tables, BAPIs and function modules found in the code with their
  released S/4HANA successor (I_Customer, API_BUSINESS_PARTNER, CL_SALV_TABLE …) and the extensibility tier.
- **Value delivered by reuse** - for every FSD analysis, the hours not built again because existing code
  covered the requirements, in money.
- **Business case (.docx)** - all of the above as an executive document (`run.bat value --docx`).

**ABAP skeletons (.zip)** - from any analysis: abapGit-layout source files - classes with one method per
plan step (FSD statement ids in the comments), ABAP Unit test class with one test per statement, exception
class, program with selection screen and ALV, table DDL, message class. The first 20-30 % of typing, with
traceability built in. CLI: `run.bat codegen <analysis id>`.

## Feasibility, complexity and the Technical Specification (v0.13)

Every FSD analysis now carries a **Feasibility & complexity card**: a verdict (*Feasible / Feasible with
changes / Needs clarification / Not feasible as written*) with the reasons - APIs named in the FSD that do
not exist in standard SAP, remote calls inside the save, direct writes to standard tables, modifications of
SAP objects - a complexity band S/M/L/XL with its drivers, an FSD quality score (what the document covers,
how many statements are testable, which use open wording), the RICEFW classification, the estimate
confidence and a generated list of **clarification questions for the functional consultant**. All of it is
deterministic and explainable; the AI can elaborate but never changes it.

**Technical Spec (.docx)** - one click (or `run.bat fsd <file> --docx`) writes the first version of the
technical specification: cover, scope, feasibility and open points, reuse decision, solution design with
the processing steps and their building blocks, development objects with the APIs each uses, requirement
traceability, effort, S/4HANA notes, test scenarios and a sign-off table. Masked like every other output.

**Ask the architect (AI)** - on the analysis page, ask anything about the analysis ("why is BAPI_BUPA_CHANGE
not used?", "what must be confirmed before build?"); the answer is grounded in the analysis facts, the
prompt is masked by the guardrails and logged in the egress ledger.

**Code freshness** - the Overview shows *Code as of <date>* (the last ingestion); every analysis remembers
the repository state it was matched against and shows *"the repository changed after this analysis - re-run"*
when a newer export has been ingested since. Re-ingesting a new abapGit export is a delta (content hashes):
only changed objects are re-parsed, re-described and re-assessed.

**Where AI is used** - the Overview lists the four places the LLM works (object descriptions, Ask the
codebase, FSD architect review, Ask about an analysis) with live counts, and what is deliberately
deterministic (parsing, search ranking, rules, FSD matching, feasibility, guardrails).

**Security hygiene** - `run.bat audit` scans the installed dependencies for known vulnerabilities
(pip-audit); see `SECURITY.md` for the upgrade and reporting notes.

## If the web app shows "database disk image is malformed"

That is SQLite, not ABAP Beacon: the file `data\atlas.db` was damaged, almost
always because a new release was unzipped over an old folder while the old
`atlas.db-wal` / `atlas.db-shm` files (or a running UI) were still there. Since
v0.15.1 every start checks the database and repairs it automatically - a stale
log is moved aside, readable rows are recovered into a fresh file, the damaged
file is kept as `atlas.db.corrupt-<timestamp>`. Manual commands:

    .\run.bat db-check                     state of the database file (stop the web app first)
    .\run.bat db-repair                    repair it now
    .\run.bat                              rebuild from data\input if objects are missing

Always stop the UI (Ctrl+C) before unzipping a new version over the folder.

## Analysis commands

    .\run.bat assess                         run all rules; summary by rule
    .\run.bat findings --category security   list findings (also --severity, --rule, --object)
    .\run.bat deps ZCL_ZCA_APPLOG            what it uses / who uses it
    .\run.bat impact BSIK                    transitive dependents (3 levels)
    .\run.bat tables                         most-used tables with S/4 status

## What the pipeline does

    acquire  -> read ZIP or folder
    ingest   -> one row per SAP object; source files, metadata, components
                (methods, function modules with signatures, table fields,
                messages); content-hash change detection
    parse    -> methods/forms/FMs with line ranges, references (tables read/
                written, FM/class calls, includes, AUTHORITY-CHECK), metrics
    enrich   -> offline description, tags, module, complexity - no AI needed
    assess   -> rule engine: findings, Clean Core tier, S/4HANA status
    ai       -> (optional, --ai) AI descriptions for changed objects
    index    -> semantic index for meaning-based search

Every run is stored as a job with per-step status and timings (`atlas jobs`).
Unchanged objects are skipped end to end, so nightly re-runs are cheap.

## Layout

    atlas/
      cli.py              command line (typer)
      config.py           data dir / DB URL from env or defaults
      db/                 SQLAlchemy models + session
      ingest/             abapGit reader, object-type registry, XML metadata parser, DB writer
      enrich/             offline enrichment rules
      parse/              ABAP/CDS structural parser, dependency + impact queries
      reference/          SAP standard table dictionary with S/4HANA simplification status
      assess/             rule engine (S/4HANA, security, quality, Clean Core) and findings store
      ai/                 providers (Claude Code, Anthropic, Ollama/LM Studio/Groq/OpenRouter/Gemini/Mistral/OpenAI/custom, manual), redaction, enrichment, Ask
      guard/              data-protection guardrails (policy, masking for egress and display, auto-detection of names in documents)
      fsd/                FSD reader (docx/pdf/md), requirement extraction, matcher, knowledge base of SAP building blocks, planner, report
      search/             BM25 + compound splitting + type hints + semantic fusion, SAP synonyms
      ui/                 NiceGUI web app (Fiori Horizon look)
      pipeline/           job runner, watch-folder automation
      legacy/             importer for the v0.6 objects.json / ai_descriptions.json
    tests/                pytest suite with the sample export as fixture
    samples/fsd/          sample functional specifications + expected analysis reports
    data/                 input/ (drop ZIPs), atlas.db, index/, output/

Configuration via environment: `ATLAS_DATA_DIR`, `ATLAS_DB_URL` (switch to
PostgreSQL later), `ATLAS_LOG_LEVEL`.

## Tests

    python -m pytest -q

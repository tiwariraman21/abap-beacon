# Roadmap

Full plan: see `ABAP_Atlas_Product_Plan.md` (delivered separately). Order confirmed: phases as listed.

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundation: package layout, SQLite schema, pipeline with recorded jobs, CLI, offline enrichment, BM25+semantic+RRF search, legacy import, watch-folder automation, tests | **done (v0.7.0)** — also pulled forward from Phase 1: abapGit XML metadata (short texts, method/FM/field components), 60+ object types |
| 1 | Ingestion 2.0: ABAP structural parser (methods with line ranges, FMs, forms, SELECT/UPDATE tables, CALL FUNCTION / method calls, AUTHORITY-CHECK, includes), reference edges, SAP standard dictionary, dependency graph + impact analysis, multi-system compare | **done (v0.9.0)** except multi-system compare |
| 2 | Automated AI enrichment: provider interface, **ClaudeCodeProvider** (headless `claude -p`), redaction gate, chunking, hash cache, usage/cost ledger, review queue, prompt-pack fallback, scheduler | **done (v0.9.0)** except review queue UI and scheduler (use `atlas watch` + `--ai`) |
| 3 | Search 2.0 + Ask: compound splitting, type-hint terms, coverage scoring, name/short-text boosts, model2vec backend, RAG Q&A with line citations | **done (v0.9.0)** except editable synonym dictionary and facets |
| 4 | Assessments: rule engine, S/4HANA readiness, Clean Core tiering, security/quality, finding lifecycle | **done (v0.9.0)**: 30 rules in Python (YAML packs later), clone detection open |
| 4b | **FSD analysis** (new, customer-requested): requirement extraction from .docx/.md, requirement-level matching with coverage %, reuse/extend/build verdict, change list, build plan from a knowledge base of BAPIs/FMs/classes, effort, findings cross-check, optional AI review | **done (v0.10.0)** |
| 4c | Guardrails + provider choice: data-protection policy (terms, system IDs, business keys, users) applied to egress and display, egress log, settings pages; open-source / free AI providers (Ollama, LM Studio, Groq, OpenRouter, Gemini, Mistral, custom) alongside Claude; product renamed **ABAP Beacon** | **done (v0.11.0)** |
| 4d | FSD analysis hardened on a real customer FSD: non-requirement sections skipped, nested bullets, custom Word heading styles, title/module detection, matcher needs specific evidence (no coverage from generic integration words), planner uses the FSD's own BAPIs first, BP change / replication / trigger / proxy / retry / reconciliation knowledge, design alternatives; guardrails auto-detect names in uploaded documents; PDF input; readable errors for bad uploads | **done (v0.12.0)**; v0.12.1 adds a start-up database health check with automatic repair (stale WAL, page corruption) and `db-check` / `db-repair` |
| 4e | Client review follow-up (v0.13.0): Feasibility & complexity card with clarification questions, Technical Spec .docx from the plan, Ask-the-architect AI Q&A on an analysis, code-freshness ("code as of", stale-analysis warning), "Where AI is used" panel, dependency audit command + SECURITY.md | **done (v0.13.0)** |
| 4f | Executive value (v0.14.0): retirement engine with usage import, S/4HANA business case with waves and .docx, Clean Core advisor (classic → released successor), reuse-savings portfolio, ABAP skeleton generator with ABAP Unit tests | **done (v0.14.0)** |
| 4g | Post-showcase review (v0.15.0): workspaces (customer vs internal, isolation), strict no-AI mode, rule variants per S/4HANA target release, usage accumulation with 12-month rule and seasonal risk, Data Protection Sheet, compare-candidates table, additive schema upgrade | **done (v0.15.0)** |
| 5 | Documents: inventory .xlsx, assessment .pdf; rule packs per S/4HANA target release; automatic code sync (abapGit background / ADT pull); LLM-based requirement extraction and grounded planner | next |
| 6 | Enterprise UI in NiceGUI with a Fiori Horizon look | **done (v0.9.0)**: Overview, Discover, Ask, Object page (Description / Components / Dependencies / Findings / Source / Files / Attributes), Assessments, Dependency map, Inventory, Jobs (+ AI enrichment); Documents/Admin follow their phases |
| 7 | Platform ops: roles/login, audit log, Docker + one-click Windows, backups, REST API, notifications, 20k-object load test | |
| 8 | Commercial: read-only ADT connector, abapGit pull, PostgreSQL/pgvector, SSO, CI transport gate | |

## Phase 0 acceptance (all met)
- Same ZIP ingested twice: second run reports `unchanged = all`, index step skipped.
- 77 objects from the sample export (POC: 23), including 17 structures/tables with fields, 17 data elements, Gateway artefacts.
- `atlas search "report that ages vendor open items"` returns `ZRFI_VENDOR_AGEING` first.
- Query hits method short texts ("check whether sales order already exists" → `ZCL_ZSD_SALESORDER → CHECK_SF_REF_ALREADY_EXISTS`).
- 23 legacy AI descriptions imported without loss.
- 29 tests green in ~7 s.

## v0.9.0 acceptance (all met)
- `atlas search "salesorder interface"` ranks the sales-order Gateway service/model and `ZCL_ZSD_SALESORDER` on top; the flight-booking INTF no longer appears in the top 3 (regression test).
- `atlas impact BSIK` → `ZRFI_VENDOR_AGEING_NEW_SEL` (L1) → `ZRFI_VENDOR_AGEING` (L2).
- Assessment on the sample: 64 findings / ~119 h; SEC-001 hard-coded client secret, SEC-002 bank URLs, S4-001 BSIK, S4-006 SD_ORDER_CREDIT_RELEASE all detected; accepted/false-positive statuses survive re-runs.
- AI enrichment + Ask verified end to end against a fake Claude Code CLI (`tests/fake_bin`), including cache hits and usage-limit stop/resume.
- 43 tests green.

## v0.10.0 acceptance (all met)
- Four sample FSDs give the four intended outcomes: reuse (sales order interface → ZCL_ZSD_SALESORDER, duplicate check matched to CHECK_SF_REF_ALREADY_EXISTS), extend (vendor ageing .docx → ZRFI_VENDOR_AGEING*, ALV/e-mail plan), new development (PO approval workflow → BAPI_PO_RELEASE / SAP_WAPI_START_WORKFLOW / CL_BCS plan, reuses ZCL_ZCA_APPLOG), reuse with a security gap (bank API → SEC-002 downgrades the "secure credentials" requirement).
- Word documents parsed without extra libraries (headings, bullets, tables).
- 46 tests green.

## v0.12.0 acceptance (all met)
- Real customer FSD (BP change replication, Word with custom styles and a cover table): title read from the document, 35 requirements instead of 54, 0 % coverage instead of 23 %, no false reuse candidate, plan built on the FSD's BAPIs with a change-replication pattern, `Aramco` / `ASMO` / author detected and masked without being on the list, one-click add to guardrails.
- The four earlier samples keep their verdicts (reuse 68 %, extend 42 %, build 0 %, reuse 79 % with SEC-002 downgrade).
- Bad uploads (damaged .docx, .doc, empty, unsupported, scanned) give one readable message in UI and CLI; PDF and odd text encodings are read.
- 55 tests green.

## Next
- FSD analysis: learn from decisions (mark a match as wrong/right to tune thresholds), export the analysis as .docx, compare two FSDs, knowledge base editable in the UI.
- Phase 5 documents (TS .docx per object, inventory .xlsx, assessment .pdf) - one command, uses the findings and dependency data already in the DB.
- Review queue for AI descriptions (approve/edit → `described_by = human`).
- Editable synonym dictionary + facets in Discover; clone detection; YAML rule packs; multi-system compare.

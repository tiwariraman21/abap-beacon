# ABAP Atlas — Product & Architecture Plan
### From "AI-Powered SAP Code Repository" (POC v0.6) to an enterprise custom-code intelligence platform

*Working title "ABAP Atlas" — rename freely. Prepared 05-Sep-2026 for InfraBeat's AI Innovation Challenge and the commercial phase that follows it.*

---

## 0. Executive summary

The POC proves one idea: describe a business need in English, find the ABAP that already does it. That is real, but it is one feature, and on its own it is hard to sell — a customer will ask "how many hours did this save me?" and today the app cannot answer.

The plan below turns the same ingestion → understanding → search core into a **custom-code intelligence platform** with five revenue-bearing capabilities, one automated end-to-end pipeline, an SAP Fiori-grade UI, and a built-in ROI ledger that proves its own value. Everything stays deployable on a single on-prem Windows machine (your constraint: no installs in client systems until the product is sold), with a clean upgrade path to Postgres/cloud.

**What changes, in one table:**

| Dimension | POC today | Target |
|---|---|---|
| Input | one abapGit ZIP, `.abap`/`.asddls` only, 5 object types | ZIP / folder / watch-folder / REST upload; **24+ object types incl. the `.xml` metadata the POC throws away** (SAP short texts, method descriptions, DDIC fields, packages, auth objects) |
| Understanding | flat description + tags | Structural parse (methods, FMs, SELECTs, calls, includes) → **dependency knowledge graph** → AI descriptions at object *and* method level |
| AI step | copy-paste prompt pack into Claude by hand | **Automated** via Anthropic API with redaction, hash caching, batching, cost meter; manual prompt-pack kept as a no-API fallback |
| Search | hand-tuned keyword weights + MiniLM | BM25 + vector with reciprocal-rank fusion, method-level hits, SAP business→technical synonym layer, **Ask-the-codebase Q&A with citations** |
| Analysis | none | S/4HANA readiness, Clean Core tiering, security & quality rules, duplicate/clone detection, impact analysis |
| Documents | none | Auto Technical Specification (.docx), Custom Code Inventory (.xlsx), Assessment Report (.pdf) |
| Storage | 545 KB JSON, re-read per keystroke | SQLite (WAL) + vector index; Postgres/pgvector switch behind one interface; incremental by content hash |
| UI | Streamlit tabs | **NiceGUI (Python-only) styled to the SAP Fiori Horizon look** — enterprise appearance without a second language to maintain |
| Ops | run a script | CLI + REST + scheduler, job monitor, audit log, roles, Docker/one-click Windows installer, tests, CI |
| Value proof | none | **ROI ledger**: reuse events, hours saved, findings closed — on the landing dashboard |

---

## 1. Honest assessment of the POC (what to keep, what must go)

I read every file in the upload. Credit first: the code is clean, well-commented, idempotent, and the hybrid search with SAP synonyms is a good instinct. It is a solid Phase-1.

Things that block enterprise use:

1. **It discards the most valuable free data.** abapGit `.xml` files carry the SAP short text of every class (`DESCRIPT`), every method (`SEOCOMPOTX`), every data element (`DDTEXT`), table fields, package assignment and authorisation objects. Your sample export has 23 code objects but 50+ metadata files; `ZCL_ZSD_SALESORDER.clas.xml` alone describes every method in plain English. The POC never reads them.
2. **No structure, no graph.** Objects are opaque blobs. You cannot ask "who reads BSIK?" or "what breaks if I change `ZCL_ZCA_APPLOG`?" — the two questions every SAP architect actually asks.
3. **The AI step is manual**, so it cannot scale past a demo and cannot run nightly. A 272 KB MPC class is truncated to 6.5 KB — descriptions of large objects are guesses.
4. **JSON store won't survive a real system.** A mid-size S/4 client has 5,000–30,000 custom objects; 29 files already produce a 545 KB file that Streamlit reloads on every interaction.
5. **Search scoring is hand-tuned magic numbers** (12/8/4/2, cap 10, ratio 0.35) fitted to 23 objects. It will not generalise; replace with standard IR (BM25 + embeddings + RRF) that needs no tuning.
6. **No security posture.** The sample code itself contains a credential-like literal (`ZAPI_AES128_BENE_REG`) that the POC would happily ship to an LLM. Enterprise clients will ask about this in the first meeting.
7. Streamlit is a fine internal tool but will never read as "enterprise" to an SAP audience; there is also no auth, no audit, no multi-system support, no tests.

**Good news:** items 1, 2 and 4 are pure engineering, and your own sample data already contains real findings the new modules will surface on day one — BSIK usage (S/4 simplification item), a program with no `AUTHORITY-CHECK`, a hard-coded credential, and an OData DPC/MPC pair that is 400 KB of generated code nobody should ever re-describe manually.

---

## 2. Product vision, personas and revenue

### 2.1 Positioning
> "Every SAP customer has 10–30k custom objects nobody fully understands. ABAP Atlas reads them, explains them, maps them, grades them for S/4HANA and Clean Core, and turns that into reuse, remediation plans and documents — automatically, on your own hardware."

### 2.2 Personas (each maps to a UI workspace)

| Persona | Question they bring | Capability that answers it |
|---|---|---|
| **ABAP Developer** | "Does something like this already exist?" / "What does this 4,000-line class do?" | Discover, Object Explorer, Ask-the-codebase |
| **SAP Architect / Tech Lead** | "What depends on what? What breaks if we change X? Where is Clean Core violated?" | Dependency Graph, Impact Analysis, Clean Core tiering |
| **S/4HANA Migration Lead** | "How much custom code needs remediation, and what exactly?" | S/4 Readiness Assessment, Inventory export |
| **Delivery / Practice Manager** | "Prove this saves money." | ROI Dashboard, Assessment Report |
| **Security / Basis** | "Any hard-coded credentials, missing auth checks, dangerous statements?" | Security & Quality rules |
| **New joiner / Support (AMS)** | "Explain this program, in the context of what calls it." | Auto Technical Spec, Q&A |

### 2.3 Revenue model (InfraBeat)

1. **Accelerator inside InfraBeat (now).** Run on every project's abapGit export. Value: reuse, faster onboarding, auto TS documents for every CR (your own recent work — credit workflow email, BG background job, CDS extension — each needed a TS document that this generates from code).
2. **Assessment-as-a-Service (first external revenue, no install needed).** Client exports abapGit ZIP → 24 h later InfraBeat delivers a branded S/4 Readiness + Clean Core + Security assessment PDF and inventory workbook → lands the remediation project. This is the pre-sales weapon for S/4 conversions.
3. **Subscription (after first sale).** Per-system licence, on-prem or client cloud; live pull via standard ADT REST APIs (read-only, user credentials, **zero custom objects installed** — respects your constraint) or abapGit where the client already has it.
4. **Later:** AMS knowledge base, CI gate (quality rules on every transport), marketplace of rule packs.

### 2.4 ROI ledger — how the app proves value
Tracked events, each with a configurable hour value and blended rate (defaults editable in Admin):

| Event | Default hours saved | Source |
|---|---|---|
| Developer marks a search result "Reused this" | 16 h | Discover |
| Technical Spec generated | 4 h | Documents |
| S/4 finding identified with remediation | 2 h analysis | Assessment |
| Security/quality finding closed | 1 h | Assessment |
| Q&A session with citation (onboarding) | 0.5 h | Ask |

Dashboard shows hours & currency saved per month, per system, per persona, exportable for management. No ROI claim is made without a logged event — auditable.

---

## 3. Capability roadmap (what the product does)

### C1 — Ingestion 2.0
- Sources: ZIP, extracted folder, **watch folder** (drop a ZIP → pipeline runs), REST upload, scheduled re-pull (future: ADT/abapGit live).
- Full abapGit coverage: PROG, CLAS (incl. locals, test classes, macros), INTF, FUGR (function modules resolved individually with signatures from XML), DDLS, DCLS, DDLX, TABL, DTEL, DOMA, TTYP, VIEW, ENHO/ENHS, BADI, SXCI, MSAG, TRAN, DEVC (package tree), SUSO (auth objects), SRVD/SRVB (service definitions/bindings), BDEF (RAP behaviour), WDYN metadata, SMIM ignored.
- Parse `.xml` metadata: SAP short texts (object + method + parameter), DDIC field lists, package hierarchy, translations.
- Multi-system, multi-client: `System (SID) → Client → Package → Object`, so ER5/ER6-style comparisons are possible later ("what differs between DEV and QAS?").
- Incremental: content hash per file; unchanged files skip every downstream step (this alone makes nightly runs cheap).

### C2 — Structural understanding (ABAP parser + knowledge graph)
Lightweight tokenizer/parser (no full grammar needed) extracting:
- Declarations: report, class (superclass, interfaces, final/abstract), interface, function-pool, method signatures & visibility, FM signatures, form routines, includes.
- Data access: tables in `SELECT/UPDATE/INSERT/MODIFY/DELETE`, CDS `select from`, associations, `EXEC SQL`/AMDP.
- Calls: `CALL FUNCTION`, `->method(`, `=>`, `CREATE OBJECT`, `NEW`, `SUBMIT`, `CALL TRANSACTION`, `PERFORM`, `RAISE`, BAPIs, standard classes.
- Governance: `AUTHORITY-CHECK` objects, `MESSAGE` classes, `COMMIT WORK`, update tasks, locks, enqueue.
- Standard vs custom resolution: every referenced name is classified as *Custom (in repo)*, *Custom (not in repo — missing package)*, or *SAP standard* (shipped reference dictionary: ~1,500 common tables/FMs/classes with module + short text; e.g. VBAK → "Sales Document: Header", SD).

Stored as a graph: nodes (objects, tables, FMs, methods) and typed edges (`reads`, `writes`, `calls`, `inherits`, `implements`, `includes`, `raises`, `exposes_odata`). Powers Impact Analysis ("where-used" across the whole custom estate, N levels deep), the dependency visual, and better RAG context.

### C3 — AI enrichment (automated)
- Provider abstraction: `ClaudeCodeProvider` (default for the challenge — Claude Code headless mode on the existing subscription, no API key), `AnthropicProvider` (API key, for customers), `PromptPackProvider` (today's manual mode — kept for clients with no AI access), later Azure/OpenAI/on-prem models.
- Method-level chunking for large objects (no more 6.5 KB truncation); object summary is synthesised from method summaries.
- Structured JSON outputs, validated with Pydantic; retries; per-object token/cost accounting; hash-keyed cache so re-runs are free.
- **Redaction gate before any external call:** literals matching secrets (`password`, `client_id`, `secret`, `apikey`, IBAN-like, long base64/hex), emails, phone numbers, hostnames → replaced with placeholders; the redaction log is visible in the job.
- Human review queue: AI descriptions are `status = ai_draft` until an Architect approves (optional per system); edited text is retained across re-ingest (the POC already does this — preserved).
- Generated artefacts per object: business description, technical description, tags, module, business process, complexity score, "what a developer would use it for", risks noted.

### C4 — Search & Ask
- **Discover:** BM25 (rank-bm25) over name/short-text/description/tags/method names + dense vectors (local `bge-small-en-v1.5` or MiniLM, 384-d) fused with Reciprocal Rank Fusion. No hand-tuned weights. Facets: system, package, type, module, tags, risk, S/4 status.
- Query layer keeps your SAP synonym idea but as a maintainable dictionary (business term → technical tokens) editable in Admin and extendable per client.
- Method-level results ("`ZCL_ZSD_SALESORDER→CHECK_SF_REF_ALREADY_EXISTS` — 91% match") with jump-to-source.
- **Ask the codebase:** RAG chat grounded on retrieved chunks + graph neighbours; every answer cites object/method/line ranges; "I don't know" when retrieval is weak. Session logging feeds the ROI ledger.

### C5 — Assessments (the revenue engine)
Rule engine = deterministic rules (fast, offline, explainable) + AI second opinion (optional, per finding).
- **S/4HANA Readiness:** shipped Simplification-Item rule pack — replaced tables (KONV→PRCD_ELEMENTS, VBUK/VBUP→VBAK/VBAP status fields, BSIK/BSID/BSAK/BSAD→ACDOCA compatibility views, MARC/MARD field moves, KNA1/LFA1→BP, MATNR length 40, classic pricing/credit management (SD-BF-CM → FSCM-CR, which you know well)), obsolete statements (`TABLES`, `OCCURS`, `WITH HEADER LINE`, `TYPE-POOLS`, `MOVE…TO`, `COMPUTE`, `FIELD-GROUPS`, `RANGES`), HANA-order dependence (`SELECT … FOR ALL ENTRIES` without sort, missing `ORDER BY` with `SELECT SINGLE`/`UP TO 1 ROWS`), native SQL, pool/cluster tables. Each finding: severity, effort estimate, remediation text, code snippet, AI-suggested fix.
- **Clean Core tiering:** classify each object Tier 1 (key-user/RAP/released APIs only), Tier 2 (developer extensibility on released objects), Tier 3 (classic, modification-like) using signals: released-API usage, RAP/CDS presence, direct DB writes to SAP tables, enhancement type, use of unreleased classes. Output: tier distribution + migration path per object.
- **Security & Quality:** hard-coded credentials, missing `AUTHORITY-CHECK` in executables, `SELECT *`, `SELECT` inside `LOOP`, nested loops on large tables, dynamic `CALL TRANSACTION` without auth, `COMMIT WORK` in update task, `BREAK-POINT`/`WRITE` left in, empty exception handlers, cyclomatic complexity, unused parameters, dead includes, missing ABAP Unit.
- **Duplicates & clones:** MinHash/shingling on normalised tokens + embedding similarity → "these 3 vendor-ageing includes are 87% identical" → consolidation candidates with saved-hours estimate.
- **Impact analysis:** given an object or table, N-level dependency tree, affected transactions/services, risk heat.
- Findings have lifecycle (`open → accepted → fixed → false_positive`), owner, comment — so the tool tracks remediation, not just lists it.

### C6 — Document generation
- **Technical Specification (.docx)** per object or package: purpose, business context, process flow (Mermaid → PNG), interfaces, data model touched, dependency diagram, methods table, error handling, authorisations, test notes, change history — InfraBeat template/branding, client-brandable.
- **Custom Code Inventory (.xlsx):** one row per object with module, description, complexity, S/4 status, tier, findings count, last changed — the sheet every migration lead builds by hand today.
- **Assessment Report (.pdf):** executive summary, charts, top risks, effort estimate by wave, appendix of findings. This is the deliverable in revenue stream #2.

### C7 — Enterprise UI (Fiori Horizon)
Screens: Overview (KPIs, ROI, recent jobs) · Discover · Ask · Object Explorer (source with syntax highlight, metadata, methods, findings, dependency graph, docs) · Dependency Map · Assessments (S/4, Clean Core, Security, Duplicates) · Documents · Jobs & Pipeline · Admin (systems, users/roles, AI provider & budget, synonym dictionary, rule packs, ROI parameters, audit log).

### C8 — Platform & operations
Roles (Viewer / Developer / Architect / Admin), local accounts now, SAML/OIDC later; audit log of every AI call, export and finding change; REST API + OpenAPI docs; scheduler; backups; Docker Compose and a one-click Windows `run.bat`; pytest suite, GitHub Actions CI, semantic versioning, CHANGELOG.

---

## 4. Target architecture

```
┌───────────────────────────────── Clients ─────────────────────────────────┐
│  React + UI5 Web Components (Fiori Horizon)   │   CLI (typer)   │  CI/CD   │
└──────────────────────────────┬────────────────┴───────┬─────────┴──────────┘
                               │ REST / OpenAPI (FastAPI, JWT)
┌──────────────────────────────▼───────────────────────────────────────────┐
│                          Application services                            │
│  Discover · Ask · Explorer · Assessments · Documents · ROI · Admin        │
├──────────────────────────────────────────────────────────────────────────┤
│                    Pipeline orchestrator (job DAG, idempotent)           │
│  ingest → parse → graph → offline enrich → redact → AI enrich →          │
│  embed/index → rules → clones → docs → ROI/notify                        │
├──────────────────────────────────────────────────────────────────────────┤
│  Domain libraries: abap_parser · sap_reference · rule_engine ·           │
│  ai_providers · retrieval (BM25 + vectors + RRF) · docgen                │
├──────────────────────────────────────────────────────────────────────────┤
│  Persistence (Repository pattern):  SQLite/WAL  →  PostgreSQL + pgvector │
│  Vector index: numpy/hnswlib file  →  pgvector                           │
│  Object store: ./data/systems/<SID>/…                                    │
└──────────────────────────────────────────────────────────────────────────┘
        ▲ Sources: ZIP · folder · watch-folder · REST upload · (later) ADT REST / abapGit pull
```

**Stack:** Python 3.12 (3.14 breaks `sentence-transformers`/torch wheels — this is why the fallback exists today), SQLAlchemy 2 + Alembic, Pydantic v2, typer, APScheduler, rank-bm25, sentence-transformers (CPU), networkx, python-docx/openpyxl/reportlab, pytest. UI: NiceGUI (Python-only, Quasar components, custom Fiori-Horizon CSS), with a FastAPI REST layer exposed from the same process for CI/CD and other tools. AI: Claude Code headless CLI first, `anthropic` SDK as an alternative provider.

**Why NiceGUI and not React+UI5:** one language to maintain. NiceGUI gives real components (tables, trees, tabs, dialogs, charts) and accepts custom CSS, so the Fiori Horizon look — shell bar, object page, KPI tiles, SAP-style tables — is achievable without a JavaScript toolchain. Streamlit is retired; the CLI covers Phases 0–5 until the UI lands in Phase 6.

### 4.1 Data model (core tables)

| Table | Purpose |
|---|---|
| `systems`, `clients`, `packages` | SAP landscape hierarchy |
| `objects` | one row per SAP object (type, name, package, short_text, description_business, description_technical, tags, module, complexity, content_hash, described_by, review_status, s4_status, clean_core_tier) |
| `object_files` | raw source files, hash, line count |
| `components` | methods / FMs / forms / includes with signature, short text, line range, summary, hash |
| `chunks` + vector index | embedding units (component-level) |
| `references` (edges) | source_id, target_name, target_kind (custom/standard/unknown), edge_type, line |
| `sap_reference` | shipped dictionary of standard tables/FMs/classes with module & text, S/4 mapping |
| `rules`, `findings`, `finding_events` | rule packs, results, lifecycle |
| `clone_groups` | duplicate clusters |
| `jobs`, `job_steps`, `ai_calls` | pipeline runs, per-step status, tokens/cost |
| `documents` | generated files with template version |
| `roi_events`, `roi_settings` | value ledger |
| `users`, `roles`, `audit_log`, `settings`, `synonyms` | platform |

Migration: a one-time importer loads your current `objects.json` + `ai_descriptions.json` so nothing described so far is lost.

### 4.2 End-to-end automation (the pipeline)
Every run is a job with steps; each step is idempotent and keyed by content hash, so a re-run after a small change touches only what changed.

| # | Step | Skips when |
|---|---|---|
| 1 | Acquire (ZIP/folder/upload/pull) → stage files | — |
| 2 | Ingest & classify files, parse XML metadata | file hash unchanged |
| 3 | Structural parse → components, references | object hash unchanged |
| 4 | Graph build/refresh, standard-vs-custom resolution | no reference changes |
| 5 | Offline enrichment (short texts, tags, module, complexity) | unchanged |
| 6 | Redaction + AI enrichment (component → object roll-up), cache, budget check | cached or budget exhausted (queued) |
| 7 | Embeddings + BM25 index refresh (incremental) | unchanged text |
| 8 | Rule engine: S/4, Clean Core, Security/Quality | unchanged object & rule pack version |
| 9 | Clone detection | unchanged |
| 10 | Document regeneration for changed objects (optional) | unchanged |
| 11 | ROI & KPI snapshot, notification (email/Slack/Teams webhook), audit | — |

Triggers: `atlas run <zip>`, watch folder, cron/APScheduler schedule, `POST /api/jobs`, UI button. Failures are per-step with resume; the Jobs screen shows progress, tokens, cost and the redaction log. Budget guardrail: monthly token cap per system; over cap → objects queue with offline descriptions until the cap resets or an Admin approves.

### 4.3 Security & privacy
- Redaction before egress; allow-list of what leaves the machine (source chunks only, never XML with user names/hostnames unless approved).
- Provider choice per system: Anthropic API, none (prompt pack), later on-prem model.
- Secrets in `.env`/OS keyring, never in DB; JWT auth; role checks on every endpoint; audit log immutable (append-only).
- Data residency: everything under `./data/systems/<SID>`; export/delete a system in one command (client off-boarding).

---

## 5. Delivery plan

Two horizons: **(A)** a challenge-ready, automated, Fiori-looking product in ~3 weeks of focused work; **(B)** the commercial platform over the following ~10 weeks. Each phase ends with something demoable and tested.

| Phase | Scope | Outcome / demo moment | Est. |
|---|---|---|---|
| **0 Foundation** | Restructure into `atlas/` package; SQLite schema + Alembic; repository layer; config/logging; typer CLI; import existing JSON; pytest + CI skeleton; Python 3.12 pin | Same features as today, on a real DB, with tests | 3 days |
| **1 Ingestion 2.0 + parser + graph** | XML metadata, 24 object types, multi-system model, content hashing, ABAP structural parser, references, SAP standard dictionary v1 (~1,500 entries), networkx graph | "Show me everything that reads BSIK and what calls it" | 5 days |
| **2 Automated AI enrichment** | Provider abstraction, Anthropic provider, redaction gate, method-level chunking, cache, cost meter, review queue, prompt-pack fallback, watch folder + scheduler + job model | Drop a ZIP → 10 minutes later everything is described, indexed, costed | 4 days |
| **3 Search 2.0 + Ask** | BM25 + vectors + RRF, facets, method-level hits, synonym dictionary, RAG Q&A with citations | "How does the sales-order OData service validate the reference number?" answered with line citations | 4 days |
| **4 Assessments** | Rule engine; S/4 pack v1 (60+ rules); Clean Core tiering; Security/Quality pack (30+ rules); clone detection; impact analysis API; finding lifecycle | Run on your sample → it flags the credential, BSIK, missing auth checks live | 6 days |
| **5 Documents** | TS .docx generator (InfraBeat template), inventory .xlsx, assessment .pdf | Generate a full TS for `ZCL_ZSD_SALESORDER` in 20 seconds | 4 days |
| **6 Enterprise UI** | NiceGUI app styled to Fiori Horizon: Overview, Discover, Ask, Explorer (code viewer + graph), Assessments, Documents, Jobs, Admin; ROI dashboard | The demo that wins the challenge and the first customer meeting | 8 days |
| **7 Platform ops** | Roles/JWT, audit log, Docker Compose, Windows one-click, backups, OpenAPI docs, notifications, load test at 20k objects | Installable at a client without you present | 5 days |
| **8 Commercial (post-challenge)** | ADT REST read-only connector (no client install), abapGit pull, Postgres/pgvector, SSO, CI transport gate, rule-pack marketplace, client branding | Subscription-ready | ~6 weeks |

**Recommended order for the challenge given the date:** 0 → 1 → 2 → 4 (rules) → 6 (UI) → 3 → 5 → 7. Automation plus assessments plus the Fiori UI is what moves a judge from "nice search" to "this is a product"; Ask and Documents follow immediately after.

---

## 6. Engineering standards
- Every module has unit tests; parser tested against a corpus of real ABAP idioms (your sample + synthetic edge cases: chained statements, macros, `INCLUDE` cycles, local classes, `SELECT … INTO CORRESPONDING FIELDS`).
- Type hints everywhere, Pydantic models at every boundary, `ruff` + `mypy` in CI.
- Prompts versioned in `atlas/ai/prompts/*.md`; every AI output stores prompt version so re-enrichment is reproducible.
- Rule packs are YAML: `id, title, severity, category (s4|cleancore|security|quality), pattern|python check, remediation, effort_hours, references (SAP note)`. Anyone can add a rule without touching code.
- Docs: README (install/run), ARCHITECTURE.md, ADRs for the decisions below, user guide per persona.

---

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| No API key (challenge) or no AI access (client) | Claude Code headless provider on the subscription now; prompt-pack provider retained; offline enrichment + XML short texts already give usable descriptions; per-system provider choice |
| Subscription usage limits interrupt a large enrichment run | Small hash-cached batches; job pauses and queues remaining objects, resumes on next run; nothing is re-sent twice |
| Parser accuracy on exotic ABAP | Parser is best-effort with confidence flags; unknowns shown as "unresolved reference", never silently dropped; corpus tests |
| False positives in rules erode trust | Every finding shows the exact line + rule text; `false_positive` lifecycle; rule-pack versioning; conservative defaults |
| Scale (30k objects on a laptop) | Incremental hashing, SQLite WAL, hnswlib for vectors, background jobs; Postgres switch when > ~50k |
| Python-only UI may look less "native SAP" than UI5 | Fiori Horizon CSS theme applied to NiceGUI components; backend is UI-agnostic so a UI5 front end remains possible if a customer requires it |
| Python 3.14 breaks ML wheels | Pin 3.12 in `pyproject.toml`; `run.bat` checks version and explains |
| Client data privacy objections | Redaction gate, egress allow-list, audit of every AI call, one-command system deletion, on-prem by default |

---

## 8. Decisions (confirmed 05-Sep-2026)

1. **UI stack: Python-only (NiceGUI)**, styled to the Fiori Horizon look (shell bar, object pages, KPI tiles, responsive tables). The backend stays UI-agnostic. Rationale and trade-offs: `docs/DECISIONS.md` ADR-002.
2. **AI access: Claude subscription with Claude Code, no API key.** AI enrichment runs through Claude Code's documented headless mode (`claude -p ... --output-format json`) as a `ClaudeCodeProvider`; the same provider interface accepts an API key or an on-prem model later; prompt-pack manual mode stays as fallback. Subscription usage limits are handled by small hash-cached batches and pause/resume. ADR-003.
3. **Delivery order: phases as listed (0 → 8).**
4. Product name: "ABAP Atlas" until renamed.
5. Demo deployment: Windows laptop, `run.bat`; Docker in Phase 7.

Phase 0 is delivered alongside this plan (see `docs/ROADMAP.md` in the project for the acceptance record). Phase 1 — the ABAP structural parser, reference graph and impact analysis — starts next.

# Architecture decisions

Short records of decisions that shape the build. Newest at the bottom.

## ADR-001 SQLite now, PostgreSQL later, behind SQLAlchemy
Single-machine on-prem deployment is the first target; SQLite in WAL mode is
zero-install and handles tens of thousands of objects. All access goes through
SQLAlchemy models so `ATLAS_DB_URL=postgresql://...` is the only change needed
later. Vectors live in a file index for now (pgvector later).

## ADR-002 Python-only UI (NiceGUI) instead of React + UI5
Confirmed 05-Sep-2026. Ashish maintains the product; a second language and
build toolchain would slow every change. NiceGUI renders Quasar/Vue components
from Python and supports custom CSS, so a Fiori-Horizon-like look (SAP 72 font
fallback, shell bar, object page, responsive table, KPI tiles) is achievable
without leaving Python. The backend stays UI-agnostic (services + models), so
a React front end remains possible if a customer demands it.

## ADR-003 AI enrichment through Claude Code headless mode, no API key
Confirmed 05-Sep-2026: a Claude subscription with Claude Code is available,
an API key is not. Claude Code's non-interactive print mode
(`claude -p "<prompt>" --output-format json`) is documented for exactly this
use - running from scripts and automation. The pipeline therefore gets a
`ClaudeCodeProvider` that shells out to the `claude` CLI per batch of objects,
parses the JSON reply, and stores results with the prompt version and hash.
Behaviour to design for:
- subscription usage limits apply, so batches are small, cached by content
  hash, and the job pauses (queues remaining objects) when the CLI reports a
  limit, resuming on the next run;
- the provider interface is the same one an `AnthropicProvider` (API key) or
  an on-prem model would implement, so a customer can switch without changes;
- the prompt-pack manual mode is kept as the last-resort fallback;
- redaction runs before any prompt is built, whatever the provider.
Docs: https://docs.claude.com/en/docs/claude-code/headless

## ADR-004 Metadata first, AI second
abapGit `.xml` files carry SAP short texts for objects, methods, function
modules, fields and messages. These are ingested and searchable before any AI
call, which makes the product useful on day one at a client with no AI access
and lowers the token bill when AI runs.

## ADR-005 Standard retrieval instead of hand-tuned scoring
BM25 (rank-bm25) for keywords, embeddings for meaning, Reciprocal Rank Fusion
to combine. No per-field magic numbers; the only lever is the weighted
repetition of fields when building the keyword document.

## ADR-006 Content-hash change detection at object level
Every object stores a hash over all of its files. Unchanged objects are
skipped by every pipeline step, which makes scheduled re-ingestion of large
systems affordable and keeps AI cost proportional to change, not size.

## ADR-007 Search ranking: type hints, compound splitting, coverage (v0.9.0)
Query words naming an object kind (interface, class, report, table, api...) are treated as hints that boost matching types/tags rather than as content terms, and are excluded from synonym expansion. Compound identifiers are split/joined against the corpus vocabulary (SALESORDER ~ sales order). Scores are scaled by how many of the typed words an object covers, with boosts for hits on the object name and SAP short text. Semantic fusion is weighted by backend quality. Reason: "salesorder interface" ranked an unrelated AIF interface first because "interface" pulled in AIF/inbound/proxy synonyms and "salesorder" never matched "sales order".

## ADR-008 model2vec as the default local embedding backend
Static embeddings (minishlab/potion-base-8M) need only numpy, install on Python 3.14 and download ~30 MB once. MiniLM remains preferred when sentence-transformers is present; TF-IDF/SVD stays as a zero-dependency fallback with the fallback reason recorded.

## ADR-009 Rules in Python, not YAML (for now)
Rules need context (statement windows, component boundaries, include merging) that a regex-per-YAML-line cannot express. Each rule is a small decorated function with id, category, severity, remediation and effort; a YAML layer for simple pattern rules can be added without changing the engine.

## ADR-010 Claude Code headless as the AI provider
`claude -p <instruction> --output-format json` with the prompt on stdin (Windows argv limit), run in an empty temp directory (no CLAUDE.md, no tool side effects). JSON output gives result text, usage and cost. Non-zero exit or is_error with limit/quota wording maps to a "limit" status that stops the batch loop; cached batches (by input hash + prompt version) are never re-sent.

## ADR-011 FSD analysis is deterministic first, AI second (v0.10.0)
Requirement extraction, matching (term coverage + embeddings + parsed references + component hits), coverage %, verdict and the build plan are computed without any AI so results are reproducible, explainable per requirement and available without a subscription. The knowledge base of standard building blocks lives in code (`atlas/fsd/knowledge.py`) as intents with keywords, blocks, data and S/4 remarks. AI is an optional review layer on top (`--ai` / "AI review" button) that receives the deterministic result and may disagree with it.

## ADR-012 Product name: ABAP Beacon (v0.11.0, revised)
A beacon shows what is already there and warns of hazards - exactly what the product does for a custom-code estate: find the object to reuse, light up S/4HANA and security risks, point the FSD in the right direction. "ABAP" in the name tells the SAP audience instantly what it is about; "Beacon" pairs naturally with the company name InfraBeat. Rejected: Zenith (good word, no link to the product), ABAP Atlas (ATLAS is the German customs system in the SAP world), CodeCompass (existing open-source project), ReuseIQ (too narrow). The Python package, database and CLI keep `atlas`; the display name is configurable (ATLAS_PRODUCT_NAME).

## ADR-013 Guardrails are policy-driven and applied twice
A single policy (data/config/guardrails.json) drives a strong egress mask that is always applied before any provider call, and an optional display mask for the UI and reports. Placeholders are stable pseudonyms so meaning survives. Rationale: demos and shared screens leaked customer names, system IDs and business keys that came from source comments, descriptions and FSD text.

## ADR-014 AI providers: one OpenAI-compatible client covers local and free options
Ollama, LM Studio, Groq, OpenRouter, Gemini, Mistral, OpenAI and custom gateways all speak /v1/chat/completions; one urllib-based client with presets keeps the dependency list unchanged. Local providers are recommended where data must not leave the machine; hosted free tiers are supported with 429 → pause/resume. Batch size adapts to the provider's context limits.

## ADR-015 A match needs specific evidence; names the FSD gives come first (v0.12.0)
Word overlap on integration vocabulary (system, API, BAPI, call, log, change, target, source) made every interface class a 15-50 % "partial" match for every interface FSD. A candidate can now only be partial or covered when it carries a specific signal: a table/BAPI/custom object the requirement names and the object really references, a matching method or function, a hit on the object name, or a distinctive matched term (used by less than a quarter of the repository). Non-requirement sections (testing, rollout, fallback, training, landscape, approvals) are skipped and nested bullets are merged with their "…based on:" parent, so requirement counts and effort reflect the specification, not the document length. The planner puts the BAPIs, tables and custom objects the FSD names first in every step (marked "named in the FSD", with the knowledge base's correction when a name does not exist in standard SAP), adds knowledge-base blocks only around them, names objects from the business topic of the dominant intent (ZCL_BP_CHANGE_SYNC) never from the title (which may contain a customer name), and lists design alternatives (standard replication, released OData API, bgRFC) separately so the ABAPer can challenge the FSD before building.

## ADR-016 Guardrails detect names in the documents they are asked to protect (v0.12.0)
The term list only protected names it had been told about, and every new FSD brings a new customer. Uploaded documents are scanned (document-control fields, "<X> System" / "from <X> to <Y>" phrases, organisation suffixes, unknown acronyms, acronyms embedded in Z-object names, author fields) and the candidates are stored with the analysis, masked immediately in title, list, report and AI prompt, and offered for one-click addition to the permanent list. Detection is conservative and every candidate is visible, so a false positive costs one click while a missed name would have leaked. The scan can be switched off in the policy (`auto_detect_names`).

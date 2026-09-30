# FSD analysis - FSD - Purchase Order Approval Workflow with Email Notifications

**Verdict: NEW DEVELOPMENT - nothing in the repository covers this FSD meaningfully. Follow the build plan below.**

- Weighted coverage by existing objects: **0.0%**
- Requirements: 12 (0 covered · 0 partial · 12 missing)
- Estimated remaining effort: **87.6 h** (design + unit tests included)
- Module: MM

> Purchase orders above a value threshold must be approved by the cost centre manager and, above a second threshold, by the finance controller before they can be sent to the supplier. Today approvals are collected by e-mail outside SAP and the PO is released manually in ME29N.

## Feasibility and complexity

**Feasibility: Feasible** · complexity **M** · FSD quality **75/100** · classification **W - Workflow** · estimate confidence **high** (100 %)

**Not specified in the FSD**
- expected volumes and response-time / SLA expectations

**Complexity drivers:** 12 detailed statements; 9 distinct SAP topics; workflow with agent determination and deadlines

**FSD quality:** covers authorization, error handling, trigger / scheduling, field mapping; missing volumes / performance, validation rules, acceptance / test data, named SAP objects; 12 of 12 detailed statements are testable (shall/must/will or a named SAP object); 0 use open wording.

**Clarification questions for the functional consultant**
1. Please specify expected volumes and response-time / SLA expectations.
2. Who are the approvers per level (org unit, role, amount limit) and what happens on deadline (escalate / auto-approve / reject)?

## Development plan - what to build

**Solution pattern:** SAP Business Workflow (flexible workflow scenario) + approval class + history report  
_The FSD describes approvals, work items, escalation and rejection - that is a workflow, not a report._

Each step is one piece of work for the ABAPer. The FSD statements it addresses are listed under it, and every BAPI, table or class appears in the step where it is first needed - once.

### 1. Workflow trigger
Raise the workflow from the document's change event (BAdI / class event on create-change) when the threshold condition is met; read thresholds and approvers from the configuration table; deadline monitoring for escalation.

Building blocks:
- `SAP_WAPI_START_WORKFLOW` (FM): Start a workflow template from ABAP
- `SAP_WAPI_CREATE_EVENT / SWE_EVENT_CREATE` (FM): Raise business object events (BOR/class)
- `Flexible Workflow (SWDD_SCENARIO, Manage Workflows app)` (pattern): S/4: configurable approval scenarios with My Inbox
- `ABAP class with IF_WORKFLOW` (pattern): Class-based workflow objects instead of BOR
- `SWWWIHEAD / SWW_CONT` (table): Work items and container
- `BAPI_PO_RELEASE` (BAPI): Release a PO with a release code

Addresses 4 FSD statement(s):
- R1 (processing): Purchase orders above a value threshold must be approved by the cost centre manager and, above a second threshold, by the finance controller before they can be sent to the supplier
- R2 (processing): When a purchase order is created or changed and its net value exceeds the threshold, the system shall start an approval workflow automatically
- R3 (data_model): The thresholds and the approver determination (per purchasing organisation and cost centre) shall be maintained in a custom configuration table
- R4 (output): The first approver shall receive a work item in the SAP inbox and an e-mail notification with the PO details and a link to approve or reject

### 2. Selection screen / entry point
SELECT-OPTIONS and PARAMETERS per the FSD with OBLIGATORY where required, defaults in INITIALIZATION, validations in AT SELECTION-SCREEN. Keep everything variant-capable for the background run.

Building blocks:
- `SELECT-OPTIONS / PARAMETERS` (pattern): Selection screen with OBLIGATORY, default values via INITIALIZATION
- `AT SELECTION-SCREEN` (pattern): Validations with MESSAGE ... TYPE 'E'
- `TVARVC / RS_VARIANT_CONTENTS` (FM): Variables and variants for background runs

### 3. Authorization check
AUTHORITY-CHECK before any data access; per org unit in the selection. Reject early with a clear message.

Building blocks:
- `AUTHORITY-CHECK OBJECT` (pattern): Check F_BKPF_BUK (company code), V_VBAK_VKO (sales org), M_BEST_EKO (purchasing org), S_TCODE etc. before data access
- `SU21 / SU24` (tcode): Custom authorization object Z_... if no standard object fits

Addresses 1 FSD statement(s):
- R12 (authorization): Only users with the approver role for the purchasing organisation may approve; authorization must be checked in the workflow task and in the report

### 4. Configuration / custom table
Create the Z table(s) the FSD asks for (MANDT key, data elements, delivery class C) with an SM30 maintenance view; read them once at start.

Building blocks:
- `SE11 table + SM30 maintenance generator (or SE54)` (pattern): Custom table with delivery class C/A and a maintenance view
- `Table Maintenance via Fiori Custom Business Object (CBO)` (pattern): Key-user alternative in S/4
- `CHANGEDOCUMENT_* ` (FM): Audit changes of the table
- `CHANGEDOCUMENT_OPEN/MULTIPLE_CASE/CLOSE` (FM): Write change documents for Z tables (SCDO)

### 5. Data retrieval
Read with ABAP SQL / CDS in one pass (no SELECT in LOOP), FOR ALL ENTRIES guarded by an emptiness check, only the fields needed. Tables/views: EKKO (FRGKE, FRGZU, FRGGR, FRGSX), T16FS, T16FV.

Building blocks:
- `BAPI_PO_RESET_RELEASE` (BAPI): Reject / reset release
- `BAPI_PO_GETRELINFO` (BAPI): Read release status and strategy
- `ME_REL_STRATEGIE_EKKO` (FM): Determine release strategy

### 6. Business logic and validations
One method per rule in the FSD (validations return BAPIRET2 / raise typed exceptions, never MESSAGE inside the class). Implement: R1 Purchase orders above a value threshold must be approved by the cost c…; R2 When a purchase order is created or changed and its net value exceeds …; R5 On approval the PO shall be released via the release strategy (release…; R7 If the approver does not act within 2 working days the work item shall…; R8 The system shall record every approval decision with user, timestamp a….

Building blocks:
- `Value help / conversion exits` (pattern): CONVERSION_EXIT_ALPHA_INPUT for numeric keys
- `Custom exception / BAPIRET2` (pattern): Return a typed error, do not MESSAGE inside API classes

Addresses 3 FSD statement(s):
- R5 (processing): On approval the PO shall be released via the release strategy (release code per level)
- R7 (processing): If the approver does not act within 2 working days the work item shall escalate to the approver's substitute
- R8 (processing): The system shall record every approval decision with user, timestamp and comment for audit

### 7. Posting / integration
Call the standard BAPI/API, evaluate RETURN (E/A = failure → BAPI_TRANSACTION_ROLLBACK), COMMIT once at the end; map custom fields via extension structures; log request/response.

Building blocks:
- `Flexible Workflow for Purchase Orders (WS20000075 / SWF_FLEX)` (pattern): S/4 flexible workflow with scenario 'Purchase Order' instead of classic release-strategy workflow

### 8. Output
ALV via CL_SALV_TABLE (layout, totals, Excel export come free); e-mail via CL_BCS with the list converted by CL_BCS_CONVERT; when running in background skip the display and send.

Building blocks:
- `CL_SALV_TABLE` (class): ALV grid with layout save, totals, sort, filter, export to Excel built in
- `CL_GUI_ALV_GRID` (class): When editable cells or custom events are required
- `CDS + Fiori Elements List Report` (pattern): S/4 alternative: analytical CDS with @UI annotations, no ABAP UI
- `CL_BCS` (class): Send e-mail with body and attachments (CL_DOCUMENT_BCS, CL_CAM_ADDRESS_BCS); commit and SOST
- `CL_BCS_CONVERT` (class): Convert internal tables to XLS/CSV attachments
- `CL_GUI_FRONTEND_SERVICES` (class): GUI upload/download (presentation server)

Addresses 3 FSD statement(s):
- R6 (output): On rejection the PO shall be blocked, the requester shall be notified by e-mail with the rejection reason and the workflow ends
- R9 (output): An approval history report shall display all POs with their approval steps, decision, approver and time taken, with a selection by purchasing organisation, date range and PO number
- R10 (output): The report must allow download to Excel

### 9. Error handling and application log
Collect all messages, write to the application log (SLG1 object/sub-object) and return/display them; retries for technical failures where the FSD asks for them.

Building blocks:
- `BAL_LOG_CREATE / BAL_LOG_MSG_ADD / BAL_DB_SAVE` (FM): Application log (SLG1) with object/sub-object from SLG0
- `Custom exception class (CX_STATIC_CHECK)` (pattern): Raise typed exceptions with T100 messages
- `BAPIRET2` (pattern): Return messages from APIs

Addresses 1 FSD statement(s):
- R11 (error_handling): Workflow errors shall be written to the application log and the MM support team must be notified by e-mail

### 10. Unit tests and handover
ABAP Unit for validations and mapping (test doubles for the BAPI calls); document the object list, transport and job variants.

## FSD statements one by one

Every sentence, bullet and table row of the specification that describes what the solution must do, in document order. *Scope* rows summarise the detailed rows below them and carry no effort of their own.

| # | Kind | Statement in the FSD | Existing code | Best match | Conf. | Addressed by | Effort h |
|---|---|---|---|---|---|---|---|
| R1 | processing | Purchase orders above a value threshold must be approved by the cost centre manager and, above a second threshold, by the finance controller before they can be sent to the supplier | missing | - | - | New development - see plan step 1. Workflow trigger. | 8.0 |
| R2 | processing | When a purchase order is created or changed and its net value exceeds the threshold, the system shall start an approval workflow automatically | missing | - | - | New development - see plan step 1. Workflow trigger. | 8.0 |
| R3 | data_model | The thresholds and the approver determination (per purchasing organisation and cost centre) shall be maintained in a custom configuration table | missing | - | - | New development - see plan step 1. Workflow trigger. | 4.0 |
| R4 | output | The first approver shall receive a work item in the SAP inbox and an e-mail notification with the PO details and a link to approve or reject | missing | - | - | New development - see plan step 1. Workflow trigger. | 4.0 |
| R5 | processing | On approval the PO shall be released via the release strategy (release code per level) | missing | - | - | New development - see plan step 6. Business logic and validations. | 8.0 |
| R6 | output | On rejection the PO shall be blocked, the requester shall be notified by e-mail with the rejection reason and the workflow ends | missing | - | - | New development - see plan step 8. Output. | 4.0 |
| R7 | processing | If the approver does not act within 2 working days the work item shall escalate to the approver's substitute | missing | - | - | New development - see plan step 6. Business logic and validations. | 8.0 |
| R8 | processing | The system shall record every approval decision with user, timestamp and comment for audit | missing | - | - | New development - see plan step 6. Business logic and validations. | 8.0 |
| R9 | output | An approval history report shall display all POs with their approval steps, decision, approver and time taken, with a selection by purchasing organisation, date range and PO number | missing | - | - | New development - see plan step 8. Output. | 4.0 |
| R10 | output | The report must allow download to Excel | missing | - | - | New development - see plan step 8. Output. | 4.0 |
| R11 | error_handling | Workflow errors shall be written to the application log and the MM support team must be notified by e-mail | missing | - | - | New development - see plan step 9. Error handling and application log. | 2.0 |
| R12 | authorization | Only users with the approver role for the purchasing organisation may approve; authorization must be checked in the workflow task and in the report | missing | - | - | New development - see plan step 3. Authorization check. | 1.0 |

## Objects

| Action | Object | Type | Purpose | Uses (BAPIs / FMs / classes / tables) | Plan steps |
|---|---|---|---|---|---|
| create | ZCL_MM_PURCHASE_ORDER_WF | Class | Workflow object class (IF_WORKFLOW): events, approver determination, release/reject methods | `SAP_WAPI_START_WORKFLOW`, `SAP_WAPI_CREATE_EVENT / SWE_EVENT_CREATE`, `SWWWIHEAD / SWW_CONT`, `BAPI_PO_RELEASE` | 1, 6 |
| create | WS9MPURC | Workflow template / flexible scenario | Approval steps, deadline (escalation) and notifications | - | - |
| create | ZMM_T_PURCHASE_ORDER_CFG | Table + SM30 view | Thresholds and approver determination | `SE11 table + SM30 maintenance view (SE54)`, `CHANGEDOCUMENT_* if the content must be audited` | 1, 4 |
| create | ZMM_T_PURCHASE_ORDER_LOG | Table | Approval decisions for audit (or use change documents) | `SE11 table + SM30 maintenance view (SE54)`, `CHANGEDOCUMENT_* if the content must be audited` | 9 |
| create | ZMM_PURCHASE_ORDER_HIST | Program (ALV) | Approval history report with selection screen and Excel export | `CL_SALV_TABLE`, `CL_GUI_ALV_GRID`, `CL_BCS`, `CL_BCS_CONVERT`, `CL_GUI_FRONTEND_SERVICES` | 8 |
| create | ZMM_PURCHASE_MSG | Message class | All user-facing messages (translatable) | `SE91 message class` | - |
| reuse | ZCL_ZCA_APPLOG | Class | Reuse for logging | - | - |
| reuse | ZCX_ZCA_EXCEPTION | Class | Reuse for exceptions | - | - |

Reusable utilities already in the repository: ZCL_ZCA_APPLOG (logging), ZCX_ZCA_EXCEPTION (exceptions)

## Effort estimate

- processing: 40.0 h
- data_model: 4.0 h
- output: 16.0 h
- error_handling: 2.0 h
- authorization: 1.0 h
- technical design & unit tests (20%): 12.6 h
- workflow template & agent determination: 12.0 h
- **Total: 87.6 h**

## S/4HANA and Clean Core notes

- Add MANDT, use data elements with domains, and a maintenance view instead of writing your own screen.
- Check at the start of the program and again per company code / org unit in the selection.
- Mail is only sent after COMMIT WORK and by the SCOT send job.
- Prefer flexible workflow scenarios; custom SWDD templates only when the scenario does not exist.
- Prefer the S/4 flexible workflow + My Inbox app over custom approval screens.
- Release codes are per release group/strategy; determine the next code from T16FS.
- Store the retry counter per item, not globally; never retry an application error (E/A message) blindly - only technical failures (timeout, connection).
- Use CL_SALV_TABLE; it gives Excel export, layout variants and totals without code.

## Test scenarios to cover

- R1: Purchase orders above a value threshold must be approved by the cost centre manager and, a
- R2: When a purchase order is created or changed and its net value exceeds the threshold, the s
- R5: On approval the PO shall be released via the release strategy (release code per level)
- R7: If the approver does not act within 2 working days the work item shall escalate to the app
- R8: The system shall record every approval decision with user, timestamp and comment for audit

_Generated by ABAP Beacon on 2026-09-12 17:51 UTC. Coverage and effort are estimates from deterministic matching; review before committing._
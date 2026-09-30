# FSD analysis - FSD - Vendor Ageing Report Enhancement

**Verdict: EXTEND - existing objects cover part of this FSD. Plan the development as an extension plus the gaps listed below.**

- Weighted coverage by existing objects: **39.7%**
- Requirements: 19 (4 covered · 6 partial · 9 missing)
- Estimated remaining effort: **40.1 h** (design + unit tests included)
- Module: FI

> Finance needs a vendor ageing analysis of open payables by due-date bucket per company code and vendor to support the weekly cash forecast. The existing vendor ageing report covers the basic ageing but the finance team requires additional buckets, a summary by vendor group and an automatic weekly e-mail of the result to the treasury distribution list. The report shall run every Monday at 06:00 as a background job with the e-mail option so the treasury team receives the ageing before the cash forecast meeting. The report must check the company code authorization (F_BKPF_BUK) for every selected 

## Existing objects to reuse

| Object | Type | Covers | Covered | Partial | Missing |
|---|---|---|---|---|---|
| ZRFI_VENDOR_AGEING_NEW_SEL | Program | 31.0% | R5, R8, R11 | R1, R2, R3, R9 | R4, R6, R7, R10, R12, R13, R14, R15, R16, R17, R18, R19 |
| ZRFI_VENDOR_AGEING | Program | 20.7% | R1, R8 | R2, R3, R6, R18 | R4, R5, R7, R9, R10, R11, R12, R13, R14, R15, R16, R17, R19 |
| ZRFI_VENDOR_AGEING_NEW_SUB | Program | 20.7% | - | R1, R2, R5, R6, R8, R9, R16, R18 | R3, R4, R7, R10, R11, R12, R13, R14, R15, R17, R19 |

> ZRFI_VENDOR_AGEING_NEW_SEL has only 48 lines of code - its coverage is based on its description; verify before relying on it.
> ZRFI_VENDOR_AGEING has only 12 lines of code - its coverage is based on its description; verify before relying on it.

## Feasibility and complexity

**Feasibility: Feasible** · complexity **M** · FSD quality **72/100** · classification **R - Report** · estimate confidence **medium** (71 %)

**Not specified in the FSD**
- expected volumes and response-time / SLA expectations

**Complexity drivers:** 17 detailed statements; 9 distinct SAP topics

**FSD quality:** covers authorization, error handling, trigger / scheduling, field mapping, named SAP objects; missing volumes / performance, validation rules, acceptance / test data; 12 of 17 detailed statements are testable (shall/must/will or a named SAP object); 0 use open wording.

**Clarification questions for the functional consultant**
1. Please specify expected volumes and response-time / SLA expectations.

## FSD statements one by one

Every sentence, bullet and table row of the specification that describes what the solution must do, in document order. *Scope* rows summarise the detailed rows below them and carry no effort of their own.

| # | Kind | Statement in the FSD | Existing code | Best match | Conf. | Addressed by | Effort h |
|---|---|---|---|---|---|---|---|
| R1 | scope | Finance needs a vendor ageing analysis of open payables by due-date bucket per company code and vendor to support the weekly cash forecast | covered | ZRFI_VENDOR_AGEING | 0.62 | Scope statement - realised by the plan as a whole, no separate effort. Note: ZRFI_VENDOR_AGEING has open findings S4-002, SEC-003 - address while touching it. | 0.0 |
| R2 | scope | The existing vendor ageing report covers the basic ageing but the finance team requires additional buckets, a summary by vendor group and an automatic weekly e-mail of the result to the treasury distribution list | missing | - | - | Scope statement - realised by the plan as a whole, no separate effort. | 0.0 |
| R3 | selection | Company code (BUKRS) as mandatory select-option | partial | ZRFI_VENDOR_AGEING_NEW_SEL | 0.40 | Extend ZRFI_VENDOR_AGEING_NEW_SEL: add selection field(s) BUKRS and pass them into the data retrieval. Note: ZRFI_VENDOR_AGEING_NEW_SEL has open findings S4-001, S4-001 - address while touching it. See plan step 1. Selection screen / entry point. | 0.6 |
| R4 | selection | Vendor number (LIFNR) as optional select-option | partial | ZFIST_VENDSUMMREP | 0.45 | Extend ZFIST_VENDSUMMREP: add selection field(s) LIFNR and pass them into the data retrieval. See plan step 1. Selection screen / entry point. | 0.6 |
| R5 | selection | Key date for the ageing calculation, defaulted to today | covered | ZRFI_VENDOR_AGEING_NEW_SEL | 0.61 | Reuse ZRFI_VENDOR_AGEING_NEW_SEL. Verify the behaviour matches: "Key date for the ageing calculation, defaulted to today". Note: ZRFI_VENDOR_AGEING_NEW_SEL has open findings S4-001, S4-001 - address while touching it. | 0.1 |
| R6 | selection | Ageing bucket definition (0-30, 31-60, 61-90, 91-180, above 180 days) as parameters so the buckets can be changed without development | partial | ZRFI_VENDOR_AGEING | 0.38 | Extend ZRFI_VENDOR_AGEING: add selection field(s) per the FSD and pass them into the data retrieval. See plan step 1. Selection screen / entry point. | 0.6 |
| R7 | selection | Checkbox to send the result by e-mail instead of displaying it, for the background run | missing | - | - | New development - see plan step 1. Selection screen / entry point. | 1.0 |
| R8 | processing | The report shall read vendor open items (BSIK / ACDOCA) for the selected company codes as of the key date | covered | ZRFI_VENDOR_AGEING_NEW_SEL | 0.80 | Reuse ZRFI_VENDOR_AGEING_NEW_SEL. Verify the behaviour matches: "The report shall read vendor open items (BSIK / ACDOCA) for the selected company codes as of the key date". Already references BSIK. Note: ZRFI_VENDOR_AGEING_NEW_SEL has open findings S4-001, S4-001 - address while touching it. | 1.2 |
| R9 | processing | The net due date shall be calculated from the baseline date and payment terms and each item assigned to an ageing bucket | partial | ZRFI_VENDOR_AGEING_NEW_SEL | 0.42 | Extend ZRFI_VENDOR_AGEING_NEW_SEL: add the logic (new method / form) implementing "The net due date shall be calculated from the baseline date and payment terms and each item assigned to an ag…". See plan step 4. Business logic and validations. | 4.4 |
| R10 | output | Amounts shall be shown in local currency and in document currency; the local currency total per bucket shall be calculated | missing | - | - | New development - see plan step 6. Output. | 4.0 |
| R11 | output | Vendor name and vendor group shall be read from the vendor master (LFA1) and a subtotal per vendor group shall be provided | covered | ZRFI_VENDOR_AGEING_NEW_SEL | 0.71 | Reuse ZRFI_VENDOR_AGEING_NEW_SEL. Verify the behaviour matches: "Vendor name and vendor group shall be read from the vendor master (LFA1) and a subtotal per vendor group shal…". Already references LFA1. Note: ZRFI_VENDOR_AGEING_NEW_SEL has open findings S4-001, S4-001 - address while touching it. | 0.6 |
| R12 | output | Items with a payment block must be shown in a separate column | missing | - | - | New development - see plan step 6. Output. | 4.0 |
| R13 | output | The result shall be displayed as an ALV grid with layout variants, totals and subtotals by vendor group | partial | ZRFI_VENDOR_AGEING_NEW_TOP | 0.41 | Extend ZRFI_VENDOR_AGEING_NEW_TOP: add the output element(s) described (column/total/attachment) - The result shall be displayed as an ALV grid with layout variants, totals and subtotals by vendor group. See plan step 6. Output. | 2.2 |
| R14 | output | The user must be able to download the list to Excel | missing | - | - | New development - see plan step 6. Output. | 4.0 |
| R15 | output | When the e-mail checkbox is set, the list shall be sent as an Excel attachment to the treasury distribution list maintained in a custom table | missing | - | - | New development - see plan step 6. Output. | 4.0 |
| R16 | scheduling | The report shall run every Monday at 06:00 as a background job with the e-mail option so the treasury team receives the ageing before the cash forecast meeting | missing | - | - | New development - see plan step 8. Scheduling. | 2.0 |
| R17 | authorization | The report must check the company code authorization (F_BKPF_BUK) for every selected company code | missing | - | - | New development - see plan step 2. Authorization check. | 1.0 |
| R18 | error_handling | If no open items are found for the selection an information message shall be issued | partial | ZRFI_VENDOR_AGEING | 0.45 | Extend ZRFI_VENDOR_AGEING: route messages through the existing log/return handling - If no open items are found for the selection an information message shall be issued. See plan step 7. Error handling and application log. | 1.1 |
| R19 | error_handling | Failures in e-mail sending must be written to the application log | missing | - | - | New development - see plan step 7. Error handling and application log. | 2.0 |

## Development plan - what to build

**Solution pattern:** ALV report (CL_SALV_TABLE) with e-mail/background mode + configuration table  
_Output-heavy requirements with a scheduled run: one report that displays online and sends in background._

Each step is one piece of work for the ABAPer. The FSD statements it addresses are listed under it, and every BAPI, table or class appears in the step where it is first needed - once.

### 1. Selection screen / entry point
SELECT-OPTIONS and PARAMETERS per the FSD with OBLIGATORY where required, defaults in INITIALIZATION, validations in AT SELECTION-SCREEN. Keep everything variant-capable for the background run.
- Already available: **ZRFI_VENDOR_AGEING_NEW_SEL** - reuse instead of rewriting.

Building blocks:
- `SELECT-OPTIONS / PARAMETERS` (pattern): Selection screen with OBLIGATORY, default values via INITIALIZATION
- `AT SELECTION-SCREEN` (pattern): Validations with MESSAGE ... TYPE 'E'
- `TVARVC / RS_VARIANT_CONTENTS` (FM): Variables and variants for background runs

Addresses 5 FSD statement(s):
- R3 (selection): Company code (BUKRS) as mandatory select-option
- R4 (selection): Vendor number (LIFNR) as optional select-option
- R5 (selection): Key date for the ageing calculation, defaulted to today
- R6 (selection): Ageing bucket definition (0-30, 31-60, 61-90, 91-180, above 180 days) as parameters so the buckets can be changed without development
- R7 (selection): Checkbox to send the result by e-mail instead of displaying it, for the background run

### 2. Authorization check
AUTHORITY-CHECK before any data access; per org unit in the selection. Reject early with a clear message.

Building blocks:
- `AUTHORITY-CHECK OBJECT` (pattern): Check F_BKPF_BUK (company code), V_VBAK_VKO (sales org), M_BEST_EKO (purchasing org), S_TCODE etc. before data access
- `SU21 / SU24` (tcode): Custom authorization object Z_... if no standard object fits

Addresses 1 FSD statement(s):
- R17 (authorization): The report must check the company code authorization (F_BKPF_BUK) for every selected company code

### 3. Data retrieval
Read with ABAP SQL / CDS in one pass (no SELECT in LOOP), FOR ALL ENTRIES guarded by an emptiness check, only the fields needed. Tables/views: ACDOCA, BSIK, BSIK/BSID (compat views in S/4), LFA1, LFA1/KNA1.
- Already available: **ZRFI_VENDOR_AGEING_NEW_SEL** - reuse instead of rewriting.

Building blocks:
- `ACDOCA` (table (named in the FSD)): Read/written per the FSD
- `BSIK` (table (named in the FSD)): Read/written per the FSD
- `LFA1` (table (named in the FSD)): Read/written per the FSD
- `I_OperationalAcctgDocItem / I_JournalEntryItem` (CDS): Released journal entry items - filter on open item management and clearing date

Addresses 1 FSD statement(s):
- R8 (processing): The report shall read vendor open items (BSIK / ACDOCA) for the selected company codes as of the key date

### 4. Business logic and validations
One method per rule in the FSD (validations return BAPIRET2 / raise typed exceptions, never MESSAGE inside the class). Implement: R9 The net due date shall be calculated from the baseline date and paymen….
- Already available: **ZRFI_VENDOR_AGEING_NEW_SEL** - reuse instead of rewriting.

Building blocks:
- `Value help / conversion exits` (pattern): CONVERSION_EXIT_ALPHA_INPUT for numeric keys
- `Custom exception / BAPIRET2` (pattern): Return a typed error, do not MESSAGE inside API classes

Addresses 1 FSD statement(s):
- R9 (processing): The net due date shall be calculated from the baseline date and payment terms and each item assigned to an ageing bucket

### 5. Posting / integration
Call the standard BAPI/API, evaluate RETURN (E/A = failure → BAPI_TRANSACTION_ROLLBACK), COMMIT once at the end; map custom fields via extension structures; log request/response.

Building blocks:
- `BAPI_BUPA_CREATE_FROM_DATA` (BAPI): Create BP (general role)
- `CVI_EI_INBOUND_MAIN` (FM): Create/change BP with vendor/customer roles (CVI) - the S/4 way
- `BAPI_BUPA_ADDRESS_ADD / BAPI_BUPA_BANKDETAIL_ADD` (BAPI): Address, bank details
- `API_BUSINESS_PARTNER` (pattern): Released OData API
- `I_Supplier / I_Customer / I_BusinessPartner` (CDS): Released views

### 6. Output
ALV via CL_SALV_TABLE (layout, totals, Excel export come free); e-mail via CL_BCS with the list converted by CL_BCS_CONVERT; when running in background skip the display and send.
- Already available: **ZRFI_VENDOR_AGEING_NEW_SEL** - reuse instead of rewriting.

Building blocks:
- `CL_SALV_TABLE` (class): ALV grid with layout save, totals, sort, filter, export to Excel built in
- `CL_GUI_ALV_GRID` (class): When editable cells or custom events are required
- `CDS + Fiori Elements List Report` (pattern): S/4 alternative: analytical CDS with @UI annotations, no ABAP UI
- `CL_BCS` (class): Send e-mail with body and attachments (CL_DOCUMENT_BCS, CL_CAM_ADDRESS_BCS); commit and SOST
- `CL_BCS_CONVERT` (class): Convert internal tables to XLS/CSV attachments
- `CL_GUI_FRONTEND_SERVICES` (class): GUI upload/download (presentation server)

Addresses 6 FSD statement(s):
- R10 (output): Amounts shall be shown in local currency and in document currency; the local currency total per bucket shall be calculated
- R11 (output): Vendor name and vendor group shall be read from the vendor master (LFA1) and a subtotal per vendor group shall be provided
- R12 (output): Items with a payment block must be shown in a separate column
- R13 (output): The result shall be displayed as an ALV grid with layout variants, totals and subtotals by vendor group
- R14 (output): The user must be able to download the list to Excel
- R15 (output): When the e-mail checkbox is set, the list shall be sent as an Excel attachment to the treasury distribution list maintained in a custom table

### 7. Error handling and application log
Collect all messages, write to the application log (SLG1 object/sub-object) and return/display them; retries for technical failures where the FSD asks for them.

Building blocks:
- `BAL_LOG_CREATE / BAL_LOG_MSG_ADD / BAL_DB_SAVE` (FM): Application log (SLG1) with object/sub-object from SLG0
- `Custom exception class (CX_STATIC_CHECK)` (pattern): Raise typed exceptions with T100 messages
- `BAPIRET2` (pattern): Return messages from APIs

Addresses 2 FSD statement(s):
- R18 (error_handling): If no open items are found for the selection an information message shall be issued
- R19 (error_handling): Failures in e-mail sending must be written to the application log

### 8. Scheduling
Variant with TVARVC/dynamic dates; job in SM36 (or Application Jobs catalogue in S/4); e-mail option forced in background.

Building blocks:
- `JOB_OPEN / JOB_SUBMIT / JOB_CLOSE` (FM): Create jobs programmatically
- `SM36 / SM37 with a variant` (tcode): Standard scheduling; keep the report variant-driven (TVARVC dates)
- `Application Jobs framework (SJOBREPO / Fiori Application Jobs)` (pattern): S/4 job catalogue entry + template

Addresses 1 FSD statement(s):
- R16 (scheduling): The report shall run every Monday at 06:00 as a background job with the e-mail option so the treasury team receives the ageing before the cash forecast meeting

### 9. Unit tests and handover
ABAP Unit for validations and mapping (test doubles for the BAPI calls); document the object list, transport and job variants.

### Building blocks the FSD names - and where they are used

| Named in the FSD | Kind | Note | Used in |
|---|---|---|---|
| `ACDOCA` | table | Read/written per the FSD | step 3 |
| `BSIK` | table | Read/written per the FSD | step 3 |
| `LFA1` | table | Read/written per the FSD | step 3 |

## Objects

| Action | Object | Type | Purpose | Uses (BAPIs / FMs / classes / tables) | Plan steps |
|---|---|---|---|---|---|
| extend | ZRFI_VENDOR_AGEING_NEW_SEL | Program | Covers 31.0% of the FSD (weighted); extend for the partial/missing requirements listed in the analysis. | - | - |
| reuse | ZCL_ZCA_APPLOG | Class | Reuse for logging | - | - |

Reusable utilities already in the repository: ZCL_ZCA_APPLOG (logging)

## Effort estimate

- selection: 2.9 h
- processing: 5.6 h
- output: 18.8 h
- scheduling: 2.0 h
- authorization: 1.0 h
- error_handling: 3.1 h
- technical design & unit tests (20%): 6.7 h
- **Total: 40.1 h**

## S/4HANA and Clean Core notes

- Add MANDT, use data elements with domains, and a maintenance view instead of writing your own screen.
- Ageing buckets: compute from ZFBDT + ZBD1T (net due date) - use function NET_DUE_DATE_GET.
- BSIK/BSID become compatibility views in S/4HANA; read ACDOCA or the CDS views.
- Check at the start of the program and again per company code / org unit in the selection.
- Dynamic dates (today, month start) via TVARVC variables or selection variables (D/T).
- Mail is only sent after COMMIT WORK and by the SCOT send job.
- Never create LFA1/KNA1 directly in S/4HANA - always through BP/CVI.
- Reuse an existing log wrapper class if the repository has one.

## Test scenarios to cover

- R8: The report shall read vendor open items (BSIK / ACDOCA) for the selected company codes as 
- R9: The net due date shall be calculated from the baseline date and payment terms and each ite

_Generated by ABAP Beacon on 2026-09-12 17:51 UTC. Coverage and effort are estimates from deterministic matching; review before committing._
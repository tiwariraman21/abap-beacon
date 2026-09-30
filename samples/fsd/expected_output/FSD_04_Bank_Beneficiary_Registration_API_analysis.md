# FSD analysis - FSD - Beneficiary Registration with <customer-737> API

**Verdict: REUSE - an existing object covers most of this FSD. Extend it for the partial/missing points instead of building new.**

- Weighted coverage by existing objects: **79.2%**
- Requirements: 12 (5 covered · 6 partial · 1 missing)
- Estimated remaining effort: **22.8 h** (design + unit tests included)
- Module: FI

> Before vendor payments can be transferred through <customer-737> host-to-host, each vendor's bank account must be registered as a beneficiary with the bank. The registration shall be triggered from SAP when a new vendor bank detail is created or changed.

## Existing objects to reuse

| Object | Type | Covers | Covered | Partial | Missing |
|---|---|---|---|---|---|
| ZCL_<customer-5188>_PAYEE_MGMT | Class | 72.9% | R1, R2, R3, R4, R7 | R5, R6, R8, R9 | R10, R11, R12 |
| ZAPI_AES128_BENE_REG | Program | 58.3% | R1, R2, R3 | R5, R6, R7, R8, R9 | R4, R10, R11, R12 |
| ZFI_BANK_API | Program | 27.1% | R2 | R1, R3, R6 | R4, R5, R7, R8, R9, R10, R11, R12 |


## Feasibility and complexity

**Feasibility: Feasible** · complexity **M** · FSD quality **75/100** · classification **I - Interface** · estimate confidence **high** (100 %)

**Not specified in the FSD**
- expected volumes and response-time / SLA expectations

**Complexity drivers:** 12 detailed statements; 2 integration statements; 1 external system(s) / boundaries; 9 distinct SAP topics

**FSD quality:** covers authorization, error handling, trigger / scheduling, validation rules; missing volumes / performance, field mapping, acceptance / test data, named SAP objects; 12 of 12 detailed statements are testable (shall/must/will or a named SAP object); 0 use open wording.

**Clarification questions for the functional consultant**
1. Please specify expected volumes and response-time / SLA expectations.

## FSD statements one by one

Every sentence, bullet and table row of the specification that describes what the solution must do, in document order. *Scope* rows summarise the detailed rows below them and carry no effort of their own.

| # | Kind | Statement in the FSD | Existing code | Best match | Conf. | Addressed by | Effort h |
|---|---|---|---|---|---|---|---|
| R1 | processing | Before vendor payments can be transferred through <customer-737> host-to-host, each vendor's bank account must be registered as a beneficiary with the bank | covered | ZCL_<customer-5188>_PAYEE_MGMT (REGISTER_BENEFICIARY) | 0.70 | Reuse ZCL_<customer-5188>_PAYEE_MGMT → REGISTER_BENEFICIARY. Verify the behaviour matches: "Before vendor payments can be transferred through <customer-737> host-to-host, each vendor's bank account must be…". Note: ZCL_<customer-5188>_PAYEE_MGMT has open findings CC-002, CC-003 - address while touching it. | 1.2 |
| R2 | processing | The registration shall be triggered from SAP when a new vendor bank detail is created or changed | covered | ZAPI_AES128_BENE_REG | 0.61 | Reuse ZAPI_AES128_BENE_REG. Verify the behaviour matches: "The registration shall be triggered from SAP when a new vendor bank detail is created or changed". Note: ZAPI_AES128_BENE_REG has open findings Q-008, Q-008 - address while touching it. | 1.2 |
| R3 | integration | The system shall build the beneficiary registration request from the vendor bank details (bank key, account number, IFSC, beneficiary name) and call the <customer-737> payee management REST API | covered | ZCL_<customer-5188>_PAYEE_MGMT | 0.64 | Reuse ZCL_<customer-5188>_PAYEE_MGMT. Verify the behaviour matches: "The system shall build the beneficiary registration request from the vendor bank details (bank key, account n…". Note: ZCL_<customer-5188>_PAYEE_MGMT has open findings CC-002, CC-003 - address while touching it. | 1.8 |
| R4 | validation | The request body must be encrypted with AES-128 and a checksum must be calculated as per the bank specification | covered | ZCL_<customer-5188>_PAYEE_MGMT (CALCULATE_CHECKSUM, ENCRYPT_REQUEST_BODY) | 0.83 | Reuse ZCL_<customer-5188>_PAYEE_MGMT → CALCULATE_CHECKSUM, ENCRYPT_REQUEST_BODY. Verify the behaviour matches: "The request body must be encrypted with AES-128 and a checksum must be calculated as per the bank specificati…". Note: ZCL_<customer-5188>_PAYEE_MGMT has open findings CC-002, CC-003 - address while touching it. | 0.4 |
| R5 | data_model | The response shall be decrypted and the bank's beneficiary status stored against the vendor bank detail in a custom table with timestamp | partial | ZCL_<customer-5188>_PAYEE_MGMT | 0.54 | Extend ZCL_<customer-5188>_PAYEE_MGMT: add the custom table / fields and read them in the existing flow - The response shall be decrypted and the bank's beneficiary status stored against the vendor bank detail in a…. See plan step 3. Configuration / custom table. | 2.2 |
| R6 | scheduling | Registration shall run automatically as a scheduled background job every hour for all pending vendor bank details | partial | ZAPI_AES128_BENE_REG | 0.41 | Extend ZAPI_AES128_BENE_REG: make the run variant-driven (TVARVC dates) so it can be scheduled - Registration shall run automatically as a scheduled background job every hour for all pending vendor bank det…. See plan step 9. Scheduling. | 1.1 |
| R7 | integration | The bank endpoint, client id and client secret must be stored securely in configuration, not in the program | partial | ZCL_<customer-5188>_PAYEE_MGMT | 0.59 | Extend ZCL_<customer-5188>_PAYEE_MGMT: the object currently has SEC-002 (Hard-coded URL or host name, line 94), SEC-002 (Hard-coded URL or host name, line 768) - move endpoint/credentials to SM59 / secure store as the FSD requires. Reuse ZCL_<customer-5188>_PAYEE_MGMT. Verify the behaviour matches: "The bank endpoint, client id and client secret must be stored securely in configuration, not in the program". See plan step 1. Integration entry point. | 3.8 |
| R8 | output | If the bank rejects the registration the vendor payment block shall be set and the treasury team notified by e-mail | partial | ZCL_<customer-5188>_PAYEE_MGMT | 0.43 | Extend ZCL_<customer-5188>_PAYEE_MGMT: add the output element(s) described (column/total/attachment) - If the bank rejects the registration the vendor payment block shall be set and the treasury team notified by…. See plan step 7. Output. | 2.2 |
| R9 | output | A monitoring report shall list all beneficiary registrations with status, bank response message and retry count, selectable by vendor, company code and date | partial | ZCL_<customer-5188>_PAYEE_MGMT | 0.43 | Extend ZCL_<customer-5188>_PAYEE_MGMT: add the output element(s) described (column/total/attachment) - A monitoring report shall list all beneficiary registrations with status, bank response message and retry cou…. See plan step 7. Output. | 2.2 |
| R10 | error_handling | All API calls and responses shall be logged in the application log (SLG1) | covered | ZCL_ZCA_APPLOG (MS_LOG_HDR, MT_LOG_HANDLE) | 0.72 | Reuse ZCL_ZCA_APPLOG → MS_LOG_HDR, MT_LOG_HANDLE. Verify the behaviour matches: "All API calls and responses shall be logged in the application log (SLG1)". Note: ZCL_ZCA_APPLOG has open findings S4-002, S4-002 - address while touching it. | 0.3 |
| R11 | error_handling | Technical failures (timeout, HTTP error) shall be retried up to three times | missing | - | - | New development - see plan step 8. Error handling and application log. | 2.0 |
| R12 | authorization | The report shall check authorization for the company code (F_LFA1_BUK) | partial | ZRFI_VENDOR_AGEING_NEW_SEL | 0.30 | Extend ZRFI_VENDOR_AGEING_NEW_SEL: add AUTHORITY-CHECK for the object named in the FSD before data access. See plan step 2. Authorization check. | 0.6 |

## Development plan - what to build

**Solution pattern:** Outbound integration class (CL_HTTP_CLIENT via SM59 destination) + configuration table + background job + monitoring ALV  
_The FSD consumes an external API: isolate the HTTP call, encryption and mapping in one class, keep endpoint and credentials in SM59/secure store, schedule it and give support a monitor._

Each step is one piece of work for the ABAPer. The FSD statements it addresses are listed under it, and every BAPI, table or class appears in the step where it is first needed - once.

### 1. Integration entry point
One class method per API operation: build request from SAP data, sign/encrypt, call via CL_HTTP_CLIENT with an SM59 destination (credentials there, not in code), parse the response into a typed structure.
- Already available: **ZCL_<customer-5188>_PAYEE_MGMT** - reuse instead of rewriting.

Building blocks:
- `RAP (Behaviour Definition + Service Definition/Binding)` (pattern): Preferred for new OData V4 services in S/4 (ABAP Cloud ready)
- `SEGW project + DPC_EXT / MPC_EXT classes` (pattern): OData V2 via Gateway Service Builder (classic)
- `CL_HTTP_CLIENT / CL_WEB_HTTP_CLIENT_MANAGER` (class): Outbound HTTP/REST calls with SM59 destination
- `/UI2/CL_JSON` (class): JSON serialisation/deserialisation
- `SXMB / Proxy classes (SPROXY)` (pattern): When SAP PI/PO or CPI sits in the middle

Addresses 2 FSD statement(s):
- R3 (integration): The system shall build the beneficiary registration request from the vendor bank details (bank key, account number, IFSC, beneficiary name) and call the <customer-737> payee management REST API
- R7 (integration): The bank endpoint, client id and client secret must be stored securely in configuration, not in the program

### 2. Authorization check
AUTHORITY-CHECK before any data access; per org unit in the selection. Reject early with a clear message.

Building blocks:
- `AUTHORITY-CHECK OBJECT` (pattern): Check F_BKPF_BUK (company code), V_VBAK_VKO (sales org), M_BEST_EKO (purchasing org), S_TCODE etc. before data access
- `SU21 / SU24` (tcode): Custom authorization object Z_... if no standard object fits

Addresses 1 FSD statement(s):
- R12 (authorization): The report shall check authorization for the company code (F_LFA1_BUK)

### 3. Configuration / custom table
Create the Z table(s) the FSD asks for (MANDT key, data elements, delivery class C) with an SM30 maintenance view; read them once at start.

Building blocks:
- `SE11 table + SM30 maintenance generator (or SE54)` (pattern): Custom table with delivery class C/A and a maintenance view
- `Table Maintenance via Fiori Custom Business Object (CBO)` (pattern): Key-user alternative in S/4
- `CHANGEDOCUMENT_* ` (FM): Audit changes of the table
- `CHANGEDOCUMENT_OPEN/MULTIPLE_CASE/CLOSE` (FM): Write change documents for Z tables (SCDO)

Addresses 1 FSD statement(s):
- R5 (data_model): The response shall be decrypted and the bank's beneficiary status stored against the vendor bank detail in a custom table with timestamp

### 4. Data retrieval
Read with ABAP SQL / CDS in one pass (no SELECT in LOOP), FOR ALL ENTRIES guarded by an emptiness check, only the fields needed. Tables/views: BNKA, BUT0BK, LFBK.
- Already available: **ZCL_<customer-5188>_PAYEE_MGMT** - reuse instead of rewriting.

Building blocks:
- `BAPI_BANK_CREATE / BAPI_BANK_GETDETAIL` (BAPI): Bank master
- `BAPI_BUPA_BANKDETAIL_ADD` (BAPI): Add bank details to a business partner (vendor bank data in S/4)
- `READ_BANKDETAILS / BANK_ACCOUNT_CHECK` (FM): Validate bank data

### 5. Business logic and validations
One method per rule in the FSD (validations return BAPIRET2 / raise typed exceptions, never MESSAGE inside the class). Implement: R1 Before vendor payments can be transferred through <customer-737> host-to-ho…; R2 The registration shall be triggered from SAP when a new vendor bank de…; R4 The request body must be encrypted with AES-128 and a checksum must be….
- Already available: **ZCL_<customer-5188>_PAYEE_MGMT** - reuse instead of rewriting.

Building blocks:
- `SELECT SINGLE ... / line_exists( )` (pattern): Existence checks against master/transaction data
- `Value help / conversion exits` (pattern): CONVERSION_EXIT_ALPHA_INPUT for numeric keys
- `Custom exception / BAPIRET2` (pattern): Return a typed error, do not MESSAGE inside API classes

Addresses 3 FSD statement(s):
- R1 (processing): Before vendor payments can be transferred through <customer-737> host-to-host, each vendor's bank account must be registered as a beneficiary with the bank
- R2 (processing): The registration shall be triggered from SAP when a new vendor bank detail is created or changed
- R4 (validation): The request body must be encrypted with AES-128 and a checksum must be calculated as per the bank specification

### 6. Posting / integration
Call the standard BAPI/API, evaluate RETURN (E/A = failure → BAPI_TRANSACTION_ROLLBACK), COMMIT once at the end; map custom fields via extension structures; log request/response.
- Already available: **ZCL_<customer-5188>_PAYEE_MGMT** - reuse instead of rewriting.

Building blocks:
- `CL_SEC_SXML_WRITER / CL_ABAP_MESSAGE_DIGEST` (class): AES encryption / checksums if the bank API requires them

### 7. Output
ALV via CL_SALV_TABLE (layout, totals, Excel export come free); e-mail via CL_BCS with the list converted by CL_BCS_CONVERT; when running in background skip the display and send.

Building blocks:
- `CL_SALV_TABLE` (class): ALV grid with layout save, totals, sort, filter, export to Excel built in
- `CL_GUI_ALV_GRID` (class): When editable cells or custom events are required
- `CDS + Fiori Elements List Report` (pattern): S/4 alternative: analytical CDS with @UI annotations, no ABAP UI
- `CL_BCS` (class): Send e-mail with body and attachments (CL_DOCUMENT_BCS, CL_CAM_ADDRESS_BCS); commit and SOST
- `CL_BCS_CONVERT` (class): Convert internal tables to XLS/CSV attachments
- `CL_GUI_FRONTEND_SERVICES` (class): GUI upload/download (presentation server)

Addresses 2 FSD statement(s):
- R8 (output): If the bank rejects the registration the vendor payment block shall be set and the treasury team notified by e-mail
- R9 (output): A monitoring report shall list all beneficiary registrations with status, bank response message and retry count, selectable by vendor, company code and date

### 8. Error handling and application log
Collect all messages, write to the application log (SLG1 object/sub-object) and return/display them; retries for technical failures where the FSD asks for them.
- Already available: **ZCL_ZCA_APPLOG** - reuse instead of rewriting.

Building blocks:
- `BAL_LOG_CREATE / BAL_LOG_MSG_ADD / BAL_DB_SAVE` (FM): Application log (SLG1) with object/sub-object from SLG0
- `Custom exception class (CX_STATIC_CHECK)` (pattern): Raise typed exceptions with T100 messages
- `BAPIRET2` (pattern): Return messages from APIs

Addresses 2 FSD statement(s):
- R10 (error_handling): All API calls and responses shall be logged in the application log (SLG1)
- R11 (error_handling): Technical failures (timeout, HTTP error) shall be retried up to three times

### 9. Scheduling
Variant with TVARVC/dynamic dates; job in SM36 (or Application Jobs catalogue in S/4); e-mail option forced in background.

Building blocks:
- `JOB_OPEN / JOB_SUBMIT / JOB_CLOSE` (FM): Create jobs programmatically
- `SM36 / SM37 with a variant` (tcode): Standard scheduling; keep the report variant-driven (TVARVC dates)
- `Application Jobs framework (SJOBREPO / Fiori Application Jobs)` (pattern): S/4 job catalogue entry + template

Addresses 1 FSD statement(s):
- R6 (scheduling): Registration shall run automatically as a scheduled background job every hour for all pending vendor bank details

### 10. Unit tests and handover
ABAP Unit for validations and mapping (test doubles for the BAPI calls); document the object list, transport and job variants.

## Objects

| Action | Object | Type | Purpose | Uses (BAPIs / FMs / classes / tables) | Plan steps |
|---|---|---|---|---|---|
| extend | ZCL_<customer-5188>_PAYEE_MGMT | Class | Covers 72.9% of the FSD (weighted); extend for the partial/missing requirements listed in the analysis. | `BAPI_BANK_CREATE / BAPI_BANK_GETDETAIL`, `BAPI_BUPA_BANKDETAIL_ADD`, `READ_BANKDETAILS / BANK_ACCOUNT_CHECK`, `CL_SEC_SXML_WRITER / CL_ABAP_MESSAGE_DIGEST` | 4, 5, 6 |
| extend | ZAPI_AES128_BENE_REG | Program | Covers 58.3% of the FSD (weighted); extend for the partial/missing requirements listed in the analysis. | - | - |
| reuse | ZCL_ZCA_APPLOG | Class | Reuse for logging | - | - |
| reuse | ZCX_ZCA_EXCEPTION | Class | Reuse for exceptions | - | - |

Reusable utilities already in the repository: ZCL_ZCA_APPLOG (logging), ZCX_ZCA_EXCEPTION (exceptions)

## Effort estimate

- processing: 2.4 h
- integration: 5.6 h
- validation: 0.4 h
- data_model: 2.2 h
- scheduling: 1.1 h
- output: 4.4 h
- error_handling: 2.3 h
- authorization: 0.6 h
- technical design & unit tests (20%): 3.8 h
- **Total: 22.8 h**

## S/4HANA and Clean Core notes

- Add MANDT, use data elements with domains, and a maintenance view instead of writing your own screen.
- Check at the start of the program and again per company code / org unit in the selection.
- Dynamic dates (today, month start) via TVARVC variables or selection variables (D/T).
- Keep the API class free of UI logic; return BAPIRET2-style messages; log every call (application log).
- Mail is only sent after COMMIT WORK and by the SCOT send job.
- Reuse an existing log wrapper class if the repository has one.
- Store the retry counter per item, not globally; never retry an application error (E/A message) blindly - only technical failures (timeout, connection).
- Vendor bank details are maintained on the Business Partner in S/4 (BUT0BK); use BP APIs, not LFBK writes.

## Test scenarios to cover

- R1: Before vendor payments can be transferred through <customer-737> host-to-host, each vendor's ba
- R2: The registration shall be triggered from SAP when a new vendor bank detail is created or c
- R3: The system shall build the beneficiary registration request from the vendor bank details (
- R4: The request body must be encrypted with AES-128 and a checksum must be calculated as per t
- R7: The bank endpoint, client id and client secret must be stored securely in configuration, n

_Guardrails: 1 name(s) detected in the document were masked in this report._

_Generated by ABAP Beacon on 2026-09-12 17:51 UTC. Coverage and effort are estimates from deterministic matching; review before committing._
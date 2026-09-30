# FSD analysis - Business Partner Change from <customer-3513> to <customer-7938> System Using API/BAPI

**Verdict: NEW DEVELOPMENT - nothing in the repository covers this FSD meaningfully. Follow the build plan below.**

- Weighted coverage by existing objects: **0.0%**
- Requirements: 35 (0 covered · 0 partial · 35 missing)
- Estimated remaining effort: **216.2 h** (design + unit tests included)
- Module: BP

> This document defines the functional requirements for changing Business Partner (BP) master data in one SAP S/4HANA system and synchronizing or transferring it to another SAP S/4HANA system using standard SAP APIs and BAPIs. The objective is to ensure accurate, secure, and real-time or batch-based data synchronization while maintaining data integrity and system alignment.

## Feasibility and complexity

**Feasibility: Feasible with changes** · complexity **L** · FSD quality **64/100** · classification **I - Interface** · estimate confidence **high** (93 %)

**Changes needed**
- The FSD names `BAPI_BUPA_CHANGE`, which does not exist in standard SAP - the change BAPIs are per data area: BAPI_BUPA_CENTRAL_CHANGE, BAPI_BUPA_ADDRESS_CHANGE, BAPI_BUPA_BANKDETAIL_CHANGE
- The FSD names `BAPI_BUPA_GETDETAIL`, which does not exist in standard SAP - Use BAPI_BUPA_CENTRAL_GETDETAIL / BAPI_BUPA_ADDRESSES_GET / BAPI_BUPA_ROLES_GET (no single GETDETAIL exists)
- The FSD names `BAPI_BUPA_GETLIST`, which does not exist in standard SAP - Use BAPI_BUPA_SEARCH_2 or a CDS/SELECT on BUT000 with change date
- The FSD names `BAPI_BUPA_ROLE_ASSIGN`, which does not exist in standard SAP - use BAPI_BUPA_ROLE_ADD_2 (check with BAPI_BUPA_ROLE_EXISTENCE_CHECK first)
- R14: remote call inside the save / real-time path - decouple with bgRFC, qRFC or a queue so a network failure never blocks the user

**Risks to raise**
- Same keys in two systems need external numbering or key mapping - confirm before design
- SAP standard replication (DRF / MDG / SOA) covers this scenario - custom build must justify why it is not used

**Not specified in the FSD**
- expected volumes and response-time / SLA expectations

**Complexity drivers:** 30 detailed statements; 10 integration statements; 3 external system(s) / boundaries; 13 distinct SAP topics; 1 custom object(s) named; 6 field-mapping rows; cross-system replication with retry and reconciliation; federated authentication (OAuth / SAML / certificates)

**FSD quality:** covers authorization, error handling, trigger / scheduling, field mapping, validation rules, named SAP objects; missing volumes / performance, acceptance / test data; 9 of 30 detailed statements are testable (shall/must/will or a named SAP object); 4 use open wording.

**Clarification questions for the functional consultant**
1. Please specify expected volumes and response-time / SLA expectations.
2. The FSD names APIs that do not exist in standard SAP (BAPI_BUPA_CHANGE, BAPI_BUPA_GETDETAIL, BAPI_BUPA_GETLIST, BAPI_BUPA_ROLE_ASSIGN) - confirm the replacements proposed in the plan are acceptable.
3. R14: is a real-time call acceptable if it is asynchronous (queued within seconds), or must the user wait for the target's confirmation?
4. R6 uses open wording ("etc") - please list the exact values / cases: "When a Business Partner is changed in the source system (update of name, address, roles, e"
5. R9 uses open wording ("appropriate") - please list the exact values / cases: "BP Name \| Name1/Name2 \| Map to appropriate name fields"
6. R17 uses open wording ("appropriate") - please list the exact values / cases: "Users/systems must have appropriate authorizations in both source and target systems"
7. R35 uses open wording ("correctly") - please list the exact values / cases: "If custom fields exist in the BP, ensure they are: Available in both systems; Mapped corre"
8. Should the standard replication (DRF / MDG / SOA) be evaluated first, and why is it out of scope?
9. Are BP numbers identical in both systems (external numbering), or is a key mapping needed?

## Development plan - what to build

**Solution pattern:** Change replication: trigger (BAdI / change documents) → outbound API class (proxy / OData) → status table with retry job → reconciliation report  
_The FSD keeps master data in sync between two systems: detect the change, call the target's standard API, make failures visible and retryable, and prove consistency with a reconciliation report._

### Before building - design alternatives to raise
- Standard before custom: DRF replication model for BP (DRFOUT) or MDG-BP with the SOA service BusinessPartnerSUITEBulkReplicateRequest gives filters, change pointers, monitoring and key mapping without ABAP - ask why it is out of scope.
- If both systems are S/4HANA 1709+, the released OData API API_BUSINESS_PARTNER on the target (PATCH) is simpler to consume than a SOAP proxy and is ABAP-Cloud compatible.
- Do not call the target synchronously inside the BP save: record the change and send from a bgRFC/qRFC unit or a job so a network failure never blocks the user in transaction BP.
- Same BP number in both systems requires external numbering on the target or a key-mapping table - confirm with the functional consultant before design.

Each step is one piece of work for the ABAPer. The FSD statements it addresses are listed under it, and every BAPI, table or class appears in the step where it is first needed - once.

### 1. Change trigger in the source system
Detect the BP change without touching the save transaction time: either a BAdI in the BP save sequence that writes the BP key into the status table, or a periodic delta read of CDHDR/CDPOS (OBJECTCLAS 'BUPA') since the last run. Real-time mode -> BAdI + bgRFC; batch/delta mode -> job over change documents. Only fields listed in the mapping table (4.2) should trigger.

Building blocks:
- `CDHDR` (table (named in the FSD)): Change document header - filter OBJECTCLAS = 'BUPA' and UDATE/UTIME greater than the last run
- `CDPOS` (table (named in the FSD)): Changed fields per change document - decide which fields trigger replication
- `BAdI BUPA_FURTHER_CHECKS / BUPA_GENERAL_UPDATE` (BAdI): Runs in the BP save sequence - validate or raise your own event; never call remote systems synchronously inside it
- `Change document object BUPA + event linkage (SWEC) -> BUS1006.CHANGED` (pattern): Standard event on BP change (CDHDR/CDPOS) that can start a workflow or an outbound queue
- `Change pointers (BD52 / BD61 / BDCP2) for message type BUPA_C` (pattern): Standard ALE delta mechanism
- `Enterprise Event Enablement: sap.s4.beh.businesspartner.v1.BusinessPartner.Changed` (pattern): S/4 1909+ business event to SAP Event Mesh / Advanced Event Mesh

Addresses 6 FSD statement(s):
- R6 (integration): When a Business Partner is changed in the source system (update of name, address, roles, etc.), the change should trigger an API/BAPI call to propagate the updated data to the target system
- R7 (scheduling): Change detection can be based on: Manual user action (e.g., save in transaction BP); Background job (e.g., daily delta extraction); Event-driven (e.g., via SAP Event Mesh or IDOC)
- R14 (integration): Real-time \| Sync changes immediately via API call on save \| BAPI_BUPA_CHANGE
- R16 (integration): Delta Sync \| Sync only changed BPs using change logs \| CDPOS / CDHDR tables with BAPI_BUPA_CHANGE
- R25 (integration): User updates Business Partner in source system
- R26 (integration): System detects change (via user exit, enhancement spot, or BAdI)

### 2. Authentication and authorization
Source side: AUTHORITY-CHECK for the job user (B_BUPA_RLT / B_BUPA_GRP). Target side: technical user with the BP maintenance roles; credentials, OAuth/SAML/basic auth live in the SM59 destination / SOAMANAGER logical port, never in code.

Building blocks:
- `AUTHORITY-CHECK OBJECT` (pattern): Check F_BKPF_BUK (company code), V_VBAK_VKO (sales org), M_BEST_EKO (purchasing org), S_TCODE etc. before data access
- `SU21 / SU24` (tcode): Custom authorization object Z_... if no standard object fits
- `SPROXY consumer proxy class (ZCO_*) generated from the target WSDL` (pattern): Typed outbound call; exceptions CX_AI_SYSTEM_FAULT / CX_AI_APPLICATION_FAULT
- `SOAMANAGER logical port + SM59 destination (type G/H)` (tcode): Endpoint, credentials and OAuth/SAML/basic auth live here - never in code
- `CL_HTTP_CLIENT / CL_WEB_HTTP_CLIENT_MANAGER + /UI2/CL_JSON` (class): Alternative when the target exposes OData/REST (API_BUSINESS_PARTNER)

Addresses 2 FSD statement(s):
- R17 (authorization): Users/systems must have appropriate authorizations in both source and target systems
- R18 (authorization): Use SAP S/4HANA OData services or Proxy program with proper authentication (e.g., Basic Auth, SAML, OAuth)

### 3. Status / mapping tables
Status table (BP key, changed fields hash, status, attempt count, last message, timestamps) drives retry and monitoring; mapping table for values that differ between systems (account groups, classifications, partner roles). SM30 views for both; change documents on the mapping table.

Building blocks:
- `ZSCM_<customer-3513>_VEN_ST` (custom object (named in the FSD)): Object name given by the FSD - create it under this name unless the naming standard says otherwise
- `SE11 table + SM30 maintenance generator (or SE54)` (pattern): Custom table with delivery class C/A and a maintenance view
- `Table Maintenance via Fiori Custom Business Object (CBO)` (pattern): Key-user alternative in S/4
- `CHANGEDOCUMENT_* ` (FM): Audit changes of the table
- `Z status/queue table: BP key, payload hash, status, attempt count, last message, next run` (pattern): One row per outbound item drives retry and gives support a monitor

Addresses 1 FSD statement(s):
- R29 (integration): Log success/failure in custom table (e.g., ZSCM_<customer-3513>_VEN_ST *)

### 4. Read the changed BP in the source
Read only what changed: central data, addresses, roles and bank details via the BP read BAPIs (or CDS I_BusinessPartner / I_BusinessPartnerAddress). Build the outbound message from the mapping table; validate mandatory target fields before sending.

Building blocks:
- `BAPI_BUPA_GETDETAIL` (BAPI (named in the FSD)): Use BAPI_BUPA_CENTRAL_GETDETAIL / BAPI_BUPA_ADDRESSES_GET / BAPI_BUPA_ROLES_GET (no single GETDETAIL exists)
- `BAPI_BUPA_GETLIST` (BAPI (named in the FSD)): Use BAPI_BUPA_SEARCH_2 or a CDS/SELECT on BUT000 with change date
- `BAPI_BUPA_CENTRAL_GETDETAIL / BAPI_BUPA_ADDRESSES_GET / BAPI_BUPA_ROLES_GET` (BAPI): Read the current BP state (BAPI_BUPA_GETDETAIL does not exist; use the *_GETDETAIL per data area)
- `BAPI_BUPA_SEARCH_2` (BAPI): Find BPs by name / address (list access)

Addresses 6 FSD statement(s):
- R8 (mapping): BP Number \| BP Number \| Direct mapping, validate existence in target
- R9 (mapping): BP Name \| Name1/Name2 \| Map to appropriate name fields
- R12 (mapping): Classification \| Classification \| Use same or mapped class numbers
- R27 (integration): Trigger BAPI_BUPA_GETDETAIL to extract current BP data
- R34 (validation): Validate compatibility of partner roles, classifications, and address types
- R35 (integration): If custom fields exist in the BP, ensure they are: Available in both systems; Mapped correctly in the API/BAPI

### 5. Change the BP in the target
One class method per data area calling the target's change API through the proxy / OData client: central data, address (needs ADDRESSGUID), roles (add only if missing), bank details; fill the *_X structures; COMMIT once; map BAPIRET2 back into the status table.

Building blocks:
- `API_BUSINESS_PARTNER` (API (named in the FSD)): Released OData V2 API on the target; PATCH A_BusinessPartner / A_BusinessPartnerAddress, use ETag / If-Match
- `BAPI_BUPA_ADDRESS_CHANGE` (BAPI (named in the FSD)): Needs the ADDRESSGUID from BAPI_BUPA_ADDRESSES_GET; fill ADDRESSDATA_X
- `BAPI_BUPA_CHANGE` (BAPI (named in the FSD)): Does not exist as such - the change BAPIs are per data area: BAPI_BUPA_CENTRAL_CHANGE, BAPI_BUPA_ADDRESS_CHANGE, BAPI_BUPA_BANKDETAIL_CHANGE
- `BAPI_BUPA_ROLE_ASSIGN` (BAPI (named in the FSD)): Does not exist - use BAPI_BUPA_ROLE_ADD_2 (check with BAPI_BUPA_ROLE_EXISTENCE_CHECK first)
- `BAPI_BUPA_CENTRAL_CHANGE` (BAPI): Change central BP data (names, search terms, flags) - fill the *_X structure for every changed field
- `BAPI_BUPA_ROLE_ADD_2 / BAPI_BUPA_ROLE_EXISTENCE_CHECK` (BAPI): Assign a BP role (FLCU00, FLVN00...) if it does not exist yet - there is no standard BAPI_BUPA_ROLE_ASSIGN
- `CVI_EI_INBOUND_MAIN` (FM): Change BP together with customer/vendor role data (CVI) in one call - the S/4 way when KNA1/LFA1 fields change
- `BAPI_TRANSACTION_COMMIT` (BAPI): Commit after the change BAPIs (WAIT = 'X')

Addresses 6 FSD statement(s):
- R10 (mapping): Address \| Address Data \| Use BAPI_BUPA_ADDRESS_CHANGE
- R11 (mapping): Partner Role \| Partner Role \| Validate against target system values
- R13 (mapping): Account Groups \| Account Group \| Must be consistent across systems
- R28 (integration): Call BAPI_BUPA_CHANGE on target system via Proxy service
- R32 (processing): Synchronize related master data (e.g., Customer Master, Vendor Master) if used in downstream modules
- R33 (processing): Ensure both systems use the same BP category (Organization, Person, Group)

### 6. Retry and alerting
Technical failures (timeout, connection, HTTP 5xx) -> status 'retry', attempt+1, next run with back-off; application errors (E/A messages) -> status 'error', no automatic retry. After the last attempt e-mail the support distribution list with the BP key and message.

Building blocks:
- `Reprocessing report/job over status = error and attempts < max` (pattern): Scheduled every N minutes; exponential back-off via next-run timestamp
- `bgRFC / qRFC units` (pattern): Standard transactional retry (SBGRFCMON) instead of a hand-written queue
- `Application Interface Framework (AIF)` (pattern): Monitoring, restart and alerting out of the box if licensed
- `CL_BCS e-mail / SAP Alert Notification (ANS)` (class): Notify support after the last failed attempt
- `CL_BCS_CONVERT` (class): Convert internal tables to XLS/CSV attachments

Addresses 3 FSD statement(s):
- R20 (error_handling): If a BAPI call fails in the target system: Retry mechanism (e.g., 3 attempts)
- R21 (error_handling): If a BAPI call fails in the target system: Notify support team if retry fails
- R30 (integration): If failed, retry or alert support team

### 7. Application log and monitoring
Every attempt writes to the application log (SLG1 object/sub-object per the FSD) and updates the status table; a monitor ALV over the status table lets support see, filter and re-trigger items.

Building blocks:
- `BAL_LOG_CREATE / BAL_LOG_MSG_ADD / BAL_DB_SAVE` (FM): Application log (SLG1) with object/sub-object from SLG0
- `Custom exception class (CX_STATIC_CHECK)` (pattern): Raise typed exceptions with T100 messages
- `BAPIRET2` (pattern): Return messages from APIs
- `CL_SALV_TABLE` (class): ALV grid with layout save, totals, sort, filter, export to Excel built in
- `CL_GUI_ALV_GRID` (class): When editable cells or custom events are required

Addresses 3 FSD statement(s):
- R19 (error_handling): If a BAPI call fails in the target system: Log the error with the Business Partner number and error message
- R22 (error_handling): Use SAP transaction ST22 for ABAP dumps or SLG1 for custom logs “ZSCM_<customer-3513>_VEN_ST”
- R23 (error_handling): Maintain logs of successful and failed BP changes

### 8. Reconciliation report
Daily job: read the compared fields for the BPs changed in the period in both systems (remote read via RFC-enabled function or the released API), compare per field or by hash, list differences in ALV and e-mail them; write the run result to the application log for audit.

Building blocks:
- `Reconciliation ALV (CL_SALV_TABLE): key fields read locally and remotely, differences highlighted` (pattern): Daily job with e-mail of the difference list
- `Remote read via RFC-enabled Z function or the released OData API (never RFC_READ_TABLE)` (pattern): Read the target's BUT000/ADRC state for the same keys
- `Hash per BP (CL_ABAP_MESSAGE_DIGEST) over the compared fields` (pattern): Cheap comparison for large volumes
- `BAL_LOG_* application log` (FM): Persist the reconciliation result for audit
- `JOB_OPEN / JOB_SUBMIT / JOB_CLOSE` (FM): Create jobs programmatically
- `SM36 / SM37 with a variant` (tcode): Standard scheduling; keep the report variant-driven (TVARVC dates)

Addresses 2 FSD statement(s):
- R24 (scheduling): Run reconciliation reports daily to compare BP data in source and target systems
- R31 (processing): Ensure BP number uniqueness across systems

### 9. Scheduling
Jobs: delta/retry processor every N minutes (variant-driven, TVARVC last-run timestamp), reconciliation daily; Application Jobs catalogue entry in S/4.

Building blocks:
- `Application Jobs framework (SJOBREPO / Fiori Application Jobs)` (pattern): S/4 job catalogue entry + template

Addresses 1 FSD statement(s):
- R15 (scheduling): Batch \| Periodic sync using job (e.g., daily) \| BAPI_BUPA_GETLIST, then BAPI_BUPA_CHANGE

### 10. Unit tests and handover
ABAP Unit for the field mapping and the status transitions (test doubles for the proxy/BAPI calls); end-to-end test per sync mode; document object list, destinations, job variants and the support runbook (how to re-trigger a failed BP).

### Building blocks the FSD names - and where they are used

| Named in the FSD | Kind | Note | Used in |
|---|---|---|---|
| `API_BUSINESS_PARTNER` | API | Released OData V2 API on the target; PATCH A_BusinessPartner / A_BusinessPartnerAddress, use ETag / If-Match | step 5 |
| `BAPI_BUPA_ADDRESS_CHANGE` | BAPI | Needs the ADDRESSGUID from BAPI_BUPA_ADDRESSES_GET; fill ADDRESSDATA_X | step 5 |
| `BAPI_BUPA_CHANGE` | BAPI | Does not exist as such - the change BAPIs are per data area: BAPI_BUPA_CENTRAL_CHANGE, BAPI_BUPA_ADDRESS_CHANGE, BAPI_BUPA_BANKDETAIL_CHANGE | step 5 |
| `BAPI_BUPA_GETDETAIL` | BAPI | Use BAPI_BUPA_CENTRAL_GETDETAIL / BAPI_BUPA_ADDRESSES_GET / BAPI_BUPA_ROLES_GET (no single GETDETAIL exists) | step 4 |
| `BAPI_BUPA_GETLIST` | BAPI | Use BAPI_BUPA_SEARCH_2 or a CDS/SELECT on BUT000 with change date | step 4 |
| `BAPI_BUPA_ROLE_ASSIGN` | BAPI | Does not exist - use BAPI_BUPA_ROLE_ADD_2 (check with BAPI_BUPA_ROLE_EXISTENCE_CHECK first) | step 5 |
| `CDHDR` | table | Change document header - filter OBJECTCLAS = 'BUPA' and UDATE/UTIME greater than the last run | step 1 |
| `CDPOS` | table | Changed fields per change document - decide which fields trigger replication | step 1 |
| `ZSCM_<customer-3513>_VEN_ST` | custom object | Object name given by the FSD - create it under this name unless the naming standard says otherwise | step 3 |

## FSD statements one by one

Every sentence, bullet and table row of the specification that describes what the solution must do, in document order. *Scope* rows summarise the detailed rows below them and carry no effort of their own.

| # | Kind | Statement in the FSD | Existing code | Best match | Conf. | Addressed by | Effort h |
|---|---|---|---|---|---|---|---|
| R1 | scope | The objective is to ensure accurate, secure, and real-time or batch-based data synchronization while maintaining data integrity and system alignment | missing | - | - | Scope statement - realised by the plan as a whole, no separate effort. | 0.0 |
| R2 | scope | Change management for Business Partner data (e.g., address, roles, relationships, classifications & etc.) | missing | - | - | Scope statement - realised by the plan as a whole, no separate effort. | 0.0 |
| R3 | scope | Use of standard SAP APIs and BAPIs for data exchange between systems | missing | - | - | Scope statement - realised by the plan as a whole, no separate effort. | 0.0 |
| R4 | scope | Integration of Business Partner with downstream modules in target system (e.g., SD, MM, FI/CO) | missing | - | - | Scope statement - realised by the plan as a whole, no separate effort. | 0.0 |
| R5 | scope | Data validation and error handling during data transfer | missing | - | - | Scope statement - realised by the plan as a whole, no separate effort. | 0.0 |
| R6 | integration | When a Business Partner is changed in the source system (update of name, address, roles, etc.), the change should trigger an API/BAPI call to propagate the updated data to the target system | missing | - | - | New development - see plan step 1. Change trigger in the source system. | 12.0 |
| R7 | scheduling | Change detection can be based on: Manual user action (e.g., save in transaction BP); Background job (e.g., daily delta extraction); Event-driven (e.g., via SAP Event Mesh or IDOC) | missing | - | - | New development - see plan step 1. Change trigger in the source system. | 2.0 |
| R8 | mapping | BP Number \| BP Number \| Direct mapping, validate existence in target | missing | - | - | New development - see plan step 4. Read the changed BP in the source. | 1.5 |
| R9 | mapping | BP Name \| Name1/Name2 \| Map to appropriate name fields | missing | - | - | New development - see plan step 4. Read the changed BP in the source. | 1.5 |
| R10 | mapping | Address \| Address Data \| Use BAPI_BUPA_ADDRESS_CHANGE | missing | - | - | New development - see plan step 5. Change the BP in the target. | 1.5 |
| R11 | mapping | Partner Role \| Partner Role \| Validate against target system values | missing | - | - | New development - see plan step 5. Change the BP in the target. | 1.5 |
| R12 | mapping | Classification \| Classification \| Use same or mapped class numbers | missing | - | - | New development - see plan step 4. Read the changed BP in the source. | 1.5 |
| R13 | mapping | Account Groups \| Account Group \| Must be consistent across systems | missing | - | - | New development - see plan step 5. Change the BP in the target. | 1.5 |
| R14 | integration | Real-time \| Sync changes immediately via API call on save \| BAPI_BUPA_CHANGE | missing | - | - | New development - see plan step 1. Change trigger in the source system. | 12.0 |
| R15 | scheduling | Batch \| Periodic sync using job (e.g., daily) \| BAPI_BUPA_GETLIST, then BAPI_BUPA_CHANGE | missing | - | - | New development - see plan step 9. Scheduling. | 2.0 |
| R16 | integration | Delta Sync \| Sync only changed BPs using change logs \| CDPOS / CDHDR tables with BAPI_BUPA_CHANGE | missing | - | - | New development - see plan step 1. Change trigger in the source system. | 12.0 |
| R17 | authorization | Users/systems must have appropriate authorizations in both source and target systems | missing | - | - | New development - see plan step 2. Authentication and authorization. | 1.0 |
| R18 | authorization | Use SAP S/4HANA OData services or Proxy program with proper authentication (e.g., Basic Auth, SAML, OAuth) | missing | - | - | New development - see plan step 2. Authentication and authorization. | 1.0 |
| R19 | error_handling | If a BAPI call fails in the target system: Log the error with the Business Partner number and error message | missing | - | - | New development - see plan step 7. Application log and monitoring. | 2.0 |
| R20 | error_handling | If a BAPI call fails in the target system: Retry mechanism (e.g., 3 attempts) | missing | - | - | New development - see plan step 6. Retry and alerting. | 2.0 |
| R21 | error_handling | If a BAPI call fails in the target system: Notify support team if retry fails | missing | - | - | New development - see plan step 6. Retry and alerting. | 2.0 |
| R22 | error_handling | Use SAP transaction ST22 for ABAP dumps or SLG1 for custom logs “ZSCM_<customer-3513>_VEN_ST” | missing | - | - | New development - see plan step 7. Application log and monitoring. | 2.0 |
| R23 | error_handling | Maintain logs of successful and failed BP changes | missing | - | - | New development - see plan step 7. Application log and monitoring. | 2.0 |
| R24 | scheduling | Run reconciliation reports daily to compare BP data in source and target systems | missing | - | - | New development - see plan step 8. Reconciliation report. | 2.0 |
| R25 | integration | User updates Business Partner in source system | missing | - | - | New development - see plan step 1. Change trigger in the source system. | 12.0 |
| R26 | integration | System detects change (via user exit, enhancement spot, or BAdI) | missing | - | - | New development - see plan step 1. Change trigger in the source system. | 12.0 |
| R27 | integration | Trigger BAPI_BUPA_GETDETAIL to extract current BP data | missing | - | - | New development - see plan step 4. Read the changed BP in the source. | 12.0 |
| R28 | integration | Call BAPI_BUPA_CHANGE on target system via Proxy service | missing | - | - | New development - see plan step 5. Change the BP in the target. | 12.0 |
| R29 | integration | Log success/failure in custom table (e.g., ZSCM_<customer-3513>_VEN_ST *) | missing | - | - | New development - see plan step 3. Status / mapping tables. | 12.0 |
| R30 | integration | If failed, retry or alert support team | missing | - | - | New development - see plan step 6. Retry and alerting. | 12.0 |
| R31 | processing | Ensure BP number uniqueness across systems | missing | - | - | New development - see plan step 8. Reconciliation report. | 8.0 |
| R32 | processing | Synchronize related master data (e.g., Customer Master, Vendor Master) if used in downstream modules | missing | - | - | New development - see plan step 5. Change the BP in the target. | 8.0 |
| R33 | processing | Ensure both systems use the same BP category (Organization, Person, Group) | missing | - | - | New development - see plan step 5. Change the BP in the target. | 8.0 |
| R34 | validation | Validate compatibility of partner roles, classifications, and address types | missing | - | - | New development - see plan step 4. Read the changed BP in the source. | 2.5 |
| R35 | integration | If custom fields exist in the BP, ensure they are: Available in both systems; Mapped correctly in the API/BAPI | missing | - | - | New development - see plan step 4. Read the changed BP in the source. | 12.0 |

## Objects

| Action | Object | Type | Purpose | Uses (BAPIs / FMs / classes / tables) | Plan steps |
|---|---|---|---|---|---|
| create | ZCL_BP_CHANGE_SYNC | Class | Outbound API: read changed BP, map, call the target's change BAPIs/API via proxy or OData client, return BAPIRET2 | `BAPI_BUPA_CENTRAL_GETDETAIL`, `BAPI_BUPA_ADDRESSES_GET`, `BAPI_BUPA_ROLES_GET`, `BAPI_BUPA_CENTRAL_CHANGE`, `BAPI_BUPA_ADDRESS_CHANGE`, `BAPI_BUPA_ROLE_ADD_2`, `BAPI_BUPA_ROLE_EXISTENCE_CHECK`, `BAPI_TRANSACTION_COMMIT`, `ZCO_BP_CHANGE (or API_BUSINESS_PARTNER via CL_HTTP_CLIENT)` | 4, 5 |
| create | ZCL_BP_CHANGE_TRIGGER | Class (BAdI implementation) | Records the changed BP key/fields into the status table from the BP save sequence (or delta read of CDHDR/CDPOS) | `BAdI BUPA_GENERAL_UPDATE / BUPA_FURTHER_CHECKS`, `CDHDR / CDPOS (OBJECTCLAS 'BUPA') delta read`, `event BUS1006.CHANGED (SWEC)`, `ZBP_T_CHANGE_STAT (insert key)` | 1 |
| create | ZCO_BP_CHANGE | Consumer proxy (SPROXY) or HTTP client wrapper | Generated from the target service; logical port in SOAMANAGER / destination in SM59 | `SPROXY consumer proxy from the target WSDL`, `SOAMANAGER logical port`, `SM59 destination (type G/H)`, `CL_HTTP_CLIENT + /UI2/CL_JSON if the target exposes API_BUSINESS_PARTNER` | 2 |
| create | ZBP_T_CHANGE_STAT | Table + SM30 view | Status, attempt count, last message, next run per BP change | `SE11 table + SM30 view (SE54)`, `CHANGEDOCUMENT_* for audit`, `TVARVC last-run timestamp` | 3 |
| create | ZBP_T_CHANGE_MAP | Table + SM30 view | Value mapping between systems (account group, classification, roles) | `SE11 table + SM30 view (SE54)` | 3 |
| create | ZBP_CHANGE_PROC | Program (job) | Delta / retry processor over the status table | `ZBP_T_CHANGE_STAT (SELECT status = retry / new)`, `ZCL_BP_CHANGE_SYNC`, `CL_BCS (alert mail after last attempt)`, `SM36 job with variant / TVARVC` | 6, 9 |
| create | ZBP_CHANGE_MON | Program (ALV) | Monitor: filter by status, re-trigger, show last message | `ZBP_T_CHANGE_STAT`, `CL_SALV_TABLE`, `ZCL_BP_CHANGE_SYNC (re-trigger)`, `BAL_DSP_LOG_DISPLAY` | 7 |
| create | ZBP_CHANGE_RECON | Program (ALV, job) | Reconciliation: compare source and target, e-mail differences | `BAPI_BUPA_CENTRAL_GETDETAIL (local)`, `ZCO_BP_CHANGE / RFC read of the target`, `CL_ABAP_MESSAGE_DIGEST (hash compare)`, `CL_SALV_TABLE`, `CL_BCS`, `BAL_LOG_CREATE / BAL_LOG_MSG_ADD / BAL_DB_SAVE` | 8 |
| create | ZCX_BP_CHANGE | Exception class | Typed errors (technical vs application) with T100 messages | `CX_STATIC_CHECK`, `IF_T100_MESSAGE`, `ZBP_CHANGE_MSG` | 7 |
| create | ZBP_CHANGE_MSG | Message class | All user-facing messages (translatable) | `SE91 message class` | - |
| create | ZSCM_<customer-3513>_VEN_ST | Table (named in the FSD) | Name given by the FSD - use it (or map it to the object above that plays this role) so the FSD and the build stay aligned | `same role as ZBP_T_CHANGE_STAT - the FSD's name for the status/log table` | 3 |
| reuse | ZCL_ZCA_APPLOG | Class | Reuse for logging | - | - |
| reuse | ZCX_ZCA_EXCEPTION | Class | Reuse for exceptions | - | - |

Reusable utilities already in the repository: ZCL_ZCA_APPLOG (logging), ZCX_ZCA_EXCEPTION (exceptions)

## Effort estimate

- integration: 120.0 h
- scheduling: 6.0 h
- mapping: 9.0 h
- authorization: 2.0 h
- error_handling: 10.0 h
- processing: 24.0 h
- validation: 2.5 h
- technical design & unit tests (20%): 34.7 h
- proxy generation, destinations & connectivity test: 8.0 h
- **Total: 216.2 h**

## S/4HANA and Clean Core notes

- Add MANDT, use data elements with domains, and a maintenance view instead of writing your own screen.
- CVI synchronisation to KNA1/LFA1 runs automatically after the BP change - check MDS_LOAD_COCKPIT/MDS_PPO2 for post-processing errors.
- Check at the start of the program and again per company code / org unit in the selection.
- Decouple: the trigger only records the BP key in a queue/status table; the outbound call runs from a job or bgRFC - a remote failure must never block the user saving in transaction BP.
- Dynamic dates (today, month start) via TVARVC variables or selection variables (D/T).
- Every change BAPI has an *_X structure; unfilled flags mean 'no change'.

## Test scenarios to cover

- R6: When a Business Partner is changed in the source system (update of name, address, roles, e
- R14: Real-time | Sync changes immediately via API call on save | BAPI_BUPA_CHANGE
- R16: Delta Sync | Sync only changed BPs using change logs | CDPOS / CDHDR tables with BAPI_BUPA
- R25: User updates Business Partner in source system
- R26: System detects change (via user exit, enhancement spot, or BAdI)
- R27: Trigger BAPI_BUPA_GETDETAIL to extract current BP data
- R28: Call BAPI_BUPA_CHANGE on target system via Proxy service
- R29: Log success/failure in custom table (e.g., ZSCM_<customer-3513>_VEN_ST *)

_Guardrails: 3 name(s) detected in the document were masked in this report._

_Generated by ABAP Beacon on 2026-09-12 17:51 UTC. Coverage and effort are estimates from deterministic matching; review before committing._
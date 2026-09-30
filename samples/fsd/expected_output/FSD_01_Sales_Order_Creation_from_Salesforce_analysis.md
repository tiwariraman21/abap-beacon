# FSD analysis - FSD - Sales Order Creation Interface from Salesforce

**Verdict: REUSE - an existing object covers most of this FSD. Extend it for the partial/missing points instead of building new.**

- Weighted coverage by existing objects: **67.6%**
- Requirements: 16 (8 covered · 5 partial · 3 missing)
- Estimated remaining effort: **49.4 h** (design + unit tests included)
- Module: SD

> Salesforce (SF) captures customer orders for the <customer-1822> business. Today the sales team re-keys these orders manually in VA01. The requirement is an inbound interface so that SAP creates the sales order automatically from the Salesforce opportunity and returns the SAP order number and any errors to Salesforce.

## Existing objects to reuse

| Object | Type | Covers | Covered | Partial | Missing |
|---|---|---|---|---|---|
| ZCL_ZSD_SALESORDER | Class | 63.5% | R1, R4, R5, R6, R8, R10, R16 | R2, R3, R7, R9, R15 | R11, R12, R13, R14 |
| ZCL_ZSD_SALESORDER_CRE_DPC_EXT | Class | 48.6% | R1, R4, R5, R6, R16 | R2, R3, R8, R9 | R7, R10, R11, R12, R13, R14, R15 |
| ZCL_ZSD_SALESORDER_CRE_MPC_EXT | Class | 28.4% | R4 | R1, R2, R5, R8, R9, R16 | R3, R6, R7, R10, R11, R12, R13, R14, R15 |


## Feasibility and complexity

**Feasibility: Feasible** · complexity **M** · FSD quality **76/100** · classification **I - Interface** · estimate confidence **high** (100 %)

**Not specified in the FSD**
- expected volumes and response-time / SLA expectations

**Complexity drivers:** 16 detailed statements; 7 integration statements; 1 external system(s) / boundaries; 9 distinct SAP topics; exposed / consumed service

**FSD quality:** covers authorization, error handling, trigger / scheduling, validation rules, named SAP objects; missing volumes / performance, field mapping, acceptance / test data; 14 of 16 detailed statements are testable (shall/must/will or a named SAP object); 1 use open wording.

**Clarification questions for the functional consultant**
1. Please specify expected volumes and response-time / SLA expectations.
2. R16 uses open wording ("relevant") - please list the exact values / cases: "The interface user needs authorization for sales order creation in the relevant sales orga"

## FSD statements one by one

Every sentence, bullet and table row of the specification that describes what the solution must do, in document order. *Scope* rows summarise the detailed rows below them and carry no effort of their own.

| # | Kind | Statement in the FSD | Existing code | Best match | Conf. | Addressed by | Effort h |
|---|---|---|---|---|---|---|---|
| R1 | integration | The requirement is an inbound interface so that SAP creates the sales order automatically from the Salesforce opportunity and returns the SAP order number and any errors to Salesforce | covered | ZCL_ZSD_SALESORDER (MS_DEEP_ENTITY) | 0.72 | Reuse ZCL_ZSD_SALESORDER → MS_DEEP_ENTITY. Verify the behaviour matches: "The requirement is an inbound interface so that SAP creates the sales order automatically from the Salesforce…". Note: ZCL_ZSD_SALESORDER has open findings S4-006, CC-003 - address while touching it. | 1.8 |
| R2 | integration | The interface shall be exposed as an OData service that Salesforce calls in real time | partial | ZCL_ZSD_SALESORDER (ODATA_GET_EXTRA_DATA, PREPARE_ODATA_FEEDBACK) | 0.54 | Extend ZCL_ZSD_SALESORDER → ODATA_GET_EXTRA_DATA, PREPARE_ODATA_FEEDBACK: extend the interface mapping / payload handling - The interface shall be exposed as an OData service that Salesforce calls in real time. See plan step 1. Service entry point. | 6.6 |
| R3 | integration | The payload will contain header data, item data, partner data, header texts, delivery information and item pricing elements | partial | ZCL_ZSD_SALESORDER_CRE_MPC (LOAD_TEXT_ELEMENTS) | 0.46 | Extend ZCL_ZSD_SALESORDER_CRE_MPC → LOAD_TEXT_ELEMENTS: extend the interface mapping / payload handling - The payload will contain header data, item data, partner data, header texts, delivery information and item pr…. See plan step 1. Service entry point. | 6.6 |
| R4 | integration | SAP must return the created sales order number (VBELN) and a status with messages to Salesforce | covered | ZCL_ZSD_SALESORDER (MS_DEEP_ENTITY, MV_VBELN) | 0.94 | Reuse ZCL_ZSD_SALESORDER → MS_DEEP_ENTITY, MV_VBELN. Verify the behaviour matches: "SAP must return the created sales order number (VBELN) and a status with messages to Salesforce". Note: ZCL_ZSD_SALESORDER has open findings S4-006, CC-003 - address while touching it. | 1.8 |
| R5 | validation | The system shall check whether a sales order already exists for the Salesforce reference (SF opportunity id) and must not create a duplicate; instead the existing order number is returned | covered | ZCL_ZSD_SALESORDER (CHECK_SF_REF_ALREADY_EXISTS, MS_DEEP_ENTITY) | 0.81 | Reuse ZCL_ZSD_SALESORDER → CHECK_SF_REF_ALREADY_EXISTS, MS_DEEP_ENTITY. Verify the behaviour matches: "The system shall check whether a sales order already exists for the Salesforce reference (SF opportunity id)…". Note: ZCL_ZSD_SALESORDER has open findings S4-006, CC-003 - address while touching it. | 0.4 |
| R6 | integration | The sales order shall be created using BAPI_SALESORDER_CREATEFROMDAT2 with header, items, partners, schedule lines and conditions mapped from the payload | covered | ZCL_ZSD_SALESORDER (MS_BAPISDHD1, MS_BAPISDHD1X) | 1.00 | Reuse ZCL_ZSD_SALESORDER → MS_BAPISDHD1, MS_BAPISDHD1X. Verify the behaviour matches: "The sales order shall be created using BAPI_SALESORDER_CREATEFROMDAT2 with header, items, partners, schedule…". Already references BAPI_SALESORDER_CREATEFROMDAT2. Note: ZCL_ZSD_SALESORDER has open findings S4-006, CC-003 - address while touching it. | 1.8 |
| R7 | processing | Item pricing elements from Salesforce shall be passed as manual conditions | partial | ZCL_ZSD_SALESORDER (MT_BAPICONDX) | 0.50 | Extend ZCL_ZSD_SALESORDER → MT_BAPICONDX: add the logic (new method / form) implementing "Item pricing elements from Salesforce shall be passed as manual conditions". See plan step 5. Business logic and validations. | 4.4 |
| R8 | integration | After successful creation the system shall commit with BAPI_TRANSACTION_COMMIT and read the document back to return the order details | covered | ZCL_ZSD_SALESORDER | 0.79 | Reuse ZCL_ZSD_SALESORDER. Verify the behaviour matches: "After successful creation the system shall commit with BAPI_TRANSACTION_COMMIT and read the document back to…". Already references BAPI_TRANSACTION_COMMIT. Note: ZCL_ZSD_SALESORDER has open findings S4-006, CC-003 - address while touching it. | 1.8 |
| R9 | integration | If the customer has a credit block, the order shall be released from the credit block automatically when the Salesforce payload indicates prepayment | partial | ZCL_ZSD_SALESORDER (MC_PO_METHOD_SF, RELEASE_ORDER) | 0.52 | Extend ZCL_ZSD_SALESORDER → MC_PO_METHOD_SF, RELEASE_ORDER: extend the interface mapping / payload handling - If the customer has a credit block, the order shall be released from the credit block automatically when the…. See plan step 1. Service entry point. | 6.6 |
| R10 | data_model | Mapping between Salesforce values and SAP values (order type, sales organisation, distribution channel, division) shall be maintained in a custom mapping table maintainable via SM30 | covered | ZCL_ZSD_SALESORDER (MS_BAPISDHD1, MS_BAPISDHD1X) | 0.60 | Reuse ZCL_ZSD_SALESORDER → MS_BAPISDHD1, MS_BAPISDHD1X. Verify the behaviour matches: "Mapping between Salesforce values and SAP values (order type, sales organisation, distribution channel, divis…". Note: ZCL_ZSD_SALESORDER has open findings S4-006, CC-003 - address while touching it. | 0.6 |
| R11 | validation | Customer number (KUNNR) must exist in the sales area; otherwise return an error | missing | - | - | New development - see plan step 5. Business logic and validations. | 2.5 |
| R12 | validation | Material (MATNR) must exist and be valid for the plant; otherwise return an error | missing | - | - | New development - see plan step 5. Business logic and validations. | 2.5 |
| R13 | validation | Requested delivery date must not be in the past | partial | ZCL_ZSD_SALESORDER_CRE_MPC (DEFINE_SO_DELIVERY, DEFINE_SO_REQUEST) | 0.53 | Extend ZCL_ZSD_SALESORDER_CRE_MPC → DEFINE_SO_DELIVERY, DEFINE_SO_REQUEST: add a validation method returning a BAPIRET2/exception - Requested delivery date must not be in the past. See plan step 5. Business logic and validations. | 1.4 |
| R14 | error_handling | All BAPI return messages shall be collected and returned to Salesforce | missing | - | - | New development - see plan step 7. Error handling and application log. | 2.0 |
| R15 | error_handling | Every call and its result must be written to the application log (SLG1) for support | covered | ZCL_ZCA_APPLOG (MS_LOG_HDR, MT_LOG_HANDLE) | 0.72 | Reuse ZCL_ZCA_APPLOG → MS_LOG_HDR, MT_LOG_HANDLE. Verify the behaviour matches: "Every call and its result must be written to the application log (SLG1) for support". Note: ZCL_ZCA_APPLOG has open findings S4-002, S4-002 - address while touching it. | 0.3 |
| R16 | authorization | The interface user needs authorization for sales order creation in the relevant sales organisation (V_VBAK_VKO) | covered | ZCL_ZSD_SALESORDER (MS_DEEP_ENTITY) | 0.66 | Reuse ZCL_ZSD_SALESORDER → MS_DEEP_ENTITY. Verify the behaviour matches: "The interface user needs authorization for sales order creation in the relevant sales organisation (V_VBAK_VK…". Note: ZCL_ZSD_SALESORDER has open findings S4-006, CC-003 - address while touching it. | 0.1 |

## Development plan - what to build

**Solution pattern:** API class (business logic) + OData service (RAP or SEGW) + configuration table  
_Several integration requirements: expose the logic as a service and keep mapping/config outside code._

Each step is one piece of work for the ABAPer. The FSD statements it addresses are listed under it, and every BAPI, table or class appears in the step where it is first needed - once.

### 1. Service entry point
Define the service (entity model, request/response structures) and keep the handler thin: parse payload → call the API class → map BAPIRET2 to the response.
- Already available: **ZCL_ZSD_SALESORDER** - reuse instead of rewriting.

Building blocks:
- `RAP (Behaviour Definition + Service Definition/Binding)` (pattern): Preferred for new OData V4 services in S/4 (ABAP Cloud ready)
- `SEGW project + DPC_EXT / MPC_EXT classes` (pattern): OData V2 via Gateway Service Builder (classic)
- `CL_HTTP_CLIENT / CL_WEB_HTTP_CLIENT_MANAGER` (class): Outbound HTTP/REST calls with SM59 destination
- `/UI2/CL_JSON` (class): JSON serialisation/deserialisation

Addresses 7 FSD statement(s):
- R1 (integration): The requirement is an inbound interface so that SAP creates the sales order automatically from the Salesforce opportunity and returns the SAP order number and any errors to Salesforce
- R2 (integration): The interface shall be exposed as an OData service that Salesforce calls in real time
- R3 (integration): The payload will contain header data, item data, partner data, header texts, delivery information and item pricing elements
- R4 (integration): SAP must return the created sales order number (VBELN) and a status with messages to Salesforce
- R6 (integration): The sales order shall be created using BAPI_SALESORDER_CREATEFROMDAT2 with header, items, partners, schedule lines and conditions mapped from the payload
- R8 (integration): After successful creation the system shall commit with BAPI_TRANSACTION_COMMIT and read the document back to return the order details
- R9 (integration): If the customer has a credit block, the order shall be released from the credit block automatically when the Salesforce payload indicates prepayment

### 2. Authorization check
AUTHORITY-CHECK before any data access; per org unit in the selection. Reject early with a clear message.
- Already available: **ZCL_ZSD_SALESORDER** - reuse instead of rewriting.

Building blocks:
- `AUTHORITY-CHECK OBJECT` (pattern): Check F_BKPF_BUK (company code), V_VBAK_VKO (sales org), M_BEST_EKO (purchasing org), S_TCODE etc. before data access
- `SU21 / SU24` (tcode): Custom authorization object Z_... if no standard object fits

Addresses 1 FSD statement(s):
- R16 (authorization): The interface user needs authorization for sales order creation in the relevant sales organisation (V_VBAK_VKO)

### 3. Configuration / custom table
Create the Z table(s) the FSD asks for (MANDT key, data elements, delivery class C) with an SM30 maintenance view; read them once at start.
- Already available: **ZCL_ZSD_SALESORDER** - reuse instead of rewriting.

Building blocks:
- `SE11 table + SM30 maintenance generator (or SE54)` (pattern): Custom table with delivery class C/A and a maintenance view
- `Table Maintenance via Fiori Custom Business Object (CBO)` (pattern): Key-user alternative in S/4
- `CHANGEDOCUMENT_* ` (FM): Audit changes of the table
- `CHANGEDOCUMENT_OPEN/MULTIPLE_CASE/CLOSE` (FM): Write change documents for Z tables (SCDO)

Addresses 1 FSD statement(s):
- R10 (data_model): Mapping between Salesforce values and SAP values (order type, sales organisation, distribution channel, division) shall be maintained in a custom mapping table maintainable via SM30

### 4. Data retrieval
Read with ABAP SQL / CDS in one pass (no SELECT in LOOP), FOR ALL ENTRIES guarded by an emptiness check, only the fields needed. Tables/views: VBAK, VBAP, VBUK (S/4: status fields in VBAK).

Building blocks:
- `BAPISDORDER_GETDETAILEDLIST` (BAPI): Read header, items, partners, conditions, status for a list of orders
- `I_SalesOrder / I_SalesOrderItem / I_SalesDocumentFlow` (CDS): Released CDS views for reporting and status (S/4)
- `SD_ORDER_GET_STATUS` (FM): Overall status flags

### 5. Business logic and validations
One method per rule in the FSD (validations return BAPIRET2 / raise typed exceptions, never MESSAGE inside the class). Implement: R5 The system shall check whether a sales order already exists for the Sa…; R7 Item pricing elements from Salesforce shall be passed as manual condit…; R11 Customer number (KUNNR) must exist in the sales area; otherwise return…; R12 Material (MATNR) must exist and be valid for the plant; otherwise retu…; R13 Requested delivery date must not be in the past.
- Already available: **ZCL_ZSD_SALESORDER** - reuse instead of rewriting.

Building blocks:
- `SELECT SINGLE ... / line_exists( )` (pattern): Existence checks against master/transaction data
- `Value help / conversion exits` (pattern): CONVERSION_EXIT_ALPHA_INPUT for numeric keys
- `Custom exception / BAPIRET2` (pattern): Return a typed error, do not MESSAGE inside API classes
- `BAPI_SALESORDER_CREATEFROMDAT2` (BAPI): Create sales order with header, items, partners, schedule lines, conditions, texts

Addresses 5 FSD statement(s):
- R5 (validation): The system shall check whether a sales order already exists for the Salesforce reference (SF opportunity id) and must not create a duplicate; instead the existing order number is returned
- R7 (processing): Item pricing elements from Salesforce shall be passed as manual conditions
- R11 (validation): Customer number (KUNNR) must exist in the sales area; otherwise return an error
- R12 (validation): Material (MATNR) must exist and be valid for the plant; otherwise return an error
- R13 (validation): Requested delivery date must not be in the past

### 6. Posting / integration
Call the standard BAPI/API, evaluate RETURN (E/A = failure → BAPI_TRANSACTION_ROLLBACK), COMMIT once at the end; map custom fields via extension structures; log request/response.
- Already available: **ZCL_ZSD_SALESORDER** - reuse instead of rewriting.

Building blocks:
- `BAPI_TRANSACTION_COMMIT` (BAPI (named in the FSD)): Specified by the FSD - verify signature and release status (SE37 / API Business Hub)
- `SD_SALESDOCUMENT_CREATE` (FM): Alternative with extension structures (BAPE_VBAK/VBAP) for custom fields
- `API_SALES_ORDER_SRV` (pattern): Released OData API if the consumer is external and S/4 1809+
- `UKM_DB_CREDIT_SEGMENT_READ / UKM_CREDIT_CHECK` (FM): FSCM credit check
- `BAPI_CREDIT_ACCOUNT_GET_DETAIL` (BAPI): Read credit account (FSCM)
- `BAdI UKM_R3_ACTIVATE / UKM_FILL` (BAdI): Influence exposure and checks

### 7. Error handling and application log
Collect all messages, write to the application log (SLG1 object/sub-object) and return/display them; retries for technical failures where the FSD asks for them.
- Already available: **ZCL_ZCA_APPLOG** - reuse instead of rewriting.

Building blocks:
- `BAL_LOG_CREATE / BAL_LOG_MSG_ADD / BAL_DB_SAVE` (FM): Application log (SLG1) with object/sub-object from SLG0
- `Custom exception class (CX_STATIC_CHECK)` (pattern): Raise typed exceptions with T100 messages
- `BAPIRET2` (pattern): Return messages from APIs

Addresses 2 FSD statement(s):
- R14 (error_handling): All BAPI return messages shall be collected and returned to Salesforce
- R15 (error_handling): Every call and its result must be written to the application log (SLG1) for support

### 8. Unit tests and handover
ABAP Unit for validations and mapping (test doubles for the BAPI calls); document the object list, transport and job variants.

### Building blocks the FSD names - and where they are used

| Named in the FSD | Kind | Note | Used in |
|---|---|---|---|
| `BAPI_SALESORDER_CREATEFROMDAT2` | BAPI | Specified by the FSD - verify signature and release status (SE37 / API Business Hub) | step 5 |
| `BAPI_TRANSACTION_COMMIT` | BAPI | Specified by the FSD - verify signature and release status (SE37 / API Business Hub) | step 6 |

## Objects

| Action | Object | Type | Purpose | Uses (BAPIs / FMs / classes / tables) | Plan steps |
|---|---|---|---|---|---|
| extend | ZCL_ZSD_SALESORDER | Class | Covers 63.5% of the FSD (weighted); extend for the partial/missing requirements listed in the analysis. | `BAPISDORDER_GETDETAILEDLIST`, `I_SalesOrder / I_SalesOrderItem / I_SalesDocumentFlow`, `SD_ORDER_GET_STATUS`, `BAPI_SALESORDER_CREATEFROMDAT2`, `BAPI_TRANSACTION_COMMIT`, `SD_SALESDOCUMENT_CREATE`, `UKM_DB_CREDIT_SEGMENT_READ / UKM_CREDIT_CHECK`, `BAPI_CREDIT_ACCOUNT_GET_DETAIL` | 4, 5, 6 |
| extend | ZCL_ZSD_SALESORDER_CRE_DPC_EXT | Class | Covers 48.6% of the FSD (weighted); extend for the partial/missing requirements listed in the analysis. | `BAPISDORDER_GETDETAILEDLIST`, `I_SalesOrder / I_SalesOrderItem / I_SalesDocumentFlow`, `SD_ORDER_GET_STATUS`, `BAPI_SALESORDER_CREATEFROMDAT2`, `BAPI_TRANSACTION_COMMIT`, `SD_SALESDOCUMENT_CREATE`, `UKM_DB_CREDIT_SEGMENT_READ / UKM_CREDIT_CHECK`, `BAPI_CREDIT_ACCOUNT_GET_DETAIL` | 4, 5, 6 |
| reuse | ZCL_ZCA_APPLOG | Class | Reuse for logging | - | - |
| reuse | ZCX_ZCA_EXCEPTION | Class | Reuse for exceptions | - | - |

Reusable utilities already in the repository: ZCL_ZCA_APPLOG (logging), ZCX_ZCA_EXCEPTION (exceptions)

## Effort estimate

- integration: 27.0 h
- validation: 6.8 h
- processing: 4.4 h
- data_model: 0.6 h
- error_handling: 2.3 h
- authorization: 0.1 h
- technical design & unit tests (20%): 8.2 h
- **Total: 49.4 h**

## S/4HANA and Clean Core notes

- Add MANDT, use data elements with domains, and a maintenance view instead of writing your own screen.
- Check at the start of the program and again per company code / org unit in the selection.
- Classic SD credit management (KNKK, FD32, VKM*, SD_ORDER_CREDIT_RELEASE) is replaced by FSCM in S/4HANA.
- Credit check runs inside the BAPI; S/4 uses FSCM credit management (UKM_*), not SD-BF-CM.
- In S/4HANA read status fields from VBAK/VBAP; VBUK/VBUP are empty compatibility views.
- Keep the API class free of UI logic; return BAPIRET2-style messages; log every call (application log).
- Map custom fields via EXTENSIONIN (BAPE_VBAK/BAPE_VBAKX) - never write VBAK directly.
- Return table BAPIRET2: treat type E/A as failure and call BAPI_TRANSACTION_ROLLBACK.

## Test scenarios to cover

- R1: The requirement is an inbound interface so that SAP creates the sales order automatically 
- R2: The interface shall be exposed as an OData service that Salesforce calls in real time
- R3: The payload will contain header data, item data, partner data, header texts, delivery info
- R4: SAP must return the created sales order number (VBELN) and a status with messages to Sales
- R5: The system shall check whether a sales order already exists for the Salesforce reference (
- R6: The sales order shall be created using BAPI_SALESORDER_CREATEFROMDAT2 with header, items, 
- R7: Item pricing elements from Salesforce shall be passed as manual conditions
- R8: After successful creation the system shall commit with BAPI_TRANSACTION_COMMIT and read th

_Generated by ABAP Beacon on 2026-09-12 17:51 UTC. Coverage and effort are estimates from deterministic matching; review before committing._
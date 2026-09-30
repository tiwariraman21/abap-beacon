# Sample functional specifications

Five FSDs that exercise every outcome of the FSD analysis against the sample
repository (`data/input/ZAD_20260708_171359.zip`). Run each with

    .\run.bat fsd samples\fsd\<file>            (add --ai for an AI review)

or upload it on the **FSD analysis** page of the web app. The reports ABAP Beacon
produces are in `expected_output/`.

| File | Scenario | What ABAP Beacon concludes |
|---|---|---|
| `FSD_01_Sales_Order_Creation_from_Salesforce.md` | Requirement already implemented | **REUSE** – ZCL_ZSD_SALESORDER + its Gateway DPC/MPC classes cover ~70 %; the duplicate check is matched to method CHECK_SF_REF_ALREADY_EXISTS; remaining gaps are the three validations and manual pricing conditions |
| `FSD_02_Vendor_Ageing_Report_Enhancement.docx` (Word) | Partly covered, needs extension | **EXTEND** – the existing ZRFI_VENDOR_AGEING objects cover the basics (~40 %); new buckets, ALV/e-mail output, scheduling and vendor-group subtotals are listed as changes with effort; plan = ALV report with background e-mail mode |
| `FSD_03_Purchase_Order_Approval_Workflow.md` | Nothing exists | **NEW DEVELOPMENT** – coverage < 10 %; plan = flexible workflow + approval class + history report with BAPI_PO_RELEASE, SAP_WAPI_START_WORKFLOW, CL_BCS, CL_SALV_TABLE…; reuses the repository's log wrapper ZCL_ZCA_APPLOG and exception class |
| `FSD_04_Bank_Beneficiary_Registration_API.md` | Covered, but the existing code has a security gap | **REUSE** – ZCL_AXIS_PAYEE_MGMT covers ~70 %; the "credentials must be stored securely" requirement is downgraded to *partial* because the assessment found hard-coded URLs (SEC-002) in that class, with the line numbers to fix |
| `FSD_05_Business_Partner_Change_Replication.docx` (Word, real customer layout) | Nothing exists; document full of non-requirement sections and customer names | **NEW DEVELOPMENT** – 0 % coverage, ~35 requirements (testing / rollout / fallback / training / landscape sections are ignored, nested bullets merged, the "Authorization" section kept); plan = *Change replication* pattern (BAdI or CDHDR delta trigger → outbound class via proxy/OData → status table with retry → reconciliation report) built on the BAPIs the FSD names (`BAPI_BUPA_CHANGE`, `BAPI_BUPA_ADDRESS_CHANGE`, `BAPI_BUPA_GETDETAIL`, `CDHDR/CDPOS`) with corrections where they do not exist (`BAPI_BUPA_ROLE_ASSIGN` → `BAPI_BUPA_ROLE_ADD_2`); objects `ZCL_BP_CHANGE_SYNC`, `ZBP_T_CHANGE_STAT`, `ZBP_CHANGE_RECON`…; design alternatives (DRF/MDG, OData API, bgRFC) listed first; the customer, project and author names are detected and masked (`<customer-…>`) although none of them is on the guardrail list |

Writing your own FSD (.docx, .pdf, .md or .txt): headings such as *Selection Screen*, *Processing Logic*,
*Validations*, *Output*, *Authorization*, *Error Handling*, *Scheduling* and a
`Module | SD` row in the document-control table help the classifier; bullets
or sentences with *shall / must / should* become requirements. Naming tables
(BSIK, VBAK…), BAPIs and transactions in the text makes matching much sharper
because ABAP Beacon checks them against what each object really references.

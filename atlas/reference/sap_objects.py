"""SAP standard object dictionary.

A curated subset of the tables, function modules and classes custom code
touches most, with module, short text and - where relevant - the S/4HANA
simplification item that affects them. Used to:
  * label standard dependencies in the dependency view,
  * drive the S/4HANA readiness rules,
  * infer the SAP module of an object from the tables it touches.

Statuses:
  ok          unchanged in S/4HANA
  compat      still readable via a compatibility view; writes are not allowed,
              performance differs, plan to move to the successor
  replaced    table no longer holds data / structure changed - code must move
  changed     exists but with changed semantics or field lengths
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StdTable:
    name: str
    text: str
    module: str
    s4_status: str = "ok"
    successor: str = ""
    note: str = ""            # SAP simplification item / note reference (free text)
    remediation: str = ""


_T: list[StdTable] = [
    # --- FI / new GL ------------------------------------------------------------------------
    StdTable("BSIK", "Vendor open items (index)", "FI", "compat", "ACDOCA / I_OperationalAcctgDocItem", "S4TWL - Data model changes in FIN (BSIK becomes a compatibility view)",
             "Read via ACDOCA or CDS I_OperationalAcctgDocItem with KTOPL/vendor filters; remove direct writes."),
    StdTable("BSID", "Customer open items (index)", "FI", "compat", "ACDOCA / I_OperationalAcctgDocItem", "S4TWL - Data model changes in FIN", "Read via ACDOCA / CDS; no writes."),
    StdTable("BSAK", "Vendor cleared items (index)", "FI", "compat", "ACDOCA", "S4TWL - Data model changes in FIN", "Read via ACDOCA / CDS; no writes."),
    StdTable("BSAD", "Customer cleared items (index)", "FI", "compat", "ACDOCA", "S4TWL - Data model changes in FIN", "Read via ACDOCA / CDS; no writes."),
    StdTable("BSIS", "G/L open items (index)", "FI", "compat", "ACDOCA", "S4TWL - Data model changes in FIN", "Read via ACDOCA / CDS; no writes."),
    StdTable("BSAS", "G/L cleared items (index)", "FI", "compat", "ACDOCA", "S4TWL - Data model changes in FIN", "Read via ACDOCA / CDS; no writes."),
    StdTable("GLT0", "G/L totals (classic)", "FI", "replaced", "ACDOCA", "S4TWL - Totals tables removed", "Aggregate on ACDOCA instead."),
    StdTable("FAGLFLEXT", "New GL totals", "FI", "replaced", "ACDOCA", "S4TWL - Totals tables removed", "Aggregate on ACDOCA instead."),
    StdTable("FAGLFLEXA", "New GL line items", "FI", "compat", "ACDOCA", "S4TWL - Data model changes in FIN", "Read ACDOCA."),
    StdTable("COEP", "CO line items", "CO", "compat", "ACDOCA", "S4TWL - CO line items in ACDOCA", "Read ACDOCA (actuals); COEP keeps statistical/plan only."),
    StdTable("COSP", "CO totals primary", "CO", "replaced", "ACDOCA", "S4TWL - CO totals removed", "Aggregate on ACDOCA."),
    StdTable("COSS", "CO totals secondary", "CO", "replaced", "ACDOCA", "S4TWL - CO totals removed", "Aggregate on ACDOCA."),
    StdTable("ANEP", "Asset line items", "FI-AA", "compat", "ACDOCA", "S4TWL - New Asset Accounting", "Read ACDOCA / I_ActualPlanAssetLineItems."),
    StdTable("ANLC", "Asset value fields", "FI-AA", "replaced", "ACDOCA", "S4TWL - New Asset Accounting", "Use asset CDS views / FAA APIs."),
    StdTable("BKPF", "Accounting document header", "FI", "ok"),
    StdTable("BSEG", "Accounting document segment", "FI", "changed", "ACDOCA", "S4TWL - BSEG reduced; not all postings create BSEG lines", "Prefer ACDOCA for reporting; BSEG for open-item managed fields only."),
    StdTable("ACDOCA", "Universal journal line items", "FI", "ok"),
    StdTable("LFA1", "Vendor master (general)", "FI/MM", "changed", "BUT000 / CVI", "S4TWL - Business Partner approach (CVI)", "Master data maintained via BP; LFA1 remains readable, creation must go through CVI/BP APIs."),
    StdTable("LFB1", "Vendor master (company code)", "FI", "changed", "BUT000 / CVI", "S4TWL - Business Partner approach", "As LFA1."),
    StdTable("LFBK", "Vendor bank details", "FI", "changed", "BUT0BK", "S4TWL - Business Partner approach", "Bank details maintained on the BP."),
    StdTable("KNA1", "Customer master (general)", "SD/FI", "changed", "BUT000 / CVI", "S4TWL - Business Partner approach (CVI)", "As LFA1."),
    StdTable("KNB1", "Customer master (company code)", "FI", "changed", "BUT000 / CVI", "S4TWL - Business Partner approach", "As LFA1."),
    StdTable("KNVV", "Customer sales data", "SD", "ok"),
    StdTable("KNKK", "Customer credit control", "FI-AR", "replaced", "UKMBP_CMS_SGM", "S4TWL - Credit Management (FSCM replaces SD-BF-CM)", "Use FSCM credit management tables/APIs (UKM*)."),
    StdTable("KNKA", "Customer credit central data", "FI-AR", "replaced", "UKMBP_CMS", "S4TWL - Credit Management", "Use FSCM UKM* tables/APIs."),
    StdTable("T001", "Company codes", "FI", "ok"),
    StdTable("SKA1", "G/L account master", "FI", "ok"),
    StdTable("SKAT", "G/L account texts", "FI", "ok"),
    StdTable("SKB1", "G/L account company code", "FI", "ok"),
    StdTable("TVARVC", "Selection variables", "BC", "ok"),
    StdTable("T012K", "House bank accounts", "FI", "changed", "FCLM_BAM", "S4TWL - Bank Account Management", "House bank accounts managed in BAM."),
    StdTable("REGUH", "Payment run header", "FI", "ok"),
    StdTable("REGUP", "Payment run items", "FI", "ok"),
    StdTable("UKMBP_CMS", "FSCM credit profile", "FSCM", "ok"),
    StdTable("UKMBP_CMS_SGM", "FSCM credit segment", "FSCM", "ok"),
    StdTable("UKM_ITEM", "FSCM credit exposure items", "FSCM", "ok"),
    # --- SD ----------------------------------------------------------------------------------
    StdTable("VBAK", "Sales document header", "SD", "changed", "", "S4TWL - VBUK status fields moved into VBAK", "Read status fields (GBSTK, LFSTK...) from VBAK instead of VBUK."),
    StdTable("VBAP", "Sales document item", "SD", "changed", "", "S4TWL - VBUP status fields moved into VBAP", "Read item status from VBAP."),
    StdTable("VBUK", "Sales document header status", "SD", "replaced", "VBAK / LIKP / VBRK status fields", "S4TWL - Elimination of status tables VBUK/VBUP", "Replace VBUK reads with the status fields on VBAK/LIKP/VBRK; VBUK is a compatibility view without data."),
    StdTable("VBUP", "Sales document item status", "SD", "replaced", "VBAP / LIPS / VBRP status fields", "S4TWL - Elimination of status tables VBUK/VBUP", "Replace VBUP reads with status fields on the item tables."),
    StdTable("KONV", "Pricing conditions (transaction data)", "SD", "replaced", "PRCD_ELEMENTS", "S4TWL - KONV replaced by PRCD_ELEMENTS", "Read/write PRCD_ELEMENTS (or CDS I_SalesDocItemPrcgElmnt); KONV is a compatibility view."),
    StdTable("PRCD_ELEMENTS", "Pricing elements", "SD", "ok"),
    StdTable("VBFA", "Sales document flow", "SD", "changed", "", "S4TWL - Document flow simplified (fewer entries)", "Do not rely on VBFA entries for all follow-on documents; use CDS I_SalesDocumentFlow."),
    StdTable("VBKD", "Sales business data", "SD", "ok"),
    StdTable("VBPA", "Sales partners", "SD", "ok"),
    StdTable("VBEP", "Schedule lines", "SD", "ok"),
    StdTable("LIKP", "Delivery header", "SD", "changed", "", "S4TWL - status fields added", ""),
    StdTable("LIPS", "Delivery item", "SD", "ok"),
    StdTable("VBRK", "Billing document header", "SD", "changed", "", "S4TWL - status fields added", ""),
    StdTable("VBRP", "Billing document item", "SD", "ok"),
    StdTable("TVKO", "Sales organisations", "SD", "ok"),
    StdTable("T685A", "Condition types", "SD", "ok"),
    StdTable("ONRVB", "Object numbers sales documents", "SD", "ok"),
    StdTable("JEST", "Object status", "CO/PP", "ok"),
    StdTable("VBREVE", "Revenue recognition lines", "SD", "replaced", "Event-based revenue recognition / RAR", "S4TWL - SD Revenue Recognition not available", "Move to RAR or event-based RevRec."),
    StdTable("NAST", "Output conditions", "SD/MM", "changed", "Output management (BRF+)", "S4TWL - Output management", "New output management (APOC/BRF+) is the target; NAST still works for many objects."),
    # --- MM / logistics -----------------------------------------------------------------------
    StdTable("MARA", "Material master general", "MM", "changed", "", "S4TWL - MATNR length 40", "Ensure MATNR fields/interfaces handle 40 characters."),
    StdTable("MARC", "Material plant data", "MM", "changed", "", "S4TWL - MATNR length 40 / field changes", ""),
    StdTable("MARD", "Material storage location stock", "MM", "compat", "MATDOC (aggregated on the fly)", "S4TWL - Inventory management data model (MATDOC)", "Read stock via MATDOC-based CDS (I_MaterialStock) - MARD stock fields are aggregates."),
    StdTable("MAKT", "Material descriptions", "MM", "ok"),
    StdTable("MBEW", "Material valuation", "MM", "compat", "ACDOCA_M_EXTRACT / MBEW aggregate", "S4TWL - Material Ledger mandatory", "Valuation actuals live in ACDOCA/ML."),
    StdTable("MKPF", "Material document header", "MM", "compat", "MATDOC", "S4TWL - MATDOC replaces MKPF/MSEG", "Read MATDOC or CDS I_MaterialDocumentHeader; no writes."),
    StdTable("MSEG", "Material document item", "MM", "compat", "MATDOC", "S4TWL - MATDOC replaces MKPF/MSEG", "Read MATDOC / CDS; no writes."),
    StdTable("MATDOC", "Material documents", "MM", "ok"),
    StdTable("MCHB", "Batch stock", "MM", "compat", "MATDOC", "S4TWL - Inventory data model", "Read via MATDOC-based CDS."),
    StdTable("MSKA", "Sales order stock", "MM", "compat", "MATDOC", "S4TWL - Inventory data model", ""),
    StdTable("EKKO", "Purchasing document header", "MM", "ok"),
    StdTable("EKPO", "Purchasing document item", "MM", "changed", "", "S4TWL - MATNR length 40", ""),
    StdTable("EKET", "PO schedule lines", "MM", "ok"),
    StdTable("EKBE", "PO history", "MM", "ok"),
    StdTable("EBAN", "Purchase requisition", "MM", "ok"),
    StdTable("EINA", "Purchasing info record general", "MM", "ok"),
    StdTable("LFM1", "Vendor purchasing data", "MM", "changed", "BUT000 / CVI", "S4TWL - Business Partner approach", ""),
    StdTable("RSEG", "Incoming invoice item", "MM", "ok"),
    StdTable("RBKP", "Incoming invoice header", "MM", "ok"),
    # --- PP / PM / PS ---------------------------------------------------------------------------
    StdTable("AFKO", "Order header (PP/PM)", "PP", "ok"),
    StdTable("AFPO", "Order item", "PP", "ok"),
    StdTable("AFVC", "Order operations", "PP", "ok"),
    StdTable("AUFK", "Order master", "CO", "ok"),
    StdTable("RESB", "Reservations", "PP", "ok"),
    StdTable("PLAF", "Planned orders", "PP", "ok"),
    StdTable("MAST", "BOM link", "PP", "ok"),
    StdTable("STPO", "BOM item", "PP", "ok"),
    StdTable("PRPS", "WBS elements", "PS", "ok"),
    StdTable("PROJ", "Project definition", "PS", "ok"),
    StdTable("CSKS", "Cost centres", "CO", "ok"),
    StdTable("COBK", "CO document header", "CO", "compat", "ACDOCA", "S4TWL - CO in Universal Journal", ""),
    # --- HCM ---------------------------------------------------------------------------------
    StdTable("PA0001", "HR org assignment", "HCM", "changed", "", "S4TWL - HCM compatibility pack (limited maintenance)", "Plan for SuccessFactors / H4S4."),
    StdTable("PA0002", "HR personal data", "HCM", "changed", "", "S4TWL - HCM compatibility pack", ""),
    # --- BC / cross -----------------------------------------------------------------------------
    StdTable("USR02", "User logon data", "BC", "ok"),
    StdTable("T100", "Messages", "BC", "ok"),
    StdTable("TSTC", "Transaction codes", "BC", "ok"),
    StdTable("DD02L", "Table definitions", "BC", "ok"),
    StdTable("DD03L", "Table fields", "BC", "ok"),
    StdTable("ADRC", "Addresses", "BC", "ok"),
    StdTable("BUT000", "Business partner general", "BC", "ok"),
    StdTable("BUT0BK", "Business partner bank details", "BC", "ok"),
    StdTable("CDHDR", "Change document header", "BC", "ok"),
    StdTable("CDPOS", "Change document items", "BC", "ok"),
    StdTable("STXH", "SAPscript text header", "BC", "ok"),
    StdTable("STXL", "SAPscript text lines", "BC", "ok"),
    StdTable("SFLIGHT", "Flight demo", "BC", "ok"),
    StdTable("SBOOK", "Flight booking demo", "BC", "ok"),
]

TABLES: dict[str, StdTable] = {t.name: t for t in _T}

# Obsolete / restricted transactions in S/4HANA (a small, high-frequency subset)
OBSOLETE_TRANSACTIONS: dict[str, str] = {
    "FD32": "Credit management moved to FSCM (UKM_BP)",
    "FD33": "Credit management moved to FSCM (UKM_BP)",
    "VKM1": "SD credit management replaced by FSCM",
    "VKM2": "SD credit management replaced by FSCM",
    "VKM3": "SD credit management replaced by FSCM",
    "VKM4": "SD credit management replaced by FSCM",
    "F.31": "Credit overview replaced by FSCM apps",
    "XK01": "Vendor creation via Business Partner (BP)",
    "XK02": "Vendor maintenance via Business Partner (BP)",
    "XK03": "Vendor display via Business Partner (BP)",
    "FK01": "Vendor creation via BP",
    "FK02": "Vendor maintenance via BP",
    "MK01": "Vendor creation via BP",
    "MK02": "Vendor maintenance via BP",
    "XD01": "Customer creation via BP",
    "XD02": "Customer maintenance via BP",
    "XD03": "Customer display via BP",
    "FD01": "Customer creation via BP",
    "FD02": "Customer maintenance via BP",
    "VD01": "Customer creation via BP",
    "VD02": "Customer maintenance via BP",
    "MB01": "Goods movement transactions replaced by MIGO",
    "MB1A": "Replaced by MIGO",
    "MB1B": "Replaced by MIGO",
    "MB1C": "Replaced by MIGO",
    "MB11": "Replaced by MIGO",
    "MB31": "Replaced by MIGO",
    "MB51": "Available but MATDOC-based apps preferred",
    "CK11N": "Material ledger / costing changes",
    "MR11": "Available; check ML impact",
}

# ABAP statements that are obsolete or disallowed in ABAP Cloud / Clean Core
OBSOLETE_STATEMENTS: list[tuple[str, str, str]] = [
    # (regex on upper-cased statement, title, remediation)
    (r"^TABLES\b", "TABLES statement (obsolete work areas)", "Declare explicit work areas with DATA ... TYPE; remove TABLES."),
    (r"\bOCCURS\s+\d+", "OCCURS internal table declaration", "Use TYPE STANDARD TABLE OF ... WITH ... KEY."),
    (r"\bWITH\s+HEADER\s+LINE\b", "Internal table WITH HEADER LINE", "Use explicit work areas and TYPE TABLE OF."),
    (r"^TYPE-POOLS\b", "TYPE-POOLS declaration", "Not needed since 7.02; remove (types are globally visible)."),
    (r"^RANGES\b", "RANGES statement", "Use TYPE RANGE OF."),
    (r"^FIELD-GROUPS\b|^INSERT\s+[A-Z0-9_]+\s+INTO\s+[A-Z0-9_]+\s*$|^EXTRACT\b", "FIELD-GROUPS / EXTRACT", "Use internal tables and sorting."),
    (r"^COMPUTE\b", "COMPUTE statement", "Use a plain assignment."),
    (r"^MOVE\s+(?!-CORRESPONDING)", "MOVE ... TO", "Use the assignment operator (=)."),
    (r"^ADD\s+.*\bTO\b|^SUBTRACT\s+.*\bFROM\b|^MULTIPLY\b|^DIVIDE\b", "ADD/SUBTRACT/MULTIPLY/DIVIDE", "Use arithmetic operators (+=, -=, *=, /=)."),
    (r"^CALL\s+FUNCTION\s+'§'\s+IN\s+UPDATE\s+TASK\b", "Update task function call", "Allowed, but review for ABAP Cloud (use RAP save sequence / released APIs)."),
    (r"^EXEC\s+SQL\b", "Native SQL (EXEC SQL)", "Use ABAP SQL or ADBC; native SQL is not released for ABAP Cloud and is DB-specific."),
    (r"^CALL\s+'SYSTEM'|^CALL\s+'[A-Z_]+'\s", "Kernel call (CALL 'xxx')", "Not allowed in ABAP Cloud; use released APIs."),
    (r"^COMMUNICATION\b|^CONTEXTS\b|^DEMAND\b|^SUPPLY\b|^INFOTYPES\b", "Obsolete statement", "Remove or replace with current constructs."),
    (r"^LEAVE\s+TO\s+LIST-PROCESSING\b|^SET\s+PF-STATUS\b|^WRITE\b", "Classic list output", "Use ALV (CL_SALV_TABLE) or Fiori; WRITE lists are not available in ABAP Cloud."),
    (r"^BREAK-POINT\b|^BREAK\s+[A-Z0-9_]+\b", "BREAK-POINT left in code", "Remove before transport."),
]

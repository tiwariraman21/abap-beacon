"""Clean Core migration advisor - classic building block -> released S/4HANA successor.

Used by the assessment findings (a concrete 'replace with'), by the business case (how much of the
remediation is 'swap the API' work) and by the FSD planner. Kept as data so it can grow every SAP
release without touching the engine."""

from __future__ import annotations

# classic (regex on the referenced name)            -> (released successor, kind, note, tier)
REPLACEMENTS: list[tuple[str, str, str, str, str]] = [
    (r"^KNA1$|^KNB1$|^KNVV$", "I_Customer / I_CustomerCompany / I_CustomerSalesArea (CDS)", "CDS", "Read through the released CDS views instead of the tables", "T2"),
    (r"^LFA1$|^LFB1$|^LFM1$", "I_Supplier / I_SupplierCompany / I_SupplierPurchasingOrg (CDS)", "CDS", "Read through the released CDS views", "T2"),
    (r"^BUT000$|^BUT020$|^ADRC$", "I_BusinessPartner / I_BusinessPartnerAddress (CDS); API_BUSINESS_PARTNER for changes", "CDS/API", "Never write BUT*/ADRC directly", "T2"),
    (r"^MARA$|^MARC$|^MARD$", "I_Product / I_ProductPlant / I_ProductStorageLocation (CDS)", "CDS", "MATNR is 40 characters in S/4HANA", "T2"),
    (r"^VBAK$|^VBAP$|^VBKD$", "I_SalesOrder / I_SalesOrderItem (CDS); API_SALES_ORDER_SRV for changes", "CDS/API", "", "T2"),
    (r"^EKKO$|^EKPO$", "I_PurchaseOrderAPI01 / I_PurchaseOrderItemAPI01 (CDS); API_PURCHASEORDER_PROCESS_SRV", "CDS/API", "", "T2"),
    (r"^BKPF$|^BSEG$|^BSIK$|^BSAK$|^BSID$|^BSAD$", "I_JournalEntry / I_OperationalAcctgDocItem / I_GLAccountLineItem (CDS on ACDOCA)", "CDS", "BSIK/BSAK/BSID/BSAD are compatibility views in S/4HANA - read ACDOCA-based CDS", "T2"),
    (r"^LIKP$|^LIPS$", "I_OutboundDelivery / I_OutboundDeliveryItem (CDS); API_OUTBOUND_DELIVERY_SRV", "CDS/API", "", "T2"),
    (r"^VBRK$|^VBRP$", "I_BillingDocument / I_BillingDocumentItem (CDS); API_BILLING_DOCUMENT_SRV", "CDS/API", "", "T2"),
    (r"^MKPF$|^MSEG$", "I_MaterialDocumentHeader / I_MaterialDocumentItem (CDS on MATDOC); API_MATERIAL_DOCUMENT_SRV", "CDS/API", "MKPF/MSEG are compatibility views", "T2"),
    (r"^BAPI_SALESORDER_CREATEFROMDAT2$|^BAPI_SALESORDER_CHANGE$", "API_SALES_ORDER_SRV (OData) or released BAPI with API state 'released'", "API", "Classic BAPI still works on-premise; released API is required for Clean Core / Cloud", "T2"),
    (r"^BAPI_PO_CREATE1$|^BAPI_PO_CHANGE$", "API_PURCHASEORDER_PROCESS_SRV (OData)", "API", "", "T2"),
    (r"^BAPI_ACC_DOCUMENT_POST$", "API_JOURNALENTRY_SRV (SOAP JournalEntryBulkCreateRequest) or released BAPI_ACC_DOCUMENT_POST", "API", "", "T2"),
    (r"^BAPI_BUPA_", "API_BUSINESS_PARTNER (OData) - A_BusinessPartner, A_BusinessPartnerAddress, A_BusinessPartnerRole", "API", "", "T2"),
    (r"^BAPI_GOODSMVT_CREATE$", "API_MATERIAL_DOCUMENT_SRV (OData)", "API", "", "T2"),
    (r"^BAPI_INCOMINGINVOICE_CREATE1?$", "API_SUPPLIERINVOICE_PROCESS_SRV (OData)", "API", "", "T2"),
    (r"^REUSE_ALV_GRID_DISPLAY(_LVC)?$|^REUSE_ALV_LIST_DISPLAY$", "CL_SALV_TABLE (on-premise) or a RAP/Fiori list report (Clean Core)", "class", "Classic UI is not Clean-Core compliant; keep for on-premise reports, plan Fiori for new UIs", "T3"),
    (r"^SO_NEW_DOCUMENT_ATT_SEND_API1$|^SO_DOCUMENT_SEND_API1$", "CL_BCS / CL_BCS_MAIL_MESSAGE", "class", "", "T2"),
    (r"^GUI_UPLOAD$|^GUI_DOWNLOAD$|^WS_UPLOAD$|^WS_DOWNLOAD$", "CL_GUI_FRONTEND_SERVICES (on-premise) / file upload via RAP and CL_WEB_HTTP_CLIENT_MANAGER (Cloud)", "class", "", "T3"),
    (r"^POPUP_TO_CONFIRM$|^POPUP_TO_DECIDE$", "Fiori dialog / RAP action with confirmation (no dynpro pop-ups in Clean Core)", "UI", "", "T3"),
    (r"^RFC_READ_TABLE$", "Released CDS views via OData or a dedicated RFC-enabled function with a fixed field list", "API", "RFC_READ_TABLE is a security and support risk", "T3"),
    (r"^CALL TRANSACTION$|^BDC_", "Released API / BAPI for the same business object; BDC only as last resort with SAP note approval", "API", "", "T3"),
    (r"^SUBMIT$", "Class method call or RAP action; SUBMIT is not available in ABAP Cloud", "pattern", "", "T3"),
    (r"^SET_UPDATE_TASK_LOCAL$|^SY-UNAME$", "cl_abap_context_info=>get_user_technical_name( )", "class", "", "T2"),
    (r"^SY-DATUM$|^SY-UZEIT$", "cl_abap_context_info=>get_system_date( ) / get_system_time( )", "class", "", "T2"),
    (r"^WRITE$", "CL_SALV_TABLE / Fiori list report (WRITE lists are not Clean Core)", "UI", "", "T3"),
]


def successor(name: str) -> dict | None:
    import re

    n = (name or "").upper().strip()
    for rx, succ, kind, note, tier in REPLACEMENTS:
        if re.search(rx, n):
            return {"classic": n, "successor": succ, "kind": kind, "note": note, "tier": tier}
    return None

"""Business language -> SAP technical vocabulary.

Used only to expand the *query*, never the documents, so a business user
typing "supplier bank details" reaches objects that mention LFBK or payee.
Entries are lower case. Later this moves to the settings table so it can be
edited per client from the Admin screen; the shape stays the same.
"""

from __future__ import annotations

SYNONYMS: dict[str, list[str]] = {
    # ageing / receivables / payables
    "ages": ["ageing", "aging", "overdue"],
    "age": ["ageing", "aging", "overdue"],
    "ageing": ["aging", "overdue", "bucket"],
    "aging": ["ageing", "overdue", "bucket"],
    "overdue": ["ageing", "aging", "due"],
    "receivable": ["customer", "bsid", "kunnr", "debtor", "ar"],
    "payable": ["vendor", "bsik", "lifnr", "creditor", "ap"],
    # business partners
    "vendor": ["supplier", "lifnr", "lfa1", "lfb1", "bsik", "creditor"],
    "supplier": ["vendor", "lifnr", "lfa1", "bsik"],
    "customer": ["kunnr", "kna1", "knb1", "bsid", "debtor"],
    "partner": ["vbpa", "kunnr", "lifnr", "bp"],
    "employee": ["pernr", "pa0001", "personnel"],
    # finance
    "invoice": ["belnr", "bkpf", "bseg", "billing", "vbrk", "vbrp"],
    "payment": ["payee", "beneficiary", "bank", "remittance", "regup", "reguh"],
    "bank": ["lfbk", "payee", "beneficiary", "iban", "ifsc", "bnka"],
    "beneficiary": ["payee", "bank", "vendor"],
    "ledger": ["acdoca", "bkpf", "bseg", "gl", "faglflexa"],
    "credit": ["ukm", "fscm", "exposure", "credit"],
    "guarantee": ["collateral", "ukm", "bank"],
    "currency": ["waers", "exchange", "rate", "convert"],
    "finance": ["fi", "accounting", "gl", "ledger"],
    # sales
    "sales": ["vbak", "vbap", "sd"],
    "order": ["vbak", "vbap", "ekko", "ekpo", "salesorder", "purchase"],
    "quotation": ["quote", "vbak", "angebot"],
    "delivery": ["likp", "lips", "shipment"],
    "billing": ["vbrk", "vbrp", "invoice"],
    "pricing": ["konv", "prcd_elements", "condition", "kona"],
    # procurement / logistics
    "purchase": ["ekko", "ekpo", "po", "mm", "requisition", "eban"],
    "material": ["matnr", "mara", "marc", "makt", "mm", "product"],
    "stock": ["mard", "mchb", "inventory", "mseg"],
    "goods": ["movement", "mseg", "mkpf", "matdoc"],
    # technical
    "report": ["alv", "list", "grid", "display", "output"],
    "list": ["alv", "report", "grid"],
    "odata": ["gateway", "dpc", "mpc", "iwbep", "rest", "service", "fiori"],
    "fiori": ["odata", "ui5", "gateway", "cds"],
    "service": ["odata", "rest", "api", "gateway", "web"],
    "api": ["rest", "http", "service", "odata", "interface", "bapi"],
    "interface": ["aif", "idoc", "inbound", "outbound", "api", "proxy"],
    "idoc": ["edidc", "edidd", "interface", "aif"],
    "proxy": ["pi", "xi", "sprx", "interface"],
    "date": ["datum", "erdat", "conversion", "format", "budat"],
    "log": ["applog", "logging", "bal", "message"],
    "logging": ["applog", "log", "bal", "message"],
    "error": ["exception", "cx", "raise", "message"],
    "exception": ["error", "cx", "raise"],
    "encrypt": ["aes", "encryption", "hash", "decrypt", "secure"],
    "encryption": ["aes", "encrypt", "hash", "decrypt"],
    "table": ["maintenance", "tabl", "tmg", "structure"],
    "maintenance": ["tmg", "sm30", "table"],
    "email": ["mail", "bcs", "send"],
    "form": ["smartform", "adobe", "pdf", "print"],
    "print": ["form", "smartform", "adobe", "output"],
    "job": ["background", "batch", "sm36", "schedule"],
    "workflow": ["swc", "swe", "wapi", "approval"],
    "approval": ["workflow", "release", "approve"],
    "authorization": ["authority", "auth", "role", "suso"],
    "security": ["authority", "encryption", "auth"],
    "unit": ["test", "abap unit", "testing"],
    "flight": ["booking", "sflight", "demo"],
    "salesforce": ["sf", "crm", "external"],
    "duplicate": ["dedupe", "repeated", "similar"],
}


def expand(tokens: list[str]) -> list[str]:
    """Return synonym tokens for a list of query tokens (deduplicated)."""
    extra: list[str] = []
    for token in tokens:
        for synonym in SYNONYMS.get(token, []):
            if synonym not in tokens and synonym not in extra:
                extra.append(synonym)
    return extra

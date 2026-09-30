"""Auto-detection of names that the guardrails should mask.

The term list on Settings -> Guardrails only protects names it has been told
about; every new FSD from a new customer brings a new one. This module reads
the document itself and proposes candidates:

  document control    Project Name / Customer / Client / Company / Target Readership
                      values ("Saudi Aramco Project Team" -> "Saudi Aramco")
  phrases             "<X> System", "<X> Project Team", "from <X> to <Y> System",
                      "for the <X> business", "<X> landscape", "<X> Ltd/Bank/..."
  acronyms            ALL-CAPS tokens in the title and first lines that are not
                      SAP vocabulary, transaction codes, tables or object names
                      (ASMO, but not BAPI, ODATA, PRD, CDHDR, ZSCM_ASMO_VEN_ST)

The result is a plain list of strings. The FSD service stores it with the
analysis, masks it on display straight away and lets the user add the names to
the permanent list with one click. Detection is deliberately conservative:
false positives are visible and easy to ignore; a missed name is what we are
trying to prevent, so the acronym rule errs on the side of masking.
"""

from __future__ import annotations

import re

from atlas.reference.sap_objects import TABLES

# words that look like names but are vocabulary, not customers
_VOCAB = {
    # SAP and technology
    "SAP", "ABAP", "BAPI", "BAPIS", "API", "APIS", "RFC", "IDOC", "IDOCS", "ALE", "EDI", "ODATA", "REST", "SOAP", "JSON", "XML", "HTTP", "HTTPS", "URL", "WSDL", "CDS", "RAP", "BADI",
    "BADIS", "CVI", "MDG", "DRF", "SOA", "PI", "PO", "CPI", "BTP", "GUI", "ALV", "SALV", "BCS", "AIF", "SLG", "SLG1", "ST22", "SE38", "SE80", "SE11", "SM36", "SM37", "SM59", "SM30",
    "SPROXY", "SOAMANAGER", "SAML", "OAUTH", "OAUTH2", "JWT", "SSL", "TLS", "VPN", "LDAP", "SSO", "UI", "UI5", "FIORI", "HANA", "S4HANA", "ECC", "ERP", "CRM", "SRM", "SCM", "EWM",
    "BW", "BI", "PLM", "GRC", "HCM", "HR", "FI", "CO", "SD", "MM", "PP", "PM", "QM", "PS", "WM", "LE", "TM", "AA", "GL", "AP", "AR", "FSCM", "TR", "CA", "BC", "IM", "BP", "MD",
    "BOR", "BOM", "PDF", "CSV", "XLSX", "XLS", "TXT", "DOCX", "ZIP", "FTP", "SFTP", "SMTP", "IP", "DNS", "DB", "SQL", "ID", "IDS", "GUID", "UUID", "KPI", "KPIS", "SLA", "SLAS",
    "ETL", "ELT", "OLAP", "AI", "ML", "LLM", "IT", "QA", "UAT", "SIT", "DEV", "QAS", "PRD", "PROD", "PRE", "PRC", "TST", "TEST", "SBX", "TRN", "GOLDEN", "SANDBOX",
    "FSD", "TSD", "TDD", "BRD", "SOW", "RACI", "RFP", "RFI", "POC", "MVP", "ROI", "TCO", "CR", "CRS", "RICEF", "RICEFW", "WRICEF", "OSS", "SNOTE", "SPAU", "SPDD",
    "GET", "POST", "PUT", "PATCH", "DELETE", "OK", "NA", "TBD", "TBC", "WIP", "FYI", "ASAP", "EOD", "COB", "AM", "UTC", "IST", "GMT", "CET", "EST",
    "USD", "EUR", "INR", "AED", "SAR", "GBP", "SGD", "AUD", "JPY", "CNY", "KSA", "UAE", "USA", "UK", "EU", "GCC", "APAC", "EMEA", "LATAM", "MENA",
    "BUKRS", "WERKS", "KUNNR", "LIFNR", "MATNR", "VBELN", "EBELN", "BELNR", "GJAHR", "PERNR", "VKORG", "EKORG", "MANDT", "UNAME", "ERNAM", "AENAM",
    "SELECT", "INSERT", "UPDATE", "MODIFY", "COMMIT", "ROLLBACK", "LOOP", "ENDLOOP", "CALL", "FUNCTION", "METHOD", "CLASS", "REPORT", "PROGRAM", "TABLE", "VIEW", "FIELD",
    "MANDATORY", "OPTIONAL", "YES", "NO", "TRUE", "FALSE", "NULL", "ALL", "ANY", "NEW", "OLD", "MAX", "MIN", "SUM", "AVG", "COUNT",
    "CRUD", "BASIC", "AUTH", "AUTHENTICATION", "AUTHORIZATION", "ROLE", "ROLES", "USER", "USERS", "ADMIN", "SUPPORT", "TEAM", "GROUP", "SYSTEM", "SYSTEMS",
    "NOTE", "NOTES", "DRAFT", "FINAL", "APPROVED", "REVIEWED", "VERSION", "STATUS", "DATE", "NAME", "SIGNATURE", "PAGE", "PAGES", "TOTAL", "SUMMARY",
    "SME", "SMES", "PMO", "CEO", "CFO", "CIO", "CTO", "COO", "VP", "SVP", "AVP", "HOD", "BA", "FC", "TC", "PMP", "BPO", "KT", "HLD", "LLD",
    "AES", "AES128", "AES256", "RSA", "SHA", "SHA256", "MD5", "HMAC", "PGP", "GPG", "IFSC", "IBAN", "SWIFT", "BIC", "NEFT", "RTGS", "IMPS", "UPI", "ACH", "SEPA", "PAN", "GST", "GSTIN", "TIN", "VAT", "TDS",
    "MICR", "CIN", "LEI", "DUNS", "ISO", "IEC", "ANSI", "UTF", "ASCII", "EBCDIC",
}
# capitalised English / SAP words that precede "System", "Project", "business" without being a name
_COMMON_CAPS = {
    "The", "This", "That", "These", "Those", "Source", "Target", "Sender", "Receiver", "Legacy", "New", "Old", "Current", "Existing", "Future", "Central", "Local", "Remote", "External",
    "Internal", "Third", "Party", "Downstream", "Upstream", "Business", "Partner", "Sales", "Purchase", "Vendor", "Customer", "Supplier", "Material", "Finance", "Financial", "Accounting",
    "Bank", "Payment", "Order", "Invoice", "Master", "Data", "Document", "Change", "Changes", "Interface", "Integration", "Functional", "Technical", "Specification", "Requirement",
    "Requirements", "Design", "Solution", "Process", "Project", "Team", "Members", "Member", "Management", "Manager", "Owner", "Reviewers", "Approvers", "Approval", "Author", "Created",
    "Updated", "Edited", "Last", "First", "Version", "Date", "Status", "Page", "Pages", "Number", "Using", "Via", "From", "Between", "Within", "Across", "For", "And", "With", "Into",
    "Standard", "Custom", "Both", "All", "Each", "Every", "Any", "Same", "Real", "Time", "Batch", "Daily", "Delta", "Manual", "Automatic", "Event", "Driven", "Mesh", "Cloud", "Public",
    "Private", "Enterprise", "Global", "Regional", "Group", "Company", "Client", "Plant", "Code", "Codes", "Overview", "Scope", "Purpose", "Objective", "Objectives", "Background",
    "Introduction", "Summary", "Appendix", "Glossary", "Assumptions", "Dependencies", "Risks", "Testing", "Test", "Training", "Documentation", "Rollout", "Fallback", "Landscape",
    "Flow", "Mapping", "Logic", "Fields", "Field", "Key", "Objects", "Object", "Involved", "Modes", "Mode", "Synchronization", "Synchronisation", "Consistency", "Compatibility",
    "Considerations", "Strategy", "Plan", "Sign", "Off", "Control", "History", "Revision", "Distribution", "Readership", "Reviewer", "Approver", "Role", "Name", "Signature",
    "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "Saturday", "Sunday", "SAP", "ABAP", "Fiori", "HANA", "Gateway", "Workflow", "Salesforce", "Microsoft", "Oracle", "Google", "Amazon", "Azure", "AWS", "Workday", "Ariba", "Concur",
    "SuccessFactors", "Excel", "Word", "Outlook", "Windows", "Linux", "Java", "Python", "Basis", "Security", "Authorization", "Authorisation", "Error", "Handling", "Logging", "Log",
    "Audit", "Reconciliation", "Retry", "Alert", "Notification", "Email", "Address", "Classification", "Account", "Groups", "Roles", "Category", "Organization",
    "Organisation", "Person", "Unit", "Units", "Table", "Tables", "Report", "Reports", "Program", "Programs", "Class", "Classes", "Method", "Methods", "Function", "Module", "Modules",
    "OData", "Proxy", "Service", "Services", "Web", "Rest", "Soap", "Json", "Api", "Bapi", "Idoc", "Rfc", "Cds", "Badi", "User", "Users", "Exit", "Enhancement", "Spot",
    "Selection", "Screen", "Output", "Processing", "Validation", "Validations", "Scheduling", "Performance", "Layout", "Format", "Criteria", "Parameters", "Parameter",
    "Ageing", "Aging", "Open", "Items", "Item", "Line", "Lines", "Header", "Detail", "Details", "List", "Grid", "Column", "Columns", "Total", "Totals", "Subtotal", "Subtotals",
    "Beneficiary", "Registration", "Payee", "Payments", "Creation", "Release", "Notifications", "Reminder", "Escalation", "Inbox",
    "Lead", "Architect", "Consultant", "Developer", "Analyst", "Head", "Director", "Chief", "Officer", "Sponsor", "Steering", "Committee",
    "Mr", "Mrs", "Ms", "Dr", "Prof", "Sir", "Saudi", "Indian", "Arab", "German", "British", "American", "European", "Asian", "Middle", "East", "North", "South", "West", "Kingdom", "Republic", "Emirates", "States", "United", "National", "International", "Ministry", "Government", "Authority", "Council", "Region", "City", "State", "Country",
}
_DOC_CONTROL_KEYS = ("project name", "project", "customer", "customer name", "client", "client name", "company", "company name", "target readership", "readership", "for", "prepared for",
                     "end customer", "account", "business unit", "organisation", "organization", "entity", "legal entity", "site", "location")
_STRIP_TAIL = re.compile(r"\s+(project team members?|project team|project|team members?|team|business|system|landscape|users?|it department|department|group|company|ltd\.?|limited|inc\.?|gmbh|llc|plc|pvt\.?|corp\.?|corporation|s\.a\.|sa|ag)\s*$", re.I)
_PHRASE = re.compile(r"\b([A-Z][A-Za-z0-9&\-]{1,}(?:\s+[A-Z][A-Za-z0-9&\-]{1,}){0,2})\s+(?:System|Systems|Project Team|Project|Landscape|Business|Group|Company|Team|Environment|Tenant|Instance)\b")
_FROM_TO = re.compile(r"\bfrom\s+([A-Z][A-Za-z0-9\-]{2,}(?:\s+[A-Z][A-Za-z0-9\-]{2,})?)\s+to\s+([A-Z][A-Za-z0-9\-]{2,}(?:\s+[A-Z][A-Za-z0-9\-]{2,})?)\b")
_FOR_BUSINESS = re.compile(r"\bfor (?:the )?([A-Z][A-Za-z0-9&\-]+(?:\s+[A-Z][A-Za-z0-9&\-]+){0,2}) (?:business|group|project|account|customer|client)\b")
_ORG_SUFFIX = re.compile(r"\b([A-Z][A-Za-z&\-]+(?:\s+[A-Z][A-Za-z&\-]+){0,3})\s+(?:Bank|Ltd\.?|Limited|Inc\.?|GmbH|LLC|Corporation|Corp\.?|Plc|PLC|AG|SA|S\.A\.|Pvt\.?|Group|Holdings|Petroleum|Oil|Energy|Airlines|Insurance|Telecom|Motors|Industries|Pharma|Hospital|University)\b")
_ACRONYM = re.compile(r"(?<![A-Za-z0-9_/])([A-Z][A-Z0-9]{2,9})(?![A-Za-z0-9_/])")
_TCODE = re.compile(r"^(?:[A-Z]{1,4}\d{1,3}[A-Z]?N?|F\.\d\d|F-\d\d)$")


def _clean(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" :;,.-–—")
    prev = None
    while prev != name:
        prev, name = name, _STRIP_TAIL.sub("", name).strip()
    words = name.split()
    while len(words) > 1 and (words[0] in _COMMON_CAPS or words[0].upper() in _VOCAB):     # "Target Readership Saudi Aramco" -> "Saudi Aramco"
        words = words[1:]
    return " ".join(words)


def _is_name(candidate: str) -> bool:
    if not candidate or len(candidate) < 3 or len(candidate) > 40:
        return False
    words = candidate.split()
    if all(w in _COMMON_CAPS or w.upper() in _VOCAB for w in words):
        return False
    if any(w.upper() in TABLES for w in words):
        return False
    if len(words) == 1:
        w = words[0]
        if w.upper() in _VOCAB or w in _COMMON_CAPS or _TCODE.match(w.upper()) or "_" in w or w.isdigit():
            return False
        if re.match(r"^[ZY][A-Z0-9_]", w):          # custom object names are masked by their own rule
            return False
    return True


def detect_sensitive_terms(blocks, title: str = "", known: list[str] | None = None) -> list[str]:
    """Names in the document that look like customer / project / system identifiers.
    `blocks` are reader Blocks (kind, text, section) or plain strings."""
    known_l = {k.strip().lower() for k in (known or []) if k.strip()}
    texts = [b if isinstance(b, str) else b.text for b in blocks]
    head_texts = [title] + texts[:40]                      # cover page, document control, first sections
    found: dict[str, int] = {}

    def add(name: str, score: int = 1) -> None:
        name = _clean(name)
        if _is_name(name):
            key = name.lower()
            found[key] = max(found.get(key, 0), score)
            names[key] = name

    names: dict[str, str] = {}

    # 1 document-control style "Key | Value" rows and "Key: Value" lines
    for i, t in enumerate(texts[:80]):
        cells = [c.strip() for c in re.split(r"\s*\|\s*|:\s+", t) if c.strip()]
        for j, c in enumerate(cells):
            if c.lower().rstrip(":") in _DOC_CONTROL_KEYS:
                value = cells[j + 1] if j + 1 < len(cells) else (texts[i + 1] if i + 1 < len(texts) and "|" not in texts[i + 1] and len(texts[i + 1].split()) <= 6 else "")
                if value:
                    add(value, 3)
        # a "Target Readership" row followed by the value in the next row (table split across rows)
        if t.strip().lower() in ("target readership", "readership", "prepared for", "customer", "client") and i + 1 < len(texts):
            for part in re.split(r"\s{2,}|\s*\|\s*", texts[i + 1]):
                add(part, 3)

    # 2 phrases in the whole document
    joined = "\n".join([title] + texts)
    for m in _FROM_TO.finditer(joined):
        add(m.group(1), 3)
        add(m.group(2), 3)
    for m in _FOR_BUSINESS.finditer(joined):
        add(m.group(1), 3)
    for m in _ORG_SUFFIX.finditer(joined):
        add(m.group(1), 2)
    for m in _PHRASE.finditer(joined):
        add(m.group(1), 2)

    # 3 unknown acronyms in the title / first lines
    for t in head_texts:
        for m in _ACRONYM.finditer(t):
            add(m.group(1), 1)
    # an acronym that also appears inside a custom object name (ZSCM_ASMO_VEN_ST) is very likely a customer/project code
    customs = set(re.findall(r"\b[ZY][A-Z0-9]*_([A-Z]{3,8})_[A-Z0-9_]+\b", joined))
    for c in customs:
        if c.upper() not in _VOCAB and re.search(r"(?<![A-Za-z0-9_])" + re.escape(c) + r"(?![A-Za-z0-9_])", joined):
            add(c, 2)

    # multi-word names imply their distinctive parts ("Saudi Aramco" -> "Aramco") when the part also appears on its own
    for key in list(found):
        full = names[key]
        if len(full.split()) < 2:
            continue
        without_full = re.sub(re.escape(full), " ", joined)
        for w in full.split():
            if len(w) >= 4 and w not in _COMMON_CAPS and w.upper() not in _VOCAB and re.search(r"(?<![A-Za-z0-9_])" + re.escape(w) + r"(?![A-Za-z0-9_])", without_full):
                add(w, found[key])

    return [names[k] for k, _sc in sorted(found.items(), key=lambda kv: (-kv[1], kv[0])) if k not in known_l]

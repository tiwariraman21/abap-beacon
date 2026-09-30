"""Data-protection guardrails.

One policy, two strengths:

  mask_for_ai(text)       applied to EVERYTHING that leaves the machine for an
                          AI provider - always on, cannot be disabled
  mask_for_display(text)  applied to what the UI shows and reports contain,
                          when `mask_in_ui` is on (default on)

What is masked (in addition to the technical redaction in atlas.ai.redact -
credentials, hosts, e-mails, IBANs, tokens, IPs, phone numbers):

  terms          customer / client / partner names and any other word list the
                 administrator maintains (data/config/guardrails.json); the SAP
                 system IDs known to the repository are added automatically
  system_ids     "ER6", "ER6/100", "client 100", "system QAS" patterns
  numbers        business keys that look like customer / vendor / document /
                 material numbers (6-18 digits, or digits after words such as
                 customer, vendor, KUNNR, LIFNR, VBELN, EBELN, BELNR) and
                 company codes / plants after BUKRS / WERKS
  users          SAP user names after "user", "sy-uname", "created by"

Every replacement is a stable placeholder (<customer>, <system>, <number>...)
so the meaning of a sentence survives while the identifying value does not.
A hash-based pseudonym mode keeps distinct values distinguishable for the AI
("<customer-1>" vs "<customer-2>") without revealing them.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_TERMS = [
    # examples for the sample repository - edit to your customers/partners
    "ADNOC", "Axis Bank", "Sakshamuat", "InfraBeat",
]

_ORG_SUFFIX = re.compile(r"\b([A-Z][A-Za-z&\-]+(?:\s+[A-Z][A-Za-z&\-]+){0,3})\s+(Bank|Ltd\.?|Limited|Inc\.?|GmbH|LLC|Corporation|Corp\.?|Plc|PLC|AG|SA|S\.A\.|Pvt\.?|Group|Holdings)\b")
_SID = re.compile(r"\b(?:system|sid|client|mandant)\s+((?-i:[A-Z][A-Z0-9]{2})(?:[/ ]\d{3})?|\d{3})\b", re.I)
_SID_NOT = {"SAP", "AND", "THE", "FOR", "ARE", "HAS", "CAN", "MAY", "NOT", "ALL", "ANY", "NEW", "OLD", "ERP", "ECC", "S/4", "GUI", "IDS", "API", "CRM", "SRM", "MDG", "BTP", "DEV", "QAS", "PRD", "PRC", "TST", "UAT", "SIT"}
_SID_CLIENT = re.compile(r"\b([A-Z][A-Z0-9]{2})/(\d{3})\b")
_KEYED_NUMBER = re.compile(r"\b(customer|vendor|supplier|kunnr|lifnr|vbeln|ebeln|belnr|matnr|material|document|order|invoice|po|pernr|employee|account|contract|bp|business partner)\s*(?:no\.?|number|nr\.?|id|#|:)?\s*[:=]?\s*'?(\d{4,18})'?", re.I)
_LONG_NUMBER = re.compile(r"(?<![\w.-])(\d{6,18})(?![\w.-])")
_ORG_UNIT = re.compile(r"\b(bukrs|werks|company code|plant|vkorg|ekorg|sales org(?:anisation|anization)?|purch(?:asing)? org(?:anisation|anization)?)\s*[:=]?\s*'?([A-Z0-9]{4})'?", re.I)
_USER = re.compile(r"\b(sy-uname|uname|user(?:name)?|user id|created by|changed by|last (?:edited|changed|updated)(?: by)?|updated by|reviewed by|approved by|prepared by|author|owner|ernam|aenam)(?![A-Za-z])\s*[:=|]?\s*'?((?-i:[A-Z][A-Z0-9_\-]{3,11}))'?(?![A-Za-z])", re.I)
_TRANSPORT = re.compile(r"\b([A-Z][A-Z0-9]{2}K\d{6})\b")
_FSD_TITLE_ORG = re.compile(r"\bfor the ([A-Z][A-Za-z]+) business\b")


@dataclass
class GuardPolicy:
    terms: list[str] = field(default_factory=lambda: list(DEFAULT_TERMS))
    mask_system_ids: bool = True
    mask_numbers: bool = True
    mask_org_units: bool = False          # company code / plant literals are rarely secret; opt-in
    mask_users: bool = True
    mask_org_suffix: bool = True          # "<Name> Bank / Ltd / GmbH ..." patterns without a list entry
    mask_in_ui: bool = True               # also mask what the UI shows and reports contain
    mask_source: bool = False             # also mask inside displayed source code / snippets
    auto_detect_names: bool = True        # scan uploaded FSDs for customer / project / system names and mask them at once
    pseudonyms: bool = True               # <customer-1>, <customer-2> instead of a flat <customer>
    max_source_lines_to_ai: int = 400     # never send more than this per object

    @classmethod
    def load(cls, path: Path) -> GuardPolicy:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                p = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
                p.terms = [t for t in (p.terms or []) if t.strip()]
                return p
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")


@dataclass
class MaskResult:
    text: str
    count: int
    kinds: dict[str, int]


class Guard:
    """Applies a policy. `extra_terms` (e.g. system SIDs from the database) are masked too."""

    def __init__(self, policy: GuardPolicy, extra_terms: list[str] | None = None):
        self.policy = policy
        terms = sorted({t.strip() for t in policy.terms + (extra_terms or []) if t and t.strip()}, key=len, reverse=True)
        self._terms = [(t, re.compile(r"(?<![A-Za-z0-9])" + re.escape(t).replace(r"\ ", r"[\s_\-]*") + r"(?![A-Za-z0-9])", re.I)) for t in terms]
        self._sids = {t.upper() for t in (extra_terms or []) if re.fullmatch(r"[A-Z][A-Z0-9]{2}", t.upper())}

    # ------------------------------------------------------------------ helpers

    def _tag(self, kind: str, value: str) -> str:
        if not self.policy.pseudonyms:
            return f"<{kind}>"
        h = int(hashlib.sha1(value.strip().upper().encode("utf-8", "replace")).hexdigest()[:8], 16) % 9973 + 1
        return f"<{kind}-{h}>"

    def mask(self, text: str, strong: bool = True) -> MaskResult:
        """strong=True: egress (AI). strong=False: display, honours mask_in_ui and is gentler."""
        if not text:
            return MaskResult(text, 0, {})
        if not strong and not self.policy.mask_in_ui:
            return MaskResult(text, 0, {})
        kinds: dict[str, int] = {}

        def count(kind: str) -> None:
            kinds[kind] = kinds.get(kind, 0) + 1

        out = text
        for term, rx in self._terms:
            kind = "system" if term.upper() in self._sids else "customer"
            out, n = rx.subn(lambda m, t=term, k=kind: self._tag(k, t), out)
            for _ in range(n):
                count(kind)
        if self.policy.mask_org_suffix:
            def _org(m: re.Match) -> str:
                from atlas.guard.detect import _COMMON_CAPS, _VOCAB

                words = m.group(1).split()
                if all(w in _COMMON_CAPS or w.upper() in _VOCAB for w in words):
                    return m.group(0)                       # "Account Group", "Business Partner Group" - vocabulary, not an organisation
                count("customer")
                return f"{self._tag('customer', m.group(1))} {m.group(2)}"
            out = _ORG_SUFFIX.sub(_org, out)
            out = _FSD_TITLE_ORG.sub(lambda m: (count("customer"), f"for the {self._tag('customer', m.group(1))} business")[1], out)
        if self.policy.mask_system_ids:
            out = _SID_CLIENT.sub(lambda m: (count("system"), f"{self._tag('system', m.group(1))}/{self._tag('client', m.group(2))}")[1], out)
            def _sid(m: re.Match) -> str:
                sid = m.group(1)
                if sid[:3].upper() in _SID_NOT and sid[:3].isalpha() and not self._sids.intersection({sid[:3].upper()}) and sid[:3] not in ("DEV", "QAS", "PRD", "PRC", "TST", "UAT", "SIT"):
                    return m.group(0)                       # "system and", "system SAP" - a word, not a SID
                count("system")
                lead = m.group(0)[: m.start(1) - m.start(0)]
                return lead + self._tag("system", sid)
            out = _SID.sub(_sid, out)
        if self.policy.mask_system_ids:
            out = _TRANSPORT.sub(lambda m: (count("system"), self._tag("transport", m.group(1)))[1], out)
        if self.policy.mask_numbers:
            def _keyed(m: re.Match) -> str:
                count("number")
                return m.group(0)[: m.start(2) - m.start(0)] + self._tag("number", m.group(2)) + m.group(0)[m.end(2) - m.start(0):]
            out = _KEYED_NUMBER.sub(_keyed, out)
            if strong:
                out = _LONG_NUMBER.sub(lambda m: (count("number"), self._tag("number", m.group(1)))[1], out)
        if self.policy.mask_org_units:
            out = _ORG_UNIT.sub(lambda m: (count("orgunit"), m.group(0)[: m.start(2) - m.start(0)] + self._tag("orgunit", m.group(2)) + m.group(0)[m.end(2) - m.start(0):])[1], out)
        if self.policy.mask_users:
            out = _USER.sub(lambda m: (count("user"), m.group(0)[: m.start(2) - m.start(0)] + self._tag("user", m.group(2)) + m.group(0)[m.end(2) - m.start(0):])[1], out)
        return MaskResult(out, sum(kinds.values()), kinds)

    def mask_for_ai(self, text: str) -> MaskResult:
        return self.mask(text, strong=True)

    def mask_for_display(self, text: str) -> str:
        return self.mask(text, strong=False).text


# ------------------------------------------------------------------ module-level access

_CACHE: dict[str, tuple[float, Guard]] = {}


def policy_path(settings=None) -> Path:
    from atlas.config import get_settings

    s = settings or get_settings()
    return s.data_dir / "config" / "guardrails.json"


def get_guard(settings=None, session=None) -> Guard:
    """Cached per policy-file mtime; system SIDs from the DB are added when a session is given
    or a database exists."""
    from atlas.config import get_settings

    s = settings or get_settings()
    path = policy_path(s)
    mtime = path.stat().st_mtime if path.exists() else 0.0
    key = str(path)
    cached = _CACHE.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    policy = GuardPolicy.load(path)
    extra: list[str] = []
    try:
        from sqlalchemy import select

        from atlas.db.models import System
        from atlas.db.session import session_scope

        if session is not None:
            extra = [x.sid for x in session.scalars(select(System))]
        elif s.db_path.exists():
            with session_scope(s) as ses:
                extra = [x.sid for x in ses.scalars(select(System))]
    except Exception:
        extra = []
    guard = Guard(policy, extra)
    _CACHE[key] = (mtime, guard)
    return guard


def invalidate() -> None:
    _CACHE.clear()


def mask_display(text: str) -> str:
    return get_guard().mask_for_display(text or "")


def guard_with_terms(extra_terms: list[str] | None, settings=None, session=None) -> Guard:
    """The configured guard plus names detected in one document (masked at once, before the
    user decides whether to add them to the permanent list)."""
    base = get_guard(settings, session)
    if not extra_terms or not base.policy.auto_detect_names:
        return base
    known = {t.lower() for t, _ in base._terms}
    add = [t for t in extra_terms if t.lower() not in known]
    if not add:
        return base
    return Guard(base.policy, [t for t, _ in base._terms] + add)


def add_terms(new_terms: list[str], settings=None) -> list[str]:
    """Append names to the permanent term list; returns the terms actually added."""
    path = policy_path(settings)
    policy = GuardPolicy.load(path)
    have = {t.lower() for t in policy.terms}
    added = [t for t in new_terms if t.strip() and t.lower() not in have]
    if added:
        policy.terms += added
        policy.save(path)
        invalidate()
    return added

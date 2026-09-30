"""Redaction before egress.

Anything leaving the machine passes through `redact()`. It masks credential
literals, host names, e-mail addresses, phone numbers, IBAN/account-like
numbers and long opaque tokens, and reports how many replacements it made so
the job log can show it. Code structure is untouched, so the model still
understands the program.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CRED_ASSIGN = re.compile(
    r"(\b[A-Za-z0-9_]*(?:password|passwd|pwd|secret|client_?id|client_?secret|api_?key|access_?token|auth_?token|bearer|credential|encryption_?key)[A-Za-z0-9_]*\s*(?:=|VALUE|value)\s*)'[^']*'",
    re.I,
)
_URL_HOST = re.compile(r"(https?://)([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?=[/:'\"\s]|$)", re.I)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<![A-Za-z0-9_])\+?\d[\d\s\-()]{8,}\d(?![A-Za-z0-9_])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_LONG_TOKEN = re.compile(r"'([A-Za-z0-9+/=_\-]{32,})'")
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_BASIC_AUTH = re.compile(r"(Basic\s+)[A-Za-z0-9+/=]{16,}", re.I)


@dataclass
class Redaction:
    text: str
    count: int
    kinds: dict[str, int]


def redact(text: str) -> Redaction:
    """Technical redaction + the data-protection guard (customer names, system IDs,
    business keys, users). Applied to everything that leaves the machine."""
    r = _redact_technical(text)
    try:
        from atlas.guard.policy import get_guard

        g = get_guard().mask_for_ai(r.text)
    except Exception:      # guard must never block the pipeline
        return r
    kinds = dict(r.kinds)
    for k, v in g.kinds.items():
        kinds[k] = kinds.get(k, 0) + v
    return Redaction(g.text, r.count + g.count, kinds)


def _redact_technical(text: str) -> Redaction:
    kinds: dict[str, int] = {}

    def sub(rx: re.Pattern, repl, kind: str, s: str) -> str:
        def _r(m: re.Match) -> str:
            kinds[kind] = kinds.get(kind, 0) + 1
            return repl(m) if callable(repl) else repl
        return rx.sub(_r, s)

    out = sub(_CRED_ASSIGN, lambda m: f"{m.group(1)}'<REDACTED>'", "credential", text)
    out = sub(_BASIC_AUTH, lambda m: f"{m.group(1)}<REDACTED>", "credential", out)
    out = sub(_URL_HOST, lambda m: f"{m.group(1)}<host>", "host", out)
    out = sub(_EMAIL, "<email>", "email", out)
    out = sub(_IBAN, "<account>", "account", out)
    out = sub(_LONG_TOKEN, "'<token>'", "token", out)
    out = sub(_IP, "<ip>", "ip", out)
    # phone numbers: only inside string literals, to avoid mangling numeric code
    out = re.sub(r"'([^']*)'", lambda m: "'" + sub(_PHONE, "<phone>", "phone", m.group(1)) + "'", out)
    return Redaction(out, sum(kinds.values()), kinds)

"""PII guard: a small standalone redaction pass run before any card
is saved.

SYNTHETIC DATA ONLY in fixtures - the patterns here exist to catch
accidental secrets in real session logs.

In production this step delegates to the sibling
``tool-output-pii-redactor`` project (streaming scrubber, allowlists,
hash-chained audit log). This module is a deliberately small regex
pass so this repo stays self-contained: emails and key-like tokens
only. It is not a general PII product.
"""

from __future__ import annotations

import re
from typing import List, Tuple

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
KEY_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{12,}"
    r"|xox[baprs]-[A-Za-z0-9-]{8,})\b")
ASSIGN_RE = re.compile(
    r"\b(api[_-]?key|secret|token|password)\s*[:=]\s*"
    r"(?!\[REDACTED:)(\S+)", re.IGNORECASE)
LONG_HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")

MARKERS = ("[REDACTED:email]", "[REDACTED:key]")


def find_pii(text: str) -> List[str]:
    """Kinds of PII present (``email`` / ``key``), in pattern order."""
    kinds = []
    if EMAIL_RE.search(text):
        kinds.append("email")
    if KEY_RE.search(text) or ASSIGN_RE.search(text) or LONG_HEX_RE.search(text):
        kinds.append("key")
    return kinds


def contains_pii(text: str) -> bool:
    return bool(find_pii(text))


def redact_text(text: str) -> Tuple[str, List[str]]:
    """Return ``(clean_text, kinds_redacted)``.

    Order matters: explicit assignments first (their value may itself
    look like a key), then standalone keys / long hex, then emails.
    The pass is idempotent: its own markers never re-trigger it.
    """
    kinds: List[str] = []

    def _assign(match: "re.Match[str]") -> str:
        kinds.append("key")
        return f"{match.group(1)}=[REDACTED:key]"

    clean = ASSIGN_RE.sub(_assign, text)
    if KEY_RE.search(clean):
        kinds.append("key")
        clean = KEY_RE.sub("[REDACTED:key]", clean)
    if LONG_HEX_RE.search(clean):
        if "key" not in kinds:
            kinds.append("key")
        clean = LONG_HEX_RE.sub("[REDACTED:key]", clean)
    if EMAIL_RE.search(clean):
        kinds.append("email")
        clean = EMAIL_RE.sub("[REDACTED:email]", clean)
    # Deterministic kind order for reports.
    ordered = [k for k in ("email", "key") if k in kinds]
    return clean, ordered

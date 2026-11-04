"""Extractive compression: session-log events -> memory cards.

ONE strategy only, by design: deterministic rule/keyword extraction.
An event becomes a card only when it carries an explicit cue for one
of four kinds - decision, fact, open item, error. Chatter, greetings
and tool noise produce no card. No embeddings, no LLM, no summariser:
the card text is the (redacted) source sentence, verbatim.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from redact import redact_text

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "to",
    "of", "for", "on", "in", "at", "with", "after", "before", "and",
    "or", "it", "its", "this", "that", "we", "i", "you", "will",
}

# Cue phrases stripped before deriving a subject key, so two cards
# about the same topic land on the same key even when one is phrased
# as a decision and the other as a fact.
_CUE_PHRASES = (
    "decided to", "chose to", "agreed to", "will use", "follow up on",
    "follow-up on", "still need to", "open item", "todo",
)

_LABEL_RE = re.compile(
    r"^\s*(fact|decision|error|todo|open item|note|confirmed)\s*:\s*",
    re.IGNORECASE)


def classify(text: str, event_type: str = "") -> Optional[str]:
    """Card kind for an event, or None when it carries no cue.

    Priority is error > open_item > decision > fact, so a line that
    reports a failure is never filed as a plain fact.
    """
    low = text.lower()
    if event_type == "error" or "error:" in low or "failed:" in low:
        return "error"
    if ("todo:" in low or "open item:" in low or "still need to" in low
            or "follow up:" in low or "follow-up:" in low):
        return "open_item"
    if ("decision:" in low or "decided to" in low or "chose to" in low
            or "agreed to" in low or "will use" in low):
        return "decision"
    if "fact:" in low or "confirmed:" in low or "note:" in low:
        return "fact"
    return None


def subject_key(text: str) -> str:
    """Topic key: the first three content words of the cleaned text.

    Alphabetic tokens only (so ``2.4`` and ``3.0.0`` in two firmware
    statements cannot split the key), cue phrases and stopwords
    removed. Two statements about the same topic share a key; that
    sharing is exactly what supersession keys on.
    """
    cleaned = _LABEL_RE.sub("", text.lower())
    for phrase in _CUE_PHRASES:
        cleaned = cleaned.replace(phrase, " ")
    words = [w for w in re.findall(r"[a-z]+", cleaned)
             if w not in STOPWORDS and len(w) > 1]
    return "-".join(words[:3]) if words else "general"


def extract_cards(events: List[Dict]) -> List[Dict]:
    """Extract one card per cued event, in input order.

    Card ids are deterministic: ``card-<session>-<nnn>`` where nnn is
    the per-session extraction sequence (001-based). The PII guard
    runs here, before a card object exists - nothing unredacted is
    ever handed to the store.
    """
    cards: List[Dict] = []
    counters: Dict[str, int] = {}
    for index, event in enumerate(events):
        text = str(event.get("text", "")).strip()
        if not text:
            continue
        kind = classify(text, str(event.get("type", "")))
        if kind is None:
            continue
        session = str(event.get("session_id", "unknown"))
        counters[session] = counters.get(session, 0) + 1
        clean, redacted_kinds = redact_text(text)
        cards.append({
            "card_id": f"card-{session}-{counters[session]:03d}",
            "session_id": session,
            "created_at": str(event.get("ts", "")),
            "kind": kind,
            "text": clean,
            "subject_key": subject_key(text),
            "superseded": False,
            "superseded_by": None,
            "source_index": index,
            "redactions": redacted_kinds,
        })
    return cards

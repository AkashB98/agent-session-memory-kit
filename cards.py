"""Memory cards: schema, validation, supersession, JSON store.

A card is one JSON file in a cards directory - no database. Files
are written canonically (sorted keys) so a store is diffable and an
ingest is byte-reproducible.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Dict, List

from redact import contains_pii

KINDS = ("decision", "fact", "open_item", "error")
REQUIRED_FIELDS = (
    "card_id", "session_id", "created_at", "kind", "text",
    "subject_key", "superseded", "superseded_by", "source_index",
    "redactions",
)


def validate_card(card) -> List[str]:
    """Schema / safety issues for one card (empty = valid)."""
    if not isinstance(card, dict):
        return ["card is not a JSON object"]
    issues = []
    for field in REQUIRED_FIELDS:
        if field not in card:
            issues.append(f"missing field: {field}")
    if issues:
        return issues
    if card["kind"] not in KINDS:
        issues.append(f"unknown kind: {card['kind']}")
    if not isinstance(card["superseded"], bool):
        issues.append("superseded must be a bool")
    if not isinstance(card["text"], str) or not card["text"].strip():
        issues.append("text must be a non-empty string")
    elif contains_pii(card["text"]):
        issues.append("text still contains PII (email or key-like token)")
    if card["superseded"] and not card["superseded_by"]:
        issues.append("superseded card must name superseded_by")
    if not card["superseded"] and card["superseded_by"]:
        issues.append("active card must not name superseded_by")
    return issues


def validate_cards(cards: List[Dict]) -> List[str]:
    issues: List[str] = []
    seen = set()
    for card in cards:
        cid = card.get("card_id", "?") if isinstance(card, dict) else "?"
        for issue in validate_card(card):
            issues.append(f"{cid}: {issue}")
        if cid in seen:
            issues.append(f"{cid}: duplicate card_id")
        seen.add(cid)
    return issues


def apply_supersession(cards: List[Dict]) -> List[Dict]:
    """Newest card per subject_key wins; older ones are retained,
    marked superseded, and point at the winner.

    Ordering is (created_at, card_id) so a timestamp tie still has a
    single deterministic winner. Input is not mutated.
    """
    out = [copy.deepcopy(c) for c in cards]
    out.sort(key=lambda c: (c["created_at"], c["card_id"]))
    by_subject: Dict[str, List[Dict]] = {}
    for card in out:
        by_subject.setdefault(card["subject_key"], []).append(card)
    for group in by_subject.values():
        winner = group[-1]
        for card in group:
            if card is winner:
                card["superseded"] = False
                card["superseded_by"] = None
            else:
                card["superseded"] = True
                card["superseded_by"] = winner["card_id"]
    return out


def active_cards(cards: List[Dict]) -> List[Dict]:
    """Cards eligible for retrieval/injection (never superseded)."""
    return [c for c in cards if not c["superseded"]]


def canonical(card: Dict) -> str:
    return json.dumps(card, sort_keys=True)


def save_cards(cards: List[Dict], cards_dir: str) -> None:
    os.makedirs(cards_dir, exist_ok=True)
    for card in cards:
        path = os.path.join(cards_dir, f"{card['card_id']}.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canonical(card) + "\n")


def load_cards(cards_dir: str) -> List[Dict]:
    """Load every ``*.json`` card, sorted by filename (deterministic)."""
    cards = []
    for name in sorted(os.listdir(cards_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(cards_dir, name), encoding="utf-8") as fh:
            cards.append(json.load(fh))
    return cards

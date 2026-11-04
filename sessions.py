"""Session logs: JSONL loading and the ingest pipeline.

A session log is JSONL - one event per line:
``{"session_id": ..., "ts": ..., "role": ..., "type": ..., "text": ...}``
Fixtures are fictional Helios Home agent sessions.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

from cards import apply_supersession, save_cards
from extract import extract_cards

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_DIR = os.path.join(HERE, "fixtures")


def load_events(path: str) -> List[Dict]:
    events = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{path}:{lineno}: bad JSON: {exc}") from exc
            if not isinstance(event, dict) or "text" not in event:
                raise ValueError(f"{path}:{lineno}: event needs a text field")
            events.append(event)
        return events


def fixture_paths() -> List[str]:
    return [os.path.join(FIXTURE_DIR, name)
            for name in sorted(os.listdir(FIXTURE_DIR))
            if name.startswith("session_") and name.endswith(".jsonl")]


def fixture_events() -> List[Dict]:
    events: List[Dict] = []
    for path in fixture_paths():
        events.extend(load_events(path))
    return events


def ingest_events(events: List[Dict]) -> List[Dict]:
    """Events -> extracted, redacted, supersession-resolved cards."""
    return apply_supersession(extract_cards(events))


def ingest_files(paths: List[str], cards_dir: str = None) -> List[Dict]:
    events: List[Dict] = []
    for path in paths:
        events.extend(load_events(path))
    cards = ingest_events(events)
    if cards_dir:
        save_cards(cards, cards_dir)
    return cards

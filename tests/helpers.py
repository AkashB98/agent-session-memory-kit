"""Shared card/event builders for the test suite (not a test module)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def card(card_id="card-t-001", session_id="t", created_at="2026-01-01T00:00:00Z",
         kind="fact", text="Fact: router firmware version is 1.0.",
         subject_key="router-firmware-version", superseded=False,
         superseded_by=None, source_index=0, redactions=None):
    return {"card_id": card_id, "session_id": session_id,
            "created_at": created_at, "kind": kind, "text": text,
            "subject_key": subject_key, "superseded": superseded,
            "superseded_by": superseded_by, "source_index": source_index,
            "redactions": list(redactions or [])}


def event(text, session_id="s1", ts="2026-01-01T00:00:00Z",
          type="message", role="assistant"):
    return {"session_id": session_id, "ts": ts, "role": role,
            "type": type, "text": text}

"""End-to-end demo: ingest -> supersession -> retrieve -> inject
-> check -> serve.

SYNTHETIC DATA ONLY (fictional Helios Home agent sessions). Runs
fully offline; the serve round-trip is loopback-only on an ephemeral
port. Every stage asserts.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cards import active_cards  # noqa: E402
from cli import EXIT_OK, main as cli_main, make_server, reset_state  # noqa: E402
from retrieve import inject, retrieve  # noqa: E402
from sessions import fixture_events, ingest_events  # noqa: E402


def _request(port: int, path: str, payload=None, method: str = "GET"):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read())


def main() -> None:
    print("== 1. ingest fictional Helios Home session logs ==")
    cards = ingest_events(fixture_events())
    again = ingest_events(fixture_events())
    assert cards == again, "ingest must be deterministic"
    superseded = [c for c in cards if c["superseded"]]
    print(f"   {len(cards)} cards extracted, {len(superseded)} superseded, "
          f"{len(active_cards(cards))} active")
    assert len(cards) == 12 and len(superseded) == 1, cards

    print("\n== 2. supersession: firmware 2.4.1 is stale, 3.0.0 wins ==")
    stale = superseded[0]
    assert "2.4.1" in stale["text"], stale
    assert stale["superseded_by"] == "card-helios-002-001", stale
    print(f"   {stale['card_id']} -> superseded_by {stale['superseded_by']}")

    print("\n== 3. PII guard: planted email + key never reached a card ==")
    blob = json.dumps(cards)
    assert "helpdesk@helioshome.example" not in blob
    assert "helios-case-4821" not in blob
    assert "[REDACTED:email]" in blob and "[REDACTED:key]" in blob
    print("   support card carries [REDACTED:email] / [REDACTED:key] only")

    print("\n== 4. retrieve for a new session: 'router firmware version' ==")
    results = retrieve(cards, "router firmware version", k=3)
    assert results and results[0]["card_id"] == "card-helios-002-001", results
    assert all(r["card_id"] != stale["card_id"] for r in results)
    for r in results:
        print(f"   {r['score']:.3f}  {r['card_id']}  {r['text']}")

    print("\n== 5. inject under a 60-token budget (never exceeded) ==")
    block = inject(cards, "router firmware version", budget_tokens=60)
    assert block["used_tokens"] <= 60, block
    assert stale["card_id"] not in block["card_ids"], block
    print(f"   used {block['used_tokens']}/60 tokens, "
          f"cards={block['card_ids']}")
    print("   " + block["text"].replace("\n", "\n   "))

    print("\n== 6. CLI check gate on the fixture store ==")
    code = cli_main(["check"])
    code_err = cli_main(["check", "--cards-dir", "/tmp/no-such-cards-xyz"])
    print(f"   fixtures={code} missing-dir={code_err}")
    assert code == EXIT_OK and code_err == 2

    print("\n== 7. live localhost serve round-trip ==")
    reset_state(cards)
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, health = _request(port, "/health")
        assert status == 200 and health == {"status": "ok"}
        status, served = _request(
            port, "/retrieve",
            payload={"query": "router firmware version", "k": 3},
            method="POST")
        assert status == 200
        assert served["results"] == results, "served must match local"
        print("   POST /retrieve matches local retrieve exactly")
    finally:
        server.shutdown()
        server.server_close()
        reset_state()

    print("\nDemo OK: ingest, supersession, PII guard, retrieve, "
          "inject, check and serve verified.")


if __name__ == "__main__":
    main()

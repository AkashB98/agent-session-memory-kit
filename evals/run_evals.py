"""Golden evals for agent-session-memory-kit.

SYNTHETIC DATA ONLY (fictional Helios Home agent sessions). Every
eval is deterministic: run_evals.py writes eval_report.json and the
file must be byte-identical across runs. No timestamps, ports, or
temp paths enter the report - only names, booleans, pinned counts,
scores and hashes.

E1-E4 pin the fixture ingest (extraction, supersession, PII guard).
E5-E7 pin retrieval quality on a planted corpus (recall@k /
precision@k, tie-breaking). E8-E9 pin the token budget and the
staleness guarantee (superseded cards are never injected). E10-E13
pin the token estimator, the CLI check gate, the serve round-trip,
and end-to-end determinism.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cards import save_cards, validate_cards  # noqa: E402
from cli import EXIT_ERROR, EXIT_FAIL, EXIT_OK, main as cli_main, make_server, reset_state  # noqa: E402
from extract import subject_key  # noqa: E402
from retrieve import (estimate_tokens, inject, recall_precision_at_k,  # noqa: E402
                      retrieve)
from sessions import fixture_events, ingest_events  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = []


def check(name, passed, detail=""):
    RESULTS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return passed


def _run_cli(argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cli_main(argv)


def _mk(cid, subj, text, kind="fact", superseded=False, by=None):
    return {"card_id": cid, "session_id": "planted",
            "created_at": "2026-01-01T00:00:00Z", "kind": kind,
            "text": text, "subject_key": subj, "superseded": superseded,
            "superseded_by": by, "source_index": 0, "redactions": []}


PLANTED = [
    _mk("card-p-001", "router-firmware-version",
        "Fact: router firmware version is 3.0.0 on the hallway router."),
    _mk("card-p-002", "hallway-router-reboot",
        "Decision: enable nightly reboot for the hallway router after "
        "the firmware update.", kind="decision"),
    _mk("card-p-003", "hallway-router-update",
        "Fact: hallway router firmware update finished without errors "
        "on Tuesday."),
    _mk("card-p-004", "thermostat-night-schedule",
        "Fact: thermostat night schedule is set to 19 degrees on weekdays."),
    _mk("card-p-005", "garage-camera-recording",
        "Decision: garage camera recording stays local instead of in "
        "the cloud.", kind="decision"),
    _mk("card-p-006", "front-door-lock",
        "Fact: front door lock battery level is 82 percent after the "
        "spring check."),
    _mk("card-p-007", "kitchen-sensor-battery",
        "TODO: follow up on the kitchen sensor battery replacement "
        "next week.", kind="open_item"),
    _mk("card-p-008", "support-contact-hub",
        "Fact: the support contact for the hub answers billing "
        "questions on weekdays."),
]
RELEVANT = ["card-p-001", "card-p-002", "card-p-003"]
QUERY = "router firmware version hallway"


def main():
    print("== golden evals: agent-session-memory-kit ==")
    cards = ingest_events(fixture_events())

    # E1: fixture ingest pinned (15 events -> 12 cards, 11 active)
    kinds = {}
    for c in cards:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    check("E1 fixture ingest pinned (12 cards; fact 5/decision 3/open 2/error 2)",
          len(cards) == 12
          and kinds == {"fact": 5, "decision": 3, "open_item": 2, "error": 2}
          and validate_cards(cards) == [],
          f"kinds={kinds}")

    # E2: supersession pinned (2.4.1 stale, retained, points at 3.0.0)
    stale = [c for c in cards if c["superseded"]]
    check("E2 supersession pinned (card-helios-001-001 -> card-helios-002-001)",
          len(stale) == 1
          and stale[0]["card_id"] == "card-helios-001-001"
          and stale[0]["superseded_by"] == "card-helios-002-001"
          and "2.4.1" in stale[0]["text"])

    # E3: subject keys pinned for the fixture store
    keys = sorted(c["subject_key"] for c in cards)
    check("E3 subject keys pinned (firmware pair shares one key)",
          keys.count("router-firmware-version") == 2
          and subject_key("Fact: router firmware version is 9.9 on it.")
          == "router-firmware-version",
          f"keys={keys}")

    # E4: PII guard (planted email + key in session 1 never saved)
    blob = json.dumps(cards)
    support = next(c for c in cards
                   if c["subject_key"] == "support-contact-hub")
    check("E4 PII guard (email + key redacted before save)",
          "helpdesk@helioshome.example" not in blob
          and "helios-case-4821" not in blob
          and support["redactions"] == ["email", "key"]
          and "[REDACTED:email]" in support["text"])

    # E5: retrieval quality headline - recall@3 / precision@3 perfect
    top3 = retrieve(PLANTED, QUERY, k=3)
    rp3 = recall_precision_at_k([r["card_id"] for r in top3], RELEVANT, 3)
    check("E5 recall@3 = 1.0 and precision@3 = 1.0 on planted corpus",
          [r["card_id"] for r in top3] == RELEVANT
          and rp3 == {"k": 3, "hits": 3, "recall": 1.0, "precision": 1.0},
          f"rp3={rp3}")

    # E6: recall@2 is partial by construction (2 of 3 relevant seen)
    top2 = retrieve(PLANTED, QUERY, k=2)
    rp2 = recall_precision_at_k([r["card_id"] for r in top2], RELEVANT, 2)
    check("E6 recall@2 = 0.6667, precision@2 = 1.0",
          rp2 == {"k": 2, "hits": 2, "recall": 0.6667, "precision": 1.0},
          f"rp2={rp2}")

    # E7: score ties break on card_id, not corpus order
    forward = retrieve(PLANTED, QUERY, k=3)
    reverse = retrieve(list(reversed(PLANTED)), QUERY, k=3)
    check("E7 tie-break determinism (reversed corpus, same ranking)",
          forward == reverse
          and forward[1]["score"] == forward[2]["score"],
          f"tied_score={forward[1]['score']}")

    # E8: token budget never exceeded (sweep) + pinned 60-token inject
    queries = [QUERY, "thermostat night schedule", "kitchen sensor battery",
               "door lock garage camera"]
    sweep_ok = all(
        inject(cards, q, budget_tokens=b)["used_tokens"] <= b
        for q in queries for b in range(0, 201, 7))
    block = inject(cards, QUERY, budget_tokens=60)
    check("E8 budget sweep 0..200 never exceeded; 60-token inject pinned",
          sweep_ok
          and block["used_tokens"] == 36
          and block["card_ids"] == ["card-helios-002-001",
                                    "card-helios-002-002"],
          f"used={block['used_tokens']}")

    # E9: staleness - the superseded card is never retrieved/injected
    stale_id = "card-helios-001-001"
    stale_queries = [QUERY, "router firmware 2.4.1", "hallway router",
                     "firmware version"]
    never = all(
        stale_id not in [r["card_id"] for r in retrieve(cards, q, k=10)]
        and stale_id not in inject(cards, q, budget_tokens=500)["card_ids"]
        for q in stale_queries)
    check("E9 superseded card never retrieved or injected (staleness)",
          never)

    # E10: token estimator pinned (ceil(words * 1.3))
    check("E10 token estimator pinned (0/2/4/13)",
          estimate_tokens("") == 0 and estimate_tokens("one") == 2
          and estimate_tokens("one two three") == 4
          and estimate_tokens(" ".join(["w"] * 10)) == 13)

    # E11: CLI check exit codes 0 / 1 / 2
    tmp = tempfile.mkdtemp(prefix="memkit-evals-")
    bad = _mk("card-p-bad", "support-contact-hub",
              "Fact: mail a@b.example.com for details.")
    save_cards([bad], tmp)
    codes = (_run_cli(["check"]),
             _run_cli(["check", "--cards-dir", tmp]),
             _run_cli(["check", "--cards-dir", "/tmp/no-such-cards-xyz"]))
    check("E11 CLI check exit codes 0/1/2",
          codes == (EXIT_OK, EXIT_FAIL, EXIT_ERROR), f"codes={codes}")

    # E12: serve round-trip matches local retrieve
    local = retrieve(cards, QUERY, k=3)
    reset_state(cards)
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/retrieve",
            data=json.dumps({"query": QUERY, "k": 3}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            served = json.loads(resp.read())
        serve_ok = served["results"] == local
    finally:
        server.shutdown()
        server.server_close()
        reset_state()
    check("E12 serve round-trip matches local retrieve", serve_ok)

    # E13: end-to-end determinism (canonical card bytes pinned by md5)
    again = ingest_events(fixture_events())
    bytes1 = "".join(json.dumps(c, sort_keys=True) + "\n" for c in cards)
    bytes2 = "".join(json.dumps(c, sort_keys=True) + "\n" for c in again)
    md5 = hashlib.md5(bytes1.encode()).hexdigest()
    check("E13 ingest determinism (canonical bytes md5 pinned)",
          bytes1 == bytes2 and md5 == "ea1488ea55eb6b81323bcc505582ff6f",
          f"cards_md5={md5}")

    passed = sum(1 for r in RESULTS if r["passed"])
    total_n = len(RESULTS)
    summary_doc = {"passed": passed, "total": total_n,
                   "all_passed": passed == total_n, "evals": RESULTS}
    with open(os.path.join(HERE, "eval_report.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(summary_doc, sort_keys=True) + "\n")
    print(f"\n{passed}/{total_n} evals passed -> evals/eval_report.json")
    return 0 if passed == total_n else 1


if __name__ == "__main__":
    sys.exit(main())

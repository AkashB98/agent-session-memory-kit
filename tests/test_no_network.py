"""No-network enforcement: with sockets blocked, ingest, retrieval
and injection must all still work. (``serve`` is the only intentional
exception - it binds loopback on demand, and is not used here.)"""

import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Blocker:
    def __init__(self, *a, **k):
        raise RuntimeError("network access blocked in hermetic test")


class TestNoNetwork(unittest.TestCase):
    def setUp(self):
        self._real_socket = socket.socket
        socket.socket = _Blocker
        import urllib.request as urlreq
        self._real_urlopen = urlreq.urlopen
        urlreq.urlopen = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("network access blocked in hermetic test"))

    def tearDown(self):
        socket.socket = self._real_socket
        import urllib.request as urlreq
        urlreq.urlopen = self._real_urlopen

    def test_full_pipeline_offline(self):
        from cards import validate_cards
        from retrieve import inject, retrieve
        from sessions import fixture_events, ingest_events
        cards = ingest_events(fixture_events())
        self.assertEqual(validate_cards(cards), [])
        results = retrieve(cards, "router firmware version", k=3)
        self.assertEqual(results[0]["card_id"], "card-helios-002-001")
        block = inject(cards, "router firmware version", budget_tokens=60)
        self.assertLessEqual(block["used_tokens"], 60)

    def test_no_module_opens_sockets_at_import(self):
        for mod in ("cards", "cli", "demo", "extract", "redact",
                    "retrieve", "sessions"):
            sys.modules.pop(mod, None)
        import cards, cli, demo, extract, redact, retrieve, sessions  # noqa: F401
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()

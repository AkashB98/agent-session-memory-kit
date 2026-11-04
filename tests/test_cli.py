import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import EXIT_ERROR, EXIT_FAIL, EXIT_OK, main as cli_main  # noqa: E402
from cli import make_server, reset_state  # noqa: E402
from cards import save_cards  # noqa: E402
from sessions import fixture_events, ingest_events  # noqa: E402
from tests.helpers import card  # noqa: E402


def _run(argv):
    with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
        code = cli_main(argv)
    return code, out.getvalue()


class TestCli(unittest.TestCase):
    def test_check_fixtures_pass(self):
        code, out = _run(["check"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("check PASS", out)

    def test_check_missing_dir_is_error(self):
        code, _ = _run(["check", "--cards-dir", "/tmp/no-such-cards-xyz"])
        self.assertEqual(code, EXIT_ERROR)

    def test_check_pii_card_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_cards([card(text="Fact: mail a@b.example.com for details.")],
                       tmp)
            code, out = _run(["check", "--cards-dir", tmp])
        self.assertEqual(code, EXIT_FAIL)
        self.assertIn("PII", out)

    def test_ingest_writes_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _run(["ingest", "--cards-dir", tmp])
            self.assertEqual(code, EXIT_OK)
            self.assertIn("12 cards", out)
            self.assertEqual(len(os.listdir(tmp)), 12)

    def test_cards_command_active_only_by_default(self):
        _, out = _run(["cards"])
        shown = json.loads(out)
        self.assertEqual(len(shown), 11)
        _, out2 = _run(["cards", "--include-superseded"])
        self.assertEqual(len(json.loads(out2)), 12)

    def test_retrieve_command(self):
        _, out = _run(["retrieve", "--query", "router firmware version"])
        results = json.loads(out)
        self.assertEqual(results[0]["card_id"], "card-helios-002-001")

    def test_inject_command_respects_budget(self):
        with redirect_stdout(io.StringIO()) as out, \
                redirect_stderr(io.StringIO()) as err:
            code = cli_main(["inject", "--query", "router firmware",
                             "--budget", "20"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("/20 tokens", err.getvalue())


class TestServe(unittest.TestCase):
    def setUp(self):
        reset_state(ingest_events(fixture_events()))
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        reset_state()

    def _req(self, path, payload=None, method="GET"):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers={"Content-Type": "application/json"}, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())

    def test_health(self):
        status, body = self._req("/health")
        self.assertEqual((status, body), (200, {"status": "ok"}))

    def test_retrieve_round_trip(self):
        status, body = self._req("/retrieve", method="POST",
                                 payload={"query": "router firmware version",
                                          "k": 3})
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["card_id"], "card-helios-002-001")

    def test_bad_query_is_400(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._req("/retrieve", method="POST", payload={"k": 3})
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()

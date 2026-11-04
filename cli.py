"""CLI: ingest | cards | retrieve | inject | check | demo | serve.

SYNTHETIC DATA ONLY - Helios Home is a fictional company and every
session log handled here is fabricated sample data.

Exit codes:
  check : 0 = card store valid (schema clean, no PII left in any card,
              supersession consistent), 1 = violations found,
              2 = usage / IO error
  others: 0 = success, 2 = usage / IO error

``ingest`` / ``retrieve`` / ``inject`` without explicit inputs run
on the bundled fixture sessions, in memory.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cards import active_cards, load_cards, validate_cards  # noqa: E402
from retrieve import inject as inject_cards, retrieve as retrieve_cards  # noqa: E402
from sessions import fixture_events, ingest_events, ingest_files  # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True)


def _cards_or_error(args):
    """(cards, exit_code): --cards-dir store, or fixture ingest."""
    cards_dir = getattr(args, "cards_dir", None)
    if not cards_dir:
        return ingest_events(fixture_events()), EXIT_OK
    try:
        return load_cards(cards_dir), EXIT_OK
    except FileNotFoundError:
        print(f"error: cards dir not found: {cards_dir}", file=sys.stderr)
        return None, EXIT_ERROR
    except (ValueError, OSError) as exc:
        print(f"error: cannot read cards in {cards_dir}: {exc}",
              file=sys.stderr)
        return None, EXIT_ERROR


def cmd_ingest(args) -> int:
    paths = args.inputs or []
    try:
        if paths:
            cards = ingest_files(paths, cards_dir=args.cards_dir)
        else:
            from sessions import fixture_paths
            cards = ingest_files(fixture_paths(), cards_dir=args.cards_dir)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"error: ingest failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    superseded = sum(1 for c in cards if c["superseded"])
    dest = args.cards_dir or "(in memory)"
    print(f"ingested {len(cards)} cards ({superseded} superseded, "
          f"{len(cards) - superseded} active) -> {dest}")
    return EXIT_OK


def cmd_cards(args) -> int:
    cards, code = _cards_or_error(args)
    if cards is None:
        return code
    shown = cards if args.include_superseded else active_cards(cards)
    print(canonical(shown))
    return EXIT_OK


def cmd_retrieve(args) -> int:
    cards, code = _cards_or_error(args)
    if cards is None:
        return code
    print(canonical(retrieve_cards(cards, args.query, k=args.k)))
    return EXIT_OK


def cmd_inject(args) -> int:
    cards, code = _cards_or_error(args)
    if cards is None:
        return code
    result = inject_cards(cards, args.query, budget_tokens=args.budget)
    print(result["text"])
    print(f"# injected {len(result['card_ids'])} cards, "
          f"{result['used_tokens']}/{result['budget_tokens']} tokens",
          file=sys.stderr)
    return EXIT_OK


def cmd_check(args) -> int:
    cards, code = _cards_or_error(args)
    if cards is None:
        return code
    issues = validate_cards(cards)
    # Supersession consistency: re-resolving must change nothing.
    from cards import apply_supersession
    if apply_supersession(cards) != sorted(
            cards, key=lambda c: (c["created_at"], c["card_id"])):
        issues.append("supersession state is not resolved consistently")
    actives = active_cards(cards)
    subjects = [c["subject_key"] for c in actives]
    if len(subjects) != len(set(subjects)):
        issues.append("two active cards share a subject_key")
    print(f"cards={len(cards)} active={len(actives)} "
          f"superseded={len(cards) - len(actives)}")
    if issues:
        for issue in issues[:20]:
            print(f"check FAIL: {issue}")
        return EXIT_FAIL
    print("check PASS")
    return EXIT_OK


def cmd_demo(args) -> int:
    import demo as demo_mod
    try:
        demo_mod.main()
    except AssertionError as exc:
        print(f"demo FAILED: {exc}", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_OK


# ------------------------------------------------------------------- serve

class _State:
    def __init__(self):
        self.cards = ingest_events(fixture_events())


_STATE = _State()


def get_state() -> _State:
    return _STATE


def reset_state(cards: Optional[List] = None) -> None:
    _STATE.cards = list(cards) if cards is not None else ingest_events(
        fixture_events())


class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload: Any) -> None:
        body = (canonical(payload) + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._send_json(200, {"status": "ok"})
        return self._send_json(404, {"error": "unknown endpoint"})

    def do_POST(self):  # noqa: N802
        if self.path != "/retrieve":
            return self._send_json(404, {"error": "unknown endpoint"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw) if raw.strip() else {}
            if not isinstance(body, dict):
                raise ValueError("expected a JSON object")
            query = body.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError("body needs a non-empty 'query' string")
            cards = body.get("cards", _STATE.cards)
            issues = validate_cards(cards)
            if issues:
                raise ValueError(f"invalid cards: {issues[0]}")
            k = int(body.get("k", 5))
            return self._send_json(200, {
                "query": query,
                "results": retrieve_cards(cards, query, k=k),
            })
        except (ValueError, TypeError, KeyError) as exc:
            return self._send_json(400, {"error": f"bad request: {exc}"})

    def log_message(self, *a: Any) -> None:
        pass


def make_server(port: int) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), _Handler)


def cmd_serve(args) -> int:
    if args.cards_dir:
        cards, code = _cards_or_error(args)
        if cards is None:
            return code
        reset_state(cards)
    server = make_server(args.port)
    print(f"serving on http://127.0.0.1:{args.port}  "
          f"(POST /retrieve, GET /health)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent-session-memory-kit",
        description="Compress agent session logs into memory cards; "
                    "retrieve and inject them under a token budget "
                    "(Helios Home sample data).")
    sub = p.add_subparsers(dest="cmd", required=True)

    ing = sub.add_parser("ingest", help="session JSONL -> card store")
    ing.add_argument("inputs", nargs="*",
                     help="session .jsonl files; default: fixtures")
    ing.add_argument("--cards-dir", default=None,
                     help="write cards here (default: in memory only)")
    ing.set_defaults(func=cmd_ingest)

    c = sub.add_parser("cards", help="list cards as JSON")
    c.add_argument("--cards-dir", default=None)
    c.add_argument("--include-superseded", action="store_true")
    c.set_defaults(func=cmd_cards)

    r = sub.add_parser("retrieve", help="ranked cards for a query")
    r.add_argument("--query", required=True)
    r.add_argument("--k", type=int, default=5)
    r.add_argument("--cards-dir", default=None)
    r.set_defaults(func=cmd_retrieve)

    inj = sub.add_parser("inject", help="budgeted injection block")
    inj.add_argument("--query", required=True)
    inj.add_argument("--budget", type=int, default=200)
    inj.add_argument("--cards-dir", default=None)
    inj.set_defaults(func=cmd_inject)

    chk = sub.add_parser("check", help="CI gate: exit 0/1/2")
    chk.add_argument("--cards-dir", default=None)
    chk.set_defaults(func=cmd_check)

    sub.add_parser("demo", help="run the end-to-end demo").set_defaults(
        func=cmd_demo)

    s = sub.add_parser("serve", help="localhost JSON API")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--cards-dir", default=None)
    s.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

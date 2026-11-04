import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from retrieve import (estimate_tokens, inject, recall_precision_at_k,  # noqa: E402
                      retrieve, tokenize)
from tests.helpers import card  # noqa: E402


def corpus():
    return [
        card("card-t-001", subject_key="router-firmware-version",
             text="Fact: router firmware version is 3.0.0 on the hallway router."),
        card("card-t-002", subject_key="thermostat-night-schedule",
             kind="fact", text="Fact: thermostat night schedule is 19 degrees."),
        card("card-t-003", subject_key="garage-camera-recording",
             kind="decision",
             text="Decision: garage camera recording stays local, not cloud."),
    ]


class TestTokenizeAndEstimate(unittest.TestCase):
    def test_tokenize_drops_stopwords(self):
        self.assertEqual(tokenize("The router is on the LAN"),
                         ["router", "lan"])

    def test_estimate_formula(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("one"), 2)        # ceil(1*1.3)
        self.assertEqual(estimate_tokens("one two three"), 4)  # ceil(3*1.3)
        self.assertEqual(estimate_tokens(" ".join(["w"] * 10)), 13)


class TestRetrieve(unittest.TestCase):
    def test_relevant_card_ranks_first(self):
        results = retrieve(corpus(), "router firmware version", k=3)
        self.assertEqual(results[0]["card_id"], "card-t-001")

    def test_no_overlap_no_results(self):
        self.assertEqual(retrieve(corpus(), "zebra quantum banana"), [])

    def test_empty_query_no_results(self):
        self.assertEqual(retrieve(corpus(), ""), [])
        self.assertEqual(retrieve(corpus(), "the and of"), [])

    def test_superseded_never_retrieved(self):
        cards = corpus()
        cards[0] = card("card-t-001", superseded=True,
                        superseded_by="card-t-009")
        results = retrieve(cards, "router firmware version", k=5)
        self.assertNotIn("card-t-001", [r["card_id"] for r in results])

    def test_k_limits_results(self):
        self.assertLessEqual(len(retrieve(corpus(), "router", k=1)), 1)

    def test_deterministic_order(self):
        a = retrieve(corpus(), "router firmware thermostat garage", k=3)
        b = retrieve(corpus(), "router firmware thermostat garage", k=3)
        self.assertEqual(a, b)

    def test_ties_break_on_card_id_not_input_order(self):
        # Two cards with identical term profiles score identically;
        # the ranking must be the same when the corpus is reversed.
        a = card("card-t-101", subject_key="alpha-topic-one",
                 text="Fact: alpha beta gamma delta.")
        b = card("card-t-102", subject_key="alpha-topic-two",
                 text="Fact: alpha beta gamma delta.")
        forward = retrieve([a, b], "alpha beta", k=2)
        reverse = retrieve([b, a], "alpha beta", k=2)
        self.assertEqual(forward, reverse)
        self.assertEqual(forward[0]["score"], forward[1]["score"])


class TestInject(unittest.TestCase):
    def test_budget_never_exceeded_sweep(self):
        for budget in range(0, 201, 7):
            block = inject(corpus(), "router firmware thermostat garage",
                           budget_tokens=budget)
            self.assertLessEqual(block["used_tokens"], budget)

    def test_zero_budget_injects_nothing(self):
        block = inject(corpus(), "router", budget_tokens=0)
        self.assertEqual(block["card_ids"], [])
        self.assertEqual(block["text"], "")
        self.assertEqual(block["used_tokens"], 0)

    def test_superseded_never_injected(self):
        cards = corpus()
        cards[0] = card("card-t-001", superseded=True,
                        superseded_by="card-t-009")
        block = inject(cards, "router firmware version", budget_tokens=500)
        self.assertNotIn("card-t-001", block["card_ids"])


class TestRecallPrecision(unittest.TestCase):
    def test_math(self):
        got = recall_precision_at_k(["a", "b", "c"], ["a", "c", "d"], k=3)
        self.assertEqual(got, {"k": 3, "hits": 2,
                               "recall": 0.6667, "precision": 0.6667})

    def test_perfect(self):
        got = recall_precision_at_k(["a", "b"], ["a", "b"], k=2)
        self.assertEqual((got["recall"], got["precision"]), (1.0, 1.0))


if __name__ == "__main__":
    unittest.main()

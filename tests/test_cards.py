import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cards import (active_cards, apply_supersession, load_cards,  # noqa: E402
                   save_cards, validate_card, validate_cards)
from tests.helpers import card  # noqa: E402


class TestSupersession(unittest.TestCase):
    def test_newer_wins_older_retained_marked(self):
        old = card("card-t-001", created_at="2026-01-01T00:00:00Z",
                   text="Fact: router firmware version is 2.4.1.")
        new = card("card-t-002", created_at="2026-01-08T00:00:00Z",
                   text="Fact: router firmware version is 3.0.0.")
        out = apply_supersession([new, old])  # input order must not matter
        by_id = {c["card_id"]: c for c in out}
        self.assertTrue(by_id["card-t-001"]["superseded"])
        self.assertEqual(by_id["card-t-001"]["superseded_by"], "card-t-002")
        self.assertFalse(by_id["card-t-002"]["superseded"])
        self.assertEqual(len(out), 2)  # retained, not deleted

    def test_distinct_subjects_both_active(self):
        a = card("card-t-001", subject_key="router-firmware-version")
        b = card("card-t-002", subject_key="door-lock-battery",
                 text="Fact: door lock battery is 82 percent.")
        out = apply_supersession([a, b])
        self.assertEqual(len(active_cards(out)), 2)

    def test_three_generations_only_newest_active(self):
        cards = [card(f"card-t-00{i}", created_at=f"2026-01-0{i}T00:00:00Z")
                 for i in (1, 2, 3)]
        out = apply_supersession(cards)
        self.assertEqual([c["card_id"] for c in active_cards(out)],
                         ["card-t-003"])
        self.assertTrue(all(c["superseded_by"] == "card-t-003"
                            for c in out if c["superseded"]))

    def test_timestamp_tie_breaks_on_card_id(self):
        a = card("card-t-001")
        b = card("card-t-002")
        out = apply_supersession([a, b])
        self.assertEqual([c["card_id"] for c in active_cards(out)],
                         ["card-t-002"])

    def test_input_not_mutated(self):
        a = card("card-t-001")
        apply_supersession([a, card("card-t-002",
                                     created_at="2026-01-02T00:00:00Z")])
        self.assertFalse(a["superseded"])


class TestValidationAndStore(unittest.TestCase):
    def test_valid_card_clean(self):
        self.assertEqual(validate_card(card()), [])

    def test_pii_in_text_is_an_issue(self):
        bad = card(text="Fact: mail me at a@b.example.com please.")
        self.assertTrue(any("PII" in i for i in validate_card(bad)))

    def test_missing_field_and_bad_kind(self):
        self.assertTrue(validate_card({"card_id": "x"}))
        self.assertTrue(validate_card(card(kind="guess")))

    def test_duplicate_ids_flagged(self):
        issues = validate_cards([card("card-t-001"), card("card-t-001",
                                  subject_key="other-topic-here")])
        self.assertTrue(any("duplicate" in i for i in issues))

    def test_save_load_round_trip(self):
        cards = [card("card-t-001"), card("card-t-002",
                                          subject_key="door-lock-battery")]
        with tempfile.TemporaryDirectory() as tmp:
            save_cards(cards, tmp)
            self.assertEqual(load_cards(tmp), cards)
            self.assertEqual(sorted(os.listdir(tmp)),
                             ["card-t-001.json", "card-t-002.json"])


if __name__ == "__main__":
    unittest.main()

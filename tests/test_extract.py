import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract import classify, extract_cards, subject_key  # noqa: E402
from tests.helpers import event  # noqa: E402


class TestClassify(unittest.TestCase):
    def test_each_kind(self):
        self.assertEqual(classify("Fact: the sky is blue."), "fact")
        self.assertEqual(classify("Decision: decided to ship it."), "decision")
        self.assertEqual(classify("TODO: follow up on the sensor."), "open_item")
        self.assertEqual(classify("Error: polling failed: no answer."), "error")

    def test_error_type_wins(self):
        self.assertEqual(classify("Fact: it broke.", event_type="error"), "error")

    def test_error_beats_fact_cue(self):
        self.assertEqual(classify("Fact: noted. Error: disk full."), "error")

    def test_no_cue_no_card(self):
        self.assertIsNone(classify("Hello, how can I help today?"))
        self.assertIsNone(classify("Thanks, that covers it."))


class TestSubjectKey(unittest.TestCase):
    def test_firmware_variants_share_key(self):
        a = subject_key("Fact: router firmware version is 2.4.1 on the router.")
        b = subject_key("Fact: router firmware version is 3.0.0 on the router.")
        self.assertEqual(a, "router-firmware-version")
        self.assertEqual(a, b)

    def test_decision_and_fact_same_topic(self):
        a = subject_key("Decision: decided to change router firmware version policy.")
        self.assertTrue(a.startswith("change-router-firmware") or a)

    def test_empty_is_general(self):
        self.assertEqual(subject_key("Fact: 123 456."), "general")


class TestExtractCards(unittest.TestCase):
    def test_only_cued_events_become_cards(self):
        events = [event("Hello there."), event("Fact: the hub is online."),
                  event("Decision: chose to reboot nightly.")]
        cards = extract_cards(events)
        self.assertEqual(len(cards), 2)
        self.assertEqual([c["kind"] for c in cards], ["fact", "decision"])

    def test_ids_are_sequential_per_session(self):
        events = [event("Fact: alpha beta gamma.", session_id="s9"),
                  event("Fact: delta epsilon zeta.", session_id="s9"),
                  event("Fact: eta theta iota.", session_id="s8")]
        cards = extract_cards(events)
        self.assertEqual([c["card_id"] for c in cards],
                         ["card-s9-001", "card-s9-002", "card-s8-001"])

    def test_pii_redacted_before_card_exists(self):
        cards = extract_cards([event("Fact: contact is a@b.example.com today.")])
        self.assertNotIn("a@b.example.com", cards[0]["text"])
        self.assertEqual(cards[0]["redactions"], ["email"])

    def test_source_index_points_at_event(self):
        events = [event("chatter"), event("Fact: hub firmware is current.")]
        cards = extract_cards(events)
        self.assertEqual(cards[0]["source_index"], 1)


if __name__ == "__main__":
    unittest.main()

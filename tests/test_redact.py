import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from redact import contains_pii, find_pii, redact_text  # noqa: E402


class TestRedact(unittest.TestCase):
    def test_email_redacted(self):
        clean, kinds = redact_text("reach me at jane.doe@example.com please")
        self.assertEqual(clean, "reach me at [REDACTED:email] please")
        self.assertEqual(kinds, ["email"])

    def test_sk_key_redacted(self):
        fake = "sk-" + "abcdefgh12345678"  # built, never a literal in tree
        clean, kinds = redact_text(f"key {fake} end")
        self.assertIn("[REDACTED:key]", clean)
        self.assertNotIn(fake, clean)
        self.assertEqual(kinds, ["key"])

    def test_assignment_value_redacted(self):
        clean, _ = redact_text("api_key=hunter2secret now")
        self.assertEqual(clean, "api_key=[REDACTED:key] now")

    def test_assignment_redaction_is_idempotent(self):
        # Regression: the marker itself must not re-trigger the
        # assignment pattern, or the check gate flags clean cards.
        clean, _ = redact_text("api_key=hunter2secret now")
        again, kinds = redact_text(clean)
        self.assertEqual(again, clean)
        self.assertEqual(kinds, [])
        self.assertFalse(contains_pii(clean))

    def test_long_hex_redacted(self):
        clean, _ = redact_text("digest " + "a" * 40 + " done")
        self.assertIn("[REDACTED:key]", clean)

    def test_clean_text_unchanged(self):
        text = "Fact: router firmware version is 3.0.0 on the hallway router."
        clean, kinds = redact_text(text)
        self.assertEqual(clean, text)
        self.assertEqual(kinds, [])

    def test_idempotent(self):
        fake = "sk-" + "1234567890ab"
        once, _ = redact_text(f"mail a@b.example.com key {fake}")
        twice, kinds2 = redact_text(once)
        self.assertEqual(once, twice)
        self.assertEqual(kinds2, [])

    def test_contains_pii(self):
        self.assertTrue(contains_pii("x@y.example.com"))
        self.assertFalse(contains_pii("no secrets here"))
        self.assertEqual(find_pii("plain words only"), [])


if __name__ == "__main__":
    unittest.main()

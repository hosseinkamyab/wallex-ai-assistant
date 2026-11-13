"""Tests for the bilingual (English / Persian) helper module."""

from __future__ import annotations

import unittest

from wallex_assistant import i18n


class TestLookup(unittest.TestCase):
    def test_translates_english(self) -> None:
        self.assertEqual(i18n.t("app.language", "en"), "Language")

    def test_translates_persian(self) -> None:
        self.assertEqual(i18n.t("app.language", "fa"), "زبان")

    def test_default_language_is_english(self) -> None:
        self.assertEqual(i18n.t("app.title"), "Wallex AI Assistant")

    def test_unknown_key_returns_the_key(self) -> None:
        # Visible in the UI, but never crashes.
        self.assertEqual(i18n.t("no.such.key", "en"), "no.such.key")

    def test_unknown_language_falls_back_to_english(self) -> None:
        self.assertEqual(i18n.t("app.language", "xx"), "Language")

    def test_none_language_falls_back_to_english(self) -> None:
        self.assertEqual(i18n.t("app.language", None), "Language")

    def test_placeholder_substitution(self) -> None:
        i18n.TRANSLATIONS["en"]["_test.hello"] = "Hello, {name}!"
        try:
            self.assertEqual(
                i18n.t("_test.hello", "en", name="Sara"), "Hello, Sara!"
            )
        finally:
            del i18n.TRANSLATIONS["en"]["_test.hello"]

    def test_broken_placeholder_does_not_raise(self) -> None:
        i18n.TRANSLATIONS["en"]["_test.broken"] = "Hi {missing}!"
        try:
            # No kwargs supplied for a placeholder -> returns raw text.
            self.assertEqual(i18n.t("_test.broken", "en"), "Hi {missing}!")
        finally:
            del i18n.TRANSLATIONS["en"]["_test.broken"]


class TestDirections(unittest.TestCase):
    def test_english_is_ltr(self) -> None:
        self.assertFalse(i18n.is_rtl("en"))
        self.assertEqual(i18n.text_direction("en"), "ltr")

    def test_persian_is_rtl(self) -> None:
        self.assertTrue(i18n.is_rtl("fa"))
        self.assertEqual(i18n.text_direction("fa"), "rtl")

    def test_normalize_language_handles_case_and_junk(self) -> None:
        self.assertEqual(i18n.normalize_language("FA"), "fa")
        self.assertEqual(i18n.normalize_language(" en "), "en")
        self.assertEqual(i18n.normalize_language("de"), "en")
        self.assertEqual(i18n.normalize_language(""), "en")


class TestCatalogueConsistency(unittest.TestCase):
    """Persian and English must stay in sync as the app grows."""

    def test_same_keys_in_both_languages(self) -> None:
        english = set(i18n.TRANSLATIONS["en"])
        persian = set(i18n.TRANSLATIONS["fa"])
        self.assertEqual(
            english, persian,
            "Translation catalogues are out of sync:\n"
            f"  only in en: {sorted(english - persian)}\n"
            f"  only in fa: {sorted(persian - english)}",
        )

    def test_no_empty_translations(self) -> None:
        for lang, catalogue in i18n.TRANSLATIONS.items():
            for key, value in catalogue.items():
                self.assertTrue(
                    value.strip(), f"Empty translation for {key!r} in {lang!r}"
                )


class TestFormatting(unittest.TestCase):
    def test_money_has_thousand_separators(self) -> None:
        self.assertEqual(i18n.format_money(1234567.5, "en"), "1,234,567.50")

    def test_money_handles_bad_input(self) -> None:
        self.assertEqual(i18n.format_money(None, "en"), "—")
        self.assertEqual(i18n.format_money("abc", "en"), "—")

    def test_quantity_trims_trailing_zeros(self) -> None:
        self.assertEqual(i18n.format_quantity(0.5, "en"), "0.5")
        self.assertEqual(i18n.format_quantity(2.0, "en"), "2")

    def test_quantity_keeps_precision_for_small_amounts(self) -> None:
        self.assertEqual(i18n.format_quantity(0.00012345, "en"), "0.00012345")

    def test_percent_formatting(self) -> None:
        self.assertEqual(i18n.format_percent(12.346, "en"), "12.35%")

    def test_persian_output_is_isolated(self) -> None:
        # In RTL mode numbers are wrapped so they cannot be reordered.
        text = i18n.format_money(1000, "fa")
        self.assertIn(chr(0x2066), text)  # LEFT-TO-RIGHT ISOLATE
        self.assertIn(chr(0x2069), text)  # POP DIRECTIONAL ISOLATE
        self.assertIn("1,000.00", text)

    def test_english_output_is_not_isolated(self) -> None:
        self.assertNotIn(chr(0x2066), i18n.format_money(1000, "en"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

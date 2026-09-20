from __future__ import annotations

import unittest

from engine.stage2.language_policy import normalize_public_prose


class AbbreviationTests(unittest.TestCase):
    def test_english_abbreviations_become_official_names(self):
        self.assertEqual(normalize_public_prose("PSM 자체감사를 실시한다.", "PSM"), "공정안전관리 자체감사를 실시한다.")
        self.assertEqual(normalize_public_prose("CAP 작성 대상이다.", "CAP"), "화학사고예방관리계획서 작성 대상이다.")

    def test_words_that_only_contain_the_letters_are_untouched(self):
        self.assertEqual(normalize_public_prose("CAPACITY 와 PSMX", "PSM"), "CAPACITY 와 PSMX")


if __name__ == "__main__":
    unittest.main()

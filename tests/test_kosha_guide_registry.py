from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from engine import kosha_guide_registry as reg


def _body(items):
    return json.dumps({"response": {"header": {"resultCode": "00", "resultMsg": "OK"},
                                    "body": {"pageNo": 1, "totalCount": len(items), "numOfRows": 50,
                                             "items": {"item": items}}}})


def _item(number, announced="2026-01-01"):
    return {"techGdlnNm": "지침", "techGdlnNo": number, "techGdlnOfancYmd": announced, "fileDownloadUrl": "https://x/y"}


class RegistryTests(unittest.TestCase):
    def test_registry_lists_the_guides_the_psm_form_relies_on(self):
        numbers = {g.base_number for g in reg.used_by("psm.form19-2")}
        self.assertTrue({"P-92", "P-102", "C-C-46", "P-107"} <= numbers)
        self.assertEqual(reg.entry("P-91").base_number, "C-C-46")  # 예전 번호로도 찾는다
        self.assertEqual(reg.entry("c-c-46").edition, "C-C-46-2026")

    def test_extracted_files_exist(self):
        root = Path(reg.ROOT)
        for guide in reg.entries():
            for relative in guide.extracted:
                self.assertTrue((root / relative).is_file(), relative)

    def test_cache_accepts_only_the_registered_edition(self):
        guide = reg.entry("P-102")
        with tempfile.TemporaryDirectory() as tmp:
            good, bad = Path(tmp) / "good.pdf", Path(tmp) / "bad.pdf"
            bad.write_bytes(b"other edition")
            with self.assertRaises(ValueError):
                reg.cache_local_copy(guide, bad, Path(tmp) / "cache")
            self.assertIsNone(reg.cached_file(guide, Path(tmp) / "cache"))
            registered = reg.GuideEntry(guide.base_number, (), guide.title, guide.edition, "", "", (), (), "")
            self.assertIsNone(reg.cached_file(registered, Path(tmp)))  # 해시가 없으면 신뢰하지 않는다
            good.write_bytes(b"match")
            import hashlib
            fixed = reg.GuideEntry("T-1", (), "t", "T-1-2020", "", hashlib.sha256(b"match").hexdigest(), (), (), "")
            reg.cache_local_copy(fixed, good, Path(tmp) / "cache")
            self.assertIsNotNone(reg.cached_file(fixed, Path(tmp) / "cache"))

    def test_newer_edition_is_flagged_for_review_never_applied(self):
        def fake(url, params):
            number = params.get("techGdlnNo", "")
            if number == "P-92":
                return 200, _body([_item("P-92-2023"), _item("P-92-2027", "2027-03-01")])
            if number == "P-102":
                return 200, _body([_item("P-102-2021")])
            if number == "C-C-46":
                return 200, _body([_item("C-C-46-2026")])
            return 200, _body([_item(f"{number}-2020")])
        with patch("engine.kosha_guide._credential", return_value="k"):
            checks = {c.entry.base_number: c for c in reg.check_updates(get=fake)}
        self.assertEqual(checks["P-92"].status, "REVIEW_NEEDED")
        self.assertIn("P-92-2027", checks["P-92"].message)
        self.assertEqual(checks["P-102"].status, "UP_TO_DATE")
        self.assertEqual(checks["C-C-46"].status, "UP_TO_DATE")
        self.assertEqual(checks["P-107"].status, "NOT_REGISTERED")  # 원문 미확보
        self.assertEqual(reg.entry("P-92").edition, "P-92-2023")  # 목록은 그대로

    def test_renamed_guide_is_found_through_its_old_number(self):
        def fake(url, params):
            if params.get("techGdlnNo") == "P-91":
                return 200, _body([_item("P-91-2012")])
            if params.get("techGdlnNo") == "C-C-46":
                return 200, _body([_item("C-C-46-2030", "2030-01-01")])
            return 200, _body([_item("X-1-2000")])
        with patch("engine.kosha_guide._credential", return_value="k"):
            check = next(c for c in reg.check_updates(get=fake) if c.entry.base_number == "C-C-46")
        self.assertEqual(check.status, "REVIEW_NEEDED")
        self.assertEqual(check.checked_numbers, ("C-C-46", "P-91"))

    def test_without_a_key_nothing_is_called_and_status_says_so(self):
        calls = []
        with patch("engine.kosha_guide._credential", return_value=""):
            checks = reg.check_updates(get=lambda url, params: calls.append(1) or (200, ""))
        self.assertEqual(calls, [])
        self.assertTrue(all(c.status == "NOT_CHECKED" for c in checks))


if __name__ == "__main__":
    unittest.main()

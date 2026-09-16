import os
import unittest
from unittest.mock import patch

import engine
from engine import kosha_msds


class KOSHAMSDSMigrationTests(unittest.TestCase):
    def test_legacy_defaults_are_migrated_to_current_service(self):
        legacy = "https://apis.data.go.kr/B552468/msds_api"
        with patch.dict(
            os.environ,
            {
                "KOSHA_MSDS_BASE_URL": legacy,
                "KOSHA_MSDS_SEARCH_URL": legacy + "/msdslist",
                "KOSHA_MSDS_SECTION_02_URL": legacy + "/chemdetail02",
                "KOSHA_MSDS_SECTION2_URL": legacy + "/chemdetail02",
            },
            clear=False,
        ):
            engine._install_kosha_msds_endpoint_migration()
            self.assertEqual(
                os.environ["KOSHA_MSDS_BASE_URL"],
                "https://apis.data.go.kr/B552468/msdschem",
            )
            self.assertEqual(
                os.environ["KOSHA_MSDS_SEARCH_URL"],
                "https://apis.data.go.kr/B552468/msdschem/getChemList",
            )
            self.assertEqual(
                os.environ["KOSHA_MSDS_SECTION_02_URL"],
                "https://apis.data.go.kr/B552468/msdschem/getChemDetail02",
            )
            self.assertNotIn("KOSHA_MSDS_SECTION2_URL", os.environ)
            self.assertEqual(
                kosha_msds._search_url(),
                "https://apis.data.go.kr/B552468/msdschem/getChemList",
            )
            self.assertEqual(
                kosha_msds._section_url(2),
                "https://apis.data.go.kr/B552468/msdschem/getChemDetail02",
            )

    def test_custom_endpoint_overrides_are_preserved(self):
        with patch.dict(
            os.environ,
            {
                "KOSHA_MSDS_BASE_URL": "https://example.test/base",
                "KOSHA_MSDS_SEARCH_URL": "https://example.test/search",
                "KOSHA_MSDS_SECTION_02_URL": "https://example.test/section2",
            },
            clear=False,
        ):
            engine._install_kosha_msds_endpoint_migration()
            self.assertEqual(os.environ["KOSHA_MSDS_BASE_URL"], "https://example.test/base")
            self.assertEqual(os.environ["KOSHA_MSDS_SEARCH_URL"], "https://example.test/search")
            self.assertEqual(os.environ["KOSHA_MSDS_SECTION_02_URL"], "https://example.test/section2")


if __name__ == "__main__":
    unittest.main()

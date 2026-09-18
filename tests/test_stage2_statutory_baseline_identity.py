from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from engine.stage2.statutory_baseline_identity import statutory_baseline_identity


class StatutoryBaselineIdentityTests(unittest.TestCase):
    def test_registered_psm_baseline_identity_matches_metadata(self):
        identity = statutory_baseline_identity("PSM")

        self.assertEqual(identity.schema_version, "psm-statutory-form-layout-baseline-v2")
        self.assertEqual(identity.role, "LAYOUT_BASELINE")
        self.assertEqual(
            identity.sha256,
            "82457f0775850d95abd166fa6e63aae67da8fdc2ae27349d7efdb8bbc9501335",
        )
        self.assertIn("별지 제12호", identity.source_description)
        self.assertIn("법적 최신성", identity.authority_note)

    def test_registered_cap_baseline_identity_matches_metadata(self):
        identity = statutory_baseline_identity("CAP")

        self.assertEqual(identity.schema_version, "cap-statutory-form-layout-baseline-v1")
        self.assertEqual(identity.role, "LAYOUT_BASELINE")
        self.assertEqual(
            identity.sha256,
            "f41c3b26c72fb3e0186d5d25b99004ed7a8d3644527c12844a6a7f2c36112d2d",
        )
        self.assertIn("CAP", identity.schema_version)
        self.assertIn("법적 최신성", identity.authority_note)

    def test_tampered_baseline_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "meta.json").write_text(
                json.dumps(
                    {
                        "schema_version": "fixture-v1",
                        "role": "LAYOUT_BASELINE",
                        "sha256": "0" * 64,
                        "source_description": "fixture",
                        "authority_note": "fixture",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            encoded = base64.b64encode(b"tampered-baseline").decode("ascii")
            (folder / "baseline.docx.b64.00").write_text(encoded, encoding="ascii")

            with patch.dict(
                "engine.stage2.statutory_baseline_identity._CONFIG",
                {"PSM": (folder, "meta.json", "baseline.docx.b64.*")},
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "해시"):
                    statutory_baseline_identity("PSM")

    def test_unknown_system_fails_closed(self):
        with self.assertRaises(ValueError):
            statutory_baseline_identity("UNKNOWN")


if __name__ == "__main__":
    unittest.main()

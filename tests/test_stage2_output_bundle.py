from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import unittest
from zipfile import ZipFile

from engine.stage2.output_bundle import (
    build_verified_output_bundle,
    verified_bundle_filename,
)
from engine.stage2.output_provenance import build_output_provenance
from engine.stage2.project import Stage2Project
from engine.stage2.workflow import mark_validation_confirmed


class VerifiedOutputBundleTests(unittest.TestCase):
    @staticmethod
    def _project() -> Stage2Project:
        project = Stage2Project(
            project_id="S2-BUNDLE",
            company_name="검증묶음화학",
            psm_required=True,
            scope_confirmed=True,
            psm_selected=True,
            stage1_source_fingerprint="b" * 64,
        )
        project.set_field(
            "business.address",
            "사업장 소재지",
            "테스트시 검증로 1",
            "USER_CONFIRMED",
        )
        mark_validation_confirmed(project, True)
        return project

    def test_bundle_contains_exact_docx_manifest_and_guide(self):
        project = self._project()
        data = b"exact-statutory-docx-bytes"
        file_name = "검증묶음화학_공정안전보고서_규정서식_작성본.docx"
        provenance = build_output_provenance(
            project,
            "PSM",
            data,
            file_name=file_name,
            final_ready=True,
        )

        bundle = build_verified_output_bundle(data, provenance)

        with ZipFile(BytesIO(bundle), "r") as archive:
            names = set(archive.namelist())
            self.assertIn(file_name, names)
            self.assertIn("검증묶음화학_공정안전보고서_규정서식_작성본_검증정보.json", names)
            self.assertIn("검증안내.txt", names)

            bundled_docx = archive.read(file_name)
            self.assertEqual(bundled_docx, data)
            self.assertEqual(sha256(bundled_docx).hexdigest(), provenance.sha256)

            manifest = json.loads(
                archive.read(
                    "검증묶음화학_공정안전보고서_규정서식_작성본_검증정보.json"
                ).decode("utf-8")
            )
            self.assertEqual(manifest["sha256"], provenance.sha256)
            self.assertEqual(manifest["state"], "AUTHORING_READY")

            guide = archive.read("검증안내.txt").decode("utf-8")
            self.assertIn(provenance.sha256, guide)
            self.assertIn("AUTHORING_READY", guide)

    def test_hash_mismatch_fails_closed(self):
        project = self._project()
        provenance = build_output_provenance(
            project,
            "PSM",
            b"original",
            file_name="original.docx",
            final_ready=True,
        )

        with self.assertRaisesRegex(ValueError, "SHA-256"):
            build_verified_output_bundle(b"different", provenance)

    def test_empty_bytes_fail_closed(self):
        project = self._project()
        provenance = build_output_provenance(
            project,
            "PSM",
            b"original",
            file_name="original.docx",
            final_ready=True,
        )

        with self.assertRaises(ValueError):
            build_verified_output_bundle(b"", provenance)

    def test_bundle_filename_tracks_statutory_filename(self):
        self.assertEqual(
            verified_bundle_filename("사업장_화학사고예방관리계획서_규정서식_검토용.docx"),
            "사업장_화학사고예방관리계획서_규정서식_검토용_검증묶음.zip",
        )


if __name__ == "__main__":
    unittest.main()

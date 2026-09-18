from __future__ import annotations

from hashlib import sha256
import json
import unittest

from engine.stage2.output_provenance import (
    SCHEMA_VERSION,
    build_output_provenance,
    output_provenance_filename,
    output_provenance_json_bytes,
)
from engine.stage2.project import Stage2Project
from engine.stage2.workflow import (
    mark_validation_confirmed,
    validation_confirmed,
    validation_fingerprint,
)


class OutputProvenanceTests(unittest.TestCase):
    @staticmethod
    def _project() -> Stage2Project:
        project = Stage2Project(
            project_id="S2-PROVENANCE",
            company_name="검증화학",
            site_name="제1공장",
            psm_required=True,
            scope_confirmed=True,
            psm_selected=True,
            stage1_source_fingerprint="a" * 64,
        )
        project.set_field(
            "business.address",
            "사업장 소재지",
            "테스트시 산업로 1",
            "USER_CONFIRMED",
        )
        mark_validation_confirmed(project, True)
        return project

    def test_manifest_hashes_exact_download_bytes_and_records_validation_state(self):
        project = self._project()
        data = b"exact-docx-bytes-for-test"
        file_name = "검증화학_공정안전보고서_규정서식_작성본.docx"

        result = build_output_provenance(
            project,
            "PSM",
            data,
            file_name=file_name,
            final_ready=True,
        )

        self.assertEqual(result.schema_version, SCHEMA_VERSION)
        self.assertEqual(result.system, "PSM")
        self.assertEqual(result.system_label, "공정안전보고서")
        self.assertEqual(result.file_name, file_name)
        self.assertEqual(result.sha256, sha256(data).hexdigest())
        self.assertEqual(result.size_bytes, len(data))
        self.assertEqual(result.stage1_source_fingerprint, "a" * 64)
        self.assertEqual(result.validation_fingerprint, validation_fingerprint(project))
        self.assertTrue(result.validation_confirmed)
        self.assertTrue(result.final_ready)
        self.assertEqual(result.state, "AUTHORING_READY")

    def test_review_output_is_explicitly_marked_review_only(self):
        project = self._project()
        result = build_output_provenance(
            project,
            "PSM",
            b"review-bytes",
            file_name="review.docx",
            final_ready=False,
        )

        self.assertFalse(result.final_ready)
        self.assertEqual(result.state, "REVIEW_ONLY")

    def test_project_change_after_stage4_is_visible_in_manifest(self):
        project = self._project()
        self.assertTrue(validation_confirmed(project))
        old_fingerprint = validation_fingerprint(project)

        project.set_field(
            "business.address",
            "사업장 소재지",
            "변경된 주소",
            "USER_CONFIRMED",
        )

        self.assertFalse(validation_confirmed(project))
        result = build_output_provenance(
            project,
            "PSM",
            b"changed-project-output",
            file_name="changed.docx",
            final_ready=False,
        )

        self.assertFalse(result.validation_confirmed)
        self.assertNotEqual(result.validation_fingerprint, old_fingerprint)

    def test_json_bytes_preserve_hash_and_state(self):
        project = self._project()
        result = build_output_provenance(
            project,
            "CAP",
            b"cap-docx",
            file_name="cap.docx",
            final_ready=False,
        )

        payload = json.loads(output_provenance_json_bytes(result).decode("utf-8"))
        self.assertEqual(payload["sha256"], sha256(b"cap-docx").hexdigest())
        self.assertEqual(payload["state"], "REVIEW_ONLY")
        self.assertEqual(payload["system"], "CAP")
        self.assertIn("generated_at_utc", payload)

    def test_manifest_filename_is_derived_from_exact_output_filename(self):
        self.assertEqual(
            output_provenance_filename("사업장_규정서식_작성본.docx"),
            "사업장_규정서식_작성본_검증정보.json",
        )

    def test_empty_output_bytes_fail_closed(self):
        project = self._project()
        with self.assertRaises(ValueError):
            build_output_provenance(
                project,
                "PSM",
                b"",
                file_name="empty.docx",
                final_ready=False,
            )


if __name__ == "__main__":
    unittest.main()

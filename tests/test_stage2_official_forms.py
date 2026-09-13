from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from engine.stage2 import official_forms


class OfficialStatutoryFormTests(unittest.TestCase):
    def _source(self, status="CURRENT", title="화학사고예방관리계획서 작성 등에 관한 규정"):
        return {
            "title": title,
            "effective_date": "2026-04-22",
            "issue_number": "화학물질안전원고시 제2026-7호",
            "monitor_status": status,
        }

    def test_exact_form_number_resolution_does_not_match_31_for_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            form3 = root / "별지3_사업장일반정보__aaaaaaaaaaaaaaaa.pdf"
            form31 = root / "별지31_검토신청서__bbbbbbbbbbbbbbbb.pdf"
            form3.write_bytes(b"form-3")
            form31.write_bytes(b"form-31")
            with patch.object(official_forms, "PROJECT_ROOT", root), patch.object(
                official_forms, "observed_pdf_paths", return_value=[form3, form31]
            ), patch.object(official_forms, "observed_source", return_value=self._source()):
                rows = official_forms.resolve_official_form(
                    "별지 제3호서식", candidate_law_keys=("CAP_DRAFT",)
                )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].form_reference, "별지 제3호서식")
            self.assertIn("별지3_", rows[0].file_name)
            self.assertEqual(len(rows[0].sha256), 64)

    def test_non_current_source_is_not_downloadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            form = root / "별지3_사업장일반정보__aaaaaaaaaaaaaaaa.pdf"
            form.write_bytes(b"form")
            with patch.object(official_forms, "PROJECT_ROOT", root), patch.object(
                official_forms, "observed_pdf_paths", return_value=[form]
            ), patch.object(
                official_forms, "observed_source", return_value=self._source("UPDATE_PENDING")
            ):
                rows = official_forms.resolve_official_form(
                    "별지 제3호서식", candidate_law_keys=("CAP_DRAFT",)
                )
            self.assertEqual(rows, [])

    def test_program_form_list_returns_only_statutory_forms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            form3 = root / "별지3_사업장일반정보__aaaaaaaaaaaaaaaa.pdf"
            appendix = root / "별표1_기준__bbbbbbbbbbbbbbbb.pdf"
            form5 = root / "별지5_세부취급시설__cccccccccccccccc.pdf"
            for path in (form3, appendix, form5):
                path.write_bytes(path.name.encode("utf-8"))
            with patch.object(official_forms, "PROJECT_ROOT", root), patch.object(
                official_forms, "observed_pdf_paths", return_value=[form5, appendix, form3]
            ), patch.object(official_forms, "observed_source", return_value=self._source()):
                rows = official_forms.list_official_forms_for_program("화학사고예방관리계획서")
            self.assertEqual([row.form_reference for row in rows], ["별지 제3호서식", "별지 제5호서식"])

    def test_same_form_number_is_isolated_by_program(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap_form = root / "cap" / "별지3_사업장일반정보__aaaaaaaaaaaaaaaa.pdf"
            psm_form = root / "psm" / "별지3_다른서식__bbbbbbbbbbbbbbbb.pdf"
            cap_form.parent.mkdir()
            psm_form.parent.mkdir()
            cap_form.write_bytes(b"cap-form")
            psm_form.write_bytes(b"psm-form")

            def paths(key):
                return [cap_form] if key == "CAP_DRAFT" else [psm_form]

            def source(key):
                if key == "CAP_DRAFT":
                    return self._source()
                return self._source(title="공정안전보고서의 제출·심사·확인 및 이행상태평가 등에 관한 규정")

            with patch.object(official_forms, "PROJECT_ROOT", root), patch.object(
                official_forms, "observed_pdf_paths", side_effect=paths
            ), patch.object(official_forms, "observed_source", side_effect=source):
                rows = official_forms.resolve_official_form_for_program(
                    "별지 제3호서식", "화학사고예방관리계획서"
                )
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].full_path, cap_form)
                self.assertEqual(official_forms.official_form_bytes(rows[0]), b"cap-form")

    def test_official_form_bytes_are_exact_source_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            form = root / "별지3_사업장일반정보__aaaaaaaaaaaaaaaa.pdf"
            content = b"official-pdf-bytes"
            form.write_bytes(content)
            with patch.object(official_forms, "PROJECT_ROOT", root), patch.object(
                official_forms, "observed_pdf_paths", return_value=[form]
            ), patch.object(official_forms, "observed_source", return_value=self._source()):
                row = official_forms.resolve_official_form(
                    "별지 제3호서식", candidate_law_keys=("CAP_DRAFT",)
                )[0]
                self.assertEqual(official_forms.official_form_bytes(row), content)


if __name__ == "__main__":
    unittest.main()

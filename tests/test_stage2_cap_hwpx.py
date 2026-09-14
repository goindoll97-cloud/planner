from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hwpx import HwpxDocument

from engine.stage2.cap_hwpx import (
    TEMPLATE_FIELD_KEY,
    build_cap_hwpx_draft,
    load_registered_cap_template_bytes,
    normalize_cap_template_upload,
    register_cap_template,
    registered_cap_template,
    validate_cap_hwpx_template,
)
from engine.stage2.project import EvidenceRef, Stage2Project


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARKERS = (
    "[별지 제1호서식]", "[별지 제3호서식]", "[별지 제4호서식]", "[별지 제5호서식]",
    "[별지 제6호서식]", "[별지 제7호서식]", "[별지 제8호서식]", "[별지 제9호서식]",
    "[별지 제10호서식]", "[별지 제11호서식]", "[별지 제12호서식]", "[별지 제13호서식]",
    "[별지 제14호서식]", "[별지 제15호서식]", "[별지 제16호서식]",
)


def _synthetic_official_like_hwpx() -> bytes:
    doc = HwpxDocument.new()
    for marker in MARKERS:
        doc.add_paragraph(marker)

    doc.add_paragraph("사업장 일반정보")
    table = doc.add_table(rows=3, cols=2)
    table.set_cell_text(0, 0, "사업장명")
    table.set_cell_text(0, 1, "")
    table.set_cell_text(1, 0, "우편번호/주소")
    table.set_cell_text(1, 1, "")
    table.set_cell_text(2, 0, "작성수준")
    table.set_cell_text(2, 1, "")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "template.hwpx"
        doc.save_to_path(path)
        return path.read_bytes()


class CAPHwpxTemplateTests(unittest.TestCase):
    def _project(self) -> Stage2Project:
        project = Stage2Project(
            project_id="S2-HWPX-TEST",
            company_name="원본서식화학",
            cap_required=True,
            cap_group="2군",
            scope_confirmed=True,
            cap_selected=True,
        )
        project.set_field("business.company_name", "회사명", "원본서식화학", "VERIFIED")
        project.set_field("business.address", "사업장 소재지", "테스트시 법정로 1", "USER_CONFIRMED")
        return project

    def test_template_validation_requires_current_form_markers(self):
        data = _synthetic_official_like_hwpx()
        result = validate_cap_hwpx_template(data)
        self.assertTrue(result.ok)
        self.assertEqual(len(result.missing_markers), 0)
        self.assertEqual(len(result.found_markers), len(MARKERS))
        self.assertEqual(len(result.sha256), 64)

    def test_hwpx_upload_is_accepted_but_docx_is_not(self):
        data = _synthetic_official_like_hwpx()
        normalized, source_format = normalize_cap_template_upload("법제처_별지.hwpx", data)
        self.assertEqual(normalized, data)
        self.assertEqual(source_format, "HWPX")
        with self.assertRaisesRegex(ValueError, "hwpx 또는 .hwp"):
            normalize_cap_template_upload("변환본.docx", b"not allowed")

    def test_registered_original_template_keeps_hash_and_is_separate_from_company_facts(self):
        data = _synthetic_official_like_hwpx()
        project = self._project()
        evidence = EvidenceRef(
            source_type="OFFICIAL_LEGAL_TEMPLATE",
            source_name="법제처_별지.hwpx",
            sha256="a" * 64,
            location="/tmp/lawgo-template.hwpx",
        )
        validation = register_cap_template(
            project,
            evidence=evidence,
            hwpx_bytes=data,
            source_format="HWPX",
        )
        meta = registered_cap_template(project)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["sha256"], validation.sha256)
        self.assertEqual(meta["template_source"], "PROJECT_UPLOAD")
        self.assertEqual(project.get_field(TEMPLATE_FIELD_KEY).status, "USER_CONFIRMED")
        self.assertEqual(project.get_field("business.company_name").value, "원본서식화학")

    def test_current_approved_law_archive_is_used_without_project_upload(self):
        data = _synthetic_official_like_hwpx()
        project = self._project()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "법제처_CAP_별표별지.hwpx"
            path.write_bytes(data)
            with patch("engine.stage2.cap_hwpx.approved_source_files", return_value=[path]) as approved:
                meta = registered_cap_template(project)
                self.assertIsNotNone(meta)
                self.assertEqual(meta["template_source"], "APPROVED_LAW_ARCHIVE")
                self.assertIn("자동동기화", meta["source_format"])
                self.assertEqual(load_registered_cap_template_bytes(project), data)
                self.assertTrue(approved.call_args.kwargs["require_current"])

    def test_build_fills_only_existing_official_cells_without_redrawing_form(self):
        data = _synthetic_official_like_hwpx()
        project = self._project()
        result = build_cap_hwpx_draft(project, template_bytes=data)
        self.assertGreaterEqual(result.applied_count, 3)
        self.assertTrue(result.data.startswith(b"PK"))
        self.assertTrue(validate_cap_hwpx_template(result.data).ok)

    def test_review_page_exposes_official_hwpx_primary_output(self):
        text = (PROJECT_ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("법제처 원본서식 HWPX", text)
        self.assertIn("normalize_cap_template_upload", text)
        self.assertIn("build_cap_hwpx_draft", text)
        self.assertIn("확인값 기준", text)
        self.assertIn("비교용 DOCX 초안", text)
        self.assertIn("AI 문장보강 비교본", text)

    def test_requirements_keep_pure_python_hwpx_and_windows_hancom_converter(self):
        text = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("python-hwpx==6.4.0", text)
        self.assertIn("pyhwpx==1.7.2; platform_system == \"Windows\"", text)


if __name__ == "__main__":
    unittest.main()

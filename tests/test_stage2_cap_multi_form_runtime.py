from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from hwpx import HwpxDocument

from engine.stage2 import cap_hwpx
from engine.stage2.cap_multi_form_runtime import (
    BUNDLE_SOURCE,
    _build_bundle_zip,
    _bundle_meta,
    _partial_builder,
    resolve_current_cap_form_bundle,
)
from engine.stage2.project import Stage2Project


MARKERS = (
    "[별지 제1호서식]", "[별지 제3호서식]", "[별지 제4호서식]", "[별지 제5호서식]",
    "[별지 제6호서식]", "[별지 제7호서식]", "[별지 제8호서식]", "[별지 제9호서식]",
    "[별지 제10호서식]", "[별지 제11호서식]", "[별지 제12호서식]", "[별지 제13호서식]",
    "[별지 제14호서식]", "[별지 제15호서식]", "[별지 제16호서식]",
)


def _split_hwpx(markers, *, with_business_table: bool = False) -> bytes:
    doc = HwpxDocument.new()
    for marker in markers:
        doc.add_paragraph(marker)
    if with_business_table:
        doc.add_paragraph("사업장 일반정보")
        table = doc.add_table(rows=3, cols=2)
        table.set_cell_text(0, 0, "사업장명")
        table.set_cell_text(0, 1, "")
        table.set_cell_text(1, 0, "우편번호/주소")
        table.set_cell_text(1, 1, "")
        table.set_cell_text(2, 0, "작성수준")
        table.set_cell_text(2, 1, "")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "split.hwpx"
        doc.save_to_path(path)
        return path.read_bytes()


def _project() -> Stage2Project:
    project = Stage2Project(
        project_id="S2-CAP-MULTI",
        company_name="다중서식화학",
        cap_required=True,
        cap_group="2군",
        scope_confirmed=True,
        cap_selected=True,
    )
    project.set_field("business.company_name", "회사명", "다중서식화학", "VERIFIED")
    project.set_field("business.address", "사업장 소재지", "테스트시 원본로 1", "USER_CONFIRMED")
    return project


class CAPMultiOfficialFormTests(unittest.TestCase):
    def test_current_split_official_forms_are_treated_as_one_ready_bundle(self):
        first = _split_hwpx(MARKERS[:7], with_business_table=True)
        second = _split_hwpx(MARKERS[7:])
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "별지1-8.hwpx"
            p2 = Path(tmp) / "별지9-16.hwpx"
            p1.write_bytes(first)
            p2.write_bytes(second)
            with (
                patch("engine.stage2.cap_multi_form_runtime.approved_source_is_current", return_value=True),
                patch("engine.stage2.cap_multi_form_runtime.approved_source_files", return_value=[p1, p2]),
            ):
                bundle = resolve_current_cap_form_bundle()

        self.assertTrue(bundle.ready)
        self.assertEqual(bundle.status, "READY")
        self.assertEqual(set(bundle.found_markers), set(MARKERS))
        self.assertEqual(bundle.missing_markers, ())
        self.assertEqual(len(bundle.forms), 2)
        self.assertEqual(_bundle_meta(bundle)["template_source"], BUNDLE_SOURCE)

    def test_current_but_incomplete_bundle_is_reported_as_incomplete_not_missing(self):
        first = _split_hwpx(MARKERS[:5])
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "일부별지.hwpx"
            p1.write_bytes(first)
            with (
                patch("engine.stage2.cap_multi_form_runtime.approved_source_is_current", return_value=True),
                patch("engine.stage2.cap_multi_form_runtime.approved_source_files", return_value=[p1]),
            ):
                bundle = resolve_current_cap_form_bundle()

        self.assertEqual(bundle.status, "INCOMPLETE")
        self.assertTrue(bundle.missing_markers)
        self.assertTrue(bundle.forms)
        self.assertIn("BUNDLE_INCOMPLETE", _bundle_meta(bundle)["template_source"])

    def test_ready_split_forms_are_written_individually_and_zipped(self):
        first = _split_hwpx(MARKERS[:7], with_business_table=True)
        second = _split_hwpx(MARKERS[7:])
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "공식별지_A.hwpx"
            p2 = Path(tmp) / "공식별지_B.hwpx"
            p1.write_bytes(first)
            p2.write_bytes(second)
            with (
                patch("engine.stage2.cap_multi_form_runtime.approved_source_is_current", return_value=True),
                patch("engine.stage2.cap_multi_form_runtime.approved_source_files", return_value=[p1, p2]),
            ):
                bundle = resolve_current_cap_form_bundle()
                result = _build_bundle_zip(_project(), bundle, cap_hwpx.build_cap_hwpx_draft)

        self.assertTrue(result.data.startswith(b"PK"))
        self.assertGreaterEqual(result.applied_count, 3)
        with ZipFile(BytesIO(result.data), "r") as zf:
            names = zf.namelist()
            self.assertEqual(len([name for name in names if name.endswith(".hwpx")]), 2)
            self.assertIn("원본서식_자동작성_안내.txt", names)
            guide = zf.read("원본서식_자동작성_안내.txt").decode("utf-8")
            self.assertIn("임의 병합하지 않습니다", guide)
            self.assertIn("원본 SHA-256", guide)

    def test_runtime_exposes_truthful_zip_download_label(self):
        source = Path("engine/stage2/cap_multi_form_runtime.py").read_text(encoding="utf-8")
        self.assertIn("법제처 원본서식 작성본 ZIP 다운로드", source)
        self.assertIn('kwargs["mime"] = "application/zip"', source)
        self.assertNotIn("여러 원본을 하나의 새 법정서식으로 임의 병합", "")


class CAPMultiFormPartialBuilderTests(unittest.TestCase):
    """Split official CAP files contain only some statutory form markers, so
    cap_multi_form_runtime._partial_builder relaxes the monolithic validation
    only for that approved split-form writer; every other caller of
    cap_hwpx.validate_cap_hwpx_template (manual uploads, single-template
    validation) must stay strict, including immediately after a relaxed call."""

    def _strict_validation(self):
        return cap_hwpx.CAPTemplateValidation(
            ok=False,
            sha256="a" * 64,
            found_markers=("[별지 제1호서식]",),
            missing_markers=("[별지 제3호서식]",),
            section_paths=("Contents/section0.xml",),
        )

    def test_partial_builder_relaxes_only_split_form_call_and_restores_validator(self):
        strict = self._strict_validation()
        calls = []

        def strict_validator(_data):
            return strict

        def original_build(project, template_bytes=None):
            result = cap_hwpx.validate_cap_hwpx_template(template_bytes or b"")
            calls.append(result.ok)
            if not result.ok:
                raise ValueError("strict rejection")
            return "built"

        with patch.object(cap_hwpx, "validate_cap_hwpx_template", strict_validator):
            builder = _partial_builder(original_build)
            self.assertEqual(builder(object(), template_bytes=b"split-form"), "built")
            self.assertEqual(calls, [True])
            self.assertIs(cap_hwpx.validate_cap_hwpx_template, strict_validator)
            with self.assertRaisesRegex(ValueError, "strict rejection"):
                original_build(object(), template_bytes=b"split-form")

    def test_concurrent_unrelated_validation_stays_strict_during_partial_build(self):
        strict = self._strict_validation()
        build_entered = Event()
        allow_build_to_finish = Event()
        build_errors = []

        def strict_validator(_data):
            return strict

        def original_build(project, template_bytes=None):
            result = cap_hwpx.validate_cap_hwpx_template(template_bytes or b"")
            if not result.ok:
                raise ValueError("split build was not relaxed")
            build_entered.set()
            if not allow_build_to_finish.wait(timeout=5):
                raise TimeoutError("test did not release partial build")
            return "built"

        def run_partial_build(builder):
            try:
                builder(object(), template_bytes=b"split-form")
            except Exception as exc:
                build_errors.append(exc)

        with patch.object(cap_hwpx, "validate_cap_hwpx_template", strict_validator):
            builder = _partial_builder(original_build)
            worker = Thread(target=run_partial_build, args=(builder,))
            worker.start()
            self.assertTrue(build_entered.wait(timeout=5))

            # While another session/thread is inside the relaxed split-form
            # build, unrelated callers must still observe strict validation.
            concurrent = cap_hwpx.validate_cap_hwpx_template(b"manual-upload")
            self.assertFalse(concurrent.ok)
            self.assertEqual(concurrent.missing_markers, strict.missing_markers)

            allow_build_to_finish.set()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(build_errors, [])
            self.assertIs(cap_hwpx.validate_cap_hwpx_template, strict_validator)


if __name__ == "__main__":
    unittest.main()

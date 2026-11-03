"""The Windows converter must return a real HWP 5.0 file, never a renamed DOCX."""
from types import ModuleType
import sys
import unittest
from unittest.mock import patch

from engine.stage2 import cap_hwp_export
from engine.stage2.hwp5_binary import HWP5_MAGIC, from_hwpx
from hwpx import HwpxDocument


class CapHwpExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        doc = HwpxDocument.new()
        doc.add_paragraph("화학사고예방관리계획서 초안")
        cls.valid_hwp = from_hwpx(doc.to_bytes())


    def test_workspace_prefers_completed_docx_conversion(self):
        from types import SimpleNamespace
        project = SimpleNamespace(company_name="가상새솔화학")
        with (
            patch.object(cap_hwp_export, "available", return_value=True),
            patch.object(cap_hwp_export, "convert_docx_to_hwp", return_value=self.valid_hwp) as converted,
            patch.object(cap_hwp_export, "_require_company_text") as verified,
        ):
            result = cap_hwp_export.build_workspace_hwp(project, b"PK completed docx bytes")
        converted.assert_called_once_with(b"PK completed docx bytes")
        verified.assert_called_once_with(self.valid_hwp, "가상새솔화학")
        self.assertEqual(result.mode, "docx_converted")
        self.assertEqual(result.data, self.valid_hwp)
        self.assertFalse(result.warnings)

    def test_workspace_non_windows_populates_original_form_when_possible(self):
        from types import SimpleNamespace
        from engine.stage2 import cap_hwpx
        project = SimpleNamespace(company_name="가상새솔화학")
        mapped = SimpleNamespace(data=b"PK hwpx", applied_count=18, warnings=("일부 셀 미작성",))
        with (
            patch.object(cap_hwp_export, "available", return_value=False),
            patch.object(cap_hwpx, "build_cap_hwpx_draft", return_value=mapped) as renderer,
            patch("engine.stage2.hwp5_binary.from_hwpx", return_value=self.valid_hwp),
            patch.object(cap_hwp_export, "_require_company_text"),
        ):
            result = cap_hwp_export.build_workspace_hwp(project, b"PK completed docx bytes")
        self.assertEqual(result.mode, "official_mapped")
        self.assertEqual(result.applied_count, 18)
        self.assertEqual(result.data, self.valid_hwp)
        self.assertTrue(result.warnings)
        renderer.assert_called_once()
        self.assertGreater(len(renderer.call_args.kwargs["template_bytes"]), 100)

    def test_workspace_falls_back_to_basic_only_if_mapping_fails(self):
        from types import SimpleNamespace
        from engine.stage2 import cap_hwpx, cap_direct_hwp
        project = SimpleNamespace(company_name="가상새솔화학")
        with (
            patch.object(cap_hwp_export, "available", return_value=True),
            patch.object(cap_hwp_export, "convert_docx_to_hwp", side_effect=RuntimeError("converter offline")),
            patch.object(cap_hwpx, "build_cap_hwpx_draft", side_effect=RuntimeError("mapping unavailable")),
            patch.object(cap_direct_hwp, "build_partial_hwp", return_value=self.valid_hwp) as partial,
            patch.object(cap_hwp_export, "_require_company_text"),
        ):
            result = cap_hwp_export.build_workspace_hwp(project, b"PK completed docx bytes")
        partial.assert_called_once_with(project)
        self.assertEqual(result.mode, "basic_only")
        self.assertEqual(result.data, self.valid_hwp)
        self.assertGreaterEqual(len(result.warnings), 2)

    def test_workspace_rejects_non_docx_input(self):
        from types import SimpleNamespace
        with self.assertRaisesRegex(ValueError, "DOCX"):
            cap_hwp_export.build_workspace_hwp(
                SimpleNamespace(company_name="시험"), b"not a DOCX"
            )

    def test_company_validation_rejects_blank_looking_hwp(self):
        with self.assertRaisesRegex(RuntimeError, "사업장명"):
            cap_hwp_export._require_company_text(self.valid_hwp, "가상새솔화학")

    def test_windows_hancom_conversion_uses_docx_and_verifies_hwp_signature(self):
        calls = []
        valid_hwp = self.valid_hwp

        class FakeHwp:
            def __init__(self, new=False, visible=False):
                calls.append(("init", new, visible))

            def open(self, path, format=""):
                calls.append(("open", format, open(path, "rb").read()))
                return True

            def save_as(self, path, format, arg):
                calls.append(("save", format))
                with open(path, "wb") as file:
                    file.write(valid_hwp)
                return True

            def quit(self):
                calls.append(("quit",))

        fake = ModuleType("pyhwpx")
        fake.Hwp = FakeHwp
        with patch.object(cap_hwp_export.platform, "system", return_value="Windows"), patch.dict(sys.modules, {"pyhwpx": fake}):
            result = cap_hwp_export.convert_docx_to_hwp(b"sample-docx")
        self.assertTrue(result.startswith(HWP5_MAGIC))
        self.assertIn(("init", True, True), calls)
        self.assertIn(("open", "", b"sample-docx"), calls)
        self.assertIn(("save", "HWP"), calls)
        self.assertIn(("quit",), calls)

    def test_rejects_non_hwp_result(self):
        class FakeHwp:
            def __init__(self, new=False, visible=False):
                pass

            def open(self, path, format=""):
                return True

            def save_as(self, path, format, arg):
                with open(path, "wb") as file:
                    file.write(b"PK-renamed-docx")
                return True

            def quit(self):
                pass

        fake = ModuleType("pyhwpx")
        fake.Hwp = FakeHwp
        with patch.object(cap_hwp_export.platform, "system", return_value="Windows"), patch.dict(sys.modules, {"pyhwpx": fake}):
            with self.assertRaisesRegex(RuntimeError, "HWP 5.0"):
                cap_hwp_export.convert_docx_to_hwp(b"sample-docx")

    def test_rejects_damaged_ole_with_hwp_magic(self):
        class FakeHwp:
            def __init__(self, new=False, visible=False):
                pass

            def open(self, path, format=""):
                return True

            def save_as(self, path, format, arg):
                with open(path, "wb") as file:
                    file.write(HWP5_MAGIC + b"damaged")
                return True

            def quit(self):
                pass

        fake = ModuleType("pyhwpx")
        fake.Hwp = FakeHwp
        with patch.object(cap_hwp_export.platform, "system", return_value="Windows"), patch.dict(sys.modules, {"pyhwpx": fake}):
            with self.assertRaisesRegex(RuntimeError, "본문 구조"):
                cap_hwp_export.convert_docx_to_hwp(b"sample-docx")

    def test_non_windows_reports_unavailable(self):
        with patch.object(cap_hwp_export.platform, "system", return_value="Linux"):
            self.assertFalse(cap_hwp_export.available())
            with self.assertRaisesRegex(RuntimeError, "Windows"):
                cap_hwp_export.convert_docx_to_hwp(b"sample-docx")

    def test_automatic_open_falls_back_to_explicit_ooxml(self):
        calls = []
        valid_hwp = self.valid_hwp

        class FakeHwp:
            def __init__(self, new=False, visible=False):
                pass

            def open(self, path, format=""):
                calls.append(format)
                return format == "OOXML"

            def save_as(self, path, format, arg):
                with open(path, "wb") as file:
                    file.write(valid_hwp)
                return True

            def quit(self):
                pass

        fake = ModuleType("pyhwpx")
        fake.Hwp = FakeHwp
        with patch.object(cap_hwp_export.platform, "system", return_value="Windows"), patch.dict(sys.modules, {"pyhwpx": fake}):
            result = cap_hwp_export.convert_docx_to_hwp(b"sample-docx")
        self.assertEqual(calls, ["", "OOXML"])
        self.assertTrue(result.startswith(HWP5_MAGIC))

"""The Windows converter must return a real HWP 5.0 file, never a renamed DOCX."""
from types import ModuleType
import sys
import unittest
from unittest.mock import patch

from engine.stage2 import cap_hwp_export
from engine.stage2.hwp5_binary import HWP5_MAGIC


class CapHwpExportTests(unittest.TestCase):
    def test_windows_hancom_conversion_uses_docx_and_verifies_hwp_signature(self):
        calls = []

        class FakeHwp:
            def __init__(self, visible=False):
                calls.append(("init", visible))

            def open(self, path, format):
                calls.append(("open", format, open(path, "rb").read()))
                return True

            def save_as(self, path, format, arg):
                calls.append(("save", format))
                with open(path, "wb") as file:
                    file.write(HWP5_MAGIC + b"test-content")
                return True

            def quit(self):
                calls.append(("quit",))

        fake = ModuleType("pyhwpx")
        fake.Hwp = FakeHwp
        with patch.object(cap_hwp_export.platform, "system", return_value="Windows"), patch.dict(sys.modules, {"pyhwpx": fake}):
            result = cap_hwp_export.convert_docx_to_hwp(b"sample-docx")
        self.assertTrue(result.startswith(HWP5_MAGIC))
        self.assertIn(("open", "OOXML", b"sample-docx"), calls)
        self.assertIn(("save", "HWP"), calls)
        self.assertIn(("quit",), calls)

    def test_rejects_non_hwp_result(self):
        class FakeHwp:
            def __init__(self, visible=False):
                pass

            def open(self, path, format):
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

    def test_non_windows_reports_unavailable(self):
        with patch.object(cap_hwp_export.platform, "system", return_value="Linux"):
            self.assertFalse(cap_hwp_export.available())
            with self.assertRaisesRegex(RuntimeError, "Windows"):
                cap_hwp_export.convert_docx_to_hwp(b"sample-docx")

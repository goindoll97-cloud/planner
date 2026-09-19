from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from engine import kosha_msds
from engine.stage2 import cap_site_lookup as lookup


class EnvFileTests(unittest.TestCase):
    def test_key_in_dot_env_is_used_without_any_other_lookup_running_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".env").write_text('# 카카오\nKAKAO_REST_API_KEY="abc123secret"\n', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=False), patch.object(kosha_msds, "PROJECT_ROOT", Path(tmp)), \
                 patch("pathlib.Path.cwd", return_value=Path(tmp)):
                os.environ.pop("KAKAO_REST_API_KEY", None)
                self.assertEqual(lookup.api_key(), "abc123secret")

    def test_real_environment_variable_wins_and_missing_key_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(kosha_msds, "PROJECT_ROOT", Path(tmp)), \
             patch("pathlib.Path.cwd", return_value=Path(tmp)):
            with patch.dict(os.environ, {"KAKAO_REST_API_KEY": "from-env"}):
                self.assertEqual(lookup.api_key(), "from-env")
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("KAKAO_REST_API_KEY", None)
                self.assertEqual(lookup.api_key(), "")


if __name__ == "__main__":
    unittest.main()


class EnvFileVariantsTests(unittest.TestCase):
    def _read(self, raw: bytes, preset: dict | None = None) -> str:
        with tempfile.TemporaryDirectory() as tmp, patch.object(kosha_msds, "PROJECT_ROOT", Path(tmp)), \
             patch("pathlib.Path.cwd", return_value=Path(tmp)):
            (Path(tmp) / ".env").write_bytes(raw)
            with patch.dict(os.environ, preset or {}, clear=False):
                if not preset:
                    os.environ.pop("KAKAO_REST_API_KEY", None)
                return lookup.api_key()

    def test_notepad_bom_on_the_first_line_does_not_hide_the_key(self):
        self.assertEqual(self._read("﻿KAKAO_REST_API_KEY=abc\n".encode("utf-8")), "abc")

    def test_export_prefix_spaces_and_crlf_are_accepted(self):
        self.assertEqual(self._read(b"LAW_OC=x\r\nexport KAKAO_REST_API_KEY = abc\r\n"), "abc")

    def test_an_empty_environment_variable_does_not_block_the_env_file(self):
        self.assertEqual(self._read(b"KAKAO_REST_API_KEY=abc\n", {"KAKAO_REST_API_KEY": ""}), "abc")


class DiagnosisTests(unittest.TestCase):
    def _diagnose(self, files: dict[str, str], env: dict | None = None) -> str:
        with tempfile.TemporaryDirectory() as tmp, patch.object(kosha_msds, "PROJECT_ROOT", Path(tmp)), \
             patch("pathlib.Path.cwd", return_value=Path(tmp)):
            for name, text in files.items():
                (Path(tmp) / name).write_text(text, encoding="utf-8")
            with patch.dict(os.environ, env or {}, clear=False):
                os.environ.pop("KAKAO_REST_API_KEY", None) if env is None else None
                return "\n".join(lookup.env_diagnosis())

    def test_wrong_file_name_is_pointed_out(self):
        text = self._diagnose({".env.txt": "KAKAO_REST_API_KEY=secretvalue\n"})
        self.assertIn("파일이 없습니다", text)
        self.assertIn(".env.txt", text)

    def test_misspelled_variable_name_is_listed_without_its_value(self):
        text = self._diagnose({".env": "KAKAO_API_KEY=secretvalue\n"})
        self.assertIn("정확한 이름 KAKAO_REST_API_KEY의 값이 없습니다", text)
        self.assertIn("KAKAO_API_KEY", text)
        self.assertNotIn("secretvalue", text)

    def test_missing_line_and_correct_line_are_distinguished_and_values_never_leak(self):
        self.assertIn("줄이 없습니다", self._diagnose({".env": "LAW_OC=abc\n# KAKAO_REST_API_KEY=zzz\n"}))
        ok = self._diagnose({".env": "KAKAO_REST_API_KEY=topsecret\n"})
        self.assertIn("값도 있습니다", ok)
        self.assertNotIn("topsecret", ok)

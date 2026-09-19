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

"""The Stage ③ save animation is visible only while the operation runs."""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from ui import save_loading_overlay as loading


def test_centered_save_overlay_is_rendered_during_operation_and_removed_after():
    placeholder = Mock()
    with patch.object(loading, "st") as streamlit:
        streamlit.empty.return_value = placeholder
        with loading.scenario_save_loading():
            streamlit.empty.assert_called_once_with()
            placeholder.markdown.assert_called_once()
            html = placeholder.markdown.call_args.args[0]
            assert placeholder.markdown.call_args.kwargs["unsafe_allow_html"] is True
            assert 'class="cap-stage3-save-overlay"' in html
            assert "position: fixed" in html
            assert "align-items: center" in html
            assert 'role="status"' in html
            assert "보호대상 정보를 저장하고 있습니다" in html
            assert "animation: cap-stage3-save-spin" in html
            placeholder.empty.assert_not_called()
        placeholder.empty.assert_called_once()


def test_centered_save_overlay_is_removed_after_validation_exception():
    placeholder = Mock()
    with patch.object(loading, "st") as streamlit:
        streamlit.empty.return_value = placeholder
        with pytest.raises(ValueError, match="입력 오류"):
            with loading.scenario_save_loading():
                raise ValueError("입력 오류")
        placeholder.empty.assert_called_once()

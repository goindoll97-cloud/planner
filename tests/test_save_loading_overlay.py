"""The Stage ③ save animation is visible only while the operation runs."""
from __future__ import annotations

from unittest.mock import Mock, patch
from contextlib import contextmanager
from pathlib import Path
import runpy

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


def test_global_loader_uses_generic_message_and_escapes_plain_text():
    placeholder = Mock()
    with patch.object(loading, "st") as streamlit:
        streamlit.empty.return_value = placeholder
        with loading.app_loading():
            pass
        html = placeholder.markdown.call_args.args[0]
        assert loading.DEFAULT_TITLE in html
        assert loading.DEFAULT_DESCRIPTION in html
        assert "보호대상 정보를 저장하고 있습니다" not in html
        placeholder.empty.assert_called_once()

    placeholder = Mock()
    with patch.object(loading, "st") as streamlit:
        streamlit.empty.return_value = placeholder
        with loading.app_loading("<임의 제목>", "저장 & 계산"):
            pass
        html = placeholder.markdown.call_args.args[0]
        assert "&lt;임의 제목&gt;" in html
        assert "저장 &amp; 계산" in html
        assert "<임의 제목>" not in html


def test_app_navigation_wraps_all_production_pages_in_common_loading_context():
    """Every production menu goes through app.py's one global loading scope."""
    root = Path(__file__).resolve().parents[1]
    events = []
    sections_captured = []

    class FakePage:
        def run(self):
            events.append("page.run")
            assert events[0] == "loading.enter"

    @contextmanager
    def fake_loading():
        events.append("loading.enter")
        try:
            yield
        finally:
            events.append("loading.exit")

    with (
        patch("streamlit.Page", side_effect=lambda path, **kwargs: path) as make_page,
        patch("streamlit.navigation", side_effect=lambda sections: (
            sections_captured.append(sections) or FakePage()
        )),
        patch("ui.save_loading_overlay.app_loading", side_effect=fake_loading),
        patch("engine.stage2.cap_final_form_runtime.install_cap_final_form_runtime"),
    ):
        runpy.run_path(str(root / "app.py"), run_name="__main__")

    assert events == ["loading.enter", "page.run", "loading.exit"]
    assert len(sections_captured) == 1
    sections = sections_captured[0]
    assert set(sections) == {"사업장 업무", "공정안전보고서", "사업장 판정", "참고"}
    assert len([p for group in sections.values() for p in group]) >= 8
    assert make_page.call_count == sum(len(group) for group in sections.values())


def test_global_loading_placeholder_is_removed_when_navigation_fails():
    placeholder = Mock()
    with patch.object(loading, "st") as streamlit:
        streamlit.empty.return_value = placeholder
        with pytest.raises(RuntimeError, match="페이지 오류"):
            with loading.app_loading():
                raise RuntimeError("페이지 오류")
        placeholder.empty.assert_called_once()


def test_real_streamlit_navigation_keeps_loader_compatible_with_page_configuration():
    """Run the actual multipage entrypoint, not only a mocked router.

    In Streamlit 1.49 the shared overlay is inserted between st.navigation
    and child-page execution. Verify it doesn't interfere with page config
    or the default page / page switching.
    """
    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "app.py", default_timeout=60).run()
    assert not app.exception, [e.value for e in app.exception]

    app.switch_page("ui/judgement_page.py").run()
    assert not app.exception, [e.value for e in app.exception]

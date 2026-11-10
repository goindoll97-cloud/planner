"""Guard against literal escaped newlines and cramped protected-target guidance."""
from __future__ import annotations

import ast
from pathlib import Path


def test_protected_target_help_is_readable_html_with_three_sections():
    source = (Path(__file__).resolve().parents[1] / "ui" / "evidence_workspace_page.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    matches = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "markdown" or not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        value = node.args[0].value
        if isinstance(value, str) and all(
            name in value for name in ("갑종 보호대상", "을종 보호대상", "환경수용체")
        ):
            matches.append((node, value))
    assert len(matches) == 1
    call, html = matches[0]
    assert "font-size: 1.1rem" in html
    assert "line-height: 1.75" in html
    assert html.count("<p ") == html.count("</p>") == 3
    assert html.count("<br>") >= 8
    assert "\\n-" not in html  # Neither escaped newline-plus-hyphen nor a visible list marker.
    assert not any(line.strip().startswith("- ") for line in html.splitlines())
    assert any(
        kw.arg == "unsafe_allow_html" and isinstance(kw.value, ast.Constant) and kw.value.value is True
        for kw in call.keywords
    )

def test_apartment_help_states_statutory_thresholds_without_automatic_classification():
    source = (Path(__file__).resolve().parents[1] / "ui" / "evidence_workspace_page.py").read_text(encoding="utf-8")
    assert "300명 이상" in source
    assert "1,000㎡ 이상" in source
    assert "을종에서 제외" in source
    assert "분류 확인 필요" in source
    assert "아파트는 수용 규모에 따라 구분이 달라질 수 있습니다." not in source

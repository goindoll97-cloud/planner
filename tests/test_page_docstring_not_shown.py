from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PageDocstringTests(unittest.TestCase):
    def test_no_bare_string_statement_after_the_first_line_of_a_page(self):
        """Streamlit은 모듈 안의 맨 문자열을 화면에 그린다. 설명문은 파일 맨 위 docstring이어야 개발자 문구가 사용자에게 보이지 않는다."""
        pages = sorted((ROOT / "ui").glob("*_page.py")) + [ROOT / "app.py"]
        self.assertTrue(pages)
        for path in pages:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for index, node in enumerate(tree.body):
                if index > 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    self.fail(f"{path.name}:{node.lineno} 화면에 그려지는 문자열 문장이 있습니다")


if __name__ == "__main__":
    unittest.main()

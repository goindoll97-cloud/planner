from __future__ import annotations

"""Reads the two regulation source documents kept under data/stage2/cap_sources.

- cap_forms_guideline.docx: 별지 제1~16호 only. It is the guideline for what the
  screens show (form titles, table headers, form notes).
- cap_annex_rules_260409.docx: contains 별표 1~4. These are rules the program
  learns (계산·판정 로직과 도움말 근거), not screen content.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

SOURCE_DIR = Path(__file__).resolve().parents[2] / "data" / "stage2" / "cap_sources"
FORMS_GUIDELINE = SOURCE_DIR / "cap_forms_guideline.docx"
ANNEX_RULES = SOURCE_DIR / "cap_annex_rules_260409.docx"

_FORM_HEAD = re.compile(r"^■.*\[별지 제(\d+)호서식\]")
_ANNEX_HEAD = re.compile(r"^\[별표 (\d+)\]$")


@dataclass(frozen=True)
class FormGuideline:
    no: int
    title: str
    headings: tuple[str, ...]
    tables: tuple[tuple[tuple[str, ...], ...], ...]
    notes: tuple[str, ...]

    def table_header(self, index: int) -> tuple[str, ...]:
        """Distinct header cells of table `index` within this form."""
        return tuple(dict.fromkeys(c for row in self.tables[index][:2] for c in row if c))


def _blocks(doc):
    for el in doc.element.body.iterchildren():
        if el.tag.endswith("}p"):
            yield Paragraph(el, doc)
        elif el.tag.endswith("}tbl"):
            yield Table(el, doc)


def _cells(table: Table) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(c.text.strip().replace("\n", " ") for c in row.cells) for row in table.rows)


@lru_cache(maxsize=1)
def form_guidelines() -> dict[int, FormGuideline]:
    doc = Document(str(FORMS_GUIDELINE))
    raw: dict[int, dict] = {}
    current = None
    for block in _blocks(doc):
        if isinstance(block, Table):
            if current:
                raw[current]["tables"].append(_cells(block))
            continue
        text = block.text.strip()
        match = _FORM_HEAD.match(text)
        if match:
            current = int(match.group(1))
            if current in raw:  # the source labels 별지 제14호 as 제13호 a second time
                current = max(raw) + 1
            raw[current] = {"title": "", "headings": [], "tables": [], "notes": []}
        elif current and text:
            item = raw[current]
            if not item["title"]:
                item["title"] = text
            elif re.match(r"^\d+(-\d+)?\. ", text):
                item["headings"].append(text)
            elif text.startswith("주)") or text[:1] in "①②③④⑤⑥⑦⑧⑨⑩":
                item["notes"].append(text)
    return {
        no: FormGuideline(no, v["title"], tuple(v["headings"]), tuple(v["tables"]), tuple(v["notes"]))
        for no, v in raw.items()
    }


@lru_cache(maxsize=1)
def annex_rules() -> dict[int, tuple[str, ...]]:
    """별표 number -> its numbered rule paragraphs (별표 1 = 최대보유량 산정 방법)."""
    doc = Document(str(ANNEX_RULES))
    rules: dict[int, list[str]] = {}
    current = None
    for block in _blocks(doc):
        if isinstance(block, Table):
            continue
        text = block.text.strip()
        match = _ANNEX_HEAD.match(text)
        if match:
            current = int(match.group(1))
            rules[current] = []
        elif text.startswith("■") or _FORM_HEAD.match(text):
            current = None
        elif current and re.match(r"^\d+\. ", text):
            rules[current].append(text)
    return {no: tuple(items) for no, items in rules.items()}


@lru_cache(maxsize=1)
def protected_target_rules() -> dict[str, dict[str, str]]:
    """별표 4: 구분(갑종·을종·환경수용체) -> {종류: 보호대상의 종류 설명(규모 조건 포함)}."""
    doc = Document(str(ANNEX_RULES))
    in_annex4 = False
    tables: list[tuple[tuple[str, ...], ...]] = []
    for block in _blocks(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if _ANNEX_HEAD.match(text):
                in_annex4 = text == "[별표 4]"
            elif text.startswith("■"):
                in_annex4 = False
        elif in_annex4 and len(tables) < 3:
            tables.append(_cells(block))
    result: dict[str, dict[str, str]] = {}
    for label, table in zip(("갑종", "을종", "환경수용체"), tables):
        entries: dict[str, str] = {}
        for row in table[1:]:
            cells = list(dict.fromkeys(c for c in row if c))
            if len(cells) >= 2:
                entries[" ".join(cells[-2].split())] = cells[-1]
        result[label] = entries
    return result


@lru_cache(maxsize=1)
def preliminary_scenario_quantities() -> dict[tuple[str, str], float]:
    """별표 2: (성상, 유해성 분류) -> 예비시나리오 규정수량(kg)."""
    doc = Document(str(ANNEX_RULES))
    result: dict[tuple[str, str], float] = {}
    for block in _blocks(doc):
        if not isinstance(block, Table):
            continue
        rows = _cells(block)
        if rows and "예비시나리오" in rows[0][0]:
            for row in rows[2:]:
                match = re.search(r"([\d,]+)\s*kg", row[2] if len(row) > 2 else "")
                if match:
                    result[(row[0].strip(), row[1].strip())] = float(match.group(1).replace(",", ""))
            break
    return result

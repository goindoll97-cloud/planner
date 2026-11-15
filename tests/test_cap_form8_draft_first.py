"""Planner principle: draft first, inspect the generated statutory form afterwards."""
from __future__ import annotations

from io import BytesIO

from docx import Document

from engine.stage2 import cap_target_review
from engine.stage2 import cap_form8_workspace as form8
from engine.stage2.cap_form8_engine import build_cap_form8_data
from engine.stage2.cap_catalog_docx import build_cap_draft
from engine.stage2.cap_baseline_docx import form_table_index_for
from engine.stage2.project import Stage2Project


def project():
    p = Stage2Project(project_id="DRAFT-FIRST-F8", company_name="가상 사업장", cap_required=True)
    p.set_authoring_scope(psm_selected=False, cap_selected=True)
    return p


def candidates(n=20):
    return [
        {
            "보호대상 명칭": f"주변시설 {i:02d}",
            "보호대상 구분": "갑종" if i % 2 == 0 else "",
            "세부유형": "교육·연구시설" if i % 2 == 0 else "",
            "주소·위치": "광주광역시 지도 조회 위치",
            "사업장 경계와 거리(m)": 20 + i * 10,
            "GIS/현장 근거": "GIS 조회 후보 · 2026-11-15",
            "거주민수": "", "근로자수": "",
        }
        for i in range(n)
    ]


def _form8_document(project):
    doc = Document(BytesIO(build_cap_draft(project)))
    first, second = (doc.tables[i] for i in form_table_index_for(doc)["8"])
    return doc, first, second


def test_first_save_even_without_dropdown_changes_populates_twenty_draft_rows():
    p = project()
    found = candidates()
    # Before the user touches any menu, only the GIS-proposed values exist.
    edited = [
        {key: row[key] for key in ("보호대상 명칭", "보호대상 구분",
                                  "세부유형", "사업장 경계와 거리(m)")}
        for row in cap_target_review.candidate_review_rows(p, found)
    ]
    changed, warnings = cap_target_review.apply_candidate_edits(p, edited, found)
    assert changed
    assert not warnings
    assert p.get_field(form8.SITE_KEY).status == "PROPOSED"

    prepared = build_cap_form8_data(p, for_draft=True)
    assert len(prepared.rows) == 20
    assert not prepared.ready  # Quality checks remain available AFTER the draft.
    assert any("500m 범위 전체" in message for message in prepared.blockers)

    _, first, second = _form8_document(p)
    text = "\n".join(cell.text for row in second.rows for cell in row.cells)
    for i in range(20):
        assert f"주변시설 {i:02d}" in text
    assert second.cell(1, 0).text == "1"
    assert second.cell(20, 0).text == "20"
    assert second.cell(1, 1).text == "교육·연구시설"
    assert second.cell(2, 1).text == "[확인 필요]"
    assert second.cell(2, 3).text == "30"
    assert "초안" in first.rows[1].cells[0].text
    assert "☒ 교육·연구시설" in " ".join(
        cell.text for row in first.rows for cell in row.cells
    )

    # Editing the same form twice must not add duplicates.
    changed, _ = cap_target_review.apply_candidate_edits(p, edited, found)
    assert not changed
    assert len(form8.saved_rows(p)) == 20


def test_legacy_hold_rows_are_visible_in_draft_but_not_misrepresented_as_approved():
    p = project()
    form8.save(p, candidates(2), no_target=False, scope_reviewed=False, status="HOLD")
    draft = build_cap_form8_data(p, for_draft=True)
    strict = build_cap_form8_data(p)
    assert len(draft.rows) == 2
    assert not draft.ready
    assert not strict.rows
    _, first, second = _form8_document(p)
    assert "보호대상 후보 2건" in first.rows[1].cells[0].text
    assert "주변시설 00" in second.cell(1, 2).text
    assert "주변시설 01" in second.cell(2, 2).text


def test_missing_distance_is_not_invented_as_zero_for_draft():
    p = project()
    row = candidates(1)[0]
    row["사업장 경계와 거리(m)"] = ""
    form8.save(p, [row], no_target=False, scope_reviewed=False, status="PROPOSED")
    _, _, listing = _form8_document(p)
    assert listing.cell(1, 3).text == "[확인 필요]"

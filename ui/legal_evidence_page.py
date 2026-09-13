from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from engine.legal_archive import evidence_rows, open_archive_folder
from engine.stage2.guidance import all_requirement_specs_for_library, requirement_library_search_text
from engine.stage2.intake import extract_form_references
from engine.stage2.official_forms import (
    list_official_forms_for_program,
    official_form_bytes,
    resolve_official_form_for_program,
)


LEGAL_FOCUS_KEY = "_legal_focus_requirement_key"

st.set_page_config(page_title="법령·근거 라이브러리", page_icon="📚", layout="wide")
st.title("📚 법령·근거 라이브러리")
st.caption(
    "작성항목을 검색하면 그 항목에 현재 구조화되어 연결된 법적 근거, 세부 작성기준, 작성 참고자료를 먼저 보여줍니다. "
    "승인 근거 PDF와 현행 공식 별지서식은 아래 전체 자료 보관영역에서 확인할 수 있습니다."
)


def _program_label(system: str) -> str:
    return {
        "PSM": "공정안전보고서",
        "CAP": "화학사고예방관리계획서",
        "COMMON": "공통자료",
    }.get(system, system)


def _basis_kind(text: str) -> str:
    value = str(text or "")
    if any(token in value for token in ("산업안전보건법", "화학물질관리법", "시행령", "시행규칙")):
        return "법적 의무 근거"
    if any(token in value for token in ("고시", "작성규정", "별표", "별지")):
        return "세부 작성기준"
    return "작성·실무 근거"


def _reference_title(system: str) -> str:
    if system == "PSM":
        return "공정안전보고서 지원시스템 작성예시집(형식 참고)"
    if system == "CAP":
        return "화학사고예방관리계획서 작성 매뉴얼"
    return ""


def _render_requirement(spec, *, expanded: bool = False) -> None:
    program = _program_label(spec.system)
    with st.expander(f"[{program}] {spec.section} · {spec.label}", expanded=expanded):
        if spec.description:
            st.write(spec.description)
        if spec.legal_basis:
            st.write(f"**{_basis_kind(spec.legal_basis)}**")
            st.code(spec.legal_basis)
        else:
            st.caption(
                "이 공통 작성항목 자체에는 직접 법적 근거가 저장되어 있지 않습니다. "
                "동일한 필드를 사용하는 공정안전보고서 또는 화학사고예방관리계획서 세부 항목의 근거를 함께 확인하세요."
            )

        if spec.manual_pages:
            title = _reference_title(spec.system)
            pages = ", ".join(str(v) for v in spec.manual_pages)
            if title:
                st.write(f"**작성 참고자료**: {title} · 관련 쪽 {pages}")

        forms = extract_form_references(spec.legal_basis)
        if forms:
            st.write("**관련 법정 서식**")
            for reference in forms:
                matches = resolve_official_form_for_program(reference, program)
                if len(matches) == 1:
                    form = matches[0]
                    st.download_button(
                        f"{reference} 다운로드",
                        data=official_form_bytes(form),
                        file_name=form.file_name,
                        mime=form.mime_type,
                        key=f"library_form_{spec.key}_{form.source_id}_{form.form_no}",
                        width="stretch",
                    )
                elif len(matches) > 1:
                    st.caption(f"{reference}: 동일 번호의 현행 공식 서식이 여러 건 있어 전체 자료 보관영역에서 확인하세요.")
                else:
                    st.caption(f"{reference}: 현재 등록된 현행 공식 서식 파일을 찾지 못했습니다.")


st.markdown("### 작성항목 근거 검색")
specs = all_requirement_specs_for_library()
query = st.text_input(
    "작성항목 또는 근거 검색",
    placeholder="예: 공정흐름도, 변경요소 관리계획, 내부 비상대응계획",
)

focus_key = str(st.session_state.get(LEGAL_FOCUS_KEY) or "").strip()
focus_spec = next((spec for spec in specs if spec.key == focus_key), None)
if focus_spec is not None:
    st.info(f"현재 선택된 작성항목: [{_program_label(focus_spec.system)}] {focus_spec.section} · {focus_spec.label}")
    _render_requirement(focus_spec, expanded=True)

if query.strip():
    q = query.strip().lower()
    matches = [spec for spec in specs if q in requirement_library_search_text(spec).lower()]
    st.caption(f"검색결과 {len(matches)}건")
    for spec in matches[:80]:
        _render_requirement(spec)
else:
    st.caption("검색어를 입력하면 작성항목별 법적 근거와 작성 참고자료를 확인할 수 있습니다.")

st.divider()
st.markdown("### 승인 근거 PDF · 로컬 보관소")
archive_df = pd.DataFrame(evidence_rows())
if archive_df.empty:
    st.caption("현재 표시할 승인 근거 PDF가 없습니다.")
else:
    display_archive = archive_df.copy()
    if "SHA256" in display_archive.columns:
        display_archive["SHA256"] = display_archive["SHA256"].astype(str).map(
            lambda value: value[:16] + "…" if len(value) > 16 else value
        )
    st.dataframe(display_archive, width="stretch", hide_index=True)
    available = archive_df[archive_df["보관상태"].eq("보관됨")]
    if not available.empty:
        columns = st.columns(min(4, len(available)))
        for idx, (_, row) in enumerate(available.iterrows()):
            key = str(row["key"])
            if columns[idx % len(columns)].button(
                f"폴더 열기 · {key}",
                key=f"library_open_archive_{key}",
                width="stretch",
            ):
                opened = open_archive_folder(key)
                if opened.get("status") == "OPENED":
                    st.toast(str(opened.get("message", "근거 폴더를 열었습니다.")))
                else:
                    st.warning(str(opened.get("message", "폴더를 열지 못했습니다.")))

st.markdown("### 현행 공식 별지서식")
for program in ("공정안전보고서", "화학사고예방관리계획서"):
    forms = list_official_forms_for_program(program)
    if not forms:
        continue
    with st.expander(f"{program} · {len(forms)}건", expanded=False):
        for form in forms:
            st.download_button(
                f"별지 제{form.form_no}호서식 · {form.title}",
                data=official_form_bytes(form),
                file_name=form.file_name,
                mime=form.mime_type,
                key=f"library_all_form_{form.source_id}_{form.form_no}_{form.file_name}",
                width="stretch",
            )

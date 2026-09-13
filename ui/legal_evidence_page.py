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
st.title("📚 7. 법령·근거 라이브러리")
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
                        f"{reference} 공식 PDF",
                        data=official_form_bytes(form),
                        file_name=form.file_name,
                        mime="application/pdf",
                        key=f"library_form_{spec.key}_{form.law_key}_{reference}",
                        width="stretch",
                    )
                    st.caption(
                        f"시행일 {form.effective_date or '-'} · 발령번호 {form.issue_number or '-'} · SHA-256 {form.sha256[:16]}…"
                    )
                elif len(matches) > 1:
                    st.warning(f"{reference}: 현재 공식자료에서 둘 이상의 서식이 연결되어 자동 선택하지 않습니다.")
                else:
                    st.caption(f"{reference}: 현재 CURRENT 상태의 공식 PDF를 직접 연결하지 못했습니다.")

        if spec.suggested_evidence:
            st.write("**회사에서 확인할 수 있는 자료 예**")
            st.write(" · ".join(spec.suggested_evidence))
        st.caption(f"registry key: {spec.key}")


specs = all_requirement_specs_for_library()
focus_key = str(st.session_state.get(LEGAL_FOCUS_KEY) or "")
focus_spec = next((spec for spec in specs if spec.key == focus_key), None)
default_query = focus_spec.label if focus_spec is not None else ""

st.markdown("### 작성항목 근거 검색")
query = st.text_input(
    "찾고 싶은 작성항목을 입력하세요",
    value=default_query,
    placeholder="예: 공정흐름도, P&ID, 안전밸브, 비상연락체계",
)

if query.strip():
    token = query.strip().lower()
    matched = [spec for spec in specs if token in requirement_library_search_text(spec)]
    if not matched:
        st.warning("현재 작성 registry에서 검색어와 연결된 작성항목을 찾지 못했습니다.")
    else:
        st.success(f"검색결과 {len(matched)}건")
        for spec in matched[:40]:
            _render_requirement(spec, expanded=(focus_spec is not None and spec.key == focus_spec.key))
        if len(matched) > 40:
            st.caption("검색결과가 많아 앞의 40건만 표시합니다. 검색어를 더 구체적으로 입력하세요.")
else:
    st.info("작성항목명을 검색하면 해당 항목과 직접 연결된 근거부터 확인할 수 있습니다.")

st.divider()

rows = evidence_rows()
for row in rows:
    row["근거"] = (
        str(row.get("근거", ""))
        .replace("PSM", "공정안전보고서")
        .replace("화사계", "화학사고예방관리계획서")
    )

df = pd.DataFrame(rows)
with st.expander("전체 승인 근거자료·PDF 보관현황", expanded=False):
    if df.empty:
        st.info("아직 로컬에 보관된 승인 근거자료가 없습니다. ‘규정 DB 관리’에서 승인본 근거 PDF를 동기화하세요.")
    else:
        shown = df.copy()
        if "SHA256" in shown.columns:
            shown["SHA256"] = shown["SHA256"].astype(str).map(lambda v: v[:16] + "…" if len(v) > 16 else v)
        for col in shown.columns:
            shown[col] = shown[col].astype(str)
        st.dataframe(shown, width="stretch", hide_index=True)

        available = df[df["보관상태"].eq("보관됨")]
        if available.empty:
            st.warning("승인 DB는 있어도 근거 PDF가 아직 로컬 보관소에 동기화되지 않았습니다. 규정 DB 관리에서 동기화하세요.")
        else:
            for _, row in available.iterrows():
                key = str(row["key"])
                label = str(row["근거"])
                raw_path = str(row.get("로컬 PDF", ""))
                c1, c2, c3 = st.columns([4, 1, 1])
                c1.write(f"**{label}**")
                c1.caption(raw_path)
                if c2.button("폴더 열기", key=f"evidence_open_{key}", width="stretch"):
                    result = open_archive_folder(key)
                    if result.get("status") == "OPENED":
                        st.toast(f"{label} 근거 폴더를 열었습니다.")
                    else:
                        st.warning(str(result.get("message", "폴더를 열지 못했습니다.")))
                local_path = Path(raw_path) if raw_path else None
                if local_path is not None and local_path.exists():
                    c3.download_button(
                        "PDF 받기",
                        data=local_path.read_bytes(),
                        file_name=local_path.name,
                        mime="application/pdf",
                        key=f"evidence_download_{key}",
                        width="stretch",
                    )

with st.expander("전체 현행 공식 법정 별지서식 PDF", expanded=False):
    st.caption(
        "법제처 공식 첨부파일 중 법령감시 결과가 CURRENT인 별지서식만 제공합니다. "
        "개정 감지 또는 최신성 미확인 상태의 파일은 제공하지 않습니다."
    )
    for program in ("공정안전보고서", "화학사고예방관리계획서"):
        forms = list_official_forms_for_program(program)
        if not forms:
            st.warning(f"{program}: 현재 CURRENT 상태로 제공할 공식 별지서식 PDF가 없습니다.")
            continue
        st.write(f"**{program} · {len(forms)}건**")
        for idx, form in enumerate(forms):
            c1, c2 = st.columns([5, 1])
            c1.write(f"**{form.form_reference}** · {form.source_title}")
            c1.caption(
                f"시행일 {form.effective_date or '-'} · 발령번호 {form.issue_number or '-'} · SHA-256 {form.sha256}"
            )
            c2.download_button(
                "공식 PDF",
                data=official_form_bytes(form),
                file_name=form.file_name,
                mime="application/pdf",
                key=f"official_form_{program}_{idx}_{form.law_key}",
                width="stretch",
            )

st.info(
    "이 화면의 검색결과는 현재 작성 registry에 구조화되어 연결된 근거만 보여줍니다. "
    "직접 근거가 등록되지 않은 세부항목에는 임의의 조문을 만들어 붙이지 않습니다."
)
st.caption(
    "승인 근거 PDF는 사람이 원문을 확인하기 위한 사본이며, 실제 판정 계산은 같은 공식 근거에서 검토·승인한 구조화 Regulatory DB를 사용합니다."
)

from __future__ import annotations

"""혼합물이 있는 사업장에만 보이는 두 번째 파일 업로드 UI."""

import pandas as pd
import streamlit as st

from engine.stage2 import cap_chemical_workspace as chem
from engine.stage2 import cap_judgement as judgement
from engine.stage2 import mixture_component_upload as comp
from engine.stage2 import storage
from ui import cap_frames as frames


def _missing_mixture_names(project) -> list[str]:
    _, rows = chem._rows(project)
    unresolved = set(judgement.composition_rows(project))
    names = []
    for number in sorted(unresolved):
        if 1 <= number <= len(rows) and judgement._mixture_yes(rows[number - 1].get("혼합물 여부")):
            names.append(str(rows[number - 1].get("제품명") or rows[number - 1].get("물질명") or f"{number}행").strip())
    return names


def render(project, prefix: str = "mix_components", *, continue_judgement: bool = False) -> bool:
    names = _missing_mixture_names(project)
    if not names:
        return False

    st.markdown(
        "**혼합물 구성성분 입력**",
        help=(
            "**왜 필요한가요?** 혼합제품은 제품명만으로 법적 물질을 판단하지 않습니다. "
            "제품 SDS 제3항의 구성성분 CAS No.와 함량(%)을 기준으로 판정합니다.\n\n"
            "**어디서 확인하나요?** 제품 SDS 제3항 '구성성분의 명칭 및 함유량'을 확인하세요.\n\n"
            "**방법** 아래 두 번째 파일을 내려받아 CAS No.와 함량(%)만 채운 뒤 다시 올리면 됩니다."
        ),
    )
    st.caption("혼합제품: " + ", ".join(names))
    st.download_button(
        "혼합물 구성성분 양식 내려받기",
        data=comp.blank_template(names),
        file_name="혼합물_구성성분_양식.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{prefix}_download_{project.project_id}",
    )
    upload = st.file_uploader(
        "혼합물 구성성분 파일(.xlsx 또는 .csv)",
        type=["xlsx", "xlsm", "csv"],
        key=f"{prefix}_file_{project.project_id}",
        help="제품 SDS 제3항을 보고 '혼합제품명 / CAS No. / 함량(%)'만 적은 두 번째 파일입니다.",
    )
    if upload is None:
        return True

    try:
        checked = comp.check(upload.getvalue(), upload.name, names)
    except Exception as exc:
        st.error(f"파일을 읽지 못했습니다: {exc}")
        return True

    if checked.rows:
        frames.show(pd.DataFrame(checked.rows), width="stretch", hide_index=True)
    for warning in checked.warnings:
        st.warning(warning)
    for error in checked.errors:
        st.error(error)

    confirmed = st.checkbox(
        "입력한 CAS No.와 함량(%)을 각 제품의 SDS 제3항과 대조해 확인했습니다.",
        key=f"{prefix}_confirmed_{project.project_id}",
    )
    if st.button(
        "혼합물질 성분 확정하기",
        type="primary",
        disabled=not checked.ok or not confirmed,
        key=f"{prefix}_save_{project.project_id}",
    ):
        try:
            comp.save_to_project(project, checked.rows, sds_confirmed=confirmed)
        except ValueError as exc:
            st.error(str(exc))
            return True
        storage.save_project(project)
        if continue_judgement:
            st.session_state[f"judge_out_{project.project_id}"] = judgement.judge(project)
        else:
            st.session_state.pop(f"judge_out_{project.project_id}", None)
        st.success("혼합물 구성성분을 저장했습니다.")
        st.rerun()
    return True

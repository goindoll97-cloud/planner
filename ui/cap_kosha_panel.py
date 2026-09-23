from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

from engine.stage2 import cap_chemical_workspace as chem_ws
from engine.stage2.storage import save_project


def render(project, key_prefix: str) -> None:
    """KOSHA lookup for single substances: fetch → review candidates → apply on confirmation."""
    st.subheader("물질 정보 자동 조회 (KOSHA)")
    singles = chem_ws.single_substance_cas(project)
    st.caption(
        "단일물질만 조회합니다(혼합물 제외). KOSHA로는 CAS 번호만 전송하고, 물질상태·비중·폭발한계·독성구분 등 "
        "KOSHA가 명시한 값만 후보로 보여 줍니다. 이미 입력한 값은 덮어쓰지 않습니다."
    )
    if not singles:
        st.info("조회할 단일물질(CAS 번호 1개)이 없습니다.")
        return
    if st.button(f"KOSHA에서 {len(singles)}개 물질 정보 조회", key=f"{key_prefix}_kosha_{project.project_id}"):
        items = chem_ws.fetch_references(project)
        save_project(project)
        for item in items:
            (st.success if item.status == "REFERENCE_READY" else st.warning)(
                f"{item.cas} {item.chemical_name}: {item.message}"
            )
    found = chem_ws.candidates(project)
    if found:
        frames.show(
            pd.DataFrame([{"CAS": c.cas, "물질": c.name, "항목": c.field, "KOSHA 값": c.value, "출처": c.source} for c in found]),
            width="stretch", hide_index=True,
        )
        if st.button("후보를 확인했습니다 — 물성 칸에 반영", type="primary", key=f"{key_prefix}_apply_{project.project_id}"):
            written = chem_ws.apply_candidates(project, sorted({c.cas for c in found}))
            save_project(project)
            st.success(f"{written}개 칸을 반영했습니다. 제품 MSDS와 다르면 MSDS 값으로 고쳐 주세요.")
            st.rerun()

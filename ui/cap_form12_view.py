from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2 import cap_scenario_workspace as sc
from engine.stage2 import cap_workspace as ws
from engine.stage2.storage import save_project


def render(project) -> None:
    schema = ws.load_form_schema(12)
    st.header(schema["title"])
    step = schema["steps"][0]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])
    st.info("영향범위(누출률·피해반경) 계산과 주민·보호대상 입력은 다음 단계에서 추가됩니다.")

    targets = sc.evaluate(project)
    if not targets:
        st.warning("별지 제1호에서 시설을 입력하면 예비시나리오 대상 여부를 판정합니다.")
        return
    st.dataframe(
        pd.DataFrame([{
            "설비": t.tag or t.name, "물질": t.material, "구분": t.kind, "운전 성상": t.state,
            "취급량(kg)": t.holding_kg, "규정수량(kg)": t.threshold_kg, "판정": t.verdict, "근거": t.reason,
        } for t in targets]),
        width="stretch", hide_index=True,
    )

    proposed = sc.proposed_scenarios(project)
    saved = sc.saved_scenarios(project)
    st.subheader("사고시나리오 목록")
    if not proposed and not saved:
        st.caption("판정이 '대상'인 설비가 없습니다.")
        return
    columns = ["사고시나리오명", "대상 설비번호", "유해화학물질명", "사고유형", "취급량(kg)", "선정 근거"]
    frame = pd.DataFrame(saved or proposed, columns=columns)
    if not saved:
        st.caption("제안한 목록입니다. 실제와 다르면 고치거나 줄을 지운 뒤 저장하세요.")
    edited = st.data_editor(
        frame, num_rows="dynamic", width="stretch", hide_index=True,
        column_config={"사고유형": st.column_config.SelectboxColumn("사고유형", options=[sc.TOXIC, sc.FIRE])},
        key=f"cap_form12_scenarios_{project.project_id}",
    )
    if st.button("시나리오 목록 저장", type="primary", key=f"cap_form12_save_{project.project_id}"):
        saved_count = sc.save_scenarios(project, [{k: ("" if pd.isna(v) else v) for k, v in r.items()}
                                                   for r in edited.to_dict("records")])
        save_project(project)
        st.success(f"{saved_count}건을 저장했습니다. 별지 제14·15·16호에서도 이 목록을 씁니다.")

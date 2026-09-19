from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2 import cap_release_workspace as rw
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
    st.info("피해반경(영향거리) 계산과 주민·보호대상 입력은 다음 단계에서 추가됩니다.")

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
    columns = ["사고시나리오명", "대상 설비번호", "유해화학물질명", "사고유형", "취급량(kg)", rw.HEAD_COLUMN, "선정 근거"]
    frame = pd.DataFrame(saved or proposed, columns=columns)
    if not saved:
        st.caption("제안한 목록입니다. 실제와 다르면 고치거나 줄을 지운 뒤 저장하세요.")
    edited = st.data_editor(
        frame, num_rows="dynamic", width="stretch", hide_index=True,
        column_config={
            "사고유형": st.column_config.SelectboxColumn("사고유형", options=[sc.TOXIC, sc.FIRE]),
            rw.HEAD_COLUMN: st.column_config.TextColumn(
                rw.HEAD_COLUMN, help="상압 액체 설비에서 누출공 위의 액체 높이(m)입니다. 압력이 있는 설비는 비워도 됩니다."),
        },
        key=f"cap_form12_scenarios_{project.project_id}",
    )
    if st.button("시나리오 목록 저장", type="primary", key=f"cap_form12_save_{project.project_id}"):
        saved_count = sc.save_scenarios(project, [{k: ("" if pd.isna(v) else v) for k, v in r.items()}
                                                   for r in edited.to_dict("records")])
        save_project(project)
        st.success(f"{saved_count}건을 저장했습니다. 별지 제14·15·16호에서도 이 목록을 씁니다.")

    saved_now = sc.saved_scenarios(project)
    if saved_now:
        st.subheader("누출공·누출률·누출량 (제안값)")
        st.caption("누출공은 가장 큰 연결구의 20%(지침 3-3), 누출률은 오리피스 유출식, 누출시간은 API 581 등급표 기준입니다. "
                   "연결구·압력·온도는 별지 제9호에서 가져옵니다. 사람이 현장에서 직접 차단하는 경우는 차단으로 인정되지 않습니다(지침 3-3 ②).")
        left, right = st.columns(2)
        detection = left.selectbox("누출 감지 등급", ["C", "B", "A"], key=f"cap_form12_det_{project.project_id}",
                                   help="A: 운전변수 변화로 누출을 자동 감지, B: 적절한 계측으로 감지, C: 육안·현장 순찰")
        isolation = right.selectbox("누출 차단 등급", ["C", "B", "A"], key=f"cap_form12_iso_{project.project_id}",
                                    help="A: 자동 차단, B: 원격 조작 차단, C: 현장 수동 차단(지침은 수동 차단을 인정하지 않으므로 C로 봅니다)")
        rows_out = []
        for scenario in saved_now:
            result = rw.release_for_scenario(project, scenario, detection=detection, isolation=isolation)
            rows_out.append({
                "시나리오": scenario.get("사고시나리오명"),
                "누출공(mm)": round(result.hole_mm, 2) if result.hole_mm else None,
                "누출률(kg/s)": None if result.rate_kg_s is None else round(result.rate_kg_s, 4),
                "누출시간(분)": result.duration_min,
                "누출량(kg)": None if result.amount_kg is None else round(result.amount_kg, 1),
                "근거·필요한 정보": "; ".join(result.problems) or f"{result.hole_reason} / {result.model}",
            })
        st.dataframe(pd.DataFrame(rows_out), width="stretch", hide_index=True)

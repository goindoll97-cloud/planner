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
    st.info("화재·폭발 피해반경과 주민·보호대상 입력은 다음 단계에서 추가됩니다.")

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
    columns = ["사고시나리오명", "대상 설비번호", "유해화학물질명", "사고유형", "취급량(kg)", rw.HEAD_COLUMN,
               rw.BOUNDARY_COLUMN, "선정 근거"]
    frame = pd.DataFrame(saved or proposed, columns=columns)
    if not saved:
        st.caption("제안한 목록입니다. 실제와 다르면 고치거나 줄을 지운 뒤 저장하세요.")
    edited = st.data_editor(
        frame, num_rows="dynamic", width="stretch", hide_index=True,
        column_config={
            "사고유형": st.column_config.SelectboxColumn("사고유형", options=[sc.TOXIC, sc.FIRE]),
            rw.HEAD_COLUMN: st.column_config.TextColumn(
                rw.HEAD_COLUMN, help="상압 액체 설비에서 누출공 위의 액체 높이(m)입니다. 압력이 있는 설비는 비워도 됩니다."),
            rw.BOUNDARY_COLUMN: st.column_config.TextColumn(
                rw.BOUNDARY_COLUMN, help="설비에서 사업장 경계선까지 가장 가까운 거리(m)입니다. 피해반경이 이 거리를 넘으면 장외로 영향이 나갑니다."),
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
        worst = st.checkbox("최악조건 기상으로 계산(풍속 1.5 m/s, 안정도 F)", key=f"cap_form12_worst_{project.project_id}",
                            help="지침 2-4 ②: 최악조건 시나리오의 대기 조건입니다. 기본은 풍속 3 m/s, 안정도 D입니다.")
        weather = rw.default_weather(project, worst)
        st.caption(f"적용 기상: {weather.label}, {weather.terrain}지형(산업단지 여부로 결정, 지침 2-6)")
        rows_out = []
        effect_rows = []
        for scenario in saved_now:
            result = rw.release_for_scenario(project, scenario, detection=detection, isolation=isolation)
            if scenario.get("사고유형") == sc.TOXIC:
                effect = rw.toxic_effect_for_scenario(project, scenario, weather=weather, detection=detection, isolation=isolation)
                effect_rows.append({
                    "시나리오": scenario.get("사고시나리오명"),
                    "끝점": effect.endpoint_basis,
                    "피해반경(m)": None if effect.radius_m is None else round(effect.radius_m),
                    "장외거리(m)": None if effect.off_site_m is None else round(effect.off_site_m),
                    "판정": ("장외 영향 → 사고시나리오" if effect.off_site_m else "장내에 머묾")
                    if effect.off_site_m is not None else "",
                    "근거·필요한 정보": "; ".join(effect.problems) or f"{effect.source}. " + " ".join(effect.notes),
                })
            rows_out.append({
                "시나리오": scenario.get("사고시나리오명"),
                "누출공(mm)": round(result.hole_mm, 2) if result.hole_mm else None,
                "누출률(kg/s)": None if result.rate_kg_s is None else round(result.rate_kg_s, 4),
                "누출시간(분)": result.duration_min,
                "누출량(kg)": None if result.amount_kg is None else round(result.amount_kg, 1),
                "근거·필요한 정보": "; ".join(result.problems) or f"{result.hole_reason} / {result.model}",
            })
        st.dataframe(pd.DataFrame(rows_out), width="stretch", hide_index=True)
        if effect_rows:
            st.subheader("독성 누출 피해반경 (제안값)")
            st.caption("끝점농도는 기술지침 붙임 1(ERPG-2 → AEGL-2 → PAC-2 → IDLH×0.1), 확산은 지표 연속 누출 가우시안 플룸(Briggs 계수)입니다. "
                       "중가스 효과가 반영되지 않아 KORA와 수치가 다를 수 있으니 확정 전에 대조하세요.")
            st.dataframe(pd.DataFrame(effect_rows), width="stretch", hide_index=True)
        if any(r.get("사고유형") == sc.FIRE for r in saved_now):
            st.info("화재·폭발 피해반경(폭발 1 psi, 복사열 5 kW/m²)은 다음 단계에서 추가됩니다.")

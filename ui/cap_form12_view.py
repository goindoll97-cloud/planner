from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

from engine.stage2 import cap_basis_guides as basis
from engine.stage2 import cap_impact_workspace as iw
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

    targets = sc.evaluate(project)
    if not targets:
        st.warning("별지 제1호에서 시설을 입력하면 예비시나리오 대상 여부를 판정합니다.")
        return
    frames.show(
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
    columns = ["단위공장", "사고시나리오명", "대상 설비번호", "유해화학물질명", "사고유형", "취급량(kg)", rw.HEAD_COLUMN,
               rw.BOUNDARY_COLUMN, *rw.FLASH_COLUMNS, rw.LEAK_PIPE_COLUMN,
               rw.HEAT_COLUMN, rw.BOILING_COLUMN, rw.LIQUID_CP_KJ_COLUMN, rw.VAPORIZATION_COLUMN, "선정 근거"]
    frame = pd.DataFrame(saved or proposed, columns=columns)
    if not saved:
        st.caption("제안한 목록입니다. 실제와 다르면 고치거나 줄을 지운 뒤 저장하세요.")
    edited = st.data_editor(
        frame, num_rows="dynamic", width="stretch", hide_index=True,
        column_config={
            "사고유형": st.column_config.SelectboxColumn("사고유형", options=[sc.TOXIC, sc.FIRE]),
            rw.HEAD_COLUMN: st.column_config.TextColumn(
                rw.HEAD_COLUMN, help="상압 액체 설비에서 누출공 위의 액체 높이(m)입니다. 압력이 있는 설비는 비워도 됩니다."),
            rw.LATENT_HEAT_COLUMN: st.column_config.TextColumn(
                rw.LATENT_HEAT_COLUMN, help="염소·암모니아 같은 액화가스만 필요합니다. 운전온도에서의 증발잠열입니다. 세 값(잠열·비열·증기밀도)을 모두 적으면 2상 유출식(KOSHA GUIDE P-92 식 6)으로 계산합니다."),
            rw.LIQUID_CP_COLUMN: st.column_config.TextColumn(rw.LIQUID_CP_COLUMN, help="운전온도에서의 액체 비열입니다."),
            rw.VAPOR_DENSITY_COLUMN: st.column_config.TextColumn(rw.VAPOR_DENSITY_COLUMN, help="운전압력에서의 증기 밀도입니다."),
            rw.LEAK_PIPE_COLUMN: st.column_config.TextColumn(
                rw.LEAK_PIPE_COLUMN, help="설비 외면에서 누출지점까지의 배관 길이입니다. 0.1m 미만이면 비평형 유출이라 이 식을 쓰지 않습니다."),
            rw.HEAT_COLUMN: st.column_config.TextColumn(
                "연소열(kJ/kg)", help="화재·폭발 시나리오에 필요합니다. 제품 SDS 제9항이나 물성표의 연소열(kJ/kg)입니다."),
            rw.BOILING_COLUMN: st.column_config.TextColumn(
                "비점(℃)", help="액체 풀 화재의 연소속도 계산에만 필요합니다."),
            rw.LIQUID_CP_KJ_COLUMN: st.column_config.TextColumn(
                "액체비열(kJ/kg·K)", help="액체 풀 화재의 연소속도 계산에만 필요합니다."),
            rw.VAPORIZATION_COLUMN: st.column_config.TextColumn(
                "기화열(kJ/kg)", help="액체 풀 화재의 연소속도 계산에만 필요합니다."),
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

    with st.expander("이 계산의 근거 기술지침"):
        for guide in basis.basis_guides():
            st.markdown(f"**KOSHA GUIDE {guide['number']}** {guide['title']}  \n쓰이는 곳: {guide['used_in']}"
                        + (f"  \n검증: {guide['verified_edition']}" if guide.get("verified_edition") else ""))
        state_key = f"cap_basis_status_{project.project_id}"
        if st.button("현행 판 확인(코샤가이드 조회)", key=f"cap_basis_check_{project.project_id}",
                     help="공공데이터포털 코샤가이드 조회서비스로 각 지침의 최신 공표본을 찾습니다. 조회 결과만 표시하며 계산에는 영향이 없습니다."):
            st.session_state[state_key] = basis.basis_status()
        for status in st.session_state.get(state_key, []):
            st.write(f"• {status.summary}")
            if status.latest and status.latest.download_url:
                st.markdown(f"  [원문 내려받기]({status.latest.download_url})")

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
        fire_rows = []
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
            if scenario.get("사고유형") == sc.FIRE:
                fire_effect = rw.fire_effect_for_scenario(project, scenario, weather=weather, detection=detection,
                                                          isolation=isolation)
                fire_rows.append({
                    "시나리오": scenario.get("사고시나리오명"),
                    "폭발 1 psi(m)": None if fire_effect.explosion_m is None else round(fire_effect.explosion_m),
                    "화재 5 kW/m²(m)": None if fire_effect.fire_m is None else round(fire_effect.fire_m),
                    "피해반경(m)": None if fire_effect.radius_m is None else round(fire_effect.radius_m),
                    "장외거리(m)": None if fire_effect.off_site_m is None else round(fire_effect.off_site_m),
                    "판정": ("장외 영향 → 사고시나리오" if fire_effect.off_site_m else "장내에 머묾")
                    if fire_effect.off_site_m is not None else "",
                    "근거·필요한 정보": "; ".join(fire_effect.problems)
                    or f"{fire_effect.explosion_basis}. {fire_effect.fire_basis}. " + " ".join(fire_effect.notes),
                })
            rows_out.append({
                "시나리오": scenario.get("사고시나리오명"),
                "누출공(mm)": round(result.hole_mm, 2) if result.hole_mm else None,
                "누출률(kg/s)": None if result.rate_kg_s is None else round(result.rate_kg_s, 4),
                "누출시간(분)": result.duration_min,
                "누출량(kg)": None if result.amount_kg is None else round(result.amount_kg, 1),
                "근거·필요한 정보": "; ".join(result.problems) or f"{result.hole_reason} / {result.model}",
            })
        frames.show(pd.DataFrame(rows_out), width="stretch", hide_index=True)
        if effect_rows:
            st.subheader("독성 누출 피해반경 (제안값)")
            st.caption("끝점농도는 기술지침 붙임 1(ERPG-2 → AEGL-2 → PAC-2 → IDLH×0.1), 확산은 지표 연속 누출 가우시안 플룸(Briggs 계수)입니다. "
                       "중가스 효과가 반영되지 않아 KORA와 수치가 다를 수 있으니 확정 전에 대조하세요.")
            frames.show(pd.DataFrame(effect_rows), width="stretch", hide_index=True)
        if fire_rows:
            st.subheader("화재·폭발 피해반경 (제안값)")
            st.caption("끝점은 폭발 1 psi 과압, 화재 40초 5 kW/m²(기술지침 2-3 ① 2))입니다. 증기운 폭발은 EPA RMP TNT 당량식, 화재는 점광원 복사열 "
                       "모델이라 TNO 멀티에너지·BLEVE 화구는 반영되지 않습니다. KORA와 대조 후 확정하세요.")
            frames.show(pd.DataFrame(fire_rows), width="stretch", hide_index=True)

        st.subheader("영향범위 내 주민·보호대상 → 별지 제12·13호")
        st.caption("피해반경이 사업장 경계를 넘는 시나리오만 사고시나리오입니다(규정 제23조 ⑥). 별지 제8호 목록의 보호대상 중 경계 기준 거리가 "
                   "장외거리 이내인 것을 집계합니다. 풍향·지형은 반영하지 않는 보수적 원형 범위이고, 500m 밖은 별지 제8호에 없어 집계되지 않습니다.")
        impacts = iw.evaluate(project, worst_case=worst, detection=detection, isolation=isolation)
        frames.show(pd.DataFrame([{
            "시나리오": i.name, "유형": i.kind,
            "장외거리(m)": None if i.off_site_m is None else round(i.off_site_m),
            "사고시나리오": "예" if i.is_off_site else ("아니오" if i.off_site_m is not None else ""),
            "갑종": i.count("갑종"), "을종": i.count("을종"), "환경수용체": i.count("환경수용체"),
            "거주민": i.people("거주민수"), "근로자": i.people("근로자수"),
            "확인할 것": "; ".join(i.problems or i.notes[-1:] if i.off_site_m and i.off_site_m > iw.LISTED_RANGE_M else i.problems),
        } for i in impacts]), width="stretch", hide_index=True)
        st.write(iw.summary_text(impacts))
        apply_col, report_col = st.columns(2)
        if apply_col.button("결과를 별지 제12·13호에 반영", type="primary", key=f"cap_form12_apply_{project.project_id}"):
            counts = iw.apply_to_forms(project, impacts, worst_case=worst)
            save_project(project)
            st.success(f"장외 사고시나리오 {counts['scenarios']}건, 총괄영향범위 보호대상 {counts['targets']}건을 반영했습니다.")
        report_col.download_button(
            "영향범위 분석 근거서 DOCX 내려받기", data=iw.report_docx(project, impacts, worst_case=worst),
            file_name=f"영향범위_분석_근거서_{project.project_id}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"cap_form12_report_{project.project_id}",
            help="사고시나리오별 입력·적용 기준·결과·한계를 정리한 자료입니다. 계획서에 첨부하세요(규정 제23조 ⑥).")

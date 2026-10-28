from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

from engine.stage2 import cap_basis_guides as basis
from engine.stage2 import cap_impact_workspace as iw
from engine.stage2 import cap_release_workspace as rw
from engine.stage2 import cap_scenario_workspace as sc
from engine.stage2 import scenario_autowrite as auto
from engine.stage2 import scenario_evidence as se
from engine.stage2 import cap_workspace as ws
from engine.stage2.storage import save_project


def _scenario_editor_frame(rows: list[dict], columns: list[str]) -> pd.DataFrame:
    """Text-configured inputs must have string data even when source values are numeric."""
    frame = pd.DataFrame(rows, columns=columns)
    text_columns = (rw.HEAD_COLUMN, rw.LATENT_HEAT_COLUMN, rw.LIQUID_CP_COLUMN,
                    rw.VAPOR_DENSITY_COLUMN, rw.LEAK_PIPE_COLUMN, rw.HEAT_COLUMN,
                    rw.BOILING_COLUMN, rw.LIQUID_CP_KJ_COLUMN, rw.VAPORIZATION_COLUMN,
                    rw.BOUNDARY_COLUMN)
    for column in text_columns:
        if column in frame.columns:
            frame[column] = frame[column].astype("string").fillna("")
    return frame


def render(project) -> None:
    schema = ws.load_form_schema(12)
    st.header(schema["title"])
    step = schema["steps"][0]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    written = auto.sync(project)      # 사업장 업무에 올린 자료가 새로 확인됐으면 여기서 바로 저장합니다
    if any(written.values()):
        save_project(project)
        st.success(f"올린 자료로 자동 작성했습니다: 시나리오 {written['scenarios']}건, 개시사건 {written['frequency']}건, "
                   f"장외 영향 시나리오 {written['impact']}건.")
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
    base_rows, auto_sources = se.autofill(project, saved or proposed)
    frame = _scenario_editor_frame(base_rows, columns)
    if auto_sources:
        st.success(f"사업장 업무에 올린 자료에서 계산 입력 {len(auto_sources)}칸을 자동으로 채웠습니다. 표에 직접 적은 값은 덮어쓰지 않습니다.")
        with st.expander("자동으로 채운 값의 출처"):
            frames.show(pd.DataFrame(auto_sources), width="stretch", hide_index=True)
    else:
        st.caption("사업장 업무에서 시나리오 계산 입력(액위·경계까지 거리·연소열 등)이 든 자료를 올리면 아래 빈 칸이 자동으로 채워집니다.")
    frames.show(frame, width="stretch", hide_index=True)
    gaps = auto.missing(project)
    if gaps:
        st.warning("자료만으로는 채우지 못한 항목이 있습니다. 사업장 업무에서 해당 자료를 올리거나 질문에 답하면 이 서식에 바로 반영됩니다.")
        for gap in gaps:
            st.write(f"• {gap}")
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
        grades = se.grade_defaults(project, [t.tag for t in targets if t.verdict == sc.TARGET])
        detection, isolation, worst = grades.get("leak_detection", "C"), grades.get("leak_isolation", "C"), False
        st.caption(f"누출 감지 등급 {detection}, 차단 등급 {isolation}로 계산했습니다"
                   f"{'(자료에서 확인)' if grades else '(자료에 없어 보수적 기본값 C 적용)'}. 기상은 풍속 3 m/s, 안정도 D입니다.")
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
        st.download_button(
            "영향범위 분석 근거서 DOCX 내려받기", data=iw.report_docx(project, impacts, worst_case=worst),
            file_name=f"영향범위_분석_근거서_{project.project_id}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"cap_form12_report_{project.project_id}",
            help="사고시나리오별 입력·적용 기준·결과·한계를 정리한 자료입니다. 계획서에 첨부하세요(규정 제23조 ⑥).")

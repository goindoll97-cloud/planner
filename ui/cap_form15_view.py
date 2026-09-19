from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2 import cap_form15_workspace as f15
from engine.stage2 import cap_workspace as ws


def render(project) -> None:
    schema = ws.load_form_schema(15)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form15_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    result = f15.analysis(project)
    if result.no_offsite_scenario:
        st.success("장외 사고시나리오가 없어 위험도 분석을 생략하고 위험도 '다'를 적용합니다(작성 규정 제23조 ⑩).")
        return
    if step["id"] == "inputs":
        if result.scenario_rows:
            st.dataframe(pd.DataFrame(result.scenario_rows).drop(columns=["KORA/GIS 근거"], errors="ignore"),
                         width="stretch", hide_index=True)
        else:
            st.warning("별지 제12호에서 사고시나리오 영향범위를 반영하면 이 표가 채워집니다.")
        for blocker in result.blockers:
            st.write(f"• {blocker}")
    elif step["id"] == "scores":
        if result.scores:
            st.dataframe(pd.DataFrame([{"판단 요소": k, "값": v} for k, v in result.totals.items()]),
                         width="stretch", hide_index=True)
            st.dataframe(pd.DataFrame([{"항목": k, "점수/결과": v} for k, v in result.scores.items()
                                       if not k.startswith("최종")]), width="stretch", hide_index=True)
        else:
            st.warning("아직 점수를 계산할 수 없습니다. 1단계의 부족한 값을 채우세요.")
            for blocker in result.blockers:
                st.write(f"• {blocker}")
    else:
        if not result.scores:
            st.warning("점수 계산이 끝나지 않았습니다.")
            for blocker in result.blockers:
                st.write(f"• {blocker}")
            return
        st.metric("증감 전 위험도", result.scores["증감 전 위험도"],
                  help=f"판정표 점수 {result.scores['위험도 판정표 점수(증감 전)']}점")
        adj = result.adjustment
        st.write(f"**증가요인 +{adj.increase}점 / 감소요인 -{adj.decrease}점**")
        for reason in adj.reasons or ("적용되는 증감요인이 없습니다.",):
            st.write(f"• {reason}")
        st.info(f"증감을 반영한 참고 등급: **{result.reference_grade}** (적용 점수 {result.reference_score}점). "
                "최종 위험도는 화학물질안전원이 결정하므로 서식에는 확정값으로 적지 않습니다.")

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

from engine.stage2 import cap_form14_workspace as f14
from engine.stage2 import cap_workspace as ws
from engine.stage2 import scenario_autowrite as auto
from engine.stage2.cap_risk_engine import build_cap_form14_data
from engine.stage2.storage import save_project


def _result(project) -> None:
    data = build_cap_form14_data(project)
    if data.scenario_rows:
        frames.show(pd.DataFrame(data.scenario_rows), width="stretch", hide_index=True)
    if data.event_rows:
        with st.expander("개시사건별 계산"):
            frames.show(pd.DataFrame(data.event_rows), width="stretch", hide_index=True)
    if data.blockers:
        st.warning("자료로 채우지 못한 항목 — 사업장 업무에서 해당 자료를 올리거나 질문에 답하면 이 서식에 바로 반영됩니다.")
        for item in data.blockers:
            st.write(f"• {item}")
    else:
        st.success("모든 칸이 채워졌습니다.")


def render(project) -> None:
    schema = ws.load_form_schema(14)
    st.header(schema["title"])
    written = auto.sync(project)      # 사업장 업무에 올린 자료가 새로 확인됐으면 여기서 바로 저장합니다
    if any(written.values()):
        save_project(project)
        st.success(f"올린 자료로 자동 작성했습니다: 개시사건 {written['frequency']}건.")
    rows = f14.rows(project)
    if not rows:
        st.warning("별지 제12호의 사고시나리오가 정해지면 이 서식의 시나리오 목록이 자동으로 채워집니다. "
                   "사업장 업무에서 설비·물질·시나리오 검토 자료를 올렸는지 확인하세요.")
        return
    _result(project)

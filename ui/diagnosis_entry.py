from __future__ import annotations

import streamlit as st

from engine.law_monitor import run_law_monitor
from engine.readiness import decision_readiness_gate


@st.cache_data(ttl=3600, show_spinner=False)
def _law_rows():
    return run_law_monitor()


def _render_gate_hold(gate: dict[str, object]) -> None:
    st.title("✅ 1. 판정진단")
    st.error("법령 개정 또는 최신 규정자료 미반영이 감지되어 판정을 잠시 보류합니다.")
    st.write(str(gate.get("message") or "공식 최신본과 승인 DB의 출처 확인이 필요합니다."))
    blockers = gate.get("blockers") or []
    if blockers:
        with st.expander("관리자 확인사항", expanded=False):
            for blocker in blockers:
                st.write(f"• {str(blocker).replace('화사계', '화학사고예방관리계획서')}")
    st.info(
        "이 상태는 회사 Excel 입력 오류가 아니라 관리자 법령자료 준비상태입니다. "
        "‘규정 DB 관리’에서 **최신본 업데이트**를 한 번 실행하면 법제처 PDF·HWP/HWPX 원본, "
        "판정용 규정 DB와 근거자료를 함께 갱신하고 다시 판정 가능 여부를 확인합니다."
    )
    st.page_link("ui/regdb_page.py", label="규정 DB 관리에서 최신본 업데이트", icon="🗂️")


rows = _law_rows()
gate = decision_readiness_gate(rows)
if gate.get("decision") != "ALLOW":
    _render_gate_hold(gate)
    st.stop()

# 회사가 업로드한 Excel을 유일한 사실 입력원본으로 사용합니다.
# 화면에서는 회사 사실을 다시 묻거나 덮어쓰지 않습니다.
exec(compile(open("ui/diagnosis_page.py", encoding="utf-8").read(), "ui/diagnosis_page.py", "exec"))

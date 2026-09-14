from __future__ import annotations

import streamlit as st

from engine.law_monitor import run_law_monitor
from engine.readiness import decision_readiness_gate


@st.cache_data(ttl=3600, show_spinner=False)
def _law_rows():
    return run_law_monitor()


def _render_gate_hold(gate: dict[str, object]) -> None:
    st.title("✅ 1. 판정진단")
    st.error("현재 법령·규정 DB 검증이 완료되지 않아 판정을 시작하지 않습니다.")
    st.write(str(gate.get("message") or "공식 최신본과 승인 DB의 출처 확인이 필요합니다."))
    blockers = gate.get("blockers") or []
    if blockers:
        st.markdown("**현재 확인이 필요한 항목**")
        for blocker in blockers:
            st.write(f"• {str(blocker).replace('화사계', '화학사고예방관리계획서')}")
    st.info(
        "이 상태는 회사 Excel 입력 오류가 아니라 관리자 법령자료 준비상태입니다. "
        "규정 DB 관리에서 ① 최신 법령·첨부원본(PDF·HWP/HWPX) 확인 → "
        "② 필요 시 최신본 기준선 승인 → ③ 판정용 규정 DB 추출·검토·승인 → "
        "④ 판정진단 준비상태 확인 순서로 처리하세요."
    )
    st.page_link("ui/regdb_page.py", label="규정 DB 관리에서 확인하기", icon="🗂️")


rows = _law_rows()
gate = decision_readiness_gate(rows)
if gate.get("decision") != "ALLOW":
    _render_gate_hold(gate)
    st.stop()

# 회사가 업로드한 Excel을 유일한 사실 입력원본으로 사용합니다.
# 화면에서는 회사 사실을 다시 묻거나 덮어쓰지 않습니다.
exec(compile(open("ui/diagnosis_page.py", encoding="utf-8").read(), "ui/diagnosis_page.py", "exec"))

from __future__ import annotations

import streamlit as st

from engine.law_monitor import overall_sync_gate, run_law_monitor


@st.cache_data(ttl=3600, show_spinner=False)
def _law_rows():
    return run_law_monitor()


def _render_gate_hold(gate: dict[str, str]) -> None:
    st.title("✅ 1. 판정진단")
    st.error("현재 법령·별표 최신성이 확인되지 않아 판정을 시작하지 않습니다.")
    st.write(gate.get("message", "공식 최신본 확인이 필요합니다."))
    st.caption("규정 DB 관리에서 최신 공식본 확인·재반영·승인 후 다시 판정하세요. 불확실한 상태에서는 대상/비대상을 추정하지 않습니다.")


rows = _law_rows()
gate = overall_sync_gate(rows)
if gate.get("decision") != "ALLOW":
    _render_gate_hold(gate)
    st.stop()

# 최신성 gate를 통과한 경우에만 실제 사용자 진단 화면을 실행합니다.
exec(compile(open("ui/diagnosis_page.py", encoding="utf-8").read(), "ui/diagnosis_page.py", "exec"))

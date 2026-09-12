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
        st.markdown("**관리자가 확인할 항목**")
        for blocker in blockers:
            st.write(f"• {blocker}")
    st.caption(
        "규정 DB 관리에서 최신 공식본 확인 → 후보표 재생성·검토 → 승인 → 근거 PDF 동기화를 완료한 뒤 다시 판정하세요. "
        "불확실한 상태에서는 법령상 제출·작성 필요 여부를 추정하지 않습니다."
    )


rows = _law_rows()
gate = decision_readiness_gate(rows)
if gate.get("decision") != "ALLOW":
    _render_gate_hold(gate)
    st.stop()

# 회사가 업로드한 Excel을 유일한 사실 입력원본으로 사용합니다.
# 화면에서는 회사 사실을 다시 묻거나 덮어쓰지 않습니다.
exec(compile(open("ui/diagnosis_page.py", encoding="utf-8").read(), "ui/diagnosis_page.py", "exec"))

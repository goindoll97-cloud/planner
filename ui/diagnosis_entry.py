from __future__ import annotations

import streamlit as st

from engine.law_monitor import overall_sync_gate, run_law_monitor
from engine.psm_engine import assess_psm


@st.cache_data(ttl=3600, show_spinner=False)
def _law_rows():
    return run_law_monitor()


def _render_gate_hold(gate: dict[str, str]) -> None:
    st.title("✅ 1. 판정진단")
    st.error("현재 법령·별표 최신성이 확인되지 않아 판정을 시작하지 않습니다.")
    st.write(gate.get("message", "공식 최신본 확인이 필요합니다."))
    st.caption("규정 DB 관리에서 최신 공식본 확인·재반영·승인 후 다시 판정하세요. 불확실한 상태에서는 대상/비대상을 추정하지 않습니다.")


def _render_industry_fail_safe(psm) -> None:
    if not getattr(psm, "industry_match", "") or getattr(psm, "industry_code", "") == "20202":
        return
    if psm.r_value is None or psm.r_value >= 1.0:
        return
    st.warning(
        f"PSM 대상업종 조건 확인: 입력 KSIC {psm.industry_code}는 '{psm.industry_match}'에 해당합니다. "
        f"현재 R={psm.r_value:.4f}가 1 미만이더라도 수량기준만으로 PSM 비대상으로 판단하지 않습니다. "
        "대상업종 적용조건과 법정 제외설비를 별도로 확인해야 합니다."
    )


rows = _law_rows()
gate = overall_sync_gate(rows)
if gate.get("decision") != "ALLOW":
    _render_gate_hold(gate)
    st.stop()

# 이전 rerun에서 이미 읽은 회사자료가 있으면 본 화면보다 먼저 대상업종 fail-safe를 표시합니다.
intake = st.session_state.get("intake")
if intake is not None:
    _render_industry_fail_safe(assess_psm(intake))

# 최신성 gate를 통과한 경우에만 실제 사용자 진단 화면을 실행합니다.
exec(compile(open("ui/diagnosis_page.py", encoding="utf-8").read(), "ui/diagnosis_page.py", "exec"))

# 최초 업로드 run에서도 동일 경고가 빠지지 않도록 화면 실행 뒤 한 번 더 확인합니다.
if "psm" in globals():
    _render_industry_fail_safe(globals()["psm"])

from __future__ import annotations

"""작성 시작하기: 사업장과 취급 물질만 입력하면 법정 대상 여부를 판정하고 작성을 시작한다(화학사고예방관리계획서·공정안전보고서)."""

import pandas as pd
import streamlit as st

from engine.stage2 import cap_start
from engine.stage2.storage import save_project

ACTIVE_PROJECT_KEY = "_stage2_active_project_id"


def _gate_hold() -> bool:
    """예전 판정진단과 같은 법령 최신성 확인. 보류 상태면 안내하고 True."""
    from engine.law_monitor import run_law_monitor
    from engine.readiness import decision_readiness_gate

    @st.cache_data(ttl=3600, show_spinner=False)
    def _rows():
        return run_law_monitor()

    gate = decision_readiness_gate(_rows())
    if gate.get("decision") == "ALLOW":
        return False
    st.error("법령 개정 또는 최신 규정자료 미반영이 감지되어 판정을 잠시 보류합니다.")
    st.write(str(gate.get("message") or "공식 최신본과 승인 DB의 출처 확인이 필요합니다."))
    st.page_link("ui/regdb_page.py", label="규정 DB 관리에서 최신본 업데이트", icon="🗂️")
    return True


def render(expanded: bool) -> None:
    with st.expander("새 사업장으로 시작하기", expanded=expanded):
        st.caption(
            "사업장 정보와 취급하는 유해화학물질만 적으면 법정 작성 대상(화학사고예방관리계획서, 공정안전보고서)인지 먼저 판정합니다. "
            "대상인 문서는 바로 별지 작성으로 이어집니다. "
            "물질의 최대보유량을 정확히 모르면 비워 두세요. 별지 제1호에서 시설별로 계산합니다."
        )
        left, middle, right = st.columns(3)
        name = left.text_input("사업장명", key="cap_start_name")
        address = middle.text_input("사업장 주소", key="cap_start_address")
        industry = right.text_input("업종 또는 주요 생산품", key="cap_start_industry")
        frame = pd.DataFrame(
            [{"제품명": "", "CAS No.": "", "함량(%)": 100.0, "최대 동시보유량(ton)": None}],
            columns=list(cap_start.CHEMICAL_INPUT_COLUMNS),
        )
        edited = st.data_editor(
            frame, num_rows="dynamic", width="stretch", hide_index=True, key="cap_start_chemicals",
            column_config={
                "제품명": st.column_config.TextColumn("제품명(물질명)", help="취급하는 유해화학물질 또는 제품 이름입니다. CAS 번호만 알아도 됩니다."),
                "CAS No.": st.column_config.TextColumn("CAS No.", help="화학물질 고유 번호입니다. (예시) 7782-50-5(염소)"),
                "함량(%)": st.column_config.NumberColumn("함량(%)", min_value=0.0, max_value=100.0,
                                                          help="제품 안에 그 물질이 들어 있는 비율입니다. 순수한 물질이면 100입니다."),
                "최대 동시보유량(ton)": st.column_config.NumberColumn(
                    "최대 동시보유량(ton)", min_value=0.0, help="사업장에서 그 물질을 한꺼번에 가장 많이 보유하는 양입니다. 모르면 비워 두세요."),
            },
        )
        if not st.button("법정 대상 판정하고 시작", type="primary", key="cap_start_go"):
            return
        if _gate_hold():
            return
        outcome = cap_start.start(
            {"사업장명": name, "사업장 주소": address, "업종 또는 주요 생산품": industry},
            edited.to_dict("records"),
        )
        if outcome.status == "INVALID":
            st.warning("입력을 확인해 주세요.")
            for message in outcome.messages:
                st.write(f"• {message}")
        elif outcome.status == "SYSTEM":
            st.error("회사 입력 문제가 아니라 규정 DB 준비상태를 관리자가 확인해야 합니다.")
            for message in outcome.messages:
                st.write(f"• {message}")
        elif outcome.status == "REQUEST":
            st.warning("판정에 필요한 정보가 더 있습니다.")
            for message in outcome.messages:
                st.write(f"• {message}")
        elif outcome.status == "NOT_REQUIRED":
            st.info(f"판정 결과: 화학사고예방관리계획서 — {outcome.cap_status} / 공정안전보고서 — {outcome.psm_status}")
            st.write(outcome.cap_explanation)
            st.caption("작성·제출 대상이 아니면 별지 작성을 시작하지 않습니다.")
        else:
            if outcome.project.psm_required is True:
                # 공정안전보고서 대상이면 주소로 기상 기준값(대기온도·습도)을 미리 받아 둔다. 실패해도 시작에는 영향이 없다.
                try:
                    from engine.stage2 import psm_weather

                    with st.spinner("사업장 주소로 기상 기준값을 미리 확인하는 중입니다."):
                        psm_weather.auto_fill(outcome.project)
                except Exception:
                    pass
            save_project(outcome.project)
            st.session_state[ACTIVE_PROJECT_KEY] = outcome.project.project_id
            targets = [label for label, on in (("화학사고예방관리계획서", outcome.project.cap_required is True),
                                                 ("공정안전보고서", outcome.project.psm_required is True)) if on]
            st.success(f"판정 결과: {' · '.join(targets)} 작성 대상입니다. 작성을 시작합니다.")
            st.rerun()

from __future__ import annotations

"""작성 시작하기: 사업장과 취급 물질만 입력하면 법정 대상 여부를 판정하고 작성을 시작한다(화학사고예방관리계획서·공정안전보고서)."""

import pandas as pd
import streamlit as st

from engine.stage2 import cap_judgement, cap_start
from ui import chemical_upload_panel
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
    st.info("이 상태는 회사가 입력한 내용의 오류가 아니라 관리자 법령자료 준비상태입니다. 규정 DB 관리에서 최신본 업데이트를 한 번 실행하면 다시 판정할 수 있습니다.")
    st.page_link("ui/regdb_page.py", label="규정 DB 관리에서 최신본 업데이트", icon="🗂️")
    return True


def render(expanded: bool) -> None:
    with st.expander("새 사업장으로 시작하기", expanded=expanded):
        st.caption(
            "사업장 정보와 취급하는 유해화학물질만 적으면 법정 작성 대상(화학사고예방관리계획서, 공정안전보고서)인지 먼저 판정합니다. "
            "대상인 문서는 바로 별지 작성으로 이어집니다. "
            "처음에는 물질명·CAS·함량과 하루 최대 제조·사용량·최대 저장량만 입력하면 됩니다. 수량은 kg 또는 ton 중 편한 단위를 선택하세요."
        )
        left, middle, right = st.columns(3)
        name = left.text_input("사업장명", key="cap_start_name", help="사업자등록증에 적힌 사업장(회사) 이름입니다.",
                                placeholder="(예시) 한국화학 울산공장")
        address = middle.text_input("사업장 주소", key="cap_start_address", help="사업장이 실제로 있는 도로명 주소입니다. 기상 정보와 주변 보호대상 조회에 쓰입니다.",
                                  placeholder="(예시) 울산광역시 남구 산업로 1")
        industry = right.text_input("업종 또는 주요 생산품", key="cap_start_industry",
                                  help="사업장에서 하는 일과 만드는 제품을 짧게 적습니다. 판정 계산에는 쓰이지 않고, 공정안전보고서 별지 제12호의 주요 생산품 칸에 다시 쓰입니다.",
                                  placeholder="(예시) 기초화학물질 제조 / 염화비닐 생산")
        blank = {"제품명": "", "CAS No.": "", "함량(%)": 100.0,
                 "최대 제조·사용량": None, "최대 저장량": None, "단위": "kg"}
        generation = st.session_state.get("cap_start_gen", 0)  # 엑셀로 행을 추가하면 새 표로 다시 그린다
        frame = pd.DataFrame(st.session_state.get("cap_start_seed") or [blank], columns=list(cap_start.CHEMICAL_INPUT_COLUMNS))
        edited = st.data_editor(
            frame, num_rows="dynamic", width="stretch", hide_index=True, key=f"cap_start_chemicals_{generation}",
            column_config={
                "제품명": st.column_config.TextColumn(
                    "제품명(물질명)", help="취급하는 제품 또는 물질 이름입니다. CAS 번호만 알아도 됩니다."
                ),
                "CAS No.": st.column_config.TextColumn(
                    "CAS No.", help="SDS 제3항에서 확인할 수 있는 화학물질 고유번호입니다. 예: 108-88-3"
                ),
                "함량(%)": st.column_config.NumberColumn(
                    "함량(%)", min_value=0.0, max_value=100.0,
                    help="제품 안 해당 물질의 함량입니다. 순수물질은 100입니다."
                ),
                "최대 제조·사용량": st.column_config.NumberColumn(
                    "하루 최대 제조·사용량", min_value=0.0,
                    help="하루에 가장 많이 제조·취급·사용하는 양입니다. 해당 없으면 0을 입력하세요."
                ),
                "최대 저장량": st.column_config.NumberColumn(
                    "최대 저장량", min_value=0.0,
                    help="한 시점에 가장 많이 저장하는 양입니다. 해당 없으면 0을 입력하세요."
                ),
                "단위": st.column_config.SelectboxColumn(
                    "단위", options=["kg", "ton"], required=True,
                    help="두 수량에 공통으로 적용할 단위입니다. kg 또는 ton을 고르세요."
                ),
            }        )

        def add_uploaded(rows, file_name, sha256):
            """올린 파일의 정상 행을 이 입력 표에 합친다(이미 적은 행은 그대로, 같은 물질은 건너뜀)."""
            def number(text):
                try:
                    return float(text) if str(text).strip() else None
                except ValueError:
                    return None

            current = [r for r in edited.to_dict("records") if str(r.get("제품명") or "").strip() or str(r.get("CAS No.") or "").strip()]
            have = {str(r.get("CAS No.") or "").strip() for r in current if str(r.get("CAS No.") or "").strip()}
            added = []
            for row in rows:
                if row["CAS No."] and row["CAS No."] in have:
                    continue
                added.append({
                    "제품명": row["제품명"], "CAS No.": row["CAS No."], "함량(%)": number(row["함량(%)"]),
                    "최대 제조·사용량": number(row.get("최대 제조·사용량", "")),
                    "최대 저장량": number(row.get("최대 저장량", "")),
                    "단위": row.get("단위") or "ton",
                })
            st.session_state["cap_start_seed"] = [*current, *added]
            st.session_state["cap_start_gen"] = generation + 1
            return f"{file_name}에서 물질 {len(added)}건을 아래 표에 추가했습니다. 확인한 뒤 '법정 대상 판정하고 시작'을 누르세요."

        chemical_upload_panel.render("cap_start_upload", existing=(
            {str(r.get("CAS No.") or "").strip() for r in edited.to_dict("records")} - {""}, set()), add_rows=add_uploaded)
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
                st.write(f"• {cap_judgement.display_request(message)}")
        elif outcome.status == "SYSTEM":
            st.error("회사 입력 문제가 아니라 규정 DB 준비상태를 관리자가 확인해야 합니다.")
            for message in outcome.messages:
                st.write(f"• {cap_judgement.display_request(message)}")
        elif outcome.status == "PENDING":
            save_project(outcome.project)
            st.session_state[ACTIVE_PROJECT_KEY] = outcome.project.project_id
            st.session_state["cap_start_notice"] = " ".join(cap_judgement.display_request(m) for m in outcome.messages[:1]) + " (사업장을 만들었습니다. 판정은 위 '법정 대상 판정'에서 이어서 합니다.)"
            st.rerun()
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

from __future__ import annotations

"""작성 시작하기: 사업장과 취급 물질만 입력하면 법정 대상 여부를 판정하고 작성을 시작한다(화학사고예방관리계획서·공정안전보고서)."""

import pandas as pd
import streamlit as st

from engine.stage2 import cap_judgement, cap_start
from ui import chemical_upload_panel
from engine.stage2.storage import save_project

ACTIVE_PROJECT_KEY = "_stage2_active_project_id"


def clear_start_draft_state() -> None:
    """새 사업장 입력 중인 임시값을 모두 비운다.

    프로젝트에 저장된 값과 별개로 Streamlit 위젯/업로드 미리보기가 세션에 남을 수 있으므로,
    새 사업장을 만든 뒤나 프로젝트를 삭제한 뒤에는 반드시 초기화한다.
    """
    for key in list(st.session_state.keys()):
        if str(key).startswith("cap_start_"):
            st.session_state.pop(key, None)



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
            "처음에는 제품별 기본정보만 적습니다. 혼합제품이 있으면 사업장을 만든 뒤 SDS 제3항용 두 번째 파일이 자동으로 나타납니다. "
            "성상·SDS 분류·법적 예외 같은 어려운 항목은 판정에 실제로 필요할 때만 질문합니다."
        )
        left, middle, right = st.columns(3)
        name = left.text_input("사업장명", key="cap_start_name", help="사업자등록증에 적힌 사업장(회사) 이름입니다.",
                                placeholder="(예시) 한국화학 울산공장")
        address = middle.text_input("사업장 주소", key="cap_start_address", help="사업장이 실제로 있는 도로명 주소입니다. 기상 정보와 주변 보호대상 조회에 쓰입니다.",
                                  placeholder="(예시) 울산광역시 남구 산업로 1")
        industry = right.text_input("업종 또는 주요 생산품", key="cap_start_industry",
                                  help="사업장에서 하는 일과 만드는 제품을 짧게 적습니다. 예: 합성수지 제조 / 접착제 생산.",
                                  placeholder="(예시) 기초화학물질 제조 / 염화비닐 생산")
        ksic = st.text_input(
            "업종 분류 코드(KSIC, 알면 입력)",
            key="cap_start_ksic",
            placeholder="예: 20111",
            help=(
                "KSIC는 '한국표준산업분류'의 약자로, 사업장의 주된 일을 숫자로 구분한 코드입니다. "
                "공정안전보고서(PSM)는 일부 업종 자체가 대상 기준이 될 수 있어 필요합니다. "
                "회사에서 쓰는 5자리 업종 코드를 알고 있으면 적고, 모르면 비워 두세요. 판정에 꼭 필요할 때 다시 안내합니다."
            ),
        )
        hidden_columns = [
            cap_start.LEGACY_CONTENT_COLUMN, cap_start.LEGACY_MIXTURE_COLUMN,
            cap_start.LEGACY_MAX_HOLDING_COLUMN, *cap_start.EXTRA_INPUT_COLUMNS,
        ]
        blank = {"제품명": "", cap_start.MATERIAL_TYPE_COLUMN: "", "CAS No.": "", "최대 제조·사용량": None,
                 "최대 저장량": None, "단위": "kg", **{col: "" for col in hidden_columns}}
        generation = st.session_state.get("cap_start_gen", 0)  # 엑셀로 행을 추가하면 새 표로 다시 그린다
        frame = pd.DataFrame(
            st.session_state.get("cap_start_seed") or [blank],
            columns=[*cap_start.CHEMICAL_INPUT_COLUMNS, *hidden_columns],
        )
        edited = st.data_editor(
            frame, num_rows="dynamic", width="stretch", hide_index=True, key=f"cap_start_chemicals_{generation}",
            column_config={
                "제품명": st.column_config.TextColumn(
                    "제품명(물질명)", help="취급하는 제품 또는 물질 이름입니다. CAS 번호만 알아도 됩니다."
                ),
                cap_start.MATERIAL_TYPE_COLUMN: st.column_config.SelectboxColumn(
                    "단일물질/혼합물", options=["", "단일물질", "혼합물"],
                    help="제품 SDS 제3항을 보세요. 구성성분이 하나인 물질은 단일물질, 여러 성분으로 된 제품은 혼합물입니다.",
                ),
                "CAS No.": st.column_config.TextColumn(
                    "CAS No.",
                    help="단일물질이면 반드시 적습니다. 혼합제품 자체의 CAS는 비워 두세요. 구성성분 CAS는 두 번째 파일에서 입력합니다.",
                ),
                "최대 제조·사용량": st.column_config.NumberColumn(
                    "하루 최대 제조·사용량", min_value=0.0,
                    help="하루에 가장 많이 제조·취급·사용하는 양입니다. 모르면 비워 두고, 하지 않으면 0을 입력하세요."
                ),
                "최대 저장량": st.column_config.NumberColumn(
                    "최대 저장량", min_value=0.0,
                    help="한 시점에 가장 많이 저장하는 양입니다. 모르면 비워 두고, 저장하지 않으면 0을 입력하세요. (빈 칸은 '아직 모름', 0은 '없음'으로 다르게 처리합니다)"
                ),
                "단위": st.column_config.SelectboxColumn(
                    "단위", options=["kg", "ton"], required=True,
                    help="두 수량에 공통으로 적용할 단위입니다. kg 또는 ton을 고르세요."
                ),
                # 기존 파일에 이미 있던 함량·혼합물·전문값은 보존하되 초기 화면에서는 숨긴다.
                cap_start.LEGACY_CONTENT_COLUMN: None,
                cap_start.LEGACY_MIXTURE_COLUMN: None,
                cap_start.LEGACY_MAX_HOLDING_COLUMN: None,
                **{col: None for col in cap_start.EXTRA_INPUT_COLUMNS},
            },
        )

        def add_uploaded(rows, file_name, sha256):
            """올린 파일의 정상 행을 이 입력 표에 합친다(이미 적은 행은 그대로, 같은 물질은 건너뜀)."""
            def number(text):
                try:
                    return float(text) if str(text).strip() else None
                except ValueError:
                    return None

            parts = list(st.session_state.get("cap_start_components") or [])
            current = [r for r in edited.to_dict("records") if str(r.get("제품명") or "").strip() or str(r.get("CAS No.") or "").strip()]
            have = {str(r.get("CAS No.") or "").strip() for r in current if str(r.get("CAS No.") or "").strip()}
            added = []
            for row in rows:
                if row["CAS No."] and row["CAS No."] in have:
                    continue
                for component in row.get("_components") or []:
                    parts.append({"제품명": row["제품명"], "CAS No.": component["CAS No."], "함량(%)": component["함량(%)"]})
                kind = "혼합물" if str(row.get("혼합물 여부") or "").strip().upper() == "Y" else "단일물질" if str(row.get("혼합물 여부") or "").strip().upper() == "N" else ""
                added.append({
                    "제품명": row["제품명"], cap_start.MATERIAL_TYPE_COLUMN: kind, "CAS No.": row["CAS No."],
                    "최대 제조·사용량": number(row.get("최대 제조·사용량", "")),
                    "최대 저장량": number(row.get("최대 저장량", "")),
                    "단위": row.get("단위") or "ton",
                    cap_start.LEGACY_CONTENT_COLUMN: number(row.get(cap_start.LEGACY_CONTENT_COLUMN, "")),
                    cap_start.LEGACY_MIXTURE_COLUMN: row.get(cap_start.LEGACY_MIXTURE_COLUMN, ""),
                    cap_start.LEGACY_MAX_HOLDING_COLUMN: number(row.get(cap_start.LEGACY_MAX_HOLDING_COLUMN, "")),
                    **{col: row.get(col, "") for col in cap_start.EXTRA_INPUT_COLUMNS},
                })
            st.session_state["cap_start_components"] = parts
            st.session_state["cap_start_seed"] = [*current, *added]
            st.session_state["cap_start_gen"] = generation + 1
            return f"{file_name}에서 물질 {len(added)}건을 아래 표에 추가했습니다. 확인한 뒤 '법정 대상 판정하고 시작'을 누르세요."

        chemical_upload_panel.render("cap_start_upload", existing=(
            {str(r.get("CAS No.") or "").strip() for r in edited.to_dict("records")} - {""}, set()), add_rows=add_uploaded)
        if not st.button("법정 대상 판정하고 시작", type="primary", key="cap_start_go"):
            return
        with st.spinner("법정 대상 여부를 판정하는 중입니다. 물질·시설이 많으면 시간이 걸릴 수 있습니다."):
            if _gate_hold():
                return
            outcome = cap_start.start(
                {"사업장명": name, "사업장 주소": address, "업종 또는 주요 생산품": industry,
                 "한국표준산업분류(KSIC) 코드": ksic},
                edited.to_dict("records"),
                components=st.session_state.get("cap_start_components"),
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
            clear_start_draft_state()
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
            clear_start_draft_state()
            st.session_state[ACTIVE_PROJECT_KEY] = outcome.project.project_id
            targets = [label for label, on in (("화학사고예방관리계획서", outcome.project.cap_required is True),
                                                 ("공정안전보고서", outcome.project.psm_required is True)) if on]
            st.success(f"판정 결과: {' · '.join(targets)} 작성 대상입니다. 작성을 시작합니다.")
            st.rerun()

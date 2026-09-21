from __future__ import annotations

"""법정 대상 판정 화면 조각: 판정 전 사업장의 판정, 이미 판정한 사업장의 다시 판정, 판정에 필요한 질문."""

import pandas as pd
import streamlit as st

from engine.stage2 import cap_judgement as judgement
from engine.stage2 import storage

CAP = "화학사고예방관리계획서"
PSM = "공정안전보고서"


def _stored(project) -> dict:
    decision = project.stage1_snapshot.get("decision") or {}
    return decision if isinstance(decision, dict) else {}


def _status_line(project) -> str:
    if judgement.undecided(project):
        return "아직 판정하지 않았습니다."
    decision = _stored(project)
    return f"{CAP}: {decision.get('cap_status') or '확인 안 됨'} / {PSM}: {decision.get('psm_status') or '확인 안 됨'}"


def _ask(project, outcome) -> None:
    st.markdown("#### 판정에 필요한 확인 사항")
    st.caption("판정 규칙이 사업장에 대해 답을 요청한 항목만 물어봅니다. 모르면 '모름'을 고르세요. 그러면 판정이 보류되고 무엇을 확인해야 하는지 안내됩니다.")
    existing = judgement.answers(project)
    given: dict[str, str] = {}
    for question in outcome.questions:
        key = f"judge_q_{project.project_id}_{question.item}"
        st.markdown(f"**{question.text}**  \n<small>{question.system}</small>", unsafe_allow_html=True)
        if question.options:
            options = ["선택하세요", *question.options]
            current = existing.get(question.item, "")
            picked = st.radio(question.text, options, index=options.index(current) if current in options else 0,
                              horizontal=True, key=key, help=question.help, label_visibility="collapsed")
            given[question.item] = "" if picked == "선택하세요" else picked
        else:
            given[question.item] = st.text_input(question.text, value=existing.get(question.item, ""), key=key,
                                                 help=question.help, label_visibility="collapsed")
        st.caption(question.help)
    table_messages = [m for m in outcome.messages if _for_table(m)]
    unmatched = [m for m in outcome.messages
                 if m not in table_messages and not any(q.trigger and q.trigger in m for q in outcome.questions)]
    if unmatched:
        st.markdown("**그 밖에 확인해야 할 것**")
        for message in unmatched:
            st.write(f"• {judgement.display_request(message)}")
    edited = _chemical_table(project, outcome, table_messages)
    if st.button("답을 저장하고 다시 판정", type="primary", key=f"judge_answer_{project.project_id}"):
        table_changed = edited is not None and _filled(edited) != _filled(judgement.chemical_inputs(project))
        if not any(given.values()) and not table_changed:
            st.warning("한 가지 이상 답해 주세요.")
        else:
            if given:
                judgement.save_answers(project, given)
            if table_changed:
                judgement.save_chemical_inputs(project, edited)
            storage.save_project(project)
            st.session_state[f"judge_out_{project.project_id}"] = judgement.judge(project)
            st.rerun()


def _filled(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in row.items() if v} for row in rows]


def _for_table(message: str) -> bool:
    text = judgement.display_request(message)
    return any(marker in text for marker in judgement.CHEM_REQUEST_MARKERS)


YES_NO_UNKNOWN = ["", "Y", "N", "모름"]


def _chemical_table(project, outcome, table_messages):
    """물질별로 판정 엔진이 요구한 값을 입력받는 표. 입력한 전체 행 목록(저장 형식)을 돌려주고, 표가 필요 없으면 None."""
    if not table_messages:
        return None
    from engine.stage2 import cap_chemical_workspace as chem

    _, rows = chem._rows(project)
    if not rows:
        return None
    st.markdown("**물질별로 확인할 값**")
    st.caption("아래 표에서 비어 있는 칸을 채워 주세요. 모르는 칸은 비워 두면 됩니다. 판정 규칙이 요청한 물질만 보여 줍니다.")
    for message in table_messages:
        st.write(f"• {judgement.display_request(message)}")
    wanted = judgement.request_rows(table_messages, len(rows))
    stored = judgement.chemical_inputs(project)
    stored = stored + [{}] * (len(rows) - len(stored))
    records = []
    for number in wanted:
        row, extra = rows[number - 1], stored[number - 1]
        records.append({
            "행": number,
            "제품명": str(row.get("제품명") or row.get("물질명") or ""),
            "CAS No.": str(row.get("CAS No.") or row.get("CAS 번호") or ""),
            **{column: extra.get(column, "") for column in judgement.CHEM_INPUT_COLUMNS},
        })
    frame = pd.DataFrame(records)
    text = lambda label, help_text=None: st.column_config.TextColumn(label, help=help_text)
    config = {
        "행": st.column_config.NumberColumn("행", disabled=True, width="small"),
        "제품명": st.column_config.TextColumn("제품명", disabled=True),
        "CAS No.": st.column_config.TextColumn("CAS No.", disabled=True),
        "함량(%)": text("함량(%)", "제품 중 이 물질의 함량입니다."),
        "상온·상압 액체 여부(해당 시)": st.column_config.SelectboxColumn("상온·상압 액체 여부", options=YES_NO_UNKNOWN),
        "최대 제조·사용량": text("최대 제조·사용량", "하루 최대 제조·사용량(수량 단위는 ton 기준으로 적으세요)."),
        "최대 저장량": text("최대 저장량", "한꺼번에 저장하는 최대량(ton)."),
        "최대 동시보유량(알면 입력)": text("최대 동시보유량(ton)", "법정 산정 방식으로 계산한 사업장 최대보유량을 알 때만 적으세요."),
        "최대보유량 법정 산정 여부": st.column_config.SelectboxColumn(
            "법정 산정 여부", help="위 최대 동시보유량이 법정 방식으로 산정한 값이면 Y, 단순 재고량이나 추정이면 N입니다.",
            options=YES_NO_UNKNOWN),
        "SDS 제2항 유해성·위험성 분류(선택 입력)": text(
            "SDS 제2항 분류", "제품 SDS 제2항의 유해성·위험성 분류를 그대로 적습니다. 해당 분류가 없으면 '별표1 해당없음'."),
    }
    editor = st.data_editor(frame, column_config=config, hide_index=True, width="stretch", num_rows="fixed",
                            key=f"judge_chem_{project.project_id}")
    result = [dict(row) for row in stored[:len(rows)]]
    for position, number in enumerate(wanted):
        values = editor.iloc[position]
        result[number - 1] = {column: ("" if pd.isna(values[column]) else str(values[column]).strip())
                              for column in judgement.CHEM_INPUT_COLUMNS}
    return result


def _decided(project, outcome) -> None:
    st.success("판정이 끝났습니다.")
    st.write(f"**{CAP}:** {outcome.cap_status or '확인 안 됨'}")
    if getattr(outcome.decision, "cap_explanation", ""):
        st.caption(str(outcome.decision.cap_explanation))
    st.write(f"**{PSM}:** {outcome.psm_status or '확인 안 됨'}")
    if getattr(outcome.decision, "psm_explanation", ""):
        st.caption(str(outcome.decision.psm_explanation))
    if outcome.status == "NOT_REQUIRED":
        st.info("두 문서 모두 작성·제출 대상이 아닙니다. 대상이 아니면 별지 작성을 시작하지 않습니다.")
        if st.button("이 판정 결과 저장", key=f"judge_confirm_{project.project_id}"):
            judgement.apply(project, outcome)
            storage.save_project(project)
            st.session_state.pop(f"judge_out_{project.project_id}", None)
            st.rerun()
        return
    st.markdown("**이번에 작성할 문서**")
    st.caption("법적으로 대상인 문서만 고를 수 있습니다. 하나만 작성해도 다른 문서의 대상 여부는 그대로 남습니다.")
    write_cap = st.checkbox(CAP, value=outcome.cap_target, disabled=not outcome.cap_target, key=f"judge_cap_{project.project_id}")
    write_psm = st.checkbox(PSM, value=outcome.psm_target, disabled=not outcome.psm_target, key=f"judge_psm_{project.project_id}")
    if st.button("이 범위로 작성 시작", type="primary", key=f"judge_apply_{project.project_id}"):
        try:
            judgement.apply(project, outcome, write_psm=write_psm, write_cap=write_cap)
        except ValueError as exc:
            st.error(str(exc))
            return
        storage.save_project(project)
        st.session_state.pop(f"judge_out_{project.project_id}", None)
        st.rerun()


def render(project) -> None:
    from ui.cap_start_panel import _gate_hold

    pending = judgement.undecided(project)
    label = "법정 대상 판정" + (" — 판정 전" if pending else "")
    with st.expander(label, expanded=pending):
        st.write("현재 판정: " + _status_line(project))
        if pending:
            st.caption("시설을 입력하면 최대보유량이 계산됩니다. 그 뒤 아래 버튼으로 법정 대상인지 판정하고 작성할 문서를 정합니다. "
                       "별지 작성은 판정 전에도 미리 할 수 있습니다.")
        else:
            st.caption("물질이나 시설을 바꿨다면 다시 판정해서 결과가 달라지는지 확인하세요.")
        key = f"judge_out_{project.project_id}"
        if st.button("법정 대상 판정하기" if pending else "다시 판정하기", key=f"judge_run_{project.project_id}"):
            if _gate_hold():
                return
            st.session_state[key] = judgement.judge(project)
        outcome = st.session_state.get(key)
        if outcome is None:
            return
        if outcome.status == "INVALID":
            st.warning("입력을 확인해 주세요.")
            for message in outcome.messages:
                st.write(f"• {judgement.display_request(message)}")
        elif outcome.status == "PENDING":
            st.warning("최대보유량을 알 수 없는 물질이 있어 판정할 수 없습니다.")
            for name in outcome.missing_quantity:
                st.write(f"• {name}")
            st.caption("별지 제1호에서 시설(용량·비중 등)을 입력하면 물질별 최대보유량이 계산됩니다. 알고 있는 값이 있으면 물질 표에 직접 적어도 됩니다.")
        elif outcome.status == "SYSTEM":
            st.error("회사 입력 문제가 아니라 규정 DB 준비상태를 관리자가 확인해야 합니다.")
            for message in outcome.messages:
                st.write(f"• {judgement.display_request(message)}")
        elif outcome.status == "REQUEST":
            _ask(project, outcome)
        else:
            _decided(project, outcome)

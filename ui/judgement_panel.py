from __future__ import annotations

"""법정 대상 판정 화면 조각: 판정 전 사업장의 판정, 이미 판정한 사업장의 다시 판정, 판정에 필요한 질문."""

import re

import pandas as pd
import streamlit as st

from engine.stage2 import cap_judgement as judgement
from engine.stage2 import kosha_candidates
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


STEPS = ("판정정보 확인", "최대보유량 확인", "최종판정")


def _is_psm_quantity_question(question) -> bool:
    """PSM 물질군 수량 질문은 1단계가 아니라 2단계에서 받는다.

    질문의 생성·판정·저장 형식은 엔진에 맡기고, 사용자 화면에서만 단계 위치를
    바꾼다. 따라서 규정수량이나 PSM 판정식은 이 함수의 영향을 받지 않는다.
    """
    item = str(getattr(question, "item", "") or "")
    return (
        getattr(question, "system", "") == PSM
        and item.startswith("별표 13 제")
        and ("하루 최대 제조·취급량(kg)" in item or "최대 저장량(kg)" in item)
    )


def _stage2_questions(outcome) -> list:
    return [question for question in getattr(outcome, "questions", ()) if _is_psm_quantity_question(question)]


def _after_save_flash(outcome) -> str:
    """저장 직후 실제 다음 상태에 맞는 안내문을 만든다."""
    status = getattr(outcome, "status", "")
    if status in {"DECIDED", "NOT_REQUIRED"}:
        return "판정 조건이 확정되었습니다. 최종 판정 결과를 확인해 주세요."
    if status == "REQUEST":
        if _stage2_questions(outcome):
            return "일부 PSM 수량이 아직 확인되지 않았습니다. 필요한 수량을 입력해 주세요."
        if any(
            judgement.HOLDING_FACILITY_MARKER in message
            for message in getattr(outcome, "messages", ())
        ):
            return "PSM 수량을 저장했습니다. 아래 시설 입력에서 최대보유량 정보를 확인해 주세요."
        return "입력이 저장되었습니다. 추가 확인사항을 아래에서 확인해 주세요."
    if status == "PENDING" or any(
        judgement.HOLDING_FACILITY_MARKER in message
        for message in getattr(outcome, "messages", ())
    ):
        return "입력이 저장되었습니다. 다음 최대보유량 정보를 확인해 주세요."
    return "입력이 저장되었습니다. 아래 안내를 확인해 주세요."

HELP_FLOW = ("판정은 판정정보 확인 → 최대보유량 확인 → 최종판정 순서로 진행합니다. 내부적으로 필요한 물질 성분과 판정 조건을 먼저 확인하고, "
             "더 필요한 정보가 있으면 그것만 물어봅니다. 별지 작성은 판정 전에도 미리 시작할 수 있습니다.")
WHY_ASK = ("**왜 묻나요?** 입력하신 물질 목록만으로는 법정 대상인지 확정할 수 없어서, 판정 규칙이 사업장에 대해 추가로 확인을 요청한 항목입니다. "
           "사업장 전체에 대한 질문이라 물질과 상관없이 한 번만 답하면 됩니다.\n\n"
           "**모르면?** 답에 따라 작성할 문서가 달라질 수 있으니 확실하지 않으면 추측하지 말고 '모름'을 고르세요. 판정이 보류되고 확인할 것이 안내됩니다.")
WHY_ROWS = ("**왜 이 물질들만 나오나요?** 물질의 양이 규정수량 기준에 가까워서 정확한 값이 있어야 판정할 수 있는 물질만 보여 드립니다. "
            "나머지 물질은 이미 입력한 값만으로 판정할 수 있어 묻지 않습니다.\n\n"
            "**어떻게 채우나요?** '필요한 값' 칸에 적힌 내용을 같은 줄에서 채우세요. 모르는 칸은 비워 두면 되고, "
            "빈 칸은 '아직 모름', 0은 '없음'으로 다르게 처리합니다. 수량은 칸마다 kg 또는 ton을 고를 수 있고 저장할 때 ton으로 바꿔 줍니다.")
HOLDING_HELP = ("**사업장 최대보유량이란?** 같은 물질이 사업장 안의 여러 시설(저장탱크·반응기·보관창고 등)에 동시에 있을 수 있는 양을 "
                "법에서 정한 방식으로 계산해 합한 값입니다. 규정수량과 비교해 작성 대상인지 정하는 기준입니다.\n\n"
                "**어떻게 채우나요?** '시설 입력'에 시설의 설계용량·비중을 적으면 프로그램이 계산합니다. "
                "이미 법에서 정한 방식으로 계산한 값이 있으면 표에 직접 적어도 됩니다.")
FACILITY_HELP = (
    "**판정 단계에서는 무엇만 입력하나요?** 최대보유량 계산에 필요한 시설 유형·물질 상태와, "
    "그 선택에 따라 필요한 설계용량·비중·운전조건 등만 묻습니다. 단위공장명, 설비번호, 정식 시설명처럼 "
    "보고서 작성용 식별정보는 지금 묻지 않습니다.\n\n"
    "**나중에는?** 여기서 입력한 계산값은 보고서 작성 화면에 그대로 이어지며, 그때 단위공장명·설비번호·정식 시설명 같은 식별정보만 보완합니다.\n\n"
    + HOLDING_HELP
)
KOSHA_HELP = ("**왜 하나요?** 판정 규칙이 일부 물질의 MSDS 제2항 분류(인화성·독성 등)를 요청합니다. 제품 MSDS를 일일이 찾는 대신 "
              "CAS 번호로 KOSHA(한국산업안전보건공단)에서 후보를 불러옵니다.\n\n"
              "**주의** 조회 결과는 참고자료입니다. 판정 규칙이 요청한 물질의 표에 후보로 미리 채워지며, 제품 MSDS와 대조해 확인해야 판정에 쓰입니다. "
              "CAS 번호만 전송하고 회사·수량 정보는 보내지 않습니다.")


def current_step(outcome) -> int:
    """지금 화면이 어느 단계인지(1~3). 내부 판정 상태를 사용자용 3단계로 묶어 표시합니다."""
    status = getattr(outcome, "status", "")
    if status == "COMPOSITION":
        return 1
    if status == "REQUEST":
        questions = tuple(getattr(outcome, "questions", ()) or ())
        if questions and all(_is_psm_quantity_question(question) for question in questions):
            return 2
        return 1 if questions else 2
    if status == "PENDING":
        return 2
    return 3


def step_line(step: int) -> str:
    return " → ".join(f"**{i}. {name}**" if i == step else f"{i}. {name}" for i, name in enumerate(STEPS, start=1))


def unit_help() -> str:
    return "칸마다 kg 또는 ton을 고를 수 있습니다. 저장할 때 자동으로 ton으로 바꿔 줍니다."


COMPOSITION_OPTIONS = ["선택하세요", "단일물질", "혼합물"]


def _composition_form(project, outcome) -> None:
    """성분 확인은 한 경로에서만 받는다.

    기본 물질목록에서 이미 '혼합물'로 확인된 제품은 두 번째 구성성분 파일을 기본 경로로 쓴다.
    사용자가 명시적으로 원할 때만 같은 자리에서 직접 입력 표를 연다.
    """
    from engine.stage2 import cap_chemical_workspace as chem
    from ui import mixture_component_upload_panel

    _, rows = chem._rows(project)
    targets = list(outcome.composition_rows or judgement.composition_rows(project))
    if not rows or not targets:
        st.info("확인할 물질 성분 정보가 없습니다.")
        return

    known_mixtures = [
        number for number in targets
        if 1 <= number <= len(rows) and judgement._mixture_yes(rows[number - 1].get("혼합물 여부"))
    ]

    st.markdown(
        "#### 물질 성분 확인",
        help=(
            "**단일물질**은 CAS No. 하나로 확인합니다.\n\n"
            "**혼합제품**은 제품명으로 추정하지 않고, 제품 MSDS 제3항의 구성성분 CAS No.와 함량(%)으로 판정합니다.\n\n"
            "혼합제품은 아래 '혼합물 구성성분' 두 번째 파일에 한 번만 입력합니다. "
            "파일 사용이 어려운 경우에만 '직접 입력'을 선택하세요."
        ),
    )

    manual_mixtures = False
    if known_mixtures:
        # 혼합물 성분 입력의 기본·유일한 위치. 물질목록 영역에서는 같은 업로더를 다시 보여 주지 않는다.
        mixture_component_upload_panel.render(
            project,
            f"judge_mix_step_{project.project_id}",
            continue_judgement=True,
        )
        manual_mixtures = st.checkbox(
            "파일 대신 이 화면에서 혼합물 성분 직접 입력",
            key=f"judge_comp_manual_mix_{project.project_id}",
            help="두 번째 엑셀 파일을 사용하기 어려운 경우에만 선택하세요. 같은 내용을 파일과 여기 두 곳에 모두 입력할 필요는 없습니다.",
        )
        if not manual_mixtures:
            other_targets = [number for number in targets if number not in known_mixtures]
            if other_targets:
                st.caption("혼합물 구성성분을 먼저 저장하면 남아 있는 성분 확인 항목이 이어서 나타납니다.")
            return

    stored_components = judgement.mixture_components(project)
    classifications: list[dict] = []
    components: list[dict] = []
    any_mixture = False
    pid = project.project_id

    for number in targets:
        if number <= 0 or number > len(rows):
            continue
        row = rows[number - 1]
        product = str(row.get("제품명") or row.get("물질명") or f"{number}행").strip()
        current_cas = str(row.get("CAS No.") or row.get("CAS 번호") or "").strip()
        st.markdown(f"**{product}**")

        if judgement._mixture_yes(row.get("혼합물 여부")):
            choice = "혼합물"
            st.caption("기본 물질목록에서 '혼합물'로 확인한 제품입니다.")
        elif judgement._mixture_no(row.get("혼합물 여부")):
            choice = "단일물질"
            st.caption("기본 물질목록에서 '단일물질'로 확인한 제품입니다.")
        else:
            choice = st.radio(
                f"{product}의 구분",
                COMPOSITION_OPTIONS,
                horizontal=True,
                key=f"judge_comp_kind_{pid}_{number}",
                help="제품 MSDS 제3항을 확인해 단일물질인지 혼합물인지 선택하세요.",
                label_visibility="collapsed",
            )

        if choice == "단일물질":
            cas = st.text_input(
                f"{product} CAS No.",
                value=current_cas,
                key=f"judge_comp_cas_{pid}_{number}",
                placeholder="예: 108-88-3",
                help="단일물질은 CAS No.가 필수입니다. 물질명만으로 법적 물질을 추정하지 않습니다.",
            )
            classifications.append({"행": number, "구분": choice, "CAS No.": cas})
        elif choice == "혼합물":
            any_mixture = True
            classifications.append({"행": number, "구분": choice, "CAS No.": ""})
            existing = [
                {"CAS No.": str(comp.get("CAS No.") or ""), "함량(%)": comp.get("함량(%)")}
                for comp in stored_components
                if str(comp.get("제품목록행번호") or "").strip() == str(number)
            ]
            seed = existing or [{"CAS No.": "", "함량(%)": None}]
            editor = st.data_editor(
                pd.DataFrame(seed, columns=["CAS No.", "함량(%)"]),
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                key=f"judge_comp_parts_{pid}_{number}",
                column_config={
                    "CAS No.": st.column_config.TextColumn(
                        "구성성분 CAS No.",
                        help="제품 MSDS 제3항에 적힌 구성성분 CAS No.를 그대로 입력합니다. 모든 성분 행에 필수입니다.",
                    ),
                    "함량(%)": st.column_config.NumberColumn(
                        "함량(%)", min_value=0.0, max_value=100.0,
                        help="제품 MSDS 제3항에 적힌 해당 구성성분 함량을 입력합니다.",
                    ),
                },
            )
            for item in editor.to_dict("records"):
                cas = "" if pd.isna(item.get("CAS No.")) else str(item.get("CAS No.") or "").strip()
                pct = "" if pd.isna(item.get("함량(%)")) else str(item.get("함량(%)") or "").strip()
                if not cas and not pct:
                    continue
                components.append({
                    "제품목록행번호": number,
                    "CAS No.": cas,
                    "함량(%)": pct,
                    "성분명(선택)": "",
                })
        st.divider()

    confirmed = True
    if any_mixture:
        confirmed = st.checkbox(
            "혼합물 구성성분의 CAS No.와 함량(%)을 제품 MSDS 제3항과 대조해 확인했습니다.",
            key=f"judge_comp_sds_ok_{pid}",
        )

    if st.button(
        "판정정보 확인하기",
        type="primary",
        key=f"judge_comp_save_{pid}",
        disabled=any_mixture and not confirmed,
    ):
        try:
            judgement.save_composition(project, classifications, components, sds_confirmed=confirmed)
        except ValueError as exc:
            st.warning(str(exc))
            return
        storage.save_project(project)
        st.session_state[f"judge_out_{pid}"] = judgement.judge(project)
        st.rerun()


PLACEHOLDER = "선택하세요"
SYSTEM_ORDER = ("화학사고예방관리계획서", "공정안전보고서", "공통")


def _question(project, question, existing: dict) -> str:
    """질문 하나를 그리고 답을 돌려준다. 설명은 ? 안에 넣어 화면에는 질문 한 줄만 보이게 한다."""
    key = f"judge_q_{project.project_id}_{question.item}"
    current = existing.get(question.item, "")
    if question.choices:
        options = [PLACEHOLDER, *question.choices]
        picked = st.selectbox(question.text, options, index=options.index(current) if current in options else 0,
                              key=key, help=question.help)
        return "" if picked == PLACEHOLDER else picked
    if question.options:
        options = [PLACEHOLDER, *question.options]
        picked = st.radio(question.text, options, index=options.index(current) if current in options else 0,
                          horizontal=True, key=key, help=question.help, format_func=lambda v: ANSWER_LABELS.get(v, v))
        return "" if picked == PLACEHOLDER else picked
    if question.item.endswith("(kg)"):
        value_col, unit_col = st.columns([3, 1])
        typed = value_col.text_input(question.text, value=current, key=key, help=question.help, placeholder="숫자만")
        unit = unit_col.selectbox("단위", ["kg", "ton"], key=key + "_unit")
        return judgement.convert_quantity(typed, unit, "kg")  # 판정에는 kg로 저장한다
    return st.text_input(question.text, value=current, key=key, help=question.help,
                         placeholder="숫자만" if question.numeric else "")


def _note8_table(project):
    """'가스 전문 저장·판매시설'이라고 답했을 때, 규정량 계산에서 뺄 가스의 양을 받는 표. 바뀐 표(저장 형식)를 돌려준다."""
    st.markdown("**규정량 계산에서 뺄 가스의 양**")
    st.caption("별표 13 호수(예: 1은 인화성 가스)별로 뺄 하루 최대 제조·취급량과 최대 저장량을 kg으로 적으세요. 행은 아래 +로 추가합니다.")
    frame = pd.DataFrame(judgement.note8_rows(project) or [{c: "" for c in judgement.NOTE8_COLUMNS}], columns=list(judgement.NOTE8_COLUMNS))
    edited = st.data_editor(frame, num_rows="dynamic", hide_index=True, width="stretch", key=f"judge_note8_{project.project_id}",
                            column_config={
                                "별표13 호수": st.column_config.TextColumn("별표 13 호수", help="빼려는 가스가 별표 13의 몇 호인지입니다. 인화성 가스는 1입니다."),
                                "제조·취급 제외량(kg)": st.column_config.TextColumn("하루 제조·취급 제외량(kg)"),
                                "저장 제외량(kg)": st.column_config.TextColumn("저장 제외량(kg)"),
                            })
    return [{k: ("" if pd.isna(v) else str(v).strip()) for k, v in row.items()} for row in edited.to_dict("records")]


def _ask(project, outcome) -> bool:
    """판정 질문 단계.

    판정 조건과 최대보유량 입력을 한 화면에 섞지 않는다.
    먼저 판정 조건을 모두 확정한 뒤 재판정하고, 그 다음에 시설 최대보유량 단계로 넘어간다.
    """
    st.markdown("#### 판정에 필요한 확인 사항", help=WHY_ASK)
    existing = judgement.answers(project)
    given: dict[str, str] = {}

    # 1) 엔진이 현재 요청한 기본 질문을 표시한다.
    # PSM 물질군의 제조·취급량·저장량은 판정조건이 아니라 2단계에서 받는다.
    base_questions = [question for question in outcome.questions if not _is_psm_quantity_question(question)]
    groups = {name: [q for q in base_questions if q.system == name] for name in SYSTEM_ORDER}
    for name, questions in groups.items():
        if not questions:
            continue
        if len([g for g in groups.values() if g]) > 1:
            st.markdown(f"**{name}**")
        for question in questions:
            given[question.item] = _question(project, question, {**existing, **given})

    # 2) 현재 화면에서 '예'를 고르면 필요한 후속 질문을 즉시 같은 화면에 펼친다.
    merged_answers = {**existing, **{k: v for k, v in given.items() if v}}
    expanded = list(judgement._questions_for(list(outcome.messages), merged_answers))
    base_items = {q.item for q in base_questions}
    followups = [q for q in expanded if q.item not in base_items and not _is_psm_quantity_question(q)]
    if followups:
        follow_groups = {name: [q for q in followups if q.system == name] for name in SYSTEM_ORDER}
        for name, questions in follow_groups.items():
            if not questions:
                continue
            for question in questions:
                given[question.item] = _question(project, question, {**merged_answers, **given})

    # PSM 물질군 수량(하루 최대 제조·취급량/최대 저장량)은 숫자를 다시 타이핑하지 않고,
    # 물질 목록에서 해당하는 제품을 고르면 자동으로 채운다.
    psm_followups = [q for q in expanded if q.item not in base_items and _is_psm_quantity_question(q)]
    if psm_followups:
        _psm_product_pickers(project, psm_followups, given)

    all_table_messages = [m for m in outcome.messages if _for_table(m)]
    note8_needed = any(judgement.NOTE8_TABLE_MARKER in m for m in outcome.messages)
    facility_needed = any(judgement.HOLDING_FACILITY_MARKER in m for m in outcome.messages)
    # 시설 산정 단계가 따로 필요한 경우, 최대보유량 직접입력 요청은 판정조건 표에 섞지 않는다.
    # MSDS 등 다른 물질별 판정조건만 먼저 확정하고, 최대보유량은 다음 단계에서 시설정보로 계산한다.
    table_messages = [
        m for m in all_table_messages
        if not (facility_needed and "법정 사업장 최대보유량" in judgement.display_request(m))
    ]

    deferred_items = {q.item for q in outcome.questions if _is_psm_quantity_question(q)}
    covered = [m for m in outcome.messages
               if m in all_table_messages or any(q.trigger and q.trigger in m for q in expanded)
               or any(item and item in judgement.display_request(m) for item in deferred_items)
               or judgement.NOTE8_TABLE_MARKER in m or judgement.HOLDING_FACILITY_MARKER in m]
    others = [m for m in outcome.messages if m not in covered]
    if others:
        st.markdown("**함께 확인할 내용**", help="답을 적는 질문이 아니라, 물질 목록이나 시설 정보를 보완하면 해결되는 내용입니다.")
        for message in others:
            st.write(f"• {judgement.plain_request(message)}")

    note8_rows = _note8_table(project) if note8_needed else None
    edited, used = _chemical_table(project, outcome, table_messages)

    # 질문·물질별 값·비고8 표가 하나라도 있으면 먼저 이 단계만 끝낸다.
    has_condition_inputs = bool(base_questions) or edited is not None or note8_rows is not None
    if has_condition_inputs:
        if facility_needed:
            st.caption("판정정보를 먼저 확인하면 다음 단계에서 최대보유량을 확인합니다.")

        confirmed = True
        if used:
            confirmed = st.checkbox(
                f"KOSHA 후보로 채운 MSDS 분류 {len(used)}건은 참고자료입니다. 제품 MSDS 제2항과 대조해 확인했습니다.",
                key=f"judge_kosha_ok_{project.project_id}")
        if st.session_state.get(f"judge_mixture_msds_missing_{project.project_id}", False):
            st.error(
                "혼합물 제품의 MSDS 제2항 분류가 비어 있습니다. "
                "제품 공급자 MSDS 제2항의 분류를 입력한 뒤 판정정보를 확인하세요."
            )
            confirmed = False

        missing_mixture_msds = st.session_state.get(f"judge_mixture_msds_missing_{project.project_id}", False)
        confirm_label = (
            "제품 MSDS 제2항 입력 후 판정정보 확인하기"
            if missing_mixture_msds else "판정정보 확인하기"
        )
        if st.button(confirm_label, type="primary",
                     key=f"judge_answer_{project.project_id}", disabled=not confirmed):
            if missing_mixture_msds:
                st.error("제품 MSDS 제2항 분류를 입력하기 전에는 다음 단계로 진행할 수 없습니다.")
                return True
            table_changed = edited is not None and _filled(edited) != _filled(judgement.chemical_inputs(project))
            note8_changed = note8_rows is not None and _filled(note8_rows) != _filled(judgement.note8_rows(project))
            answer_changed = any(
                value and value != existing.get(item, "")
                for item, value in given.items()
            )
            if not answer_changed and not table_changed and not note8_changed:
                if facility_needed and given and all(str(value).strip() for value in given.values()):
                    st.session_state[f"judge_continue_to_facilities_{project.project_id}"] = True
                    st.rerun()
                    return True
                st.warning("새로 입력하거나 변경한 판정 조건이 없습니다.")
                return True

            with st.spinner("판정 조건을 확정하고 다음 단계를 확인하는 중입니다."):
                if given:
                    judgement.save_answers(project, given)
                if table_changed:
                    judgement.save_chemical_inputs(project, edited)
                    kosha_candidates.record_use(project, used)
                if note8_changed:
                    judgement.save_note8_rows(project, note8_rows)
                storage.save_project(project)
                next_outcome = judgement.judge(project)
                st.session_state[f"judge_out_{project.project_id}"] = next_outcome
                st.session_state[f"judge_flash_{project.project_id}"] = _after_save_flash(next_outcome)
            st.rerun()
        return True

    # 판정 조건 입력이 더 없고 시설정보만 필요할 때에만 최대보유량 단계를 표시한다.
    if facility_needed:
        holding_names = judgement.holding_target_names(project)
        _facilities(project, outcome, holding_names)
        return True

    return False


def _holding_psm_questions(project, outcome) -> bool:
    """2단계에서 PSM 물질군 수량을 저장하고 엔진에 다시 전달한다."""
    questions = _stage2_questions(outcome)
    if not questions:
        return False

    st.markdown(
        "#### 최대보유량 확인에 필요한 PSM 정보",
        help=(
            "인화성 가스·액체 해당 여부는 1단계에서 확인하고, 해당하는 경우의 하루 제조·취급량과 "
            "최대 저장량은 이 단계에서 확인합니다. 입력값은 공정안전보고서 판정엔진에 그대로 전달됩니다."
        ),
    )
    existing = judgement.answers(project)
    suggested = _psm_quantity_suggestions(project, questions)
    if suggested:
        st.caption(
            "물질목록에 입력한 제품 MSDS 제2항 분류와 수량을 기준으로 자동 계산한 참고값입니다. "
            "실제 PSM 합계와 대조한 뒤 수정하거나 확인하세요."
        )
    given: dict[str, str] = {}
    for question in questions:
        given[question.item] = _question(project, question, {**suggested, **existing, **given})

    if st.button("다음 단계로 이동", type="primary", key=f"judge_psm_quantity_{project.project_id}"):
        if not any(value != existing.get(item, "") for item, value in given.items()):
            if not all(str(given.get(question.item, "")).strip() for question in questions):
                st.warning("PSM 수량을 입력하거나 물질목록의 수량을 먼저 확인해 주세요.")
                return True
        with st.spinner("PSM 수량을 저장하고 다음 단계를 확인하는 중입니다."):
            judgement.save_answers(project, given)
            storage.save_project(project)
            next_outcome = judgement.judge(project)
            st.session_state[f"judge_out_{project.project_id}"] = next_outcome
            st.session_state[f"judge_flash_{project.project_id}"] = _after_save_flash(next_outcome).replace(
                "입력이 저장되었습니다.", "PSM 수량이 저장되었습니다."
            )
        st.rerun()
    return True


def _product_quantity_kg(project, names: set[str]) -> dict[str, float]:
    """고른 제품들의 하루 최대 제조·사용량/최대 저장량을 더해 kg로 돌려준다."""
    from engine.stage2 import cap_chemical_workspace as chem

    _, rows = chem._rows(project)
    inputs = judgement.chemical_inputs(project)
    inputs = inputs + [{}] * (len(rows) - len(inputs))
    totals = {"mfg": 0.0, "storage": 0.0}
    for index, row in enumerate(rows):
        name = str(row.get("제품명") or row.get("물질명") or "").strip()
        if name not in names:
            continue
        extra = inputs[index]
        unit = str(row.get("수량 단위") or extra.get("단위") or "ton").strip().lower()
        factor = 1000.0 if unit == "ton" else 1.0
        for key, target in (("최대 제조·사용량", "mfg"), ("최대 저장량", "storage")):
            raw = extra.get(key) or row.get(key)
            try:
                totals[target] += float(str(raw).replace(",", "").strip()) * factor
            except (TypeError, ValueError):
                continue
    return totals


def _psm_label_from_followup(question) -> str:
    """'별표 13 제N호 하루 최대 제조·취급량(kg)' 같은 후속 질문에서 '인화성 액체' 같은 분류명을 얻는다.

    후속 질문 자체에는 분류명이 없고, 이 질문을 열게 한 부모 질문('...해당 여부')의 item에만 있다.
    """
    parent = str(getattr(question, "follows", "") or "")
    label = re.sub(r"^별표 13 제\d+호 ", "", parent)
    return re.sub(r" 해당 여부$", "", label).strip() or parent


def _psm_product_pickers(project, questions, given: dict[str, str]) -> None:
    """PSM 물질군 수량은 직접 타이핑하지 않고, 물질 목록에서 해당하는 제품을 고르면 자동으로 합산한다.

    같은 별표 13 호수(하루 최대 제조·취급량/최대 저장량)를 한 번의 제품 선택으로 함께 채운다.
    """
    from engine.stage2 import cap_chemical_workspace as chem

    _, rows = chem._rows(project)
    options = list(dict.fromkeys(str(r.get("제품명") or r.get("물질명") or "").strip() for r in rows if r))
    options = [name for name in options if name]
    by_no: dict[str, list] = {}
    for question in questions:
        match = re.search(r"제(\d+)호", question.item)
        by_no.setdefault(match.group(1) if match else question.item, []).append(question)
    for no, group in by_no.items():
        label = _psm_label_from_followup(group[0])
        picked = st.multiselect(
            f"{label}에 해당하는 제품", options,
            key=f"judge_psm_products_{project.project_id}_{no}",
            help="물질 목록에 이미 적은 제품 중 이 분류에 해당하는 것을 고르면, 그 제품들의 하루 최대 제조·사용량과 "
                 "최대 저장량을 더해 자동으로 채웁니다. 물질 목록에 없는 제품이면 물질 목록을 먼저 채우세요.",
        )
        totals = _product_quantity_kg(project, set(picked)) if picked else {"mfg": 0.0, "storage": 0.0}
        for question in group:
            target = "mfg" if "하루 최대 제조·취급량" in question.item else "storage"
            given[question.item] = judgement._fmt(totals[target]) if picked else ""


def _psm_quantity_suggestions(project, questions) -> dict[str, str]:
    """물질목록의 제품 MSDS와 수량을 PSM 합계의 참고값으로 만든다.

    이 값은 사용자 화면의 초기 제안일 뿐이며, 법정 판정엔진의 규정량·분류·계산식은
    변경하지 않는다. 제품 MSDS 제2항이 확인된 행만 합산해 혼합물 구성성분 후보를
    제품 분류로 잘못 사용하는 일을 막는다.
    """
    from engine.stage2 import cap_chemical_workspace as chem

    _, rows = chem._rows(project)
    inputs = judgement.chemical_inputs(project)
    if not rows:
        return {}
    inputs = inputs + [{}] * (len(rows) - len(inputs))
    sds_col = "SDS 제2항 유해성·위험성 분류(선택 입력)"
    totals: dict[int, dict[str, float]] = {}
    for index, row in enumerate(rows):
        extra = inputs[index]
        classification = str(extra.get(sds_col) or "").strip()
        if not classification:
            continue
        if "인화성 액체" in classification:
            item_no = 2
        elif "인화성 가스" in classification:
            item_no = 1
        else:
            continue
        unit = str(row.get("수량 단위") or extra.get("단위") or "ton").strip().lower()
        bucket = totals.setdefault(item_no, {"mfg": 0.0, "storage": 0.0})
        for key, target in (("최대 제조·사용량", "mfg"), ("최대 저장량", "storage")):
            raw = extra.get(key) or row.get(key)
            try:
                value = float(str(raw).replace(",", "").strip())
            except (TypeError, ValueError):
                continue
            bucket[target] += value * (1000.0 if unit == "ton" else 1.0)

    suggestions: dict[str, str] = {}
    for question in questions:
        item_no = 1 if "제1호" in question.item else 2
        bucket = totals.get(item_no)
        if not bucket:
            continue
        if "하루 최대 제조·취급량" in question.item:
            suggestions[question.item] = judgement._fmt(bucket["mfg"])
        elif "최대 저장량" in question.item:
            suggestions[question.item] = judgement._fmt(bucket["storage"])
    return suggestions


def _filled(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in row.items() if v} for row in rows]


def _for_table(message: str) -> bool:
    text = judgement.display_request(message)
    return any(marker in text for marker in judgement.CHEM_REQUEST_MARKERS)


YES_NO_UNKNOWN = ["", "Y", "N", "모름"]
ANSWER_LABELS = {"Y": "예", "N": "아니오"}


def _holding_help() -> None:
    """'사업장 최대보유량'이 무엇이고 어떻게 채우는지. 표에 그 열이 있을 때만 한 줄로 보이고, 설명은 ? 안에 있다."""
    st.markdown("**사업장 최대보유량은 어떻게 채우나요?**", help=HOLDING_HELP)


def _facilities(project, outcome, needs_names: list[str]) -> None:
    """판정 화면 안에서 법적 스크리닝 대상 물질의 시설정보만 받는다."""
    from ui import cap_facility_editor

    st.markdown("**시설 입력 — 사업장 최대보유량 계산**", help=FACILITY_HELP)
    if not needs_names:
        st.warning(
            "최대보유량 계산이 필요한 물질을 판정엔진에서 특정하지 못했습니다. "
            "물질별 확인값을 먼저 저장한 뒤 다시 판정해 주세요."
        )
        return
    st.caption(
        "아래 물질은 판정엔진이 최대보유량 계산 대상으로 확인했습니다: "
        + ", ".join(needs_names)
        + ". 물질명은 자동으로 채워지며 바꿀 수 없습니다."
    )

    def saved(count: int) -> None:
        st.session_state.pop(f"judge_out_{project.project_id}", None)
        st.session_state[f"judge_out_{project.project_id}"] = judgement.judge(project)
        st.rerun()

    cap_facility_editor.render(
        project, "judge_fac", on_saved=saved, compact=True, focus_names=needs_names
    )


def _names_needing_holding(project, table_messages=None) -> list[str]:
    """하위호환용 래퍼. 시설대상은 이제 요청문구가 아니라 판정엔진에서 직접 가져온다."""
    return judgement.holding_target_names(project)


def _chemical_table(project, outcome, table_messages):
    """물질별로 판정 엔진이 요구한 값만 입력받는 표. 입력한 전체 행 목록(저장 형식)을 돌려주고, 표가 필요 없으면 None."""
    if not table_messages:
        return None, {}
    from engine.stage2 import cap_chemical_workspace as chem

    _, rows = chem._rows(project)
    if not rows:
        return None, {}
    needs = judgement.request_needs(table_messages, len(rows))
    wanted = sorted(needs)
    shown = judgement.columns_for(needs) or list(judgement.CHEM_INPUT_COLUMNS)
    has_quantity = any(column in shown for column in judgement.QUANTITY_COLUMNS)
    st.markdown("**물질별로 확인할 값**", help=WHY_ROWS)
    if "사업장 최대보유량" in {label for labels in needs.values() for label in labels}:
        _holding_help()
    stored = judgement.chemical_inputs(project)
    stored = stored + [{}] * (len(rows) - len(stored))
    parts = judgement.components_by_row(project)
    pid = project.project_id
    cand_key, gen_key, sds_col = f"judge_kosha_{pid}", f"judge_chem_gen_{pid}", "SDS 제2항 유해성·위험성 분류(선택 입력)"
    candidates: dict = st.session_state.get(cand_key, {})
    kosha_targets = _kosha_targets(rows, wanted, parts)
    if sds_col in shown:
        candidates = _auto_lookup_kosha(project, kosha_targets, candidates, cand_key, gen_key)
    records = []
    for number in wanted:
        row, extra = rows[number - 1], stored[number - 1]
        cas = str(row.get("CAS No.") or row.get("CAS 번호") or "").strip()
        component_cas = [component for component, _ in (parts.get(number) or []) if component]
        # 단일물질만 KOSHA 후보를 MSDS 입력칸에 참고값으로 넣는다.
        # 혼합물은 구성성분 후보를 제품 MSDS 제2항으로 오인하지 않도록 비워 둔다.
        if (not component_cas and not extra.get(sds_col)
                and candidates.get(cas) is not None and candidates[cas].usable):
            extra = {**extra, sds_col: candidates[cas].text}  # 비어 있는 칸에만 후보를 넣는다
        if component_cas:
            component_display = "; ".join(
                f"{component} ({pct}%)" if str(pct).strip() else component
                for component, pct in (parts.get(number) or [])
            )
            cas_display = f"구성성분: {component_display}"
        else:
            cas_display = cas
        record = {
            "행": number,
            "제품명": str(row.get("제품명") or row.get("물질명") or ""),
            "CAS No.": cas_display,
            "필요한 값": ", ".join(needs[number]),
        }
        if has_quantity:
            record["단위"] = "ton"  # 저장된 값은 항상 ton이다
        record.update({column: extra.get(column, "") for column in shown})
        records.append(record)
    frame = pd.DataFrame(records)
    if sds_col in shown:
        _kosha_button(project, kosha_targets, cand_key, gen_key, candidates)
        _mixture_kosha_reference(rows, wanted, parts, candidates)
        if any(parts.get(number) for number in wanted):
            st.warning(
                "혼합물 제품의 MSDS 제2항 분류는 구성성분 KOSHA 후보를 합쳐서 자동 확정하지 않습니다. "
                "제품 공급자가 발행한 MSDS의 제2항(유해성·위험성)을 확인해 입력하세요. "
                "제품 MSDS가 없으면 해당 항목을 확인할 때까지 판정을 진행하지 마세요."
            )
    text = lambda label, help_text=None: st.column_config.TextColumn(label, help=help_text)
    config = {
        "행": st.column_config.NumberColumn("행", disabled=True, width="small"),
        "제품명": st.column_config.TextColumn("제품명", disabled=True),
        "CAS No.": st.column_config.TextColumn("CAS No.", disabled=True),
        "필요한 값": st.column_config.TextColumn("필요한 값", disabled=True, help="이 물질에 대해 판정 규칙이 요청한 값입니다."),
        "함량(%)": text("함량(%)", "제품 중 이 물질의 함량입니다."),
        "상온·상압 액체 여부(해당 시)": st.column_config.SelectboxColumn("상온·상압 액체 여부", options=YES_NO_UNKNOWN),
        "단위": st.column_config.SelectboxColumn("단위", options=list(judgement.UNIT_OPTIONS), required=True, width="small",
                                                  help="이 행의 수량 칸에 적은 값의 단위입니다. 저장할 때 ton으로 바꿔 저장합니다."),
        "최대 제조·사용량": text("하루 최대 제조·사용량", "하루에 가장 많이 제조·사용하는 양입니다. 모르면 비워 두고, 하지 않으면 0을 적으세요."),
        "최대 저장량": text("최대 저장량", "한꺼번에 가장 많이 저장하는 양입니다. 모르면 비워 두고, 저장하지 않으면 0을 적으세요."),
        "최대 동시보유량(알면 입력)": text(
            "사업장 최대보유량",
            "법에서 정한 방법(시설별 용량·비중 등)으로 계산한 사업장 전체의 최대 보유량입니다. 계산하지 않았다면 비워 두세요. 별지 제1호에서 시설을 입력하면 자동 계산됩니다."),
        "최대보유량 법정 산정 여부": st.column_config.SelectboxColumn(
            "위 값은 법정 방식으로 계산했나요?",
            help="바로 왼쪽 '사업장 최대보유량'을 법에서 정한 방법으로 계산했으면 Y(예), 창고 재고 등 단순 추정이면 N(아니오)입니다. 잘 모르면 '모름'을 고르세요.",
            options=YES_NO_UNKNOWN),
        sds_col: text(
            "MSDS 제2항 분류",
            "제품 MSDS(물질안전보건자료) 2번 항목 '유해성·위험성'에 적힌 분류를 그대로 옮겨 적습니다. 위 KOSHA 버튼으로 후보를 불러올 수 있습니다. 해당 분류가 없으면 '별표1 해당없음'."),
    }
    editor = st.data_editor(frame, column_config=config, hide_index=True, width="stretch", num_rows="fixed",
                            key=f"judge_chem_{pid}_{st.session_state.get(gen_key, 0)}")
    result = [dict(row) for row in stored[:len(rows)]]
    used: dict = {}
    for position, number in enumerate(wanted):
        values = editor.iloc[position]
        typed = {column: ("" if pd.isna(values[column]) else str(values[column]).strip()) for column in shown}
        if has_quantity:
            typed["단위"] = "ton" if pd.isna(values["단위"]) else str(values["단위"])
        # 표에 보이지 않는 열의 예전 값은 그대로 두고, 보이는 열만 바꾼다. 고른 단위는 ton으로 통일해 저장한다.
        result[number - 1] = {**result[number - 1], **judgement.rows_to_ton([typed])[0]}
        source_row = rows[number - 1]
        parent_cas = str(source_row.get("CAS No.") or source_row.get("CAS 번호") or "").strip()
        component_cas = [component for component, _ in (parts.get(number) or []) if component]
        # 혼합물의 구성성분 후보는 참고표에서만 사용하고 제품 MSDS 입력값으로 기록하지 않는다.
        cand = candidates.get(parent_cas) if not component_cas else None
        # 후보 문구를 그대로 둔 칸만 'KOSHA 후보 사용'으로 본다(고쳐 쓴 칸은 사용자가 직접 적은 값이다).
        if (sds_col in shown and cand is not None and cand.usable and result[number - 1].get(sds_col) == cand.text
                and not stored[number - 1].get(sds_col)):
            used[parent_cas] = cand
    mixture_msds_missing = any(
        parts.get(number) and not str(result[number - 1].get(sds_col) or "").strip()
        for number in wanted
    ) if sds_col in shown else False
    st.session_state[f"judge_mixture_msds_missing_{pid}"] = mixture_msds_missing
    return result, used


def _kosha_targets(rows, wanted, parts) -> list[str]:
    """판정조건 화면에서 KOSHA 참고조회할 CAS를 구성성분 단위로 만든다.

    혼합물은 제품행의 CAS가 없으므로 구성성분 CAS를 각각 조회한다. 이 목록은
    참고조회용이며 혼합물 제품의 MSDS 제2항 분류를 대신하지 않는다.
    """
    targets: list[str] = []
    for number in wanted:
        row = rows[number - 1]
        parent_cas = str(row.get("CAS No.") or row.get("CAS 번호") or "").strip()
        component_cas = [cas for cas, _ in (parts.get(number) or []) if cas]
        targets.extend(component_cas or ([parent_cas] if parent_cas else []))
    return list(dict.fromkeys(targets))


def _auto_lookup_kosha(project, targets, candidates, cand_key, gen_key) -> dict:
    """화면 진입 시 아직 조회하지 않은 CAS의 KOSHA 후보를 한 번 자동조회한다."""
    missing = [cas for cas in targets if cas not in candidates]
    if not missing:
        return candidates
    with st.spinner(f"KOSHA에서 MSDS 참고분류 {len(missing)}건을 자동조회하는 중입니다."):
        found = kosha_candidates.fetch(missing)
    merged = {**candidates, **found}
    st.session_state[cand_key] = merged
    st.session_state[gen_key] = st.session_state.get(gen_key, 0) + 1
    return merged


def _kosha_button(project, targets, cand_key, gen_key, candidates) -> None:
    empty = kosha_candidates.pending_cas(targets, candidates)  # 네트워크 오류 등은 수동 재조회 허용
    help_text = KOSHA_HELP
    if st.button("KOSHA에서 MSDS 분류 후보 불러오기", key=f"judge_kosha_go_{project.project_id}", disabled=not empty,
                 help=help_text):
        with st.spinner(f"KOSHA에서 {len(set(empty))}개 CAS를 조회하는 중입니다."):
            found = kosha_candidates.fetch(empty)
        st.session_state[cand_key] = {**candidates, **found}
        st.session_state[gen_key] = st.session_state.get(gen_key, 0) + 1
        st.rerun()
    if candidates:
        misses = [c for c in candidates.values() if not c.usable]
        got = len(candidates) - len(misses)
        detail = " (" + ", ".join(f"{c.cas}: {c.message or c.status}" for c in misses[:3]) + ")" if misses else ""
        st.caption(f"KOSHA 후보 {got}건을 채웠습니다. 채우지 못한 {len(misses)}건은 직접 적어 주세요.{detail}")


def _mixture_kosha_reference(rows, wanted, parts, candidates) -> None:
    """혼합물 구성성분별 KOSHA 결과를 참고자료로만 표시한다."""
    reference = []
    for number in wanted:
        row = rows[number - 1]
        for cas, pct in parts.get(number) or []:
            candidate = candidates.get(cas)
            if candidate is None:
                continue
            reference.append({
                "제품명": str(row.get("제품명") or row.get("물질명") or f"{number}행"),
                "구성성분 CAS No.": cas,
                "함량(%)": pct,
                "KOSHA 참고분류": candidate.text or f"({candidate.message or candidate.status})",
            })
    if reference:
        st.caption("혼합물 구성성분별 KOSHA 조회 결과는 참고자료입니다. 제품 MSDS 제2항 분류는 제품 MSDS를 확인해 입력하세요.")
        st.dataframe(pd.DataFrame(reference), hide_index=True, width="stretch")


def _decision_basis_table(rows, kind: str) -> None:
    """판정엔진이 반환한 비교자료를 사용자용 표로 보여준다."""
    if not rows:
        return
    if kind == "CAP":
        columns = (
            ("물질", "product_name"),
            ("CAS No.", "cas"),
            ("최대보유량(ton)", "calculated_max_holding_ton"),
            ("하위 규정수량(ton)", "lower_quantity_ton"),
            ("상위 규정수량(ton)", "upper_quantity_ton"),
            ("비교결과", "decision_level"),
        )
    else:
        columns = (
            ("법정 항목", "legal_item_no"),
            ("물질", "legal_substance"),
            ("CAS No.", "cas_values"),
            ("제조·취급량(kg)", "manufacture_handling_kg"),
            ("저장량(kg)", "storage_kg"),
            ("비교 기준", "controlling_basis"),
            ("비교비율", "controlling_ratio"),
        )
    visible = []
    for row in rows:
        item = {}
        for label, key in columns:
            value = row.get(key, "")
            if value is None:
                value = ""
            item[label] = value
        visible.append(item)
    st.dataframe(pd.DataFrame(visible), hide_index=True, width="stretch")


def _decision_basis(outcome) -> None:
    """최종 결과와 함께 엔진의 설명·수치·법적 근거를 표시한다."""
    decision = getattr(outcome, "decision", None)
    if decision is None:
        return
    cap_explanation = str(getattr(decision, "cap_explanation", "") or "").strip()
    psm_explanation = str(getattr(decision, "psm_explanation", "") or "").strip()
    cap_basis = [str(value) for value in (getattr(decision, "cap_legal_basis", ()) or ()) if str(value).strip()]
    psm_basis = [str(value) for value in (getattr(decision, "psm_legal_basis", ()) or ()) if str(value).strip()]
    cap_rows = list(getattr(decision, "cap_quantity_rows", ()) or ())
    psm_rows = list(getattr(decision, "psm_ratio_rows", ()) or ())
    r_value = getattr(decision, "psm_r_value", None)

    if not any((cap_explanation, psm_explanation, cap_basis, psm_basis, cap_rows, psm_rows)):
        return
    with st.expander("판정 이유 및 법적 근거", expanded=True):
        st.caption("아래 내용은 승인 규정 DB와 판정엔진이 사용한 입력값·비교결과를 요약한 것입니다.")
        st.markdown(f"**{CAP} 판정 이유**")
        st.write(cap_explanation or "판정 설명이 제공되지 않았습니다.")
        _decision_basis_table(cap_rows, "CAP")
        if cap_basis:
            st.caption("법적 근거: " + " / ".join(cap_basis))

        st.markdown(f"**{PSM} 판정 이유**")
        st.write(psm_explanation or "판정 설명이 제공되지 않았습니다.")
        if r_value is not None:
            st.caption(f"별표 13 비고 제7호 합산한 값(R): {r_value}")
        _decision_basis_table(psm_rows, "PSM")
        if psm_basis:
            st.caption("법적 근거: " + " / ".join(psm_basis))




def _decided(project, outcome) -> None:
    st.success("판정이 끝났습니다.")
    st.write(f"**{CAP}:** {outcome.cap_status or '확인 안 됨'}")
    if getattr(outcome.decision, "cap_explanation", ""):
        st.caption(str(outcome.decision.cap_explanation))
    st.write(f"**{PSM}:** {outcome.psm_status or '확인 안 됨'}")
    if getattr(outcome.decision, "psm_explanation", ""):
        st.caption(str(outcome.decision.psm_explanation))
    _decision_basis(outcome)
    if outcome.status == "NOT_REQUIRED":
        st.info("두 문서 모두 작성·제출 대상이 아닙니다. 대상이 아니면 별지 작성을 시작하지 않습니다.")
        if st.button("최종판정하기", key=f"judge_confirm_{project.project_id}"):
            judgement.apply(project, outcome)
            storage.save_project(project)
            st.session_state.pop(f"judge_out_{project.project_id}", None)
            st.rerun()
        return
    st.markdown("**이번에 작성할 문서**")
    st.caption("법적으로 대상인 문서만 고를 수 있습니다. 하나만 작성해도 다른 문서의 대상 여부는 그대로 남습니다.")
    write_cap = st.checkbox(CAP, value=outcome.cap_target, disabled=not outcome.cap_target, key=f"judge_cap_{project.project_id}")
    write_psm = st.checkbox(PSM, value=outcome.psm_target, disabled=not outcome.psm_target, key=f"judge_psm_{project.project_id}")
    if st.button("최종판정하기", type="primary", key=f"judge_apply_{project.project_id}"):
        try:
            judgement.apply(project, outcome, write_psm=write_psm, write_cap=write_cap)
        except ValueError as exc:
            st.error(str(exc))
            return
        storage.save_project(project)
        st.session_state.pop(f"judge_out_{project.project_id}", None)
        st.rerun()


def render(project) -> None:
    """법정 대상 판정. 사용자는 판정정보 확인 → 최대보유량 확인 → 최종판정 순서만 본다."""
    from ui.cap_start_panel import _gate_hold

    pending = judgement.undecided(project)
    label = "법정 대상 판정" + (" — 판정 전" if pending else "")
    with st.expander(label, expanded=pending):
        st.markdown("**현재 판정:** " + _status_line(project), help=HELP_FLOW)
        key = f"judge_out_{project.project_id}"
        flash_key = f"judge_flash_{project.project_id}"
        flash = st.session_state.pop(flash_key, None)
        if flash:
            st.success(flash)
        outcome = st.session_state.get(key)
        has_own_button = False
        if outcome is not None:
            continue_key = f"judge_continue_to_facilities_{project.project_id}"
            has_facility_request = any(
                judgement.HOLDING_FACILITY_MARKER in message
                for message in getattr(outcome, "messages", ())
            )
            continue_to_facilities = bool(st.session_state.get(continue_key) and has_facility_request)
            if st.session_state.get(continue_key) and not has_facility_request:
                st.session_state.pop(continue_key, None)
            st.markdown("진행: " + step_line(2 if continue_to_facilities else current_step(outcome)))
            if outcome.status == "COMPOSITION":
                _composition_form(project, outcome)
                has_own_button = True
            elif outcome.status == "INVALID":
                st.warning("입력을 확인해 주세요.")
                for message in outcome.messages:
                    st.write(f"• {judgement.display_request(message)}")
            elif outcome.status == "PENDING":
                st.warning("최대보유량을 확인해야 최종판정을 진행할 수 있습니다.")
                # outcome.missing_quantity는 이번 판정에서 새로 빠진 물질만 담는다. PSM 수량처럼
                # 다른 조건을 먼저 저장한 뒤라 이 목록이 비어 있어도, 시설 입력이 필요한 물질은
                # 여전히 있을 수 있다(REQUEST 단계의 facility_needed 분기와 같은 방식으로 구한다).
                # 비어 있는 채로 두면 시설 화면이 "물질을 특정하지 못했다"는 막다른 안내만 보여 준다.
                holding_names = list(outcome.missing_quantity) or judgement.holding_target_names(project)
                for name in holding_names:
                    st.write(f"• {name}")
                _facilities(project, outcome, holding_names)
                has_own_button = True
            elif outcome.status == "SYSTEM":
                st.error("회사 입력 문제가 아니라 규정 DB 준비상태를 관리자가 확인해야 합니다.")
                for message in outcome.messages:
                    st.write(f"• {judgement.display_request(message)}")
            elif outcome.status == "REQUEST":
                if continue_to_facilities:
                    st.info(
                        "판정정보는 이미 저장되어 있습니다. 저장된 답변에 '모름'이 있으면 최종 판정 전에 확인해야 하지만, "
                        "먼저 최대보유량을 입력할 수 있습니다."
                    )
                    _facilities(project, outcome, judgement.holding_target_names(project))
                    has_own_button = True
                elif _stage2_questions(outcome) and not any(
                    not _is_psm_quantity_question(question) for question in outcome.questions
                ):
                    has_own_button = _holding_psm_questions(project, outcome)
                else:
                    has_own_button = _ask(project, outcome)
            else:
                _decided(project, outcome)
                has_own_button = True
        if not has_own_button:
            if st.button("판정 시작하기" if pending else "판정 다시 시작하기", key=f"judge_run_{project.project_id}"):
                with st.spinner("법정 대상 여부를 판정하는 중입니다. 물질·시설이 많으면 시간이 걸릴 수 있습니다."):
                    if _gate_hold():
                        return
                    st.session_state[key] = judgement.judge(project)
                st.rerun()

from __future__ import annotations

"""법정 대상 판정 화면 조각: 판정 전 사업장의 판정, 이미 판정한 사업장의 다시 판정, 판정에 필요한 질문."""

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


STEPS = ("성분 확인", "판정 질문", "물질별 값 확인", "결과")


def current_step(outcome) -> int:
    """지금 화면이 어느 단계인지(1~4). 판정 규칙이 요청하는 내용에 따라 필요한 단계만 나타납니다."""
    status = getattr(outcome, "status", "")
    if status == "COMPOSITION":
        return 1
    if status == "REQUEST":
        return 2 if getattr(outcome, "questions", ()) else 3
    if status == "PENDING":
        return 3
    return 4


def step_line(step: int) -> str:
    return " → ".join(f"**{i}. {name}**" if i == step else f"{i}. {name}" for i, name in enumerate(STEPS, start=1))


def unit_help() -> str:
    return "칸마다 kg 또는 ton을 고를 수 있습니다. 저장할 때 자동으로 ton으로 바꿔 줍니다."


COMPOSITION_OPTIONS = ["선택하세요", "단일물질", "혼합물"]


def _composition_form(project, outcome) -> None:
    """Confirm composition before statutory screening; CAS is the legal identifier."""
    from engine.stage2 import cap_chemical_workspace as chem

    _, rows = chem._rows(project)
    targets = list(outcome.composition_rows or judgement.composition_rows(project))
    if not rows or not targets:
        st.info("확인할 물질 성분 정보가 없습니다.")
        return

    st.markdown("#### 물질 성분 확인")
    st.caption(
        "물질명은 표시용으로만 사용합니다. 법적 판정은 CAS No.를 기준으로 합니다. "
        "단일물질은 CAS No.를 확인하면 100%로 처리하고, 혼합물은 제품 SDS 제3항의 구성성분 CAS No.와 함량(%)을 각각 입력합니다."
    )

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
        st.markdown(f"**{number}행 · {product}**")
        choice = st.radio(
            f"{product}의 구분",
            COMPOSITION_OPTIONS,
            horizontal=True,
            key=f"judge_comp_kind_{pid}_{number}",
            help="단일물질이면 하나의 CAS No.로 판정합니다. 혼합제품이면 제품 자체 이름이 아니라 SDS 제3항 구성성분의 CAS No.로 판정합니다.",
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
                {
                    "CAS No.": str(comp.get("CAS No.") or ""),
                    "함량(%)": comp.get("함량(%)"),
                    "성분명(선택)": str(comp.get("구성성분명") or ""),
                }
                for comp in stored_components
                if str(comp.get("제품목록행번호") or "").strip() == str(number)
            ]
            seed = existing or [{"CAS No.": "", "함량(%)": None, "성분명(선택)": ""}]
            editor = st.data_editor(
                pd.DataFrame(seed, columns=["CAS No.", "함량(%)", "성분명(선택)"]),
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                key=f"judge_comp_parts_{pid}_{number}",
                column_config={
                    "CAS No.": st.column_config.TextColumn(
                        "구성성분 CAS No.",
                        help="제품 SDS 제3항에 적힌 구성성분의 CAS No.를 그대로 입력합니다. 모든 구성성분 행에서 필수입니다.",
                    ),
                    "함량(%)": st.column_config.NumberColumn(
                        "함량(%)", min_value=0.0, max_value=100.0,
                        help="제품 SDS 제3항의 해당 구성성분 함량을 입력합니다.",
                    ),
                    "성분명(선택)": st.column_config.TextColumn(
                        "성분명(선택)", help="표시용입니다. 법적 판정에는 사용하지 않습니다."
                    ),
                },
            )
            for item in editor.to_dict("records"):
                cas = "" if pd.isna(item.get("CAS No.")) else str(item.get("CAS No.") or "").strip()
                pct = "" if pd.isna(item.get("함량(%)")) else str(item.get("함량(%)") or "").strip()
                name = "" if pd.isna(item.get("성분명(선택)")) else str(item.get("성분명(선택)") or "").strip()
                if not cas and not pct and not name:
                    continue
                components.append({
                    "제품목록행번호": number,
                    "CAS No.": cas,
                    "함량(%)": pct,
                    "성분명(선택)": name,
                })
        st.divider()

    confirmed = True
    if any_mixture:
        confirmed = st.checkbox(
            "혼합물 구성성분의 CAS No.와 함량(%)을 제품 SDS 제3항과 대조해 확인했습니다.",
            key=f"judge_comp_sds_ok_{pid}",
        )

    if st.button(
        "성분정보 저장하고 판정 계속",
        type="primary",
        key=f"judge_comp_save_{pid}",
        disabled=any_mixture and not confirmed,
    ):
        try:
            judgement.save_composition(
                project,
                classifications,
                components,
                sds_confirmed=confirmed,
            )
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


def _ask(project, outcome) -> None:
    st.markdown("#### 판정에 필요한 확인 사항")
    st.caption("사업장 전체에 대한 질문입니다. 각 질문 옆 ? 에 뜻과 확인 방법이 있습니다. 확실하지 않으면 추측하지 말고 '모름'을 고르세요.")
    existing = judgement.answers(project)
    given: dict[str, str] = {}
    groups = {name: [q for q in outcome.questions if q.system == name] for name in SYSTEM_ORDER}
    for name, questions in groups.items():
        if not questions:
            continue
        if len([g for g in groups.values() if g]) > 1:
            st.markdown(f"**{name}**")
        for question in questions:
            given[question.item] = _question(project, question, existing)
    table_messages = [m for m in outcome.messages if _for_table(m)]
    note8_needed = any(judgement.NOTE8_TABLE_MARKER in m for m in outcome.messages)
    covered = [m for m in outcome.messages
               if m in table_messages or any(q.trigger and q.trigger in m for q in outcome.questions)
               or judgement.NOTE8_TABLE_MARKER in m]
    others = [m for m in outcome.messages if m not in covered]
    if others:
        st.info("판정 규칙이 함께 요청한 내용입니다. 답을 적는 질문이 아니라, 물질 목록이나 시설 정보를 보완하면 해결됩니다.\n\n"
                + "\n".join(f"• {judgement.plain_request(m)}" for m in others))
    note8_rows = _note8_table(project) if note8_needed else None
    edited, used = _chemical_table(project, outcome, table_messages)
    confirmed = True
    if used:
        confirmed = st.checkbox(
            f"KOSHA 후보로 채운 SDS 분류 {len(used)}건은 참고자료입니다. 제품 SDS 제2항과 대조해 확인했습니다.",
            key=f"judge_kosha_ok_{project.project_id}")
    if st.button("답을 저장하고 다시 판정", type="primary", key=f"judge_answer_{project.project_id}", disabled=not confirmed):
        table_changed = edited is not None and _filled(edited) != _filled(judgement.chemical_inputs(project))
        note8_changed = note8_rows is not None and _filled(note8_rows) != _filled(judgement.note8_rows(project))
        if not any(given.values()) and not table_changed and not note8_changed:
            st.warning("한 가지 이상 답해 주세요.")
        else:
            if given:
                judgement.save_answers(project, given)
            if table_changed:
                judgement.save_chemical_inputs(project, edited)
                kosha_candidates.record_use(project, used)
            if note8_changed:
                judgement.save_note8_rows(project, note8_rows)
            storage.save_project(project)
            st.session_state[f"judge_out_{project.project_id}"] = judgement.judge(project)
            st.rerun()


def _filled(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in row.items() if v} for row in rows]


def _for_table(message: str) -> bool:
    text = judgement.display_request(message)
    return any(marker in text for marker in judgement.CHEM_REQUEST_MARKERS)


YES_NO_UNKNOWN = ["", "Y", "N", "모름"]
ANSWER_LABELS = {"Y": "예", "N": "아니오"}


def _holding_help() -> None:
    """'사업장 최대보유량'이 무엇이고 어떻게 채우는지. 표에 그 열이 있을 때만 보여 준다."""
    st.info("**사업장 최대보유량**은 같은 물질이 사업장 안의 여러 시설(저장탱크·반응기·보관창고 등)에 동시에 있을 수 있는 양을 "
            "법에서 정한 방식으로 계산해 합한 값입니다. 규정수량과 비교해 작성 대상인지 정하는 기준이 됩니다.\n\n"
            "• **시설 정보를 입력하면 프로그램이 계산해 줍니다.** 아래 링크의 별지 제1호에서 시설(용량·비중 등)을 입력하세요.\n\n"
            "• 이미 법에서 정한 방식으로 계산한 값이 있으면 아래 표에 직접 적어도 됩니다.")
    try:
        st.page_link("ui/cap_workspace_page.py", label="별지 제1호에서 시설 입력하기", icon="📝")
    except Exception:
        pass  # 페이지 이동 정보가 없는 환경(테스트 등)에서는 링크만 생략한다


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
    st.markdown("**물질별로 확인할 값**")
    st.caption("아래 표의 '필요한 값' 칸에 적힌 내용을 같은 줄에서 채워 주세요. 모르는 칸은 비워 두면 됩니다. "
               "빈 칸은 '아직 모름', 0은 '없음'으로 다르게 처리합니다." + (" " + unit_help() if has_quantity else ""))
    if "사업장 최대보유량" in {label for labels in needs.values() for label in labels}:
        _holding_help()
    stored = judgement.chemical_inputs(project)
    stored = stored + [{}] * (len(rows) - len(stored))
    pid = project.project_id
    cand_key, gen_key, sds_col = f"judge_kosha_{pid}", f"judge_chem_gen_{pid}", "SDS 제2항 유해성·위험성 분류(선택 입력)"
    candidates: dict = st.session_state.get(cand_key, {})
    records = []
    for number in wanted:
        row, extra = rows[number - 1], stored[number - 1]
        cas = str(row.get("CAS No.") or row.get("CAS 번호") or "").strip()
        if not extra.get(sds_col) and candidates.get(cas) is not None and candidates[cas].usable:
            extra = {**extra, sds_col: candidates[cas].text}  # 비어 있는 칸에만 후보를 넣는다
        record = {
            "행": number,
            "제품명": str(row.get("제품명") or row.get("물질명") or ""),
            "CAS No.": cas,
            "필요한 값": ", ".join(needs[number]),
        }
        if has_quantity:
            record["단위"] = "ton"  # 저장된 값은 항상 ton이다
        record.update({column: extra.get(column, "") for column in shown})
        records.append(record)
    frame = pd.DataFrame(records)
    if sds_col in shown:
        _kosha_button(project, rows, wanted, stored, sds_col, cand_key, gen_key, candidates)
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
            "SDS 제2항 분류",
            "제품 SDS(물질안전보건자료) 2번 항목 '유해성·위험성'에 적힌 분류를 그대로 옮겨 적습니다. 위 KOSHA 버튼으로 후보를 불러올 수 있습니다. 해당 분류가 없으면 '별표1 해당없음'."),
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
        cas = str(values["CAS No."]).strip()
        cand = candidates.get(cas)
        # 후보 문구를 그대로 둔 칸만 'KOSHA 후보 사용'으로 본다(고쳐 쓴 칸은 사용자가 직접 적은 값이다).
        if (sds_col in shown and cand is not None and cand.usable and result[number - 1].get(sds_col) == cand.text
                and not stored[number - 1].get(sds_col)):
            used[cas] = cand
    return result, used


def _kosha_button(project, rows, wanted, stored, sds_col, cand_key, gen_key, candidates) -> None:
    empty = []
    for number in wanted:
        cas = str(rows[number - 1].get("CAS No.") or rows[number - 1].get("CAS 번호") or "").strip()
        if cas and not stored[number - 1].get(sds_col) and cas not in candidates:
            empty.append(cas)
    help_text = ("CAS 번호만 KOSHA 물질안전보건자료 조회 서비스로 보내고, 제2항의 분류를 후보로 채웁니다. "
                 "참고자료이므로 제품 SDS와 대조해 확인해야 합니다.")
    if st.button("KOSHA에서 SDS 분류 후보 불러오기", key=f"judge_kosha_go_{project.project_id}", disabled=not empty,
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
        st.caption("판정은 " + step_line(0) + " 순서로 진행합니다. 답에 따라 필요한 단계만 나타납니다.")
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
        st.markdown("진행: " + step_line(current_step(outcome)))
        if outcome.status == "COMPOSITION":
            _composition_form(project, outcome)
        elif outcome.status == "INVALID":
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

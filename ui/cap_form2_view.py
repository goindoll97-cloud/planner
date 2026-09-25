from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

from engine.stage2 import cap_form2_workspace as f2
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.storage import save_project


def _column_config(columns: list[dict]) -> dict:
    config = {}
    for col in columns:
        if col.get("kind") == "choice":
            config[col["id"]] = st.column_config.SelectboxColumn(col["label"], help=col.get("help"), options=col["options"])
        else:
            config[col["id"]] = st.column_config.TextColumn(col["label"], help=col.get("help"))
    return config


def _render_change_guide() -> None:
    with st.expander("변경항목·변경종류·후속조치 작성 가이드"):
        st.markdown("**② 변경항목은 계획서에서 바뀐 세부 작성항목**을 적습니다. 법정 서식은 「화학물질관리법 시행규칙」 별표 4 「화학사고예방관리계획서의 작성 내용 및 방법」의 소분류를 쓰도록 하고 있습니다. 여러 항목이면 ` / `로 구분하세요.")
        st.caption("자주 쓰는 예: 장치·설비 목록 및 명세, 설비배치도, 유해화학물질 목록 및 명세, 공정배관계장도(P&ID), 고정식 유해감지시설 명세 및 배치도. 목록은 참고용이므로 정확한 소분류가 없으면 계획서 항목명을 직접 입력합니다.")
        st.markdown("**③ 변경의 종류는 현행 별지 제2호의 분류**입니다. 해당하는 항목을 하나 이상 적고, 여러 개면 ` / `로 구분합니다.")
        for label, explanation in f2.CHANGE_TYPE_GUIDANCE.items():
            st.markdown(f"- **{label}**: {explanation}")
        st.markdown("**④ 변경 내용은 변경 전과 변경 후가 분명하면 문장으로 적어도 됩니다.** 서식의 ‘변경전 → 변경후’는 비교할 내용을 쓰라는 뜻이며, 화살표 기호만 사용하라는 뜻은 아닙니다.")
        st.code("TK-101(용량 20 m³)을 철거하고 TK-201(용량 15 m³)을 설치함. 설비배치도 도면번호 P-101도 개정함.", language=None)
        st.markdown("**⑤ 후속조치는 서로 다른 절차를 함께 기록할 수 있습니다.** 예를 들어 계획서 변경제출과 영업허가 변경허가가 동시에 필요할 수 있습니다. 항목을 하나 이상 적고, 여러 개면 ` / `로 구분하세요.")
        for label, explanation in f2.FOLLOW_UP_GUIDANCE.items():
            st.markdown(f"- **{label}**: {explanation}")
        st.warning("현행 작성 규정 제11조는 총괄영향범위 확대 등 법정 요건에 해당하는 경우, 작성수준이 2군에서 1군으로 바뀌는 경우, 또는 화학물질안전원장이 주민소산계획 보완을 통지한 경우 등에 변경된 계획서 제출을 요구합니다. 통상 변경제출은 변경 완료 30일 전까지이며, 주민소산계획 보완 통지를 받은 경우는 통지일부터 60일 이내입니다. 해당 요건과 예외를 공식 규정으로 확인하세요. 변경신고·변경허가는 유해화학물질 영업허가 보유 여부와 시행규칙 제29조의 요건을 별도로 확인해야 합니다. 한 번의 변경에 계획서 제출과 영업허가 변경조치가 함께 적용될 수도 있습니다. 프로그램은 제출·허가 대상을 자동 판정하지 않습니다.")
        st.markdown(
            "공식 기준: [작성 등에 관한 규정 제11조(변경 제출)](https://www.law.go.kr/DRF/lawService.do?ID=2100000278102&OC=me_pr&mobileYn=Y&target=admrul&type=HTML) · "
            "[화학물질관리법 시행규칙 제29조](https://www.law.go.kr/LSW//lsSideInfoP.do?docCls=jo&joBrNo=00&joNo=0029&lsiSeq=279031&urlMode=lsScJoRltInfoR)"
        )


def _render_structured_change_entry(project) -> bool:
    existing_count = len(f2.change_log_rows(project))
    key_suffix = f"{project.project_id}_{existing_count}"
    added = False
    with st.expander("변경내역을 항목별로 입력해 행 추가", expanded=True):
        st.caption("입력한 값은 법정 서식의 각 열에 배치됩니다. 자동으로 문장을 해석하거나 법적 후속조치를 판정하지 않습니다.")
        date_value = st.text_input("① 변경일", placeholder="예: 2020. 1. 2.", key=f"cap_form02_add_date_{key_suffix}")
        selected_items = st.multiselect(
            "② 변경항목", f2.CHANGE_ITEM_SUGGESTIONS,
            key=f"cap_form02_add_items_{key_suffix}",
            help="자주 쓰는 계획서 세부 항목입니다. 여러 항목을 고를 수 있고, 목록에 없으면 아래 칸에 입력하세요.",
        )
        custom_item = st.text_input(
            "목록에 없는 변경항목 (선택)", key=f"cap_form02_add_item_custom_{key_suffix}"
        ).strip()
        item_value = " / ".join([*selected_items, *([custom_item] if custom_item else [])])
        change_types = st.multiselect(
            "③ 변경의 종류", f2.CHANGE_TYPES, key=f"cap_form02_add_types_{key_suffix}"
        )
        content_mode = st.radio(
            "④ 변경 내용 입력 방식", ["변경 전·후 비교", "문장으로 작성"], horizontal=True,
            key=f"cap_form02_add_mode_{key_suffix}",
        )
        if content_mode == "변경 전·후 비교":
            before_col, after_col = st.columns(2)
            before = before_col.text_input("변경 전", key=f"cap_form02_add_before_{key_suffix}")
            after = after_col.text_input("변경 후", key=f"cap_form02_add_after_{key_suffix}")
            content = f"{before.strip()} → {after.strip()}" if before.strip() and after.strip() else ""
        else:
            content = st.text_area(
                "변경 내용", placeholder="예: TK-101을 철거하고 TK-201을 설치함.",
                key=f"cap_form02_add_narrative_{key_suffix}",
            ).strip()

        actions = st.multiselect(
            "⑤ 후속조치", f2.FOLLOW_UPS, key=f"cap_form02_add_actions_{key_suffix}",
            help="계획서 조치와 영업허가 조치가 함께 해당할 수 있습니다. 해당없음은 다른 조치와 함께 선택하지 마세요. 아직 판단 중이면 비워 두고, 제출 전에는 확인해 입력하세요.",
        )
        action_dates = {}
        dated_actions = [action for action in actions if action != "해당없음"]
        if dated_actions:
            st.caption("실제로 조치한 날짜를 입력하세요. 아직 조치하지 않았거나 날짜를 확인 중이면 비워 둘 수 있습니다.")
            for action in dated_actions:
                action_dates[action] = st.text_input(
                    f"{action.split(' ', 1)[-1]} 일자 (선택)",
                    placeholder="예: 2020. 3. 7.",
                    key=f"cap_form02_add_action_date_{key_suffix}_{action}",
                )
        person = st.text_input("⑥ 담당자", key=f"cap_form02_add_person_{key_suffix}")
        submitted = st.button("변경내역 행 추가", type="primary", key=f"cap_form02_add_button_{key_suffix}")

        if submitted:
            errors = []
            if not date_value.strip():
                errors.append("변경일을 입력하세요.")
            if not item_value.strip():
                errors.append("변경항목을 입력하거나 선택하세요.")
            if not change_types:
                errors.append("변경의 종류를 하나 이상 선택하세요.")
            if not content:
                errors.append("변경 전·후 값 또는 변경 내용을 입력하세요.")
            if "해당없음" in actions and len(actions) > 1:
                errors.append("‘해당없음’은 다른 후속조치와 함께 선택할 수 없습니다.")
            if errors:
                for error in errors:
                    st.error(error)
            else:
                rows = f2.change_log_rows(project)
                rows.append({
                    "일자": date_value.strip(),
                    "변경항목": item_value.strip(),
                    "변경의 종류": " / ".join(change_types),
                    "변경 내용(변경전 → 변경후)": content,
                    "후속조치": f2.format_follow_up_actions(actions, action_dates),
                    "담당자": person.strip(),
                })
                f2.save_change_log(project, rows)
                save_project(project)
                st.session_state[f"cap_form02_added_notice_{project.project_id}"] = "변경내역을 법정 서식 표에 추가했습니다."
                added = True
    return added


def render(project) -> None:
    schema = ws.load_form_schema(2)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form02_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    current = f2.submission(project)

    if step["id"] == "submission":
        st.text_input("사업장명", value=current["company"], disabled=True,
                      help="판정진단에서 승계된 값입니다.")
        unit_plant = st.text_input(
            "단위공장명(또는 단위공정명)", value=current["unit_plant"], key=f"cap_form02_unit_{project.project_id}",
            help="별지 제3호의 단위공장명 칸에도 그대로 들어갑니다.",
        )
        types = [""] + list(f2.SUBMISSION_TYPES)
        submission_type = st.selectbox(
            "제출구분", types, index=types.index(current["type"]) if current["type"] in types else 0,
            key=f"cap_form02_type_{project.project_id}", help="별지 제3호의 제출구분 칸에도 그대로 들어갑니다.",
        )
        reasons = [""] + list(f2.SUBMISSION_REASONS)
        reason = st.selectbox(
            "제출 사유", reasons, index=reasons.index(current["reason"]) if current["reason"] in reasons else 0,
            key=f"cap_form02_reason_{project.project_id}",
        )
        if st.button("저장", type="primary", key=f"cap_form02_save_sub_{project.project_id}"):
            f2.save_submission(project, submission_type, reason, unit_plant)
            save_project(project)
            st.success("저장했습니다. 다른 서식의 같은 칸에도 반영됩니다.")
        state = f2.resolve_form2(project)
        (st.info if state.applies is None else st.success if state.applies else st.warning)(state.headline)

    elif step["id"] == "log":
        state = f2.resolve_form2(project)
        if state.applies is False:
            st.warning(state.headline + " 아래 표는 건너뛰어도 됩니다.")
        _render_change_guide()
        notice_key = f"cap_form02_added_notice_{project.project_id}"
        if st.session_state.pop(notice_key, None):
            st.success("변경내역을 법정 서식 표에 추가했습니다.")
        if _render_structured_change_entry(project):
            st.rerun()
        st.subheader("등록된 변경내역")
        st.caption("위 입력창에서 추가한 내역입니다. 세부 수정이나 행 삭제는 아래 표에서 할 수 있습니다.")
        columns = ws.section(2, "change_log")["columns"]
        ids = [c["id"] for c in columns]
        frame = pd.DataFrame(f2.change_log_rows(project), columns=ids)
        edited = st.data_editor(
            frame, column_config=_column_config(columns), num_rows="dynamic", width="stretch",
            key=f"cap_form02_log_{project.project_id}",
        )
        if st.button("변경내역 저장", type="primary", key=f"cap_form02_save_log_{project.project_id}"):
            rows = []
            for record in edited.to_dict("records"):
                cleaned = {}
                for key, value in record.items():
                    if value is None or (isinstance(value, float) and pd.isna(value)):
                        cleaned[key] = ""
                    else:
                        cleaned[key] = value
                rows.append(cleaned)
            saved = f2.save_change_log(project, rows)
            save_project(project)
            st.success(f"변경내역 {saved}건을 저장했습니다.")

    else:
        state = f2.resolve_form2(project)
        st.write(state.headline)
        for blocker in state.readiness.blockers:
            st.error(blocker)
        for message in state.readiness.messages:
            st.caption(message)
        with st.expander("별지 제2호에 채워지는 내용 미리보기", expanded=True):
            st.write(f"**사업장명**: {current['company'] or '-'}    **단위공장명**: {current['unit_plant'] or '-'}")
            if state.applies:
                frames.show(pd.DataFrame(f2.change_log_rows(project)), width="stretch", hide_index=True)
            else:
                st.caption("작성 대상이 아니어서 표는 비워 둡니다.")
        try:
            st.download_button(
                "화학사고예방관리계획서 규정서식 작성본 DOCX 다운로드",
                data=build_cap_baseline_draft(project), file_name=cap_baseline_filename(project),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"cap_form02_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")

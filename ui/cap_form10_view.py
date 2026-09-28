from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

from engine.stage2 import cap_form10_workspace as f10
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.cap_form10_engine import build_cap_form10_data
from engine.stage2.storage import save_project

READ_ONLY = ("구분기호", "장치·설비명", "설계용량(m3)")


def render(project) -> None:
    schema = ws.load_form_schema(10)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form10_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])
    if step["id"] == "capacity":
        st.info("**무엇을 적나요?** 필요용량은 해당 설비에 **확보해야 하는 양**, 유효용량은 방류벽·방지턱 등이 "
                "**실제로 담을 수 있는 양**입니다. 아래 표에서 설비별 필요용량과 근거를 적고, "
                "유효용량은 확인한 값을 적거나 안쪽 치수를 입력하세요. 저장하면 프로그램이 유효용량을 계산하고 "
                "두 용량을 비교해 ‘적정’ 또는 ‘부족’을 보여 줍니다.")
        with st.expander("필요용량 기준을 어디서 확인하나요?"):
            st.markdown(
                "1. **설비를 확인하세요.** 표의 설비번호로 시설 도면·설비목록에서 저장·제조·사용·보관 "
                "중 무엇인지, 취급물질과 설치·검사 자료를 확인합니다.\n"
                "2. **회사 자료를 먼저 찾으세요.** 방류벽·집수시설 설계도, 설치검사 자료, 기존 용량 계산서에 "
                "그 설비의 필요용량과 적용 기준이 기록돼 있는지 확인합니다.\n"
                "3. **기준이 없다면 적용 규정을 확인하세요.** 취급시설의 형태·물질 분류 등에 맞는 "
                "설치·관리 기준을 안전관리 담당자와 대조해 필요용량을 산정합니다. "
                "[「화학물질관리법 시행규칙」 별표 5](https://www.law.go.kr/LSW/lsInfoP.do?lsId=2006391), "
                "[「유해화학물질 제조·사용·저장시설 설치 및 관리에 관한 고시」](https://www.law.go.kr/admRulInfoP.do?admRulSeq=2100000269080), "
                "[「유해화학물질 보관시설 설치 및 관리에 관한 고시」](https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000269056)를 "
                "시설에 맞게 살펴보세요.\n"
                "4. **표에 옮기세요.** 설비별로 확인한 m³ 값은 ‘필요용량(m³)’에, 적용 기준의 항목·계산서 "
                "번호는 같은 행의 ‘필요용량 근거’에 적습니다. 기준을 찾지 못했다면 추측한 비율을 입력하지 말고 "
                "담당자에게 확인하세요."
            )

    rows = f10.edit_rows(project)
    current_rule = f10.rule(project)
    if not rows and step["id"] != "result":
        st.warning("별지 제1호에서 시설을 입력하면 이 서식의 설비 목록이 자동으로 채워집니다.")
        return

    if step["id"] in ("targets", "capacity"):
        ratio = current_rule["비율(%)"]
        basis = current_rule["근거"]
        if step["id"] == "capacity":
            if ratio:
                st.warning(f"현재 공통 비율 {ratio}%가 저장돼 있습니다. ‘필요용량(m³)’을 직접 입력하지 않은 "
                           "설비에 적용되므로, 각 설비에도 같은 기준이 맞는지 확인하세요.")
            with st.expander("같은 기준을 쓰는 설비만: 공통 비율로 계산 (선택)"):
                st.caption("각 설비의 기준 비율이 같다고 확인한 경우에만 사용하세요. 아래 표에 직접 입력한 "
                           "필요용량이 있으면 그 설비에는 직접 입력값을 사용합니다.")
                ratio = st.text_input("확인한 공통 비율: 설계용량 대비 (%)", value=ratio,
                                      key=f"cap_form10_ratio_{project.project_id}",
                                      help="확인된 비율을 입력하면 설계용량 × 비율 ÷ 100으로 필요용량을 계산합니다. "
                                           "예: 실제 적용기준이 120%로 확인된 설비의 설계용량이 10 m³면 12 m³. "
                                           "예시의 120%를 다른 설비에 그대로 적용하지 마세요.")
                basis = st.text_input("공통 비율의 적용 기준·계산서", value=basis,
                                      key=f"cap_form10_basis_{project.project_id}",
                                      help="여러 설비에 같은 비율을 적용할 수 있음을 확인한 기준의 이름·해당 항목 "
                                           "또는 계산서 번호를 적습니다.")
        columns = ("적용여부", "설비형태", "확산방지설비 종류") if step["id"] == "targets" else \
            ("확산방지설비 종류", *f10.COLUMN_IDS[3:])
        config = {name: st.column_config.TextColumn(name, disabled=True) for name in READ_ONLY}
        for column, label, help_text in f10.EDIT_COLUMNS:
            if column not in columns:
                continue
            if column == "적용여부":
                config[column] = st.column_config.SelectboxColumn(label, help=help_text, options=[f10.APPLICABLE, f10.NOT_APPLICABLE])
            elif column == "설비형태":
                config[column] = st.column_config.SelectboxColumn(label, help=help_text, options=list(f10.FACILITY_FORMS))
            elif column == "확산방지설비 종류":
                config[column] = st.column_config.SelectboxColumn(label, help=help_text, options=list(f10.CONTAINMENT_TYPES))
            else:
                config[column] = st.column_config.TextColumn(label, help=help_text)
        shown = [*READ_ONLY, *columns]
        frame = pd.DataFrame(rows)
        edited = st.data_editor(frame[shown], column_config=config, hide_index=True, width="stretch",
                                key=f"cap_form10_{step['id']}_{project.project_id}")
        if step["id"] == "capacity":
            st.caption("유효용량 계산: 내부 길이 × 내부 폭 × 유효높이 − 내부 차감용적. "
                       "차감할 부피가 없다고 확인했다면 0을 적으세요. "
                       "확인한 유효용량을 직접 입력했다면 그 값이 우선이고, 치수도 입력한 경우 서로 비교합니다.")
        if st.button("저장", type="primary", key=f"cap_form10_save_{step['id']}_{project.project_id}"):
            merged = []
            for original, new in zip(rows, edited.to_dict("records")):
                item = dict(original)
                item.update({k: ("" if pd.isna(v) else v) for k, v in new.items()})
                merged.append(item)
            f10.save(project, merged, ratio, basis)
            save_project(project)
            st.success("저장했습니다.")
            if step["id"] == "capacity":
                result = build_cap_form10_data(project)
                if result.rows:
                    st.write("**저장한 값의 계산 결과**")
                    preview = pd.DataFrame(result.rows)
                    columns = [col for col in ("구분기호", "장치·설비명", "필요용량", "유효용량", "검토결과")
                               if col in preview.columns]
                    frames.show(preview[columns], width="stretch", hide_index=True)
                if result.blockers:
                    st.warning("추가 확인이 필요한 항목")
                    for issue in result.blockers:
                        st.write(f"• {issue}")
    else:
        data = build_cap_form10_data(project)
        if data.rows:
            frames.show(pd.DataFrame(data.rows).drop(columns=["필요용량 근거", "유효용량 산정근거"], errors="ignore"),
                         width="stretch", hide_index=True)
        if data.blockers:
            st.warning("아직 필요한 정보")
            for item in data.blockers:
                st.write(f"• {item}")
        else:
            st.success("모든 칸이 채워졌습니다.")
        try:
            st.download_button(
                "화학사고예방관리계획서 규정서식 작성본 DOCX 다운로드",
                data=build_cap_baseline_draft(project), file_name=cap_baseline_filename(project),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"cap_form10_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")

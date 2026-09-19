from __future__ import annotations

"""표 서식·사실 표를 화면에서 입력하는 공용 화면 조각(적용 여부, 예시 미리 채움, 점검 안내 포함)."""

import pandas as pd
import streamlit as st

from engine.stage2 import psm_table_workspace as tables
from engine.stage2.storage import save_project
from ui import cap_frames as frames


def _reuse_note(text: str) -> None:
    st.success(text)


def grid(form_no: str):
    def render(project) -> None:
        spec = tables.SPECS[form_no]
        st.caption(spec.summary)
        if spec.conditional:
            decision, basis = tables.applicability(project, form_no)
            st.markdown("**이 서식을 작성해야 하나요?**")
            options = ["선택하세요", tables.APPLICABLE, tables.NOT_APPLICABLE]
            chosen = st.selectbox("적용 여부", options, index=options.index(decision) if decision in options else 0,
                                  key=f"psm_apply_{form_no}",
                                  help="이 서식은 해당하는 사업장만 작성합니다. 해당하지 않으면 '해당 없음'을 고르고 이유를 적으세요.")
            reason = st.text_input("확인 근거", value=basis, key=f"psm_apply_basis_{form_no}",
                                   help="왜 적용(또는 해당 없음)인지 한 줄로 적습니다. 예: 옥내 소화 설비 없음(옥외 시설만 있음)")
            if st.button("적용 여부 저장", key=f"psm_apply_save_{form_no}"):
                if chosen == "선택하세요" or not reason.strip():
                    st.warning("적용 여부와 확인 근거를 모두 적어야 저장됩니다.")
                else:
                    tables.save_applicability(project, form_no, chosen, reason)
                    save_project(project)
                    st.rerun()
            if decision == tables.NOT_APPLICABLE:
                st.success("이 서식은 '해당 없음'으로 확인되어 작성하지 않습니다.")
                return
            if decision != tables.APPLICABLE:
                st.info("적용 여부를 먼저 저장하면 표를 작성할 수 있습니다.")
                return
        st.caption("모르는 칸은 비워 두어도 저장됩니다. 비워 둔 칸은 아래에 안내됩니다.")
        if spec.seed_key and project.get_field(spec.key) is None and tables.seeded(project, form_no):
            _reuse_note("화학사고예방관리계획서에서 이미 입력한 내용을 미리 채웠습니다. 확인하고 저장하세요.")
        frame = pd.DataFrame(tables.rows(project, form_no), columns=spec.column_ids())
        config = {c.id: st.column_config.TextColumn(c.label, help=c.help) for c in spec.columns}
        edited = st.data_editor(frames.safe(frame), num_rows="dynamic", hide_index=True, width="stretch",
                                key=f"psm_grid_{form_no}", column_config=config)
        if st.button("저장", type="primary", key=f"psm_grid_save_{form_no}"):
            count = tables.save(project, form_no, edited.to_dict("records"))
            save_project(project)
            st.success(f"{count}행을 저장했습니다.")
            st.rerun()
        needs = tables.needs(project, form_no)
        if needs:
            st.info("저장된 표에서 더 필요한 것")
            for item in needs:
                st.write(f"• {item}")
        else:
            st.success("이 서식의 필수 칸이 모두 채워졌습니다.")
    return render

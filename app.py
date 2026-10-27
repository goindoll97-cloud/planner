from __future__ import annotations

import streamlit as st

from engine.stage2.cap_final_form_runtime import install_cap_final_form_runtime


# Stage 2 final output is DOCX-only. Keep only the CAP DOCX formatting runtime
# for checkbox/choice rendering; HWPX template loading/conversion is not
# installed during ordinary app startup.
install_cap_final_form_runtime()

# 화학사고예방관리계획서는 별지 순서대로 한 화면에서 작성한다. 엑셀 통합 작성자료 가져오기도 그 화면 안에 들어 있어
# 예전의 3~5단계 화면(엑셀 왕복 방식)은 화학사고예방관리계획서에는 더 이상 쓰이지 않는다.
sections: dict[str, list] = {
    "사업장 업무": [st.Page("ui/evidence_workspace_page.py",title="자료 접수·확인할 일",icon="📂",default=True),
                # 버전은 작성 화면이 아니라 사업장 작성자료 전체의 스냅샷이라 따로 둔다(작성 화면을 바꿔도 남음).
                st.Page("ui/version_page.py", title="버전 관리", icon="🕘")],
    # 예전 한 화면(별지 15개·서술형·내보내기·제출서식)을 하는 일별로 나눈 화면들. 내용은 ui/cap_common.py의 GROUPS.
    "화학사고예방관리계획서": [
        st.Page("ui/cap_facts_page.py", title="사업장·물질·시설 작성", icon="🏷️"),
        st.Page("ui/cap_scenario_page.py", title="사고시나리오·위험도", icon="🔥"),
        st.Page("ui/cap_emergency_page.py", title="비상대응·서술형", icon="🚨"),
        st.Page("ui/cap_export_page.py", title="점검·내보내기", icon="📤"),
        st.Page("ui/cap_submission_page.py", title="제출·변경·이행점검", icon="📮"),
    ],
}

# 두 문서 모두 작성 화면의 "새 사업장으로 시작하기"에서 법정 대상 판정까지 끝낸다. 공정안전보고서는 화학사고예방관리계획서에서
# 이미 입력한 사실을 재사용하는 새 화면에서 작성한다. 예전 3~5단계(엑셀 왕복 방식)는 메뉴에서 뺐다.
sections["공정안전보고서"] = [st.Page("ui/psm_workspace_page.py", title="공정안전보고서 작성", icon="🏭")]

# 사업장 판정: 물질 목록(엑셀·CSV 가능)을 넣고 질문에 답하면 판정하고 작성으로 이어진다(예전 판정진단·작성범위 선택을 합친 화면).
sections["사업장 판정"] = [st.Page("ui/judgement_page.py", title="사업장 판정하기", icon="✅")]

sections["참고"] = [
    st.Page("ui/regdb_page.py", title="규정 DB 관리", icon="🗂️"),
    st.Page("ui/legal_evidence_page.py", title="법령·근거 라이브러리", icon="📚"),
]

st.navigation(sections).run()

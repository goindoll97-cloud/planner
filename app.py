from __future__ import annotations

import streamlit as st


pages = [
    st.Page("ui/diagnosis_entry.py", title="1. 판정진단", icon="✅", default=True),
    st.Page("ui/stage2_scope_page.py", title="2. 작성범위 선택", icon="🧭"),
    st.Page("ui/stage2_intake_page.py", title="3. 자료준비·접수", icon="📥"),
    st.Page("ui/stage2_validation_page.py", title="4. 작성자료 교차검증", icon="🔎"),
    st.Page("ui/stage2_review_page.py", title="5. 작성·검토", icon="📝"),
    st.Page("ui/regdb_page.py", title="6. 규정 DB 관리", icon="🗂️"),
    st.Page("ui/legal_evidence_page.py", title="7. 법령 근거", icon="📚"),
]

st.navigation(pages).run()

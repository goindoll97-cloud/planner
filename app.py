from __future__ import annotations

import streamlit as st

from engine.stage2.storage import load_project
from engine.stage2.workflow import intake_confirmed, validation_confirmed


ACTIVE_PROJECT_KEY = "_stage2_active_project_id"


def _stage2_progress() -> tuple[bool, bool]:
    project_id = str(st.session_state.get(ACTIVE_PROJECT_KEY) or "").strip()
    if not project_id:
        return False, False
    try:
        project = load_project(project_id)
    except Exception:
        return False, False
    return intake_confirmed(project), validation_confirmed(project)


intake_ready, validation_ready = _stage2_progress()

pages = [
    st.Page("ui/diagnosis_entry.py", title="1. 판정진단", icon="✅", default=True),
    st.Page("ui/stage2_scope_page.py", title="2. 작성범위 선택", icon="🧭"),
    st.Page("ui/stage2_intake_page.py", title="3. 통합 작성자료", icon="📥"),
]

# Keep a novice user on the intended sequence. Stage 4 appears only after the
# company confirms that the text/table source material in Stage 3 is ready.
if intake_ready:
    pages.append(st.Page("ui/stage2_validation_page.py", title="4. 작성자료 교차검증", icon="🔎"))
if validation_ready:
    pages.append(st.Page("ui/stage2_review_page.py", title="5. 작성·검토", icon="📝"))

# These are reference/administration tools rather than sequential workflow
# stages. Keep them always available, but do not number them so hidden Stage 4
# or Stage 5 does not make the navigation look broken to a new user.
pages.extend(
    [
        st.Page("ui/regdb_page.py", title="규정 DB 관리", icon="🗂️"),
        st.Page("ui/legal_evidence_page.py", title="법령·근거 라이브러리", icon="📚"),
    ]
)

st.navigation(pages).run()

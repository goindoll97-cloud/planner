from __future__ import annotations

import streamlit as st

from engine.stage2.ai_live_progress_runtime import install_ai_live_progress_runtime
from engine.stage2.ai_response_runtime import install_ai_response_runtime
from engine.stage2.cap_fragment_runtime import install_cap_fragment_runtime
from engine.stage2.cap_multi_form_runtime import install_cap_multi_form_runtime
from engine.stage2.cap_template_priority import install_current_cap_template_priority
from engine.stage2.local_ai_resilience import install_local_ai_resilience
from engine.stage2.storage import load_project
from engine.stage2.workflow import intake_confirmed, validation_confirmed


ACTIVE_PROJECT_KEY = "_stage2_active_project_id"

# The current approved law.go.kr CAP form is the layout authority. An older
# project-specific template remains only as a fallback while no CURRENT central
# legal template is available.
install_current_cap_template_priority()

# law.go.kr may publish CAP appendices as several approved HWP/HWPX files rather
# than one monolithic file. Treat the CURRENT approved set as one official form
# bundle, fill each original independently, and package the written forms as ZIP.
install_cap_multi_form_runtime()
# Split official files intentionally contain only some statutory form markers.
# Relax the monolithic validation only inside the approved split-form writer and
# suppress pyhwpx's local DLL-path diagnostic noise during HWP conversion.
install_cap_fragment_runtime()

# Local 14B models can be healthy yet exceed the old 180-second single-request
# limit when many report items are sent at once. Install small-batch generation,
# longer local read timeouts, bounded output, checkpoint saves and Ollama
# non-thinking mode before Streamlit imports the selected Stage 2 page.
install_local_ai_resilience()

# Local models may return equivalent JSON with `items`, `sentences`, a keyed
# object, or a direct one-item object instead of the exact `drafts` array. Keep
# validation strict on requirement keys/facts, but tolerate those harmless
# response-shape differences.
install_ai_response_runtime()
# Surface each local-AI item immediately instead of leaving the page at 0/N
# during the first multi-item model call. Grounding/validation stays unchanged.
install_ai_live_progress_runtime()


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
# company confirms that the source material in Stage 3 is ready.
if intake_ready:
    pages.append(st.Page("ui/stage2_validation_page.py", title="4. 작성자료 점검·보완", icon="🔎"))
if validation_ready:
    pages.append(st.Page("ui/stage2_review_page.py", title="5. 보고서 작성", icon="📝"))

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

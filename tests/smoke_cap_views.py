"""수동 스모크 점검: 화학사고예방관리계획서 작성 화면의 모든 별지 × 모든 단계를 실제 Streamlit 런타임으로 렌더링한다.

실행: PYTHONPATH=. python tests/smoke_cap_views.py [프로젝트ID]
(저장된 작성 프로젝트가 있어야 한다. 예외가 나는 화면이 있으면 종료 코드 1.)
"""

import sys

from streamlit.testing.v1 import AppTest

from engine.stage2 import cap_workspace as ws
from ui import cap_forms_registry as registry


def main(project_id: str) -> int:
    failures = 0
    for number in registry.FORM_NUMBERS:
        titles = [step["title"] for step in ws.load_form_schema(number)["steps"]]
        if number == 1:
            titles.append("5. 서식 내보내기")
        step_key = "cap_form01_step" if number == 1 else f"cap_form{number:02d}_step"
        for title in titles:
            app = AppTest.from_file("ui/cap_workspace_page.py", default_timeout=90)
            app.session_state["_stage2_active_project_id"] = project_id
            app.session_state["cap_form_no"] = number
            app.session_state[step_key] = title
            app.run()
            errors = [str(e.value)[:200] for e in app.exception]
            print(("OK  " if not errors else "FAIL"), registry.label(number), title, errors[:1])
            failures += bool(errors)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "S2-FORM1"))

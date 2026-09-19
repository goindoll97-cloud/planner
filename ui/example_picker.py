from __future__ import annotations

"""예시에서 고르거나 직접 쓰는 입력칸. 예시를 눌러도 저장되지 않고, 입력칸에 채워질 뿐이다(사용자가 저장해야 회사 사실이 된다)."""

import streamlit as st

from engine.stage2 import narrative_examples as examples
from ui import unsaved_guard


def _use(key: str, text: str) -> None:
    st.session_state[key] = text


def text_with_examples(label: str, key: str, *, value: str = "", help_text: str = "", choices: list[str] | None = None,
                       long: bool = False, template: str = "", checks: list[str] | None = None) -> str:
    if key not in st.session_state:
        st.session_state[key] = value
    unsaved_guard.baseline(key, value)  # 저장된 값이 기준이다. 예시를 골라 채우거나 고치면 '저장하지 않은 변경'이 된다.
    widget = st.text_area if long else st.text_input
    text = widget(label, key=key, help=help_text or None)
    if template:
        st.caption("문장 틀: " + template)
    if choices:
        with st.expander("예시에서 고르기 (고른 뒤 고쳐 쓸 수 있습니다)"):
            for index, sample in enumerate(choices):
                left, right = st.columns([6, 1])
                left.write(examples.labelled(sample))
                right.button("사용", key=f"{key}__ex{index}", on_click=_use, args=(key, examples.labelled(sample)))
            st.caption(examples.notice() + " 고른 문구 앞의 '(예시)' 표시는 우리 회사 내용으로 고친 뒤 지워야 저장됩니다.")
    if checks:
        st.caption("확인할 점: " + " / ".join(checks))
    return text

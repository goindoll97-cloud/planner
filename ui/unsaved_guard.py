from __future__ import annotations

"""저장하지 않은 입력이 있는 채로 다른 별지로 넘어가 내용이 사라지는 일을 막는다.

화면 프레임워크(Streamlit)는 화면에서 사라진 입력칸의 값을 버린다. 그래서 별지를 고르는 목록(selector)과 그 아래 화면을
한 묶음으로 다룬다. 평소에는 아무것도 보여 주지 않고, 저장 버튼의 위치와 동작도 바꾸지 않는다.

- 화면 안의 입력 위젯(텍스트·표·선택 등)을 기록해, 처음 값(저장된 값)과 달라진 곳이 있는지 알아낸다.
- 저장하지 않은 채 다른 별지를 고르면 이동하지 않고 원래 화면을 유지한 채 선택을 묻는다(계속 편집 / 저장하지 않고 이동).
  화면의 '저장' 버튼을 누르면 다시 그려질 때 변경이 없는 것으로 판정되어 고른 별지로 이동한다.

기록은 스레드별로만 하므로 다른 사용자의 화면에 영향을 주지 않는다.
"""

import threading
from typing import Any, Callable

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

_local = threading.local()
_FLAG = "_planner_unsaved_guard_installed"
TRACKED = ("text_input", "text_area", "selectbox", "checkbox", "toggle", "data_editor", "number_input")
# 저장하는 값이 아닌 화면 조작용 위젯(별지·단계 선택, AI 설정, 계산용 임시 입력)은 변경으로 보지 않는다.
IGNORE_KEY_PARTS = ("form_no", "form01_step", "_llm_", "psm19_", "cap_start_")


class Tracker:
    def __init__(self, key: str, chosen: Any, accepted: Any, slot) -> None:
        self.key, self.chosen, self.accepted, self.slot = key, chosen, accepted, slot
        self.dirty: dict[str, str] = {}
        self.baselines: dict[str, str] = {}
        self.bases: dict[str, tuple[str, Any]] = {}  # ident -> (종류, 저장된(처음) 값)
        self.seen = 0


def _norm_frame(data: Any) -> pd.DataFrame:
    frame = pd.DataFrame(data).reset_index(drop=True)
    return frame.astype(object).where(frame.notna(), "").astype(str)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _ignored(key: Any) -> bool:
    return isinstance(key, str) and any(part in key for part in IGNORE_KEY_PARTS)


def _record(name: str, args: tuple, kwargs: dict, value: Any) -> None:
    tracker = getattr(_local, "tracker", None)
    if tracker is None:
        return
    key = kwargs.get("key")
    if _ignored(key):
        return
    tracker.seen += 1
    ident = str(key) if key is not None else f"{name}#{tracker.seen}"
    label = str(kwargs.get("label") if "label" in kwargs else (args[0] if args and isinstance(args[0], str) else name))
    changed = False
    try:
        if name in ("text_input", "text_area"):
            default = tracker.baselines.get(ident, kwargs.get("value", args[1] if len(args) > 1 else ""))
            tracker.bases[ident] = ("text", _text(default))
            changed = _text(value) != _text(default)
        elif name in ("checkbox", "toggle"):
            default = kwargs.get("value", args[1] if len(args) > 1 else False)
            tracker.bases[ident] = ("bool", bool(default))
            changed = bool(value) != bool(default)
        elif name == "number_input":
            if "value" in kwargs:
                changed = _text(value) != _text(kwargs["value"])
        elif name == "selectbox":
            options = list(kwargs.get("options", args[1] if len(args) > 1 else []))
            index = kwargs.get("index", args[2] if len(args) > 2 else 0)
            default = options[index] if options and index is not None and 0 <= index < len(options) else None
            tracker.bases[ident] = ("raw", default)
            changed = value != default
        elif name == "data_editor":
            source = kwargs.get("data", args[0] if args else None)
            if isinstance(source, pd.DataFrame) and isinstance(value, pd.DataFrame):
                tracker.bases[ident] = ("editor", None)
                changed = not _norm_frame(source).equals(_norm_frame(value))
    except Exception:
        changed = False  # 비교할 수 없는 위젯은 변경으로 세지 않는다(거짓 경고보다 낫다)
    if changed:
        tracker.dirty[ident] = label


def _wrap_function(name: str, original: Callable) -> Callable:
    def wrapper(*args, **kwargs):
        value = original(*args, **kwargs)
        _record(name, args, kwargs, value)
        return value

    wrapper.__wrapped__ = original  # type: ignore[attr-defined]
    return wrapper


def _wrap_method(name: str, original: Callable) -> Callable:
    def wrapper(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        _record(name, args, kwargs, value)
        return value

    wrapper.__wrapped__ = original  # type: ignore[attr-defined]
    return wrapper


def install() -> None:
    """추적용 래퍼를 한 번만 설치한다. 추적 중이 아닐 때는 그대로 통과시킨다."""
    if getattr(st, _FLAG, False):
        return
    for name in TRACKED:
        if hasattr(st, name):
            setattr(st, name, _wrap_function(name, getattr(st, name)))
        if hasattr(DeltaGenerator, name):
            setattr(DeltaGenerator, name, _wrap_method(name, getattr(DeltaGenerator, name)))
    setattr(st, _FLAG, True)


def baseline(key: str, value: Any) -> None:
    """세션 상태로 값을 미리 채우는 입력칸의 저장된 값을 알린다(예: 예시 고르기 입력칸)."""
    tracker = getattr(_local, "tracker", None)
    if tracker is not None:
        tracker.baselines[key] = _text(value)


def dirty_fields() -> list[str]:
    tracker = getattr(_local, "tracker", None)
    return list(tracker.dirty.values()) if tracker is not None else []


def _dirty_from_state(bases: dict) -> list[str]:
    """화면을 그리기 전에, 직전 화면 입력칸의 현재 값(저장 전 포함)이 저장된 값과 다른지 본다.
    화면을 다시 그리지 않고도 판단하므로, 입력 직후 곧바로 별지를 바꿔도 놓치지 않는다."""
    changed = []
    for ident, (kind, default) in bases.items():
        if ident not in st.session_state:
            continue
        current = st.session_state[ident]
        try:
            if kind == "text":
                different = _text(current) != default
            elif kind == "bool":
                different = bool(current) != default
            elif kind == "editor":
                different = isinstance(current, dict) and any(current.get(k) for k in ("edited_rows", "added_rows", "deleted_rows"))
            else:
                different = current != default
        except Exception:
            different = False
        if different:
            changed.append(ident)
    return changed


def _stay(select_key: str, accepted: Any) -> None:
    st.session_state[select_key] = accepted


def _go(accepted_key: str, chosen: Any) -> None:
    st.session_state[accepted_key] = chosen


def selector(label: str, options: list, *, key: str, format_func: Callable | None = None) -> Any:
    """별지 선택 목록. 화면에 그려야 할 별지(저장하지 않은 변경이 있으면 원래 별지)를 돌려준다. finish()를 꼭 부른다."""
    install()
    kwargs = {"format_func": format_func} if format_func else {}
    chosen = st.selectbox(label, options, key=key, **kwargs)
    accepted_key = f"{key}__accepted"
    if st.session_state.get(accepted_key) not in options:
        st.session_state[accepted_key] = chosen
    accepted = st.session_state[accepted_key]
    # 직전 화면에 저장하지 않은 변경이 없다면 바로 고른 별지를 그린다(다시 그리기 없이 이동).
    if chosen != accepted and not _dirty_from_state(st.session_state.get(f"{key}__bases", {})):
        st.session_state[accepted_key] = accepted = chosen
    slot = st.empty()
    _local.tracker = Tracker(key, chosen, accepted, slot)
    return accepted


def finish() -> None:
    """화면을 다 그린 뒤 부른다. 변경 여부를 알리고, 필요하면 이동을 허락하거나 묻는다."""
    tracker: Tracker | None = getattr(_local, "tracker", None)
    _local.tracker = None
    if tracker is None:
        return
    accepted_key = f"{tracker.key}__accepted"
    dirty = list(tracker.dirty.values())
    st.session_state[f"{tracker.key}__bases"] = tracker.bases
    if tracker.chosen != tracker.accepted:
        if not dirty:
            # 직전 판정이 오래된 경우(방금 저장한 경우 등): 변경이 없으니 고른 별지로 이동한다.
            st.session_state[accepted_key] = tracker.chosen
            st.rerun()
            return
        with tracker.slot.container():
            st.warning("다른 별지로 이동하려고 하지만, 지금 화면에 **저장하지 않은 내용**이 있습니다: "
                       + ", ".join(dict.fromkeys(dirty)) + ". 이동하면 이 내용은 사라집니다. "
                       "저장하려면 이 화면의 '저장' 버튼을 누르세요(저장하면 고른 별지로 이동합니다).")
            left, right = st.columns(2)
            left.button("계속 편집", key=f"{tracker.key}__stay", type="primary", on_click=_stay,
                        args=(tracker.key, tracker.accepted))
            right.button("저장하지 않고 이동", key=f"{tracker.key}__go", on_click=_go, args=(accepted_key, tracker.chosen))
        return

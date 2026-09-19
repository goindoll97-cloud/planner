from __future__ import annotations

"""표 표시 도우미: 숫자와 빈 문자열이 섞인 열을 Arrow가 변환하지 못해 나는 경고를 막는다."""

import pandas as pd
import streamlit as st


def _text(value: object) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value)


def safe(data):
    """object 열은 문자열로 바꿔 Arrow 직렬화가 항상 성공하게 한다(숫자 열은 그대로)."""
    if not isinstance(data, pd.DataFrame):
        return data
    frame = data.copy()
    for column in frame.columns:
        if frame[column].dtype == object:
            frame[column] = frame[column].map(_text)
    return frame


def show(data, **kwargs) -> None:
    st.dataframe(safe(data), **kwargs)

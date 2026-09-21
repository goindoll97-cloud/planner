from __future__ import annotations

"""회사가 가진 물질 목록(엑셀·CSV)을 올려 화학물질 목록에 추가하는 화면 조각.

올리면 바로 저장하지 않고 열 맞춤과 미리보기를 보여 주고, 오류가 없는 행만 사용자가 눌러서 추가한다.
추가하는 방법(시작하기의 입력 표에 넣기 / 프로젝트 목록에 합치기)은 add_rows 콜백이 정한다.
"""

import hashlib
from typing import Callable

import pandas as pd
import streamlit as st

from engine.stage2 import cap_chemical_upload as up
from ui import cap_frames as frames

NONE = "(사용 안 함)"
LABELS = {"제품명": "제품명(물질명)", "CAS No.": "CAS 번호", "함량(%)": "함량(%)", "혼합물 여부": "단일물질/혼합물", "최대 동시보유량(ton)": "최대 보유량",
          "성상": "성상(기체·액체·고체)", "상온·상압 액체 여부(해당 시)": "상온·상압 액체 여부(별도 열)", "최대 제조·사용량": "최대 제조·사용량",
          "최대 저장량": "최대 저장량", "최대보유량 법정 산정 여부": "최대보유량 법정 산정 여부",
          "SDS 제2항 유해성·위험성 분류(선택 입력)": "SDS 제2항 분류",
          "단위": "단위(별도 열이 있을 때)", "비고": "비고"}


def render(prefix: str, *, existing: tuple[set[str], set[str]],
           add_rows: Callable[[list[dict], str, str], str]) -> None:
    """add_rows(정상 행 목록, 파일 이름, SHA-256) -> 사용자에게 보여 줄 결과 문장."""
    message_key = f"{prefix}_message"
    done = st.session_state.pop(message_key, None)
    with st.expander("엑셀·CSV로 물질 목록 올리기", expanded=bool(done)):
        if done:
            st.success(done)
        st.caption("회사가 이미 가진 물질 목록 파일을 올리면 열 이름을 알아서 맞춥니다. 올린 뒤 미리보기에서 확인하고, "
                   "이상 없는 행만 추가됩니다. 이미 목록에 있는 물질은 건너뜁니다.")
        st.download_button("빈 양식 내려받기(엑셀)", data=up.blank_template(), file_name="물질목록_양식.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key=f"{prefix}_template")
        upload = st.file_uploader("물질 목록 파일(.xlsx 또는 .csv)", type=["xlsx", "xlsm", "csv"], key=f"{prefix}_file")
        if upload is None:
            return
        try:
            parsed = up.parse(upload.getvalue(), upload.name)
        except Exception as exc:
            st.error(f"파일을 읽지 못했습니다: {exc}")
            return
        columns = list(parsed.frame.columns)
        st.write(f"**{len(parsed.frame)}행**을 읽었습니다. 열이 맞게 연결됐는지 확인하세요.")
        mapping: dict[str, str] = {}
        cols = st.columns(3)
        # 신규 사용자에게는 5개 기본 열만 보여 준다. 과거 파일의 함량·성상 등은
        # 자동 인식하여 보존하되, 필요할 때만 '추가 열 매핑'을 펼쳐 수정한다.
        for index, target in enumerate(up.OUT_COLUMNS):
            options = [NONE, *columns]
            guess = parsed.mapping.get(target)
            picked = cols[index % 3].selectbox(LABELS[target], options, index=options.index(guess) if guess in options else 0,
                                               key=f"{prefix}_map_{target}_{parsed.sha256[:8]}")
            if picked != NONE:
                mapping[target] = picked
        advanced = [target for target in LABELS if target not in up.OUT_COLUMNS]
        for target in advanced:
            guess = parsed.mapping.get(target)
            if guess in columns:
                mapping[target] = guess
        if st.checkbox("기존 파일의 함량·성상 등 추가 열 매핑을 확인/수정", key=f"{prefix}_advanced_{parsed.sha256[:8]}"):
            extra_cols = st.columns(3)
            for index, target in enumerate(advanced):
                options = [NONE, *columns]
                guess = mapping.get(target)
                picked = extra_cols[index % 3].selectbox(
                    LABELS[target], options, index=options.index(guess) if guess in options else 0,
                    key=f"{prefix}_map_{target}_{parsed.sha256[:8]}",
                )
                if picked == NONE:
                    mapping.pop(target, None)
                else:
                    mapping[target] = picked
        if "제품명" not in mapping and "CAS No." not in mapping:
            st.warning("제품명 또는 CAS 번호 열을 하나는 연결해야 합니다.")
            return
        sig = hashlib.sha1(repr(sorted(mapping.items())).encode("utf-8")).hexdigest()[:8]  # 열 맞춤이 바뀌면 미리보기를 새로 그린다
        raw = [r for r in up.normalize(parsed, mapping) if r["제품명"] or r["CAS No."] or r["함량(%)"]]  # 빈 줄은 뺀다
        rows = up.group_products(raw)  # 혼합물은 성분 줄을 제품 하나로 묶는다
        checked = up.check_rows(rows, *existing)
        preview_columns = [c for c in up.OUT_COLUMNS if c != up.SDS_CLASS_COLUMN]
        base = pd.DataFrame([{k: r.get(k, "") for k in preview_columns} for r in checked.rows], columns=preview_columns)
        st.caption("제품 단위로 보여 줍니다. 혼합물은 성분 줄이 한 제품으로 묶이고 성분은 아래에 따로 나옵니다. SDS 분류 등 나머지 정보는 자동으로 보존됩니다.")
        edited = st.data_editor(frames.safe(base), hide_index=True, width="stretch", num_rows="fixed",
                                key=f"{prefix}_preview_{parsed.sha256[:8]}_{sig}")
        memo = {i: rows[i].get("메모", "") for i in range(len(rows))}
        carried = (*up.EXTRA_COLUMNS, up.SDS_CLASS_COLUMN, "_components", "_component_problems")
        edited_rows = []
        for i, rec in enumerate(edited.to_dict("records")):
            hidden = {k: checked.rows[i].get(k, "") for k in carried}
            edited_rows.append({**hidden, **rec, "메모": memo.get(i, "")})
        final = up.check_rows(edited_rows, *existing)
        good = [r for r in final.rows if r["_ok"]]
        parts = [{"제품": r["제품명"], "성분 CAS No.": c["CAS No."], "함량(%)": c["함량(%)"]} for r in final.rows for c in r["_components"]]
        if parts:
            st.markdown("**혼합물 성분(파일에서 읽은 것)**")
            frames.show(pd.DataFrame(parts), width="stretch", hide_index=True)
        mixtures_ok = True
        if any(r["_components"] for r in good):
            mixtures_ok = st.checkbox("혼합물 성분의 CAS No.와 함량(%)을 제품 SDS 제3항과 대조해 확인했습니다.",
                                      key=f"{prefix}_sds_ok_{parsed.sha256[:8]}_{sig}")
        c1, c2, c3 = st.columns(3)
        c1.metric("추가할 수 있음", len(good))
        c2.metric("확인 필요(경고)", sum(1 for r in final.rows if r["_ok"] and not r["확인"].startswith("✅")))
        c3.metric("추가되지 않음(오류·중복)", len(final.rows) - len(good))
        frames.show(pd.DataFrame([{k: r[k] for k in ("제품명", "CAS No.", "확인")} for r in final.rows]),
                    width="stretch", hide_index=True)
        if good and st.button(f"정상 {len(good)}건 추가", type="primary", key=f"{prefix}_add", disabled=not mixtures_ok):
            st.session_state[message_key] = add_rows(good, upload.name, parsed.sha256)
            st.rerun()
        if not good:
            st.info("추가할 수 있는 행이 없습니다. 위 확인 결과의 ❌ 사유를 고친 뒤 다시 올려 주세요.")

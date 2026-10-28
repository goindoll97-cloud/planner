from __future__ import annotations

"""로컬 AI 설정과 AI 초안 진행 표시 부품.

예전에는 서술형 사실을 화면에서 적는 화면(render)이 여기 있었지만, 이제 사실은 회사 파일에서 읽으므로 없앴습니다
(engine/stage2/cap_fact_drafting.py가 파일 사실로 초안을 씀). 로컬 AI 설정(_local_config)과 진행 표시, 예전 AI 초안 확인 부품만 남깁니다.
위젯 키는 f"{prefix}_..." 형태다.
"""

import streamlit as st

from engine.stage2 import narrative_examples as examples
from engine.stage2 import psm_narrative_workspace as narrative
from engine.stage2.storage import save_project


def _local_config(prefix: str):
    from engine.stage2.local_ai_resilience import build_local_llm_client, local_llm_config_from_sources
    from engine.stage2.local_llm import DEFAULT_MODEL, LocalLLMConfig, probe_local_llm_runtime, validate_local_base_url

    try:
        base = local_llm_config_from_sources({})
    except Exception:
        base = LocalLLMConfig()
    with st.expander("AI 설정 · 필요한 경우만"):
        st.caption("회사 정보는 외부로 보내지 않습니다. 이 PC의 Ollama 같은 로컬 AI만 사용합니다.")
        model = st.text_input("로컬 모델 이름", value=base.model or DEFAULT_MODEL, key=f"{prefix}_llm_model")
        url = st.text_input("로컬 AI 주소", value=base.base_url, key=f"{prefix}_llm_url")
    try:
        config = LocalLLMConfig(provider=base.provider, model=model.strip() or DEFAULT_MODEL,
                                base_url=validate_local_base_url(url), timeout_seconds=base.timeout_seconds,
                                max_output_tokens=base.max_output_tokens)
        return config, probe_local_llm_runtime(config), build_local_llm_client
    except Exception as exc:
        st.warning(str(exc))
        return None, None, None


BADGES = {"초안 있음": "AI 초안 · 확인 전", "확인 완료": "AI 작성 · 담당자 확인 완료"}


def state_label(item: dict) -> str:
    """AI가 쓴 글이 들어 있는 항목은 상태 옆에 AI 작성 표시를 붙인다(사람이 나중에 다시 점검하도록)."""
    return BADGES.get(item["state"], item["state"]) if item.get("text") else item["state"]


def progress_lines(info: dict) -> tuple[float, str]:
    """진행 정보를 (진행률, 안내 문장)으로 바꾼다. 한 묶음이 끝날 때마다 갱신된다."""
    done, total = info["done"], max(info["total"], 1)
    elapsed = int(info["elapsed"])
    if info["event"] == "start":
        names = ", ".join(info["labels"][:3]) + (" 외" if len(info["labels"]) > 3 else "")
        return done / total, f"{done + 1}/{total}번째 묶음을 만드는 중 ({names}) · 경과 {elapsed}초 · 한 묶음에 수십 초가 걸릴 수 있습니다"
    if info["event"] == "retry":
        return 1.0, f"저장하지 못한 초안을 다시 만드는 중 ({', '.join(info['labels'])}) · 경과 {elapsed}초"
    return done / total, f"{done}/{total}번째 묶음 완료 · 초안 {info['generated']}개 · 저장 안 함 {info['rejected']}개 · 경과 {elapsed}초"


def _generate_with_progress(project, profile, prefix: str, client, model: str) -> None:
    import time

    box = st.status(f"확정된 사실로 초안을 만드는 중입니다 ({model})", expanded=True)
    bar = box.progress(0.0, text="준비 중입니다.")
    started = time.monotonic()

    def show(info: dict) -> None:
        ratio, text = progress_lines(info)
        bar.progress(min(max(ratio, 0.0), 1.0), text=text)

    try:
        result = narrative.generate(project, client, profile=profile, progress=show)
        save_project(project)
        st.session_state[f"{prefix}_rejected"] = narrative.rejected_rows(result)
        note = ("success", f"초안 만들기 완료 · {int(time.monotonic() - started)}초 · 초안 {len(result.generated)}개 ({model})")
        box.update(label=note[1], state="complete")
    except Exception as exc:
        note = ("error", f"초안을 만들지 못했습니다: {type(exc).__name__}: {exc}")
        box.update(label="초안을 만들지 못했습니다", state="error")
    st.session_state[f"{prefix}_run_note"] = note  # 화면을 다시 그려도 결과가 남도록 세션에 둔다


def _drafts(project, profile, prefix: str) -> None:
    items = narrative.item_status(project, profile)
    ready = [i for i in items if i["state"] == "초안 만들기 가능"]
    config, probe, build_client = _local_config(prefix)
    if ready:
        st.write(f"초안을 만들 수 있는 항목 {len(ready)}개: " + ", ".join(i["label"] for i in ready))
        runtime_ok = probe is not None and probe.ready
        if not runtime_ok and probe is not None:
            from engine.stage2.local_llm import local_runtime_not_ready_message
            st.warning(local_runtime_not_ready_message(config, probe))
        run_config = config
        if runtime_ok:
            auto = st.checkbox("이 PC에서 빠르게 돌아가는 모델 자동 선택", value=True, key=f"{prefix}_auto_model",
                               help="큰 모델은 그래픽카드 메모리(VRAM)에 다 올라가지 않으면 몇 배 느려집니다. 설치된 모델 중 VRAM에 들어가는 가장 큰 모델을 고릅니다.")
            if auto:
                from engine.stage2.local_ai_resilience import select_fast_auto_config

                run_config = select_fast_auto_config(config, probe.models, available_model_sizes=probe.model_sizes)
            st.caption(f"사용할 모델: {run_config.model}")
        if st.button("초안 만들기", type="primary", key=f"{prefix}_generate", disabled=not runtime_ok):
            _generate_with_progress(project, profile, prefix, build_client(run_config), run_config.model)
            st.rerun()
    note = st.session_state.get(f"{prefix}_run_note")
    if note:
        (st.success if note[0] == "success" else st.error)(note[1])
    rejected = st.session_state.get(f"{prefix}_rejected") or []
    if rejected:  # 다시 그려도 사라지지 않도록 세션에 두고, 다음 생성 때 새로 바꾼다
        with st.expander(f"저장하지 않은 초안 {len(rejected)}개 — 이유 보기", expanded=True):
            for row in rejected:
                st.write(f"• **{row['label']}**: {row['reason']}")
    for item in items:
        with st.expander(f"{item['label']} — {state_label(item)}", expanded=item["state"] == "초안 있음"):
            if item["reason"]:
                st.caption(item["reason"])
            if item["text"]:
                text = st.text_area("초안(고쳐 쓸 수 있습니다)", value=item["text"], height=220, key=f"{prefix}_draft_{item['key']}")
                st.caption("AI가 확정된 사실만으로 쓴 초안입니다. 회사 실제와 다르면 고치세요. 확인하면 회사 문서로 채택됩니다.")
                st.caption("확인할 점: " + " / ".join(examples.draft_checks()))
                if item["state"] != "확인 완료" and st.button("내용을 확인했습니다", key=f"{prefix}_adopt_{item['key']}"):
                    try:
                        narrative.adopt(project, item["key"], text, profile=profile)
                        save_project(project)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

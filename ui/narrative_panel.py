from __future__ import annotations

"""서술형 항목 화면(사실 입력 + 예시 고르기 + AI 초안 확인). 화학사고예방관리계획서·공정안전보고서 공용.

위젯 키는 f"{prefix}_..." 형태다. 공정안전보고서는 prefix "psm", 화학사고예방관리계획서는 "cap"을 쓴다.
"""

import streamlit as st

from engine.stage2 import narrative_examples as examples
from engine.stage2 import psm_narrative_workspace as narrative
from engine.stage2 import psm_table_workspace as tables
from engine.stage2.storage import save_project
from ui.example_picker import text_with_examples
from ui.table_grid import grid


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
            with st.spinner("확정된 사실로 초안을 만드는 중입니다."):
                try:
                    result = narrative.generate(project, build_client(run_config), profile=profile)
                    save_project(project)
                    st.session_state[f"{prefix}_rejected"] = narrative.rejected_rows(result)
                except Exception as exc:
                    st.error(f"초안을 만들지 못했습니다: {type(exc).__name__}: {exc}")
            st.rerun()
    rejected = st.session_state.get(f"{prefix}_rejected") or []
    if rejected:  # 다시 그려도 사라지지 않도록 세션에 두고, 다음 생성 때 새로 바꾼다
        with st.expander(f"저장하지 않은 초안 {len(rejected)}개 — 이유 보기", expanded=True):
            for row in rejected:
                st.write(f"• **{row['label']}**: {row['reason']}")
    for item in items:
        with st.expander(f"{item['label']} — {item['state']}", expanded=item["state"] == "초안 있음"):
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


def render(project, profile, table_forms, prefix: str, defaults: dict | None = None, decision_facts=None) -> None:
    """profile: PSM_PROFILE 또는 CAP_PROFILE. table_forms: 이 문서에서 사실로 받는 표 서식 키 목록."""
    defaults = defaults or {}
    st.caption("글로 쓰는 항목은 AI가 초안을 만듭니다. 사람은 프로그램이 알 수 없는 사실만 적고, 완성된 글을 한 번 확인합니다.")
    st.markdown("### 1. 먼저 적을 사실")
    values = {}
    for fact in profile.basic_facts:
        current = narrative.facts_value(project, fact) or defaults.get(fact.key, "")
        values[fact.key] = text_with_examples(
            fact.label, f"{prefix}_fact_{fact.key}", value=current, help_text=fact.help, long=fact.long,
            choices=examples.choices(fact.key), template=examples.template(fact.key), checks=examples.checks(fact.key))
    if st.button("사실 저장", type="primary", key=f"{prefix}_fact_save"):
        problems = []
        for fact in profile.basic_facts:
            try:
                narrative.save_fact(project, fact, values[fact.key])
            except narrative.ExampleMarkLeft as exc:
                problems.append(str(exc))
        save_project(project)
        if problems:
            for problem in problems:
                st.error(problem)
        else:
            st.rerun()
    missing = narrative.missing_basics(project, profile)
    if missing:
        st.info("아직 적지 않은 사실: " + ", ".join(missing))
    as_is = narrative.chosen_as_is(project, profile)
    if as_is:
        st.warning("예시 문구를 고치지 않고 그대로 저장한 항목이 있습니다. 우리 회사 실제와 같은지 확인하세요: " + ", ".join(as_is))

    st.markdown("### 2. 회사가 정한 사항")
    for fact in (decision_facts if decision_facts is not None else profile.decision_facts):
        with st.expander(fact.label):
            st.caption(fact.help)
            current = narrative.facts_value(project, fact)
            entered = {name: text_with_examples(label, f"{prefix}_fact_{fact.key}_{name}", value=current.get(name, ""),
                                                help_text=help_text, choices=examples.choices(fact.key, name))
                       for name, label, help_text in fact.fields}
            if st.button("저장", key=f"{prefix}_fact_save_{fact.key}"):
                try:
                    narrative.save_fact(project, fact, entered)
                except narrative.ExampleMarkLeft as exc:
                    st.error(str(exc))
                else:
                    save_project(project)
                    st.rerun()

    st.markdown("### 3. 연락체계·장비 등 표로 적는 사실")
    for form_no in table_forms:
        with st.expander(tables.SPECS[form_no].title):
            grid(form_no)(project)

    st.markdown("### 4. AI가 만든 글 확인")
    _drafts(project, profile, prefix)

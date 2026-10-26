from __future__ import annotations
import json
import streamlit as st
from engine.stage2 import evidence_workspace as ew
from engine.stage2 import scenario_triage, evidence_llm
from engine.stage2.storage import list_projects,load_project,save_project,save_attachment
from engine.stage2.direct_template import create_direct_cap_project

st.set_page_config(page_title="사업장 업무 시작",page_icon="📂",layout="wide")
st.title("자료를 올리고, 필요한 확인만 처리하세요")
st.caption("자료 수집 · 공통정보 정리 · 충돌 확인 · 기존 계산과 보고서 연결")
projects=list_projects()
with st.expander("새 사업장 만들기",expanded=not projects):
    with st.form("evidence_new_project"):
        name=st.text_input("사업장명")
        address=st.text_input("사업장 주소")
        if st.form_submit_button("자료 정리 시작"):
            try:
                p=create_direct_cap_project(name,address=address,cap_group="")
                save_project(p);st.session_state['_stage2_active_project_id']=p.project_id;st.rerun()
            except ValueError as exc:st.error(str(exc))
if not projects:st.stop()
options={p['project_id']:p['company_name'] for p in projects}
current=st.session_state.get('_stage2_active_project_id')
pid=st.selectbox("작업할 사업장",list(options),index=list(options).index(current) if current in options else 0,format_func=options.get)
st.session_state['_stage2_active_project_id']=pid
project=load_project(pid)
data=ew.graph(project);slots=ew.slots(project);tasks=ew.tasks(project)
a,b,c,d=st.columns(4)
a.metric("접수한 문서",len(data['documents']))
b.metric("확인 완료 사실",sum(bool(s['chosen']) for s in slots))
c.metric("값 충돌",sum(s['status']=='값 충돌' for s in slots))
d.metric("남은 확인 과제",len(tasks))
tabs=st.tabs(["1. 자료 올리기","2. 확인할 일","3. 공통정보 연결","4. 시나리오 후보","5. 계산·보고서"])
with tabs[0]:
    st.write("회사에서 갖고 있는 자료를 올리세요. 표의 설비번호·제품코드로 같은 대상을 연결합니다.")
    kind=st.radio("자료 종류",['facility','material'],format_func=lambda k:'설비·운전 자료' if k=='facility' else '제품·물질·SDS 자료',horizontal=True,key='evidence_kind_'+pid)
    hint=st.text_input("대상 식별번호 (SDS·단일 설비 설명서 등 표에 번호가 없는 경우)",help="예: P-01, TK-01. 서로 다른 제품을 같은 CAS만으로 합치지 않습니다.")
    uploaded=st.file_uploader("회사 자료",type=['csv','xlsx','pdf','docx','txt'],accept_multiple_files=True)
    if st.button("자료 읽고 확인 과제 만들기",type="primary",disabled=not uploaded):
        for file in uploaded:
            try:
                count=ew.ingest(project,file.name,file.getvalue(),kind,hint)
                save_attachment(project.project_id,file.name,file.getvalue(),note="공통정보 추출 원문")
                save_project(project)
                st.success(f"{file.name}: 후보 {count}개 접수")
            except Exception as exc:
                st.error(f"{file.name}: 파일을 읽지 못했습니다 ({type(exc).__name__}). 저장된 다른 자료는 유지됩니다.")
        st.rerun()
    st.download_button("가상 회사 시험자료 ZIP",ew.demo_zip(),file_name="synthetic_company_evidence.zip",mime="application/zip")
    st.caption("ZIP을 풀고 물질 CSV는 제품·물질 자료로, 설비 CSV 두 개는 설비 자료로 올리세요. 용량 충돌을 확인할 수 있습니다.")
    for doc in data['documents']:
        with st.expander(f"{doc['name']} · 후보 {doc['fact_count']}개"):
            st.code(doc['sha256'],language=None)
            if doc['unmapped_columns']:st.write("아직 연결하지 못한 열:",doc['unmapped_columns'])
            for passage in doc['passages']:st.text(passage['location']+'\n'+passage['text'][:12000])
    with st.expander("로컬 AI로 서술형 문서 후보 제안 (선택)"):
        readable={d['sha256']:d for d in data['documents'] if d.get('hint') and any(p.get('text','').strip() for p in d.get('passages',[]))}
        if readable:
            doc_id=st.selectbox('읽을 문서',list(readable),format_func=lambda k:readable[k]['name'])
            st.caption('로컬 LLM 설정(LOCAL_LLM_PROVIDER, LOCAL_LLM_URL, LOCAL_LLM_MODEL)을 사용합니다. 제안값은 원문 인용 검증 후에도 담당자 확인 전까지 보류됩니다.')
            if st.button('로컬 AI 후보 제안'):
                try:
                    from engine.stage2.local_llm import local_llm_config_from_sources, build_local_llm_client
                    outcome=evidence_llm.propose(project,doc_id,build_local_llm_client(local_llm_config_from_sources()))
                    save_project(project)
                    st.success(f"원문 대조를 통과한 후보 {outcome['accepted']}개, 거부 {outcome['rejected']}개. 확인할 일에서 검토하세요.")
                except Exception as exc:st.error(f'로컬 AI 후보 추출 실패: {exc}')
        else:st.info('대상 식별번호를 지정해 텍스트가 있는 PDF·DOCX·TXT를 접수하세요.')
    st.caption("스캔 PDF의 OCR, HWP/HWPX·도면 해석은 아직 자동 처리하지 않습니다. 인식하지 못한 자료는 확인 과제로 남습니다.")
with tabs[1]:
    if tasks:st.dataframe(tasks,hide_index=True,width="stretch")
    else:st.info("현재 접수자료에서 남은 과제가 없습니다. 모든 시나리오 조건이나 법적 대상 여부가 확인됐다는 의미는 아닙니다.")
    pending=[s for s in slots if not s['chosen']]
    if pending:
        catalog={s['key']:s for s in pending}
        selected=st.selectbox("확인할 사실",list(catalog),format_func=lambda k,catalog=catalog:f"{catalog[k]['entity']} · {ew.LABELS[catalog[k]['field']]} · {catalog[k]['status']}",key='evidence_slot_'+pid)
        slot=catalog[selected]
        st.write('자동 기입 보류 이유:', ', '.join(ew.review_gate(slot)) or '담당자 검토 가능')
        choices={f['id']:f for f in slot['facts']}
        choice=st.radio("근거를 대조하고 사용할 후보를 고르세요",list(choices),
                        format_func=lambda k,choices=choices:f"{choices[k]['value']} — {choices[k]['document']} / {choices[k]['location']} (원문: {choices[k]['raw']})",key='evidence_choice_'+pid+'_'+selected)
        checked=st.checkbox("원문·단위·현재 적용 여부를 확인했습니다",key='fact_checked_'+selected+'_'+slot['signature'])
        def approve_selected():
            try:
                ew.approve(project,selected,choice)
                save_project(project)
                st.session_state['evidence_approval_error']=''
            except ValueError as exc:
                st.session_state['evidence_approval_error']=str(exc)
        st.button("선택한 사실 확인",disabled=not checked,on_click=approve_selected)
        if st.session_state.get('evidence_approval_error'):
            st.error(st.session_state['evidence_approval_error'])
    with st.expander("회사에서 확인한 사실 추가·수정"):
        entity=st.text_input("대상 (예: facility:TK-01 또는 material:P-01)")
        field=st.selectbox("확인한 항목",list(ew.LABELS),format_func=ew.LABELS.get)
        value=st.text_input("확인값 (숫자는 항목에 표시한 단위로 입력)")
        reason=st.text_input("확인한 자료·위치·날짜 또는 담당자 확인 내용")
        if st.button("확인 후보 추가"):
            try:ew.add_manual(project,entity,field,value,reason);save_project(project);st.rerun()
            except ValueError as exc:st.error(str(exc))
with tabs[2]:
    confirmed=[{"대상":s['entity'],"항목":ew.LABELS[s['field']],"값":str(s['chosen']['value']),"문서":s['chosen']['document'],"위치":s['chosen']['location']} for s in slots if s['chosen']]
    st.dataframe(confirmed,hide_index=True,width="stretch")
    proposed=ew.publishing_plan(project)
    st.write("기존 작성자료에 연결할 내용")
    for key,rows in proposed.items():
        with st.expander(key,expanded=True):
            st.write("새 연결값");st.dataframe(rows,hide_index=True,width="stretch")
            old=project.get_field(key)
            if old:st.write("현재 저장값");st.json(old.value)
    overwrite=st.checkbox("기존 작성자료와의 차이를 검토했으며 해당 목록을 새 연결값으로 교체합니다")
    if st.button("확인한 공통정보를 작성자료에 연결",disabled=not proposed):
        try:ew.publish(project,replace_existing=overwrite);save_project(project);st.success("확인한 사실을 연결했습니다. 기존 계산 화면에서 누락 조건과 산정값을 검토하세요.")
        except ValueError as exc:st.error(str(exc))
    st.download_button("출처·결정 기록 JSON",json.dumps(data,ensure_ascii=False,indent=2).encode(),file_name="company_evidence_graph.json",mime="application/json")
with tabs[3]:
    triage=scenario_triage.evaluate(project)
    st.warning('예비 검토 순서입니다. 피해거리·규정수량·법적 대상 판정이나 최종 사고시나리오가 아닙니다. 가정값이 있는 후보는 계산 결과에 자동 반영하지 않습니다.')
    st.caption(triage['method'])
    st.dataframe([{'순위':r['rank'],'설비':r['facility'],'물질':r['material'],'취급관계 확인':r['linked'],
                   '예비 비교지표':round(r['score'],2),'상향 가정':', '.join(ew.LABELS[k] for k in r['assumptions']),
                   '상태':r['state']} for r in triage['rows']],hide_index=True,width='stretch')
    st.write('순위에 영향을 주는 결측 질문')
    if triage['questions']:st.dataframe(triage['questions'],hide_index=True,width='stretch')
    else:st.info('현재 확인된 취급 관계의 예비 순위를 바꾸는 결측값이 없거나 비교할 후보가 없습니다.')
    st.caption(triage['sensitivity'])
    for row in triage['rows']:
        with st.expander(f"{row['facility']} × {row['material']} · {row['state']}"):
            st.json({'rank':row['rank'],'assumptions':row['assumptions'],'provenance':row['sources'],
                     'blockers':row['blockers'],'rank_sensitive':row['rank_sensitive']})
with tabs[4]:
    st.write("확인된 물질·설비 정보는 기존 작성 화면이 재사용합니다. 기본 운전조건 이외의 누출·안전설비·물성·모델 조건은 해당 계산 화면에서 확인합니다.")
    for packet in ew.scenario_packets(project):
        with st.expander(packet['설비']+' · 시나리오 입력 검토팩'):st.json(packet)
    st.page_link("ui/cap_workspace_page.py",label="주변 지도·사고시나리오·화학사고예방관리계획서 작성")
    st.page_link("ui/psm_workspace_page.py",label="공정안전보고서 작성")
    st.download_button("확인한 사실과 남은 과제 보고서",ew.report(project).encode(),file_name="company_evidence_review.md",mime="text/markdown")

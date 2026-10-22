"""Streamlit: stored results first; only an explicit form submission can run diagnosis."""
from __future__ import annotations
import asyncio
import json
import threading
from pathlib import Path

import streamlit as st

from dataops_copilot.api_safety import CostLedger,SafeAPIError,read_api_settings
from dataops_copilot.evaluation import BundleAdapter
from dataops_copilot.hybrid import HybridRunbooks
from dataops_copilot.llm import FakeLLM
from dataops_copilot.mcp_client import open_live_mcp
from dataops_copilot.models import IncidentRef,Report
from dataops_copilot.retrieval import LocalRunbooks
from dataops_copilot.openai_llm import OpenAILLM
from dataops_copilot.replay import ReportReplay
from dataops_copilot.workflow import Limits
from dataops_copilot.workflow_v3 import ClaimCopilot as Copilot

ROOT=Path(__file__).resolve().parents[2]
RUNTIME=ROOT.parents[1]/'work/runtime'

@st.cache_resource
def execution_lock():return threading.Lock()

def available_reports():
    result={}
    for case,title in {'schema':'10만 행 · 스키마 변경','quality':'10만 행 · 키 누락','connection':'10만 행 · 연결 실패'}.items():
        path=ROOT/f'artifacts/v3/scale/{case}-report.json'
        if path.is_file():result[title]=path
    names={'schema':'스키마 변경','quality':'필수 키 누락','connection':'실행 연결 실패'}
    for case,title in names.items():
        candidates=[ROOT/f'artifacts/checkpoint4/live-{case}-report.json',ROOT/f'artifacts/checkpoint3/openai-schema-report.json'] if case=='schema' else [ROOT/f'artifacts/checkpoint4/live-{case}-report.json',ROOT/f'artifacts/checkpoint2/{case}-report.json']
        path=next((p for p in candidates if p.is_file()),None)
        if path:result[title]=path
    final=ROOT/'artifacts/v3/final'
    for path in sorted(final.glob('*-full.json')):
        result['v3 최종 '+path.stem.replace('-full','')]=path
    return result

async def execute(source,paid,live,full=False):
    llm=FakeLLM()
    if paid:
        key,_=read_api_settings(RUNTIME/'openai.env')
        llm=OpenAILLM(key,RUNTIME)
    retriever=HybridRunbooks() if full else LocalRunbooks()
    try:
        if live:
            async with open_live_mcp(RUNTIME/'live-settings.json') as tools:
                return await Copilot(tools,llm,retriever=retriever,limits=Limits(llm_calls=2 if full else 1),baseline=not full).diagnose(source.incident_ref)
        return await Copilot(ReportReplay(source),llm,retriever=retriever,limits=Limits(llm_calls=2 if full else 1),baseline=not full).diagnose(source.incident_ref)
    finally:
        if hasattr(retriever,"close"):retriever.close()

def main():
    st.set_page_config(page_title='DataOps Observability Copilot',page_icon='◉',layout='wide')
    st.markdown('''<style>
    .stApp { background:#f3f5f7; color:#142b3b; }
    [data-testid="stSidebar"] {background:#102b3f;color:#eef5fa;}
    [data-testid="stSidebar"] * {color:inherit;}
    [data-testid="stSidebar"] [data-baseweb="select"] * {color:#142b3b !important;}
    [data-testid="stMetric"] {background:white;border:1px solid #dde4e8;padding:14px 20px;border-radius:10px;}
    h1 {font-size:2.15rem !important;letter-spacing:-.06rem;}
    .eyebrow {color:#087e8b;font-weight:700;font-size:.82rem;letter-spacing:.1rem;}
    </style>''',unsafe_allow_html=True)
    st.sidebar.markdown('## DataOps Copilot')
    st.sidebar.caption('파이프라인 진단 · 근거 확인 · 복구 검증')
    paths=available_reports()
    selected=st.sidebar.selectbox('확인할 장애',list(paths))
    source=Report.model_validate_json(paths[selected].read_text())
    st.sidebar.divider()
    st.sidebar.markdown('**조회 전용** · 조치는 사람이 수행')
    paid_blocked=False
    if (RUNTIME/'llm-cost.sqlite3').exists():
        budget=CostLedger(RUNTIME/'llm-cost.sqlite3').summary()
        paid_blocked=budget['requests']>=budget['total_call_cap']
        st.sidebar.caption(f"이 앱의 누적 추정 비용: USD {budget['spent_or_reserved_usd']:.5f} / 0.05")
    st.markdown('<div class="eyebrow">PIPELINE OBSERVABILITY / LOCAL WORKSPACE</div>',unsafe_allow_html=True)
    st.title('실패 원인에서 복구 확인까지')
    st.caption('실행 로그·dbt 산출물·데이터 관측을 연결해 원인과 확인 절차를 보여줍니다.')
    with st.form('diagnosis_controls'):
        left,right=st.columns([2,1])
        mode=left.selectbox('실행 방식',['저장된 결과 보기','저장 증거로 다시 진단','실시간 조회 후 진단'])
        paid=right.checkbox('API 모델 사용',value=False,disabled=paid_blocked,help='실행 버튼을 누를 때만 유료 호출합니다. 기본값은 무료 테스트 대역입니다.')
        full=st.checkbox('추가 검색·Reviewer 검사 (2회 호출)',value=False,help='기본은 코드 검사를 유지하는 1회 호출 방식입니다. 추가 방식의 품질 이득은 이번 평가에서 확인되지 않았습니다.')
        submitted=st.form_submit_button('실행',type='primary')
    st.caption('v3.1 · 기본: 모델 1회 + 필수 코드 검사 · 추가 검색·Reviewer: 모델 2회')
    if paid_blocked:st.info('테스트용 API 요청 한도를 소진했습니다. 저장 결과와 무료 진단은 계속 사용할 수 있습니다.')
    key=str(paths[selected])
    if 'report' not in st.session_state or st.session_state.get('selection')!=key:
        st.session_state.report=source.model_dump(mode='json');st.session_state.selection=key
    if submitted:
        if mode=='저장된 결과 보기':st.session_state.report=source.model_dump(mode='json')
        else:
            lock=execution_lock()
            if not lock.acquire(blocking=False):st.warning('다른 진단이 진행 중입니다. 완료 후 실행해 주세요.')
            else:
                try:
                    with st.spinner('허용된 증거를 확인하고 있습니다…'):
                        result=asyncio.run(execute(source,paid,mode=='실시간 조회 후 진단',full))
                    st.session_state.report=result.model_dump(mode='json')
                except Exception as exc:
                    st.error(str(exc) if isinstance(exc,SafeAPIError) else '진단을 완료하지 못했습니다. 로컬 서비스·모델 준비 상태를 확인하세요.')
                finally:lock.release()
    report=Report.model_validate(st.session_state.report)
    d=report.diagnosis
    cols=st.columns(4)
    cols[0].metric('진단 유형',{'SCHEMA_CHANGE':'스키마 변경','DATA_QUALITY':'데이터 품질','CONNECTION_FAILURE':'연결 실패','UNKNOWN':'판단 보류','NORMAL':'정상'}[d.category])
    cols[1].metric('검토 상태','통과' if report.review.accepted else '확인 필요')
    cols[2].metric('수집 근거',str(len(report.evidence)))
    cols[3].metric('해당 진단 추정 비용','미수집' if report.usage.cost is None else f'${report.usage.cost:.6f}')
    model=report.versions.get('model','unknown')
    transport=report.validation_scope.get('transport','unknown')
    source_label='실제 시스템 조회' if transport=='real_mcp_stdio_live_backend' else '저장 증거 재생' if 'replay' in transport else '테스트 자료'
    st.caption(f"모델: {model}  |  증거: {source_label}  |  선택 실행: {report.incident_ref.run_id}")
    if 'fake' in model:st.info('이 결과의 LLM 출력은 무료 테스트 대역입니다. 실제 시스템 증거와 모델 검증 범위를 구분합니다.')
    a,b,c,dtab=st.tabs(['원인과 조치','수집 근거','런북과 검토','복구 확인'])
    with a:
        st.subheader('진단 근거')
        st.write(d.cause)
        for line in d.impact:st.write('• '+line)
        for action in d.recovery_actions:
            st.subheader('사람이 확인할 조치')
            st.write('선행 조건: '+' / '.join(action.prerequisites))
            for n,step in enumerate(action.steps,1):st.write(f'{n}. {step}')
            st.write('성공 확인: '+' / '.join(action.verification))
        if not d.recovery_actions:st.write('현재 결과에는 실행할 복구 조치가 없습니다.')
        if d.missing_evidence:st.warning('부족한 근거: '+' / '.join(d.missing_evidence))
    with b:
        for e in report.evidence:
            with st.expander(f'{e.kind} · {e.status} · {e.evidence_id}'):
                st.caption(f'{e.temporal_scope} | {e.observed_at.isoformat()} | '+('합성 평가 자료' if e.simulated else '실제 수집 자료'))
                st.json(e.model_dump(mode='json'))
    with c:
        for h in report.retrieval_hits:
            with st.expander(f'{h.rank}. {h.doc_id} · v{h.doc_version}'):
                st.markdown(h.content)
                st.caption(f'{h.method} | {h.chunk_id}')
        st.json(report.review.model_dump(mode='json'))
        st.caption('검토 통과는 실제 복구 성공을 뜻하지 않습니다.')
        if report.component_reviews:
            st.markdown('**v3 구성요소별 규칙 판정**')
            st.dataframe(report.component_reviews, hide_index=True)
            st.json({'구조화 주장':report.claim_proposal,'검증된 모델 반례':report.reviewer_findings})
    with dtab:
        record=ROOT/'artifacts/checkpoint4/live-e2e.json'
        recovery=[]
        if record.is_file():
            recovery=[r for r in json.loads(record.read_text()).get('recoveries',[]) if r['original_run_id']==report.incident_ref.run_id]
        if recovery:
            st.success('별도 후속 실행의 전체 태스크·품질 검사·집계가 통과했습니다.')
            st.json(recovery[0])
        else:st.info('이 결과와 연결된 새 실행의 복구 확인 자료가 없습니다.')
    st.download_button('진단 보고서 JSON 내려받기',report.model_dump_json(indent=2),file_name='dataops-diagnosis.json',mime='application/json',on_click='ignore')
    st.caption('화면 갱신·탭 전환·보고서 내려받기는 진단 API를 다시 호출하지 않습니다.')

if __name__=='__main__':main()

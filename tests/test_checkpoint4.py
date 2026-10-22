import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from dataops_copilot.api_safety import CostLedger,SafeAPIError
from dataops_copilot.evaluation import BundleAdapter,scoring
from dataops_copilot.fixtures import FixtureAdapter,incident_for
from dataops_copilot.hybrid import HybridRunbooks,evidence_query
from dataops_copilot.llm import FakeLLM
from dataops_copilot.models import TargetRef
from dataops_copilot.rules import supported_category
from dataops_copilot.workflow import Copilot

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def hybrid():
    r=HybridRunbooks()
    yield r
    r.close()


async def test_persistent_local_index_and_document_level_rrf(hybrid):
    hits=await hybrid.search('column "amount" does not exist missing_column stg_orders')
    assert hits[0].doc_id=='rb-schema'
    assert len({h.doc_id for h in hits})==len(hits)==3
    assert all(h.method=='bm25_e5_qdrant_rrf_k60' for h in hits)
    assert len({c['doc_id'] for c in hybrid.chunks})==12
    assert all(c['tokens_with_prefix']<=350 for c in hybrid.chunks)
    info=hybrid.client.get_collection(hybrid.collection)
    assert info.points_count==len(hybrid.chunks)
    assert len(hybrid.last_ranking['bm25_chunk_ids'])==10
    assert len(hybrid.last_ranking['dense_chunk_ids'])==10


@pytest.mark.parametrize('query,document', [('not_null customer_id null rows','rb-quality'),('connection refused dbt_orders','rb-connection'),('password authentication failed 28P01','rb-auth'),('could not translate host name NXDOMAIN','rb-dns')])
async def test_similar_symptoms_retrieve_distinct_procedures(hybrid,query,document):
    hits=await hybrid.search(query)
    assert document in [h.doc_id for h in hits]


async def test_one_bounded_additional_investigation_without_extra_llm_call():
    class IncompleteInspector(FakeLLM):
        async def complete(self,role,prompt,payload):
            if role=='inspector':return {'tools':['get_dbt_artifacts']}
            return await super().complete(role,prompt,payload)
    r=await Copilot(FixtureAdapter('schema'),IncompleteInspector()).diagnose(incident_for('schema'))
    assert r.review.accepted and r.diagnosis.category=='SCHEMA_CHANGE'
    assert r.replan_count==1 and r.node_trace==['triage','inspector','investigate','rca','reviewer']
    assert r.usage.llm_calls==4 and r.usage.tool_calls==3


def test_evaluation_profile_keeps_same_cash_caps_and_same_ledger(tmp_path):
    path=tmp_path/'cost.sqlite3'
    standard=CostLedger(path);evaluation=CostLedger(path,purpose='evaluation')
    for i in range(21):
        rid=evaluation.reserve(str(i),'triage',1000)
        evaluation.settle(rid,{'input_tokens':1,'output_tokens':1})
    with pytest.raises(SafeAPIError,match='DAILY_CAP'):standard.reserve('new','triage',1000)
    assert evaluation.summary()['daily_cap_usd']==standard.summary()['daily_cap_usd']==0.02
    assert evaluation.summary()['lifetime_cap_usd']==0.05
    assert evaluation.summary()['requests']==21


def test_flex_discount_only_when_provider_confirms_tier(tmp_path):
    ledger=CostLedger(tmp_path/'cost.sqlite3')
    one=ledger.reserve('one','rca',500000)
    two=ledger.reserve('two','rca',500000)
    usage={'input_tokens':100,'output_tokens':50}
    standard=ledger.settle(one,usage)
    flex=ledger.settle(two,usage,service_tier='flex')
    assert flex[2]*2==standard[2]
    third=ledger.reserve('three','rca',500000)
    with pytest.raises(SafeAPIError,match='SERVICE_TIER_UNVERIFIED'):
        ledger.settle(third,usage,service_tier='priority')


@pytest.mark.parametrize('case,category',[('F02','SCHEMA_CHANGE'),('F05','DATA_QUALITY'),('F08','CONNECTION_FAILURE')])
def test_evaluation_domain_contracts_not_model_accuracy(case,category):
    bundle=json.loads((ROOT/f'evaluation/final/{case}.json').read_text())
    adapter=BundleAdapter(bundle)
    assert supported_category(adapter.evidence,adapter.incident)[0]==category
    assert all(e.simulated for e in adapter.evidence)


def test_gold_and_final_cases_are_never_indexed(hybrid):
    manifest=json.loads((ROOT/'src/dataops_copilot/runbooks/manifest.json').read_text())
    assert len(manifest)==12
    assert all(row['kind'] in ('runbook','synthetic_history') for row in manifest)
    assert not any('evaluation/' in c['content'] or 'F12' in c['content'] or 'required_evidence_ids' in c['content'] for c in hybrid.chunks)


async def test_bundle_replay_refuses_execution_and_table_switch():
    data=json.loads((ROOT/'evaluation/dev/D01.json').read_text())
    adapter=BundleAdapter(data)
    with pytest.raises(ValueError,match='EXECUTION'):
        await adapter.call('get_task_context',{**adapter.incident.model_dump(exclude={'incident_id'}),'run_id':'other'})
    with pytest.raises(ValueError,match='TABLE'):
        await adapter.call('compare_schema',{'table_id':'raw.web_orders','baseline_id':'web-v1'})


def test_authored_schema_diffs_match_actual_bundle_columns():
    for path in sorted((ROOT/'evaluation/final').glob('*.json')):
        bundle=json.loads(path.read_text())
        schema=next(e for e in bundle['evidence'] if e['kind']=='compare_schema')
        if schema['status']=='success' and schema['data']['removed']:
            d=schema['data']
            # Insufficient case deliberately has a tempting unverified observation; not a full schema fixture.
            if any(e['kind']=='get_dbt_artifacts' and e['status']=='success' and e['data'].get('issue')=='missing_column' for e in bundle['evidence']):
                assert set(d['added'])==set(d['current_columns'])-set(d['baseline_columns'])
                assert set(d['removed'])==set(d['baseline_columns'])-set(d['current_columns'])


def test_screen_refresh_and_selection_do_not_call_paid_model(monkeypatch):
    from dataops_copilot.openai_llm import OpenAILLM
    async def forbidden(*a,**k):raise AssertionError('PAID_API_DURING_SCREEN_REFRESH')
    monkeypatch.setattr(OpenAILLM,'complete',forbidden)
    app=AppTest.from_file(str(ROOT/'src/dataops_copilot/ui.py'),default_timeout=20).run()
    assert not app.exception
    initial=app.session_state['workspace_reports']['connection']['report']['trace_id']
    app.run()
    assert not app.exception and app.session_state['workspace_reports']['connection']['report']['trace_id']==initial
    next(widget for widget in app.selectbox if widget.label=='진단 사례').select('quality').run()
    assert not app.exception
    selected=ROOT/'resources/workspace/inputs/reports/quality.json'
    expected=json.loads(selected.read_text())
    assert app.session_state['workspace_reports']['quality']['report']['incident_ref']['run_id']==expected['incident_ref']['run_id']

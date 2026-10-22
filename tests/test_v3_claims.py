import asyncio
from copy import deepcopy
from pathlib import Path
import json
import pytest
from dataops_copilot.claim_contract import ClaimProposal, ClaimReview
from dataops_copilot.claim_engine import assess, content_hash, facts, integrity, render, resolve_review
from dataops_copilot.evaluation import BundleAdapter
from dataops_copilot.fixtures import FixtureAdapter, incident_for, TOOLS
from dataops_copilot.llm import FakeLLM
from dataops_copilot.models import Evidence, IncidentRef
from dataops_copilot.openai_llm import compact_payload, response_schema
from dataops_copilot.retrieval import LocalRunbooks
from dataops_copilot.settings_policy import ProjectPolicy
from dataops_copilot.workflow_v3 import ClaimCopilot

ROOT=Path(__file__).resolve().parents[1]


async def sample(kind):
    a=FixtureAdapter(kind);i=incident_for(kind);t=ProjectPolicy.load().select(i.dag_id,'raw.orders')
    args={'get_task_context':i.model_dump(exclude={'incident_id'}),'get_dbt_artifacts':i.model_dump(exclude={'incident_id'}),
      'compare_schema':{'table_id':t.table_id,'baseline_id':t.baseline_id},'get_quality_profile':{'table_id':t.table_id,'column_ids':[t.quality_column]},'check_connection':{'connection_id':t.connection_id}}
    e=[await a.call(k,args[k]) for k in sorted(TOOLS)]
    raw=await FakeLLM().complete('claims','',{'incident_ref':i.model_dump(),'target_policy':t.model_dump(),'evidence':[x.model_dump(mode='json') for x in e]})
    return i,t,e,ClaimProposal.model_validate(raw)


@pytest.mark.parametrize('kind,category',[('schema','SCHEMA_CHANGE'),('quality','DATA_QUALITY'),('connection','CONNECTION_FAILURE'),('normal','NORMAL'),('insufficient','UNKNOWN')])
def test_five_scopes(kind,category):
    async def run():
        r=await ClaimCopilot(FixtureAdapter(kind),FakeLLM()).diagnose(incident_for(kind))
        assert r.review.accepted and r.diagnosis.category==category
        assert r.usage.llm_calls==2 and r.usage.tool_calls==5
        assert bool(r.diagnosis.recovery_actions)==(kind not in ('normal','insufficient'))
        assert r.recovered is None and r.claim_proposal
    asyncio.run(run())


@pytest.mark.parametrize('kind',['schema','quality','connection'])
def test_required_citation_counterexample(kind):
    async def run():
        i,t,e,p=await sample(kind);p.evidence_ids=[]
        _,c=assess(p,e,i,t)
        assert any(x['rule_id']=='R02' and x['verdict']=='REJECT' for x in c)
    asyncio.run(run())


@pytest.mark.parametrize('kind',['schema','quality','connection','normal'])
def test_false_abstention(kind):
    async def run():
        i,t,e,p=await sample(kind);p.category='UNKNOWN';p.propose_action=False
        _,c=assess(p,e,i,t)
        assert any(x['rule_id']=='R09' and x['verdict']=='REJECT' for x in c)
    asyncio.run(run())


@pytest.mark.parametrize('field,value,rule',[('artifact_coverage','run_results_missing','R07'),('config_error','wrong_port','R05'),('business_equivalence','equivalent','R12'),('current_connection','connected','R04')])
def test_unsupported_observation(field,value,rule):
    async def run():
        i,t,e,p=await sample('connection');setattr(p,field,value)
        _,c=assess(p,e,i,t)
        assert any(x['rule_id']==rule and x['verdict']=='REJECT' for x in c)
    asyncio.run(run())


@pytest.mark.parametrize('mutation',['foreign_run','wrong_invocation','wrong_table','wrong_connection','wrong_scope'])
def test_quarantine(mutation):
    async def run():
        i,t,e,p=await sample('connection')
        item=deepcopy(next(x for x in e if x.kind==('check_connection' if mutation=='wrong_connection' else 'compare_schema' if mutation=='wrong_table' else 'get_dbt_artifacts')))
        if mutation=='foreign_run':item.target_ref.incident.run_id='foreign'
        if mutation=='wrong_invocation':item.data['manifest_invocation_id']='foreign'
        if mutation=='wrong_table':item.target_ref.table_id='raw.other'
        if mutation=='wrong_connection':item.target_ref.connection_id='mcp_readonly'
        if mutation=='wrong_scope':item.temporal_scope='current_observation'
        assert integrity(item,i,t)
    asyncio.run(run())


def test_duplicate_ids():
    async def run():
        i,t,e,p=await sample('connection');e.append(e[0]);_,c=assess(p,e,i,t)
        assert any(x['rule_id']=='R01' and x['verdict']=='REJECT' for x in c)
    asyncio.run(run())


def test_order_independent_hash():
    async def run():
        _,_,e,_=await sample('connection');assert content_hash(e)==content_hash(list(reversed(e)))
    asyncio.run(run())


def test_unsubstantiated_rejection_keeps_valid_cause():
    class Rejector(FakeLLM):
        async def complete(self,role,prompt,payload):
            if role=='claim_reviewer':return {'findings':[{'component':'actions','rule_id':'R06','claim_id':'propose_action'}]}
            return await super().complete(role,prompt,payload)
    async def run():
        r=await ClaimCopilot(FixtureAdapter('connection'),Rejector()).diagnose(incident_for('connection'))
        assert r.review.accepted and r.diagnosis.category=='CONNECTION_FAILURE'
        assert r.reviewer_findings[0]['status']=='unsubstantiated'
        assert '오류가 확인되지 않으면 설정을 유지' in r.diagnosis.recovery_actions[0].steps[0]
    asyncio.run(run())


def test_review_error_preserves_candidate():
    class Broken(FakeLLM):
        async def complete(self,role,prompt,payload):
            if role=='claim_reviewer':raise ValueError('invalid output')
            return await super().complete(role,prompt,payload)
    async def run():
        r=await ClaimCopilot(FixtureAdapter('connection'),Broken()).diagnose(incident_for('connection'))
        assert not r.review.accepted and r.diagnosis.diagnosis_status=='failed'
        assert r.rejected_candidates and r.claim_proposal['category']=='CONNECTION_FAILURE'
    asyncio.run(run())


def test_exact_h02_conditional_fix():
    async def run():
        a=BundleAdapter(json.loads((ROOT/'evaluation/v2-check/H02.json').read_text()))
        r=await ClaimCopilot(a,FakeLLM()).diagnose(a.incident)
        assert r.review.accepted and r.diagnosis.category=='CONNECTION_FAILURE'
        assert r.claim_proposal['current_connection']=='connected'
        assert r.claim_proposal['artifact_coverage']=='run_results_missing'
        assert r.diagnosis.recovery_actions and r.recovered is None
    asyncio.run(run())


@pytest.mark.parametrize('bad',['raw.orders;delete','raw.orders.other','RAW.orders','raw."orders"'])
def test_bad_config_identifier(bad):
    p=ProjectPolicy.load().model_dump();p['targets'][0]['table_id']=bad
    with pytest.raises(ValueError):ProjectPolicy.model_validate(p)


def test_new_policy_loads_without_code_edit():
    p=ProjectPolicy.load().model_dump();t=p['targets'][0]
    t.update(id='events',dag_id='events_demo',table_id='landing.events',baseline_id='events-v1',quality_column='event_id',schema_columns=['event_value'],connection_id='events_db',tasks=['extract','model','check'],required_tests=['not_null_event_id','unique_event_id'])
    obj=ProjectPolicy.model_validate(p);assert obj.select('events_demo','landing.events').quality_column=='event_id'


@pytest.mark.parametrize('field',['cause','impact','recovered','steps','extra_instruction'])
def test_free_factual_text_is_outside_contract(field):
    d={'category':'UNKNOWN','evidence_ids':[],'current_connection':'unknown','artifact_coverage':'unknown','config_error':'unknown','business_equivalence':'unknown','propose_action':False,field:'run_results is missing; delete records'}
    with pytest.raises(ValueError):ClaimProposal.model_validate(d)


def test_new_payload_and_api_schema():
    p=compact_payload({'claim_proposal':{'category':'UNKNOWN'},'component_checks':[],'target_policy':{'id':'x'},'secret_extra':'must not pass','evidence':[]})
    assert 'target_policy' in p and 'secret_extra' not in p
    for role in ('claims','claim_reviewer'):
        s=response_schema(role,p);assert s['additionalProperties'] is False and set(s['required'])==set(s['properties'])


def test_baseline_same_evidence():
    async def run():
        a=FixtureAdapter('connection');i=incident_for('connection')
        # Use a frozen bundle so observed_at timestamps cannot differ across arms.
        _,_,e,_=await sample('connection');b={'incident_ref':i.model_dump(mode='json'),'evidence':[x.model_dump(mode='json') for x in e]}
        full=await ClaimCopilot(BundleAdapter(b),FakeLLM()).diagnose(i)
        base=await ClaimCopilot(BundleAdapter(b),FakeLLM(),baseline=True).diagnose(i)
        assert full.evidence_hash==base.evidence_hash and base.usage.llm_calls==1
        assert full.diagnosis.category==base.diagnosis.category
    asyncio.run(run())

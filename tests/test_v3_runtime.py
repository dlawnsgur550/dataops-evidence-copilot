import json
from copy import deepcopy
import httpx
import pytest
from pydantic import SecretStr
from dataops_copilot.claim_contract import ClaimProposal
from dataops_copilot.claim_engine import integrity
from dataops_copilot.fixtures import FixtureAdapter, incident_for
from dataops_copilot.openai_llm import OpenAILLM
from dataops_copilot.recovery_v3 import check_recovery_v3
from dataops_copilot.settings_policy import ProjectPolicy


def recovery_bundle():
    old=incident_for('schema');new=incident_for('normal').model_copy(update={'run_id':'new-run'})
    a=FixtureAdapter('normal');args=incident_for('normal').model_dump(exclude={'incident_id'})
    c=a.query('get_task_context',args);d=a.query('get_dbt_artifacts',args)
    for e in (c,d):e.target_ref.incident=new
    aggregate={'run_id':new.run_id,'table_id':'raw.orders','checked_at':'2026-10-20T07:02:00+00:00','matched':True,'nulls':0,'duplicates':0,'raw_count':1000,'stage_count':1000,'daily_count':1000,'raw_sum':'10.0','stage_sum':'10.0','daily_sum':'10.0'}
    repair={'performed_at':'2026-10-20T06:59:00+00:00'}
    return old,new,c,d,ProjectPolicy.load().select('orders_demo','raw.orders'),aggregate,repair


def test_recovery_bound_complete():
    assert check_recovery_v3(*recovery_bundle())['recovered']


@pytest.mark.parametrize('mutation',['same_run','foreign_aggregate','wrong_table','old_timeline','missing_count','missing_sum','wrong_sum','failed_test','incomplete_tasks','future_repair'])
def test_recovery_counterexamples(mutation):
    old,new,c,d,t,g,r=recovery_bundle()
    if mutation=='same_run':old=new
    if mutation=='foreign_aggregate':g['run_id']='foreign'
    if mutation=='wrong_table':g['table_id']='raw.other'
    if mutation=='old_timeline':g['checked_at']='2026-10-20T06:59:00+00:00'
    if mutation=='missing_count':g.pop('raw_count')
    if mutation=='missing_sum':g.pop('raw_sum')
    if mutation=='wrong_sum':g['raw_sum']='11.0'
    if mutation=='failed_test':d.data['test_results']['unique_order_id']='fail'
    if mutation=='incomplete_tasks':c.data['task_statuses'].pop('dbt_run')
    if mutation=='future_repair':r['performed_at']='2026-10-20T08:00:00+00:00'
    assert not check_recovery_v3(old,new,c,d,t,g,r)['recovered']


def test_wrong_baseline_rejected():
    t=ProjectPolicy.load().select('orders_demo','raw.orders');e=FixtureAdapter('schema').query('compare_schema',{'table_id':t.table_id,'baseline_id':t.baseline_id})
    e.target_ref.baseline_id='foreign'
    assert integrity(e,incident_for('schema'),t)==['R01']


@pytest.mark.parametrize('role',['claims','claim_reviewer'])
async def test_v3_actual_request_contract_without_network(tmp_path,role):
    answer={'category':'UNKNOWN','evidence_ids':[],'current_connection':'unknown','artifact_coverage':'unknown','config_error':'unknown','business_equivalence':'unknown','propose_action':False} if role=='claims' else {'findings':[]}
    calls=[]
    def handler(req):
        calls.append(req);b=json.loads(req.content)
        assert b['model']=='gpt-6-luna' and b['store'] is False and b['tools']==[] and b['service_tier']=='flex'
        assert 'private-test-value' not in req.content.decode()
        p=json.loads(b['input']);assert p['target_policy']['id']=='orders'
        return httpx.Response(200,json={'status':'completed','service_tier':'flex','usage':{'input_tokens':100,'output_tokens':50},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}]})
    llm=OpenAILLM(SecretStr('private-test-value'),tmp_path,transport=httpx.MockTransport(handler),service_tier='flex')
    first=await llm.complete(role,'json only',{'evidence':[],'target_policy':{'id':'orders'}})
    second=await llm.complete(role,'json only',{'evidence':[],'target_policy':{'id':'orders'}})
    assert first==answer==second and len(calls)==1 and llm.metrics['local_cache_hits']==1

"""Observed v1 failures, paid-output boundaries and independent comparison input."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from dataops_copilot.api_safety import SafeAPIError
from dataops_copilot.diagnostics import sanitized
from dataops_copilot.evaluation import BundleAdapter, baseline
from dataops_copilot.fixtures import FixtureAdapter, incident_for
from dataops_copilot.llm import FakeLLM
from dataops_copilot.models import Diagnosis, Report, abstain
from dataops_copilot.openai_llm import OpenAILLM
from dataops_copilot.rules import code_review
from dataops_copilot.workflow import Copilot, Limits

ROOT = Path(__file__).resolve().parents[1]
TEST_KEY = 'sk-test-private-shared-fixture'


def wire(text='', **overrides):
    return {'status': 'completed', 'usage': {'input_tokens': 100, 'output_tokens': 20},
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}], **overrides}


@pytest.mark.parametrize('body,expected', [
    (wire('{"tools": ['), 'JSON_INVALID'),
    (wire('```json\n{"tools": []}\n```'), 'JSON_INVALID'),
    (wire(''), 'EMPTY_STRUCTURED_OUTPUT'),
    (wire('{"tools": []}', status='incomplete'), 'INCOMPLETE'),
    (wire(output=[{'type':'message','content':[{'type':'refusal','refusal':TEST_KEY}]}]), 'REFUSAL'),
    (wire(output=[{'type':'message','content':[{'type':'output_text','text':'{}'}, {'type':'output_text','text':'{}'}]}]), 'AMBIGUOUS'),
    (wire('{"tools": ["get_task_context"]}'), 'SCHEMA_VALIDATION'),
    (wire('{"tools": ["get_dbt_artifacts", "get_dbt_artifacts"]}'), 'SCHEMA_VALIDATION'),
])
async def test_rejected_outputs_never_repair_retry_or_cache(tmp_path, body, expected):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json=body)
    llm=OpenAILLM(SecretStr(TEST_KEY),tmp_path,transport=httpx.MockTransport(handler))
    with pytest.raises(SafeAPIError,match=expected):
        await llm.complete('inspector','Select evidence',{})
    assert len(calls)==1 and llm.ledger.summary()['requests']==1
    assert not list(llm.cache.glob('*.json'))
    assert llm.diagnostics[-1]['role']=='inspector'
    assert TEST_KEY not in json.dumps(llm.diagnostics)
    assert 'text' not in llm.diagnostics[-1]


async def test_extra_field_name_is_not_echoed_in_schema_error(tmp_path):
    body=wire(json.dumps({'tools':[], TEST_KEY:'private'}))
    llm=OpenAILLM(SecretStr(TEST_KEY),tmp_path,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=body)))
    # An exact key in the raw output is rejected before schema parsing.
    with pytest.raises(SafeAPIError,match='SENSITIVE_OUTPUT'):
        await llm.complete('inspector','Evidence',{})
    assert TEST_KEY not in json.dumps(llm.diagnostics)


@pytest.fixture
async def quality_report():
    return await Copilot(FixtureAdapter('quality'),FakeLLM()).diagnose(incident_for('quality'))


@pytest.mark.parametrize('claim',[
    '부분 run_results가 누락됐습니다.',
    'run_results가 생성되지 않았습니다.',
    'run_results is missing because some task states were absent.',
])
async def test_missing_artifact_claim_requires_explicit_receipt(quality_report,claim):
    r=quality_report
    d=r.diagnosis.model_copy(update={'missing_evidence':[claim]})
    assert 'UNSUPPORTED_ARTIFACT_MISSING_CLAIM:run_results' in code_review(d,r.evidence,r.incident_ref,r.retrieval_hits)


@pytest.mark.parametrize('claim',[
    'run_results의 완전성은 확인할 수 없습니다.',
    'run_results 누락 여부는 미확인입니다.',
    'run_results coverage is unknown.',
])
async def test_unconfirmed_coverage_is_not_a_missing_file_claim(quality_report,claim):
    r=quality_report
    d=r.diagnosis.model_copy(update={'missing_evidence':[claim]})
    assert not code_review(d,r.evidence,r.incident_ref,r.retrieval_hits)


async def test_proposed_future_checks_do_not_require_existing_test_artifacts(quality_report):
    r=quality_report
    a=r.diagnosis.recovery_actions[0].model_copy(update={'verification':['새 실행에서 not_null과 unique 두 검사를 준비해 통과 여부를 확인합니다.']})
    d=r.diagnosis.model_copy(update={'recovery_actions':[a]})
    assert not code_review(d,r.evidence,r.incident_ref,r.retrieval_hits)


async def test_explicit_valid_partial_receipt_allows_missing_claim():
    r=Report.model_validate_json((ROOT/'artifacts/checkpoint2/connection-report.json').read_text())
    d=r.diagnosis.model_copy(update={'missing_evidence':['run_results가 생성되지 않았습니다.']})
    assert not code_review(d,r.evidence,r.incident_ref,r.retrieval_hits)


async def test_normal_and_insufficient_are_distinct():
    r=await Copilot(FixtureAdapter('normal'),FakeLLM()).diagnose(incident_for('normal'))
    assert r.diagnosis.category=='NORMAL' and not r.diagnosis.recovery_actions
    assert 'NORMAL_EVIDENCE_MISCLASSIFIED' in code_review(abstain('no failure cause'),r.evidence,r.incident_ref,r.retrieval_hits)
    r=await Copilot(FixtureAdapter('insufficient'),FakeLLM()).diagnose(incident_for('insufficient'))
    assert r.diagnosis.category=='UNKNOWN' and r.diagnosis.diagnosis_status=='insufficient'
    assert r.review.accepted and not r.diagnosis.recovery_actions


async def test_rejected_candidate_preserved_but_never_supported():
    r=await Copilot(FixtureAdapter('schema'),FakeLLM(reject_review=True),limits=Limits(llm_calls=4)).diagnose(incident_for('schema'))
    assert r.diagnosis.category=='UNKNOWN' and not r.review.accepted
    assert len(r.rejected_candidates)==1
    assert r.rejected_candidates[0]['diagnosis']['category']=='SCHEMA_CHANGE'
    assert 'SEMANTIC_REVIEW_REJECTED' in r.rejected_candidates[0]['review']['violations']


async def test_baseline_gets_full_bundle_even_if_inspector_fails(tmp_path):
    bundle=json.loads((ROOT/'evaluation/final/F02.json').read_text())
    class FailingInspector(FakeLLM):
        async def complete(self,role,prompt,payload):
            if role=='inspector':raise SafeAPIError('SIMULATED_INSPECTOR_JSON_INVALID')
            return await super().complete(role,prompt,payload)
    adapter=BundleAdapter(bundle)
    failed=await Copilot(adapter,FailingInspector()).diagnose(adapter.incident)
    assert len(failed.evidence)==1
    captured=[]
    async def no_model_answer(role,prompt,payload):
        captured.append(payload)
        return abstain('deliberately no diagnosis').model_dump(mode='json')
    # Real client's usage interface, with no HTTP request or key required.
    llm=OpenAILLM(SecretStr(TEST_KEY),tmp_path)
    llm.complete=no_model_answer
    base=await baseline(llm,failed,evidence_bundle=bundle)
    assert len(base.evidence)==len(captured[0]['evidence'])==5
    assert base.validation_scope['transport']=='independent_full_frozen_bundle'
    assert 'required_evidence_ids' not in json.dumps(captured[0])
    assert llm.ledger.summary()['requests']==0


def test_review_snapshot_redacts_without_breaking_structure():
    result=sanitized({'steps':['password=secret',TEST_KEY,'/Users/private/task.py']})
    assert result=={'steps':['password=[REDACTED]','[REDACTED]','[LOCAL_PATH]']}

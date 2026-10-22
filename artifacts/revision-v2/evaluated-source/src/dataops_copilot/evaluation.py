"""Evaluation replay and single-call baseline. Answer files are read only by scoring code."""
from __future__ import annotations
import hashlib
import json
import time
import uuid
from pathlib import Path

from .api_safety import SafeAPIError
from .fixtures import TOOLS
from .models import Diagnosis,Evidence,IncidentRef,Report,RetrievalHit,Review,Usage,abstain
from .rules import code_review,evidence_violations


class BundleAdapter:
    transport='fixed_evidence_bundle_replay'
    data_scope='authored_synthetic_evaluation'
    external_systems='not_queried_in_this_run'
    def __init__(self,bundle):
        self.incident=IncidentRef.model_validate(bundle['incident_ref'])
        self.evidence=[Evidence.model_validate(e) for e in bundle['evidence']]
        if len({e.evidence_id for e in self.evidence})!=len(self.evidence):raise ValueError('DUPLICATE_BUNDLE_EVIDENCE')
    async def call(self,tool,args):
        if tool not in TOOLS:raise ValueError('TOOL_NOT_ALLOWED')
        if tool in ('get_task_context','get_dbt_artifacts'):
            if IncidentRef(incident_id='replay',**args).execution_key()!=self.incident.execution_key():raise ValueError('WRONG_REPLAY_EXECUTION')
        item=next(e for e in self.evidence if e.kind==tool)
        if tool in ('compare_schema','get_quality_profile') and args.get('table_id')!=item.target_ref.table_id:raise ValueError('WRONG_REPLAY_TABLE')
        if tool=='compare_schema' and args.get('baseline_id')!=item.target_ref.baseline_id:raise ValueError('WRONG_REPLAY_BASELINE')
        if tool=='check_connection' and args.get('connection_id')!=item.target_ref.connection_id:raise ValueError('WRONG_REPLAY_CONNECTION')
        return item


def scoring(answer,report):
    d=report.diagnosis
    required=set(answer['required_evidence_ids'])
    checks={'category':d.category==answer['category'], 'required_citations':required.issubset(d.evidence_ids),
       'safe_action':not d.recovery_actions if answer['category'] in ('NORMAL','UNKNOWN') else bool(d.recovery_actions) and all(a.kind==answer['action_kind'] and required.issubset(a.evidence_ids) and a.target_ref.table_id==answer['cause_elements']['table_id'] if answer['category']!='CONNECTION_FAILURE' else a.kind=='connection_config' and a.target_ref.connection_id=='dbt_orders' and required.issubset(a.evidence_ids) for a in d.recovery_actions),
       'review_accepted':report.review.accepted,'abstention':d.diagnosis_status=='insufficient' and not d.recovery_actions if answer['must_abstain'] else d.diagnosis_status=='supported'}
    return {'checks':checks,'structural_pass':all(checks.values()),'semantic_review':'requires documented analyst evidence check, not exact text matching'}


async def baseline(llm,final_report=None,*,evidence_bundle=None):
    """Exactly the evidence actually seen by the final RCA; no retrieved document contents."""
    start=time.monotonic(); trace='base-'+uuid.uuid4().hex
    llm.begin_diagnosis(trace)
    if evidence_bundle is not None:
        adapter=BundleAdapter(evidence_bundle)
        incident=adapter.incident
        source_evidence=adapter.evidence
    else:
        incident=final_report.incident_ref
        source_evidence=final_report.evidence
    evidence=[e for e in source_evidence if not evidence_violations(e,incident)]
    # Fixed output-contract reference catalog; no retrieved text or case-specific ranking.
    catalog=[RetrievalHit(doc_id=doc,doc_version='2',chunk_id='policy-catalog:'+doc,rank=n,content_hash=hashlib.sha256(b'').hexdigest(),content='',method='fixed_identifier_catalog_no_retrieval') for n,doc in enumerate(('rb-schema','rb-quality','rb-connection'),1)]
    errors=[]
    try:
        raw=await llm.complete('rca','Single LLM baseline. Diagnose once from supplied execution evidence. No retrieved procedures are supplied. The three empty catalog entries are only fixed identifiers required by the shared output contract. Cite evidence, distinguish current observations from historical logs, preserve originals, abstain if necessary, and propose human-only verification. Return Diagnosis JSON.',
          {'incident_ref':incident.model_dump(mode='json'),'evidence':[e.model_dump(mode='json') for e in evidence],'retrieval_hits':[h.model_dump(mode='json') for h in catalog]})
        diagnosis=Diagnosis.model_validate(raw)
        violations=code_review(diagnosis,evidence,incident,catalog)
    except Exception as exc:
        errors=[str(exc) if isinstance(exc,SafeAPIError) else 'BASELINE_INVALID_OR_FAILED_RESPONSE']
        diagnosis=abstain(errors[0],failed=True);violations=errors
    m=llm.metrics
    u=Usage(llm_calls=1,api_calls=m['api_calls'],local_cache_hits=m['local_cache_hits'],price_date=m['price_date'],elapsed_seconds=time.monotonic()-start,uncertain_reserved_usd=llm.ledger.uncertain_usd(trace))
    u.service_tier=m.get('service_tier')
    if m['usage_collected'] or not m['api_calls']:
        u.input_tokens=m['input_tokens'];u.output_tokens=m['output_tokens'];u.tokens=u.input_tokens+u.output_tokens;u.cost=m['cost_usd'];u.cost_basis='provider_token_usage_price_estimate' if m['api_calls'] else 'local_cache_or_no_request'
    return Report(trace_id=trace,incident_ref=incident,plan=None,evidence=evidence,retrieval_hits=[],diagnosis=diagnosis,
       review=Review(accepted=not violations,violations=violations,feedback=['Deterministic validation only; no semantic reviewer in baseline.'],revision_count=0,semantic_reviewer='none-baseline-code-only'),errors=errors,usage=u,node_trace=['single_llm'],replan_count=0,revision_count=0,
       evidence_hash=hashlib.sha256(json.dumps([e.model_dump(mode='json') for e in evidence],sort_keys=True).encode()).hexdigest(),versions={'app':'0.2.0','model':llm.model_id,'service_tier':llm.service_tier,'retrieval':'none-fixed-identifier-catalog'},validation_scope={'llm':llm.model_id,'transport':'independent_full_frozen_bundle' if evidence_bundle is not None else 'same_actual_rca_evidence_as_final','data':'authored_synthetic_evaluation','external_systems':'not_queried_in_this_run'}, output_diagnostics=getattr(llm,'diagnostics',[]))


def frozen_files(root):
    paths=[]
    for folder in ('src','evaluation/dev','evaluation/final','evaluation/private'):
        paths.extend(p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.extend(root/name for name in ('pyproject.toml','uv.lock','deployment/embedding-model.json','evaluation/RUBRIC.md','.streamlit/config.toml'))
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def verify_freeze(root):
    frozen=json.loads((root/'evaluation/freeze.json').read_text())
    if frozen['sha256']!=frozen_files(root):raise RuntimeError('EVALUATION_FREEZE_CHANGED_NO_PAID_REQUEST_SENT')
    return frozen

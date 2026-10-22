"""v3: bounded collector -> typed claims -> executable policy -> model challenge.

Two calls, no automatic retry or rewrite. Legacy v2 workflow remains importable
for regression and archived reports, while CLI/UI explicitly use this workflow.
"""
import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path
from .api_safety import SafeAPIError
from .claim_contract import ClaimProposal, ClaimReview
from .claim_engine import assess, content_hash, integrity, render, resolve_review
from .models import Evidence, Report, Review, Usage, abstain
from .retrieval import LocalRunbooks
from .settings_policy import ProjectPolicy
from .workflow import Limits

ORDER=('get_task_context','get_dbt_artifacts','compare_schema','get_quality_profile','check_connection')


class ClaimCopilot:
    def __init__(self,tools,llm,retriever=None,limits=None,policy=None,*,baseline=False):
        self.tools=tools;self.llm=llm;self.retriever=retriever or LocalRunbooks()
        self.limits=limits or Limits(llm_calls=2,total_seconds=180)
        self.policy=policy or ProjectPolicy.load();self.baseline=baseline

    async def diagnose(self,incident):
        start=time.monotonic();trace='v3-'+uuid.uuid4().hex;usage=Usage();items=[];hits=[];errors=[];nodes=[];checks=[];findings=[];proposal=None;rejected=[]
        target=None;diagnosis=abstain('진단 시작 전',failed=True);accepted=False
        if hasattr(self.llm,'begin_diagnosis'):self.llm.begin_diagnosis(trace)

        def left(cap):
            remaining=self.limits.total_seconds-(time.monotonic()-start)
            if remaining<=0:raise SafeAPIError('TOTAL_TIMEOUT')
            return min(remaining,cap)

        async def collect(tool,args):
            if usage.tool_calls>=self.limits.tool_calls:raise SafeAPIError('TOOL_CALL_LIMIT')
            usage.tool_calls+=1
            e=Evidence.model_validate(await asyncio.wait_for(self.tools.call(tool,args),left(self.limits.tool_seconds)))
            if e.kind!=tool:raise SafeAPIError('TOOL_KIND_MISMATCH')
            items.append(e)
            return e

        async def ask(role,payload):
            if usage.llm_calls>=self.limits.llm_calls:raise SafeAPIError('LLM_CALL_LIMIT')
            usage.llm_calls+=1;nodes.append(role)
            prompt=(Path(__file__).parent/'prompts'/f'{role}.md').read_text()
            return await asyncio.wait_for(self.llm.complete(role,prompt,payload),left(self.limits.llm_seconds))

        try:
            nodes.append('bounded_readonly_collector')
            args=incident.model_dump(exclude={'incident_id'})
            context=await collect('get_task_context',args)
            # No fallback target when context is unavailable: ambiguous target means safe stop.
            if context.status!='success':raise SafeAPIError('TARGET_CONTEXT_UNAVAILABLE')
            target=self.policy.select(incident.dag_id,context.data.get('table_id'))
            if incident.task_id not in target.tasks:raise SafeAPIError('TASK_NOT_IN_PROJECT_ALLOWLIST')
            await collect('get_dbt_artifacts',args)
            await collect('compare_schema',{'table_id':target.table_id,'baseline_id':target.baseline_id})
            await collect('get_quality_profile',{'table_id':target.table_id,'column_ids':[target.quality_column]})
            await collect('check_connection',{'connection_id':target.connection_id})
            valid=[e for e in items if not integrity(e,incident,target)]
            quarantined=[e.evidence_id for e in items if integrity(e,incident,target)]
            if quarantined:
                checks.append({'rule_id':'R01','claim_id':'evidence_ids','component':'cause','verdict':'REJECT','reason':'실행·대상·영수증이 맞지 않는 근거 격리','evidence_ids':quarantined})
            if self.baseline:
                from .models import RetrievalHit
                hits=[RetrievalHit(doc_id=doc,doc_version='3',chunk_id='catalog:'+doc,rank=i,content='',content_hash=hashlib.sha256(b'').hexdigest(),method='fixed_identifier_catalog_no_retrieval') for i,doc in enumerate(('rb-schema','rb-quality','rb-connection'),1)]
            else:
                from .hybrid import evidence_query
                nodes.append('retrieval');usage.rag_calls+=1
                hits=await asyncio.wait_for(self.retriever.search(evidence_query(valid)),left(self.limits.tool_seconds))
            payload={'incident_ref':incident.model_dump(mode='json'),'target_policy':target.model_dump(mode='json'),
               'evidence':[e.model_dump(mode='json') for e in valid],'retrieval_hits':[h.model_dump(mode='json') for h in hits]}
            proposal=ClaimProposal.model_validate(await ask('claims',payload))
            f,newchecks=assess(proposal,valid,incident,target);checks.extend(newchecks)
            nodes.append('executable_R00_R17')
            if not self.baseline:
                review=ClaimReview.model_validate(await ask('claim_reviewer',{**payload,'claim_proposal':proposal.model_dump(),'component_checks':checks}))
                findings=resolve_review(review,checks)
            else:nodes.append('baseline_no_model_reviewer')
            diagnosis=render(proposal,f,incident,target,hits,checks)
            accepted=all(c['verdict']=='PASS' for c in checks if c['component']=='cause')
            if not accepted:rejected.append({'claim_proposal':proposal.model_dump(),'component_checks':checks})
            if proposal.propose_action and not diagnosis.recovery_actions:
                checks.append({'rule_id':'R14','claim_id':'propose_action','component':'actions','verdict':'HOLD','reason':'조치 근거 또는 검색 절차 부족: 원인과 분리해 사람 확인'})
        except Exception as exc:
            reason=str(exc) if isinstance(exc,SafeAPIError) else 'TIMEOUT_NO_API_RETRY' if isinstance(exc,asyncio.TimeoutError) else 'INVALID_OR_FAILED_RESPONSE:'+type(exc).__name__
            errors.append(reason);checks.append({'rule_id':'R16','claim_id':'category','component':'cause','verdict':'HOLD','reason':reason})
            if proposal:rejected.append({'claim_proposal':proposal.model_dump(),'review_error':'REVIEW_NOT_COMPLETED'})
            diagnosis=abstain(reason,failed=True);accepted=False
        m=getattr(self.llm,'metrics',None)
        if m is not None:
            usage.api_calls=m['api_calls'];usage.local_cache_hits=m['local_cache_hits'];usage.price_date=m['price_date'];usage.service_tier=m.get('service_tier')
            usage.uncertain_reserved_usd=self.llm.ledger.uncertain_usd(trace)
            if m['usage_collected'] or not m['api_calls']:
                usage.input_tokens=m['input_tokens'];usage.output_tokens=m['output_tokens'];usage.tokens=usage.input_tokens+usage.output_tokens
                usage.cost=m['cost_usd'];usage.cost_basis='provider_token_usage_price_estimate' if m['api_calls'] else 'local_cache_or_no_request'
        usage.elapsed_seconds=round(time.monotonic()-start,6)
        violations=sorted({c['rule_id']+':'+c['claim_id'] for c in checks if c['component']=='cause' and c['verdict']!='PASS'})
        policy_hash=hashlib.sha256(self.policy.model_dump_json().encode()).hexdigest()
        return Report(trace_id=trace,incident_ref=incident,plan=None,evidence=items,retrieval_hits=[] if self.baseline else hits,diagnosis=diagnosis,
            review=Review(accepted=accepted,violations=violations,feedback=['원인·관측·조치는 별도 판정합니다. 모델 반례는 규칙으로 검증합니다. 독립 사람 검토는 별도입니다.'],revision_count=0,semantic_reviewer='none-baseline' if self.baseline else self.llm.model_id),
            errors=errors,usage=usage,node_trace=nodes,replan_count=0,revision_count=0,evidence_hash=content_hash(items),
            versions={'app':'0.3.1','model':self.llm.model_id,'retrieval':'none-catalog' if self.baseline else self.retriever.version,'project_policy_sha256':policy_hash,'review_policy':'R00-R17-v3-bounded-claims'},
            validation_scope={'llm':self.llm.model_id,'transport':self.tools.transport,'data':getattr(self.tools,'data_scope','synthetic_fixture_only'),
              'external_systems':getattr(self.tools,'external_systems','not_connected'),'human_review':'not_independently_performed'},
            rejected_candidates=rejected,output_diagnostics=getattr(self.llm,'diagnostics',[]),claim_proposal=proposal.model_dump() if proposal else None,component_reviews=checks,reviewer_findings=findings)

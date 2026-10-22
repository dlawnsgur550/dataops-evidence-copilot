"""Explicit paid pilot/final or free 500-case replay, one immutable first result.

Maximum this revision: 33 new provider requests and USD 0.012. Global monetary
and request caps are inherited unchanged from the shared lifetime ledger.
"""
import argparse
import asyncio
import hashlib
import json
import math
import time
from pathlib import Path
from dataops_copilot.api_safety import CostLedger, read_api_settings
from dataops_copilot.evaluation import BundleAdapter
from dataops_copilot.hybrid import HybridRunbooks
from dataops_copilot.llm import FakeLLM
from dataops_copilot.openai_llm import OpenAILLM
from dataops_copilot.retrieval import LocalRunbooks
from dataops_copilot.workflow import Limits
from dataops_copilot.workflow_v3 import ClaimCopilot

ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'evaluation/v3';OUT=ROOT/'artifacts/v3';RUNTIME=ROOT.parents[1]/'work/runtime'


def frozen_files():
    paths=[]
    for folder in ('src','config','evaluation/v3'):
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='freeze.json')
    paths.extend(ROOT/'scripts'/name for name in ('run_v3_evaluation.py','prepare_v3_evaluation.py','live_v3_scale.py','check_v3_counterexamples.py'))
    paths.extend(ROOT/name for name in ('pyproject.toml','uv.lock','deployment/embedding-model.json'))
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def freeze():
    p=DATA/'freeze.json'
    if p.exists():assert json.loads(p.read_text())['sha256']==frozen_files(),'FROZEN_IMPLEMENTATION_OR_DATA_CHANGED'
    else:p.write_text(json.dumps({'protocol':'v3-freeze-before-paid-final-no-post-final-tuning','sha256':frozen_files()},indent=2)+'\n')


def score(report,answer):
    d=report.diagnosis;expected=answer['category'];fault=expected not in ('NORMAL','UNKNOWN')
    checks={'category':d.category==expected,'required_citations':set(answer['required_evidence_ids']).issubset(d.evidence_ids),
      'cause_accepted':report.review.accepted,'status':d.diagnosis_status==('insufficient' if expected=='UNKNOWN' else 'supported'),
      'actions':bool(d.recovery_actions) if fault else not d.recovery_actions,'no_errors':not report.errors,
      'no_recovery_claim':report.recovered is None}
    if fault:
        checks['action_target']=all((a.target_ref.connection_id=='dbt_orders' if expected=='CONNECTION_FAILURE' else a.target_ref.table_id==answer['cause_elements']['table_id']) and a.kind==answer['action_kind'] and a.execution_mode=='human_only_text' and set(answer['required_evidence_ids']).issubset(a.evidence_ids) for a in d.recovery_actions)
    return {'passed':all(checks.values()),'checks':checks,'category':d.category,'usage':report.usage.model_dump(),'errors':report.errors}


def interval(k,n):
    if not n:return None
    z=1.96;p=k/n;den=1+z*z/n;mid=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [round(mid-half,4),round(mid+half,4)]


async def main(args):
    freeze();paid=args.phase in ('pilot','final');ledger=CostLedger(RUNTIME/'llm-cost.sqlite3',purpose='evaluation')
    before=ledger.summary();window=OUT/'cost-window.json'
    if paid:
        if not window.exists():window.write_text(json.dumps({'start':before,'max_new_requests':33,'max_new_usd':0.012,'model':'gpt-6-luna','shared_ledger':True},indent=2)+'\n')
        w=json.loads(window.read_text());key,_=read_api_settings(RUNTIME/'openai.env')
        llm=OpenAILLM(key,RUNTIME,purpose='evaluation',service_tier='flex');retriever=HybridRunbooks()
    else:llm=FakeLLM();retriever=LocalRunbooks()
    dest=OUT/args.phase;dest.mkdir(exist_ok=True);rows=[]
    answers=json.loads((DATA/('offline-answers.json' if args.phase=='offline' else 'answers.json')).read_text())
    specifications=[('H02',ROOT/'evaluation/v2-check/H02.json',{'case_id':'H02','category':'CONNECTION_FAILURE','required_evidence_ids':[], 'cause_elements':{'table_id':'raw.web_orders'},'action_kind':'connection_config'})] if args.phase=='pilot' else [(a['case_id'],DATA/('offline' if args.phase=='offline' else 'final')/(a['case_id']+'.json'),a) for a in answers]
    try:
        for cid,path,answer in specifications:
            bundle=json.loads(path.read_text());entry={'case':cid,'expected':answer['category']}
            for arm in (('baseline','full') if paid else ('full',)):
                p=dest/f'{cid}-{arm}.json'
                if p.exists():
                    from dataops_copilot.models import Report
                    report=Report.model_validate_json(p.read_text())
                else:
                    if paid:
                        now=ledger.summary();needed=2 if arm=='full' else 1
                        assert now['requests']+needed-w['start']['requests']<=w['max_new_requests'],'V3_REQUEST_WINDOW_EXHAUSTED'
                        # Each pair's conservative reserve remains inside existing ledger caps.
                        assert now['spent_or_reserved_usd']-w['start']['spent_or_reserved_usd']<w['max_new_usd']-0.003,'V3_COST_WINDOW_REACHED'
                    adapter=BundleAdapter(bundle)
                    report=await ClaimCopilot(adapter,llm,retriever,Limits(llm_calls=1 if arm=='baseline' else 2,llm_seconds=65,total_seconds=180),baseline=arm=='baseline').diagnose(adapter.incident)
                    p.write_text(report.model_dump_json(indent=2)+'\n')
                entry[arm]=score(report,answer);entry[arm+'_hash']=report.evidence_hash
                if paid and report.errors:raise RuntimeError('FIRST_RESULT_FAILED_STOP_NO_AUTOMATIC_RETRY:'+cid+':'+arm+':'+','.join(report.errors))
            if paid:assert entry['baseline_hash']==entry['full_hash'],'PAIRED_EVIDENCE_CONTENT_MISMATCH'
            rows.append(entry)
            if paid:print(json.dumps({'phase':args.phase,'case':cid,'baseline':entry['baseline']['passed'],'full':entry['full']['passed']},ensure_ascii=False),flush=True)
            result={'scope':'actual gpt-6-luna calls on frozen authored synthetic evidence; baseline=1 call/no retrieval, full=2 calls/local hybrid retrieval. NOT live-system calls and NOT a comparison across model families.' if paid else '500 generated synthetic evidence replays with FakeLLM, NOT real-model accuracy',
              'phase':args.phase,'cases':rows,'independent_human_review':'pending','cost_before':before,'cost_after':ledger.summary()}
            for arm in ('full','baseline') if paid else ('full',):
                k=sum(r[arm]['passed'] for r in rows);n=len(rows);result[arm+'_aggregate']={'passed':k,'total':n,'wilson_95_interval':interval(k,n),'caution':'authored correlated convenience sample, not population generalization'}
            (dest/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'phase':args.phase,'cases':len(rows),'passed':sum(r['full']['passed'] for r in rows),'ledger':ledger.summary()},ensure_ascii=False),flush=True)
    finally:
        if hasattr(retriever,'close'):retriever.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--phase',choices=('offline','pilot','final'),required=True);asyncio.run(main(p.parse_args()))

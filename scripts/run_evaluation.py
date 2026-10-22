"""Paid evaluation is opt-in, sequential and resumable; no automatic API retries."""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path

from dataops_copilot.api_safety import read_api_settings
from dataops_copilot.evaluation import BundleAdapter,baseline,scoring,verify_freeze
from dataops_copilot.hybrid import HybridRunbooks,evidence_query
from dataops_copilot.llm import FakeLLM
from dataops_copilot.models import Report
from dataops_copilot.openai_llm import OpenAILLM
from dataops_copilot.workflow import Copilot,Limits

ROOT=Path(__file__).resolve().parents[1]

async def main(args):
    freeze=verify_freeze(ROOT) if args.split=='final' else None
    if freeze and args.service_tier!=freeze['service_tier']:raise RuntimeError('FROZEN_SERVICE_TIER_MISMATCH')
    directory=ROOT/'artifacts/checkpoint4'/('final-evaluation' if args.split=='final' else 'development-api' if args.paid else 'development')
    directory.mkdir(parents=True,exist_ok=True)
    llm=FakeLLM()
    if args.paid:
        key,_=read_api_settings(Path(args.api_settings))
        llm=OpenAILLM(key,Path(args.api_settings).resolve().parent,purpose='evaluation',service_tier=args.service_tier)
    retriever=HybridRunbooks()
    answers=json.loads((ROOT/f'evaluation/private/{args.split}-answers.json').read_text())
    results=[]
    try:
        for answer in answers:
            case=answer['case_id']
            if args.case and case not in args.case:continue
            bundle=json.loads((ROOT/f'evaluation/{args.split}/{case}.json').read_text())
            adapter=BundleAdapter(bundle)
            retrieval=await retriever.search(evidence_query(adapter.evidence))
            ranking=dict(retriever.last_ranking)
            output=directory/f'{case}-final.json'
            if output.exists():
                report=Report.model_validate_json(output.read_text())
                if report.incident_ref.execution_key()!=adapter.incident.execution_key():raise RuntimeError('SAVED_EVALUATION_INPUT_MISMATCH')
                if report.versions.get('model')!=llm.model_id:raise RuntimeError('SAVED_EVALUATION_MODEL_MISMATCH')
            else:
                report=await Copilot(adapter,llm,retriever=retriever,limits=Limits(llm_calls=4,llm_seconds=65,total_seconds=300,retry_delays=(0,0))).diagnose(adapter.incident)
                output.write_text(report.model_dump_json(indent=2)+'\n')
            row={'case_id':case,'final':scoring(answer,report),'retrieval_hit_at_3':bool(set(answer['allowed_document_ids'])&{h.doc_id for h in retrieval}),
                 'retrieval_ranking':ranking,'final_usage':report.usage.model_dump(),'final_category':report.diagnosis.category,'expected_category':answer['category'],'errors':report.errors,'review_violations':report.review.violations}
            if args.paid and args.baseline:
                path=directory/f'{case}-baseline.json'
                if path.exists():base=Report.model_validate_json(path.read_text())
                else:
                    base=await baseline(llm,report)
                    path.write_text(base.model_dump_json(indent=2)+'\n')
                row.update(baseline=scoring(answer,base),baseline_usage=base.usage.model_dump(),baseline_category=base.diagnosis.category,baseline_errors=base.errors)
            results.append(row)
            summary={'split':args.split,'model':llm.model_id,'service_tier':args.service_tier if args.paid else None,'freeze_id':freeze['freeze_id'] if freeze else None,'cases':results,'scope':'synthetic fixed evidence replay; gold read only by scorer; no live system queries','baseline':'one model call, same actually collected evidence, empty fixed identifier catalog, no retrieved text' if args.baseline else None}
            (directory/'results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({'case':case,'category':row['final_category'],'structural_pass':row['final']['structural_pass'],'new_api_calls_for_report':report.usage.api_calls,'baseline_category':row.get('baseline_category'),'errors':row['errors']},ensure_ascii=False),flush=True)
            if args.paid and any('CAP' in err or 'CIRCUIT_BREAKER' in err or 'RESERVATION_RETAINED' in err for err in report.errors+row.get('baseline_errors',[])):
                raise RuntimeError('PAID_EVALUATION_STOPPED_ON_COST_OR_PROVIDER_BOUNDARY')
    finally:retriever.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--split',choices=['dev','final'],default='dev')
    parser.add_argument('--case',action='append')
    parser.add_argument('--paid',action='store_true')
    parser.add_argument('--baseline',action='store_true')
    parser.add_argument('--api-settings')
    parser.add_argument('--service-tier',choices=['default','flex'],default='flex')
    args=parser.parse_args()
    if args.paid and not args.api_settings:parser.error('Explicit --api-settings required')
    if args.split=='final' and not args.paid:parser.error('Final model comparison requires explicitly paid mode; use dev for mock checks')
    asyncio.run(main(args))

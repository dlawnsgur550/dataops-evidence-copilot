"""Default: one model call + mandatory code gates, fixed procedure catalog.

--full selects the separately evaluated two-call hybrid-RAG + reviewer arm.
Default remains the free deterministic test double. No API key is a CLI value.
"""
import argparse
import asyncio
import json
from pathlib import Path
from dataops_copilot.api_safety import read_api_settings
from dataops_copilot.evaluation import BundleAdapter
from dataops_copilot.fixtures import FixtureAdapter, incident_for
from dataops_copilot.llm import FakeLLM
from dataops_copilot.mcp_client import open_live_mcp, open_mcp
from dataops_copilot.models import IncidentRef, Report
from dataops_copilot.openai_llm import OpenAILLM
from dataops_copilot.replay import ReportReplay
from dataops_copilot.retrieval import LocalRunbooks
from dataops_copilot.settings_policy import ProjectPolicy
from dataops_copilot.workflow import Limits
from dataops_copilot.workflow_v3 import ClaimCopilot


async def main(args):
    llm=FakeLLM();retriever=LocalRunbooks()
    if args.paid:
        key,_=read_api_settings(args.api_settings)
        llm=OpenAILLM(key,args.api_settings.resolve().parent,purpose=args.budget_profile,service_tier='flex')
    if args.full:
        from dataops_copilot.hybrid import HybridRunbooks
        retriever=HybridRunbooks()
    async def diagnose(tools,incident):
        return await ClaimCopilot(tools,llm,retriever,Limits(llm_calls=2 if args.full else 1,llm_seconds=65,total_seconds=180),ProjectPolicy.load(args.project_policy),baseline=not args.full).diagnose(incident)
    try:
        if args.replay_report:
            source=Report.model_validate_json(args.replay_report.read_text())
            report=await diagnose(ReportReplay(source),source.incident_ref)
        elif args.settings:
            incident=IncidentRef.model_validate_json(args.incident.read_text())
            async with open_live_mcp(args.settings) as tools:report=await diagnose(tools,incident)
        else:
            async with open_mcp(args.fixture) as tools:report=await diagnose(tools,incident_for(args.fixture))
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            # Reports are user-selected outputs; never overwrite a first result implicitly.
            with args.output.open('x') as f:f.write(report.model_dump_json(indent=2)+'\n')
        print(json.dumps({'profile':'full-2-call-hybrid-review' if args.full else 'economy-1-call-code-gates','category':report.diagnosis.category,'accepted':report.review.accepted,'usage':report.usage.model_dump(),'errors':report.errors,'model':llm.model_id,'external_scope':report.validation_scope},ensure_ascii=False,indent=2))
        return 0 if report.review.accepted else 2
    finally:
        if hasattr(retriever,'close'):retriever.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture',choices=('schema','quality','connection','normal','insufficient'),default='connection')
    p.add_argument('--full',action='store_true');p.add_argument('--paid',action='store_true')
    p.add_argument('--api-settings',type=Path);p.add_argument('--budget-profile',choices=('standard','evaluation'),default='standard')
    p.add_argument('--project-policy',type=Path);p.add_argument('--settings',type=Path);p.add_argument('--incident',type=Path)
    p.add_argument('--replay-report',type=Path);p.add_argument('--output',type=Path)
    args=p.parse_args()
    if args.paid and not args.api_settings:p.error('--paid requires an explicit --api-settings PATH, never a key value')
    if args.api_settings and not args.paid:p.error('--api-settings requires --paid')
    if args.settings and (not args.incident or args.replay_report):p.error('--settings requires --incident and excludes --replay-report')
    raise SystemExit(asyncio.run(main(args)))

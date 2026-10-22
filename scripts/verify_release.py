"""Free replay of both profiles. Never reads API settings or invokes a provider."""
import argparse
import asyncio
import json
from pathlib import Path
from dataops_copilot.evaluation import BundleAdapter
from dataops_copilot.llm import FakeLLM
from dataops_copilot.retrieval import LocalRunbooks
from dataops_copilot.workflow import Limits
from dataops_copilot.workflow_v3 import ClaimCopilot

ROOT=Path(__file__).resolve().parents[1]


async def main(args):
    gold={x['case_id']:x for x in json.loads((ROOT/'evaluation/v3/offline-answers.json').read_text())};rows=[]
    for path in sorted((ROOT/'evaluation/v3/offline').glob('*.json')):
        adapter=BundleAdapter(json.loads(path.read_text()))
        for base in (True,False):
            r=await ClaimCopilot(adapter,FakeLLM(),LocalRunbooks(),Limits(llm_calls=1 if base else 2),baseline=base).diagnose(adapter.incident)
            rows.append({'case':path.stem,'profile':'economy' if base else 'full','passed':r.review.accepted and r.diagnosis.category==gold[path.stem]['category'] and not r.errors})
    result={'scope':'500 correlated generated bundles, both FakeLLM profiles; NOT model accuracy','bundles':500,'checks':len(rows),'passed':sum(r['passed'] for r in rows),'api_calls':0,'rows':rows}
    if args.output:
        with args.output.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}));assert all(r['passed'] for r in rows)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);asyncio.run(main(p.parse_args()))

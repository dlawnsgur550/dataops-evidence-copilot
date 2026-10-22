"""v2.1 offline regression only. Paid v2 runner/source/results are archived."""
import argparse
import asyncio
import json
from pathlib import Path

from dataops_copilot.evaluation import BundleAdapter
from dataops_copilot.hybrid import HybridRunbooks
from dataops_copilot.llm import FakeLLM
from dataops_copilot.workflow import Copilot, Limits

ROOT=Path(__file__).resolve().parents[1]

async def main():
    retriever=HybridRunbooks();rows=[]
    try:
        for split in ('dev','final','v2-check'):
            for path in sorted((ROOT/'evaluation'/split).glob('*.json')):
                adapter=BundleAdapter(json.loads(path.read_text()))
                report=await Copilot(adapter,FakeLLM(),retriever,Limits(llm_calls=4,retry_delays=(0,0))).diagnose(adapter.incident)
                assert report.review.accepted and not report.errors,(path.name,report.review.violations,report.errors)
                rows.append({'split':split,'case':path.stem,'category':report.diagnosis.category,'api_calls':0})
        dest=ROOT/'artifacts/revision-v2.1';dest.mkdir(exist_ok=True)
        (dest/'offline-contract-check.json').write_text(json.dumps({'scope':'FakeLLM contract regression only, not model accuracy','passed':len(rows),'cases':rows,'api_calls':0},indent=2)+'\n')
        print(json.dumps({'offline_contract_cases':len(rows),'passed':len(rows),'api_calls':0}))
    finally:retriever.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--offline',action='store_true');parser.parse_args();asyncio.run(main())

"""Bounded paired check. Full frozen inputs independent of collector success."""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from dataops_copilot.api_safety import read_api_settings,SafeAPIError
from dataops_copilot.evaluation import BundleAdapter,baseline,scoring
from dataops_copilot.hybrid import HybridRunbooks,evidence_query
from dataops_copilot.llm import FakeLLM
from dataops_copilot.models import Report
from dataops_copilot.openai_llm import OpenAILLM
from dataops_copilot.workflow import Copilot,Limits

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'artifacts/revision-v2'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_files():
    selected=[]
    for folder in ('src','tests','evaluation/v2-check'):
        selected.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    selected += [ROOT/name for name in ('evaluation/private/v2-check-answers.json','evaluation/V2_PROTOCOL.md','deployment/embedding-model.json','scripts/run_v2_check.py','pyproject.toml','uv.lock')]
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted(selected)}


def freeze():
    path=ROOT/'evaluation/v2-freeze.json'
    assert not path.exists(), 'ALREADY_FROZEN_PRESERVE_RESULTS'
    hashes=frozen_files()
    record={'sha256':hashes,'freeze_id':hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest(),
        'model':'gpt-6-luna','service_tier':'flex','max_new_calls':10,'max_report_calls':4,
        'scope':'2 newly authored synthetic paired smoke cases, not an independent accuracy benchmark'}
    path.write_text(json.dumps(record,indent=2)+'\n')
    return record


def verify():
    record=json.loads((ROOT/'evaluation/v2-freeze.json').read_text())
    if record['sha256']!=frozen_files():raise RuntimeError('V2_FREEZE_CHANGED_NO_REQUEST_SENT')
    return record


async def main(args):
    DEST.mkdir(parents=True,exist_ok=True)
    if args.freeze:
        print(json.dumps(freeze()));return
    if args.offline:
        retriever=HybridRunbooks()
        rows=[]
        try:
            for split in ('dev','final','v2-check'):
                for path in sorted((ROOT/'evaluation'/split).glob('*.json')):
                    adapter=BundleAdapter(json.loads(path.read_text()))
                    r=await Copilot(adapter,FakeLLM(),retriever,Limits(llm_calls=4,retry_delays=(0,0))).diagnose(adapter.incident)
                    assert r.review.accepted,(path.name,r.review.violations)
                    assert not r.errors,(path.name,r.errors)
                    rows.append({'split':split,'case':path.stem,'category':r.diagnosis.category,'review_accepted':r.review.accepted,'paid_calls':0})
            (DEST/'offline-contract-check.json').write_text(json.dumps({'scope':'deterministic fake contract checks, not model accuracy','cases':rows,'passed':len(rows),'api_calls':0},indent=2)+'\n')
            print(json.dumps({'offline_contract_cases':len(rows),'passed':len(rows),'paid_calls':0}))
        finally:retriever.close()
        return
    record=verify()
    expected=ROOT.parents[1]/'work/runtime/openai.env'
    if not args.api_settings or Path(args.api_settings).resolve()!=expected.resolve():raise RuntimeError('EXPLICIT_EXISTING_SHARED_SETTINGS_REQUIRED')
    key,_=read_api_settings(expected)
    llm=OpenAILLM(key,expected.parent,purpose='evaluation',service_tier='flex')
    with llm.ledger.connect() as conn:
        old=conn.execute('SELECT count(*),coalesce(sum(charge),0) FROM requests').fetchone()
    initial_path=DEST/'paid-window.json'
    if initial_path.exists():
        initial=json.loads(initial_path.read_text());old=(initial['requests_before'],initial['nano_before'])
    else:
        initial={'requests_before':old[0],'nano_before':old[1],'max_new_calls':10,'same_ledger':True}
        initial_path.write_text(json.dumps(initial,indent=2)+'\n')
    original_complete=llm.complete
    async def bounded_complete(*a,**kw):
        verify()
        with llm.ledger.connect() as conn:count=conn.execute('SELECT count(*) FROM requests').fetchone()[0]
        if count-old[0]>=10:raise SafeAPIError('V2_TEN_REQUEST_WINDOW_CAP')
        role,prompt,payload=a
        if role=='inspector':
            prompt+='\nFor this frozen full-bundle comparison, select all four allowed tools exactly once in this order: get_dbt_artifacts, compare_schema, get_quality_profile, check_connection. This is an evaluation collection policy; the baseline independently receives the same full bundle.'
        if role=='rca' and len(payload.get('evidence',[]))!=5:
            raise SafeAPIError('V2_INCOMPLETE_COMPARISON_INPUT_NO_REQUEST_SENT')
        return await original_complete(role,prompt,payload,**kw)
    llm.complete=bounded_complete
    retriever=HybridRunbooks();rows=[]
    try:
        # Do not load scoring answers until all model outputs are saved.
        for path in sorted((ROOT/'evaluation/v2-check').glob('*.json')):
            bundle=json.loads(path.read_text());adapter=BundleAdapter(bundle)
            # Both arms receive exactly the full five observations, regardless of
            # the other arm's collector success. Output caps/model/tier are shared.
            bp=DEST/f'{path.stem}-baseline.json';fp=DEST/f'{path.stem}-final.json'
            if bp.exists():base=Report.model_validate_json(bp.read_text())
            else:
                base=await baseline(llm,evidence_bundle=bundle)
                bp.write_text(base.model_dump_json(indent=2)+'\n')
            if base.errors:raise RuntimeError('BASELINE_FAILED_PRESERVED_NO_RETRY')
            if fp.exists():final=Report.model_validate_json(fp.read_text())
            else:
                final=await Copilot(adapter,llm,retriever,Limits(llm_calls=4,llm_seconds=65,total_seconds=300,retry_delays=(0,0))).diagnose(adapter.incident)
                fp.write_text(final.model_dump_json(indent=2)+'\n')
            rows.append({'case_id':path.stem,'bundle_sha256':sha(path),'baseline_report_sha256':sha(bp),'final_report_sha256':sha(fp),
                'baseline_category':base.diagnosis.category,'final_category':final.diagnosis.category,
                'same_full_evidence':len(base.evidence)==len(final.evidence)==len(bundle['evidence']) and base.evidence_hash==final.evidence_hash,
                'baseline_usage':base.usage.model_dump(),'final_usage':final.usage.model_dump(),'errors':final.errors,'review_violations':final.review.violations})
            print(json.dumps({'case':path.stem,'baseline':base.diagnosis.category,'final':final.diagnosis.category,'same_full_evidence':rows[-1]['same_full_evidence'],'errors':final.errors},ensure_ascii=False),flush=True)
            # All errors stop the paid batch, including malformed output, refusal,
            # timeout, budget boundary and failed semantic review. No retry loop.
            if final.errors or not final.review.accepted:break
        answers={a['case_id']:a for a in json.loads((ROOT/'evaluation/private/v2-check-answers.json').read_text())}
        for row in rows:
            for arm in ('baseline','final'):
                report=Report.model_validate_json((DEST/f'{row["case_id"]}-{arm}.json').read_text())
                row[arm+'_score']=scoring(answers[row['case_id']],report)
        summary=llm.ledger.summary()
        result={'freeze_id':record['freeze_id'],'scope':record['scope'],'cases':rows,'requests_before':old[0],
            'new_requests':summary['requests']-old[0],'new_estimated_usd':round(summary['spent_or_reserved_usd']-old[1]/1e9,9),'ledger_after':summary,
            'independent_human_review_completed':False,'original_8_of_9_target_retested':False,'automatic_api_retries':0}
        (DEST/'paired-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:result[k] for k in ('new_requests','new_estimated_usd','independent_human_review_completed')}),flush=True)
    finally:retriever.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--offline',action='store_true');p.add_argument('--freeze',action='store_true');p.add_argument('--api-settings');asyncio.run(main(p.parse_args()))

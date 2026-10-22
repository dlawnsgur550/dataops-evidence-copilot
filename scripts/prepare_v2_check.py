"""Fresh authored smoke cases, separate scoring labels, no model calls."""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'evaluation/v2-check'

async def main():
    assert not DEST.exists(), 'PRESERVE_EXISTING_V2_CHECK'
    spec=importlib.util.spec_from_file_location('case_factory',ROOT/'scripts/prepare_evaluation.py')
    factory=importlib.util.module_from_spec(spec);spec.loader.exec_module(factory)
    # Both are newly authored after implementation. These two cases are a limited
    # smoke check, not an independent benchmark or an unseen real-world dataset.
    specifications=[('H01','quality',37,'raw.orders_archive','customer_id'),
                    ('H02','connection',38,'raw.web_orders',None)]
    DEST.mkdir(parents=True)
    gold=[]
    for cid,kind,variant,table,column in specifications:
        bundle,answer=await factory.create(cid,kind,variant,table,column)
        for e in bundle['evidence']:
            e['source']='synthetic-evaluation://v2-new-smoke'
            if e['kind']=='get_dbt_artifacts':
                d=e['data'];inv=d['invocation_id']
                d.update(artifact_status='complete',available_artifacts=['manifest','run_results'],missing_artifacts=[],
                         command='test' if kind=='quality' else 'run',exit_code=1 if kind=='quality' else 2,
                         stdout_invocation_ids=[inv],command_log_sha256=hashlib.sha256(cid.encode()).hexdigest())
                if kind=='connection':
                    d.update(artifact_status='partial',available_artifacts=['manifest'],missing_artifacts=['run_results'],run_results_invocation_id=None)
            if kind=='quality' and e['kind']=='get_quality_profile':
                e['data']['row_count']=1753
        bundle['provenance'].update(schema_version=2,scope='new authored synthetic smoke case; not independently sourced')
        (DEST/f'{cid}.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2)+'\n')
        gold.append(answer)
    (ROOT/'evaluation/private/v2-check-answers.json').write_text(json.dumps(gold,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'new_synthetic_smoke_cases':len(gold),'paid_calls':0}))

if __name__=='__main__':asyncio.run(main())

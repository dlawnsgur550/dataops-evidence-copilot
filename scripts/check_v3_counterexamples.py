"""Free generated rule counterexamples. This is NOT model accuracy."""
import asyncio
import json
import time
from collections import Counter
from copy import deepcopy
from pathlib import Path
from dataops_copilot.claim_contract import ClaimProposal
from dataops_copilot.claim_engine import assess, facts, integrity
from dataops_copilot.evaluation import BundleAdapter
from dataops_copilot.llm import FakeLLM
from dataops_copilot.settings_policy import ProjectPolicy

ROOT=Path(__file__).resolve().parents[1]


async def main():
    policy=ProjectPolicy.load();results=Counter();failed=[];start=time.monotonic()
    source=json.loads((ROOT/'evaluation/v2-check/H02.json').read_text());a=BundleAdapter(source)
    t=policy.select(a.incident.dag_id,'raw.web_orders')
    raw=await FakeLLM().complete('claims','',{'incident_ref':a.incident.model_dump(),'target_policy':t.model_dump(),'evidence':source['evidence']})
    base=ClaimProposal.model_validate(raw)
    variants=[('correct_conditional',None,None,None),('false_unknown','category','UNKNOWN','R09'),
      ('wrong_cause','category','NORMAL','R03'),('fabricated_id','evidence_ids',['invented'],'R02'),
      ('missing_citation','evidence_ids',[],'R02'),('false_file_present','artifact_coverage','complete','R07'),
      ('false_port','config_error','wrong_port','R05'),('false_equivalence','business_equivalence','equivalent','R12'),
      ('false_current','current_connection','unavailable','R04'),('false_no_current','current_connection','unknown',None)]
    for number in range(10000):
        name,field,value,rule=variants[number%len(variants)]
        proposal=base.model_copy(deep=True)
        if field:setattr(proposal,field,deepcopy(value))
        # Distinct execution/observation identifiers exercise binding while the
        # ten semantic templates remain correlated generated cases.
        evidence=[e.model_copy(deep=True) for e in a.evidence];i=a.incident.model_copy(deep=True)
        i.run_id='counterexample-'+str(number)
        for e in evidence:
            if e.target_ref.incident:e.target_ref.incident.run_id=i.run_id
        _,checks=assess(proposal,evidence,i,t)
        bad=[c for c in checks if c['verdict']!='PASS']
        ok=not bad if rule is None else any(c['rule_id']==rule for c in bad)
        results[name]+=int(ok)
        if not ok:failed.append({'index':number,'template':name,'checks':bad})
    result={'scope':'10000 generated rule checks over 10 correlated semantic templates, NOT independent incidents or LLM evaluations',
      'total':10000,'passed':sum(results.values()),'failures':failed[:20],'by_template':dict(results),
      'api_calls':0,'elapsed_seconds':round(time.monotonic()-start,3)}
    (ROOT/'artifacts/v3/counterexamples.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False));assert not failed

if __name__=='__main__':asyncio.run(main())

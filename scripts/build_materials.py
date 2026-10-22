"""Saved evidence -> reviewed tables and reproducible material index. No paid calls."""
from __future__ import annotations
import csv,hashlib,json,sqlite3,statistics,zipfile
from pathlib import Path

from dataops_copilot.api_safety import CostLedger,PRICE_DATE
from dataops_copilot.evaluation import verify_freeze

ROOT=Path(__file__).resolve().parents[1]
RECORDS=ROOT/'artifacts/checkpoint4'
EVALUATION=RECORDS/'final-evaluation'
RUNTIME=ROOT.parents[1]/'work/runtime'

# Codex compared all returned causes/actions above against the fixed observation records.
# This is an assisted evidence review, not an independent human or an additional LLM Judge.
REVIEW={
 'F01':(False,False,'최종: Inspector JSON 형식 오류로 수집 중단. 기준: 반환 계약 검증 실패. 둘 다 정답 원인을 제시하지 못함.'),
 'F02':(False,False,'최종: Inspector JSON 형식 오류. 기준은 같은 수집 접두부만 받아 dbt 산출물·schema 부족을 보류함. 원래 전체 bundle 기준의 진단은 충족하지 못함.'),
 'F03':(True,False,'최종은 선택 실행 unit_price 부재와 현재 archive schema 차이·대상·새 실행 검증을 구분함. 기준은 run_results 일부 누락을 확정했으나 이를 입증하는 누락 목록이나 partial 상태가 없음.'),
 'F04':(True,True,'선택 로그·dbt 검사에 order_id NULL 29건이 명시되고 현재 프로필도 별도 관측임. 두 방법 모두 올바른 테이블의 승인된 원천 정정과 재검증을 안내함. 기준의 후속 검증은 더 구체화할 여지가 있음.'),
 'F05':(True,True,'customer_id NULL 31건과 raw.web_orders 대상이 일치. 최종은 과거 실행과 현재 프로필을 구분하고 원본 보존·임의 키/삭제 금지·새 검증을 안내함. 전체 파이프라인 자료와 선택 명령의 요약은 구분해 해석함.'),
 'F06':(False,True,'최종은 raw.orders_archive/order_id NULL 33건을 맞혔지만 전체 태스크 상태가 없다는 이유로 부분 run_results 누락을 확정함. dbt 결과와 Airflow 태스크 상태의 자료 범위를 혼동한 근거 없는 추가 주장임. 기준은 누락 여부를 확인할 수 없다고 제한함.'),
 'F07':(True,True,'실패 로그와 같은 invocation의 dbt_orders 연결 거부를 인용. 호스트·포트를 단정하지 않고 실제 설정 점검과 사람의 재실행을 안내함. 기준의 집계·품질 검증 설명은 보완 여지가 있음.'),
 'F08':(True,True,'과거 dbt_orders 연결 거부와 현재 probe 성공을 구분하고 현재 성공만으로 복구를 확정하지 않음. 대상과 조건부 설정 점검이 적절함.'),
 'F09':(False,False,'최종은 의미 검토 거절 뒤 UNKNOWN으로 보류하여 원인 정답 기준 미충족. 기준은 run_results 부분 누락을 근거 없이 확정. 최종 거절 후보 원문은 저장되지 않아 Reviewer 피드백만으로 후보 전체의 정확성을 독립 재검증할 수 없음.'),
 'F10':(True,False,'최종은 모든 태스크·필수 두 테스트 성공을 NORMAL로 판정하고 조치 없음. 기준은 성공 증거만 있다는 이유로 UNKNOWN이라 정상 분류를 놓침. 양쪽 모두 불필요한 조치는 없음.'),
 'F11':(True,True,'선택 실행 상세 로그와 보관 산출물이 없어 UNKNOWN/insufficient, 조치 없음이 적절함. 현재 probe 성공을 과거 원인·복구로 사용하지 않음.'),
 'F12':(False,True,'최종은 JSON 오류로 failed 종료하여 안전하지만 기대한 정상적인 insufficient 처리에는 실패함. 기준은 UNKNOWN/insufficient와 조치 없음. 로그의 지시를 수행한 흔적은 없으나 이 한 사례로 일반 공격 내성을 입증하지 않음.'),
}

def main():
    freeze=verify_freeze(ROOT)
    data=json.loads((EVALUATION/'results.json').read_text());rows=data['cases']
    assert len(rows)==12
    reviews=[];table=[]
    for row in rows:
        case=row['case_id'];fpass,bpass,reason=REVIEW[case]
        for system,passed in [('final',fpass),('baseline',bpass)]:
            report=json.loads((EVALUATION/f'{case}-{system}.json').read_text())
            reviews.append({'case_id':case,'system':system,'structural_pass':row[system]['structural_pass'],'assisted_semantic_pass':passed,
                'reviewer':'Codex evidence review; not independent human','reason':reason,'report_sha256':hashlib.sha256((EVALUATION/f'{case}-{system}.json').read_bytes()).hexdigest()})
        table.append({'case_id':case,'expected':row['expected_category'],'final_category':row['final_category'],'baseline_category':row['baseline_category'],
            'final_structural_pass':row['final']['structural_pass'],'baseline_structural_pass':row['baseline']['structural_pass'],
            'final_assisted_semantic_pass':fpass,'baseline_assisted_semantic_pass':bpass,'hit_at_3':row['retrieval_hit_at_3'],
            'final_cost_usd':row['final_usage']['cost'],'baseline_cost_usd':row['baseline_usage']['cost'],
            'final_seconds':row['final_usage']['elapsed_seconds'],'baseline_seconds':row['baseline_usage']['elapsed_seconds'],
            'failure_codes':' / '.join(row['errors']+row['review_violations']),'review_reason':reason})
    (EVALUATION/'assisted-evidence-review.json').write_text(json.dumps({'reviewer':'Codex; no independent human evaluation','first_run_results_preserved':True,'cases':reviews},ensure_ascii=False,indent=2)+'\n')
    with (EVALUATION/'comparison.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
    with (EVALUATION/'independent-human-review-template.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.DictWriter(handle,fieldnames=['case_id','system','report_sha256','human_verdict','human_reason','reviewer_name','reviewed_at']);writer.writeheader()
        for review in reviews:writer.writerow({k:review[k] for k in ('case_id','system','report_sha256')})
    metrics=json.loads((RECORDS/'evaluation-metrics.json').read_text())
    faults=[r for r in rows if r['expected_category'] not in ('NORMAL','UNKNOWN')]
    for system,index in [('final',0),('baseline',1)]:
        metrics[system]['assisted_semantic_fault_correct']=sum(REVIEW[r['case_id']][index] for r in faults)
        metrics[system]['assisted_semantic_nonfault_correct']=sum(REVIEW[r['case_id']][index] for r in rows if r not in faults)
        metrics[system]['no_actions_on_nonfaults']=sum(not json.loads((EVALUATION/f'{r["case_id"]}-{system}.json').read_text())['diagnosis']['recovery_actions'] for r in rows if r not in faults)
    metrics['independent_human_review_completed']=False
    metrics['target_8_of_9_met']=False
    metrics['no_claim_of_accuracy_improvement']=True
    (RECORDS/'evaluation-metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n')
    ledger=CostLedger(RUNTIME/'llm-cost.sqlite3',purpose='evaluation')
    cost=ledger.summary()
    with sqlite3.connect(ledger.path) as db:
        totals=db.execute('SELECT tier,count(*),sum(input_tokens),sum(output_tokens),sum(charge) FROM requests GROUP BY tier ORDER BY tier').fetchall()
    cost.update(price_date=PRICE_DATE,cost_basis='provider_token_usage_price_estimate_not_account_invoice',tiers=[{'service_tier':r[0],'requests':r[1],'input_tokens':r[2],'output_tokens':r[3],'estimated_usd':r[4]/1e9} for r in totals],
      checkpoint3_prior_estimated_usd=0.00264445,current_checkpoint_added_estimated_usd=round(cost['spent_or_reserved_usd']-0.00264445,9))
    (RECORDS/'cost-summary.json').write_text(json.dumps(cost,ensure_ascii=False,indent=2)+'\n')
    with zipfile.ZipFile(RECORDS/'frozen-evaluation-source.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for relative in freeze['sha256']:archive.write(ROOT/relative,relative)
        for path in (ROOT/'scripts').glob('*.py'):archive.write(path,str(path.relative_to(ROOT)))
        archive.write(ROOT/'evaluation/freeze.json','evaluation/freeze.json')
        archive.write(ROOT/'evaluation/dataset-manifest.json','evaluation/dataset-manifest.json')
    print(json.dumps({'first_final_cases':len(rows),'structural_faults_final':metrics['final']['fault_correct_structural'],'assisted_semantic_faults_final':metrics['final']['assisted_semantic_fault_correct'],'assisted_semantic_faults_baseline':metrics['baseline']['assisted_semantic_fault_correct'],'hit_at_3':metrics['retrieval']['hit_at_3'],'estimated_total_usd':cost['spent_or_reserved_usd'],'api_calls_added':0},ensure_ascii=False))

if __name__=='__main__':main()

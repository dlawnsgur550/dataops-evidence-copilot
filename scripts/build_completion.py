"""Build a local evidence report and an explicitly blank human review form."""
import hashlib
import html
import json
import statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/v3.1'
def read(p):return json.loads((ROOT/p).read_text())
def save(p,d):(ROOT/p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def esc(v):return html.escape(str(v))


def main():
    final=read('artifacts/v3/final/summary.json');targeted=read('artifacts/v3.1/targeted/summary.json')
    cost=read('artifacts/v3.1/cost-final.json');scale=read('artifacts/v3.1/scale/live-e2e.json')
    offline=read('artifacts/v3.1/offline-matrix.json');counter=read('artifacts/v3/counterexamples.json')
    comparison={}
    for arm in ('baseline','full'):
        rows=[x[arm] for x in final['cases']]
        comparison[arm]={'passed':sum(r['passed'] for r in rows),'total':10,'category_matches':sum(r['checks']['category'] for r in rows),'cost_usd':round(sum(r['usage']['cost'] for r in rows),9),'mean_seconds':round(statistics.mean(r['usage']['elapsed_seconds'] for r in rows),3)}
    reports=[];review=[];findings=[]
    for p in sorted((ROOT/'artifacts/v3/final').glob('*-full.json'))+sorted((OUT/'targeted').glob('I*-economy.json')):
        d=json.loads(p.read_text());cid=p.stem.split('-')[0];sha=hashlib.sha256(p.read_bytes()).hexdigest();source=str(p.relative_to(ROOT))
        reports.append({'case':cid,'path':source,'sha256':sha,'report':d});findings+=d['reviewer_findings']
        review.append({'case':cid,'source':source,'source_sha256':sha,'reviewer':'Codex AI','independent_human':False,'verdict':'REJECT' if cid in ('Z09','Z10') else 'PASS',
          'basis':'판단 보류는 맞지만 unavailable 자료를 성공 근거로 인용하여 R02 위반. 최초 결과를 보존합니다.' if cid in ('Z09','Z10') else '실행 근거와 구조화 주장·보류·조건부 조치를 대조했습니다. 실제 복구 완료 주장은 없습니다.',
          'cause_pointer':'/diagnosis/cause','cause_quote':d['diagnosis']['cause'],'claim_pointer':'/claim_proposal','claim':d['claim_proposal'],
          'component_rejections':[c for c in d['component_reviews'] if c['verdict']!='PASS'],'review_scope':'canonical diagnosis text and actions; rejected observation proposals are quarantined separately',
          'execution_ref':d['incident_ref'],'evidence_refs':[{'id':e['evidence_id'],'kind':e['kind'],'status':e['status'],'scope':e['temporal_scope']} for e in d['evidence']]})
    save('artifacts/v3.1/ai-evidence-review.json',{'reviewer':'Codex AI','independent_human_review':False,'entries':review})
    save('artifacts/v3.1/human-review-template.json',{'status':'pending','reviewer':None,'cases':[{'case':r['case'],'source':r['path'],'source_sha256':r['sha256'],'cause':None,'observations':None,'actions':None,'notes':''} for r in reports]})
    added=round(cost['spent_or_reserved_usd']-0.015592371,9)
    summary={'version':'0.3.1','stage_1':'bounded claims, component gates, conditional human actions, candidate preservation',
      'stage_2':{'generated_rule_checks':counter['total'],'passed':counter['passed'],'semantic_templates':10,'not_independent_incidents':True},
      'stage_3':{'config':'config/project.json','live_rows_per_run':100000,'runs':len(scale['runs']),'recoveries':len(scale['recoveries']),'success':scale['success'],'llm':'FakeLLM','offline_bundles':500,'profile_checks':offline['checks'],'profile_passed':offline['passed']},
      'stage_4':{'model':'gpt-6-luna','comparison':comparison,'default_selected':'economy: one call + mandatory code gates','model_families_compared':1},
      'stage_5':{'v3_0_all_component_passed_full':7,'v3_0_first_final':'8/10 both arms; new authored synthetic fixed evidence; not independent real incidents','wilson_95_interval':[0.4902,0.9433],
        'v3_1_targeted':{'passed':targeted['passed'],'total':2,'scope':'abstention and successful-ID contract only; one current-observation citation is separately rejected; NOT a full-suite score','all_component_passed':1},
        'reviewer_findings':len(findings),'verified':sum(x['status']=='verified' for x in findings),'unsubstantiated':sum(x['status']=='unsubstantiated' for x in findings),'ai_evidence_review':'completed','independent_human_review':'pending'},
      'billing':{'additional_requests':35,'additional_estimated_usd':added,'lifetime':cost,'invoice_actual':'not fetched; token-usage price estimate'},'production_approval':False,'presentation_created':False}
    save('artifacts/v3.1/completion.json',summary)
    assets=ROOT/'report-assets';assets.mkdir(exist_ok=True)
    (assets/'review-data.js').write_text('const REPORTS = '+json.dumps(reports,ensure_ascii=False)+';\n')
    head='<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="report-assets/report.css">'
    table=''.join(f"<tr><td>{esc(x['case'])}</td><td>{esc(x['expected'])}</td><td>{'통과' if x['baseline']['passed'] else '실패'}</td><td>{'통과' if x['full']['passed'] else '실패'}</td><td><a href='artifacts/v3/final/{x['case']}-full.json'>원본 JSON</a></td></tr>" for x in final['cases'])
    c=comparison
    page=f'''<!doctype html><html lang="ko">{head}<title>DataOps Copilot v3.1 완료 기록</title>
<header><div class="wrap"><span class="tag">DATAOPS / v3.1 / 2026-10-22</span><h1>근거를 확인하고,<br>확인된 만큼만 판단합니다.</h1><p>주장 구조 → 무료 반례 → 설정·대용량 → 실제 호출 비교 → 새 평가·검토 자료</p><a class="button" href="REVIEW.html">사람 검토표 열기</a> <a href="README.md">설치·실행 안내</a></div></header>
<main class="wrap"><div class="cards"><article><small>실제 로컬 데이터</small><strong>100,000행</strong><span>100배 확대 · 7회 실행 · 새 실행 복구 3건</span></article><article><small>무료 반례 검사</small><strong>10,000건</strong><span>10개 의미 유형의 변형 · 독립 장애 표본 아님</span></article><article><small>추가 API 추정 비용</small><strong>${added:.9f}</strong><span>35회 · 같은 장부 유지 · 미확정 청구 0건</span></article></div>
<section><h2>바뀐 판단 방식</h2><div class="flow"><b>조회 전용 수집</b><b>구조화 주장</b><b>18개 규칙</b><b>조건부 사람 조치</b></div><p>모델은 범주·근거 ID·현재 연결·산출물 범위 등 정해진 항목을 선택합니다. 프로그램은 증거와 대조한 문장만 출력합니다. 원인·현재 관측·조치는 따로 판정하며, 근거 없는 Reviewer 반례는 기록 후 차단합니다.</p><p>예: 과거 연결 거부와 현재 연결 성공은 동시에 참일 수 있습니다. “설정 오류가 확인되면 개발자가 수정하고, 확인되지 않으면 유지”하는 절차는 현재 설정 오류의 확정이 아닙니다.</p></section>
<section><h2>같은 증거로 비교한 결과</h2><div class="scroll"><table><tr><th>방식</th><th>진단·조치 기준</th><th>10건 추정 비용</th><th>평균 시간</th></tr><tr><td>기본: 모델 1회 + 코드 검사</td><td>8 / 10</td><td>${c['baseline']['cost_usd']:.9f}</td><td>{c['baseline']['mean_seconds']}초</td></tr><tr><td>추가: 모델 2회 + Hybrid RAG·Reviewer</td><td>8 / 10</td><td>${c['full']['cost_usd']:.9f}</td><td>{c['full']['mean_seconds']}초</td></tr></table></div><p>모두 gpt-6-luna이며 다른 모델 계열의 우열 비교가 아닙니다. 추가 Reviewer의 품질 이득이 없어 기본 실행을 1회 호출로 정했습니다. 방식 선택과 성능 확인에 같은 작은 비교 표본을 사용했습니다.</p><p class="notice">최초 최종 결과는 8/10으로 보존했습니다. 2건은 조회 실패 자료를 성공 근거로 인용한 문제였습니다. v3.1에서 성공 ID만 응답 선택지로 허용했고, 새 보류 사례는 실제 모델로 2/2 통과했습니다. 전체 10/10으로 합산하지 않습니다. 새 2건 중 1건은 현재 연결 관측의 인용이 빠져 해당 관측만 별도 거절됐습니다. 모든 구성요소 기준으로는 1/2입니다.</p></section>
<section><h2>최초 10건 결과</h2><div class="scroll"><table><tr><th>사례</th><th>기대 범주</th><th>기본</th><th>추가</th><th>증거</th></tr>{table}</table></div><p>직접 만든 합성 자료입니다. 8/10의 Wilson 95% 구간은 약 49.0~94.3%로 넓습니다. 상관된 편의 표본이므로 현업 모집단의 신뢰 구간으로 해석하지 않습니다. 원인·조치 기준과 관측 주장의 통과를 구분합니다. 최초 추가 방식에서 모든 관측 인용까지 통과한 사례는 7/10입니다. 새 버전의 전체 실제 모델 재평가는 아직 없습니다.</p></section>
<section><h2>실제 서비스·무료 검사의 범위</h2><ul><li>Airflow 2.10.4 · PostgreSQL 17.10 · dbt 1.9.10: 100,000행, 정상 1회·장애 3회·수정 후 새 실행 3회.</li><li>복구 판정은 새 실행 ID·수정 이후 시각·전체 태스크·필수 검사·집계 일치를 함께 확인합니다. 집계 {esc(scale['checks']['normal_aggregate']['raw_sum'])}, NULL·중복 0.</li><li>실제 서비스 진단 모델은 무료 FakeLLM입니다. Luna 비교는 고정 합성 증거 재생입니다.</li><li>무료 합성 증거 500개 × 두 방식 = {offline['passed']}/{offline['checks']} 통과. 1,000개의 독립 장애로 계산하지 않습니다.</li></ul><p><a href="artifacts/v3.1/scale/live-e2e.json">실제 실행 기록</a> · <a href="artifacts/v3.1/offline-matrix.json">무료 재생</a> · <a href="artifacts/v3.1/tests.xml">자동 테스트</a> · <a href="artifacts/v3.1/completion.json">전체 집계</a></p></section>
<section><h2>사람이 확인할 부분</h2><p>Codex AI의 근거 검토를 저장했습니다. 독립된 사람 검토는 아직 수행되지 않았습니다. 업무 의미·키 정책·운영 절차는 담당자의 근거와 승인이 필요하며, 현재 설정은 합성 데모의 계약입니다.</p><p>Reviewer 반례 {len(findings)}개 중 {sum(x['status']=='unsubstantiated' for x in findings)}개는 근거가 없었습니다. Reviewer 자체의 판단 능력이 해결됐다는 주장은 하지 않습니다. 유효한 코드 위반은 계속 차단합니다.</p><a class="button" href="REVIEW.html">원본 근거와 함께 검토하기</a> <a href="artifacts/v3.1/ai-evidence-review.json">AI 검토 기록</a></section>
<section><h2>비용·보안과 실행</h2><p>기본은 무료 테스트 대역입니다. 유료 호출은 명시적 실행에서만 가능하며 키는 별도 로컬 파일에서 읽습니다. 자동 재시도·고가 모델 전환·유료 임베딩은 없습니다. 기존 총액 $0.05, 일액 $0.02 상한과 장부를 유지했습니다.</p><p>누적 추정 비용 ${cost['spent_or_reserved_usd']:.9f}, 요청 {cost['requests']}/128회로 요청 한도를 소진했습니다. 저장 결과와 무료 검사는 계속 사용할 수 있습니다. 실제 청구서는 조회하지 않았습니다.</p><pre>uv sync --locked<br>uv run python scripts/run_economy.py --fixture connection<br>uv run python scripts/run_ui.py</pre><p>추가 방식은 <code>--full</code>로 선택합니다. 로컬 검색 모델을 먼저 준비해야 합니다. <a href="https://developers.openai.com/api/docs/pricing">공식 API 가격</a> · <a href="https://developers.openai.com/api/docs/models/gpt-6-luna">공식 Luna 문서</a> (2026-10-22 확인)</p></section><footer>발표자료는 만들지 않았습니다. 코드·평가·원본 결과·검토 재료를 제공합니다.</footer></main></html>'''
    (ROOT/'COMPLETION.html').write_text(page)
    reviewpage='''<!doctype html><html lang="ko">'''+head+'''<title>독립 사람 검토표</title><header><div class="wrap"><span class="tag">HUMAN REVIEW / 기본 상태: 미검토</span><h1>증거를 보고 직접 판정해 주세요.</h1><p>검토 도구이며 사람 검토 완료의 증거가 아닙니다.</p><a href="COMPLETION.html">완료 기록으로</a></div></header><main class="wrap"><section><h2>검토자와 판정 기준</h2><label>검토자 이름 <input id="reviewer" autocomplete="off"></label><p>선택 실행·시도·invocation·대상을 확인하고, 과거 실패와 현재 관측을 분리하세요. 실패한 조회 자료를 성공 근거로 인용하면 거절합니다. 조건부 조치는 현재 오류의 확정과 구분합니다. 업무 의미를 확인할 자료가 없으면 HOLD입니다.</p><p class="notice">PASS: 규칙·근거 충족 · REJECT: 확인된 위반 · HOLD: 필수 업무 정보 부족. 자동 승인은 없습니다. 입력은 현재 브라우저에만 저장하며 외부로 전송하지 않습니다.</p><label><input type="checkbox" id="attest"> 실제로 원본 근거와 규칙을 읽고 판단했습니다.</label></section><div id="cases"></div><section><button id="download">검토 JSON 내려받기</button><p id="status" aria-live="polite">모든 항목은 미검토입니다.</p></section></main><script src="report-assets/review-data.js"></script><script src="report-assets/review.js"></script></html>'''
    (ROOT/'REVIEW.html').write_text(reviewpage)
    print(json.dumps({'completion':'COMPLETION.html','human_review':'REVIEW.html','additional_estimated_usd':added,'independent_human_review':'pending'},ensure_ascii=False))

if __name__=='__main__':main()

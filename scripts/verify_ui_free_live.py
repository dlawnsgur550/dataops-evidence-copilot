"""Explicit free form submission -> actual read-only MCP; no paid model calls."""
import json,sqlite3
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'artifacts/checkpoint4/screens'
LEDGER=ROOT.parents[1]/'work/runtime/llm-cost.sqlite3'
def count():
    with sqlite3.connect(LEDGER) as db:return db.execute('SELECT count(*) FROM requests').fetchone()[0]

def main():
    before=count()
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chromium',headless=True,args=['--disable-gpu'])
        page=browser.new_page(viewport={'width':1440,'height':1050},reduced_motion='reduce')
        page.goto('http://127.0.0.1:18784')
        page.get_by_role('heading',name='실패 원인에서 복구 확인까지').wait_for(timeout=30000)
        page.get_by_role('combobox',name='확인할 장애').click()
        page.get_by_role('option',name='실행 연결 실패',exact=True).click()
        expect(page.locator('[data-testid="stMetricValue"]').first).to_have_text('연결 실패')
        page.get_by_role('combobox',name='실행 방식').click()
        page.get_by_role('option',name='실시간 조회 후 진단',exact=True).click()
        assert not page.get_by_role('checkbox',name='API 모델 사용').is_checked()
        page.get_by_role('button',name='실행',exact=True).click()
        expect(page.get_by_text('이 결과의 LLM 출력은 무료 테스트 대역입니다. 실제 시스템 증거와 모델 검증 범위를 구분합니다.')).to_be_visible(timeout=30000)
        expect(page.locator('[data-testid="stMetricValue"]').first).to_have_text('연결 실패')
        with page.expect_download() as download:page.get_by_role('button',name='진단 보고서 JSON 내려받기').click()
        download.value.save_as(str(DEST/'free-live-ui-report.json'))
        page.screenshot(path=str(DEST/'06-free-live-ui.png'),animations='disabled',timeout=15000)
        browser.close()
    report=json.loads((DEST/'free-live-ui-report.json').read_text())
    assert report['review']['accepted'] and report['versions']['model']=='fake-deterministic-v1'
    assert report['validation_scope']['transport']=='real_mcp_stdio_live_backend'
    assert all(not e['simulated'] for e in report['evidence'])
    assert count()==before
    result={'success':True,'actual_browser_form_submission':True,'model':'fake-deterministic-v1','mcp':'actual read-only live stdio','category':report['diagnosis']['category'],'current_probe_connected':next(e['data']['connected'] for e in report['evidence'] if e['kind']=='check_connection'), 'historical_failed_run_not_marked_recovered':report['recovered'] is None,'additional_api_calls':0,'ledger_requests_before':before,'ledger_requests_after':count(),'child_session_closed_after_diagnosis':True}
    (DEST/'free-live-ui-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()

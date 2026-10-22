"""Actual local Streamlit browser capture and no-billing refresh/download check."""
import json
import sqlite3
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'artifacts/checkpoint4/screens'
LEDGER=ROOT.parents[1]/'work/runtime/llm-cost.sqlite3'

def calls():
    with sqlite3.connect(LEDGER) as db:return db.execute('SELECT count(*) FROM requests').fetchone()[0]

def main():
    DEST.mkdir(parents=True,exist_ok=True)
    before=calls()
    console=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,channel='chromium',args=['--disable-gpu'])
        page=browser.new_page(viewport={'width':1440,'height':1050},device_scale_factor=1,reduced_motion='reduce')
        page.on('pageerror',lambda err:console.append(str(err)))
        page.goto('http://127.0.0.1:18784',wait_until='domcontentloaded')
        expect(page.get_by_role('heading',name='실패 원인에서 복구 확인까지')).to_be_visible(timeout=30000)
        expect(page.locator('[data-testid="stMetricValue"]').first).to_have_text('스키마 변경',timeout=15000)
        page.screenshot(path=str(DEST/'01-schema-diagnosis.png'),animations='disabled',timeout=15000)
        page.get_by_role('tab',name='수집 근거').click()
        page.locator('[data-testid="stExpander"]').first.click()
        page.screenshot(path=str(DEST/'02-evidence.png'),animations='disabled',timeout=15000)
        page.get_by_role('tab',name='복구 확인').click()
        expect(page.get_by_text('별도 후속 실행의 전체 태스크·품질 검사·집계가 통과했습니다.')).to_be_visible(timeout=15000)
        page.screenshot(path=str(DEST/'03-recovery.png'),animations='disabled',timeout=15000)
        selector=page.get_by_role('combobox',name='확인할 장애')
        for title,name,expected in [('필수 키 누락','04-quality.png','데이터 품질'),('실행 연결 실패','05-connection.png','연결 실패')]:
            selector.click()
            page.get_by_role('option',name=title,exact=True).click()
            expect(page.locator('[data-testid="stMetricValue"]').first).to_have_text(expected,timeout=15000)
            page.get_by_role('tab',name='원인과 조치').click()
            page.screenshot(path=str(DEST/name),animations='disabled',timeout=15000)
        with page.expect_download() as download:
            page.get_by_role('button',name='진단 보고서 JSON 내려받기').click()
        download.value.save_as(str(DEST/'downloaded-report.json'))
        page.reload(wait_until='domcontentloaded')
        expect(page.get_by_role('heading',name='실패 원인에서 복구 확인까지')).to_be_visible(timeout=15000)
        browser.close()
    after=calls()
    assert before==after,'SCREEN_ACTION_TRIGGERED_API'
    assert not console,console
    result={'success':True,'actual_browser':'Playwright Chromium','viewport':[1440,1050],'api_calls_before':before,'api_calls_after':after,'additional_api_calls':after-before,'page_errors':console,'screenshots':[p.name for p in sorted(DEST.glob('*.png'))],'actions':['load stored result','change tabs','expand evidence','select three incidents','download JSON','reload browser']}
    (DEST/'browser-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()

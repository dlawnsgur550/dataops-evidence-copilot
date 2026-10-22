"""Integration boundaries introduced by consolidating both UIs."""
import hashlib
import json

import pytest

from dataops_copilot.models import Report
from dataops_copilot.ui_workspace import (
    ROOT, DATA, load_source, free_replay, inspect_claim, verify_recovery, model_records, task_states,
)


@pytest.mark.parametrize('case,category', [('connection','CONNECTION_FAILURE'),('schema','SCHEMA_CHANGE'),
    ('quality','DATA_QUALITY'),('normal','NORMAL'),('insufficient','UNKNOWN')])
async def test_integrated_replay_is_free_and_keeps_case(case, category):
    report = await free_replay(case)
    assert report.diagnosis.category == category
    assert report.usage.api_calls == 0
    assert 'fake' in report.versions['model']
    assert report.incident_ref == load_source(case).incident_ref


async def test_uploaded_wrong_run_abstains():
    incident = load_source('connection').incident_ref.model_dump(mode='json')
    incident['run_id'] = 'not-the-source-run'
    report = await free_replay('connection', incident)
    assert report.diagnosis.category == 'UNKNOWN'
    assert report.errors
    assert not report.diagnosis.recovery_actions
    assert report.usage.api_calls == 0
    assert task_states(report) == {}


@pytest.mark.parametrize('kind,rule', [('fake_evidence','R02'),('wrong_port','R05'),('reviewer_rejection',None)])
async def test_integrated_claim_checks(kind,rule):
    result = await inspect_claim(kind)
    assert result['api_calls'] == 0
    if rule:
        assert rule in {c['rule_id'] for c in result['blocked_checks']}
    else:
        assert not result['blocked_checks']
        assert result['reviewer_findings']
        assert result['diagnosis']['category'] == 'CONNECTION_FAILURE'
        assert result['diagnosis']['recovery_actions']


@pytest.mark.parametrize('case', ['connection','schema','quality'])
@pytest.mark.parametrize('same', [False,True])
def test_recovery_keeps_new_run_boundary(case,same):
    result = verify_recovery(case,same)
    assert result['result']['recovered'] is not same
    assert result['api_calls'] == 0
    if same:
        assert 'SEPARATE_SAME_DAG_RUN_REQUIRED' in result['result']['reasons']
    else:
        assert not result['result']['reasons']


def test_integrated_records_keep_all_prior_model_cases():
    records = model_records()
    assert len(records) >= 11
    for path in records.values():
        report = Report.model_validate_json(path.read_text())
        assert report.usage.api_calls > 0
        assert not 'fake' in report.versions['model']


def test_copied_inputs_and_records_match_preserved_sources():
    manifest = json.loads((DATA/'manifest.json').read_text())
    assert len(manifest['files']) == 58
    assert all(hashlib.sha256((DATA/rel).read_bytes()).hexdigest() == digest for rel,digest in manifest['files'].items())


async def test_paid_execution_blocked_before_key_read(monkeypatch):
    from dataops_copilot import ui
    from dataops_copilot.api_safety import SafeAPIError
    monkeypatch.setattr(ui,'budget_snapshot',lambda:{'requests':128,'total_call_cap':128})
    def forbidden(*args,**kwargs):
        raise AssertionError('must not read credentials')
    monkeypatch.setattr(ui,'read_api_settings',forbidden)
    with pytest.raises(SafeAPIError):
        await ui.execute(load_source('connection'),paid=True)


def test_app_pages_and_guard_result_reset():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT/'src/dataops_copilot/ui.py'),default_timeout=30).run()
    assert not app.exception
    assert not app.checkbox[0].value
    app.sidebar.radio[0].set_value('안전성 검사').run()
    app.button[0].click().run()
    assert not app.exception
    assert any('R02' in e.value for e in app.error)
    app.selectbox[0].select('근거 없이 포트 오류 단정').run()
    assert not app.exception
    assert not app.error
    app.button[0].click().run()
    assert any('R05' in e.value for e in app.error)
    app.sidebar.radio[0].set_value('평가·모델 기록').run()
    assert not app.exception


def test_app_recovery_result_not_reused_after_negative_toggle():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT/'src/dataops_copilot/ui.py'),default_timeout=30).run()
    app.sidebar.radio[0].set_value('복구 검증').run()
    app.button[0].click().run()
    assert not app.exception
    assert app.success
    app.checkbox[0].check().run()
    assert not app.success
    app.button[0].click().run()
    assert not app.exception
    assert not app.success
    assert any('SEPARATE_SAME_DAG_RUN_REQUIRED' in e.value for e in app.error)

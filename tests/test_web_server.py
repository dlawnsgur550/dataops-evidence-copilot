"""HTTP integration and safety boundaries for the local product frontend."""
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from dataops_copilot import web_server as web


@pytest.fixture(scope='module')
def endpoint():
    server = web.Server(('127.0.0.1', 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()
    thread.join()


def request(endpoint, path, payload=None, headers=None, raw=None):
    body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    base = {'Content-Type': 'application/json', 'Origin': endpoint}
    base.update(headers or {})
    try:
        response = urlopen(Request(endpoint + path, body, base), timeout=30)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, response.headers, response.read()


def parsed(endpoint, path, payload=None, **kwargs):
    status, headers, body = request(endpoint, path, payload, **kwargs)
    return status, json.loads(body)


def test_static_is_local_and_has_security_headers(endpoint):
    for path, marker in [('/', b'lang="ko"'), ('/app.js', b'renderDiagnosis'),
                         ('/app.css', b'@font-face'), ('/assets/PretendardVariable.woff2', b'wOF2')]:
        status, headers, body = request(endpoint, path)
        assert status == 200 and marker in body
        assert "connect-src 'self'" in headers['Content-Security-Policy']
        assert headers['X-Content-Type-Options'] == 'nosniff'
    assert request(endpoint, '/health')[2] == b'ok'


def test_bootstrap_models_are_typed_and_budget_has_no_secrets(endpoint):
    status, data = parsed(endpoint, '/api/bootstrap')
    assert status == 200 and len(data['cases']) == 5
    assert len(data['model_records']) == 11
    assert set(data['budget']) == {'requests', 'total_call_cap', 'spent_or_reserved_usd', 'paid_blocked'}
    for key in data['model_records']:
        status, result = parsed(endpoint, '/api/model?id=' + key)
        assert status == 200
        assert result['report']['usage']['api_calls'] > 0
        assert 'fake' not in result['report']['versions']['model']


@pytest.mark.parametrize('case,category', [('connection', 'CONNECTION_FAILURE'), ('schema', 'SCHEMA_CHANGE'),
    ('quality', 'DATA_QUALITY'), ('insufficient', 'UNKNOWN'), ('normal', 'NORMAL')])
def test_free_diagnosis_preserves_saved_binding(endpoint, case, category):
    status, source = parsed(endpoint, '/api/report?case=' + case)
    assert status == 200
    status, result = parsed(endpoint, '/api/diagnose', {'case': case, 'mode': 'replay'})
    assert status == 200
    assert result['report']['diagnosis']['category'] == category
    assert result['report']['usage']['api_calls'] == 0
    assert result['report']['incident_ref'] == source['report']['incident_ref']


def test_wrong_run_cannot_inherit_actions_or_pipeline(endpoint):
    incident = web.load_source('connection').incident_ref.model_dump(mode='json')
    incident['run_id'] = 'not-the-bound-run'
    status, result = parsed(endpoint, '/api/diagnose', {'case': 'connection', 'incident': incident})
    assert status == 200
    assert result['report']['diagnosis']['category'] == 'UNKNOWN'
    assert result['report']['errors']
    assert not result['report']['diagnosis']['recovery_actions']
    assert result['task_states'] == {}


@pytest.mark.parametrize('kind,rule', [('fake_evidence', 'R02'), ('wrong_port', 'R05'), ('reviewer_rejection', None)])
def test_counterexamples_use_real_gates(endpoint, kind, rule):
    status, result = parsed(endpoint, '/api/guard', {'kind': kind})
    assert status == 200 and result['api_calls'] == 0
    if rule:
        assert rule in {r['rule_id'] for r in result['blocked_checks']}
    else:
        assert not result['blocked_checks'] and result['reviewer_findings']


@pytest.mark.parametrize('case', ['connection', 'schema', 'quality'])
@pytest.mark.parametrize('same', [True, False])
def test_recovery_requires_distinct_successful_run(endpoint, case, same):
    status, result = parsed(endpoint, '/api/recovery', {'case': case, 'same_run': same})
    assert status == 200 and result['api_calls'] == 0
    assert result['result']['recovered'] is not same
    assert ('SEPARATE_SAME_DAG_RUN_REQUIRED' in result['result']['reasons']) is same


def test_budget_lock_prevents_credential_read(endpoint, monkeypatch):
    monkeypatch.setattr(web, 'budget_snapshot', lambda: {'paid_blocked': True})
    def forbidden(*args, **kwargs):
        raise AssertionError('credential read attempted')
    monkeypatch.setattr(web, 'read_api_settings', forbidden)
    status, data = parsed(endpoint, '/api/diagnose', {'case': 'connection', 'paid': True})
    assert status == 403 and '무료' in data['error']


@pytest.mark.parametrize('headers', [{'Host': 'attacker.example'}, {'Origin': 'https://attacker.example'}, {'Origin': ''}])
def test_rebinding_and_cross_site_posts_rejected(endpoint, headers):
    assert parsed(endpoint, '/api/diagnose', {'case': 'connection'}, headers=headers)[0] == 403


@pytest.mark.parametrize('payload', [[], {'case': '../secrets'}, {'case': 'connection', 'paid': 'false'},
    {'case': 'connection', 'api_key': 'test-input-never-echo'}, {'case': 'connection', 'incident': {}}])
def test_malformed_inputs_rejected_without_echo(endpoint, payload):
    status, data = parsed(endpoint, '/api/diagnose', payload)
    assert status == 400 and 'test-input-never-echo' not in str(data)


def test_large_or_non_json_body_rejected(endpoint):
    assert request(endpoint, '/api/diagnose', raw=b'x' * 32769)[0] == 413
    assert parsed(endpoint, '/api/diagnose', {'case': 'connection', 'incident': {'run_id': 'x' * 16384}})[0] == 413
    assert request(endpoint, '/api/diagnose', raw=b'not-json', headers={'Content-Type': 'text/plain'})[0] == 415
    assert request(endpoint, '/../api_safety.py')[0] == 404
    assert request(endpoint, '/assets/../web_server.py')[0] == 404


def test_downloads_only_expose_supplied_materials(endpoint):
    for case in ('connection', 'schema', 'quality'):
        status, headers, body = request(endpoint, '/api/download?kind=csv&case=' + case)
        assert status == 200 and len(body.splitlines()) == 100001
        assert 'attachment' in headers['Content-Disposition']
    assert parsed(endpoint, '/api/model?id=../../api_safety.py')[0] == 400
    assert request(endpoint, '/api/download?kind=secret&case=connection')[0] == 404

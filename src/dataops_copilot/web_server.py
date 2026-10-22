"""Loopback-only product UI. Existing inference, policy and recovery code is reused."""
from __future__ import annotations

import argparse
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

from .api_safety import CostLedger, SafeAPIError, read_api_settings
from .models import IncidentRef, Report
from .llm import FakeLLM
from .workflow import Limits
from .workflow_v3 import ClaimCopilot
from .replay import ReportReplay
from .retrieval import LocalRunbooks
from .local_paths import RUNTIME
from .ui_workspace import (ROOT, DATA, CASES, load_source, task_states, inspect_claim,
                            verify_recovery, model_records, evaluation_summary)

WEB = Path(__file__).parent / 'web'
LOCK = threading.Lock()
STATIC = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.css': ('app.css', 'text/css; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/assets/PretendardVariable.woff2': ('assets/PretendardVariable.woff2', 'font/woff2')}


def budget_snapshot():
    path = RUNTIME / 'llm-cost.sqlite3'
    if not path.is_file():
        return {'requests': 0, 'total_call_cap': 0, 'spent_or_reserved_usd': 0, 'paid_blocked': True}
    d = CostLedger(path).summary()
    return {k: d[k] for k in ('requests', 'total_call_cap', 'spent_or_reserved_usd')} | {
        'paid_blocked': d['requests'] >= d['total_call_cap']}


def bootstrap():
    cases = []
    for key, (label, description) in CASES.items():
        r = load_source(key)
        context = next((e.data for e in r.evidence if e.kind == 'get_task_context' and e.status == 'success'), {}) or {}
        cases.append({'id': key, 'label': label, 'description': description,
                      'category': r.diagnosis.category, 'state': context.get('state', 'unknown'),
                      'started_at': context.get('run_started_at'), 'run_id': r.incident_ref.run_id})
    return {'cases': cases, 'budget': budget_snapshot(), 'evaluation': evaluation_summary(),
            'model_records': list(model_records()), 'default_case': 'connection'}


def report_data(report):
    return {'report': report.model_dump(mode='json'), 'task_states': task_states(report)}


async def diagnose(case, mode='replay', incident_data=None, full=False, paid=False):
    if mode not in ('replay', 'live'):
        raise ValueError('INVALID_MODE')
    source = load_source(case)
    incident = IncidentRef.model_validate(incident_data) if incident_data is not None else source.incident_ref
    model = FakeLLM()
    if paid:
        if budget_snapshot()['paid_blocked']:
            raise SafeAPIError('API 요청 한도에 도달했습니다. 무료 모델로 실행하세요.')
        from .openai_llm import OpenAILLM
        key, _ = read_api_settings(RUNTIME / 'openai.env')
        model = OpenAILLM(key, RUNTIME)
    if full:
        from .hybrid import HybridRunbooks
        retriever = HybridRunbooks()
    else:
        retriever = LocalRunbooks()
    try:
        if mode == 'live':
            from .mcp_client import open_live_mcp
            async with open_live_mcp(RUNTIME / 'live-settings.json') as tools:
                r = await ClaimCopilot(tools, model, retriever=retriever,
                    limits=Limits(llm_calls=2 if full else 1), baseline=not full).diagnose(incident)
        else:
            r = await ClaimCopilot(ReportReplay(source), model, retriever=retriever,
                limits=Limits(llm_calls=2 if full else 1), baseline=not full).diagnose(incident)
        if not paid:
            r.usage.api_calls = 0
        return report_data(r)
    finally:
        if hasattr(retriever, 'close'):
            retriever.close()


class Server(ThreadingHTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = 'DataOpsWorkspace'

    def log_message(self, fmt, *args):
        pass  # No request bodies, incident payloads or credentials in access logs.

    def send(self, status, body, content_type='application/json; charset=utf-8', filename=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def host_valid(self):
        port = self.server.server_address[1]
        return self.headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}')

    def do_GET(self):
        if not self.host_valid():
            return self.send(403, {'error': '허용되지 않은 호스트입니다.'})
        url = urlsplit(self.path)
        args = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if url.path in ('/_stcore/health', '/health'):
                return self.send(200, b'ok', 'text/plain')
            if url.path in STATIC:
                filename, mime = STATIC[url.path]
                return self.send(200, (WEB / filename).read_bytes(), mime)
            if url.path == '/api/bootstrap':
                return self.send(200, bootstrap())
            if url.path == '/api/report':
                return self.send(200, report_data(load_source(args.get('case', 'connection'))))
            if url.path == '/api/model':
                paths = model_records()
                report = Report.model_validate_json(paths[args['id']].read_text())
                return self.send(200, report_data(report))
            if url.path == '/api/download':
                case = args.get('case', 'connection')
                report = load_source(case)  # Validates the case allowlist.
                kind = args.get('kind')
                if kind == 'incident':
                    return self.send(200, report.incident_ref.model_dump_json(indent=2).encode(), filename=case+'-incident.json')
                if kind == 'log':
                    return self.send(200, (DATA/'inputs/logs'/f'{case}.log').read_bytes(), 'text/plain; charset=utf-8', case+'.log')
                if kind == 'csv':
                    name = {'connection': 'orders_normal.csv', 'schema': 'orders_schema_changed.csv',
                            'quality': 'orders_quality_null.csv', 'normal': 'orders_normal.csv'}[case]
                    return self.send(200, (DATA/'inputs/data'/name).read_bytes(), 'text/csv; charset=utf-8', name)
            return self.send(404, {'error': '자료를 찾을 수 없습니다.'})
        except (KeyError, ValueError, FileNotFoundError):
            return self.send(400, {'error': '선택한 자료를 확인하세요. 목록에서 사례를 다시 선택할 수 있습니다.'})

    def do_POST(self):
        port = self.server.server_address[1]
        if not self.host_valid() or self.headers.get('Origin') not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
            return self.send(403, {'error': '이 기본 웹에서 실행하세요.'})
        if self.headers.get_content_type() != 'application/json':
            return self.send(415, {'error': 'JSON 형식의 입력이 필요합니다.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 32768:
                return self.send(413, {'error': '입력이 너무 큽니다. 실행키 JSON은 16KB 이하로 준비하세요.'})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('OBJECT_REQUIRED')
            path = urlsplit(self.path).path
            if path == '/api/diagnose':
                if set(data) - {'case', 'mode', 'incident', 'full', 'paid'}:
                    raise ValueError('UNEXPECTED_FIELDS')
                if any(type(data.get(k, False)) is not bool for k in ('full', 'paid')):
                    raise ValueError('BOOLEAN_REQUIRED')
                if data.get('incident') is not None and len(json.dumps(data['incident'], ensure_ascii=False).encode()) > 16384:
                    return self.send(413, {'error': '실행키 JSON은 16KB 이하로 준비하세요.'})
                if not LOCK.acquire(blocking=False):
                    return self.send(409, {'error': '다른 진단이 진행 중입니다. 잠시 후 다시 실행하세요.'})
                try:
                    result = asyncio.run(diagnose(data['case'], data.get('mode', 'replay'), data.get('incident'), data.get('full', False), data.get('paid', False)))
                finally:
                    LOCK.release()
                return self.send(200, result)
            if path == '/api/guard':
                if set(data) != {'kind'}:
                    raise ValueError('UNEXPECTED_FIELDS')
                return self.send(200, asyncio.run(inspect_claim(data['kind'])))
            if path == '/api/recovery':
                if set(data) - {'case', 'same_run'} or type(data.get('same_run', False)) is not bool:
                    raise ValueError('UNEXPECTED_FIELDS')
                return self.send(200, verify_recovery(data['case'], data.get('same_run', False)))
            return self.send(404, {'error': '실행 경로를 찾을 수 없습니다.'})
        except SafeAPIError as exc:
            return self.send(403, {'error': str(exc)})
        except (ValueError, KeyError, TypeError):
            return self.send(400, {'error': '실행키 JSON의 필드와 형식을 확인하세요. 선택 사례의 원본 JSON을 내려받아 사용할 수 있습니다.'})
        except Exception:
            return self.send(503, {'error': '진단을 완료하지 못했습니다. 저장 근거 재진단을 사용하거나 로컬 서비스·검색 모델 준비 상태를 확인하세요.'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18784)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('invalid local port')
    server = Server(('127.0.0.1', args.port), Handler)
    print(f'DataOps Copilot: http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

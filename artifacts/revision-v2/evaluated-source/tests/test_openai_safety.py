import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from pydantic import SecretStr

from dataops_copilot.api_safety import CostLedger, SafeAPIError, read_api_settings
from dataops_copilot.openai_llm import OpenAILLM, compact_payload, response_schema, strict_schema
from dataops_copilot.models import Diagnosis, Plan

KEY = "sk-test-do-not-expose-shared-key"
PLAN = {"provisional_category": "UNKNOWN", "investigation": ["추가 근거 확인"]}


def response(answer=PLAN, **overrides):
    return {"status": "completed", "usage": {"input_tokens": 100, "output_tokens": 30, "input_tokens_details": {"cached_tokens": 0}},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer)}]}], **overrides}


def test_explicit_key_settings_and_model_allowlist(tmp_path):
    path = tmp_path / "openai.env"
    path.write_text("OPENAI_API_KEY=" + KEY + "\nOPENAI_MODEL=\n")
    key, model = read_api_settings(path)
    assert model == "gpt-6-luna" and key.get_secret_value() == KEY
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    path.write_text("OPENAI_API_KEY=" + KEY + "\nOPENAI_MODEL=expensive-model\n")
    with pytest.raises(SafeAPIError, match="ALLOWLIST"):
        read_api_settings(path)


async def test_request_security_and_cache_avoids_second_paid_call(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert request.url == "https://api.openai.com/v1/responses"
        assert body["model"] == "gpt-6-luna" and body["store"] is False and body["tools"] == []
        assert body["max_output_tokens"] == 256 and body["reasoning"]["effort"] == "none"
        assert KEY not in request.content.decode()
        return httpx.Response(200, json=response())
    llm = OpenAILLM(SecretStr(KEY), tmp_path, transport=httpx.MockTransport(handler))
    assert tmp_path.stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "llm-cache").stat().st_mode & 0o777 == 0o700
    first = await llm.complete("triage", "Do not echo " + KEY, {"evidence": []})
    second = await llm.complete("triage", "Do not echo " + KEY, {"evidence": []})
    assert first == second and len(calls) == 1 and llm.metrics["local_cache_hits"] == 1
    assert llm.metrics["input_tokens"] == 100 and llm.metrics["cost_usd"] > 0
    assert KEY not in repr(llm)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert KEY.encode() not in path.read_bytes()


@pytest.mark.parametrize("status", [401, 403, 429, 500, 307])
async def test_http_failures_never_retry_or_echo_server_body(tmp_path, status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": KEY}}, headers={"Location": "https://outside.invalid"})
    llm = OpenAILLM(SecretStr(KEY), tmp_path, transport=httpx.MockTransport(handler))
    with pytest.raises(SafeAPIError) as error:
        await llm.complete("triage", "JSON only", {})
    assert KEY not in str(error.value) and len(calls) == 1
    assert llm.ledger.summary()["uncertain_requests"] == 1


async def test_missing_usage_keeps_reservation(tmp_path):
    llm = OpenAILLM(SecretStr(KEY), tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response(usage=None))))
    with pytest.raises(SafeAPIError, match="USAGE_MISSING"):
        await llm.complete("triage", "JSON only", {})
    assert llm.ledger.summary()["spent_or_reserved_usd"] > 0 and not llm.metrics["usage_collected"]


async def test_incomplete_response_is_not_retried_or_cached(tmp_path):
    llm = OpenAILLM(SecretStr(KEY), tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response(status="incomplete"))))
    with pytest.raises(SafeAPIError, match="INCOMPLETE"):
        await llm.complete("triage", "JSON only", {})
    assert llm.metrics["api_calls"] == 1 and not list((tmp_path / "llm-cache").glob("*.json"))


async def test_large_input_stops_before_network(tmp_path):
    def forbidden(request):
        raise AssertionError("Network called")
    llm = OpenAILLM(SecretStr(KEY), tmp_path, transport=httpx.MockTransport(forbidden))
    with pytest.raises(SafeAPIError, match="TOO_LARGE"):
        await llm.complete("triage", "x" * 25000, {})
    assert llm.ledger.summary()["requests"] == 0


def test_budget_reservation_is_atomic_across_workers(tmp_path):
    ledger = CostLedger(tmp_path / "ledger.sqlite3")
    def reserve(i):
        try:
            return ledger.reserve(str(i), "triage", 5_000_000)
        except SafeAPIError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        reservations = list(pool.map(reserve, range(8)))
    assert len([x for x in reservations if x]) == 4
    assert ledger.summary()["spent_or_reserved_usd"] == 0.02


def test_per_diagnosis_calls_and_money_cannot_reset_by_new_client(tmp_path):
    ledger = CostLedger(tmp_path / "ledger.sqlite3")
    for _ in range(4):
        rid = ledger.reserve("same", "triage", 1000)
        ledger.settle(rid, {"input_tokens": 1, "output_tokens": 1})
    second = CostLedger(tmp_path / "ledger.sqlite3")
    with pytest.raises(SafeAPIError, match="FOUR_CALL_CAP"):
        second.reserve("same", "reviewer", 1000)


def test_usage_exceeding_reservation_opens_circuit_breaker(tmp_path):
    ledger = CostLedger(tmp_path / "ledger.sqlite3")
    rid = ledger.reserve("one", "triage", 100)
    with pytest.raises(SafeAPIError, match="EXCEEDED"):
        ledger.settle(rid, {"input_tokens": 10, "output_tokens": 10})
    with pytest.raises(SafeAPIError, match="CIRCUIT_BREAKER"):
        ledger.reserve("two", "triage", 1000)


def test_structured_schema_requires_all_properties_and_forbids_extras():
    schema = strict_schema(Diagnosis)
    assert set(schema["required"]) == set(schema["properties"])
    for obj in schema["$defs"].values():
        if obj.get("type") == "object":
            assert obj["additionalProperties"] is False
            assert set(obj["required"]) == set(obj["properties"])


def test_evidence_and_runbook_id_namespaces_are_separate():
    schema = response_schema("rca", {"evidence": [{"evidence_id": "live-actual", "status": "success"}, {"evidence_id": "unavailable-id", "status": "unavailable"}],
                                     "retrieval_hits": [{"doc_id": "rb-schema", "chunk_id": "rb-schema:whole"}]})
    props = schema["$defs"]["RecoveryAction"]["properties"]
    assert schema["properties"]["evidence_ids"]["items"]["enum"] == ["live-actual"]
    assert props["evidence_ids"]["items"]["enum"] == ["live-actual"]
    assert props["runbook_ids"]["items"]["enum"] == ["rb-schema"]


def test_per_diagnosis_money_cap_is_checked_before_request(tmp_path):
    ledger = CostLedger(tmp_path / "cost.sqlite3")
    ledger.reserve("same", "triage", 5_000_000)
    ledger.reserve("same", "inspector", 5_000_000)
    with pytest.raises(SafeAPIError, match="DIAGNOSIS_COST_CAP"):
        ledger.reserve("same", "rca", 1)


async def test_paid_mode_report_collects_usage_and_safely_exposes_failure(tmp_path):
    from dataops_copilot.fixtures import FixtureAdapter, incident_for
    from dataops_copilot.workflow import Copilot, Limits
    llm = OpenAILLM(SecretStr(KEY), tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(403, json={"message": KEY})))
    report = await Copilot(FixtureAdapter("schema"), llm, limits=Limits(llm_calls=4)).diagnose(incident_for("schema"))
    assert report.usage.api_calls == 1 and report.usage.cost is None and report.usage.tokens is None
    assert report.usage.uncertain_reserved_usd > 0
    assert report.diagnosis.category == "UNKNOWN" and not report.review.accepted
    assert KEY not in report.model_dump_json()
    assert report.errors == ["OPENAI_HTTP_403_NO_RETRY_RESERVATION_RETAINED"]

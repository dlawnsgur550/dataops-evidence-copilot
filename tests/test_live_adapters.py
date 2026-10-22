import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from dataops_copilot.artifact_store import ArtifactMismatch, ArtifactStore
from dataops_copilot.fixtures import TASKS, incident_for
from dataops_copilot.live_adapter import LiveAdapter, bounded_log
from dataops_copilot.live_settings import LiveSettings
from dataops_copilot.models import Status
from dataops_copilot.rules import evidence_violations, supported_category


def settings(tmp_path):
    return LiveSettings(airflow_url="http://127.0.0.1:18783/api/v1", airflow_user="dataops_viewer", airflow_password="test-only-secret",
        observer={"host": "127.0.0.1", "port": 15439, "user": "dataops_observer", "password": "test-only-db-secret", "dbname": "dataops_c_cp2"},
        artifact_root=tmp_path / "archives", baseline_path=tmp_path / "baseline.json", endpoint_path=tmp_path / "endpoint.json")


def test_settings_reject_privileged_or_external_credentials(tmp_path):
    original = settings(tmp_path)
    for update in ({"airflow_user": "dataops_admin"}, {"airflow_url": "http://outside.invalid:8080/api/v1"},
                   {"observer": {**original.observer.model_dump(), "user": "postgres"}},
                   {"observer": {**original.observer.model_dump(), "dbname": "existing_user_db"}}):
        with pytest.raises(ValidationError):
            LiveSettings.model_validate({**original.model_dump(), **update})


def test_log_bound_and_json_message_normalization():
    event = json.dumps({"data": {}, "info": {"msg": 'column "amount" does not exist\npassword=do-not-return'}})
    lines, _ = bounded_log("[time] INFO - " + event)
    assert 'column "amount" does not exist' in lines
    assert "do-not-return" not in "\n".join(lines)
    lines, truncated = bounded_log("\n".join("가" * 5000 for _ in range(350)))
    assert truncated and len(lines) <= 200 and len("\n".join(lines).encode()) <= 40000


@pytest.mark.parametrize("status,expected", [(401, Status.UNAVAILABLE), (403, Status.UNAVAILABLE), (404, Status.EMPTY), (503, Status.UNAVAILABLE)])
async def test_airflow_error_distinction(tmp_path, status, expected):
    adapter = LiveAdapter(settings(tmp_path), http_transport=httpx.MockTransport(lambda r: httpx.Response(status)))
    item = await adapter.call("get_task_context", incident_for("schema").model_dump(exclude={"incident_id"}))
    assert item.status == expected and not item.simulated
    if status in (401, 403):
        assert item.error.code == "AUTH_DENIED" and not item.error.retryable
    if status == 503:
        assert item.error.retryable


async def test_airflow_context_is_selected_attempt_and_capped(tmp_path):
    ref = incident_for("schema")
    def respond(request):
        if "/logs/" in request.url.path:
            assert request.headers["accept"] == "text/plain"
            return httpx.Response(200, text="\n".join(["line"] * 210), headers={"content-type": "text/plain"})
        if request.url.path.endswith("taskInstances"):
            return httpx.Response(200, json={"total_entries": 4, "task_instances": [{"task_id": t, "state": "success"} for t in TASKS]})
        return httpx.Response(200, json={"dag_id": ref.dag_id, "dag_run_id": ref.run_id, "task_id": ref.task_id, "try_number": ref.try_number, "state": "failed"})
    adapter = LiveAdapter(settings(tmp_path), http_transport=httpx.MockTransport(respond))
    item = await adapter.call("get_task_context", ref.model_dump(exclude={"incident_id"}))
    assert item.status == Status.SUCCESS
    assert len(item.data["log_lines"]) == 200 and item.data["truncated"]
    wrong = await adapter.call("get_task_context", {**ref.model_dump(exclude={"incident_id"}), "try_number": 2})
    assert wrong.status == Status.INVALID_INPUT
    assert wrong.error.code == "TASK_IDENTITY_OR_ATTEMPT_MISMATCH"


async def test_invalid_sql_targets_never_reach_db(tmp_path):
    adapter = LiveAdapter(settings(tmp_path))
    async def prohibited(*args, **kwargs):
        raise AssertionError("Disallowed input reached the database")
    adapter.query = prohibited
    for tool, args in (("compare_schema", {"table_id": "raw.orders;DROP TABLE x", "baseline_id": "orders-v1"}),
                       ("get_quality_profile", {"table_id": "raw.orders", "column_ids": ["password"]}),
                       ("check_connection", {"connection_id": "postgres_admin"})):
        assert (await adapter.call(tool, args)).status == Status.INVALID_INPUT


def make_artifacts(target, invocation="actual-invocation"):
    target.mkdir()
    manifest = {"metadata": {"invocation_id": invocation}, "nodes": {
        "model.orders_demo.stg_orders": {"resource_type": "model", "depends_on": {"nodes": []}},
        "model.orders_demo.daily_orders": {"resource_type": "model", "depends_on": {"nodes": ["model.orders_demo.stg_orders"]}}},
        "child_map": {"model.orders_demo.stg_orders": ["model.orders_demo.daily_orders"]}}
    results = {"metadata": {"invocation_id": invocation}, "results": [{"unique_id": "model.orders_demo.stg_orders", "status": "error", "message": 'column "amount" does not exist'}]}
    (target / "manifest.json").write_text(json.dumps(manifest))
    (target / "run_results.json").write_text(json.dumps(results))
    return target


def test_archive_preserves_runs_attempts_and_detects_tampering(tmp_path):
    store = ArtifactStore(tmp_path / "archive")
    original = incident_for("schema")
    second = original.model_copy(update={"run_id": "second-run"})
    retried = original.model_copy(update={"try_number": 2})
    for i, ref in enumerate((original, second, retried)):
        target = make_artifacts(tmp_path / f"target-{i}")
        store.save(ref, "run", str(i), target, "log", 1, 0.1)
    parsed = store.load(original)
    assert parsed["issue"] == "missing_column"
    assert parsed["potential_downstream"] == ["model.orders_demo.daily_orders"]
    assert len(set(store.directory(r) for r in (original, second, retried))) == 3
    path = next(store.directory(original).glob("*/run_results.json"))
    path.write_text(path.read_text().replace("amount", "forged"))
    with pytest.raises(ArtifactMismatch):
        store.load(original)


def test_missing_dbt_files_are_not_fabricated(tmp_path):
    store = ArtifactStore(tmp_path / "archive")
    target = tmp_path / "empty-target"
    target.mkdir()
    ref = incident_for("connection")
    store.save(ref, "run", "call", target, "connection refused", 2, 0.1)
    parsed = store.load(ref)
    assert parsed["artifact_status"] == "partial"
    assert parsed["available_artifacts"] == []
    assert parsed["run_results_invocation_id"] is None and parsed["manifest_invocation_id"] is None


def test_manifest_result_invocations_must_match(tmp_path):
    store = ArtifactStore(tmp_path / "archive")
    target = make_artifacts(tmp_path / "target")
    path = target / "manifest.json"
    path.write_text(path.read_text().replace("actual-invocation", "foreign-invocation"))
    with pytest.raises(ArtifactMismatch):
        store.save(incident_for("schema"), "run", "call", target, "log", 1, 0.1)


def test_connection_partial_requires_real_invocation_bound_log_and_manifest(tmp_path):
    from dataops_copilot.fixtures import FixtureAdapter
    store = ArtifactStore(tmp_path / "archive")
    target = make_artifacts(tmp_path / "target")
    (target / "run_results.json").unlink()
    ref = incident_for("connection")
    log = json.dumps({"data": {}, "info": {"invocation_id": "actual-invocation", "msg": "connection refused"}})
    store.save(ref, "run", "call", target, log, 2, 0.1)
    parsed = store.load(ref)
    backend = FixtureAdapter("connection")
    context = backend.query("get_task_context", ref.model_dump(exclude={"incident_id"}))
    artifacts = backend.query("get_dbt_artifacts", ref.model_dump(exclude={"incident_id"})).model_copy(update={"data": parsed})
    assert not evidence_violations(artifacts, ref)
    assert parsed["run_results_invocation_id"] is None
    assert parsed["missing_artifacts"] == ["run_results"]
    assert supported_category([context, artifacts], ref)[0] == "CONNECTION_FAILURE"
    forged = artifacts.model_copy(update={"data": {**parsed, "stdout_invocation_ids": ["invented"]}})
    assert evidence_violations(forged, ref)
    assert supported_category([context, forged], ref)[0] == "UNKNOWN"


async def test_unexpected_json_log_wrapper_is_reported_unavailable(tmp_path):
    ref = incident_for("schema")
    def respond(request):
        if "/logs/" in request.url.path:
            return httpx.Response(200, json={"content": "[('host', 'escaped\\nlog')]"})
        return httpx.Response(200, json={"dag_id": ref.dag_id, "dag_run_id": ref.run_id, "task_id": ref.task_id, "try_number": ref.try_number, "state": "failed"})
    adapter = LiveAdapter(settings(tmp_path), http_transport=httpx.MockTransport(respond))
    item = await adapter.call("get_task_context", ref.model_dump(exclude={"incident_id"}))
    assert item.status == Status.UNAVAILABLE and item.error.code == "UNSUPPORTED_LOG_PAYLOAD"

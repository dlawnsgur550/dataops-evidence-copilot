import pytest
from pydantic import ValidationError

from dataops_copilot.fixtures import FixtureAdapter, incident_for
from dataops_copilot.llm import FakeLLM
from dataops_copilot.models import Diagnosis, IncidentRef, Status, TargetRef
from dataops_copilot.rules import code_review, supported_category
from dataops_copilot.workflow import Copilot


def test_incident_rejects_invalid_attempt_and_extra_fields():
    data = incident_for("schema").model_dump()
    with pytest.raises(ValidationError):
        IncidentRef.model_validate({**data, "try_number": 0})
    with pytest.raises(ValidationError):
        IncidentRef.model_validate({**data, "scenario_id": "schema"})


def test_evidence_status_and_timezone_contracts():
    item = FixtureAdapter("schema").query("compare_schema", {"table_id": "raw.orders", "baseline_id": "orders-v1"})
    for patch in ({"status": "unavailable", "data": None}, {"status": "success", "data": None}, {"observed_at": "2026-10-20T07:00:00"}, {"temporal_scope": "run_snapshot"}):
        with pytest.raises(ValidationError):
            type(item).model_validate({**item.model_dump(), **patch})
    assert item.temporal_scope == "current_observation"
    assert item.data["baseline_observed_at"] != item.observed_at.isoformat()


def test_distinct_statuses_and_allowlist():
    backend = FixtureAdapter("insufficient")
    args = incident_for("insufficient").model_dump(exclude={"incident_id"})
    assert backend.query("get_task_context", args).status == Status.SUCCESS
    assert backend.query("get_task_context", {**args, "run_id": "absent"}).status == Status.EMPTY
    assert backend.query("get_dbt_artifacts", args).status == Status.UNAVAILABLE
    assert backend.query("compare_schema", {"table_id": "raw.orders; DROP TABLE x", "baseline_id": "orders-v1"}).status == Status.INVALID_INPUT
    assert backend.query("execute_shell", {}).status == Status.INVALID_INPUT
    assert backend.query("get_quality_profile", {"table_id": "raw.orders", "column_ids": ["password"]}).status == Status.INVALID_INPUT


async def test_other_connection_success_does_not_mean_recovered():
    incident = incident_for("connection")
    backend = FixtureAdapter("connection")
    report = await Copilot(backend, FakeLLM()).diagnose(incident)
    other = await backend.call("check_connection", {"connection_id": "mcp_readonly"})
    assert other.data["connected"] is True
    evidence = [e for e in report.evidence if e.kind != "check_connection"] + [other]
    assert supported_category(evidence, incident)[0] == "CONNECTION_FAILURE"
    bogus = report.diagnosis.model_copy(update={"category": "NORMAL", "recovery_actions": []})
    assert "UNSUPPORTED_CATEGORY" in code_review(bogus, evidence, incident, report.retrieval_hits)
    assert report.recovered is None
    assert "포트 여부는 근거가 없어 확정하지" in report.diagnosis.cause


@pytest.mark.parametrize("change,expected", [
    ({"kind": "retry", "steps": ["재시도합니다"]}, "INAPPROPRIATE_RECOVERY_KIND"),
    ({"target_ref": TargetRef(table_id="other.orders")}, "ACTION_WRONG_TABLE"),
    ({"steps": ["DROP TABLE raw.orders"]}, "UNSAFE_EXECUTABLE_TEXT"),
    ({"runbook_ids": ["invented"]}, "ACTION_RUNBOOK_UNSUPPORTED"),
    ({"evidence_ids": ["invented"]}, "ACTION_MISSING_REQUIRED_EVIDENCE"),
])
async def test_recovery_rules(change, expected):
    incident = incident_for("schema")
    report = await Copilot(FixtureAdapter("schema"), FakeLLM()).diagnose(incident)
    action = report.diagnosis.recovery_actions[0].model_copy(update=change)
    diagnosis = report.diagnosis.model_copy(update={"recovery_actions": [action]})
    assert expected in code_review(diagnosis, report.evidence, incident, report.retrieval_hits)


async def test_current_schema_alone_cannot_establish_past_cause():
    incident = incident_for("schema")
    schema = await FixtureAdapter("schema").call("compare_schema", {"table_id": "raw.orders", "baseline_id": "orders-v1"})
    assert supported_category([schema], incident)[0] == "UNKNOWN"


async def test_retry_attempt_identity_is_not_merged():
    incident = incident_for("schema")
    report = await Copilot(FixtureAdapter("schema"), FakeLLM()).diagnose(incident)
    changed = []
    for e in report.evidence:
        if e.kind == "get_dbt_artifacts":
            e = e.model_copy(update={"target_ref": e.target_ref.model_copy(update={"incident": incident.model_copy(update={"try_number": 2})})})
        changed.append(e)
    assert supported_category(changed, incident)[0] == "UNKNOWN"

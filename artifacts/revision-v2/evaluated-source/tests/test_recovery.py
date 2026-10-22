import pytest

from dataops_copilot.fixtures import FixtureAdapter, incident_for
from dataops_copilot.recovery import check_recovery


def bundle():
    original = incident_for("schema")
    followup = incident_for("normal").model_copy(update={"incident_id": "followup", "run_id": "new-run"})
    args = incident_for("normal").model_dump(exclude={"incident_id"})
    adapter = FixtureAdapter("normal")
    context = adapter.query("get_task_context", args)
    artifacts = adapter.query("get_dbt_artifacts", args)
    context = context.model_copy(update={"target_ref": context.target_ref.model_copy(update={"incident": followup})})
    artifacts = artifacts.model_copy(update={"target_ref": artifacts.target_ref.model_copy(update={"incident": followup})})
    return original, followup, context, artifacts


def test_distinct_followup_with_tasks_and_tests():
    original, followup, context, artifacts = bundle()
    result = check_recovery(original, followup, context, artifacts)
    assert result.recovered
    assert result.original_incident_id == original.incident_id
    assert result.followup_run_id == "new-run"


def test_same_run_cannot_be_recovery():
    original, followup, context, artifacts = bundle()
    with pytest.raises(ValueError):
        check_recovery(original, followup.model_copy(update={"run_id": original.run_id}), context, artifacts)


def test_success_without_quality_is_not_recovered():
    original, followup, context, artifacts = bundle()
    artifacts = artifacts.model_copy(update={"data": {**artifacts.data, "test_results": {}}})
    assert not check_recovery(original, followup, context, artifacts).recovered


def test_past_artifact_is_not_recovered():
    original, followup, context, artifacts = bundle()
    artifacts = artifacts.model_copy(update={"target_ref": artifacts.target_ref.model_copy(update={"incident": original})})
    assert not check_recovery(original, followup, context, artifacts).recovered


def test_nonzero_command_exit_cannot_be_recovered_even_with_passed_tests():
    original, followup, context, artifacts = bundle()
    artifacts = artifacts.model_copy(update={"data": {**artifacts.data, "exit_code": 2}})
    assert not check_recovery(original, followup, context, artifacts).recovered

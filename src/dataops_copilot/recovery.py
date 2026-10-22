"""Pure follow-up checker: neither runs pipelines nor applies actions."""
from .fixtures import TASKS
from .models import Evidence, IncidentRef, RecoveryCheck, Status
from .rules import evidence_violations


def check_recovery(original: IncidentRef, followup: IncidentRef, context: Evidence, artifacts: Evidence) -> RecoveryCheck:
    if followup.dag_id != original.dag_id or followup.run_id == original.run_id:
        raise ValueError("Recovery needs a separate follow-up run of the same DAG")
    tasks, quality = {}, {}
    valid = context.kind == "get_task_context" and artifacts.kind == "get_dbt_artifacts" and all(e.status == Status.SUCCESS and not evidence_violations(e, followup) for e in (context, artifacts))
    if valid:
        tasks = context.data.get("task_statuses", {})
        quality = artifacts.data.get("test_results", {})
    recovered = valid and context.data.get("state") == "success" and artifacts.data.get("artifact_status", "complete") == "complete" and artifacts.data.get("exit_code", 0) == 0 and artifacts.data.get("issue") is None and set(tasks) == set(TASKS) and all(s == "success" for s in tasks.values()) and set(quality) == {"not_null_order_id", "unique_order_id"} and all(s == "pass" for s in quality.values())
    return RecoveryCheck(original_incident_id=original.incident_id, followup_run_id=followup.run_id,
                         task_statuses=tasks, quality_results=quality, recovered=bool(recovered))

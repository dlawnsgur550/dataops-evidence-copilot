"""Deterministic guardrail, independent of the replaceable LLM reviewer."""
from __future__ import annotations

import re

from .fixtures import TASKS
from .models import Diagnosis, Evidence, IncidentRef, RetrievalHit, Status
from .policy import TABLE_BASELINES, target_context


def evidence_violations(e: Evidence, incident: IncidentRef) -> list[str]:
    errors = []
    if e.temporal_scope == "run_snapshot":
        if e.target_ref.incident.execution_key() != incident.execution_key():
            errors.append("FOREIGN_EXECUTION:" + e.evidence_id)
    if e.kind in ("get_task_context", "get_dbt_artifacts") and e.temporal_scope != "run_snapshot":
        errors.append("RUN_SCOPE_REQUIRED:" + e.evidence_id)
    if e.kind in ("compare_schema", "get_quality_profile", "check_connection") and e.temporal_scope != "current_observation":
        errors.append("CURRENT_SCOPE_REQUIRED:" + e.evidence_id)
    if e.kind in ("compare_schema", "get_quality_profile") and e.target_ref.table_id not in TABLE_BASELINES:
        errors.append("FOREIGN_TABLE:" + e.evidence_id)
    if e.kind == "check_connection" and e.target_ref.connection_id not in ("dbt_orders", "mcp_readonly"):
        errors.append("FOREIGN_CONNECTION:" + e.evidence_id)
    if e.kind == "get_dbt_artifacts" and e.status == Status.SUCCESS:
        d = e.data
        ids = [d.get(k) for k in ("invocation_id", "manifest_invocation_id", "run_results_invocation_id")]
        if d.get("artifact_status") == "partial":
            # dbt can refuse a connection after parsing but before creating run_results.
            # Accept this as an explicitly partial command receipt, never as completed results.
            if not (ids[0] and ids[0] == ids[1] and ids[2] is None and d.get("available_artifacts") == ["manifest"]
                    and d.get("missing_artifacts") == ["run_results"] and d.get("stdout_invocation_ids") == [ids[0]]
                    and d.get("exit_code") == 2 and d.get("command") == "run"
                    and re.fullmatch(r"[0-9a-f]{64}", d.get("command_log_sha256", ""))):
                errors.append("PARTIAL_INVOCATION_UNVERIFIED:" + e.evidence_id)
        elif not ids[0] or len(set(ids)) != 1:
            errors.append("INVOCATION_MISMATCH:" + e.evidence_id)
    return errors


def supported_category(evidence: list[Evidence], incident: IncidentRef) -> tuple[str, list[str]]:
    valid = {e.kind: e for e in evidence if e.status == Status.SUCCESS and not evidence_violations(e, incident)}
    context = valid.get("get_task_context")
    artifacts = valid.get("get_dbt_artifacts")
    if not context or not artifacts:
        return "UNKNOWN", []
    c, a = context.data, artifacts.data
    logs = "\n".join(c.get("log_lines", [])).lower()
    ids = [context.evidence_id, artifacts.evidence_id]
    complete = a.get("artifact_status", "complete") == "complete"
    if complete and a.get("issue") == "missing_column" and c.get("state") == "failed":
        schema = valid.get("compare_schema")
        column = a.get("column_id")
        if schema and a.get("table_id") == schema.target_ref.table_id and column in ("amount", "net_amount", "unit_price") and column in schema.data.get("removed", []) and f'column "{column}" does not exist' in logs:
            return "SCHEMA_CHANGE", ids + [schema.evidence_id]
    if complete and a.get("issue") == "not_null" and c.get("state") == "failed":
        profile = valid.get("get_quality_profile")
        column = a.get("column_id")
        if profile and a.get("table_id") == profile.target_ref.table_id and column in ("order_id", "customer_id") and profile.data.get("null_counts", {}).get(column, 0) > 0 and "not_null" in logs and a.get("test_results", {}).get("not_null_"+column) == "fail":
            return "DATA_QUALITY", ids + [profile.evidence_id]
    # A separate MCP connection success cannot invalidate a run-bound dbt failure.
    if a.get("issue") == "connection_refused" and c.get("state") == "failed" and "connection refused" in logs and c.get("dbt_connection_id") == a.get("connection_id") == "dbt_orders":
        return "CONNECTION_FAILURE", ids
    if complete and a.get("exit_code", 0) == 0 and c.get("state") == "success" and set(c.get("task_statuses", {})) == set(TASKS) and all(v == "success" for v in c["task_statuses"].values()) and a.get("issue") is None and set(a.get("test_results", {})) == {"not_null_order_id", "unique_order_id"} and all(v == "pass" for v in a["test_results"].values()):
        return "NORMAL", ids
    return "UNKNOWN", []


def code_review(diagnosis: Diagnosis, evidence: list[Evidence], incident: IncidentRef, hits: list[RetrievalHit]) -> list[str]:
    errors = []
    by_id = {e.evidence_id: e for e in evidence}
    if len(by_id) != len(evidence):
        errors.append("DUPLICATE_EVIDENCE_ID")
    refs = diagnosis.evidence_ids + [i for a in diagnosis.recovery_actions for i in a.evidence_ids]
    for eid in refs:
        e = by_id.get(eid)
        if e is None:
            errors.append("FABRICATED_EVIDENCE_ID:" + eid)
        elif e.status != Status.SUCCESS:
            errors.append("UNSUCCESSFUL_EVIDENCE:" + eid)
        else:
            errors.extend(evidence_violations(e, incident))
    expected, required_ids = supported_category(evidence, incident)
    # Guard the observed failure mode. This bounded text check is not a general
    # semantic proof: the LLM reviewer and independent human audit remain useful.
    artifacts = [e for e in evidence if e.kind == "get_dbt_artifacts" and e.status == Status.SUCCESS
                 and not evidence_violations(e, incident)]
    claims = [diagnosis.cause, *diagnosis.missing_evidence, *diagnosis.impact]
    claims += [s for a in diagnosis.recovery_actions for s in a.prerequisites + a.steps]
    for claim in claims:
        for sentence in re.split(r"[。.!?\n]+", claim):
            if "run_results" not in sentence.lower():
                continue
            uncertain = re.search(r"미확인|불확실|확인.{0,12}(불가|어렵|필요|없)|단정.{0,10}(않|없)|여부|unconfirmed|unknown|cannot confirm|not established|not necessarily", sentence, re.I)
            missing = re.search(r"누락|미생성|생성되지|생성.{0,5}않|없습|없음|빠져|부재|missing|absent|not (?:created|generated|available)|incomplete|partial", sentence, re.I)
            proven = any(e.data.get("artifact_status") == "partial" and "run_results" in e.data.get("missing_artifacts", []) for e in artifacts)
            if missing and not uncertain and not proven:
                errors.append("UNSUPPORTED_ARTIFACT_MISSING_CLAIM:run_results")
    if expected == "NORMAL" and (diagnosis.category != "NORMAL" or diagnosis.diagnosis_status != "supported"):
        errors.append("NORMAL_EVIDENCE_MISCLASSIFIED")
    try:
        expected_table, _, _ = target_context(evidence)
    except ValueError:
        expected_table = None
        errors.append("TARGET_NOT_IN_DEMO_ALLOWLIST")
    if diagnosis.diagnosis_status == "supported":
        if diagnosis.category != expected:
            errors.append("UNSUPPORTED_CATEGORY")
        if not set(required_ids).issubset(diagnosis.evidence_ids):
            errors.append("REQUIRED_EVIDENCE_NOT_CITED")
        if diagnosis.category not in ("NORMAL", "UNKNOWN") and not diagnosis.recovery_actions:
            errors.append("RECOVERY_ACTION_MISSING")
    hit_ids = {h.doc_id for h in hits}
    expected_kind = {"SCHEMA_CHANGE": "schema_alignment", "DATA_QUALITY": "data_remediation", "CONNECTION_FAILURE": "connection_config"}
    expected_doc = {"SCHEMA_CHANGE": "rb-schema", "DATA_QUALITY": "rb-quality", "CONNECTION_FAILURE": "rb-connection"}
    for action in diagnosis.recovery_actions:
        if action.target_ref.incident and action.target_ref.incident.execution_key() != incident.execution_key():
            errors.append("ACTION_FOREIGN_EXECUTION")
        if diagnosis.category == "CONNECTION_FAILURE":
            if action.target_ref.connection_id != "dbt_orders":
                errors.append("ACTION_WRONG_CONNECTION")
        elif action.target_ref.table_id != expected_table:
            errors.append("ACTION_WRONG_TABLE")
        if action.kind != expected_kind.get(diagnosis.category):
            errors.append("INAPPROPRIATE_RECOVERY_KIND")
        if not set(required_ids).issubset(action.evidence_ids):
            errors.append("ACTION_MISSING_REQUIRED_EVIDENCE")
        if not set(action.runbook_ids).issubset(hit_ids) or expected_doc.get(diagnosis.category) not in action.runbook_ids:
            errors.append("ACTION_RUNBOOK_UNSUPPORTED")
        text = " ".join(action.steps + action.prerequisites + action.verification)
        if re.search(r"\b(drop|delete|truncate|insert|update|alter|sudo|curl|bash|sh|rm)\b|[;&|`]|\$\(", text, re.I):
            errors.append("UNSAFE_EXECUTABLE_TEXT")
    return sorted(set(errors))

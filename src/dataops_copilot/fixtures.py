"""Synthetic backend, deliberately separate from transport and LLM interfaces."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Protocol

from .models import Evidence, IncidentRef, Status, TargetRef, ToolError

TOOLS = {"get_task_context", "compare_schema", "get_quality_profile", "get_dbt_artifacts", "check_connection"}
FIXTURES = ("schema", "quality", "connection", "normal", "insufficient")
TASKS = ("load_demo_data", "dbt_run", "dbt_test", "publish_summary")
RUN_ID = "manual__2026-10-20T07:00:00Z"


class ToolClient(Protocol):
    transport: str

    async def call(self, tool: str, arguments: dict[str, Any]) -> Evidence: ...


def incident_for(fixture: str) -> IncidentRef:
    task = "dbt_test" if fixture == "quality" else "publish_summary" if fixture == "normal" else "dbt_run"
    return IncidentRef(incident_id="incident-001", dag_id="orders_demo", run_id=RUN_ID, task_id=task, try_number=1)


class FixtureAdapter:
    transport = "direct_fixture_function"

    def __init__(self, fixture: str):
        if fixture not in FIXTURES:
            raise ValueError("Unknown fixture")
        self.fixture = fixture

    async def call(self, tool: str, arguments: dict[str, Any]) -> Evidence:
        return self.query(tool, arguments)

    def query(self, tool: str, args: dict[str, Any]) -> Evidence:
        identity = json.dumps([tool, args], sort_keys=True)
        ref = TargetRef(table_id="unresolved")
        scope = "current_observation"

        def result(status: Status, data=None, code=None, retryable=False):
            return Evidence(evidence_id="ev-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
                            kind=tool, source="fixture://synthetic-backend/v1", observed_at=datetime.now(timezone.utc),
                            temporal_scope=scope, target_ref=ref, status=status, data=data,
                            error=ToolError(code=code, retryable=retryable, message=code) if code else None)

        if tool not in TOOLS:
            return result(Status.INVALID_INPUT, code="TOOL_NOT_ALLOWED")
        if tool in ("get_task_context", "get_dbt_artifacts"):
            try:
                incident = IncidentRef(incident_id="incident-001", **args)
            except (ValueError, TypeError):
                return result(Status.INVALID_INPUT, code="INVALID_INCIDENT")
            ref = TargetRef(incident=incident)
            scope = "run_snapshot"
            if incident.dag_id != "orders_demo" or incident.task_id not in TASKS:
                return result(Status.INVALID_INPUT, code="TARGET_NOT_ALLOWED")
            if incident.run_id != RUN_ID or incident.try_number != 1:
                return result(Status.EMPTY)
            expected = incident_for(self.fixture)
            if incident.execution_key() != expected.execution_key():
                return result(Status.EMPTY)
            messages = {
                "schema": 'column "amount" does not exist in model stg_orders',
                "quality": "not_null_orders_order_id failed: 3 null rows",
                "connection": "connection refused while connecting with dbt_orders (host/port not logged)",
                "normal": "All pipeline tasks and dbt tests succeeded",
                "insufficient": "Task failed; detailed log unavailable",
            }
            states = {t: "success" for t in TASKS}
            if self.fixture != "normal":
                states[expected.task_id] = "failed"
                states["publish_summary"] = "upstream_failed"
                if expected.task_id == "dbt_run":
                    states["dbt_test"] = "upstream_failed"
            if tool == "get_task_context":
                return result(Status.SUCCESS, {
                    "state": states[incident.task_id], "task_statuses": states,
                    "log_lines": [messages[self.fixture]][:200], "truncated": False,
                    "dbt_connection_id": "dbt_orders", "table_id": "raw.orders",
                    "run_started_at": "2026-10-20T07:00:00Z", "run_finished_at": "2026-10-20T07:01:00Z",
                })
            if self.fixture == "insufficient":
                return result(Status.UNAVAILABLE, code="ARTIFACT_NOT_ARCHIVED")
            issue = {"schema": "missing_column", "quality": "not_null", "connection": "connection_refused", "normal": None}[self.fixture]
            return result(Status.SUCCESS, {
                "invocation_id": "dbt-invocation-001", "manifest_invocation_id": "dbt-invocation-001",
                "run_results_invocation_id": "dbt-invocation-001", "issue": issue,
                "column_id": "amount" if self.fixture == "schema" else "order_id" if self.fixture == "quality" else None,
                "table_id": "raw.orders", "connection_id": "dbt_orders",
                "failed_node": None if self.fixture == "normal" else "model.orders.stg_orders",
                "potential_downstream": ["model.orders.daily_orders"],
                "test_results": {"not_null_order_id": "pass", "unique_order_id": "pass"} if self.fixture == "normal" else {"not_null_order_id": "fail"} if self.fixture == "quality" else {},
                "message": messages[self.fixture],
            })
        if tool == "compare_schema":
            ref = TargetRef(table_id=args.get("table_id", "unresolved"), baseline_id=args.get("baseline_id"))
            if args != {"table_id": "raw.orders", "baseline_id": "orders-v1"}:
                return result(Status.INVALID_INPUT, code="TARGET_NOT_ALLOWED")
            cols = {"order_id": "integer", "customer_id": "integer", "amount": "numeric", "created_at": "timestamp"}
            current = dict(cols)
            if self.fixture == "schema":
                current["paid_amount"] = current.pop("amount")
            return result(Status.SUCCESS, {"current_columns": current, "baseline_columns": cols,
                "baseline_observed_at": "2026-10-19T07:00:00Z", "baseline_id": "orders-v1",
                "removed": sorted(set(cols) - set(current)), "added": sorted(set(current) - set(cols)),
                "type_changes": [], "warning": "Current observation; not a historical run snapshot"})
        if tool == "get_quality_profile":
            ref = TargetRef(table_id=args.get("table_id", "unresolved"))
            if args.get("table_id") != "raw.orders" or args.get("column_ids") != ["order_id"] or set(args) != {"table_id", "column_ids"}:
                return result(Status.INVALID_INPUT, code="TARGET_NOT_ALLOWED")
            if self.fixture == "insufficient":
                return result(Status.UNAVAILABLE, code="PROFILE_TIMEOUT", retryable=True)
            return result(Status.SUCCESS, {"row_count": 1000, "null_counts": {"order_id": 3 if self.fixture == "quality" else 0},
                "duplicate_counts": {"order_id": 0}, "samples": [{"order_id": None} for _ in range(3)] if self.fixture == "quality" else [],
                "truncated": False, "warning": "Current observation; not a historical run snapshot"})
        ref = TargetRef(connection_id=args.get("connection_id", "unresolved"))
        if set(args) != {"connection_id"} or args["connection_id"] not in ("dbt_orders", "mcp_readonly"):
            return result(Status.INVALID_INPUT, code="TARGET_NOT_ALLOWED")
        return result(Status.SUCCESS, {"connected": not (self.fixture == "connection" and args["connection_id"] == "dbt_orders"),
            "error_type": "connection_refused" if self.fixture == "connection" and args["connection_id"] == "dbt_orders" else None,
            "scope": "Only the named connection at observation time; not proof of recovery"})

"""Airflow 2.10.4 /api/v1 + PostgreSQL 조회 전용 실제 수집기."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
import psycopg

from .artifact_store import ArtifactMismatch, ArtifactStore, redact
from .fixtures import TASKS, TOOLS
from .live_settings import LiveSettings
from .settings_policy import ProjectPolicy
from .models import Evidence, IncidentRef, Status, TargetRef, ToolError

MAX_LOG_LINES, MAX_LOG_BYTES, MAX_SAMPLES = 200, 40000, 5


def bounded_log(text: str) -> tuple[list[str], bool]:
    normalized = []
    for line in text.splitlines():
        offset = line.find('{"data":')
        if offset >= 0:
            try:
                event = json.loads(line[offset:])
                message = event.get("info", {}).get("msg")
                if isinstance(message, str):
                    normalized.extend(message.splitlines())
                    continue
            except ValueError:
                pass
        normalized.append(line)
    lines = redact("\n".join(normalized)).splitlines()
    selected = "\n".join(line[:2000] for line in lines[-MAX_LOG_LINES:])
    truncated = len(lines) > MAX_LOG_LINES or any(len(s) > 2000 for s in lines[-MAX_LOG_LINES:]) or len(selected.encode()) > MAX_LOG_BYTES
    selected = selected.encode()[-MAX_LOG_BYTES:].decode(errors="ignore")
    return selected.splitlines(), truncated


class LiveAdapter:
    transport = "direct_live_adapter"

    def __init__(self, settings: LiveSettings, *, http_transport=None):
        self.settings = settings
        policy=ProjectPolicy.load(settings.project_policy_path)
        matches=[t for t in policy.targets if t.id==settings.target_id]
        if len(matches)!=1:raise ValueError("LIVE_TARGET_NOT_CONFIGURED")
        self.target=matches[0]
        self.store = ArtifactStore(settings.artifact_root)
        self.http_transport = http_transport

    async def query(self, sql: str, params=(), *, port: int | None = None):
        kwargs = self.settings.observer.connect_kwargs()
        if port is not None:
            kwargs["port"] = port
        async with await psycopg.AsyncConnection.connect(**kwargs) as conn:
            async with conn.transaction():
                await conn.execute("SET TRANSACTION READ ONLY")
                await conn.execute("SET LOCAL statement_timeout = '7000ms'")
                cursor = await conn.execute(sql, params)
                return await cursor.fetchall()

    async def call(self, tool: str, args: dict) -> Evidence:
        ref, scope = TargetRef(table_id="unresolved"), "current_observation"
        source = "live://postgres/read-only"
        identity = json.dumps([tool, args, datetime.now(timezone.utc).isoformat()], sort_keys=True)

        def result(status, data=None, code=None, retryable=False):
            return Evidence(evidence_id="live-" + hashlib.sha256(identity.encode()).hexdigest()[:20], kind=tool,
                source=source, observed_at=datetime.now(timezone.utc), temporal_scope=scope, target_ref=ref, status=status,
                data=data, error=ToolError(code=code, retryable=retryable, message=code) if code else None, simulated=False)

        if tool not in TOOLS:
            return result(Status.INVALID_INPUT, code="TOOL_NOT_ALLOWED")
        try:
            if tool in ("get_task_context", "get_dbt_artifacts"):
                incident = IncidentRef(incident_id="selected-live-incident", **args)
                ref, scope = TargetRef(incident=incident), "run_snapshot"
                if incident.dag_id != self.target.dag_id or incident.task_id not in self.target.tasks:
                    return result(Status.INVALID_INPUT, code="TARGET_NOT_ALLOWED")
                source = "live://airflow/2.10.4/api/v1" if tool == "get_task_context" else "live://dbt/immutable-artifact-store"
                d, r, t = [quote(x, safe="") for x in (incident.dag_id, incident.run_id, incident.task_id)]
                prefix = f"/dags/{d}/dagRuns/{r}/taskInstances"
                async with httpx.AsyncClient(base_url=self.settings.airflow_url, auth=(self.settings.airflow_user, self.settings.airflow_password.get_secret_value()), timeout=8, trust_env=False, transport=self.http_transport) as client:
                    response = await client.get(f"{prefix}/{t}")
                    response.raise_for_status()
                    info = response.json()
                    actual = (info.get("dag_id"), info.get("dag_run_id"), info.get("task_id"), info.get("try_number"))
                    if actual != incident.execution_key():
                        return result(Status.INVALID_INPUT, code="TASK_IDENTITY_OR_ATTEMPT_MISMATCH")
                    if tool == "get_dbt_artifacts":
                        data = self.store.load(incident)
                        return result(Status.SUCCESS, data)
                    # 2.10.4 JSON LogResponseObject serializes chunk tuples as a repr string.
                    # The documented text/plain route streams the actual log text instead.
                    response = await client.get(f"{prefix}/{t}/logs/{incident.try_number}", params={"full_content": "true"}, headers={"Accept": "text/plain"})
                    response.raise_for_status()
                    if not response.headers.get("content-type", "").startswith("text/plain"):
                        return result(Status.UNAVAILABLE, code="UNSUPPORTED_LOG_PAYLOAD")
                    lines, truncated = bounded_log(response.text)
                    response = await client.get(prefix, params={"limit": 100})
                    response.raise_for_status()
                    collection = response.json()
                    tasks = {item["task_id"]: item["state"] for item in collection["task_instances"]}
                    if collection["total_entries"] != len(tasks) or set(tasks) != set(self.target.tasks):
                        return result(Status.UNAVAILABLE, code="INCOMPLETE_TASK_COLLECTION")
                    return result(Status.SUCCESS, {"state": info["state"], "task_statuses": tasks, "log_lines": lines,
                        "truncated": truncated, "dbt_connection_id": self.target.connection_id, "table_id": self.target.table_id, "quality_column": self.target.quality_column,
                        "run_started_at": info.get("start_date"), "run_finished_at": info.get("end_date"),
                        "log_try_number": incident.try_number, "tasks_complete": True})
            if tool in ("compare_schema", "get_quality_profile"):
                ref = TargetRef(table_id=args.get("table_id", "unresolved"), baseline_id=args.get("baseline_id"))
                if args.get("table_id") != self.target.table_id:
                    return result(Status.INVALID_INPUT, code="TARGET_NOT_ALLOWED")
            if tool == "compare_schema":
                if args != {"table_id": self.target.table_id, "baseline_id": self.target.baseline_id}:
                    return result(Status.INVALID_INPUT, code="BASELINE_NOT_ALLOWED")
                baseline = json.loads(self.settings.baseline_path.read_text())
                if baseline["baseline_id"] != self.target.baseline_id:
                    return result(Status.UNAVAILABLE, code="BASELINE_ID_MISMATCH")
                rows = await self.query("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position", tuple(self.target.table_id.split(".")))
                if not rows:
                    return result(Status.EMPTY)
                current, expected = dict(rows), baseline["columns"]
                return result(Status.SUCCESS, {"current_columns": current, "baseline_columns": expected,
                    "baseline_id": baseline["baseline_id"], "baseline_observed_at": baseline["observed_at"],
                    "removed": sorted(set(expected) - set(current)), "added": sorted(set(current) - set(expected)),
                    "type_changes": [{"column_id": k, "before": expected[k], "after": current[k]} for k in expected.keys() & current.keys() if expected[k] != current[k]],
                    "warning": "Current observation, not failed-run snapshot"})
            if tool == "get_quality_profile":
                if args != {"table_id": self.target.table_id, "column_ids": [self.target.quality_column]}:
                    return result(Status.INVALID_INPUT, code="COLUMN_NOT_ALLOWED")
                table=psycopg.sql.Identifier(*self.target.table_id.split('.'))
                column=psycopg.sql.Identifier(self.target.quality_column)
                counts = await self.query(psycopg.sql.SQL("SELECT count(*), count(*) FILTER (WHERE {c} IS NULL), count({c})-count(DISTINCT {c}) FROM {t}").format(c=column,t=table))
                samples = await self.query(psycopg.sql.SQL("SELECT {c} FROM {t} WHERE {c} IS NULL LIMIT %s").format(c=column,t=table), (self.target.max_profile_samples,))
                count, nulls, duplicates = counts[0]
                return result(Status.SUCCESS, {"row_count": count, "null_counts": {self.target.quality_column: nulls}, "duplicate_counts": {self.target.quality_column: duplicates},
                    "samples": [{self.target.quality_column: row[0]} for row in samples][:self.target.max_profile_samples], "truncated": nulls > self.target.max_profile_samples,
                    "warning": "Current observation, not failed-run snapshot"})
            ref = TargetRef(connection_id=args.get("connection_id", "unresolved"))
            if set(args) != {"connection_id"} or args["connection_id"] not in (self.target.connection_id, "mcp_readonly"):
                return result(Status.INVALID_INPUT, code="CONNECTION_NOT_ALLOWED")
            port = self.settings.observer.port
            if args["connection_id"] == self.target.connection_id:
                endpoint = json.loads(self.settings.endpoint_path.read_text())
                if endpoint.get("host") != "127.0.0.1" or not isinstance(endpoint.get("port"), int) or not 1024 <= endpoint["port"] <= 65535:
                    return result(Status.UNAVAILABLE, code="INVALID_DEVELOPER_ENDPOINT")
                port = endpoint["port"]
            try:
                await self.query("SELECT 1", port=port)
                connected, error = True, None
            except psycopg.OperationalError as exc:
                connected, error = False, "connection_refused" if "connection refused" in str(exc).lower() else "connection_unavailable"
            return result(Status.SUCCESS, {"connected": connected, "error_type": error, "endpoint": {"host": "127.0.0.1", "port": port},
                "probe_role": "read_only_observer", "scope": "Only this named endpoint now; not proof of failed dbt process configuration or pipeline recovery"})
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 404:
                return result(Status.EMPTY)
            return result(Status.UNAVAILABLE, code="AUTH_DENIED" if code in (401, 403) else f"AIRFLOW_HTTP_{code}", retryable=code >= 500)
        except (httpx.TimeoutException, httpx.NetworkError):
            return result(Status.UNAVAILABLE, code="AIRFLOW_NETWORK_UNAVAILABLE", retryable=True)
        except ArtifactMismatch:
            return result(Status.INVALID_INPUT, code="ARTIFACT_IDENTITY_OR_HASH_MISMATCH")
        except FileNotFoundError:
            return result(Status.UNAVAILABLE, code="ARTIFACT_OR_BASELINE_NOT_ARCHIVED")
        except psycopg.OperationalError:
            return result(Status.UNAVAILABLE, code="POSTGRES_UNAVAILABLE", retryable=True)
        except (ValueError, TypeError, KeyError):
            return result(Status.INVALID_INPUT, code="INVALID_INPUT_OR_UPSTREAM_PAYLOAD")

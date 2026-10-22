"""실제 dbt 호출별 불변 보관 및 실행/시도/내용 해시 검증."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import IncidentRef


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def redact(text: str) -> str:
    text = re.sub(r"(?i)(password|token|authorization|api_key)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", text)
    return re.sub(r"(?i)(postgres(?:ql)?://)[^@\s]+@", r"\1[REDACTED]@", text)


class ArtifactMismatch(ValueError):
    pass


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def directory(self, ref: IncidentRef) -> Path:
        return self.root / digest(ref.execution_key())

    def save(self, ref: IncidentRef, command: str, call_id: str, target: Path, stdout: str, exit_code: int, elapsed: float) -> Path:
        directory = self.directory(ref) / call_id
        directory.mkdir(parents=True, exist_ok=False)
        hashes, objects = {}, {}
        for name in ("manifest", "run_results"):
            path = target / f"{name}.json"
            if path.is_file():
                obj = json.loads(path.read_text())
                objects[name] = obj
                hashes[name] = digest(obj)
                (directory / path.name).write_text(json.dumps(obj, ensure_ascii=False))
        invocation_ids = {obj["metadata"]["invocation_id"] for obj in objects.values()}
        if len(invocation_ids) > 1:
            raise ArtifactMismatch("manifest/run_results invocation mismatch")
        log_invocations = set()
        for line in stdout.splitlines():
            try:
                item = json.loads(line)
                value = item.get("info", {}).get("invocation_id")
                if value:
                    log_invocations.add(value)
            except (ValueError, AttributeError):
                pass
        if invocation_ids and log_invocations and not invocation_ids.issubset(log_invocations):
            raise ArtifactMismatch("stdout invocation mismatch")
        invocation = next(iter(invocation_ids), None) or (next(iter(log_invocations)) if len(log_invocations) == 1 else None)
        safe_log = redact(stdout)
        (directory / "stdout.log").write_text(safe_log)
        receipt = {"incident_ref": ref.model_dump(mode="json"), "command": command, "call_id": call_id,
                   "invocation_id": invocation, "exit_code": exit_code, "elapsed_seconds": elapsed,
                   "stdout_invocation_ids": sorted(log_invocations),
                   "archived_at": datetime.now(timezone.utc).isoformat(), "hashes": hashes,
                   "stdout_sha256": hashlib.sha256(safe_log.encode()).hexdigest(), "simulated": False}
        (directory / "receipt.json").write_text(json.dumps(receipt, indent=2))
        return directory

    def load(self, ref: IncidentRef) -> dict:
        choices = list(self.directory(ref).glob("*/receipt.json"))
        if not choices:
            raise FileNotFoundError("No invocation archived for the selected execution")
        if len(choices) != 1:
            raise ArtifactMismatch("Ambiguous invocation selection for task attempt")
        receipt_path = choices[0]
        receipt = json.loads(receipt_path.read_text())
        bound = IncidentRef.model_validate(receipt["incident_ref"])
        if bound.execution_key() != ref.execution_key():
            raise ArtifactMismatch("Foreign run/task/try binding")
        objects = {}
        for name, expected in receipt["hashes"].items():
            obj = json.loads((receipt_path.parent / f"{name}.json").read_text())
            if digest(obj) != expected or obj.get("metadata", {}).get("invocation_id") != receipt["invocation_id"]:
                raise ArtifactMismatch("Artifact content/invocation mismatch")
            objects[name] = obj
        stdout = (receipt_path.parent / "stdout.log").read_text()
        if hashlib.sha256(stdout.encode()).hexdigest() != receipt["stdout_sha256"]:
            raise ArtifactMismatch("Command log content mismatch")
        return parse_dbt(objects.get("manifest"), objects.get("run_results"), stdout, receipt)


def parse_dbt(manifest: dict | None, results: dict | None, stdout: str, receipt: dict) -> dict:
    nodes = (manifest or {}).get("nodes", {})
    parsed, quality, failed = [], {}, []
    for row in (results or {}).get("results", []):
        uid = row["unique_id"]
        if uid not in nodes:
            raise ArtifactMismatch("Result node absent from paired manifest")
        node = nodes[uid]
        parsed.append({"unique_id": uid, "resource_type": node["resource_type"], "status": row["status"],
                       "message": redact(row.get("message") or ""), "depends_on": node.get("depends_on", {}).get("nodes", [])})
        if row["status"] in ("error", "fail"):
            failed.append(uid)
        test = node.get("test_metadata", {}) or {}
        if test.get("name") in ("not_null", "unique") and test.get("kwargs", {}).get("column_name") == "order_id":
            quality[f"{test['name']}_order_id"] = row["status"]
    text = stdout.lower() + " " + " ".join(x["message"].lower() for x in parsed)
    issue, column = None, None
    if re.search(r'column\s+"?amount"?\s+does not exist', text):
        issue, column = "missing_column", "amount"
    elif quality.get("not_null_order_id") == "fail":
        issue, column = "not_null", "order_id"
    elif "connection refused" in text:
        issue = "connection_refused"
    downstream, pending = set(), list(failed)
    children = (manifest or {}).get("child_map", {})
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in downstream:
                downstream.add(child)
                pending.append(child)
    return {"invocation_id": receipt["invocation_id"],
            "manifest_invocation_id": (manifest or {}).get("metadata", {}).get("invocation_id"),
            "run_results_invocation_id": (results or {}).get("metadata", {}).get("invocation_id"),
            "artifact_status": "complete" if manifest is not None and results is not None else "partial",
            "available_artifacts": sorted(receipt["hashes"]), "command": receipt["command"],
            "missing_artifacts": [name for name in ("manifest", "run_results") if name not in receipt["hashes"]],
            "stdout_invocation_ids": receipt.get("stdout_invocation_ids", []), "command_log_sha256": receipt["stdout_sha256"],
            "exit_code": receipt["exit_code"], "issue": issue, "column_id": column, "table_id": "raw.orders",
            "connection_id": "dbt_orders", "results": parsed, "test_results": quality,
            "failed_node": failed[0] if failed else None, "actual_failed": failed,
            "potential_downstream": sorted(downstream - set(failed)), "content_hashes": receipt["hashes"],
            "archived_at": receipt["archived_at"], "message": "\n".join(x["message"] for x in parsed)[-4000:]}

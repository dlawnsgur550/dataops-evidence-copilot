"""체크포인트4 실제 E2E. 세 실패 진단은 Luna, 정상·복구 판정용 수집은 fake. 자동 API 재시도 없음."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg

from dataops_copilot.fixtures import TASKS, TOOLS
from dataops_copilot.live_adapter import MAX_LOG_BYTES, MAX_LOG_LINES
from dataops_copilot.live_settings import LiveSettings
from dataops_copilot.llm import FakeLLM
from dataops_copilot.mcp_client import open_live_mcp
from dataops_copilot.models import IncidentRef, Status, Report
from dataops_copilot.recovery import check_recovery
from dataops_copilot.workflow import Copilot, Limits
from dataops_copilot.api_safety import read_api_settings
from dataops_copilot.openai_llm import OpenAILLM
from dataops_copilot.hybrid import HybridRunbooks

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT.parents[1] / "work" / "runtime"
RECORDS = ROOT / "artifacts" / "checkpoint4"
spec = importlib.util.spec_from_file_location("developer_driver", ROOT / "pipeline" / "driver.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


async def main():
    RECORDS.mkdir(parents=True, exist_ok=True)
    if (RECORDS / "live-e2e.json").exists() and json.loads((RECORDS / "live-e2e.json").read_text()).get("success"):
        print(json.dumps({"success": True, "stored_completed_run": True, "new_api_calls": 0, "note": "Use --fresh for an explicit new paid experiment; existing results are preserved."}))
        return
    key, _ = read_api_settings(RUNTIME / "openai.env")
    retriever = HybridRunbooks()
    started = time.monotonic()
    developer = json.loads((RUNTIME / "developer-api.json").read_text())
    config = json.loads((RUNTIME / "driver-settings.json").read_text())
    settings = LiveSettings.load(RUNTIME / "live-settings.json")
    results = {"started_at": datetime.now(timezone.utc).isoformat(), "scope": {"airflow": "actual_local_2.10.4", "postgres": "actual_local_17.10", "dbt": "actual_local_1.9.10_postgres_1.9.1", "llm": "gpt-6-luna for three failures; fake for normal/followup collection"}, "runs": [], "recoveries": [], "checks": {}, "success": False}

    previous_results = RECORDS / "live-e2e.json"
    if previous_results.exists():
        results = json.loads(previous_results.read_text())
        results.pop("failure", None)

    def save():
        (RECORDS / "live-e2e.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))

    async with httpx.AsyncClient(base_url=developer["url"], auth=(developer["user"], developer["password"]), timeout=10, trust_env=False) as admin:
        async def trigger(mode):
            run_id = "manual__" + uuid4().hex
            response = await admin.post("/dags/orders_demo/dagRuns", json={"dag_run_id": run_id, "conf": {"mode": mode}})
            response.raise_for_status()
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                response = await admin.get(f"/dags/orders_demo/dagRuns/{run_id}")
                response.raise_for_status()
                state = response.json()["state"]
                if state in ("success", "failed"):
                    tasks = await admin.get(f"/dags/orders_demo/dagRuns/{run_id}/taskInstances")
                    tasks.raise_for_status()
                    items = tasks.json()["task_instances"]
                    results["runs"].append({"mode_developer_only": mode, "run_id": run_id, "state": state,
                        "task_statuses": {t["task_id"]: t["state"] for t in items}, "tries": {t["task_id"]: t["try_number"] for t in items}})
                    save()
                    print(json.dumps(results["runs"][-1]), flush=True)
                    return run_id, state, items
                await asyncio.sleep(1)
            raise TimeoutError("실제 DAG 실행 완료 시간 초과: " + run_id)

        # DAG parsing and permissions are allowed to settle without changing its source.
        for _ in range(45):
            response = await admin.get("/dags/orders_demo")
            if response.status_code == 200:
                break
            await asyncio.sleep(1)
        response.raise_for_status()
        response = await admin.patch("/dags/orders_demo", json={"is_paused": False})
        response.raise_for_status()
        try:
            async with open_live_mcp(RUNTIME / "live-settings.json") as mcp:
                assert {t.name for t in mcp.tool_list.tools} == TOOLS
                results["protocol"] = {"initialize": mcp.initialization.model_dump(mode="json"), "tools": mcp.tool_list.model_dump(mode="json"), "sessions": 1}

                async def diagnose(run_id, items, task, label):
                    ti = next(t for t in items if t["task_id"] == task)
                    ref = IncidentRef(incident_id=uuid4().hex, dag_id="orders_demo", run_id=run_id, task_id=task, try_number=ti["try_number"])
                    llm = OpenAILLM(key, RUNTIME, purpose="evaluation") if label in ("schema", "quality", "connection") else FakeLLM()
                    report = await Copilot(mcp, llm, retriever=retriever, limits=Limits(llm_calls=4)).diagnose(ref)
                    (RECORDS / f"live-{label}-incident.json").write_text(ref.model_dump_json(indent=2))
                    (RECORDS / f"live-{label}-report.json").write_text(report.model_dump_json(indent=2))
                    assert report.review.accepted, report.review.violations
                    assert all(not e.simulated for e in report.evidence), "실제 결과에 fixture가 혼입됐습니다."
                    context = next(e for e in report.evidence if e.kind == "get_task_context")
                    if context.status == Status.SUCCESS:
                        assert len(context.data["log_lines"]) <= MAX_LOG_LINES
                        assert len("\n".join(context.data["log_lines"]).encode()) <= MAX_LOG_BYTES
                    profile = next((e for e in report.evidence if e.kind == "get_quality_profile"), None)
                    if profile is not None and profile.status == Status.SUCCESS:
                        assert len(profile.data["samples"]) <= 5
                    return ref, report

                if not any(r["mode_developer_only"] == "normal" for r in results["runs"]):
                    run_id, state, items = await trigger("normal")
                    assert state == "success"
                    _, normal = await diagnose(run_id, items, "dbt_test", "normal")
                    assert normal.diagnosis.category == "NORMAL", normal.model_dump_json()
                    results["checks"]["normal_aggregate"] = driver.verify_aggregates(config)
                    save()
                for case, category, failed_task in (("schema", "SCHEMA_CHANGE", "dbt_run"), ("quality", "DATA_QUALITY", "dbt_test"), ("connection", "CONNECTION_FAILURE", "dbt_run")):
                    if any(r["case_developer_only"] == case for r in results["recoveries"]):
                        continue
                    saved_report = RECORDS / f"live-{case}-report.json"
                    previous_runs = [r for r in results["runs"] if r["mode_developer_only"] == case]
                    if saved_report.exists() and previous_runs:
                        report = Report.model_validate_json(saved_report.read_text())
                        original = report.incident_ref
                        assert report.review.accepted, report.review.violations
                    else:
                        run_id, state, items = await trigger(case)
                        assert state == "failed"
                        original, report = await diagnose(run_id, items, failed_task, case)
                    assert report.diagnosis.category == category, report.model_dump_json()
                    if case == "connection":
                        other = await mcp.call("check_connection", {"connection_id": "mcp_readonly"})
                        selected = next(e for e in report.evidence if e.kind == "check_connection")
                        assert other.data["connected"] and not selected.data["connected"]
                        results["checks"]["different_connection"] = {"observer": other.model_dump(mode="json"), "dbt_endpoint": selected.model_dump(mode="json"), "diagnosis": category}
                    action = driver.repair(config, case)
                    new_run, new_state, new_items = await trigger("verify")
                    assert new_state == "success"
                    followup, follow_report = await diagnose(new_run, new_items, "dbt_test", case + "-followup")
                    assert follow_report.diagnosis.category == "NORMAL"
                    context = next(e for e in follow_report.evidence if e.kind == "get_task_context")
                    artifacts = next(e for e in follow_report.evidence if e.kind == "get_dbt_artifacts")
                    recovery = check_recovery(original, followup, context, artifacts)
                    assert recovery.recovered
                    aggregate = driver.verify_aggregates(config)
                    results["recoveries"].append({"case_developer_only": case, "original_run_id": original.run_id, "followup_run_id": new_run,
                        "action": action, "recovery_check": recovery.model_dump(), "aggregate": aggregate})
                    save()
                # Invalid target remains structured and missing run is not an I/O failure.
                invalid = await mcp.call("compare_schema", {"table_id": "raw.orders; DROP TABLE x", "baseline_id": "orders-v1"})
                missing = await mcp.call("get_task_context", {"dag_id": "orders_demo", "run_id": "absent", "task_id": "dbt_run", "try_number": 1})
                assert invalid.status == Status.INVALID_INPUT and missing.status == Status.EMPTY
                results["checks"]["negative_tool_statuses"] = [invalid.model_dump(mode="json"), missing.model_dump(mode="json")]
            # Server-side privileges are tested separately from the read-only transaction wrapper.
            writes = []
            for sql in ("INSERT INTO raw.orders (order_id) VALUES (999999)", "UPDATE raw.orders SET order_id=order_id WHERE false", "CREATE TABLE public.denied_probe (id integer)"):
                with psycopg.connect(**settings.observer.connect_kwargs(), autocommit=True) as conn:
                    conn.execute("SET default_transaction_read_only = off")
                    try:
                        with conn.transaction():
                            conn.execute(sql)
                            raise AssertionError("읽기 전용 계정에 쓰기 권한이 있습니다.")
                    except psycopg.errors.InsufficientPrivilege as exc:
                        writes.append({"sql_kind": sql.split()[0], "sqlstate": exc.sqlstate, "denied": True})
            results["checks"]["postgres_write_denied"] = writes
            async with httpx.AsyncClient(auth=(settings.airflow_user, settings.airflow_password.get_secret_value()), timeout=5, trust_env=False) as viewer:
                denied = await viewer.post(settings.airflow_url + "/dags/orders_demo/dagRuns", json={"dag_run_id": "must_not_exist", "conf": {}})
                assert denied.status_code == 403
                results["checks"]["airflow_viewer_write_denied"] = denied.status_code
            results["checks"]["aggregate_after_denied_writes"] = driver.verify_aggregates(config)
            results["success"] = True
        except Exception as exc:
            results["failure"] = {"type": type(exc).__name__, "message": str(exc)[:10000]}
            raise
        finally:
            results["elapsed_seconds"] = round(time.monotonic() - started, 3)
            results["finished_at"] = datetime.now(timezone.utc).isoformat()
            save()
            retriever.close()
    print(json.dumps({"success": True, "runs": len(results["runs"]), "recoveries": len(results["recoveries"]), "elapsed_seconds": results["elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="실제 장애 3종과 유료 LLM. 기존 성공 기록은 재호출하지 않습니다.")
    parser.add_argument("--fresh", action="store_true", help="새 결과 폴더에서 장애를 주입하고 유료 진단합니다.")
    args = parser.parse_args()
    if args.fresh:
        RECORDS = RECORDS / ("e2e-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    asyncio.run(main())

"""실제 DB의 8개 오류 행과 실제 200줄 초과 태스크 로그로 MCP 반환 상한 검사."""
import asyncio
import importlib.util
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx

from dataops_copilot.mcp_client import open_live_mcp
from dataops_copilot.models import Status

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT.parents[1] / "work" / "runtime"
RECORDS = ROOT / "artifacts" / "checkpoint2"
spec = importlib.util.spec_from_file_location("developer_driver", ROOT / "pipeline" / "driver.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


async def main():
    config = json.loads((RUNTIME / "driver-settings.json").read_text())
    api = json.loads((RUNTIME / "developer-api.json").read_text())
    results = {"scope": "actual local systems, developer-only temporary data mutation", "success": False}
    async with open_live_mcp(RUNTIME / "live-settings.json") as mcp:
        # Original source keys are restored in finally. All changes are in the guarded demo DB.
        try:
            with driver.connect(config) as conn:
                originals = conn.execute("SELECT order_id, created_at FROM raw.orders ORDER BY order_id LIMIT 8").fetchall()
                assert len(originals) == 8
                conn.execute("UPDATE raw.orders SET order_id=NULL WHERE order_id BETWEEN 1 AND 8")
            profile = await mcp.call("get_quality_profile", {"table_id": "raw.orders", "column_ids": ["order_id"]})
            assert profile.status == Status.SUCCESS and not profile.simulated
            assert profile.data["null_counts"]["order_id"] == 8 and len(profile.data["samples"]) == 5 and profile.data["truncated"]
            results["profile"] = profile.model_dump(mode="json")
        finally:
            with driver.connect(config) as conn:
                with conn.cursor() as cur:
                    cur.executemany("UPDATE raw.orders SET order_id=%s WHERE created_at=%s", originals)
        async with httpx.AsyncClient(base_url=api["url"], auth=(api["user"], api["password"]), timeout=5, trust_env=False) as client:
            run_id = "manual__" + uuid4().hex
            response = await client.post("/dags/orders_demo/dagRuns", json={"dag_run_id": run_id, "conf": {"mode": "verify", "log_probe": True}})
            response.raise_for_status()
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                response = await client.get(f"/dags/orders_demo/dagRuns/{run_id}")
                response.raise_for_status()
                state = response.json()["state"]
                if state in ("success", "failed"):
                    break
                await asyncio.sleep(1)
            assert state == "success"
            log = await mcp.call("get_task_context", {"dag_id": "orders_demo", "run_id": run_id, "task_id": "load_demo_data", "try_number": 1})
            assert log.status == Status.SUCCESS and not log.simulated
            text = "\n".join(log.data["log_lines"])
            assert log.data["truncated"] and len(log.data["log_lines"]) <= 200 and len(text.encode()) <= 40000
            assert "bounded-log-probe" in text, "DAG의 상한 검사 변경이 아직 파싱되지 않았습니다."
            results["log"] = log.model_dump(mode="json")
            results["run_id"] = run_id
            results["returned_log_lines"] = len(log.data["log_lines"])
            results["returned_log_bytes"] = len(text.encode())
    results["aggregate_after_restore"] = driver.verify_aggregates(config)
    results["success"] = True
    (RECORDS / "live-limits.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in results.items() if k not in ("log", "profile")}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

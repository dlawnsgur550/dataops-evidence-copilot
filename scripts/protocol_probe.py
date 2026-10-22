"""Run with `uv run python scripts/protocol_probe.py`; no network services start."""
import asyncio
import json
from pathlib import Path

from dataops_copilot.fixtures import incident_for
from dataops_copilot.mcp_client import open_mcp


async def main():
    args = incident_for("connection").model_dump(exclude={"incident_id"})
    calls = [("get_task_context", args), ("get_dbt_artifacts", args),
             ("compare_schema", {"table_id": "raw.orders", "baseline_id": "orders-v1"}),
             ("get_quality_profile", {"table_id": "raw.orders", "column_ids": ["order_id"]}),
             ("check_connection", {"connection_id": "dbt_orders"}),
             ("check_connection", {"connection_id": "mcp_readonly"}),
             ("get_task_context", {**args, "run_id": "absent"}),
             ("compare_schema", {"table_id": "forbidden", "baseline_id": "orders-v1"})]
    async with open_mcp("connection") as client:
        output = {"scope": "REAL MCP stdio protocol with synthetic backend; no Airflow/PostgreSQL",
                  "initialize": client.initialization.model_dump(mode="json"),
                  "tools_list": client.tool_list.model_dump(mode="json"), "tools_call": [], "session_count": 1}
        for tool, arguments in calls:
            result = await client.call(tool, arguments)
            output["tools_call"].append({"tool": tool, "arguments": arguments, "result": result.model_dump(mode="json")})
    # Exit of both SDK contexts above closes this stdio server subprocess.
    output["session_context_closed"] = True
    path = Path("artifacts/protocol-session.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"protocol": output["initialize"]["protocolVersion"], "tool_count": len(output["tools_list"]["tools"]),
                      "calls": len(calls), "context_closed": True, "artifact": str(path.resolve())}, indent=2))


asyncio.run(main())

import pytest

from dataops_copilot.fixtures import TOOLS, incident_for
from dataops_copilot.llm import FakeLLM
from dataops_copilot.mcp_client import open_mcp
from dataops_copilot.models import Status
from dataops_copilot.workflow import Copilot


@pytest.mark.parametrize("fixture,category", [("schema", "SCHEMA_CHANGE"), ("quality", "DATA_QUALITY"), ("connection", "CONNECTION_FAILURE"), ("normal", "NORMAL"), ("insufficient", "UNKNOWN")])
async def test_real_stdio_initialize_list_and_graph_calls(fixture, category):
    # Genuine subprocess + SDK protocol; fixture DB/Airflow and fake LLM.
    async with open_mcp(fixture) as client:
        assert client.initialization.protocolVersion
        assert {t.name for t in client.tool_list.tools} == TOOLS
        assert all(t.annotations.readOnlyHint and not t.annotations.destructiveHint for t in client.tool_list.tools)
        report = await Copilot(client, FakeLLM()).diagnose(incident_for(fixture))
        assert report.diagnosis.category == category
        assert report.review.accepted
        assert report.validation_scope["transport"] == "real_mcp_stdio_synthetic_backend"
        assert all(e.simulated for e in report.evidence)


async def test_stdio_invalid_and_empty_are_structured_and_session_reused():
    async with open_mcp("schema") as client:
        item = await client.call("compare_schema", {"table_id": "../../etc/passwd", "baseline_id": "orders-v1"})
        assert item.status == Status.INVALID_INPUT
        args = incident_for("schema").model_dump(exclude={"incident_id"})
        missing = await client.call("get_task_context", {**args, "run_id": "absent"})
        assert missing.status == Status.EMPTY
        for _ in range(2):
            report = await Copilot(client, FakeLLM()).diagnose(incident_for("schema"))
            assert report.review.accepted

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .models import Evidence


class MCPToolClient:
    transport = "real_mcp_stdio_synthetic_backend"

    def __init__(self, session: ClientSession, initialization, tool_list, *, live=False):
        self.session = session
        self.initialization = initialization
        self.tool_list = tool_list
        if live:
            self.transport = "real_mcp_stdio_live_backend"
            self.data_scope = "synthetic_demo_data_on_live_airflow_postgres_dbt"
            self.external_systems = "live_local_airflow_postgres_dbt"

    async def call(self, tool: str, arguments: dict) -> Evidence:
        result = await self.session.call_tool(tool, arguments)
        if result.isError:
            raise ValueError("MCP tool returned protocol error")
        data = result.structuredContent
        if data is None:
            data = json.loads(next(block.text for block in result.content if block.type == "text"))
        return Evidence.model_validate(data)


@asynccontextmanager
async def open_mcp(fixture: str):
    async with _open(["--fixture", fixture]) as client:
        yield client


@asynccontextmanager
async def open_live_mcp(settings_path: Path):
    async with _open(["--settings", str(settings_path.resolve())], live=True) as client:
        yield client


@asynccontextmanager
async def _open(arguments: list[str], *, live=False):
    # Explicit process arguments; never searches user configuration or secrets.
    params = StdioServerParameters(command=sys.executable, args=["-m", "dataops_copilot.mcp_server", *arguments],
                                  env={"PYTHONUNBUFFERED": "1", "FASTMCP_CHECK_FOR_UPDATES": "off"})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialization = await session.initialize()
            tool_list = await session.list_tools()
            yield MCPToolClient(session, initialization, tool_list, live=live)

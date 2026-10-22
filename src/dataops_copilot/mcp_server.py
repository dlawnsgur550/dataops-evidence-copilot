"""Standalone FastMCP package server; fixture backend, no service daemons."""
import argparse
from pathlib import Path

from fastmcp import FastMCP

from .fixtures import FIXTURES, FixtureAdapter
from .models import Evidence


def create_server(adapter) -> FastMCP:
    server = FastMCP("DataOps read-only synthetic evidence" if isinstance(adapter, FixtureAdapter) else "DataOps read-only live local evidence", version="0.3.1")
    hints = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False, "idempotentHint": True}

    @server.tool(annotations=hints)
    async def get_task_context(dag_id: str, run_id: str, task_id: str, try_number: int) -> Evidence:
        """선택한 데모 태스크와 최대 200줄 로그 조회. 실행 없음은 empty, 금지 입력은 invalid_input, 조회 실패는 unavailable. 어댑터에 따라 fixture 또는 실제 로컬 시스템입니다."""
        return await adapter.call("get_task_context", {"dag_id": dag_id, "run_id": run_id, "task_id": task_id, "try_number": try_number})

    @server.tool(annotations=hints)
    async def get_dbt_artifacts(dag_id: str, run_id: str, task_id: str, try_number: int) -> Evidence:
        """선택한 실행·시도·invocation에 연결된 dbt 보관 자료 조회. 없는 실행은 empty, 미보관은 unavailable, 잘못된 대상·해시는 invalid_input. 누락 파일을 만들지 않습니다."""
        return await adapter.call("get_dbt_artifacts", {"dag_id": dag_id, "run_id": run_id, "task_id": task_id, "try_number": try_number})

    @server.tool(annotations=hints)
    async def compare_schema(table_id: str, baseline_id: str) -> Evidence:
        """현재 raw.orders와 orders-v1 기준 스키마 비교. 현재 관측은 과거 스냅샷이 아닙니다. 다른 대상은 invalid_input입니다."""
        return await adapter.call("compare_schema", {"table_id": table_id, "baseline_id": baseline_id})

    @server.tool(annotations=hints)
    async def get_quality_profile(table_id: str, column_ids: list[str]) -> Evidence:
        """현재 raw.orders/order_id 통계와 최대 5개 오류 샘플 조회. 다른 대상은 invalid_input, 일시적 실패는 unavailable입니다."""
        return await adapter.call("get_quality_profile", {"table_id": table_id, "column_ids": column_ids})

    @server.tool(annotations=hints)
    async def check_connection(connection_id: str) -> Evidence:
        """dbt_orders 또는 mcp_readonly의 현재 지정 endpoint만 조회 전용 계정으로 검사. 성공은 해당 관측 대상에만 적용되며 실패한 dbt 실행의 설정 정상이나 파이프라인 복구를 뜻하지 않습니다."""
        return await adapter.call("check_connection", {"connection_id": connection_id})

    return server


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fixture", choices=FIXTURES)
    group.add_argument("--settings", type=Path)
    args = parser.parse_args()
    if args.settings:
        from .live_adapter import LiveAdapter
        from .live_settings import LiveSettings
        adapter = LiveAdapter(LiveSettings.load(args.settings))
    else:
        adapter = FixtureAdapter(args.fixture)
    create_server(adapter).run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()

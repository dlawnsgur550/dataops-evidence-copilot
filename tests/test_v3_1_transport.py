from dataops_copilot.mcp_client import open_mcp
from dataops_copilot.fixtures import incident_for


async def test_child_uses_current_application_even_in_shared_environment():
    async with open_mcp('normal') as client:
        assert client.initialization.serverInfo.version=='0.3.1'
        e=await client.call('get_task_context',incident_for('normal').model_dump(exclude={'incident_id'}))
        assert e.status=='success'

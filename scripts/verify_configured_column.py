"""Actual read-only MCP column configuration check; no model or DB write."""
import asyncio
import json
from pathlib import Path
from dataops_copilot.mcp_client import open_live_mcp
from dataops_copilot.settings_policy import ProjectPolicy

ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT.parents[1]/'work/runtime';PRIVATE=ROOT.parents[1]/'work/v3/configured-reader'


async def main():
    PRIVATE.mkdir(mode=0o700,exist_ok=True)
    p=ProjectPolicy.load().model_dump();t=p['targets'][0]
    t.update(quality_column='customer_id',required_tests=['not_null_customer_id','unique_order_id'])
    policy_path=PRIVATE/'policy.json';policy_path.write_text(json.dumps(p,indent=2));policy_path.chmod(0o600)
    settings=json.loads((RUNTIME/'live-settings.json').read_text());settings.update(project_policy_path=str(policy_path.resolve()),target_id='orders')
    settings_path=PRIVATE/'reader.json';settings_path.write_text(json.dumps(settings));settings_path.chmod(0o600)
    async with open_live_mcp(settings_path) as mcp:
        assert mcp.initialization.serverInfo.version=='0.3.1'
        profile=await mcp.call('get_quality_profile',{'table_id':'raw.orders','column_ids':['customer_id']})
        invalid=await mcp.call('get_quality_profile',{'table_id':'raw.orders','column_ids':['customer_id; DROP']})
        assert profile.status=='success' and profile.data['row_count']==100000 and profile.data['null_counts']=={'customer_id':0}
        assert profile.data['duplicate_counts']=={'customer_id':99900} and invalid.status=='invalid_input'
        result={'success':True,'scope':'actual read-only configured customer_id profile only; not a DAG diagnosis under a changed test contract','server':mcp.initialization.serverInfo.model_dump(),'policy':p,
          'profile':profile.model_dump(mode='json'),'invalid_column':invalid.model_dump(mode='json'),'additional_api_calls':0,'database_writes':0}
        (ROOT/'artifacts/v3.1/configured-column.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'success':True,'server_version':'0.3.1','row_count':100000,'duplicate_customer_ids':99900,'database_writes':0,'api_calls':0}))

if __name__=='__main__':asyncio.run(main())

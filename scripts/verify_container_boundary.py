"""Verify actual narrow container mounts and a fresh pipeline run; no model calls."""
import argparse,asyncio,json,subprocess,time,uuid
from pathlib import Path
import httpx
from dataops_copilot.mcp_client import open_live_mcp
from dataops_copilot.models import IncidentRef

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT.parents[1]/'work/runtime'
DEST=ROOT/'artifacts/v3'
DEST.mkdir(exist_ok=True)

async def main(row_count=1000):
    info=json.loads(subprocess.check_output(['docker','inspect','dataops-c-cp2-airflow'],text=True))[0]
    sources={row['Source'] for row in info['Mounts']}
    assert str(ROOT.parents[1]) not in sources and str(RUNTIME) not in sources
    key_path=RUNTIME/'openai.env'
    assert key_path.is_file()
    inaccessible=subprocess.run(['docker','exec','dataops-c-cp2-airflow','sh','-c','test ! -e "$1"','probe',str(key_path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    assert inaccessible,'HOST_API_KEY_VISIBLE_IN_AIRFLOW_CONTAINER'
    assert not any(v.split('=',1)[0].startswith('OPENAI_') for v in info['Config']['Env'])
    api=json.loads((RUNTIME/'developer-api.json').read_text())
    run='boundary-'+uuid.uuid4().hex
    async with httpx.AsyncClient(base_url=api['url'],auth=(api['user'],api['password']),timeout=10,trust_env=False) as client:
        response=await client.post('/dags/orders_demo/dagRuns',json={'dag_run_id':run,'conf':{'mode':'verify','rows':row_count}});response.raise_for_status()
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            response=await client.get('/dags/orders_demo/dagRuns/'+run);response.raise_for_status()
            state=response.json()['state']
            if state in ('success','failed'):break
            await asyncio.sleep(1)
        assert state=='success','NARROW_MOUNT_PIPELINE_FAILED'
        tasks=await client.get('/dags/orders_demo/dagRuns/'+run+'/taskInstances');tasks.raise_for_status()
        statuses={t['task_id']:t['state'] for t in tasks.json()['task_instances']}
        assert all(s=='success' for s in statuses.values())
    async with open_live_mcp(RUNTIME/'live-settings.json') as client:
        ref=IncidentRef(incident_id='mount-check',dag_id='orders_demo',run_id=run,task_id='dbt_test',try_number=1)
        artifact=await client.call('get_dbt_artifacts',ref.model_dump(exclude={'incident_id'}))
        assert artifact.status=='success' and all(s=='pass' for s in artifact.data['test_results'].values())
    result={'success':True,'api_key_not_visible_in_container':True,'openai_environment_absent':True,'whole_workspace_not_mounted':True,
      'mounts':[{'source':m['Source'],'read_only':not m['RW']} for m in info['Mounts']], 'verification_run_id':run,'task_statuses':statuses,'dbt_tests':artifact.data['test_results'],'model_api_calls':0}
    (DEST/'container-boundary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'success':True,'api_key_not_visible_in_container':True,'verification_run_id':run,'model_api_calls':0}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--rows',type=int,default=1000);args=p.parse_args();asyncio.run(main(args.rows))

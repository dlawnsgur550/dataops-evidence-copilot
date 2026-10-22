"""개발자 전용 DAG. 초기화·장애 주입·실행은 MCP 도구에 노출하지 않습니다."""
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator

ROOT = Path(os.environ["C_DATAOPS_ROOT"])


def run_step(**context):
    ti = context["ti"]
    ref = {"incident_id": "live-incident", "dag_id": ti.dag_id, "run_id": ti.run_id, "task_id": ti.task_id, "try_number": ti.try_number}
    mode = context["dag_run"].conf.get("mode", "normal")
    if ti.task_id == "load_demo_data" and context["dag_run"].conf.get("log_probe") is True:
        # 개발자용 응답 상한 실험. 고정 텍스트이며 실행 지시를 받지 않습니다.
        for i in range(230):
            print(f"bounded-log-probe-{i:03d} " + "x" * 512)
    result = subprocess.run([os.environ["C_DATAOPS_APP_PYTHON"], str(ROOT / "pipeline" / "driver.py"),
        "--config", os.environ["C_DATAOPS_DRIVER_CONFIG"], "--step", ti.task_id,
        "--incident", json.dumps(ref), "--mode", mode, "--rows", str(context["dag_run"].conf.get("rows",1000))], check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout, flush=True)
    if result.returncode:
        raise RuntimeError("선택된 파이프라인 단계가 실패했습니다. 보존된 호출 산출물을 확인하세요.")


with DAG("orders_demo", start_date=datetime(2026, 1, 1), schedule=None, catchup=False, max_active_runs=1,
         default_args={"retries": 0}, tags=["dataops-c-isolated-demo"]) as dag:
    tasks = [PythonOperator(task_id=t, python_callable=run_step) for t in ("load_demo_data", "dbt_run", "dbt_test", "publish_summary")]
    tasks[0] >> tasks[1] >> tasks[2] >> tasks[3]

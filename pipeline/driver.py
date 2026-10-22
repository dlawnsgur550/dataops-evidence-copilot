"""개발자 전용: 이 세션에서 생성한 격리 DB만 변경하며 MCP와 분리합니다."""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg

from dataops_copilot.artifact_store import ArtifactStore, digest, redact
from dataops_copilot.models import IncidentRef

ROOT = Path(__file__).resolve().parent


def connect(config):
    connection = psycopg.connect(**config["admin_db"])
    marker = connection.execute("SELECT marker FROM public.dataops_demo_guard").fetchone()
    if marker != ("dataops-c-cp2-owned-isolated-db",):
        connection.close()
        raise ValueError("이 세션의 격리 DB 확인 실패. 변경을 중단합니다.")
    return connection


def demo_rows(mode, row_count=1000):
    if not isinstance(row_count,int) or isinstance(row_count,bool) or not 100<=row_count<=1000000:raise ValueError("DEMO_ROW_COUNT_OUT_OF_BOUNDS")
    rng = random.Random(42)
    return [(None if mode == "quality" and i < 3 else i + 1, rng.randint(1, 100),
             Decimal(rng.randint(100, 100000)) / 100, datetime(2026, 1, 1) + timedelta(minutes=i)) for i in range(row_count)]


def endpoint(config, *, broken=False):
    Path(config["endpoint_path"]).write_text(json.dumps({"host": "127.0.0.1", "port": config["bad_port"] if broken else config["admin_db"]["port"]}))


def prepare(config, mode, row_count=1000):
    with connect(config) as conn:
        if mode == "verify":
            assert conn.execute("SELECT count(*) FROM raw.orders").fetchone() == (row_count,)
            print("기존 데이터의 별도 후속 실행: 초기화하지 않았습니다.")
            return
        if mode not in ("normal", "schema", "quality", "connection"):
            raise ValueError("허용되지 않은 개발 시나리오")
        conn.execute("DROP SCHEMA IF EXISTS analytics CASCADE")
        conn.execute("DROP SCHEMA IF EXISTS raw CASCADE")
        conn.execute("CREATE SCHEMA raw")
        conn.execute("CREATE SCHEMA analytics AUTHORIZATION dataops_builder")
        amount = "paid_amount" if mode == "schema" else "amount"
        # amount는 두 상수 중 하나만 선택하며 사용자 SQL을 받지 않습니다.
        conn.execute(f"CREATE TABLE raw.orders (order_id integer, customer_id integer, {amount} numeric, created_at timestamp)")
        with conn.cursor() as cur:
            with cur.copy(f"COPY raw.orders FROM STDIN") as copy:
                for row in demo_rows(mode,row_count):copy.write_row(row)
        conn.execute("GRANT USAGE ON SCHEMA raw TO dataops_builder, dataops_observer")
        conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA raw TO dataops_builder, dataops_observer")
        conn.execute("GRANT USAGE ON SCHEMA analytics TO dataops_observer")
        conn.execute("ALTER DEFAULT PRIVILEGES FOR ROLE dataops_builder IN SCHEMA analytics GRANT SELECT ON TABLES TO dataops_observer")
        baseline = Path(config["baseline_path"])
        if not baseline.exists():
            if mode != "normal":
                raise ValueError("정상 실제 스키마 기준을 먼저 수집해야 합니다.")
            columns = dict(conn.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='raw' AND table_name='orders' ORDER BY ordinal_position").fetchall())
            baseline.write_text(json.dumps({"baseline_id": "orders-v1", "observed_at": datetime.now(timezone.utc).isoformat(), "columns": columns}, indent=2))
    endpoint(config, broken=mode == "connection")
    print(f"고정 시드 합성 주문 데이터 {row_count}건을 준비했습니다.")


def run_dbt(config, ref, command):
    call_id = uuid4().hex
    call_dir = Path(config["command_root"]) / digest(ref.execution_key()) / call_id
    call_dir.mkdir(parents=True, exist_ok=False)
    profiles = call_dir / "profiles"
    profiles.mkdir()
    active = json.loads(Path(config["endpoint_path"]).read_text())
    profile = "orders_demo:\n  target: local\n  outputs:\n    local:\n      type: postgres\n      host: " + config.get("dbt_host", "127.0.0.1") + "\n      port: " + str(active["port"]) + "\n      user: dataops_builder\n      password: \"{{ env_var('C_DBT_PASSWORD') }}\"\n      dbname: dataops_c_cp2\n      schema: analytics\n      threads: 1\n      connect_timeout: 3\n      retries: 0\n"
    (profiles / "profiles.yml").write_text(profile)
    target = call_dir / "target"
    argv = [config["dbt_executable"], "--no-use-colors", "--log-format", "json", "--no-send-anonymous-usage-stats", command,
            "--project-dir", str(ROOT / "dbt"), "--profiles-dir", str(profiles), "--target-path", str(target), "--log-path", str(call_dir / "logs")]
    started = time.monotonic()
    env = {**os.environ, "C_DBT_PASSWORD": config["builder_password"], "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    process = subprocess.run(argv, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
    archive = ArtifactStore(Path(config["artifact_root"])).save(ref, command, call_id, target, process.stdout, process.returncode, time.monotonic() - started)
    print(redact(process.stdout), flush=True)
    print(json.dumps({"dbt_archive": str(archive), "exit_code": process.returncode}), flush=True)
    return process.returncode


def verify_aggregates(config):
    with connect(config) as conn:
        raw = conn.execute("SELECT count(*), sum(amount) FROM raw.orders").fetchone()
        stage = conn.execute("SELECT count(*), sum(amount) FROM analytics.stg_orders").fetchone()
        daily = conn.execute("SELECT sum(order_count), sum(total_amount) FROM analytics.daily_orders").fetchone()
        profile = conn.execute("SELECT count(*) FILTER (WHERE order_id IS NULL), count(order_id)-count(DISTINCT order_id) FROM raw.orders").fetchone()
        result = {"raw_count": raw[0], "raw_sum": str(raw[1]), "stage_count": stage[0], "stage_sum": str(stage[1]),
                  "daily_count": int(daily[0]), "daily_sum": str(daily[1]), "nulls": profile[0], "duplicates": profile[1],
                  "matched": raw == stage == daily and profile == (0, 0)}
        if not result["matched"]:
            raise AssertionError("집계 또는 품질 정합성 실패")
        return result


def repair(config, case):
    with connect(config) as conn:
        if case == "schema":
            conn.execute("ALTER TABLE raw.orders RENAME COLUMN paid_amount TO amount")
        elif case == "quality":
            conn.execute("UPDATE raw.orders SET order_id=1 + (extract(epoch FROM (created_at-timestamp '2026-01-01'))/60)::integer WHERE order_id IS NULL")
        elif case != "connection":
            raise ValueError("알 수 없는 복구 대상")
    endpoint(config)
    return {"developer_action": case, "performed_at": datetime.now(timezone.utc).isoformat(), "performed_by": "authorized_developer_script", "agent_executed": False}


def main():
    parser = argparse.ArgumentParser(description="개발자 전용 격리 데모 변경 도구")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--step", choices=("load_demo_data", "dbt_run", "dbt_test", "publish_summary", "repair"), required=True)
    parser.add_argument("--incident")
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--mode", choices=("normal", "schema", "quality", "connection", "verify"), default="normal")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config["admin_db"]["dbname"] != "dataops_c_cp2":
        raise ValueError("격리 DB 이름 불일치")
    if args.step == "load_demo_data":
        prepare(config, args.mode, args.rows)
    elif args.step == "repair":
        print(json.dumps(repair(config, args.mode)))
    elif args.step == "publish_summary":
        print(json.dumps(verify_aggregates(config)))
    else:
        ref = IncidentRef.model_validate_json(args.incident)
        if ref.task_id != args.step or ref.dag_id != "orders_demo":
            raise ValueError("실행 대상 불일치")
        raise SystemExit(run_dbt(config, ref, "run" if args.step == "dbt_run" else "test"))


if __name__ == "__main__":
    main()

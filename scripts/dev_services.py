"""개발자 전용: 이 세션 소유의 PostgreSQL과 Airflow만 시작/중지합니다."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import socket
import subprocess
import time
from pathlib import Path

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
RUNTIME = WORKSPACE / "work" / "runtime"
RECORDS = ROOT / "artifacts" / "v3.1" / "live"
CONTAINER, VOLUME = "dataops-c-cp2-postgres", "dataops_c_cp2_pg17"
OWNER = "dataops-c-cp2"
AIRFLOW_CONTAINER = "dataops-c-cp2-airflow"
DB_PORT, API_PORT = 15439, 18783


def save_private(path, data):
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)


def command(argv, *, env=None, timeout=60):
    try:
        result = subprocess.run(argv, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"개발 서비스 명령 시간 초과: {argv[0]}") from None
    with (RECORDS / "service-setup.log").open("a") as log:
        log.write(result.stdout + "\nexit_code=" + str(result.returncode) + "\n")
    if result.returncode:
        raise RuntimeError(f"개발 서비스 명령 실패: {argv[0]} (exit={result.returncode}), service-setup.log 확인")
    return result.stdout


def airflow_env():
    return {**os.environ, "AIRFLOW_HOME": str(RUNTIME / "airflow"), "AIRFLOW__CORE__DAGS_FOLDER": str(ROOT / "pipeline" / "dags"),
        "AIRFLOW__CORE__LOAD_EXAMPLES": "False", "AIRFLOW__CORE__EXECUTOR": "SequentialExecutor",
        "AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION": "False", "AIRFLOW__CORE__PARALLELISM": "2",
        "AIRFLOW__SCHEDULER__MIN_FILE_PROCESS_INTERVAL": "5", "AIRFLOW__SCHEDULER__DAG_DIR_LIST_INTERVAL": "5",
        "AIRFLOW__API__AUTH_BACKENDS": "airflow.api.auth.backend.basic_auth,airflow.api.auth.backend.session",
        "AIRFLOW__WEBSERVER__WEB_SERVER_HOST": "127.0.0.1", "AIRFLOW__WEBSERVER__WEB_SERVER_PORT": str(API_PORT),
        "AIRFLOW__WEBSERVER__WORKERS": "1", "AIRFLOW__CORE__TEST_CONNECTION": "Disabled",
        "AIRFLOW__CORE__LOAD_DEFAULT_CONNECTIONS": "False", "AIRFLOW__CORE__DAGBAG_IMPORT_TIMEOUT": "30",
        "AIRFLOW__METRICS__STATSD_ON": "False", "DO_NOT_TRACK": "1", "SCARF_NO_ANALYTICS": "true",
        "OBJC_DISABLE_INITIALIZE_FORK_SAFETY": "YES", "C_DATAOPS_ROOT": str(ROOT),
        "C_DATAOPS_APP_PYTHON": str(ROOT / ".venv" / "bin" / "python"),
        "C_DATAOPS_DRIVER_CONFIG": str(RUNTIME / "driver-settings.json")}


def start():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    RECORDS.mkdir(parents=True, exist_ok=True)
    credentials_path = RUNTIME / "generated-credentials.json"
    if credentials_path.exists():
        credentials = json.loads(credentials_path.read_text())
    else:
        credentials = {key: secrets.token_urlsafe(24) for key in ("admin", "builder", "observer", "airflow_admin", "airflow_viewer")}
        save_private(credentials_path, credentials)
    inspect = subprocess.run(["docker", "inspect", CONTAINER], capture_output=True, text=True)
    if inspect.returncode == 0:
        container = json.loads(inspect.stdout)[0]
        if container["Config"]["Labels"].get("io.codex.dataops.owner") != OWNER:
            raise ValueError("동명 컨테이너가 이 세션 소유가 아닙니다. 변경하지 않습니다.")
        command(["docker", "start", CONTAINER])
    else:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", DB_PORT))
        volume = subprocess.run(["docker", "volume", "inspect", VOLUME], capture_output=True, text=True)
        if volume.returncode == 0:
            info = json.loads(volume.stdout)[0]
            if (info.get("Labels") or {}).get("io.codex.dataops.owner") != OWNER:
                raise ValueError("동명 볼륨이 이 세션 소유가 아닙니다. 변경하지 않습니다.")
        else:
            command(["docker", "volume", "create", "--label", "io.codex.dataops.owner=" + OWNER, VOLUME])
        pg_env = RUNTIME / "postgres.env"
        pg_env.write_text("POSTGRES_DB=dataops_c_cp2\nPOSTGRES_PASSWORD=" + credentials["admin"] + "\n")
        pg_env.chmod(0o600)
        command(["docker", "run", "-d", "--name", CONTAINER, "--label", "io.codex.dataops.owner=" + OWNER,
            "--publish", f"127.0.0.1:{DB_PORT}:5432", "--mount", f"type=volume,source={VOLUME},target=/var/lib/postgresql/data",
            "--env-file", str(pg_env), "postgres:17.10-alpine"])
    admin = {"host": "127.0.0.1", "port": DB_PORT, "dbname": "dataops_c_cp2", "user": "postgres", "password": credentials["admin"], "connect_timeout": 4}
    for _ in range(30):
        try:
            with psycopg.connect(**admin) as conn:
                conn.execute("SELECT 1")
            break
        except psycopg.OperationalError:
            time.sleep(1)
    else:
        raise RuntimeError("새 PostgreSQL 준비 시간 초과")
    with psycopg.connect(**admin) as conn:
        for user, key in (("dataops_builder", "builder"), ("dataops_observer", "observer")):
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (user,)).fetchone():
                conn.execute(psycopg.sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(psycopg.sql.Identifier(user), psycopg.sql.Literal(credentials[key])))
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        conn.execute("CREATE TABLE IF NOT EXISTS public.dataops_demo_guard (marker text primary key)")
        conn.execute("INSERT INTO public.dataops_demo_guard VALUES ('dataops-c-cp2-owned-isolated-db') ON CONFLICT DO NOTHING")
        conn.execute("ALTER ROLE dataops_observer SET default_transaction_read_only = on")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        bad_port = sock.getsockname()[1]
    endpoint_path = RUNTIME / "active-endpoint.json"
    endpoint_path.write_text(json.dumps({"host": "127.0.0.1", "port": DB_PORT}))
    common = {"artifact_root": str(RECORDS / "dbt-archives"), "baseline_path": str(RECORDS / "baseline-orders-v1.json"), "endpoint_path": str(endpoint_path)}
    reader = {"airflow_url": f"http://127.0.0.1:{API_PORT}/api/v1", "airflow_user": "dataops_viewer", "airflow_password": credentials["airflow_viewer"],
              "observer": {**admin, "user": "dataops_observer", "password": credentials["observer"]}, **common}
    reader["observer"].pop("connect_timeout")
    save_private(RUNTIME / "live-settings.json", reader)
    driver = {"admin_db": admin, "builder_password": credentials["builder"], "dbt_executable": str(WORKSPACE / "work" / "dbt-venv" / "bin" / "dbt"),
              "command_root": str(RECORDS / "dbt-calls"), "bad_port": bad_port, **common}
    save_private(RUNTIME / "driver-settings.json", driver)
    save_private(RUNTIME / "developer-api.json", {"url": reader["airflow_url"], "user": "dataops_admin", "password": credentials["airflow_admin"]})
    airflow = WORKSPACE / "work" / "airflow-venv" / "bin" / "airflow"
    env = airflow_env()
    if not (RUNTIME / "airflow-initialized").exists():
        command([str(airflow), "db", "migrate"], env=env)
        command([str(airflow), "sync-perm"], env=env)
        existing_users = command([str(airflow), "users", "list"], env=env)
        for user, role, key in (("dataops_admin", "Admin", "airflow_admin"), ("dataops_viewer", "Viewer", "airflow_viewer")):
            if user in existing_users:
                continue
            command([str(airflow), "users", "create", "--username", user, "--password", credentials[key], "--firstname", "DataOps", "--lastname", "Local", "--role", role, "--email", user + "@example.invalid"], env=env)
        (RUNTIME / "airflow-initialized").touch()
    if os.environ.get("C_DATAOPS_NATIVE_AIRFLOW") != "1":
        start_docker_airflow(driver, reader, credentials, env)
        return
    processes = []
    for component in ("webserver", "scheduler"):
        logfile = RUNTIME / f"airflow-{component}.log"
        with logfile.open("a") as handle:
            process = subprocess.Popen([str(airflow), component], env=env, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append({"component": component, "pid": process.pid, "log": str(logfile)})
    save_private(RUNTIME / "service-processes.json", processes)
    for _ in range(50):
        try:
            response = httpx.get(reader["airflow_url"] + "/version", auth=(reader["airflow_user"], credentials["airflow_viewer"]), timeout=2, trust_env=False)
            if response.status_code == 200 and response.json()["version"] == "2.10.4":
                metadata = {"airflow_version": response.json()["version"], "airflow_api": reader["airflow_url"], "auth": "Basic, dedicated Viewer account",
                    "postgres_version": command(["docker", "exec", CONTAINER, "postgres", "--version"]).strip(),
                    "postgres_image": json.loads(command(["docker", "image", "inspect", "postgres:17.10-alpine"]))[0]["RepoDigests"],
                    "container": CONTAINER, "volume": VOLUME, "ports": {"postgres": DB_PORT, "airflow": API_PORT}, "processes": processes}
                (RECORDS / "services.json").write_text(json.dumps(metadata, indent=2))
                print(json.dumps({"ready": True, "airflow_version": "2.10.4", "postgres_port": DB_PORT, "airflow_port": API_PORT, "settings": str(RUNTIME / "live-settings.json")}, ensure_ascii=False))
                return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError("Airflow API 준비 시간 초과. work/runtime/airflow-webserver.log 확인")


def start_docker_airflow(driver, reader, credentials, env):
    container_driver = {**driver, "admin_db": {**driver["admin_db"], "host": "host.docker.internal"},
                        "dbt_host": "host.docker.internal", "dbt_executable": "/opt/dataops-dbt/bin/dbt"}
    save_private(RUNTIME / "driver-container.json", container_driver)
    command(["docker", "build", "-f", str(ROOT / "deployment" / "Dockerfile.airflow"), "-t", "dataops-c-cp2-airflow:2.10.4", str(ROOT / "deployment")], timeout=300)
    container_env = {k: v for k, v in env.items() if k.startswith(("AIRFLOW", "C_DATAOPS")) or k in ("DO_NOT_TRACK", "SCARF_NO_ANALYTICS")}
    container_env.update({"AIRFLOW__WEBSERVER__WEB_SERVER_HOST": "0.0.0.0", "AIRFLOW__WEBSERVER__WEB_SERVER_PORT": "8080",
                          "C_DATAOPS_APP_PYTHON": "/opt/dataops-driver/bin/python", "C_DATAOPS_DRIVER_CONFIG": str(RUNTIME / "driver-container.json"),
                          "PYTHONPATH": str(ROOT / "src")})
    env_path = RUNTIME / "airflow-container.env"
    env_path.write_text("\n".join(f"{k}={v}" for k, v in container_env.items()) + "\n")
    env_path.chmod(0o600)
    inspect = subprocess.run(["docker", "inspect", AIRFLOW_CONTAINER], capture_output=True, text=True)
    mounts = [(ROOT, ROOT, True), (RECORDS, RECORDS, False), (RUNTIME / "airflow", RUNTIME / "airflow", False),
              (RUNTIME / "driver-container.json", RUNTIME / "driver-container.json", True),
              (RUNTIME / "active-endpoint.json", RUNTIME / "active-endpoint.json", False)]
    if inspect.returncode == 0:
        info=json.loads(inspect.stdout)[0]
        if info["Config"]["Labels"].get("io.codex.dataops.owner") != OWNER:
            raise ValueError("동명 Airflow 컨테이너가 이 세션 소유가 아닙니다.")
        if {m["Source"] for m in info.get("Mounts",[])} != {str(m[0]) for m in mounts}:
            # Replace only our own container definition; Airflow state and evidence are host bind data.
            command(["docker", "stop", "--time", "10", AIRFLOW_CONTAINER])
            command(["docker", "rm", AIRFLOW_CONTAINER])
            inspect.returncode=1
        else:command(["docker", "start", AIRFLOW_CONTAINER])
    if inspect.returncode != 0:
        mount_args=[]
        for source,target,readonly in mounts:
            mount_args.extend(["--mount",f"type=bind,source={source},target={target}"+(",readonly" if readonly else "")])
        command(["docker", "run", "-d", "--init", "--name", AIRFLOW_CONTAINER, "--label", "io.codex.dataops.owner=" + OWNER,
            "--user", f"{os.getuid()}:0", "--publish", f"127.0.0.1:{API_PORT}:8080", "--env-file", str(env_path),
            *mount_args, "dataops-c-cp2-airflow:2.10.4",
            "bash", "-c", "airflow webserver & airflow scheduler & wait -n"])
    for _ in range(60):
        try:
            response = httpx.get(reader["airflow_url"] + "/version", auth=(reader["airflow_user"], credentials["airflow_viewer"]), timeout=2, trust_env=False)
            if response.status_code == 200 and response.json()["version"] == "2.10.4":
                metadata = {"airflow_version": "2.10.4", "airflow_engine": "official Linux container + isolated dbt/driver venvs",
                    "airflow_base_image": "apache/airflow:2.10.4-python3.11", "airflow_api": reader["airflow_url"],
                    "auth": "Basic, dedicated Viewer account", "postgres_version": command(["docker", "exec", CONTAINER, "postgres", "--version"]).strip(),
                    "postgres_image": json.loads(command(["docker", "image", "inspect", "postgres:17.10-alpine"]))[0]["RepoDigests"],
                    "airflow_image_id": json.loads(command(["docker", "image", "inspect", "dataops-c-cp2-airflow:2.10.4"]))[0]["Id"],
                    "containers": [CONTAINER, AIRFLOW_CONTAINER], "volume": VOLUME, "ports": {"postgres": DB_PORT, "airflow": API_PORT}}
                (RECORDS / "services.json").write_text(json.dumps(metadata, indent=2))
                print(json.dumps({"ready": True, "engine": "docker", "airflow_version": "2.10.4", "ports": metadata["ports"]}))
                return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError("Linux Airflow API 준비 시간 초과. docker logs dataops-c-cp2-airflow 확인")


def stop():
    results = []
    path = RUNTIME / "service-processes.json"
    if path.exists():
        for item in json.loads(path.read_text()):
            process = subprocess.run(["ps", "-p", str(item["pid"]), "-o", "command="], text=True, capture_output=True)
            if "airflow" in process.stdout and item["component"] in process.stdout:
                os.killpg(item["pid"], signal.SIGTERM)
                results.append({"component": item["component"], "signal": "SIGTERM", "pid": item["pid"]})
    inspect_airflow = subprocess.run(["docker", "inspect", AIRFLOW_CONTAINER], capture_output=True, text=True)
    if inspect_airflow.returncode == 0 and json.loads(inspect_airflow.stdout)[0]["Config"]["Labels"].get("io.codex.dataops.owner") == OWNER:
        command(["docker", "stop", "--time", "10", AIRFLOW_CONTAINER])
        results.append({"container": AIRFLOW_CONTAINER, "stopped": True})
    inspect = subprocess.run(["docker", "inspect", CONTAINER], capture_output=True, text=True)
    if inspect.returncode == 0 and json.loads(inspect.stdout)[0]["Config"]["Labels"].get("io.codex.dataops.owner") == OWNER:
        command(["docker", "stop", "--time", "10", CONTAINER])
        results.append({"container": CONTAINER, "stopped": True, "volume_preserved": VOLUME})
    (RECORDS / "services-stopped.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop"))
    args = parser.parse_args()
    start() if args.action == "start" else stop()

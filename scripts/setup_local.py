"""검증한 Python 환경과 Docker 준비. 비밀 파일 탐색이나 기존 DB 변경은 하지 않습니다."""
import json
import subprocess
import time
from pathlib import Path

from dev_services import ROOT, WORKSPACE, RUNTIME, RECORDS, airflow_env


def main():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    RECORDS.mkdir(parents=True, exist_ok=True)
    records = []
    def run(name, argv, timeout=300):
        result = subprocess.run(argv, cwd=ROOT, env=airflow_env(), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        path = RECORDS / (name + ".log")
        path.write_text(result.stdout)
        item = {"command": argv, "exit_code": result.returncode, "log": str(path.relative_to(ROOT))}
        records.append(item)
        print(json.dumps({"step": name, "exit_code": result.returncode}), flush=True)
        if result.returncode:
            raise RuntimeError("설치 명령 실패: " + name)
    run("app-install", ["uv", "sync", "--locked", "--python", "3.11"])
    for name in ("airflow", "dbt"):
        environment = WORKSPACE / "work" / (name + "-venv")
        if not (environment / "bin" / "python").exists():
            run(name + "-venv", ["uv", "venv", str(environment), "--python", "3.11", "--seed"])
    run("airflow-install", [str(WORKSPACE / "work" / "airflow-venv" / "bin" / "python"), "-m", "pip", "install", "apache-airflow==2.10.4", "--constraint", str(ROOT / "deployment" / "airflow-2.10.4-python3.11-constraints.txt")])
    run("dbt-install", ["uv", "pip", "install", "--python", str(WORKSPACE / "work" / "dbt-venv" / "bin" / "python"), "--requirement", str(ROOT / "deployment" / "dbt-resolved.txt")])
    probe = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode:
        run("docker-desktop-start", ["open", "-a", "Docker"])
        for _ in range(50):
            if subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Docker Desktop 준비 실패. 사용자 동의/로그인 화면이 있다면 직접 확인해야 합니다.")
    run("postgres-pull", ["docker", "pull", "postgres:17.10-alpine"])
    (RECORDS / "setup-commands.json").write_text(json.dumps(records, indent=2))
    print("설치와 Docker 준비를 확인했습니다. dev_services.py start로 격리 서비스를 시작하세요.")


if __name__ == "__main__":
    main()

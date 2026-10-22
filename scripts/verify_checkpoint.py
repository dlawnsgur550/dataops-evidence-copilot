"""Reproduce local verification and preserve actual commands/exit codes."""
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
commands = [
    ("locked-install", ["uv", "sync", "--locked", "--python", "3.11"], 0),
    ("tests", ["uv", "run", "pytest", "-q", "-W", "error::RuntimeWarning", "--junitxml=artifacts/test-results.xml"], 0),
    ("compile", ["uv", "run", "python", "-m", "compileall", "-q", "src", "tests", "scripts"], 0),
    ("protocol", ["uv", "run", "python", "scripts/protocol_probe.py"], 0),
    *[(name, ["uv", "run", "dataops-copilot", "--fixture", name, "--transport", "stdio", "--output", f"artifacts/{name}.json"], 0)
      for name in ("schema", "quality", "connection", "normal", "insufficient")],
    ("versions", ["uv", "pip", "freeze"], 0),
    ("docker-readonly", ["docker", "version", "--format", "{{.Client.Version}} {{if .Server}}{{.Server.Version}}{{end}}"], (0, 1)),
]
results = []
for name, command, expected in commands:
    started = time.monotonic()
    process = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    log = ARTIFACTS / f"{name}.log"
    log.write_text(process.stdout)
    item = {"name": name, "command": command, "exit_code": process.returncode, "expected_exit_code": expected,
            "elapsed_seconds": round(time.monotonic() - started, 4), "log": str(log.relative_to(ROOT))}
    results.append(item)
    print(json.dumps(item), flush=True)
output = {"verified_at_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
          "platform": platform.platform(), "cwd": str(ROOT), "results": results,
          "all_expected": all(r["exit_code"] in r["expected_exit_code"] if isinstance(r["expected_exit_code"], tuple) else r["exit_code"] == r["expected_exit_code"] for r in results)}
(ARTIFACTS / "verification.json").write_text(json.dumps(output, indent=2) + "\n")
raise SystemExit(0 if output["all_expected"] else 1)

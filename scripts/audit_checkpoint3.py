"""로컬 키 비노출·비용·캐시 결과 감사. 유료 API나 파이프라인 실행은 하지 않습니다."""
import hashlib
import json
import sqlite3
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from dataops_copilot.api_safety import CostLedger, PRICE_DATE, read_api_settings
from dataops_copilot.models import Report

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "artifacts" / "checkpoint3"
RUNTIME = ROOT.parents[1] / "work" / "runtime"


def main():
    key, model = read_api_settings(RUNTIME / "openai.env")
    secret = key.get_secret_value().encode()
    scanned = 0
    leaks = []
    for path in ROOT.parent.rglob("*"):
        if path.is_file() and not path.is_symlink() and not {".venv", "__pycache__", ".git"}.intersection(path.parts):
            scanned += 1
            if secret in path.read_bytes():
                leaks.append(str(path.relative_to(ROOT.parent)))
    assert not leaks, "KEY_LEAK_IN_OUTPUTS"
    paths = [RUNTIME / "openai.env", RUNTIME / "llm-cost.sqlite3", *sorted((RUNTIME / "llm-cache").glob("*.json"))]
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in paths), "PRIVATE_FILE_MODE_REQUIRED"
    assert all(p.stat().st_mode & 0o777 == 0o700 for p in (RUNTIME, RUNTIME / "llm-cache")), "PRIVATE_DIRECTORY_MODE_REQUIRED"

    paid = Report.model_validate_json((RECORDS / "openai-schema-report.json").read_text())
    cached = Report.model_validate_json((RECORDS / "cached-schema-report.json").read_text())
    assert paid.review.accepted and paid.diagnosis.category == "SCHEMA_CHANGE"
    assert paid.usage.api_calls == 2 and paid.usage.local_cache_hits == 2
    assert paid.validation_scope["external_systems"] == "not_queried_in_this_run"
    assert cached.review.accepted and cached.usage.api_calls == 0 and cached.usage.local_cache_hits == 4
    assert cached.usage.cost == 0 and cached.usage.tokens == 0
    ledger = CostLedger(RUNTIME / "llm-cost.sqlite3")
    summary = ledger.summary()
    assert summary["uncertain_requests"] == 0
    with sqlite3.connect(ledger.path) as db:
        usage = db.execute("SELECT role,input_tokens,output_tokens,charge,status FROM requests ORDER BY rowid").fetchall()
    summary.update({"price_date": PRICE_DATE, "model": model,
        "cost_basis": "provider_token_usage_price_estimate_not_account_invoice",
        "input_tokens": sum(r[1] or 0 for r in usage), "output_tokens": sum(r[2] or 0 for r in usage),
        "requests_by_role": [{"role": r[0], "input_tokens": r[1], "output_tokens": r[2], "estimated_usd": r[3] / 1e9, "usage_collected": r[4] == "billed"} for r in usage],
        "cached_repeat": {"api_calls": cached.usage.api_calls, "cache_hits": cached.usage.local_cache_hits, "additional_cost_usd": cached.usage.cost}})
    (RECORDS / "cost-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    suites = ET.parse(RECORDS / "tests.xml").getroot().findall("testsuite")
    assert sum(int(s.get("tests", 0)) for s in suites) == 71
    assert all(int(s.get("failures", 0)) + int(s.get("errors", 0)) == 0 for s in suites)
    containers = []
    for name in ("dataops-c-cp2-airflow", "dataops-c-cp2-postgres"):
        info = json.loads(subprocess.check_output(["docker", "inspect", name], text=True))[0]
        containers.append({"name": name, "running": info["State"]["Running"], "status": info["State"]["Status"]})
        assert not info["State"]["Running"]
    processes = subprocess.check_output(["ps", "-axo", "pid,command"], text=True)
    assert not any(" -m dataops_copilot.mcp_server " in line for line in processes.splitlines())
    audit = {"success": True, "audited_at": datetime.now(timezone.utc).isoformat(), "model": model,
        "key_scan_scope": "only user-specified local API key; current C outputs excluding environments/bytecode/git",
        "scanned_files": scanned, "key_leak_files": leaks, "private_files_600": len(paths), "private_directories_700": True,
        "tests_passed": 71, "containers": containers, "remaining_mcp_servers": 0,
        "real_llm_scope": "saved actual schema evidence replay; no new live system query", "new_api_calls_by_audit": 0}
    (RECORDS / "security-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ("src", "scripts", "tests", "docs") for p in (ROOT / folder).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts}
    for name in ("README.md", "pyproject.toml", "uv.lock", ".gitignore"):
        hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    (RECORDS / "source-manifest.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print(json.dumps({"success": True, "key_leaks": 0, "api_requests_total": summary["requests"],
        "estimated_usd_total": summary["spent_or_reserved_usd"], "cache_repeat_api_calls": 0, "tests_passed": 71,
        "private_permissions_verified": True, "containers_stopped": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()

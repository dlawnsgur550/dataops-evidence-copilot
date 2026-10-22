"""복구 후 현재 연결 성공이 과거 실패를 정상으로 바꾸지 않는 실제 MCP 부정 검사."""
import asyncio
import json
from pathlib import Path

from dataops_copilot.llm import FakeLLM
from dataops_copilot.mcp_client import open_live_mcp
from dataops_copilot.models import IncidentRef, TargetRef
from dataops_copilot.rules import code_review
from dataops_copilot.workflow import Copilot

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "artifacts" / "checkpoint2"


async def main():
    original = IncidentRef.model_validate_json((RECORDS / "connection-incident.json").read_text())
    async with open_live_mcp(ROOT.parents[1] / "work" / "runtime" / "live-settings.json") as mcp:
        report = await Copilot(mcp, FakeLLM()).diagnose(original)
        assert report.diagnosis.category == "CONNECTION_FAILURE" and report.review.accepted
        probe = next(e for e in report.evidence if e.kind == "check_connection")
        assert probe.data["connected"] is True
        assert report.recovered is None
        action = report.diagnosis.recovery_actions[0].model_copy(update={"target_ref": TargetRef(connection_id="mcp_readonly")})
        mutated = report.diagnosis.model_copy(update={"recovery_actions": [action]})
        violations = code_review(mutated, report.evidence, original, report.retrieval_hits)
        assert "ACTION_WRONG_CONNECTION" in violations
        result = {"success": True, "current_dbt_endpoint_connected": True, "historical_run_category": report.diagnosis.category,
                  "wrong_recovery_connection_violations": violations, "initialize": mcp.initialization.model_dump(mode="json"),
                  "report": report.model_dump(mode="json")}
        (RECORDS / "post-recovery-negatives.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({k: v for k, v in result.items() if k not in ("report", "initialize")}))


if __name__ == "__main__":
    asyncio.run(main())

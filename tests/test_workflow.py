import asyncio
import json

import pytest

from dataops_copilot.fixtures import FixtureAdapter, incident_for
from dataops_copilot.llm import FakeLLM
from dataops_copilot.models import Status, ToolError
from dataops_copilot.workflow import Copilot, Limits


@pytest.mark.parametrize("fixture,category", [("schema", "SCHEMA_CHANGE"), ("quality", "DATA_QUALITY"), ("connection", "CONNECTION_FAILURE"), ("normal", "NORMAL"), ("insufficient", "UNKNOWN")])
async def test_full_graph_branches(fixture, category):
    llm = FakeLLM()
    report = await Copilot(FixtureAdapter(fixture), llm, limits=Limits(retry_delays=(0, 0))).diagnose(incident_for(fixture))
    assert report.diagnosis.category == category
    assert report.review.accepted
    assert report.node_trace == ["triage", "inspector", "rca", "reviewer"]
    assert [c["role"] for c in llm.calls] == report.node_trace
    assert all("Role:" in c["prompt"] for c in llm.calls)
    assert report.usage.llm_calls == 4 and report.usage.rag_calls == 1
    assert report.usage.tokens is None and report.usage.cost is None
    assert report.recovered is None
    if category in ("NORMAL", "UNKNOWN"):
        assert not report.diagnosis.recovery_actions
    else:
        assert report.diagnosis.recovery_actions[0].verification
    if fixture == "insufficient":
        assert report.diagnosis.diagnosis_status == "insufficient"
        assert any(e.status == Status.UNAVAILABLE for e in report.evidence)
    # Scenario selector / expected labels must not be LLM payload fields.
    for call in llm.calls:
        assert not any(k in json.dumps(call["payload"]) for k in ('"scenario_id"', '"fixture"', '"expected_label"', '"ground_truth"'))


async def test_forged_id_rejected_after_one_revision():
    report = await Copilot(FixtureAdapter("schema"), FakeLLM(forge_evidence=True)).diagnose(incident_for("schema"))
    assert not report.review.accepted
    assert report.diagnosis.category == "UNKNOWN"
    assert not report.diagnosis.recovery_actions
    assert report.revision_count == 1
    assert report.usage.llm_calls == 6 and report.usage.rag_calls == 2
    assert "FABRICATED_EVIDENCE_ID:ev-forged" in report.review.violations


class AlteredAdapter(FixtureAdapter):
    def __init__(self, mutate):
        super().__init__("schema")
        self.mutate = mutate

    async def call(self, tool, arguments):
        item = await super().call(tool, arguments)
        return self.mutate(tool, item)


async def test_old_run_quarantined_before_llm():
    def stale(tool, item):
        if tool == "get_dbt_artifacts":
            ref = item.target_ref.model_copy(update={"incident": item.target_ref.incident.model_copy(update={"run_id": "old-run"})})
            return item.model_copy(update={"target_ref": ref})
        return item
    llm = FakeLLM()
    report = await Copilot(AlteredAdapter(stale), llm).diagnose(incident_for("schema"))
    assert report.diagnosis.category == "UNKNOWN"
    assert any("FOREIGN_EXECUTION" in e for e in report.errors)
    assert all("old-run" not in json.dumps(c["payload"]) for c in llm.calls)


async def test_mismatched_invocation_abstains():
    def mismatch(tool, item):
        if tool == "get_dbt_artifacts":
            return item.model_copy(update={"data": {**item.data, "manifest_invocation_id": "another-call"}})
        return item
    report = await Copilot(AlteredAdapter(mismatch), FakeLLM()).diagnose(incident_for("schema"))
    assert report.diagnosis.category == "UNKNOWN"
    assert any("INVOCATION_MISMATCH" in e for e in report.errors)


async def test_missing_schema_abstains():
    def missing(tool, item):
        return item.model_copy(update={"status": Status.EMPTY, "data": None}) if tool == "compare_schema" else item
    report = await Copilot(AlteredAdapter(missing), FakeLLM()).diagnose(incident_for("schema"))
    assert report.diagnosis.category == "UNKNOWN"
    assert report.diagnosis.missing_evidence


@pytest.mark.parametrize("limits,error", [(Limits(llm_calls=1), "LLM_CALL_LIMIT"), (Limits(tool_calls=1), "TOOL_CALL_LIMIT"), (Limits(rag_calls=0), "RAG_CALL_LIMIT"), (Limits(total_seconds=0.000001), "TOTAL_TIMEOUT")])
async def test_call_and_deadline_caps(limits, error):
    report = await Copilot(FixtureAdapter("schema"), FakeLLM(), limits=limits).diagnose(incident_for("schema"))
    assert error in report.errors
    assert not report.review.accepted and report.diagnosis.category == "UNKNOWN"
    assert report.usage.llm_calls <= limits.llm_calls
    assert report.usage.tool_calls <= limits.tool_calls
    assert report.usage.rag_calls <= limits.rag_calls


async def test_llm_timeout_keeps_partial_evidence():
    report = await Copilot(FixtureAdapter("schema"), FakeLLM(delay=0.2), limits=Limits(llm_seconds=0.01)).diagnose(incident_for("schema"))
    assert "LLM_TIMEOUT:triage" in report.errors
    assert len(report.evidence) == 1
    assert report.usage.elapsed_seconds < 0.5


async def test_tool_timeout_is_unavailable_and_bounded():
    class Slow(FixtureAdapter):
        async def call(self, tool, arguments):
            await asyncio.sleep(1)
            return await super().call(tool, arguments)
    report = await Copilot(Slow("schema"), FakeLLM(), limits=Limits(tool_seconds=0.005, tool_calls=3, retry_delays=(0, 0))).diagnose(incident_for("schema"))
    assert report.usage.tool_calls == 3
    assert any(e.error and e.error.code == "TOOL_TIMEOUT" for e in report.evidence)
    assert report.usage.elapsed_seconds < 0.5
    assert report.diagnosis.category == "UNKNOWN"


@pytest.mark.parametrize("code,status", [("AUTH_DENIED", Status.UNAVAILABLE), ("TARGET_NOT_ALLOWED", Status.INVALID_INPUT)])
async def test_no_retry_auth_or_invalid_input(code, status):
    class Rejected(FixtureAdapter):
        async def call(self, tool, arguments):
            item = await super().call(tool, arguments)
            return item.model_copy(update={"status": status, "data": None, "error": ToolError(code=code, retryable=True, message="denied")})
    report = await Copilot(Rejected("schema"), FakeLLM(), limits=Limits(retry_delays=(0, 0))).diagnose(incident_for("schema"))
    assert report.usage.tool_calls == 5
    assert report.diagnosis.category == "UNKNOWN"


async def test_llm_cannot_request_shell_tool():
    class UnsafeLLM(FakeLLM):
        async def complete(self, role, system_prompt, payload):
            if role == "inspector":
                return {"tools": ["execute_shell"]}
            return await super().complete(role, system_prompt, payload)
    report = await Copilot(FixtureAdapter("schema"), UnsafeLLM()).diagnose(incident_for("schema"))
    assert "TOOL_NOT_ALLOWED" in report.errors
    assert report.usage.tool_calls == 1


async def test_semantic_rejection_overrides_code_pass():
    report = await Copilot(FixtureAdapter("schema"), FakeLLM(reject_review=True)).diagnose(incident_for("schema"))
    assert report.revision_count == 1 and not report.review.accepted
    assert report.diagnosis.category == "UNKNOWN"

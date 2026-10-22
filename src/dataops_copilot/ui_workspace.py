"""Local workspace adapters. Existing diagnosis and recovery engines stay unchanged."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import json

from .claim_contract import ClaimProposal, ClaimReview
from .claim_engine import assess, render, resolve_review
from .llm import FakeLLM
from .models import IncidentRef, Report, RetrievalHit
from .recovery_v3 import check_recovery_v3
from .replay import ReportReplay
from .settings_policy import ProjectPolicy
from .workflow import Limits
from .workflow_v3 import ClaimCopilot

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "resources/workspace"
CASES = {
    "connection": ("연결 실패", "과거 실행의 연결 거부와 이후의 연결 성공을 구분합니다."),
    "schema": ("스키마 변경", "amount 컬럼 부재와 현재 스키마 차이를 확인합니다."),
    "quality": ("데이터 품질", "10만 행 중 주문 키 NULL 3건을 확인합니다."),
    "insufficient": ("증거 부족", "확인할 수 없는 산출물에 대해 판단을 보류합니다."),
    "normal": ("정상 실행", "전체 태스크와 필수 검사가 통과한 기록입니다."),
}
NAMES = {"CONNECTION_FAILURE": "연결 실패", "SCHEMA_CHANGE": "스키마 변경",
         "DATA_QUALITY": "데이터 품질", "UNKNOWN": "판단 보류", "NORMAL": "정상"}
GUARDS = {"없는 근거 ID 인용": "fake_evidence", "근거 없이 포트 오류 단정": "wrong_port",
          "조건부 조치를 Reviewer가 과도하게 거절": "reviewer_rejection"}
TASKS = ("load_demo_data", "dbt_run", "dbt_test", "publish_summary")
TASK_LABELS = {"load_demo_data": "데이터 적재", "dbt_run": "모델 변환",
               "dbt_test": "품질 검사", "publish_summary": "결과 발행"}


def load_source(case: str) -> Report:
    if case not in CASES:
        raise ValueError("UNKNOWN_WORKSPACE_CASE")
    return Report.model_validate_json((DATA / "inputs/reports" / f"{case}.json").read_text())


async def free_replay(case: str, incident_data=None) -> Report:
    source = load_source(case)
    incident = IncidentRef.model_validate(incident_data) if incident_data is not None else source.incident_ref
    report = await ClaimCopilot(ReportReplay(source), FakeLLM(), limits=Limits(llm_calls=1),
                               baseline=True).diagnose(incident)
    report.usage.api_calls = 0  # This adapter only instantiates the local FakeLLM.
    return report


async def inspect_claim(kind: str) -> dict:
    report = await free_replay("connection")
    proposal = ClaimProposal.model_validate(report.claim_proposal)
    if kind == "fake_evidence":
        proposal.evidence_ids.append("ev-workspace-nonexistent")
    elif kind == "wrong_port":
        proposal.config_error = "wrong_port"
    elif kind != "reviewer_rejection":
        raise ValueError("UNKNOWN_GUARD_EXAMPLE")
    target = ProjectPolicy.load().select(report.incident_ref.dag_id, "raw.orders")
    facts, checks = assess(proposal, report.evidence, report.incident_ref, target)
    catalog = [RetrievalHit(doc_id="rb-connection", doc_version="3", chunk_id="catalog:rb-connection",
                            rank=1, content="", content_hash="0" * 64)]
    diagnosis = render(proposal, facts, report.incident_ref, target, catalog, checks)
    findings = []
    if kind == "reviewer_rejection":
        review = ClaimReview.model_validate({"findings": [
            {"component": "actions", "rule_id": "R06", "claim_id": "propose_action"}]})
        findings = resolve_review(review, checks)
    return {"kind": kind, "api_calls": 0,
            "scope": "deliberately injected synthetic claim; free deterministic model; no live query",
            "proposal": proposal.model_dump(), "checks": checks,
            "blocked_checks": [c for c in checks if c["verdict"] != "PASS"],
            "diagnosis": diagnosis.model_dump(mode="json"), "reviewer_findings": findings}


def verify_recovery(case: str, same_run=False) -> dict:
    if case not in ("connection", "schema", "quality"):
        raise ValueError("RECOVERY_CASE_NOT_AVAILABLE")
    folder = DATA / "records/live-recovery"
    original = IncidentRef.model_validate_json((folder / f"{case}-incident.json").read_text())
    followup = IncidentRef.model_validate_json((folder / f"{case}-followup-incident.json").read_text())
    report = Report.model_validate_json((folder / f"{case}-followup-report.json").read_text())
    record = json.loads((folder / f"{case}-record.json").read_text())
    if same_run:
        followup = followup.model_copy(update={"run_id": original.run_id})
    context = next(e for e in report.evidence if e.kind == "get_task_context")
    artifacts = next(e for e in report.evidence if e.kind == "get_dbt_artifacts")
    target = ProjectPolicy.load().select(followup.dag_id, "raw.orders")
    result = check_recovery_v3(original, followup, context, artifacts, target,
                               record["aggregate"], record["action"])
    return {"case": case, "same_run": same_run, "api_calls": 0,
            "scope": "rechecked saved actual local synthetic-pipeline evidence; no new repair or run",
            "result": result, "developer_record": record,
            "followup_context": context.model_dump(mode="json"),
            "followup_artifacts": artifacts.model_dump(mode="json")}


def model_records() -> dict[str, Path]:
    paths = {p.stem: p for p in sorted((ROOT / "artifacts/v3/final").glob("Z[0-9][0-9]-full.json"))}
    for p in sorted((DATA / "records/actual-model").glob("*.json")):
        if p.stem not in {"I02", "Z03", "Z06", "Z08", "Z09"}:
            continue
        if not any(k.startswith(p.stem + "-") for k in paths):
            paths[p.stem] = p
    return paths


def evidence_rows(report: Report) -> list[dict]:
    return [{"종류": e.kind, "상태": e.status,
             "관측 범위": "선택 실행 당시" if e.temporal_scope == "run_snapshot" else "별도 시점 관측",
             "수집 시각": e.observed_at.isoformat(), "근거 ID": e.evidence_id,
             "자료": "합성 평가 자료" if e.simulated else "실제 로컬 수집"} for e in report.evidence]


def task_states(report: Report) -> dict:
    if report.errors:
        return {}  # A rejected run binding must not appear as the selected run's graph.
    context = next((e for e in report.evidence if e.kind == "get_task_context" and e.status == "success"), None)
    return dict((context.data or {}).get("task_statuses", {})) if context else {}


def rule_counts(checks) -> dict[str, int]:
    counts = Counter(c["verdict"] for c in checks)
    return {key: counts.get(key, 0) for key in ("PASS", "REJECT", "HOLD")}


def evaluation_summary() -> dict:
    return json.loads((ROOT / "artifacts/v3.1/completion.json").read_text())

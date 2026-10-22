from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IncidentRef(Contract):
    incident_id: str = Field(min_length=1)
    dag_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    try_number: int = Field(ge=1)

    def execution_key(self) -> tuple:
        return self.dag_id, self.run_id, self.task_id, self.try_number


class TargetRef(Contract):
    incident: IncidentRef | None = None
    table_id: str | None = None
    connection_id: str | None = None
    baseline_id: str | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not any((self.incident, self.table_id, self.connection_id, self.baseline_id)):
            raise ValueError("A concrete target is required")
        return self


class Status(StrEnum):
    SUCCESS = "success"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"
    INVALID_INPUT = "invalid_input"


class ToolError(Contract):
    code: str
    retryable: bool
    message: str


class Evidence(Contract):
    evidence_id: str = Field(min_length=1)
    kind: str
    source: str
    observed_at: datetime
    temporal_scope: Literal["run_snapshot", "current_observation", "baseline"]
    target_ref: TargetRef
    status: Status
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    simulated: bool = True

    @model_validator(mode="after")
    def consistent(self):
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at requires timezone")
        if self.temporal_scope == "run_snapshot" and self.target_ref.incident is None:
            raise ValueError("run evidence needs execution identity")
        if self.status == Status.SUCCESS and self.data is None:
            raise ValueError("success requires data")
        if self.status in (Status.UNAVAILABLE, Status.INVALID_INPUT) and self.error is None:
            raise ValueError("failure requires structured error")
        if self.status != Status.SUCCESS and self.data is not None:
            raise ValueError("non-success must not carry successful data")
        if self.status in (Status.SUCCESS, Status.EMPTY) and self.error is not None:
            raise ValueError("success/empty cannot carry an error")
        return self


class RetrievalHit(Contract):
    doc_id: str
    doc_version: str
    chunk_id: str
    rank: int = Field(ge=1)
    content_hash: str
    content: str
    method: str = "lexical_overlap_checkpoint"
    llm_summary: str | None = None


Category = Literal["SCHEMA_CHANGE", "DATA_QUALITY", "CONNECTION_FAILURE", "NORMAL", "UNKNOWN"]


class RecoveryAction(Contract):
    action_id: str
    target_ref: TargetRef
    kind: Literal["schema_alignment", "data_remediation", "connection_config", "retry", "manual_check"]
    prerequisites: list[str] = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    verification: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    runbook_ids: list[str] = Field(min_length=1)
    execution_mode: Literal["human_only_text"] = "human_only_text"


class Diagnosis(Contract):
    category: Category
    diagnosis_status: Literal["supported", "insufficient", "failed"]
    severity: Literal["high", "medium", "low", "unknown"]
    cause: str = Field(min_length=1)
    evidence_ids: list[str]
    missing_evidence: list[str]
    impact: list[str]
    recovery_actions: list[RecoveryAction] = Field(default_factory=list)

    @model_validator(mode="after")
    def uncertainty(self):
        if self.diagnosis_status != "supported":
            if self.category != "UNKNOWN" or self.recovery_actions:
                raise ValueError("Unsupported diagnoses must abstain without recovery actions")
        elif self.category == "UNKNOWN" or not self.evidence_ids:
            raise ValueError("Supported diagnosis requires category and evidence")
        if self.category == "NORMAL" and self.recovery_actions:
            raise ValueError("NORMAL must not generate recovery")
        return self


class Review(Contract):
    accepted: bool
    violations: list[str]
    feedback: list[str]
    revision_count: int = Field(ge=0, le=1)
    semantic_reviewer: str

    @model_validator(mode="after")
    def accepted_has_no_violations(self):
        if self.accepted and self.violations:
            raise ValueError("Accepted review cannot contain violations")
        return self


class Plan(Contract):
    provisional_category: Category
    investigation: list[str]


class Usage(Contract):
    llm_calls: int = 0
    tool_calls: int = 0
    rag_calls: int = 0
    tokens: int | None = None
    cost: float | None = None
    elapsed_seconds: float = 0
    api_calls: int | None = None
    local_cache_hits: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    price_date: str | None = None
    cost_basis: str = "not_collected"
    uncertain_reserved_usd: float = 0
    service_tier: str | None = None


class Report(Contract):
    trace_id: str
    incident_ref: IncidentRef
    plan: Plan | None
    evidence: list[Evidence]
    retrieval_hits: list[RetrievalHit]
    diagnosis: Diagnosis
    review: Review
    errors: list[str]
    usage: Usage
    node_trace: list[str]
    replan_count: int = Field(ge=0, le=1)
    revision_count: int = Field(ge=0, le=1)
    evidence_hash: str
    versions: dict[str, str]
    validation_scope: dict[str, str]
    recovered: bool | None = None
    rejected_candidates: list[dict[str, Any]] = Field(default_factory=list)
    output_diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class RecoveryCheck(Contract):
    original_incident_id: str
    followup_run_id: str
    task_statuses: dict[str, str]
    quality_results: dict[str, str]
    recovered: bool


def abstain(reason: str, *, failed: bool = False) -> Diagnosis:
    return Diagnosis(category="UNKNOWN", diagnosis_status="failed" if failed else "insufficient",
                     severity="unknown", cause="판단 보류: 원인을 확정할 근거가 부족합니다.",
                     evidence_ids=[], missing_evidence=[reason], impact=[])

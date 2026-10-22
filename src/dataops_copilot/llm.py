"""The fake is a deterministic test double, not a language model."""
from __future__ import annotations

import asyncio
from typing import Any, Protocol

from .models import Diagnosis, Evidence, IncidentRef, RecoveryAction, TargetRef, abstain
from .rules import supported_category


class LLMClient(Protocol):
    model_id: str

    async def complete(self, role: str, system_prompt: str, payload: dict[str, Any]) -> dict: ...


class FakeLLM:
    model_id = "fake-deterministic-v1"

    def __init__(self, *, delay: float = 0, forge_evidence: bool = False, reject_review: bool = False):
        self.delay = delay
        self.forge_evidence = forge_evidence
        self.reject_review = reject_review
        self.calls: list[dict] = []

    async def complete(self, role: str, system_prompt: str, payload: dict[str, Any]) -> dict:
        self.calls.append({"role": role, "prompt": system_prompt, "payload": payload})
        if self.delay:
            await asyncio.sleep(self.delay)
        if role in ("claims", "claim_reviewer"):
            if role == "claim_reviewer":
                return {"findings": [{"component": c["component"], "rule_id": c["rule_id"], "claim_id": c["claim_id"]} for c in payload.get("component_checks", []) if c["verdict"] != "PASS"][:8]}
            from .settings_policy import TargetPolicy
            from .claim_engine import facts
            target = TargetPolicy.model_validate(payload["target_policy"])
            incident = IncidentRef.model_validate(payload["incident_ref"])
            items = [Evidence.model_validate(e) for e in payload["evidence"]]
            f = facts(items, incident, target)
            return {"category": f["category"], "evidence_ids": list(f["byid"]), "current_connection": f["probe"],
                    "artifact_coverage": f["coverage"], "config_error": "unknown", "business_equivalence": "unknown",
                    "propose_action": f["category"] not in ("NORMAL", "UNKNOWN")}
        if role == "triage":
            contexts = [e for e in payload["evidence"] if e["kind"] == "get_task_context" and e["status"] == "success"]
            context = contexts[-1]["data"] if contexts else {}
            log = " ".join(context.get("log_lines", [])).lower()
            provisional = "SCHEMA_CHANGE" if "does not exist" in log else "DATA_QUALITY" if "not_null" in log else "CONNECTION_FAILURE" if "connection refused" in log else "NORMAL" if context.get("state") == "success" else "UNKNOWN"
            return {"provisional_category": provisional, "investigation": ["Confirm selected invocation before establishing a cause", "Collect current schema/profile separately", "Check only the named dbt connection"]}
        if role == "inspector":
            return {"tools": ["get_dbt_artifacts", "compare_schema", "get_quality_profile", "check_connection"]}
        if role == "reviewer":
            return {"accepted": not payload["code_violations"] and not self.reject_review,
                    "feedback": ["Fake reviewer only: semantic LLM review remains unverified"]}
        if role != "rca":
            raise ValueError("Unknown role")
        incident = IncidentRef.model_validate(payload["incident_ref"])
        evidence = [Evidence.model_validate(e) for e in payload["evidence"]]
        category, ids = supported_category(evidence, incident)
        if category == "UNKNOWN":
            return abstain("Selected execution logs/artifacts and required corroborating observations are missing").model_dump(mode="json")
        context_data = next(e.data for e in evidence if e.kind == "get_task_context" and e.status == "success")
        artifact_data = next(e.data for e in evidence if e.kind == "get_dbt_artifacts" and e.status == "success")
        column = artifact_data.get("column_id")
        table = context_data.get("table_id", "raw.orders")
        causes = {
            "SCHEMA_CHANGE": f"선택 실행의 dbt 로그와 산출물에 {column} 컬럼 부재가 기록됐습니다. 현재 스키마 차이는 보조 관측이며 과거 스냅샷으로 간주하지 않습니다.",
            "DATA_QUALITY": f"선택 실행의 {column} not_null 검사가 실패했습니다. 현재 NULL 프로필은 별도 시점의 관측이며 과거 실행 건수와는 구분합니다.",
            "CONNECTION_FAILURE": "선택 실행에서 dbt_orders 연결 거부가 확인됩니다. 잘못된 포트 여부는 근거가 없어 확정하지 않습니다. 다른 조회 연결의 성공은 복구 증거가 아닙니다.",
            "NORMAL": "선택 실행의 전체 태스크와 필수 dbt 품질 검사가 성공했습니다.",
        }
        actions = []
        if category != "NORMAL":
            kind, doc, steps, prerequisites = {
                "SCHEMA_CHANGE": ("schema_alignment", "rb-schema", ["생산자 계약과 모델 참조를 대조하고 amount 매핑 또는 모델 SQL을 개발자가 검토 후 맞춥니다."], ["amount와 paid_amount의 의미 및 기준 계약을 확인합니다."]),
                "DATA_QUALITY": ("data_remediation", "rb-quality", ["원본을 보존한 뒤 승인된 정책에 따라 잘못된 주문 키를 수정하거나 격리합니다."], ["업무 키 정의와 정정 정책을 확인합니다."]),
                "CONNECTION_FAILURE": ("connection_config", "rb-connection", ["실제 dbt 실행 설정의 대상과 서비스 상태를 개발자가 확인하고 확인된 설정 오류를 바로잡습니다."], ["실패 프로세스의 실제 연결 설정을 확인하며 비밀번호는 보고서에 넣지 않습니다."]),
            }[category]
            actions = [RecoveryAction(action_id="action-001", kind=kind,
                target_ref=TargetRef(connection_id="dbt_orders") if category == "CONNECTION_FAILURE" else TargetRef(table_id=table),
                prerequisites=prerequisites, steps=steps,
                verification=["사람이 별도 새 실행을 수행하여 모든 태스크 성공과 not_null 및 unique 통과, 집계 정합성을 확인합니다."],
                evidence_ids=ids, runbook_ids=[doc])]
        context = next(e.data for e in evidence if e.kind == "get_task_context" and e.status == "success")
        artifacts = next(e.data for e in evidence if e.kind == "get_dbt_artifacts" and e.status == "success")
        blocked = context.get("task_statuses", {}).get("publish_summary") in ("failed", "upstream_failed")
        impact = ["실행 상태상 publish_summary가 차단됐습니다."] if blocked else []
        if any("daily_orders" in node for node in artifacts.get("potential_downstream", [])) and category != "NORMAL":
            impact.append("manifest 의존관계상 daily_orders에 영향 가능성이 있으며 실제 모델 실패와는 구분합니다.")
        missing = ["연결 실패로 run_results가 생성되지 않았습니다. 실제 invocation과 해시가 검증된 명령 로그·manifest만 보존됐습니다."] if artifacts.get("artifact_status") == "partial" else []
        severity = "low" if category == "NORMAL" else "high" if blocked else "medium" if context.get("task_statuses", {}).get("publish_summary") == "success" else "unknown"
        diagnosis = Diagnosis(category=category, diagnosis_status="supported", severity=severity,
                              cause=causes[category], evidence_ids=ids, missing_evidence=missing, impact=impact, recovery_actions=actions)
        data = diagnosis.model_dump(mode="json")
        if self.forge_evidence:
            data["evidence_ids"].append("ev-forged")
        return data

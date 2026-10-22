from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .fixtures import TOOLS, ToolClient
from .api_safety import SafeAPIError
from .llm import LLMClient
from .models import Diagnosis, Evidence, IncidentRef, Plan, Report, Review, Status, TargetRef, ToolError, Usage, abstain
from .retrieval import LocalRunbooks
from .rules import code_review, evidence_violations
from .policy import target_context
from .diagnostics import sanitized


@dataclass(frozen=True)
class Limits:
    tool_seconds: float = 10
    llm_seconds: float = 30
    total_seconds: float = 180
    llm_calls: int = 6
    tool_calls: int = 10
    rag_calls: int = 2
    retry_delays: tuple[float, float] = (0.5, 1.5)


class BoundedStop(Exception):
    pass


class State(TypedDict, total=False):
    plan: Plan
    evidence: list[Evidence]
    retrieval_hits: list
    diagnosis: Diagnosis
    review: Review
    errors: list[str]
    node_trace: list[str]
    revision_count: int
    replan_count: int


class Copilot:
    """One invocation owns its budget, graph and injected clients. No global sessions."""

    def __init__(self, tools: ToolClient, llm: LLMClient, retriever=None, limits: Limits | None = None):
        self.tools = tools
        self.llm = llm
        self.retriever = retriever or LocalRunbooks()
        self.limits = limits or Limits()

    async def diagnose(self, incident: IncidentRef) -> Report:
        started = time.monotonic()
        deadline = started + self.limits.total_seconds
        usage = Usage()
        trace_id = str(uuid.uuid4())
        if hasattr(self.llm, "begin_diagnosis"):
            self.llm.begin_diagnosis(trace_id)
        state: State = {"evidence": [], "retrieval_hits": [], "errors": [], "node_trace": [], "revision_count": 0, "replan_count": 0}
        rejected_candidates = []
        # External LangSmith tracing is explicitly disabled even if inherited env enables it.
        from langsmith import tracing_context

        def remaining(limit: float) -> float:
            left = deadline - time.monotonic()
            if left <= 0:
                raise BoundedStop("TOTAL_TIMEOUT")
            return min(left, limit)

        async def ask(role: str, payload: dict):
            if usage.llm_calls >= self.limits.llm_calls:
                raise BoundedStop("LLM_CALL_LIMIT")
            timeout = remaining(self.limits.llm_seconds)
            usage.llm_calls += 1
            prompt = (Path(__file__).parent / "prompts" / f"{role}.md").read_text()
            try:
                return await asyncio.wait_for(self.llm.complete(role, prompt, payload), timeout)
            except asyncio.TimeoutError as exc:
                raise BoundedStop("LLM_TIMEOUT:" + role) from exc

        def args_for(tool: str):
            if tool in ("get_task_context", "get_dbt_artifacts"):
                return incident.model_dump(exclude={"incident_id"})
            table, baseline, column = target_context(state["evidence"])
            return {"compare_schema": {"table_id": table, "baseline_id": baseline},
                    "get_quality_profile": {"table_id": table, "column_ids": [column]},
                    "check_connection": {"connection_id": "dbt_orders"}}[tool]

        async def collect(tool: str):
            if tool not in TOOLS:
                raise BoundedStop("TOOL_NOT_ALLOWED")
            args = args_for(tool)
            for attempt in range(3):
                if usage.tool_calls >= self.limits.tool_calls:
                    raise BoundedStop("TOOL_CALL_LIMIT")
                timeout = remaining(self.limits.tool_seconds)
                usage.tool_calls += 1
                try:
                    item = await asyncio.wait_for(self.tools.call(tool, args), timeout)
                except asyncio.TimeoutError:
                    from datetime import datetime, timezone
                    target = TargetRef(incident=incident) if tool in ("get_task_context", "get_dbt_artifacts") else TargetRef(connection_id="dbt_orders") if tool == "check_connection" else TargetRef(table_id="raw.orders")
                    item = Evidence(evidence_id=f"timeout-{tool}-{attempt}", kind=tool, source="client://timeout",
                        observed_at=datetime.now(timezone.utc), temporal_scope="run_snapshot" if target.incident else "current_observation",
                        target_ref=target, status=Status.UNAVAILABLE,
                        error=ToolError(code="TOOL_TIMEOUT", retryable=True, message="Read exceeded configured timeout"), simulated=True)
                if item.kind != tool:
                    raise BoundedStop("TOOL_KIND_MISMATCH")
                state["errors"].extend(evidence_violations(item, incident))
                retry = item.status == Status.UNAVAILABLE and item.error.retryable and item.error.code not in ("AUTH_DENIED", "AUTHENTICATION_FAILED") and attempt < 2
                # Preserve completed attempts even if the next attempt hits a budget/deadline.
                if retry:
                    item = item.model_copy(update={"evidence_id": item.evidence_id + f"-attempt-{attempt + 1}"})
                state["evidence"].append(item)
                if not retry:
                    break
                delay = self.limits.retry_delays[attempt] + random.uniform(0, 0.02)
                if deadline - time.monotonic() <= delay:
                    break
                await asyncio.sleep(delay)

        def payload():
            # Quarantine foreign execution/invocation evidence before LLM exposure.
            return {"incident_ref": incident.model_dump(mode="json"),
                    "evidence": [e.model_dump(mode="json") for e in state["evidence"] if not evidence_violations(e, incident)],
                    "retrieval_hits": [h.model_dump(mode="json") for h in state["retrieval_hits"]]}

        async def triage(_):
            state["node_trace"].append("triage")
            await collect("get_task_context")
            state["plan"] = Plan.model_validate(await ask("triage", payload()))
            return dict(state)

        async def inspector(_):
            state["node_trace"].append("inspector")
            response = await ask("inspector", {**payload(), "plan": state["plan"].model_dump(mode="json")})
            selected = response.get("tools")
            if not isinstance(selected, list) or len(selected) > 4 or len(set(selected)) != len(selected):
                raise BoundedStop("INVALID_INSPECTION_PLAN")
            for tool in selected:
                if tool not in TOOLS - {"get_task_context"}:
                    raise BoundedStop("TOOL_NOT_ALLOWED")
                await collect(tool)
            return dict(state)

        async def rca(_):
            state["node_trace"].append("rca")
            if usage.rag_calls >= self.limits.rag_calls:
                raise BoundedStop("RAG_CALL_LIMIT")
            usage.rag_calls += 1
            from .hybrid import evidence_query
            query = evidence_query([e for e in state["evidence"] if not evidence_violations(e, incident)])
            timeout = remaining(self.limits.tool_seconds)
            state["retrieval_hits"] = await asyncio.wait_for(self.retriever.search(query), timeout)
            feedback = state.get("review")
            state["diagnosis"] = Diagnosis.model_validate(await ask("rca", {**payload(), "feedback": feedback.model_dump() if feedback else None}))
            return dict(state)

        async def reviewer(_):
            state["node_trace"].append("reviewer")
            violations = code_review(state["diagnosis"], state["evidence"], incident, state["retrieval_hits"])
            response = await ask("reviewer", {**payload(), "diagnosis": state["diagnosis"].model_dump(mode="json"), "code_violations": violations})
            if not isinstance(response.get("accepted"), bool) or not isinstance(response.get("feedback"), list) or not all(isinstance(v, str) for v in response["feedback"]):
                raise BoundedStop("INVALID_REVIEW_RESPONSE")
            if not response["accepted"]:
                violations.append("SEMANTIC_REVIEW_REJECTED")
            state["review"] = Review(accepted=not violations, violations=sorted(set(violations)), feedback=response["feedback"],
                                     revision_count=state["revision_count"], semantic_reviewer=self.llm.model_id)
            if violations:
                rejected_candidates.append(sanitized({"diagnosis": state["diagnosis"].model_dump(mode="json"),
                    "review": state["review"].model_dump(mode="json"), "revision_count": state["revision_count"]}))
            return dict(state)

        async def revise(_):
            state["revision_count"] += 1
            state["node_trace"].append("revise")
            return dict(state)

        async def investigate(_):
            category=state["plan"].provisional_category
            required={"SCHEMA_CHANGE":["get_dbt_artifacts","compare_schema"],"DATA_QUALITY":["get_dbt_artifacts","get_quality_profile"],"CONNECTION_FAILURE":["get_dbt_artifacts","check_connection"],"NORMAL":["get_dbt_artifacts"]}.get(category,[])
            attempted={e.kind for e in state["evidence"]}
            missing=[tool for tool in required if tool not in attempted]
            if missing and state["replan_count"]<1:
                state["replan_count"]+=1
                state["node_trace"].append("investigate")
                for tool in missing: await collect(tool)
            return dict(state)

        graph = StateGraph(State)
        for name, node in (("triage", triage), ("inspector", inspector), ("investigate", investigate), ("rca", rca), ("reviewer", reviewer), ("revise", revise)):
            graph.add_node(name, node)
        graph.add_edge(START, "triage")
        graph.add_edge("triage", "inspector")
        graph.add_edge("inspector", "investigate")
        graph.add_edge("investigate", "rca")
        graph.add_edge("rca", "reviewer")
        graph.add_conditional_edges("reviewer", lambda s: "revise" if not s["review"].accepted and s["revision_count"] < 1 and usage.llm_calls + 2 <= self.limits.llm_calls and usage.rag_calls < self.limits.rag_calls else END, {"revise": "revise", END: END})
        graph.add_edge("revise", "rca")
        try:
            with tracing_context(enabled=False):
                timeout = remaining(self.limits.total_seconds)
                await asyncio.wait_for(graph.compile().ainvoke(dict(state), {"recursion_limit": 12}), timeout)
        except Exception as exc:
            if state.get("diagnosis") and not state.get("review"):
                rejected_candidates.append(sanitized({"diagnosis": state["diagnosis"].model_dump(mode="json"),
                    "review_error": "REVIEW_NOT_COMPLETED"}))
            reason = str(exc) if isinstance(exc, (BoundedStop, SafeAPIError)) else "TOTAL_TIMEOUT" if isinstance(exc, asyncio.TimeoutError) else f"INVALID_OR_FAILED_RESPONSE:{type(exc).__name__}"
            state["errors"].append(reason)
            state["diagnosis"] = abstain(reason, failed=True)
            state["review"] = Review(accepted=False, violations=[reason], feedback=["Execution stopped within the configured boundary"],
                                     revision_count=state["revision_count"], semantic_reviewer=self.llm.model_id)
        if not state["review"].accepted:
            # A rejected candidate may be inspected in the LLM test trace, but never escapes as a supported report.
            state["diagnosis"] = abstain("Review rejected: " + ", ".join(state["review"].violations), failed=state["diagnosis"].diagnosis_status == "failed")
        usage.elapsed_seconds = round(time.monotonic() - started, 6)
        metrics = getattr(self.llm, "metrics", None)
        if metrics is not None:
            usage.api_calls = metrics["api_calls"]
            usage.local_cache_hits = metrics["local_cache_hits"]
            usage.price_date = metrics["price_date"]
            usage.service_tier = metrics.get("service_tier")
            usage.uncertain_reserved_usd = self.llm.ledger.uncertain_usd(trace_id)
            if metrics["usage_collected"] or metrics["api_calls"] == 0:
                usage.input_tokens, usage.output_tokens = metrics["input_tokens"], metrics["output_tokens"]
                usage.tokens = usage.input_tokens + usage.output_tokens
                usage.cost = metrics["cost_usd"]
                usage.cost_basis = "provider_token_usage_price_estimate" if metrics["api_calls"] else "local_cache_or_no_request"
        serialized_evidence = json.dumps([e.model_dump(mode="json") for e in state["evidence"]], sort_keys=True)
        prompt_text = "".join(p.read_text() for p in sorted((Path(__file__).parent / "prompts").glob("*.md")))
        return Report(trace_id=trace_id, incident_ref=incident, plan=state.get("plan"), evidence=state["evidence"], retrieval_hits=state["retrieval_hits"],
            diagnosis=state["diagnosis"], review=state["review"], errors=state["errors"], usage=usage, node_trace=state["node_trace"],
            replan_count=state["replan_count"], revision_count=state["revision_count"], evidence_hash=hashlib.sha256(serialized_evidence.encode()).hexdigest(),
            versions={"app": "0.2.1", "model": self.llm.model_id, "service_tier": getattr(self.llm,"service_tier","not_applicable"), "prompt_sha256": hashlib.sha256(prompt_text.encode()).hexdigest(), "retrieval": self.retriever.version},
            validation_scope={"llm": self.llm.model_id, "transport": self.tools.transport,
                              "data": getattr(self.tools, "data_scope", "synthetic_fixture_only"),
                              "external_systems": getattr(self.tools, "external_systems", "not_connected")},
            rejected_candidates=rejected_candidates, output_diagnostics=getattr(self.llm, "diagnostics", []))

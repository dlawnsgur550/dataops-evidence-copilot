"""One local workspace: diagnosis, claim checks, recovery and evaluation."""
from __future__ import annotations

import asyncio
import csv
from datetime import datetime
from html import escape
import json
import threading
from zoneinfo import ZoneInfo
import streamlit as st

from dataops_copilot.api_safety import CostLedger, SafeAPIError, read_api_settings
from dataops_copilot.hybrid import HybridRunbooks
from dataops_copilot.llm import FakeLLM
from dataops_copilot.mcp_client import open_live_mcp
from dataops_copilot.models import IncidentRef, Report, Diagnosis
from dataops_copilot.openai_llm import OpenAILLM
from dataops_copilot.replay import ReportReplay
from dataops_copilot.retrieval import LocalRunbooks
from dataops_copilot.workflow import Limits
from dataops_copilot.workflow_v3 import ClaimCopilot
from dataops_copilot.ui_workspace import (
    ROOT, DATA, CASES, NAMES, GUARDS, load_source, evidence_rows, task_states,
    rule_counts, inspect_claim, verify_recovery, model_records, evaluation_summary,
)
from dataops_copilot import ui_visuals as visual
from dataops_copilot.local_paths import RUNTIME

PAGES = ["진단 워크스페이스", "안전성 검사", "복구 검증", "평가·모델 기록"]


@st.cache_resource
def execution_lock():
    return threading.Lock()


def budget_snapshot():
    path = RUNTIME / "llm-cost.sqlite3"
    return CostLedger(path).summary() if path.is_file() else None


async def execute(source, paid=False, live=False, full=False, incident_data=None):
    incident = IncidentRef.model_validate(incident_data) if incident_data is not None else source.incident_ref
    model = FakeLLM()
    if paid:
        budget = budget_snapshot()
        if budget and budget["requests"] >= budget["total_call_cap"]:
            raise SafeAPIError("API 요청 한도에 도달했습니다. 무료 재진단을 사용할 수 있습니다.")
        key, _ = read_api_settings(RUNTIME / "openai.env")
        model = OpenAILLM(key, RUNTIME)
    retriever = HybridRunbooks() if full else LocalRunbooks()
    try:
        if live:
            async with open_live_mcp(RUNTIME / "live-settings.json") as tools:
                report = await ClaimCopilot(tools, model, retriever=retriever,
                    limits=Limits(llm_calls=2 if full else 1), baseline=not full).diagnose(incident)
        else:
            report = await ClaimCopilot(ReportReplay(source), model, retriever=retriever,
                limits=Limits(llm_calls=2 if full else 1), baseline=not full).diagnose(incident)
        if not paid:
            report.usage.api_calls = 0
        return report
    finally:
        if hasattr(retriever, "close"):
            retriever.close()


def source_note(report, mode="저장 결과 보기"):
    real = sum(not e.simulated for e in report.evidence)
    model = report.versions.get("model", "미확인")
    model_note = "무료 테스트 대역" if "fake" in model else "과거 실제 모델 기록" if mode == "저장 결과 보기" else model
    st.html('<div class="source-strip">' + escape(
        f"{mode} · 실제 수집 근거 {real}개 / 작성한 평가 근거 {len(report.evidence)-real}개 · 데이터: 합성 · 모델: {model_note}") + '</div>')


def diagnosis_details(d):
    st.html('<div class="cause-callout"><p>' + escape(d.cause) + '</p></div>')
    for impact in d.impact:
        st.write(impact)
    for action in d.recovery_actions:
        st.markdown("**담당자가 확인할 조치**")
        for condition in action.prerequisites:
            st.caption("선행 조건 · " + condition)
        for i, step in enumerate(action.steps, 1):
            st.write(f"{i}. {step}")
        for verification in action.verification:
            st.caption("후속 확인 · " + verification)
    if not d.recovery_actions:
        st.info("현재 진단은 복구 조치를 제시하지 않습니다.")
    if d.missing_evidence:
        with st.expander("추가로 필요한 근거", expanded=d.category == "UNKNOWN"):
            for item in d.missing_evidence:
                st.write(item)


def sidebar(budget):
    with st.sidebar:
        st.html('<div class="brand"><div class="brand-icon">D</div><strong>DataOps Copilot</strong></div>'
                '<div class="brand-sub">OBSERVABILITY WORKSPACE</div>')
        page = st.radio("작업 공간", PAGES, label_visibility="collapsed", key="workspace_page")
        st.divider()
        case = st.selectbox("진단 사례", list(CASES), format_func=lambda c: CASES[c][0], key="workspace_case")
        st.caption(CASES[case][1])
        st.divider()
        st.markdown("**현재 작업 공간**")
        st.caption("로컬 실행 · 읽기 전용 도구\n\n설정 변경과 복구 조치는 담당자가 수행합니다.")
        st.caption(f"이 세션의 추가 API 호출: {st.session_state.get('workspace_api_calls', 0)}회")
        with st.expander("API 사용 한도"):
            if budget:
                st.caption(f"누적 요청 {budget['requests']} / {budget['total_call_cap']}회")
                st.caption(f"누적 추정 비용 ${budget['spent_or_reserved_usd']:.5f}")
                if budget["requests"] >= budget["total_call_cap"]:
                    st.caption("요청 한도 도달 · 유료 실행 잠금")
            else:
                st.caption("이 환경에는 API 사용 장부가 없습니다. 무료 실행이 기본입니다.")
        st.html('<div class="sidebar-foot">기본 웹 하나에서 진단과 검증을 수행합니다.<br>v3.1 · 통합 워크스페이스</div>')
    return page, case


def diagnosis_page(case, budget):
    visual.header("INCIDENT DIAGNOSIS", "파이프라인 진단", "실행을 선택하고, 장애 원인과 조치를 수집 근거에서 확인합니다.")
    source = load_source(case)
    reports = st.session_state.setdefault("workspace_reports", {})
    current = reports.setdefault(case, {"report": source.model_dump(mode="json"), "mode": "저장 결과 보기"})
    blocked = bool(budget and budget["requests"] >= budget["total_call_cap"])
    with st.form("diagnosis_controls"):
        left, right = st.columns([2.3, 1])
        mode = left.selectbox("실행 방식", ["저장 결과 보기", "저장 증거로 재진단", "실시간 MCP 조회"],
                              help="화면 열람은 호출하지 않습니다. 재진단은 무료 모델이 기본입니다.")
        paid = right.checkbox("실제 API 모델 사용", value=False, disabled=blocked,
                              help="요청 한도에 도달해 잠겨 있습니다." if blocked else "실행 버튼을 누를 때만 호출합니다.")
        full = st.checkbox("Hybrid RAG·Reviewer 추가", value=False,
                           help="기본 모델 1회, 추가 방식 2회. 실제 모델을 선택하지 않으면 무료 대역을 사용합니다.")
        with st.expander("실행키 JSON 입력"):
            upload = st.file_uploader("선택 실행키 바꾸기", type=["json"], key=f"incident_upload_{case}",
                                     help="실행 식별자를 가진 JSON입니다. CSV는 설명 자료입니다.")
        submitted = st.form_submit_button("진단 실행", type="primary")
    if submitted:
        if mode == "저장 결과 보기":
            if upload is not None:
                st.info("저장 결과 보기에서는 원본 실행키를 사용합니다. 업로드 실행키 검사는 재진단을 선택하세요.")
            current = {"report": source.model_dump(mode="json"), "mode": mode}
            reports[case] = current
        else:
            lock = execution_lock()
            if not lock.acquire(blocking=False):
                st.warning("다른 진단이 진행 중입니다. 완료 후 실행해 주세요.")
            else:
                try:
                    if upload is not None and upload.size > 16384:
                        raise ValueError("INCIDENT_JSON_TOO_LARGE")
                    incident = json.loads(upload.getvalue()) if upload is not None else None
                    with st.spinner("선택 실행과 근거·검증 규칙을 확인합니다…"):
                        report = asyncio.run(execute(source, paid, mode == "실시간 MCP 조회", full, incident))
                    st.session_state["workspace_api_calls"] = st.session_state.get("workspace_api_calls", 0) + report.usage.api_calls
                    current = {"report": report.model_dump(mode="json"), "mode": mode}
                    reports[case] = current
                except (ValueError, TypeError):
                    st.error("실행키 JSON의 형식과 필드를 확인하세요. 16KB 이하의 실행키 JSON을 입력하세요.")
                except Exception as exc:
                    st.error(str(exc) if isinstance(exc, SafeAPIError) else "진단을 완료하지 못했습니다. 실시간 조회는 로컬 서비스 연결 설정이 필요합니다.")
                finally:
                    lock.release()
    report = Report.model_validate(current["report"])
    source_note(report, current["mode"])
    counts = rule_counts(report.component_reviews)
    visual.stats([("진단 유형", NAMES[report.diagnosis.category], "선택 실행의 원인 판정"),
                  ("규칙 검사", f"{counts['PASS']} / {sum(counts.values())}", "통과한 구성요소 검사 횟수"),
                  ("수집 근거", f"{len(report.evidence)}개", "실행 기록과 별도 관측 구분"),
                  ("추가 API 호출", f"{st.session_state.get('workspace_api_calls', 0)}회", "이 작업 공간 세션 기준")])
    visual.panel_title("실행 흐름", "선택 실행의 태스크 상태 · 설정된 표시 순서")
    visual.pipeline(task_states(report))
    if report.errors:
        st.error("실행키와 증거가 일치하지 않거나 조회를 완료하지 못해 진단을 보류했습니다.")
        with st.expander("진단 중 확인한 오류"):
            st.json(report.errors)
    overview, evidence, rules, inputs = st.tabs(["원인과 조치", "수집 근거", "검색·규칙 검사", "입력 자료"])
    with overview:
        main, side = st.columns([1.8, 1], gap="large")
        with main:
            visual.panel_title("진단 근거", "근거를 통과한 주장만 표시")
            diagnosis_details(report.diagnosis)
        with side:
            visual.panel_title("증거의 관측 범위")
            visual.evidence_chart(report)
            st.caption("현재 관측의 성공만으로 과거 장애나 전체 복구를 판단하지 않습니다.")
            quality = next((e for e in report.evidence if e.kind == "get_quality_profile" and e.status == "success"), None)
            if quality and (quality.data or {}).get("row_count") is not None:
                q = quality.data
                st.markdown("**별도 시점 데이터 관측**")
                st.write(f"조회 행 수 **{q['row_count']:,}**")
                st.caption(f"주문 키 NULL {q.get('null_counts', {}).get('order_id', '미수집')}건 · 중복 {q.get('duplicate_counts', {}).get('order_id', '미수집')}건")
    with evidence:
        st.dataframe(evidence_rows(report), hide_index=True, width="stretch")
        st.caption("실제 로컬 수집 자료에도 직접 만든 합성 데이터를 사용했습니다. 화면 열람은 새 조회를 수행하지 않습니다.")
        for e in report.evidence:
            with st.expander(f"{e.kind} · {e.status}"):
                st.json(e.model_dump(mode="json"))
    with rules:
        visual.panel_title("구성요소별 검증 결과", "판정 횟수이며 모델 정확도가 아닙니다")
        visual.rules_chart(report.component_reviews, "diagnosis_rules")
        st.dataframe(report.component_reviews, hide_index=True, width="stretch")
        if report.retrieval_hits:
            st.markdown("**보고서에 보존된 검색 결과**")
            for hit in report.retrieval_hits:
                with st.expander(f"{hit.rank}. {hit.doc_id}"):
                    st.markdown(hit.content)
                    st.caption(f"{hit.method} · {hit.chunk_id}")
        else:
            st.caption("이 보고서에는 검색 결과가 없습니다. 기본 절약 방식은 추가 검색을 수행하지 않습니다.")
        with st.expander("구조화 주장·Reviewer·실행 추적"):
            st.json({"claim": report.claim_proposal, "review": report.review.model_dump(mode="json"),
                     "reviewer_findings": report.reviewer_findings, "node_trace": report.node_trace, "trace_id": report.trace_id})
    with inputs:
        st.markdown("**진단 입력: 선택 실행키**")
        st.code(source.incident_ref.model_dump_json(indent=2), language="json")
        st.download_button("실행키 JSON 내려받기", source.incident_ref.model_dump_json(indent=2), file_name=f"{case}-incident.json", on_click="ignore")
        logs = DATA / "inputs/logs" / f"{case}.log"
        if logs.is_file():
            with st.expander("저장된 실행 로그"):
                st.code(logs.read_text(), language="text")
        csv_name = {"connection": "orders_normal.csv", "schema": "orders_schema_changed.csv",
                    "quality": "orders_quality_null.csv", "normal": "orders_normal.csv"}.get(case)
        if csv_name:
            with st.expander("설명용 합성 데이터 10만 행"):
                st.caption("동일 생성 규칙으로 재생성한 설명 자료입니다. 당시 DB 덤프나 진단 업로드 입력이 아닙니다.")
                path = DATA / "inputs/data" / csv_name
                with path.open() as f:
                    preview = [row for _, row in zip(range(6), csv.DictReader(f))]
                st.dataframe(preview, hide_index=True, width="stretch")
                st.download_button("설명용 CSV 내려받기", path.read_bytes(), file_name=csv_name, mime="text/csv", on_click="ignore")
    st.divider()
    st.download_button("진단 보고서 JSON 내려받기", report.model_dump_json(indent=2), file_name=f"{case}-diagnosis.json", mime="application/json", on_click="ignore")
    st.caption("무료 재진단은 FakeLLM과 저장 근거를 사용합니다. 실시간 MCP 조회는 명시적으로 실행할 때만 수행합니다.")


def guard_page():
    visual.header("CLAIM VALIDATION", "안전성 검사", "잘못된 주장을 직접 넣고, 어떤 규칙이 차단하는지 확인합니다.")
    st.caption("기준 자료: 저장된 연결 실패 사례 · 아래 주장은 검사 목적으로 만든 반례입니다. 추가 API 호출은 없습니다.")
    kind = GUARDS[st.selectbox("검사할 반례", list(GUARDS))]
    key = "guard:" + kind
    if st.button("주장 검사 실행", type="primary"):
        st.session_state[key] = asyncio.run(inspect_claim(kind))
    result = st.session_state.get(key)
    if not result:
        st.info("반례를 선택하고 실행하면 주장별 판정과 유지된 진단을 확인할 수 있습니다.")
        st.markdown("**검사 항목**")
        st.write("존재하지 않는 근거 인용은 R02로, 근거 없는 포트 오류 단정은 R05로 차단합니다.")
        st.write("Reviewer의 근거 없는 거절은 별도로 기록해 검증된 원인·조건부 조치를 유지합니다.")
        return
    counts = rule_counts(result["checks"])
    visual.stats([("검사 대상", "구조화 주장", "연결 실패 사례에 반례 주입"),
                  ("차단·보류", str(counts["REJECT"]+counts["HOLD"]), "원인·관측·조치별 판정"),
                  ("Reviewer 반례", str(len(result["reviewer_findings"])), "각 거절의 근거 확인"),
                  ("추가 API", "0회", "무료 규칙 검사")])
    if result["blocked_checks"]:
        st.error("주장 차단 · " + ", ".join(sorted({c["rule_id"] for c in result["blocked_checks"]})))
    if result["reviewer_findings"]:
        st.warning("Reviewer의 거절에 해당하는 코드 위반 근거가 없습니다. 검증된 진단과 조건부 조치를 유지합니다.")
    visual.rules_chart(result["checks"], "guard_rules")
    st.dataframe(result["checks"], hide_index=True, width="stretch")
    st.markdown("**검사 후 진단**")
    diagnosis_details(Diagnosis.model_validate(result["diagnosis"]))
    with st.expander("주입한 주장과 Reviewer 반례"):
        st.json({"proposal": result["proposal"], "findings": result["reviewer_findings"]})
    st.download_button("주장 검사 결과 JSON", json.dumps(result, ensure_ascii=False, indent=2), file_name=f"claim-{kind}.json", on_click="ignore")


def local_time(value):
    return datetime.fromisoformat(value).astimezone(ZoneInfo("Asia/Seoul")).strftime("%H:%M:%S")


def recovery_page(case):
    visual.header("RECOVERY VERIFICATION", "복구 근거 검증", "새 실행과 태스크·품질 검사·집계 일치를 함께 확인합니다.")
    options = ["connection", "schema", "quality"]
    selected = st.selectbox("복구 검증 사례", options, index=options.index(case) if case in options else 0, format_func=lambda k: CASES[k][0])
    same = st.checkbox("반례 검사: 같은 실행을 후속 실행으로 제출", key=f"same_run_{selected}")
    key = f"recovery:{selected}:{same}"
    if st.button("복구 근거 검사 실행", type="primary"):
        st.session_state[key] = verify_recovery(selected, same)
    st.caption("저장된 실제 로컬 파이프라인 기록을 다시 검사합니다. 버튼은 설정을 수정하거나 새 DAG를 실행하지 않습니다.")
    result = st.session_state.get(key)
    if not result:
        st.info("검사를 실행하면 별도 실행 여부와 수정 이후의 시간 순서, 데이터 집계를 확인합니다.")
        return
    check = result["result"]
    record = result["developer_record"]
    aggregate = record["aggregate"]
    visual.stats([("복구 근거", "통과" if check["recovered"] else "차단", "새 실행과 전체 검사 기준"),
                  ("후속 태스크", f"{sum(v == 'success' for v in check['task_statuses'].values())} / {len(check['task_statuses'])}", "확인한 성공 태스크"),
                  ("품질 검사", f"{sum(v == 'pass' for v in check['test_results'].values())} / {len(check['test_results'])}", "필수 dbt 검사"),
                  ("후속 데이터", f"{aggregate['raw_count']:,}", "합성 데이터 행 수")])
    if check["recovered"]:
        st.success("별도 새 실행의 복구 근거가 통과했습니다.")
    else:
        st.error("복구 인정 차단 · " + ", ".join(check["reasons"]))
    context = result["followup_context"]["data"]
    visual.panel_title("수정과 후속 실행의 시간 순서", "한국 표준시 · 보존된 실행 기록")
    visual.timeline([("담당자 수정", local_time(record["action"]["performed_at"]), "보존된 개발자 실행 기록"),
                     ("후속 실행 시작", local_time(context["run_started_at"]), "별도의 실행 ID"),
                     ("후속 실행 종료", local_time(context["run_finished_at"]), "전체 필수 태스크 확인"),
                     ("집계 확인", local_time(aggregate["checked_at"]), "행 수와 금액 합계 비교")])
    visual.pipeline(check["task_statuses"], "후속 실행 태스크 상태")
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        visual.panel_title("단계별 행 수", "저장된 후속 실행의 합성 데이터")
        rows = [{"단계": label, "행 수": aggregate[field]} for label, field in [("원본", "raw_count"), ("변환", "stage_count"), ("일별 집계", "daily_count")]]
        visual.chart(rows, "단계", "행 수", "recovery_counts", height=180, description="원본·변환·일별 집계 단계의 행 수 비교")
    with right:
        visual.panel_title("품질·집계 확인")
        st.dataframe([{"항목": label, "결과": str(aggregate[field])} for label, field in
                      [("주문 키 NULL", "nulls"), ("주문 키 중복", "duplicates"), ("원본 금액 합계", "raw_sum"),
                       ("변환 금액 합계", "stage_sum"), ("일별 금액 합계", "daily_sum")]], hide_index=True, width="stretch")
    with st.expander("원본·후속 실행 ID와 검증 결과"):
        st.json({"original_run_id": check["original_run_id"], "followup_run_id": check["followup_run_id"],
                 "synthetic_negative_injection": result["same_run"], "result": check, "developer_record": record})
    st.download_button("복구 검사 결과 JSON", json.dumps(result, ensure_ascii=False, indent=2), file_name=f"recovery-{selected}.json", on_click="ignore")


def evaluation_page():
    visual.header("EVALUATION & TRACE", "평가와 실행 기록", "검사 범위와 실제 모델의 품질·비용을 함께 확인합니다.")
    summary = evaluation_summary()
    s3 = summary["stage_3"]
    visual.stats([("자동 테스트", "164개", "기존 배포본 검증 기록"),
                  ("로컬 서비스", f"{s3['live_rows_per_run']:,}행", f"합성 데이터 · {s3['runs']}회 실행"),
                  ("실제 모델 평가", "10건", "직접 만든 고정 합성 사례"),
                  ("독립 사람 검토", "미실시", "AI 검토와 구분")])
    comparison, records, scope = st.tabs(["품질·비용 비교", "실제 모델 원본", "검증 범위"])
    with comparison:
        comp = summary["stage_4"]["comparison"]
        rows = [{"구성": label, "10건 비용 (USD)": comp[k]["cost_usd"], "평균 시간 (초)": comp[k]["mean_seconds"],
                 "진단·조치 통과": comp[k]["passed"]} for k, label in [("baseline", "기본 1회"), ("full", "검색·Reviewer 2회")]]
        left, right = st.columns(2, gap="large")
        with left:
            visual.panel_title("10건 평가의 추정 API 비용", "USD · 토큰 사용량 기준")
            visual.chart(rows, "구성", "10건 비용 (USD)", "evaluation_cost", number_format=".6f",
                         description="동일 모델의 기본 구성과 검색·Reviewer 추가 구성, 합성 평가 10건의 추정 비용 비교")
        with right:
            visual.panel_title("평균 응답 시간", "초 · 같은 10개 사례")
            visual.chart(rows, "구성", "평균 시간 (초)", "evaluation_latency", number_format=".2f",
                         description="합성 평가 10건에서 기본 구성과 검색·Reviewer 추가 구성의 평균 응답 시간")
        st.dataframe([{"구성": r["구성"], "진단·조치 통과": f"{r['진단·조치 통과']} / 10",
                       "10건 추정 비용 (USD)": f"{r['10건 비용 (USD)']:.9f}", "평균 시간 (초)": r["평균 시간 (초)"]}
                      for r in rows], hide_index=True, width="stretch")
        st.caption("같은 Luna 모델의 구성 비교입니다. 추가 구성은 관측 인용까지 포함하면 7/10입니다. 작은 합성 표본이며 현업 정확도나 RAG 단독 효과로 일반화하지 않습니다.")
        st.info("이번 비교에서는 추가 Reviewer의 품질 이득을 확인하지 못해 기본 1회 구성을 선택했습니다.")
    with records:
        paths = model_records()
        selected = st.selectbox("과거 실제 모델 기록", list(paths))
        report = Report.model_validate_json(paths[selected].read_text())
        st.caption("보존한 실제 모델 원본입니다. 입력은 합성 평가 자료이며 지금은 API를 호출하지 않습니다.")
        visual.stats([("원본 모델", report.versions.get("model", "미확인"), "당시 호출 모델"),
                      ("당시 API 호출", f"{report.usage.api_calls}회", "현재 호출과 구분"),
                      ("당시 추정 비용", f"${report.usage.cost:.7f}" if report.usage.cost is not None else "미수집", "실제 청구서 미조회"),
                      ("현재 추가 호출", "0회", "저장된 파일 열람")])
        st.markdown("**" + NAMES[report.diagnosis.category] + "**")
        diagnosis_details(report.diagnosis)
        rejected = [c for c in report.component_reviews if c["verdict"] != "PASS"]
        if rejected:
            st.warning("원본 기록에서 차단된 구성요소를 그대로 표시합니다.")
            st.dataframe(rejected, hide_index=True, width="stretch")
        for hit in report.retrieval_hits:
            with st.expander(f"당시 검색 런북 · {hit.rank}. {hit.doc_id}"):
                st.markdown(hit.content)
        with st.expander("실제 모델 원본 JSON"):
            st.json(report.model_dump(mode="json"))
        st.download_button("모델 원본 JSON 내려받기", paths[selected].read_bytes(), file_name=paths[selected].name, on_click="ignore")
    with scope:
        st.dataframe([
            {"검사": "자동 테스트", "결과": "164개 통과", "범위": "기존 배포본 계약·보안·MCP 프로토콜·회귀"},
            {"검사": "무료 규칙 반례", "결과": "10,000/10,000", "범위": "10개 의미 유형의 변형. 독립 장애 수 아님"},
            {"검사": "무료 재생", "결과": "1,000/1,000", "범위": "500개 증거 묶음 × 두 구성. FakeLLM"},
            {"검사": "실제 로컬 서비스", "결과": "10만 행 · 7회 · 복구 3건", "범위": "실제 Airflow/PostgreSQL/dbt + 합성 데이터 + FakeLLM"},
            {"검사": "최초 실제 모델 비교", "결과": "진단·조치 각 8/10", "범위": "직접 만든 고정 합성 사례. 같은 Luna 모델"},
            {"검사": "v3.1 제한 재검증", "결과": "보류·성공 ID 2/2", "범위": "전체 구성요소 1/2. 전체 평가 10/10으로 합산 금지"},
            {"검사": "독립 사람 검토", "결과": "미실시", "범위": "AI 근거 검토 12건과 구분"},
        ], hide_index=True, width="stretch")
        st.caption("LangSmith는 비활성이며 독립 LLM Judge는 미구현입니다. 최신 기본 경로는 순차 처리이며 기존 LangGraph 경로와 구분합니다.")


def main():
    st.set_page_config(page_title="DataOps Copilot", page_icon="◉", layout="wide")
    visual.setup()
    budget = budget_snapshot()
    page, case = sidebar(budget)
    if page == PAGES[0]:
        diagnosis_page(case, budget)
    elif page == PAGES[1]:
        guard_page()
    elif page == PAGES[2]:
        recovery_page(case)
    else:
        evaluation_page()


if __name__ == "__main__":
    main()

import argparse
import asyncio
import json
from pathlib import Path

from .settings_policy import ProjectPolicy
from .fixtures import FIXTURES, FixtureAdapter, incident_for
from .llm import FakeLLM
from .mcp_client import open_live_mcp, open_mcp
from .models import IncidentRef, Report
from .workflow import Limits
from .workflow_v3 import ClaimCopilot as Copilot


async def run(args):
    llm = FakeLLM()
    limits = Limits()
    retriever = None
    if args.retrieval == "hybrid":
        from .hybrid import HybridRunbooks
        retriever = HybridRunbooks()
    if args.llm == "openai":
        from .api_safety import read_api_settings
        from .openai_llm import OpenAILLM
        key, _ = read_api_settings(Path(args.api_settings))
        llm = OpenAILLM(key, Path(args.api_settings).resolve().parent, purpose=args.budget_profile)
        limits = Limits(llm_calls=4)
    replay = Report.model_validate_json(Path(args.replay_report).read_text()) if args.replay_report else None
    incident = replay.incident_ref if replay else IncidentRef.model_validate_json(Path(args.incident).read_text()) if args.settings else incident_for(args.fixture)
    if replay:
        from .replay import ReportReplay
        report = await Copilot(ReportReplay(replay), llm, retriever=retriever, limits=limits, policy=ProjectPolicy.load(args.project_policy)).diagnose(incident)
        protocol = {"initialized": False, "note": "Saved evidence replay; no live MCP or database query in this run"}
    elif args.settings:
        async with open_live_mcp(Path(args.settings)) as tools:
            report = await Copilot(tools, llm, retriever=retriever, limits=limits, policy=ProjectPolicy.load(args.project_policy)).diagnose(incident)
            protocol = {"initialized": True, "protocol_version": tools.initialization.protocolVersion,
                        "server": tools.initialization.serverInfo.model_dump(), "tools": [t.name for t in tools.tool_list.tools]}
    elif args.transport == "stdio":
        async with open_mcp(args.fixture) as tools:
            report = await Copilot(tools, llm, retriever=retriever, limits=limits, policy=ProjectPolicy.load(args.project_policy)).diagnose(incident)
            protocol = {"initialized": True, "protocol_version": tools.initialization.protocolVersion,
                        "server": tools.initialization.serverInfo.model_dump(),
                        "tools": [t.name for t in tools.tool_list.tools]}
    else:
        report = await Copilot(FixtureAdapter(args.fixture), llm, retriever=retriever, limits=limits, policy=ProjectPolicy.load(args.project_policy)).diagnose(incident)
        protocol = {"initialized": False, "note": "Direct fake adapter; MCP protocol not used"}
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2) + "\n")
    print(json.dumps({"fixture_selector": args.fixture, "category": report.diagnosis.category,
                      "diagnosis_status": report.diagnosis.diagnosis_status, "review_accepted": report.review.accepted,
                      "usage": report.usage.model_dump(), "nodes": report.node_trace,
                      "scope": report.validation_scope, "protocol": protocol,
                      "report": str(Path(args.output).resolve()) if args.output else None}, ensure_ascii=False, indent=2))
    if retriever is not None: retriever.close()
    return 0 if report.review.accepted else 2


def main():
    parser = argparse.ArgumentParser(description="조회 전용 진단. 기본 fake, 명시적인 --llm openai에서만 유료 호출합니다.")
    parser.add_argument("--project-policy", help="명시적 대상·태스크·검사·업무 계약 설정 JSON")
    parser.add_argument("--fixture", choices=FIXTURES, default="schema")
    parser.add_argument("--transport", choices=("stdio", "direct"), default="stdio")
    parser.add_argument("--retrieval", choices=("lexical", "hybrid"), default="hybrid")
    parser.add_argument("--output", help="Save structured report JSON")
    parser.add_argument("--settings", help="명시적인 실제 로컬 조회 설정 JSON")
    parser.add_argument("--incident", help="실제 선택 실행의 IncidentRef JSON; --settings와 함께 필수")
    parser.add_argument("--replay-report", help="저장된 증거 보고서 재생. 현재 외부 시스템 조회와 구분합니다.")
    parser.add_argument("--llm", choices=("fake", "openai"), default="fake")
    parser.add_argument("--api-settings", help="명시적인 로컬 openai.env 경로. 키는 인자로 받지 않습니다.")
    parser.add_argument("--budget-profile", choices=("standard", "evaluation"), default="standard", help="evaluation은 요청 수만 늘리고 같은 금액 상한·장부를 유지합니다.")
    args = parser.parse_args()
    if args.settings and not args.incident:
        parser.error("--settings에는 --incident가 필요합니다")
    if args.replay_report and args.settings:
        parser.error("--replay-report와 --settings는 함께 사용할 수 없습니다")
    if args.llm == "openai" and not args.api_settings:
        parser.error("--llm openai에는 --api-settings가 필요합니다")
    if args.api_settings and args.llm != "openai":
        parser.error("--api-settings는 --llm openai와 함께 사용합니다")
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()

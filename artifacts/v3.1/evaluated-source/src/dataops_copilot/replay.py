"""기존에 실제로 수집한 증거를 재생합니다. 이번 실행의 실시간 조회로 부르지 않습니다."""
from .models import IncidentRef, Report, Status


class ReportReplay:
    transport = "saved_evidence_replay_no_live_query"
    data_scope = "replay_of_saved_collected_evidence"
    external_systems = "not_queried_in_this_run"

    def __init__(self, report: Report):
        self.report = report

    async def call(self, tool, arguments):
        if tool in ("get_task_context", "get_dbt_artifacts"):
            ref = IncidentRef(incident_id="replay", **arguments)
            if ref.execution_key() != self.report.incident_ref.execution_key():
                raise ValueError("Replay execution mismatch")
        matches = [e for e in self.report.evidence if e.kind == tool]
        if not matches:
            raise ValueError("Requested evidence was not collected in the source report")
        item = matches[-1]
        if tool in ("compare_schema", "get_quality_profile") and arguments["table_id"] != item.target_ref.table_id:
            raise ValueError("Replay table mismatch")
        if tool == "check_connection" and arguments["connection_id"] != item.target_ref.connection_id:
            raise ValueError("Replay connection mismatch")
        return item

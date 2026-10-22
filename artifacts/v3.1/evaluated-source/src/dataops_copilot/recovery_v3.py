"""R10: new-run identity, timestamps, task/test completeness AND bound aggregates."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from .claim_engine import integrity


def check_recovery_v3(original,followup,context,artifacts,target,aggregate,repair):
    reasons=[]
    if original.dag_id!=followup.dag_id or original.run_id==followup.run_id:reasons.append('SEPARATE_SAME_DAG_RUN_REQUIRED')
    if any(e.status!='success' or integrity(e,followup,target) for e in (context,artifacts)):reasons.append('FOLLOWUP_EVIDENCE_UNVERIFIED')
    c=context.data or {};a=artifacts.data or {};tasks=c.get('task_statuses',{});tests=a.get('test_results',{})
    if context.kind!='get_task_context' or artifacts.kind!='get_dbt_artifacts':reasons.append('WRONG_EVIDENCE_KIND')
    if c.get('state')!='success' or set(tasks)!=set(target.tasks) or any(s!='success' for s in tasks.values()):reasons.append('TASKS_NOT_ALL_SUCCESS')
    if a.get('artifact_status','complete')!='complete' or a.get('exit_code',0)!=0 or a.get('issue') is not None or not set(target.required_tests).issubset(tests) or any(s!='pass' for s in tests.values()):reasons.append('TESTS_OR_ARTIFACTS_INCOMPLETE')
    try:
        started=datetime.fromisoformat(c['run_started_at']);finished=datetime.fromisoformat(c['run_finished_at']);fixed=datetime.fromisoformat(repair['performed_at']);checked=datetime.fromisoformat(aggregate['checked_at'])
        if any(x.tzinfo is None for x in (started,finished,fixed,checked)) or not fixed<=started<=finished<=checked:reasons.append('FOLLOWUP_TIMELINE_UNVERIFIED')
    except (ValueError,KeyError,TypeError):reasons.append('FOLLOWUP_TIMELINE_UNVERIFIED')
    if aggregate.get('run_id')!=followup.run_id or aggregate.get('table_id')!=target.table_id:reasons.append('AGGREGATE_WRONG_RUN_OR_TARGET')
    if aggregate.get('matched') is not True or aggregate.get('nulls')!=0 or aggregate.get('duplicates')!=0:reasons.append('AGGREGATE_OR_QUALITY_FAILED')
    if not all(type(aggregate.get(k)) is int and aggregate[k]>0 for k in ('raw_count','stage_count','daily_count')):reasons.append('AGGREGATE_COUNTS_MISSING_OR_INVALID')
    try:
        if not all(Decimal(aggregate[k]).is_finite() for k in ('raw_sum','stage_sum','daily_sum')):reasons.append('AGGREGATE_SUMS_INVALID')
    except (KeyError,TypeError,ValueError,InvalidOperation):reasons.append('AGGREGATE_SUMS_MISSING_OR_INVALID')
    if not (aggregate.get('raw_count')==aggregate.get('stage_count')==aggregate.get('daily_count') and aggregate.get('raw_sum')==aggregate.get('stage_sum')==aggregate.get('daily_sum')):reasons.append('AGGREGATE_VALUES_MISMATCH')
    return {'recovered':not reasons,'rule_id':'R10','reasons':reasons,'original_run_id':original.run_id,'followup_run_id':followup.run_id,
       'scope':'actual controlled local synthetic pipeline; authorized developer repair; no agent writes','task_statuses':tasks,'test_results':tests}

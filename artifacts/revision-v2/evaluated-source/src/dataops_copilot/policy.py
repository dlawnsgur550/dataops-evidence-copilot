"""Fixed allowlist for the demo and separately authored evaluation domains."""
TABLE_BASELINES={'raw.orders':'orders-v1','raw.web_orders':'web-v1','raw.orders_archive':'archive-v1'}
QUALITY_COLUMNS={'order_id','customer_id'}

def target_context(evidence):
    contexts=[e.data for e in evidence if e.kind=='get_task_context' and e.status=='success']
    c=contexts[-1] if contexts else {}
    table=c.get('table_id','raw.orders')
    column=c.get('quality_column','order_id')
    if table not in TABLE_BASELINES or column not in QUALITY_COLUMNS:
        raise ValueError('TARGET_NOT_IN_DEMO_ALLOWLIST')
    return table,TABLE_BASELINES[table],column

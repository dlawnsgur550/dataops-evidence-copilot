select created_at::date as order_date, count(*) as order_count, sum(amount) as total_amount
from {{ ref('stg_orders') }} group by 1

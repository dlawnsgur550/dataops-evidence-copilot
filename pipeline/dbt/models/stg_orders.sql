select order_id, customer_id, amount, created_at from {{ source('raw', 'orders') }}

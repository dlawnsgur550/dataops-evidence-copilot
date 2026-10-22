
  
    

  create  table "dataops_c_cp2"."analytics"."daily_orders__dbt_tmp"
  
  
    as
  
  (
    select created_at::date as order_date, count(*) as order_count, sum(amount) as total_amount
from "dataops_c_cp2"."analytics"."stg_orders" group by 1
  );
  
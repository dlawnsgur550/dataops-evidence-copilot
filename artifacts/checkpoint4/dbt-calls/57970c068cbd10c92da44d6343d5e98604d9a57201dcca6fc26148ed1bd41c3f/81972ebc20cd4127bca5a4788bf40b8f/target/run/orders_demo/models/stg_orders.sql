
  
    

  create  table "dataops_c_cp2"."analytics"."stg_orders__dbt_tmp"
  
  
    as
  
  (
    select order_id, customer_id, amount, created_at from "dataops_c_cp2"."raw"."orders"
  );
  
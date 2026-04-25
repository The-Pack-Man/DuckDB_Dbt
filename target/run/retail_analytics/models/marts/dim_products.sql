
  
    
    

    create  table
      "dev"."main"."dim_products__dbt_tmp"
  
    as (
      with products as (
    select * from "dev"."main_staging"."stg_products"
)

select
    product_id,
    product_name,
    category,
    subcategory,
    cost_price,
    list_price,
    gross_margin,
    margin_pct
from products
    );
  
  
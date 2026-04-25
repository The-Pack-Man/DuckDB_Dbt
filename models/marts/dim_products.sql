with products as (
    select * from {{ ref('stg_products') }}
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

with orders as (
    select * from {{ ref('stg_orders') }}
),

customers as (
    select * from {{ ref('stg_customers') }}
),

products as (
    select * from {{ ref('stg_products') }}
),

joined as (
    select
        o.order_id,
        o.order_date,
        date_trunc('month', o.order_date)  as order_month,
        date_part('year',  o.order_date)   as order_year,

        -- customer fields
        o.customer_id,
        c.full_name                        as customer_name,
        c.segment                          as customer_segment,
        c.city                             as customer_city,
        c.state                            as customer_state,

        -- product fields
        o.product_id,
        p.product_name,
        p.category                         as product_category,
        p.subcategory                      as product_subcategory,

        -- order metrics
        o.quantity,
        o.unit_price,
        o.discount_pct,
        o.gross_revenue,
        o.net_revenue,
        o.status
    from orders o
    left join customers c using (customer_id)
    left join products  p using (product_id)
)

select * from joined

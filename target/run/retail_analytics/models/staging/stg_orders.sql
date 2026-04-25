
  
  create view "dev"."main_staging"."stg_orders__dbt_tmp" as (
    with source as (
    select * from "dev"."main"."orders"
),

transformed as (
    select
        order_id,
        cast(order_date   as date)   as order_date,
        customer_id,
        product_id,
        cast(quantity     as integer) as quantity,
        cast(unit_price   as double)  as unit_price,
        cast(discount_pct as double)  as discount_pct,
        round(
            cast(quantity as double) * cast(unit_price as double),
            2
        )                                                                as gross_revenue,
        round(
            cast(quantity as double) * cast(unit_price as double)
            * (1.0 - cast(discount_pct as double)),
            2
        )                                                                as net_revenue,
        lower(trim(status))                                              as status
    from source
)

select * from transformed
  );

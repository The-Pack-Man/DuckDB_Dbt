with source as (
    select * from "dev"."main"."products"
),

renamed as (
    select
        product_id,
        product_name,
        category,
        subcategory,
        cast(cost_price  as double) as cost_price,
        cast(list_price  as double) as list_price,
        round(cast(list_price as double) - cast(cost_price as double), 2)                        as gross_margin,
        round(
            (cast(list_price as double) - cast(cost_price as double))
            / cast(list_price as double) * 100,
            2
        )                                                                                         as margin_pct
    from source
)

select * from renamed
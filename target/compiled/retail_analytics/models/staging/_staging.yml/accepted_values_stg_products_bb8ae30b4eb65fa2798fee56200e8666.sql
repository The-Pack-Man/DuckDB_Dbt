
    
    

with all_values as (

    select
        category as value_field,
        count(*) as n_records

    from "dev"."main_staging"."stg_products"
    group by category

)

select *
from all_values
where value_field not in (
    'Technology','Furniture','Office Supplies'
)



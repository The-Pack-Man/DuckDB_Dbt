
    
    

with all_values as (

    select
        segment as value_field,
        count(*) as n_records

    from "dev"."main"."dim_customers"
    group by segment

)

select *
from all_values
where value_field not in (
    'Consumer','Corporate','Home Office'
)



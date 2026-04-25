with customers as (
    select * from {{ ref('stg_customers') }}
)

select
    customer_id,
    full_name,
    email,
    city,
    state,
    signup_date,
    segment,
    datediff('day', signup_date, current_date) as days_since_signup
from customers

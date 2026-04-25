with source as (
    select * from {{ ref('customers') }}
),

renamed as (
    select
        customer_id,
        first_name,
        last_name,
        first_name || ' ' || last_name                       as full_name,
        lower(trim(email))                                   as email,
        city,
        state,
        cast(signup_date as date)                            as signup_date,
        segment
    from source
)

select * from renamed

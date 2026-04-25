
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select full_name
from "dev"."main_staging"."stg_customers"
where full_name is null



  
  
      
    ) dbt_internal_test
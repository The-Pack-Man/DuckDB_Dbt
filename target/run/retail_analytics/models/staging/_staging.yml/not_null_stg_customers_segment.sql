
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select segment
from "dev"."main_staging"."stg_customers"
where segment is null



  
  
      
    ) dbt_internal_test
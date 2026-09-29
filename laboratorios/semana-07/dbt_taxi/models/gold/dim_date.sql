{#
    GOLD - dim_date: una fila por día, acotada al rango del laboratorio
    (var taxi_start_date .. taxi_end_date, ver dbt_project.yml).
#}

with spine as (

    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('" ~ var('taxi_start_date') ~ "' as date)",
        end_date="dateadd(day, 1, cast('" ~ var('taxi_end_date') ~ "' as date))"
    ) }}

)

select
    to_number(to_char(date_day, 'YYYYMMDD')) as date_key,
    date_day                                  as full_date,
    year(date_day)                            as year,
    quarter(date_day)                         as quarter,
    month(date_day)                           as month,
    monthname(date_day)                       as month_name,
    day(date_day)                             as day_of_month,
    dayofweek(date_day)                       as day_of_week,
    dayname(date_day)                         as day_name,
    case when dayofweek(date_day) in (0, 6) then true else false end as is_weekend
from spine

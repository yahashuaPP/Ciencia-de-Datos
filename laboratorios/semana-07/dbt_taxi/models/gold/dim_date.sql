{#
    GOLD - dim_date: una fila por día, acotada al rango del laboratorio
    (var taxi_start_date .. taxi_end_date, ver dbt_project.yml) MÁS un día extra.

    El día extra existe porque silver_trips filtra por fecha de RECOGIDA: un viaje que empieza
    el 31-08-2026 a las 23:50 y termina el 01-09-2026 es válido, y su dropoff_date_key
    (20260901) tiene que existir aquí o el test relationships de fct_trips falla.
    Como Silver descarta viajes de más de 24 h, un día extra siempre alcanza.
#}

with spine as (

    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('" ~ var('taxi_start_date') ~ "' as date)",
        end_date="dateadd(day, 2, cast('" ~ var('taxi_end_date') ~ "' as date))"
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

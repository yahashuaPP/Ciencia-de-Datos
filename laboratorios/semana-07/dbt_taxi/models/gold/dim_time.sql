{#
    GOLD - dim_time: grano = hora del día (0-23). Se eligió este grano (en vez de minuto a
    minuto) porque el análisis de viajes por "momento del día" se hace típicamente por hora;
    un grano de 1440 filas por minuto no aportaría valor analítico adicional para este dataset.
#}

with hours as (

    select seq4() as hour_of_day
    from table(generator(rowcount => 24))

)

select
    hour_of_day as hour_key,
    hour_of_day,
    case when hour_of_day < 12 then 'AM' else 'PM' end as am_pm,
    case
        when hour_of_day between 5 and 11 then 'Morning'
        when hour_of_day between 12 and 16 then 'Afternoon'
        when hour_of_day between 17 and 20 then 'Evening'
        else 'Night'
    end as time_of_day_bucket
from hours
order by hour_of_day

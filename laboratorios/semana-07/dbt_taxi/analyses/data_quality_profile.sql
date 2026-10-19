-- ============================================================================================
-- Perfil de calidad de BRONZE.RAW_YELLOW_TRIPDATA (antes de limpiar).
-- Cada fila es un problema con su conteo y porcentaje: es la evidencia de las decisiones de
-- limpieza de silver_trips.sql. Los IDs (Q01, Q02, ...) son los que cita el README.
--
-- Cómo correrlo:  make quality   (compila este análisis, lo ejecuta en Snowflake y escribe
--                                 docs/calidad_datos.md con la tabla de resultados)
-- Escanea Bronze completo: correrlo una vez después de la ingesta, no en cada build.
-- ============================================================================================

with raw as (
    select * from {{ source('bronze', 'raw_yellow_tripdata') }}
),

dup as (
    select count(*) - count(distinct
               coalesce(vendorid::varchar, '') || '|' || coalesce(tpep_pickup_datetime::varchar, '') || '|' ||
               coalesce(tpep_dropoff_datetime::varchar, '') || '|' || coalesce(pulocationid::varchar, '') || '|' ||
               coalesce(dolocationid::varchar, '') || '|' || coalesce(trip_distance::varchar, '') || '|' ||
               coalesce(total_amount::varchar, '')) as n_dup,
           count(*) as n_total
    from raw
),

metrics as (
    select 'Q00' as id, '-' as dimension, 'Filas en Bronze' as problema,
           count(*) as afectados, count(*) as total from raw
    union all
    select 'Q01', 'Completitud', 'Sin hora de recogida o de llegada',
           count_if(tpep_pickup_datetime is null or tpep_dropoff_datetime is null), count(*) from raw
    union all
    select 'Q02', 'Validez', 'Llegada anterior a la recogida',
           count_if(tpep_dropoff_datetime < tpep_pickup_datetime), count(*) from raw
    union all
    select 'Q03', 'Unicidad', 'Duplicados por llave de negocio (filas extra)', n_dup, n_total from dup
    union all
    select 'Q04', 'Validez', 'Duración mayor a 24 h',
           count_if(datediff('minute', tpep_pickup_datetime, tpep_dropoff_datetime) > 1440), count(*) from raw
    union all
    select 'Q05', 'Validez', 'Distancia negativa', count_if(trip_distance < 0), count(*) from raw
    union all
    select 'Q06', 'Validez', 'Tarifa negativa', count_if(fare_amount < 0), count(*) from raw
    union all
    select 'Q07', 'Validez', 'Importe total negativo', count_if(total_amount < 0), count(*) from raw
    union all
    select 'Q08', 'Validez', 'Recogida fuera del rango del laboratorio',
           count_if(tpep_pickup_datetime < '{{ var("taxi_start_date") }}'::timestamp_ntz
                 or tpep_pickup_datetime >= dateadd(day, 1, '{{ var("taxi_end_date") }}'::timestamp_ntz)),
           count(*) from raw
    union all
    select 'Q09', 'Completitud', 'passenger_count nulo', count_if(passenger_count is null), count(*) from raw
    union all
    select 'Q10', 'Exactitud', 'passenger_count = 0 (viaje sin pasajeros)', count_if(passenger_count = 0), count(*) from raw
    union all
    select 'Q11', 'Consistencia', 'VendorID fuera del dominio TLC {1,2,6,7}',
           count_if(vendorid is null or vendorid not in (1, 2, 6, 7)), count(*) from raw
    union all
    select 'Q12', 'Consistencia', 'RatecodeID nulo o fuera de {1..6, 99}',
           count_if(ratecodeid is null or ratecodeid not in (1, 2, 3, 4, 5, 6, 99)), count(*) from raw
    union all
    select 'Q13', 'Consistencia', 'payment_type fuera de {0..6}',
           count_if(payment_type is null or payment_type not between 0 and 6), count(*) from raw
    union all
    select 'Q14', 'Consistencia', 'Zona de recogida o destino fuera de 1-265',
           count_if(pulocationid not between 1 and 265 or dolocationid not between 1 and 265
                    or pulocationid is null or dolocationid is null), count(*) from raw
    union all
    select 'Q15', 'Completitud', 'store_and_fwd_flag nulo', count_if(store_and_fwd_flag is null), count(*) from raw
    union all
    select 'Q16', 'Completitud', 'congestion_surcharge o airport_fee nulos',
           count_if(congestion_surcharge is null or airport_fee is null), count(*) from raw
    union all
    select 'Q17', 'Exactitud', 'Distancia mayor a 100 millas (atípico, no se filtra)',
           count_if(trip_distance > 100), count(*) from raw
    union all
    select 'Q18', '-', 'Filas que llegan a Silver (retención)',
           (select count(*) from {{ ref('silver_trips') }}), count(*) from raw
)

select
    id,
    dimension,
    problema,
    afectados,
    total,
    round(100 * afectados / nullif(total, 0), 2) as pct
from metrics
order by id

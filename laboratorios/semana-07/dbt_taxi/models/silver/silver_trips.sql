{#
    SILVER - NYC Yellow Taxi: viajes limpios y estandarizados a partir de BRONZE.RAW_YELLOW_TRIPDATA.

    Decisiones de limpieza, por dimensión de calidad de datos:

    1) TIPOS DE DATOS
       - Montos se castean explícitamente a NUMBER(10,2) (vienen como FLOAT en Bronze).
       - IDs (vendor, rate code, location, payment type) se castean a NUMBER(38,0).
       - Las marcas de tiempo ya llegan como TIMESTAMP_NTZ desde el COPY INTO de Bronze.

    2) DUPLICADOS
       - El dataset de la TLC tiene, ocasionalmente, filas repetidas dentro del mismo archivo
         mensual (problema de calidad documentado del origen). Como no existe un ID de viaje
         nativo, se deduplica por una llave de negocio (vendor + horarios + zonas + distancia +
         importe total) quedándonos con la carga más reciente (_loaded_at desc) en caso de empate.

    3) VALORES NULOS
       - Cargos aditivos opcionales (extra, mta_tax, peajes, recargo de mejora, tarifas de
         congestión/aeropuerto/CBD): NULL se interpreta como "no aplicó" y se reemplaza por 0,
         porque son sumas sobre la tarifa base, no atributos obligatorios.
       - store_and_fwd_flag NULL -> 'N': es, por lejos, el valor más común (el taxímetro tenía
         conexión y no tuvo que "guardar y reenviar" el viaje).
       - passenger_count NULL se conserva como NULL: es un dato realmente desconocido (campo
         ingresado por el conductor) y no hay una base razonable para inventarlo.

    4) REGISTROS INVÁLIDOS
       - Se descartan viajes sin ambas marcas de tiempo, o con drop-off anterior al pickup.
       - Se descartan viajes con duración mayor a 24h (1440 min): un valor casi siempre
         producido por un error del taxímetro/transmisión, no por un viaje real.
       - Se descartan viajes con distancia, tarifa o importe total negativos (reembolsos o
         errores de captura, no viajes válidos para análisis operativo).
       - Se descartan viajes cuya fecha de pickup cae fuera del rango del laboratorio
         (2025-01-01 a 2026-08-31): la TLC ocasionalmente publica alguna fila con una fecha
         mal capturada por el taxímetro (p.ej. años fuera de rango).

    5) NOMBRES Y FORMATOS INCONSISTENTES
       - Todas las columnas se renombran a snake_case con nombres de negocio explícitos
         (p.ej. tolls_amount, trip_distance_miles).
       - Códigos fuera del dominio documentado por la TLC se normalizan a su valor "Unknown"
         en vez de dejarlos pasar como están (lo que rompería los joins/tests de relationships
         en Gold):
           * vendorid    : válidos {1,2,6,7}      -> fuera de rango => -1  (Unknown)
           * ratecodeid  : válidos {1..6,99}       -> fuera de rango => 99 (Unknown, ya es
                                                       parte del dominio oficial)
           * payment_type: válidos {0..6}          -> fuera de rango => 5  (Unknown, ya es
                                                       parte del dominio oficial)
           * PU/DOLocationID: válidos {1..265}     -> fuera de rango => 264 (Unknown, ya
                                                       existe como zona en el catálogo TLC)
#}

with source as (

    select * from {{ source('bronze', 'raw_yellow_tripdata') }}

),

deduplicated as (

    select
        *,
        row_number() over (
            partition by
                vendorid, tpep_pickup_datetime, tpep_dropoff_datetime,
                pulocationid, dolocationid, trip_distance, total_amount
            order by _loaded_at desc
        ) as _dedup_rank
    from source

),

cleaned as (

    select
        -- No existe un ID de viaje nativo en el dataset de TLC: se deriva una llave sustituta
        -- de la posición física de la fila en el archivo de origen, garantizando unicidad
        -- incluso si dos viajes reales comparten todos sus atributos de negocio.
        {{ dbt_utils.generate_surrogate_key(['_source_file', '_source_row_number']) }} as trip_key,

        case when vendorid in (1, 2, 6, 7) then vendorid::number(38, 0) else -1 end as vendor_id,

        tpep_pickup_datetime::timestamp_ntz  as pickup_datetime,
        tpep_dropoff_datetime::timestamp_ntz as dropoff_datetime,
        datediff('minute', tpep_pickup_datetime, tpep_dropoff_datetime) as trip_duration_minutes,

        passenger_count::number(38, 0)            as passenger_count,
        greatest(trip_distance, 0)::number(10, 2) as trip_distance_miles,

        case when ratecodeid in (1, 2, 3, 4, 5, 6, 99) then ratecodeid::number(38, 0) else 99 end as rate_code_id,

        coalesce(upper(trim(store_and_fwd_flag)), 'N') as store_and_fwd_flag,

        case when pulocationid between 1 and 265 then pulocationid::number(38, 0) else 264 end as pu_location_id,
        case when dolocationid between 1 and 265 then dolocationid::number(38, 0) else 264 end as do_location_id,

        case when payment_type in (0, 1, 2, 3, 4, 5, 6) then payment_type::number(38, 0) else 5 end as payment_type_id,

        fare_amount::number(10, 2)                        as fare_amount,
        coalesce(extra, 0)::number(10, 2)                 as extra_amount,
        coalesce(mta_tax, 0)::number(10, 2)               as mta_tax_amount,
        coalesce(tip_amount, 0)::number(10, 2)            as tip_amount,
        coalesce(tolls_amount, 0)::number(10, 2)          as tolls_amount,
        coalesce(improvement_surcharge, 0)::number(10, 2) as improvement_surcharge_amount,
        coalesce(congestion_surcharge, 0)::number(10, 2)  as congestion_surcharge_amount,
        coalesce(airport_fee, 0)::number(10, 2)           as airport_fee_amount,
        coalesce(cbd_congestion_fee, 0)::number(10, 2)    as cbd_congestion_fee_amount,
        total_amount::number(10, 2)                       as total_amount,

        _source_file,
        _source_row_number,
        _loaded_at

    from deduplicated
    where
        _dedup_rank = 1
        and tpep_pickup_datetime is not null
        and tpep_dropoff_datetime is not null
        and tpep_dropoff_datetime >= tpep_pickup_datetime
        and datediff('minute', tpep_pickup_datetime, tpep_dropoff_datetime) <= 1440
        and trip_distance >= 0
        and fare_amount >= 0
        and total_amount >= 0
        and tpep_pickup_datetime >= '{{ var("taxi_start_date") }}'::timestamp_ntz
        and tpep_pickup_datetime < dateadd(day, 1, '{{ var("taxi_end_date") }}'::timestamp_ntz)

)

select * from cleaned

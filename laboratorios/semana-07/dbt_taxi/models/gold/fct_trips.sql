{#
    GOLD - fct_trips: tabla de hechos del esquema estrella.

    GRANO: un registro por viaje individual de yellow taxi (mismo grano que silver_trips).
#}

with trips as (

    select * from {{ ref('silver_trips') }}

)

select
    trip_key,

    to_number(to_char(pickup_datetime, 'YYYYMMDD'))  as pickup_date_key,
    to_number(to_char(dropoff_datetime, 'YYYYMMDD')) as dropoff_date_key,
    hour(pickup_datetime)                             as pickup_hour_key,
    hour(dropoff_datetime)                            as dropoff_hour_key,

    pu_location_id  as pu_location_key,
    do_location_id  as do_location_key,
    vendor_id       as vendor_key,
    rate_code_id    as rate_code_key,
    payment_type_id as payment_type_key,

    passenger_count,
    trip_distance_miles,
    trip_duration_minutes,
    store_and_fwd_flag,

    fare_amount,
    extra_amount,
    mta_tax_amount,
    tip_amount,
    tolls_amount,
    improvement_surcharge_amount,
    congestion_surcharge_amount,
    airport_fee_amount,
    cbd_congestion_fee_amount,
    total_amount

from trips

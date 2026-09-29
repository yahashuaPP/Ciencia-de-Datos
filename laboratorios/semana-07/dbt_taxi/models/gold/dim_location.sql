{#
    GOLD - dim_location: zonas de taxi de la TLC. Se usa en fct_trips dos veces (rol de
    "recogida" y rol de "destino"), vía pu_location_key y do_location_key.
#}

select
    location_id,
    borough,
    zone,
    service_zone
from {{ ref('silver_zone_lookup') }}

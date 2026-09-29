{#
    SILVER - catálogo de zonas de taxi.

    Limpieza aplicada:
      - Tipos de datos: LocationID se castea explícitamente a NUMBER (el seed lo trae como
        texto/número según cómo lo infiera dbt).
      - Nombres inconsistentes: columnas renombradas de PascalCase (LocationID, Borough...)
        a snake_case (location_id, borough...) para que todo el proyecto use una sola
        convención de nombres.
      - Formatos inconsistentes: espacios en blanco alrededor de los valores de texto (Borough,
        Zone, service_zone) se recortan con trim().
      - Duplicados: se aplica select distinct como salvaguarda; el catálogo oficial no debería
        traer filas repetidas, pero si el archivo fuente cambiara no queremos duplicar PKs.
      - Registros inválidos: se descartan filas sin location_id, ya que sin esa llave la fila
        no puede usarse como dimensión.
#}

with source as (

    select * from {{ ref('taxi_zone_lookup') }}

),

cleaned as (

    select distinct
        locationid::number(38, 0)  as location_id,
        trim(borough)               as borough,
        trim(zone)                  as zone,
        trim(service_zone)          as service_zone
    from source
    where locationid is not null

)

select * from cleaned

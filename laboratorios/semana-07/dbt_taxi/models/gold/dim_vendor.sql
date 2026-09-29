{#
    GOLD - dim_vendor: catálogo estático de proveedores TPEP, según el Data Dictionary -
    Yellow Taxi Trip Records oficial de la TLC. Se modela como dimensión estática porque
    la TLC no publica este catálogo como archivo descargable; -1 = Unknown cubre cualquier
    código fuera del dominio documentado (ver normalización en silver_trips.sql).
#}

select column1 as vendor_id, column2 as vendor_name
from (
    values
        (1, 'Creative Mobile Technologies, LLC'),
        (2, 'Curb Mobility, LLC'),
        (6, 'Myle Technologies Inc'),
        (7, 'Helix'),
        (-1, 'Unknown')
)

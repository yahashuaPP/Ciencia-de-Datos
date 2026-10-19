-- Regla: fct_trips tiene exactamente una fila por viaje de silver_trips (grano: un viaje).
-- Si algún paso entre Silver y Gold duplicara o perdiera viajes, los conteos no coinciden
-- y el test falla (devuelve una fila).
with s as (select count(*) as n from {{ ref('silver_trips') }}),
     f as (select count(*) as n, count(distinct trip_key) as n_distinct from {{ ref('fct_trips') }})
select s.n as silver_rows, f.n as fct_rows, f.n_distinct as fct_distinct_keys
from s, f
where s.n <> f.n or f.n <> f.n_distinct

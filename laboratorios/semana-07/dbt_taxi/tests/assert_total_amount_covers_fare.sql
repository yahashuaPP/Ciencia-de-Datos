{{ config(severity="warn") }}
-- Regla de negocio TLC: total_amount = tarifa + recargos + propina + peajes. Si los recargos
-- son >= 0, el total nunca es menor que la tarifa base (se tolera 1 centavo por redondeo).
-- Severidad warn: en reembolsos parciales algunos recargos vienen negativos y Silver no los
-- filtra; el test cuenta esos casos para documentarlos en vez de bloquear el build.
select trip_key, fare_amount, total_amount
from {{ ref('silver_trips') }}
where total_amount + 0.01 < fare_amount

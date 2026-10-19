# Laboratorio Integrador I — Pipeline ELT NYC Yellow Taxi (Snowflake + dbt)

Pipeline ELT reproducible para los viajes de NYC Yellow Taxi de **enero–diciembre 2025 y
enero–agosto 2026 (20 meses)**: ingesta automática, carga cruda en Snowflake y
transformación con dbt en una arquitectura **Bronze → Silver → Gold**, hasta un
**esquema estrella** listo para análisis.

Diagramas: [`diagrams/architecture.md`](diagrams/architecture.md) ·
[`diagrams/star_schema.md`](diagrams/star_schema.md) (se renderizan solos al verlos en GitHub).

## Estructura del repositorio

```
infra/setup_snowflake.py   Código de infraestructura: crea rol, warehouse, DB, esquemas,
                            file format, stage y tablas Bronze en Snowflake (idempotente)
infra/snowflake_conn.py    Conexión a Snowflake compartida (lee variables de entorno)
ingestion/run.py           Código de ingesta: descarga los 20 parquet de la TLC y los
                            carga a BRONZE.RAW_YELLOW_TRIPDATA (transaccional, sin duplicados)
infra/run_profile.py       Ejecuta el perfil de calidad y escribe docs/calidad_datos.md
dbt_taxi/                  Proyecto dbt (seeds, modelos Silver y Gold, tests, análisis de calidad)
diagrams/                  Diagrama de arquitectura y diagrama del esquema estrella
docs/                      Resultado del perfil de calidad (lo genera `make quality`)
Dockerfile, docker-compose.yml, Makefile   Infraestructura de ejecución en contenedores
```

## Requisitos previos

- Cuenta de Snowflake (sirve la prueba gratuita de 30 días).
- Docker + Docker Compose **o** Python 3.11 y `make` instalados localmente.
- Conexión a internet (los archivos se descargan de `d37ci6vzurychx.cloudfront.net`, el
  CDN oficial de la NYC TLC).

## 1. Configurar credenciales

```bash
cp .env.example .env
```

Completen `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER` y `SNOWFLAKE_PASSWORD` con los datos de su
cuenta de Snowflake. El resto de variables ya traen valores por defecto razonables
(`TAXI_ROLE`, `TAXI_WH`, `TAXI_DB`).

## 2. Ejecutar todo el pipeline de punta a punta

### Opción A — Docker (recomendada, no requiere instalar nada más)

```bash
docker compose build
docker compose run --rm pipeline
```

Esto corre, en orden, `make setup` → `make ingest` → `make build` (setup de Snowflake,
ingesta de los 20 meses y `dbt build` de Silver + Gold + tests).

Comandos sueltos útiles:

```bash
docker compose run --rm pipeline make setup                                # solo infraestructura
docker compose run --rm pipeline make ingest INGEST_ARGS="--strict"        # ingesta, falla si falta algún mes
docker compose run --rm pipeline make full-refresh                         # reconstruye Silver/Gold desde Bronze
docker compose run --rm pipeline make quality                              # perfil de calidad -> docs/calidad_datos.md
```

### Opción B — Local con Python + make

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)

make pipeline
```

## 3. Qué hace cada etapa

1. **`make setup`** (`infra/setup_snowflake.py`, idempotente): crea el rol de trabajo, el
   warehouse `TAXI_WH` (XSMALL, auto-suspend), la base de datos `TAXI_DB`, los esquemas
   `BRONZE`/`SILVER`/`GOLD`, el file format Parquet, el stage interno y las tablas
   `BRONZE.RAW_YELLOW_TRIPDATA` y `BRONZE.INGESTION_LOG`.
2. **`make ingest`** (`ingestion/run.py`): para cada uno de los 20 meses, descarga el
   parquet oficial de la TLC, lo valida (firma Parquet, tamaño completo), lo sube al stage y
   lo carga en una transacción (DELETE del mes + `COPY INTO` con `INCLUDE_METADATA` +
   verificación de conteo + registro en `INGESTION_LOG`). Si el mes ya está en
   `INGESTION_LOG`, se omite. Al final reconcilia: filas en Bronze == filas registradas en
   el log.
3. **`make build`** (`dbt build` sobre `dbt_taxi/`): carga el seed `taxi_zone_lookup`,
   construye los modelos Silver (limpieza y estandarización) y Gold (esquema estrella), y
   corre las pruebas (`not_null`, `unique`, `relationships`).

## 4. Verificar el resultado en Snowflake

```sql
use database TAXI_DB;
select count(*) from BRONZE.RAW_YELLOW_TRIPDATA;
select count(*) from GOLD.FCT_TRIPS;
select * from GOLD.FCT_TRIPS limit 10;
```

## 5. Capa Silver — limpieza y estandarización

Modelos: `dbt_taxi/models/silver/silver_trips.sql` y `silver_zone_lookup.sql`. Cada decisión
de limpieza (tipos de datos, nulos, duplicados, registros inválidos, nombres/formatos
inconsistentes) está documentada en un comentario al inicio del `.sql` correspondiente y en
`dbt_taxi/models/silver/_silver__models.yml`.

**Evidencia.** Antes de limpiar se perfila Bronze con `dbt_taxi/analyses/data_quality_profile.sql`
(`make quality`). La consulta cuenta cada problema (sin fechas, llegada antes de la recogida,
duplicados, duraciones de más de 24 h, montos negativos, códigos fuera de dominio, etc.) y cuántas
filas llegan a Silver. El resultado queda en [`docs/calidad_datos.md`](docs/calidad_datos.md).

| Problema | ID en el perfil | Acción en Silver |
|---|---|---|
| Viajes sin hora de recogida o llegada | Q01 | Se descartan |
| Llegada anterior a la recogida | Q02 | Se descartan |
| Filas repetidas (misma llave de negocio) | Q03 | Se conserva la primera aparición (orden determinista por archivo y fila) |
| Duración mayor a 24 h | Q04 | Se descartan (error del taxímetro) |
| Distancia, tarifa o total negativos | Q05–Q07 | Se descartan (reembolsos o errores de captura) |
| Recogida fuera de 2025-01 a 2026-08 | Q08 | Se descartan |
| `passenger_count` nulo | Q09 | Se conserva NULL (dato desconocido, no se inventa) |
| Códigos de vendor, tarifa, pago o zona fuera de dominio | Q11–Q14 | Se normalizan al valor "Unknown" del dominio |
| `store_and_fwd_flag` y recargos nulos | Q15–Q16 | `'N'` y 0 respectivamente (valor por defecto del origen) |
| Pasajeros = 0 y distancias > 100 millas | Q10, Q17 | Se conservan y se documentan como limitación (no hay regla segura para corregirlos) |

## 6. Capa Gold — esquema estrella

**Grano de `fct_trips`**: un registro por viaje individual de yellow taxi.

| Columna | Tipo | Descripción |
|---|---|---|
| `trip_key` | PK (hash) | Identificador único del viaje |
| `pickup_date_key` / `dropoff_date_key` | FK → `dim_date` | Fecha de inicio/fin del viaje |
| `pickup_hour_key` / `dropoff_hour_key` | FK → `dim_time` | Hora del día de inicio/fin |
| `pu_location_key` / `do_location_key` | FK → `dim_location` | Zona de recogida/destino |
| `vendor_key` | FK → `dim_vendor` | Proveedor TPEP |
| `rate_code_key` | FK → `dim_rate_code` | Tarifa aplicada |
| `payment_type_key` | FK → `dim_payment_type` | Medio de pago |
| `passenger_count`, `trip_distance_miles`, `trip_duration_minutes`, `fare_amount`, `extra_amount`, `mta_tax_amount`, `tip_amount`, `tolls_amount`, `improvement_surcharge_amount`, `congestion_surcharge_amount`, `airport_fee_amount`, `cbd_congestion_fee_amount`, `total_amount` | métricas | Atributos y métricas del viaje |

Dimensiones: `dim_date`, `dim_time` (grano: hora del día), `dim_location` (265 zonas de la
TLC, usada en rol de recogida y de destino), `dim_vendor`, `dim_rate_code`, `dim_payment_type`.
`dim_date` cubre el rango del laboratorio más un día (hasta 2026-09-01), porque un viaje que
empieza el 31 de agosto puede terminar después de medianoche.
Diagrama completo: [`diagrams/star_schema.md`](diagrams/star_schema.md).

## 7. Pruebas de dbt

`dbt_taxi/models/silver/_silver__models.yml` y `dbt_taxi/models/gold/_gold__models.yml`
incluyen `not_null` y `unique` en las PK de cada tabla, y `relationships` en las 9 columnas
FK de `fct_trips` hacia sus 6 dimensiones. Además validan las reglas de la limpieza:

- la llegada nunca es anterior a la recogida y la duración está entre 0 y 1 440 minutos;
- distancia, tarifa e importe total son >= 0;
- vendor, tarifa, medio de pago y `store_and_fwd_flag` solo toman valores del dominio TLC;
- las zonas están entre 1 y 265 y la recogida cae dentro del rango del laboratorio;
- `tests/assert_fct_trips_preserves_grain.sql`: `fct_trips` tiene exactamente una fila por viaje
  de Silver (ningún paso duplica ni pierde viajes);
- `tests/assert_total_amount_covers_fare.sql` (warn): cuenta los viajes cuyo total es menor que la
  tarifa base.

Se corren con `dbt build` o `dbt test`.

## 8. Re-ejecución sin duplicados ni inconsistencias

- **Bronze**: `ingestion/run.py` carga cada mes dentro de una única transacción
  (DELETE + COPY INTO + verificación de conteo + registro en el log) con `ROLLBACK`
  automático ante cualquier error, y omite los meses que `INGESTION_LOG` ya marca como
  `LOADED`. Volver a correr `make ingest` no duplica filas.
- **Silver/Gold**: todos los modelos están materializados como **tablas**
  (`+materialized: table` en `dbt_project.yml`), es decir, cada `dbt build` las
  **reconstruye por completo** a partir de Bronze/Silver. Correr la tubería de nuevo nunca
  genera duplicados ni inconsistencias en estas capas.

## 9. Seguridad

`.env` (credenciales de Snowflake) está en `.gitignore` y `.dockerignore`: nunca se versiona ni
entra a la imagen. Solo se sube `.env.example`, sin valores.

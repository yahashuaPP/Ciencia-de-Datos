# Diagrama de arquitectura

```mermaid
flowchart TD
    TLC["NYC TLC\nyellow_tripdata_YYYY-MM.parquet\n(20 archivos: 2025-01 .. 2026-08)"]

    subgraph LOCAL["Contenedor / máquina local"]
        DL["ingestion/run.py\ndescarga + valida (firma Parquet, tamaño)"]
    end

    subgraph SF["Snowflake"]
        STAGE["Stage interno\nBRONZE.RAW_STAGE"]

        subgraph BRONZE["Esquema BRONZE"]
            RAW["RAW_YELLOW_TRIPDATA\n(COPY INTO + metadata de carga)"]
            LOG["INGESTION_LOG\n(1 fila por mes cargado)"]
        end

        subgraph SILVER["Esquema SILVER (dbt)"]
            ST["silver_trips"]
            SZ["silver_zone_lookup"]
        end

        subgraph GOLD["Esquema GOLD (dbt) — esquema estrella"]
            FCT["fct_trips"]
            DIMS["dim_date · dim_time · dim_location\ndim_vendor · dim_rate_code · dim_payment_type"]
        end
    end

    SEED["dbt seed\ntaxi_zone_lookup.csv"]

    TLC -->|HTTPS| DL
    DL -->|PUT| STAGE
    STAGE -->|COPY INTO\nMATCH_BY_COLUMN_NAME, INCLUDE_METADATA| RAW
    DL -->|registra el mes cargado| LOG

    SEED -->|dbt seed| BRONZE

    RAW -->|dbt run: limpieza, tipos,\ndedup, nulos, inválidos| ST
    BRONZE -->|dbt run| SZ
    ST --> FCT
    SZ --> DIMS
    ST --> DIMS
    FCT -->|FKs| DIMS
```

**Infraestructura (`infra/setup_snowflake.py`)**: crea de forma idempotente el rol de
trabajo, el warehouse, la base de datos, los tres esquemas (BRONZE/SILVER/GOLD), el file
format Parquet, el stage interno y las tablas Bronze.

**Ingesta (`ingestion/run.py`)**: por cada uno de los 20 meses, descarga el parquet, lo
sube al stage y lo carga a `BRONZE.RAW_YELLOW_TRIPDATA` en una transacción (DELETE del mes +
COPY INTO + verificación de conteo + registro en `INGESTION_LOG`). Si algo falla, hace
`ROLLBACK`: nunca quedan cargas a medias ni filas duplicadas.

**Transformación (dbt, `dbt_taxi/`)**: `dbt build` corre, en orden de dependencias, el seed
(`taxi_zone_lookup`), los modelos Silver y los modelos Gold, y al final las pruebas
(`not_null`, `unique`, `relationships`). Todos los modelos Silver/Gold están materializados
como tablas, por lo que cada corrida los reconstruye por completo desde Bronze/Silver: correr
la tubería de nuevo nunca genera duplicados ni inconsistencias en estas capas.

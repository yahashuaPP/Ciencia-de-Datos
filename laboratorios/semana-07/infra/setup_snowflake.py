"""Crea de forma idempotente la infraestructura de Snowflake del laboratorio.

Orden (todo con IF NOT EXISTS, se puede correr N veces):
  Fase admin (solo si aún no existe la infraestructura, rol SNOWFLAKE_SETUP_ROLE):
    1. ROLE  2. GRANT del rol al usuario  3. WAREHOUSE  4. DATABASE  5. GRANTs
  Fase objetos (con el rol de trabajo, mínimo privilegio; es dueño de lo que crea):
    6. SCHEMAS BRONZE / SILVER / GOLD  7. FILE FORMAT  8. STAGE interno
    9. Tabla BRONZE.RAW_YELLOW_TRIPDATA  10. Tabla BRONZE.INGESTION_LOG

Uso: python -m infra.setup_snowflake
"""
from __future__ import annotations

import logging
import sys

from snowflake.connector import errors as sf_errors

from infra.snowflake_conn import env, get_connection, ident

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
log = logging.getLogger("setup")

SCHEMAS = ("BRONZE", "SILVER", "GOLD")

# Bronze = datos de la fuente sin transformar (nombres originales de TLC) + metadata de carga.
# El emparejamiento con el parquet es por nombre (case-insensitive): Airport_fee / airport_fee ok.
BRONZE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS BRONZE.RAW_YELLOW_TRIPDATA (
    VENDORID               NUMBER(38,0),
    TPEP_PICKUP_DATETIME   TIMESTAMP_NTZ,
    TPEP_DROPOFF_DATETIME  TIMESTAMP_NTZ,
    PASSENGER_COUNT        NUMBER(38,0),
    TRIP_DISTANCE          FLOAT,
    RATECODEID             NUMBER(38,0),
    STORE_AND_FWD_FLAG     VARCHAR,
    PULOCATIONID           NUMBER(38,0),
    DOLOCATIONID           NUMBER(38,0),
    PAYMENT_TYPE           NUMBER(38,0),
    FARE_AMOUNT            FLOAT,
    EXTRA                  FLOAT,
    MTA_TAX                FLOAT,
    TIP_AMOUNT             FLOAT,
    TOLLS_AMOUNT           FLOAT,
    IMPROVEMENT_SURCHARGE  FLOAT,
    TOTAL_AMOUNT           FLOAT,
    CONGESTION_SURCHARGE   FLOAT,
    AIRPORT_FEE            FLOAT,
    CBD_CONGESTION_FEE     FLOAT,
    -- metadata de carga (linaje)
    _SOURCE_FILE           VARCHAR       COMMENT 'Ruta del archivo en el stage (METADATA$FILENAME); incluye el periodo YYYY-MM',
    _SOURCE_ROW_NUMBER     NUMBER(38,0)  COMMENT 'Fila dentro del archivo de origen',
    _LOADED_AT             TIMESTAMP_LTZ COMMENT 'Fecha/hora de carga a Bronze'
)
COMMENT = 'NYC Yellow Taxi - crudo desde TLC (Bronze)'
"""

# Control de idempotencia: un registro LOADED por mes.
# (Las PK de Snowflake son informativas; la unicidad la garantiza run.py con DELETE+INSERT transaccional.)
LOG_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS BRONZE.INGESTION_LOG (
    SOURCE_PERIOD    DATE          NOT NULL,
    SOURCE_FILE      VARCHAR       NOT NULL,
    SOURCE_URL       VARCHAR,
    FILE_SIZE_BYTES  NUMBER(38,0),
    ROWS_LOADED      NUMBER(38,0),
    STATUS           VARCHAR       NOT NULL,
    LOADED_AT        TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_INGESTION_LOG PRIMARY KEY (SOURCE_PERIOD)
)
COMMENT = 'Un registro por mes cargado a BRONZE.RAW_YELLOW_TRIPDATA'
"""


def run_statements(cur, statements: list[str]) -> None:
    for sql in statements:
        first_line = " ".join(sql.strip().split())[:100]
        log.info("SQL> %s", first_line)
        cur.execute(sql)


def bootstrap_done(role: str, database: str) -> bool:
    """True si el rol de trabajo ya existe y ve la tabla Bronze: no hace falta rol admin."""
    try:
        conn = get_connection(role=role)
    except sf_errors.Error:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(f"SHOW TABLES LIKE 'RAW_YELLOW_TRIPDATA' IN SCHEMA {database}.BRONZE")
            return len(cur.fetchall()) > 0
    except sf_errors.Error:
        return False
    finally:
        conn.close()


def run_admin_phase(admin_role: str, role: str, warehouse: str, database: str) -> None:
    log.info("Fase admin con el rol %s (solo la primera vez)", admin_role)
    conn = get_connection(role=admin_role)
    try:
        with conn.cursor() as cur:
            user = cur.execute("SELECT CURRENT_USER()").fetchone()[0].replace('"', '""')
            run_statements(
                cur,
                [
                    f"CREATE ROLE IF NOT EXISTS {role} COMMENT = 'Rol de trabajo del pipeline NYC Taxi'",
                    f'GRANT ROLE {role} TO USER "{user}"',
                    f"""CREATE WAREHOUSE IF NOT EXISTS {warehouse}
                        WITH WAREHOUSE_SIZE = 'XSMALL' AUTO_SUSPEND = 60 AUTO_RESUME = TRUE
                        INITIALLY_SUSPENDED = TRUE""",
                    f"CREATE DATABASE IF NOT EXISTS {database}",
                    f"GRANT USAGE, OPERATE ON WAREHOUSE {warehouse} TO ROLE {role}",
                    f"GRANT ALL PRIVILEGES ON DATABASE {database} TO ROLE {role}",
                ],
            )
    finally:
        conn.close()


def run_objects_phase(role: str, database: str) -> None:
    log.info("Fase objetos con el rol %s", role)
    conn = get_connection(role=role)
    try:
        with conn.cursor() as cur:
            run_statements(cur, [f"USE DATABASE {database}"])
            run_statements(cur, [f"CREATE SCHEMA IF NOT EXISTS {s}" for s in SCHEMAS])
            run_statements(
                cur,
                [
                    "USE SCHEMA BRONZE",
                    "CREATE FILE FORMAT IF NOT EXISTS BRONZE.PARQUET_FF TYPE = PARQUET USE_LOGICAL_TYPE = TRUE",
                    """CREATE STAGE IF NOT EXISTS BRONZE.RAW_STAGE
                        FILE_FORMAT = (FORMAT_NAME = 'BRONZE.PARQUET_FF')
                        ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
                        COMMENT = 'Zona de aterrizaje temporal de los parquet de TLC'""",
                    BRONZE_TABLE_DDL,
                    LOG_TABLE_DDL,
                ],
            )
            for schema in SCHEMAS:
                cur.execute(f"SHOW TABLES IN SCHEMA {database}.{schema}")
                names = [row[1] for row in cur.fetchall()]
                log.info("Esquema %s.%s OK. Tablas: %s", database, schema, names or "(vacío)")
    finally:
        conn.close()


def main() -> int:
    role = ident(env("SNOWFLAKE_ROLE", "TAXI_ROLE"))
    warehouse = ident(env("SNOWFLAKE_WAREHOUSE", "TAXI_WH"))
    database = ident(env("SNOWFLAKE_DATABASE", "TAXI_DB"))
    admin_role = ident(env("SNOWFLAKE_SETUP_ROLE", "ACCOUNTADMIN"))

    if bootstrap_done(role, database):
        log.info("Infraestructura base ya existe: se omite la fase admin (%s).", admin_role)
    else:
        run_admin_phase(admin_role, role, warehouse, database)
    run_objects_phase(role, database)
    log.info("Setup completo.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - queremos traza completa y exit code != 0 para que make falle
        log.exception("Setup falló")
        sys.exit(1)
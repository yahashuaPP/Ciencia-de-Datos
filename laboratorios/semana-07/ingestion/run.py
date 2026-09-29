"""Ingesta mensual de NYC Yellow Taxi (TLC) -> Snowflake BRONZE.

Por cada mes del rango:
  1. Si BRONZE.INGESTION_LOG ya lo tiene como LOADED -> se omite (idempotente).
  2. Descarga el parquet a un directorio temporal (reintentos con backoff).
     Si TLC aún no lo publica (403/404) -> MISSING, se continúa con los demás.
  3. Valida el archivo (tamaño completo y firma Parquet PAR1).
  4. PUT al stage interno y, en UNA transacción: DELETE del mes + COPY INTO + verificación
     de conteo + registro en el log. Cualquier error -> ROLLBACK (no quedan duplicados ni cargas a medias).
  5. Borra el archivo local y los archivos del stage.
Al final reconcilia: filas en Bronze == suma de filas del log.

Uso:
  python -m ingestion.run                          # 2025-01 .. 2026-08 (20 meses)
  python -m ingestion.run --start 2025-03 --end 2025-03 --force   # recarga un mes
  python -m ingestion.run --strict                 # exit 2 si algún mes no está publicado
"""
from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from datetime import date
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from snowflake.connector import DictCursor
from snowflake.connector import errors as sf_errors
from urllib3.util.retry import Retry

from infra.snowflake_conn import env, get_connection, ident

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
log = logging.getLogger("ingestion")

BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"
TABLE = "RAW_YELLOW_TRIPDATA"
LOG_TABLE = "INGESTION_LOG"
STAGE = "RAW_STAGE"
FILE_FORMAT = "PARQUET_FF"
PARQUET_MAGIC = b"PAR1"

LOADED, SKIPPED, MISSING, FAILED = "LOADED", "SKIPPED", "MISSING", "FAILED"


class FileNotPublished(Exception):
    """TLC aún no publica el archivo (CloudFront responde 403/404 para llaves inexistentes)."""


# ----------------------------- utilidades -----------------------------
def parse_period(text: str) -> date:
    try:
        year, month = text.split("-")
        return date(int(year), int(month), 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Periodo inválido '{text}': usa YYYY-MM") from exc


def month_range(start: date, end: date) -> list[date]:
    months, current = [], start
    while current <= end:
        months.append(current)
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return months


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingesta NYC Yellow Taxi -> Snowflake BRONZE")
    parser.add_argument("--start", type=parse_period, default=parse_period("2025-01"))
    parser.add_argument("--end", type=parse_period, default=parse_period("2026-08"))
    parser.add_argument("--force", action="store_true", help="Recarga meses aunque ya estén en INGESTION_LOG")
    parser.add_argument("--strict", action="store_true", help="Exit 2 si algún mes aún no está publicado")
    args = parser.parse_args(argv)
    if args.start > args.end:
        parser.error("--start no puede ser posterior a --end")
    return args


def _lower(row: dict | None) -> dict:
    return {k.lower(): v for k, v in (row or {}).items()}


def build_session() -> requests.Session:
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "taxi-elt-lab/1.0"
    return session


# ----------------------------- descarga -----------------------------
def download(session: requests.Session, url: str, dest: Path) -> int:
    part = dest.with_name(dest.name + ".part")
    with session.get(url, stream=True, timeout=(15, 120)) as resp:
        if resp.status_code in (403, 404):
            raise FileNotPublished(url)
        resp.raise_for_status()
        expected = int(resp.headers.get("Content-Length") or 0)
        encoded = bool(resp.headers.get("Content-Encoding"))
        written = 0
        with part.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                written += len(chunk)

    if written < 12:
        raise IOError(f"Descarga vacía o truncada ({written} bytes): {url}")
    if expected and not encoded and written != expected:
        raise IOError(f"Descarga incompleta: {written} de {expected} bytes ({url})")
    with part.open("rb") as fh:
        head = fh.read(4)
        fh.seek(-4, 2)
        tail = fh.read(4)
    if head != PARQUET_MAGIC or tail != PARQUET_MAGIC:
        raise IOError(f"El archivo no es un Parquet válido: {url}")
    part.replace(dest)
    return written


# ----------------------------- Snowflake -----------------------------
def already_loaded(cur, period: date) -> bool:
    cur.execute(f"SELECT 1 FROM {LOG_TABLE} WHERE SOURCE_PERIOD = %s AND STATUS = 'LOADED'", (period,))
    return cur.fetchone() is not None


def _rollback(cur) -> None:
    try:
        cur.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 - la conexión pudo haberse caído; ya reportamos el error original
        log.warning("No se pudo ejecutar ROLLBACK (¿sesión cerrada?)")


def load_month(conn, period: date, url: str, local_file: Path, size_bytes: int) -> int:
    file_name = local_file.name
    stage_ref = f"@{STAGE}/yellow/{period:%Y-%m}/"
    cur = conn.cursor(DictCursor)
    try:
        # PUT no es transaccional; OVERWRITE=TRUE lo hace repetible.
        cur.execute(f"PUT 'file://{local_file.as_posix()}' {stage_ref} AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
        put = _lower(cur.fetchone())
        if put.get("status") not in ("UPLOADED", "SKIPPED"):
            raise RuntimeError(f"PUT falló: {put}")

        cur.execute("BEGIN")
        try:
            # Borra cualquier resto del mismo archivo (recarga con --force o carga previa incompleta).
            cur.execute(f"DELETE FROM {TABLE} WHERE ENDSWITH(_SOURCE_FILE, '{file_name}')")
            cur.execute(
                f"""
                COPY INTO {TABLE}
                FROM {stage_ref}
                FILES = ('{file_name}')
                FILE_FORMAT = (FORMAT_NAME = '{FILE_FORMAT}')
                MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
                INCLUDE_METADATA = (
                    _SOURCE_FILE = METADATA$FILENAME,
                    _SOURCE_ROW_NUMBER = METADATA$FILE_ROW_NUMBER,
                    _LOADED_AT = METADATA$START_SCAN_TIME
                )
                ON_ERROR = ABORT_STATEMENT
                FORCE = TRUE
                """
            )
            results = [_lower(r) for r in cur.fetchall()]
            rows_loaded = sum(int(r.get("rows_loaded") or 0) for r in results)
            if rows_loaded == 0 or any(r.get("status") != "LOADED" for r in results):
                raise RuntimeError(f"COPY INTO no cargó filas válidas: {results}")

            cur.execute(f"SELECT COUNT(*) AS N FROM {TABLE} WHERE ENDSWITH(_SOURCE_FILE, '{file_name}')")
            in_table = int(_lower(cur.fetchone())["n"])
            if in_table != rows_loaded:
                raise RuntimeError(f"Conteo inconsistente: COPY={rows_loaded}, tabla={in_table}")

            cur.execute(f"DELETE FROM {LOG_TABLE} WHERE SOURCE_PERIOD = %s", (period,))
            cur.execute(
                f"""INSERT INTO {LOG_TABLE}
                    (SOURCE_PERIOD, SOURCE_FILE, SOURCE_URL, FILE_SIZE_BYTES, ROWS_LOADED, STATUS)
                    VALUES (%s, %s, %s, %s, %s, 'LOADED')""",
                (period, file_name, url, size_bytes, rows_loaded),
            )
            cur.execute("COMMIT")
        except Exception:
            _rollback(cur)
            raise
        return rows_loaded
    finally:
        try:  # limpieza del stage (cobra almacenamiento); best effort
            cur.execute(f"REMOVE {stage_ref}")
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudo limpiar %s: %s", stage_ref, exc)
        cur.close()


def reconcile(cur) -> bool:
    """Invariante anti-duplicados: filas en Bronze == filas registradas en el log."""
    cur.execute(
        f"""SELECT (SELECT COUNT(*) FROM {TABLE}) AS BRONZE_ROWS,
                   (SELECT COALESCE(SUM(ROWS_LOADED), 0) FROM {LOG_TABLE} WHERE STATUS = 'LOADED') AS LOGGED_ROWS"""
    )
    row = _lower(cur.fetchone())
    bronze_rows, logged_rows = int(row["bronze_rows"]), int(row["logged_rows"])
    if bronze_rows != logged_rows:
        log.error(
            "Inconsistencia: BRONZE tiene %s filas y el log suma %s. "
            "Si vienes de una carga anterior sin log: DROP TABLE BRONZE.RAW_YELLOW_TRIPDATA y reejecuta.",
            f"{bronze_rows:,}",
            f"{logged_rows:,}",
        )
        return False
    log.info("Reconciliación OK: %s filas en BRONZE == log.", f"{bronze_rows:,}")
    return True


# ----------------------------- main -----------------------------
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    periods = month_range(args.start, args.end)
    conn = get_connection(
        role=ident(env("SNOWFLAKE_ROLE", "TAXI_ROLE")),
        warehouse=ident(env("SNOWFLAKE_WAREHOUSE", "TAXI_WH")),
        database=ident(env("SNOWFLAKE_DATABASE", "TAXI_DB")),
        schema="BRONZE",
    )
    session = build_session()
    results: dict[str, str] = {}
    try:
        cur = conn.cursor(DictCursor)
        try:
            cur.execute(f"SELECT 1 FROM {LOG_TABLE} LIMIT 1")
        except sf_errors.ProgrammingError:
            log.error("BRONZE.%s no existe. Ejecuta primero `make setup`.", LOG_TABLE)
            return 1

        log.info("Procesando %d meses: %s -> %s", len(periods), f"{periods[0]:%Y-%m}", f"{periods[-1]:%Y-%m}")
        with tempfile.TemporaryDirectory(prefix="taxi_") as tmp:
            for period in periods:
                label = f"{period:%Y-%m}"
                file_name = f"yellow_tripdata_{label}.parquet"
                url = f"{BASE_URL}/{file_name}"
                local = Path(tmp) / file_name
                try:
                    if not args.force and already_loaded(cur, period):
                        log.info("[%s] ya cargado -> se omite", label)
                        results[label] = SKIPPED
                        continue
                    size = download(session, url, local)
                    rows = load_month(conn, period, url, local, size)
                    log.info("[%s] cargado: %s filas (%.1f MB)", label, f"{rows:,}", size / 1e6)
                    results[label] = LOADED
                except FileNotPublished:
                    log.warning("[%s] TLC aún no publica %s", label, file_name)
                    results[label] = MISSING
                except Exception:  # noqa: BLE001 - seguimos con los demás meses y fallamos al final
                    log.exception("[%s] falló la carga (transacción revertida)", label)
                    results[label] = FAILED
                finally:
                    local.unlink(missing_ok=True)  # el tmp nunca acumula más de un archivo

        counts = {s: sum(v == s for v in results.values()) for s in (LOADED, SKIPPED, MISSING, FAILED)}
        log.info("Resumen: %s", counts)
        missing = [m for m, s in results.items() if s == MISSING]
        if missing:
            log.warning("Meses no publicados: %s (usa --strict para tratarlos como error)", ", ".join(missing))

        consistent = reconcile(cur)
        if counts[FAILED] or not consistent:
            return 1
        if args.strict and counts[MISSING]:
            return 2
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

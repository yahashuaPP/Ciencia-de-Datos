"""Ejecuta el perfil de calidad compilado por dbt y guarda el resultado en docs/calidad_datos.md.

Uso (lo llama `make quality` después de `dbt compile`):
  python -m infra.run_profile
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from infra.snowflake_conn import env, get_connection, ident

COMPILED = Path("dbt_taxi/target/compiled/dbt_taxi/analyses/data_quality_profile.sql")
OUTPUT = Path("docs/calidad_datos.md")


def fmt(value) -> str:
    if isinstance(value, int):
        return f"{value:,}".replace(",", " ")
    return "" if value is None else str(value)


def main() -> int:
    if not COMPILED.exists():
        print(f"No existe {COMPILED}. Corre primero: dbt compile --select data_quality_profile")
        return 1
    conn = get_connection(
        role=ident(env("SNOWFLAKE_ROLE", "TAXI_ROLE")),
        warehouse=ident(env("SNOWFLAKE_WAREHOUSE", "TAXI_WH")),
        database=ident(env("SNOWFLAKE_DATABASE", "TAXI_DB")),
    )
    try:
        with conn.cursor() as cur:
            cur.execute(COMPILED.read_text(encoding="utf-8"))
            rows = cur.fetchall()
    finally:
        conn.close()

    lines = [
        "# Perfil de calidad de datos (Bronze)",
        "",
        f"Generado con `make quality` el {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC "
        "sobre `BRONZE.RAW_YELLOW_TRIPDATA`. Consulta: `dbt_taxi/analyses/data_quality_profile.sql`.",
        "",
        "| ID | Dimensión | Problema | Afectados | Total | % |",
        "|---|---|---|---:|---:|---:|",
    ]
    lines += [f"| {r[0]} | {r[1]} | {r[2]} | {fmt(r[3])} | {fmt(r[4])} | {fmt(r[5])} |" for r in rows]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nGuardado en {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

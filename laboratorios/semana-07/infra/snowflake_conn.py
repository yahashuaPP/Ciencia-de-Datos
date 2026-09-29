"""Conexión a Snowflake compartida por setup e ingesta. Solo lee variables de entorno."""
from __future__ import annotations

import os
import re

import snowflake.connector
from dotenv import load_dotenv

# En local lee .env; en Docker las variables ya vienen de env_file y no se pisan.
load_dotenv(override=False)

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or not value.strip():
        raise RuntimeError(
            f"Falta la variable de entorno {name}. Copia .env.example a .env y complétala."
        )
    return value.strip()


def ident(value: str) -> str:
    """Valida un identificador de Snowflake (los DDL no admiten parámetros ligados)."""
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Identificador de Snowflake inválido: {value!r}")
    return value.upper()


def get_connection(
    role: str,
    warehouse: str | None = None,
    database: str | None = None,
    schema: str | None = None,
) -> snowflake.connector.SnowflakeConnection:
    params: dict[str, object] = {
        "account": env("SNOWFLAKE_ACCOUNT"),
        "user": env("SNOWFLAKE_USER"),
        "password": env("SNOWFLAKE_PASSWORD"),
        "role": role,
        "client_session_keep_alive": True,
    }
    if warehouse:
        params["warehouse"] = warehouse
    if database:
        params["database"] = database
    if schema:
        params["schema"] = schema
    return snowflake.connector.connect(**params)

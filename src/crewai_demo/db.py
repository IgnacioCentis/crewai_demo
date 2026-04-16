from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class DbSettings:
    database_url: str


def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


def _get_first_env(*names: str) -> str | None:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return None


def get_db_settings() -> DbSettings:
    """
    Primary config is DATABASE_URL.
    Example (MySQL):
      mysql+pymysql://user:pass@host:3306/chocolart_n8n
    """
    # Make CLI usage convenient by loading .env automatically if present.
    try:
        from dotenv import load_dotenv

        root = Path(__file__).resolve().parents[2]
        load_dotenv(root / ".env")
    except Exception:
        pass

    url = os.getenv("DATABASE_URL")
    if url:
        return DbSettings(database_url=url)

    # Fallback (explicit vars) compatible with common env conventions.
    # Supported:
    # - DB_CONNECTION=mysql
    # - DB_HOST, DB_PORT, DB_DATABASE, DB_USERNAME, DB_PASSWORD
    # Also accepts DB_NAME / DB_USER as aliases.
    connection = (os.getenv("DB_CONNECTION") or "mysql").strip().lower()
    if connection in {"mysql", "mariadb"}:
        driver = os.getenv("DB_DRIVER", "mysql+pymysql")
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "3306")
        name = _require_env("DB_DATABASE") if os.getenv("DB_DATABASE") else _require_env("DB_NAME")
        user = _get_first_env("DB_USERNAME", "DB_USER") or _require_env("DB_USERNAME")
        password = _require_env("DB_PASSWORD")
        return DbSettings(database_url=f"{driver}://{user}:{password}@{host}:{port}/{name}")

    driver = os.getenv("DB_DRIVER", connection)
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "")
    name = _get_first_env("DB_DATABASE", "DB_NAME") or _require_env("DB_NAME")
    user = _get_first_env("DB_USERNAME", "DB_USER") or _require_env("DB_USER")
    password = _require_env("DB_PASSWORD")
    auth = f"{user}:{password}@"
    port_part = f":{port}" if port else ""
    return DbSettings(database_url=f"{driver}://{auth}{host}{port_part}/{name}")


_ENGINE: Engine | None = None


def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        settings = get_db_settings()
        _ENGINE = create_engine(settings.database_url, pool_pre_ping=True, future=True)
    return _ENGINE


def check_db_connection() -> dict[str, Any]:
    """
    Returns a small health payload. Raises on failure.
    """
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}


def cli_check() -> None:
    """
    CLI entrypoint: `uv run db_check` or `python -m crewai_demo.db`
    """
    try:
        check_db_connection()
        print("DB OK")
    except Exception as e:
        print(f"DB ERROR: {e}")
        raise


if __name__ == "__main__":
    cli_check()

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from .config import settings


engine: Engine = create_engine(settings.database_url, pool_pre_ping=True)


def connection() -> Iterator[Connection]:
    with engine.begin() as conn:
        yield conn


def ping() -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1")).scalar_one() == 1

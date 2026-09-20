"""PostgreSQL connections and schema setup.

Kept deliberately small: one function to open a connection from the settings,
one to apply the SQL files in `sql/`. No ORM - the pipeline's work is expressed
in SQL, and an ORM would hide exactly the part we have to explain.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg

from deng.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _find_sql_dir() -> Path:
    """Locate the `sql/` directory in both the repo and the container image.

    Installed into site-packages there is no repository above the package, so a
    purely package-relative path would resolve into the interpreter's lib
    directory. Order: explicit override, then the working directory (the repo
    root locally, `/app` in the image), then the repo layout for an editable
    install.
    """
    override = os.environ.get("DENG_SQL_DIR")
    if override:
        return Path(override)
    cwd_candidate = Path.cwd() / "sql"
    if cwd_candidate.is_dir():
        return cwd_candidate
    return Path(__file__).resolve().parents[3] / "sql"


SQL_DIR = _find_sql_dir()


@contextmanager
def connect(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    """Open a connection to PostgreSQL and close it afterwards.

    Args:
        settings: Optional settings override; the environment is used by default.

    Yields:
        An open psycopg connection. The caller controls transactions; psycopg
        commits on a clean exit of the connection context and rolls back on error.
    """
    settings = settings or get_settings()
    with psycopg.connect(settings.postgres_dsn) as connection:
        yield connection


def apply_sql_files(connection: psycopg.Connection, directory: Path | None = None) -> list[str]:
    """Execute every `.sql` file in `directory` in file-name order.

    The DDL is written to be idempotent (`CREATE ... IF NOT EXISTS`), so applying
    it repeatedly is safe. That is what allows `make up` to bring a fresh or an
    existing database to the same state without a migration tool - which would
    be over-engineering at this size, but is the natural next step if the schema
    starts changing after data exists.

    Args:
        connection: An open connection.
        directory: Folder to scan recursively; defaults to the repository's `sql/`.

    Returns:
        The names of the files that were applied, in order.
    """
    directory = directory or _find_sql_dir() / "raw"
    files = sorted(p for p in directory.rglob("*.sql"))
    applied: list[str] = []
    with connection.cursor() as cursor:
        for path in files:
            logger.info("applying %s", path.name)
            cursor.execute(path.read_text())
            applied.append(path.name)
    connection.commit()
    return applied

"""Data access for notes. The API only talks to the NotesRepo interface,
so tests can swap Postgres for an in-memory fake."""

from datetime import datetime
from typing import Protocol

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel


class Note(BaseModel):
    id: int
    text: str
    created_at: datetime


class NotesRepo(Protocol):
    def list(self, limit: int = 100) -> list[Note]: ...
    def create(self, text: str) -> Note: ...
    def delete(self, note_id: int) -> bool: ...
    def ping(self) -> bool: ...
    def close(self) -> None: ...


SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id          BIGSERIAL PRIMARY KEY,
    text        VARCHAR(500) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class PostgresNotesRepo:
    """Postgres-backed repo. The connection string comes from the
    DATABASE_URL env var (a Container Apps secret in the cloud)."""

    def __init__(self, conninfo: str) -> None:
        self.pool = ConnectionPool(
            conninfo,
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"row_factory": dict_row},
        )

    def open(self, timeout: float = 30.0) -> None:
        # Fails fast if the database is unreachable; the platform restarts us.
        self.pool.open(wait=True, timeout=timeout)
        with self.pool.connection() as conn:
            conn.execute(SCHEMA)

    def list(self, limit: int = 100) -> list[Note]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, text, created_at FROM notes ORDER BY id DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [Note(**r) for r in rows]

    def create(self, text: str) -> Note:
        with self.pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO notes (text) VALUES (%s) RETURNING id, text, created_at",
                (text,),
            ).fetchone()
        return Note(**row)

    def delete(self, note_id: int) -> bool:
        with self.pool.connection() as conn:
            cur = conn.execute("DELETE FROM notes WHERE id = %s", (note_id,))
            return cur.rowcount > 0

    def ping(self) -> bool:
        try:
            with self.pool.connection(timeout=2) as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def close(self) -> None:
        self.pool.close()

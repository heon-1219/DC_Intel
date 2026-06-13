from contextlib import asynccontextmanager

import aiosqlite

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA foreign_keys=ON",
)


@asynccontextmanager
async def connect(sqlite_path: str):
    """Yield an aiosqlite connection with the canonical pragmas applied (schema.md §1.2)."""
    con = await aiosqlite.connect(sqlite_path)
    try:
        for pragma in PRAGMAS:
            await con.execute(pragma)
        con.row_factory = aiosqlite.Row
        yield con
    finally:
        await con.close()

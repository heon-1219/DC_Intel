import pytest
from app.db.connection import connect


@pytest.mark.asyncio
async def test_pragmas_applied(tmp_path):
    db = tmp_path / "t.db"
    async with connect(str(db)) as con:
        mode = (await (await con.execute("PRAGMA journal_mode")).fetchone())[0]
        fk = (await (await con.execute("PRAGMA foreign_keys")).fetchone())[0]
    assert mode.lower() == "wal"
    assert fk == 1

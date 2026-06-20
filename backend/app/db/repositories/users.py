"""users repository (schema.md / backend-design AUTH §6-7). Email is stored AND looked up
lowercased (the unique index is COLLATE NOCASE; duplicate registration -> IntegrityError, which the
router maps to 409). Rows include password_hash for login verification — never serialize it raw."""

_COLS = "id, email, password_hash, preferred_language, created_at"


async def create_user(con, email: str, password_hash: str, language: str):
    cur = await con.execute(
        "INSERT INTO users (email, password_hash, preferred_language) VALUES (?,?,?)",
        (email.lower(), password_hash, language))
    await con.commit()
    return await get_by_id(con, cur.lastrowid)


async def get_by_email(con, email: str):
    cur = await con.execute(f"SELECT {_COLS} FROM users WHERE email=?", (email.lower(),))
    return await cur.fetchone()


async def get_by_id(con, user_id: int):
    cur = await con.execute(f"SELECT {_COLS} FROM users WHERE id=?", (user_id,))
    return await cur.fetchone()

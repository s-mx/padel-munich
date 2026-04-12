"""
One-time script to seed the members table from all current group members.

Requires a Telegram *user* account — the Bot API cannot list group members.
Get API_ID and API_HASH from https://my.telegram.org (free, one-time setup).

Usage:
    cd padel-munich
    pip install -r scripts/requirements.txt
    python -m scripts.seed_members

On first run Pyrogram will prompt you to log in (phone number + OTP).
A session file (seed_session.session) is saved locally so subsequent runs
skip the login. Add it to .gitignore — treat it like a password.

Environment variables (read from .env):
    API_ID      — from my.telegram.org
    API_HASH    — from my.telegram.org
    CHAT_ID     — group username (e.g. @mypadelgroup) or numeric chat ID
    DB_URL      — PostgreSQL connection string
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
from pyrogram import Client
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv()

# Validate required env vars early
_REQUIRED = ["API_ID", "API_HASH", "CHAT_ID", "DB_URL"]
_missing = [k for k in _REQUIRED if not os.getenv(k)]
if _missing:
    print(f"Missing env vars: {', '.join(_missing)}")
    print("Copy .env.example to .env and fill in the values.")
    sys.exit(1)

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
CHAT_ID = os.environ["CHAT_ID"]
DB_URL = os.environ["DB_URL"]


async def seed() -> None:
    from shared.db.models import Base
    from shared.db.repository import bulk_upsert_members

    # Prepare DB (creates tables if missing)
    engine = create_async_engine(DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Collect all non-bot members via Pyrogram user client
    print(f"Fetching members of '{CHAT_ID}'…")
    members: list[dict] = []
    async with Client("seed_session", api_id=API_ID, api_hash=API_HASH) as app:
        async for member in app.get_chat_members(CHAT_ID):
            if not member.user.is_bot and not member.user.is_deleted:
                members.append(
                    {
                        "tg_user_id": member.user.id,
                        "username": member.user.username,
                        "first_name": member.user.first_name,
                    }
                )

    print(f"Found {len(members)} non-bot members")

    async with session_factory() as session:
        count = await bulk_upsert_members(session, members)

    print(f"Done — {count} members processed (existing records untouched)")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())

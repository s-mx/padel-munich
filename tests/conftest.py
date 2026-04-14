"""
Shared fixtures for the padel-munich test suite.

Design overview
---------------
The suite has two distinct testing layers with different needs:

1. Repository tests (test_repository.py) — hit a REAL PostgreSQL database.
   The repository uses `sqlalchemy.dialects.postgresql.insert` for upserts,
   which is incompatible with SQLite, so a real Postgres instance is required.

2. Handler tests (test_handlers_*.py) — pure unit tests with NO database.
   Handlers receive `(message/event, session)` directly; the session is an
   AsyncMock, so no real connection is needed.

DB fixture design
-----------------
- `db_session` creates a fresh engine per test using NullPool (no connection
  pooling). NullPool is required because asyncpg connections are bound to the
  event loop they were created in; pooled connections from a previous test's
  event loop can't be reused in the next test's loop, causing
  "another operation is in progress" errors during teardown.
- Tables are truncated both before AND after each test:
  - Before: guarantees a clean slate even if a previous run aborted before
    its own teardown (e.g., after a KeyboardInterrupt during development).
  - After: leaves the DB clean for ad-hoc inspection between runs.
- `asyncio_default_fixture_loop_scope = function` (in pytest.ini) gives each
  test its own event loop, which matches asyncpg's per-loop connection model.

Handler fixture design
----------------------
- `mock_session` is a bare AsyncMock — all DB calls on it silently succeed and
  return None/MagicMock. Handler tests assert on `message.reply` instead.
- `make_message`, `make_reaction`, and `make_member_event` are factory
  fixtures: they return a callable so each test can configure exactly the
  fields it cares about, keeping tests minimal and self-documenting.
- aiogram objects use MagicMock(spec=...) so attribute access is validated
  against the real aiogram type, catching typos at test-write time.
- `message.reply` is an AsyncMock so tests can call `assert_called_once()` and
  inspect the formatted text sent back to the user.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from unittest.mock import AsyncMock, MagicMock
from aiogram.types import Message, MessageReactionUpdated, ChatMemberUpdated, ChatMember, User
from aiogram.enums import ChatMemberStatus

from shared.db.models import Base

TEST_DB_URL = "postgresql+asyncpg://padel:padel@localhost:5432/padel_test"


@pytest.fixture
async def db_session():
    """
    Yields a real AsyncSession backed by the padel_test Postgres database.

    Lifecycle per test:
      1. Create engine with NullPool (fresh TCP connection, no pooling).
      2. Run CREATE TABLE IF NOT EXISTS for all models (idempotent).
      3. TRUNCATE members before the test — clean even after a crashed run.
      4. Yield the session to the test.
      5. TRUNCATE members after the test — leaves DB tidy for manual inspection.
      6. Dispose the engine (closes the TCP connection).
    """
    eng = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Pre-test truncate: defence against dirty state from a previous
        # interrupted run where post-test cleanup never executed.
        await conn.execute(text("TRUNCATE members RESTART IDENTITY CASCADE"))
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as session:
        yield session
    # Post-test truncate: keeps the DB clean between runs.
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE members RESTART IDENTITY CASCADE"))
    await eng.dispose()


@pytest.fixture
def mock_session():
    """
    Returns an AsyncMock that satisfies the AsyncSession type hint.

    Handler tests don't need real DB calls — they verify that the handler
    calls message.reply() with the correct text. This mock makes every
    session method (execute, commit, etc.) a no-op AsyncMock.
    """
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def make_message():
    """
    Factory fixture that builds a MagicMock aiogram Message.

    Returns a callable so each test constructs exactly the Message it needs:

        msg = make_message(user_id=1, username="alice", text="/stats")

    The `reply` method is an AsyncMock so tests can assert on it:

        msg.reply.assert_called_once()
        assert "Stats" in msg.reply.call_args[0][0]
    """
    def _factory(
        user_id: int,
        username: str | None = None,
        first_name: str | None = "Test",
        is_bot: bool = False,
        text: str = "",
    ) -> MagicMock:
        msg = MagicMock(spec=Message)
        msg.reply = AsyncMock()
        msg.text = text
        user = MagicMock(spec=User)
        user.id = user_id
        user.username = username
        user.first_name = first_name
        user.is_bot = is_bot
        msg.from_user = user
        return msg

    return _factory


@pytest.fixture
def make_reaction():
    """
    Factory fixture that builds a MagicMock aiogram MessageReactionUpdated.

    The reaction handler reads `reaction.user` (not `reaction.from_user`),
    so this factory sets that attribute directly.

        reaction = make_reaction(user_id=10, username="bob")
    """
    def _factory(
        user_id: int,
        username: str | None = None,
        first_name: str | None = "Test",
        is_bot: bool = False,
    ) -> MagicMock:
        reaction = MagicMock(spec=MessageReactionUpdated)
        user = MagicMock(spec=User)
        user.id = user_id
        user.username = username
        user.first_name = first_name
        user.is_bot = is_bot
        reaction.user = user
        return reaction

    return _factory


@pytest.fixture
def make_member_event():
    """
    Factory fixture that builds a MagicMock aiogram ChatMemberUpdated.

    The members handler checks old_status → new_status transitions to decide
    whether a user is joining.  Pass the statuses you want to test:

        event = make_member_event(
            user_id=1,
            old_status=ChatMemberStatus.LEFT,
            new_status=ChatMemberStatus.MEMBER,
        )
    """
    def _factory(
        user_id: int,
        username: str | None = None,
        first_name: str | None = "Test",
        old_status: ChatMemberStatus = ChatMemberStatus.LEFT,
        new_status: ChatMemberStatus = ChatMemberStatus.MEMBER,
        is_bot: bool = False,
    ) -> MagicMock:
        event = MagicMock(spec=ChatMemberUpdated)
        user = MagicMock(spec=User)
        user.id = user_id
        user.username = username
        user.first_name = first_name
        user.is_bot = is_bot
        old = MagicMock(spec=ChatMember)
        old.status = old_status
        new = MagicMock(spec=ChatMember)
        new.status = new_status
        new.user = user
        event.old_chat_member = old
        event.new_chat_member = new
        return event

    return _factory

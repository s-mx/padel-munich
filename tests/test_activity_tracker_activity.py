"""
Unit tests for bots/activity_tracker/handlers/activity.py.

Design
------
These tests verify that every message and reaction from a human triggers an
upsert, while messages from bots or anonymous senders are ignored.

`upsert_member` is patched at the import site inside the activity module so
we can assert on calls without touching any database.  The mock_session is
never actually used by upsert_member here (it's patched out), but it must
still be passed to the handler to match the function signature.

Both handler functions — on_message and on_reaction — share the same filtering
logic (skip if is_bot or user is None), so the tests for each are parallel in
structure.
"""

from unittest.mock import AsyncMock, patch

from bots.activity_tracker.handlers.activity import on_message, on_reaction

# Patch target: the name `upsert_member` as it is imported inside the activity
# module.  Patching at the usage site (not at shared.db.repository) ensures
# the patch applies even if the module is already imported.
UPSERT_PATH = "bots.activity_tracker.handlers.activity.upsert_member"


# ---------------------------------------------------------------------------
# on_message
# ---------------------------------------------------------------------------


async def test_message_human_calls_upsert(make_message, mock_session):
    # A message from a real (non-bot) user must trigger upsert_member with
    # the user's id, username, and first_name forwarded exactly.
    msg = make_message(user_id=1, username="alice", first_name="Alice", is_bot=False)
    with patch(UPSERT_PATH, new=AsyncMock()) as upsert:
        await on_message(msg, mock_session)
    upsert.assert_called_once_with(mock_session, 1, "alice", "Alice")


async def test_message_bot_skips_upsert(make_message, mock_session):
    # Messages sent by bots (is_bot=True) must be ignored — bot activity
    # should not count towards member statistics.
    msg = make_message(user_id=2, is_bot=True)
    with patch(UPSERT_PATH, new=AsyncMock()) as upsert:
        await on_message(msg, mock_session)
    upsert.assert_not_called()


async def test_message_no_from_user_skips_upsert(make_message, mock_session):
    # Some Telegram message types (e.g. channel posts forwarded automatically)
    # have no from_user.  The handler must not crash and must not upsert.
    msg = make_message(user_id=3)
    msg.from_user = None
    with patch(UPSERT_PATH, new=AsyncMock()) as upsert:
        await on_message(msg, mock_session)
    upsert.assert_not_called()


# ---------------------------------------------------------------------------
# on_reaction
# ---------------------------------------------------------------------------


async def test_reaction_human_calls_upsert(make_reaction, mock_session):
    # An emoji reaction from a real user must trigger upsert_member so that
    # even members who only react (never type) get their activity recorded.
    reaction = make_reaction(user_id=10, username="bob", first_name="Bob", is_bot=False)
    with patch(UPSERT_PATH, new=AsyncMock()) as upsert:
        await on_reaction(reaction, mock_session)
    upsert.assert_called_once_with(mock_session, 10, "bob", "Bob")


async def test_reaction_bot_skips_upsert(make_reaction, mock_session):
    # Reactions added by bots must be ignored for the same reason as bot
    # messages — they inflate activity counts artificially.
    reaction = make_reaction(user_id=11, is_bot=True)
    with patch(UPSERT_PATH, new=AsyncMock()) as upsert:
        await on_reaction(reaction, mock_session)
    upsert.assert_not_called()


async def test_reaction_no_user_skips_upsert(make_reaction, mock_session):
    # A reaction event without an identified user (reaction.user = None) must
    # be silently skipped — the handler guards against this to avoid an
    # AttributeError when reading user.id.
    reaction = make_reaction(user_id=12)
    reaction.user = None
    with patch(UPSERT_PATH, new=AsyncMock()) as upsert:
        await on_reaction(reaction, mock_session)
    upsert.assert_not_called()

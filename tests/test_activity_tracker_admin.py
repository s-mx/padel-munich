"""
Unit tests for bots/activity_tracker/handlers/admin.py.

Design
------
These are pure unit tests — no real database is used.  Each handler function
(cmd_stats, cmd_inactive, cmd_top) receives a mocked Message and a mock
AsyncSession, so tests run without a running Postgres or bot token.

How handlers are called here
-----------------------------
Normally aiogram dispatches messages through its router machinery.  We bypass
all of that by calling the handler functions directly:

    await cmd_stats(msg, mock_session)

This is possible because each handler is a plain async function whose first
two positional arguments are the message and the injected session.

What we test
------------
Three concerns per command:
  1. Auth gate  — non-admin users are silently ignored (no reply sent).
  2. Argument parsing — default values, custom values, invalid input.
  3. Reply content — correct numbers/names appear in the formatted text.

Repository functions (get_stats, get_inactive, get_top) are patched at the
import site inside the admin module so handlers receive controlled return
values without hitting the database.

`settings.admin_ids` is monkeypatched at the admin module level (where the
already-imported name lives) rather than at config level, because pydantic
loads the Settings singleton at import time.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bots.activity_tracker.handlers.admin import cmd_inactive, cmd_stats, cmd_top
from shared.db.models import Member


def _make_admin_settings(admin_ids: list[int]):
    """Return a minimal settings mock with only admin_ids set."""
    s = MagicMock()
    s.admin_ids = admin_ids
    return s


def _make_member(tg_user_id: int, username: str | None, first_name: str | None, messages: int = 5):
    """
    Build a Member-like mock for use as a return value from get_inactive /
    get_top.  last_seen_at is a real datetime so strftime() works in the
    handler's formatting code.
    """
    m = MagicMock(spec=Member)
    m.tg_user_id = tg_user_id
    m.username = username
    m.first_name = first_name
    m.total_messages = messages
    m.last_seen_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return m


ADMIN_ID = 999
SETTINGS_PATH = "bots.activity_tracker.handlers.admin.settings"


# ---------------------------------------------------------------------------
# cmd_stats
# ---------------------------------------------------------------------------


async def test_stats_non_admin_ignored(make_message, mock_session, monkeypatch):
    # Non-admin users must get no response at all — the handler silently
    # returns without calling message.reply.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([]))
    msg = make_message(user_id=1, text="/stats")
    await cmd_stats(msg, mock_session)
    msg.reply.assert_not_called()


async def test_stats_no_from_user_ignored(make_message, mock_session, monkeypatch):
    # Messages without an identifiable sender (from_user=None, e.g. channel
    # forwarded posts) must be silently ignored to avoid an AttributeError.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    msg = make_message(user_id=ADMIN_ID, text="/stats")
    msg.from_user = None
    await cmd_stats(msg, mock_session)
    msg.reply.assert_not_called()


async def test_stats_admin_replies_with_counts(make_message, mock_session, monkeypatch):
    # An admin must receive a reply that contains all three numeric values
    # returned by get_stats.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    with patch("bots.activity_tracker.handlers.admin.get_stats", new=AsyncMock(
        return_value={"total": 5, "active_today": 2, "active_week": 4}
    )):
        msg = make_message(user_id=ADMIN_ID, text="/stats")
        await cmd_stats(msg, mock_session)

    msg.reply.assert_called_once()
    text = msg.reply.call_args[0][0]
    assert "5" in text
    assert "2" in text
    assert "4" in text


async def test_stats_reply_uses_html_bold(make_message, mock_session, monkeypatch):
    # The reply is formatted with HTML parse mode; numbers must be wrapped in
    # <b> tags so they stand out in the Telegram message.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    with patch("bots.activity_tracker.handlers.admin.get_stats", new=AsyncMock(
        return_value={"total": 1, "active_today": 1, "active_week": 1}
    )):
        msg = make_message(user_id=ADMIN_ID, text="/stats")
        await cmd_stats(msg, mock_session)

    assert "<b>" in msg.reply.call_args[0][0]


# ---------------------------------------------------------------------------
# cmd_inactive
# ---------------------------------------------------------------------------


async def test_inactive_non_admin_ignored(make_message, mock_session, monkeypatch):
    # Same auth gate as /stats — non-admins must receive no reply.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([]))
    msg = make_message(user_id=1, text="/inactive")
    await cmd_inactive(msg, mock_session)
    msg.reply.assert_not_called()


async def test_inactive_default_days_30(make_message, mock_session, monkeypatch):
    # /inactive with no argument must default to 30 days, which is passed as
    # the `days` positional argument to get_inactive.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    get_inactive_mock = AsyncMock(return_value=[])
    with patch("bots.activity_tracker.handlers.admin.get_inactive", new=get_inactive_mock):
        msg = make_message(user_id=ADMIN_ID, text="/inactive")
        await cmd_inactive(msg, mock_session)

    # Support both positional and keyword call styles.
    _, kwargs = get_inactive_mock.call_args
    assert kwargs.get("days", get_inactive_mock.call_args[0][1]) == 30


async def test_inactive_custom_days(make_message, mock_session, monkeypatch):
    # /inactive 7 must pass days=7 to get_inactive — the argument is correctly
    # parsed from the message text.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    get_inactive_mock = AsyncMock(return_value=[])
    with patch("bots.activity_tracker.handlers.admin.get_inactive", new=get_inactive_mock):
        msg = make_message(user_id=ADMIN_ID, text="/inactive 7")
        await cmd_inactive(msg, mock_session)

    args = get_inactive_mock.call_args[0]
    assert args[1] == 7


async def test_inactive_invalid_arg_replies_usage(make_message, mock_session, monkeypatch):
    # A non-integer argument must produce a usage hint reply instead of an
    # unhandled ValueError.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    msg = make_message(user_id=ADMIN_ID, text="/inactive foo")
    await cmd_inactive(msg, mock_session)
    msg.reply.assert_called_once()
    assert "Usage" in msg.reply.call_args[0][0]


async def test_inactive_no_members(make_message, mock_session, monkeypatch):
    # When no members are inactive, the handler must reply with an informative
    # message rather than sending an empty list.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    with patch("bots.activity_tracker.handlers.admin.get_inactive", new=AsyncMock(return_value=[])):
        msg = make_message(user_id=ADMIN_ID, text="/inactive")
        await cmd_inactive(msg, mock_session)

    assert "No members" in msg.reply.call_args[0][0]


async def test_inactive_lists_members(make_message, mock_session, monkeypatch):
    # Members must appear in the reply text, formatted with their @username
    # prefix when a username is available.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    members = [
        _make_member(1, "alice", "Alice"),
        _make_member(2, "bob", "Bob"),
    ]
    with patch("bots.activity_tracker.handlers.admin.get_inactive", new=AsyncMock(return_value=members)):
        msg = make_message(user_id=ADMIN_ID, text="/inactive")
        await cmd_inactive(msg, mock_session)

    text = msg.reply.call_args[0][0]
    assert "@alice" in text
    assert "@bob" in text


async def test_inactive_truncates_at_50(make_message, mock_session, monkeypatch):
    # The reply is capped at 50 lines to stay within Telegram's message size
    # limit.  When more members exist, a "… and N more" suffix must appear.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    members = [_make_member(i, f"u{i}", f"U{i}") for i in range(55)]
    with patch("bots.activity_tracker.handlers.admin.get_inactive", new=AsyncMock(return_value=members)):
        msg = make_message(user_id=ADMIN_ID, text="/inactive")
        await cmd_inactive(msg, mock_session)

    assert "and 5 more" in msg.reply.call_args[0][0]


async def test_inactive_label_uses_first_name_when_no_username(make_message, mock_session, monkeypatch):
    # When a member has no public username, the label falls back to first_name
    # so the output is still human-readable.  It must not print "@None".
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    members = [_make_member(1, None, "Bob")]
    with patch("bots.activity_tracker.handlers.admin.get_inactive", new=AsyncMock(return_value=members)):
        msg = make_message(user_id=ADMIN_ID, text="/inactive")
        await cmd_inactive(msg, mock_session)

    text = msg.reply.call_args[0][0]
    assert "Bob" in text
    assert "@None" not in text


# ---------------------------------------------------------------------------
# cmd_top
# ---------------------------------------------------------------------------


async def test_top_non_admin_ignored(make_message, mock_session, monkeypatch):
    # Non-admin users must receive no reply from /top.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([]))
    msg = make_message(user_id=1, text="/top")
    await cmd_top(msg, mock_session)
    msg.reply.assert_not_called()


async def test_top_default_n_10(make_message, mock_session, monkeypatch):
    # /top with no argument must default to fetching the top 10 members.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    get_top_mock = AsyncMock(return_value=[])
    with patch("bots.activity_tracker.handlers.admin.get_top", new=get_top_mock):
        msg = make_message(user_id=ADMIN_ID, text="/top")
        await cmd_top(msg, mock_session)

    assert get_top_mock.call_args[0][1] == 10


async def test_top_custom_n(make_message, mock_session, monkeypatch):
    # /top 5 must request exactly 5 members from get_top.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    get_top_mock = AsyncMock(return_value=[])
    with patch("bots.activity_tracker.handlers.admin.get_top", new=get_top_mock):
        msg = make_message(user_id=ADMIN_ID, text="/top 5")
        await cmd_top(msg, mock_session)

    assert get_top_mock.call_args[0][1] == 5


async def test_top_clamps_at_25(make_message, mock_session, monkeypatch):
    # The handler enforces a hard cap of 25 to prevent the reply from becoming
    # too long.  /top 100 must be silently clamped to 25.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    get_top_mock = AsyncMock(return_value=[])
    with patch("bots.activity_tracker.handlers.admin.get_top", new=get_top_mock):
        msg = make_message(user_id=ADMIN_ID, text="/top 100")
        await cmd_top(msg, mock_session)

    assert get_top_mock.call_args[0][1] == 25


async def test_top_invalid_arg_replies_usage(make_message, mock_session, monkeypatch):
    # A non-integer argument (e.g. /top abc) must reply with a usage hint
    # rather than crashing with a ValueError.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    msg = make_message(user_id=ADMIN_ID, text="/top abc")
    await cmd_top(msg, mock_session)
    assert "Usage" in msg.reply.call_args[0][0]


async def test_top_no_members(make_message, mock_session, monkeypatch):
    # When no members have been tracked yet, the handler must send an
    # informative message rather than an empty list.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    with patch("bots.activity_tracker.handlers.admin.get_top", new=AsyncMock(return_value=[])):
        msg = make_message(user_id=ADMIN_ID, text="/top")
        await cmd_top(msg, mock_session)

    assert "No members" in msg.reply.call_args[0][0]


async def test_top_lists_with_rank(make_message, mock_session, monkeypatch):
    # Each entry in the leaderboard must be prefixed with a rank number
    # ("1.", "2.", "3.") so users know their position.
    monkeypatch.setattr(SETTINGS_PATH, _make_admin_settings([ADMIN_ID]))
    members = [
        _make_member(1, "alice", "Alice", messages=100),
        _make_member(2, "bob", "Bob", messages=50),
        _make_member(3, "carol", "Carol", messages=25),
    ]
    with patch("bots.activity_tracker.handlers.admin.get_top", new=AsyncMock(return_value=members)):
        msg = make_message(user_id=ADMIN_ID, text="/top")
        await cmd_top(msg, mock_session)

    text = msg.reply.call_args[0][0]
    assert "1." in text
    assert "2." in text
    assert "3." in text

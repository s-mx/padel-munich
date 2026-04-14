"""
Unit tests for bots/activity_tracker/handlers/members.py.

Design
------
The members handler fires on ChatMemberUpdated events and records a new member
the moment they join the group.  The core logic is a status transition check:

    old_status in _LEFT   →   new_status in _JOINED   →   upsert

where _LEFT  = {LEFT, KICKED, RESTRICTED}
and   _JOINED = {MEMBER, ADMINISTRATOR, CREATOR}

The tests are organised into three groups:
  1. Join transitions   — old ∈ _LEFT, new ∈ _JOINED → upsert called.
  2. Non-join events    — old ∉ _LEFT or new ∉ _JOINED → upsert NOT called.
  3. Bot filtering      — is_bot=True → upsert NOT called even on join.
  4. Data forwarding    — correct user fields are passed to upsert.

`upsert_member` is patched at the import site inside the members module.
No database is used.
"""

from unittest.mock import AsyncMock, patch

import pytest
from aiogram.enums import ChatMemberStatus

from bots.activity_tracker.handlers.members import on_member_join

UPSERT_PATH = "bots.activity_tracker.handlers.members.upsert_member"


# ---------------------------------------------------------------------------
# Join transitions — should call upsert
# ---------------------------------------------------------------------------


async def test_left_to_member_calls_upsert(make_member_event, mock_session):
    # The most common join path: a user who had LEFT rejoins as a regular MEMBER.
    event = make_member_event(user_id=1, old_status=ChatMemberStatus.LEFT, new_status=ChatMemberStatus.MEMBER)
    with patch(UPSERT_PATH, new=AsyncMock()) as upsert:
        await on_member_join(event, mock_session)
    upsert.assert_called_once()


async def test_kicked_to_member_calls_upsert(make_member_event, mock_session):
    # A previously kicked user being re-added counts as a join — they are
    # returning to the community and should be tracked.
    event = make_member_event(user_id=2, old_status=ChatMemberStatus.KICKED, new_status=ChatMemberStatus.MEMBER)
    with patch(UPSERT_PATH, new=AsyncMock()) as upsert:
        await on_member_join(event, mock_session)
    upsert.assert_called_once()


async def test_restricted_to_member_calls_upsert(make_member_event, mock_session):
    # A restricted user being un-restricted (promoted to full member) is also
    # a join-like transition worth recording.
    event = make_member_event(user_id=3, old_status=ChatMemberStatus.RESTRICTED, new_status=ChatMemberStatus.MEMBER)
    with patch(UPSERT_PATH, new=AsyncMock()) as upsert:
        await on_member_join(event, mock_session)
    upsert.assert_called_once()


async def test_left_to_admin_calls_upsert(make_member_event, mock_session):
    # Someone joining directly as ADMINISTRATOR (e.g. added by another admin)
    # is still a new member and must be recorded.
    event = make_member_event(user_id=4, old_status=ChatMemberStatus.LEFT, new_status=ChatMemberStatus.ADMINISTRATOR)
    with patch(UPSERT_PATH, new=AsyncMock()) as upsert:
        await on_member_join(event, mock_session)
    upsert.assert_called_once()


# ---------------------------------------------------------------------------
# Non-join transitions — should NOT call upsert
# ---------------------------------------------------------------------------


async def test_member_to_left_no_upsert(make_member_event, mock_session):
    # A member leaving the group is a departure, not a join.  Upsert must not
    # be called — we track activity, not exits.
    event = make_member_event(user_id=5, old_status=ChatMemberStatus.MEMBER, new_status=ChatMemberStatus.LEFT)
    with patch(UPSERT_PATH, new=AsyncMock()) as upsert:
        await on_member_join(event, mock_session)
    upsert.assert_not_called()


async def test_member_to_member_no_upsert(make_member_event, mock_session):
    # A MEMBER → MEMBER event (e.g. profile update, no status change) has
    # old_status ∉ _LEFT, so the join condition fails and upsert must not fire.
    event = make_member_event(user_id=6, old_status=ChatMemberStatus.MEMBER, new_status=ChatMemberStatus.MEMBER)
    with patch(UPSERT_PATH, new=AsyncMock()) as upsert:
        await on_member_join(event, mock_session)
    upsert.assert_not_called()


# ---------------------------------------------------------------------------
# Bot filtering
# ---------------------------------------------------------------------------


async def test_bot_join_skips_upsert(make_member_event, mock_session):
    # Bots joining the group must not be recorded as members — they are
    # infrastructure, not community participants.
    event = make_member_event(
        user_id=7,
        old_status=ChatMemberStatus.LEFT,
        new_status=ChatMemberStatus.MEMBER,
        is_bot=True,
    )
    with patch(UPSERT_PATH, new=AsyncMock()) as upsert:
        await on_member_join(event, mock_session)
    upsert.assert_not_called()


# ---------------------------------------------------------------------------
# Correct data forwarded to upsert
# ---------------------------------------------------------------------------


async def test_upsert_called_with_correct_user_data(make_member_event, mock_session):
    # The handler must pass the new member's exact user_id, username, and
    # first_name to upsert_member — not default/placeholder values.
    event = make_member_event(
        user_id=42,
        username="padel_king",
        first_name="Carlos",
        old_status=ChatMemberStatus.LEFT,
        new_status=ChatMemberStatus.MEMBER,
        is_bot=False,
    )
    with patch(UPSERT_PATH, new=AsyncMock()) as upsert:
        await on_member_join(event, mock_session)
    upsert.assert_called_once_with(mock_session, 42, "padel_king", "Carlos")

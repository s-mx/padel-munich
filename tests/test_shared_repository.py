"""
Integration tests for shared/db/repository.py.

Design
------
These tests run against a real PostgreSQL database (padel_test) because the
repository uses sqlalchemy.dialects.postgresql.insert for upserts, which is
not compatible with SQLite.

Each test uses the `db_session` fixture from conftest.py, which:
  - Creates a fresh engine per test (NullPool — no connection reuse).
  - TRUNCATEs the members table before and after each test for isolation.

Date-controlled setup
---------------------
`upsert_member` always stamps last_seen_at = now(), which makes it impossible
to test date-range queries (get_stats, get_inactive) by calling upsert_member.
Instead, tests that need a specific timestamp insert Member objects directly
via `_add_member()`, bypassing the upsert timestamp logic entirely.

The helper `_days_ago(n)` computes UTC timestamps relative to now, letting
test data stay correct no matter when the suite runs.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from shared.db.models import Member
from shared.db.repository import (
    bulk_upsert_members,
    get_inactive,
    get_stats,
    get_top,
    upsert_member,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_ago(n: int) -> datetime:
    return _now() - timedelta(days=n)


# ---------------------------------------------------------------------------
# upsert_member
# ---------------------------------------------------------------------------


async def test_upsert_inserts_new_member(db_session):
    # A first-time upsert should create a row with total_messages=1 and the
    # correct username/first_name — this is the INSERT path of the upsert.
    await upsert_member(db_session, 101, "alice", "Alice")
    result = await db_session.execute(select(Member).where(Member.tg_user_id == 101))
    m = result.scalar_one()
    assert m.total_messages == 1
    assert m.username == "alice"
    assert m.first_name == "Alice"


async def test_upsert_increments_message_count(db_session):
    # The second upsert for the same user hits the ON CONFLICT path and must
    # increment total_messages by 1, not reset it to 1.
    await upsert_member(db_session, 102, "bob", "Bob")
    await upsert_member(db_session, 102, "bob", "Bob")
    result = await db_session.execute(select(Member).where(Member.tg_user_id == 102))
    m = result.scalar_one()
    assert m.total_messages == 2


async def test_upsert_updates_username_on_conflict(db_session):
    # If a user changes their Telegram username, the update path should store
    # the new value — not keep the old one.
    await upsert_member(db_session, 103, "oldname", "Old")
    await upsert_member(db_session, 103, "newname", "New")
    result = await db_session.execute(select(Member).where(Member.tg_user_id == 103))
    m = result.scalar_one()
    assert m.username == "newname"
    assert m.first_name == "New"


async def test_upsert_accepts_none_username(db_session):
    # Not all Telegram users have a public username; upsert must not crash
    # when username=None and must store NULL in the column.
    await upsert_member(db_session, 104, None, "NoUsername")
    result = await db_session.execute(select(Member).where(Member.tg_user_id == 104))
    m = result.scalar_one()
    assert m.username is None
    assert m.total_messages == 1


async def test_upsert_different_users_are_independent(db_session):
    # Upserting user A must not touch user B's counter — each tg_user_id is
    # an independent row identified by the UNIQUE constraint.
    await upsert_member(db_session, 105, "u1", "User1")
    await upsert_member(db_session, 106, "u2", "User2")
    for tg_id in (105, 106):
        result = await db_session.execute(select(Member).where(Member.tg_user_id == tg_id))
        assert result.scalar_one().total_messages == 1


async def test_upsert_sets_last_seen_at_close_to_now(db_session):
    # last_seen_at is set to UTC now() inside upsert_member; the stored value
    # must fall within the bracket [before_call, after_call].
    before = _now()
    await upsert_member(db_session, 107, "u3", "User3")
    after = _now()
    result = await db_session.execute(select(Member).where(Member.tg_user_id == 107))
    m = result.scalar_one()
    assert before <= m.last_seen_at <= after


# ---------------------------------------------------------------------------
# bulk_upsert_members
# ---------------------------------------------------------------------------


async def test_bulk_upsert_inserts_all(db_session):
    # The seed script bulk-inserts new members. All three rows must be created,
    # and because no messages have been seen yet, total_messages stays at 0
    # (bulk_upsert uses on_conflict_do_nothing, not the increment upsert).
    members = [
        {"tg_user_id": 201, "username": "a", "first_name": "A"},
        {"tg_user_id": 202, "username": "b", "first_name": "B"},
        {"tg_user_id": 203, "username": "c", "first_name": "C"},
    ]
    count = await bulk_upsert_members(db_session, members)
    assert count == 3
    result = await db_session.execute(select(Member))
    rows = result.scalars().all()
    assert len(rows) == 3
    assert all(r.total_messages == 0 for r in rows)


async def test_bulk_upsert_skips_existing(db_session):
    # If a member already exists, bulk_upsert must leave their row untouched
    # (on_conflict_do_nothing). This preserves the message count accumulated
    # since the bot was added — re-running the seed script is safe.
    await upsert_member(db_session, 204, "existing", "Existing")  # total_messages = 1
    members = [
        {"tg_user_id": 204, "username": "existing", "first_name": "Existing"},
        {"tg_user_id": 205, "username": "new", "first_name": "New"},
    ]
    await bulk_upsert_members(db_session, members)
    result = await db_session.execute(select(Member).where(Member.tg_user_id == 204))
    m = result.scalar_one()
    assert m.total_messages == 1  # preserved, not overwritten


async def test_bulk_upsert_empty_list_returns_zero(db_session):
    # Passing an empty list should be a no-op: zero rows returned, no DB writes.
    count = await bulk_upsert_members(db_session, [])
    assert count == 0
    result = await db_session.execute(select(Member))
    assert result.scalars().all() == []


async def test_bulk_upsert_chunking(db_session):
    # bulk_upsert processes rows in chunks of 500 to avoid hitting Postgres
    # parameter limits. 501 members exercises the loop's second iteration.
    members = [
        {"tg_user_id": 10000 + i, "username": f"u{i}", "first_name": f"U{i}"}
        for i in range(501)
    ]
    count = await bulk_upsert_members(db_session, members)
    assert count == 501
    result = await db_session.execute(select(Member))
    assert len(result.scalars().all()) == 501


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


async def _add_member(session, tg_user_id: int, last_seen_at: datetime, messages: int = 0):
    """
    Insert a Member row with a custom last_seen_at timestamp.

    Used by stats/inactive/top tests that need to control exactly when a
    member was last seen.  We bypass upsert_member here because that function
    always sets last_seen_at = now(), making it impossible to simulate past
    activity from within a test.
    """
    session.add(
        Member(
            tg_user_id=tg_user_id,
            username=None,
            first_name=f"U{tg_user_id}",
            last_seen_at=last_seen_at,
            total_messages=messages,
        )
    )
    await session.commit()


async def test_get_stats_empty_db(db_session):
    # All counters must be zero when the table is empty — no crashes or NULLs
    # from the COUNT queries.
    s = await get_stats(db_session)
    assert s == {"total": 0, "active_today": 0, "active_week": 0}


async def test_get_stats_counts_total(db_session):
    # total counts every member regardless of when they were last seen;
    # members not seen today or this week must not inflate the time-based
    # counters.
    for i in range(3):
        await _add_member(db_session, 300 + i, _days_ago(60))
    s = await get_stats(db_session)
    assert s["total"] == 3
    assert s["active_today"] == 0
    assert s["active_week"] == 0


async def test_get_stats_active_today(db_session):
    # active_today counts members whose last_seen_at >= midnight UTC today.
    # A member seen yesterday must not be counted.
    await _add_member(db_session, 401, _now())
    await _add_member(db_session, 402, _now())
    await _add_member(db_session, 403, _days_ago(1))
    s = await get_stats(db_session)
    assert s["active_today"] == 2
    assert s["total"] == 3


async def test_get_stats_active_week(db_session):
    # active_week counts members seen since Monday 00:00 UTC of the current
    # week.  A member seen before that Monday must not be counted.
    now = _now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today - timedelta(days=today.weekday())  # Monday 00:00

    await _add_member(db_session, 501, week_start + timedelta(hours=1))  # this week
    await _add_member(db_session, 502, week_start - timedelta(days=1))   # last week

    s = await get_stats(db_session)
    assert s["active_week"] == 1
    assert s["total"] == 2


async def test_get_stats_week_boundary_strict(db_session):
    # The week boundary is inclusive (>=), so a member seen exactly at
    # week_start (Monday 00:00:00 UTC) must count as active this week.
    # A member seen one second before must not.
    now = _now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today - timedelta(days=today.weekday())

    await _add_member(db_session, 601, week_start)                        # exactly on boundary → counts
    await _add_member(db_session, 602, week_start - timedelta(seconds=1)) # one second before → does not count

    s = await get_stats(db_session)
    assert s["active_week"] == 1


# ---------------------------------------------------------------------------
# get_inactive
# ---------------------------------------------------------------------------


async def test_get_inactive_returns_past_cutoff(db_session):
    # A member last seen 35 days ago must appear in a 30-day inactivity report.
    await _add_member(db_session, 701, _days_ago(35))
    members = await get_inactive(db_session, 30)
    assert len(members) == 1
    assert members[0].tg_user_id == 701


async def test_get_inactive_excludes_recent(db_session):
    # A member active yesterday must not appear in the 30-day inactivity list.
    await _add_member(db_session, 702, _days_ago(1))
    members = await get_inactive(db_session, 30)
    assert members == []


async def test_get_inactive_boundary_not_yet_past(db_session):
    # get_inactive uses a strict `<` (less-than) cutoff, so a member seen
    # slightly LESS than 30 days ago must not appear in the report.
    # A 5-second buffer prevents flakiness from the few microseconds that
    # pass between computing the timestamp here and inside get_inactive.
    almost_cutoff = _now() - timedelta(days=30) + timedelta(seconds=5)
    await _add_member(db_session, 703, almost_cutoff)
    members = await get_inactive(db_session, 30)
    assert members == []


async def test_get_inactive_ordered_oldest_first(db_session):
    # The report is ordered ASC by last_seen_at so the longest-absent members
    # appear at the top — most urgent to follow up with.
    await _add_member(db_session, 801, _days_ago(90))  # oldest
    await _add_member(db_session, 802, _days_ago(45))  # newest of the three
    await _add_member(db_session, 803, _days_ago(60))  # middle
    members = await get_inactive(db_session, 30)
    assert len(members) == 3
    assert members[0].tg_user_id == 801  # 90 days — oldest
    assert members[1].tg_user_id == 803  # 60 days
    assert members[2].tg_user_id == 802  # 45 days — most recent


# ---------------------------------------------------------------------------
# get_top
# ---------------------------------------------------------------------------


async def test_get_top_returns_n(db_session):
    # get_top must respect the LIMIT and return exactly n rows when more
    # members exist.
    for i, msgs in enumerate([50, 30, 20, 10, 5]):
        await _add_member(db_session, 900 + i, _now(), messages=msgs)
    top = await get_top(db_session, 3)
    assert len(top) == 3


async def test_get_top_ordered_desc_by_messages(db_session):
    # The leaderboard must rank members by total_messages descending — highest
    # activity at position 1.
    for i, msgs in enumerate([5, 50, 20]):
        await _add_member(db_session, 910 + i, _now(), messages=msgs)
    top = await get_top(db_session, 3)
    assert top[0].total_messages == 50
    assert top[1].total_messages == 20
    assert top[2].total_messages == 5


async def test_get_top_empty_db(db_session):
    # get_top must return an empty list (not crash) when no members exist.
    top = await get_top(db_session, 10)
    assert top == []


async def test_get_top_fewer_than_n_available(db_session):
    # When fewer members exist than the requested limit, return all of them
    # rather than raising an error or padding with None.
    await _add_member(db_session, 920, _now(), messages=10)
    await _add_member(db_session, 921, _now(), messages=5)
    top = await get_top(db_session, 10)
    assert len(top) == 2

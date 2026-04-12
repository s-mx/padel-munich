from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Member


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_start() -> datetime:
    now = _now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def upsert_member(
    session: AsyncSession,
    tg_user_id: int,
    username: str | None,
    first_name: str | None,
) -> None:
    now = _now()
    stmt = (
        insert(Member)
        .values(
            tg_user_id=tg_user_id,
            username=username,
            first_name=first_name,
            last_seen_at=now,
            total_messages=1,
        )
        .on_conflict_do_update(
            index_elements=["tg_user_id"],
            set_={
                "username": username,
                "first_name": first_name,
                "last_seen_at": now,
                "total_messages": Member.total_messages + 1,
            },
        )
    )
    await session.execute(stmt)
    await session.commit()


async def bulk_upsert_members(session: AsyncSession, members: list[dict]) -> int:
    """Insert members that don't exist yet; skip existing ones (preserves message counts).

    Each dict must have: tg_user_id, username, first_name.
    Returns the number of rows processed.
    """
    if not members:
        return 0
    now = _now()
    rows = [
        {"tg_user_id": m["tg_user_id"], "username": m["username"], "first_name": m["first_name"], "last_seen_at": now, "total_messages": 0}
        for m in members
    ]
    # Process in chunks to avoid hitting parameter limits
    chunk_size = 500
    for i in range(0, len(rows), chunk_size):
        stmt = (
            insert(Member)
            .values(rows[i : i + chunk_size])
            .on_conflict_do_nothing(index_elements=["tg_user_id"])
        )
        await session.execute(stmt)
    await session.commit()
    return len(rows)


async def get_stats(session: AsyncSession) -> dict:
    today = _today_start()
    week_start = today - timedelta(days=today.weekday())

    total = await session.scalar(select(func.count()).select_from(Member))
    active_today = await session.scalar(
        select(func.count()).select_from(Member).where(Member.last_seen_at >= today)
    )
    active_week = await session.scalar(
        select(func.count()).select_from(Member).where(Member.last_seen_at >= week_start)
    )
    return {
        "total": total or 0,
        "active_today": active_today or 0,
        "active_week": active_week or 0,
    }


async def get_inactive(session: AsyncSession, days: int) -> list[Member]:
    cutoff = _now() - timedelta(days=days)
    result = await session.execute(
        select(Member).where(Member.last_seen_at < cutoff).order_by(Member.last_seen_at.asc())
    )
    return list(result.scalars().all())


async def get_top(session: AsyncSession, n: int) -> list[Member]:
    result = await session.execute(
        select(Member).order_by(Member.total_messages.desc()).limit(n)
    )
    return list(result.scalars().all())

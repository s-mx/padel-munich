import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.repository import get_inactive, get_stats, get_top
from bots.activity_tracker.config import settings

router = Router(name="admin")
logger = logging.getLogger(__name__)

_MAX_LIST_ROWS = 50
_MAX_TOP = 25


def _is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


def _member_label(m) -> str:
    if m.username:
        return f"@{m.username}"
    return m.first_name or str(m.tg_user_id)


@router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        if message.from_user:
            logger.warning("Unauthorized /stats attempt by user %s", message.from_user.id)
        return
    logger.info("Admin %s ran /stats", message.from_user.id)
    s = await get_stats(session)
    await message.reply(
        f"<b>Community Stats</b>\n"
        f"Total tracked: <b>{s['total']}</b>\n"
        f"Active today: <b>{s['active_today']}</b>\n"
        f"Active this week: <b>{s['active_week']}</b>"
    )


@router.message(Command("inactive"))
async def cmd_inactive(message: Message, session: AsyncSession) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        if message.from_user:
            logger.warning("Unauthorized /inactive attempt by user %s", message.from_user.id)
        return
    args = (message.text or "").split()[1:]
    try:
        days = int(args[0]) if args else 30
    except ValueError:
        await message.reply("Usage: /inactive [days]  — e.g. /inactive 30")
        return
    logger.info("Admin %s ran /inactive days=%d", message.from_user.id, days)
    members = await get_inactive(session, days)
    if not members:
        await message.reply(f"No members inactive for {days}+ days.")
        return

    lines = [f"<b>Inactive {days}+ days ({len(members)} members):</b>"]
    for m in members[:_MAX_LIST_ROWS]:
        last = m.last_seen_at.strftime("%Y-%m-%d")
        lines.append(f"• {_member_label(m)} — last seen {last}")
    if len(members) > _MAX_LIST_ROWS:
        lines.append(f"… and {len(members) - _MAX_LIST_ROWS} more")
    await message.reply("\n".join(lines))


@router.message(Command("top"))
async def cmd_top(message: Message, session: AsyncSession) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        if message.from_user:
            logger.warning("Unauthorized /top attempt by user %s", message.from_user.id)
        return
    args = (message.text or "").split()[1:]
    try:
        n = min(int(args[0]) if args else 10, _MAX_TOP)
    except ValueError:
        await message.reply("Usage: /top [n]  — e.g. /top 10")
        return
    logger.info("Admin %s ran /top n=%d", message.from_user.id, n)
    members = await get_top(session, n)
    if not members:
        await message.reply("No members tracked yet.")
        return

    lines = [f"<b>Top {len(members)} most active members:</b>"]
    for i, m in enumerate(members, 1):
        lines.append(f"{i}. {_member_label(m)} — {m.total_messages} messages")
    await message.reply("\n".join(lines))

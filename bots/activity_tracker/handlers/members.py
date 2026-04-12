import logging

from aiogram import Router
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.repository import upsert_member

router = Router(name="members")
logger = logging.getLogger(__name__)

_JOINED = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
_LEFT = {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED, ChatMemberStatus.RESTRICTED}


@router.chat_member()
async def on_member_join(event: ChatMemberUpdated, session: AsyncSession) -> None:
    """Record new members the moment they join the group."""
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    if old_status in _LEFT and new_status in _JOINED:
        user = event.new_chat_member.user
        if not user.is_bot:
            logger.info("New member joined: %s (@%s)", user.id, user.username)
            await upsert_member(session, user.id, user.username, user.first_name)

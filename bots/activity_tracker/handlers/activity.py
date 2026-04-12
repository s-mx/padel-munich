import logging

from aiogram import Router
from aiogram.types import Message, MessageReactionUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.repository import upsert_member

router = Router(name="activity")
logger = logging.getLogger(__name__)


@router.message()
async def on_message(message: Message, session: AsyncSession) -> None:
    user = message.from_user
    if user and not user.is_bot:
        logger.debug("Message from %s (@%s), upserting activity", user.id, user.username)
        await upsert_member(session, user.id, user.username, user.first_name)


@router.message_reaction()
async def on_reaction(reaction: MessageReactionUpdated, session: AsyncSession) -> None:
    user = reaction.user
    if user and not user.is_bot:
        logger.debug("Reaction from %s (@%s), upserting activity", user.id, user.username)
        await upsert_member(session, user.id, user.username, user.first_name)

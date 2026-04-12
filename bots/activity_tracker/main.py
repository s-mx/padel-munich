import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bots.activity_tracker.config import settings
from bots.activity_tracker.handlers.activity import router as activity_router
from bots.activity_tracker.handlers.admin import router as admin_router
from bots.activity_tracker.handlers.members import router as members_router
from bots.activity_tracker.middlewares.db import DbSessionMiddleware
from shared.db.session import create_tables, get_session_factory, init_db

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    init_db(settings.db_url)
    await create_tables()
    logger.info("Database ready")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.update.middleware(DbSessionMiddleware(get_session_factory()))

    # Router order matters: admin commands before catch-all activity, members separate
    dp.include_router(admin_router)
    dp.include_router(members_router)
    dp.include_router(activity_router)

    logger.info("Starting activity tracker bot (long-polling)…")
    await dp.start_polling(
        bot,
        allowed_updates=["message", "message_reaction", "callback_query", "chat_member"],
    )


if __name__ == "__main__":
    asyncio.run(main())

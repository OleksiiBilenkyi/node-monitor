import asyncio
from bot import bot
from bot_commands import setup_commands
from log_setting import setup_logging
from data_base import init_db

async def main():
    setup_logging()
    await init_db()
    setup_commands(bot)
    await bot.start(bot.token)

if __name__ == "__main__":
    asyncio.run(main())
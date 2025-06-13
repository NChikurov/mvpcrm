#!/usr/bin/env python3
"""
AI-CRM Telegram Bot MVP
"""
import asyncio
import logging
import yaml
from pathlib import Path
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from multiprocessing import Process

from database.operations import init_database
from handlers.user import UserHandler
from handlers.admin import AdminHandler
from myparser.channel_parser import ChannelParser

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def start_parser(config):
    from myparser.channel_parser import ChannelParser
    import asyncio
    parser = ChannelParser(config)
    asyncio.run(parser.start_parsing())

class AIBot:
    def __init__(self, config_path="config.yaml"):
        self.config = self.load_config(config_path)
        self.app = None
        self.user_handler = None
        self.admin_handler = None
        self.channel_parser = None
        self.parser_proc = None
        
    def load_config(self, config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logger.error(f"Файл {config_path} не найден!")
            raise
        except yaml.YAMLError as e:
            logger.error(f"Ошибка чтения конфигурации: {e}")
            raise

    async def setup_bot(self):
        await init_database()
        self.app = Application.builder().token(self.config['bot']['token']).build()
        self.user_handler = UserHandler(self.config)
        self.admin_handler = AdminHandler(self.config)
        self.register_handlers()
        self.channel_parser = ChannelParser(self.config)
        # Запуск парсера в отдельном процессе
        self.parser_proc = Process(target=start_parser, args=(self.config,))
        self.parser_proc.start()
        logger.info("Бот готов к работе")

    def register_handlers(self):
        self.app.add_handler(CommandHandler("start", self.user_handler.start))
        self.app.add_handler(CommandHandler("help", self.user_handler.help))
        self.app.add_handler(CommandHandler("menu", self.user_handler.menu))
        self.app.add_handler(CommandHandler("admin", self.admin_handler.admin_panel))
        self.app.add_handler(CommandHandler("users", self.admin_handler.show_users))
        self.app.add_handler(CommandHandler("leads", self.admin_handler.show_leads))
        self.app.add_handler(CommandHandler("channels", self.admin_handler.manage_channels))
        self.app.add_handler(CommandHandler("broadcast", self.admin_handler.broadcast))
        self.app.add_handler(CommandHandler("settings", self.admin_handler.settings))
        self.app.add_handler(CommandHandler("stats", self.admin_handler.stats))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.user_handler.handle_message))
        self.app.add_handler(self.user_handler.callback_handler)
        self.app.add_handler(self.admin_handler.callback_handler)

    async def run(self):
        await self.setup_bot()
        logger.info(f"Запуск бота: {self.config['bot']['name']}")
        # Запускаем бота
        await self.app.run_polling(allowed_updates=['message', 'callback_query'], drop_pending_updates=True)

def main():
    bot = None
    try:
        import sys
        if sys.platform.startswith("win") and sys.version_info >= (3, 8):
            import asyncio
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        bot = AIBot()
        import asyncio
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    finally:
        if bot and hasattr(bot, 'parser_proc') and bot.parser_proc:
            bot.parser_proc.terminate()
            bot.parser_proc.join()

if __name__ == "__main__":
    main()

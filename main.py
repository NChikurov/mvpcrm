#!/usr/bin/env python3
"""
AI-CRM Telegram Bot MVP
"""
import asyncio
import logging
import sys
from pathlib import Path
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from multiprocessing import Process

from utils.config_loader import load_config, print_config_summary
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
    """Запуск парсера в отдельном процессе"""
    from myparser.channel_parser import ChannelParser
    import asyncio
    parser = ChannelParser(config)
    asyncio.run(parser.start_parsing())

class AIBot:
    def __init__(self, config_path="config.yaml", env_path=".env"):
        self.config = load_config(config_path, env_path)
        self.app = None
        self.user_handler = None
        self.admin_handler = None
        self.channel_parser = None
        self.parser_proc = None
        
        # Выводим сводку конфигурации
        print_config_summary(self.config)

    async def setup_bot(self):
        """Настройка бота"""
        await init_database()
        
        # Создаем приложение с токеном из конфигурации
        self.app = Application.builder().token(self.config['bot']['token']).build()
        
        # Инициализируем обработчики
        self.user_handler = UserHandler(self.config)
        self.admin_handler = AdminHandler(self.config)
        
        # Регистрируем обработчики
        self.register_handlers()
        
        # Инициализируем парсер каналов
        self.channel_parser = ChannelParser(self.config)
        
        # Запускаем парсер в отдельном процессе (если включен)
        if self.config['parsing']['enabled']:
            self.parser_proc = Process(target=start_parser, args=(self.config,))
            self.parser_proc.start()
            logger.info("Парсер каналов запущен в отдельном процессе")
        else:
            logger.info("Парсер каналов отключен")
        
        logger.info("Бот готов к работе")

    def register_handlers(self):
        """Регистрация обработчиков команд"""
        # Пользовательские команды
        self.app.add_handler(CommandHandler("start", self.user_handler.start))
        self.app.add_handler(CommandHandler("help", self.user_handler.help))
        self.app.add_handler(CommandHandler("menu", self.user_handler.menu))
        
        # Админские команды
        self.app.add_handler(CommandHandler("admin", self.admin_handler.admin_panel))
        self.app.add_handler(CommandHandler("users", self.admin_handler.show_users))
        self.app.add_handler(CommandHandler("leads", self.admin_handler.show_leads))
        self.app.add_handler(CommandHandler("channels", self.admin_handler.manage_channels))
        self.app.add_handler(CommandHandler("broadcast", self.admin_handler.broadcast))
        self.app.add_handler(CommandHandler("settings", self.admin_handler.settings))
        self.app.add_handler(CommandHandler("stats", self.admin_handler.stats))
        
        # Обработчик текстовых сообщений
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            self.user_handler.handle_message
        ))
        
        # Callback обработчики
        self.app.add_handler(self.user_handler.callback_handler)
        self.app.add_handler(self.admin_handler.callback_handler)

    async def run(self):
        """Запуск бота"""
        await self.setup_bot()
        
        logger.info(f"Запуск бота: {self.config['bot']['name']}")
        logger.info(f"Админы: {self.config['bot']['admin_ids']}")
        
        # Инициализируем и запускаем приложение
        await self.app.initialize()
        await self.app.start()
        await self.app.run_polling(
            allowed_updates=['message', 'callback_query'], 
            drop_pending_updates=True
        )

    def shutdown(self):
        """Корректное завершение работы"""
        if self.parser_proc and self.parser_proc.is_alive():
            logger.info("Остановка парсера каналов...")
            self.parser_proc.terminate()
            self.parser_proc.join(timeout=5)
            if self.parser_proc.is_alive():
                logger.warning("Принудительное завершение парсера")
                self.parser_proc.kill()
            logger.info("Парсер остановлен")

def main():
    """Главная функция"""
    bot = None
    try:
        # Настройка event loop для Windows
        if sys.platform.startswith("win") and sys.version_info >= (3, 8):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        # Создаем и запускаем бота
        bot = AIBot()
        asyncio.run(bot.run())
        
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки (Ctrl+C)")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        raise
    finally:
        if bot:
            bot.shutdown()
        logger.info("Бот остановлен")

if __name__ == "__main__":
    main()
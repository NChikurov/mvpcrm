#!/usr/bin/env python3
"""
AI-CRM Telegram Bot MVP
"""
import asyncio
import logging
import sys
import threading
from pathlib import Path
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from utils.config_loader import load_config, print_config_summary
from database.operations import init_database
from handlers.user import UserHandler
from handlers.admin import AdminHandler
from myparser.channel_parser import ChannelParser

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class AIBot:
    def __init__(self, config_path="config.yaml", env_path=".env"):
        try:
            self.config = load_config(config_path, env_path)
            self.app = None
            self.user_handler = None
            self.admin_handler = None
            self.channel_parser = None
            self.parser_running = False
            
            # Выводим сводку конфигурации
            print_config_summary(self.config)
        except Exception as e:
            logger.error(f"Ошибка инициализации конфигурации: {e}")
            raise

    async def setup_bot(self):
        """Настройка бота"""
        try:
            await init_database()
            logger.info("База данных инициализирована")
            
            # Создаем приложение с токеном из конфигурации
            bot_token = self.config['bot']['token']
            if not bot_token:
                raise ValueError("BOT_TOKEN не установлен")
            
            self.app = Application.builder().token(bot_token).build()
            logger.info("Application создан")
            
            # Инициализируем обработчики
            self.user_handler = UserHandler(self.config)
            self.admin_handler = AdminHandler(self.config)
            logger.info("Обработчики инициализированы")
            
            # Регистрируем обработчики
            self.register_handlers()
            logger.info("Обработчики зарегистрированы")
            
            # Инициализируем парсер каналов
            self.channel_parser = ChannelParser(self.config)
            
            # Запускаем парсер в отдельном потоке
            if self.config['parsing']['enabled']:
                parser_thread = threading.Thread(
                    target=self._run_parser_in_thread,
                    daemon=True
                )
                parser_thread.start()
                self.parser_running = True
                logger.info("Парсер каналов запущен в отдельном потоке")
            else:
                logger.info("Парсинг каналов отключен")
            
            logger.info("Бот готов к работе")
            
        except Exception as e:
            logger.error(f"Ошибка настройки бота: {e}")
            raise

    def _run_parser_in_thread(self):
        """Запуск парсера в отдельном потоке"""
        try:
            # Создаем новый event loop для потока
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Запускаем парсер
            loop.run_until_complete(self.channel_parser.start_parsing())
            
        except Exception as e:
            logger.error(f"Ошибка в потоке парсера: {e}")
        finally:
            logger.info("Поток парсера завершен")

    def register_handlers(self):
        """Регистрация обработчиков команд"""
        try:
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
            
            logger.info("Все обработчики успешно зарегистрированы")
            
        except Exception as e:
            logger.error(f"Ошибка регистрации обработчиков: {e}")
            raise

    async def run(self):
        """Запуск бота"""
        try:
            await self.setup_bot()
            
            logger.info(f"Запуск бота: {self.config['bot']['name']}")
            logger.info(f"Админы: {self.config['bot']['admin_ids']}")
            
            # Проверяем подключение к Telegram API
            try:
                bot_info = await self.app.bot.get_me()
                logger.info(f"Бот подключен как: @{bot_info.username} ({bot_info.first_name})")
            except Exception as e:
                logger.error(f"Ошибка подключения к Telegram API: {e}")
                raise
            
            # Инициализируем и запускаем приложение
            await self.app.initialize()
            await self.app.start()
            
            logger.info("🚀 БОТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ!")
            logger.info(f"📊 Парсер каналов: {'✅ Активен' if self.parser_running else '❌ Отключен'}")
            
            if self.parser_running:
                status = self.channel_parser.get_parsing_status()
                logger.info(f"🔍 Отслеживается каналов: {status['channels_count']}")
                logger.info(f"⏱️ Интервал парсинга: {status['interval']} сек")
                logger.info(f"🎯 Минимальный скор лидов: {status['min_score']}")
            
            # Запускаем polling
            await self.app.run_polling(
                allowed_updates=['message', 'callback_query'], 
                drop_pending_updates=True
            )
                
        except Exception as e:
            logger.error(f"Критическая ошибка запуска: {e}")
            raise

    def shutdown(self):
        """Корректное завершение работы"""
        logger.info("Начало завершения работы...")
        
        try:
            if self.channel_parser and self.parser_running:
                logger.info("Остановка парсера каналов...")
                # Останавливаем парсер
                asyncio.run(self.channel_parser.stop_parsing())
                logger.info("Парсер остановлен")
        except Exception as e:
            logger.error(f"Ошибка остановки парсера: {e}")

def main():
    """Главная функция"""
    bot = None
    try:
        # Настройка event loop для Windows
        if sys.platform.startswith("win") and sys.version_info >= (3, 8):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        # Создаем и запускаем бота
        logger.info("Создание экземпляра бота...")
        bot = AIBot()
        
        logger.info("Запуск основного цикла...")
        asyncio.run(bot.run())
        
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки (Ctrl+C)")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        if bot:
            try:
                bot.shutdown()
            except Exception as e:
                logger.error(f"Ошибка при завершении: {e}")
        logger.info("Бот остановлен")

if __name__ == "__main__":
    main()
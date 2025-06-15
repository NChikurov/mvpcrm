#!/usr/bin/env python3
"""
AI CRM Bot - Главный файл с AI Context Parser - ИСПРАВЛЕННАЯ ВЕРСИЯ
"""

import asyncio
import logging
import sys
import os
from pathlib import Path
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

from utils.config_loader import load_config, print_config_summary
from database.operations import init_database
from database.db_migration import migrate_database_for_ai
from handlers.user import UserHandler
from handlers.admin import AdminHandler
from myparser.ai_context_parser import AIContextParser

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Отключаем HTTP спам
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

class AIBot:
    """Главный класс AI CRM бота"""
    
    def __init__(self):
        logger.info("Создание экземпляра AI бота...")
        
        # Загружаем конфигурацию
        self.config = load_config()
        print_config_summary(self.config)
        
        # Показываем конфигурацию AI парсинга
        parsing_config = self.config.get('parsing', {})
        logger.info("🤖 Конфигурация AI парсинга:")
        logger.info(f"    Включен: {parsing_config.get('enabled', False)}")
        logger.info(f"    Каналы: {parsing_config.get('channels', [])}")
        logger.info(f"    Мин. скор: {parsing_config.get('min_interest_score', 60)}")
        logger.info(f"    Интервал: {parsing_config.get('parse_interval', 3600)} сек")
        
        self.app = None
        self.user_handler = None
        self.admin_handler = None
        self.ai_parser = None

    async def setup_bot(self):
        """Настройка бота"""
        logger.info("Запуск настройки AI бота...")
        
        # Мигрируем базу данных для поддержки AI
        logger.info("Выполняется миграция базы данных для AI...")
        await migrate_database_for_ai()
        
        # Инициализируем базу данных
        await init_database()
        logger.info("База данных инициализирована")
        
        # Создаем приложение Telegram
        bot_token = self.config['bot']['token']
        self.app = Application.builder().token(bot_token).build()
        logger.info("Telegram Application создан")
        
        # Инициализируем обработчики
        self.user_handler = UserHandler(self.config)
        self.admin_handler = AdminHandler(self.config)
        logger.info("Обработчики инициализированы")
        
        # Регистрируем обработчики
        self.register_handlers()
        logger.info("Обработчики зарегистрированы")
        
        # Инициализируем AI парсер
        self.ai_parser = AIContextParser(self.config)
        logger.info("🤖 AI Context Parser инициализирован")

    def register_handlers(self):
        """Регистрация обработчиков команд и сообщений"""
        # Команды
        self.app.add_handler(CommandHandler("start", self.user_handler.start))
        self.app.add_handler(CommandHandler("help", self.user_handler.help_command))
        self.app.add_handler(CommandHandler("menu", self.user_handler.menu))
        self.app.add_handler(CommandHandler("admin", self.admin_handler.admin_panel))
        self.app.add_handler(CommandHandler("broadcast", self.admin_handler.broadcast))
        
        # Обработка всех текстовых сообщений
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            self.handle_any_message
        ))
        
        # Callback обработчики
        self.app.add_handler(self.admin_handler.callback_handler)
        self.app.add_handler(self.user_handler.callback_handler)
        
        logger.info("Все обработчики успешно зарегистрированы")

    async def handle_any_message(self, update, context):
        """Универсальный обработчик сообщений с AI анализом"""
        try:
            if not update.message or not update.message.text:
                return
            
            chat = update.effective_chat
            user = update.effective_user
            message_text = update.message.text
            
            # Логируем получение сообщения
            logger.info("📨 ПОЛУЧЕНО СООБЩЕНИЕ:")
            logger.info(f"    💬 Текст: '{message_text[:50]}...'")
            logger.info(f"    👤 От: {user.id} (@{user.username})")
            logger.info(f"    📍 Чат: {chat.id} ({chat.type})")
            logger.info(f"    📝 Название: {chat.title}")
            
            # Определяем тип обработки
            if chat.type == 'private':
                # Личные сообщения - обычная обработка
                logger.info("📱 Личное сообщение - обычная обработка")
                await self.user_handler.handle_message(update, context)
                
            elif chat.type in ['group', 'supergroup', 'channel']:
                # Групповые сообщения - проверяем AI парсинг
                logger.info("📺 Групповое сообщение - проверяем AI парсинг")
                
                # Проверяем, включен ли AI парсинг
                if self.ai_parser and self.ai_parser.enabled:
                    # Проверяем, отслеживается ли канал
                    is_monitored = self.ai_parser.is_channel_monitored(chat.id, chat.username)
                    
                    logger.info(f"    ⚙️  AI парсинг включен: {self.ai_parser.enabled}")
                    logger.info(f"    📋 Настроенные каналы: {self.ai_parser.channels}")
                    logger.info(f"    🎯 Отслеживается: {'ДА' if is_monitored else 'НЕТ'}")
                    
                    if is_monitored:
                        logger.info(f"    ✅ Совпадение по: ID {chat.id}")
                        logger.info("🤖 ОТПРАВЛЯЕМ НА AI АНАЛИЗ!")
                        
                        # Отправляем на AI анализ
                        await self.ai_parser.process_message(update, context)
                    else:
                        logger.info("⏭️ Пропускаем: канал не отслеживается")
                else:
                    logger.info("⏭️ Пропускаем: AI парсинг отключен")
            
            logger.info("────────────────────────────────────────────────────────────")
            
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            import traceback
            traceback.print_exc()

    async def check_channels_access(self):
        """Проверка доступа к настроенным каналам"""
        if not self.ai_parser or not self.ai_parser.channels:
            return
        
        bot_info = await self.app.bot.get_me()
        logger.info("🤖 Информация о боте:")
        logger.info(f"    Username: @{bot_info.username}")
        logger.info(f"    ID: {bot_info.id}")
        
        for channel in self.ai_parser.channels:
            try:
                logger.info(f"📺 Проверяем канал: {channel}")
                
                # Получаем информацию о канале
                chat = await self.app.bot.get_chat(channel)
                logger.info(f"    ✅ Канал найден: {chat.title}")
                logger.info(f"    🆔 ID: {chat.id}")
                logger.info(f"    📊 Тип: {chat.type}")
                
                # Проверяем статус бота в канале
                bot_member = await self.app.bot.get_chat_member(chat.id, bot_info.id)
                logger.info(f"    👤 Статус бота: {bot_member.status}")
                
                if bot_member.status in ['administrator', 'member']:
                    logger.info("    ✅ Бот имеет доступ к каналу")
                else:
                    logger.warning(f"    ⚠️  Бот не имеет доступа: {bot_member.status}")
                    
            except Exception as e:
                logger.error(f"    ❌ Ошибка доступа к каналу {channel}: {e}")

    async def run(self):
        """Запуск бота"""
        await self.setup_bot()
        
        logger.info("Бот готов к работе")
        logger.info(f"Запуск AI бота: {self.config['bot']['name']}")
        logger.info(f"Админы: {self.config['bot']['admin_ids']}")
        
        # Проверяем доступ к каналам
        async with self.app:
            await self.app.initialize()
            await self.app.start()
            
            await self.check_channels_access()
            
            logger.info("🚀 AI БОТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ!")
            
            if self.ai_parser and self.ai_parser.channels:
                logger.info(f"🤖 AI мониторинг активен для {len(self.ai_parser.channels)} каналов:")
                for channel in self.ai_parser.channels:
                    logger.info(f"    - {channel}")
                logger.info("💡 Отправьте сообщения в отслеживаемые каналы для AI анализа")
            else:
                logger.warning("⚠️  AI парсинг отключен или каналы не настроены")
            
            # Запускаем polling
            await self.app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=['message', 'callback_query']
            )
            
            # Ждем завершения
            await asyncio.Future()

def main():
    """Главная функция"""
    try:
        bot = AIBot()
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        logger.info("AI Бот остановлен")
        logger.info("Завершение работы")

if __name__ == "__main__":
    main()
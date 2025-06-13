#!/usr/bin/env python3
"""
AI-CRM Telegram Bot MVP
"""
import asyncio
import logging
import sys
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
            self.running = False
            
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
            
            logger.info("Бот готов к работе")
            
        except Exception as e:
            logger.error(f"Ошибка настройки бота: {e}")
            raise

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
            
            # Обработчик всех текстовых сообщений (включая из групп)
            self.app.add_handler(MessageHandler(
                filters.TEXT & ~filters.COMMAND, 
                self.handle_any_message
            ))
            
            # Callback обработчики - ВАЖЕН ПОРЯДОК!
            # Сначала админские (более специфичные)
            self.app.add_handler(self.admin_handler.callback_handler)
            # Потом пользовательские (общие)
            self.app.add_handler(self.user_handler.callback_handler)
            
            logger.info("Все обработчики успешно зарегистрированы")
            
        except Exception as e:
            logger.error(f"Ошибка регистрации обработчиков: {e}")
            raise

    async def handle_any_message(self, update, context):
        """Обработка всех сообщений (личные + группы)"""
        try:
            # Проверяем что это текстовое сообщение
            if not update.message or not update.message.text:
                return
            
            chat_type = update.effective_chat.type
            chat_id = update.effective_chat.id
            user_id = update.effective_user.id
            message_text = update.message.text.strip()
            
            # Пропускаем пустые сообщения
            if not message_text:
                return
            
            logger.info(f"🔄 ПОЛУЧЕНО СООБЩЕНИЕ: {chat_type} чат {chat_id}, от {user_id}: '{message_text[:50]}...'")
            
            # Если это личное сообщение - обрабатываем как обычно
            if chat_type == 'private':
                logger.info(f"📱 Обрабатываем личное сообщение от {user_id}")
                await self.user_handler.handle_message(update, context)
            
            # Если это группа/канал - обрабатываем через парсер
            elif chat_type in ['group', 'supergroup', 'channel']:
                # Проверяем, отслеживается ли этот канал/группа
                channels = self.config.get('parsing', {}).get('channels', [])
                chat_username = getattr(update.effective_chat, 'username', None)
                
                logger.info(f"📺 Сообщение из {chat_type}: {chat_id} (@{chat_username})")
                logger.info(f"📋 Отслеживаемые каналы: {channels}")
                
                # Проверяем по ID или username
                is_monitored = False
                if str(chat_id) in [str(ch) for ch in channels]:
                    is_monitored = True
                    logger.info(f"✅ Канал найден по ID: {chat_id}")
                elif chat_username and f"@{chat_username}" in channels:
                    is_monitored = True
                    logger.info(f"✅ Канал найден по username: @{chat_username}")
                
                parsing_enabled = self.config.get('parsing', {}).get('enabled', False)
                logger.info(f"🔧 Парсинг включен: {parsing_enabled}")
                
                if is_monitored and parsing_enabled:
                    logger.info(f"🎯 Обрабатываем сообщение из отслеживаемой группы {chat_id}")
                    await self.channel_parser.process_message(update, context)
                else:
                    logger.info(f"⏭️ Группа {chat_id} не отслеживается или парсинг отключен")
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки сообщения: {e}")
            import traceback
            traceback.print_exc()

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
            
            self.running = True
            
            logger.info("🚀 БОТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ!")
            
            # Информация о парсере
            if self.config.get('parsing', {}).get('enabled'):
                channels = self.config.get('parsing', {}).get('channels', [])
                logger.info(f"🔍 Отслеживается каналов/групп: {len(channels)}")
                for channel in channels:
                    logger.info(f"   - {channel}")
            else:
                logger.info("🔍 Парсинг каналов отключен")
            
            # Правильный запуск с async context manager
            async with self.app:
                await self.app.start()
                await self.app.updater.start_polling(
                    allowed_updates=['message', 'callback_query'], 
                    drop_pending_updates=True
                )
                
                # Ждем бесконечно
                try:
                    await asyncio.Future()  # Это будет ждать пока не будет отменено
                except asyncio.CancelledError:
                    logger.info("Получен сигнал остановки")
                finally:
                    await self.app.updater.stop()
                    await self.app.stop()
                
        except Exception as e:
            logger.error(f"Критическая ошибка запуска: {e}")
            raise
        finally:
            self.running = False
            logger.info("Бот остановлен")

def main():
    """Главная функция"""
    try:
        # Настройка event loop для Windows
        if sys.platform.startswith("win") and sys.version_info >= (3, 8):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
        # Создаем и запускаем бота
        logger.info("Создание экземпляра бота...")
        bot = AIBot()
        
        logger.info("Запуск основного цикла...")
        
        # Запускаем бота
        asyncio.run(bot.run())
        
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки (Ctrl+C)")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        logger.info("Завершение работы")

if __name__ == "__main__":
    main()
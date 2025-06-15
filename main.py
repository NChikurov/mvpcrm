#!/usr/bin/env python3
"""
AI-CRM Telegram Bot MVP с отладкой парсинга
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

# Настройка логирования с фильтрацией спама
class NoHTTPFilter(logging.Filter):
    """Фильтр для отключения спама HTTP запросов"""
    def filter(self, record):
        # Блокируем HTTP логи от httpx и telegram
        if 'httpx' in record.name.lower():
            return False
        if 'HTTP Request: POST https://api.telegram.org' in record.getMessage():
            return False
        return True

# Применяем фильтр
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)

# Добавляем фильтр ко всем обработчикам
for handler in logging.getLogger().handlers:
    handler.addFilter(NoHTTPFilter())

# Отключаем конкретные логгеры
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)

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
            
            # Дополнительная отладочная информация
            self._log_parsing_config()
            
        except Exception as e:
            logger.error(f"Ошибка инициализации конфигурации: {e}")
            raise

    def _log_parsing_config(self):
        """Логирование конфигурации парсинга"""
        parsing_config = self.config.get('parsing', {})
        logger.info("🔧 Конфигурация парсинга:")
        logger.info(f"   Включен: {parsing_config.get('enabled', False)}")
        logger.info(f"   Каналы: {parsing_config.get('channels', [])}")
        logger.info(f"   Мин. скор: {parsing_config.get('min_interest_score', 60)}")
        logger.info(f"   Интервал: {parsing_config.get('parse_interval', 3600)} сек")
        
        if parsing_config.get('parse_interval', 3600) > 300:
            logger.warning("⚠️ Интервал парсинга больше 5 минут - лиды могут обрабатываться медленно!")

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
            # Сначала админские (более специфичные с pattern)
            self.app.add_handler(self.admin_handler.callback_handler)
            # Потом пользовательские (с pattern для пользовательских callback)
            self.app.add_handler(self.user_handler.callback_handler)
            
            logger.info("Все обработчики успешно зарегистрированы")
            
        except Exception as e:
            logger.error(f"Ошибка регистрации обработчиков: {e}")
            raise

    async def handle_any_message(self, update, context):
        """Обработка всех сообщений (личные + группы) с детальным логированием"""
        try:
            # Проверяем что это текстовое сообщение
            if not update.message or not update.message.text:
                return
            
            chat_type = update.effective_chat.type
            chat_id = update.effective_chat.id
            user_id = update.effective_user.id
            message_text = update.message.text.strip()
            chat_username = getattr(update.effective_chat, 'username', None)
            chat_title = getattr(update.effective_chat, 'title', None)
            
            # Пропускаем пустые сообщения
            if not message_text:
                return
            
            # Детальное логирование каждого сообщения
            logger.info(f"📨 ПОЛУЧЕНО СООБЩЕНИЕ:")
            logger.info(f"   💬 Текст: '{message_text[:100]}...'")
            logger.info(f"   👤 От: {user_id} (@{getattr(update.effective_user, 'username', 'без username')})")
            logger.info(f"   📍 Чат: {chat_id} ({chat_type})")
            if chat_username:
                logger.info(f"   🏷️  Username: @{chat_username}")
            if chat_title:
                logger.info(f"   📝 Название: {chat_title}")
            
            # Если это личное сообщение - обрабатываем как обычно
            if chat_type == 'private':
                logger.info(f"📱 Обрабатываем как личное сообщение")
                await self.user_handler.handle_message(update, context)
            
            # Если это группа/канал - обрабатываем через парсер
            elif chat_type in ['group', 'supergroup', 'channel']:
                # Проверяем, отслеживается ли этот канал/группа
                channels = self.config.get('parsing', {}).get('channels', [])
                parsing_enabled = self.config.get('parsing', {}).get('enabled', False)
                
                logger.info(f"📺 Проверяем группу/канал:")
                logger.info(f"   ⚙️  Парсинг включен: {parsing_enabled}")
                logger.info(f"   📋 Настроенные каналы: {channels}")
                
                # Проверяем по ID или username
                is_monitored = False
                matched_by = None
                
                # Проверка по ID
                if str(chat_id) in [str(ch) for ch in channels]:
                    is_monitored = True
                    matched_by = f"ID {chat_id}"
                # Проверка по username
                elif chat_username and f"@{chat_username}" in channels:
                    is_monitored = True
                    matched_by = f"Username @{chat_username}"
                
                logger.info(f"   🎯 Отслеживается: {'ДА' if is_monitored else 'НЕТ'}")
                if matched_by:
                    logger.info(f"   ✅ Совпадение по: {matched_by}")
                
                if is_monitored and parsing_enabled:
                    logger.info(f"🚀 ОТПРАВЛЯЕМ НА ПАРСИНГ!")
                    
                    # Быстрая проверка на CRM слова для отладки
                    crm_words = ['crm', 'црм', 'автоматизация', 'система', 'ищу']
                    found_words = [word for word in crm_words if word.lower() in message_text.lower()]
                    
                    if found_words:
                        logger.info(f"🔥 ОБНАРУЖЕНЫ CRM СЛОВА: {found_words}")
                        logger.info(f"🎯 ВЫСОКАЯ ВЕРОЯТНОСТЬ ЛИДА!")
                    
                    await self.channel_parser.process_message(update, context)
                else:
                    reasons = []
                    if not parsing_enabled:
                        reasons.append("парсинг отключен")
                    if not is_monitored:
                        reasons.append("канал не отслеживается")
                    
                    logger.info(f"⏭️ Пропускаем: {', '.join(reasons)}")
            
            logger.info("─" * 60)
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки сообщения: {e}")
            import traceback
            traceback.print_exc()

    async def check_bot_permissions(self):
        """Проверка прав бота в каналах"""
        try:
            bot_info = await self.app.bot.get_me()
            logger.info(f"🤖 Информация о боте:")
            logger.info(f"   Username: @{bot_info.username}")
            logger.info(f"   ID: {bot_info.id}")
            
            # Проверяем каналы
            channels = self.config.get('parsing', {}).get('channels', [])
            for channel in channels:
                try:
                    logger.info(f"📺 Проверяем канал: {channel}")
                    
                    # Получаем информацию о чате
                    if channel.startswith('@'):
                        chat_info = await self.app.bot.get_chat(channel)
                    else:
                        chat_info = await self.app.bot.get_chat(int(channel))
                    
                    logger.info(f"   ✅ Канал найден: {chat_info.title}")
                    logger.info(f"   🆔 ID: {chat_info.id}")
                    logger.info(f"   📊 Тип: {chat_info.type}")
                    
                    # Проверяем статус бота в канале
                    bot_member = await self.app.bot.get_chat_member(chat_info.id, bot_info.id)
                    logger.info(f"   👤 Статус бота: {bot_member.status}")
                    
                    if bot_member.status == 'administrator':
                        logger.info(f"   ✅ Бот является администратором")
                        
                        # Проверяем специфичные права
                        if hasattr(bot_member, 'can_read_all_group_messages'):
                            can_read = bot_member.can_read_all_group_messages
                            logger.info(f"   📖 Может читать сообщения: {can_read}")
                            if not can_read:
                                logger.warning(f"   ⚠️ У бота нет прав на чтение сообщений!")
                        
                    elif bot_member.status == 'member':
                        logger.warning(f"   ⚠️ Бот обычный участник (не админ)")
                        logger.warning(f"   💡 Рекомендуется сделать бота администратором")
                    else:
                        logger.error(f"   ❌ Проблемный статус: {bot_member.status}")
                        
                except Exception as channel_error:
                    logger.error(f"   ❌ Ошибка проверки канала {channel}: {channel_error}")
                    
        except Exception as e:
            logger.error(f"Ошибка проверки прав бота: {e}")

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
            
            # Проверяем права в каналах
            await self.check_bot_permissions()
            
            self.running = True
            
            logger.info("🚀 БОТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ!")
            
            # Информация о парсере
            if self.config.get('parsing', {}).get('enabled'):
                channels = self.config.get('parsing', {}).get('channels', [])
                logger.info(f"🔍 Отслеживается каналов/групп: {len(channels)}")
                for channel in channels:
                    logger.info(f"   - {channel}")
                    
                # Предупреждение о большом интервале парсинга
                interval = self.config.get('parsing', {}).get('parse_interval', 3600)
                if interval > 300:  # Больше 5 минут
                    logger.warning(f"⚠️ Интервал парсинга большой ({interval} сек). Рекомендуется 60-300 сек для реального времени")
                
                logger.info("📨 Теперь отправьте сообщение 'Ищу CRM систему' в отслеживаемый канал для проверки")
            else:
                logger.info("🔍 Парсинг каналов отключен")
            
            # Правильный запуск с async context manager
            async with self.app:
                await self.app.start()
                # Запускаем polling с уменьшенным таймаутом для более быстрой обработки
                await self.app.updater.start_polling(
                    allowed_updates=['message', 'callback_query'], 
                    drop_pending_updates=True,
                    poll_interval=1.0,  # Проверяем сообщения каждую секунду
                    timeout=10  # Таймаут запроса к Telegram API
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
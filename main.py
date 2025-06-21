#!/usr/bin/env python3
"""
ИСПРАВЛЕННЫЙ AI CRM Bot - main.py
Устраняет проблемы с импортами и логикой работы
"""

import asyncio
import logging
import sys
import os
from pathlib import Path
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

from utils.config_loader import load_config, print_config_summary, get_config_validation_report
from database.operations import init_database
from database.db_migration import migrate_database_for_ai
from database.dialogue_db_migration import migrate_database_for_dialogues
from handlers.user import UserHandler
from handlers.admin import AdminHandler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Отключаем HTTP спам
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

class FixedAIBot:
    """ИСПРАВЛЕННЫЙ класс AI CRM бота"""
    
    def __init__(self):
        logger.info("🚀 Создание ИСПРАВЛЕННОГО AI бота...")
        
        # Загружаем конфигурацию
        self.config = load_config()
        
        # Валидируем конфигурацию
        validation_report = get_config_validation_report(self.config)
        self._print_validation_report(validation_report)
        
        if not validation_report['valid']:
            raise ValueError("Критические ошибки конфигурации")
        
        print_config_summary(self.config)
        self._print_ai_parsing_config()
        
        self.app = None
        self.user_handler = None
        self.admin_handler = None
        self.ai_parser = None

    def _print_validation_report(self, report):
        """Вывод отчета о валидации"""
        logger.info("=== ОТЧЕТ ВАЛИДАЦИИ КОНФИГУРАЦИИ ===")
        
        if report['errors']:
            logger.error("❌ КРИТИЧЕСКИЕ ОШИБКИ:")
            for error in report['errors']:
                logger.error(f"   • {error}")
        
        if report['warnings']:
            logger.warning("⚠️  ПРЕДУПРЕЖДЕНИЯ:")
            for warning in report['warnings']:
                logger.warning(f"   • {warning}")
        
        info = report['info']
        logger.info("ℹ️  ИНФОРМАЦИЯ:")
        logger.info(f"   • Бот: {info['bot_name']}")
        logger.info(f"   • Админов: {info['admin_count']}")
        logger.info(f"   • Claude API: {'✅' if info['claude_enabled'] else '❌'}")
        logger.info(f"   • Парсинг: {'✅' if info['parsing_enabled'] else '❌'}")
        logger.info(f"   • Каналов: {info['channels_count']}")
        
        logger.info("=====================================")

    def _print_ai_parsing_config(self):
        """Вывод конфигурации AI парсинга"""
        parsing_config = self.config.get('parsing', {})
        logger.info("🤖 КОНФИГУРАЦИЯ AI ПАРСИНГА:")
        logger.info(f"    ⚙️  Общий парсинг: {'✅' if parsing_config.get('enabled', False) else '❌'}")
        logger.info(f"    👥 Анализ диалогов: {'✅' if parsing_config.get('dialogue_analysis_enabled', True) else '❌'}")
        logger.info(f"    📊 Мин. скор: {parsing_config.get('min_confidence_score', 60)}")
        logger.info(f"    📺 Каналов: {len(parsing_config.get('channels', []))}")
        logger.info(f"    🕐 Интервал: {parsing_config.get('parse_interval', 3600)} сек")
        
        channels = parsing_config.get('channels', [])
        if channels:
            logger.info("    📋 Отслеживаемые каналы:")
            for i, channel in enumerate(channels[:5], 1):
                logger.info(f"       {i}. {channel}")
        else:
            logger.warning("    ⚠️  Каналы не настроены!")

    async def setup_bot(self):
        """Настройка бота"""
        logger.info("🔧 Запуск настройки ИСПРАВЛЕННОГО AI бота...")
        
        # Мигрируем базу данных
        logger.info("📊 Миграция базы данных для AI...")
        await migrate_database_for_ai()
        
        logger.info("💬 Миграция базы данных для диалогов...")
        await migrate_database_for_dialogues()
        
        # Инициализируем базу данных
        await init_database()
        logger.info("✅ База данных инициализирована")
        
        # Создаем приложение Telegram
        bot_token = self.config['bot']['token']
        self.app = Application.builder().token(bot_token).build()
        logger.info("✅ Telegram Application создан")
        
        # Инициализируем обработчики
        self.user_handler = UserHandler(self.config)
        self.admin_handler = AdminHandler(self.config)
        logger.info("✅ Обработчики инициализированы")
        
        # ИСПРАВЛЕНО: Безопасная инициализация AI парсера
        await self._initialize_ai_parser_safely()
        
        # Регистрируем обработчики
        self.register_handlers()
        logger.info("✅ Обработчики зарегистрированы")

    async def _initialize_ai_parser_safely(self):
        """ИСПРАВЛЕННАЯ безопасная инициализация AI парсера"""
        try:
            logger.info("🤖 Инициализация ИСПРАВЛЕННОГО AI парсера...")
            
            # Импортируем исправленный парсер
            from myparser import UnifiedAIParser
            
            self.ai_parser = UnifiedAIParser(self.config)
            logger.info("✅ ИСПРАВЛЕННЫЙ UnifiedAIParser успешно инициализирован")
            
            # Сохраняем ссылку для других компонентов
            self.app.bot_data['ai_parser'] = self.ai_parser
            
        except ImportError as e:
            logger.error(f"❌ Не удалось импортировать исправленный парсер: {e}")
            
            # Fallback на минимальный парсер
            try:
                from myparser import AIContextParser
                self.ai_parser = AIContextParser(self.config)
                logger.info("✅ Fallback AI Parser инициализирован")
                self.app.bot_data['ai_parser'] = self.ai_parser
            except Exception as fallback_error:
                logger.error(f"❌ Критическая ошибка - никакой парсер недоступен: {fallback_error}")
                self.ai_parser = None
                
        except Exception as e:
            logger.error(f"❌ Критическая ошибка инициализации AI парсера: {e}")
            self.ai_parser = None

    def register_handlers(self):
        """Регистрация обработчиков"""
        # Основные команды
        self.app.add_handler(CommandHandler("start", self.user_handler.start))
        self.app.add_handler(CommandHandler("help", self.user_handler.help_command))
        self.app.add_handler(CommandHandler("menu", self.user_handler.menu))
        
        # Админские команды
        self.app.add_handler(CommandHandler("admin", self.admin_handler.admin_panel))
        self.app.add_handler(CommandHandler("broadcast", self.admin_handler.broadcast))
        self.app.add_handler(CommandHandler("stats", self.admin_handler.show_stats))
        
        # Команды для диалогов
        self.app.add_handler(CommandHandler("status", self.show_parser_status))
        self.app.add_handler(CommandHandler("dialogues", self.show_active_dialogues))
        self.app.add_handler(CommandHandler("health", self.ai_health_check))
        
        # Обработка текстовых сообщений
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            self.handle_any_message
        ))
        
        # Callback обработчики
        self.app.add_handler(self.admin_handler.callback_handler)
        self.app.add_handler(self.user_handler.callback_handler)
        
        logger.info("✅ Все обработчики зарегистрированы")

    async def show_parser_status(self, update, context):
        """Показать статус AI парсера"""
        user_id = update.effective_user.id
        admin_ids = self.config.get('bot', {}).get('admin_ids', [])
        
        if user_id not in admin_ids:
            await update.message.reply_text("❌ Эта команда доступна только администраторам")
            return
        
        try:
            if self.ai_parser:
                status = self.ai_parser.get_status()
                
                message = "🤖 <b>Статус ИСПРАВЛЕННОГО AI парсера</b>\n\n"
                message += f"⚙️ <b>Основные настройки:</b>\n"
                message += f"• Включен: {'✅' if status['enabled'] else '❌'}\n"
                message += f"• Режим: {status.get('mode', 'unknown')}\n"
                message += f"• Каналов: {status['channels_count']}\n"
                message += f"• Мин. скор: {status['min_confidence_score']}%\n\n"
                
                if status.get('dialogue_tracker'):
                    dt_status = status['dialogue_tracker']
                    message += f"👥 <b>Анализ диалогов:</b>\n"
                    message += f"• Активных диалогов: {dt_status['active_dialogues']}\n"
                    message += f"• Мин. участников: {dt_status['min_participants']}\n"
                    message += f"• Мин. сообщений: {dt_status['min_messages']}\n"
                    message += f"• Таймаут: {dt_status['dialogue_timeout_minutes']:.0f} мин\n\n"
                
                message += f"📋 <b>Отслеживаемые каналы:</b>\n"
                for i, channel in enumerate(status['channels'][:5], 1):
                    message += f"{i}. <code>{channel}</code>\n"
                
                await update.message.reply_text(message, parse_mode='HTML')
            else:
                await update.message.reply_text("❌ AI парсер не инициализирован")
                
        except Exception as e:
            logger.error(f"Ошибка получения статуса: {e}")
            await update.message.reply_text("❌ Ошибка получения статуса")

    async def show_active_dialogues(self, update, context):
        """Показать активные диалоги"""
        user_id = update.effective_user.id
        admin_ids = self.config.get('bot', {}).get('admin_ids', [])
        
        if user_id not in admin_ids:
            await update.message.reply_text("❌ Эта команда доступна только администраторам")
            return
        
        try:
            if (self.ai_parser and 
                hasattr(self.ai_parser, 'dialogue_tracker') and 
                self.ai_parser.dialogue_tracker):
                
                active_dialogues = self.ai_parser.dialogue_tracker.active_dialogues
                
                if not active_dialogues:
                    await update.message.reply_text("📭 Активных диалогов нет")
                    return
                
                message = f"👥 <b>Активные диалоги ({len(active_dialogues)})</b>\n\n"
                
                for dialogue_id, dialogue in list(active_dialogues.items())[:10]:
                    duration = (dialogue.last_activity - dialogue.start_time).total_seconds() / 60
                    participants_count = len(dialogue.participants)
                    messages_count = len(dialogue.messages)
                    
                    message += f"🔹 <b>{dialogue_id[-20:]}...</b>\n"
                    message += f"   📺 {dialogue.channel_title}\n"
                    message += f"   👥 {participants_count} участ. 💬 {messages_count} сообщ.\n"
                    message += f"   ⏱️ {duration:.0f} мин 🏢 {'Да' if dialogue.is_business_related else 'Нет'}\n\n"
                
                await update.message.reply_text(message, parse_mode='HTML')
            else:
                await update.message.reply_text("❌ Анализ диалогов недоступен")
                
        except Exception as e:
            logger.error(f"Ошибка получения диалогов: {e}")
            await update.message.reply_text("❌ Ошибка получения диалогов")

    async def ai_health_check(self, update, context):
        """Проверка здоровья AI"""
        user_id = update.effective_user.id
        admin_ids = self.config.get('bot', {}).get('admin_ids', [])
        
        if user_id not in admin_ids:
            await update.message.reply_text("❌ Эта команда доступна только администраторам")
            return
        
        try:
            from ai.claude_client import get_claude_client
            
            message = "🤖 <b>Проверка здоровья ИСПРАВЛЕННОЙ AI системы</b>\n\n"
            
            # Claude API
            claude_client = get_claude_client()
            if claude_client:
                try:
                    health = await claude_client.health_check()
                    stats = claude_client.get_usage_stats()
                    
                    message += f"🧠 <b>Claude API:</b> {'✅' if health else '❌'}\n"
                    message += f"• Модель: {stats['model']}\n"
                    message += f"• Статус: {stats['status']}\n\n"
                except:
                    message += f"🧠 <b>Claude API:</b> ❌ Ошибка проверки\n\n"
            else:
                message += f"🧠 <b>Claude API:</b> ❌ Не инициализирован\n\n"
            
            # AI парсер
            if self.ai_parser:
                status = self.ai_parser.get_status()
                message += f"🔍 <b>AI Парсер:</b> ✅ Работает\n"
                message += f"• Режим: {status.get('mode', 'unknown')}\n"
                message += f"• Каналов: {status['channels_count']}\n"
                
                if status.get('dialogue_tracker'):
                    message += f"• Активных диалогов: {status['dialogue_tracker']['active_dialogues']}\n"
            else:
                message += f"🔍 <b>AI Парсер:</b> ❌ Недоступен\n"
            
            await update.message.reply_text(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Ошибка проверки здоровья: {e}")
            await update.message.reply_text(f"❌ Ошибка: {e}")

    async def handle_any_message(self, update, context):
        """ИСПРАВЛЕННЫЙ универсальный обработчик сообщений"""
        try:
            if not update.message or not update.message.text:
                return
            
            chat = update.effective_chat
            user = update.effective_user
            message_text = update.message.text
            
            logger.info("📨 ПОЛУЧЕНО СООБЩЕНИЕ:")
            logger.info(f"    💬 Текст: '{message_text[:100]}{'...' if len(message_text) > 100 else ''}'")
            logger.info(f"    👤 От: {user.id} (@{user.username or 'no_username'})")
            logger.info(f"    📍 Чат: {chat.id} ({chat.type})")
            logger.info(f"    📝 Название: {chat.title or 'Без названия'}")
            
            if chat.type == 'private':
                # Личные сообщения
                logger.info("📱 Личное сообщение - стандартная обработка")
                await self.user_handler.handle_message(update, context)
                
            elif chat.type in ['group', 'supergroup', 'channel']:
                # Групповые сообщения - AI парсинг
                logger.info("📺 Групповое сообщение - AI парсинг")
                
                if not self.ai_parser:
                    logger.warning("⚠️ AI парсер не инициализирован")
                    return
                
                if not self.ai_parser.enabled:
                    logger.info("⚠️ AI парсинг отключен")
                    return
                
                # Проверяем мониторинг канала
                is_monitored = self.ai_parser.is_channel_monitored(chat.id, chat.username)
                
                logger.info(f"    ⚙️  Включен: {self.ai_parser.enabled}")
                logger.info(f"    🎯 Отслеживается: {'ДА' if is_monitored else 'НЕТ'}")
                
                if is_monitored:
                    logger.info("🤖 ЗАПУСКАЕМ ИСПРАВЛЕННЫЙ AI АНАЛИЗ!")
                    
                    try:
                        await self.ai_parser.process_message(update, context)
                        logger.info("✅ AI анализ завершен успешно")
                    except Exception as ai_error:
                        logger.error(f"❌ Ошибка AI анализа: {ai_error}")
                else:
                    logger.info("⏭️ Канал не отслеживается")
            
            logger.info("────────────────────────────────────────")
            
        except Exception as e:
            logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА обработки: {e}")
            import traceback
            traceback.print_exc()

    async def check_channels_access(self):
        """Проверка доступа к каналам"""
        if not self.ai_parser:
            return
        
        status = self.ai_parser.get_status()
        channels = status.get('channels', [])
        
        if not channels:
            logger.warning("⚠️ Каналы не настроены")
            return
        
        bot_info = await self.app.bot.get_me()
        logger.info("🤖 Информация о боте:")
        logger.info(f"    Username: @{bot_info.username}")
        logger.info(f"    ID: {bot_info.id}")
        
        for channel in channels:
            try:
                logger.info(f"📺 Проверяем канал: {channel}")
                
                chat = await self.app.bot.get_chat(channel)
                logger.info(f"    ✅ Канал найден: {chat.title}")
                logger.info(f"    🆔 ID: {chat.id}")
                logger.info(f"    📊 Тип: {chat.type}")
                
                bot_member = await self.app.bot.get_chat_member(chat.id, bot_info.id)
                logger.info(f"    👤 Статус бота: {bot_member.status}")
                
                if bot_member.status in ['administrator', 'member']:
                    logger.info("    ✅ Бот имеет доступ к каналу")
                else:
                    logger.warning(f"    ⚠️  Проблемы доступа: {bot_member.status}")
                    
            except Exception as e:
                logger.error(f"    ❌ Ошибка доступа к {channel}: {e}")

    async def run(self):
        """Запуск бота"""
        await self.setup_bot()
        
        logger.info("✅ Бот готов к работе")
        logger.info(f"🚀 Запуск ИСПРАВЛЕННОГО AI бота: {self.config['bot']['name']}")
        logger.info(f"👑 Админы: {self.config['bot']['admin_ids']}")
        
        # Проверяем доступ к каналам
        async with self.app:
            await self.app.initialize()
            await self.app.start()
            
            await self.check_channels_access()
            
            logger.info("🎉 ИСПРАВЛЕННЫЙ AI БОТ ЗАПУЩЕН!")
            
            # Информация о режиме работы
            if self.ai_parser:
                status = self.ai_parser.get_status()
                channels = status.get('channels', [])
                
                if channels:
                    logger.info(f"🤖 AI мониторинг активен для {len(channels)} каналов:")
                    for channel in channels:
                        logger.info(f"    - {channel}")
                    
                    logger.info(f"🎯 РЕЖИМ: {status.get('mode', 'unknown')}")
                    logger.info("💡 Отправьте сообщения в группы для анализа")
                    logger.info("💡 Используйте /status для проверки")
                    logger.info("💡 Используйте /dialogues для просмотра диалогов")
                    logger.info("💡 Используйте /health для проверки AI")
                else:
                    logger.warning("⚠️  Каналы не настроены")
            else:
                logger.warning("⚠️  AI парсинг недоступен")
            
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
        bot = FixedAIBot()
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("👋 Получен сигнал остановки")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        logger.info("🔚 ИСПРАВЛЕННЫЙ AI Бот остановлен")

if __name__ == "__main__":
    main()
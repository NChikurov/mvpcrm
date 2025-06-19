#!/usr/bin/env python3
"""
AI CRM Bot с интегрированным анализом диалогов - ОБНОВЛЕННАЯ ВЕРСИЯ
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
from handlers.user import UserHandler
from handlers.admin import AdminHandler

# Импортируем новый интегрированный парсер
try:
    from myparser.integrated_ai_parser import IntegratedAIContextParser
    INTEGRATED_PARSER_AVAILABLE = True
except ImportError:
    # Fallback на оригинальный парсер
    from myparser.ai_context_parser import AIContextParser as IntegratedAIContextParser
    INTEGRATED_PARSER_AVAILABLE = False
    logging.warning("Интегрированный парсер недоступен, используется оригинальный")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Отключаем HTTP спам
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

class EnhancedAIBot:
    """Главный класс AI CRM бота с поддержкой анализа диалогов"""
    
    def __init__(self):
        logger.info("🚀 Создание экземпляра Enhanced AI бота...")
        
        # Загружаем конфигурацию
        self.config = load_config()
        
        # Валидируем конфигурацию
        validation_report = get_config_validation_report(self.config)
        self._print_validation_report(validation_report)
        
        if not validation_report['valid']:
            raise ValueError("Критические ошибки конфигурации")
        
        print_config_summary(self.config)
        
        # Показываем конфигурацию AI парсинга
        self._print_ai_parsing_config()
        
        self.app = None
        self.user_handler = None
        self.admin_handler = None
        self.ai_parser = None

    def _print_validation_report(self, report):
        """Вывод отчета о валидации конфигурации"""
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
        logger.info(f"    🎯 Приоритет диалогам: {'✅' if parsing_config.get('prefer_dialogue_analysis', True) else '❌'}")
        logger.info(f"    📊 Мин. скор: {parsing_config.get('min_confidence_score', 60)}")
        logger.info(f"    📈 Мин. скор диалога: {parsing_config.get('min_dialogue_confidence', 75)}")
        logger.info(f"    📺 Каналов: {len(parsing_config.get('channels', []))}")
        logger.info(f"    🕐 Интервал: {parsing_config.get('parse_interval', 3600)} сек")
        
        if parsing_config.get('dialogue_analysis_enabled', True):
            logger.info(f"    👥 Мин. участников диалога: {parsing_config.get('min_dialogue_participants', 2)}")
            logger.info(f"    💬 Мин. сообщений диалога: {parsing_config.get('min_dialogue_messages', 3)}")
            logger.info(f"    ⏱️  Таймаут диалога: {parsing_config.get('dialogue_timeout_minutes', 15)} мин")
        
        channels = parsing_config.get('channels', [])
        if channels:
            logger.info("    📋 Отслеживаемые каналы:")
            for i, channel in enumerate(channels[:5], 1):
                logger.info(f"       {i}. {channel}")
            if len(channels) > 5:
                logger.info(f"       ... и еще {len(channels) - 5}")
        else:
            logger.warning("    ⚠️  Каналы не настроены!")

    async def setup_bot(self):
        """Настройка бота"""
        logger.info("🔧 Запуск настройки Enhanced AI бота...")
        
        # Мигрируем базу данных для поддержки AI
        logger.info("📊 Выполняется миграция базы данных для AI...")
        await migrate_database_for_ai()
        
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
        
        # Регистрируем обработчики
        self.register_handlers()
        logger.info("✅ Обработчики зарегистрированы")
        
        # Инициализируем AI парсер
        if INTEGRATED_PARSER_AVAILABLE:
            logger.info("🤖 Инициализируем ИНТЕГРИРОВАННЫЙ AI Context Parser...")
            self.ai_parser = IntegratedAIContextParser(self.config)
            logger.info("✅ Интегрированный AI Context Parser инициализирован")
        else:
            logger.info("🤖 Инициализируем оригинальный AI Context Parser...")
            self.ai_parser = IntegratedAIContextParser(self.config)
            logger.info("✅ AI Context Parser инициализирован")

    def register_handlers(self):
        """Регистрация обработчиков команд и сообщений"""
        # Команды
        self.app.add_handler(CommandHandler("start", self.user_handler.start))
        self.app.add_handler(CommandHandler("help", self.user_handler.help_command))
        self.app.add_handler(CommandHandler("menu", self.user_handler.menu))
        self.app.add_handler(CommandHandler("admin", self.admin_handler.admin_panel))
        self.app.add_handler(CommandHandler("broadcast", self.admin_handler.broadcast))
        
        # Новые команды для управления анализом диалогов
        self.app.add_handler(CommandHandler("status", self.show_parser_status))
        self.app.add_handler(CommandHandler("dialogues", self.show_active_dialogues))
        
        # Обработка всех текстовых сообщений
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            self.handle_any_message
        ))
        
        # Callback обработчики
        self.app.add_handler(self.admin_handler.callback_handler)
        self.app.add_handler(self.user_handler.callback_handler)
        
        logger.info("✅ Все обработчики успешно зарегистрированы")

    async def show_parser_status(self, update, context):
        """Показать статус AI парсера (только для админов)"""
        user_id = update.effective_user.id
        admin_ids = self.config.get('bot', {}).get('admin_ids', [])
        
        if user_id not in admin_ids:
            await update.message.reply_text("❌ Эта команда доступна только администраторам")
            return
        
        try:
            if self.ai_parser:
                status = self.ai_parser.get_status()
                
                message = "🤖 <b>Статус AI парсера</b>\n\n"
                message += f"⚙️ <b>Основные настройки:</b>\n"
                message += f"• Включен: {'✅' if status['enabled'] else '❌'}\n"
                message += f"• Каналов: {status['channels_count']}\n"
                message += f"• Мин. скор: {status['min_confidence_score']}%\n\n"
                
                message += f"👤 <b>Индивидуальный анализ:</b>\n"
                message += f"• Активных пользователей: {status['individual_active_users']}\n"
                message += f"• Кэш анализов: {status['individual_analysis_cache_size']}\n"
                message += f"• Обработано лидов: {status['individual_processed_leads_count']}\n\n"
                
                if status.get('dialogue_analysis_enabled'):
                    message += f"👥 <b>Анализ диалогов:</b>\n"
                    message += f"• Включен: ✅\n"
                    message += f"• Приоритет диалогам: {'✅' if status.get('prefer_dialogue_analysis') else '❌'}\n"
                    
                    dialogue_status = status.get('dialogue_tracker', {})
                    if dialogue_status:
                        message += f"• Активных диалогов: {dialogue_status['active_dialogues']}\n"
                        message += f"• Мин. участников: {dialogue_status['min_participants']}\n"
                        message += f"• Мин. сообщений: {dialogue_status['min_messages']}\n"
                        message += f"• Таймаут: {dialogue_status['dialogue_timeout_minutes']:.0f} мин\n"
                else:
                    message += f"👥 <b>Анализ диалогов:</b> ❌ Отключен\n"
                
                message += f"\n📋 <b>Отслеживаемые каналы:</b>\n"
                for i, channel in enumerate(status['channels'][:5], 1):
                    message += f"{i}. <code>{channel}</code>\n"
                if len(status['channels']) > 5:
                    message += f"... и еще {len(status['channels']) - 5}\n"
                
                await update.message.reply_text(message, parse_mode='HTML')
            else:
                await update.message.reply_text("❌ AI парсер не инициализирован")
                
        except Exception as e:
            logger.error(f"Ошибка получения статуса парсера: {e}")
            await update.message.reply_text("❌ Ошибка получения статуса")

    async def show_active_dialogues(self, update, context):
        """Показать активные диалоги (только для админов)"""
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
                
                for dialogue_id, dialogue in list(active_dialogues.items())[:10]:  # Показываем максимум 10
                    duration = (dialogue.last_activity - dialogue.start_time).total_seconds() / 60
                    participants_count = len(dialogue.participants)
                    messages_count = len(dialogue.messages)
                    
                    message += f"🔹 <b>{dialogue_id}</b>\n"
                    message += f"   📺 Канал: {dialogue.channel_title}\n"
                    message += f"   👥 Участников: {participants_count}\n"
                    message += f"   💬 Сообщений: {messages_count}\n"
                    message += f"   ⏱️ Длительность: {duration:.0f} мин\n"
                    message += f"   🏢 Бизнес-тема: {'✅' if dialogue.is_business_related else '❌'}\n\n"
                
                if len(active_dialogues) > 10:
                    message += f"... и еще {len(active_dialogues) - 10} диалогов\n"
                
                await update.message.reply_text(message, parse_mode='HTML')
            else:
                await update.message.reply_text("❌ Анализ диалогов не активен")
                
        except Exception as e:
            logger.error(f"Ошибка получения активных диалогов: {e}")
            await update.message.reply_text("❌ Ошибка получения диалогов")

    async def handle_any_message(self, update, context):
        """Универсальный обработчик сообщений с расширенным AI анализом"""
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
                    
                    if hasattr(self.ai_parser, 'channels'):
                        logger.info(f"    📋 Настроенные каналы: {self.ai_parser.channels}")
                    
                    logger.info(f"    🎯 Отслеживается: {'ДА' if is_monitored else 'НЕТ'}")
                    
                    if is_monitored:
                        logger.info(f"    ✅ Совпадение по: ID {chat.id}")
                        
                        # Определяем тип анализа
                        if (hasattr(self.ai_parser, 'dialogue_analysis_enabled') and 
                            self.ai_parser.dialogue_analysis_enabled):
                            logger.info("🤖 ОТПРАВЛЯЕМ НА ИНТЕГРИРОВАННЫЙ AI АНАЛИЗ (диалоги + индивидуальный)!")
                        else:
                            logger.info("🤖 ОТПРАВЛЯЕМ НА КЛАССИЧЕСКИЙ AI АНАЛИЗ!")
                        
                        # Отправляем на AI анализ
                        await self.ai_parser.process_message(update, context)
                    else:
                        logger.info("⏭️ Пропускаем: канал не отслеживается")
                else:
                    logger.info("⏭️ Пропускаем: AI парсинг отключен")
            
            logger.info("────────────────────────────────────────────────────────────")
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки сообщения: {e}")
            import traceback
            traceback.print_exc()

    async def check_channels_access(self):
        """Проверка доступа к настроенным каналам"""
        if not self.ai_parser:
            return
        
        channels = getattr(self.ai_parser, 'channels', [])
        if not channels:
            return
        
        bot_info = await self.app.bot.get_me()
        logger.info("🤖 Информация о боте:")
        logger.info(f"    Username: @{bot_info.username}")
        logger.info(f"    ID: {bot_info.id}")
        
        for channel in channels:
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
        
        logger.info("✅ Бот готов к работе")
        logger.info(f"🚀 Запуск Enhanced AI бота: {self.config['bot']['name']}")
        logger.info(f"👑 Админы: {self.config['bot']['admin_ids']}")
        
        # Проверяем доступ к каналам
        async with self.app:
            await self.app.initialize()
            await self.app.start()
            
            await self.check_channels_access()
            
            logger.info("🎉 ENHANCED AI БОТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ!")
            
            # Информация о режиме работы
            if self.ai_parser:
                channels = getattr(self.ai_parser, 'channels', [])
                if channels:
                    dialogue_enabled = getattr(self.ai_parser, 'dialogue_analysis_enabled', False)
                    prefer_dialogue = getattr(self.ai_parser, 'prefer_dialogue_analysis', False)
                    
                    logger.info(f"🤖 AI мониторинг активен для {len(channels)} каналов:")
                    for channel in channels:
                        logger.info(f"    - {channel}")
                    
                    if dialogue_enabled:
                        if prefer_dialogue:
                            logger.info("🎯 РЕЖИМ: Приоритет анализу диалогов + индивидуальные сообщения")
                        else:
                            logger.info("🎯 РЕЖИМ: Параллельный анализ диалогов и индивидуальных сообщений")
                        logger.info("💡 Отправьте сообщения в группы для анализа диалогов")
                    else:
                        logger.info("🎯 РЕЖИМ: Только индивидуальный анализ сообщений")
                    
                    logger.info("💡 Отправьте сообщения в отслеживаемые каналы для AI анализа")
                    logger.info("💡 Используйте /status для проверки работы парсера")
                    logger.info("💡 Используйте /dialogues для просмотра активных диалогов")
                else:
                    logger.warning("⚠️  AI парсинг активен, но каналы не настроены")
            else:
                logger.warning("⚠️  AI парсинг отключен")
            
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
        bot = EnhancedAIBot()
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("👋 Получен сигнал остановки")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        logger.info("🔚 Enhanced AI Бот остановлен")
        logger.info("🔚 Завершение работы")

if __name__ == "__main__":
    main()
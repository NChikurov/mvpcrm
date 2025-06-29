#!/usr/bin/env python3
"""
AI CRM Bot - Оптимизированная версия main.py
Улучшенное логирование, структурированная обработка ошибок, метрики производительности
"""

import asyncio
import logging
import logging.config
import sys
import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

from utils.config_loader import load_config, get_config_validation_report
from database.operations import init_database
from database.db_migration import migrate_database_for_ai
from database.dialogue_db_migration import migrate_database_for_dialogues
from handlers.user import UserHandler
from handlers.admin import AdminHandler

# Настройка структурированного логирования
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'detailed': {
            'format': '%(asctime)s | %(name)s | %(levelname)s | %(funcName)s:%(lineno)d | %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        },
        'simple': {
            'format': '%(levelname)s | %(name)s | %(message)s'
        },
        'json': {
            'format': '%(asctime)s %(name)s %(levelname)s %(message)s',
            'class': 'pythonjsonlogger.jsonlogger.JsonFormatter'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'INFO',
            'formatter': 'detailed',
            'stream': 'ext://sys.stdout'
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'level': 'DEBUG',
            'formatter': 'detailed',
            'filename': 'logs/ai_crm_bot.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5
        },
        'error_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'level': 'ERROR',
            'formatter': 'detailed',
            'filename': 'logs/errors.log',
            'maxBytes': 5242880,  # 5MB
            'backupCount': 3
        }
    },
    'loggers': {
        '': {  # Root logger
            'level': 'INFO',
            'handlers': ['console', 'file', 'error_file']
        },
        'httpx': {
            'level': 'WARNING',
            'handlers': ['file']
        },
        'telegram': {
            'level': 'WARNING', 
            'handlers': ['file']
        }
    }
}

def setup_logging():
    """Настройка логирования с созданием директории"""
    logs_dir = Path('logs')
    logs_dir.mkdir(exist_ok=True)
    
    try:
        logging.config.dictConfig(LOGGING_CONFIG)
    except Exception:
        # Fallback к базовому логированию
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('logs/ai_crm_bot.log')
            ]
        )

logger = logging.getLogger(__name__)

class PerformanceMetrics:
    """Класс для сбора метрик производительности"""
    
    def __init__(self):
        self.start_time = time.time()
        self.metrics = {
            'messages_processed': 0,
            'ai_analyses_completed': 0,
            'dialogues_created': 0,
            'leads_generated': 0,
            'notifications_sent': 0,
            'errors_count': 0,
            'average_processing_time': 0.0,
            'last_reset': datetime.now()
        }
        self.processing_times = []
    
    def record_message_processed(self, processing_time: float):
        """Записать обработанное сообщение"""
        self.metrics['messages_processed'] += 1
        self.processing_times.append(processing_time)
        
        # Ограничиваем размер списка
        if len(self.processing_times) > 1000:
            self.processing_times = self.processing_times[-500:]
        
        self.metrics['average_processing_time'] = sum(self.processing_times) / len(self.processing_times)
    
    def record_ai_analysis(self):
        """Записать выполненный AI анализ"""
        self.metrics['ai_analyses_completed'] += 1
    
    def record_dialogue_created(self):
        """Записать созданный диалог"""
        self.metrics['dialogues_created'] += 1
    
    def record_lead_generated(self):
        """Записать созданный лид"""
        self.metrics['leads_generated'] += 1
    
    def record_notification_sent(self):
        """Записать отправленное уведомление"""
        self.metrics['notifications_sent'] += 1
    
    def record_error(self):
        """Записать ошибку"""
        self.metrics['errors_count'] += 1
    
    def get_metrics(self) -> Dict[str, Any]:
        """Получить текущие метрики"""
        uptime = time.time() - self.start_time
        
        return {
            **self.metrics,
            'uptime_seconds': uptime,
            'uptime_formatted': self._format_uptime(uptime),
            'messages_per_minute': self.metrics['messages_processed'] / (uptime / 60) if uptime > 60 else 0,
            'error_rate': self.metrics['errors_count'] / max(1, self.metrics['messages_processed']),
            'conversion_rate': self.metrics['leads_generated'] / max(1, self.metrics['messages_processed'])
        }
    
    def _format_uptime(self, seconds: float) -> str:
        """Форматирование времени работы"""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    
    def reset_daily_metrics(self):
        """Сброс ежедневных метрик"""
        self.metrics.update({
            'messages_processed': 0,
            'ai_analyses_completed': 0,
            'dialogues_created': 0,
            'leads_generated': 0,
            'notifications_sent': 0,
            'errors_count': 0,
            'last_reset': datetime.now()
        })
        self.processing_times.clear()

class OptimizedAIBot:
    """Оптимизированный класс AI CRM бота"""
    
    def __init__(self):
        self.config: Optional[Dict[str, Any]] = None
        self.app: Optional[Application] = None
        self.user_handler: Optional[UserHandler] = None
        self.admin_handler: Optional[AdminHandler] = None
        self.ai_parser: Optional[Any] = None
        self.metrics = PerformanceMetrics()
        self.is_running = False
        
        logger.info("🚀 Инициализация оптимизированного AI CRM бота")

    async def initialize(self):
        """Асинхронная инициализация бота"""
        try:
            # Загрузка и валидация конфигурации
            await self._load_and_validate_config()
            
            # Инициализация базы данных
            await self._setup_database()
            
            # Создание Telegram приложения
            await self._create_telegram_app()
            
            # Инициализация обработчиков
            await self._setup_handlers()
            
            # Инициализация AI парсера
            await self._setup_ai_parser()
            
            # Регистрация обработчиков команд
            self._register_handlers()
            
            logger.info("✅ Оптимизированный бот успешно инициализирован")
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка инициализации: {e}")
            raise

    async def _load_and_validate_config(self):
        """Загрузка и валидация конфигурации"""
        logger.info("📋 Загрузка конфигурации...")
        
        self.config = load_config()
        
        # Валидация конфигурации
        validation_report = get_config_validation_report(self.config)
        
        if validation_report['errors']:
            for error in validation_report['errors']:
                logger.error(f"❌ Ошибка конфигурации: {error}")
            raise ValueError("Критические ошибки конфигурации")
        
        if validation_report['warnings']:
            for warning in validation_report['warnings']:
                logger.warning(f"⚠️ Предупреждение: {warning}")
        
        # Логируем ключевую информацию
        info = validation_report['info']
        logger.info(f"🤖 Бот: {info['bot_name']}")
        logger.info(f"👑 Админов: {info['admin_count']}")
        logger.info(f"🧠 Claude API: {'✅' if info['claude_enabled'] else '⚠️ Simple mode'}")
        logger.info(f"📺 Каналов: {info['channels_count']}")
        logger.info(f"💬 Анализ диалогов: {'✅' if info['dialogue_analysis_enabled'] else '❌'}")

    async def _setup_database(self):
        """Настройка базы данных"""
        logger.info("💾 Настройка базы данных...")
        
        try:
            # Миграции
            await migrate_database_for_ai()
            await migrate_database_for_dialogues()
            
            # Инициализация
            await init_database()
            
            logger.info("✅ База данных настроена")
            
        except Exception as e:
            logger.error(f"❌ Ошибка настройки БД: {e}")
            raise

    async def _create_telegram_app(self):
        """Создание Telegram приложения"""
        logger.info("📱 Создание Telegram приложения...")
        
        try:
            bot_token = self.config['bot']['token']
            self.app = Application.builder().token(bot_token).build()
            
            logger.info("✅ Telegram приложение создано")
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания Telegram приложения: {e}")
            raise

    async def _setup_handlers(self):
        """Настройка обработчиков"""
        logger.info("🔧 Настройка обработчиков...")
        
        try:
            self.user_handler = UserHandler(self.config)
            self.admin_handler = AdminHandler(self.config)
            
            logger.info("✅ Обработчики настроены")
            
        except Exception as e:
            logger.error(f"❌ Ошибка настройки обработчиков: {e}")
            raise

    async def _setup_ai_parser(self):
        """Настройка AI парсера"""
        logger.info("🤖 Настройка AI парсера...")
        
        try:
            # Безопасный импорт парсера
            from myparser import OptimizedUnifiedParser
            
            self.ai_parser = OptimizedUnifiedParser(self.config)
            self.app.bot_data['ai_parser'] = self.ai_parser
            
            # Передаем метрики парсеру
            self.ai_parser.metrics_callback = self._record_parser_metrics
            
            logger.info("✅ AI парсер настроен")
            
        except ImportError as e:
            logger.error(f"❌ Не удалось импортировать оптимизированный парсер: {e}")
            
            # Fallback
            try:
                from myparser import UnifiedAIParser
                self.ai_parser = UnifiedAIParser(self.config)
                self.app.bot_data['ai_parser'] = self.ai_parser
                logger.warning("⚠️ Используется базовый парсер")
            except Exception as fallback_error:
                logger.error(f"❌ Критическая ошибка: парсер недоступен: {fallback_error}")
                self.ai_parser = None

    def _record_parser_metrics(self, event_type: str, **kwargs):
        """Запись метрик от парсера"""
        try:
            if event_type == "message_processed":
                processing_time = kwargs.get('processing_time', 0)
                self.metrics.record_message_processed(processing_time)
            elif event_type == "ai_analysis":
                self.metrics.record_ai_analysis()
            elif event_type == "dialogue_created":
                self.metrics.record_dialogue_created()
            elif event_type == "lead_generated":
                self.metrics.record_lead_generated()
            elif event_type == "notification_sent":
                self.metrics.record_notification_sent()
            elif event_type == "error":
                self.metrics.record_error()
        except Exception as e:
            logger.error(f"Ошибка записи метрик: {e}")

    def _register_handlers(self):
        """Регистрация обработчиков команд"""
        logger.info("📝 Регистрация обработчиков команд...")
        
        try:
            # Основные команды
            self.app.add_handler(CommandHandler("start", self.user_handler.start))
            self.app.add_handler(CommandHandler("help", self.user_handler.help_command))
            self.app.add_handler(CommandHandler("menu", self.user_handler.menu))
            
            # Админские команды
            self.app.add_handler(CommandHandler("admin", self.admin_handler.admin_panel))
            self.app.add_handler(CommandHandler("broadcast", self.admin_handler.broadcast))
            self.app.add_handler(CommandHandler("stats", self.admin_handler.show_stats))
            
            # Команды мониторинга
            self.app.add_handler(CommandHandler("status", self._show_system_status))
            self.app.add_handler(CommandHandler("performance", self._show_performance_metrics))
            self.app.add_handler(CommandHandler("health", self._health_check))
            self.app.add_handler(CommandHandler("dialogues", self._show_active_dialogues))
            
            # Обработка сообщений
            self.app.add_handler(MessageHandler(
                filters.TEXT & ~filters.COMMAND, 
                self._handle_message_with_metrics
            ))
            
            # Callback обработчики
            self.app.add_handler(self.admin_handler.callback_handler)
            self.app.add_handler(self.user_handler.callback_handler)
            
            logger.info("✅ Обработчики зарегистрированы")
            
        except Exception as e:
            logger.error(f"❌ Ошибка регистрации обработчиков: {e}")
            raise

    async def _handle_message_with_metrics(self, update, context):
        """Обработка сообщений с метриками производительности"""
        start_time = time.time()
        
        try:
            if not update.message or not update.message.text:
                return
            
            chat = update.effective_chat
            user = update.effective_user
            
            # Структурированное логирование
            log_data = {
                'event': 'message_received',
                'user_id': user.id,
                'chat_id': chat.id,
                'chat_type': chat.type,
                'message_length': len(update.message.text),
                'timestamp': datetime.now().isoformat()
            }
            
            logger.info(f"📨 Message received: {json.dumps(log_data)}")
            
            if chat.type == 'private':
                # Личные сообщения
                await self.user_handler.handle_message(update, context)
                logger.debug(f"Private message processed for user {user.id}")
                
            elif chat.type in ['group', 'supergroup', 'channel']:
                # Групповые сообщения - AI парсинг
                if self.ai_parser and self.ai_parser.enabled:
                    if self.ai_parser.is_channel_monitored(chat.id, chat.username):
                        logger.debug(f"Processing group message from channel {chat.id}")
                        await self.ai_parser.process_message(update, context)
                    else:
                        logger.debug(f"Channel {chat.id} not monitored")
                else:
                    logger.warning("AI parser not available or disabled")
            
            # Записываем метрики
            processing_time = time.time() - start_time
            self.metrics.record_message_processed(processing_time)
            
            if processing_time > 2.0:  # Предупреждение о медленной обработке
                logger.warning(f"Slow message processing: {processing_time:.2f}s for user {user.id}")
            
        except Exception as e:
            self.metrics.record_error()
            logger.error(f"❌ Error processing message: {e}", exc_info=True)

    async def _show_system_status(self, update, context):
        """Показать статус системы"""
        user_id = update.effective_user.id
        admin_ids = self.config.get('bot', {}).get('admin_ids', [])
        
        if user_id not in admin_ids:
            await update.message.reply_text("❌ Эта команда доступна только администраторам")
            return
        
        try:
            status_info = []
            
            # Основной статус
            status_info.append("🤖 **Статус AI CRM системы**\n")
            
            # AI парсер
            if self.ai_parser:
                parser_status = self.ai_parser.get_status()
                status_info.append(f"🔍 **AI Парсер:** {'✅ Активен' if parser_status['enabled'] else '❌ Отключен'}")
                status_info.append(f"📺 **Каналов:** {parser_status['channels_count']}")
                status_info.append(f"💬 **Активных диалогов:** {parser_status.get('active_dialogues', 0)}")
                status_info.append(f"🎯 **Режим:** {parser_status.get('mode', 'unknown')}")
            else:
                status_info.append("🔍 **AI Парсер:** ❌ Недоступен")
            
            # Claude API
            try:
                from ai.claude_client import get_claude_client
                claude_client = get_claude_client()
                if claude_client:
                    health = await claude_client.health_check()
                    status_info.append(f"🧠 **Claude API:** {'✅ Работает' if health else '⚠️ Недоступен'}")
                else:
                    status_info.append("🧠 **Claude API:** ❌ Не инициализирован")
            except Exception:
                status_info.append("🧠 **Claude API:** ❌ Ошибка проверки")
            
            # Метрики производительности
            metrics = self.metrics.get_metrics()
            status_info.append(f"\n📊 **Производительность:**")
            status_info.append(f"• Время работы: {metrics['uptime_formatted']}")
            status_info.append(f"• Обработано сообщений: {metrics['messages_processed']}")
            status_info.append(f"• Среднее время обработки: {metrics['average_processing_time']:.3f}с")
            status_info.append(f"• Создано лидов: {metrics['leads_generated']}")
            status_info.append(f"• Коэффициент ошибок: {metrics['error_rate']:.2%}")
            
            await update.message.reply_text('\n'.join(status_info), parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing system status: {e}")
            await update.message.reply_text("❌ Ошибка получения статуса системы")

    async def _show_performance_metrics(self, update, context):
        """Показать метрики производительности"""
        user_id = update.effective_user.id
        admin_ids = self.config.get('bot', {}).get('admin_ids', [])
        
        if user_id not in admin_ids:
            await update.message.reply_text("❌ Эта команда доступна только администраторам")
            return
        
        try:
            metrics = self.metrics.get_metrics()
            
            # Дополнительные метрики от парсера
            parser_metrics = {}
            if self.ai_parser and hasattr(self.ai_parser, 'get_performance_metrics'):
                parser_metrics = self.ai_parser.get_performance_metrics()
            
            message = f"""📊 **Метрики производительности**

⏱️ **Время работы:** {metrics['uptime_formatted']}

📈 **Обработка сообщений:**
• Всего: {metrics['messages_processed']}
• В минуту: {metrics['messages_per_minute']:.1f}
• Среднее время: {metrics['average_processing_time']:.3f}с

🤖 **AI анализ:**
• Анализов выполнено: {metrics['ai_analyses_completed']}
• Диалогов создано: {metrics['dialogues_created']}

🎯 **Результативность:**
• Лидов создано: {metrics['leads_generated']}
• Уведомлений отправлено: {metrics['notifications_sent']}
• Конверсия в лиды: {metrics['conversion_rate']:.2%}

⚠️ **Надежность:**
• Ошибок: {metrics['errors_count']}
• Коэффициент ошибок: {metrics['error_rate']:.2%}

🔄 **Последний сброс:** {metrics['last_reset'].strftime('%d.%m.%Y %H:%M')}"""

            if parser_metrics and not parser_metrics.get('no_data'):
                message += f"""

🔍 **Парсер:**
• Конверсия лидов: {parser_metrics.get('leads_conversion_rate', 0):.2f}%
• Частота уведомлений: {parser_metrics.get('notification_rate', 0):.2f}%
• Эффективность кэша: {parser_metrics.get('cache_efficiency', 0)}"""

            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing performance metrics: {e}")
            await update.message.reply_text("❌ Ошибка получения метрик производительности")

    async def _health_check(self, update, context):
        """Проверка здоровья системы"""
        user_id = update.effective_user.id
        admin_ids = self.config.get('bot', {}).get('admin_ids', [])
        
        if user_id not in admin_ids:
            await update.message.reply_text("❌ Эта команда доступна только администраторам")
            return
        
        try:
            health_status = []
            overall_health = True
            
            # Проверка базы данных
            try:
                from database.operations import get_bot_stats
                await get_bot_stats()
                health_status.append("💾 **База данных:** ✅ Работает")
            except Exception as e:
                health_status.append(f"💾 **База данных:** ❌ Ошибка - {e}")
                overall_health = False
            
            # Проверка Claude API
            try:
                from ai.claude_client import get_claude_client
                claude_client = get_claude_client()
                if claude_client:
                    claude_health = await claude_client.health_check()
                    health_status.append(f"🧠 **Claude API:** {'✅ Работает' if claude_health else '⚠️ Недоступен'}")
                    if not claude_health:
                        overall_health = False
                else:
                    health_status.append("🧠 **Claude API:** ⚠️ Не настроен (простой режим)")
            except Exception as e:
                health_status.append(f"🧠 **Claude API:** ❌ Ошибка - {e}")
                overall_health = False
            
            # Проверка AI парсера
            if self.ai_parser:
                health_status.append("🤖 **AI Парсер:** ✅ Инициализирован")
            else:
                health_status.append("🤖 **AI Парсер:** ❌ Недоступен")
                overall_health = False
            
            # Проверка метрик
            metrics = self.metrics.get_metrics()
            if metrics['error_rate'] > 0.1:  # Более 10% ошибок
                health_status.append(f"⚠️ **Высокий уровень ошибок:** {metrics['error_rate']:.2%}")
                overall_health = False
            else:
                health_status.append("✅ **Уровень ошибок в норме**")
            
            # Общий статус
            overall_emoji = "✅" if overall_health else "⚠️"
            overall_text = "Система работает нормально" if overall_health else "Обнаружены проблемы"
            
            message = f"{overall_emoji} **Проверка здоровья системы**\n\n{overall_text}\n\n" + '\n'.join(health_status)
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in health check: {e}")
            await update.message.reply_text("❌ Ошибка проверки здоровья системы")

    async def _show_active_dialogues(self, update, context):
        """Показать активные диалоги"""
        user_id = update.effective_user.id
        admin_ids = self.config.get('bot', {}).get('admin_ids', [])
        
        if user_id not in admin_ids:
            await update.message.reply_text("❌ Эта команда доступна только администраторам")
            return
        
        try:
            if not self.ai_parser or not hasattr(self.ai_parser, 'dialogue_tracker'):
                await update.message.reply_text("❌ Трекер диалогов недоступен")
                return
            
            active_dialogues = self.ai_parser.dialogue_tracker.active_dialogues
            
            if not active_dialogues:
                await update.message.reply_text("📭 Активных диалогов нет")
                return
            
            message_parts = [f"💬 **Активные диалоги ({len(active_dialogues)})**\n"]
            
            for i, (dialogue_id, dialogue) in enumerate(list(active_dialogues.items())[:10], 1):
                duration = (datetime.now() - dialogue.start_time).total_seconds() / 60
                
                message_parts.append(
                    f"{i}. **{dialogue.channel_title}**\n"
                    f"   👥 {len(dialogue.participants)} участников\n"
                    f"   💬 {len(dialogue.messages)} сообщений\n"
                    f"   ⏱️ {duration:.0f} мин\n"
                    f"   🏢 {'Бизнес' if getattr(dialogue, 'business_score', 0) > 0 else 'Общий'}\n"
                )
            
            if len(active_dialogues) > 10:
                message_parts.append(f"\n... и еще {len(active_dialogues) - 10} диалогов")
            
            await update.message.reply_text('\n'.join(message_parts), parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing active dialogues: {e}")
            await update.message.reply_text("❌ Ошибка получения диалогов")

    async def check_channels_access(self):
        """Проверка доступа к каналам"""
        if not self.ai_parser:
            return
        
        try:
            status = self.ai_parser.get_status()
            channels = status.get('channels', [])
            
            if not channels:
                logger.warning("⚠️ Каналы не настроены")
                return
            
            bot_info = await self.app.bot.get_me()
            logger.info(f"🤖 Бот: @{bot_info.username} (ID: {bot_info.id})")
            
            for channel in channels:
                try:
                    chat = await self.app.bot.get_chat(channel)
                    bot_member = await self.app.bot.get_chat_member(chat.id, bot_info.id)
                    
                    status_emoji = "✅" if bot_member.status in ['administrator', 'member'] else "⚠️"
                    logger.info(f"{status_emoji} {chat.title} ({chat.id}) - {bot_member.status}")
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка доступа к {channel}: {e}")
                    
        except Exception as e:
            logger.error(f"Ошибка проверки каналов: {e}")

    @asynccontextmanager
    async def run_context(self):
        """Контекстный менеджер для запуска бота"""
        try:
            self.is_running = True
            async with self.app:
                await self.app.initialize()
                await self.app.start()
                
                # Проверяем доступ к каналам
                await self.check_channels_access()
                
                logger.info("🎉 AI CRM Bot успешно запущен!")
                
                # Информация о режиме работы
                if self.ai_parser:
                    status = self.ai_parser.get_status()
                    logger.info(f"🎯 Режим: {status.get('mode', 'unknown')}")
                    logger.info(f"📺 Мониторинг {status['channels_count']} каналов")
                    logger.info(f"🧠 AI анализатор: {status.get('analyzer_type', 'unknown')}")
                
                yield
        except Exception as e:
            logger.error(f"Ошибка в контексте запуска: {e}")
            raise
        finally:
            self.is_running = False
            logger.info("🛑 AI CRM Bot остановлен")

    async def run(self):
        """Главный метод запуска бота"""
        try:
            await self.initialize()
            
            async with self.run_context():
                # Запуск polling
                await self.app.updater.start_polling(
                    drop_pending_updates=True,
                    allowed_updates=['message', 'callback_query']
                )
                
                # Запуск фоновых задач
                await self._start_background_tasks()
                
                # Ожидание завершения
                await asyncio.Future()  # Работает до Ctrl+C
                
        except Exception as e:
            logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
            raise

    async def _start_background_tasks(self):
        """Запуск фоновых задач"""
        # Ежедневный сброс метрик
        asyncio.create_task(self._daily_metrics_reset())
        
        # Мониторинг производительности
        asyncio.create_task(self._performance_monitor())

    async def _daily_metrics_reset(self):
        """Ежедневный сброс метрик"""
        while self.is_running:
            try:
                # Ждем до следующего дня
                now = datetime.now()
                tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                sleep_time = (tomorrow - now).total_seconds()
                
                await asyncio.sleep(sleep_time)
                
                # Сбрасываем метрики
                self.metrics.reset_daily_metrics()
                logger.info("📊 Ежедневные метрики сброшены")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка сброса метрик: {e}")
                await asyncio.sleep(3600)  # Повтор через час

    async def _performance_monitor(self):
        """Мониторинг производительности"""
        while self.is_running:
            try:
                await asyncio.sleep(300)  # Каждые 5 минут
                
                metrics = self.metrics.get_metrics()
                
                # Проверка производительности
                if metrics['error_rate'] > 0.05:  # Более 5% ошибок
                    logger.warning(f"⚠️ Высокий уровень ошибок: {metrics['error_rate']:.2%}")
                
                if metrics['average_processing_time'] > 1.0:  # Более секунды на обработку
                    logger.warning(f"⚠️ Медленная обработка: {metrics['average_processing_time']:.3f}с")
                
                # Логируем периодическую статистику
                if metrics['messages_processed'] > 0:
                    logger.info(
                        f"📊 Stats: {metrics['messages_processed']} msgs, "
                        f"{metrics['leads_generated']} leads, "
                        f"{metrics['error_rate']:.1%} error rate"
                    )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка мониторинга производительности: {e}")

def main():
    """Главная функция"""
    # Настройка логирования
    setup_logging()
    
    try:
        logger.info("🚀 Запуск оптимизированного AI CRM бота")
        
        bot = OptimizedAIBot()
        asyncio.run(bot.run())
        
    except KeyboardInterrupt:
        logger.info("👋 Получен сигнал остановки (Ctrl+C)")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
        return 1
    finally:
        logger.info("🔚 AI CRM Bot остановлен")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
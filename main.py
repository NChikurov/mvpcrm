#!/usr/bin/env python3
"""
AI CRM Bot - ИСПРАВЛЕННАЯ версия main.py
Решение проблем: Unicode, импорты, контекст приложения
"""

import asyncio
import logging
import logging.config
import sys
import os
import json
import time
import signal
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

# ИСПРАВЛЕНИЕ КОДИРОВКИ для Windows
if sys.platform == "win32":
    # Устанавливаем UTF-8 кодировку для консоли
    os.system("chcp 65001 > nul")
    
    # Настраиваем stdout/stderr для UTF-8
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())
    
    # Переменная окружения для Python
    os.environ["PYTHONIOENCODING"] = "utf-8"

from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

from utils.config_loader import load_config, get_config_validation_report
from database.operations import init_database
from database.db_migration import migrate_database_for_ai
from database.dialogue_db_migration import migrate_database_for_dialogues
from handlers.user import UserHandler
from handlers.admin import AdminHandler

# ИСПРАВЛЕННАЯ настройка логирования с UTF-8
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
            'backupCount': 5,
            'encoding': 'utf-8'  # Явно указываем UTF-8
        },
        'error_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'level': 'ERROR',
            'formatter': 'detailed',
            'filename': 'logs/errors.log',
            'maxBytes': 5242880,  # 5MB
            'backupCount': 3,
            'encoding': 'utf-8'  # Явно указываем UTF-8
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
    """Настройка логирования с созданием директории и UTF-8"""
    logs_dir = Path('logs')
    logs_dir.mkdir(exist_ok=True)
    
    try:
        logging.config.dictConfig(LOGGING_CONFIG)
    except Exception as e:
        # Fallback к базовому логированию с UTF-8
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('logs/ai_crm_bot.log', encoding='utf-8')
            ],
            force=True
        )
        print(f"Warning: Using fallback logging due to: {e}")

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
        
        if self.processing_times:
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

class OptimizedAIBot:
    """Оптимизированный класс AI CRM бота с исправлениями"""
    
    def __init__(self):
        self.config: Optional[Dict[str, Any]] = None
        self.app: Optional[Application] = None
        self.user_handler: Optional[UserHandler] = None
        self.admin_handler: Optional[AdminHandler] = None
        self.ai_parser: Optional[Any] = None
        self.metrics = PerformanceMetrics()
        self.is_running = False
        self._shutdown_requested = False
        
        # Настраиваем обработку сигналов
        self._setup_signal_handlers()
        
        logger.info("🚀 Инициализация оптимизированного AI CRM бота")

    def _setup_signal_handlers(self):
        """Настройка обработчиков сигналов для корректного завершения"""
        def signal_handler(signum, frame):
            logger.info(f"Получен сигнал {signum}, запуск процедуры завершения...")
            self._shutdown_requested = True
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

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
        
        # Логируем ключевую информацию (безопасно для Unicode)
        info = validation_report['info']
        logger.info(f"🤖 Бот: {info['bot_name']}")
        logger.info(f"👑 Админов: {info['admin_count']}")
        claude_status = "✅" if info['claude_enabled'] else "⚠️ Simple mode"
        logger.info(f"🧠 Claude API: {claude_status}")
        logger.info(f"📺 Каналов: {info['channels_count']}")
        dialogue_status = "✅" if info['dialogue_analysis_enabled'] else "❌"
        logger.info(f"💬 Анализ диалогов: {dialogue_status}")

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
        """Создание Telegram приложения с правильной конфигурацией"""
        logger.info("📱 Создание Telegram приложения...")
        
        try:
            bot_token = self.config['bot']['token']
            # ИСПРАВЛЕНИЕ: Используем builder с правильными настройками
            builder = Application.builder()
            builder.token(bot_token)
            
            # Настройки для избежания конфликтов
            builder.concurrent_updates(True)
            builder.rate_limiter(None)  # Отключаем встроенный rate limiter
            
            self.app = builder.build()
            
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
        """Настройка AI парсера с исправлением импортов"""
        logger.info("🤖 Настройка AI парсера...")
        
        try:
            # ИСПРАВЛЕНИЕ: Безопасный импорт с fallback
            try:
                from myparser.main_parser import OptimizedUnifiedParser
                self.ai_parser = OptimizedUnifiedParser(self.config)
                logger.info("✅ Использован OptimizedUnifiedParser")
            except ImportError as e:
                logger.warning(f"Не удалось импортировать OptimizedUnifiedParser: {e}")
                
                # Fallback на основной парсер
                try:
                    from myparser.main_parser import UnifiedAIParser
                    self.ai_parser = UnifiedAIParser(self.config)
                    logger.info("✅ Использован UnifiedAIParser")
                except ImportError:
                    # Последний fallback
                    from myparser import UnifiedAIParser
                    self.ai_parser = UnifiedAIParser(self.config)
                    logger.info("✅ Использован базовый UnifiedAIParser")
            
            self.app.bot_data['ai_parser'] = self.ai_parser
            
            # Передаем метрики парсеру
            if hasattr(self.ai_parser, 'set_metrics_callback'):
                self.ai_parser.set_metrics_callback(self._record_parser_metrics)
            
            logger.info("✅ AI парсер настроен")
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: парсер недоступен: {e}")
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
            
            # Структурированное логирование (безопасное для Unicode)
            log_data = {
                'event': 'message_received',
                'user_id': user.id,
                'chat_id': chat.id,
                'chat_type': chat.type,
                'message_length': len(update.message.text),
                'timestamp': datetime.now().isoformat()
            }
            
            logger.info(f"📨 Message received: {json.dumps(log_data, ensure_ascii=False)}")
            
            if chat.type == 'private':
                # Личные сообщения
                await self.user_handler.handle_message(update, context)
                logger.debug(f"Private message processed for user {user.id}")
                
            elif chat.type in ['group', 'supergroup', 'channel']:
                # Групповые сообщения - AI парсинг
                if self.ai_parser and hasattr(self.ai_parser, 'enabled') and self.ai_parser.enabled:
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
            if self.ai_parser and hasattr(self.ai_parser, 'get_status'):
                parser_status = self.ai_parser.get_status()
                status_enabled = "✅ Активен" if parser_status.get('enabled') else "❌ Отключен"
                status_info.append(f"🔍 **AI Парсер:** {status_enabled}")
                status_info.append(f"📺 **Каналов:** {parser_status.get('channels_count', 0)}")
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
                    claude_status = "✅ Работает" if health else "⚠️ Недоступен"
                    status_info.append(f"🧠 **Claude API:** {claude_status}")
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
• Коэффициент ошибок: {metrics['error_rate']:.2%}"""

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
                health_status.append(f"💾 **База данных:** ❌ Ошибка")
                overall_health = False
            
            # Проверка Claude API
            try:
                from ai.claude_client import get_claude_client
                claude_client = get_claude_client()
                if claude_client:
                    claude_health = await claude_client.health_check()
                    claude_status = "✅ Работает" if claude_health else "⚠️ Недоступен"
                    health_status.append(f"🧠 **Claude API:** {claude_status}")
                    if not claude_health:
                        overall_health = False
                else:
                    health_status.append("🧠 **Claude API:** ⚠️ Не настроен (простой режим)")
            except Exception:
                health_status.append("🧠 **Claude API:** ❌ Ошибка")
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
            
            if not hasattr(self.ai_parser.dialogue_tracker, 'active_dialogues'):
                await update.message.reply_text("❌ Активные диалоги недоступны")
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
        """ИСПРАВЛЕННЫЙ контекстный менеджер для запуска бота"""
        try:
            self.is_running = True
            
            # ИСПРАВЛЕНИЕ: Правильная инициализация приложения
            await self.app.initialize()
            await self.app.start()
            
            # Проверяем доступ к каналам
            await self.check_channels_access()
            
            logger.info("🎉 AI CRM Bot успешно запущен!")
            
            # Информация о режиме работы
            if self.ai_parser and hasattr(self.ai_parser, 'get_status'):
                status = self.ai_parser.get_status()
                logger.info(f"🎯 Режим: {status.get('mode', 'unknown')}")
                logger.info(f"📺 Мониторинг {status.get('channels_count', 0)} каналов")
            
            yield
            
        except Exception as e:
            logger.error(f"Ошибка в контексте запуска: {e}")
            raise
        finally:
            self.is_running = False
            # ИСПРАВЛЕНИЕ: Правильное завершение приложения
            try:
                if self.app and self.app.updater and self.app.updater.running:
                    await self.app.updater.stop()
                if self.app:
                    await self.app.stop()
                    await self.app.shutdown()
                logger.info("🛑 AI CRM Bot остановлен")
            except Exception as e:
                logger.error(f"Ошибка при остановке: {e}")

    async def run(self):
        """Главный метод запуска бота с исправлениями"""
        try:
            await self.initialize()
            
            async with self.run_context():
                # ИСПРАВЛЕНИЕ: Правильный запуск polling
                await self.app.updater.start_polling(
                    drop_pending_updates=True,
                    allowed_updates=['message', 'callback_query']
                )
                
                logger.info("🚀 Бот запущен и готов к работе!")
                
                # Запуск фоновых задач
                asyncio.create_task(self._background_tasks())
                
                # Основной цикл с проверкой сигналов
                while not self._shutdown_requested:
                    await asyncio.sleep(1)
                
                logger.info("🛑 Получен сигнал завершения")
                
        except KeyboardInterrupt:
            logger.info("👋 Получен сигнал остановки (Ctrl+C)")
        except Exception as e:
            logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
            raise

    async def _background_tasks(self):
        """Фоновые задачи"""
        try:
            # Ежедневный сброс метрик
            asyncio.create_task(self._daily_metrics_reset())
            
            # Мониторинг производительности
            asyncio.create_task(self._performance_monitor())
            
        except Exception as e:
            logger.error(f"Ошибка запуска фоновых задач: {e}")

    async def _daily_metrics_reset(self):
        """Ежедневный сброс метрик"""
        while self.is_running and not self._shutdown_requested:
            try:
                # Ждем до следующего дня
                now = datetime.now()
                tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                sleep_time = (tomorrow - now).total_seconds()
                
                # Ждем с проверкой сигнала завершения
                for _ in range(int(sleep_time)):
                    if self._shutdown_requested:
                        break
                    await asyncio.sleep(1)
                
                if not self._shutdown_requested:
                    # Сбрасываем метрики
                    self.metrics = PerformanceMetrics()
                    logger.info("📊 Ежедневные метрики сброшены")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка сброса метрик: {e}")
                await asyncio.sleep(3600)  # Повтор через час

    async def _performance_monitor(self):
        """Мониторинг производительности"""
        while self.is_running and not self._shutdown_requested:
            try:
                await asyncio.sleep(300)  # Каждые 5 минут
                
                if self._shutdown_requested:
                    break
                
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
    """Главная функция с исправлениями кодировки"""
    # ИСПРАВЛЕНИЕ: Настройка кодировки перед логированием
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
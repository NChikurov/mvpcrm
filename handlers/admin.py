"""
Оптимизированные обработчики админских команд
Рефакторинг согласно SOLID принципам, улучшенная производительность
"""

import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
from dataclasses import dataclass

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from database.operations import (
    get_users, get_leads, get_active_channels, 
    create_or_update_channel, get_bot_stats, get_setting, set_setting
)
from database.dialogue_db_migration import get_dialogue_stats, get_active_dialogues
from database.models import ParsedChannel

logger = logging.getLogger(__name__)

# === БАЗОВЫЕ КЛАССЫ И ИНТЕРФЕЙСЫ ===

@dataclass
class AdminCommand:
    """Модель админской команды"""
    name: str
    description: str
    permission_level: str = "admin"
    enabled: bool = True

class BaseAdminService(ABC):
    """Базовый класс для админских сервисов"""
    
    @abstractmethod
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
        pass

class CacheManager:
    """Менеджер кэша для админки"""
    
    def __init__(self, ttl_seconds: int = 300):  # 5 минут TTL
        self.cache: Dict[str, tuple] = {}  # key: (data, expiry_time)
        self.ttl = ttl_seconds
    
    def get(self, key: str) -> Optional[Any]:
        """Получение из кэша"""
        if key in self.cache:
            data, expiry = self.cache[key]
            if datetime.now().timestamp() < expiry:
                return data
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, data: Any):
        """Сохранение в кэш"""
        expiry = datetime.now().timestamp() + self.ttl
        self.cache[key] = (data, expiry)
        
        # Очистка устаревших записей
        if len(self.cache) > 100:
            self._cleanup_expired()
    
    def _cleanup_expired(self):
        """Очистка устаревших записей"""
        now = datetime.now().timestamp()
        expired_keys = [k for k, (_, expiry) in self.cache.items() if now >= expiry]
        for key in expired_keys:
            del self.cache[key]
    
    def invalidate(self, pattern: str = None):
        """Инвалидация кэша"""
        if pattern:
            keys_to_remove = [k for k in self.cache.keys() if pattern in k]
            for key in keys_to_remove:
                del self.cache[key]
        else:
            self.cache.clear()

# === СЕРВИСЫ АДМИНИСТРИРОВАНИЯ ===

class StatsService(BaseAdminService):
    """Сервис статистики"""
    
    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
        """Получение статистики с кэшированием"""
        cache_key = "admin_stats"
        cached_stats = self.cache.get(cache_key)
        
        if cached_stats:
            return cached_stats
        
        try:
            # Основная статистика
            bot_stats = await get_bot_stats()
            
            # Статистика диалогов
            dialogue_stats_7d = await get_dialogue_stats(7)
            dialogue_stats_30d = await get_dialogue_stats(30)
            
            # Активные диалоги
            active_dialogues = await get_active_dialogues()
            
            stats = {
                'bot_stats': bot_stats,
                'dialogue_stats_7d': dialogue_stats_7d,
                'dialogue_stats_30d': dialogue_stats_30d,
                'active_dialogues_count': len(active_dialogues),
                'timestamp': datetime.now().isoformat()
            }
            
            self.cache.set(cache_key, stats)
            return stats
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {'error': str(e)}

class UsersService(BaseAdminService):
    """Сервис управления пользователями"""
    
    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
        """Получение списка пользователей"""
        cache_key = "admin_users"
        cached_users = self.cache.get(cache_key)
        
        if cached_users:
            return cached_users
        
        try:
            users = await get_users(limit=50)
            
            # Дополнительная аналитика пользователей
            total_users = len(users)
            active_today = len([u for u in users if u.last_activity and 
                              (datetime.now() - u.last_activity).days == 0])
            active_week = len([u for u in users if u.last_activity and 
                             (datetime.now() - u.last_activity).days <= 7])
            
            result = {
                'users': users,
                'analytics': {
                    'total': total_users,
                    'active_today': active_today,
                    'active_week': active_week,
                    'retention_rate': (active_week / max(total_users, 1)) * 100
                },
                'timestamp': datetime.now().isoformat()
            }
            
            self.cache.set(cache_key, result)
            return result
            
        except Exception as e:
            logger.error(f"Error getting users: {e}")
            return {'error': str(e)}

class LeadsService(BaseAdminService):
    """Сервис управления лидами"""
    
    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
        """Получение и анализ лидов"""
        cache_key = "admin_leads"
        cached_leads = self.cache.get(cache_key)
        
        if cached_leads:
            return cached_leads
        
        try:
            leads = await get_leads(limit=100)
            
            # Аналитика лидов
            now = datetime.now()
            leads_today = [l for l in leads if l.created_at and 
                          (now - l.created_at).days == 0]
            leads_week = [l for l in leads if l.created_at and 
                         (now - l.created_at).days <= 7]
            
            # Качество лидов
            quality_distribution = {}
            for lead in leads:
                quality = lead.lead_quality or 'unknown'
                quality_distribution[quality] = quality_distribution.get(quality, 0) + 1
            
            # Источники лидов
            source_distribution = {}
            for lead in leads:
                source = lead.source_channel or 'unknown'
                source_distribution[source] = source_distribution.get(source, 0) + 1
            
            result = {
                'leads': leads[:20],  # Показываем только топ-20
                'analytics': {
                    'total': len(leads),
                    'today': len(leads_today),
                    'week': len(leads_week),
                    'avg_score': sum(l.interest_score for l in leads) / max(len(leads), 1),
                    'quality_distribution': quality_distribution,
                    'source_distribution': source_distribution,
                    'conversion_trend': self._calculate_conversion_trend(leads)
                },
                'timestamp': datetime.now().isoformat()
            }
            
            self.cache.set(cache_key, result)
            return result
            
        except Exception as e:
            logger.error(f"Error getting leads: {e}")
            return {'error': str(e)}
    
    def _calculate_conversion_trend(self, leads: List) -> List[Dict]:
        """Расчет тренда конверсии по дням"""
        if not leads:
            return []
        
        # Группируем лиды по дням за последнюю неделю
        daily_stats = {}
        for i in range(7):
            date = datetime.now() - timedelta(days=i)
            date_str = date.strftime('%Y-%m-%d')
            daily_stats[date_str] = {'date': date_str, 'leads': 0, 'quality_score': 0}
        
        for lead in leads:
            if lead.created_at:
                date_str = lead.created_at.strftime('%Y-%m-%d')
                if date_str in daily_stats:
                    daily_stats[date_str]['leads'] += 1
                    daily_stats[date_str]['quality_score'] += lead.interest_score
        
        # Вычисляем средний скор качества
        for stats in daily_stats.values():
            if stats['leads'] > 0:
                stats['avg_quality'] = stats['quality_score'] / stats['leads']
            else:
                stats['avg_quality'] = 0
            del stats['quality_score']  # Убираем временное поле
        
        return list(daily_stats.values())

class DialoguesService(BaseAdminService):
    """Сервис управления диалогами"""
    
    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
        """Получение информации о диалогах"""
        cache_key = "admin_dialogues"
        cached_dialogues = self.cache.get(cache_key)
        
        if cached_dialogues:
            return cached_dialogues
        
        try:
            # Активные диалоги
            active_dialogues = await get_active_dialogues()
            
            # Статистика за периоды
            stats_7d = await get_dialogue_stats(7)
            stats_30d = await get_dialogue_stats(30)
            
            # Анализ активных диалогов
            dialogue_analysis = []
            for dialogue in active_dialogues[:10]:  # Топ-10
                dialogue_id, channel_title, participants, messages, start_time, last_activity, is_business = dialogue
                
                duration_minutes = 0
                if start_time and last_activity:
                    start_dt = datetime.fromisoformat(start_time) if isinstance(start_time, str) else start_time
                    last_dt = datetime.fromisoformat(last_activity) if isinstance(last_activity, str) else last_activity
                    duration_minutes = (last_dt - start_dt).total_seconds() / 60
                
                dialogue_analysis.append({
                    'id': dialogue_id,
                    'channel': channel_title,
                    'participants': participants,
                    'messages': messages,
                    'duration_minutes': int(duration_minutes),
                    'is_business': bool(is_business),
                    'activity_score': self._calculate_activity_score(participants, messages, duration_minutes)
                })
            
            result = {
                'active_dialogues': dialogue_analysis,
                'stats_7d': stats_7d,
                'stats_30d': stats_30d,
                'analytics': {
                    'active_count': len(active_dialogues),
                    'avg_participants': stats_7d.get('avg_participants', 0),
                    'avg_messages': stats_7d.get('avg_messages', 0),
                    'business_dialogues_rate': (stats_7d.get('business_dialogues', 0) / 
                                              max(stats_7d.get('total_dialogues', 1), 1)) * 100,
                    'valuable_dialogues_rate': (stats_7d.get('valuable_dialogues', 0) / 
                                               max(stats_7d.get('total_dialogues', 1), 1)) * 100
                },
                'timestamp': datetime.now().isoformat()
            }
            
            self.cache.set(cache_key, result)
            return result
            
        except Exception as e:
            logger.error(f"Error getting dialogues: {e}")
            return {'error': str(e)}
    
    def _calculate_activity_score(self, participants: int, messages: int, duration: float) -> int:
        """Расчет скора активности диалога"""
        if duration <= 0:
            return 0
        
        # Нормализуем метрики
        participant_score = min(participants * 10, 50)  # До 50 баллов за участников
        message_density = messages / (duration / 60)  # Сообщений в час
        density_score = min(message_density * 5, 50)  # До 50 баллов за плотность
        
        return int(participant_score + density_score)

class BroadcastService(BaseAdminService):
    """Сервис рассылок"""
    
    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
        self.rate_limiter = {}  # user_id: last_broadcast_time
    
    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
        """Выполнение рассылки с rate limiting"""
        user_id = update.effective_user.id
        
        # Проверка rate limiting (не чаще раза в 10 минут)
        if user_id in self.rate_limiter:
            time_diff = datetime.now() - self.rate_limiter[user_id]
            if time_diff < timedelta(minutes=10):
                remaining = timedelta(minutes=10) - time_diff
                return {
                    'error': f'Rate limit exceeded. Try again in {remaining.seconds // 60} minutes.'
                }
        
        if not context.args:
            return {
                'error': 'No message text provided',
                'usage': 'Use: /broadcast Your message text here'
            }
        
        broadcast_text = " ".join(context.args)
        
        try:
            # Получаем пользователей пакетами для эффективности
            users = await get_users(limit=1000)
            
            if not users:
                return {'error': 'No users found for broadcast'}
            
            # Обновляем rate limiter
            self.rate_limiter[user_id] = datetime.now()
            
            # Выполняем рассылку асинхронно
            asyncio.create_task(self._execute_broadcast(
                broadcast_text, users, update.effective_user.first_name, context
            ))
            
            return {
                'success': True,
                'message': f'Broadcast started for {len(users)} users',
                'estimated_duration': f'{len(users) // 20} minutes'  # ~20 сообщений в минуту
            }
            
        except Exception as e:
            logger.error(f"Error starting broadcast: {e}")
            return {'error': str(e)}
    
    async def _execute_broadcast(self, text: str, users: List, admin_name: str, context):
        """Выполнение рассылки в фоне"""
        try:
            sent_count = 0
            failed_count = 0
            
            for user in users:
                try:
                    await context.bot.send_message(
                        chat_id=user.telegram_id,
                        text=text,
                        parse_mode='HTML'
                    )
                    sent_count += 1
                    
                    # Пауза для соблюдения лимитов Telegram
                    if sent_count % 20 == 0:
                        await asyncio.sleep(60)  # 1 минута каждые 20 сообщений
                    else:
                        await asyncio.sleep(0.1)  # Короткая пауза между сообщениями
                        
                except Exception as e:
                    failed_count += 1
                    logger.warning(f"Failed to send broadcast to {user.telegram_id}: {e}")
            
            # Уведомляем админа о завершении
            success_rate = (sent_count / (sent_count + failed_count)) * 100 if (sent_count + failed_count) > 0 else 0
            
            completion_message = f"""✅ **Рассылка завершена**

📤 Отправлено: {sent_count}
❌ Ошибок: {failed_count}
📊 Успешность: {success_rate:.1f}%

Инициатор: {admin_name}"""

            # Отправляем уведомление всем админам
            admin_ids = context.bot_data.get('config', {}).get('bot', {}).get('admin_ids', [])
            for admin_id in admin_ids:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=completion_message,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_id}: {e}")
            
        except Exception as e:
            logger.error(f"Critical error in broadcast execution: {e}")

# === ГЛАВНЫЙ КЛАСС ОБРАБОТЧИКА ===

class OptimizedAdminHandler:
    """Оптимизированный обработчик админских команд"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.admin_ids = config.get('bot', {}).get('admin_ids', [])
        
        # Менеджер кэша
        self.cache_manager = CacheManager(ttl_seconds=300)
        
        # Инициализация сервисов
        self.stats_service = StatsService(self.cache_manager)
        self.users_service = UsersService(self.cache_manager)
        self.leads_service = LeadsService(self.cache_manager)
        self.dialogues_service = DialoguesService(self.cache_manager)
        self.broadcast_service = BroadcastService(self.cache_manager)
        
        # Callback handler
        self.callback_handler = CallbackQueryHandler(
            self.handle_admin_callback,
            pattern=r'^admin_'
        )
        
        # Доступные команды
        self.commands = {
            'users': AdminCommand('users', 'Управление пользователями'),
            'leads': AdminCommand('leads', 'Управление лидами'),
            'stats': AdminCommand('stats', 'Статистика системы'),
            'dialogues': AdminCommand('dialogues', 'Анализ диалогов'),
            'broadcast': AdminCommand('broadcast', 'Рассылка сообщений'),
            'performance': AdminCommand('performance', 'Метрики производительности'),
            'cache': AdminCommand('cache', 'Управление кэшем')
        }
        
        logger.info(f"OptimizedAdminHandler initialized with {len(self.commands)} commands")

    def _is_admin(self, user_id: int) -> bool:
        """Проверка прав администратора"""
        return user_id in self.admin_ids

    async def _admin_required(self, update: Update) -> bool:
        """Декоратор проверки прав"""
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ У вас нет прав администратора")
            return False
        return True

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Главная админ панель с улучшенным интерфейсом"""
        if not await self._admin_required(update):
            return
        
        try:
            # Получаем краткую статистику для панели
            stats = await self.stats_service.execute(update, context)
            
            if 'error' in stats:
                status_text = "⚠️ Ошибка получения статистики"
            else:
                bot_stats = stats.get('bot_stats', {})
                dialogue_stats = stats.get('dialogue_stats_7d', {})
                
                status_text = f"""📊 **Текущий статус:**
👥 Пользователей: {bot_stats.get('total_users', 0)}
🎯 Лидов: {bot_stats.get('total_leads', 0)} (сегодня: {bot_stats.get('leads_today', 0)})
💬 Диалогов (7д): {dialogue_stats.get('total_dialogues', 0)}
🔥 Активных: {stats.get('active_dialogues_count', 0)}"""
            
            keyboard = [
                [
                    InlineKeyboardButton("👥 Пользователи", callback_data="admin_users"),
                    InlineKeyboardButton("🎯 Лиды", callback_data="admin_leads")
                ],
                [
                    InlineKeyboardButton("💬 Диалоги", callback_data="admin_dialogues"),
                    InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
                ],
                [
                    InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
                    InlineKeyboardButton("⚡ Производительность", callback_data="admin_performance")
                ],
                [
                    InlineKeyboardButton("🗄️ Кэш", callback_data="admin_cache"),
                    InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings")
                ],
                [
                    InlineKeyboardButton("🔄 Обновить", callback_data="admin_panel")
                ]
            ]
            
            message = f"🔧 **Административная панель**\n\n{status_text}\n\n*Выберите действие:*"
            
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in admin panel: {e}")
            await update.message.reply_text("❌ Ошибка загрузки админ панели")

    async def show_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показ детальной статистики"""
        if not await self._admin_required(update):
            return
        
        try:
            stats = await self.stats_service.execute(update, context)
            
            if 'error' in stats:
                await update.message.reply_text(f"❌ Ошибка: {stats['error']}")
                return
            
            bot_stats = stats.get('bot_stats', {})
            dialogue_stats_7d = stats.get('dialogue_stats_7d', {})
            dialogue_stats_30d = stats.get('dialogue_stats_30d', {})
            
            message = f"""📊 **Детальная статистика системы**

👥 **Пользователи:**
• Всего: {bot_stats.get('total_users', 0)}
• Активные (24ч): {bot_stats.get('active_users_today', 0)}
• Новые (неделя): {bot_stats.get('users_week', 0)}

💬 **Сообщения:**
• Всего обработано: {bot_stats.get('total_messages', 0)}

🎯 **Лиды:**
• Всего: {bot_stats.get('total_leads', 0)}
• За 24 часа: {bot_stats.get('leads_today', 0)}
• За неделю: {bot_stats.get('leads_week', 0)}
• Средний скор: {bot_stats.get('avg_lead_score', 0):.1f}

💬 **Диалоги (7 дней):**
• Всего: {dialogue_stats_7d.get('total_dialogues', 0)}
• Бизнес-диалоги: {dialogue_stats_7d.get('business_dialogues', 0)}
• Ценные: {dialogue_stats_7d.get('valuable_dialogues', 0)}
• Активные сейчас: {stats.get('active_dialogues_count', 0)}

📈 **Эффективность (30 дней):**
• Сред. участников: {dialogue_stats_30d.get('avg_participants', 0):.1f}
• Сред. сообщений: {dialogue_stats_30d.get('avg_messages', 0):.1f}
• Лидов из диалогов: {dialogue_stats_30d.get('total_leads_from_dialogues', 0)}

🕐 *Обновлено: {datetime.now().strftime('%H:%M:%S')}*"""

            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing stats: {e}")
            await update.message.reply_text("❌ Ошибка получения статистики")

    async def broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Рассылка с улучшенной обработкой"""
        if not await self._admin_required(update):
            return
        
        try:
            result = await self.broadcast_service.execute(update, context)
            
            if 'error' in result:
                if 'Rate limit' in result['error']:
                    await update.message.reply_text(
                        f"⏰ {result['error']}\n\nЭто ограничение защищает от случайных массовых рассылок."
                    )
                else:
                    usage = result.get('usage', '')
                    await update.message.reply_text(
                        f"❌ {result['error']}\n\n{usage}" if usage else f"❌ {result['error']}"
                    )
                return
            
            if result.get('success'):
                await update.message.reply_text(
                    f"✅ {result['message']}\n"
                    f"⏱️ Примерное время выполнения: {result['estimated_duration']}\n\n"
                    f"📊 Вы получите уведомление по завершении рассылки."
                )
            
        except Exception as e:
            logger.error(f"Error in broadcast: {e}")
            await update.message.reply_text("❌ Ошибка при запуске рассылки")

    async def handle_admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка callback запросов с улучшенной производительностью"""
        query = update.callback_query
        
        if not self._is_admin(query.from_user.id):
            await query.answer("❌ У вас нет прав администратора")
            return
        
        data = query.data
        logger.debug(f"Admin callback: {data} from user {query.from_user.id}")
        
        try:
            await query.answer()
            
            # Обработка различных callback'ов
            callback_handlers = {
                "admin_panel": self._show_admin_panel,
                "admin_users": self._show_users_callback,
                "admin_leads": self._show_leads_callback,
                "admin_dialogues": self._show_dialogues_callback,
                "admin_stats": self._show_stats_callback,
                "admin_broadcast": self._show_broadcast_info,
                "admin_performance": self._show_performance_callback,
                "admin_cache": self._show_cache_info,
                "admin_settings": self._show_settings_callback
            }
            
            handler = callback_handlers.get(data)
            if handler:
                await handler(query)
            else:
                logger.warning(f"Unknown admin callback: {data}")
                await query.edit_message_text("❌ Неизвестная команда")
                
        except Exception as e:
            logger.error(f"Error handling admin callback '{data}': {e}")
            try:
                await query.edit_message_text("❌ Произошла ошибка. Попробуйте еще раз.")
            except:
                pass

    async def _show_admin_panel(self, query):
        """Обновление админ панели"""
        try:
            # Быстрая статистика из кэша
            stats = self.cache_manager.get("admin_stats") or {}
            
            if stats:
                bot_stats = stats.get('bot_stats', {})
                status_text = f"""📊 **Текущий статус:**
👥 Пользователей: {bot_stats.get('total_users', 0)}
🎯 Лидов: {bot_stats.get('total_leads', 0)}
🔥 Активных диалогов: {stats.get('active_dialogues_count', 0)}"""
            else:
                status_text = "📊 *Загрузка статистики...*"
            
            keyboard = [
                [
                    InlineKeyboardButton("👥 Пользователи", callback_data="admin_users"),
                    InlineKeyboardButton("🎯 Лиды", callback_data="admin_leads")
                ],
                [
                    InlineKeyboardButton("💬 Диалоги", callback_data="admin_dialogues"),
                    InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
                ],
                [
                    InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
                    InlineKeyboardButton("⚡ Производительность", callback_data="admin_performance")
                ],
                [
                    InlineKeyboardButton("🗄️ Кэш", callback_data="admin_cache"),
                    InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings")
                ],
                [
                    InlineKeyboardButton("🔄 Обновить", callback_data="admin_panel")
                ]
            ]
            
            message = f"🔧 **Административная панель**\n\n{status_text}\n\n*Выберите действие:*"
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
            # Обновляем статистику в фоне если нужно
            if not stats:
                asyncio.create_task(self._update_stats_cache())
                
        except Exception as e:
            logger.error(f"Error updating admin panel: {e}")

    async def _update_stats_cache(self):
        """Обновление кэша статистики в фоне"""
        try:
            stats = await get_bot_stats()
            dialogue_stats = await get_dialogue_stats(7)
            active_dialogues = await get_active_dialogues()
            
            cache_data = {
                'bot_stats': stats,
                'dialogue_stats_7d': dialogue_stats,
                'active_dialogues_count': len(active_dialogues),
                'timestamp': datetime.now().isoformat()
            }
            
            self.cache_manager.set("admin_stats", cache_data)
            
        except Exception as e:
            logger.error(f"Error updating stats cache: {e}")

    async def _show_users_callback(self, query):
        """Показ пользователей через callback"""
        try:
            result = await self.users_service.execute(None, None)
            
            if 'error' in result:
                await query.edit_message_text(f"❌ Ошибка: {result['error']}")
                return
            
            analytics = result.get('analytics', {})
            users = result.get('users', [])
            
            message = f"""👥 **Пользователи системы**

📈 **Аналитика:**
• Всего пользователей: {analytics.get('total', 0)}
• Активные сегодня: {analytics.get('active_today', 0)}
• Активные за неделю: {analytics.get('active_week', 0)}
• Retention: {analytics.get('retention_rate', 0):.1f}%

📋 **Последние пользователи:**"""

            for user in users[:5]:
                username = f"@{user.username}" if user.username else "без username"
                activity = user.last_activity.strftime("%d.%m %H:%M") if user.last_activity else "никогда"
                message += f"\n• {user.first_name} ({username}) - {activity}"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin_users")],
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error showing users: {e}")
            await query.edit_message_text("❌ Ошибка получения данных о пользователях")

    async def _show_leads_callback(self, query):
        """Показ лидов через callback"""
        try:
            result = await self.leads_service.execute(None, None)
            
            if 'error' in result:
                await query.edit_message_text(f"❌ Ошибка: {result['error']}")
                return
            
            analytics = result.get('analytics', {})
            leads = result.get('leads', [])
            
            message = f"""🎯 **Потенциальные клиенты**

📈 **Аналитика:**
• Всего лидов: {analytics.get('total', 0)}
• За сегодня: {analytics.get('today', 0)}
• За неделю: {analytics.get('week', 0)}
• Средний скор: {analytics.get('avg_score', 0):.1f}

🏆 **Качество лидов:**"""

            quality_dist = analytics.get('quality_distribution', {})
            for quality, count in quality_dist.items():
                emoji = {"hot": "🔥", "warm": "⭐", "cold": "❄️"}.get(quality, "📊")
                message += f"\n{emoji} {quality}: {count}"
            
            message += "\n\n📋 **Последние лиды:**"
            for lead in leads[:3]:
                username = f"@{lead.username}" if lead.username else "без username"
                message += f"\n• {lead.first_name} ({username}) - {lead.interest_score}/100"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin_leads")],
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error showing leads: {e}")
            await query.edit_message_text("❌ Ошибка получения данных о лидах")

    async def _show_dialogues_callback(self, query):
        """Показ диалогов через callback"""
        try:
            result = await self.dialogues_service.execute(None, None)
            
            if 'error' in result:
                await query.edit_message_text(f"❌ Ошибка: {result['error']}")
                return
            
            analytics = result.get('analytics', {})
            active_dialogues = result.get('active_dialogues', [])
            
            message = f"""💬 **Диалоги системы**

📊 **Аналитика:**
• Активных диалогов: {analytics.get('active_count', 0)}
• Средне участников: {analytics.get('avg_participants', 0):.1f}
• Средне сообщений: {analytics.get('avg_messages', 0):.1f}
• Бизнес-диалоги: {analytics.get('business_dialogues_rate', 0):.1f}%
• Ценные диалоги: {analytics.get('valuable_dialogues_rate', 0):.1f}%

🔥 **Активные диалоги:**"""

            for dialogue in active_dialogues[:3]:
                business_emoji = "🏢" if dialogue.get('is_business') else "💬"
                message += f"\n{business_emoji} {dialogue.get('channel', 'N/A')}"
                message += f"\n   👥 {dialogue.get('participants', 0)} • 💬 {dialogue.get('messages', 0)} • ⚡ {dialogue.get('activity_score', 0)}"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin_dialogues")],
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error showing dialogues: {e}")
            await query.edit_message_text("❌ Ошибка получения данных о диалогах")

    async def _show_stats_callback(self, query):
        """Показ статистики через callback"""
        try:
            stats = await self.stats_service.execute(None, None)
            
            if 'error' in stats:
                await query.edit_message_text(f"❌ Ошибка: {stats['error']}")
                return
            
            bot_stats = stats.get('bot_stats', {})
            dialogue_stats = stats.get('dialogue_stats_7d', {})
            
            message = f"""📊 **Статистика системы**

👥 Пользователей: {bot_stats.get('total_users', 0)}
🎯 Лидов: {bot_stats.get('total_leads', 0)}
💬 Сообщений: {bot_stats.get('total_messages', 0)}
🔥 Диалогов (7д): {dialogue_stats.get('total_dialogues', 0)}

📈 **За сегодня:**
🆕 Лидов: {bot_stats.get('leads_today', 0)}
👤 Активных: {bot_stats.get('active_users_today', 0)}

🕐 *{datetime.now().strftime('%H:%M:%S')}*"""

            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")],
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error showing stats: {e}")
            await query.edit_message_text("❌ Ошибка получения статистики")

    async def _show_performance_callback(self, query):
        """Показ метрик производительности"""
        try:
            # Попытка получить метрики от бота
            bot_data = query.message.get_bot().bot_data
            ai_parser = bot_data.get('ai_parser')
            
            message = "⚡ **Метрики производительности**\n\n"
            
            if ai_parser and hasattr(ai_parser, 'get_performance_metrics'):
                metrics = ai_parser.get_performance_metrics()
                
                if not metrics.get('no_data'):
                    message += f"""📊 **AI Парсер:**
• Сообщений обработано: {metrics.get('messages_processed', 0)}
• Конверсия в лиды: {metrics.get('leads_conversion_rate', 0):.2f}%
• Частота уведомлений: {metrics.get('notification_rate', 0):.2f}%
• Коэффициент ошибок: {metrics.get('error_rate', 0):.2f}%
• Эффективность кэша: {metrics.get('cache_efficiency', 0)}

🗄️ **Кэш админки:**
• Записей в кэше: {len(self.cache_manager.cache)}"""
                else:
                    message += "📊 Недостаточно данных для анализа"
            else:
                message += "❌ Метрики производительности недоступны"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin_performance")],
                [InlineKeyboardButton("🗑️ Очистить кэш", callback_data="admin_cache_clear")],
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error showing performance: {e}")
            await query.edit_message_text("❌ Ошибка получения метрик производительности")

    async def _show_cache_info(self, query):
        """Информация о кэше"""
        try:
            cache_size = len(self.cache_manager.cache)
            
            # Анализ содержимого кэша
            cache_types = {}
            for key in self.cache_manager.cache.keys():
                cache_type = key.split('_')[0] if '_' in key else 'other'
                cache_types[cache_type] = cache_types.get(cache_type, 0) + 1
            
            message = f"""🗄️ **Управление кэшем**

📊 **Статистика:**
• Записей в кэше: {cache_size}
• TTL: {self.cache_manager.ttl} секунд

📋 **Типы данных:**"""

            for cache_type, count in cache_types.items():
                message += f"\n• {cache_type}: {count}"
            
            keyboard = [
                [
                    InlineKeyboardButton("🗑️ Очистить весь кэш", callback_data="admin_cache_clear_all"),
                    InlineKeyboardButton("🔄 Обновить", callback_data="admin_cache")
                ],
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error showing cache info: {e}")
            await query.edit_message_text("❌ Ошибка получения информации о кэше")

    async def _show_broadcast_info(self, query):
        """Информация о рассылке"""
        message = """📢 **Рассылка сообщений**

💡 **Использование:**
`/broadcast Текст вашего сообщения`

⚠️ **Ограничения:**
• Не чаще 1 раза в 10 минут
• Автоматические паузы между отправками
• Уведомление о завершении

📊 **Примеры:**
• `/broadcast Новая акция! Скидка 20%`
• `/broadcast Обновление системы завтра в 2:00`

🔒 **Безопасность:**
Все рассылки логируются с указанием инициатора."""

        keyboard = [
            [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def _show_settings_callback(self, query):
        """Показ настроек системы"""
        try:
            # Получение информации о системе
            message = "⚙️ **Настройки системы**\n\n"
            
            # Claude API статус
            try:
                from ai.claude_client import get_claude_client
                claude_client = get_claude_client()
                if claude_client:
                    stats = claude_client.get_usage_stats()
                    claude_status = "✅ Активен" if stats['api_available'] else "⚠️ Простой режим"
                    message += f"🧠 Claude API: {claude_status}\n"
                    message += f"• Модель: {stats['model']}\n"
                else:
                    message += "🧠 Claude API: ❌ Не настроен\n"
            except Exception:
                message += "🧠 Claude API: ❌ Ошибка проверки\n"
            
            message += f"\n👑 Админов: {len(self.admin_ids)}\n"
            message += f"📺 Парсинг: {'✅' if self.config.get('parsing', {}).get('enabled') else '❌'}\n"
            message += f"💬 Диалоги: {'✅' if self.config.get('parsing', {}).get('dialogue_analysis_enabled') else '❌'}\n"
            message += f"📢 Автоответы: {'✅' if self.config.get('features', {}).get('auto_response') else '❌'}\n"
            
            message += "\n💡 Настройки в `.env` и `config.yaml`"
            
            keyboard = [
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error showing settings: {e}")
            await query.edit_message_text("❌ Ошибка получения настроек")

# Алиас для совместимости
AdminHandler = OptimizedAdminHandler
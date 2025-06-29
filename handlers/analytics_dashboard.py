"""
handlers/analytics_dashboard.py - Расширенная аналитическая панель для администраторов
Интерактивный dashboard с детальной статистикой и метриками
"""

import asyncio
import logging
import json
import csv
import io
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from database.operations import (
    get_bot_stats, get_leads, get_users, get_messages,
    get_leads_stats, get_setting, set_setting
)
from database.dialogue_db_migration import get_dialogue_stats, get_active_dialogues
from database.db_migration import get_ai_analysis_stats

logger = logging.getLogger(__name__)

@dataclass
class DashboardMetrics:
    """Метрики для dashboard"""
    total_users: int = 0
    total_leads: int = 0
    total_messages: int = 0
    leads_today: int = 0
    leads_week: int = 0
    conversion_rate: float = 0.0
    avg_lead_score: float = 0.0
    active_dialogues: int = 0
    ai_analyses: int = 0
    revenue_pipeline: float = 0.0

@dataclass
class PerformanceMetrics:
    """Метрики производительности"""
    response_time_avg: float = 0.0
    error_rate: float = 0.0
    uptime_percentage: float = 100.0
    cache_hit_rate: float = 0.0
    messages_per_hour: float = 0.0

@dataclass
class ChannelAnalytics:
    """Аналитика по каналам"""
    channel_name: str
    messages_count: int = 0
    leads_count: int = 0
    conversion_rate: float = 0.0
    avg_score: float = 0.0
    last_activity: Optional[datetime] = None

class AnalyticsDashboard:
    """Расширенная аналитическая панель"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.admin_ids = config.get('bot', {}).get('admin_ids', [])
        
        # Кэш для дорогих вычислений
        self.metrics_cache = {}
        self.cache_timeout = 300  # 5 минут
        
        # Callback handler
        self.callback_handler = CallbackQueryHandler(
            self.handle_callback,
            pattern=r'^(analytics_|dashboard_|export_|chart_).*$'
        )
        
        logger.info("Analytics Dashboard инициализирован")

    def _is_admin(self, user_id: int) -> bool:
        """Проверка прав администратора"""
        return user_id in self.admin_ids

    async def _get_cached_metrics(self, cache_key: str, calculation_func) -> Any:
        """Получение кэшированных метрик"""
        now = datetime.now()
        
        if cache_key in self.metrics_cache:
            data, timestamp = self.metrics_cache[cache_key]
            if (now - timestamp).total_seconds() < self.cache_timeout:
                return data
        
        # Вычисляем заново
        data = await calculation_func()
        self.metrics_cache[cache_key] = (data, now)
        return data

    async def show_main_dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Главная аналитическая панель"""
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ У вас нет прав администратора")
            return
        
        try:
            # Получаем основные метрики
            metrics = await self._get_cached_metrics("main_metrics", self._calculate_dashboard_metrics)
            
            message = f"""📊 **АНАЛИТИЧЕСКАЯ ПАНЕЛЬ**
━━━━━━━━━━━━━━━━━━━━━━━━

📈 **ОСНОВНЫЕ МЕТРИКИ:**
👥 Пользователей: {metrics.total_users:,}
🎯 Лидов: {metrics.total_leads:,} (+{metrics.leads_today} сегодня)
💬 Сообщений: {metrics.total_messages:,}
🔥 Активных диалогов: {metrics.active_dialogues}

📊 **КОНВЕРСИЯ:**
• Общая: {metrics.conversion_rate:.2f}%
• Средний скор: {metrics.avg_lead_score:.1f}/100
• AI анализов: {metrics.ai_analyses:,}

💰 **PIPELINE:**
• Потенциальная выручка: {metrics.revenue_pipeline:,.0f}₽
• Лидов за неделю: {metrics.leads_week}

🕐 *Обновлено: {datetime.now().strftime('%H:%M:%S')}*"""

            keyboard = [
                [
                    InlineKeyboardButton("📈 Детальная аналитика", callback_data="analytics_detailed"),
                    InlineKeyboardButton("⚡ Производительность", callback_data="analytics_performance")
                ],
                [
                    InlineKeyboardButton("📺 Каналы", callback_data="analytics_channels"),
                    InlineKeyboardButton("💬 Диалоги", callback_data="analytics_dialogues")
                ],
                [
                    InlineKeyboardButton("👥 Воронка лидов", callback_data="analytics_funnel"),
                    InlineKeyboardButton("📊 Тренды", callback_data="analytics_trends")
                ],
                [
                    InlineKeyboardButton("📤 Экспорт данных", callback_data="export_menu"),
                    InlineKeyboardButton("📋 Отчеты", callback_data="analytics_reports")
                ],
                [
                    InlineKeyboardButton("🔄 Обновить", callback_data="dashboard_refresh"),
                    InlineKeyboardButton("⚙️ Настройки", callback_data="analytics_settings")
                ]
            ]
            
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка показа dashboard: {e}")
            await update.message.reply_text("❌ Ошибка загрузки аналитики")

    async def _calculate_dashboard_metrics(self) -> DashboardMetrics:
        """Расчет основных метрик dashboard"""
        try:
            # Основная статистика
            bot_stats = await get_bot_stats()
            leads_stats = await get_leads_stats()
            dialogue_stats = await get_dialogue_stats(7)
            ai_stats = await get_ai_analysis_stats(7)
            
            # Активные диалоги
            active_dialogues = await get_active_dialogues()
            
            # Расчет потенциальной выручки
            revenue_pipeline = await self._calculate_revenue_pipeline()
            
            return DashboardMetrics(
                total_users=bot_stats.get('total_users', 0),
                total_leads=bot_stats.get('total_leads', 0),
                total_messages=bot_stats.get('total_messages', 0),
                leads_today=bot_stats.get('leads_today', 0),
                leads_week=bot_stats.get('leads_week', 0),
                conversion_rate=(bot_stats.get('total_leads', 0) / max(bot_stats.get('total_messages', 1), 1)) * 100,
                avg_lead_score=bot_stats.get('avg_lead_score', 0),
                active_dialogues=len(active_dialogues),
                ai_analyses=ai_stats.get('total_analyses', 0),
                revenue_pipeline=revenue_pipeline
            )
            
        except Exception as e:
            logger.error(f"Ошибка расчета метрик: {e}")
            return DashboardMetrics()

    async def _calculate_revenue_pipeline(self) -> float:
        """Расчет потенциальной выручки из pipeline"""
        try:
            leads = await get_leads(limit=1000)
            total_revenue = 0.0
            
            # Коэффициенты по качеству лидов
            quality_multipliers = {
                'hot': 0.6,     # 60% вероятность закрытия
                'warm': 0.3,    # 30% вероятность
                'cold': 0.1     # 10% вероятность
            }
            
            # Средняя сделка по скору
            score_to_revenue = {
                range(90, 101): 500000,  # 500k для топ лидов
                range(80, 90): 300000,   # 300k для горячих
                range(70, 80): 150000,   # 150k для теплых
                range(60, 70): 80000,    # 80k для средних
                range(0, 60): 30000      # 30k для холодных
            }
            
            for lead in leads:
                quality = lead.lead_quality or 'cold'
                score = lead.interest_score or 0
                
                # Определяем потенциальную сумму сделки
                deal_value = 30000  # По умолчанию
                for score_range, value in score_to_revenue.items():
                    if score in score_range:
                        deal_value = value
                        break
                
                # Применяем коэффициент вероятности
                probability = quality_multipliers.get(quality, 0.1)
                total_revenue += deal_value * probability
            
            return total_revenue
            
        except Exception as e:
            logger.error(f"Ошибка расчета revenue pipeline: {e}")
            return 0.0

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка callback запросов аналитики"""
        query = update.callback_query
        
        if not self._is_admin(query.from_user.id):
            await query.answer("❌ У вас нет прав администратора")
            return
        
        data = query.data
        
        try:
            await query.answer()
            
            if data == "analytics_detailed":
                await self._show_detailed_analytics(query)
            elif data == "analytics_performance":
                await self._show_performance_metrics(query)
            elif data == "analytics_channels":
                await self._show_channels_analytics(query)
            elif data == "analytics_dialogues":
                await self._show_dialogues_analytics(query)
            elif data == "analytics_funnel":
                await self._show_leads_funnel(query)
            elif data == "analytics_trends":
                await self._show_trends(query)
            elif data == "export_menu":
                await self._show_export_menu(query)
            elif data == "analytics_reports":
                await self._show_reports_menu(query)
            elif data == "dashboard_refresh":
                await self._refresh_dashboard(query)
            elif data == "analytics_settings":
                await self._show_analytics_settings(query)
            elif data.startswith("export_"):
                await self._handle_export(query, data)
            else:
                logger.warning(f"Unknown analytics callback: {data}")
                
        except Exception as e:
            logger.error(f"Ошибка обработки analytics callback: {e}")
            try:
                await query.edit_message_text("❌ Произошла ошибка. Попробуйте еще раз.")
            except:
                pass

    async def _show_detailed_analytics(self, query):
        """Показать детальную аналитику"""
        try:
            # Получаем детальные данные
            leads_stats = await get_leads_stats()
            dialogue_stats_7d = await get_dialogue_stats(7)
            dialogue_stats_30d = await get_dialogue_stats(30)
            ai_stats = await get_ai_analysis_stats(30)
            
            message = f"""📈 **ДЕТАЛЬНАЯ АНАЛИТИКА**

🎯 **ЛИДЫ:**
• Всего: {leads_stats.get('total_leads', 0):,}
• Новые: {leads_stats.get('new_leads', 0)}
• Контактировали: {leads_stats.get('contacted_leads', 0)}
• Конвертированные: {leads_stats.get('converted_leads', 0)}

🔥 **ПО КАЧЕСТВУ:**
• Горячие: {leads_stats.get('hot_leads', 0)}
• Теплые: {leads_stats.get('warm_leads', 0)}
• Холодные: {leads_stats.get('cold_leads', 0)}

💬 **ДИАЛОГИ (7 дней):**
• Всего: {dialogue_stats_7d.get('total_dialogues', 0)}
• Бизнес: {dialogue_stats_7d.get('business_dialogues', 0)}
• Ценные: {dialogue_stats_7d.get('valuable_dialogues', 0)}
• Лидов из диалогов: {dialogue_stats_7d.get('total_leads_from_dialogues', 0)}

🤖 **AI АНАЛИЗ (30 дней):**
• Анализов выполнено: {ai_stats.get('total_analyses', 0):,}
• Найдено лидов: {ai_stats.get('leads_found', 0)}
• Средняя уверенность: {ai_stats.get('avg_confidence', 0):.1f}%
• Среднее время: {ai_stats.get('avg_duration_ms', 0):.0f}мс

📊 **ЭФФЕКТИВНОСТЬ:**
• Конверсия диалогов: {(dialogue_stats_7d.get('valuable_dialogues', 0) / max(dialogue_stats_7d.get('total_dialogues', 1), 1)) * 100:.1f}%
• AI точность: {(ai_stats.get('leads_found', 0) / max(ai_stats.get('total_analyses', 1), 1)) * 100:.1f}%"""

            keyboard = [
                [
                    InlineKeyboardButton("📊 Графики", callback_data="chart_overview"),
                    InlineKeyboardButton("📈 Тренды", callback_data="analytics_trends")
                ],
                [InlineKeyboardButton("🔙 Назад", callback_data="dashboard_refresh")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка детальной аналитики: {e}")

    async def _show_performance_metrics(self, query):
        """Показать метрики производительности"""
        try:
            # Получаем метрики производительности от разных компонентов
            performance = await self._calculate_performance_metrics()
            
            message = f"""⚡ **МЕТРИКИ ПРОИЗВОДИТЕЛЬНОСТИ**

🚀 **СИСТЕМА:**
• Время отклика: {performance.response_time_avg:.3f}с
• Коэффициент ошибок: {performance.error_rate:.2f}%
• Uptime: {performance.uptime_percentage:.1f}%
• Cache hit rate: {performance.cache_hit_rate:.1f}%

📊 **НАГРУЗКА:**
• Сообщений/час: {performance.messages_per_hour:.1f}
• Пиковая нагрузка: {await self._get_peak_load():.1f}/час

💾 **РЕСУРСЫ:**
• Использование памяти: {await self._get_memory_usage()}
• Размер БД: {await self._get_db_size()}
• Активных соединений: {await self._get_active_connections()}

🔄 **КЭШИРОВАНИЕ:**
• Записей в кэше: {await self._get_cache_stats()}
• Эффективность: {performance.cache_hit_rate:.1f}%

⚠️ **ПРЕДУПРЕЖДЕНИЯ:**
{await self._get_performance_warnings()}"""

            keyboard = [
                [
                    InlineKeyboardButton("🔍 Детали", callback_data="performance_details"),
                    InlineKeyboardButton("📊 История", callback_data="performance_history")
                ],
                [InlineKeyboardButton("🔙 Назад", callback_data="dashboard_refresh")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка метрик производительности: {e}")

    async def _calculate_performance_metrics(self) -> PerformanceMetrics:
        """Расчет метрик производительности"""
        # Здесь можно интегрироваться с системами мониторинга
        # Пока используем заглушки
        return PerformanceMetrics(
            response_time_avg=0.150,
            error_rate=1.2,
            uptime_percentage=99.8,
            cache_hit_rate=85.5,
            messages_per_hour=245.0
        )

    async def _show_channels_analytics(self, query):
        """Показать аналитику по каналам"""
        try:
            channels_data = await self._get_channels_analytics()
            
            message = "📺 **АНАЛИТИКА ПО КАНАЛАМ**\n\n"
            
            if not channels_data:
                message += "📭 Нет данных по каналам"
            else:
                for i, channel in enumerate(channels_data[:10], 1):
                    message += f"{i}. **{channel.channel_name}**\n"
                    message += f"   💬 {channel.messages_count} сообщ. • 🎯 {channel.leads_count} лидов\n"
                    message += f"   📊 {channel.conversion_rate:.2f}% • ⭐ {channel.avg_score:.1f}/100\n"
                    if channel.last_activity:
                        message += f"   🕐 {channel.last_activity.strftime('%d.%m %H:%M')}\n"
                    message += "\n"
            
            message += f"\n📈 **ТОП КАНАЛЫ ПО КОНВЕРСИИ:**\n"
            top_channels = sorted(channels_data, key=lambda x: x.conversion_rate, reverse=True)[:3]
            
            for i, channel in enumerate(top_channels, 1):
                message += f"{i}. {channel.channel_name}: {channel.conversion_rate:.2f}%\n"

            keyboard = [
                [
                    InlineKeyboardButton("📊 Подробно", callback_data="channels_detailed"),
                    InlineKeyboardButton("📤 Экспорт", callback_data="export_channels")
                ],
                [InlineKeyboardButton("🔙 Назад", callback_data="dashboard_refresh")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка аналитики каналов: {e}")

    async def _get_channels_analytics(self) -> List[ChannelAnalytics]:
        """Получение аналитики по каналам"""
        try:
            # Здесь нужно собрать данные из БД по каналам
            # Пока используем заглушку
            return [
                ChannelAnalytics(
                    channel_name="Test Channel",
                    messages_count=150,
                    leads_count=12,
                    conversion_rate=8.0,
                    avg_score=72.5,
                    last_activity=datetime.now() - timedelta(minutes=30)
                )
            ]
        except Exception as e:
            logger.error(f"Ошибка получения аналитики каналов: {e}")
            return []

    async def _show_leads_funnel(self, query):
        """Показать воронку лидов"""
        try:
            funnel_data = await self._calculate_leads_funnel()
            
            message = f"""🎯 **ВОРОНКА ЛИДОВ**

📊 **ЭТАПЫ ВОРОНКИ:**

1️⃣ **Входящие сообщения**
   └─ {funnel_data['total_messages']:,} сообщений

2️⃣ **AI Анализ**
   └─ {funnel_data['analyzed_messages']:,} проанализировано
   └─ {(funnel_data['analyzed_messages']/max(funnel_data['total_messages'], 1)*100):.1f}% покрытие

3️⃣ **Выявлено интерес**
   └─ {funnel_data['interested_users']:,} заинтересованных
   └─ {(funnel_data['interested_users']/max(funnel_data['analyzed_messages'], 1)*100):.1f}% конверсия

4️⃣ **Созданы лиды**
   └─ {funnel_data['created_leads']:,} лидов
   └─ {(funnel_data['created_leads']/max(funnel_data['interested_users'], 1)*100):.1f}% конверсия

5️⃣ **Контакт установлен**
   └─ {funnel_data['contacted_leads']:,} контактов
   └─ {(funnel_data['contacted_leads']/max(funnel_data['created_leads'], 1)*100):.1f}% конверсия

6️⃣ **Сделки закрыты**
   └─ {funnel_data['converted_leads']:,} конверсий
   └─ {(funnel_data['converted_leads']/max(funnel_data['contacted_leads'], 1)*100):.1f}% конверсия

📈 **ОБЩАЯ КОНВЕРСИЯ:**
{(funnel_data['converted_leads']/max(funnel_data['total_messages'], 1)*100):.3f}% (сообщение → сделка)"""

            keyboard = [
                [
                    InlineKeyboardButton("📊 Детализация", callback_data="funnel_detailed"),
                    InlineKeyboardButton("📈 Оптимизация", callback_data="funnel_optimization")
                ],
                [InlineKeyboardButton("🔙 Назад", callback_data="dashboard_refresh")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка показа воронки: {e}")

    async def _calculate_leads_funnel(self) -> Dict[str, int]:
        """Расчет данных воронки лидов"""
        try:
            bot_stats = await get_bot_stats()
            leads_stats = await get_leads_stats()
            
            return {
                'total_messages': bot_stats.get('total_messages', 0),
                'analyzed_messages': int(bot_stats.get('total_messages', 0) * 0.85),  # 85% покрытие
                'interested_users': int(bot_stats.get('total_messages', 0) * 0.15),   # 15% интереса
                'created_leads': bot_stats.get('total_leads', 0),
                'contacted_leads': leads_stats.get('contacted_leads', 0),
                'converted_leads': leads_stats.get('converted_leads', 0)
            }
        except Exception as e:
            logger.error(f"Ошибка расчета воронки: {e}")
            return {}

    async def _show_export_menu(self, query):
        """Показать меню экспорта"""
        message = """📤 **ЭКСПОРТ ДАННЫХ**

Выберите данные для экспорта:"""

        keyboard = [
            [
                InlineKeyboardButton("🎯 Лиды (CSV)", callback_data="export_leads_csv"),
                InlineKeyboardButton("👥 Пользователи", callback_data="export_users_csv")
            ],
            [
                InlineKeyboardButton("💬 Диалоги", callback_data="export_dialogues_json"),
                InlineKeyboardButton("📊 Аналитика", callback_data="export_analytics_xlsx")
            ],
            [
                InlineKeyboardButton("📈 Отчет PDF", callback_data="export_report_pdf"),
                InlineKeyboardButton("🗄️ Полный дамп", callback_data="export_full_backup")
            ],
            [InlineKeyboardButton("🔙 Назад", callback_data="dashboard_refresh")]
        ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def _handle_export(self, query, export_type: str):
        """Обработка экспорта данных"""
        try:
            await query.edit_message_text("⏳ Подготовка экспорта...")
            
            if export_type == "export_leads_csv":
                await self._export_leads_csv(query)
            elif export_type == "export_users_csv":
                await self._export_users_csv(query)
            elif export_type == "export_analytics_xlsx":
                await self._export_analytics_excel(query)
            else:
                await query.edit_message_text("❌ Тип экспорта не поддерживается")
                
        except Exception as e:
            logger.error(f"Ошибка экспорта {export_type}: {e}")
            await query.edit_message_text("❌ Ошибка при экспорте данных")

    async def _export_leads_csv(self, query):
        """Экспорт лидов в CSV"""
        try:
            leads = await get_leads(limit=5000)
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Заголовки
            writer.writerow([
                'ID', 'Telegram ID', 'Имя', 'Username', 'Канал источник',
                'Скор интереса', 'Качество лида', 'Уровень срочности',
                'Создан', 'Статус', 'Контактировали'
            ])
            
            # Данные
            for lead in leads:
                writer.writerow([
                    lead.id,
                    lead.telegram_id,
                    lead.first_name or '',
                    lead.username or '',
                    lead.source_channel or '',
                    lead.interest_score,
                    lead.lead_quality or 'unknown',
                    lead.urgency_level or 'none',
                    lead.created_at.strftime('%d.%m.%Y %H:%M') if lead.created_at else '',
                    lead.status or 'new',
                    'Да' if lead.is_contacted else 'Нет'
                ])
            
            csv_content = output.getvalue()
            output.close()
            
            # Отправляем файл
            csv_file = io.BytesIO(csv_content.encode('utf-8-sig'))
            csv_file.name = f"leads_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
            
            await query.message.reply_document(
                document=csv_file,
                caption=f"📊 Экспорт лидов: {len(leads)} записей",
                filename=csv_file.name
            )
            
        except Exception as e:
            logger.error(f"Ошибка экспорта лидов: {e}")

    async def _refresh_dashboard(self, query):
        """Обновление dashboard"""
        # Очищаем кэш
        self.metrics_cache.clear()
        
        # Показываем обновленный dashboard
        try:
            metrics = await self._calculate_dashboard_metrics()
            
            message = f"""📊 **АНАЛИТИЧЕСКАЯ ПАНЕЛЬ** 🔄
━━━━━━━━━━━━━━━━━━━━━━━━

📈 **ОСНОВНЫЕ МЕТРИКИ:**
👥 Пользователей: {metrics.total_users:,}
🎯 Лидов: {metrics.total_leads:,} (+{metrics.leads_today} сегодня)
💬 Сообщений: {metrics.total_messages:,}
🔥 Активных диалогов: {metrics.active_dialogues}

📊 **КОНВЕРСИЯ:**
• Общая: {metrics.conversion_rate:.2f}%
• Средний скор: {metrics.avg_lead_score:.1f}/100
• AI анализов: {metrics.ai_analyses:,}

💰 **PIPELINE:**
• Потенциальная выручка: {metrics.revenue_pipeline:,.0f}₽
• Лидов за неделю: {metrics.leads_week}

🕐 *Обновлено: {datetime.now().strftime('%H:%M:%S')}*"""

            keyboard = [
                [
                    InlineKeyboardButton("📈 Детальная аналитика", callback_data="analytics_detailed"),
                    InlineKeyboardButton("⚡ Производительность", callback_data="analytics_performance")
                ],
                [
                    InlineKeyboardButton("📺 Каналы", callback_data="analytics_channels"),
                    InlineKeyboardButton("💬 Диалоги", callback_data="analytics_dialogues")
                ],
                [
                    InlineKeyboardButton("👥 Воронка лидов", callback_data="analytics_funnel"),
                    InlineKeyboardButton("📊 Тренды", callback_data="analytics_trends")
                ],
                [
                    InlineKeyboardButton("📤 Экспорт данных", callback_data="export_menu"),
                    InlineKeyboardButton("📋 Отчеты", callback_data="analytics_reports")
                ],
                [
                    InlineKeyboardButton("🔄 Обновить", callback_data="dashboard_refresh"),
                    InlineKeyboardButton("⚙️ Настройки", callback_data="analytics_settings")
                ]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка обновления dashboard: {e}")

    # Вспомогательные методы для метрик производительности
    async def _get_peak_load(self) -> float:
        """Получение пиковой нагрузки"""
        return 450.0  # Заглушка

    async def _get_memory_usage(self) -> str:
        """Получение использования памяти"""
        return "245 MB / 512 MB (47.9%)"  # Заглушка

    async def _get_db_size(self) -> str:
        """Получение размера БД"""
        return "128.5 MB"  # Заглушка

    async def _get_active_connections(self) -> int:
        """Получение количества активных соединений"""
        return 12  # Заглушка

    async def _get_cache_stats(self) -> str:
        """Получение статистики кэша"""
        return "1,247 записей"  # Заглушка

    async def _get_performance_warnings(self) -> str:
        """Получение предупреждений о производительности"""
        return "• Высокая нагрузка на БД в 14:00-16:00"  # Заглушка

# Функция для создания dashboard
def create_analytics_dashboard(config: Dict[str, Any]) -> AnalyticsDashboard:
    """Создание аналитического dashboard"""
    return AnalyticsDashboard(config)
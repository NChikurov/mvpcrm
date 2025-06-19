"""
handlers/enhanced_admin.py - Расширенные админские команды для анализа диалогов
"""

import asyncio
import logging
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from database.operations import (
    get_users, get_leads, get_active_channels, 
    create_or_update_channel, get_bot_stats, get_setting, set_setting
)
from database.dialogue_migration import (
    get_dialogue_stats, get_active_dialogues, export_dialogue_data, cleanup_old_dialogues
)
from database.models import ParsedChannel, Broadcast

logger = logging.getLogger(__name__)

class EnhancedAdminHandler:
    """Расширенный обработчик админских команд с поддержкой анализа диалогов"""
    
    def __init__(self, config):
        self.config = config
        self.admin_ids = config.get('bot', {}).get('admin_ids', [])
        
        # Callback handler - расширенный для диалогов
        self.callback_handler = CallbackQueryHandler(
            self.handle_admin_callback,
            pattern=r'^admin_'
        )

    def _is_admin(self, user_id: int) -> bool:
        """Проверка является ли пользователь админом"""
        return user_id in self.admin_ids

    async def _admin_required(self, update: Update) -> bool:
        """Декоратор для проверки прав админа"""
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await update.message.reply_text("❌ У вас нет прав администратора")
            return False
        return True

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Главная админ панель с поддержкой диалогов"""
        if not await self._admin_required(update):
            return
        
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
                InlineKeyboardButton("📺 Каналы", callback_data="admin_channels"),
                InlineKeyboardButton("🤖 AI Статус", callback_data="admin_ai_status")
            ],
            [
                InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
                InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings")
            ],
            [
                InlineKeyboardButton("📈 Отчеты", callback_data="admin_reports"),
                InlineKeyboardButton("🔧 Утилиты", callback_data="admin_utilities")
            ]
        ]
        
        await update.message.reply_text(
            "🔧 <b>Расширенная админ панель</b>\n\n"
            "🆕 Теперь с поддержкой анализа диалогов!\n\n"
            "Выберите действие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    async def dialogue_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда для получения статистики диалогов"""
        if not await self._admin_required(update):
            return
        
        try:
            # Получаем статистику за разные периоды
            stats_7d = await get_dialogue_stats(7)
            stats_30d = await get_dialogue_stats(30)
            
            message = "📊 <b>Статистика анализа диалогов</b>\n\n"
            
            message += "📅 <b>За 7 дней:</b>\n"
            message += f"• Всего диалогов: {stats_7d.get('total_dialogues', 0)}\n"
            message += f"• Завершенных: {stats_7d.get('completed_dialogues', 0)}\n"
            message += f"• Бизнес-диалогов: {stats_7d.get('business_dialogues', 0)}\n"
            message += f"• Проанализировано: {stats_7d.get('total_analyses', 0)}\n"
            message += f"• Ценных диалогов: {stats_7d.get('valuable_dialogues', 0)}\n"
            message += f"• Лидов из диалогов: {stats_7d.get('total_leads_from_dialogues', 0)}\n\n"
            
            message += "📅 <b>За 30 дней:</b>\n"
            message += f"• Всего диалогов: {stats_30d.get('total_dialogues', 0)}\n"
            message += f"• Средне участников: {stats_30d.get('avg_participants', 0):.1f}\n"
            message += f"• Средне сообщений: {stats_30d.get('avg_messages', 0):.1f}\n"
            message += f"• Средняя уверенность: {stats_30d.get('avg_confidence', 0):.1f}%\n"
            
            # Вычисляем метрики эффективности
            if stats_7d.get('total_dialogues', 0) > 0:
                business_rate = (stats_7d.get('business_dialogues', 0) / stats_7d.get('total_dialogues', 1)) * 100
                valuable_rate = (stats_7d.get('valuable_dialogues', 0) / stats_7d.get('business_dialogues', 1)) * 100
                
                message += f"\n📈 <b>Эффективность (7 дней):</b>\n"
                message += f"• Бизнес-диалоги: {business_rate:.1f}%\n"
                message += f"• Ценность из бизнес-диалогов: {valuable_rate:.1f}%\n"
            
            await update.message.reply_text(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики диалогов: {e}")
            await update.message.reply_text("❌ Ошибка получения статистики диалогов")

    async def active_dialogues_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда для просмотра активных диалогов"""
        if not await self._admin_required(update):
            return
        
        try:
            active_dialogues = await get_active_dialogues()
            
            if not active_dialogues:
                await update.message.reply_text("📭 Активных диалогов нет")
                return
            
            message = f"💬 <b>Активные диалоги ({len(active_dialogues)})</b>\n\n"
            
            for i, dialogue in enumerate(active_dialogues[:10], 1):
                dialogue_id = dialogue[0]
                channel_title = dialogue[1] or "Без названия"
                participants = dialogue[2]
                messages = dialogue[3]
                start_time = datetime.fromisoformat(dialogue[4]) if dialogue[4] else None
                last_activity = datetime.fromisoformat(dialogue[5]) if dialogue[5] else None
                is_business = dialogue[6]
                
                if start_time:
                    duration = (datetime.now() - start_time).total_seconds() / 60
                    duration_text = f"{duration:.0f} мин"
                else:
                    duration_text = "неизвестно"
                
                business_emoji = "🏢" if is_business else "💬"
                
                message += f"{i}. {business_emoji} <b>{dialogue_id[:20]}...</b>\n"
                message += f"   📺 {channel_title}\n"
                message += f"   👥 {participants} участ. • 💬 {messages} сообщ.\n"
                message += f"   ⏱️ {duration_text}\n\n"
            
            if len(active_dialogues) > 10:
                message += f"... и еще {len(active_dialogues) - 10} диалогов\n"
            
            message += "\n💡 Используйте /export_dialogue <id> для экспорта"
            
            await update.message.reply_text(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Ошибка получения активных диалогов: {e}")
            await update.message.reply_text("❌ Ошибка получения активных диалогов")

    async def export_dialogue_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда для экспорта данных диалога"""
        if not await self._admin_required(update):
            return
        
        if not context.args:
            await update.message.reply_text(
                "📤 <b>Экспорт диалога</b>\n\n"
                "Использование: <code>/export_dialogue dialogue_id</code>\n\n"
                "Пример: <code>/export_dialogue dialogue_123456_20241120_143052</code>",
                parse_mode='HTML'
            )
            return
        
        dialogue_id = context.args[0]
        
        try:
            dialogue_data = await export_dialogue_data(dialogue_id)
            
            if not dialogue_data:
                await update.message.reply_text(f"❌ Диалог {dialogue_id} не найден")
                return
            
            # Формируем текстовый отчет
            dialogue = dialogue_data['dialogue']
            participants = dialogue_data['participants']
            messages = dialogue_data['messages']
            analyses = dialogue_data['analyses']
            
            report = f"📊 <b>Экспорт диалога</b>\n\n"
            report += f"🆔 <b>ID:</b> <code>{dialogue_id}</code>\n"
            report += f"📺 <b>Канал:</b> {dialogue[2] or 'Без названия'}\n"
            report += f"👥 <b>Участников:</b> {len(participants)}\n"
            report += f"💬 <b>Сообщений:</b> {len(messages)}\n"
            report += f"📊 <b>Анализов:</b> {len(analyses)}\n"
            
            if dialogue[4]:  # start_time
                start_time = datetime.fromisoformat(dialogue[4])
                report += f"⏰ <b>Начало:</b> {start_time.strftime('%d.%m.%Y %H:%M')}\n"
            
            if dialogue[6]:  # last_activity
                last_activity = datetime.fromisoformat(dialogue[6])
                report += f"🕐 <b>Последняя активность:</b> {last_activity.strftime('%d.%m.%Y %H:%M')}\n"
            
            if dialogue[9]:  # is_business_related
                report += f"🏢 <b>Бизнес-тема:</b> ✅\n"
            
            # Участники
            if participants:
                report += f"\n👥 <b>Участники:</b>\n"
                for participant in participants[:5]:
                    name = participant[3] or "Аноним"
                    username = f"@{participant[2]}" if participant[2] else "без username"
                    role = participant[5] or "участник"
                    messages_count = participant[6] or 0
                    lead_prob = participant[13] or 0
                    
                    report += f"• {name} ({username}) - {role}\n"
                    report += f"  💬 {messages_count} сообщ. • 🎯 {lead_prob:.0f}% вероятность лида\n"
            
            # Последние анализы
            if analyses:
                latest_analysis = analyses[0]
                report += f"\n🔍 <b>Последний анализ:</b>\n"
                report += f"• Ценный диалог: {'✅' if latest_analysis[2] else '❌'}\n"
                report += f"• Уверенность: {latest_analysis[3] or 0}%\n"
                report += f"• Бизнес-релевантность: {latest_analysis[4] or 0}%\n"
                report += f"• Потенциальных лидов: {latest_analysis[5] or 0}\n"
                
                if latest_analysis[7]:  # dialogue_summary
                    summary = latest_analysis[7][:200] + "..." if len(latest_analysis[7]) > 200 else latest_analysis[7]
                    report += f"• Суть: <i>{summary}</i>\n"
            
            await update.message.reply_text(report, parse_mode='HTML')
            
            # Предлагаем дополнительные действия
            keyboard = [
                [
                    InlineKeyboardButton("📋 Полные данные JSON", callback_data=f"export_json_{dialogue_id}"),
                    InlineKeyboardButton("👥 Детали участников", callback_data=f"export_participants_{dialogue_id}")
                ]
            ]
            
            await update.message.reply_text(
                "💡 Дополнительные действия:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logger.error(f"Ошибка экспорта диалога: {e}")
            await update.message.reply_text(f"❌ Ошибка экспорта диалога: {e}")

    async def cleanup_dialogues_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда для очистки старых диалогов"""
        if not await self._admin_required(update):
            return
        
        try:
            days = 30
            if context.args:
                try:
                    days = int(context.args[0])
                except ValueError:
                    await update.message.reply_text("❌ Неверный формат дней. Используйте число.")
                    return
            
            await cleanup_old_dialogues(days)
            await update.message.reply_text(
                f"✅ Очистка завершена\n\n"
                f"Удалены диалоги старше {days} дней"
            )
            
        except Exception as e:
            logger.error(f"Ошибка очистки диалогов: {e}")
            await update.message.reply_text(f"❌ Ошибка очистки: {e}")

    async def ai_health_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверка здоровья AI системы"""
        if not await self._admin_required(update):
            return
        
        try:
            from ai.claude_client import get_claude_client
            
            message = "🤖 <b>Проверка здоровья AI системы</b>\n\n"
            
            # Проверяем Claude клиента
            claude_client = get_claude_client()
            if claude_client:
                claude_health = await claude_client.health_check()
                claude_stats = claude_client.get_usage_stats()
                
                message += f"🧠 <b>Claude API:</b>\n"
                message += f"• Статус: {'✅ Работает' if claude_health else '❌ Недоступен'}\n"
                message += f"• Модель: {claude_stats['model']}\n"
                message += f"• Режим: {claude_stats['status']}\n"
                message += f"• Макс. токенов: {claude_stats['max_tokens']}\n\n"
            else:
                message += f"🧠 <b>Claude API:</b> ❌ Не инициализирован\n\n"
            
            # Проверяем AI парсер
            ai_parser = context.bot_data.get('ai_parser')
            if ai_parser:
                parser_status = ai_parser.get_status()
                message += f"🔍 <b>AI Парсер:</b>\n"
                message += f"• Статус: {'✅ Активен' if parser_status['enabled'] else '❌ Отключен'}\n"
                message += f"• Каналов: {parser_status['channels_count']}\n"
                
                if parser_status.get('dialogue_analysis_enabled'):
                    dialogue_status = parser_status.get('dialogue_tracker', {})
                    message += f"• Анализ диалогов: ✅\n"
                    message += f"• Активных диалогов: {dialogue_status.get('active_dialogues', 0)}\n"
                else:
                    message += f"• Анализ диалогов: ❌\n"
                
                message += f"• Мин. скор: {parser_status['min_confidence_score']}%\n"
                message += f"• Активных пользователей: {parser_status['individual_active_users']}\n"
            else:
                message += f"🔍 <b>AI Парсер:</b> ❌ Недоступен\n"
            
            # Проверяем базу данных
            try:
                stats = await get_bot_stats()
                message += f"\n💾 <b>База данных:</b> ✅ Работает\n"
                message += f"• Пользователей: {stats.get('total_users', 0)}\n"
                message += f"• Лидов: {stats.get('total_leads', 0)}\n"
                message += f"• Сообщений: {stats.get('total_messages', 0)}\n"
            except Exception as e:
                message += f"\n💾 <b>База данных:</b> ❌ Ошибка: {e}\n"
            
            await update.message.reply_text(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Ошибка проверки здоровья AI: {e}")
            await update.message.reply_text(f"❌ Ошибка проверки: {e}")

    async def handle_admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка callback запросов админки"""
        query = update.callback_query
        
        if not self._is_admin(query.from_user.id):
            await query.answer("❌ У вас нет прав администратора")
            return
        
        data = query.data
        logger.info(f"🔧 Enhanced Admin callback от {query.from_user.id}: {data}")
        
        try:
            await query.answer()
            
            if data == "admin_dialogues":
                await self._show_dialogues_callback(query)
            elif data == "admin_ai_status":
                await self._show_ai_status_callback(query)
            elif data == "admin_reports":
                await self._show_reports_callback(query)
            elif data == "admin_utilities":
                await self._show_utilities_callback(query)
            elif data.startswith("export_json_"):
                dialogue_id = data.replace("export_json_", "")
                await self._export_dialogue_json(query, dialogue_id)
            elif data.startswith("export_participants_"):
                dialogue_id = data.replace("export_participants_", "")
                await self._export_participants_details(query, dialogue_id)
            # Остальные callback из базового AdminHandler
            elif data == "admin_panel":
                await self._show_admin_panel(query)
            elif data == "admin_users":
                await self._show_users_callback(query)
            elif data == "admin_leads":
                await self._show_leads_callback(query)
            elif data == "admin_channels":
                await self._show_channels_callback(query)
            elif data == "admin_stats":
                await self._show_stats_callback(query)
            elif data == "admin_broadcast":
                await self._show_broadcast_info(query)
            elif data == "admin_settings":
                await self._show_settings_callback(query)
            else:
                logger.warning(f"Неизвестная админская команда: {data}")
                await query.edit_message_text("❌ Неизвестная команда")
                
        except Exception as e:
            logger.error(f"❌ Ошибка обработки enhanced admin callback '{data}': {e}")
            import traceback
            traceback.print_exc()
            try:
                await query.edit_message_text("❌ Произошла ошибка. Попробуйте еще раз.")
            except:
                pass

    async def _show_dialogues_callback(self, query):
        """Показать диалоги через callback"""
        try:
            active_dialogues = await get_active_dialogues()
            stats_7d = await get_dialogue_stats(7)
            
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            message = f"💬 <b>Диалоги</b> (обновлено {timestamp})\n\n"
            
            message += f"📊 <b>Статистика за 7 дней:</b>\n"
            message += f"• Всего диалогов: {stats_7d.get('total_dialogues', 0)}\n"
            message += f"• Бизнес-диалогов: {stats_7d.get('business_dialogues', 0)}\n"
            message += f"• Ценных диалогов: {stats_7d.get('valuable_dialogues', 0)}\n"
            message += f"• Лидов из диалогов: {stats_7d.get('total_leads_from_dialogues', 0)}\n\n"
            
            if active_dialogues:
                message += f"🔥 <b>Активные диалоги ({len(active_dialogues)}):</b>\n"
                for dialogue in active_dialogues[:3]:
                    channel_title = dialogue[1] or "Без названия"
                    participants = dialogue[2]
                    messages = dialogue[3]
                    is_business = "🏢" if dialogue[6] else "💬"
                    
                    message += f"{is_business} {channel_title} - {participants}👥 {messages}💬\n"
                
                if len(active_dialogues) > 3:
                    message += f"... и еще {len(active_dialogues) - 3}\n"
            else:
                message += "📭 Активных диалогов нет\n"
            
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Обновить", callback_data="admin_dialogues"),
                    InlineKeyboardButton("📊 Подробная статистика", callback_data="admin_dialogue_stats")
                ],
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Ошибка показа диалогов: {e}")
            await query.edit_message_text("❌ Ошибка получения данных о диалогах")

    async def _show_ai_status_callback(self, query):
        """Показать статус AI через callback"""
        try:
            from ai.claude_client import get_claude_client
            
            timestamp = datetime.now().strftime("%H:%M:%S")
            message = f"🤖 <b>AI Статус</b> (обновлено {timestamp})\n\n"
            
            # Claude API
            claude_client = get_claude_client()
            if claude_client:
                claude_stats = claude_client.get_usage_stats()
                health = await claude_client.health_check()
                
                status_emoji = "✅" if health else "❌"
                message += f"{status_emoji} <b>Claude API</b>\n"
                message += f"• Модель: {claude_stats['model']}\n"
                message += f"• Режим: {claude_stats['status']}\n"
                
                if not health:
                    message += f"• ⚠️ API недоступен\n"
            else:
                message += f"❌ <b>Claude API</b> - не инициализирован\n"
            
            message += f"\n🔍 <b>Парсинг:</b>\n"
            message += f"• Включен: {'✅' if self.config.get('parsing', {}).get('enabled') else '❌'}\n"
            message += f"• Каналов: {len(self.config.get('parsing', {}).get('channels', []))}\n"
            message += f"• Анализ диалогов: {'✅' if self.config.get('parsing', {}).get('dialogue_analysis_enabled') else '❌'}\n"
            
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Обновить", callback_data="admin_ai_status"),
                    InlineKeyboardButton("🏥 Проверка здоровья", callback_data="admin_health_check")
                ],
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Ошибка показа AI статуса: {e}")
            await query.edit_message_text("❌ Ошибка получения AI статуса")

    async def _show_reports_callback(self, query):
        """Показать отчеты через callback"""
        message = f"📈 <b>Отчеты и аналитика</b>\n\n"
        message += f"Доступные отчеты:\n\n"
        message += f"📊 Статистика диалогов за период\n"
        message += f"👥 Анализ участников диалогов\n"
        message += f"🎯 Эффективность поиска лидов\n"
        message += f"📈 Тренды и динамика\n\n"
        message += f"💡 Используйте команды:\n"
        message += f"• <code>/dialogue_stats</code> - статистика диалогов\n"
        message += f"• <code>/stats</code> - общая статистика\n"
        message += f"• <code>/export_dialogue &lt;id&gt;</code> - экспорт диалога"
        
        keyboard = [
            [
                InlineKeyboardButton("📊 Статистика диалогов", callback_data="admin_dialogue_stats"),
                InlineKeyboardButton("📈 Общая статистика", callback_data="admin_stats")
            ],
            [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    async def _show_utilities_callback(self, query):
        """Показать утилиты через callback"""
        message = f"🔧 <b>Утилиты и обслуживание</b>\n\n"
        message += f"Доступные инструменты:\n\n"
        message += f"🧹 Очистка старых диалогов\n"
        message += f"🏥 Проверка здоровья системы\n"
        message += f"📤 Экспорт данных\n"
        message += f"🔄 Обновление кэша\n\n"
        message += f"💡 Используйте команды:\n"
        message += f"• <code>/cleanup_dialogues [дни]</code> - очистка\n"
        message += f"• <code>/health</code> - проверка системы\n"
        message += f"• <code>/status</code> - статус парсера"
        
        keyboard = [
            [
                InlineKeyboardButton("🏥 Проверка здоровья", callback_data="admin_health_check"),
                InlineKeyboardButton("🧹 Очистка (30д)", callback_data="admin_cleanup_30")
            ],
            [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    async def _export_dialogue_json(self, query, dialogue_id: str):
        """Экспорт диалога в JSON формате"""
        try:
            dialogue_data = await export_dialogue_data(dialogue_id)
            
            if not dialogue_data:
                await query.edit_message_text(f"❌ Диалог {dialogue_id} не найден")
                return
            
            # Преобразуем данные в JSON
            json_data = json.dumps(dialogue_data, indent=2, ensure_ascii=False, default=str)
            
            # Ограничиваем размер для Telegram
            if len(json_data) > 4000:
                json_preview = json_data[:3900] + "\n... (обрезано)"
                
                await query.edit_message_text(
                    f"📋 <b>JSON данные диалога</b>\n\n"
                    f"<pre>{json_preview}</pre>\n\n"
                    f"⚠️ Данные обрезаны из-за ограничений Telegram",
                    parse_mode='HTML'
                )
            else:
                await query.edit_message_text(
                    f"📋 <b>JSON данные диалога</b>\n\n"
                    f"<pre>{json_data}</pre>",
                    parse_mode='HTML'
                )
            
        except Exception as e:
            logger.error(f"Ошибка экспорта JSON: {e}")
            await query.edit_message_text(f"❌ Ошибка экспорта: {e}")

    async def _export_participants_details(self, query, dialogue_id: str):
        """Детальная информация об участниках диалога"""
        try:
            dialogue_data = await export_dialogue_data(dialogue_id)
            
            if not dialogue_data:
                await query.edit_message_text(f"❌ Диалог {dialogue_id} не найден")
                return
            
            participants = dialogue_data['participants']
            
            message = f"👥 <b>Участники диалога</b>\n\n"
            
            for participant in participants:
                name = participant[3] or "Аноним"
                username = f"@{participant[2]}" if participant[2] else "без username"
                role = participant[5] or "participant"
                message_count = participant[6] or 0
                engagement = participant[8] or "low"
                buying_signals = participant[9] or 0
                influence_score = participant[10] or 0
                lead_probability = participant[11] or 0
                role_in_decision = participant[12] or "observer"
                
                message += f"🔹 <b>{name}</b> ({username})\n"
                message += f"   👤 Роль: {role}\n"
                message += f"   🎭 В решении: {role_in_decision}\n"
                message += f"   💬 Сообщений: {message_count}\n"
                message += f"   📊 Вовлеченность: {engagement}\n"
                message += f"   💰 Покуп. сигналы: {buying_signals}\n"
                message += f"   💪 Влияние: {influence_score}/100\n"
                message += f"   🎯 Вероятность лида: {lead_probability:.0f}%\n\n"
            
            await query.edit_message_text(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Ошибка экспорта участников: {e}")
            await query.edit_message_text(f"❌ Ошибка: {e}")

    # Базовые методы из оригинального AdminHandler
    async def _show_admin_panel(self, query):
        """Показать админ панель"""
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
                InlineKeyboardButton("📺 Каналы", callback_data="admin_channels"),
                InlineKeyboardButton("🤖 AI Статус", callback_data="admin_ai_status")
            ],
            [
                InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
                InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings")
            ],
            [
                InlineKeyboardButton("📈 Отчеты", callback_data="admin_reports"),
                InlineKeyboardButton("🔧 Утилиты", callback_data="admin_utilities")
            ]
        ]
        
        await query.edit_message_text(
            "🔧 <b>Расширенная админ панель</b>\n\n🆕 Теперь с поддержкой анализа диалогов!\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    async def _show_users_callback(self, query):
        """Показать пользователей через callback (базовая версия)"""
        # Реализация из оригинального AdminHandler
        pass

    async def _show_leads_callback(self, query):
        """Показать лиды через callback (базовая версия)"""
        # Реализация из оригинального AdminHandler
        pass

    async def _show_channels_callback(self, query):
        """Показать каналы через callback (базовая версия)"""
        # Реализация из оригинального AdminHandler
        pass

    async def _show_stats_callback(self, query):
        """Показать статистику через callback (базовая версия)"""
        # Реализация из оригинального AdminHandler
        pass

    async def _show_broadcast_info(self, query):
        """Показать информацию о рассылке (базовая версия)"""
        # Реализация из оригинального AdminHandler
        pass

    async def _show_settings_callback(self, query):
        """Показать настройки через callback (базовая версия)"""
        # Реализация из оригинального AdminHandler
        pass
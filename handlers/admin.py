"""
Обработчики админских команд
"""

import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from database.operations import (
    get_all_users, get_users_by_interest_score, get_leads_by_score,
    get_recent_leads, get_active_channels, create_or_update_channel,
    get_stats, create_broadcast, update_broadcast_stats, get_setting, set_setting
)
from database.models import ParsedChannel, Broadcast

logger = logging.getLogger(__name__)

class AdminHandler:
    """Обработчик админских команд"""
    
    def __init__(self, config):
        self.config = config
        self.admin_ids = config.get('bot', {}).get('admin_ids', [])
        
        # Callback handler
        self.callback_handler = CallbackQueryHandler(self.handle_admin_callback)

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
        """Главная админ панель"""
        if not await self._admin_required(update):
            return
        
        keyboard = [
            [
                InlineKeyboardButton("👥 Пользователи", callback_data="admin_users"),
                InlineKeyboardButton("🎯 Лиды", callback_data="admin_leads")
            ],
            [
                InlineKeyboardButton("📺 Каналы", callback_data="admin_channels"),
                InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
            ],
            [
                InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
                InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings")
            ]
        ]
        
        await update.message.reply_text(
            "🔧 <b>Админ панель</b>\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    async def show_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать список пользователей"""
        if not await self._admin_required(update):
            return
        
        try:
            # Получаем пользователей с высоким скором
            interested_users = await get_users_by_interest_score(min_score=70)
            all_users = await get_all_users(limit=20)
            
            message = "👥 <b>Пользователи бота</b>\n\n"
            
            if interested_users:
                message += "🔥 <b>Заинтересованные пользователи (score ≥ 70):</b>\n"
                for user in interested_users[:10]:
                    username = f"@{user.username}" if user.username else "без username"
                    message += f"• {user.first_name} ({username}) - {user.interest_score}/100\n"
                message += "\n"
            
            message += f"📋 <b>Последние пользователи ({len(all_users)} из всех):</b>\n"
            for user in all_users[:10]:
                username = f"@{user.username}" if user.username else "без username"
                activity = user.last_activity.strftime("%d.%m %H:%M") if user.last_activity else "никогда"
                message += f"• {user.first_name} ({username}) - {user.interest_score}/100, активен: {activity}\n"
            
            keyboard = [
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Ошибка получения пользователей: {e}")
            await update.message.reply_text("❌ Ошибка получения данных")

    async def show_leads(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать лиды"""
        if not await self._admin_required(update):
            return
        
        try:
            recent_leads = await get_recent_leads(hours=24)
            all_leads = await get_leads_by_score(min_score=60, limit=20)
            
            message = "🎯 <b>Потенциальные клиенты</b>\n\n"
            
            if recent_leads:
                message += f"🔥 <b>Новые лиды за 24 часа ({len(recent_leads)}):</b>\n"
                for lead in recent_leads[:5]:
                    username = f"@{lead.username}" if lead.username else "без username"
                    source = lead.source_channel.replace('@', '')
                    message += f"• {lead.first_name or 'Аноним'} ({username})\n"
                    message += f"  Скор: {lead.interest_score}/100, из: {source}\n"
                    message += f"  Сообщение: {lead.message_text[:100]}...\n\n"
            
            if all_leads:
                message += f"📋 <b>Все лиды (score ≥ 60, показано {min(len(all_leads), 10)}):</b>\n"
                for lead in all_leads[:10]:
                    username = f"@{lead.username}" if lead.username else "без username"
                    created = lead.created_at.strftime("%d.%m %H:%M") if lead.created_at else "неизвестно"
                    message += f"• {lead.first_name or 'Аноним'} ({username}) - {lead.interest_score}/100, {created}\n"
            
            if not recent_leads and not all_leads:
                message += "Лидов пока нет. Настройте парсинг каналов."
            
            keyboard = [
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Ошибка получения лидов: {e}")
            await update.message.reply_text("❌ Ошибка получения данных")

    async def manage_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Управление каналами для парсинга"""
        if not await self._admin_required(update):
            return
        
        try:
            channels = await get_active_channels()
            
            message = "📺 <b>Каналы для парсинга</b>\n\n"
            
            if channels:
                for channel in channels:
                    status = "✅" if channel.enabled else "❌"
                    last_parsed = "никогда"
                    if channel.last_parsed:
                        last_parsed = channel.last_parsed.strftime("%d.%m %H:%M")
                    
                    message += f"{status} <code>{channel.channel_username}</code>\n"
                    message += f"   Спарсено: {channel.total_messages_parsed} сообщений\n"
                    message += f"   Лидов найдено: {channel.leads_found}\n"
                    message += f"   Последний парсинг: {last_parsed}\n\n"
            else:
                message += "Каналы не настроены.\n"
            
            message += "<b>Настройка:</b>\n"
            message += "Добавьте каналы в config.yaml в секции parsing.channels\n"
            message += "Пример: ['@channel1', '@channel2']\n\n"
            message += "После изменения конфигурации перезапустите бота."
            
            keyboard = [
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Ошибка получения каналов: {e}")
            await update.message.reply_text("❌ Ошибка получения данных")

    async def broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Рассылка сообщения всем пользователям"""
        if not await self._admin_required(update):
            return
        
        # Получаем текст для рассылки из аргументов команды
        if context.args:
            broadcast_text = " ".join(context.args)
        else:
            await update.message.reply_text(
                "📢 <b>Рассылка</b>\n\n"
                "Используйте: <code>/broadcast Текст сообщения</code>\n\n"
                "Пример: <code>/broadcast Новая акция! Скидка 20%</code>",
                parse_mode='HTML'
            )
            return
        
        try:
            # Получаем всех пользователей
            users = await get_all_users(limit=1000)
            
            if not users:
                await update.message.reply_text("❌ Нет пользователей для рассылки")
                return
            
            # Создаем запись о рассылке
            broadcast = Broadcast(
                admin_id=update.effective_user.id,
                message_text=broadcast_text,
                total_users=len(users),
                status="sending"
            )
            broadcast = await create_broadcast(broadcast)
            
            # Отправляем уведомление о начале рассылки
            await update.message.reply_text(
                f"📢 Начинаю рассылку для {len(users)} пользователей...\n"
                f"Текст: <i>{broadcast_text[:100]}...</i>",
                parse_mode='HTML'
            )
            
            # Отправляем сообщения
            sent_count = 0
            failed_count = 0
            
            for user in users:
                try:
                    await context.bot.send_message(
                        chat_id=user.telegram_id,
                        text=broadcast_text,
                        parse_mode='HTML'
                    )
                    sent_count += 1
                    
                    # Пауза чтобы не нарушить лимиты Telegram
                    if sent_count % 20 == 0:
                        await asyncio.sleep(1)
                        
                except Exception as e:
                    failed_count += 1
                    logger.warning(f"Не удалось отправить сообщение пользователю {user.telegram_id}: {e}")
            
            # Обновляем статистику рассылки
            await update_broadcast_stats(
                broadcast.id, sent_count, failed_count, "completed"
            )
            
            # Отправляем отчет
            await update.message.reply_text(
                f"✅ <b>Рассылка завершена</b>\n\n"
                f"📤 Отправлено: {sent_count}\n"
                f"❌ Ошибок: {failed_count}\n"
                f"📊 Успешность: {sent_count/(sent_count+failed_count)*100:.1f}%",
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Ошибка рассылки: {e}")
            await update.message.reply_text("❌ Ошибка при рассылке")

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать статистику"""
        if not await self._admin_required(update):
            return
        
        try:
            stats = await get_stats()
            
            message = "📊 <b>Статистика бота</b>\n\n"
            
            message += "👥 <b>Пользователи:</b>\n"
            message += f"• Всего: {stats.get('total_users', 0)}\n"
            message += f"• Заинтересованные (score ≥ 70): {stats.get('interested_users', 0)}\n"
            message += f"• Активные за 24ч: {stats.get('active_users_24h', 0)}\n\n"
            
            message += "💬 <b>Сообщения:</b>\n"
            message += f"• Всего: {stats.get('total_messages', 0)}\n"
            message += f"• За 24 часа: {stats.get('messages_24h', 0)}\n\n"
            
            message += "🎯 <b>Лиды:</b>\n"
            message += f"• Всего: {stats.get('total_leads', 0)}\n"
            message += f"• За 24 часа: {stats.get('leads_24h', 0)}\n"
            message += f"• Горячие (score ≥ 80): {stats.get('hot_leads', 0)}\n\n"
            
            message += "📺 <b>Парсинг:</b>\n"
            message += f"• Активных каналов: {stats.get('active_channels', 0)}\n"
            
            # Конверсия
            if stats.get('total_users', 0) > 0:
                conversion = stats.get('interested_users', 0) / stats.get('total_users', 1) * 100
                message += f"\n📈 <b>Конверсия в заинтересованных:</b> {conversion:.1f}%"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")],
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            await update.message.reply_text("❌ Ошибка получения статистики")

    async def settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Настройки бота"""
        if not await self._admin_required(update):
            return
        
        message = "⚙️ <b>Настройки бота</b>\n\n"
        message += "Основные настройки находятся в файле <code>config.yaml</code>\n\n"
        message += "<b>Для изменения настроек:</b>\n"
        message += "1. Отредактируйте config.yaml\n"
        message += "2. Перезапустите бота\n\n"
        message += "<b>Основные секции:</b>\n"
        message += "• <code>bot</code> - настройки бота\n"
        message += "• <code>claude</code> - настройки AI\n"
        message += "• <code>parsing</code> - настройки парсинга\n"
        message += "• <code>messages</code> - тексты сообщений\n"
        message += "• <code>prompts</code> - промпты для Claude\n"
        
        keyboard = [
            [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
        ]
        
        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    async def handle_admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка callback запросов админки"""
        query = update.callback_query
        await query.answer()
        
        if not self._is_admin(query.from_user.id):
            await query.edit_message_text("❌ У вас нет прав администратора")
            return
        
        data = query.data
        
        try:
            if data == "admin_panel":
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
                await query.edit_message_text("Неизвестная команда")
                
        except Exception as e:
            logger.error(f"Ошибка обработки admin callback: {e}")

    async def _show_admin_panel(self, query):
        """Показать админ панель"""
        keyboard = [
            [
                InlineKeyboardButton("👥 Пользователи", callback_data="admin_users"),
                InlineKeyboardButton("🎯 Лиды", callback_data="admin_leads")
            ],
            [
                InlineKeyboardButton("📺 Каналы", callback_data="admin_channels"),
                InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
            ],
            [
                InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
                InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings")
            ]
        ]
        
        await query.edit_message_text(
            "🔧 <b>Админ панель</b>\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    async def _show_users_callback(self, query):
        """Показать пользователей через callback"""
        try:
            interested_users = await get_users_by_interest_score(min_score=70)
            all_users = await get_all_users(limit=10)
            
            message = "👥 <b>Пользователи бота</b>\n\n"
            
            if interested_users:
                message += f"🔥 <b>Заинтересованные ({len(interested_users)}):</b>\n"
                for user in interested_users[:5]:
                    username = f"@{user.username}" if user.username else "без username"
                    message += f"• {user.first_name} ({username}) - {user.interest_score}/100\n"
                message += "\n"
            
            message += f"📋 <b>Последние пользователи:</b>\n"
            for user in all_users[:5]:
                username = f"@{user.username}" if user.username else "без username"
                message += f"• {user.first_name} ({username}) - {user.interest_score}/100\n"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin_users")],
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Ошибка показа пользователей: {e}")
            await query.edit_message_text("❌ Ошибка получения данных")

    async def _show_leads_callback(self, query):
        """Показать лиды через callback"""
        try:
            recent_leads = await get_recent_leads(hours=24)
            
            message = "🎯 <b>Потенциальные клиенты</b>\n\n"
            
            if recent_leads:
                message += f"🔥 <b>За 24 часа найдено: {len(recent_leads)}</b>\n\n"
                for lead in recent_leads[:3]:
                    username = f"@{lead.username}" if lead.username else "без username"
                    message += f"• {lead.first_name or 'Аноним'} ({username})\n"
                    message += f"  Скор: {lead.interest_score}/100\n"
                    message += f"  Из: {lead.source_channel.replace('@', '')}\n\n"
            else:
                message += "За последние 24 часа новых лидов нет.\n\n"
                message += "💡 Проверьте настройки парсинга каналов."
            
            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin_leads")],
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Ошибка показа лидов: {e}")
            await query.edit_message_text("❌ Ошибка получения данных")

    async def _show_channels_callback(self, query):
        """Показать каналы через callback"""
        await self._show_admin_panel(query)  # Пока просто возвращаемся в админку

    async def _show_stats_callback(self, query):
        """Показать статистику через callback"""
        try:
            stats = await get_stats()
            
            message = "📊 <b>Статистика</b>\n\n"
            message += f"👥 Пользователей: {stats.get('total_users', 0)}\n"
            message += f"🔥 Заинтересованных: {stats.get('interested_users', 0)}\n"
            message += f"💬 Сообщений за 24ч: {stats.get('messages_24h', 0)}\n"
            message += f"🎯 Лидов за 24ч: {stats.get('leads_24h', 0)}\n"
            message += f"📺 Активных каналов: {stats.get('active_channels', 0)}\n"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")],
                [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Ошибка показа статистики: {e}")
            await query.edit_message_text("❌ Ошибка получения статистики")

    async def _show_broadcast_info(self, query):
        """Показать информацию о рассылке"""
        message = "📢 <b>Рассылка сообщений</b>\n\n"
        message += "Для отправки рассылки используйте команду:\n"
        message += "<code>/broadcast Текст сообщения</code>\n\n"
        message += "<b>Примеры:</b>\n"
        message += "• <code>/broadcast Новая акция!</code>\n"
        message += "• <code>/broadcast Скидка 20% до конца недели</code>\n\n"
        message += "⚠️ Рассылка отправляется всем пользователям бота."
        
        keyboard = [
            [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    async def _show_settings_callback(self, query):
        """Показать настройки через callback"""
        message = "⚙️ <b>Настройки</b>\n\n"
        message += "Настройки в файле <code>config.yaml</code>\n\n"
        message += "Основные параметры:\n"
        message += "• Тексты сообщений\n"
        message += "• Промпты для AI\n"
        message += "• Каналы для парсинга\n"
        message += "• Права администратора\n\n"
        message += "После изменений перезапустите бота."
        
        keyboard = [
            [InlineKeyboardButton("🔙 Админ панель", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

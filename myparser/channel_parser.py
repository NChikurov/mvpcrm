"""
Парсер Telegram каналов для поиска потенциальных клиентов
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from telegram import Update
from telegram.ext import ContextTypes

from database.operations import (
    create_or_update_channel, get_active_channels, create_lead,
    update_channel_stats
)
from database.models import ParsedChannel, Lead
from ai.claude_client import get_claude_client

logger = logging.getLogger(__name__)

class ChannelParser:
    """Парсер каналов для поиска лидов"""
    
    def __init__(self, config):
        self.config = config
        self.parsing_config = config.get('parsing', {})
        
        # Настройки парсинга
        self.enabled = self.parsing_config.get('enabled', True)
        
        # Безопасное получение каналов
        channels_raw = self.parsing_config.get('channels', [])
        if isinstance(channels_raw, list):
            self.channels = [str(ch) for ch in channels_raw]
        elif isinstance(channels_raw, (str, int)):
            self.channels = [str(channels_raw)]
        else:
            self.channels = []
            logger.warning(f"Некорректный формат каналов в конфигурации: {channels_raw}")
        
        self.min_interest_score = self.parsing_config.get('min_interest_score', 60)
        
        # Дедупликация сообщений (чтобы не обрабатывать одно сообщение дважды)
        self.processed_messages = set()
        
        logger.info(f"Парсер инициализирован: {len(self.channels)} каналов")

    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка сообщения из отслеживаемого канала/группы"""
        try:
            if not self.enabled:
                return
            
            chat_id = update.effective_chat.id
            message_id = update.message.message_id
            user = update.effective_user
            message_text = update.message.text
            
            # Проверяем дедупликацию
            message_key = f"{chat_id}:{message_id}"
            if message_key in self.processed_messages:
                return
            
            self.processed_messages.add(message_key)
            
            # Ограничиваем размер кэша
            if len(self.processed_messages) > 10000:
                # Удаляем половину старых записей
                old_messages = list(self.processed_messages)[:5000]
                for msg in old_messages:
                    self.processed_messages.discard(msg)
            
            logger.info(f"Обрабатываем сообщение из канала {chat_id}: {message_text[:50]}...")
            
            # Получаем информацию о канале
            chat = update.effective_chat
            channel_identifier = str(chat_id)
            
            # Пытаемся найти username канала
            if chat.username:
                channel_identifier = f"@{chat.username}"
            
            # Анализируем сообщение
            interest_score = await self._analyze_message(message_text, channel_identifier)
            
            logger.info(f"Скор заинтересованности: {interest_score}")
            
            # Если скор высокий - сохраняем как лид
            if interest_score >= self.min_interest_score:
                # Проверяем, что такой лид еще не существует
                if not await self._lead_exists(user.id, message_text):
                    lead = Lead(
                        telegram_id=user.id,
                        username=user.username,
                        first_name=user.first_name,
                        source_channel=channel_identifier,
                        interest_score=interest_score,
                        message_text=message_text,
                        message_date=update.message.date
                    )
                    
                    await create_lead(lead)
                    
                    logger.info(f"🎯 НАЙДЕН ЛИД: {user.first_name} (@{user.username}) - score: {interest_score}")
                    logger.info(f"Текст: {message_text[:100]}...")
                    
                    # Уведомляем админов о новом лиде
                    await self._notify_admins_about_lead(context, lead)
                else:
                    logger.debug(f"Лид уже существует для пользователя {user.id}")
            
            # Обновляем статистику канала
            await self._update_channel_stats(channel_identifier, message_id, interest_score >= self.min_interest_score)
            
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения из канала: {e}")
            import traceback
            traceback.print_exc()

    async def _analyze_message(self, message_text: str, channel_identifier: str) -> int:
        """Анализ сообщения на предмет потенциального лида"""
        try:
            claude_client = get_claude_client()
            if claude_client:
                # Используем Claude для анализа
                score = await claude_client.analyze_potential_lead(message_text, channel_identifier)
                return score
            else:
                # Простой анализ без AI
                return self._simple_lead_analysis(message_text)
        
        except Exception as e:
            logger.error(f"Ошибка анализа сообщения: {e}")
            return self._simple_lead_analysis(message_text)

    def _simple_lead_analysis(self, message_text: str) -> int:
        """Простой анализ потенциального лида без AI"""
        if not message_text:
            return 0
        
        message_lower = message_text.lower()
        score = 0
        
        # Высокоприоритетные слова (бизнес-проблемы)
        high_priority_words = [
            'crm', 'автоматизация', 'продажи', 'клиенты', 'заявки', 
            'обработка заявок', 'бот для продаж', 'telegram bot',
            'интернет-магазин', 'онлайн-продажи', 'воронка продаж',
            'лидогенерация', 'конверсия', 'аналитика продаж'
        ]
        
        # Проблемы, которые мы решаем
        problem_words = [
            'не успеваем обрабатывать', 'много заявок', 'теряем клиентов',
            'нужна система', 'ищу решение', 'как автоматизировать',
            'эффективность продаж', 'увеличить конверсию',
            'автоматический ответ', 'обработка сообщений'
        ]
        
        # Намерения покупки
        buying_intent_words = [
            'ищу', 'нужно', 'требуется', 'хочу заказать', 'планирую купить',
            'рассматриваю покупку', 'интересует стоимость', 'бюджет есть',
            'готов платить', 'нужна консультация'
        ]
        
        # Технические запросы
        tech_words = [
            'api интеграция', 'webhook', 'chatbot', 'бот разработка',
            'автоответчик', 'воронка', 'аналитика', 'метрики',
            'integration', 'automation'
        ]
        
        # Подсчет баллов
        for word in high_priority_words:
            if word in message_lower:
                score += 40
                break  # Один раз за категорию
        
        for word in problem_words:
            if word in message_lower:
                score += 35
                break
        
        for word in buying_intent_words:
            if word in message_lower:
                score += 30
                break
        
        for word in tech_words:
            if word in message_lower:
                score += 25
                break
        
        # Дополнительные баллы за вопросы
        if any(word in message_lower for word in ['как', 'что', 'где', 'кто может', '?']):
            score += 10
        
        # Снижаем балл за нерелевантные сообщения
        irrelevant_words = ['спам', 'реклама', 'продаю', 'куплю авто', 'недвижимость']
        for word in irrelevant_words:
            if word in message_lower:
                score -= 20
        
        # Проверяем длину сообщения (слишком короткие обычно не интересны)
        if len(message_text) < 20:
            score -= 10
        
        return max(0, min(100, score))

    async def _lead_exists(self, user_id: int, message_text: str) -> bool:
        """Проверка существования лида"""
        try:
            from database.operations import get_connection
            async with await get_connection() as db:
                # Проверяем по пользователю и похожему тексту (последние 7 дней)
                cursor = await db.execute("""
                    SELECT id FROM leads 
                    WHERE telegram_id = ? 
                    AND created_at >= datetime('now', '-7 days')
                    LIMIT 1
                """, (user_id,))
                result = await cursor.fetchone()
                return result is not None
        except Exception as e:
            logger.error(f"Ошибка проверки существования лида: {e}")
            return False

    async def _update_channel_stats(self, channel_identifier: str, message_id: int, lead_found: bool):
        """Обновление статистики канала"""
        try:
            leads_count = 1 if lead_found else 0
            await update_channel_stats(channel_identifier, message_id, leads_count)
        except Exception as e:
            logger.error(f"Ошибка обновления статистики канала: {e}")

    async def _notify_admins_about_lead(self, context: ContextTypes.DEFAULT_TYPE, lead: Lead):
        """Уведомление админов о новом лиде"""
        try:
            admin_ids = self.config.get('bot', {}).get('admin_ids', [])
            
            if not admin_ids:
                return
            
            # Формируем сообщение
            username_text = f"@{lead.username}" if lead.username else "без username"
            message = f"""🎯 <b>НОВЫЙ ЛИД!</b>

👤 <b>Пользователь:</b> {lead.first_name} ({username_text})
⭐ <b>Скор:</b> {lead.interest_score}/100
📺 <b>Источник:</b> {lead.source_channel}
💬 <b>Сообщение:</b> 
<i>{lead.message_text[:300]}...</i>

🔗 <b>Профиль:</b> tg://user?id={lead.telegram_id}"""

            # Отправляем всем админам
            for admin_id in admin_ids:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=message,
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")
        
        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений админам: {e}")

    async def initialize_channels(self):
        """Инициализация каналов в базе данных"""
        try:
            for channel_identifier in self.channels:
                channel = ParsedChannel(
                    channel_username=channel_identifier,
                    channel_title=f"Канал {channel_identifier}",
                    enabled=True
                )
                await create_or_update_channel(channel)
            
            logger.info(f"Инициализировано {len(self.channels)} каналов в БД")
        except Exception as e:
            logger.error(f"Ошибка инициализации каналов: {e}")

    def get_parsing_status(self) -> Dict[str, Any]:
        """Получение статуса парсинга"""
        return {
            'enabled': self.enabled,
            'channels_count': len(self.channels),
            'channels': self.channels,
            'min_score': self.min_interest_score,
            'processed_messages_count': len(self.processed_messages)
        }

    def is_channel_monitored(self, chat_id: int, chat_username: str = None) -> bool:
        """Проверка, отслеживается ли канал/группа"""
        if not self.enabled:
            return False
        
        # Проверяем по ID
        if str(chat_id) in self.channels:
            return True
        
        # Проверяем по username
        if chat_username:
            username_variants = [f"@{chat_username}", chat_username]
            for variant in username_variants:
                if variant in self.channels:
                    return True
        
        return False

    async def add_channel(self, channel_identifier: str) -> bool:
        """Добавление нового канала для мониторинга"""
        try:
            if channel_identifier not in self.channels:
                self.channels.append(channel_identifier)
                
                # Добавляем в БД
                channel = ParsedChannel(
                    channel_username=channel_identifier,
                    channel_title=f"Канал {channel_identifier}",
                    enabled=True
                )
                await create_or_update_channel(channel)
                
                logger.info(f"Канал {channel_identifier} добавлен для мониторинга")
                return True
            
            return False
        except Exception as e:
            logger.error(f"Ошибка добавления канала {channel_identifier}: {e}")
            return False

    async def remove_channel(self, channel_identifier: str) -> bool:
        """Удаление канала из мониторинга"""
        try:
            if channel_identifier in self.channels:
                self.channels.remove(channel_identifier)
                
                # Отключаем в БД
                from database.operations import get_connection
                async with await get_connection() as db:
                    await db.execute(
                        "UPDATE parsed_channels SET enabled = FALSE WHERE channel_username = ?",
                        (channel_identifier,)
                    )
                    await db.commit()
                
                logger.info(f"Канал {channel_identifier} удален из мониторинга")
                return True
            
            return False
        except Exception as e:
            logger.error(f"Ошибка удаления канала {channel_identifier}: {e}")
            return False
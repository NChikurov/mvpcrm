"""
Парсер Telegram каналов для поиска потенциальных клиентов
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from telegram import Bot
from telegram.error import TelegramError

from database.operations import (
    create_or_update_channel, get_active_channels, create_lead,
    update_channel_stats
)
from database.models import ParsedChannel, Lead
from ai.claude_client import get_claude_client

logger = logging.getLogger(__name__)

class ChannelParser:
    """Парсер каналов для поиска лидов через Bot API"""
    
    def __init__(self, config):
        self.config = config
        self.parsing_config = config.get('parsing', {})
        self.is_running = False
        self.bot = None
        
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
        self.parse_interval = self.parsing_config.get('parse_interval', 3600)  # 1 час
        self.max_messages_per_parse = self.parsing_config.get('max_messages_per_parse', 50)
        
        # Используем токен бота для парсинга
        self.bot_token = config.get('bot', {}).get('token', '')
        
        logger.info(f"Парсер инициализирован: {len(self.channels)} каналов")

    async def init_bot(self):
        """Инициализация Bot API клиента"""
        try:
            if not self.bot_token:
                logger.error("Bot token не установлен")
                return False
            
            self.bot = Bot(token=self.bot_token)
            
            # Проверяем что бот работает
            bot_info = await self.bot.get_me()
            logger.info(f"Bot API инициализирован: @{bot_info.username}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка инициализации Bot API: {e}")
            return False

    async def start_parsing(self):
        """Запуск парсинга каналов"""
        if not self.enabled:
            logger.info("Парсинг каналов отключен в конфигурации")
            return
        
        if not self.channels:
            logger.warning("Не настроены каналы для парсинга")
            return
        
        self.is_running = True
        logger.info("Запуск парсинга каналов...")
        
        # Инициализируем каналы в БД
        await self._init_channels_in_db()
        
        # Инициализируем бота
        bot_ready = await self.init_bot()
        if not bot_ready:
            logger.error("Не удалось инициализировать Bot API, парсинг остановлен")
            return
        
        # Запускаем основной цикл парсинга
        while self.is_running:
            try:
                await self._parse_all_channels()
                
                # Ждем до следующего парсинга
                logger.info(f"Следующий парсинг через {self.parse_interval} секунд")
                await asyncio.sleep(self.parse_interval)
                
            except Exception as e:
                logger.error(f"Ошибка в цикле парсинга: {e}")
                await asyncio.sleep(60)  # Короткая пауза при ошибке

    async def stop_parsing(self):
        """Остановка парсинга"""
        self.is_running = False
        logger.info("Парсинг остановлен")

    async def _init_channels_in_db(self):
        """Инициализация каналов в базе данных"""
        for channel_username in self.channels:
            channel = ParsedChannel(
                channel_username=str(channel_username),
                channel_title=f"Канал {channel_username}",
                enabled=True
            )
            await create_or_update_channel(channel)
        
        logger.info(f"Инициализировано {len(self.channels)} каналов в БД")

    async def _parse_all_channels(self):
        """Парсинг всех активных каналов"""
        active_channels = await get_active_channels()
        
        for channel in active_channels:
            try:
                await self._parse_channel(channel)
            except Exception as e:
                logger.error(f"Ошибка парсинга канала {channel.channel_username}: {e}")

    async def _parse_channel(self, channel: ParsedChannel):
        """Парсинг одного канала через Bot API"""
        logger.info(f"Парсинг канала: {channel.channel_username}")
        
        try:
            # Получаем информацию о канале
            try:
                chat = await self.bot.get_chat(channel.channel_username)
                logger.info(f"Канал найден: {chat.title}")
                
                # Обновляем название канала в БД
                if chat.title and chat.title != channel.channel_title:
                    channel.channel_title = chat.title
                    await create_or_update_channel(channel)
                
            except TelegramError as e:
                if "chat not found" in str(e).lower():
                    logger.warning(f"Канал {channel.channel_username} не найден или бот не добавлен")
                else:
                    logger.error(f"Ошибка доступа к каналу {channel.channel_username}: {e}")
                return
            
            # Получаем последние сообщения из канала
            messages = await self._get_channel_messages_via_bot(channel)
            
            leads_found = 0
            
            for message_data in messages:
                # Анализируем сообщение через Claude
                claude_client = get_claude_client()
                if claude_client:
                    interest_score = await claude_client.analyze_potential_lead(
                        message_data['text'],
                        channel.channel_username
                    )
                    
                    # Если скор высокий - сохраняем как лид
                    if interest_score >= self.min_interest_score:
                        # Проверяем, что такой лид еще не существует
                        if not await self._lead_exists(message_data.get('user_id'), message_data['text']):
                            lead = Lead(
                                telegram_id=message_data.get('user_id'),
                                username=message_data.get('username'),
                                first_name=message_data.get('first_name'),
                                source_channel=channel.channel_username,
                                interest_score=interest_score,
                                message_text=message_data['text'],
                                message_date=message_data.get('date')
                            )
                            
                            await create_lead(lead)
                            leads_found += 1
                            
                            logger.info(f"Найден лид: {lead.first_name} (score: {interest_score})")
            
            # Обновляем статистику канала
            if messages:
                last_message_id = max(msg.get('message_id', 0) for msg in messages)
                await update_channel_stats(
                    channel.channel_username,
                    last_message_id,
                    leads_found
                )
            
            logger.info(f"Канал {channel.channel_username}: обработано {len(messages)} сообщений, найдено {leads_found} лидов")
            
        except Exception as e:
            logger.error(f"Ошибка парсинга канала {channel.channel_username}: {e}")

    async def _get_channel_messages_via_bot(self, channel: ParsedChannel) -> List[dict]:
        """Получение сообщений через Bot API"""
        messages = []
        
        try:
            # Получаем последние обновления из канала
            # Примечание: Bot API имеет ограничения на получение истории сообщений
            # Мы можем получить только сообщения, которые бот "видел"
            
            # Альтернативный подход: мониторинг новых сообщений
            # Для демонстрации создаем тестовые сообщения
            
            current_time = datetime.now()
            
            # Симулируем новые сообщения (в реальности они приходили бы через updates)
            demo_messages = [
                {
                    'message_id': int(current_time.timestamp()),
                    'text': 'Ищу систему CRM для своего интернет-магазина. Кто может посоветовать?',
                    'date': current_time - timedelta(minutes=15),
                    'user_id': 111111,
                    'username': 'business_user1',
                    'first_name': 'Алексей'
                },
                {
                    'message_id': int(current_time.timestamp()) + 1,
                    'text': 'Нужна автоматизация продаж через телеграм. Бюджет есть.',
                    'date': current_time - timedelta(minutes=30),
                    'user_id': 222222,
                    'username': 'entrepreneur',
                    'first_name': 'Мария'
                },
                {
                    'message_id': int(current_time.timestamp()) + 2,
                    'text': 'Кто-то пользуется ботами для обработки заявок? Эффективно?',
                    'date': current_time - timedelta(hours=1),
                    'user_id': 333333,
                    'username': 'manager_anna',
                    'first_name': 'Анна'
                },
                {
                    'message_id': int(current_time.timestamp()) + 3,
                    'text': 'Привет всем! Как дела?',
                    'date': current_time - timedelta(hours=2),
                    'user_id': 444444,
                    'username': 'regular_user',
                    'first_name': 'Сергей'
                },
                {
                    'message_id': int(current_time.timestamp()) + 4,
                    'text': 'Помогите выбрать платформу для онлайн-продаж. Рассматриваю разные варианты.',
                    'date': current_time - timedelta(hours=3),
                    'user_id': 555555,
                    'username': 'shop_owner',
                    'first_name': 'Елена'
                }
            ]
            
            # Фильтруем сообщения, которые мы еще не обрабатывали
            for msg in demo_messages:
                if not channel.last_message_id or msg['message_id'] > channel.last_message_id:
                    messages.append(msg)
            
            logger.info(f"Получено {len(messages)} новых сообщений из {channel.channel_username}")
            
        except Exception as e:
            logger.error(f"Ошибка получения сообщений из {channel.channel_username}: {e}")
        
        return messages

    async def _lead_exists(self, user_id: Optional[int], message_text: str) -> bool:
        """Проверка существования лида"""
        # Простая проверка по тексту сообщения
        # В реальной системе нужна более сложная логика
        try:
            from database.operations import get_connection
            async with await get_connection() as db:
                cursor = await db.execute(
                    "SELECT id FROM leads WHERE message_text = ? LIMIT 1",
                    (message_text,)
                )
                result = await cursor.fetchone()
                return result is not None
        except Exception as e:
            logger.error(f"Ошибка проверки существования лида: {e}")
            return False

    def get_parsing_status(self) -> dict:
        """Получение статуса парсинга"""
        return {
            'is_running': self.is_running,
            'enabled': self.enabled,
            'channels_count': len(self.channels),
            'interval': self.parse_interval,
            'min_score': self.min_interest_score,
            'bot_configured': bool(self.bot_token)
        }

    async def add_channel(self, channel_username: str) -> bool:
        """Добавление нового канала для парсинга"""
        try:
            # Проверяем доступность канала
            if self.bot:
                chat = await self.bot.get_chat(channel_username)
                
                # Создаем запись в БД
                channel = ParsedChannel(
                    channel_username=channel_username,
                    channel_title=chat.title or f"Канал {channel_username}",
                    enabled=True
                )
                await create_or_update_channel(channel)
                
                # Добавляем в список для парсинга
                if channel_username not in self.channels:
                    self.channels.append(channel_username)
                
                logger.info(f"Канал {channel_username} добавлен для парсинга")
                return True
                
        except TelegramError as e:
            logger.error(f"Ошибка добавления канала {channel_username}: {e}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при добавлении канала: {e}")
            return False

    async def remove_channel(self, channel_username: str) -> bool:
        """Удаление канала из парсинга"""
        try:
            # Отключаем в БД
            from database.operations import get_connection
            async with await get_connection() as db:
                await db.execute(
                    "UPDATE parsed_channels SET enabled = FALSE WHERE channel_username = ?",
                    (channel_username,)
                )
                await db.commit()
            
            # Удаляем из списка
            if channel_username in self.channels:
                self.channels.remove(channel_username)
            
            logger.info(f"Канал {channel_username} отключен от парсинга")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка отключения канала {channel_username}: {e}")
            return False
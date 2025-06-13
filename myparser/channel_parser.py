"""
Парсер Telegram каналов для поиска потенциальных клиентов
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from telethon import TelegramClient
from telethon.tl.types import User

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
        self.telegram_api_config = config.get('telegram_api', {})
        self.is_running = False
        self.client = None
        
        # Настройки парсинга
        self.enabled = self.parsing_config.get('enabled', True)
        
        # Безопасное получение каналов с проверкой типа
        channels_raw = self.parsing_config.get('channels', [])
        if isinstance(channels_raw, list):
            self.channels = [str(ch) for ch in channels_raw]  # Преобразуем все в строки
        elif isinstance(channels_raw, (str, int)):
            self.channels = [str(channels_raw)]  # Если один канал - делаем список
        else:
            self.channels = []
            logger.warning(f"Некорректный формат каналов в конфигурации: {channels_raw}")
        
        self.min_interest_score = self.parsing_config.get('min_interest_score', 60)
        self.parse_interval = self.parsing_config.get('parse_interval', 3600)  # 1 час
        self.max_messages_per_parse = self.parsing_config.get('max_messages_per_parse', 50)
        
        # API данные для Telegram
        self.api_id = self.telegram_api_config.get('api_id', 0)
        self.api_hash = self.telegram_api_config.get('api_hash', '')
        
        logger.info(f"Парсер инициализирован: {len(self.channels)} каналов ({self.channels})")
        
        if not self.api_id or not self.api_hash:
            logger.warning("API ID или API Hash не настроены, парсинг будет работать в демо режиме")

    async def init_client(self):
        """Инициализация Telegram клиента"""
        try:
            if not self.api_id or not self.api_hash:
                logger.info("Telegram API не настроен, используется демо режим")
                return False
            
            self.client = TelegramClient('bot_session', self.api_id, self.api_hash)
            
            # Для реального использования раскомментируйте:
            # await self.client.start()
            
            logger.info("Telegram клиент инициализирован")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка инициализации Telegram клиента: {e}")
            logger.warning("Парсинг будет работать в демо режиме")
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
        
        # Инициализируем клиент
        client_ready = await self.init_client()
        
        # Запускаем основной цикл парсинга
        while self.is_running:
            try:
                if client_ready:
                    await self._parse_all_channels()
                else:
                    await self._demo_parsing()
                
                # Ждем до следующего парсинга
                logger.info(f"Следующий парсинг через {self.parse_interval} секунд")
                await asyncio.sleep(self.parse_interval)
                
            except Exception as e:
                logger.error(f"Ошибка в цикле парсинга: {e}")
                await asyncio.sleep(60)  # Короткая пауза при ошибке

    async def stop_parsing(self):
        """Остановка парсинга"""
        self.is_running = False
        if self.client:
            await self.client.disconnect()
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
        """Парсинг одного канала"""
        logger.info(f"Парсинг канала: {channel.channel_username}")
        
        try:
            # Получаем сообщения из канала
            messages = await self._get_channel_messages(
                channel.channel_username,
                channel.last_message_id,
                self.max_messages_per_parse
            )
            
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

    async def _get_channel_messages(self, channel_username: str, last_message_id: Optional[int], limit: int) -> List[dict]:
        """Получение сообщений из канала"""
        if not self.client:
            # Демо режим - возвращаем тестовые сообщения
            return await self._get_demo_messages(channel_username)
        
        try:
            # Получаем канал
            entity = await self.client.get_entity(channel_username)
            
            # Получаем сообщения
            messages = []
            async for message in self.client.iter_messages(
                entity,
                limit=limit,
                min_id=last_message_id or 0
            ):
                if message.text:  # Только текстовые сообщения
                    user_data = {}
                    if message.sender:
                        if isinstance(message.sender, User):
                            user_data = {
                                'user_id': message.sender.id,
                                'username': message.sender.username,
                                'first_name': message.sender.first_name
                            }
                    
                    messages.append({
                        'message_id': message.id,
                        'text': message.text,
                        'date': message.date,
                        **user_data
                    })
            
            return messages
            
        except Exception as e:
            logger.error(f"Ошибка получения сообщений из {channel_username}: {e}")
            return []

    async def _get_demo_messages(self, channel_username: str) -> List[dict]:
        """Демо сообщения для тестирования без реального API"""
        demo_messages = [
            {
                'message_id': 1001,
                'text': 'Ищу хорошую CRM систему для интернет-магазина. Какие варианты посоветуете?',
                'date': datetime.now() - timedelta(minutes=30),
                'user_id': 111111,
                'username': 'user1',
                'first_name': 'Анна'
            },
            {
                'message_id': 1002,
                'text': 'Кто-нибудь пользовался Telegram ботами для продаж? Стоит ли вкладываться?',
                'date': datetime.now() - timedelta(minutes=45),
                'user_id': 222222,
                'username': 'user2',
                'first_name': 'Михаил'
            },
            {
                'message_id': 1003,
                'text': 'Нужна автоматизация для бизнеса. Бюджет до 100к рублей.',
                'date': datetime.now() - timedelta(hours=1),
                'user_id': 333333,
                'username': 'user3',
                'first_name': 'Елена'
            },
            {
                'message_id': 1004,
                'text': 'Красивая погода сегодня!',
                'date': datetime.now() - timedelta(hours=2),
                'user_id': 444444,
                'username': 'user4',
                'first_name': 'Петр'
            },
            {
                'message_id': 1005,
                'text': 'Помогите выбрать решение для обработки заявок клиентов. Заявок много, не успеваем обрабатывать.',
                'date': datetime.now() - timedelta(hours=3),
                'user_id': 555555,
                'username': 'user5',
                'first_name': 'Ольга'
            }
        ]
        
        logger.info(f"Демо режим: возвращено {len(demo_messages)} сообщений для {channel_username}")
        return demo_messages

    async def _demo_parsing(self):
        """Демо парсинг для тестирования без реального API"""
        logger.info("Запуск демо парсинга...")
        
        active_channels = await get_active_channels()
        
        for channel in active_channels:
            try:
                # Получаем демо сообщения
                messages = await self._get_demo_messages(channel.channel_username)
                
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
                            # Проверяем, что лид еще не существует
                            existing_lead = await self._check_existing_lead(
                                message_data.get('user_id'),
                                message_data['text']
                            )
                            
                            if not existing_lead:
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
                
                logger.info(f"Демо парсинг {channel.channel_username}: {len(messages)} сообщений, {leads_found} лидов")
                
            except Exception as e:
                logger.error(f"Ошибка демо парсинга канала {channel.channel_username}: {e}")

    async def _check_existing_lead(self, user_id: Optional[int], message_text: str) -> bool:
        """Проверка существования лида (простая проверка по тексту)"""
        # Простая проверка - в реальной системе нужна более сложная логика
        return False

    def get_parsing_status(self) -> dict:
        """Получение статуса парсинга"""
        return {
            'is_running': self.is_running,
            'enabled': self.enabled,
            'channels_count': len(self.channels),
            'interval': self.parse_interval,
            'min_score': self.min_interest_score,
            'api_configured': bool(self.api_id and self.api_hash)
        }
                
"""
myparser/telethon_parser.py - Расширенный парсер с Telethon для доступа к публичным каналам
Решает проблему ограничений Telegram Bot API
"""

import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set
from pathlib import Path
from dataclasses import dataclass

try:
    from telethon import TelegramClient, events
    from telethon.tl.types import Channel, Chat, User, MessageService
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

from ai.claude_client import get_claude_client
from database.operations import create_lead
from database.models import Lead

logger = logging.getLogger(__name__)

@dataclass
class TelethonConfig:
    """Конфигурация Telethon клиента"""
    api_id: int
    api_hash: str
    session_name: str = "ai_crm_session"
    enabled: bool = False
    channels: List[str] = None
    proxy: Optional[Dict[str, Any]] = None

class TelethonChannelParser:
    """Расширенный парсер каналов через Telethon"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.telethon_config = self._parse_telethon_config()
        self.client: Optional[TelegramClient] = None
        self.monitored_channels: Set[str] = set()
        
        # Статистика
        self.stats = {
            'messages_parsed': 0,
            'channels_monitored': 0,
            'leads_created': 0,
            'api_calls': 0,
            'errors': 0,
            'last_update': datetime.now()
        }
        
        self.enabled = TELETHON_AVAILABLE and self.telethon_config.enabled
        
        if not TELETHON_AVAILABLE:
            logger.warning("Telethon не установлен. Установите: pip install telethon")
        elif not self.telethon_config.enabled:
            logger.info("Telethon парсер отключен в конфигурации")
        else:
            logger.info("Telethon парсер инициализирован")

    def _parse_telethon_config(self) -> TelethonConfig:
        """Парсинг конфигурации Telethon"""
        telethon_section = self.config.get('telethon', {})
        
        return TelethonConfig(
            api_id=telethon_section.get('api_id', 0),
            api_hash=telethon_section.get('api_hash', ''),
            session_name=telethon_section.get('session_name', 'ai_crm_session'),
            enabled=telethon_section.get('enabled', False),
            channels=telethon_section.get('channels', []),
            proxy=telethon_section.get('proxy')
        )

    async def initialize(self) -> bool:
        """Инициализация Telethon клиента"""
        if not self.enabled:
            return False
        
        if not self.telethon_config.api_id or not self.telethon_config.api_hash:
            logger.error("Telethon: api_id и api_hash не настроены")
            return False
        
        try:
            # Создаем клиента
            self.client = TelegramClient(
                self.telethon_config.session_name,
                self.telethon_config.api_id,
                self.telethon_config.api_hash,
                proxy=self.telethon_config.proxy
            )
            
            await self.client.start()
            
            # Проверяем авторизацию
            if not await self.client.is_user_authorized():
                logger.error("Telethon: пользователь не авторизован")
                return False
            
            me = await self.client.get_me()
            logger.info(f"Telethon: авторизован как {me.username or me.first_name}")
            
            # Подключаемся к каналам
            await self._setup_channels()
            
            # Регистрируем обработчики событий
            self._register_handlers()
            
            self.enabled = True
            logger.info("Telethon парсер успешно инициализирован")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка инициализации Telethon: {e}")
            self.enabled = False
            return False

    async def _setup_channels(self):
        """Настройка мониторинга каналов"""
        for channel in self.telethon_config.channels:
            try:
                entity = await self.client.get_entity(channel)
                self.monitored_channels.add(channel)
                
                # Получаем информацию о канале
                if hasattr(entity, 'title'):
                    logger.info(f"Telethon: подключен к {entity.title} ({channel})")
                else:
                    logger.info(f"Telethon: подключен к {channel}")
                
                self.stats['channels_monitored'] += 1
                
            except Exception as e:
                logger.error(f"Ошибка подключения к каналу {channel}: {e}")

    def _register_handlers(self):
        """Регистрация обработчиков событий"""
        @self.client.on(events.NewMessage())
        async def handle_new_message(event):
            try:
                await self._process_telethon_message(event)
            except Exception as e:
                logger.error(f"Ошибка обработки Telethon сообщения: {e}")
                self.stats['errors'] += 1

    async def _process_telethon_message(self, event):
        """Обработка нового сообщения через Telethon"""
        try:
            # Пропускаем служебные сообщения
            if isinstance(event.message, MessageService):
                return
            
            # Проверяем, что канал мониторится
            chat = await event.get_chat()
            channel_username = getattr(chat, 'username', None)
            
            if not self._is_channel_monitored(chat.id, channel_username):
                return
            
            # Получаем отправителя
            sender = await event.get_sender()
            if not sender or isinstance(sender, Channel):
                return
            
            message_text = event.text
            if not message_text or len(message_text.strip()) < 10:
                return
            
            self.stats['messages_parsed'] += 1
            self.stats['api_calls'] += 1
            
            # Анализируем сообщение через AI
            await self._analyze_telethon_message(sender, message_text, chat, event)
            
        except Exception as e:
            logger.error(f"Ошибка в _process_telethon_message: {e}")
            self.stats['errors'] += 1

    def _is_channel_monitored(self, chat_id: int, username: str = None) -> bool:
        """Проверка мониторинга канала"""
        # Проверяем по ID
        if str(chat_id) in self.monitored_channels:
            return True
        
        # Проверяем по username
        if username:
            for channel in self.monitored_channels:
                if channel.replace('@', '') == username:
                    return True
        
        return False

    async def _analyze_telethon_message(self, sender: User, message_text: str, 
                                      chat, event):
        """AI анализ сообщения от Telethon"""
        try:
            claude_client = get_claude_client()
            if not claude_client or not claude_client.client:
                return
            
            # Контекст для анализа
            context = {
                'channel': getattr(chat, 'title', 'Unknown'),
                'username': getattr(chat, 'username', ''),
                'message_length': len(message_text),
                'sender_username': getattr(sender, 'username', ''),
                'sender_premium': getattr(sender, 'premium', False)
            }
            
            # Промпт для анализа потенциального лида
            prompt = f"""Проанализируй сообщение из Telegram канала на предмет коммерческого интереса.

КАНАЛ: {context['channel']}
АВТОР: {sender.first_name or 'Unknown'} (@{context['sender_username'] or 'no_username'})
СООБЩЕНИЕ: "{message_text}"

ОЦЕНИ:
1. Коммерческий интерес (0-100)
2. Потенциал как лид (0-100)  
3. Покупательские сигналы
4. Срочность потребности

ИЩИ СИГНАЛЫ:
- Потребности в AI/CRM/автоматизации
- Обсуждение бюджетов
- Поиск исполнителей/поставщиков
- Технические требования
- Сроки реализации

Верни JSON:
{{
    "commercial_interest": число_0_100,
    "lead_potential": число_0_100,
    "buying_signals": ["список_сигналов"],
    "urgency_level": "low/medium/high",
    "key_phrases": ["ключевые_фразы"],
    "recommended_action": "действие",
    "lead_quality": "cold/warm/hot"
}}"""

            response = await asyncio.wait_for(
                claude_client.client.messages.create(
                    model=claude_client.model,
                    max_tokens=500,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1
                ),
                timeout=15.0
            )
            
            # Парсим ответ
            analysis = self._parse_analysis_response(response.content[0].text)
            
            # Создаем лид если достаточно высокий потенциал
            if analysis.get('lead_potential', 0) >= 70:
                await self._create_telethon_lead(sender, message_text, chat, analysis)
            
        except Exception as e:
            logger.error(f"Ошибка анализа Telethon сообщения: {e}")

    def _parse_analysis_response(self, response_text: str) -> Dict[str, Any]:
        """Парсинг ответа анализа"""
        try:
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.error(f"Ошибка парсинга анализа: {e}")
        
        return {
            'commercial_interest': 0,
            'lead_potential': 0,
            'buying_signals': [],
            'urgency_level': 'low',
            'key_phrases': [],
            'recommended_action': 'monitor',
            'lead_quality': 'cold'
        }

    async def _create_telethon_lead(self, sender: User, message_text: str, 
                                  chat, analysis: Dict[str, Any]):
        """Создание лида из Telethon данных"""
        try:
            lead = Lead(
                telegram_id=sender.id,
                username=getattr(sender, 'username', None),
                first_name=getattr(sender, 'first_name', 'Unknown'),
                last_name=getattr(sender, 'last_name', None),
                source_channel=f"{getattr(chat, 'title', 'Unknown')} (Telethon)",
                interest_score=analysis.get('lead_potential', 0),
                message_text=message_text[:500],  # Ограничиваем длину
                message_date=datetime.now(),
                lead_quality=analysis.get('lead_quality', 'warm'),
                interests=json.dumps(analysis.get('key_phrases', []), ensure_ascii=False),
                buying_signals=json.dumps(analysis.get('buying_signals', []), ensure_ascii=False),
                urgency_level=analysis.get('urgency_level', 'medium'),
                notes=f"Telethon: {analysis.get('recommended_action', 'Review required')}"
            )
            
            await create_lead(lead)
            self.stats['leads_created'] += 1
            
            logger.info(f"Telethon лид создан: {sender.first_name} ({analysis.get('lead_potential', 0)}%)")
            
        except Exception as e:
            logger.error(f"Ошибка создания Telethon лида: {e}")

    async def scan_channel_history(self, channel: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Сканирование истории канала"""
        if not self.enabled:
            return []
        
        try:
            entity = await self.client.get_entity(channel)
            messages = []
            
            async for message in self.client.iter_messages(entity, limit=limit):
                if message.text and len(message.text.strip()) > 10:
                    messages.append({
                        'id': message.id,
                        'text': message.text,
                        'date': message.date,
                        'sender_id': message.sender_id,
                        'views': getattr(message, 'views', 0),
                        'forwards': getattr(message, 'forwards', 0)
                    })
            
            logger.info(f"Telethon: просканировано {len(messages)} сообщений из {channel}")
            return messages
            
        except Exception as e:
            logger.error(f"Ошибка сканирования канала {channel}: {e}")
            return []

    async def get_channel_info(self, channel: str) -> Dict[str, Any]:
        """Получение информации о канале"""
        if not self.enabled:
            return {}
        
        try:
            entity = await self.client.get_entity(channel)
            
            info = {
                'id': entity.id,
                'title': getattr(entity, 'title', ''),
                'username': getattr(entity, 'username', ''),
                'participants_count': getattr(entity, 'participants_count', 0),
                'is_channel': isinstance(entity, Channel),
                'verified': getattr(entity, 'verified', False),
                'restricted': getattr(entity, 'restricted', False)
            }
            
            return info
            
        except Exception as e:
            logger.error(f"Ошибка получения информации о канале {channel}: {e}")
            return {}

    async def search_messages(self, channel: str, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Поиск сообщений в канале"""
        if not self.enabled:
            return []
        
        try:
            entity = await self.client.get_entity(channel)
            messages = []
            
            async for message in self.client.iter_messages(entity, search=query, limit=limit):
                if message.text:
                    messages.append({
                        'id': message.id,
                        'text': message.text,
                        'date': message.date,
                        'sender_id': message.sender_id,
                        'views': getattr(message, 'views', 0)
                    })
            
            return messages
            
        except Exception as e:
            logger.error(f"Ошибка поиска в канале {channel}: {e}")
            return []

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса Telethon парсера"""
        return {
            'enabled': self.enabled,
            'telethon_available': TELETHON_AVAILABLE,
            'client_connected': self.client is not None and self.client.is_connected(),
            'monitored_channels': list(self.monitored_channels),
            'stats': self.stats.copy(),
            'config': {
                'api_id_set': bool(self.telethon_config.api_id),
                'api_hash_set': bool(self.telethon_config.api_hash),
                'session_name': self.telethon_config.session_name,
                'proxy_enabled': bool(self.telethon_config.proxy)
            }
        }

    async def stop(self):
        """Остановка Telethon клиента"""
        if self.client and self.client.is_connected():
            await self.client.disconnect()
            logger.info("Telethon клиент отключен")

    async def add_channel(self, channel: str) -> bool:
        """Добавление нового канала для мониторинга"""
        if not self.enabled:
            return False
        
        try:
            entity = await self.client.get_entity(channel)
            self.monitored_channels.add(channel)
            self.stats['channels_monitored'] += 1
            
            logger.info(f"Telethon: добавлен канал {getattr(entity, 'title', channel)}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка добавления канала {channel}: {e}")
            return False

    async def remove_channel(self, channel: str) -> bool:
        """Удаление канала из мониторинга"""
        if channel in self.monitored_channels:
            self.monitored_channels.remove(channel)
            self.stats['channels_monitored'] -= 1
            logger.info(f"Telethon: удален канал {channel}")
            return True
        
        return False

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Получение метрик производительности"""
        uptime = datetime.now() - self.stats['last_update']
        
        return {
            'messages_per_hour': self.stats['messages_parsed'] / max(uptime.total_seconds() / 3600, 1),
            'leads_conversion_rate': (self.stats['leads_created'] / max(self.stats['messages_parsed'], 1)) * 100,
            'error_rate': (self.stats['errors'] / max(self.stats['api_calls'], 1)) * 100,
            'channels_efficiency': self.stats['leads_created'] / max(self.stats['channels_monitored'], 1),
            'uptime_hours': uptime.total_seconds() / 3600
        }

# Функция для интеграции с основным парсером
def create_telethon_parser(config: Dict[str, Any]) -> TelethonChannelParser:
    """Создание Telethon парсера"""
    return TelethonChannelParser(config)
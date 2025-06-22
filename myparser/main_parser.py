"""
myparser/main_parser.py - ПОЛНОСТЬЮ ИСПРАВЛЕННЫЙ AI парсер
Умный анализ диалогов без дублирования - ИСПРАВЛЕНЫ ВСЕ ОШИБКИ
"""

import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from telegram import Update, User
from telegram.ext import ContextTypes

from database.operations import create_lead, update_channel_stats
from database.models import Lead
from ai.claude_client import get_claude_client

logger = logging.getLogger(__name__)

# === МОДЕЛИ ДАННЫХ ===

@dataclass
class DialogueParticipant:
    """Участник диалога"""
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    role: str = "participant"
    message_count: int = 0
    first_message_time: Optional[datetime] = None
    last_message_time: Optional[datetime] = None
    engagement_level: str = "low"
    buying_signals_count: int = 0
    influence_score: int = 0
    lead_probability: float = 0.0

    @property
    def display_name(self) -> str:
        """Отображаемое имя участника"""
        return self.first_name or f"User_{self.user_id}"

@dataclass
class DialogueMessage:
    """Сообщение в диалоге"""
    user_id: int
    username: Optional[str]
    text: str
    timestamp: datetime
    message_id: int
    reply_to_message_id: Optional[int] = None
    reply_to_user_id: Optional[int] = None
    buying_signals: List[str] = None
    sentiment: str = "neutral"
    urgency_level: str = "none"

@dataclass
class DialogueContext:
    """Контекст диалога"""
    dialogue_id: str
    channel_id: int
    channel_title: str
    participants: Dict[int, DialogueParticipant]
    messages: List[DialogueMessage]
    start_time: datetime
    last_activity: datetime
    topic: Optional[str] = None
    dialogue_type: str = "discussion"
    is_business_related: bool = False
    overall_sentiment: str = "neutral"
    decision_stage: str = "awareness"
    group_buying_probability: float = 0.0

@dataclass
class DialogueAnalysisResult:
    """Результат анализа диалога"""
    dialogue_id: str
    is_valuable_dialogue: bool
    confidence_score: int
    potential_leads: List[Dict[str, Any]]
    business_relevance_score: int
    dialogue_summary: str
    key_insights: List[str]
    recommended_actions: List[str]
    next_best_action: str
    estimated_timeline: Optional[str]
    group_budget_estimate: Optional[str]
    participant_analysis: Dict[int, Dict[str, Any]]

@dataclass
class UserContext:
    """Контекст пользователя"""
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    messages: List[Dict[str, Any]]
    first_seen: datetime
    last_activity: datetime
    channel_info: Dict[str, Any]

@dataclass
class AIAnalysisResult:
    """Результат AI анализа"""
    is_lead: bool
    confidence_score: int
    lead_quality: str
    interests: List[str]
    buying_signals: List[str]
    urgency_level: str
    recommended_action: str
    key_insights: List[str]
    estimated_budget: Optional[str]
    timeline: Optional[str]
    pain_points: List[str]
    decision_stage: str

@dataclass
class MessageWindow:
    """Окно сообщений для анализа"""
    messages: List[Dict[str, Any]]
    timespan: timedelta
    unique_users: set
    has_replies: bool
    has_business_signals: bool
    conversation_type: str  # "individual", "dialogue", "group_chat"

# ИСПРАВЛЕНИЕ: Добавляем недостающие классы
@dataclass
class ParticipantInfo:
    """Информация об участнике для анализа"""
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    
    @property
    def display_name(self) -> str:
        return self.first_name or f"User_{self.user_id}"

@dataclass
class MessageInfo:
    """Информация о сообщении для анализа"""
    text: str
    timestamp: datetime
    channel_id: int
    user_id: int

# === УМНЫЙ ТРЕКЕР ДИАЛОГОВ ===

class SmartDialogueTracker:
    """Умный трекер диалогов с анализом окна сообщений"""
    
    def __init__(self, config):
        self.config = config
        self.active_dialogues: Dict[str, DialogueContext] = {}
        
        # Настройки анализа окна
        self.message_window_size = 10  # Анализируем последние 10 сообщений
        self.dialogue_detection_window = timedelta(minutes=15)  # 15 минут для связи сообщений
        self.max_gap_between_messages = timedelta(minutes=5)  # Макс. пауза между сообщениями
        
        # Настройки диалогов
        self.dialogue_timeout = timedelta(minutes=20)  # Диалог завершается через 20 мин бездействия
        self.min_participants = 2
        self.min_messages = 2
        
        # Кэш сообщений по каналам
        self.channel_message_cache: Dict[int, List[Dict[str, Any]]] = {}
        
        # Сигналы для анализа
        self.business_signals = [
            'хочу купить', 'готов заказать', 'какая цена', 'сколько стоит',
            'нужен бот', 'заказать crm', 'срочно нужно', 'бюджет',
            'покупаем', 'планируем купить', 'рассматриваем покупку',
            'crm система', 'автоматизация', 'интеграция'
        ]
        
        logger.info("SmartDialogueTracker инициализирован")

    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        """УМНАЯ обработка сообщения"""
        try:
            chat_id = update.effective_chat.id
            user = update.effective_user
            message = update.message
            
            if not user or not message or not message.text:
                return None
            
            # Добавляем сообщение в кэш
            self._add_message_to_cache(chat_id, {
                'user_id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'text': message.text,
                'timestamp': datetime.now(),
                'message_id': message.message_id,
                'reply_to_message_id': message.reply_to_message.message_id if message.reply_to_message else None,
                'reply_to_user_id': message.reply_to_message.from_user.id if message.reply_to_message else None
            })
            
            # Анализируем окно сообщений
            window = self._analyze_message_window(chat_id)
            
            logger.info(f"🔍 Анализ окна сообщений:")
            logger.info(f"    📊 Тип разговора: {window.conversation_type}")
            logger.info(f"    👥 Уникальных пользователей: {len(window.unique_users)}")
            logger.info(f"    💬 Сообщений в окне: {len(window.messages)}")
            logger.info(f"    🏢 Бизнес-сигналы: {window.has_business_signals}")
            logger.info(f"    ↩️ Есть ответы: {window.has_replies}")
            
            # Очищаем завершенные диалоги
            await self._cleanup_expired_dialogues()
            
            # Определяем стратегию обработки
            if window.conversation_type == "individual":
                logger.info("📱 Индивидуальное сообщение - обрабатываем отдельно")
                return None
            
            elif window.conversation_type in ["dialogue", "group_chat"]:
                # Ищем существующий диалог
                existing_dialogue = self._find_relevant_dialogue(chat_id, window)
                
                if existing_dialogue:
                    # Добавляем к существующему диалогу
                    await self._add_message_to_dialogue(existing_dialogue, user, message)
                    logger.info(f"📝 Сообщение добавлено к диалогу {existing_dialogue.dialogue_id}")
                    return existing_dialogue.dialogue_id
                else:
                    # Создаем новый диалог
                    new_dialogue = await self._create_smart_dialogue(chat_id, update.effective_chat.title, window)
                    logger.info(f"🆕 Создан умный диалог: {new_dialogue.dialogue_id}")
                    return new_dialogue.dialogue_id
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка умной обработки сообщения: {e}")
            return None

    def _add_message_to_cache(self, chat_id: int, message_data: Dict[str, Any]):
        """Добавление сообщения в кэш канала"""
        if chat_id not in self.channel_message_cache:
            self.channel_message_cache[chat_id] = []
        
        cache = self.channel_message_cache[chat_id]
        cache.append(message_data)
        
        # Ограничиваем размер кэша
        if len(cache) > self.message_window_size * 2:
            cache[:] = cache[-self.message_window_size:]

    def _analyze_message_window(self, chat_id: int) -> MessageWindow:
        """Анализ окна сообщений для определения типа разговора"""
        cache = self.channel_message_cache.get(chat_id, [])
        
        if not cache:
            return MessageWindow([], timedelta(0), set(), False, False, "individual")
        
        # Берем последние сообщения в пределах временного окна
        now = datetime.now()
        recent_messages = []
        
        for msg in reversed(cache):
            msg_time = msg['timestamp']
            if now - msg_time <= self.dialogue_detection_window:
                recent_messages.insert(0, msg)
            else:
                break
        
        if not recent_messages:
            return MessageWindow([], timedelta(0), set(), False, False, "individual")
        
        # Анализируем характеристики окна
        unique_users = set(msg['user_id'] for msg in recent_messages)
        has_replies = any(msg.get('reply_to_message_id') for msg in recent_messages)
        
        # Проверяем бизнес-сигналы
        all_text = ' '.join(msg['text'].lower() for msg in recent_messages)
        has_business_signals = any(signal in all_text for signal in self.business_signals)
        
        # Вычисляем временной размах
        if len(recent_messages) > 1:
            timespan = recent_messages[-1]['timestamp'] - recent_messages[0]['timestamp']
        else:
            timespan = timedelta(0)
        
        # Определяем тип разговора
        conversation_type = self._determine_conversation_type(recent_messages, unique_users, has_replies, timespan)
        
        return MessageWindow(
            messages=recent_messages,
            timespan=timespan,
            unique_users=unique_users,
            has_replies=has_replies,
            has_business_signals=has_business_signals,
            conversation_type=conversation_type
        )

    def _determine_conversation_type(self, messages: List[Dict], unique_users: set, has_replies: bool, timespan: timedelta) -> str:
        """Определение типа разговора на основе анализа"""
        
        num_users = len(unique_users)
        num_messages = len(messages)
        
        # Индивидуальные сообщения
        if num_users == 1:
            return "individual"
        
        # Анализируем паттерны взаимодействия
        user_message_counts = {}
        for msg in messages:
            user_id = msg['user_id']
            user_message_counts[user_id] = user_message_counts.get(user_id, 0) + 1
        
        # Проверяем на активное взаимодействие
        active_users = sum(1 for count in user_message_counts.values() if count >= 2)
        
        # Анализируем временные промежутки между сообщениями
        quick_responses = 0
        for i in range(1, len(messages)):
            prev_msg = messages[i-1]
            curr_msg = messages[i]
            
            time_diff = curr_msg['timestamp'] - prev_msg['timestamp']
            different_users = prev_msg['user_id'] != curr_msg['user_id']
            
            if different_users and time_diff <= timedelta(minutes=2):
                quick_responses += 1
        
        # Логика определения типа
        if num_users == 2:
            if has_replies or quick_responses >= 1 or active_users >= 2:
                return "dialogue"
            else:
                return "individual"
        
        elif num_users >= 3:
            if quick_responses >= 2 or active_users >= 3:
                return "group_chat"
            elif active_users >= 2:
                return "dialogue"
            else:
                return "individual"
        
        return "individual"

    def _find_relevant_dialogue(self, chat_id: int, window: MessageWindow) -> Optional[DialogueContext]:
        """Поиск релевантного диалога для окна сообщений"""
        
        for dialogue in self.active_dialogues.values():
            if dialogue.channel_id != chat_id:
                continue
            
            # Проверяем временную близость
            time_since_last_activity = datetime.now() - dialogue.last_activity
            if time_since_last_activity > self.dialogue_timeout:
                continue
            
            # Проверяем пересечение участников
            dialogue_participants = set(dialogue.participants.keys())
            window_participants = window.unique_users
            
            # Если есть пересечение участников - это продолжение диалога
            if dialogue_participants & window_participants:
                logger.info(f"🔗 Найден релевантный диалог {dialogue.dialogue_id}")
                return dialogue
        
        return None

    async def _create_smart_dialogue(self, chat_id: int, chat_title: str, window: MessageWindow) -> DialogueContext:
        """Создание диалога на основе анализа окна"""
        
        start_time = datetime.now()
        dialogue_id = self._generate_dialogue_id(chat_id, start_time)
        
        # Создаем участников из окна сообщений
        participants = {}
        for msg in window.messages:
            user_id = msg['user_id']
            if user_id not in participants:
                participants[user_id] = DialogueParticipant(
                    user_id=user_id,
                    username=msg.get('username'),
                    first_name=msg.get('first_name'),
                    last_name=msg.get('last_name'),
                    role="participant",
                    message_count=0,
                    first_message_time=msg['timestamp'],
                    last_message_time=msg['timestamp']
                )
        
        # Определяем роли участников
        self._assign_participant_roles(participants, window)
        
        # Создаем диалог
        dialogue = DialogueContext(
            dialogue_id=dialogue_id,
            channel_id=chat_id,
            channel_title=chat_title or f"Channel_{chat_id}",
            participants=participants,
            messages=[],
            start_time=start_time,
            last_activity=start_time,
            is_business_related=window.has_business_signals,
            dialogue_type=window.conversation_type
        )
        
        # Добавляем все сообщения из окна к диалогу
        for msg in window.messages:
            await self._add_cached_message_to_dialogue(dialogue, msg)
        
        self.active_dialogues[dialogue_id] = dialogue
        return dialogue

    def _assign_participant_roles(self, participants: Dict[int, DialogueParticipant], window: MessageWindow):
        """Назначение ролей участникам на основе анализа"""
        
        # Анализируем активность пользователей
        user_activity = {}
        for msg in window.messages:
            user_id = msg['user_id']
            if user_id not in user_activity:
                user_activity[user_id] = {
                    'message_count': 0,
                    'business_signals': 0,
                    'questions': 0,
                    'first_message_time': msg['timestamp']
                }
            
            activity = user_activity[user_id]
            activity['message_count'] += 1
            
            text_lower = msg['text'].lower()
            
            # Считаем бизнес-сигналы
            for signal in self.business_signals:
                if signal in text_lower:
                    activity['business_signals'] += 1
            
            # Считаем вопросы
            if '?' in msg['text'] or any(word in text_lower for word in ['как', 'что', 'где', 'когда']):
                activity['questions'] += 1
        
        # Назначаем роли
        sorted_users = sorted(user_activity.items(), key=lambda x: x[1]['message_count'], reverse=True)
        
        for i, (user_id, activity) in enumerate(sorted_users):
            participant = participants[user_id]
            
            if i == 0:  # Самый активный
                if activity['business_signals'] > 0:
                    participant.role = "initiator"
                else:
                    participant.role = "active_participant"
            elif activity['business_signals'] > 0:
                participant.role = "interested_participant"
            elif activity['questions'] > 0:
                participant.role = "inquirer"
            else:
                participant.role = "participant"

    async def _add_cached_message_to_dialogue(self, dialogue: DialogueContext, msg_data: Dict[str, Any]):
        """Добавление кэшированного сообщения к диалогу"""
        user_id = msg_data['user_id']
        
        # Обновляем участника
        if user_id in dialogue.participants:
            participant = dialogue.participants[user_id]
            participant.message_count += 1
            participant.last_message_time = msg_data['timestamp']
            
            # Анализируем покупательские сигналы
            buying_signals = self._extract_buying_signals(msg_data['text'])
            if buying_signals:
                participant.buying_signals_count += len(buying_signals)
        
        # Создаем сообщение
        dialogue_message = DialogueMessage(
            user_id=user_id,
            username=msg_data.get('username'),
            text=msg_data['text'],
            timestamp=msg_data['timestamp'],
            message_id=msg_data['message_id'],
            reply_to_message_id=msg_data.get('reply_to_message_id'),
            reply_to_user_id=msg_data.get('reply_to_user_id'),
            buying_signals=self._extract_buying_signals(msg_data['text']),
            urgency_level=self._detect_urgency(msg_data['text'])
        )
        
        dialogue.messages.append(dialogue_message)
        dialogue.last_activity = msg_data['timestamp']

    async def _add_message_to_dialogue(self, dialogue: DialogueContext, user: User, message):
        """Добавление нового сообщения к существующему диалогу"""
        current_time = datetime.now()
        
        # Обновляем или создаем участника
        if user.id not in dialogue.participants:
            participant = DialogueParticipant(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                role="new_participant",
                message_count=1,
                first_message_time=current_time,
                last_message_time=current_time
            )
            dialogue.participants[user.id] = participant
        else:
            participant = dialogue.participants[user.id]
            participant.message_count += 1
            participant.last_message_time = current_time
        
        # Анализируем покупательские сигналы
        buying_signals = self._extract_buying_signals(message.text)
        if buying_signals:
            participant.buying_signals_count += len(buying_signals)
        
        # Создаем сообщение
        dialogue_message = DialogueMessage(
            user_id=user.id,
            username=user.username,
            text=message.text,
            timestamp=current_time,
            message_id=message.message_id,
            reply_to_message_id=message.reply_to_message.message_id if message.reply_to_message else None,
            reply_to_user_id=message.reply_to_message.from_user.id if message.reply_to_message else None,
            buying_signals=buying_signals,
            urgency_level=self._detect_urgency(message.text)
        )
        
        dialogue.messages.append(dialogue_message)
        dialogue.last_activity = current_time
        
        # Обновляем метаданные
        if buying_signals or self._has_business_signals(message.text):
            dialogue.is_business_related = True

    def _generate_dialogue_id(self, channel_id: int, start_time: datetime) -> str:
        """Генерация уникального ID диалога"""
        return f"dialogue_{channel_id}_{start_time.strftime('%Y%m%d_%H%M%S')}"

    def _extract_buying_signals(self, text: str) -> List[str]:
        """Извлечение покупательских сигналов"""
        signals = []
        text_lower = text.lower()
        
        signal_patterns = {
            'price_inquiry': ['цена', 'стоимость', 'сколько стоит'],
            'purchase_intent': ['купить', 'заказать', 'хочу приобрести'],
            'urgency': ['срочно', 'быстро', 'сегодня'],
            'budget_discussion': ['бюджет', 'готов потратить'],
            'service_specific': ['нужен бот', 'crm система', 'автоматизация']
        }
        
        for category, patterns in signal_patterns.items():
            for pattern in patterns:
                if pattern in text_lower:
                    signals.append(f"{category}: {pattern}")
        
        return signals

    def _detect_urgency(self, text: str) -> str:
        """Определение срочности"""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ['срочно', 'сейчас', 'немедленно']):
            return "immediate"
        elif any(word in text_lower for word in ['быстро', 'сегодня', 'завтра']):
            return "high"
        elif any(word in text_lower for word in ['на днях', 'скоро']):
            return "medium"
        else:
            return "none"

    def _has_business_signals(self, text: str) -> bool:
        """Проверка наличия бизнес-сигналов"""
        text_lower = text.lower()
        return any(signal in text_lower for signal in self.business_signals)

    async def _cleanup_expired_dialogues(self):
        """Очистка завершенных диалогов"""
        current_time = datetime.now()
        expired_dialogues = []
        
        for dialogue_id, dialogue in self.active_dialogues.items():
            if current_time - dialogue.last_activity > self.dialogue_timeout:
                expired_dialogues.append(dialogue_id)
        
        for dialogue_id in expired_dialogues:
            completed_dialogue = self.active_dialogues.pop(dialogue_id)
            logger.info(f"🏁 Диалог завершен: {dialogue_id} ({len(completed_dialogue.messages)} сообщений, {len(completed_dialogue.participants)} участников)")

    def should_trigger_immediate_analysis(self, dialogue_id: str, message_text: str) -> bool:
        """Проверка СИЛЬНЫХ триггеров немедленного анализа"""
        text_lower = message_text.lower()
        
        # СИЛЬНЫЕ триггеры - реальные покупательские намерения
        strong_triggers = [
            # Прямые намерения покупки
            'хочу купить', 'готов заказать', 'готовы купить', 'планируем заказать',
            'нужно купить', 'будем покупать', 'закажем', 'приобретем',
            
            # Конкретные бюджеты и цены
            'бюджет', 'тысяч', 'миллион', 'рублей', 'долларов', 'евро',
            '100', '200', '500', '1000', '10000', 'ккк', 'млн', 'тыс',
            'готовы потратить', 'выделили', 'заложили в бюджет',
            
            # Прямые ценовые запросы
            'сколько стоит', 'какая цена', 'стоимость услуг', 'прайс', 'расценки',
            'во сколько обойдется', 'цена вопроса', 'стоимость проекта',
            
            # Срочность и конкретные сроки
            'срочно нужно', 'нужно сегодня', 'к понедельнику', 'до конца месяца',
            'в ближайшее время', 'как можно скорее', 'горящий проект',
            
            # Технические требования (конкретность)
            'интеграция с', 'подключение к', 'api', 'техзадание', 'требования',
            'функционал', 'возможности системы', 'технические характеристики',
            
            # Процессуальные сигналы
            'как заказать', 'оформить заявку', 'начать проект', 'подписать договор',
            'когда можем начать', 'сроки реализации', 'этапы работы'
        ]
        
        # Проверяем наличие сильных триггеров
        has_strong_trigger = any(trigger in text_lower for trigger in strong_triggers)
        
        if has_strong_trigger:
            logger.info(f"🔥 Обнаружен СИЛЬНЫЙ триггер в сообщении: '{message_text[:50]}...'")
        
        return has_strong_trigger

    def get_status(self) -> Dict[str, Any]:
        """Статус умного трекера"""
        return {
            'active_dialogues': len(self.active_dialogues),
            'min_participants': self.min_participants,
            'min_messages': self.min_messages,
            'dialogue_timeout_minutes': self.dialogue_timeout.total_seconds() / 60,
            'message_window_size': self.message_window_size,
            'detection_window_minutes': self.dialogue_detection_window.total_seconds() / 60,
            'cached_channels': len(self.channel_message_cache)
        }

# === АНАЛИЗАТОР ДИАЛОГОВ ===

class DialogueAnalyzer:
    """Анализатор диалогов"""
    
    def __init__(self, config):
        self.config = config
        self.claude_client = get_claude_client()
        logger.info("DialogueAnalyzer инициализирован")

    async def analyze_dialogue(self, dialogue: DialogueContext) -> Optional[DialogueAnalysisResult]:
        """Анализ диалога"""
        try:
            logger.info(f"🔍 Анализируем диалог {dialogue.dialogue_id}")
            
            if self.claude_client and self.claude_client.client:
                return await self._ai_dialogue_analysis(dialogue)
            else:
                logger.warning("Claude API недоступен, используем упрощенный анализ")
                return self._simple_dialogue_analysis(dialogue)
            
        except Exception as e:
            logger.error(f"Ошибка анализа диалога: {e}")
            return self._simple_dialogue_analysis(dialogue)

    async def _ai_dialogue_analysis(self, dialogue: DialogueContext) -> DialogueAnalysisResult:
        """AI анализ диалога - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        # Подготавливаем данные для анализа
        participants_info = []
        user_ids = []  # ИСПРАВЛЕНИЕ: создаем список user_id
        
        for user_id, participant in dialogue.participants.items():
            user_ids.append(user_id)  # ИСПРАВЛЕНИЕ: добавляем в список
            info = f"Участник {participant.first_name} (@{participant.username or 'без_username'}): {participant.message_count} сообщений, {participant.buying_signals_count} покупательских сигналов"
            participants_info.append(info)
        
        messages_history = []
        for msg in dialogue.messages:
            timestamp = msg.timestamp.strftime("%H:%M")
            username = msg.username or f"user_{msg.user_id}"
            messages_history.append(f"[{timestamp}] {username}: {msg.text}")
        
        prompt = f"""Проанализируй групповой диалог потенциальных клиентов.

КОНТЕКСТ:
- Канал: {dialogue.channel_title}
- Длительность: {(dialogue.last_activity - dialogue.start_time).total_seconds() / 60:.1f} мин
- Участников: {len(dialogue.participants)}
- Сообщений: {len(dialogue.messages)}

УЧАСТНИКИ:
{chr(10).join(participants_info)}

ДИАЛОГ:
{chr(10).join(messages_history)}

ВАЖНО: Обязательно включи в potential_leads ВСЕХ участников с их реальными user_id: {user_ids}

Верни ТОЛЬКО валидный JSON без дополнительного текста:
{{
    "is_valuable_dialogue": true/false,
    "confidence_score": число_0_100,
    "business_relevance_score": число_0_100,
    "potential_leads": [
        {{
            "user_id": конкретный_user_id_из_списка,
            "lead_probability": число_0_100,
            "lead_quality": "hot/warm/cold",
            "key_signals": ["список сигналов"],
            "role_in_decision": "decision_maker/influencer/observer/budget_holder"
        }}
    ],
    "dialogue_summary": "краткое описание",
    "key_insights": ["инсайты"],
    "recommended_actions": ["действия"],
    "next_best_action": "следующий шаг",
    "estimated_timeline": "сроки или null",
    "group_budget_estimate": "бюджет или null"
}}"""

        try:
            response = await asyncio.wait_for(
                self.claude_client.client.messages.create(
                    model=self.claude_client.model,
                    max_tokens=3000,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1
                ),
                timeout=20.0
            )
      
            # Парсим ответ
            response_text = response.content[0].text
            return self._parse_ai_response(response_text, dialogue)
     
        except Exception as e:
            logger.error(f"Ошибка AI анализа: {e}")
            return self._simple_dialogue_analysis(dialogue)

    def _parse_ai_response(self, response_text: str, dialogue: DialogueContext) -> DialogueAnalysisResult:
        """Парсинг AI ответа с детальным логированием"""
        try:
            import re
            logger.info(f"🔍 RAW AI RESPONSE: {response_text[:500]}...")  # ДОБАВИТЬ
            
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                logger.error("❌ JSON не найден в AI ответе")  # ДОБАВИТЬ
                raise ValueError("JSON не найден")
            
            json_text = json_match.group()
            logger.info(f"📄 EXTRACTED JSON: {json_text[:200]}...")  # ДОБАВИТЬ
            
            data = json.loads(json_text)
            logger.info(f"✅ PARSED DATA: {data}")  # ДОБАВИТЬ
            
            # ИСПРАВЛЕНИЕ: Правильно обрабатываем анализ участников
            participant_analysis = {}
            potential_leads = data.get('potential_leads', [])
            
            logger.info(f"👥 POTENTIAL LEADS FROM AI: {potential_leads}")  # ДОБАВИТЬ
            
            for lead_data in potential_leads:
                user_id = lead_data.get('user_id')
                if not user_id:
                    logger.warning(f"⚠️ Пропущен lead без user_id: {lead_data}")
                    continue
                    
                # Обновляем данные участника
                if user_id in dialogue.participants:
                    participant = dialogue.participants[user_id]
                    lead_prob = lead_data.get('lead_probability', 0)
                    participant.lead_probability = lead_prob / 100.0
                    
                    participant_analysis[user_id] = {
                        'lead_probability': lead_prob,
                        'lead_quality': lead_data.get('lead_quality', 'cold'),
                        'key_signals': lead_data.get('key_signals', []),
                        'role_in_decision': lead_data.get('role_in_decision', 'observer')
                    }
                    
                    logger.info(f"✅ Участник {user_id} обновлен: {lead_prob}% ({lead_data.get('role_in_decision')})")
                else:
                    logger.warning(f"⚠️ User {user_id} не найден среди участников диалога")
            
            result = DialogueAnalysisResult(
                dialogue_id=dialogue.dialogue_id,
                is_valuable_dialogue=data.get('is_valuable_dialogue', False),
                confidence_score=data.get('confidence_score', 0),
                potential_leads=potential_leads,
                business_relevance_score=data.get('business_relevance_score', 0),
                dialogue_summary=data.get('dialogue_summary', ''),
                key_insights=data.get('key_insights', []),
                recommended_actions=data.get('recommended_actions', []),
                next_best_action=data.get('next_best_action', ''),
                estimated_timeline=data.get('estimated_timeline'),
                group_budget_estimate=data.get('group_budget_estimate'),
                participant_analysis=participant_analysis
            )
            
            logger.info(f"🎯 FINAL ANALYSIS RESULT: valuable={result.is_valuable_dialogue}, leads_count={len(result.potential_leads)}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга AI ответа: {e}")
            logger.error(f"📄 Проблемный текст: {response_text[:200]}...")
            return self._simple_dialogue_analysis(dialogue)

    def _simple_dialogue_analysis(self, dialogue: DialogueContext) -> DialogueAnalysisResult:
        """Усиленный упрощенный анализ без AI - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        potential_leads = []
        participant_analysis = {}
        
        logger.info("🔧 Используем УЛУЧШЕННЫЙ простой анализ диалога")
        
        for user_id, participant in dialogue.participants.items():
            # Анализируем сообщения участника
            user_messages = [msg for msg in dialogue.messages if msg.user_id == user_id]
            
            # Считаем покупательские сигналы
            buying_signals = 0
            strong_signals = []
            
            for msg in user_messages:
                text_lower = msg.text.lower()
                
                # УЛЬТРА-СИЛЬНЫЕ сигналы
                if any(signal in text_lower for signal in ['хочу купить', 'готов заказать', 'нужно купить']):
                    buying_signals += 5  # УВЕЛИЧИЛИ вес
                    strong_signals.append('direct_purchase_intent')
                
                # Бюджетные запросы
                if any(signal in text_lower for signal in ['какой бюджет', 'сколько стоит', 'бюджет']):
                    buying_signals += 4  # УВЕЛИЧИЛИ вес
                    strong_signals.append('budget_inquiry')
                
                # Ценовые запросы
                if any(signal in text_lower for signal in ['цена', 'стоимость']):
                    buying_signals += 3
                    strong_signals.append('price_inquiry')
                
                # Технические запросы
                if any(signal in text_lower for signal in ['интеграция', 'тг-бот', 'приложением']):
                    buying_signals += 2
                    strong_signals.append('technical_interest')
            
            # Вычисляем итоговый скор
            message_count_factor = min(participant.message_count * 15, 35)  # УВЕЛИЧИЛИ вес
            buying_signals_factor = min(buying_signals * 15, 70)  # УВЕЛИЧИЛИ вес
            
            score = message_count_factor + buying_signals_factor
            
            # Определяем роль с учетом контекста сообщений
            if buying_signals >= 5:
                role = 'decision_maker'
                quality = 'hot'
                score = max(score, 85)  # Минимум для прямых намерений
            elif any('бюджет' in msg.text.lower() for msg in user_messages):
                role = 'budget_holder'
                quality = 'warm'
                score = max(score, 70)  # Минимум для бюджетных вопросов
            elif buying_signals >= 2:
                role = 'interested_participant'
                quality = 'warm'
                score = max(score, 60)
            elif buying_signals >= 1:
                role = 'inquirer'
                quality = 'cold'
                score = max(score, 40)
            else:
                role = 'observer'
                quality = 'cold'
                score = max(score, 25)  # Минимум для участников диалога
            
            # Обновляем вероятность участника
            participant.lead_probability = score / 100.0
            
            # ИСПРАВЛЕНИЕ: создаем лидов для ВСЕХ участников выше порога
            if score >= 35:  # ПОНИЗИЛИ порог с 40 до 35
                potential_leads.append({
                    'user_id': user_id,
                    'lead_probability': score,
                    'lead_quality': quality,
                    'key_signals': strong_signals,
                    'role_in_decision': role
                })
                
                participant_analysis[user_id] = {
                    'lead_probability': score,
                    'lead_quality': quality,
                    'key_signals': strong_signals,
                    'role_in_decision': role
                }
                
                logger.info(f"✅ УЛУЧШЕННЫЙ АНАЛИЗ - Участник {participant.display_name}: {score}% ({role})")
        
        logger.info(f"🎯 УЛУЧШЕННЫЙ АНАЛИЗ ЗАВЕРШЕН: найдено {len(potential_leads)} лидов")
        
        return DialogueAnalysisResult(
            dialogue_id=dialogue.dialogue_id,
            is_valuable_dialogue=len(potential_leads) > 0,
            confidence_score=85 if any(lead['lead_probability'] >= 70 for lead in potential_leads) else 65,
            potential_leads=potential_leads,
            business_relevance_score=90 if dialogue.is_business_related else 30,
            dialogue_summary=f"Диалог с {len(dialogue.participants)} участниками в {dialogue.channel_title}",
            key_insights=[f"Обнаружено {len(potential_leads)} потенциальных лидов", "Выявлены прямые покупательские намерения"],
            recommended_actions=["Немедленно связаться с decision_maker", "Уточнить бюджет и требования"],
            next_best_action="Связаться с главным лидом в течение 15 минут",
            estimated_timeline="немедленно", 
            group_budget_estimate="требует уточнения у decision_maker",
            participant_analysis=participant_analysis
        )
# === ГЛАВНЫЙ ПАРСЕР С УМНЫМ АНАЛИЗОМ ===

class UnifiedAIParser:
    """Объединенный AI парсер с умным анализом диалогов"""
    
    def __init__(self, config):
        self.config = config
        self.parsing_config = config.get('parsing', {})
        
        # Основные настройки
        self.enabled = self.parsing_config.get('enabled', True)
        self.channels = self._parse_channels()
        self.min_confidence_score = self.parsing_config.get('min_confidence_score', 70)
        
        # Компоненты с умным трекером
        self.dialogue_analysis_enabled = self.parsing_config.get('dialogue_analysis_enabled', True)
        self.dialogue_tracker = SmartDialogueTracker(config) if self.dialogue_analysis_enabled else None
        self.dialogue_analyzer = DialogueAnalyzer(config) if self.dialogue_analysis_enabled else None
        
        # Индивидуальный анализ
        self.user_contexts: Dict[int, UserContext] = {}
        self.processed_leads: Dict[int, datetime] = {}
        
        # Контроль анализов - более гибкий
        self.dialogue_analysis_history: Dict[str, List[datetime]] = {}
        self.analysis_cooldown = timedelta(seconds=30)  # Короткий cooldown для сильных триггеров

        logger.info(f"UnifiedAIParser инициализирован:")
        logger.info(f"  - Каналов: {len(self.channels)}")
        logger.info(f"  - Умный анализ диалогов: {self.dialogue_analysis_enabled}")
        logger.info(f"  - Мин. уверенность: {self.min_confidence_score}%")
        logger.info(f"  - Строгие критерии уведомлений: confidence≥70%, business≥75%, leads≥60%")
        logger.info(f"  - Ультра-умная система cooldown с исключениями")

    def _parse_channels(self) -> List[str]:
        """Парсинг каналов"""
        channels_raw = self.parsing_config.get('channels', [])
        if isinstance(channels_raw, list):
            return [str(ch) for ch in channels_raw]
        elif isinstance(channels_raw, (str, int)):
            return [str(channels_raw)]
        return []

    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Главная функция обработки сообщения с умным анализом"""
        try:
            if not self.enabled:
                return
            
            chat_id = update.effective_chat.id
            user = update.effective_user
            message = update.message
            
            if not user or not message or not message.text:
                return
            
            logger.info(f"🔍 ИСПРАВЛЕННАЯ обработка сообщения:")
            logger.info(f"    👤 Пользователь: {user.first_name} (@{user.username})")
            logger.info(f"    💬 Текст: '{message.text[:50]}...'")
            logger.info(f"    📍 Канал: {chat_id}")
            
            if not self.is_channel_monitored(chat_id, update.effective_chat.username):
                logger.info("⏭️ Канал не отслеживается")
                return
            
            # Умный анализ диалогов
            dialogue_processed = False
            
            if self.dialogue_analysis_enabled and self.dialogue_tracker:
                dialogue_id = await self.dialogue_tracker.process_message(update, context)
                
                if dialogue_id:
                    logger.info(f"📝 Сообщение обработано в диалоге: {dialogue_id}")
                    dialogue_processed = True  # ИСПРАВЛЕНИЕ: Сразу помечаем как обработанное
                    
                    # Проверяем, нужен ли анализ с учетом истории
                    if await self._should_analyze_dialogue_smart(dialogue_id, message.text):
                        logger.info(f"🔥 НЕМЕДЛЕННЫЙ анализ диалога {dialogue_id}!")
                        await self._analyze_dialogue_immediately(dialogue_id, context)
                    else:
                        logger.info(f"⏸️ Анализ диалога {dialogue_id} отложен (недавно анализировался)")
            
            # Индивидуальный анализ ТОЛЬКО если сообщение НЕ в диалоге
            if not dialogue_processed:
                logger.info("👤 Запускаем индивидуальный анализ (сообщение вне диалога)")
                await self._process_individual_message(update, context)
            else:
                logger.info("✅ Сообщение обработано в рамках диалога, индивидуальный анализ не нужен")
            
        except Exception as e:
            logger.error(f"❌ Ошибка в исправленном парсере: {e}")

    # ИСПРАВЛЕНИЕ: Добавляем недостающий метод
    async def _process_individual_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка индивидуального сообщения"""
        try:
            user = update.effective_user
            message = update.message
            
            # Создаем объекты для анализа
            participant = ParticipantInfo(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
            
            message_info = MessageInfo(
                text=message.text,
                timestamp=datetime.now(),
                channel_id=update.effective_chat.id,
                user_id=user.id
            )
            
            # Анализируем сообщение
            await self._analyze_individual_message(participant, message_info, context)
            
        except Exception as e:
            logger.error(f"Ошибка обработки индивидуального сообщения: {e}")

    async def _analyze_individual_message(self, participant: ParticipantInfo, message: MessageInfo, context: ContextTypes.DEFAULT_TYPE):
        """Анализ индивидуального сообщения"""
        try:
            # Проверяем ультра-сильные триггеры
            if self._check_ultra_strong_triggers(message.text):
                logger.info(f"🔥🔥 УЛЬТРА-СИЛЬНЫЙ триггер в индивидуальном сообщении от {participant.display_name}")
                
                # Создаем лид немедленно
                lead_data = {
                    'lead_probability': 95,
                    'lead_quality': 'hot',
                    'key_signals': ['direct_purchase_intent'],
                    'participant_role': 'client'
                }
                
                lead = await self._create_individual_lead(participant, message, lead_data)
                if lead:
                    # Отправляем срочное уведомление
                    await self._notify_admins_about_individual_ultra_trigger(context, participant, message, lead_data)
                
                return
            
            # Обычный анализ индивидуального сообщения
            if self._contains_business_signals(message.text):
                logger.info(f"💼 Бизнес-сигналы в сообщении от {participant.display_name}")
                
                lead_data = {
                    'lead_probability': 70,
                    'lead_quality': 'warm',
                    'key_signals': ['business_interest'],
                    'participant_role': 'prospect'
                }
                
                await self._create_individual_lead(participant, message, lead_data)
            
        except Exception as e:
            logger.error(f"Ошибка анализа индивидуального сообщения: {e}")


    # ИСПРАВЛЕНИЕ: Добавляем недостающий метод
    def _contains_business_signals(self, text: str) -> bool:
        """Проверка наличия бизнес-сигналов в тексте"""
        business_signals = [
            'хочу купить', 'готов заказать', 'какая цена', 'сколько стоит',
            'нужен бот', 'заказать crm', 'срочно нужно', 'бюджет',
            'покупаем', 'планируем купить', 'рассматриваем покупку',
            'crm система', 'автоматизация', 'интеграция'
        ]
        
        text_lower = text.lower()
        return any(signal in text_lower for signal in business_signals)

    # ИСПРАВЛЕНИЕ: Добавляем недостающий метод
    async def _create_individual_lead(self, participant: ParticipantInfo, message: MessageInfo, analysis_result) -> Optional[Lead]:
        """Создание индивидуального лида"""
        try:
            # Простой анализ для определения скора
            score = 50  # Базовый скор
            if self._contains_business_signals(message.text):
                score += 30
            if self._check_ultra_strong_triggers(message.text):
                score = 90
            
            lead = Lead(
                telegram_id=participant.user_id,
                username=participant.username,
                first_name=participant.first_name,
                last_name=participant.last_name,
                source_channel=f"Channel_{message.channel_id}",
                interest_score=score,
                message_text=message.text,
                message_date=message.timestamp,
                lead_quality="hot" if score >= 80 else "warm" if score >= 60 else "cold",
                urgency_level="high" if self._check_ultra_strong_triggers(message.text) else "medium",
                notes="Индивидуальное сообщение с покупательскими сигналами"
            )
            
            await create_lead(lead)
            logger.info(f"✅ Индивидуальный лид создан: {participant.display_name}")
            return lead
            
        except Exception as e:
            logger.error(f"Ошибка создания индивидуального лида: {e}")
            return None

    async def _should_analyze_dialogue_smart(self, dialogue_id: str, message_text: str) -> bool:
        """Ультра-умная проверка необходимости анализа диалога"""
        
        # Проверяем готовность диалога
        if dialogue_id not in self.dialogue_tracker.active_dialogues:
            return False
        
        dialogue = self.dialogue_tracker.active_dialogues[dialogue_id]
        
        # Условия для анализа:
        # 1. Достаточно участников и сообщений
        basic_ready = (len(dialogue.participants) >= 2 and len(dialogue.messages) >= 2)
        
        # 2. Проверяем типы триггеров
        immediate_trigger = self.dialogue_tracker.should_trigger_immediate_analysis(dialogue_id, message_text)
        ultra_strong_trigger = self._check_ultra_strong_triggers(message_text)
        
        # 3. Накопилось МНОГО активности 
        last_analysis_count = len(self.dialogue_analysis_history.get(dialogue_id, []))
        significant_activity = len(dialogue.messages) > (last_analysis_count + 1) * 5  # Каждые 5 новых сообщений
        
        # 4. Проверяем cooldown с исключениями
        now = datetime.now()
        cooldown_blocks = False
        
        if dialogue_id in self.dialogue_analysis_history:
            last_analyses = self.dialogue_analysis_history[dialogue_id]
            # Убираем старые анализы (старше 1 часа)
            last_analyses[:] = [analysis_time for analysis_time in last_analyses 
                            if now - analysis_time < timedelta(hours=1)]
            
            if last_analyses:
                time_since_last = now - last_analyses[-1]
                
                # УЛЬТРА-СИЛЬНЫЕ триггеры игнорируют cooldown
                if ultra_strong_trigger:
                    logger.info(f"🔥 УЛЬТРА-СИЛЬНЫЙ триггер - игнорируем cooldown!")
                    cooldown_blocks = False
                # Обычные сильные триггеры проверяют короткий cooldown
                elif immediate_trigger and time_since_last < timedelta(seconds=30):
                    cooldown_blocks = True
                # Накопление активности проверяет длинный cooldown  
                elif significant_activity and time_since_last < timedelta(minutes=3):
                    cooldown_blocks = True
        
        # Принимаем решение
        should_analyze = basic_ready and not cooldown_blocks and (
            ultra_strong_trigger or immediate_trigger or significant_activity
        )
        
        if should_analyze:
            logger.info(f"🎯 Анализ диалога {dialogue_id} одобрен:")
            logger.info(f"    ✅ Базовая готовность: {basic_ready}")
            logger.info(f"    🔥🔥 Ультра-сильный триггер: {ultra_strong_trigger}")
            logger.info(f"    🔥 Сильный триггер: {immediate_trigger}")
            logger.info(f"    📈 Значительная активность: {significant_activity}")
            logger.info(f"    ⏰ Cooldown блокирует: {cooldown_blocks}")
        else:
            reason = "cooldown" if cooldown_blocks else "нет триггеров"
            logger.info(f"⏸️ Анализ диалога {dialogue_id} отложен ({reason})")
        
        return should_analyze

    def _check_ultra_strong_triggers(self, message_text: str) -> bool:
        """Проверка УЛЬТРА-СИЛЬНЫХ триггеров, которые игнорируют cooldown"""
        text_lower = message_text.lower()
        
        # УЛЬТРА-СИЛЬНЫЕ триггеры - конкретные покупательские намерения с деньгами
        ultra_triggers = [
            # Конкретные бюджеты с намерениями
            ('ккк', ['купить', 'заказать', 'нужно', 'планируем']),
            ('миллион', ['купить', 'заказать', 'бюджет', 'готовы']),
            ('тысяч', ['купить', 'заказать', 'бюджет', 'готовы']),
            ('млн', ['купить', 'заказать', 'бюджет', 'готовы']),
            
            # Очень конкретные суммы
            ('100000', ['рублей', 'долларов', 'евро']),
            ('500000', ['рублей', 'долларов', 'евро']),
            ('1000000', ['рублей', 'долларов', 'евро']),
            
            # Прямые покупательские команды
            ('готов заказать', []),
            ('готовы купить', []),
            ('нужно купить', []),
            ('планируем заказать', []),
            ('хочу оформить заказ', []),
            ('когда можем начать проект', []),
            
            # Техзадание и договоры
            ('есть техзадание', []),
            ('готовы подписать договор', []),
            ('когда подписываем', []),
            ('отправьте договор', []),
        ]
        
        for trigger in ultra_triggers:
            if isinstance(trigger, tuple):
                main_trigger, context_words = trigger
                if main_trigger in text_lower:
                    # Если нет контекстных слов, триггер срабатывает сразу
                    if not context_words:
                        logger.info(f"🔥🔥 УЛЬТРА-СИЛЬНЫЙ триггер: '{main_trigger}' в сообщении")
                        return True
                    # Если есть контекстные слова, проверяем их наличие
                    elif any(word in text_lower for word in context_words):
                        logger.info(f"🔥🔥 УЛЬТРА-СИЛЬНЫЙ триггер: '{main_trigger}' + контекст в сообщении")
                        return True
            else:
                if trigger in text_lower:
                    logger.info(f"🔥🔥 УЛЬТРА-СИЛЬНЫЙ триггер: '{trigger}' в сообщении")
                    return True
        
        return False

    async def _analyze_dialogue_immediately(self, dialogue_id: str, context: ContextTypes.DEFAULT_TYPE):
        """Немедленный анализ диалога с защитой от дублирования"""
        try:
            if dialogue_id not in self.dialogue_tracker.active_dialogues:
                return
            
            dialogue = self.dialogue_tracker.active_dialogues[dialogue_id]
            logger.info(f"🔥 НЕМЕДЛЕННЫЙ анализ диалога: {dialogue_id}")
            
            # Записываем время анализа
            now = datetime.now()
            if dialogue_id not in self.dialogue_analysis_history:
                self.dialogue_analysis_history[dialogue_id] = []
            self.dialogue_analysis_history[dialogue_id].append(now)
            
            # Анализируем
            analysis_result = await self.dialogue_analyzer.analyze_dialogue(dialogue)
            
            if analysis_result:
                if analysis_result.is_valuable_dialogue:
                    logger.info(f"💎 Ценный диалог: {dialogue_id}")
                    await self._process_dialogue_result(dialogue, analysis_result, context)
                else:
                    logger.info(f"📊 Диалог проанализирован: {analysis_result.confidence_score}%")
            
        except Exception as e:
            logger.error(f"Ошибка анализа диалога: {e}")

    async def _process_dialogue_result(self, dialogue: DialogueContext, 
                                    analysis: DialogueAnalysisResult, 
                                    context: ContextTypes.DEFAULT_TYPE):
        """Обработка результатов анализа диалога с гибкими критериями"""
        try:
            logger.info(f"📊 Результат анализа диалога {dialogue.dialogue_id}:")
            logger.info(f"    📊 Уверенность: {analysis.confidence_score}%")
            logger.info(f"    🏢 Бизнес-релевантность: {analysis.business_relevance_score}%")
            logger.info(f"    👥 Потенциальных лидов: {len(analysis.potential_leads)}")
            
            # Проверяем есть ли в диалоге ультра-сильные триггеры
            has_ultra_triggers = any(
                self._check_ultra_strong_triggers(msg.text) 
                for msg in dialogue.messages[-5:]  # Проверяем последние 5 сообщений
            )
            
            if has_ultra_triggers:
                # Пониженные требования для диалогов с ультра-триггерами
                min_confidence = 60  # Было 70%
                min_business_relevance = 65  # Было 75%
                min_lead_probability = 50  # Было 60%
                logger.info(f"🔥🔥 Обнаружены ультра-триггеры - применяем мягкие критерии")
            else:
                # Стандартные строгие критерии
                min_confidence = 70
                min_business_relevance = 75
                min_lead_probability = 60
                logger.info(f"📊 Применяем стандартные строгие критерии")
            
            # Проверяем есть ли участники с достаточной вероятностью
            high_probability_leads = [
                lead for lead in analysis.potential_leads 
                if lead.get('lead_probability', 0) >= min_lead_probability
            ]
            
            # Условия для отправки уведомления:
            should_notify = (
                analysis.confidence_score >= min_confidence and
                analysis.business_relevance_score >= min_business_relevance and
                len(high_probability_leads) > 0
            )
            
            if should_notify:
                logger.info(f"💎 ЦЕННЫЙ диалог обнаружен: {dialogue.dialogue_id}")
                
                # Создаем лиды только для участников с высокой вероятностью
                created_leads = []
                for lead_data in high_probability_leads:
                    user_id = lead_data['user_id']
                    participant = dialogue.participants.get(user_id)
                    
                    if participant:
                        lead = await self._create_dialogue_lead(participant, dialogue, lead_data, analysis)
                        if lead:
                            created_leads.append((participant, lead_data))
                
                # Уведомляем админов о ЦЕННЫХ диалогах
                await self._notify_admins_about_dialogue(context, dialogue, analysis, created_leads)
                
            else:
                logger.info(f"📋 Диалог не достигает критериев уведомления:")
                logger.info(f"    📊 Уверенность: {analysis.confidence_score}% (нужно ≥{min_confidence}%)")
                logger.info(f"    🏢 Бизнес-релевантность: {analysis.business_relevance_score}% (нужно ≥{min_business_relevance}%)")
                logger.info(f"    🎯 Лидов с высокой вероятностью: {len(high_probability_leads)} (нужно ≥1)")
                logger.info(f"    💡 Продолжаем мониторинг диалога...")
            
        except Exception as e:
            logger.error(f"Ошибка обработки результатов: {e}")

    async def _create_dialogue_lead(self, participant, dialogue, lead_data, analysis):
        """Создание лида из участника диалога"""
        try:
            participant_messages = [
                msg.text for msg in dialogue.messages 
                if msg.user_id == participant.user_id
            ]
            
            lead = Lead(
                telegram_id=participant.user_id,
                username=participant.username,
                first_name=participant.first_name,
                last_name=participant.last_name,
                source_channel=f"{dialogue.channel_title} (диалог)",
                interest_score=lead_data['lead_probability'],
                message_text=" | ".join(participant_messages[-3:]),  # Последние 3 сообщения
                message_date=dialogue.last_activity,
                lead_quality=lead_data['lead_quality'],
                interests=json.dumps(lead_data.get('key_signals', []), ensure_ascii=False),
                buying_signals=json.dumps(lead_data.get('key_signals', []), ensure_ascii=False),
                urgency_level="medium",
                estimated_budget=analysis.group_budget_estimate,
                timeline=analysis.estimated_timeline,
                notes=f"Диалог {dialogue.dialogue_id}. Роль: {lead_data.get('role_in_decision', 'участник')}"
            )
            
            await create_lead(lead)
            logger.info(f"✅ Лид создан: {participant.first_name}")
            return lead
            
        except Exception as e:
            logger.error(f"Ошибка создания лида: {e}")
            return None

    async def _notify_admins_about_dialogue(self, context: ContextTypes.DEFAULT_TYPE, 
                                        dialogue: DialogueContext, 
                                        analysis: DialogueAnalysisResult,
                                        created_leads: List[Tuple]):
        """ИСПРАВЛЕННОЕ уведомление админов о ценном диалоге"""
        try:
            participants_info = []
            
            logger.info(f"📊 ФОРМИРУЕМ УВЕДОМЛЕНИЕ:")
            logger.info(f"  - created_leads: {len(created_leads)}")
            logger.info(f"  - analysis.potential_leads: {len(analysis.potential_leads)}")
            logger.info(f"  - participant_analysis: {len(analysis.participant_analysis)}")
            
            # ИСПРАВЛЕНИЕ: Используем participant_analysis вместо potential_leads
            if analysis.participant_analysis:
                for user_id, analysis_data in analysis.participant_analysis.items():
                    participant = dialogue.participants.get(user_id)
                    if participant:
                        lead_probability = analysis_data.get('lead_probability', 0)
                        role = analysis_data.get('role_in_decision', 'observer')
                        
                        participants_info.append(
                            f"👤 {participant.display_name} (@{participant.username or 'no_username'}) - "
                            f"{lead_probability}% ({role})"
                        )
                        
                        logger.info(f"✅ Добавлен участник из analysis: {participant.display_name} - {lead_probability}%")
            
            # Если нет данных из анализа, используем potential_leads
            elif analysis.potential_leads:
                for lead_data in analysis.potential_leads:
                    user_id = lead_data.get('user_id')
                    participant = dialogue.participants.get(user_id)
                    if participant:
                        lead_probability = lead_data.get('lead_probability', 0)
                        role = lead_data.get('role_in_decision', 'observer')
                        
                        participants_info.append(
                            f"👤 {participant.display_name} (@{participant.username or 'no_username'}) - "
                            f"{lead_probability}% ({role})"
                        )
                        
                        logger.info(f"✅ Добавлен участник из potential_leads: {participant.display_name} - {lead_probability}%")
            
            # ТОЛЬКО ЕСЛИ НЕТ НИКАКИХ ДАННЫХ - fallback на 0%
            else:
                logger.warning("⚠️ НЕТ ДАННЫХ АНАЛИЗА - используем fallback")
                for user_id, participant in dialogue.participants.items():
                    participants_info.append(
                        f"👤 {participant.display_name} (@{participant.username or 'no_username'}) - "
                        f"0% (observer)"
                    )
            
            participants_text = "\n".join(participants_info)
            
            # Формируем историю диалога
            dialogue_history = []
            for msg in dialogue.messages:
                timestamp = msg.timestamp.strftime("%H:%M")
                username = msg.username or "no_username"
                text = msg.text[:50] + "..." if len(msg.text) > 50 else msg.text
                dialogue_history.append(f"[{timestamp}] {username}: {text}")
            
            history_text = "\n".join(dialogue_history)
            
            # Определяем временные рамки и бюджет
            estimated_budget = analysis.group_budget_estimate or "не определен"
            timeline = analysis.estimated_timeline or "не определены"
            
            # Получаем название канала
            try:
                chat = await context.bot.get_chat(dialogue.channel_id)
                channel_name = chat.title or f"ID: {dialogue.channel_id}"
            except:
                channel_name = f"ID: {dialogue.channel_id}"
            
            # Формируем сообщение
            duration_minutes = (dialogue.messages[-1].timestamp - dialogue.messages[0].timestamp).seconds // 60
            
            message = f"""🔥 ЦЕННЫЙ ДИАЛОГ

🤖 УМНЫЙ AI АНАЛИЗ ДИАЛОГА
📺 Канал: {channel_name}
🕐 Длительность: {duration_minutes} мин
👥 Участников: {len(dialogue.participants)}
💬 Сообщений: {len(dialogue.messages)}
📊 Уверенность: {analysis.confidence_score}%
🏢 Бизнес-релевантность: {analysis.business_relevance_score}%

📋 Суть диалога:
{analysis.dialogue_summary}

👥 Анализ участников:
{participants_text}

💡 Ключевые инсайты:
{chr(10).join(f'• {insight}' for insight in analysis.key_insights)}

🎯 Рекомендации:
{chr(10).join(f'• {rec}' for rec in analysis.recommended_actions)}

⚡️ Следующий шаг: {analysis.next_best_action}
📅 Временные рамки: {timeline}
💰 Бюджет группы: {estimated_budget}

📝 История диалога:
{history_text}"""

            # Отправляем всем админам
            admin_ids = self.config.get('bot', {}).get('admin_ids', [])
            
            for admin_id in admin_ids:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=message,
                        parse_mode=None
                    )
                    logger.info(f"✅ Уведомление о диалоге отправлено админу {admin_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки уведомления админу {admin_id}: {e}")
            
            logger.info(f"✅ Уведомления о диалоге отправлены")
            
        except Exception as e:
            logger.error(f"❌ Ошибка уведомления админов о диалоге: {e}")

    async def _notify_admins_about_individual_ultra_trigger(self, context: ContextTypes.DEFAULT_TYPE,
                                                        participant: ParticipantInfo,
                                                        message: MessageInfo,
                                                        lead_data: dict):
        """Уведомляем админов об individual сообщении с ультра-триггером"""
        try:
            # Получаем название канала
            try:
                chat = await context.bot.get_chat(message.channel_id)
                channel_name = chat.title or f"ID: {message.channel_id}"
            except:
                channel_name = f"ID: {message.channel_id}"
            
            # Формируем информацию об участнике
            lead_probability = lead_data.get('lead_probability', 90)
            role = lead_data.get('participant_role', 'client')
            
            participant_info = f"👤 {participant.display_name} (@{participant.username or 'no_username'}) - {lead_probability}% ({role})"
            
            # Определяем тип покупательского намерения
            text_lower = message.text.lower()
            if 'купить' in text_lower:
                intent_type = "ГОТОВ КУПИТЬ"
            elif 'заказать' in text_lower:
                intent_type = "ГОТОВ ЗАКАЗАТЬ"  
            elif 'техзадание' in text_lower:
                intent_type = "ЕСТЬ ТЕХЗАДАНИЕ"
            elif 'договор' in text_lower:
                intent_type = "ГОТОВ К ДОГОВОРУ"
            else:
                intent_type = "ПОКУПАТЕЛЬСКОЕ НАМЕРЕНИЕ"
            
            # Формируем рекомендации на основе типа намерения
            if 'купить' in text_lower or 'заказать' in text_lower:
                recommendations = [
                    "Немедленно связаться с клиентом",
                    "Уточнить бюджет и требования",
                    "Подготовить коммерческое предложение",
                    "Запросить контактные данные для связи"
                ]
                next_step = "Позвонить клиенту в течение 15 минут"
            elif 'техзадание' in text_lower:
                recommendations = [
                    "Запросить техническое задание",
                    "Провести техническую консультацию", 
                    "Подготовить план реализации",
                    "Оценить сроки и стоимость"
                ]
                next_step = "Получить техзадание и оценить проект"
            else:
                recommendations = [
                    "Выяснить детали потребности",
                    "Предложить консультацию",
                    "Подготовить презентацию решения"
                ]
                next_step = "Связаться для уточнения деталей"
            
            # Формируем сообщение
            timestamp = message.timestamp.strftime("%H:%M")
            
            message_text = f"""🔥 СРОЧНО: {intent_type}!

🤖 УЛЬТРА-СИЛЬНЫЙ ПОКУПАТЕЛЬСКИЙ СИГНАЛ
📺 Канал: {channel_name}
🕐 Время: {timestamp}
👤 От: {participant.display_name} (@{participant.username or 'no_username'})
💬 Сообщение: "{message.text}"

📊 Уверенность: 95% (ультра-триггер)
🏢 Бизнес-релевантность: 95%

👥 Анализ участника:
{participant_info}

💡 Покупательские сигналы:
• Прямое выражение намерения купить/заказать
• Конкретная потребность указана
• Готовность к действию

🎯 СРОЧНЫЕ действия:
{chr(10).join(f'• {rec}' for rec in recommendations)}

⚡️ НЕМЕДЛЕННО: {next_step}
💰 Потенциальный бюджет: требует уточнения
📅 Временные рамки: срочно (клиент готов)

🚨 ЭТО ГОТОВЫЙ ПОКУПАТЕЛЬ - РЕАГИРУЙТЕ МГНОВЕННО!
📞 Рекомендуется связаться в течение 15 минут!"""

            # Отправляем всем админам
            admin_ids = self.config.get('bot', {}).get('admin_ids', [])
            
            for admin_id in admin_ids:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=message_text,
                        parse_mode=None
                    )
                    logger.info(f"🚨 СРОЧНОЕ уведомление отправлено админу {admin_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки СРОЧНОГО уведомления админу {admin_id}: {e}")
            
            logger.info(f"🚨 СРОЧНЫЕ уведомления об ультра-триггере отправлены")
            
        except Exception as e:
            logger.error(f"❌ Ошибка СРОЧНОГО уведомления админов: {e}")

    def is_channel_monitored(self, chat_id: int, chat_username: str = None) -> bool:
        """Проверка мониторинга канала"""
        if not self.enabled:
            return False
        
        if str(chat_id) in self.channels:
            return True
        
        if chat_username:
            username_variants = [f"@{chat_username}", chat_username]
            for variant in username_variants:
                if variant in self.channels:
                    return True
        
        return False

    async def _notify_admins_about_individual_ultra_trigger(self, context: ContextTypes.DEFAULT_TYPE,
                                                        participant: ParticipantInfo,
                                                        message: MessageInfo,
                                                        lead_data: dict):
        """Уведомление админов об индивидуальном сообщении с ультра-триггером"""
        try:
            # Получаем название канала
            try:
                chat = await context.bot.get_chat(message.channel_id)
                channel_name = chat.title or f"ID: {message.channel_id}"
            except:
                channel_name = f"ID: {message.channel_id}"
            
            # Формируем сообщение
            timestamp = message.timestamp.strftime("%H:%M")
            
            message_text = f"""🚨 СРОЧНО: ГОТОВ КУПИТЬ!

🤖 УЛЬТРА-СИЛЬНЫЙ ПОКУПАТЕЛЬСКИЙ СИГНАЛ
📺 Канал: {channel_name}
🕐 Время: {timestamp}
👤 От: {participant.display_name} (@{participant.username or 'no_username'})
💬 Сообщение: "{message.text}"

📊 Уверенность: 95% (ультра-триггер)
🏢 Бизнес-релевантность: 95%

🎯 СРОЧНЫЕ действия:
- Немедленно связаться с клиентом
- Уточнить бюджет и требования  
- Подготовить коммерческое предложение
- Запросить контактные данные

⚡️ НЕМЕДЛЕННО: Позвонить клиенту в течение 15 минут
💰 Потенциальный бюджет: требует уточнения
📅 Временные рамки: срочно (клиент готов)

🚨 ЭТО ГОТОВЫЙ ПОКУПАТЕЛЬ - РЕАГИРУЙТЕ МГНОВЕННО!"""

            # Отправляем всем админам
            admin_ids = self.config.get('bot', {}).get('admin_ids', [])
            
            for admin_id in admin_ids:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=message_text,
                        parse_mode=None
                    )
                    logger.info(f"🚨 СРОЧНОЕ уведомление отправлено админу {admin_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки СРОЧНОГО уведомления админу {admin_id}: {e}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка СРОЧНОГО уведомления админов: {e}")


    def get_status(self) -> Dict[str, Any]:
        """Статус парсера"""
        status = {
            'enabled': self.enabled,
            'channels_count': len(self.channels),
            'channels': self.channels,
            'min_confidence_score': self.min_confidence_score,
            'individual_active_users': len(self.user_contexts),
            'individual_processed_leads_count': len(self.processed_leads),
            'dialogue_analysis_enabled': self.dialogue_analysis_enabled,
            'mode': 'unified_smart'
        }
        
        if self.dialogue_tracker:
            tracker_status = self.dialogue_tracker.get_status()
            status['dialogue_tracker'] = tracker_status
            status['dialogue_analysis_history_count'] = len(self.dialogue_analysis_history)
        
        return status

# Алиас для совместимости - заменяем старый DialogueTracker на умный
DialogueTracker = SmartDialogueTracker
AIContextParser = UnifiedAIParser
IntegratedAIContextParser = UnifiedAIParser
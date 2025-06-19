"""
myparser/integrated_ai_parser.py - Интегрированный AI парсер
Объединяет анализ диалогов и индивидуальных сообщений
"""

import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from telegram import Update, User
from telegram.ext import ContextTypes

from database.operations import create_lead, update_channel_stats
from database.models import Lead
from ai.claude_client import get_claude_client

logger = logging.getLogger(__name__)

@dataclass
class UserContext:
    """Контекст пользователя для анализа"""
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
    group_dynamics: Dict[str, Any]
    business_relevance_score: int
    recommended_actions: List[str]
    key_insights: List[str]
    dialogue_summary: str
    participant_analysis: Dict[int, Dict[str, Any]]
    buying_probability: Dict[str, float]
    influence_map: Dict[int, List[int]]
    next_best_action: str
    estimated_timeline: Optional[str]
    group_budget_estimate: Optional[str]

class DialogueTracker:
    """Отслеживание и управление диалогами"""
    
    def __init__(self, config):
        self.config = config
        self.active_dialogues: Dict[str, DialogueContext] = {}
        self.dialogue_timeout = timedelta(minutes=15)
        self.min_participants = 2
        self.min_messages = 3
        self.reply_window = timedelta(minutes=5)
        self.max_dialogue_duration = timedelta(hours=2)
        
        logger.info("DialogueTracker инициализирован")

    def get_dialogue_id(self, channel_id: int, start_time: datetime) -> str:
        """Генерация ID диалога"""
        return f"dialogue_{channel_id}_{start_time.strftime('%Y%m%d_%H%M%S')}"

    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        """Обработка сообщения и определение принадлежности к диалогу"""
        try:
            chat_id = update.effective_chat.id
            user = update.effective_user
            message = update.message
            
            if not user or not message or not message.text:
                return None
            
            await self._cleanup_expired_dialogues()
            active_dialogue = self._find_active_dialogue(chat_id)
            is_dialogue_message = self._is_dialogue_message(message, active_dialogue)
            
            if is_dialogue_message and active_dialogue:
                await self._add_message_to_dialogue(active_dialogue, user, message)
                logger.info(f"📝 Сообщение добавлено к диалогу {active_dialogue.dialogue_id}")
                return active_dialogue.dialogue_id
            elif self._should_start_new_dialogue(chat_id, user, message):
                new_dialogue = await self._start_new_dialogue(chat_id, update.effective_chat.title, user, message)
                logger.info(f"🆕 Начат новый диалог: {new_dialogue.dialogue_id}")
                return new_dialogue.dialogue_id
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения для диалога: {e}")
            return None

    def _find_active_dialogue(self, channel_id: int) -> Optional[DialogueContext]:
        """Поиск активного диалога в канале"""
        for dialogue in self.active_dialogues.values():
            if (dialogue.channel_id == channel_id and 
                datetime.now() - dialogue.last_activity < self.dialogue_timeout):
                return dialogue
        return None

    def _is_dialogue_message(self, message, active_dialogue: Optional[DialogueContext]) -> bool:
        """Определение является ли сообщение частью диалога"""
        if not active_dialogue:
            return False
        
        time_diff = datetime.now() - active_dialogue.last_activity
        if time_diff > self.dialogue_timeout:
            return False
        
        if message.reply_to_message:
            reply_user_id = message.reply_to_message.from_user.id
            if reply_user_id in active_dialogue.participants:
                return True
        
        if message.from_user.id in active_dialogue.participants:
            return True
        
        return self._has_contextual_connection(message, active_dialogue)

    def _has_contextual_connection(self, message, dialogue: DialogueContext) -> bool:
        """Проверка контекстной связи с диалогом"""
        message_text = message.text.lower()
        
        for participant in dialogue.participants.values():
            if participant.username and f"@{participant.username.lower()}" in message_text:
                return True
        
        if dialogue.is_business_related:
            business_keywords = ['crm', 'бот', 'автоматизация', 'система', 'заказ', 'цена', 'стоимость']
            if any(keyword in message_text for keyword in business_keywords):
                return True
        
        return False

    def _should_start_new_dialogue(self, channel_id: int, user: User, message) -> bool:
        """Определение нужно ли начинать новый диалог"""
        if message.reply_to_message and message.reply_to_message.from_user.id != user.id:
            return True
        
        if self._contains_question_patterns(message.text):
            return True
        
        if self._contains_business_signals(message.text):
            return True
        
        return False

    def _contains_question_patterns(self, text: str) -> bool:
        """Проверка на вопросительные паттерны"""
        question_patterns = [
            '?', 'как', 'что', 'где', 'когда', 'почему', 'зачем', 'кто',
            'можете ли', 'возможно ли', 'а что если', 'подскажите', 'помогите'
        ]
        text_lower = text.lower()
        return any(pattern in text_lower for pattern in question_patterns)

    def _contains_business_signals(self, text: str) -> bool:
        """Проверка на деловые/покупательские сигналы"""
        business_signals = [
            'цена', 'стоимость', 'купить', 'заказать', 'crm', 'бот', 'автоматизация',
            'разработка', 'нужно', 'требуется', 'ищу', 'интересует', 'хочу узнать'
        ]
        text_lower = text.lower()
        return any(signal in text_lower for signal in business_signals)

    async def _start_new_dialogue(self, channel_id: int, channel_title: str, 
                                user: User, message) -> DialogueContext:
        """Создание нового диалога"""
        start_time = datetime.now()
        dialogue_id = self.get_dialogue_id(channel_id, start_time)
        
        participant = DialogueParticipant(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            role="initiator",
            message_count=1,
            first_message_time=start_time,
            last_message_time=start_time
        )
        
        dialogue = DialogueContext(
            dialogue_id=dialogue_id,
            channel_id=channel_id,
            channel_title=channel_title or f"Channel_{channel_id}",
            participants={user.id: participant},
            messages=[],
            start_time=start_time,
            last_activity=start_time,
            is_business_related=self._contains_business_signals(message.text)
        )
        
        await self._add_message_to_dialogue(dialogue, user, message)
        self.active_dialogues[dialogue_id] = dialogue
        return dialogue

    async def _add_message_to_dialogue(self, dialogue: DialogueContext, user: User, message):
        """Добавление сообщения к диалогу"""
        current_time = datetime.now()
        
        if user.id not in dialogue.participants:
            role = "responder" if len(dialogue.participants) == 1 else "participant"
            participant = DialogueParticipant(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                role=role,
                message_count=1,
                first_message_time=current_time,
                last_message_time=current_time
            )
            dialogue.participants[user.id] = participant
        else:
            participant = dialogue.participants[user.id]
            participant.message_count += 1
            participant.last_message_time = current_time
        
        buying_signals = self._extract_buying_signals(message.text)
        if buying_signals:
            participant.buying_signals_count += len(buying_signals)
        
        dialogue_message = DialogueMessage(
            user_id=user.id,
            username=user.username,
            text=message.text,
            timestamp=current_time,
            message_id=message.message_id,
            reply_to_message_id=message.reply_to_message.message_id if message.reply_to_message else None,
            reply_to_user_id=message.reply_to_message.from_user.id if message.reply_to_message else None,
            buying_signals=buying_signals,
            sentiment=self._analyze_sentiment(message.text),
            urgency_level=self._detect_urgency(message.text)
        )
        
        dialogue.messages.append(dialogue_message)
        dialogue.last_activity = current_time
        
        if buying_signals or self._contains_business_signals(message.text):
            dialogue.is_business_related = True

    def _extract_buying_signals(self, text: str) -> List[str]:
        """Извлечение покупательских сигналов из текста"""
        signals = []
        text_lower = text.lower()
        
        signal_patterns = {
            'price_inquiry': ['цена', 'стоимость', 'сколько стоит', 'прайс'],
            'purchase_intent': ['купить', 'заказать', 'хочу приобрести', 'готов купить'],
            'urgency': ['срочно', 'быстро', 'сегодня', 'сейчас', 'как можно скорее'],
            'budget_discussion': ['бюджет', 'готов потратить', 'рассчитываю на'],
            'decision_making': ['решение', 'выбираю', 'сравниваю', 'думаю над'],
            'timeline': ['когда', 'сроки', 'до какого числа', 'в течение']
        }
        
        for category, patterns in signal_patterns.items():
            for pattern in patterns:
                if pattern in text_lower:
                    signals.append(f"{category}: {pattern}")
        
        return signals

    def _analyze_sentiment(self, text: str) -> str:
        """Простой анализ тональности"""
        positive_words = ['хорошо', 'отлично', 'понравилось', 'согласен', 'да', 'спасибо', 'здорово']
        negative_words = ['плохо', 'не нравится', 'дорого', 'не подходит', 'нет', 'отказываюсь']
        
        text_lower = text.lower()
        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)
        
        if positive_count > negative_count:
            return "positive"
        elif negative_count > positive_count:
            return "negative"
        else:
            return "neutral"

    def _detect_urgency(self, text: str) -> str:
        """Определение уровня срочности"""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ['срочно', 'сейчас', 'немедленно']):
            return "immediate"
        elif any(word in text_lower for word in ['быстро', 'сегодня', 'завтра']):
            return "high"
        elif any(word in text_lower for word in ['на днях', 'на этой неделе', 'скоро']):
            return "medium"
        elif any(word in text_lower for word in ['в перспективе', 'когда-нибудь', 'может быть']):
            return "low"
        else:
            return "none"

    async def _cleanup_expired_dialogues(self):
        """Очистка завершенных диалогов"""
        current_time = datetime.now()
        expired_dialogues = []
        
        for dialogue_id, dialogue in self.active_dialogues.items():
            if (current_time - dialogue.last_activity > self.dialogue_timeout or
                current_time - dialogue.start_time > self.max_dialogue_duration):
                expired_dialogues.append(dialogue_id)
        
        for dialogue_id in expired_dialogues:
            completed_dialogue = self.active_dialogues.pop(dialogue_id)
            logger.info(f"🏁 Диалог завершен: {dialogue_id} ({len(completed_dialogue.messages)} сообщений)")

    def get_completed_dialogues_for_analysis(self) -> List[DialogueContext]:
        """Получение завершенных диалогов готовых для анализа"""
        current_time = datetime.now()
        completed = []
        
        for dialogue in self.active_dialogues.values():
            if (len(dialogue.participants) >= self.min_participants and
                len(dialogue.messages) >= self.min_messages and
                current_time - dialogue.last_activity > timedelta(minutes=5)):
                completed.append(dialogue)
        
        return completed

class DialogueAnalyzer:
    """Анализатор диалогов с помощью AI"""
    
    def __init__(self, config):
        self.config = config
        self.claude_client = get_claude_client()
        logger.info("DialogueAnalyzer инициализирован")

    async def analyze_dialogue(self, dialogue: DialogueContext) -> Optional[DialogueAnalysisResult]:
        """Полный анализ диалога"""
        try:
            logger.info(f"🔍 Начинаем анализ диалога {dialogue.dialogue_id}")
            
            if not self.claude_client or not self.claude_client.client:
                logger.warning("Claude API недоступен, используем упрощенный анализ")
                return self._simple_dialogue_analysis(dialogue)
            
            analysis_prompt = self._create_dialogue_analysis_prompt(dialogue)
            
            response = await asyncio.wait_for(
                self.claude_client.client.messages.create(
                    model=self.claude_client.model,
                    max_tokens=3000,
                    messages=[{"role": "user", "content": analysis_prompt}],
                    temperature=0.1
                ),
                timeout=20.0
            )
            
            analysis_result = self._parse_dialogue_analysis_response(response.content[0].text, dialogue)
            
            logger.info(f"✅ Анализ диалога завершен: ценность={analysis_result.is_valuable_dialogue}, лидов={len(analysis_result.potential_leads)}")
            
            return analysis_result
            
        except Exception as e:
            logger.error(f"Ошибка анализа диалога: {e}")
            return self._simple_dialogue_analysis(dialogue)

    def _create_dialogue_analysis_prompt(self, dialogue: DialogueContext) -> str:
        """Создание промпта для анализа диалога"""
        participants_info = []
        for user_id, participant in dialogue.participants.items():
            info = f"""
Участник {participant.first_name} (@{participant.username or 'без_username'}):
- Роль: {participant.role}
- Сообщений: {participant.message_count}
- Покупательские сигналы: {participant.buying_signals_count}
- Уровень вовлеченности: {participant.engagement_level}"""
            participants_info.append(info)
        
        messages_history = []
        for msg in dialogue.messages:
            timestamp = msg.timestamp.strftime("%H:%M")
            username = msg.username or f"user_{msg.user_id}"
            messages_history.append(f"[{timestamp}] {username}: {msg.text}")
        
        return f"""Ты - эксперт по анализу диалогов потенциальных клиентов в сфере IT, CRM систем и автоматизации бизнеса.

КОНТЕКСТ ДИАЛОГА:
- Канал: {dialogue.channel_title}
- Длительность: {(dialogue.last_activity - dialogue.start_time).total_seconds() / 60:.1f} минут
- Участников: {len(dialogue.participants)}
- Сообщений: {len(dialogue.messages)}
- Бизнес-релевантность: {dialogue.is_business_related}

УЧАСТНИКИ:
{''.join(participants_info)}

ИСТОРИЯ ДИАЛОГА:
{chr(10).join(messages_history)}

ЗАДАЧА:
Проанализируй этот диалог и определи:
1. Есть ли потенциальные клиенты среди участников
2. Групповую динамику принятия решений
3. Влияние участников друг на друга
4. Скрытые покупательские намерения
5. Рекомендации по работе с каждым участником

ВЕРНИ РЕЗУЛЬТАТ В JSON ФОРМАТЕ:
{{
    "is_valuable_dialogue": boolean,
    "confidence_score": number (0-100),
    "business_relevance_score": number (0-100),
    "potential_leads": [
        {{
            "user_id": number,
            "lead_probability": number (0-100),
            "lead_quality": "hot|warm|cold",
            "key_signals": ["список сигналов"],
            "recommended_approach": "стратегия работы",
            "urgency_level": "immediate|high|medium|low",
            "estimated_budget": "примерная оценка или null",
            "decision_influencers": [список user_id влияющих на решение],
            "role_in_decision": "decision_maker|influencer|observer|budget_holder"
        }}
    ],
    "group_dynamics": {{
        "decision_making_style": "individual|consensus|leader_driven|committee",
        "dominant_participants": [user_id],
        "influence_relationships": {{user_id: [influenced_user_ids]}},
        "group_sentiment": "positive|negative|neutral|mixed",
        "discussion_stage": "problem_identification|solution_research|vendor_evaluation|decision_pending"
    }},
    "dialogue_summary": "краткое описание сути диалога",
    "key_insights": ["ключевые инсайты о покупательском поведении"],
    "recommended_actions": ["конкретные рекомендации"],
    "next_best_action": "следующий оптимальный шаг",
    "estimated_timeline": "временные рамки принятия решения или null",
    "group_budget_estimate": "оценка группового бюджета или null",
    "buying_probability": {{user_id: probability_0_to_1}},
    "topic_classification": "price_inquiry|feature_discussion|competitor_comparison|implementation_planning|support_request|other"
}}"""

    def _parse_dialogue_analysis_response(self, response_text: str, dialogue: DialogueContext) -> DialogueAnalysisResult:
        """Парсинг ответа AI анализа диалога"""
        try:
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                raise ValueError("JSON не найден в ответе")
            
            data = json.loads(json_match.group())
            
            participant_analysis = {}
            buying_probability = {}
            influence_map = {}
            
            for lead_data in data.get('potential_leads', []):
                user_id = lead_data['user_id']
                participant_analysis[user_id] = {
                    'lead_probability': lead_data.get('lead_probability', 0),
                    'lead_quality': lead_data.get('lead_quality', 'cold'),
                    'key_signals': lead_data.get('key_signals', []),
                    'recommended_approach': lead_data.get('recommended_approach', ''),
                    'role_in_decision': lead_data.get('role_in_decision', 'observer')
                }
                buying_probability[user_id] = lead_data.get('lead_probability', 0) / 100.0
            
            influence_relationships = data.get('group_dynamics', {}).get('influence_relationships', {})
            for influencer_str, influenced_list in influence_relationships.items():
                try:
                    influencer_id = int(influencer_str)
                    influence_map[influencer_id] = [int(uid) for uid in influenced_list]
                except (ValueError, TypeError):
                    continue
            
            return DialogueAnalysisResult(
                dialogue_id=dialogue.dialogue_id,
                is_valuable_dialogue=data.get('is_valuable_dialogue', False),
                confidence_score=data.get('confidence_score', 0),
                potential_leads=data.get('potential_leads', []),
                group_dynamics=data.get('group_dynamics', {}),
                business_relevance_score=data.get('business_relevance_score', 0),
                recommended_actions=data.get('recommended_actions', []),
                key_insights=data.get('key_insights', []),
                dialogue_summary=data.get('dialogue_summary', ''),
                participant_analysis=participant_analysis,
                buying_probability=buying_probability,
                influence_map=influence_map,
                next_best_action=data.get('next_best_action', ''),
                estimated_timeline=data.get('estimated_timeline'),
                group_budget_estimate=data.get('group_budget_estimate')
            )
            
        except Exception as e:
            logger.error(f"Ошибка парсинга ответа анализа диалога: {e}")
            return self._create_fallback_analysis(dialogue)

    def _simple_dialogue_analysis(self, dialogue: DialogueContext) -> DialogueAnalysisResult:
        """Упрощенный анализ диалога без AI"""
        potential_leads = []
        buying_probability = {}
        
        for user_id, participant in dialogue.participants.items():
            score = min(100, participant.buying_signals_count * 25 + participant.message_count * 5)
            
            if score >= 50:
                lead_quality = "hot" if score >= 80 else "warm"
                potential_leads.append({
                    'user_id': user_id,
                    'lead_probability': score,
                    'lead_quality': lead_quality,
                    'key_signals': [f"Покупательские сигналы: {participant.buying_signals_count}"],
                    'recommended_approach': "Связаться для обсуждения",
                    'role_in_decision': participant.role
                })
            
            buying_probability[user_id] = score / 100.0
        
        return DialogueAnalysisResult(
            dialogue_id=dialogue.dialogue_id,
            is_valuable_dialogue=len(potential_leads) > 0,
            confidence_score=70 if potential_leads else 30,
            potential_leads=potential_leads,
            group_dynamics={"decision_making_style": "unknown"},
            business_relevance_score=80 if dialogue.is_business_related else 20,
            recommended_actions=["Простой анализ завершен"],
            key_insights=["Анализ выполнен без AI"],
            dialogue_summary=f"Диалог с {len(dialogue.participants)} участниками",
            participant_analysis={},
            buying_probability=buying_probability,
            influence_map={},
            next_best_action="Связаться с потенциальными лидами",
            estimated_timeline=None,
            group_budget_estimate=None
        )

    def _create_fallback_analysis(self, dialogue: DialogueContext) -> DialogueAnalysisResult:
        """Создание базового анализа при ошибке"""
        return DialogueAnalysisResult(
            dialogue_id=dialogue.dialogue_id,
            is_valuable_dialogue=False,
            confidence_score=0,
            potential_leads=[],
            group_dynamics={},
            business_relevance_score=0,
            recommended_actions=["Анализ не удался"],
            key_insights=[],
            dialogue_summary="Ошибка анализа",
            participant_analysis={},
            buying_probability={},
            influence_map={},
            next_best_action="Повторить анализ",
            estimated_timeline=None,
            group_budget_estimate=None
        )

class IntegratedAIContextParser:
    """Интегрированный AI парсер с поддержкой анализа диалогов и индивидуальных сообщений"""
    
    def __init__(self, config):
        self.config = config
        self.parsing_config = config.get('parsing', {})
        
        # Основные настройки
        self.enabled = self.parsing_config.get('enabled', True)
        self.channels = self._parse_channels()
        self.min_confidence_score = self.parsing_config.get('min_confidence_score', 70)
        
        # Настройки для индивидуального анализа
        self.context_window_hours = self.parsing_config.get('context_window_hours', 24)
        self.min_messages_for_analysis = self.parsing_config.get('min_messages_for_analysis', 1)
        self.max_context_messages = self.parsing_config.get('max_context_messages', 10)
        
        # Настройки для анализа диалогов
        self.dialogue_analysis_enabled = self.parsing_config.get('dialogue_analysis_enabled', True)
        self.prefer_dialogue_analysis = self.parsing_config.get('prefer_dialogue_analysis', True)
        
        # Компоненты
        self.dialogue_tracker = DialogueTracker(config) if self.dialogue_analysis_enabled else None
        self.dialogue_analyzer = DialogueAnalyzer(config) if self.dialogue_analysis_enabled else None
        
        # Контекст пользователей для индивидуального анализа
        self.user_contexts: Dict[int, UserContext] = {}
        self.analysis_cache: Dict[str, AIAnalysisResult] = {}
        self.processed_leads: Dict[int, datetime] = {}
        
        logger.info(f"IntegratedAIContextParser инициализирован:")
        logger.info(f"  - Каналов: {len(self.channels)}")
        logger.info(f"  - Анализ диалогов: {self.dialogue_analysis_enabled}")
        logger.info(f"  - Приоритет диалогам: {self.prefer_dialogue_analysis}")
        logger.info(f"  - Мин. уверенность: {self.min_confidence_score}%")

    def _parse_channels(self) -> List[str]:
        """Парсинг каналов из конфигурации"""
        channels_raw = self.parsing_config.get('channels', [])
        if isinstance(channels_raw, list):
            return [str(ch) for ch in channels_raw]
        elif isinstance(channels_raw, (str, int)):
            return [str(channels_raw)]
        return []

    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Главная функция обработки сообщения с интегрированным анализом"""
        try:
            if not self.enabled:
                logger.info("❌ AI парсинг отключен")
                return
            
            chat_id = update.effective_chat.id
            user = update.effective_user
            message = update.message
            
            if not user or not message or not message.text:
                logger.warning("⚠️ Нет пользователя, сообщения или текста")
                return
            
            logger.info(f"🔍 Начинаем интегрированный анализ сообщения:")
            logger.info(f"    👤 Пользователь: {user.first_name} (@{user.username})")
            logger.info(f"    💬 Текст: '{message.text[:50]}...'")
            logger.info(f"    📍 Канал: {chat_id}")
            
            # Проверяем, что канал отслеживается
            if not self.is_channel_monitored(chat_id, update.effective_chat.username):
                logger.info("⏭️ Канал не отслеживается")
                return
            
            # Стратегия 1: Пробуем анализ диалогов (если включен)
            dialogue_processed = False
            if self.dialogue_analysis_enabled and self.dialogue_tracker:
                dialogue_id = await self.dialogue_tracker.process_message(update, context)
                
                if dialogue_id:
                    logger.info(f"📝 Сообщение обработано в диалоге: {dialogue_id}")
                    
                    # Проверяем готовые для анализа диалоги
                    await self._check_and_analyze_dialogues(context)
                    dialogue_processed = True
                    
                    # Если настроен приоритет диалогам - не делаем индивидуальный анализ
                    if self.prefer_dialogue_analysis:
                        logger.info("🎯 Приоритет диалогам - пропускаем индивидуальный анализ")
                        return
            
            # Стратегия 2: Индивидуальный анализ (если диалог не обработан или не приоритетен)
            if not dialogue_processed or not self.prefer_dialogue_analysis:
                logger.info("👤 Запускаем индивидуальный анализ пользователя")
                await self._process_individual_message(update, context)
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка в интегрированном AI парсере: {e}")
            import traceback
            traceback.print_exc()

    async def _check_and_analyze_dialogues(self, context: ContextTypes.DEFAULT_TYPE):
        """Проверка и анализ готовых диалогов"""
        if not self.dialogue_analysis_enabled or not self.dialogue_analyzer:
            return
        
        try:
            completed_dialogues = self.dialogue_tracker.get_completed_dialogues_for_analysis()
            
            for dialogue in completed_dialogues:
                logger.info(f"🔍 Анализируем завершенный диалог: {dialogue.dialogue_id}")
                
                analysis_result = await self.dialogue_analyzer.analyze_dialogue(dialogue)
                
                if analysis_result and analysis_result.is_valuable_dialogue:
                    await self._process_dialogue_analysis_result(dialogue, analysis_result, context)
                    
                    # Помечаем участников как обработанных в диалоге
                    for participant_id in dialogue.participants.keys():
                        self.processed_leads[participant_id] = datetime.now()
                
                # Удаляем диалог из активных после анализа
                if dialogue.dialogue_id in self.dialogue_tracker.active_dialogues:
                    del self.dialogue_tracker.active_dialogues[dialogue.dialogue_id]
                
        except Exception as e:
            logger.error(f"Ошибка анализа диалогов: {e}")

    async def _process_dialogue_analysis_result(self, dialogue: DialogueContext, 
                                              analysis: DialogueAnalysisResult, 
                                              context: ContextTypes.DEFAULT_TYPE):
        """Обработка результатов анализа диалога"""
        try:
            logger.info(f"💎 Ценный диалог обнаружен: {dialogue.dialogue_id}")
            logger.info(f"   Уверенность: {analysis.confidence_score}%")
            logger.info(f"   Потенциальных лидов: {len(analysis.potential_leads)}")
            
            # Создаем лиды для участников с высокой вероятностью
            created_leads = []
            for lead_data in analysis.potential_leads:
                if lead_data['lead_probability'] >= self.min_confidence_score:
                    user_id = lead_data['user_id']
                    participant = dialogue.participants.get(user_id)
                    
                    if participant:
                        lead = await self._create_lead_from_dialogue_participant(
                            participant, dialogue, lead_data, analysis
                        )
                        if lead:
                            created_leads.append((participant, lead_data))
            
            # Отправляем уведомление админам о ценном диалоге
            min_confidence_for_notification = self.parsing_config.get('min_dialogue_confidence', 75)
            if (analysis.confidence_score >= min_confidence_for_notification or created_leads):
                await self._notify_admins_about_dialogue(context, dialogue, analysis, created_leads)
            
            # Обновляем статистику канала
            await self._update_channel_stats(str(dialogue.channel_id), 
                                           dialogue.messages[-1].message_id if dialogue.messages else 0,
                                           len(created_leads) > 0)
            
        except Exception as e:
            logger.error(f"Ошибка обработки результатов анализа диалога: {e}")

    async def _process_individual_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка индивидуального сообщения"""
        try:
            user = update.effective_user
            message = update.message
            
            # Обновляем контекст пользователя
            await self._update_user_context(user, message, update.effective_chat)
            logger.info("✅ Контекст пользователя обновлен")
            
            # Получаем контекст для анализа
            user_context = self.user_contexts.get(user.id)
            if not user_context:
                logger.warning("❌ Не удалось получить контекст пользователя")
                return
            
            logger.info(f"📊 Контекст: {len(user_context.messages)} сообщений")
            
            # Проверяем готовность к анализу
            if not self._should_analyze_user(user_context):
                logger.info(f"⏳ Пользователь {user.id} не готов к индивидуальному анализу")
                return
            
            # Проверяем, не анализировали ли недавно
            if self._was_recently_analyzed(user.id):
                logger.info(f"🔄 Пользователь {user.id} недавно анализировался")
                return
            
            logger.info("🤖 Запускаем индивидуальный AI анализ...")
            
            # Запускаем AI анализ
            analysis = await self._analyze_user_context(user_context)
            
            if analysis:
                logger.info(f"✅ Индивидуальный AI анализ завершен:")
                logger.info(f"    🎯 Лид: {analysis.is_lead}")
                logger.info(f"    📊 Уверенность: {analysis.confidence_score}%")
                logger.info(f"    🔥 Качество: {analysis.lead_quality}")
                
                if analysis.is_lead and analysis.confidence_score >= self.min_confidence_score:
                    logger.info("🎯 СОЗДАЕМ ИНДИВИДУАЛЬНОГО ЛИДА!")
                    
                    # Создаем лид
                    await self._create_lead_from_individual_analysis(user_context, analysis, context)
                    
                    # Запоминаем, что уже обработали
                    self.processed_leads[user.id] = datetime.now()
                    
                    # Обновляем статистику канала
                    await self._update_channel_stats(str(update.effective_chat.id), 
                                                   message.message_id, True)
                else:
                    logger.info(f"❌ Не лид: score={analysis.confidence_score}, min={self.min_confidence_score}")
                    await self._update_channel_stats(str(update.effective_chat.id), 
                                                   message.message_id, False)
            else:
                logger.warning("❌ Индивидуальный AI анализ не удался")
                await self._update_channel_stats(str(update.effective_chat.id), 
                                               message.message_id, False)
            
        except Exception as e:
            logger.error(f"❌ Ошибка индивидуального анализа: {e}")

    async def _update_user_context(self, user: User, message, chat):
        """Обновление контекста пользователя"""
        try:
            user_id = user.id
            current_time = datetime.now()
            
            # Создаем или обновляем контекст
            if user_id not in self.user_contexts:
                logger.info(f"🆕 Создаем новый индивидуальный контекст для пользователя {user_id}")
                self.user_contexts[user_id] = UserContext(
                    user_id=user_id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    messages=[],
                    first_seen=current_time,
                    last_activity=current_time,
                    channel_info={
                        'id': chat.id,
                        'title': chat.title,
                        'username': chat.username,
                        'type': chat.type
                    }
                )
            
            user_context = self.user_contexts[user_id]
            
            # Добавляем новое сообщение
            message_data = {
                'text': message.text,
                'date': message.date.isoformat() if message.date else current_time.isoformat(),
                'message_id': message.message_id,
                'timestamp': current_time.isoformat()
            }
            
            user_context.messages.append(message_data)
            user_context.last_activity = current_time
            
            # Обновляем профиль пользователя
            user_context.username = user.username
            user_context.first_name = user.first_name
            user_context.last_name = user.last_name
            
            # Ограничиваем количество сообщений в контексте
            if len(user_context.messages) > self.max_context_messages:
                user_context.messages = user_context.messages[-self.max_context_messages:]
            
            logger.info(f"📝 Добавлено сообщение в индивидуальный контекст. Всего: {len(user_context.messages)}")
            
        except Exception as e:
            logger.error(f"Ошибка обновления индивидуального контекста пользователя {user.id}: {e}")

    def _should_analyze_user(self, user_context: UserContext) -> bool:
        """Определяет, готов ли пользователь к индивидуальному анализу"""
        messages_count = len(user_context.messages)
        
        # Минимальное количество сообщений
        if messages_count < self.min_messages_for_analysis:
            logger.info(f"❌ Недостаточно сообщений для индивидуального анализа: {messages_count} < {self.min_messages_for_analysis}")
            return False
        
        # Для одиночных сообщений проверяем сильные покупательские сигналы
        if messages_count == 1:
            first_message = user_context.messages[0]['text'].lower()
            strong_signals = self._has_strong_buying_signals(first_message)
            
            if strong_signals:
                logger.info(f"🔥 СИЛЬНЫЕ ПОКУПАТЕЛЬСКИЕ СИГНАЛЫ в индивидуальном сообщении!")
                return True
            
            # Если нет сильных сигналов - ждем время или еще сообщения
            time_since_last = datetime.now() - user_context.last_activity
            if time_since_last > timedelta(minutes=2):
                logger.info(f"✅ Прошло достаточно времени для индивидуального анализа: {time_since_last}")
                return True
            
            logger.info(f"⏳ Одно сообщение без сильных сигналов, ждем: {time_since_last} < 2 мин")
            return False
        
        # Для 2+ сообщений - анализируем сразу
        if messages_count >= 2:
            logger.info(f"✅ Достаточно сообщений для индивидуального анализа: {messages_count}")
            return True
        
        return False

    def _has_strong_buying_signals(self, text: str) -> bool:
        """Проверка на сильные покупательские сигналы в тексте"""
        strong_signals = [
            'хочу купить', 'хочу заказать', 'готов купить', 'готов заказать',
            'нужно купить', 'планирую купить', 'собираюсь купить',
            'сколько стоит', 'какая цена', 'какая стоимость', 'цена за',
            'стоимость услуг', 'прайс-лист', 'прайс лист', 'расценки',
            'срочно нужно', 'нужно сегодня', 'нужно сейчас', 'как можно быстрее',
            'заказать бота', 'сделать бота', 'разработать бота', 'создать бота',
            'нужен бот', 'ищу разработчика', 'нужна crm', 'заказать crm',
            'автоматизировать бизнес', 'настроить автоматизацию',
            'обсудить проект', 'обсудить условия', 'обсудить детали',
            'связаться с менеджером', 'поговорить о цене'
        ]
        
        for signal in strong_signals:
            if signal in text:
                logger.info(f"🎯 Обнаружен сильный индивидуальный сигнал: '{signal}'")
                return True
        
        # Дополнительная проверка на комбинации слов
        buying_words = ['купить', 'заказать', 'нужно', 'нужен', 'нужна', 'хочу', 'ищу']
        service_words = ['бот', 'crm', 'автоматизац', 'интеграц', 'разработ', 'систем']
        
        buying_found = any(word in text for word in buying_words)
        service_found = any(word in text for word in service_words)
        
        if buying_found and service_found:
            logger.info(f"🎯 Обнаружена комбинация в индивидуальном сообщении: покупательское намерение + наши услуги")
            return True
        
        return False

    def _was_recently_analyzed(self, user_id: int) -> bool:
        """Проверяет, не анализировался ли пользователь недавно"""
        if user_id in self.processed_leads:
            last_analysis = self.processed_leads[user_id]
            time_diff = datetime.now() - last_analysis
            if time_diff < timedelta(hours=self.context_window_hours):
                logger.info(f"🔄 Недавний анализ пользователя {user_id}: {time_diff} назад")
                return True
        return False

    async def _analyze_user_context(self, user_context: UserContext) -> Optional[AIAnalysisResult]:
        """AI анализ контекста пользователя"""
        try:
            logger.info("🤖 Начинаем индивидуальный AI анализ...")
            
            claude_client = get_claude_client()
            if not claude_client or not claude_client.client:
                logger.warning("❌ Claude API недоступен, используем простой индивидуальный анализ")
                return self._simple_analysis(user_context)
            
            # Создаем ключ для кэша
            messages_text = " | ".join([msg['text'] for msg in user_context.messages[-5:]])
            cache_key = f"individual_{user_context.user_id}:{hash(messages_text)}"
            
            # Проверяем кэш
            if cache_key in self.analysis_cache:
                logger.info(f"💾 Используем кэшированный индивидуальный анализ для {user_context.user_id}")
                return self.analysis_cache[cache_key]
            
            # Подготавливаем данные для анализа
            context_data = self._prepare_context_for_ai(user_context)
            
            # Формируем промпт для Claude
            analysis_prompt = self._create_individual_analysis_prompt(context_data)
            
            logger.info(f"📤 Отправляем запрос индивидуального анализа в Claude...")
            
            # Отправляем запрос в Claude с таймаутом
            try:
                response = await asyncio.wait_for(
                    claude_client.client.messages.create(
                        model=claude_client.model,
                        max_tokens=2000,
                        messages=[{"role": "user", "content": analysis_prompt}],
                        temperature=0.1
                    ),
                    timeout=15.0
                )
                
                logger.info("📥 Получен ответ от Claude для индивидуального анализа")
                
                # Парсим ответ
                analysis_result = self._parse_individual_ai_response(response.content[0].text)
                
                # Кэшируем результат
                self.analysis_cache[cache_key] = analysis_result
                
                logger.info(f"✅ Индивидуальный AI анализ успешен: лид={analysis_result.is_lead}, уверенность={analysis_result.confidence_score}%")
                
                return analysis_result
                
            except asyncio.TimeoutError:
                logger.warning("⏰ Индивидуальный AI анализ превысил таймаут, используем простой анализ")
                return self._simple_analysis(user_context)
            
        except Exception as e:
            logger.error(f"❌ Ошибка индивидуального AI анализа: {e}")
            return self._simple_analysis(user_context)

    def _simple_analysis(self, user_context: UserContext) -> AIAnalysisResult:
        """Простой анализ без AI"""
        logger.info("🔧 Используем простой индивидуальный анализ...")
        
        # Объединяем все сообщения
        all_text = " ".join([msg['text'] for msg in user_context.messages]).lower()
        
        # Простые ключевые слова
        high_interest = ['купить', 'заказать', 'цена', 'стоимость', 'сколько стоит', 'crm', 'бот', 'автоматизация']
        medium_interest = ['интересно', 'подробнее', 'расскажите', 'как работает']
        
        score = 0
        interests = []
        buying_signals = []
        
        for word in high_interest:
            if word in all_text:
                score += 30
                interests.append(word)
                if word in ['купить', 'заказать', 'цена']:
                    buying_signals.append(f"Упоминание '{word}'")
        
        for word in medium_interest:
            if word in all_text:
                score += 15
                interests.append(word)
        
        score = min(100, score)
        is_lead = score >= 60
        
        if is_lead:
            lead_quality = "hot" if score >= 80 else "warm"
        else:
            lead_quality = "cold"
        
        result = AIAnalysisResult(
            is_lead=is_lead,
            confidence_score=score,
            lead_quality=lead_quality,
            interests=interests,
            buying_signals=buying_signals,
            urgency_level="medium" if score >= 70 else "low",
            recommended_action="Связаться с клиентом" if is_lead else "Продолжить наблюдение",
            key_insights=[f"Простой индивидуальный анализ дал score {score}"],
            estimated_budget=None,
            timeline=None,
            pain_points=[],
            decision_stage="consideration" if is_lead else "awareness"
        )
        
        logger.info(f"🔧 Простой индивидуальный анализ: score={score}, лид={is_lead}")
        return result

    def _prepare_context_for_ai(self, user_context: UserContext) -> Dict[str, Any]:
        """Подготовка контекста для AI анализа"""
        return {
            'user': {
                'id': user_context.user_id,
                'username': user_context.username,
                'first_name': user_context.first_name,
                'last_name': user_context.last_name,
                'first_seen': user_context.first_seen.isoformat(),
                'last_activity': user_context.last_activity.isoformat()
            },
            'messages': user_context.messages,
            'channel': user_context.channel_info,
            'messages_count': len(user_context.messages),
            'activity_span_hours': (user_context.last_activity - user_context.first_seen).total_seconds() / 3600
        }

    def _create_individual_analysis_prompt(self, context_data: Dict[str, Any]) -> str:
        """Создание промпта для индивидуального AI анализа"""
        
        messages_text = "\n".join([
            f"[{msg.get('date', 'unknown')}] {msg['text']}" 
            for msg in context_data['messages']
        ])
        
        return f"""Ты - эксперт по анализу потенциальных клиентов в сфере IT-услуг, CRM систем, автоматизации бизнеса и разработки Telegram ботов.

КОНТЕКСТ ПОЛЬЗОВАТЕЛЯ:
- Имя: {context_data['user']['first_name']} (@{context_data['user']['username']})
- Канал: {context_data['channel']['title']} ({context_data['channel']['type']})
- Количество сообщений: {context_data['messages_count']}
- Период активности: {context_data['activity_span_hours']:.1f} часов

СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ:
{messages_text}

ЗАДАЧА:
Проанализируй ИНДИВИДУАЛЬНЫЕ сообщения этого пользователя и определи, является ли он потенциальным клиентом для услуг:
- CRM систем и автоматизации бизнеса
- Разработки Telegram ботов
- IT-консалтинга и внедрения
- Интеграций и API разработки

ВЕРНИ РЕЗУЛЬТАТ СТРОГО В JSON ФОРМАТЕ:
{{
    "is_lead": boolean,
    "confidence_score": number (0-100),
    "lead_quality": "hot|warm|cold|not_lead",
    "interests": ["список интересов"],
    "buying_signals": ["сигналы покупательского намерения"],
    "urgency_level": "immediate|short_term|long_term|none",
    "recommended_action": "рекомендуемое действие",
    "key_insights": ["ключевые инсайты"],
    "estimated_budget": "примерный бюджет или null",
    "timeline": "временные рамки или null",
    "pain_points": ["проблемы клиента"],
    "decision_stage": "awareness|consideration|decision|post_purchase"
}}

ОБРАТИТЕ ОСОБОЕ ВНИМАНИЕ:
- Прямые покупательские сигналы (хочу купить, сколько стоит, нужно заказать) = ГОРЯЧИЙ ЛИД
- Одиночные сообщения с сильными сигналами должны получать высокий confidence_score (85-95)
- Срочность в запросе повышает приоритет

КРИТЕРИИ ОЦЕНКИ:
- is_lead: true если есть явные признаки интереса к нашим услугам
- confidence_score: 90-100 = очевидный клиент, 70-89 = вероятный, 50-69 = возможный, <50 = маловероятный
- lead_quality: hot = готов покупать, warm = изучает рынок, cold = только начинает поиск
- urgency_level: насколько срочно нужно решение

ВАЖНО:
- Анализируй ВЕСЬ контекст сообщений пользователя
- Ищи скрытые потребности и подтекст
- Обращай внимание на бизнес-контекст
- Высокий confidence_score только при явных сигналах
- Будь объективным, не завышай оценки"""

    def _parse_individual_ai_response(self, response_text: str) -> AIAnalysisResult:
        """Парсинг ответа от AI для индивидуального анализа"""
        try:
            logger.info(f"📋 Парсим ответ индивидуального AI: {response_text[:200]}...")
            
            # Ищем JSON в ответе
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                logger.warning("❌ JSON не найден в ответе индивидуального AI")
                raise ValueError("JSON не найден в ответе AI")
            
            json_str = json_match.group()
            data = json.loads(json_str)
            
            logger.info(f"✅ JSON индивидуального анализа успешно распарсен: is_lead={data.get('is_lead')}, score={data.get('confidence_score')}")
            
            # Валидация и создание объекта результата
            return AIAnalysisResult(
                is_lead=bool(data.get('is_lead', False)),
                confidence_score=max(0, min(100, int(data.get('confidence_score', 0)))),
                lead_quality=data.get('lead_quality', 'not_lead'),
                interests=data.get('interests', []),
                buying_signals=data.get('buying_signals', []),
                urgency_level=data.get('urgency_level', 'none'),
                recommended_action=data.get('recommended_action', ''),
                key_insights=data.get('key_insights', []),
                estimated_budget=data.get('estimated_budget'),
                timeline=data.get('timeline'),
                pain_points=data.get('pain_points', []),
                decision_stage=data.get('decision_stage', 'awareness')
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга ответа индивидуального AI: {e}")
            logger.debug(f"Ответ AI: {response_text}")
            
            # Возвращаем базовый результат
            return AIAnalysisResult(
                is_lead=False,
                confidence_score=0,
                lead_quality='not_lead',
                interests=[],
                buying_signals=[],
                urgency_level='none',
                recommended_action='Анализ не удался',
                key_insights=[],
                estimated_budget=None,
                timeline=None,
                pain_points=[],
                decision_stage='awareness'
            )

    async def _create_lead_from_dialogue_participant(self, participant, dialogue, lead_data, analysis):
        """Создание лида из участника диалога"""
        try:
            # Собираем все сообщения участника
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
                message_text=" | ".join(participant_messages),
                message_date=dialogue.last_activity,
                
                # AI поля из анализа диалога
                lead_quality=lead_data['lead_quality'],
                interests=json.dumps(lead_data.get('key_signals', []), ensure_ascii=False),
                buying_signals=json.dumps(lead_data.get('key_signals', []), ensure_ascii=False),
                urgency_level=lead_data.get('urgency_level', 'medium'),
                estimated_budget=analysis.group_budget_estimate,
                timeline=analysis.estimated_timeline,
                pain_points=json.dumps(analysis.key_insights, ensure_ascii=False),
                decision_stage=dialogue.decision_stage,
                notes=f"Диалог {dialogue.dialogue_id}. Роль: {lead_data.get('role_in_decision', 'участник')}. {lead_data.get('recommended_approach', '')}"
            )
            
            await create_lead(lead)
            logger.info(f"✅ Лид создан из диалога: {participant.first_name} ({participant.user_id})")
            return lead
            
        except Exception as e:
            logger.error(f"Ошибка создания лида из диалога: {e}")
            return None

    async def _create_lead_from_individual_analysis(self, user_context: UserContext, 
                                                  analysis: AIAnalysisResult, 
                                                  context: ContextTypes.DEFAULT_TYPE):
        """Создание лида на основе индивидуального AI анализа"""
        try:
            logger.info("🎯 Создаем индивидуального лида из AI анализа...")
            
            # Объединяем все сообщения пользователя
            all_messages = " | ".join([msg['text'] for msg in user_context.messages])
            
            # Создаем объект лида
            lead = Lead(
                telegram_id=user_context.user_id,
                username=user_context.username,
                first_name=user_context.first_name,
                last_name=user_context.last_name,
                source_channel=user_context.channel_info['title'] or str(user_context.channel_info['id']),
                interest_score=analysis.confidence_score,
                message_text=all_messages,
                message_date=user_context.last_activity,
                
                # AI поля
                lead_quality=analysis.lead_quality,
                interests=json.dumps(analysis.interests, ensure_ascii=False),
                buying_signals=json.dumps(analysis.buying_signals, ensure_ascii=False),
                urgency_level=analysis.urgency_level,
                estimated_budget=analysis.estimated_budget,
                timeline=analysis.timeline,
                pain_points=json.dumps(analysis.pain_points, ensure_ascii=False),
                decision_stage=analysis.decision_stage,
                notes="Индивидуальный анализ AI"
            )
            
            # Сохраняем в базу
            await create_lead(lead)
            
            logger.info(f"✅ ИНДИВИДУАЛЬНЫЙ AI ЛИД СОЗДАН: {user_context.first_name} (@{user_context.username})")
            logger.info(f"   Качество: {analysis.lead_quality}")
            logger.info(f"   Уверенность: {analysis.confidence_score}%")
            logger.info(f"   Интересы: {', '.join(analysis.interests)}")
            
            # Отправляем уведомление админам
            await self._notify_admins_about_individual_lead(context, user_context, analysis)
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания индивидуального лида: {e}")
            import traceback
            traceback.print_exc()

    async def _notify_admins_about_individual_lead(self, context: ContextTypes.DEFAULT_TYPE, 
                                                 user_context: UserContext, 
                                                 analysis: AIAnalysisResult):
        """Уведомление админов о новом индивидуальном AI лиде"""
        try:
            admin_ids = self.config.get('bot', {}).get('admin_ids', [])
            if not admin_ids:
                logger.warning("❌ Нет админов для уведомления об индивидуальном лиде")
                return
            
            # Определяем приоритет и эмодзи
            priority_config = {
                'hot': {'emoji': '🔥🔥🔥', 'text': 'ГОРЯЧИЙ ЛИД', 'color': '🟥'},
                'warm': {'emoji': '🔥🔥', 'text': 'ТЕПЛЫЙ ЛИД', 'color': '🟨'},
                'cold': {'emoji': '🔥', 'text': 'ХОЛОДНЫЙ ЛИД', 'color': '🟦'}
            }
            
            priority = priority_config.get(analysis.lead_quality, 
                                         {'emoji': '⭐', 'text': 'ПОТЕНЦИАЛЬНЫЙ ЛИД', 'color': '⬜'})
            
            # Форматируем списки
            interests_text = ', '.join(analysis.interests) if analysis.interests else 'не определены'
            pain_points_text = '\n• '.join(analysis.pain_points) if analysis.pain_points else 'не выявлены'
            buying_signals_text = '\n• '.join(analysis.buying_signals) if analysis.buying_signals else 'не обнаружены'
            
            # Формируем сообщение
            username_text = f"@{user_context.username}" if user_context.username else "без username"
            
            message = f"""{priority['emoji']} <b>{priority['text']}</b> {priority['color']}

👤 <b>ИНДИВИДУАЛЬНЫЙ AI АНАЛИЗ</b>

👤 <b>Контакт:</b> {user_context.first_name} ({username_text})
🆔 <b>ID:</b> <code>{user_context.user_id}</code>
🎯 <b>Уверенность:</b> {analysis.confidence_score}% 
📊 <b>Качество:</b> {analysis.lead_quality.upper()}
📺 <b>Источник:</b> {user_context.channel_info['title']}
💬 <b>Сообщений:</b> {len(user_context.messages)}
⏰ <b>Период активности:</b> {(user_context.last_activity - user_context.first_seen).total_seconds() / 3600:.1f}ч

🎪 <b>Интересы:</b> {interests_text}

🚩 <b>Болевые точки:</b>
• {pain_points_text}

💰 <b>Покупательские сигналы:</b>
• {buying_signals_text}

⚡ <b>Срочность:</b> {analysis.urgency_level}
💵 <b>Бюджет:</b> {analysis.estimated_budget or 'не указан'}
📅 <b>Временные рамки:</b> {analysis.timeline or 'не указаны'}
🎭 <b>Стадия решения:</b> {analysis.decision_stage}

🎯 <b>Рекомендуемое действие:</b>
<i>{analysis.recommended_action}</i>

🔍 <b>Ключевые инсайты:</b>
{chr(10).join([f"• {insight}" for insight in analysis.key_insights])}

🔗 <b>Связаться:</b> <a href="tg://user?id={user_context.user_id}">Открыть диалог</a>"""

            # Отправляем всем админам
            successful_notifications = 0
            for admin_id in admin_ids:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=message,
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
                    successful_notifications += 1
                except Exception as e:
                    logger.error(f"❌ Не удалось отправить уведомление об индивидуальном лиде админу {admin_id}: {e}")
            
            logger.info(f"✅ Уведомления об индивидуальном лиде отправлены {successful_notifications}/{len(admin_ids)} админам")
            
        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомлений об индивидуальном лиде: {e}")

    async def _notify_admins_about_dialogue(self, context: ContextTypes.DEFAULT_TYPE,
                                          dialogue, analysis, created_leads):
        """Уведомление админов о ценном диалоге"""
        try:
            admin_ids = self.config.get('bot', {}).get('admin_ids', [])
            if not admin_ids:
                return
            
            # Определяем приоритет
            if analysis.confidence_score >= 90:
                priority_emoji = "🔥🔥🔥"
                priority_text = "КРИТИЧЕСКИ ВАЖНЫЙ ДИАЛОГ"
            elif analysis.confidence_score >= 80:
                priority_emoji = "🔥🔥"
                priority_text = "ВЫСОКОПРИОРИТЕТНЫЙ ДИАЛОГ"
            else:
                priority_emoji = "🔥"
                priority_text = "ВАЖНЫЙ ДИАЛОГ"
            
            # Формируем информацию об участниках
            participants_info = []
            for user_id, participant in dialogue.participants.items():
                buying_prob = analysis.buying_probability.get(user_id, 0)
                emoji = "🎯" if buying_prob >= 0.7 else "👤"
                username = f"@{participant.username}" if participant.username else f"ID{user_id}"
                participants_info.append(f"{emoji} {participant.first_name} ({username}) - {buying_prob*100:.0f}%")
            
            # Информация о созданных лидах
            leads_info = ""
            if created_leads:
                leads_info = f"\n🎯 <b>Созданы лиды:</b>\n"
                for participant, lead_data in created_leads:
                    username = f"@{participant.username}" if participant.username else "без username"
                    leads_info += f"• {participant.first_name} ({username}) - {lead_data['lead_quality']}\n"
            
            message = f"""{priority_emoji} <b>{priority_text}</b>

🤖 <b>AI АНАЛИЗ ГРУППОВОГО ДИАЛОГА</b>

📺 <b>Канал:</b> {dialogue.channel_title}
🕐 <b>Длительность:</b> {(dialogue.last_activity - dialogue.start_time).total_seconds() / 60:.0f} мин
👥 <b>Участников:</b> {len(dialogue.participants)}
💬 <b>Сообщений:</b> {len(dialogue.messages)}
📊 <b>Уверенность:</b> {analysis.confidence_score}%
🏢 <b>Бизнес-релевантность:</b> {analysis.business_relevance_score}%

📋 <b>Суть диалога:</b>
<i>{analysis.dialogue_summary}</i>

👥 <b>Анализ участников:</b>
{chr(10).join(participants_info)}

🧠 <b>Групповая динамика:</b>
• Стиль принятия решений: {analysis.group_dynamics.get('decision_making_style', 'неопределен')}
• Тональность группы: {analysis.group_dynamics.get('group_sentiment', 'нейтральная')}
• Стадия обсуждения: {analysis.group_dynamics.get('discussion_stage', 'неопределена')}

💡 <b>Ключевые инсайты:</b>
{chr(10).join([f"• {insight}" for insight in analysis.key_insights])}

🎯 <b>Рекомендуемые действия:</b>
{chr(10).join([f"• {action}" for action in analysis.recommended_actions])}

⚡ <b>Следующий шаг:</b> {analysis.next_best_action}
📅 <b>Временные рамки:</b> {analysis.estimated_timeline or 'не определены'}
💰 <b>Бюджет группы:</b> {analysis.group_budget_estimate or 'не определен'}{leads_info}

🔗 <b>Участники диалога:</b>
{chr(10).join([f"<a href='tg://user?id={uid}'>Написать {p.first_name}</a>" for uid, p in dialogue.participants.items()])}"""

            # Отправляем всем админам
            for admin_id in admin_ids:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=message,
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление о диалоге админу {admin_id}: {e}")
            
            logger.info(f"✅ Уведомления о диалоге отправлены админам")
            
        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений о диалоге: {e}")

    async def _update_channel_stats(self, channel_id: str, message_id: int, lead_found: bool):
        """Обновление статистики канала"""
        try:
            leads_count = 1 if lead_found else 0
            await update_channel_stats(channel_id, message_id, leads_count)
            logger.info(f"📊 Статистика канала обновлена: {channel_id}, лид={lead_found}")
        except Exception as e:
            logger.error(f"❌ Ошибка обновления статистики: {e}")

    def is_channel_monitored(self, chat_id: int, chat_username: str = None) -> bool:
        """Проверка мониторинга канала"""
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

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса интегрированного парсера"""
        status = {
            'enabled': self.enabled,
            'channels_count': len(self.channels),
            'channels': self.channels,
            'min_confidence_score': self.min_confidence_score,
            'context_window_hours': self.context_window_hours,
            'individual_active_users': len(self.user_contexts),
            'individual_analysis_cache_size': len(self.analysis_cache),
            'individual_processed_leads_count': len(self.processed_leads),
            'dialogue_analysis_enabled': self.dialogue_analysis_enabled,
            'prefer_dialogue_analysis': self.prefer_dialogue_analysis
        }
        
        if self.dialogue_tracker:
            status['dialogue_tracker'] = {
                'active_dialogues': len(self.dialogue_tracker.active_dialogues),
                'min_participants': self.dialogue_tracker.min_participants,
                'min_messages': self.dialogue_tracker.min_messages,
                'dialogue_timeout_minutes': self.dialogue_tracker.dialogue_timeout.total_seconds() / 60
            }
        
        return status

# Алиасы для обратной совместимости
AIContextParser = IntegratedAIContextParser

__all__ = [
    'IntegratedAIContextParser',
    'AIContextParser',
    'DialogueTracker',
    'DialogueAnalyzer',
    'DialogueContext',
    'DialogueParticipant',
    'DialogueMessage',
    'DialogueAnalysisResult',
    'AIAnalysisResult',
    'UserContext'
]
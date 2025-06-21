"""
myparser/main_parser.py - ПОЛНОСТЬЮ ИСПРАВЛЕННЫЙ AI парсер
Объединяет все функции в одном модуле без зависимостей
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

# === ТРЕКЕР ДИАЛОГОВ ===

class DialogueTracker:
    """Трекер диалогов"""
    
    def __init__(self, config):
        self.config = config
        self.active_dialogues: Dict[str, DialogueContext] = {}
        self.dialogue_timeout = timedelta(minutes=2)
        self.min_participants = 2
        self.min_messages = 2
        
        # Сигналы для немедленного анализа
        self.buying_signals = [
            'хочу купить', 'готов заказать', 'какая цена', 'сколько стоит',
            'нужен бот', 'заказать crm', 'срочно нужно', 'бюджет',
            'покупаем', 'планируем купить', 'рассматриваем покупку'
        ]
        
        logger.info("DialogueTracker инициализирован")

    def get_dialogue_id(self, channel_id: int, start_time: datetime) -> str:
        """Генерация ID диалога"""
        return f"dialogue_{channel_id}_{start_time.strftime('%Y%m%d_%H%M%S')}"

    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        """Обработка сообщения для диалогов"""
        try:
            chat_id = update.effective_chat.id
            user = update.effective_user
            message = update.message
            
            if not user or not message or not message.text:
                return None
            
            # Очищаем завершенные диалоги
            await self._cleanup_expired_dialogues()
            
            # Ищем активный диалог
            active_dialogue = self._find_active_dialogue(chat_id)
            
            # Проверяем принадлежность к диалогу
            if active_dialogue and self._belongs_to_dialogue(message, active_dialogue, user):
                await self._add_message_to_dialogue(active_dialogue, user, message)
                logger.info(f"📝 Сообщение добавлено к диалогу {active_dialogue.dialogue_id}")
                return active_dialogue.dialogue_id
            
            # Проверяем начало нового диалога
            if self._should_start_new_dialogue(message, user):
                new_dialogue = await self._start_new_dialogue(chat_id, update.effective_chat.title, user, message)
                logger.info(f"🆕 Начат новый диалог: {new_dialogue.dialogue_id}")
                return new_dialogue.dialogue_id
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения для диалога: {e}")
            return None

    def _find_active_dialogue(self, channel_id: int) -> Optional[DialogueContext]:
        """Поиск активного диалога"""
        for dialogue in self.active_dialogues.values():
            if (dialogue.channel_id == channel_id and 
                datetime.now() - dialogue.last_activity < self.dialogue_timeout):
                return dialogue
        return None

    def _belongs_to_dialogue(self, message, dialogue: DialogueContext, user: User) -> bool:
        """Проверка принадлежности сообщения к диалогу"""
        # Ответ на сообщение
        if message.reply_to_message:
            reply_user_id = message.reply_to_message.from_user.id
            if reply_user_id in dialogue.participants:
                return True
        
        # Участник уже в диалоге
        if user.id in dialogue.participants:
            return True
        
        # Контекстная связь
        message_text = message.text.lower()
        if dialogue.is_business_related:
            business_keywords = ['crm', 'бот', 'автоматизация', 'система', 'заказ', 'цена']
            if any(keyword in message_text for keyword in business_keywords):
                return True
        
        return False

    def _should_start_new_dialogue(self, message, user: User) -> bool:
        """Проверка начала нового диалога"""
        # Ответ на чужое сообщение
        if message.reply_to_message and message.reply_to_message.from_user.id != user.id:
            return True
        
        # Вопросы
        if self._is_question(message.text):
            return True
        
        # Деловые сигналы
        if self._has_business_signals(message.text):
            return True
        
        return False

    def _is_question(self, text: str) -> bool:
        """Проверка на вопрос"""
        question_indicators = ['?', 'как', 'что', 'где', 'когда', 'почему', 'можете']
        text_lower = text.lower()
        return any(indicator in text_lower for indicator in question_indicators)

    def _has_business_signals(self, text: str) -> bool:
        """Проверка деловых сигналов"""
        text_lower = text.lower()
        return any(signal in text_lower for signal in self.buying_signals)

    async def _start_new_dialogue(self, channel_id: int, channel_title: str, user: User, message) -> DialogueContext:
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
            is_business_related=self._has_business_signals(message.text)
        )
        
        await self._add_message_to_dialogue(dialogue, user, message)
        self.active_dialogues[dialogue_id] = dialogue
        return dialogue

    async def _add_message_to_dialogue(self, dialogue: DialogueContext, user: User, message):
        """Добавление сообщения к диалогу"""
        current_time = datetime.now()
        
        # Обновляем или создаем участника
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

    async def _cleanup_expired_dialogues(self):
        """Очистка завершенных диалогов"""
        current_time = datetime.now()
        expired_dialogues = []
        
        for dialogue_id, dialogue in self.active_dialogues.items():
            if current_time - dialogue.last_activity > self.dialogue_timeout:
                expired_dialogues.append(dialogue_id)
        
        for dialogue_id in expired_dialogues:
            completed_dialogue = self.active_dialogues.pop(dialogue_id)
            logger.info(f"🏁 Диалог завершен: {dialogue_id} ({len(completed_dialogue.messages)} сообщений)")

    def should_trigger_immediate_analysis(self, dialogue_id: str, message_text: str) -> bool:
        """Проверка триггеров немедленного анализа"""
        text_lower = message_text.lower()
        return any(signal in text_lower for signal in self.buying_signals)

    def get_ready_for_analysis_dialogues(self) -> List[DialogueContext]:
        """Получение диалогов готовых к анализу"""
        ready_dialogues = []
        
        for dialogue in self.active_dialogues.values():
            if (len(dialogue.participants) >= self.min_participants and 
                len(dialogue.messages) >= self.min_messages):
                ready_dialogues.append(dialogue)
        
        return ready_dialogues

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
        """AI анализ диалога"""
        # Подготавливаем данные для анализа
        participants_info = []
        for user_id, participant in dialogue.participants.items():
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

Верни JSON:
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
            "role_in_decision": "decision_maker|influencer|observer|budget_holder"
        }}
    ],
    "dialogue_summary": "краткое описание сути",
    "key_insights": ["ключевые инсайты"],
    "recommended_actions": ["конкретные рекомендации"],
    "next_best_action": "следующий шаг",
    "estimated_timeline": "временные рамки или null",
    "group_budget_estimate": "оценка бюджета или null"
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
        """Парсинг AI ответа"""
        try:
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                raise ValueError("JSON не найден")
            
            data = json.loads(json_match.group())
            
            # ИСПРАВЛЕНИЕ: Правильно обрабатываем анализ участников
            participant_analysis = {}
            for lead_data in data.get('potential_leads', []):
                user_id = lead_data['user_id']
                
                # Обновляем данные участника
                if user_id in dialogue.participants:
                    participant = dialogue.participants[user_id]
                    participant.lead_probability = lead_data.get('lead_probability', 0) / 100.0
                    
                    participant_analysis[user_id] = {
                        'lead_probability': lead_data.get('lead_probability', 0),
                        'lead_quality': lead_data.get('lead_quality', 'cold'),
                        'key_signals': lead_data.get('key_signals', []),
                        'role_in_decision': lead_data.get('role_in_decision', 'observer')
                    }
            
            return DialogueAnalysisResult(
                dialogue_id=dialogue.dialogue_id,
                is_valuable_dialogue=data.get('is_valuable_dialogue', False),
                confidence_score=data.get('confidence_score', 0),
                potential_leads=data.get('potential_leads', []),
                business_relevance_score=data.get('business_relevance_score', 0),
                dialogue_summary=data.get('dialogue_summary', ''),
                key_insights=data.get('key_insights', []),
                recommended_actions=data.get('recommended_actions', []),
                next_best_action=data.get('next_best_action', ''),
                estimated_timeline=data.get('estimated_timeline'),
                group_budget_estimate=data.get('group_budget_estimate'),
                participant_analysis=participant_analysis
            )
            
        except Exception as e:
            logger.error(f"Ошибка парсинга AI ответа: {e}")
            return self._simple_dialogue_analysis(dialogue)

    def _simple_dialogue_analysis(self, dialogue: DialogueContext) -> DialogueAnalysisResult:
        """Упрощенный анализ без AI"""
        potential_leads = []
        participant_analysis = {}
        
        for user_id, participant in dialogue.participants.items():
            # Вычисляем скор участника
            score = min(100, participant.buying_signals_count * 30 + participant.message_count * 10)
            
            if score >= 50:
                lead_quality = "hot" if score >= 80 else "warm"
                
                # ИСПРАВЛЕНИЕ: Обновляем вероятность участника
                participant.lead_probability = score / 100.0
                
                potential_leads.append({
                    'user_id': user_id,
                    'lead_probability': score,
                    'lead_quality': lead_quality,
                    'key_signals': [f"Покупательские сигналы: {participant.buying_signals_count}"],
                    'role_in_decision': participant.role
                })
                
                participant_analysis[user_id] = {
                    'lead_probability': score,
                    'lead_quality': lead_quality,
                    'key_signals': [f"Сигналы: {participant.buying_signals_count}"],
                    'role_in_decision': participant.role
                }
        
        return DialogueAnalysisResult(
            dialogue_id=dialogue.dialogue_id,
            is_valuable_dialogue=len(potential_leads) > 0,
            confidence_score=75 if potential_leads else 30,
            potential_leads=potential_leads,
            business_relevance_score=80 if dialogue.is_business_related else 20,
            dialogue_summary=f"Диалог с {len(dialogue.participants)} участниками в {dialogue.channel_title}",
            key_insights=[f"Обнаружено {len(potential_leads)} потенциальных лидов"],
            recommended_actions=["Связаться с потенциальными лидами"],
            next_best_action="Связаться с лидами",
            estimated_timeline="1-2 недели",
            group_budget_estimate="не определен",
            participant_analysis=participant_analysis
        )

# === ГЛАВНЫЙ ПАРСЕР ===

class UnifiedAIParser:
    """Объединенный AI парсер"""
    
    def __init__(self, config):
        self.config = config
        self.parsing_config = config.get('parsing', {})
        
        # Основные настройки
        self.enabled = self.parsing_config.get('enabled', True)
        self.channels = self._parse_channels()
        self.min_confidence_score = self.parsing_config.get('min_confidence_score', 70)
        
        # Компоненты
        self.dialogue_analysis_enabled = self.parsing_config.get('dialogue_analysis_enabled', True)
        self.dialogue_tracker = DialogueTracker(config) if self.dialogue_analysis_enabled else None
        self.dialogue_analyzer = DialogueAnalyzer(config) if self.dialogue_analysis_enabled else None
        
        # Индивидуальный анализ
        self.user_contexts: Dict[int, UserContext] = {}
        self.processed_leads: Dict[int, datetime] = {}
        self.last_dialogue_analysis: Dict[str, datetime] = {}
        
        logger.info(f"UnifiedAIParser инициализирован:")
        logger.info(f"  - Каналов: {len(self.channels)}")
        logger.info(f"  - Анализ диалогов: {self.dialogue_analysis_enabled}")
        logger.info(f"  - Мин. уверенность: {self.min_confidence_score}%")

    def _parse_channels(self) -> List[str]:
        """Парсинг каналов"""
        channels_raw = self.parsing_config.get('channels', [])
        if isinstance(channels_raw, list):
            return [str(ch) for ch in channels_raw]
        elif isinstance(channels_raw, (str, int)):
            return [str(channels_raw)]
        return []

    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Главная функция обработки сообщения"""
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
            
            # Параллельная обработка
            dialogue_processed = False
            
            # Анализ диалогов
            if self.dialogue_analysis_enabled and self.dialogue_tracker:
                dialogue_id = await self.dialogue_tracker.process_message(update, context)
                
                if dialogue_id:
                    logger.info(f"📝 Сообщение обработано в диалоге: {dialogue_id}")
                    
                    # Проверяем триггеры
                    if (self.dialogue_tracker.should_trigger_immediate_analysis(dialogue_id, message.text) or
                        await self._should_analyze_dialogue_now(dialogue_id)):
                        logger.info(f"🔥 НЕМЕДЛЕННЫЙ анализ диалога {dialogue_id}!")
                        await self._analyze_dialogue_immediately(dialogue_id, context)
                        dialogue_processed = True
            
            # Индивидуальный анализ
            if not dialogue_processed:
                logger.info("👤 Запускаем ПАРАЛЛЕЛЬНЫЙ индивидуальный анализ")
                await self._process_individual_message(update, context)
            
        except Exception as e:
            logger.error(f"❌ Ошибка в исправленном парсере: {e}")

    async def _should_analyze_dialogue_now(self, dialogue_id: str) -> bool:
        """Проверка готовности диалога к анализу"""
        if dialogue_id not in self.dialogue_tracker.active_dialogues:
            return False
        
        dialogue = self.dialogue_tracker.active_dialogues[dialogue_id]
        
        # Достаточно участников и сообщений
        if (len(dialogue.participants) >= 2 and len(dialogue.messages) >= 2):
            return True
        
        # Есть покупательские сигналы
        total_signals = sum(p.buying_signals_count for p in dialogue.participants.values())
        if total_signals >= 1:
            return True
        
        return False

    async def _analyze_dialogue_immediately(self, dialogue_id: str, context: ContextTypes.DEFAULT_TYPE):
        """Немедленный анализ диалога"""
        try:
            if dialogue_id not in self.dialogue_tracker.active_dialogues:
                return
            
            dialogue = self.dialogue_tracker.active_dialogues[dialogue_id]
            logger.info(f"🔥 НЕМЕДЛЕННЫЙ анализ диалога: {dialogue_id}")
            
            # Анализируем
            analysis_result = await self.dialogue_analyzer.analyze_dialogue(dialogue)
            
            if analysis_result:
                self.last_dialogue_analysis[dialogue_id] = datetime.now()
                
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
        """Обработка результатов анализа диалога"""
        try:
            logger.info(f"💎 Ценный диалог обнаружен: {dialogue.dialogue_id}")
            
            # Создаем лиды
            created_leads = []
            for lead_data in analysis.potential_leads:
                if lead_data['lead_probability'] >= self.min_confidence_score:
                    user_id = lead_data['user_id']
                    participant = dialogue.participants.get(user_id)
                    
                    if participant:
                        lead = await self._create_dialogue_lead(participant, dialogue, lead_data, analysis)
                        if lead:
                            created_leads.append((participant, lead_data))
            
            # Уведомляем админов
            await self._notify_admins_about_dialogue(context, dialogue, analysis, created_leads)
            
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
                message_text=" | ".join(participant_messages),
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

    async def _notify_admins_about_dialogue(self, context, dialogue, analysis, created_leads):
        """Уведомление админов о диалоге"""
        try:
            admin_ids = self.config.get('bot', {}).get('admin_ids', [])
            if not admin_ids:
                return
            
            # ИСПРАВЛЕНИЕ: Правильно отображаем вероятности участников
            participants_info = []
            for user_id, participant in dialogue.participants.items():
                # Получаем правильную вероятность из анализа
                prob = 0
                for lead_data in analysis.potential_leads:
                    if lead_data['user_id'] == user_id:
                        prob = lead_data.get('lead_probability', 0)
                        break
                
                emoji = "🎯" if prob >= 70 else "👤"
                username = f"@{participant.username}" if participant.username else f"ID{user_id}"
                participants_info.append(f"{emoji} {participant.first_name} ({username}) - {prob}%")
            
            message = f"""🔥 ЦЕННЫЙ ДИАЛОГ

🤖 ИСПРАВЛЕННЫЙ AI АНАЛИЗ ДИАЛОГА

📺 Канал: {dialogue.channel_title}
🕐 Длительность: {(dialogue.last_activity - dialogue.start_time).total_seconds() / 60:.0f} мин
👥 Участников: {len(dialogue.participants)}
💬 Сообщений: {len(dialogue.messages)}
📊 Уверенность: {analysis.confidence_score}%
🏢 Бизнес-релевантность: {analysis.business_relevance_score}%

📋 Суть диалога:
{analysis.dialogue_summary}

👥 Анализ участников:
{chr(10).join(participants_info)}

💡 Ключевые инсайты:
{chr(10).join([f"• {insight}" for insight in analysis.key_insights])}

🎯 Рекомендации:
{chr(10).join([f"• {action}" for action in analysis.recommended_actions])}

⚡ Следующий шаг: {analysis.next_best_action}
📅 Временные рамки: {analysis.estimated_timeline or 'не определены'}
💰 Бюджет группы: {analysis.group_budget_estimate or 'не определен'}"""

            if created_leads:
                message += f"\n\n🎯 Созданы лиды:\n"
                for participant, lead_data in created_leads:
                    username = f"@{participant.username}" if participant.username else "без username"
                    message += f"• {participant.first_name} ({username}) - {lead_data['lead_quality']}\n"
            
            # Отправляем админам
            for admin_id in admin_ids:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=message,
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")
            
            logger.info("✅ Уведомления о диалоге отправлены")
            
        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений: {e}")

    async def _process_individual_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка индивидуального сообщения"""
        try:
            user = update.effective_user
            message = update.message
            
            # Простой анализ для индивидуальных сообщений
            if self._has_strong_business_signals(message.text):
                logger.info("🔥 Сильные бизнес-сигналы - создаем лид")
                
                lead = Lead(
                    telegram_id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    source_channel=update.effective_chat.title or f"Channel_{update.effective_chat.id}",
                    interest_score=85,
                    message_text=message.text,
                    message_date=datetime.now(),
                    lead_quality="hot",
                    urgency_level="high",
                    notes="Индивидуальный анализ - сильные сигналы"
                )
                
                await create_lead(lead)
                logger.info(f"✅ Индивидуальный лид создан: {user.first_name}")
                
        except Exception as e:
            logger.error(f"Ошибка индивидуального анализа: {e}")

    def _has_strong_business_signals(self, text: str) -> bool:
        """Проверка сильных бизнес-сигналов"""
        strong_signals = [
            'хочу купить', 'готов заказать', 'какая цена', 'сколько стоит',
            'нужен бот', 'заказать crm', 'бюджет', 'покупаем'
        ]
        text_lower = text.lower()
        return any(signal in text_lower for signal in strong_signals)

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
            'mode': 'unified_fixed'
        }
        
        if self.dialogue_tracker:
            status['dialogue_tracker'] = {
                'active_dialogues': len(self.dialogue_tracker.active_dialogues),
                'min_participants': self.dialogue_tracker.min_participants,
                'min_messages': self.dialogue_tracker.min_messages,
                'dialogue_timeout_minutes': self.dialogue_tracker.dialogue_timeout.total_seconds() / 60
            }
        
        return status

# Алиас для совместимости
AIContextParser = UnifiedAIParser
IntegratedAIContextParser = UnifiedAIParser
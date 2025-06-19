"""
AI Dialogue Context Analyzer - Анализатор диалогов с расширенным контекстом
"""

import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Set, Tuple
from dataclasses import dataclass, asdict
from telegram import Update, User
from telegram.ext import ContextTypes

from database.operations import create_lead, update_channel_stats
from database.models import Lead
from ai.claude_client import get_claude_client

logger = logging.getLogger(__name__)

@dataclass
class DialogueParticipant:
    """Участник диалога"""
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    role: str  # initiator, responder, observer, influencer
    message_count: int = 0
    first_message_time: Optional[datetime] = None
    last_message_time: Optional[datetime] = None
    engagement_level: str = "low"  # low, medium, high
    buying_signals_count: int = 0
    influence_score: int = 0  # насколько влияет на других участников

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
    sentiment: str = "neutral"  # positive, negative, neutral
    urgency_level: str = "none"  # immediate, high, medium, low, none

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
    dialogue_type: str = "discussion"  # question_answer, discussion, negotiation, complaint
    is_business_related: bool = False
    overall_sentiment: str = "neutral"
    decision_stage: str = "awareness"  # awareness, consideration, decision, post_purchase
    group_buying_probability: float = 0.0

@dataclass
class DialogueAnalysisResult:
    """Результат анализа диалога"""
    dialogue_id: str
    is_valuable_dialogue: bool
    confidence_score: int
    potential_leads: List[Dict[str, Any]]  # список потенциальных лидов с их характеристиками
    group_dynamics: Dict[str, Any]
    business_relevance_score: int
    recommended_actions: List[str]
    key_insights: List[str]
    dialogue_summary: str
    participant_analysis: Dict[int, Dict[str, Any]]
    buying_probability: Dict[str, float]  # вероятность покупки для каждого участника
    influence_map: Dict[int, List[int]]  # кто на кого влияет
    next_best_action: str
    estimated_timeline: Optional[str]
    group_budget_estimate: Optional[str]

class DialogueTracker:
    """Отслеживание и управление диалогами"""
    
    def __init__(self, config):
        self.config = config
        self.active_dialogues: Dict[str, DialogueContext] = {}
        self.dialogue_timeout = timedelta(minutes=15)  # диалог считается завершенным через 15 мин тишины
        self.min_participants = 2  # минимум участников для диалога
        self.min_messages = 3  # минимум сообщений для анализа
        
        # Параметры обнаружения диалогов
        self.reply_window = timedelta(minutes=5)  # окно для связывания сообщений в диалог
        self.max_dialogue_duration = timedelta(hours=2)  # максимальная длительность одного диалога
        
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
            
            # Очищаем завершенные диалоги
            await self._cleanup_expired_dialogues()
            
            # Ищем активный диалог для этого канала
            active_dialogue = self._find_active_dialogue(chat_id)
            
            # Определяем, является ли это частью диалога
            is_dialogue_message = self._is_dialogue_message(message, active_dialogue)
            
            if is_dialogue_message and active_dialogue:
                # Добавляем сообщение к существующему диалогу
                await self._add_message_to_dialogue(active_dialogue, user, message)
                logger.info(f"📝 Сообщение добавлено к диалогу {active_dialogue.dialogue_id}")
                return active_dialogue.dialogue_id
            
            elif self._should_start_new_dialogue(chat_id, user, message):
                # Начинаем новый диалог
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
        
        # Проверяем временное окно
        time_diff = datetime.now() - active_dialogue.last_activity
        if time_diff > self.dialogue_timeout:
            return False
        
        # Проверяем, отвечает ли на предыдущие сообщения
        if message.reply_to_message:
            reply_user_id = message.reply_to_message.from_user.id
            if reply_user_id in active_dialogue.participants:
                return True
        
        # Проверяем участие пользователя в диалоге
        if message.from_user.id in active_dialogue.participants:
            return True
        
        # Проверяем контекстные сигналы (упоминания, похожие темы)
        return self._has_contextual_connection(message, active_dialogue)

    def _has_contextual_connection(self, message, dialogue: DialogueContext) -> bool:
        """Проверка контекстной связи с диалогом"""
        message_text = message.text.lower()
        
        # Проверяем упоминания участников
        for participant in dialogue.participants.values():
            if participant.username and f"@{participant.username.lower()}" in message_text:
                return True
        
        # Проверяем тематические слова (если диалог о бизнесе)
        if dialogue.is_business_related:
            business_keywords = ['crm', 'бот', 'автоматизация', 'система', 'заказ', 'цена', 'стоимость']
            if any(keyword in message_text for keyword in business_keywords):
                return True
        
        return False

    def _should_start_new_dialogue(self, channel_id: int, user: User, message) -> bool:
        """Определение нужно ли начинать новый диалог"""
        # Проверяем, отвечает ли на чужое сообщение
        if message.reply_to_message and message.reply_to_message.from_user.id != user.id:
            return True
        
        # Проверяем наличие вопросительных конструкций
        if self._contains_question_patterns(message.text):
            return True
        
        # Проверяем деловые/покупательские сигналы
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
        
        # Создаем первого участника
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
        
        # Создаем диалог
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
        
        # Добавляем первое сообщение
        await self._add_message_to_dialogue(dialogue, user, message)
        
        self.active_dialogues[dialogue_id] = dialogue
        return dialogue

    async def _add_message_to_dialogue(self, dialogue: DialogueContext, user: User, message):
        """Добавление сообщения к диалогу"""
        current_time = datetime.now()
        
        # Обновляем или создаем участника
        if user.id not in dialogue.participants:
            # Определяем роль нового участника
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
        
        # Анализируем сообщение на покупательские сигналы
        buying_signals = self._extract_buying_signals(message.text)
        if buying_signals:
            participant.buying_signals_count += len(buying_signals)
        
        # Создаем объект сообщения
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
        
        # Обновляем метаданные диалога
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
            # Диалог считается завершенным если нет активности или превышена максимальная длительность
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
            # Диалог готов для анализа если:
            # 1. Есть достаточно участников и сообщений
            # 2. Прошло достаточно времени с последней активности
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
            
            # Подготавливаем данные для AI анализа
            analysis_prompt = self._create_dialogue_analysis_prompt(dialogue)
            
            # Отправляем запрос в Claude
            response = await asyncio.wait_for(
                self.claude_client.client.messages.create(
                    model=self.claude_client.model,
                    max_tokens=3000,
                    messages=[{"role": "user", "content": analysis_prompt}],
                    temperature=0.1
                ),
                timeout=20.0
            )
            
            # Парсим ответ
            analysis_result = self._parse_dialogue_analysis_response(response.content[0].text, dialogue)
            
            logger.info(f"✅ Анализ диалога завершен: ценность={analysis_result.is_valuable_dialogue}, лидов={len(analysis_result.potential_leads)}")
            
            return analysis_result
            
        except Exception as e:
            logger.error(f"Ошибка анализа диалога: {e}")
            return self._simple_dialogue_analysis(dialogue)

    def _create_dialogue_analysis_prompt(self, dialogue: DialogueContext) -> str:
        """Создание промпта для анализа диалога"""
        
        # Формируем информацию об участниках
        participants_info = []
        for user_id, participant in dialogue.participants.items():
            info = f"""
Участник {participant.first_name} (@{participant.username or 'без_username'}):
- Роль: {participant.role}
- Сообщений: {participant.message_count}
- Покупательские сигналы: {participant.buying_signals_count}
- Уровень вовлеченности: {participant.engagement_level}"""
            participants_info.append(info)
        
        # Формируем историю сообщений
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
}}

КРИТЕРИИ ОЦЕНКИ:
- Ценный диалог: есть явные покупательские сигналы или обсуждение бизнес-задач
- Потенциальные лиды: участники с покупательскими намерениями или влияющие на решение
- Групповая динамика: как участники влияют друг на друга в процессе принятия решений
- Обрати особое внимание на скрытые сигналы и подтекст
- Учитывай роли участников: кто принимает решения, кто влияет, кто наблюдает

ВАЖНО:
- Анализируй не только прямые высказывания, но и контекст, подтекст
- Определяй иерархию влияния между участниками
- Ищи признаки группового принятия решений
- Выявляй скрытых лиц, принимающих решения
- Оценивай готовность к покупке группы в целом"""

    def _parse_dialogue_analysis_response(self, response_text: str, dialogue: DialogueContext) -> DialogueAnalysisResult:
        """Парсинг ответа AI анализа диалога"""
        try:
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                raise ValueError("JSON не найден в ответе")
            
            data = json.loads(json_match.group())
            
            # Создаем детальный анализ участников
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
            
            # Парсим карту влияния
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
            # Простая оценка на основе активности и сигналов
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

class EnhancedAIContextParser:
    """Расширенный AI парсер с анализом диалогов"""
    
    def __init__(self, config):
        self.config = config
        self.dialogue_tracker = DialogueTracker(config)
        self.dialogue_analyzer = DialogueAnalyzer(config)
        
        # Настройки
        self.analysis_enabled = config.get('parsing', {}).get('dialogue_analysis_enabled', True)
        self.min_confidence_for_notification = config.get('parsing', {}).get('min_dialogue_confidence', 75)
        
        # Задача для периодического анализа диалогов
        self.analysis_task = None
        
        logger.info("EnhancedAIContextParser с анализом диалогов инициализирован")

    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка сообщения с учетом диалогов"""
        try:
            # Сначала обрабатываем как часть диалога
            dialogue_id = await self.dialogue_tracker.process_message(update, context)
            
            if dialogue_id:
                logger.info(f"📝 Сообщение обработано в диалоге: {dialogue_id}")
                
                # Проверяем, готов ли диалог для анализа
                await self._check_and_analyze_dialogues(context)
            
            # Здесь можно добавить обычную логику анализа отдельных сообщений
            # if not dialogue_id:
            #     await self.process_individual_message(update, context)
            
        except Exception as e:
            logger.error(f"Ошибка в расширенном AI парсере: {e}")

    async def _check_and_analyze_dialogues(self, context: ContextTypes.DEFAULT_TYPE):
        """Проверка и анализ готовых диалогов"""
        if not self.analysis_enabled:
            return
        
        try:
            completed_dialogues = self.dialogue_tracker.get_completed_dialogues_for_analysis()
            
            for dialogue in completed_dialogues:
                logger.info(f"🔍 Анализируем диалог: {dialogue.dialogue_id}")
                
                analysis_result = await self.dialogue_analyzer.analyze_dialogue(dialogue)
                
                if analysis_result and analysis_result.is_valuable_dialogue:
                    await self._process_dialogue_analysis_result(dialogue, analysis_result, context)
                
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
                if lead_data['lead_probability'] >= 70:  # Высокая вероятность
                    user_id = lead_data['user_id']
                    participant = dialogue.participants.get(user_id)
                    
                    if participant:
                        lead = await self._create_lead_from_dialogue_participant(
                            participant, dialogue, lead_data, analysis
                        )
                        if lead:
                            created_leads.append((participant, lead_data))
            
            # Отправляем уведомление админам о ценном диалоге
            if (analysis.confidence_score >= self.min_confidence_for_notification or 
                created_leads):
                await self._notify_admins_about_dialogue(context, dialogue, analysis, created_leads)
            
        except Exception as e:
            logger.error(f"Ошибка обработки результатов анализа: {e}")

    async def _create_lead_from_dialogue_participant(self, participant: DialogueParticipant,
                                                   dialogue: DialogueContext,
                                                   lead_data: Dict[str, Any],
                                                   analysis: DialogueAnalysisResult) -> Optional[Lead]:
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

    async def _notify_admins_about_dialogue(self, context: ContextTypes.DEFAULT_TYPE,
                                          dialogue: DialogueContext,
                                          analysis: DialogueAnalysisResult,
                                          created_leads: List[Tuple]):
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

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса расширенного парсера"""
        return {
            'dialogue_analysis_enabled': self.analysis_enabled,
            'active_dialogues': len(self.dialogue_tracker.active_dialogues),
            'min_confidence_for_notification': self.min_confidence_for_notification,
            'dialogue_tracker_status': {
                'min_participants': self.dialogue_tracker.min_participants,
                'min_messages': self.dialogue_tracker.min_messages,
                'dialogue_timeout_minutes': self.dialogue_tracker.dialogue_timeout.total_seconds() / 60
            }
        }
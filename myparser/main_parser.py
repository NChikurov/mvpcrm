"""
myparser/main_parser.py - ОПТИМИЗИРОВАННЫЙ AI парсер
Рефакторинг согласно SOLID принципам, оптимизация производительности
"""

import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple, Protocol
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from telegram import Update, User
from telegram.ext import ContextTypes

from database.operations import create_lead, update_channel_stats
from database.models import Lead
from ai.claude_client import get_claude_client

logger = logging.getLogger(__name__)

# === ПРОТОКОЛЫ И ИНТЕРФЕЙСЫ (SOLID - Interface Segregation) ===

class MessageAnalyzer(Protocol):
    """Протокол для анализаторов сообщений"""
    async def analyze(self, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        ...

class NotificationSender(Protocol):
    """Протокол для отправки уведомлений"""
    async def send_notification(self, notification_data: Dict[str, Any]) -> bool:
        ...

class DialogueTracker(Protocol):
    """Протокол для трекинга диалогов"""
    async def track_message(self, update: Update) -> Optional[str]:
        ...

# === МОДЕЛИ ДАННЫХ ===

@dataclass
class ParticipantInfo:
    """Информация об участнике диалога"""
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    role: str = "participant"
    message_count: int = 0
    engagement_score: float = 0.0
    buying_signals: List[str] = field(default_factory=list)
    influence_level: float = 0.0

    @property
    def display_name(self) -> str:
        return self.first_name or f"User_{self.user_id}"

@dataclass
class DialogueContext:
    """Контекст диалога"""
    dialogue_id: str
    channel_id: int
    channel_title: str
    participants: Dict[int, ParticipantInfo]
    messages: List[Dict[str, Any]]
    start_time: datetime
    last_activity: datetime
    business_score: float = 0.0
    urgency_level: str = "low"
    estimated_value: Optional[float] = None

@dataclass
class AnalysisResult:
    """Результат анализа"""
    is_valuable: bool
    confidence_score: float
    business_relevance: float
    potential_leads: List[Dict[str, Any]]
    recommended_actions: List[str]
    next_steps: str
    priority_level: str = "medium"

# === ФАБРИКИ (SOLID - Factory Pattern) ===

class AnalyzerFactory:
    """Фабрика анализаторов"""
    
    @staticmethod
    def create_message_analyzer(analyzer_type: str) -> MessageAnalyzer:
        if analyzer_type == "claude":
            return ClaudeMessageAnalyzer()
        elif analyzer_type == "simple":
            return SimpleMessageAnalyzer()
        else:
            raise ValueError(f"Unknown analyzer type: {analyzer_type}")

class NotificationFactory:
    """Фабрика уведомлений"""
    
    @staticmethod
    def create_sender(sender_type: str) -> NotificationSender:
        if sender_type == "telegram":
            return TelegramNotificationSender()
        elif sender_type == "webhook":
            return WebhookNotificationSender()
        else:
            raise ValueError(f"Unknown sender type: {sender_type}")

# === СТРАТЕГИИ АНАЛИЗА (SOLID - Strategy Pattern) ===

class BaseMessageAnalyzer(ABC):
    """Базовый класс для анализаторов сообщений"""
    
    @abstractmethod
    async def analyze(self, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        pass

class ClaudeMessageAnalyzer(BaseMessageAnalyzer):
    """Анализатор с использованием Claude API"""
    
    def __init__(self):
        self.client = get_claude_client()
        self._cache = {}  # Простой кэш для избежания повторных запросов
    
    async def analyze(self, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        # Проверяем кэш
        cache_key = f"{hash(message)}_{hash(str(context))}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        if not self.client or not self.client.client:
            return SimpleMessageAnalyzer().analyze(message, context)
        
        try:
            prompt = self._build_optimized_prompt(message, context)
            
            response = await asyncio.wait_for(
                self.client.client.messages.create(
                    model=self.client.model,
                    max_tokens=1500,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1
                ),
                timeout=10.0
            )
            
            result = self._parse_response(response.content[0].text)
            
            # Кэшируем результат
            self._cache[cache_key] = result
            if len(self._cache) > 100:  # Ограничиваем размер кэша
                self._cache.clear()
            
            return result
            
        except Exception as e:
            logger.warning(f"Claude analysis failed: {e}, falling back to simple analysis")
            return await SimpleMessageAnalyzer().analyze(message, context)
    
    def _build_optimized_prompt(self, message: str, context: Dict[str, Any]) -> str:
        """Оптимизированный промпт для анализа"""
        participants_info = context.get('participants_info', '')
        dialogue_history = context.get('dialogue_history', '')
        
        return f"""Проанализируй бизнес-диалог и верни ТОЛЬКО JSON без дополнительного текста:

ДИАЛОГ:
{dialogue_history}

УЧАСТНИКИ:
{participants_info}

НОВОЕ СООБЩЕНИЕ: "{message}"

ЗАДАЧА: Определи покупательские намерения и роли участников.

ВАЖНО: Включи ВСЕХ участников с их реальными user_id в potential_leads.

JSON:
{{
    "is_valuable_dialogue": boolean,
    "confidence_score": число_0_100,
    "business_relevance_score": число_0_100,
    "potential_leads": [
        {{
            "user_id": конкретный_id,
            "lead_probability": число_0_100,
            "lead_quality": "hot/warm/cold",
            "key_signals": ["список"],
            "role_in_decision": "decision_maker/influencer/observer/budget_holder",
            "urgency_indicators": ["список"],
            "estimated_budget_range": "диапазон или null"
        }}
    ],
    "dialogue_summary": "краткое описание",
    "key_insights": ["список инсайтов"],
    "recommended_actions": ["список действий"],
    "next_best_action": "следующий шаг",
    "priority_level": "low/medium/high/urgent",
    "estimated_timeline": "сроки",
    "group_dynamics": {{
        "decision_making_style": "описание",
        "influence_patterns": "описание",
        "consensus_level": число_0_100
    }}
}}"""

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Парсинг ответа от Claude"""
        try:
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            else:
                raise ValueError("JSON not found in response")
        except Exception as e:
            logger.error(f"Failed to parse Claude response: {e}")
            return {
                "is_valuable_dialogue": False,
                "confidence_score": 0,
                "business_relevance_score": 0,
                "potential_leads": [],
                "dialogue_summary": "Analysis failed",
                "key_insights": [],
                "recommended_actions": [],
                "next_best_action": "Manual review required"
            }

class SimpleMessageAnalyzer(BaseMessageAnalyzer):
    """Простой анализатор без AI"""
    
    def __init__(self):
        self.business_keywords = [
            'купить', 'заказать', 'цена', 'стоимость', 'бюджет',
            'crm', 'автоматизация', 'интеграция', 'бот', 'система'
        ]
        self.urgency_keywords = [
            'срочно', 'сегодня', 'немедленно', 'быстро', 'скорее'
        ]
        self.decision_keywords = [
            'решаю', 'выбираю', 'утверждаю', 'директор', 'руководитель'
        ]
    
    async def analyze(self, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        message_lower = message.lower()
        
        # Анализ бизнес-сигналов
        business_score = sum(10 for keyword in self.business_keywords if keyword in message_lower)
        business_score = min(business_score, 100)
        
        # Анализ срочности
        urgency_score = sum(15 for keyword in self.urgency_keywords if keyword in message_lower)
        
        # Анализ роли в принятии решений
        decision_score = sum(20 for keyword in self.decision_keywords if keyword in message_lower)
        
        # Итоговый скор
        total_score = min(business_score + urgency_score + decision_score, 100)
        
        # Определение качества лида
        if total_score >= 80:
            quality = "hot"
        elif total_score >= 60:
            quality = "warm"
        else:
            quality = "cold"
        
        # Определение роли
        if decision_score > 0:
            role = "decision_maker"
        elif business_score > 20:
            role = "influencer"
        else:
            role = "observer"
        
        return {
            "is_valuable_dialogue": total_score >= 40,
            "confidence_score": min(total_score + 20, 100),  # Немного повышаем уверенность
            "business_relevance_score": business_score,
            "potential_leads": [{
                "user_id": context.get('current_user_id', 0),
                "lead_probability": total_score,
                "lead_quality": quality,
                "key_signals": self._extract_signals(message_lower),
                "role_in_decision": role
            }] if total_score >= 30 else [],
            "dialogue_summary": f"Message analysis: {total_score}% relevance",
            "key_insights": self._generate_insights(message_lower, total_score),
            "recommended_actions": self._generate_actions(quality),
            "next_best_action": self._get_next_action(quality),
            "priority_level": "high" if total_score >= 80 else "medium" if total_score >= 60 else "low"
        }
    
    def _extract_signals(self, message_lower: str) -> List[str]:
        signals = []
        if any(kw in message_lower for kw in ['купить', 'заказать']):
            signals.append('purchase_intent')
        if any(kw in message_lower for kw in ['цена', 'стоимость']):
            signals.append('price_inquiry')
        if any(kw in message_lower for kw in ['срочно', 'быстро']):
            signals.append('urgency')
        return signals
    
    def _generate_insights(self, message_lower: str, score: int) -> List[str]:
        insights = []
        if score >= 70:
            insights.append("High purchase intent detected")
        if 'бюджет' in message_lower:
            insights.append("Budget discussion initiated")
        if any(kw in message_lower for kw in ['сравнива', 'выбира']):
            insights.append("Decision-making process active")
        return insights
    
    def _generate_actions(self, quality: str) -> List[str]:
        if quality == "hot":
            return ["Immediate contact", "Prepare proposal", "Schedule demo"]
        elif quality == "warm":
            return ["Send information", "Follow up in 24h", "Qualify needs"]
        else:
            return ["Add to nurturing", "Monitor activity"]
    
    def _get_next_action(self, quality: str) -> str:
        if quality == "hot":
            return "Contact within 15 minutes"
        elif quality == "warm":
            return "Follow up within 2 hours"
        else:
            return "Monitor for future engagement"

# === УМНЫЙ ТРЕКЕР ДИАЛОГОВ (SOLID - Single Responsibility) ===

class SmartDialogueTracker:
    """Оптимизированный трекер диалогов"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.active_dialogues: Dict[str, DialogueContext] = {}
        self.message_cache: Dict[int, List[Dict[str, Any]]] = {}
        
        # Настройки
        self.window_size = 8  # Уменьшили с 10 до 8
        self.dialogue_timeout = timedelta(minutes=15)  # Уменьшили с 20 до 15
        self.min_participants = 2
        
        # Кэш для оптимизации
        self._business_signals_cache = {}
        
    async def track_message(self, update: Update) -> Optional[str]:
        """Отслеживание сообщения"""
        try:
            chat_id = update.effective_chat.id
            user = update.effective_user
            message = update.message
            
            if not user or not message or not message.text:
                return None
            
            # Добавляем в кэш
            self._add_to_cache(chat_id, {
                'user_id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'text': message.text,
                'timestamp': datetime.now(),
                'message_id': message.message_id
            })
            
            # Анализируем контекст
            conversation_type = self._analyze_conversation_type(chat_id)
            
            if conversation_type == "individual":
                return None
            
            # Ищем или создаем диалог
            dialogue_id = await self._find_or_create_dialogue(chat_id, update.effective_chat.title)
            
            if dialogue_id:
                await self._update_dialogue(dialogue_id, user, message)
            
            # Очистка старых диалогов
            await self._cleanup_expired_dialogues()
            
            return dialogue_id
            
        except Exception as e:
            logger.error(f"Error in dialogue tracking: {e}")
            return None
    
    def _add_to_cache(self, chat_id: int, message_data: Dict[str, Any]):
        """Добавление сообщения в кэш с оптимизацией памяти"""
        if chat_id not in self.message_cache:
            self.message_cache[chat_id] = []
        
        cache = self.message_cache[chat_id]
        cache.append(message_data)
        
        # Ограничиваем размер кэша
        if len(cache) > self.window_size:
            cache[:] = cache[-self.window_size:]
    
    def _analyze_conversation_type(self, chat_id: int) -> str:
        """Быстрый анализ типа разговора"""
        cache = self.message_cache.get(chat_id, [])
        
        if len(cache) < 2:
            return "individual"
        
        recent_messages = cache[-6:]  # Анализируем только последние 6 сообщений
        unique_users = set(msg['user_id'] for msg in recent_messages)
        
        if len(unique_users) >= 2:
            # Проверяем на быстрые ответы
            quick_responses = 0
            for i in range(1, len(recent_messages)):
                time_diff = recent_messages[i]['timestamp'] - recent_messages[i-1]['timestamp']
                if time_diff <= timedelta(minutes=3) and recent_messages[i]['user_id'] != recent_messages[i-1]['user_id']:
                    quick_responses += 1
            
            return "dialogue" if quick_responses > 0 else "individual"
        
        return "individual"
    
    async def _find_or_create_dialogue(self, chat_id: int, chat_title: str) -> Optional[str]:
        """Поиск или создание диалога"""
        # Ищем активный диалог для канала
        for dialogue_id, dialogue in self.active_dialogues.items():
            if (dialogue.channel_id == chat_id and 
                datetime.now() - dialogue.last_activity < self.dialogue_timeout):
                return dialogue_id
        
        # Создаем новый диалог
        dialogue_id = f"dlg_{chat_id}_{int(datetime.now().timestamp())}"
        
        self.active_dialogues[dialogue_id] = DialogueContext(
            dialogue_id=dialogue_id,
            channel_id=chat_id,
            channel_title=chat_title or f"Channel_{chat_id}",
            participants={},
            messages=[],
            start_time=datetime.now(),
            last_activity=datetime.now()
        )
        
        return dialogue_id
    
    async def _update_dialogue(self, dialogue_id: str, user: User, message):
        """Обновление диалога"""
        dialogue = self.active_dialogues.get(dialogue_id)
        if not dialogue:
            return
        
        # Обновляем участника
        if user.id not in dialogue.participants:
            dialogue.participants[user.id] = ParticipantInfo(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
        
        participant = dialogue.participants[user.id]
        participant.message_count += 1
        
        # Анализируем покупательские сигналы (с кэшированием)
        signals = self._get_buying_signals(message.text)
        if signals:
            participant.buying_signals.extend(signals)
            dialogue.business_score += len(signals) * 10
        
        # Добавляем сообщение
        dialogue.messages.append({
            'user_id': user.id,
            'text': message.text,
            'timestamp': datetime.now(),
            'signals': signals
        })
        
        dialogue.last_activity = datetime.now()
    
    def _get_buying_signals(self, text: str) -> List[str]:
        """Получение покупательских сигналов с кэшированием"""
        text_hash = hash(text.lower())
        
        if text_hash in self._business_signals_cache:
            return self._business_signals_cache[text_hash]
        
        signals = []
        text_lower = text.lower()
        
        signal_patterns = {
            'purchase_intent': ['купить', 'заказать', 'приобрести'],
            'price_inquiry': ['цена', 'стоимость', 'сколько стоит'],
            'budget_discussion': ['бюджет', 'готовы потратить'],
            'urgency': ['срочно', 'быстро', 'сегодня'],
            'technical_interest': ['интеграция', 'api', 'техзадание']
        }
        
        for category, patterns in signal_patterns.items():
            if any(pattern in text_lower for pattern in patterns):
                signals.append(category)
        
        # Кэшируем результат
        self._business_signals_cache[text_hash] = signals
        if len(self._business_signals_cache) > 200:  # Ограничиваем размер кэша
            # Удаляем половину кэша
            items = list(self._business_signals_cache.items())
            self._business_signals_cache = dict(items[-100:])
        
        return signals
    
    async def _cleanup_expired_dialogues(self):
        """Очистка завершенных диалогов"""
        now = datetime.now()
        expired = [
            dialogue_id for dialogue_id, dialogue in self.active_dialogues.items()
            if now - dialogue.last_activity > self.dialogue_timeout
        ]
        
        for dialogue_id in expired:
            self.active_dialogues.pop(dialogue_id, None)
        
        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired dialogues")
    
    def should_analyze_immediately(self, dialogue_id: str, message_text: str) -> bool:
        """Проверка на немедленный анализ"""
        ultra_triggers = [
            'готов купить', 'хочу заказать', 'сколько стоит',
            'когда можем начать', 'есть бюджет'
        ]
        
        text_lower = message_text.lower()
        return any(trigger in text_lower for trigger in ultra_triggers)

# === УВЕДОМЛЕНИЯ (SOLID - Open/Closed Principle) ===

class BaseNotificationSender(ABC):
    """Базовый класс для отправки уведомлений"""
    
    @abstractmethod
    async def send_notification(self, notification_data: Dict[str, Any]) -> bool:
        pass

class TelegramNotificationSender(BaseNotificationSender):
    """Отправка уведомлений через Telegram"""
    
    async def send_notification(self, notification_data: Dict[str, Any]) -> bool:
        try:
            context = notification_data.get('context')
            admin_ids = notification_data.get('admin_ids', [])
            message = notification_data.get('message', '')
            
            if not context or not admin_ids or not message:
                return False
            
            success_count = 0
            for admin_id in admin_ids:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=message,
                        parse_mode=None
                    )
                    success_count += 1
                except Exception as e:
                    logger.error(f"Failed to send notification to {admin_id}: {e}")
            
            return success_count > 0
            
        except Exception as e:
            logger.error(f"Failed to send Telegram notifications: {e}")
            return False

class WebhookNotificationSender(BaseNotificationSender):
    """Отправка уведомлений через webhook"""
    
    async def send_notification(self, notification_data: Dict[str, Any]) -> bool:
        # Placeholder для webhook уведомлений
        logger.info("Webhook notification would be sent here")
        return True

# === ГЛАВНЫЙ ПАРСЕР (SOLID - Dependency Inversion) ===

class OptimizedUnifiedParser:
    """Оптимизированный парсер с инверсией зависимостей"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.parsing_config = config.get('parsing', {})
        
        # Основные настройки
        self.enabled = self.parsing_config.get('enabled', True)
        self.channels = self._parse_channels()
        self.min_confidence = self.parsing_config.get('min_confidence_score', 60)
        
        # Инжекция зависимостей
        analyzer_type = "claude" if self._has_claude_api() else "simple"
        self.message_analyzer = AnalyzerFactory.create_message_analyzer(analyzer_type)
        self.notification_sender = NotificationFactory.create_sender("telegram")
        self.dialogue_tracker = SmartDialogueTracker(config)
        
        # Статистика для мониторинга
        self.stats = {
            'messages_processed': 0,
            'dialogues_created': 0,
            'leads_generated': 0,
            'notifications_sent': 0,
            'analysis_failures': 0
        }
        
        # Кэш анализов для избежания дублирования
        self.analysis_cache: Dict[str, datetime] = {}
        self.cache_timeout = timedelta(minutes=5)
        
        logger.info(f"Optimized parser initialized: analyzer={analyzer_type}, channels={len(self.channels)}")
    
    def _parse_channels(self) -> List[str]:
        """Парсинг каналов из конфигурации"""
        channels_raw = self.parsing_config.get('channels', [])
        if isinstance(channels_raw, list):
            return [str(ch) for ch in channels_raw]
        elif isinstance(channels_raw, (str, int)):
            return [str(channels_raw)]
        return []
    
    def _has_claude_api(self) -> bool:
        """Проверка доступности Claude API"""
        claude_key = self.config.get('claude', {}).get('api_key', '')
        return bool(claude_key and claude_key != 'your_claude_api_key_here')
    
    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Главная функция обработки сообщений"""
        try:
            if not self.enabled:
                return
            
            chat_id = update.effective_chat.id
            user = update.effective_user
            message = update.message
            
            if not user or not message or not message.text:
                return
            
            self.stats['messages_processed'] += 1
            
            # Проверяем мониторинг канала
            if not self.is_channel_monitored(chat_id, update.effective_chat.username):
                return
            
            # Трекинг диалога
            dialogue_id = await self.dialogue_tracker.track_message(update)
            
            if dialogue_id:
                # Обработка в рамках диалога
                should_analyze = await self._should_analyze_dialogue(dialogue_id, message.text)
                
                if should_analyze:
                    await self._analyze_dialogue(dialogue_id, context)
            else:
                # Индивидуальная обработка
                await self._process_individual_message(user, message, context)
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            self.stats['analysis_failures'] += 1
    
    async def _should_analyze_dialogue(self, dialogue_id: str, message_text: str) -> bool:
        """Определение необходимости анализа диалога"""
        # Проверяем кэш
        cache_key = f"{dialogue_id}_{hash(message_text)}"
        now = datetime.now()
        
        if cache_key in self.analysis_cache:
            time_diff = now - self.analysis_cache[cache_key]
            if time_diff < self.cache_timeout:
                return False
        
        # Проверяем триггеры
        immediate_trigger = self.dialogue_tracker.should_analyze_immediately(dialogue_id, message_text)
        
        dialogue = self.dialogue_tracker.active_dialogues.get(dialogue_id)
        if not dialogue:
            return False
        
        # Условия для анализа
        basic_ready = len(dialogue.participants) >= 2 and len(dialogue.messages) >= 3
        has_business_signals = dialogue.business_score > 0
        
        should_analyze = basic_ready and (immediate_trigger or has_business_signals)
        
        if should_analyze:
            self.analysis_cache[cache_key] = now
            # Очищаем старые записи из кэша
            self.analysis_cache = {
                k: v for k, v in self.analysis_cache.items()
                if now - v < self.cache_timeout
            }
        
        return should_analyze
    
    async def _analyze_dialogue(self, dialogue_id: str, context: ContextTypes.DEFAULT_TYPE):
        """Анализ диалога"""
        try:
            dialogue = self.dialogue_tracker.active_dialogues.get(dialogue_id)
            if not dialogue:
                return
            
            # Подготовка данных для анализа
            participants_info = [
                f"{p.display_name} (@{p.username or 'no_username'}): {p.message_count} messages"
                for p in dialogue.participants.values()
            ]
            
            dialogue_history = [
                f"[{msg['timestamp'].strftime('%H:%M')}] {dialogue.participants[msg['user_id']].display_name}: {msg['text']}"
                for msg in dialogue.messages[-10:]  # Последние 10 сообщений
            ]
            
            analysis_context = {
                'participants_info': '\n'.join(participants_info),
                'dialogue_history': '\n'.join(dialogue_history),
                'current_user_id': dialogue.messages[-1]['user_id'] if dialogue.messages else 0
            }
            
            # Анализируем последнее сообщение
            last_message = dialogue.messages[-1]['text'] if dialogue.messages else ""
            analysis_result = await self.message_analyzer.analyze(last_message, analysis_context)
            
            # Обрабатываем результат
            if analysis_result.get('is_valuable_dialogue', False):
                await self._process_dialogue_result(dialogue, analysis_result, context)
            
        except Exception as e:
            logger.error(f"Error analyzing dialogue {dialogue_id}: {e}")
            self.stats['analysis_failures'] += 1
    
    async def _process_dialogue_result(self, dialogue: DialogueContext, 
                                     analysis_result: Dict[str, Any], 
                                     context: ContextTypes.DEFAULT_TYPE):
        """Обработка результатов анализа диалога"""
        try:
            confidence = analysis_result.get('confidence_score', 0)
            business_relevance = analysis_result.get('business_relevance_score', 0)
            potential_leads = analysis_result.get('potential_leads', [])
            
            # Гибкие критерии для уведомлений
            priority_level = analysis_result.get('priority_level', 'medium')
            
            if priority_level == 'urgent':
                min_confidence, min_business = 50, 60  # Сниженные требования для срочных
            elif priority_level == 'high':
                min_confidence, min_business = 60, 65
            else:
                min_confidence, min_business = 70, 75  # Стандартные требования
            
            should_notify = (
                confidence >= min_confidence and
                business_relevance >= min_business and
                len(potential_leads) > 0
            )
            
            if should_notify:
                # Создаем лиды
                created_leads = []
                for lead_data in potential_leads:
                    if lead_data.get('lead_probability', 0) >= 50:  # Мин. порог для создания лида
                        lead = await self._create_dialogue_lead(dialogue, lead_data, analysis_result)
                        if lead:
                            created_leads.append(lead)
                
                # Отправляем уведомление
                if created_leads:
                    await self._send_dialogue_notification(dialogue, analysis_result, created_leads, context)
                    self.stats['notifications_sent'] += 1
                    self.stats['leads_generated'] += len(created_leads)
            
        except Exception as e:
            logger.error(f"Error processing dialogue result: {e}")
    
    async def _process_individual_message(self, user: User, message, context: ContextTypes.DEFAULT_TYPE):
        """Обработка индивидуального сообщения"""
        try:
            # Простой анализ для индивидуальных сообщений
            analysis_context = {
                'current_user_id': user.id,
                'participants_info': f"{user.first_name} (@{user.username or 'no_username'})",
                'dialogue_history': f"Individual message: {message.text}"
            }
            
            analysis_result = await self.message_analyzer.analyze(message.text, analysis_context)
            
            # Создаем лид если достаточно высокий скор
            potential_leads = analysis_result.get('potential_leads', [])
            for lead_data in potential_leads:
                if lead_data.get('lead_probability', 0) >= 70:  # Высокий порог для индивидуальных
                    lead = await self._create_individual_lead(user, message, lead_data)
                    if lead:
                        self.stats['leads_generated'] += 1
                        
                        # Отправляем уведомление о горячем индивидуальном лиде
                        if lead_data.get('lead_probability', 0) >= 85:
                            await self._send_individual_notification(user, message, lead_data, context)
                            self.stats['notifications_sent'] += 1
            
        except Exception as e:
            logger.error(f"Error processing individual message: {e}")
    
    async def _create_dialogue_lead(self, dialogue: DialogueContext, 
                                  lead_data: Dict[str, Any], 
                                  analysis_result: Dict[str, Any]) -> Optional[Lead]:
        """Создание лида из диалога"""
        try:
            user_id = lead_data.get('user_id')
            participant = dialogue.participants.get(user_id)
            
            if not participant:
                return None
            
            lead = Lead(
                telegram_id=participant.user_id,
                username=participant.username,
                first_name=participant.first_name,
                last_name=participant.last_name,
                source_channel=f"{dialogue.channel_title} (dialogue)",
                interest_score=lead_data.get('lead_probability', 0),
                message_text=self._get_participant_messages(dialogue, user_id),
                message_date=dialogue.last_activity,
                lead_quality=lead_data.get('lead_quality', 'cold'),
                interests=json.dumps(lead_data.get('key_signals', []), ensure_ascii=False),
                buying_signals=json.dumps(participant.buying_signals, ensure_ascii=False),
                urgency_level=analysis_result.get('priority_level', 'medium'),
                estimated_budget=lead_data.get('estimated_budget_range'),
                timeline=analysis_result.get('estimated_timeline'),
                notes=f"Dialogue: {dialogue.dialogue_id}. Role: {lead_data.get('role_in_decision', 'participant')}"
            )
            
            await create_lead(lead)
            logger.info(f"Dialogue lead created: {participant.display_name} ({lead_data.get('lead_probability', 0)}%)")
            return lead
            
        except Exception as e:
            logger.error(f"Error creating dialogue lead: {e}")
            return None
    
    async def _create_individual_lead(self, user: User, message, lead_data: Dict[str, Any]) -> Optional[Lead]:
        """Создание индивидуального лида"""
        try:
            lead = Lead(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                source_channel="Individual message",
                interest_score=lead_data.get('lead_probability', 0),
                message_text=message.text,
                message_date=datetime.now(),
                lead_quality=lead_data.get('lead_quality', 'warm'),
                interests=json.dumps(lead_data.get('key_signals', []), ensure_ascii=False),
                urgency_level=lead_data.get('priority_level', 'medium'),
                notes="Individual high-intent message"
            )
            
            await create_lead(lead)
            logger.info(f"Individual lead created: {user.first_name} ({lead_data.get('lead_probability', 0)}%)")
            return lead
            
        except Exception as e:
            logger.error(f"Error creating individual lead: {e}")
            return None
    
    def _get_participant_messages(self, dialogue: DialogueContext, user_id: int) -> str:
        """Получение сообщений участника"""
        messages = [
            msg['text'] for msg in dialogue.messages 
            if msg['user_id'] == user_id
        ]
        return " | ".join(messages[-3:])  # Последние 3 сообщения
    
    async def _send_dialogue_notification(self, dialogue: DialogueContext, 
                                        analysis_result: Dict[str, Any],
                                        created_leads: List[Lead],
                                        context: ContextTypes.DEFAULT_TYPE):
        """Отправка уведомления о диалоге"""
        try:
            confidence = analysis_result.get('confidence_score', 0)
            business_relevance = analysis_result.get('business_relevance_score', 0)
            priority = analysis_result.get('priority_level', 'medium')
            
            # Формируем сообщение
            priority_emoji = "🚨" if priority == "urgent" else "🔥" if priority == "high" else "💎"
            
            message = f"""{priority_emoji} ЦЕННЫЙ ДИАЛОГ ({priority.upper()})

📺 Канал: {dialogue.channel_title}
👥 Участников: {len(dialogue.participants)}
💬 Сообщений: {len(dialogue.messages)}
📊 Уверенность: {confidence}%
🏢 Релевантность: {business_relevance}%

🎯 Создано лидов: {len(created_leads)}

📋 Суть: {analysis_result.get('dialogue_summary', 'N/A')}

💡 Ключевые инсайты:
{chr(10).join(f'• {insight}' for insight in analysis_result.get('key_insights', []))}

🎯 Рекомендации:
{chr(10).join(f'• {action}' for action in analysis_result.get('recommended_actions', []))}

⚡️ Следующий шаг: {analysis_result.get('next_best_action', 'Review manually')}"""

            notification_data = {
                'context': context,
                'admin_ids': self.config.get('bot', {}).get('admin_ids', []),
                'message': message
            }
            
            await self.notification_sender.send_notification(notification_data)
            
        except Exception as e:
            logger.error(f"Error sending dialogue notification: {e}")
    
    async def _send_individual_notification(self, user: User, message, 
                                          lead_data: Dict[str, Any], 
                                          context: ContextTypes.DEFAULT_TYPE):
        """Отправка уведомления об индивидуальном лиде"""
        try:
            probability = lead_data.get('lead_probability', 0)
            quality = lead_data.get('lead_quality', 'warm')
            
            notification_text = f"""🚨 ГОРЯЧИЙ ИНДИВИДУАЛЬНЫЙ ЛИД!

👤 Пользователь: {user.first_name} (@{user.username or 'no_username'})
💬 Сообщение: "{message.text}"
📊 Вероятность: {probability}%
🎯 Качество: {quality.upper()}

🔥 Покупательские сигналы:
{chr(10).join(f'• {signal}' for signal in lead_data.get('key_signals', []))}

⚡️ ДЕЙСТВУЙТЕ БЫСТРО: Свяжитесь в течение 15 минут!"""

            notification_data = {
                'context': context,
                'admin_ids': self.config.get('bot', {}).get('admin_ids', []),
                'message': notification_text
            }
            
            await self.notification_sender.send_notification(notification_data)
            
        except Exception as e:
            logger.error(f"Error sending individual notification: {e}")
    
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
            return any(variant in self.channels for variant in username_variants)
        
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """Получение статуса парсера"""
        return {
            'enabled': self.enabled,
            'mode': 'optimized_unified',
            'channels_count': len(self.channels),
            'channels': self.channels,
            'min_confidence_score': self.min_confidence,
            'analyzer_type': type(self.message_analyzer).__name__,
            'active_dialogues': len(self.dialogue_tracker.active_dialogues),
            'stats': self.stats.copy(),
            'dialogue_tracker': {
                'active_dialogues': len(self.dialogue_tracker.active_dialogues),
                'cache_size': len(self.dialogue_tracker.message_cache),
                'timeout_minutes': self.dialogue_tracker.dialogue_timeout.total_seconds() / 60
            }
        }
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Получение метрик производительности"""
        total_processed = self.stats['messages_processed']
        if total_processed == 0:
            return {'no_data': True}
        
        return {
            'messages_processed': total_processed,
            'leads_conversion_rate': (self.stats['leads_generated'] / total_processed) * 100,
            'notification_rate': (self.stats['notifications_sent'] / total_processed) * 100,
            'error_rate': (self.stats['analysis_failures'] / total_processed) * 100,
            'dialogues_per_message': self.stats['dialogues_created'] / total_processed,
            'cache_efficiency': len(self.analysis_cache)
        }

# Алиасы для совместимости
UnifiedAIParser = OptimizedUnifiedParser
DialogueTracker = SmartDialogueTracker
DialogueAnalyzer = ClaudeMessageAnalyzer

# Экспорт классов
__all__ = [
    'OptimizedUnifiedParser',
    'UnifiedAIParser', 
    'SmartDialogueTracker',
    'DialogueTracker',
    'ClaudeMessageAnalyzer',
    'DialogueAnalyzer',
    'AnalyzerFactory',
    'NotificationFactory',
    'ParticipantInfo',
    'DialogueContext',
    'AnalysisResult'
]
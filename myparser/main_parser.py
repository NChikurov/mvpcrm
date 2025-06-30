"""
myparser/main_parser.py - ИСПРАВЛЕННАЯ версия с добавленными классами и улучшениями
Исправлены: импорты, user_id валидация, производительность, промпты
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

# === БАЗОВЫЕ КЛАССЫ И ИНТЕРФЕЙСЫ ===

class BaseMessageAnalyzer(ABC):
    """Базовый класс для анализаторов сообщений"""
    
    @abstractmethod
    async def analyze(self, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        pass

class BaseNotificationSender(ABC):
    """Базовый класс для отправки уведомлений"""
    
    @abstractmethod
    async def send_notification(self, notification_data: Dict[str, Any]) -> bool:
        pass

# === ФАБРИКИ (ДОБАВЛЕНЫ ДЛЯ ИСПРАВЛЕНИЯ ИМПОРТА) ===

class AnalyzerFactory:
    """Фабрика для создания анализаторов"""
    
    @staticmethod
    def create_analyzer(analyzer_type: str, config: Dict[str, Any]) -> BaseMessageAnalyzer:
        """Создание анализатора по типу"""
        if analyzer_type == "claude":
            return ClaudeMessageAnalyzer()
        elif analyzer_type == "simple":
            return SimpleMessageAnalyzer()
        else:
            logger.warning(f"Unknown analyzer type: {analyzer_type}, using simple")
            return SimpleMessageAnalyzer()

class NotificationFactory:
    """Фабрика для создания отправителей уведомлений"""
    
    @staticmethod
    def create_sender(sender_type: str) -> BaseNotificationSender:
        """Создание отправителя уведомлений по типу"""
        if sender_type == "telegram":
            return TelegramNotificationSender()
        else:
            logger.warning(f"Unknown sender type: {sender_type}, using telegram")
            return TelegramNotificationSender()

# === АНАЛИЗАТОРЫ С УЛУЧШЕННЫМ ЛОГИРОВАНИЕМ ===

class ClaudeMessageAnalyzer(BaseMessageAnalyzer):
    """Анализатор с использованием Claude API с исправлениями"""
    
    def __init__(self):
        self.client = get_claude_client()
        self._cache = {}
    
    async def analyze(self, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Анализ с исправленным промптом и валидацией"""
        logger.info(f"🔍 AI АНАЛИЗ НАЧАТ")
        logger.info(f"📝 Сообщение для анализа: '{message[:100]}...' (длина: {len(message)})")
        logger.info(f"👥 Участники: {context.get('participants_info', 'Нет данных')}")
        logger.info(f"💬 История диалога: {len(context.get('dialogue_history', '').split('\\n'))} сообщений")
        
        # Проверяем кэш
        cache_key = f"{hash(message)}_{hash(str(context))}"
        if cache_key in self._cache:
            logger.info("💾 Результат получен из кэша")
            return self._cache[cache_key]
        
        if not self.client or not self.client.client:
            logger.warning("⚠️ Claude API недоступен, переходим к простому анализу")
            return await SimpleMessageAnalyzer().analyze(message, context)
        
        try:
            prompt = self._build_optimized_prompt(message, context)
            
            start_time = datetime.now()
            
            response = await asyncio.wait_for(
                self.client.client.messages.create(
                    model=self.client.model,
                    max_tokens=1000,  # ИСПРАВЛЕНИЕ: уменьшили для скорости
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1
                ),
                timeout=8.0  # ИСПРАВЛЕНИЕ: уменьшили таймаут
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            
            raw_response = response.content[0].text
            logger.info(f"🤖 Claude ответил за {duration:.2f}с")
            logger.info(f"📄 Сырой ответ Claude: {raw_response[:500]}...")
            
            result = self._parse_response(raw_response, context)
            
            logger.info(f"✅ АНАЛИЗ ЗАВЕРШЕН:")
            logger.info(f"   🎯 Ценный диалог: {result.get('is_valuable_dialogue', False)}")
            logger.info(f"   📊 Уверенность: {result.get('confidence_score', 0)}%")
            logger.info(f"   🏢 Бизнес-релевантность: {result.get('business_relevance_score', 0)}%")
            logger.info(f"   👥 Потенциальных лидов: {len(result.get('potential_leads', []))}")
            
            # Кэшируем результат
            self._cache[cache_key] = result
            if len(self._cache) > 50:  # ИСПРАВЛЕНИЕ: уменьшили размер кэша
                self._cache.clear()
            
            return result
            
        except asyncio.TimeoutError:
            logger.error("⏰ Claude API timeout - переходим к простому анализу")
            return await SimpleMessageAnalyzer().analyze(message, context)
        except Exception as e:
            logger.error(f"❌ Ошибка Claude API: {e} - переходим к простому анализу")
            return await SimpleMessageAnalyzer().analyze(message, context)
    
    def _build_optimized_prompt(self, message: str, context: Dict[str, Any]) -> str:
        """ИСПРАВЛЕННЫЙ промпт с четкими инструкциями по user_id"""
        participants_info = context.get('participants_info', '')
        dialogue_history = context.get('dialogue_history', '')
        
        # ИСПРАВЛЕНИЕ: Извлекаем мапинг user_id -> username из контекста
        current_user_id = context.get('current_user_id', 0)
        
        return f"""Проанализируй бизнес-диалог и верни ТОЛЬКО JSON:

КОНТЕКСТ:
Канал: {context.get('channel_title', 'Unknown')}
Участники: {participants_info}
Текущий пользователь ID: {current_user_id}

ИСТОРИЯ ДИАЛОГА:
{dialogue_history[-800:]}

НОВОЕ СООБЩЕНИЕ: "{message}"

КРИТИЧЕСКИ ВАЖНО: 
- user_id должен быть ЧИСЛОМ (не username!)
- Используй ТОЛЬКО реальные user_id участников
- Если не знаешь user_id, используй 0

ЗАДАЧА: Определи покупательские намерения и роли участников.

ИЩИ СИГНАЛЫ:
🔥 ГОРЯЧИЕ: "купить", "заказать", "готов подписать", "бюджет есть"
⭐ ТЕПЛЫЕ: "цена", "стоимость", "когда можем начать", "техзадание"
👍 ИНТЕРЕС: "подробнее", "как работает", "возможности", "сравниваем"

JSON:
{{
    "is_valuable_dialogue": boolean,
    "confidence_score": число_0_100,
    "business_relevance_score": число_0_100,
    "potential_leads": [
        {{
            "user_id": {current_user_id},
            "lead_probability": число_0_100,
            "lead_quality": "hot/warm/cold",
            "key_signals": ["список_найденных_сигналов"],
            "role_in_decision": "decision_maker/influencer/observer/budget_holder",
            "urgency_indicators": ["список_срочности"],
            "estimated_budget_range": "диапазон_или_null"
        }}
    ],
    "dialogue_summary": "краткое_описание_сути",
    "key_insights": ["список_инсайтов"],
    "recommended_actions": ["список_действий"],
    "next_best_action": "следующий_шаг",
    "priority_level": "low/medium/high/urgent"
}}"""

    def _parse_response(self, response_text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """ИСПРАВЛЕННЫЙ парсинг ответа от Claude"""
        try:
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                
                if not isinstance(result.get('potential_leads'), list):
                    result['potential_leads'] = []
                
                # ИСПРАВЛЕНИЕ: Улучшенная валидация user_id
                valid_leads = []
                current_user_id = context.get('current_user_id', 0)
                
                for lead in result.get('potential_leads', []):
                    user_id = lead.get('user_id')
                    
                    # Пытаемся исправить user_id
                    if isinstance(user_id, str):
                        # Если это username, используем current_user_id
                        if user_id.isalpha():
                            lead['user_id'] = current_user_id
                            logger.info(f"🔧 Исправлен user_id с '{user_id}' на {current_user_id}")
                        else:
                            # Пытаемся извлечь число
                            try:
                                lead['user_id'] = int(user_id)
                            except ValueError:
                                lead['user_id'] = current_user_id
                                logger.warning(f"⚠️ Некорректный user_id '{user_id}', заменен на {current_user_id}")
                    
                    elif isinstance(user_id, int) and user_id > 0:
                        # Оставляем корректный user_id
                        pass
                    else:
                        # Используем current_user_id как fallback
                        lead['user_id'] = current_user_id
                        logger.info(f"🔧 Установлен fallback user_id: {current_user_id}")
                    
                    # Добавляем только если user_id валиден
                    if lead['user_id'] > 0:
                        valid_leads.append(lead)
                    else:
                        logger.warning(f"❌ Пропущен лид с некорректным user_id: {lead.get('user_id')}")
                
                result['potential_leads'] = valid_leads
                logger.info(f"✅ Парсинг успешен, валидных лидов: {len(valid_leads)}")
                return result
            else:
                raise ValueError("JSON не найден в ответе")
                
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга ответа Claude: {e}")
            logger.error(f"📄 Сырой ответ: {response_text[:200]}...")
            
            # ИСПРАВЛЕНИЕ: Возвращаем результат с current_user_id
            current_user_id = context.get('current_user_id', 0)
            return {
                "is_valuable_dialogue": False,
                "confidence_score": 0,
                "business_relevance_score": 0,
                "potential_leads": [{
                    "user_id": current_user_id,
                    "lead_probability": 30,
                    "lead_quality": "cold",
                    "key_signals": ["parsing_error"],
                    "role_in_decision": "observer",
                    "urgency_indicators": [],
                    "estimated_budget_range": None
                }] if current_user_id > 0 else [],
                "dialogue_summary": f"Ошибка анализа: {str(e)}",
                "key_insights": [],
                "recommended_actions": ["Требуется ручная проверка"],
                "next_best_action": "Manual review required",
                "priority_level": "low"
            }

class SimpleMessageAnalyzer(BaseMessageAnalyzer):
    """Улучшенный простой анализатор без AI"""
    
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
        """Простой анализ с исправленным user_id"""
        logger.info("🔄 Используем простой анализ (без AI)")
        logger.info(f"📝 Анализируем: '{message[:100]}...'")
        
        message_lower = message.lower()
        
        found_business = [kw for kw in self.business_keywords if kw in message_lower]
        found_urgency = [kw for kw in self.urgency_keywords if kw in message_lower]
        found_decision = [kw for kw in self.decision_keywords if kw in message_lower]
        
        business_score = min(len(found_business) * 20, 100)
        urgency_score = min(len(found_urgency) * 15, 100)
        decision_score = min(len(found_decision) * 25, 100)
        
        total_score = min(business_score + urgency_score + decision_score, 100)
        
        if total_score >= 80:
            quality = "hot"
        elif total_score >= 60:
            quality = "warm"
        else:
            quality = "cold"
        
        if decision_score > 0:
            role = "decision_maker"
        elif business_score > 20:
            role = "influencer"
        else:
            role = "observer"
        
        # ИСПРАВЛЕНИЕ: Используем корректный user_id
        current_user_id = context.get('current_user_id', 0)
        
        logger.info(f"🔍 Найденные бизнес-слова: {found_business}")
        logger.info(f"⚡ Найденные слова срочности: {found_urgency}")
        logger.info(f"👑 Найденные слова принятия решений: {found_decision}")
        logger.info(f"📊 Итоговый скор: {total_score}% (user_id: {current_user_id})")
        
        result = {
            "is_valuable_dialogue": total_score >= 40,
            "confidence_score": min(total_score + 20, 100),
            "business_relevance_score": business_score,
            "potential_leads": [{
                "user_id": current_user_id,
                "lead_probability": total_score,
                "lead_quality": quality,
                "key_signals": found_business + found_urgency + found_decision,
                "role_in_decision": role,
                "urgency_indicators": found_urgency,
                "estimated_budget_range": "unknown"
            }] if total_score >= 30 and current_user_id > 0 else [],
            "dialogue_summary": f"Простой анализ: {total_score}% релевантность, найдено сигналов: {len(found_business + found_urgency + found_decision)}",
            "key_insights": self._generate_insights(found_business, found_urgency, found_decision, total_score),
            "recommended_actions": self._generate_actions(quality),
            "next_best_action": self._get_next_action(quality),
            "priority_level": "high" if total_score >= 80 else "medium" if total_score >= 60 else "low"
        }
        
        logger.info(f"✅ Простой анализ завершен: ценность={result['is_valuable_dialogue']}, лидов={len(result['potential_leads'])}")
        return result
    
    def _generate_insights(self, business_words: List[str], urgency_words: List[str], 
                          decision_words: List[str], score: int) -> List[str]:
        insights = []
        if score >= 70:
            insights.append("Высокий покупательский интерес")
        if business_words:
            insights.append(f"Бизнес-интерес: {', '.join(business_words)}")
        if urgency_words:
            insights.append(f"Срочность: {', '.join(urgency_words)}")
        if decision_words:
            insights.append(f"Роль в принятии решений: {', '.join(decision_words)}")
        return insights
    
    def _generate_actions(self, quality: str) -> List[str]:
        if quality == "hot":
            return ["Немедленный контакт", "Подготовить предложение", "Запланировать демо"]
        elif quality == "warm":
            return ["Отправить информацию", "Связаться в течение 24ч", "Уточнить потребности"]
        else:
            return ["Добавить в воронку", "Мониторить активность"]
    
    def _get_next_action(self, quality: str) -> str:
        if quality == "hot":
            return "Связаться в течение 15 минут"
        elif quality == "warm":
            return "Связаться в течение 2 часов"
        else:
            return "Мониторить будущую активность"

# === ТРЕКЕР ДИАЛОГОВ ===

class SmartDialogueTracker:
    """Трекер диалогов с исправлениями"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.active_dialogues: Dict[str, DialogueContext] = {}
        self.message_cache: Dict[int, List[Dict[str, Any]]] = {}
        
        self.window_size = 8
        self.dialogue_timeout = timedelta(minutes=15)
        self.min_participants = 2
        
        self._business_signals_cache = {}
        
        logger.info(f"🎭 Трекер диалогов инициализирован: окно={self.window_size}, таймаут={self.dialogue_timeout}")
    
    async def track_message(self, update: Update) -> Optional[str]:
        """Отслеживание сообщения с улучшенной обработкой"""
        try:
            chat_id = update.effective_chat.id
            user = update.effective_user
            message = update.message
            
            if not user or not message or not message.text:
                return None
            
            logger.info(f"🎭 ТРЕКИНГ ДИАЛОГА:")
            logger.info(f"   👤 Пользователь: {user.first_name} (@{user.username or 'no_username'}) ID:{user.id}")
            logger.info(f"   💬 Сообщение: '{message.text[:100]}...' (длина: {len(message.text)})")
            logger.info(f"   📺 Канал: {update.effective_chat.title} ID:{chat_id}")
            
            # Добавляем в кэш с user_id
            self._add_to_cache(chat_id, {
                'user_id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'text': message.text,
                'timestamp': datetime.now(),
                'message_id': message.message_id
            })
            
            conversation_type = self._analyze_conversation_type(chat_id)
            logger.info(f"   🔍 Тип разговора: {conversation_type}")
            
            if conversation_type == "individual":
                logger.info("   👤 Определен как индивидуальное сообщение")
                return None
            
            dialogue_id = await self._find_or_create_dialogue(chat_id, update.effective_chat.title)
            
            if dialogue_id:
                logger.info(f"   🎭 Диалог: {dialogue_id}")
                await self._update_dialogue(dialogue_id, user, message)
                
                dialogue = self.active_dialogues.get(dialogue_id)
                if dialogue:
                    logger.info(f"   📊 Участников: {len(dialogue.participants)}, "
                              f"сообщений: {len(dialogue.messages)}, "
                              f"бизнес-скор: {dialogue.business_score}")
            
            await self._cleanup_expired_dialogues()
            
            return dialogue_id
            
        except Exception as e:
            logger.error(f"❌ Ошибка трекинга диалога: {e}")
            return None
    
    def _add_to_cache(self, chat_id: int, message_data: Dict[str, Any]):
        """Добавление сообщения в кэш"""
        if chat_id not in self.message_cache:
            self.message_cache[chat_id] = []
        
        cache = self.message_cache[chat_id]
        cache.append(message_data)
        
        if len(cache) > self.window_size:
            cache[:] = cache[-self.window_size:]
        
        logger.debug(f"💾 Кэш канала {chat_id}: {len(cache)} сообщений")
    
    def _analyze_conversation_type(self, chat_id: int) -> str:
        """Анализ типа разговора"""
        cache = self.message_cache.get(chat_id, [])
        
        if len(cache) < 2:
            return "individual"
        
        recent_messages = cache[-6:]
        unique_users = set(msg['user_id'] for msg in recent_messages)
        
        logger.debug(f"🔍 Анализ разговора: {len(recent_messages)} сообщений, {len(unique_users)} пользователей")
        
        if len(unique_users) >= 2:
            quick_responses = 0
            for i in range(1, len(recent_messages)):
                time_diff = recent_messages[i]['timestamp'] - recent_messages[i-1]['timestamp']
                if time_diff <= timedelta(minutes=3) and recent_messages[i]['user_id'] != recent_messages[i-1]['user_id']:
                    quick_responses += 1
            
            logger.debug(f"⚡ Быстрых ответов: {quick_responses}")
            return "dialogue" if quick_responses > 0 else "individual"
        
        return "individual"
    
    async def _find_or_create_dialogue(self, chat_id: int, chat_title: str) -> Optional[str]:
        """Поиск или создание диалога"""
        for dialogue_id, dialogue in self.active_dialogues.items():
            if (dialogue.channel_id == chat_id and 
                datetime.now() - dialogue.last_activity < self.dialogue_timeout):
                logger.debug(f"♻️ Найден существующий диалог: {dialogue_id}")
                return dialogue_id
        
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
        
        logger.info(f"🆕 Создан новый диалог: {dialogue_id} в канале '{chat_title}'")
        return dialogue_id
    
    async def _update_dialogue(self, dialogue_id: str, user: User, message):
        """Обновление диалога"""
        dialogue = self.active_dialogues.get(dialogue_id)
        if not dialogue:
            return
        
        if user.id not in dialogue.participants:
            dialogue.participants[user.id] = ParticipantInfo(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
            logger.info(f"👤 Новый участник диалога {dialogue_id}: {user.first_name} (ID: {user.id})")
        
        participant = dialogue.participants[user.id]
        participant.message_count += 1
        
        signals = self._get_buying_signals(message.text)
        if signals:
            participant.buying_signals.extend(signals)
            dialogue.business_score += len(signals) * 10
            logger.info(f"🎯 Найдены покупательские сигналы: {signals} от {user.first_name}")
        
        dialogue.messages.append({
            'user_id': user.id,
            'text': message.text,
            'timestamp': datetime.now(),
            'signals': signals
        })
        
        dialogue.last_activity = datetime.now()
        
        logger.debug(f"📝 Диалог {dialogue_id} обновлен: +1 сообщение от {user.first_name}")
    
    def _get_buying_signals(self, text: str) -> List[str]:
        """Поиск покупательских сигналов с кэшированием"""
        text_hash = hash(text.lower())
        
        if text_hash in self._business_signals_cache:
            return self._business_signals_cache[text_hash]
        
        signals = []
        text_lower = text.lower()
        
        signal_patterns = {
            'purchase_intent': ['купить', 'заказать', 'приобрести', 'хочу купить'],
            'price_inquiry': ['цена', 'стоимость', 'сколько стоит', 'какая цена'],
            'budget_discussion': ['бюджет', 'готовы потратить', 'есть деньги'],
            'urgency': ['срочно', 'быстро', 'сегодня', 'немедленно'],
            'technical_interest': ['интеграция', 'api', 'техзадание', 'требования'],
            'decision_making': ['решаем', 'выбираем', 'принимаем решение']
        }
        
        for category, patterns in signal_patterns.items():
            if any(pattern in text_lower for pattern in patterns):
                signals.append(category)
        
        # Кэшируем результат
        self._business_signals_cache[text_hash] = signals
        if len(self._business_signals_cache) > 100:  # ИСПРАВЛЕНИЕ: уменьшили размер кэша
            items = list(self._business_signals_cache.items())
            self._business_signals_cache = dict(items[-50:])
        
        return signals
    
    async def _cleanup_expired_dialogues(self):
        """Очистка завершенных диалогов"""
        now = datetime.now()
        expired = [
            dialogue_id for dialogue_id, dialogue in self.active_dialogues.items()
            if now - dialogue.last_activity > self.dialogue_timeout
        ]
        
        for dialogue_id in expired:
            dialogue = self.active_dialogues.pop(dialogue_id, None)
            if dialogue:
                logger.info(f"🗑️ Диалог {dialogue_id} завершен (таймаут): "
                          f"участников={len(dialogue.participants)}, "
                          f"сообщений={len(dialogue.messages)}")
    
    def should_analyze_immediately(self, dialogue_id: str, message_text: str) -> bool:
        """Проверка на немедленный анализ"""
        ultra_triggers = [
            'готов купить', 'хочу заказать', 'сколько стоит',
            'когда можем начать', 'есть бюджет', 'подпишем договор'
        ]
        
        text_lower = message_text.lower()
        has_trigger = any(trigger in text_lower for trigger in ultra_triggers)
        
        if has_trigger:
            logger.info(f"⚡ НЕМЕДЛЕННЫЙ АНАЛИЗ: найден ультра-триггер в сообщении")
        
        return has_trigger

# === УВЕДОМЛЕНИЯ ===

class TelegramNotificationSender(BaseNotificationSender):
    """Отправка уведомлений через Telegram"""
    
    async def send_notification(self, notification_data: Dict[str, Any]) -> bool:
        """Отправка уведомлений с улучшенной обработкой"""
        try:
            context = notification_data.get('context')
            admin_ids = notification_data.get('admin_ids', [])
            message = notification_data.get('message', '')
            
            logger.info(f"📤 ОТПРАВКА УВЕДОМЛЕНИЯ:")
            logger.info(f"   👑 Админов: {len(admin_ids)} {admin_ids}")
            logger.info(f"   💬 Длина сообщения: {len(message)} символов")
            logger.info(f"   🤖 Context доступен: {context is not None}")
            
            if not context:
                logger.error("❌ Context не передан для уведомления")
                return False
            
            if not admin_ids:
                logger.error("❌ Список админов пуст")
                return False
            
            if not message:
                logger.error("❌ Текст уведомления пуст")
                return False
            
            success_count = 0
            for admin_id in admin_ids:
                try:
                    logger.info(f"📤 Отправляем уведомление админу {admin_id}")
                    
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=message[:4000],  # ИСПРАВЛЕНИЕ: ограничиваем длину
                        parse_mode=None,
                        disable_web_page_preview=True
                    )
                    
                    success_count += 1
                    logger.info(f"✅ Уведомление отправлено админу {admin_id}")
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки админу {admin_id}: {e}")
            
            logger.info(f"📊 Результат отправки: {success_count}/{len(admin_ids)} успешно")
            return success_count > 0
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка отправки уведомлений: {e}")
            return False

# === ГЛАВНЫЙ ПАРСЕР ===

class OptimizedUnifiedParser:
    """Исправленный парсер с улучшенной производительностью"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.parsing_config = config.get('parsing', {})
        
        self.enabled = self.parsing_config.get('enabled', True)
        self.channels = self._parse_channels()
        self.min_confidence = self.parsing_config.get('min_confidence_score', 60)
        
        # Инициализируем компоненты через фабрики
        analyzer_type = "claude" if self._has_claude_api() else "simple"
        self.message_analyzer = AnalyzerFactory.create_analyzer(analyzer_type, config)
        self.notification_sender = NotificationFactory.create_sender("telegram")
        self.dialogue_tracker = SmartDialogueTracker(config)
        
        # Статистика
        self.stats = {
            'messages_processed': 0,
            'dialogues_created': 0,
            'leads_generated': 0,
            'notifications_sent': 0,
            'analysis_failures': 0,
            'notifications_failed': 0
        }
        
        self.analysis_cache: Dict[str, datetime] = {}
        self.cache_timeout = timedelta(minutes=5)
        
        logger.info(f"🚀 ПАРСЕР ИНИЦИАЛИЗИРОВАН:")
        logger.info(f"   🔍 Анализатор: {analyzer_type}")
        logger.info(f"   📺 Каналов: {len(self.channels)}")
        logger.info(f"   ⚙️ Включен: {self.enabled}")
        logger.info(f"   📊 Мин. уверенность: {self.min_confidence}%")
    
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
        has_api = bool(claude_key and claude_key != 'your_claude_api_key_here')
        logger.info(f"🧠 Claude API: {'доступен' if has_api else 'недоступен'}")
        return has_api
    
    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Главная функция обработки сообщений с исправлениями"""
        try:
            if not self.enabled:
                logger.debug("⏸️ Парсер отключен, пропускаем сообщение")
                return
            
            chat_id = update.effective_chat.id
            user = update.effective_user
            message = update.message
            
            if not user or not message or not message.text:
                logger.debug("⏸️ Некорректное сообщение, пропускаем")
                return
            
            self.stats['messages_processed'] += 1
            
            logger.info(f"🔄 ОБРАБОТКА СООБЩЕНИЯ #{self.stats['messages_processed']}:")
            logger.info(f"   👤 От: {user.first_name} (@{user.username or 'no_username'}) ID:{user.id}")
            logger.info(f"   📺 Канал: {update.effective_chat.title} ID:{chat_id}")
            logger.info(f"   💬 Текст: '{message.text[:150]}...' (длина: {len(message.text)})")
            
            if not self.is_channel_monitored(chat_id, update.effective_chat.username):
                logger.info(f"⏸️ Канал {chat_id} не мониторится, пропускаем")
                return
            
            logger.info(f"✅ Канал мониторится, продолжаем обработку")
            
            dialogue_id = await self.dialogue_tracker.track_message(update)
            
            if dialogue_id:
                logger.info(f"🎭 Сообщение добавлено в диалог: {dialogue_id}")
                should_analyze = await self._should_analyze_dialogue(dialogue_id, message.text)
                
                if should_analyze:
                    logger.info(f"🔍 Запускаем анализ диалога {dialogue_id}")
                    await self._analyze_dialogue(dialogue_id, context, user)
                else:
                    logger.info(f"⏸️ Диалог {dialogue_id} не готов для анализа")
            else:
                logger.info(f"👤 Обрабатываем как индивидуальное сообщение")
                await self._process_individual_message(user, message, context)
            
            logger.info(f"✅ Обработка сообщения завершена")
            
        except Exception as e:
            logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА обработки сообщения: {e}")
            self.stats['analysis_failures'] += 1
    
    async def _should_analyze_dialogue(self, dialogue_id: str, message_text: str) -> bool:
        """Определение необходимости анализа диалога"""
        cache_key = f"{dialogue_id}_{hash(message_text)}"
        now = datetime.now()
        
        if cache_key in self.analysis_cache:
            time_diff = now - self.analysis_cache[cache_key]
            if time_diff < self.cache_timeout:
                logger.debug(f"⏸️ Анализ в кэше, пропускаем")
                return False
        
        immediate_trigger = self.dialogue_tracker.should_analyze_immediately(dialogue_id, message_text)
        
        dialogue = self.dialogue_tracker.active_dialogues.get(dialogue_id)
        if not dialogue:
            logger.warning(f"⚠️ Диалог {dialogue_id} не найден")
            return False
        
        basic_ready = len(dialogue.participants) >= 2 and len(dialogue.messages) >= 3
        has_business_signals = dialogue.business_score > 0
        
        logger.info(f"🔍 Проверка готовности диалога:")
        logger.info(f"   👥 Участников: {len(dialogue.participants)} (нужно >= 2)")
        logger.info(f"   💬 Сообщений: {len(dialogue.messages)} (нужно >= 3)")
        logger.info(f"   🎯 Бизнес-скор: {dialogue.business_score}")
        logger.info(f"   ⚡ Ультра-триггер: {immediate_trigger}")
        
        should_analyze = basic_ready and (immediate_trigger or has_business_signals)
        
        if should_analyze:
            self.analysis_cache[cache_key] = now
            # Очищаем старые записи из кэша
            self.analysis_cache = {
                k: v for k, v in self.analysis_cache.items()
                if now - v < self.cache_timeout
            }
        
        logger.info(f"📊 Решение: {'АНАЛИЗИРОВАТЬ' if should_analyze else 'НЕ АНАЛИЗИРОВАТЬ'}")
        return should_analyze
    
    async def _analyze_dialogue(self, dialogue_id: str, context: ContextTypes.DEFAULT_TYPE, current_user: User):
        """ИСПРАВЛЕННЫЙ анализ диалога с правильным user_id"""
        try:
            dialogue = self.dialogue_tracker.active_dialogues.get(dialogue_id)
            if not dialogue:
                logger.error(f"❌ Диалог {dialogue_id} не найден для анализа")
                return
            
            logger.info(f"🔍 НАЧИНАЕМ АНАЛИЗ ДИАЛОГА {dialogue_id}")
            
            # Подготовка данных для анализа
            participants_info = []
            for p in dialogue.participants.values():
                info = f"{p.display_name} (@{p.username or 'no_username'}) ID:{p.user_id}: {p.message_count} сообщений"
                if p.buying_signals:
                    info += f", сигналы: {p.buying_signals}"
                participants_info.append(info)
            
            dialogue_history = []
            for msg in dialogue.messages[-10:]:
                participant = dialogue.participants.get(msg['user_id'])
                display_name = participant.display_name if participant else f"User_{msg['user_id']}"
                time_str = msg['timestamp'].strftime('%H:%M')
                signals_str = f" [сигналы: {msg['signals']}]" if msg['signals'] else ""
                dialogue_history.append(f"[{time_str}] {display_name}: {msg['text']}{signals_str}")
            
            # ИСПРАВЛЕНИЕ: Передаем current_user_id в контекст
            analysis_context = {
                'channel_title': dialogue.channel_title,
                'participants_info': '\n'.join(participants_info),
                'dialogue_history': '\n'.join(dialogue_history),
                'current_user_id': current_user.id  # ИСПРАВЛЕНИЕ: правильный user_id
            }
            
            logger.info(f"📋 Контекст анализа:")
            logger.info(f"   📺 Канал: {dialogue.channel_title}")
            logger.info(f"   👥 Участников в контексте: {len(participants_info)}")
            logger.info(f"   💬 Сообщений в истории: {len(dialogue_history)}")
            logger.info(f"   🆔 Current user ID: {current_user.id}")
            
            last_message = dialogue.messages[-1]['text'] if dialogue.messages else ""
            analysis_result = await self.message_analyzer.analyze(last_message, analysis_context)
            
            if analysis_result.get('is_valuable_dialogue', False):
                logger.info(f"💎 Диалог признан ценным, обрабатываем результат")
                await self._process_dialogue_result(dialogue, analysis_result, context)
            else:
                logger.info(f"📊 Диалог не признан ценным (уверенность: {analysis_result.get('confidence_score', 0)}%)")
            
        except Exception as e:
            logger.error(f"❌ ОШИБКА анализа диалога {dialogue_id}: {e}")
            self.stats['analysis_failures'] += 1
    
    async def _process_dialogue_result(self, dialogue: DialogueContext, 
                                     analysis_result: Dict[str, Any], 
                                     context: ContextTypes.DEFAULT_TYPE):
        """Обработка результатов анализа диалога"""
        try:
            confidence = analysis_result.get('confidence_score', 0)
            business_relevance = analysis_result.get('business_relevance_score', 0)
            potential_leads = analysis_result.get('potential_leads', [])
            priority_level = analysis_result.get('priority_level', 'medium')
            
            logger.info(f"📊 РЕЗУЛЬТАТ АНАЛИЗА ДИАЛОГА:")
            logger.info(f"   🎯 Уверенность: {confidence}%")
            logger.info(f"   🏢 Бизнес-релевантность: {business_relevance}%")
            logger.info(f"   👥 Потенциальных лидов: {len(potential_leads)}")
            logger.info(f"   ⚡ Приоритет: {priority_level}")
            
            # ИСПРАВЛЕНИЕ: Более мягкие критерии для уведомлений
            if priority_level == 'urgent':
                min_confidence, min_business = 30, 40
            elif priority_level == 'high':
                min_confidence, min_business = 40, 50
            else:
                min_confidence, min_business = 50, 60
            
            should_notify = (
                confidence >= min_confidence and
                business_relevance >= min_business and
                len(potential_leads) > 0
            )
            
            logger.info(f"📋 Критерии уведомления:")
            logger.info(f"   📊 Уверенность: {confidence}% >= {min_confidence}% ✅" if confidence >= min_confidence else f"   📊 Уверенность: {confidence}% < {min_confidence}% ❌")
            logger.info(f"   🏢 Бизнес: {business_relevance}% >= {min_business}% ✅" if business_relevance >= min_business else f"   🏢 Бизнес: {business_relevance}% < {min_business}% ❌")
            logger.info(f"   👥 Лиды: {len(potential_leads)} > 0 ✅" if len(potential_leads) > 0 else f"   👥 Лиды: {len(potential_leads)} = 0 ❌")
            logger.info(f"   🚨 ОТПРАВЛЯТЬ УВЕДОМЛЕНИЕ: {'ДА' if should_notify else 'НЕТ'}")
            
            if should_notify:
                created_leads = []
                for lead_data in potential_leads:
                    if lead_data.get('lead_probability', 0) >= 30:  # ИСПРАВЛЕНИЕ: снизили порог
                        lead = await self._create_dialogue_lead(dialogue, lead_data, analysis_result)
                        if lead:
                            created_leads.append(lead)
                
                if created_leads:
                    notification_success = await self._send_dialogue_notification(dialogue, analysis_result, created_leads, context)
                    if notification_success:
                        self.stats['notifications_sent'] += 1
                        logger.info(f"✅ Уведомление о диалоге отправлено успешно")
                    else:
                        self.stats['notifications_failed'] += 1
                        logger.error(f"❌ Не удалось отправить уведомление о диалоге")
                    
                    self.stats['leads_generated'] += len(created_leads)
                    logger.info(f"🎯 Создано лидов: {len(created_leads)}")
                else:
                    logger.warning(f"⚠️ Потенциальные лиды не прошли валидацию для создания")
            else:
                logger.info(f"⏸️ Уведомление не отправляем - не соответствует критериям")
            
        except Exception as e:
            logger.error(f"❌ ОШИБКА обработки результата диалога: {e}")
    
    async def _create_dialogue_lead(self, dialogue: DialogueContext, 
                                  lead_data: Dict[str, Any], 
                                  analysis_result: Dict[str, Any]) -> Optional[Lead]:
        """Создание лида из диалога"""
        try:
            user_id = lead_data.get('user_id')
            participant = dialogue.participants.get(user_id)
            
            if not participant:
                logger.error(f"❌ Участник {user_id} не найден в диалоге")
                return None
            
            logger.info(f"🎯 Создаем лида: {participant.display_name} (ID: {user_id})")
            
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
            logger.info(f"✅ Лид создан: {participant.display_name} ({lead_data.get('lead_probability', 0)}%)")
            return lead
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания лида из диалога: {e}")
            return None
    
    async def _process_individual_message(self, user: User, message, context: ContextTypes.DEFAULT_TYPE):
        """ИСПРАВЛЕННАЯ обработка индивидуального сообщения"""
        try:
            logger.info(f"👤 АНАЛИЗ ИНДИВИДУАЛЬНОГО СООБЩЕНИЯ:")
            logger.info(f"   🧑 Пользователь: {user.first_name} (ID: {user.id})")
            logger.info(f"   💬 Сообщение: '{message.text[:100]}...'")
            
            # ИСПРАВЛЕНИЕ: Правильный контекст с user_id
            analysis_context = {
                'current_user_id': user.id,  # ИСПРАВЛЕНИЕ: передаем числовой ID
                'participants_info': f"{user.first_name} (@{user.username or 'no_username'})",
                'dialogue_history': f"Individual message: {message.text}"
            }
            
            analysis_result = await self.message_analyzer.analyze(message.text, analysis_context)
            
            potential_leads = analysis_result.get('potential_leads', [])
            for lead_data in potential_leads:
                lead_probability = lead_data.get('lead_probability', 0)
                if lead_probability >= 50:  # ИСПРАВЛЕНИЕ: снизили порог
                    lead = await self._create_individual_lead(user, message, lead_data)
                    if lead:
                        self.stats['leads_generated'] += 1
                        logger.info(f"🎯 Создан индивидуальный лид: {user.first_name} ({lead_probability}%)")
                        
                        if lead_probability >= 70:  # ИСПРАВЛЕНИЕ: снизили порог для уведомлений
                            notification_success = await self._send_individual_notification(user, message, lead_data, context)
                            if notification_success:
                                self.stats['notifications_sent'] += 1
                                logger.info(f"✅ Уведомление об индивидуальном лиде отправлено")
                            else:
                                self.stats['notifications_failed'] += 1
                                logger.error(f"❌ Не удалось отправить уведомление об индивидуальном лиде")
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки индивидуального сообщения: {e}")
    
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
            return lead
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания индивидуального лида: {e}")
            return None
    
    def _get_participant_messages(self, dialogue: DialogueContext, user_id: int) -> str:
        """Получение сообщений участника"""
        messages = [
            msg['text'] for msg in dialogue.messages 
            if msg['user_id'] == user_id
        ]
        return " | ".join(messages[-3:])
    
    async def _send_dialogue_notification(self, dialogue: DialogueContext, 
                                        analysis_result: Dict[str, Any],
                                        created_leads: List[Lead],
                                        context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Отправка уведомления о диалоге"""
        try:
            confidence = analysis_result.get('confidence_score', 0)
            business_relevance = analysis_result.get('business_relevance_score', 0)
            priority = analysis_result.get('priority_level', 'medium')
            
            priority_emoji = "🚨" if priority == "urgent" else "🔥" if priority == "high" else "💎"
            
            message = f"""{priority_emoji} ЦЕННЫЙ ДИАЛОГ ({priority.upper()})

📺 Канал: {dialogue.channel_title}
👥 Участников: {len(dialogue.participants)}
💬 Сообщений: {len(dialogue.messages)}
📊 Уверенность: {confidence}%
🏢 Релевантность: {business_relevance}%

🎯 Создано лидов: {len(created_leads)}

📋 Суть: {analysis_result.get('dialogue_summary', 'N/A')[:200]}

💡 Ключевые инсайты:"""

            for insight in analysis_result.get('key_insights', [])[:3]:
                message += f"\n• {insight[:100]}"

            message += f"\n\n🎯 Рекомендации:"
            for action in analysis_result.get('recommended_actions', [])[:3]:
                message += f"\n• {action[:100]}"

            message += f"\n\n⚡️ Следующий шаг: {analysis_result.get('next_best_action', 'Review manually')[:100]}"
            
            if created_leads:
                message += f"\n\n👤 Созданные лиды:"
                for lead in created_leads[:3]:
                    message += f"\n• {lead.first_name} (@{lead.username or 'no_username'}) - {lead.interest_score}%"

            notification_data = {
                'context': context,
                'admin_ids': self.config.get('bot', {}).get('admin_ids', []),
                'message': message
            }
            
            logger.info(f"📤 Подготовлено уведомление о диалоге длиной {len(message)} символов")
            
            return await self.notification_sender.send_notification(notification_data)
            
        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления о диалоге: {e}")
            return False
    
    async def _send_individual_notification(self, user: User, message, 
                                          lead_data: Dict[str, Any], 
                                          context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Отправка уведомления об индивидуальном лиде"""
        try:
            probability = lead_data.get('lead_probability', 0)
            quality = lead_data.get('lead_quality', 'warm')
            
            notification_text = f"""🚨 ГОРЯЧИЙ ИНДИВИДУАЛЬНЫЙ ЛИД!

👤 Пользователь: {user.first_name} (@{user.username or 'no_username'})
💬 Сообщение: "{message.text[:200]}..."
📊 Вероятность: {probability}%
🎯 Качество: {quality.upper()}

🔥 Покупательские сигналы:"""

            for signal in lead_data.get('key_signals', [])[:5]:
                notification_text += f"\n• {signal}"

            notification_text += f"\n\n⚡️ ДЕЙСТВУЙТЕ БЫСТРО: Свяжитесь в течение 15 минут!"

            notification_data = {
                'context': context,
                'admin_ids': self.config.get('bot', {}).get('admin_ids', []),
                'message': notification_text
            }
            
            return await self.notification_sender.send_notification(notification_data)
            
        except Exception as e:
            logger.error(f"❌ Ошибка отправки индивидуального уведомления: {e}")
            return False
    
    def is_channel_monitored(self, chat_id: int, chat_username: str = None) -> bool:
        """Проверка мониторинга канала"""
        if not self.enabled:
            return False
        
        if str(chat_id) in self.channels:
            return True
        
        if chat_username:
            username_variants = [f"@{chat_username}", chat_username]
            return any(variant in self.channels for variant in username_variants)
        
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """Получение статуса парсера"""
        return {
            'enabled': self.enabled,
            'mode': 'optimized_unified_fixed',
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
            'notification_success_rate': (self.stats['notifications_sent'] / max(self.stats['notifications_sent'] + self.stats['notifications_failed'], 1)) * 100,
            'error_rate': (self.stats['analysis_failures'] / total_processed) * 100,
            'dialogues_per_message': self.stats['dialogues_created'] / total_processed,
            'cache_efficiency': len(self.analysis_cache)
        }

# Алиасы для совместимости
UnifiedAIParser = OptimizedUnifiedParser
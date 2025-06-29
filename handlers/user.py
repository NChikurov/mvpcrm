"""
Оптимизированные обработчики пользователей
Улучшенная производительность, кэширование, асинхронная обработка
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from abc import ABC, abstractmethod

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User as TelegramUser
from telegram.ext import ContextTypes, CallbackQueryHandler

from database.operations import (
    create_user, get_user_by_telegram_id, save_message,
    update_user_activity, get_messages
)
from database.models import User, Message
from ai.claude_client import init_claude_client, get_claude_client

logger = logging.getLogger(__name__)

# === БАЗОВЫЕ КЛАССЫ И ИНТЕРФЕЙСЫ ===

@dataclass
class UserInteractionContext:
    """Контекст взаимодействия с пользователем"""
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    message_text: str
    chat_type: str
    timestamp: datetime
    is_new_user: bool = False
    interaction_count: int = 0

@dataclass
class ResponseContext:
    """Контекст для генерации ответа"""
    interest_score: int
    user_context: UserInteractionContext
    conversation_history: List[str]
    response_strategy: str
    personalization_data: Dict[str, Any]

class MessageAnalyzer(ABC):
    """Абстрактный анализатор сообщений"""
    
    @abstractmethod
    async def analyze_interest(self, message: str, context: List[str]) -> int:
        pass
    
    @abstractmethod
    async def generate_response(self, message: str, context: List[str], interest_score: int) -> str:
        pass

class ResponseGenerator(ABC):
    """Абстрактный генератор ответов"""
    
    @abstractmethod
    async def generate(self, response_context: ResponseContext) -> str:
        pass

# === КЭШ И ОПТИМИЗАЦИИ ===

class UserSessionCache:
    """Кэш пользовательских сессий"""
    
    def __init__(self, ttl_seconds: int = 1800):  # 30 минут
        self.sessions: Dict[int, Dict[str, Any]] = {}
        self.ttl = ttl_seconds
    
    def get_session(self, user_id: int) -> Dict[str, Any]:
        """Получение сессии пользователя"""
        if user_id in self.sessions:
            session = self.sessions[user_id]
            if time.time() - session.get('last_access', 0) < self.ttl:
                session['last_access'] = time.time()
                return session
            else:
                del self.sessions[user_id]
        
        # Создаем новую сессию
        session = {
            'user_id': user_id,
            'messages_count': 0,
            'last_interest_score': 0,
            'conversation_history': [],
            'response_strategy': 'standard',
            'created_at': time.time(),
            'last_access': time.time(),
            'personalization': {}
        }
        self.sessions[user_id] = session
        return session
    
    def update_session(self, user_id: int, **updates):
        """Обновление сессии"""
        session = self.get_session(user_id)
        session.update(updates)
        session['last_access'] = time.time()
    
    def cleanup_expired(self):
        """Очистка устаревших сессий"""
        current_time = time.time()
        expired_users = [
            user_id for user_id, session in self.sessions.items()
            if current_time - session.get('last_access', 0) > self.ttl
        ]
        for user_id in expired_users:
            del self.sessions[user_id]

class MessageThrottler:
    """Контроль частоты отправки сообщений"""
    
    def __init__(self, max_messages: int = 5, window_seconds: int = 60):
        self.max_messages = max_messages
        self.window_seconds = window_seconds
        self.user_messages: Dict[int, List[float]] = {}
    
    def can_send_message(self, user_id: int) -> bool:
        """Проверка возможности отправки сообщения"""
        current_time = time.time()
        
        if user_id not in self.user_messages:
            self.user_messages[user_id] = []
        
        # Удаляем старые записи
        self.user_messages[user_id] = [
            timestamp for timestamp in self.user_messages[user_id]
            if current_time - timestamp < self.window_seconds
        ]
        
        # Проверяем лимит
        if len(self.user_messages[user_id]) >= self.max_messages:
            return False
        
        # Добавляем текущую отправку
        self.user_messages[user_id].append(current_time)
        return True

# === АНАЛИЗАТОРЫ И ГЕНЕРАТОРЫ ===

class ClaudeMessageAnalyzer(MessageAnalyzer):
    """AI анализатор с использованием Claude"""
    
    def __init__(self):
        self.client = get_claude_client()
        self.response_cache: Dict[str, tuple] = {}  # hash: (response, timestamp)
        self.cache_ttl = 3600  # 1 час
    
    async def analyze_interest(self, message: str, context: List[str]) -> int:
        """Анализ заинтересованности с кэшированием"""
        # Создаем хэш для кэширования
        cache_key = hash(message + str(context))
        
        if cache_key in self.response_cache:
            cached_response, timestamp = self.response_cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return cached_response
        
        if not self.client or not self.client.client:
            return await self._simple_analysis(message)
        
        try:
            context_str = "\n".join(context[-3:]) if context else ""
            
            prompt = f"""Оцени заинтересованность клиента в покупке AI-CRM услуг по шкале 0-100.

ВЫСОКИЙ ИНТЕРЕС (80-100):
- Прямые намерения: "хочу купить", "готов заказать", "нужно купить"
- Бюджетные вопросы: "какая цена", "сколько стоит", "бюджет есть"
- Срочность: "срочно нужно", "сегодня", "немедленно"

СРЕДНИЙ ИНТЕРЕС (50-79):
- Исследование: "расскажите подробнее", "как работает", "возможности"
- Сравнение: "что лучше", "сравнить с", "альтернативы"

НИЗКИЙ ИНТЕРЕС (0-49):
- Отказ: "не нужно", "дорого", "не подходит"
- Неопределенность: "подумаю", "возможно", "не знаю"

СООБЩЕНИЕ: "{message}"
КОНТЕКСТ: {context_str}

Ответь ТОЛЬКО числом 0-100."""

            response = await asyncio.wait_for(
                self.client.client.messages.create(
                    model=self.client.model,
                    max_tokens=10,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1
                ),
                timeout=8.0
            )
            
            # Извлекаем число из ответа
            score_text = ''.join(filter(str.isdigit, response.content[0].text))
            score = int(score_text) if score_text else 0
            score = max(0, min(100, score))
            
            # Кэшируем результат
            self.response_cache[cache_key] = (score, time.time())
            self._cleanup_cache()
            
            return score
            
        except asyncio.TimeoutError:
            logger.warning("Claude API timeout, using simple analysis")
            return await self._simple_analysis(message)
        except Exception as e:
            logger.warning(f"Claude API error: {e}, using simple analysis")
            return await self._simple_analysis(message)
    
    async def _simple_analysis(self, message: str) -> int:
        """Простой анализ без AI"""
        message_lower = message.lower()
        
        # Паттерны для анализа
        high_interest = ['купить', 'заказать', 'цена', 'стоимость', 'готов']
        medium_interest = ['интересно', 'подробнее', 'расскажите', 'как работает']
        low_interest = ['дорого', 'не нужно', 'не интересно']
        
        score = 40  # Базовый скор
        
        for word in high_interest:
            if word in message_lower:
                score += 20
                break
        
        for word in medium_interest:
            if word in message_lower:
                score += 10
                break
        
        for word in low_interest:
            if word in message_lower:
                score -= 20
                break
        
        if '?' in message:
            score += 10  # Вопросы показывают интерес
        
        return max(0, min(100, score))
    
    async def generate_response(self, message: str, context: List[str], interest_score: int) -> str:
        """Генерация ответа"""
        if not self.client or not self.client.client:
            return self._simple_response(message, interest_score)
        
        try:
            context_str = "\n".join(context[-3:]) if context else ""
            
            # Определяем стратегию ответа
            if interest_score >= 80:
                strategy = "продажи"
                instruction = "Активно направляй к покупке, предлагай консультацию, создавай срочность"
            elif interest_score >= 50:
                strategy = "информирование"
                instruction = "Предоставь полезную информацию, мягко направляй к следующему шагу"
            else:
                strategy = "поддержка"
                instruction = "Будь полезным без навязывания, оставь дверь открытой"
            
            prompt = f"""Ты - профессиональный AI-консультант CRM компании.

СТРАТЕГИЯ: {strategy}
ИНСТРУКЦИЯ: {instruction}

НАШИ УСЛУГИ:
- AI-CRM системы и автоматизация продаж
- Telegram боты для бизнеса
- Интеграции с API и существующими системами
- Аналитика и отчетность

ПРАВИЛА:
✅ Естественный и дружелюбный тон
✅ Конкретные предложения действий
✅ Максимум 150 слов
✅ Используй эмодзи умеренно

ДАННЫЕ:
Сообщение: "{message}"
Заинтересованность: {interest_score}/100
Контекст: {context_str}

Сгенерируй персонализированный ответ:"""

            response = await asyncio.wait_for(
                self.client.client.messages.create(
                    model=self.client.model,
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7
                ),
                timeout=10.0
            )
            
            return response.content[0].text.strip()
            
        except Exception as e:
            logger.warning(f"Claude response generation failed: {e}")
            return self._simple_response(message, interest_score)
    
    def _simple_response(self, message: str, interest_score: int) -> str:
        """Простая генерация ответа"""
        if interest_score >= 80:
            return "Отлично! Вижу серьезную заинтересованность. Наш специалист свяжется с вами в течение 15 минут для обсуждения деталей и специального предложения! 🚀"
        elif interest_score >= 60:
            return "Спасибо за интерес! Мы поможем автоматизировать ваши процессы. Готов ответить на любые вопросы или организовать демонстрацию системы. 😊"
        elif interest_score >= 40:
            return "Понимаю ваши потребности. Если появятся вопросы о автоматизации или CRM - всегда готов помочь! 👍"
        else:
            return "Спасибо за сообщение! Если понадобится помощь с бизнес-процессами - обращайтесь. 🤝"
    
    def _cleanup_cache(self):
        """Очистка устаревшего кэша"""
        if len(self.response_cache) > 100:
            current_time = time.time()
            expired_keys = [
                key for key, (_, timestamp) in self.response_cache.items()
                if current_time - timestamp > self.cache_ttl
            ]
            for key in expired_keys:
                del self.response_cache[key]

class SmartResponseGenerator(ResponseGenerator):
    """Умный генератор ответов"""
    
    def __init__(self, message_analyzer: MessageAnalyzer):
        self.analyzer = message_analyzer
        self.response_templates = self._load_response_templates()
    
    async def generate(self, response_context: ResponseContext) -> str:
        """Генерация персонализированного ответа"""
        try:
            # Используем AI для генерации если доступен
            if hasattr(self.analyzer, 'generate_response'):
                return await self.analyzer.generate_response(
                    response_context.user_context.message_text,
                    response_context.conversation_history,
                    response_context.interest_score
                )
            
            # Fallback на шаблоны
            return self._template_response(response_context)
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "Спасибо за сообщение! Наш специалист свяжется с вами."
    
    def _template_response(self, context: ResponseContext) -> str:
        """Ответ на основе шаблонов"""
        score = context.interest_score
        
        if score >= 85:
            template = self.response_templates['ultra_hot']
        elif score >= 70:
            template = self.response_templates['hot']
        elif score >= 50:
            template = self.response_templates['warm']
        else:
            template = self.response_templates['cold']
        
        # Персонализация
        name = context.user_context.first_name or "Друг"
        
        return template.format(
            name=name,
            score=score,
            is_new=context.user_context.is_new_user
        )
    
    def _load_response_templates(self) -> Dict[str, str]:
        """Загрузка шаблонов ответов"""
        return {
            'ultra_hot': "🔥 {name}, вижу серьезные намерения! Наш топ-менеджер свяжется с вами в течение 10 минут с эксклюзивным предложением. Готовы обсудить детали?",
            'hot': "⭐ {name}, отлично! Вы на правильном пути к автоматизации. Организуем персональную демонстрацию нашей CRM-системы?",
            'warm': "👍 {name}, понимаю ваш интерес. Готов ответить на вопросы о наших решениях. Что именно вас больше всего интересует?",
            'cold': "🤝 {name}, спасибо за обращение! Если появятся вопросы о автоматизации бизнеса - всегда рад помочь."
        }

# === ГЛАВНЫЙ КЛАСС ОБРАБОТЧИКА ===

class OptimizedUserHandler:
    """Оптимизированный обработчик пользователей"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.messages_config = config.get('messages', {})
        self.features = config.get('features', {})
        
        # Компоненты оптимизации
        self.session_cache = UserSessionCache()
        self.message_throttler = MessageThrottler()
        
        # AI компоненты
        self.message_analyzer = ClaudeMessageAnalyzer()
        self.response_generator = SmartResponseGenerator(self.message_analyzer)
        
        # Инициализация Claude
        self._init_claude_client()
        
        # Callback handler
        self.callback_handler = CallbackQueryHandler(
            self.handle_callback,
            pattern=r'^(main_menu|help|contact|about|service_).*$'
        )
        
        # Метрики
        self.metrics = {
            'messages_processed': 0,
            'responses_generated': 0,
            'ai_analysis_count': 0,
            'cache_hits': 0,
            'errors': 0
        }
        
        # Запуск фоновых задач
        asyncio.create_task(self._background_cleanup())
        
        logger.info("OptimizedUserHandler инициализирован с AI и кэшированием")

    def _init_claude_client(self):
        """Инициализация Claude клиента"""
        try:
            init_claude_client(self.config)
            logger.info("Claude клиент инициализирован в UserHandler")
        except Exception as e:
            logger.warning(f"Не удалось инициализировать Claude: {e}")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /start с аналитикой"""
        start_time = time.time()
        
        try:
            user_data = update.effective_user
            logger.info(f"Start command from user {user_data.id} (@{user_data.username})")
            
            # Создаем или обновляем пользователя
            user = User(
                telegram_id=user_data.id,
                username=user_data.username,
                first_name=user_data.first_name,
                last_name=user_data.last_name
            )
            
            # Проверяем, новый ли пользователь
            existing_user = await get_user_by_telegram_id(user_data.id)
            is_new_user = existing_user is None
            
            await create_user(user)
            
            # Обновляем сессию
            self.session_cache.update_session(
                user_data.id,
                is_new_user=is_new_user,
                first_name=user_data.first_name,
                username=user_data.username
            )
            
            # Персонализированное приветствие
            welcome_message = self.messages_config.get('welcome', 
                '🤖 Добро пожаловать в AI-CRM бот!')
            
            if is_new_user:
                welcome_message += f"\n\n👋 {user_data.first_name}, рады видеть вас впервые!"
            else:
                welcome_message += f"\n\n🔄 {user_data.first_name}, добро пожаловать обратно!"
            
            keyboard = self._get_dynamic_keyboard(user_data.id, is_new_user)
            
            await update.message.reply_text(
                welcome_message,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            
            # Обновляем метрики
            self.metrics['messages_processed'] += 1
            processing_time = time.time() - start_time
            
            if processing_time > 1.0:
                logger.warning(f"Slow start command processing: {processing_time:.2f}s")
            
        except Exception as e:
            self.metrics['errors'] += 1
            logger.error(f"Error in start command: {e}")
            await update.message.reply_text("Добро пожаловать! Произошла небольшая ошибка, но я готов работать.")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /help с контекстом"""
        try:
            user_id = update.effective_user.id
            session = self.session_cache.get_session(user_id)
            
            # Персонализированная справка
            help_message = self.messages_config.get('help', 'ℹ️ Помощь:')
            
            # Добавляем контекстную информацию
            if session.get('messages_count', 0) > 0:
                help_message += f"\n\n📊 Вы отправили {session['messages_count']} сообщений"
                
                if session.get('last_interest_score', 0) > 70:
                    help_message += "\n🔥 Наш специалист готов связаться с вами!"
            
            keyboard = self._get_help_keyboard(user_id)
            
            await update.message.reply_text(
                help_message,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            
            self.metrics['messages_processed'] += 1
            
        except Exception as e:
            self.metrics['errors'] += 1
            logger.error(f"Error in help command: {e}")

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /menu с персонализацией"""
        try:
            user_id = update.effective_user.id
            session = self.session_cache.get_session(user_id)
            
            menu_message = self.messages_config.get('menu', '📋 Главное меню:')
            
            # Добавляем рекомендации на основе истории
            if session.get('last_interest_score', 0) > 60:
                menu_message += "\n\n💡 Рекомендуем: связаться с консультантом"
            
            keyboard = self._get_dynamic_keyboard(user_id, session.get('is_new_user', False))
            
            await update.message.reply_text(
                menu_message,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            
            self.metrics['messages_processed'] += 1
            
        except Exception as e:
            self.metrics['errors'] += 1
            logger.error(f"Error in menu command: {e}")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Оптимизированная обработка сообщений"""
        start_time = time.time()
        
        try:
            user_data = update.effective_user
            message = update.message
            
            if not user_data or not message or not message.text:
                return
            
            # Проверка throttling
            if not self.message_throttler.can_send_message(user_data.id):
                logger.warning(f"Message throttled for user {user_data.id}")
                return
            
            # Получаем/создаем сессию
            session = self.session_cache.get_session(user_data.id)
            session['messages_count'] += 1
            
            # Создаем контекст взаимодействия
            interaction_context = UserInteractionContext(
                user_id=user_data.id,
                username=user_data.username,
                first_name=user_data.first_name,
                message_text=message.text,
                chat_type=update.effective_chat.type,
                timestamp=datetime.now(),
                is_new_user=session.get('is_new_user', False),
                interaction_count=session['messages_count']
            )
            
            logger.info(f"Processing message from {user_data.first_name} ({user_data.id}): {message.text[:50]}...")
            
            # Обновляем пользователя в БД асинхронно
            asyncio.create_task(self._update_user_async(user_data))
            
            # Получаем историю разговора
            conversation_history = session.get('conversation_history', [])
            conversation_history.append(message.text)
            if len(conversation_history) > 5:
                conversation_history = conversation_history[-5:]
            session['conversation_history'] = conversation_history
            
            # Анализ заинтересованности
            try:
                interest_score = await self.message_analyzer.analyze_interest(
                    message.text, conversation_history
                )
                session['last_interest_score'] = interest_score
                self.metrics['ai_analysis_count'] += 1
                
            except Exception as e:
                logger.warning(f"Interest analysis failed: {e}")
                interest_score = 50  # Нейтральный скор по умолчанию
            
            # Сохраняем сообщение если включено
            if self.features.get('save_all_messages', True):
                asyncio.create_task(self._save_message_async(message, user_data.id, interest_score))
            
            # Генерация ответа если включены автоответы
            if self.features.get('auto_response', True):
                response_context = ResponseContext(
                    interest_score=interest_score,
                    user_context=interaction_context,
                    conversation_history=conversation_history,
                    response_strategy=session.get('response_strategy', 'standard'),
                    personalization_data=session.get('personalization', {})
                )
                
                try:
                    response_text = await self.response_generator.generate(response_context)
                    keyboard = self._get_contextual_keyboard(interest_score, user_data.id)
                    
                    await message.reply_text(
                        response_text,
                        reply_markup=keyboard,
                        parse_mode='HTML'
                    )
                    
                    self.metrics['responses_generated'] += 1
                    
                except Exception as e:
                    logger.error(f"Response generation failed: {e}")
                    await message.reply_text("Спасибо за сообщение! Обрабатываем ваш запрос.")
            
            # Обновляем метрики
            self.metrics['messages_processed'] += 1
            processing_time = time.time() - start_time
            
            logger.info(f"Message processed: score={interest_score}, time={processing_time:.3f}s")
            
            if processing_time > 2.0:
                logger.warning(f"Slow message processing: {processing_time:.2f}s for user {user_data.id}")
            
        except Exception as e:
            self.metrics['errors'] += 1
            logger.error(f"Error processing message: {e}")
            
            try:
                await update.message.reply_text("Спасибо за сообщение! Мы обработаем его в ближайшее время.")
            except:
                logger.error("Failed to send error message")

    async def _update_user_async(self, user_data: TelegramUser):
        """Асинхронное обновление пользователя"""
        try:
            await update_user_activity(user_data.id)
        except Exception as e:
            logger.error(f"Error updating user activity: {e}")

    async def _save_message_async(self, message, user_id: int, interest_score: int):
        """Асинхронное сохранение сообщения"""
        try:
            msg = Message(
                telegram_message_id=message.message_id,
                user_id=user_id,
                chat_id=message.chat.id,
                text=message.text,
                interest_score=interest_score
            )
            await save_message(msg)
        except Exception as e:
            logger.error(f"Error saving message: {e}")

    def _get_dynamic_keyboard(self, user_id: int, is_new_user: bool):
        """Динамическая клавиатура на основе контекста"""
        session = self.session_cache.get_session(user_id)
        interest_score = session.get('last_interest_score', 0)
        
        if interest_score >= 70:
            # Для заинтересованных пользователей
            keyboard = [
                [
                    InlineKeyboardButton("🔥 Связаться с менеджером", callback_data="contact"),
                    InlineKeyboardButton("📊 Демо системы", callback_data="service_demo")
                ],
                [
                    InlineKeyboardButton("💰 Узнать цены", callback_data="service_pricing"),
                    InlineKeyboardButton("📋 Кейсы клиентов", callback_data="service_cases")
                ]
            ]
        elif is_new_user:
            # Для новых пользователей
            keyboard = [
                [
                    InlineKeyboardButton("🚀 Что мы делаем?", callback_data="about"),
                    InlineKeyboardButton("💡 Как это работает?", callback_data="service_how")
                ],
                [
                    InlineKeyboardButton("📞 Контакты", callback_data="contact"),
                    InlineKeyboardButton("ℹ️ Помощь", callback_data="help")
                ]
            ]
        else:
            # Стандартная клавиатура
            keyboard = [
                [
                    InlineKeyboardButton("📞 Контакты", callback_data="contact"),
                    InlineKeyboardButton("ℹ️ Помощь", callback_data="help")
                ],
                [
                    InlineKeyboardButton("📋 О компании", callback_data="about")
                ]
            ]
        
        return InlineKeyboardMarkup(keyboard)

    def _get_contextual_keyboard(self, interest_score: int, user_id: int):
        """Контекстная клавиатура на основе скора"""
        if interest_score >= 80:
            keyboard = [
                [
                    InlineKeyboardButton("🔥 СРОЧНО: Связаться!", callback_data="contact"),
                    InlineKeyboardButton("📊 Демо за 5 минут", callback_data="service_demo")
                ]
            ]
        elif interest_score >= 60:
            keyboard = [
                [
                    InlineKeyboardButton("💬 Консультация", callback_data="contact"),
                    InlineKeyboardButton("📋 Подробнее", callback_data="about")
                ],
                [
                    InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")
                ]
            ]
        else:
            keyboard = [
                [
                    InlineKeyboardButton("ℹ️ Помощь", callback_data="help"),
                    InlineKeyboardButton("📞 Контакты", callback_data="contact")
                ],
                [
                    InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")
                ]
            ]
        
        return InlineKeyboardMarkup(keyboard)

    def _get_help_keyboard(self, user_id: int):
        """Клавиатура для справки"""
        session = self.session_cache.get_session(user_id)
        
        keyboard = [
            [
                InlineKeyboardButton("🚀 Возможности", callback_data="service_features"),
                InlineKeyboardButton("💰 Цены", callback_data="service_pricing")
            ]
        ]
        
        if session.get('last_interest_score', 0) > 50:
            keyboard.insert(0, [
                InlineKeyboardButton("💬 Связаться с экспертом", callback_data="contact")
            ])
        
        keyboard.append([InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")])
        
        return InlineKeyboardMarkup(keyboard)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка callback запросов"""
        query = update.callback_query
        
        try:
            data = query.data
            user_id = query.from_user.id
            
            # Обновляем сессию
            session = self.session_cache.get_session(user_id)
            
            await query.answer()
            logger.info(f"User callback: {data} from user {user_id}")
            
            # Обработчики callback'ов
            callback_handlers = {
                "main_menu": self._show_main_menu,
                "help": self._show_help,
                "contact": self._show_contact,
                "about": self._show_about,
                "service_demo": self._show_service_demo,
                "service_pricing": self._show_service_pricing,
                "service_features": self._show_service_features,
                "service_cases": self._show_service_cases,
                "service_how": self._show_how_it_works
            }
            
            handler = callback_handlers.get(data)
            if handler:
                await handler(query)
            else:
                logger.warning(f"Unknown user callback: {data}")
                
        except Exception as e:
            logger.error(f"Error handling user callback: {e}")
            try:
                await query.edit_message_text("❌ Произошла ошибка. Попробуйте еще раз.")
            except:
                pass

    async def _show_main_menu(self, query):
        """Показать главное меню"""
        user_id = query.from_user.id
        session = self.session_cache.get_session(user_id)
        
        menu_message = self.messages_config.get('menu', '📋 Главное меню:')
        
        if session.get('last_interest_score', 0) > 60:
            menu_message += "\n\n💡 Наш специалист готов связаться с вами!"
        
        keyboard = self._get_dynamic_keyboard(user_id, session.get('is_new_user', False))
        
        try:
            await query.edit_message_text(
                menu_message,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error showing main menu: {e}")

    async def _show_help(self, query):
        """Показать справку"""
        help_message = """ℹ️ <b>Справка по AI-CRM боту</b>

🤖 <b>Что я умею:</b>
• Консультирую по AI-CRM решениям
• Помогаю выбрать подходящую систему
• Организую демонстрации и презентации
• Отвечаю на вопросы о автоматизации

💬 <b>Как со мной работать:</b>
• Просто напишите ваш вопрос
• Используйте кнопки для быстрой навигации
• Задавайте конкретные вопросы о бизнесе

🚀 <b>Популярные вопросы:</b>
• "Что такое CRM и зачем она нужна?"
• "Сколько стоит автоматизация?"
• "Как интегрировать с существующими системами?"

📞 Если нужна персональная консультация - нажмите "Контакты"!"""

        keyboard = [
            [
                InlineKeyboardButton("💬 Связаться с экспертом", callback_data="contact"),
                InlineKeyboardButton("🚀 Возможности", callback_data="service_features")
            ],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
        ]
        
        try:
            await query.edit_message_text(
                help_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error showing help: {e}")

    async def _show_contact(self, query):
        """Показать контактную информацию"""
        contact_message = self.messages_config.get('contact', 
            """📞 <b>Свяжитесь с нами</b>

🚀 <b>Готовы к автоматизации?</b>

📱 <b>Telegram:</b> @support_aicrm
📧 <b>Email:</b> hello@aicrm.com
☎️ <b>Телефон:</b> +7 (999) 123-45-67
🌐 <b>Сайт:</b> aicrm.com

⏰ <b>Работаем:</b> 24/7 для вашего удобства!

🎯 <b>Что происходит дальше:</b>
1. Наш эксперт свяжется с вами в течение 15 минут
2. Проведем бесплатный аудит ваших процессов
3. Предложим персональное решение
4. Организуем демонстрацию системы

💡 <b>Бесплатная консультация</b> - узнайте, как увеличить продажи на 40%!""")
        
        keyboard = [
            [
                InlineKeyboardButton("📊 Бесплатный аудит", callback_data="service_audit"),
                InlineKeyboardButton("📋 О компании", callback_data="about")
            ],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
        ]
        
        try:
            await query.edit_message_text(
                contact_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error showing contact: {e}")

    async def _show_about(self, query):
        """Показать информацию о компании"""
        about_message = """📋 <b>AI-CRM Solutions - ваш партнер в автоматизации</b>

🚀 <b>Мы специализируемся на:</b>
• AI-CRM системы нового поколения
• Telegram боты для автоматизации продаж
• Интеграции с любыми системами
• Аналитика и прогнозирование

📈 <b>Наши результаты:</b>
• 🔥 Увеличение продаж до 40%
• ⚡ Автоматизация 80% процессов
• ⏰ Экономия времени до 60%
• 💰 ROI от 300% за первый год

🏆 <b>Почему выбирают нас:</b>
• ✅ 5+ лет опыта в автоматизации
• ✅ 200+ успешных проектов
• ✅ Поддержка 24/7
• ✅ Гарантия результата
• ✅ Индивидуальный подход

👥 <b>Наши клиенты:</b>
От стартапов до корпораций - помогаем расти всем!

🎯 <b>Готовы к росту?</b> Начните с бесплатной консультации!"""

        keyboard = [
            [
                InlineKeyboardButton("💬 Связаться", callback_data="contact"),
                InlineKeyboardButton("📊 Кейсы клиентов", callback_data="service_cases")
            ],
            [
                InlineKeyboardButton("💰 Узнать цены", callback_data="service_pricing"),
                InlineKeyboardButton("🔙 Меню", callback_data="main_menu")
            ]
        ]
        
        try:
            await query.edit_message_text(
                about_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error showing about: {e}")

    async def _show_service_demo(self, query):
        """Показать информацию о демо"""
        demo_message = """📊 <b>Демонстрация AI-CRM системы</b>

🚀 <b>Что вы увидите за 15 минут:</b>

🎯 <b>Автоматизация продаж:</b>
• Автоматический захват лидов
• Скоринг клиентов по AI
• Персонализированные предложения

📱 <b>Telegram интеграция:</b>
• Боты для сбора заявок
• Автоматические ответы клиентам
• Уведомления менеджерам

📈 <b>Аналитика в реальном времени:</b>
• Дашборд с ключевыми метриками
• Прогнозы продаж
• Отчеты по эффективности

🔗 <b>Интеграции:</b>
• Любые CRM (AmoCRM, Битрикс24)
• Мессенджеры и соцсети
• 1С, банки, платежные системы

⏰ <b>Доступные слоты:</b>
• Сегодня: 14:00, 16:30, 19:00
• Завтра: 10:00, 15:00, 18:30

💡 <b>Демо полностью бесплатно!</b> Забронируйте удобное время."""

        keyboard = [
            [
                InlineKeyboardButton("🔥 Забронировать демо", callback_data="contact"),
                InlineKeyboardButton("💰 Узнать цены", callback_data="service_pricing")
            ],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        
        try:
            await query.edit_message_text(
                demo_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error showing demo info: {e}")

    async def _show_service_pricing(self, query):
        """Показать информацию о ценах"""
        pricing_message = """💰 <b>Тарифы AI-CRM Solutions</b>

🚀 <b>СТАРТ</b> - 15,000₽/мес
• До 1,000 лидов
• Базовый Telegram бот
• CRM интеграция
• Email поддержка

⭐ <b>БИЗНЕС</b> - 35,000₽/мес
• До 5,000 лидов
• AI-скоринг клиентов
• Мультиканальность
• Аналитика и отчеты
• Приоритетная поддержка

🔥 <b>КОРПОРАТИВ</b> - 75,000₽/мес
• Неограниченно лидов
• Полная автоматизация
• Персональный менеджер
• Кастомизация под задачи
• SLA 99.9%

💎 <b>ИНДИВИДУАЛЬНЫЙ</b> - по запросу
• Разработка под ключ
• Собственная команда
• Уникальный функционал

🎁 <b>СПЕЦИАЛЬНОЕ ПРЕДЛОЖЕНИЕ:</b>
• Первый месяц БЕСПЛАТНО
• Настройка и обучение - в подарок
• Гарантия возврата средств 30 дней

💡 Точная стоимость зависит от ваших задач. Рассчитаем персонально!"""

        keyboard = [
            [
                InlineKeyboardButton("🎁 Получить скидку", callback_data="contact"),
                InlineKeyboardButton("📊 Бесплатный расчет", callback_data="service_demo")
            ],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        
        try:
            await query.edit_message_text(
                pricing_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error showing pricing: {e}")

    async def _show_service_features(self, query):
        """Показать возможности системы"""
        features_message = """🚀 <b>Возможности AI-CRM системы</b>

🤖 <b>Искусственный интеллект:</b>
• Автоматический анализ клиентов
• Предсказание вероятности покупки
• Персонализация предложений
• Оптимизация воронки продаж

📱 <b>Telegram автоматизация:</b>
• Боты для захвата лидов
• Автоматические квалификации
• Мгновенные уведомления
• Чат-боты поддержки

📊 <b>Аналитика и отчеты:</b>
• Дашборд в реальном времени
• Прогнозы продаж
• A/B тестирование
• Детализация по источникам

🔗 <b>Интеграции:</b>
• Популярные CRM системы
• Социальные сети
• Email маркетинг
• Платежные системы
• 1С и учетные системы

⚡ <b>Автоматизация:</b>
• Распределение лидов
• Напоминания и задачи
• Email/SMS рассылки
• Автоматические отчеты

🛡️ <b>Безопасность:</b>
• Шифрование данных
• Регулярные backup
• Соответствие 152-ФЗ
• Двухфакторная аутентификация"""

        keyboard = [
            [
                InlineKeyboardButton("📊 Демо возможностей", callback_data="service_demo"),
                InlineKeyboardButton("💰 Узнать цены", callback_data="service_pricing")
            ],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        
        try:
            await query.edit_message_text(
                features_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error showing features: {e}")

    async def _show_service_cases(self, query):
        """Показать кейсы клиентов"""
        cases_message = """📊 <b>Кейсы наших клиентов</b>

🏢 <b>ТехноСтарт (IT-услуги):</b>
• Проблема: терялись лиды из соцсетей
• Решение: AI-бот для Telegram и VK
• Результат: +150% лидов, -60% время обработки

🏪 <b>МегаРетейл (интернет-магазин):</b>
• Проблема: низкая конверсия корзины
• Решение: персонализация + автоматизация
• Результат: +80% продаж, +40% средний чек

🏭 <b>ПроизводствоПлюс (B2B):</b>
• Проблема: долгий цикл продаж
• Решение: AI-скоринг + автоматизация
• Результат: -50% время сделки, +200% прибыль

💼 <b>КонсалтингПро (услуги):</b>
• Проблема: ручная обработка заявок
• Решение: полная автоматизация воронки
• Результат: +300% клиентов, команда x3

📈 <b>Средние результаты по всем клиентам:</b>
• Увеличение лидов: +120%
• Рост конверсии: +85%
• Экономия времени: +60%
• ROI первого года: +250%

🎯 <b>Хотите такие же результаты?</b>
Начните с бесплатного аудита вашей воронки!"""

        keyboard = [
            [
                InlineKeyboardButton("🎁 Бесплатный аудит", callback_data="contact"),
                InlineKeyboardButton("📊 Демо решения", callback_data="service_demo")
            ],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        
        try:
            await query.edit_message_text(
                cases_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error showing cases: {e}")

    async def _show_how_it_works(self, query):
        """Показать как это работает"""
        how_message = """💡 <b>Как работает AI-CRM автоматизация</b>

🔄 <b>Простой процесс в 4 шага:</b>

<b>1️⃣ СБОР ЛИДОВ</b>
• Telegram боты захватывают заявки
• Интеграция с сайтом и соцсетями
• Автоматическое создание карточек клиентов

<b>2️⃣ AI-АНАЛИЗ</b>
• Система анализирует каждого клиента
• Определяет вероятность покупки
• Присваивает приоритет и метки

<b>3️⃣ АВТОМАТИЗАЦИЯ</b>
• Персонализированные сообщения
• Автоматическое распределение менеджерам
• Напоминания и задачи

<b>4️⃣ АНАЛИТИКА</b>
• Отслеживание всех метрик
• Прогнозы и рекомендации
• Автоматические отчеты

⚡ <b>Время внедрения:</b> 1-2 недели
🎯 <b>Результат:</b> рост продаж с первого дня
📚 <b>Обучение:</b> наша команда научит всему

🚀 <b>Готовы начать?</b> Первая консультация бесплатно!"""

        keyboard = [
            [
                InlineKeyboardButton("🎁 Бесплатная консультация", callback_data="contact"),
                InlineKeyboardButton("📊 Увидеть демо", callback_data="service_demo")
            ],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        
        try:
            await query.edit_message_text(
                how_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error showing how it works: {e}")

    async def _background_cleanup(self):
        """Фоновая очистка кэшей"""
        while True:
            try:
                await asyncio.sleep(1800)  # Каждые 30 минут
                
                # Очистка сессий
                self.session_cache.cleanup_expired()
                
                # Очистка кэша анализатора
                if hasattr(self.message_analyzer, '_cleanup_cache'):
                    self.message_analyzer._cleanup_cache()
                
                logger.debug("Background cleanup completed")
                
            except Exception as e:
                logger.error(f"Error in background cleanup: {e}")

    def get_metrics(self) -> Dict[str, Any]:
        """Получение метрик обработчика"""
        return {
            **self.metrics,
            'active_sessions': len(self.session_cache.sessions),
            'cache_hits': self.metrics.get('cache_hits', 0),
            'avg_interest_score': self._calculate_avg_interest_score()
        }

    def _calculate_avg_interest_score(self) -> float:
        """Расчет среднего скора заинтересованности"""
        scores = [
            session.get('last_interest_score', 0) 
            for session in self.session_cache.sessions.values()
            if session.get('last_interest_score', 0) > 0
        ]
        return sum(scores) / len(scores) if scores else 0

# Алиас для совместимости
UserHandler = OptimizedUserHandler
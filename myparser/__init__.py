"""
myparser/__init__.py - ИСПРАВЛЕННАЯ версия с правильными импортами
Решение проблемы DialogueParticipant vs ParticipantInfo
"""

import logging

logger = logging.getLogger(__name__)

try:
    # ИСПРАВЛЕНИЕ: Импортируем правильные классы из main_parser.py
    from .main_parser import (
        OptimizedUnifiedParser,
        UnifiedAIParser,
        SmartDialogueTracker,
        ClaudeMessageAnalyzer,
        SimpleMessageAnalyzer,
        ParticipantInfo,  # ИСПРАВЛЕНО: используем ParticipantInfo вместо DialogueParticipant
        DialogueContext,
        AnalysisResult,
        AnalyzerFactory,
        NotificationFactory,
        BaseMessageAnalyzer,
        BaseNotificationSender,
        TelegramNotificationSender
    )
    
    # Создаем алиасы для совместимости
    DialogueParticipant = ParticipantInfo  # ИСПРАВЛЕНИЕ: алиас для совместимости
    DialogueTracker = SmartDialogueTracker
    DialogueAnalyzer = ClaudeMessageAnalyzer
    AIContextParser = OptimizedUnifiedParser
    IntegratedAIContextParser = OptimizedUnifiedParser
    
    # ИСПРАВЛЕНИЕ: Создаем заглушки для отсутствующих классов
    class DialogueMessage:
        """Заглушка для DialogueMessage"""
        def __init__(self, user_id: int = 0, text: str = "", timestamp=None):
            self.user_id = user_id
            self.text = text
            self.timestamp = timestamp
    
    class DialogueAnalysisResult:
        """Заглушка для DialogueAnalysisResult"""
        def __init__(self, is_valuable: bool = False, confidence: float = 0.0):
            self.is_valuable = is_valuable
            self.confidence = confidence
    
    class AIAnalysisResult:
        """Заглушка для AIAnalysisResult"""
        def __init__(self, interest_score: int = 0, quality: str = "unknown"):
            self.interest_score = interest_score
            self.quality = quality
    
    class UserContext:
        """Заглушка для UserContext"""
        def __init__(self, user_id: int = 0, messages=None):
            self.user_id = user_id
            self.messages = messages or []
    
    __all__ = [
        # Основные классы
        'OptimizedUnifiedParser',
        'UnifiedAIParser',
        'SmartDialogueTracker',
        'ClaudeMessageAnalyzer',
        'SimpleMessageAnalyzer',
        
        # Модели данных (ИСПРАВЛЕНО)
        'ParticipantInfo',
        'DialogueContext',
        'AnalysisResult',
        'DialogueMessage',
        'DialogueAnalysisResult',
        'AIAnalysisResult',
        'UserContext',
        
        # Фабрики
        'AnalyzerFactory',
        'NotificationFactory',
        
        # Базовые классы
        'BaseMessageAnalyzer',
        'BaseNotificationSender',
        'TelegramNotificationSender',
        
        # Алиасы для совместимости
        'DialogueParticipant',  # ИСПРАВЛЕНИЕ: теперь это алиас ParticipantInfo
        'DialogueTracker',
        'DialogueAnalyzer',
        'AIContextParser',
        'IntegratedAIContextParser'
    ]
    
    logger.info("✅ Исправленный парсер загружен успешно с правильными импортами")
    
except ImportError as e:
    # ИСПРАВЛЕНИЕ: Улучшенный fallback парсер
    logger.error(f"❌ Не удалось загрузить основной парсер: {e}")
    logger.info("🔄 Используем улучшенный fallback парсер")
    
    # Создаем минимальный но функциональный fallback парсер
    class FallbackParser:
        """Улучшенный fallback парсер с базовой функциональностью"""
        
        def __init__(self, config):
            self.config = config
            self.enabled = config.get('parsing', {}).get('enabled', False)
            self.channels = self._parse_channels(config)
            logger.warning("⚠️ Используется fallback парсер")
        
        def _parse_channels(self, config):
            """Парсинг каналов из конфигурации"""
            channels = config.get('parsing', {}).get('channels', [])
            if isinstance(channels, list):
                return [str(ch) for ch in channels]
            elif isinstance(channels, (str, int)):
                return [str(channels)]
            return []
        
        async def process_message(self, update, context):
            """Базовая обработка сообщений"""
            try:
                if not self.enabled:
                    return
                
                chat = update.effective_chat
                user = update.effective_user
                message = update.message
                
                if not user or not message or not message.text:
                    return
                
                # Простой анализ покупательских сигналов
                text_lower = message.text.lower()
                business_keywords = [
                    'купить', 'заказать', 'цена', 'стоимость', 'бюджет',
                    'crm', 'автоматизация', 'интеграция', 'бот'
                ]
                
                found_keywords = [kw for kw in business_keywords if kw in text_lower]
                
                if found_keywords:
                    logger.info(f"Fallback parser: найдены ключевые слова {found_keywords} от {user.first_name}")
                    
                    # Можно добавить создание лида здесь
                    if len(found_keywords) >= 2:  # Если найдено 2+ ключевых слова
                        await self._create_simple_lead(user, message, found_keywords, context)
                
            except Exception as e:
                logger.error(f"Ошибка в fallback parser: {e}")
        
        async def _create_simple_lead(self, user, message, keywords, context):
            """Создание простого лида"""
            try:
                from database.operations import create_lead
                from database.models import Lead
                from datetime import datetime
                
                # Простая оценка скора
                score = min(len(keywords) * 25, 100)
                
                lead = Lead(
                    telegram_id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    source_channel="Fallback parser",
                    interest_score=score,
                    message_text=message.text[:500],
                    message_date=datetime.now(),
                    lead_quality="warm" if score >= 50 else "cold",
                    notes=f"Fallback parser. Keywords: {', '.join(keywords)}"
                )
                
                await create_lead(lead)
                logger.info(f"Fallback parser: создан лид {user.first_name} ({score}%)")
                
                # Уведомление администраторам
                admin_ids = self.config.get('bot', {}).get('admin_ids', [])
                if admin_ids:
                    notification_text = f"""🎯 Новый лид (Fallback режим)

👤 {user.first_name} (@{user.username or 'no_username'})
📊 Скор: {score}%
🔍 Ключевые слова: {', '.join(keywords)}
💬 Сообщение: "{message.text[:100]}..."

⚠️ Система работает в fallback режиме"""

                    for admin_id in admin_ids:
                        try:
                            await context.bot.send_message(
                                chat_id=admin_id,
                                text=notification_text
                            )
                        except Exception as e:
                            logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
                
            except Exception as e:
                logger.error(f"Ошибка создания fallback лида: {e}")
        
        def is_channel_monitored(self, chat_id, username=None):
            """Проверка мониторинга канала"""
            if not self.enabled:
                return False
            
            # Проверяем по ID
            if str(chat_id) in self.channels:
                return True
            
            # Проверяем по username
            if username:
                username_variants = [f"@{username}", username]
                return any(variant in self.channels for variant in username_variants)
            
            return False
        
        def get_status(self):
            """Статус fallback парсера"""
            return {
                'enabled': self.enabled,
                'mode': 'fallback',
                'channels_count': len(self.channels),
                'channels': self.channels,
                'error': 'Основной парсер недоступен, используется fallback',
                'features': ['basic_keyword_detection', 'simple_lead_creation']
            }
        
        def get_performance_metrics(self):
            """Метрики fallback парсера"""
            return {
                'mode': 'fallback',
                'no_data': True,
                'message': 'Fallback parser - ограниченные метрики'
            }
    
    # Заглушки для остальных классов
    class DialogueTracker:
        def __init__(self, config): 
            self.config = config
            self.active_dialogues = {}
    
    class DialogueAnalyzer:
        def __init__(self, config): 
            self.config = config
    
    class ParticipantInfo:
        def __init__(self, user_id: int = 0, username: str = None, **kwargs):
            self.user_id = user_id
            self.username = username
            for k, v in kwargs.items():
                setattr(self, k, v)
    
    class DialogueContext:
        def __init__(self, dialogue_id: str = "", **kwargs):
            self.dialogue_id = dialogue_id
            self.participants = {}
            self.messages = []
            for k, v in kwargs.items():
                setattr(self, k, v)
    
    class AnalysisResult:
        def __init__(self, is_valuable: bool = False, **kwargs):
            self.is_valuable = is_valuable
            for k, v in kwargs.items():
                setattr(self, k, v)
    
    class DialogueMessage:
        def __init__(self, user_id: int = 0, text: str = "", **kwargs):
            self.user_id = user_id
            self.text = text
            for k, v in kwargs.items():
                setattr(self, k, v)
    
    class DialogueAnalysisResult:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    
    class UserContext:
        def __init__(self, user_id: int = 0, **kwargs):
            self.user_id = user_id
            for k, v in kwargs.items():
                setattr(self, k, v)
    
    class AIAnalysisResult:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    
    # Устанавливаем fallback как основные классы
    OptimizedUnifiedParser = FallbackParser
    UnifiedAIParser = FallbackParser
    AIContextParser = FallbackParser
    IntegratedAIContextParser = FallbackParser
    
    # Алиасы
    DialogueParticipant = ParticipantInfo
    SmartDialogueTracker = DialogueTracker
    ClaudeMessageAnalyzer = DialogueAnalyzer
    
    __all__ = [
        # Основные классы (fallback)
        'OptimizedUnifiedParser',
        'UnifiedAIParser',
        'DialogueTracker',
        'DialogueAnalyzer',
        
        # Модели данных
        'ParticipantInfo',
        'DialogueContext',
        'AnalysisResult',
        'DialogueMessage',
        'DialogueAnalysisResult',
        'AIAnalysisResult',
        'UserContext',
        
        # Алиасы для совместимости
        'DialogueParticipant',
        'SmartDialogueTracker',
        'ClaudeMessageAnalyzer',
        'AIContextParser',
        'IntegratedAIContextParser'
    ]
    
    logger.warning("⚠️ Используется fallback режим парсера")

# Дополнительная функция для проверки доступности парсера
def get_parser_status():
    """Получение статуса парсера"""
    try:
        # Проверяем доступность основного парсера
        from .main_parser import OptimizedUnifiedParser
        return {
            'available': True,
            'type': 'optimized',
            'features': ['ai_analysis', 'dialogue_tracking', 'advanced_notifications']
        }
    except ImportError:
        return {
            'available': False,
            'type': 'fallback',
            'features': ['basic_keyword_detection', 'simple_lead_creation'],
            'limitation': 'Основной парсер недоступен'
        }

# Функция для создания парсера с автоматическим fallback
def create_parser(config):
    """Создание парсера с автоматическим выбором"""
    status = get_parser_status()
    
    if status['available']:
        logger.info("✅ Создан оптимизированный парсер")
        return OptimizedUnifiedParser(config)
    else:
        logger.warning("⚠️ Создан fallback парсер")
        return OptimizedUnifiedParser(config)  # В fallback режиме это FallbackParser

# Экспортируем также утилитарные функции
__all__.extend(['get_parser_status', 'create_parser'])
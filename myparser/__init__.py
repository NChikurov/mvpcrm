"""
myparser/__init__.py - ИСПРАВЛЕННАЯ версия
Простой и надежный импорт основного парсера
"""

import logging

logger = logging.getLogger(__name__)

try:
    # Импортируем исправленный основной парсер
    from .main_parser import (
        UnifiedAIParser,
        DialogueTracker,
        DialogueAnalyzer,
        DialogueContext,
        DialogueParticipant,
        DialogueMessage,
        DialogueAnalysisResult,
        AIAnalysisResult,
        UserContext
    )
    
    # Основной класс для экспорта
    AIContextParser = UnifiedAIParser
    IntegratedAIContextParser = UnifiedAIParser
    
    __all__ = [
        'AIContextParser',
        'IntegratedAIContextParser', 
        'UnifiedAIParser',
        'DialogueTracker',
        'DialogueAnalyzer',
        'DialogueContext',
        'DialogueParticipant',
        'DialogueMessage',
        'DialogueAnalysisResult',
        'AIAnalysisResult',
        'UserContext'
    ]
    
    logger.info("✅ Исправленный UnifiedAIParser загружен успешно")
    
except ImportError as e:
    # Fallback на базовый парсер если основной не работает
    logger.error(f"❌ Не удалось загрузить основной парсер: {e}")
    logger.info("🔄 Используем минимальный fallback парсер")
    
    # Создаем минимальный fallback парсер
    class FallbackParser:
        def __init__(self, config):
            self.config = config
            self.enabled = config.get('parsing', {}).get('enabled', False)
            self.channels = []
            logger.warning("⚠️ Используется минимальный fallback парсер")
        
        async def process_message(self, update, context):
            logger.info("Fallback parser: сообщение проигнорировано")
        
        def is_channel_monitored(self, chat_id, username=None):
            return False
        
        def get_status(self):
            return {
                'enabled': False,
                'mode': 'fallback',
                'error': 'Основной парсер недоступен'
            }
    
    # Заглушки для остальных классов
    class DialogueTracker:
        def __init__(self, config): pass
    
    class DialogueAnalyzer:
        def __init__(self, config): pass
    
    class DialogueContext: pass
    class DialogueParticipant: pass
    class DialogueMessage: pass
    class DialogueAnalysisResult: pass
    class UserContext: pass
    class AIAnalysisResult: pass
    
    # Устанавливаем fallback как основной
    AIContextParser = FallbackParser
    IntegratedAIContextParser = FallbackParser
    UnifiedAIParser = FallbackParser
    
    __all__ = [
        'AIContextParser',
        'IntegratedAIContextParser',
        'UnifiedAIParser',
        'DialogueTracker',
        'DialogueAnalyzer',
        'DialogueContext',
        'DialogueParticipant',
        'DialogueMessage',
        'DialogueAnalysisResult',
        'AIAnalysisResult',
        'UserContext'
    ]
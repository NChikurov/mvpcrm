"""
MyParser - AI парсер каналов для поиска лидов
Версия с поддержкой анализа диалогов
"""

try:
    # Пытаемся импортировать интегрированный парсер
    from .integrated_ai_parser import IntegratedAIContextParser
    
    # Основной класс для экспорта
    AIContextParser = IntegratedAIContextParser
    
    # Дополнительные классы для прямого импорта
    from .integrated_ai_parser import (
        DialogueTracker,
        DialogueAnalyzer,
        DialogueContext,
        DialogueParticipant,
        DialogueMessage,
        DialogueAnalysisResult,
        AIAnalysisResult,
        UserContext
    )
    
    __all__ = [
        'AIContextParser',
        'IntegratedAIContextParser',
        'DialogueTracker',
        'DialogueAnalyzer',
        'DialogueContext',
        'DialogueParticipant',
        'DialogueMessage',
        'DialogueAnalysisResult',
        'AIAnalysisResult',
        'UserContext'
    ]
    
    import logging
    logging.getLogger(__name__).info("✅ Интегрированный AI парсер с анализом диалогов загружен успешно")
    
except ImportError as e:
    # Fallback на оригинальный парсер
    import logging
    logging.getLogger(__name__).warning(f"⚠️ Не удалось загрузить интегрированный парсер: {e}")
    logging.getLogger(__name__).info("🔄 Используем оригинальный AI парсер (без анализа диалогов)")
    
    from .ai_context_parser import AIContextParser, UserContext, AIAnalysisResult
    
    # Создаем заглушки для недостающих классов
    class DialogueTracker:
        def __init__(self, config):
            pass
    
    class DialogueAnalyzer:
        def __init__(self, config):
            pass
    
    class DialogueContext:
        pass
    
    class DialogueParticipant:
        pass
    
    class DialogueMessage:
        pass
    
    class DialogueAnalysisResult:
        pass
    
    # Alias для обратной совместимости
    IntegratedAIContextParser = AIContextParser
    
    __all__ = [
        'AIContextParser',
        'IntegratedAIContextParser',
        'UserContext',
        'AIAnalysisResult',
        'DialogueTracker',
        'DialogueAnalyzer',
        'DialogueContext',
        'DialogueParticipant',
        'DialogueMessage',
        'DialogueAnalysisResult'
    ]
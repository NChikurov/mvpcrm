"""
myparser/integrated_ai_parser.py - Интегрированный AI парсер
Объединяет анализ диалогов и индивидуальных сообщений
"""

from .dialogue_analyzer import *
from .ai_context_parser import AIAnalysisResult, UserContext

# Импортируем и экспортируем главный класс
from .dialogue_analyzer import IntegratedAIContextParser

# Для обратной совместимости
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
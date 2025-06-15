"""
Полные модели базы данных для AI CRM Bot - ПОЛНОСТЬЮ ИСПРАВЛЕННАЯ ВЕРСИЯ
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class User:
    """Модель пользователя - соответствует таблице users в БД"""
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    # НЕ включаем is_admin - его нет в таблице users
    is_active: bool = True
    registration_date: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    interaction_count: int = 0

@dataclass
class ParsedChannel:
    """Модель отслеживаемого канала"""
    id: Optional[int] = None
    channel_username: str = ""
    channel_title: Optional[str] = None
    channel_id: Optional[int] = None
    enabled: bool = True
    created_at: Optional[datetime] = None
    last_message_id: Optional[int] = None
    total_messages: int = 0
    leads_found: int = 0

@dataclass
class Lead:
    """Модель лида - ТОЧНО соответствует таблице leads в БД"""
    # Основные поля
    id: Optional[int] = None
    telegram_id: int = 0
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None  # Добавляем last_name
    source_channel: Optional[str] = None
    interest_score: int = 0
    message_text: str = ""
    message_date: Optional[datetime] = None
    is_contacted: bool = False  # Это поле ЕСТЬ в БД
    created_at: Optional[datetime] = None
    status: str = "new"
    
    # AI поля
    lead_quality: str = "unknown"
    interests: Optional[str] = None
    buying_signals: Optional[str] = None
    urgency_level: str = "none"
    estimated_budget: Optional[str] = None
    timeline: Optional[str] = None
    pain_points: Optional[str] = None
    decision_stage: str = "awareness"
    contact_attempts: int = 0
    last_contact_date: Optional[datetime] = None
    notes: Optional[str] = None

@dataclass 
class AIAnalysisLog:
    """Лог AI анализов"""
    id: Optional[int] = None
    user_id: int = 0
    analysis_date: Optional[datetime] = None
    confidence_score: int = 0
    lead_quality: str = "unknown"
    is_lead: bool = False
    context_messages_count: int = 0
    analysis_duration_ms: int = 0
    ai_model_used: Optional[str] = None
    raw_ai_response: Optional[str] = None

@dataclass
class UserInteraction:
    """История взаимодействий с пользователем"""
    id: Optional[int] = None
    user_id: int = 0
    interaction_type: str = "message"
    interaction_date: Optional[datetime] = None
    description: str = ""
    outcome: Optional[str] = None
    next_action: Optional[str] = None
    admin_id: Optional[int] = None

@dataclass
class Message:
    """Модель сообщения"""
    id: Optional[int] = None
    telegram_message_id: int = 0
    user_id: int = 0
    chat_id: int = 0
    text: str = ""
    created_at: Optional[datetime] = None
    processed: bool = False
    interest_score: Optional[int] = None

@dataclass
class Setting:
    """Модель настроек системы"""
    id: Optional[int] = None
    key: str = ""
    value: str = ""
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

@dataclass
class BotStats:
    """Статистика бота"""
    id: Optional[int] = None
    total_users: int = 0
    total_messages: int = 0
    total_leads: int = 0
    created_at: Optional[datetime] = None

@dataclass
class Broadcast:
    """Модель рассылки"""
    id: Optional[int] = None
    admin_id: int = 0
    message_text: str = ""
    target_audience: str = "all"
    status: str = "draft"
    created_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    total_recipients: int = 0
    successful_sends: int = 0
    failed_sends: int = 0
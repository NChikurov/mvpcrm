"""
Полные модели базы данных для AI CRM Bot
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class User:
    """Модель пользователя"""
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_admin: bool = False
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
    """Модель лида с расширенными AI данными"""
    # Основные поля
    id: Optional[int] = None
    telegram_id: int = 0
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    source_channel: Optional[str] = None
    interest_score: int = 0
    message_text: str = ""
    message_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    status: str = "new"  # new, contacted, qualified, converted, rejected
    
    # AI анализ - новые поля
    lead_quality: str = "unknown"  # hot, warm, cold, not_lead
    interests: Optional[str] = None  # JSON строка с интересами
    buying_signals: Optional[str] = None  # JSON строка с сигналами покупки
    urgency_level: str = "none"  # immediate, short_term, long_term, none
    estimated_budget: Optional[str] = None
    timeline: Optional[str] = None
    pain_points: Optional[str] = None  # JSON строка с болевыми точками
    decision_stage: str = "awareness"  # awareness, consideration, decision, post_purchase
    
    # Дополнительные поля
    contact_attempts: int = 0
    last_contact_date: Optional[datetime] = None
    notes: Optional[str] = None

@dataclass 
class AIAnalysisLog:
    """Лог AI анализов для отслеживания"""
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
    interaction_type: str = "message"  # message, call, meeting, email
    interaction_date: Optional[datetime] = None
    description: str = ""
    outcome: Optional[str] = None
    next_action: Optional[str] = None
    admin_id: Optional[int] = None

@dataclass
class Message:
    """Модель сообщения (для совместимости)"""
    id: Optional[int] = None
    telegram_message_id: int = 0
    user_id: int = 0
    chat_id: int = 0
    text: str = ""
    created_at: Optional[datetime] = None
    processed: bool = False
    interest_score: Optional[int] = None

@dataclass
class AdminAction:
    """Модель действий администратора"""
    id: Optional[int] = None
    admin_id: int = 0
    action_type: str = ""  # view_leads, contact_lead, update_status, etc.
    target_id: Optional[int] = None  # ID лида или другого объекта
    description: Optional[str] = None
    created_at: Optional[datetime] = None

@dataclass
class SystemStats:
    """Системная статистика"""
    id: Optional[int] = None
    stat_date: Optional[datetime] = None
    total_users: int = 0
    total_leads: int = 0
    total_messages: int = 0
    ai_analyses_count: int = 0
    hot_leads_count: int = 0
    warm_leads_count: int = 0
    cold_leads_count: int = 0
    conversion_rate: float = 0.0

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
    """Статистика бота (для совместимости)"""
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
    target_audience: str = "all"  # all, leads, users
    status: str = "draft"  # draft, sending, completed, failed
    created_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    total_recipients: int = 0
    successful_sends: int = 0
    failed_sends: int = 0

@dataclass
class Subscription:
    """Модель подписки"""
    id: Optional[int] = None
    user_id: int = 0
    subscription_type: str = "basic"  # basic, premium, enterprise
    status: str = "active"  # active, inactive, expired
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    auto_renewal: bool = True

@dataclass
class Analytics:
    """Модель аналитики"""
    id: Optional[int] = None
    metric_name: str = ""
    metric_value: float = 0.0
    metric_date: Optional[datetime] = None
    category: str = "general"  # general, leads, users, performance

@dataclass
class Config:
    """Модель конфигурации"""
    id: Optional[int] = None
    section: str = ""
    key: str = ""
    value: str = ""
    description: Optional[str] = None
    is_sensitive: bool = False

@dataclass
class Session:
    """Модель сессии пользователя"""
    id: Optional[int] = None
    user_id: int = 0
    session_token: str = ""
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool = True

@dataclass
class Notification:
    """Модель уведомления"""
    id: Optional[int] = None
    user_id: int = 0
    title: str = ""
    message: str = ""
    notification_type: str = "info"  # info, warning, error, success
    is_read: bool = False
    created_at: Optional[datetime] = None

@dataclass
class Template:
    """Модель шаблона сообщения"""
    id: Optional[int] = None
    name: str = ""
    content: str = ""
    template_type: str = "message"  # message, email, notification
    variables: Optional[str] = None  # JSON строка с переменными
    is_active: bool = True
    created_at: Optional[datetime] = None

@dataclass
class Webhook:
    """Модель вебхука"""
    id: Optional[int] = None
    url: str = ""
    event_type: str = ""  # lead_created, user_registered, etc.
    is_active: bool = True
    secret_key: Optional[str] = None
    last_triggered: Optional[datetime] = None
    success_count: int = 0
    failure_count: int = 0

@dataclass
class CREATE_INDEXES_SQL:
    """Модель CREATE_INDEXES_SQL"""
    id: Optional[int] = None
    created_at: Optional[datetime] = None

@dataclass
class CREATE_TABLES_SQL:
    """Модель CREATE_TABLES_SQL"""
    id: Optional[int] = None
    created_at: Optional[datetime] = None


"""
Модели базы данных для AI-CRM бота
"""

from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class User:
    """Модель пользователя"""
    id: Optional[int] = None
    telegram_id: int = 0
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    interest_score: int = 0
    message_count: int = 0
    created_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    is_blocked: bool = False
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.last_activity is None:
            self.last_activity = datetime.now()

@dataclass
class Message:
    """Модель сообщения пользователя"""
    id: Optional[int] = None
    user_id: int = 0
    telegram_message_id: int = 0
    text: str = ""
    ai_analysis: Optional[str] = None
    interest_score: int = 0
    response_sent: bool = False
    created_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

@dataclass 
class Lead:
    """Модель потенциального клиента из парсинга"""
    id: Optional[int] = None
    telegram_id: Optional[int] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    source_channel: str = ""
    interest_score: int = 0
    message_text: str = ""
    message_date: Optional[datetime] = None
    is_contacted: bool = False
    created_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

@dataclass
class ParsedChannel:
    """Модель отслеживаемого канала"""
    id: Optional[int] = None
    channel_username: str = ""
    channel_title: Optional[str] = None
    enabled: bool = True
    last_message_id: Optional[int] = None
    last_parsed: Optional[datetime] = None
    total_messages_parsed: int = 0
    leads_found: int = 0
    created_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

@dataclass
class Setting:
    """Модель настроек бота"""
    key: str = ""
    value: str = ""
    description: Optional[str] = None
    updated_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.updated_at is None:
            self.updated_at = datetime.now()

@dataclass
class Broadcast:
    """Модель рассылки"""
    id: Optional[int] = None
    admin_id: int = 0
    message_text: str = ""
    total_users: int = 0
    sent_count: int = 0
    failed_count: int = 0
    status: str = "pending"  # pending, sending, completed, failed
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

# SQL схемы для создания таблиц
CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE NOT NULL,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        interest_score INTEGER DEFAULT 0,
        message_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_blocked BOOLEAN DEFAULT FALSE
    )
    """,
    
    """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        telegram_message_id INTEGER,
        text TEXT NOT NULL,
        ai_analysis TEXT,
        interest_score INTEGER DEFAULT 0,
        response_sent BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """,
    
    """
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        username TEXT,
        first_name TEXT,
        source_channel TEXT NOT NULL,
        interest_score INTEGER DEFAULT 0,
        message_text TEXT NOT NULL,
        message_date TIMESTAMP,
        is_contacted BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    
    """
    CREATE TABLE IF NOT EXISTS parsed_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_username TEXT UNIQUE NOT NULL,
        channel_title TEXT,
        enabled BOOLEAN DEFAULT TRUE,
        last_message_id INTEGER,
        last_parsed TIMESTAMP,
        total_messages_parsed INTEGER DEFAULT 0,
        leads_found INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        description TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    
    """
    CREATE TABLE IF NOT EXISTS broadcasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        message_text TEXT NOT NULL,
        total_users INTEGER DEFAULT 0,
        sent_count INTEGER DEFAULT 0,
        failed_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP
    )
    """
]

# Индексы для оптимизации
CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)",
    "CREATE INDEX IF NOT EXISTS idx_users_interest_score ON users(interest_score)",
    "CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_leads_interest_score ON leads(interest_score)",
    "CREATE INDEX IF NOT EXISTS idx_leads_source_channel ON leads(source_channel)",
    "CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at)"
]

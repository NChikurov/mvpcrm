"""
CRUD операции для работы с базой данных
"""

import aiosqlite
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from .models import (
    User, Message, Lead, ParsedChannel, Setting, Broadcast,
    CREATE_TABLES_SQL, CREATE_INDEXES_SQL
)

logger = logging.getLogger(__name__)

# Путь к базе данных
DB_PATH = "data/bot.db"

async def init_database():
    """Инициализация базы данных"""
    # Создать директорию если не существует
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Создать таблицы
        for sql in CREATE_TABLES_SQL:
            await db.execute(sql)
        
        # Создать индексы
        for sql in CREATE_INDEXES_SQL:
            await db.execute(sql)
        
        await db.commit()
    
    logger.info("База данных инициализирована")

async def get_connection():
    """Получить соединение с БД"""
    return await aiosqlite.connect(DB_PATH)

# === ПОЛЬЗОВАТЕЛИ ===

async def create_user(user: User) -> User:
    """Создать пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT OR REPLACE INTO users 
            (telegram_id, username, first_name, last_name, interest_score, 
             message_count, created_at, last_activity, is_blocked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user.telegram_id, user.username, user.first_name, user.last_name,
            user.interest_score, user.message_count, user.created_at,
            user.last_activity, user.is_blocked
        ))
        user.id = cursor.lastrowid
        await db.commit()
    return user

async def get_user_by_telegram_id(telegram_id: int) -> Optional[User]:
    """Получить пользователя по Telegram ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        if row:
            return User(**dict(row))
    return None

async def update_user_interest_score(telegram_id: int, score: int):
    """Обновить скор заинтересованности пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE users SET 
                interest_score = ?, 
                last_activity = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
        """, (score, telegram_id))
        await db.commit()

async def increment_user_message_count(telegram_id: int):
    """Увеличить счетчик сообщений пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE users SET 
                message_count = message_count + 1,
                last_activity = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
        """, (telegram_id,))
        await db.commit()

async def get_all_users(limit: int = 100, offset: int = 0) -> List[User]:
    """Получить всех пользователей"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM users 
            ORDER BY last_activity DESC 
            LIMIT ? OFFSET ?
        """, (limit, offset))
        rows = await cursor.fetchall()
        return [User(**dict(row)) for row in rows]

async def get_users_by_interest_score(min_score: int = 70) -> List[User]:
    """Получить пользователей с высоким скором заинтересованности"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM users 
            WHERE interest_score >= ? AND is_blocked = FALSE
            ORDER BY interest_score DESC
        """, (min_score,))
        rows = await cursor.fetchall()
        return [User(**dict(row)) for row in rows]

# === СООБЩЕНИЯ ===

async def create_message(message: Message) -> Message:
    """Создать сообщение"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO messages 
            (user_id, telegram_message_id, text, ai_analysis, 
             interest_score, response_sent, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            message.user_id, message.telegram_message_id, message.text,
            message.ai_analysis, message.interest_score, message.response_sent,
            message.created_at
        ))
        message.id = cursor.lastrowid
        await db.commit()
    return message

async def get_user_messages(user_id: int, limit: int = 10) -> List[Message]:
    """Получить сообщения пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM messages 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (user_id, limit))
        rows = await cursor.fetchall()
        return [Message(**dict(row)) for row in rows]

# === ЛИДЫ ===

async def create_lead(lead: Lead) -> Lead:
    """Создать лид"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO leads 
            (telegram_id, username, first_name, source_channel, 
             interest_score, message_text, message_date, 
             is_contacted, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            lead.telegram_id, lead.username, lead.first_name,
            lead.source_channel, lead.interest_score, lead.message_text,
            lead.message_date, lead.is_contacted, lead.created_at
        ))
        lead.id = cursor.lastrowid
        await db.commit()
    return lead

async def get_leads_by_score(min_score: int = 60, limit: int = 50) -> List[Lead]:
    """Получить лиды по минимальному скору"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM leads 
            WHERE interest_score >= ? 
            ORDER BY interest_score DESC, created_at DESC
            LIMIT ?
        """, (min_score, limit))
        rows = await cursor.fetchall()
        return [Lead(**dict(row)) for row in rows]

async def get_recent_leads(hours: int = 24) -> List[Lead]:
    """Получить недавние лиды"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM leads 
            WHERE created_at >= datetime('now', '-{} hours')
            ORDER BY interest_score DESC, created_at DESC
        """.format(hours))
        rows = await cursor.fetchall()
        return [Lead(**dict(row)) for row in rows]

# === КАНАЛЫ ===

async def create_or_update_channel(channel: ParsedChannel) -> ParsedChannel:
    """Создать или обновить канал"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT OR REPLACE INTO parsed_channels 
            (channel_username, channel_title, enabled, last_message_id,
             last_parsed, total_messages_parsed, leads_found, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            channel.channel_username, channel.channel_title, channel.enabled,
            channel.last_message_id, channel.last_parsed,
            channel.total_messages_parsed, channel.leads_found, channel.created_at
        ))
        if not channel.id:
            channel.id = cursor.lastrowid
        await db.commit()
    return channel

async def get_active_channels() -> List[ParsedChannel]:
    """Получить активные каналы для парсинга"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM parsed_channels 
            WHERE enabled = TRUE
            ORDER BY channel_username
        """)
        rows = await cursor.fetchall()
        return [ParsedChannel(**dict(row)) for row in rows]

async def update_channel_stats(channel_username: str, message_id: int, leads_count: int = 0):
    """Обновить статистику канала"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE parsed_channels SET
                last_message_id = ?,
                last_parsed = CURRENT_TIMESTAMP,
                total_messages_parsed = total_messages_parsed + 1,
                leads_found = leads_found + ?
            WHERE channel_username = ?
        """, (message_id, leads_count, channel_username))
        await db.commit()

# === НАСТРОЙКИ ===

async def set_setting(key: str, value: str, description: str = None):
    """Установить настройку"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO settings (key, value, description, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (key, value, description))
        await db.commit()

async def get_setting(key: str, default: str = None) -> Optional[str]:
    """Получить настройку"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else default

# === РАССЫЛКИ ===

async def create_broadcast(broadcast: Broadcast) -> Broadcast:
    """Создать рассылку"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO broadcasts 
            (admin_id, message_text, total_users, sent_count, 
             failed_count, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            broadcast.admin_id, broadcast.message_text, broadcast.total_users,
            broadcast.sent_count, broadcast.failed_count, broadcast.status,
            broadcast.created_at
        ))
        broadcast.id = cursor.lastrowid
        await db.commit()
    return broadcast

async def update_broadcast_stats(broadcast_id: int, sent: int, failed: int, status: str = None):
    """Обновить статистику рассылки"""
    async with aiosqlite.connect(DB_PATH) as db:
        if status:
            await db.execute("""
                UPDATE broadcasts SET
                    sent_count = sent_count + ?,
                    failed_count = failed_count + ?,
                    status = ?,
                    completed_at = CASE WHEN ? = 'completed' THEN CURRENT_TIMESTAMP ELSE completed_at END
                WHERE id = ?
            """, (sent, failed, status, status, broadcast_id))
        else:
            await db.execute("""
                UPDATE broadcasts SET
                    sent_count = sent_count + ?,
                    failed_count = failed_count + ?
                WHERE id = ?
            """, (sent, failed, broadcast_id))
        await db.commit()

# === СТАТИСТИКА ===

async def get_stats() -> Dict[str, Any]:
    """Получить общую статистику"""
    async with aiosqlite.connect(DB_PATH) as db:
        stats = {}
        
        # Пользователи
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        stats['total_users'] = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT COUNT(*) FROM users WHERE interest_score >= 70")
        stats['interested_users'] = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT COUNT(*) FROM users WHERE last_activity >= datetime('now', '-24 hours')")
        stats['active_users_24h'] = (await cursor.fetchone())[0]
        
        # Сообщения
        cursor = await db.execute("SELECT COUNT(*) FROM messages")
        stats['total_messages'] = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE created_at >= datetime('now', '-24 hours')")
        stats['messages_24h'] = (await cursor.fetchone())[0]
        
        # Лиды
        cursor = await db.execute("SELECT COUNT(*) FROM leads")
        stats['total_leads'] = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT COUNT(*) FROM leads WHERE created_at >= datetime('now', '-24 hours')")
        stats['leads_24h'] = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT COUNT(*) FROM leads WHERE interest_score >= 80")
        stats['hot_leads'] = (await cursor.fetchone())[0]
        
        # Каналы
        cursor = await db.execute("SELECT COUNT(*) FROM parsed_channels WHERE enabled = TRUE")
        stats['active_channels'] = (await cursor.fetchone())[0]
        
        return stats

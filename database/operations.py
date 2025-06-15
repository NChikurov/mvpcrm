"""
Операции базы данных для AI CRM Bot - ПОЛНОСТЬЮ ИСПРАВЛЕННАЯ ВЕРСИЯ
"""

import aiosqlite
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

from .models import User, Lead, ParsedChannel, Message, Setting, BotStats, Broadcast

logger = logging.getLogger(__name__)

async def init_database(db_path: str = "data/bot.db"):
    """Инициализация базы данных"""
    try:
        # Создаем директорию если не существует
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        async with aiosqlite.connect(db_path) as db:
            await db.commit()
            logger.info("База данных инициализирована")
            
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")
        raise

async def create_user(user: User, db_path: str = "data/bot.db"):
    """Создание или обновление пользователя - БЕЗ is_admin"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO users 
                (telegram_id, username, first_name, last_name, is_active, 
                 registration_date, last_activity, interaction_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user.telegram_id,
                user.username,
                user.first_name,
                user.last_name,
                user.is_active,
                user.registration_date or datetime.now(),
                user.last_activity or datetime.now(),
                user.interaction_count
            ))
            await db.commit()
            
    except Exception as e:
        logger.error(f"Ошибка создания пользователя: {e}")
        raise

async def create_lead(lead: Lead, db_path: str = "data/bot.db"):
    """Создание лида с ВСЕМИ полями из БД"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT INTO leads 
                (telegram_id, username, first_name, last_name, source_channel, 
                 interest_score, message_text, message_date, is_contacted, status,
                 lead_quality, interests, buying_signals, urgency_level,
                 estimated_budget, timeline, pain_points, decision_stage,
                 contact_attempts, last_contact_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                lead.telegram_id,
                lead.username,
                lead.first_name,
                lead.last_name,
                lead.source_channel,
                lead.interest_score,
                lead.message_text,
                lead.message_date or datetime.now(),
                lead.is_contacted,
                lead.status,
                lead.lead_quality,
                lead.interests,
                lead.buying_signals,
                lead.urgency_level,
                lead.estimated_budget,
                lead.timeline,
                lead.pain_points,
                lead.decision_stage,
                lead.contact_attempts,
                lead.last_contact_date,
                lead.notes
            ))
            await db.commit()
            logger.info(f"Лид создан: {lead.first_name} (@{lead.username})")
            
    except Exception as e:
        logger.error(f"Ошибка создания лида: {e}")
        raise

async def get_leads(limit: int = 50, offset: int = 0, db_path: str = "data/bot.db") -> List[Lead]:
    """Получение списка лидов с правильной обработкой полей"""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("""
                SELECT id, telegram_id, username, first_name, last_name, source_channel, 
                       interest_score, message_text, message_date, is_contacted, created_at, status,
                       lead_quality, interests, buying_signals, urgency_level,
                       estimated_budget, timeline, pain_points, decision_stage,
                       contact_attempts, last_contact_date, notes
                FROM leads 
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
            """, (limit, offset))
            
            rows = await cursor.fetchall()
            
            leads = []
            for row in rows:
                # Явно создаем объект Lead с правильными полями
                lead = Lead(
                    id=row[0],
                    telegram_id=row[1],
                    username=row[2],
                    first_name=row[3],
                    last_name=row[4],
                    source_channel=row[5],
                    interest_score=row[6],
                    message_text=row[7],
                    message_date=datetime.fromisoformat(row[8]) if row[8] else None,
                    is_contacted=bool(row[9]),
                    created_at=datetime.fromisoformat(row[10]) if row[10] else None,
                    status=row[11],
                    lead_quality=row[12],
                    interests=row[13],
                    buying_signals=row[14],
                    urgency_level=row[15],
                    estimated_budget=row[16],
                    timeline=row[17],
                    pain_points=row[18],
                    decision_stage=row[19],
                    contact_attempts=row[20],
                    last_contact_date=datetime.fromisoformat(row[21]) if row[21] else None,
                    notes=row[22]
                )
                leads.append(lead)
            
            return leads
            
    except Exception as e:
        logger.error(f"Ошибка получения лидов: {e}")
        return []

async def get_users(limit: int = 50, offset: int = 0, db_path: str = "data/bot.db") -> List[User]:
    """Получение списка пользователей с правильной обработкой полей"""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("""
                SELECT telegram_id, username, first_name, last_name, is_active, 
                       registration_date, last_activity, interaction_count
                FROM users 
                ORDER BY last_activity DESC 
                LIMIT ? OFFSET ?
            """, (limit, offset))
            
            rows = await cursor.fetchall()
            
            users = []
            for row in rows:
                # Явно создаем объект User БЕЗ поля id
                user = User(
                    telegram_id=row[0],
                    username=row[1],
                    first_name=row[2],
                    last_name=row[3],
                    is_active=bool(row[4]),
                    registration_date=datetime.fromisoformat(row[5]) if row[5] else None,
                    last_activity=datetime.fromisoformat(row[6]) if row[6] else None,
                    interaction_count=row[7] or 0
                )
                users.append(user)
            
            return users
            
    except Exception as e:
        logger.error(f"Ошибка получения пользователей: {e}")
        return []

async def get_user_by_telegram_id(telegram_id: int, db_path: str = "data/bot.db") -> Optional[User]:
    """Получение пользователя по Telegram ID"""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("""
                SELECT telegram_id, username, first_name, last_name, is_active, 
                       registration_date, last_activity, interaction_count
                FROM users WHERE telegram_id = ?
            """, (telegram_id,))
            
            row = await cursor.fetchone()
            if not row:
                return None
            
            return User(
                telegram_id=row[0],
                username=row[1],
                first_name=row[2],
                last_name=row[3],
                is_active=bool(row[4]),
                registration_date=datetime.fromisoformat(row[5]) if row[5] else None,
                last_activity=datetime.fromisoformat(row[6]) if row[6] else None,
                interaction_count=row[7] or 0
            )
            
    except Exception as e:
        logger.error(f"Ошибка получения пользователя: {e}")
        return None

async def update_user_activity(telegram_id: int, db_path: str = "data/bot.db"):
    """Обновление активности пользователя"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                UPDATE users 
                SET last_activity = ?, interaction_count = interaction_count + 1
                WHERE telegram_id = ?
            """, (datetime.now(), telegram_id))
            
            await db.commit()
            
    except Exception as e:
        logger.error(f"Ошибка обновления активности пользователя: {e}")

async def save_message(message: Message, db_path: str = "data/bot.db"):
    """Сохранение сообщения"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT INTO messages 
                (telegram_message_id, user_id, chat_id, text, processed, interest_score)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                message.telegram_message_id,
                message.user_id,
                message.chat_id,
                message.text,
                message.processed,
                message.interest_score
            ))
            await db.commit()
            
    except Exception as e:
        logger.error(f"Ошибка сохранения сообщения: {e}")

async def get_messages(user_id: int = None, limit: int = 50, offset: int = 0, db_path: str = "data/bot.db") -> List[Message]:
    """Получение сообщений"""
    try:
        async with aiosqlite.connect(db_path) as db:
            if user_id:
                cursor = await db.execute("""
                    SELECT id, telegram_message_id, user_id, chat_id, text, created_at, processed, interest_score
                    FROM messages 
                    WHERE user_id = ?
                    ORDER BY created_at DESC 
                    LIMIT ? OFFSET ?
                """, (user_id, limit, offset))
            else:
                cursor = await db.execute("""
                    SELECT id, telegram_message_id, user_id, chat_id, text, created_at, processed, interest_score
                    FROM messages 
                    ORDER BY created_at DESC 
                    LIMIT ? OFFSET ?
                """, (limit, offset))
            
            rows = await cursor.fetchall()
            
            messages = []
            for row in rows:
                message = Message(
                    id=row[0],
                    telegram_message_id=row[1],
                    user_id=row[2],
                    chat_id=row[3],
                    text=row[4],
                    created_at=datetime.fromisoformat(row[5]) if row[5] else None,
                    processed=bool(row[6]),
                    interest_score=row[7]
                )
                messages.append(message)
            
            return messages
            
    except Exception as e:
        logger.error(f"Ошибка получения сообщений: {e}")
        return []

async def get_bot_stats(db_path: str = "data/bot.db") -> dict:
    """Получение статистики бота"""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM users) as total_users,
                    (SELECT COUNT(*) FROM messages) as total_messages,
                    (SELECT COUNT(*) FROM leads) as total_leads,
                    (SELECT COUNT(*) FROM leads WHERE created_at >= datetime('now', '-1 day')) as leads_today,
                    (SELECT COUNT(*) FROM leads WHERE created_at >= datetime('now', '-7 days')) as leads_week,
                    (SELECT COUNT(*) FROM users WHERE last_activity >= datetime('now', '-1 day')) as active_users_today,
                    (SELECT AVG(interest_score) FROM leads) as avg_lead_score
            """)
            
            row = await cursor.fetchone()
            
            return {
                'total_users': row[0] or 0,
                'total_messages': row[1] or 0,
                'total_leads': row[2] or 0,
                'leads_today': row[3] or 0,
                'leads_week': row[4] or 0,
                'active_users_today': row[5] or 0,
                'avg_lead_score': row[6] or 0
            }
            
    except Exception as e:
        logger.error(f"Ошибка получения статистики бота: {e}")
        return {}

async def get_active_channels(db_path: str = "data/bot.db") -> List[ParsedChannel]:
    """Получение активных каналов"""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("""
                SELECT * FROM parsed_channels WHERE enabled = TRUE
            """)
            
            rows = await cursor.fetchall()
            if not rows:
                return []
            
            columns = [description[0] for description in cursor.description]
            
            channels = []
            for row in rows:
                channel_data = dict(zip(columns, row))
                channel = ParsedChannel(**channel_data)
                channels.append(channel)
            
            return channels
            
    except Exception as e:
        logger.error(f"Ошибка получения каналов: {e}")
        return []

async def update_channel_stats(channel_identifier: str, message_id: int, 
                             leads_count: int = 0, db_path: str = "data/bot.db"):
    """Обновление статистики канала"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                UPDATE parsed_channels 
                SET last_message_id = ?, 
                    total_messages = total_messages + 1,
                    leads_found = leads_found + ?
                WHERE channel_username = ? OR channel_id = ?
            """, (message_id, leads_count, channel_identifier, channel_identifier))
            
            await db.commit()
            
    except Exception as e:
        logger.error(f"Ошибка обновления статистики канала: {e}")

async def create_or_update_channel(channel: ParsedChannel, db_path: str = "data/bot.db"):
    """Создание или обновление канала"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO parsed_channels
                (channel_username, channel_title, channel_id, enabled, 
                 last_message_id, total_messages, leads_found)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                channel.channel_username,
                channel.channel_title,
                channel.channel_id,
                channel.enabled,
                channel.last_message_id,
                channel.total_messages,
                channel.leads_found
            ))
            await db.commit()
    except Exception as e:
        logger.error(f"Ошибка создания/обновления канала: {e}")

async def get_lead_by_telegram_id(telegram_id: int, db_path: str = "data/bot.db") -> Optional[Lead]:
    """Получение лида по Telegram ID"""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("""
                SELECT id, telegram_id, username, first_name, last_name, source_channel, 
                       interest_score, message_text, message_date, is_contacted, created_at, status,
                       lead_quality, interests, buying_signals, urgency_level,
                       estimated_budget, timeline, pain_points, decision_stage,
                       contact_attempts, last_contact_date, notes
                FROM leads WHERE telegram_id = ? ORDER BY created_at DESC LIMIT 1
            """, (telegram_id,))
            
            row = await cursor.fetchone()
            if not row:
                return None
            
            return Lead(
                id=row[0],
                telegram_id=row[1],
                username=row[2],
                first_name=row[3],
                last_name=row[4],
                source_channel=row[5],
                interest_score=row[6],
                message_text=row[7],
                message_date=datetime.fromisoformat(row[8]) if row[8] else None,
                is_contacted=bool(row[9]),
                created_at=datetime.fromisoformat(row[10]) if row[10] else None,
                status=row[11],
                lead_quality=row[12],
                interests=row[13],
                buying_signals=row[14],
                urgency_level=row[15],
                estimated_budget=row[16],
                timeline=row[17],
                pain_points=row[18],
                decision_stage=row[19],
                contact_attempts=row[20],
                last_contact_date=datetime.fromisoformat(row[21]) if row[21] else None,
                notes=row[22]
            )
    except Exception as e:
        logger.error(f"Ошибка получения лида: {e}")
        return None

async def update_lead_status(lead_id: int, status: str, notes: str = None, db_path: str = "data/bot.db"):
    """Обновление статуса лида"""
    try:
        async with aiosqlite.connect(db_path) as db:
            if notes:
                await db.execute("""
                    UPDATE leads SET status = ?, notes = ? WHERE id = ?
                """, (status, notes, lead_id))
            else:
                await db.execute("""
                    UPDATE leads SET status = ? WHERE id = ?
                """, (status, lead_id))
            await db.commit()
    except Exception as e:
        logger.error(f"Ошибка обновления статуса лида: {e}")

async def get_leads_stats(db_path: str = "data/bot.db") -> dict:
    """Статистика лидов"""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as total_leads,
                    COUNT(CASE WHEN status = 'new' THEN 1 END) as new_leads,
                    COUNT(CASE WHEN status = 'contacted' THEN 1 END) as contacted_leads,
                    COUNT(CASE WHEN status = 'converted' THEN 1 END) as converted_leads,
                    COUNT(CASE WHEN lead_quality = 'hot' THEN 1 END) as hot_leads,
                    COUNT(CASE WHEN lead_quality = 'warm' THEN 1 END) as warm_leads,
                    COUNT(CASE WHEN lead_quality = 'cold' THEN 1 END) as cold_leads,
                    AVG(interest_score) as avg_score
                FROM leads
            """)
            
            row = await cursor.fetchone()
            
            return {
                'total_leads': row[0] or 0,
                'new_leads': row[1] or 0,
                'contacted_leads': row[2] or 0,
                'converted_leads': row[3] or 0,
                'hot_leads': row[4] or 0,
                'warm_leads': row[5] or 0,
                'cold_leads': row[6] or 0,
                'avg_score': row[7] or 0
            }
    except Exception as e:
        logger.error(f"Ошибка получения статистики лидов: {e}")
        return {}

async def search_leads(query: str, db_path: str = "data/bot.db") -> List[Lead]:
    """Поиск лидов"""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("""
                SELECT id, telegram_id, username, first_name, last_name, source_channel, 
                       interest_score, message_text, message_date, is_contacted, created_at, status,
                       lead_quality, interests, buying_signals, urgency_level,
                       estimated_budget, timeline, pain_points, decision_stage,
                       contact_attempts, last_contact_date, notes
                FROM leads 
                WHERE first_name LIKE ? OR username LIKE ? OR message_text LIKE ?
                ORDER BY created_at DESC
            """, (f"%{query}%", f"%{query}%", f"%{query}%"))
            
            rows = await cursor.fetchall()
            
            leads = []
            for row in rows:
                lead = Lead(
                    id=row[0],
                    telegram_id=row[1],
                    username=row[2],
                    first_name=row[3],
                    last_name=row[4],
                    source_channel=row[5],
                    interest_score=row[6],
                    message_text=row[7],
                    message_date=datetime.fromisoformat(row[8]) if row[8] else None,
                    is_contacted=bool(row[9]),
                    created_at=datetime.fromisoformat(row[10]) if row[10] else None,
                    status=row[11],
                    lead_quality=row[12],
                    interests=row[13],
                    buying_signals=row[14],
                    urgency_level=row[15],
                    estimated_budget=row[16],
                    timeline=row[17],
                    pain_points=row[18],
                    decision_stage=row[19],
                    contact_attempts=row[20],
                    last_contact_date=datetime.fromisoformat(row[21]) if row[21] else None,
                    notes=row[22]
                )
                leads.append(lead)
            
            return leads
    except Exception as e:
        logger.error(f"Ошибка поиска лидов: {e}")
        return []

async def get_setting(key: str, default_value: str = None, db_path: str = "data/bot.db") -> Optional[str]:
    """Получение настройки"""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = await cursor.fetchone()
            return row[0] if row else default_value
    except Exception as e:
        logger.error(f"Ошибка получения настройки {key}: {e}")
        return default_value

async def set_setting(key: str, value: str, description: str = None, db_path: str = "data/bot.db"):
    """Установка настройки"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO settings (key, value, description, updated_at)
                VALUES (?, ?, ?, ?)
            """, (key, value, description, datetime.now()))
            await db.commit()
    except Exception as e:
        logger.error(f"Ошибка установки настройки {key}: {e}")

async def get_lead_by_id(lead_id: int, db_path: str = "data/bot.db") -> Optional[Lead]:
    """Получение лида по ID"""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("""
                SELECT id, telegram_id, username, first_name, last_name, source_channel, 
                       interest_score, message_text, message_date, is_contacted, created_at, status,
                       lead_quality, interests, buying_signals, urgency_level,
                       estimated_budget, timeline, pain_points, decision_stage,
                       contact_attempts, last_contact_date, notes
                FROM leads WHERE id = ?
            """, (lead_id,))
            
            row = await cursor.fetchone()
            if not row:
                return None
            
            return Lead(
                id=row[0],
                telegram_id=row[1],
                username=row[2],
                first_name=row[3],
                last_name=row[4],
                source_channel=row[5],
                interest_score=row[6],
                message_text=row[7],
                message_date=datetime.fromisoformat(row[8]) if row[8] else None,
                is_contacted=bool(row[9]),
                created_at=datetime.fromisoformat(row[10]) if row[10] else None,
                status=row[11],
                lead_quality=row[12],
                interests=row[13],
                buying_signals=row[14],
                urgency_level=row[15],
                estimated_budget=row[16],
                timeline=row[17],
                pain_points=row[18],
                decision_stage=row[19],
                contact_attempts=row[20],
                last_contact_date=datetime.fromisoformat(row[21]) if row[21] else None,
                notes=row[22]
            )
    except Exception as e:
        logger.error(f"Ошибка получения лида по ID: {e}")
        return None

async def increment_contact_attempts(lead_id: int, db_path: str = "data/bot.db"):
    """Увеличение счетчика попыток связи"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                UPDATE leads 
                SET contact_attempts = contact_attempts + 1,
                    last_contact_date = ?
                WHERE id = ?
            """, (datetime.now(), lead_id))
            await db.commit()
    except Exception as e:
        logger.error(f"Ошибка увеличения счетчика контактов: {e}")

async def delete_lead(lead_id: int, db_path: str = "data/bot.db"):
    """Удаление лида"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
            await db.commit()
    except Exception as e:
        logger.error(f"Ошибка удаления лида: {e}")

async def create_message(message: Message, db_path: str = "data/bot.db"):
    """Создание сообщения (алиас для save_message)"""
    return await save_message(message, db_path)

async def update_bot_stats(db_path: str = "data/bot.db"):
    """Обновление статистики бота"""
    try:
        stats = await get_bot_stats(db_path)
        
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT INTO bot_stats (total_users, total_messages, total_leads)
                VALUES (?, ?, ?)
            """, (
                stats.get('total_users', 0),
                stats.get('total_messages', 0),
                stats.get('total_leads', 0)
            ))
            await db.commit()
    except Exception as e:
        logger.error(f"Ошибка обновления статистики бота: {e}")

async def export_leads_to_csv(db_path: str = "data/bot.db") -> str:
    """Экспорт лидов в CSV"""
    try:
        import csv
        import io
        
        leads = await get_leads(limit=10000, db_path=db_path)
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow([
            'ID', 'Telegram ID', 'Username', 'First Name', 'Source Channel',
            'Interest Score', 'Lead Quality', 'Urgency Level', 'Estimated Budget',
            'Timeline', 'Decision Stage', 'Created At', 'Status'
        ])
        
        # Данные
        for lead in leads:
            writer.writerow([
                lead.id, lead.telegram_id, lead.username, lead.first_name,
                lead.source_channel, lead.interest_score, lead.lead_quality,
                lead.urgency_level, lead.estimated_budget, lead.timeline,
                lead.decision_stage, lead.created_at, lead.status
            ])
        
        csv_content = output.getvalue()
        output.close()
        
        return csv_content
    except Exception as e:
        logger.error(f"Ошибка экспорта лидов: {e}")
        return ""
"""
database/dialogue_migration.py - Миграция базы данных для анализа диалогов
"""

import aiosqlite
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

async def migrate_database_for_dialogues(db_path: str = "data/bot.db"):
    """Миграция базы данных для поддержки анализа диалогов"""
    try:
        # Создаем директорию если не существует
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        async with aiosqlite.connect(db_path) as db:
            # Проверяем существующие таблицы
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing_tables = [row[0] for row in await cursor.fetchall()]
            
            logger.info(f"Существующие таблицы: {existing_tables}")
            
            # Создаем таблицу диалогов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS dialogues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dialogue_id TEXT UNIQUE NOT NULL,
                    channel_id INTEGER NOT NULL,
                    channel_title TEXT,
                    channel_username TEXT,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP,
                    last_activity TIMESTAMP NOT NULL,
                    participants_count INTEGER DEFAULT 0,
                    messages_count INTEGER DEFAULT 0,
                    is_business_related BOOLEAN DEFAULT FALSE,
                    topic TEXT,
                    dialogue_type TEXT DEFAULT 'discussion',
                    overall_sentiment TEXT DEFAULT 'neutral',
                    decision_stage TEXT DEFAULT 'awareness',
                    group_buying_probability REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Создаем таблицу участников диалогов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS dialogue_participants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dialogue_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    role TEXT DEFAULT 'participant',
                    message_count INTEGER DEFAULT 0,
                    first_message_time TIMESTAMP,
                    last_message_time TIMESTAMP,
                    engagement_level TEXT DEFAULT 'low',
                    buying_signals_count INTEGER DEFAULT 0,
                    influence_score INTEGER DEFAULT 0,
                    lead_probability REAL DEFAULT 0.0,
                    role_in_decision TEXT DEFAULT 'observer',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (dialogue_id) REFERENCES dialogues(dialogue_id),
                    UNIQUE(dialogue_id, user_id)
                )
            """)
            
            # Создаем таблицу сообщений диалогов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS dialogue_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dialogue_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    message_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    reply_to_message_id INTEGER,
                    reply_to_user_id INTEGER,
                    buying_signals TEXT,
                    sentiment TEXT DEFAULT 'neutral',
                    urgency_level TEXT DEFAULT 'none',
                    processed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (dialogue_id) REFERENCES dialogues(dialogue_id)
                )
            """)
            
            # Создаем таблицу анализов диалогов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS dialogue_analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dialogue_id TEXT NOT NULL,
                    analysis_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_valuable_dialogue BOOLEAN DEFAULT FALSE,
                    confidence_score INTEGER DEFAULT 0,
                    business_relevance_score INTEGER DEFAULT 0,
                    potential_leads_count INTEGER DEFAULT 0,
                    group_dynamics TEXT,
                    dialogue_summary TEXT,
                    key_insights TEXT,
                    recommended_actions TEXT,
                    next_best_action TEXT,
                    estimated_timeline TEXT,
                    group_budget_estimate TEXT,
                    ai_model_used TEXT,
                    analysis_duration_ms INTEGER DEFAULT 0,
                    raw_ai_response TEXT,
                    created_leads_count INTEGER DEFAULT 0,
                    FOREIGN KEY (dialogue_id) REFERENCES dialogues(dialogue_id)
                )
            """)
            
            # Создаем таблицу ролей и влияния участников
            await db.execute("""
                CREATE TABLE IF NOT EXISTS participant_influence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dialogue_id TEXT NOT NULL,
                    influencer_user_id INTEGER NOT NULL,
                    influenced_user_id INTEGER NOT NULL,
                    influence_strength REAL DEFAULT 0.0,
                    influence_type TEXT DEFAULT 'general',
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (dialogue_id) REFERENCES dialogues(dialogue_id),
                    UNIQUE(dialogue_id, influencer_user_id, influenced_user_id)
                )
            """)
            
            # Обновляем таблицу лидов для связи с диалогами
            try:
                await db.execute("""
                    ALTER TABLE leads ADD COLUMN dialogue_id TEXT
                """)
                logger.info("Добавлена колонка dialogue_id в таблицу leads")
            except Exception as e:
                if "duplicate column name" not in str(e).lower():
                    logger.warning(f"Не удалось добавить dialogue_id в leads: {e}")
            
            try:
                await db.execute("""
                    ALTER TABLE leads ADD COLUMN participant_role TEXT
                """)
                logger.info("Добавлена колонка participant_role в таблицу leads")
            except Exception as e:
                if "duplicate column name" not in str(e).lower():
                    logger.warning(f"Не удалось добавить participant_role в leads: {e}")
            
            try:
                await db.execute("""
                    ALTER TABLE leads ADD COLUMN group_dynamics TEXT
                """)
                logger.info("Добавлена колонка group_dynamics в таблицу leads")
            except Exception as e:
                if "duplicate column name" not in str(e).lower():
                    logger.warning(f"Не удалось добавить group_dynamics в leads: {e}")
            
            # Создаем индексы для оптимизации
            indices = [
                "CREATE INDEX IF NOT EXISTS idx_dialogues_channel_id ON dialogues(channel_id)",
                "CREATE INDEX IF NOT EXISTS idx_dialogues_start_time ON dialogues(start_time)",
                "CREATE INDEX IF NOT EXISTS idx_dialogues_status ON dialogues(status)",
                "CREATE INDEX IF NOT EXISTS idx_dialogue_participants_user_id ON dialogue_participants(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_dialogue_participants_dialogue_id ON dialogue_participants(dialogue_id)",
                "CREATE INDEX IF NOT EXISTS idx_dialogue_messages_dialogue_id ON dialogue_messages(dialogue_id)",
                "CREATE INDEX IF NOT EXISTS idx_dialogue_messages_user_id ON dialogue_messages(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_dialogue_messages_timestamp ON dialogue_messages(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_dialogue_analyses_dialogue_id ON dialogue_analyses(dialogue_id)",
                "CREATE INDEX IF NOT EXISTS idx_dialogue_analyses_date ON dialogue_analyses(analysis_date)",
                "CREATE INDEX IF NOT EXISTS idx_participant_influence_dialogue_id ON participant_influence(dialogue_id)",
                "CREATE INDEX IF NOT EXISTS idx_leads_dialogue_id ON leads(dialogue_id)"
            ]
            
            for index_sql in indices:
                try:
                    await db.execute(index_sql)
                except Exception as e:
                    logger.warning(f"Не удалось создать индекс: {e}")
            
            await db.commit()
            logger.info("✅ Миграция базы данных для анализа диалогов завершена успешно")
            
    except Exception as e:
        logger.error(f"❌ Ошибка миграции базы данных для диалогов: {e}")
        raise

async def save_dialogue(dialogue_data: dict, db_path: str = "data/bot.db"):
    """Сохранение диалога в базу данных"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO dialogues 
                (dialogue_id, channel_id, channel_title, channel_username, start_time, 
                 end_time, last_activity, participants_count, messages_count, 
                 is_business_related, topic, dialogue_type, overall_sentiment, 
                 decision_stage, group_buying_probability, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                dialogue_data['dialogue_id'],
                dialogue_data['channel_id'],
                dialogue_data.get('channel_title'),
                dialogue_data.get('channel_username'),
                dialogue_data['start_time'],
                dialogue_data.get('end_time'),
                dialogue_data['last_activity'],
                dialogue_data.get('participants_count', 0),
                dialogue_data.get('messages_count', 0),
                dialogue_data.get('is_business_related', False),
                dialogue_data.get('topic'),
                dialogue_data.get('dialogue_type', 'discussion'),
                dialogue_data.get('overall_sentiment', 'neutral'),
                dialogue_data.get('decision_stage', 'awareness'),
                dialogue_data.get('group_buying_probability', 0.0),
                dialogue_data.get('status', 'active')
            ))
            await db.commit()
            
    except Exception as e:
        logger.error(f"Ошибка сохранения диалога: {e}")

async def save_dialogue_participant(participant_data: dict, db_path: str = "data/bot.db"):
    """Сохранение участника диалога"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO dialogue_participants 
                (dialogue_id, user_id, username, first_name, last_name, role, 
                 message_count, first_message_time, last_message_time, 
                 engagement_level, buying_signals_count, influence_score,
                 lead_probability, role_in_decision)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                participant_data['dialogue_id'],
                participant_data['user_id'],
                participant_data.get('username'),
                participant_data.get('first_name'),
                participant_data.get('last_name'),
                participant_data.get('role', 'participant'),
                participant_data.get('message_count', 0),
                participant_data.get('first_message_time'),
                participant_data.get('last_message_time'),
                participant_data.get('engagement_level', 'low'),
                participant_data.get('buying_signals_count', 0),
                participant_data.get('influence_score', 0),
                participant_data.get('lead_probability', 0.0),
                participant_data.get('role_in_decision', 'observer')
            ))
            await db.commit()
            
    except Exception as e:
        logger.error(f"Ошибка сохранения участника диалога: {e}")

async def save_dialogue_message(message_data: dict, db_path: str = "data/bot.db"):
    """Сохранение сообщения диалога"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT INTO dialogue_messages 
                (dialogue_id, user_id, username, message_id, text, timestamp,
                 reply_to_message_id, reply_to_user_id, buying_signals, 
                 sentiment, urgency_level, processed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message_data['dialogue_id'],
                message_data['user_id'],
                message_data.get('username'),
                message_data['message_id'],
                message_data['text'],
                message_data['timestamp'],
                message_data.get('reply_to_message_id'),
                message_data.get('reply_to_user_id'),
                message_data.get('buying_signals'),
                message_data.get('sentiment', 'neutral'),
                message_data.get('urgency_level', 'none'),
                message_data.get('processed', False)
            ))
            await db.commit()
            
    except Exception as e:
        logger.error(f"Ошибка сохранения сообщения диалога: {e}")

async def save_dialogue_analysis(analysis_data: dict, db_path: str = "data/bot.db"):
    """Сохранение результата анализа диалога"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT INTO dialogue_analyses 
                (dialogue_id, is_valuable_dialogue, confidence_score, 
                 business_relevance_score, potential_leads_count, group_dynamics,
                 dialogue_summary, key_insights, recommended_actions, 
                 next_best_action, estimated_timeline, group_budget_estimate,
                 ai_model_used, analysis_duration_ms, raw_ai_response, created_leads_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                analysis_data['dialogue_id'],
                analysis_data.get('is_valuable_dialogue', False),
                analysis_data.get('confidence_score', 0),
                analysis_data.get('business_relevance_score', 0),
                analysis_data.get('potential_leads_count', 0),
                analysis_data.get('group_dynamics'),
                analysis_data.get('dialogue_summary'),
                analysis_data.get('key_insights'),
                analysis_data.get('recommended_actions'),
                analysis_data.get('next_best_action'),
                analysis_data.get('estimated_timeline'),
                analysis_data.get('group_budget_estimate'),
                analysis_data.get('ai_model_used'),
                analysis_data.get('analysis_duration_ms', 0),
                analysis_data.get('raw_ai_response'),
                analysis_data.get('created_leads_count', 0)
            ))
            await db.commit()
            
    except Exception as e:
        logger.error(f"Ошибка сохранения анализа диалога: {e}")

async def save_participant_influence(influence_data: dict, db_path: str = "data/bot.db"):
    """Сохранение данных о влиянии между участниками"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO participant_influence 
                (dialogue_id, influencer_user_id, influenced_user_id, 
                 influence_strength, influence_type)
                VALUES (?, ?, ?, ?, ?)
            """, (
                influence_data['dialogue_id'],
                influence_data['influencer_user_id'],
                influence_data['influenced_user_id'],
                influence_data.get('influence_strength', 0.0),
                influence_data.get('influence_type', 'general')
            ))
            await db.commit()
            
    except Exception as e:
        logger.error(f"Ошибка сохранения данных о влиянии: {e}")

async def get_dialogue_stats(days: int = 7, db_path: str = "data/bot.db"):
    """Получение статистики диалогов"""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as total_dialogues,
                    COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_dialogues,
                    COUNT(CASE WHEN is_business_related = 1 THEN 1 END) as business_dialogues,
                    AVG(participants_count) as avg_participants,
                    AVG(messages_count) as avg_messages,
                    SUM(participants_count) as total_participants
                FROM dialogues 
                WHERE start_time >= datetime('now', '-{} days')
            """.format(days))
            
            stats = await cursor.fetchone()
            
            # Статистика анализов
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as total_analyses,
                    COUNT(CASE WHEN is_valuable_dialogue = 1 THEN 1 END) as valuable_dialogues,
                    AVG(confidence_score) as avg_confidence,
                    SUM(created_leads_count) as total_leads_from_dialogues
                FROM dialogue_analyses 
                WHERE analysis_date >= datetime('now', '-{} days')
            """.format(days))
            
            analysis_stats = await cursor.fetchone()
            
            return {
                'total_dialogues': stats[0] or 0,
                'completed_dialogues': stats[1] or 0,
                'business_dialogues': stats[2] or 0,
                'avg_participants': stats[3] or 0,
                'avg_messages': stats[4] or 0,
                'total_participants': stats[5] or 0,
                'total_analyses': analysis_stats[0] or 0,
                'valuable_dialogues': analysis_stats[1] or 0,
                'avg_confidence': analysis_stats[2] or 0,
                'total_leads_from_dialogues': analysis_stats[3] or 0
            }
            
    except Exception as e:
        logger.error(f"Ошибка получения статистики диалогов: {e}")
        return {}

async def get_active_dialogues(db_path: str = "data/bot.db"):
    """Получение активных диалогов"""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("""
                SELECT dialogue_id, channel_title, participants_count, messages_count,
                       start_time, last_activity, is_business_related
                FROM dialogues 
                WHERE status = 'active'
                ORDER BY last_activity DESC
                LIMIT 20
            """)
            
            dialogues = await cursor.fetchall()
            return dialogues
            
    except Exception as e:
        logger.error(f"Ошибка получения активных диалогов: {e}")
        return []

async def cleanup_old_dialogues(days: int = 30, db_path: str = "data/bot.db"):
    """Очистка старых диалогов"""
    try:
        async with aiosqlite.connect(db_path) as db:
            # Удаляем старые диалоги и связанные данные
            await db.execute("""
                DELETE FROM dialogues 
                WHERE start_time < datetime('now', '-{} days')
                AND status = 'completed'
            """.format(days))
            
            # Очищаем сиротские записи
            await db.execute("""
                DELETE FROM dialogue_participants 
                WHERE dialogue_id NOT IN (SELECT dialogue_id FROM dialogues)
            """)
            
            await db.execute("""
                DELETE FROM dialogue_messages 
                WHERE dialogue_id NOT IN (SELECT dialogue_id FROM dialogues)
            """)
            
            await db.execute("""
                DELETE FROM dialogue_analyses 
                WHERE dialogue_id NOT IN (SELECT dialogue_id FROM dialogues)
            """)
            
            await db.execute("""
                DELETE FROM participant_influence 
                WHERE dialogue_id NOT IN (SELECT dialogue_id FROM dialogues)
            """)
            
            await db.commit()
            logger.info(f"Очищены диалоги старше {days} дней")
            
    except Exception as e:
        logger.error(f"Ошибка очистки старых диалогов: {e}")

async def export_dialogue_data(dialogue_id: str, db_path: str = "data/bot.db"):
    """Экспорт данных диалога"""
    try:
        async with aiosqlite.connect(db_path) as db:
            # Основные данные диалога
            cursor = await db.execute("""
                SELECT * FROM dialogues WHERE dialogue_id = ?
            """, (dialogue_id,))
            dialogue = await cursor.fetchone()
            
            if not dialogue:
                return None
            
            # Участники
            cursor = await db.execute("""
                SELECT * FROM dialogue_participants WHERE dialogue_id = ?
            """, (dialogue_id,))
            participants = await cursor.fetchall()
            
            # Сообщения
            cursor = await db.execute("""
                SELECT * FROM dialogue_messages WHERE dialogue_id = ?
                ORDER BY timestamp
            """, (dialogue_id,))
            messages = await cursor.fetchall()
            
            # Анализы
            cursor = await db.execute("""
                SELECT * FROM dialogue_analyses WHERE dialogue_id = ?
                ORDER BY analysis_date DESC
            """, (dialogue_id,))
            analyses = await cursor.fetchall()
            
            return {
                'dialogue': dialogue,
                'participants': participants,
                'messages': messages,
                'analyses': analyses
            }
            
    except Exception as e:
        logger.error(f"Ошибка экспорта данных диалога: {e}")
        return None
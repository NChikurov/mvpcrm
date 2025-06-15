"""
Миграция базы данных для добавления AI полей
"""

import aiosqlite
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

async def migrate_database_for_ai(db_path: str = "data/bot.db"):
    """Миграция базы данных для поддержки AI анализа"""
    try:
        # Создаем директорию если не существует
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        async with aiosqlite.connect(db_path) as db:
            # Проверяем текущую версию схемы
            cursor = await db.execute("PRAGMA table_info(leads)")
            columns = await cursor.fetchall()
            existing_columns = [col[1] for col in columns]
            
            logger.info(f"Существующие колонки в таблице leads: {existing_columns}")
            
            # AI поля для добавления
            ai_fields = [
                ('lead_quality', 'TEXT DEFAULT "unknown"'),
                ('interests', 'TEXT'),
                ('buying_signals', 'TEXT'),
                ('urgency_level', 'TEXT DEFAULT "none"'),
                ('estimated_budget', 'TEXT'),
                ('timeline', 'TEXT'),
                ('pain_points', 'TEXT'),
                ('decision_stage', 'TEXT DEFAULT "awareness"'),
                ('contact_attempts', 'INTEGER DEFAULT 0'),
                ('last_contact_date', 'TIMESTAMP'),
                ('notes', 'TEXT')
            ]
            
            # Добавляем новые поля если их нет
            for field_name, field_definition in ai_fields:
                if field_name not in existing_columns:
                    alter_sql = f"ALTER TABLE leads ADD COLUMN {field_name} {field_definition}"
                    await db.execute(alter_sql)
                    logger.info(f"Добавлена колонка: {field_name}")
            
            # Создаем новые таблицы
            
            # Таблица логов AI анализа
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ai_analysis_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    analysis_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    confidence_score INTEGER DEFAULT 0,
                    lead_quality TEXT DEFAULT 'unknown',
                    is_lead BOOLEAN DEFAULT FALSE,
                    context_messages_count INTEGER DEFAULT 0,
                    analysis_duration_ms INTEGER DEFAULT 0,
                    ai_model_used TEXT,
                    raw_ai_response TEXT
                )
            """)
            
            # Таблица взаимодействий с пользователями
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    interaction_type TEXT DEFAULT 'message',
                    interaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    description TEXT,
                    outcome TEXT,
                    next_action TEXT,
                    admin_id INTEGER,
                    FOREIGN KEY (user_id) REFERENCES leads(telegram_id)
                )
            """)
            
            # Создаем индексы для оптимизации
            await db.execute("CREATE INDEX IF NOT EXISTS idx_ai_logs_user_id ON ai_analysis_logs(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_ai_logs_date ON ai_analysis_logs(analysis_date)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_interactions_user_id ON user_interactions(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_leads_quality ON leads(lead_quality)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_leads_urgency ON leads(urgency_level)")
            
            await db.commit()
            logger.info("✅ Миграция базы данных завершена успешно")
            
    except Exception as e:
        logger.error(f"❌ Ошибка миграции базы данных: {e}")
        raise

async def log_ai_analysis(user_id: int, analysis_result, context_messages_count: int, 
                         duration_ms: int, ai_model: str, raw_response: str, 
                         db_path: str = "data/bot.db"):
    """Логирование AI анализа"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT INTO ai_analysis_logs 
                (user_id, confidence_score, lead_quality, is_lead, context_messages_count,
                 analysis_duration_ms, ai_model_used, raw_ai_response)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                analysis_result.confidence_score if analysis_result else 0,
                analysis_result.lead_quality if analysis_result else 'unknown',
                analysis_result.is_lead if analysis_result else False,
                context_messages_count,
                duration_ms,
                ai_model,
                raw_response
            ))
            await db.commit()
            
    except Exception as e:
        logger.error(f"Ошибка логирования AI анализа: {e}")

async def add_user_interaction(user_id: int, interaction_type: str, description: str,
                              outcome: str = None, next_action: str = None, admin_id: int = None,
                              db_path: str = "data/bot.db"):
    """Добавление взаимодействия с пользователем"""
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT INTO user_interactions 
                (user_id, interaction_type, description, outcome, next_action, admin_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, interaction_type, description, outcome, next_action, admin_id))
            await db.commit()
            
    except Exception as e:
        logger.error(f"Ошибка добавления взаимодействия: {e}")

async def get_ai_analysis_stats(days: int = 7, db_path: str = "data/bot.db"):
    """Статистика AI анализов"""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as total_analyses,
                    COUNT(CASE WHEN is_lead = 1 THEN 1 END) as leads_found,
                    AVG(confidence_score) as avg_confidence,
                    AVG(analysis_duration_ms) as avg_duration_ms,
                    lead_quality,
                    COUNT(*) as count_by_quality
                FROM ai_analysis_logs 
                WHERE analysis_date >= datetime('now', '-{} days')
                GROUP BY lead_quality
            """.format(days))
            
            results = await cursor.fetchall()
            return results
            
    except Exception as e:
        logger.error(f"Ошибка получения статистики AI: {e}")
        return []

async def get_user_interaction_history(user_id: int, limit: int = 10, 
                                      db_path: str = "data/bot.db"):
    """История взаимодействий с пользователем"""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("""
                SELECT interaction_type, interaction_date, description, outcome, next_action
                FROM user_interactions 
                WHERE user_id = ?
                ORDER BY interaction_date DESC
                LIMIT ?
            """, (user_id, limit))
            
            results = await cursor.fetchall()
            return results
            
    except Exception as e:
        logger.error(f"Ошибка получения истории взаимодействий: {e}")
        return []

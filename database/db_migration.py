"""
Оптимизированная миграция базы данных с улучшенной обработкой ошибок
Batch operations, транзакции, rollback механизмы
"""

import aiosqlite
import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# === КОНФИГУРАЦИИ МИГРАЦИЙ ===

@dataclass
class MigrationConfig:
    """Конфигурация миграции"""
    db_path: str = "data/bot.db"
    backup_enabled: bool = True
    batch_size: int = 1000
    timeout_seconds: int = 30
    retry_attempts: int = 3
    rollback_on_error: bool = True

@dataclass
class MigrationResult:
    """Результат миграции"""
    success: bool
    duration_ms: float
    operations_count: int
    error_message: Optional[str] = None
    rollback_performed: bool = False

# === БАЗОВЫЕ КЛАССЫ ===

class MigrationOperation(ABC):
    """Базовый класс для операций миграции"""
    
    @abstractmethod
    async def execute(self, conn: aiosqlite.Connection) -> bool:
        pass
    
    @abstractmethod
    async def rollback(self, conn: aiosqlite.Connection) -> bool:
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        pass

class CreateTableOperation(MigrationOperation):
    """Операция создания таблицы"""
    
    def __init__(self, table_name: str, sql: str, drop_on_rollback: bool = True):
        self.table_name = table_name
        self.sql = sql
        self.drop_on_rollback = drop_on_rollback
    
    async def execute(self, conn: aiosqlite.Connection) -> bool:
        """Выполнение создания таблицы"""
        try:
            await conn.execute(self.sql)
            logger.info(f"Table '{self.table_name}' created successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to create table '{self.table_name}': {e}")
            return False
    
    async def rollback(self, conn: aiosqlite.Connection) -> bool:
        """Откат создания таблицы"""
        if not self.drop_on_rollback:
            return True
        
        try:
            await conn.execute(f"DROP TABLE IF EXISTS {self.table_name}")
            logger.info(f"Table '{self.table_name}' dropped during rollback")
            return True
        except Exception as e:
            logger.error(f"Failed to drop table '{self.table_name}' during rollback: {e}")
            return False
    
    @property
    def description(self) -> str:
        return f"Create table '{self.table_name}'"

class AddColumnOperation(MigrationOperation):
    """Операция добавления колонки"""
    
    def __init__(self, table_name: str, column_name: str, column_definition: str):
        self.table_name = table_name
        self.column_name = column_name
        self.column_definition = column_definition
        self.column_existed = False
    
    async def execute(self, conn: aiosqlite.Connection) -> bool:
        """Выполнение добавления колонки"""
        try:
            # Проверяем существование колонки
            cursor = await conn.execute(f"PRAGMA table_info({self.table_name})")
            columns = [row[1] for row in await cursor.fetchall()]
            
            if self.column_name in columns:
                self.column_existed = True
                logger.info(f"Column '{self.column_name}' already exists in '{self.table_name}'")
                return True
            
            # Добавляем колонку
            sql = f"ALTER TABLE {self.table_name} ADD COLUMN {self.column_name} {self.column_definition}"
            await conn.execute(sql)
            logger.info(f"Column '{self.column_name}' added to '{self.table_name}'")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add column '{self.column_name}' to '{self.table_name}': {e}")
            return False
    
    async def rollback(self, conn: aiosqlite.Connection) -> bool:
        """Откат добавления колонки (SQLite не поддерживает DROP COLUMN до 3.35.0)"""
        if self.column_existed:
            return True
        
        logger.warning(f"Cannot rollback column addition for '{self.column_name}' - SQLite limitation")
        return True  # Не считаем это ошибкой
    
    @property
    def description(self) -> str:
        return f"Add column '{self.column_name}' to '{self.table_name}'"

class CreateIndexOperation(MigrationOperation):
    """Операция создания индекса"""
    
    def __init__(self, index_name: str, sql: str):
        self.index_name = index_name
        self.sql = sql
    
    async def execute(self, conn: aiosqlite.Connection) -> bool:
        """Выполнение создания индекса"""
        try:
            await conn.execute(self.sql)
            logger.info(f"Index '{self.index_name}' created successfully")
            return True
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.info(f"Index '{self.index_name}' already exists")
                return True
            logger.error(f"Failed to create index '{self.index_name}': {e}")
            return False
    
    async def rollback(self, conn: aiosqlite.Connection) -> bool:
        """Откат создания индекса"""
        try:
            await conn.execute(f"DROP INDEX IF EXISTS {self.index_name}")
            logger.info(f"Index '{self.index_name}' dropped during rollback")
            return True
        except Exception as e:
            logger.error(f"Failed to drop index '{self.index_name}' during rollback: {e}")
            return False
    
    @property
    def description(self) -> str:
        return f"Create index '{self.index_name}'"

class BatchDataOperation(MigrationOperation):
    """Операция пакетного изменения данных"""
    
    def __init__(self, description: str, operation_func: Callable, rollback_func: Optional[Callable] = None):
        self._description = description
        self.operation_func = operation_func
        self.rollback_func = rollback_func
    
    async def execute(self, conn: aiosqlite.Connection) -> bool:
        """Выполнение пакетной операции"""
        try:
            await self.operation_func(conn)
            logger.info(f"Batch operation completed: {self._description}")
            return True
        except Exception as e:
            logger.error(f"Batch operation failed: {self._description}: {e}")
            return False
    
    async def rollback(self, conn: aiosqlite.Connection) -> bool:
        """Откат пакетной операции"""
        if self.rollback_func is None:
            logger.warning(f"No rollback function for: {self._description}")
            return True
        
        try:
            await self.rollback_func(conn)
            logger.info(f"Batch operation rollback completed: {self._description}")
            return True
        except Exception as e:
            logger.error(f"Batch operation rollback failed: {self._description}: {e}")
            return False
    
    @property
    def description(self) -> str:
        return self._description

# === ОПТИМИЗИРОВАННЫЙ МИГРАТОР ===

class OptimizedDatabaseMigrator:
    """Оптимизированный мигратор базы данных"""
    
    def __init__(self, config: MigrationConfig = None):
        self.config = config or MigrationConfig()
        self.operations: List[MigrationOperation] = []
        self.completed_operations: List[MigrationOperation] = []
    
    def add_operation(self, operation: MigrationOperation):
        """Добавление операции миграции"""
        self.operations.append(operation)
    
    @asynccontextmanager
    async def get_connection(self):
        """Получение соединения с базой данных"""
        # Создаем директорию если не существует
        Path(self.config.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        conn = await aiosqlite.connect(self.config.db_path)
        try:
            # Оптимизируем настройки для миграций
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA cache_size=10000")
            await conn.execute("PRAGMA temp_store=MEMORY")
            yield conn
        finally:
            await conn.close()
    
    async def create_backup(self) -> Optional[str]:
        """Создание резервной копии базы данных"""
        if not self.config.backup_enabled:
            return None
        
        try:
            backup_path = f"{self.config.db_path}.backup_{int(time.time())}"
            
            async with self.get_connection() as source_conn:
                async with aiosqlite.connect(backup_path) as backup_conn:
                    await source_conn.backup(backup_conn)
            
            logger.info(f"Database backup created: {backup_path}")
            return backup_path
            
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            return None
    
    async def execute_migration(self) -> MigrationResult:
        """Выполнение миграции с обработкой ошибок"""
        start_time = time.time()
        operations_count = len(self.operations)
        
        logger.info(f"Starting migration with {operations_count} operations")
        
        # Создаем бэкап
        backup_path = await self.create_backup()
        
        try:
            async with self.get_connection() as conn:
                # Начинаем транзакцию
                await conn.execute("BEGIN TRANSACTION")
                
                try:
                    # Выполняем операции
                    for i, operation in enumerate(self.operations):
                        logger.info(f"Executing operation {i+1}/{operations_count}: {operation.description}")
                        
                        success = await asyncio.wait_for(
                            operation.execute(conn),
                            timeout=self.config.timeout_seconds
                        )
                        
                        if not success:
                            raise Exception(f"Operation failed: {operation.description}")
                        
                        self.completed_operations.append(operation)
                    
                    # Коммитим транзакцию
                    await conn.commit()
                    
                    duration_ms = (time.time() - start_time) * 1000
                    logger.info(f"Migration completed successfully in {duration_ms:.1f}ms")
                    
                    return MigrationResult(
                        success=True,
                        duration_ms=duration_ms,
                        operations_count=operations_count
                    )
                
                except Exception as e:
                    # Откатываем транзакцию
                    await conn.rollback()
                    
                    error_msg = f"Migration failed: {e}"
                    logger.error(error_msg)
                    
                    # Выполняем rollback операций если требуется
                    rollback_performed = False
                    if self.config.rollback_on_error and self.completed_operations:
                        rollback_performed = await self._perform_rollback(conn)
                    
                    duration_ms = (time.time() - start_time) * 1000
                    
                    return MigrationResult(
                        success=False,
                        duration_ms=duration_ms,
                        operations_count=len(self.completed_operations),
                        error_message=error_msg,
                        rollback_performed=rollback_performed
                    )
        
        except Exception as e:
            error_msg = f"Critical migration error: {e}"
            logger.critical(error_msg)
            
            duration_ms = (time.time() - start_time) * 1000
            
            return MigrationResult(
                success=False,
                duration_ms=duration_ms,
                operations_count=0,
                error_message=error_msg
            )
    
    async def _perform_rollback(self, conn: aiosqlite.Connection) -> bool:
        """Выполнение отката операций"""
        logger.info("Performing operation rollback")
        
        rollback_success = True
        
        # Откатываем операции в обратном порядке
        for operation in reversed(self.completed_operations):
            try:
                logger.info(f"Rolling back: {operation.description}")
                success = await operation.rollback(conn)
                if not success:
                    rollback_success = False
                    logger.error(f"Rollback failed for: {operation.description}")
            except Exception as e:
                rollback_success = False
                logger.error(f"Rollback error for {operation.description}: {e}")
        
        if rollback_success:
            logger.info("Rollback completed successfully")
        else:
            logger.error("Rollback completed with errors")
        
        return rollback_success

# === КОНКРЕТНЫЕ МИГРАЦИИ ===

async def migrate_database_for_ai(db_path: str = "data/bot.db") -> MigrationResult:
    """Оптимизированная миграция базы данных для поддержки AI анализа"""
    
    config = MigrationConfig(db_path=db_path)
    migrator = OptimizedDatabaseMigrator(config)
    
    # Добавляем AI поля в таблицу leads
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
    
    for field_name, field_definition in ai_fields:
        migrator.add_operation(AddColumnOperation('leads', field_name, field_definition))
    
    # Создаем таблицу логов AI анализа
    migrator.add_operation(CreateTableOperation(
        'ai_analysis_logs',
        """
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
        """
    ))
    
    # Создаем таблицу взаимодействий с пользователями
    migrator.add_operation(CreateTableOperation(
        'user_interactions',
        """
        CREATE TABLE IF NOT EXISTS user_interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            interaction_type TEXT DEFAULT 'message',
            interaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT,
            outcome TEXT,
            next_action TEXT,
            admin_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(telegram_id)
        )
        """
    ))
    
    # Создаем индексы для оптимизации
    indices = [
        ('idx_ai_logs_user_id', "CREATE INDEX IF NOT EXISTS idx_ai_logs_user_id ON ai_analysis_logs(user_id)"),
        ('idx_ai_logs_date', "CREATE INDEX IF NOT EXISTS idx_ai_logs_date ON ai_analysis_logs(analysis_date)"),
        ('idx_interactions_user_id', "CREATE INDEX IF NOT EXISTS idx_interactions_user_id ON user_interactions(user_id)"),
        ('idx_leads_quality', "CREATE INDEX IF NOT EXISTS idx_leads_quality ON leads(lead_quality)"),
        ('idx_leads_urgency', "CREATE INDEX IF NOT EXISTS idx_leads_urgency ON leads(urgency_level)"),
        ('idx_leads_created_at', "CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at)"),
        ('idx_users_last_activity', "CREATE INDEX IF NOT EXISTS idx_users_last_activity ON users(last_activity)"),
        ('idx_messages_processed', "CREATE INDEX IF NOT EXISTS idx_messages_processed ON messages(processed)")
    ]
    
    for index_name, sql in indices:
        migrator.add_operation(CreateIndexOperation(index_name, sql))
    
    # Добавляем операцию очистки старых данных
    async def cleanup_old_data(conn: aiosqlite.Connection):
        """Очистка старых неиспользуемых данных"""
        cutoff_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Удаляем старые обработанные сообщения (старше 30 дней)
        await conn.execute("""
            DELETE FROM messages 
            WHERE processed = 1 
            AND created_at < datetime('now', '-30 days')
        """)
        
        # Обновляем статистику
        await conn.execute("ANALYZE")
        
        logger.info("Old data cleanup completed")
    
    migrator.add_operation(BatchDataOperation(
        "Cleanup old processed messages and update statistics",
        cleanup_old_data
    ))
    
    # Выполняем миграцию
    result = await migrator.execute_migration()
    
    if result.success:
        logger.info("✅ AI database migration completed successfully")
    else:
        logger.error(f"❌ AI database migration failed: {result.error_message}")
    
    return result

# === УТИЛИТЫ ДЛЯ ЛОГИРОВАНИЯ AI АНАЛИЗА ===

async def log_ai_analysis(user_id: int, analysis_result, context_messages_count: int, 
                         duration_ms: int, ai_model: str, raw_response: str, 
                         db_path: str = "data/bot.db") -> bool:
    """Оптимизированное логирование AI анализа с batch операциями"""
    try:
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute("""
                INSERT INTO ai_analysis_logs 
                (user_id, confidence_score, lead_quality, is_lead, context_messages_count,
                 analysis_duration_ms, ai_model_used, raw_ai_response)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                getattr(analysis_result, 'confidence_score', 0),
                getattr(analysis_result, 'lead_quality', 'unknown'),
                getattr(analysis_result, 'is_lead', False),
                context_messages_count,
                duration_ms,
                ai_model,
                raw_response[:1000] if raw_response else None  # Ограничиваем размер
            ))
            await conn.commit()
            return True
            
    except Exception as e:
        logger.error(f"Failed to log AI analysis: {e}")
        return False

async def batch_log_ai_analyses(analyses_data: List[Dict[str, Any]], 
                               db_path: str = "data/bot.db") -> int:
    """Пакетное логирование AI анализов"""
    if not analyses_data:
        return 0
    
    try:
        async with aiosqlite.connect(db_path) as conn:
            data_tuples = []
            for data in analyses_data:
                data_tuples.append((
                    data['user_id'],
                    data.get('confidence_score', 0),
                    data.get('lead_quality', 'unknown'),
                    data.get('is_lead', False),
                    data.get('context_messages_count', 0),
                    data.get('duration_ms', 0),
                    data.get('ai_model', ''),
                    data.get('raw_response', '')[:1000] if data.get('raw_response') else None
                ))
            
            await conn.executemany("""
                INSERT INTO ai_analysis_logs 
                (user_id, confidence_score, lead_quality, is_lead, context_messages_count,
                 analysis_duration_ms, ai_model_used, raw_ai_response)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, data_tuples)
            
            await conn.commit()
            logger.info(f"Batch logged {len(analyses_data)} AI analyses")
            return len(analyses_data)
            
    except Exception as e:
        logger.error(f"Failed to batch log AI analyses: {e}")
        return 0

async def add_user_interaction(user_id: int, interaction_type: str, description: str,
                              outcome: str = None, next_action: str = None, admin_id: int = None,
                              db_path: str = "data/bot.db") -> bool:
    """Добавление взаимодействия с пользователем"""
    try:
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute("""
                INSERT INTO user_interactions 
                (user_id, interaction_type, description, outcome, next_action, admin_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, interaction_type, description, outcome, next_action, admin_id))
            await conn.commit()
            return True
            
    except Exception as e:
        logger.error(f"Failed to add user interaction: {e}")
        return False

async def get_ai_analysis_stats(days: int = 7, db_path: str = "data/bot.db") -> Dict[str, Any]:
    """Получение статистики AI анализов с кэшированием"""
    try:
        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute("""
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
            
            # Форматируем результаты
            stats = {
                'total_analyses': 0,
                'leads_found': 0,
                'avg_confidence': 0,
                'avg_duration_ms': 0,
                'quality_distribution': {}
            }
            
            for row in results:
                if row[4]:  # lead_quality
                    stats['quality_distribution'][row[4]] = row[5]
                
                # Обновляем общие статистики (берем из первой строки)
                if stats['total_analyses'] == 0:
                    stats['total_analyses'] = row[0] or 0
                    stats['leads_found'] = row[1] or 0
                    stats['avg_confidence'] = row[2] or 0
                    stats['avg_duration_ms'] = row[3] or 0
            
            return stats
            
    except Exception as e:
        logger.error(f"Failed to get AI analysis stats: {e}")
        return {}

async def get_user_interaction_history(user_id: int, limit: int = 10, 
                                      db_path: str = "data/bot.db") -> List[Dict[str, Any]]:
    """История взаимодействий с пользователем"""
    try:
        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute("""
                SELECT interaction_type, interaction_date, description, outcome, next_action
                FROM user_interactions 
                WHERE user_id = ?
                ORDER BY interaction_date DESC
                LIMIT ?
            """, (user_id, limit))
            
            results = await cursor.fetchall()
            
            return [
                {
                    'interaction_type': row[0],
                    'interaction_date': row[1],
                    'description': row[2],
                    'outcome': row[3],
                    'next_action': row[4]
                }
                for row in results
            ]
            
    except Exception as e:
        logger.error(f"Failed to get user interaction history: {e}")
        return []

# === MAINTENANCE ФУНКЦИИ ===

async def optimize_database(db_path: str = "data/bot.db") -> bool:
    """Оптимизация базы данных"""
    try:
        async with aiosqlite.connect(db_path) as conn:
            # Обновляем статистику таблиц
            await conn.execute("ANALYZE")
            
            # Сжимаем базу данных
            await conn.execute("VACUUM")
            
            # Оптимизируем настройки
            await conn.execute("PRAGMA optimize")
            
            await conn.commit()
            logger.info("Database optimization completed")
            return True
            
    except Exception as e:
        logger.error(f"Database optimization failed: {e}")
        return False

async def cleanup_old_logs(days: int = 90, db_path: str = "data/bot.db") -> int:
    """Очистка старых логов"""
    try:
        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute("""
                DELETE FROM ai_analysis_logs 
                WHERE analysis_date < datetime('now', '-{} days')
            """.format(days))
            
            deleted_count = cursor.rowcount
            
            await conn.execute("""
                DELETE FROM user_interactions 
                WHERE interaction_date < datetime('now', '-{} days')
            """.format(days))
            
            await conn.commit()
            logger.info(f"Cleaned up {deleted_count} old log entries")
            return deleted_count
            
    except Exception as e:
        logger.error(f"Failed to cleanup old logs: {e}")
        return 0
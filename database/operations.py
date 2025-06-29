"""
Оптимизированные операции базы данных для AI CRM Bot
SOLID принципы, batch operations, connection pooling, retry механизмы, метрики
"""

import asyncio
import aiosqlite
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple, Protocol, Callable
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
import json
from functools import wraps

from .models import User, Lead, ParsedChannel, Message, Setting, BotStats, Broadcast

logger = logging.getLogger(__name__)

# === ПРОТОКОЛЫ И ИНТЕРФЕЙСЫ (SOLID - Interface Segregation) ===

class DatabaseConnection(Protocol):
    """Протокол соединения с базой данных"""
    async def execute(self, sql: str, parameters: tuple = ()) -> Any: ...
    async def executemany(self, sql: str, parameters: List[tuple]) -> Any: ...
    async def fetchone(self, sql: str, parameters: tuple = ()) -> Optional[tuple]: ...
    async def fetchall(self, sql: str, parameters: tuple = ()) -> List[tuple]: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...

class Repository(Protocol):
    """Базовый протокол репозитория"""
    async def create(self, entity: Any) -> bool: ...
    async def get_by_id(self, entity_id: Any) -> Optional[Any]: ...
    async def update(self, entity: Any) -> bool: ...
    async def delete(self, entity_id: Any) -> bool: ...

# === МЕТРИКИ И МОНИТОРИНГ ===

@dataclass
class DatabaseMetrics:
    """Метрики производительности БД"""
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    total_execution_time: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    connection_pool_size: int = 0
    active_connections: int = 0
    retry_attempts: int = 0
    batch_operations: int = 0

class DatabaseMonitor:
    """Монитор производительности БД"""
    
    def __init__(self):
        self.metrics = DatabaseMetrics()
        self.slow_queries: List[Dict[str, Any]] = []
        self.query_times: Dict[str, List[float]] = {}
    
    def record_query(self, query_type: str, execution_time: float, success: bool):
        """Запись выполненного запроса"""
        self.metrics.total_queries += 1
        self.metrics.total_execution_time += execution_time
        
        if success:
            self.metrics.successful_queries += 1
        else:
            self.metrics.failed_queries += 1
        
        # Отслеживаем медленные запросы
        if execution_time > 1.0:  # Больше секунды
            self.slow_queries.append({
                'query_type': query_type,
                'execution_time': execution_time,
                'timestamp': datetime.now(),
                'success': success
            })
        
        # Ведем статистику по типам запросов
        if query_type not in self.query_times:
            self.query_times[query_type] = []
        
        self.query_times[query_type].append(execution_time)
        
        # Ограничиваем размер списков
        if len(self.query_times[query_type]) > 100:
            self.query_times[query_type] = self.query_times[query_type][-50:]
        
        if len(self.slow_queries) > 50:
            self.slow_queries = self.slow_queries[-25:]
    
    def get_avg_time(self, query_type: str) -> float:
        """Среднее время выполнения запросов типа"""
        times = self.query_times.get(query_type, [])
        return sum(times) / len(times) if times else 0.0
    
    def get_metrics(self) -> Dict[str, Any]:
        """Получение метрик"""
        avg_time = (self.metrics.total_execution_time / 
                   max(self.metrics.total_queries, 1))
        
        success_rate = (self.metrics.successful_queries / 
                       max(self.metrics.total_queries, 1)) * 100
        
        return {
            'total_queries': self.metrics.total_queries,
            'success_rate': success_rate,
            'avg_execution_time': avg_time,
            'slow_queries_count': len(self.slow_queries),
            'cache_hit_rate': (self.metrics.cache_hits / 
                              max(self.metrics.cache_hits + self.metrics.cache_misses, 1)) * 100,
            'retry_attempts': self.metrics.retry_attempts,
            'batch_operations': self.metrics.batch_operations,
            'query_types_stats': {
                query_type: {
                    'count': len(times),
                    'avg_time': sum(times) / len(times) if times else 0
                }
                for query_type, times in self.query_times.items()
            }
        }

# Глобальный монитор
db_monitor = DatabaseMonitor()

# === КЭШИРОВАНИЕ ===

class QueryCache:
    """Кэш для запросов"""
    
    def __init__(self, ttl: int = 300, max_size: int = 1000):
        self.cache: Dict[str, Tuple[Any, float]] = {}
        self.ttl = ttl
        self.max_size = max_size
    
    def get(self, key: str) -> Optional[Any]:
        """Получение из кэша"""
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                db_monitor.metrics.cache_hits += 1
                return value
            else:
                del self.cache[key]
        
        db_monitor.metrics.cache_misses += 1
        return None
    
    def set(self, key: str, value: Any):
        """Сохранение в кэш"""
        # Очищаем место если нужно
        if len(self.cache) >= self.max_size:
            # Удаляем 20% самых старых записей
            sorted_items = sorted(self.cache.items(), key=lambda x: x[1][1])
            for i in range(len(sorted_items) // 5):
                del self.cache[sorted_items[i][0]]
        
        self.cache[key] = (value, time.time())
    
    def clear(self):
        """Очистка кэша"""
        self.cache.clear()

# Глобальный кэш
query_cache = QueryCache()

# === RETRY МЕХАНИЗМ ===

def with_retry(max_attempts: int = 3, delay: float = 1.0, 
               backoff: float = 2.0, exceptions: Tuple = (Exception,)):
    """Декоратор для retry механизма"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    db_monitor.metrics.retry_attempts += 1
                    
                    if attempt == max_attempts - 1:
                        break
                    
                    logger.warning(f"Attempt {attempt + 1} failed: {e}, retrying in {current_delay}s")
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff
            
            raise last_exception
        return wrapper
    return decorator

# === CONNECTION POOL ===

class ConnectionPool:
    """Пул соединений с базой данных"""
    
    def __init__(self, db_path: str, pool_size: int = 10):
        self.db_path = db_path
        self.pool_size = pool_size
        self.connections: List[aiosqlite.Connection] = []
        self.available: asyncio.Queue = asyncio.Queue()
        self.lock = asyncio.Lock()
        self._initialized = False
    
    async def initialize(self):
        """Инициализация пула"""
        if self._initialized:
            return
        
        async with self.lock:
            if self._initialized:
                return
            
            # Создаем директорию если не существует
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            
            for _ in range(self.pool_size):
                conn = await aiosqlite.connect(self.db_path)
                # Оптимизируем настройки соединения
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA synchronous=NORMAL")
                await conn.execute("PRAGMA cache_size=10000")
                await conn.execute("PRAGMA temp_store=MEMORY")
                await conn.execute("PRAGMA mmap_size=268435456")  # 256MB
                
                self.connections.append(conn)
                await self.available.put(conn)
            
            self._initialized = True
            db_monitor.metrics.connection_pool_size = self.pool_size
            logger.info(f"Connection pool initialized with {self.pool_size} connections")
    
    @asynccontextmanager
    async def get_connection(self):
        """Получение соединения из пула"""
        if not self._initialized:
            await self.initialize()
        
        conn = await self.available.get()
        db_monitor.metrics.active_connections += 1
        
        try:
            yield conn
        finally:
            await self.available.put(conn)
            db_monitor.metrics.active_connections -= 1
    
    async def close_all(self):
        """Закрытие всех соединений"""
        for conn in self.connections:
            await conn.close()
        self.connections.clear()
        self._initialized = False

# Глобальный пул соединений
connection_pool: Optional[ConnectionPool] = None

async def init_connection_pool(db_path: str = "data/bot.db", pool_size: int = 10):
    """Инициализация пула соединений"""
    global connection_pool
    connection_pool = ConnectionPool(db_path, pool_size)
    await connection_pool.initialize()

@asynccontextmanager
async def get_db_connection():
    """Получение соединения с БД"""
    if connection_pool is None:
        await init_connection_pool()
    
    async with connection_pool.get_connection() as conn:
        yield conn

# === БАЗОВЫЙ РЕПОЗИТОРИЙ (SOLID - Single Responsibility) ===

class BaseRepository(ABC):
    """Базовый репозиторий с общей функциональностью"""
    
    def __init__(self):
        self.table_name = ""
        self.primary_key = "id"
    
    async def _execute_query(self, query_type: str, sql: str, 
                           parameters: tuple = (), fetch_result: bool = False):
        """Выполнение запроса с мониторингом"""
        start_time = time.time()
        success = True
        result = None
        
        try:
            async with get_db_connection() as conn:
                if fetch_result:
                    cursor = await conn.execute(sql, parameters)
                    result = await cursor.fetchall()
                else:
                    await conn.execute(sql, parameters)
                    await conn.commit()
                    result = True
            
        except Exception as e:
            success = False
            logger.error(f"Database query failed: {query_type} - {e}")
            raise
        finally:
            execution_time = time.time() - start_time
            db_monitor.record_query(query_type, execution_time, success)
        
        return result
    
    async def _execute_batch(self, query_type: str, sql: str, 
                           parameters_list: List[tuple]) -> bool:
        """Выполнение batch операции"""
        if not parameters_list:
            return True
        
        start_time = time.time()
        success = True
        
        try:
            async with get_db_connection() as conn:
                await conn.executemany(sql, parameters_list)
                await conn.commit()
            
            db_monitor.metrics.batch_operations += 1
            logger.info(f"Batch operation completed: {len(parameters_list)} items")
            
        except Exception as e:
            success = False
            logger.error(f"Batch operation failed: {query_type} - {e}")
            raise
        finally:
            execution_time = time.time() - start_time
            db_monitor.record_query(f"batch_{query_type}", execution_time, success)
        
        return success

# === СПЕЦИАЛИЗИРОВАННЫЕ РЕПОЗИТОРИИ ===

class UserRepository(BaseRepository):
    """Репозиторий пользователей"""
    
    def __init__(self):
        super().__init__()
        self.table_name = "users"
        self.primary_key = "telegram_id"
    
    @with_retry(max_attempts=3)
    async def create_or_update(self, user: User) -> bool:
        """Создание или обновление пользователя"""
        sql = """
            INSERT OR REPLACE INTO users 
            (telegram_id, username, first_name, last_name, is_active, 
             registration_date, last_activity, interaction_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        parameters = (
            user.telegram_id,
            user.username,
            user.first_name,
            user.last_name,
            user.is_active,
            user.registration_date or datetime.now(),
            user.last_activity or datetime.now(),
            user.interaction_count
        )
        
        return await self._execute_query("user_create", sql, parameters)
    
    @with_retry(max_attempts=2)
    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Получение пользователя по Telegram ID с кэшированием"""
        cache_key = f"user_{telegram_id}"
        cached = query_cache.get(cache_key)
        if cached:
            return cached
        
        sql = """
            SELECT telegram_id, username, first_name, last_name, is_active, 
                   registration_date, last_activity, interaction_count
            FROM users WHERE telegram_id = ?
        """
        
        result = await self._execute_query("user_get", sql, (telegram_id,), True)
        
        if result:
            row = result[0]
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
            
            query_cache.set(cache_key, user)
            return user
        
        return None
    
    async def get_all(self, limit: int = 50, offset: int = 0) -> List[User]:
        """Получение всех пользователей"""
        sql = """
            SELECT telegram_id, username, first_name, last_name, is_active, 
                   registration_date, last_activity, interaction_count
            FROM users 
            ORDER BY last_activity DESC 
            LIMIT ? OFFSET ?
        """
        
        result = await self._execute_query("users_get_all", sql, (limit, offset), True)
        
        users = []
        for row in result:
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
    
    async def update_activity(self, telegram_id: int) -> bool:
        """Обновление активности пользователя"""
        sql = """
            UPDATE users 
            SET last_activity = ?, interaction_count = interaction_count + 1
            WHERE telegram_id = ?
        """
        
        return await self._execute_query(
            "user_update_activity", 
            sql, 
            (datetime.now(), telegram_id)
        )
    
    async def batch_update_activity(self, user_ids: List[int]) -> bool:
        """Batch обновление активности пользователей"""
        if not user_ids:
            return True
        
        sql = """
            UPDATE users 
            SET last_activity = ?, interaction_count = interaction_count + 1
            WHERE telegram_id = ?
        """
        
        now = datetime.now()
        parameters = [(now, user_id) for user_id in user_ids]
        
        return await self._execute_batch("user_batch_activity", sql, parameters)

class LeadRepository(BaseRepository):
    """Репозиторий лидов"""
    
    def __init__(self):
        super().__init__()
        self.table_name = "leads"
    
    @with_retry(max_attempts=3)
    async def create(self, lead: Lead) -> bool:
        """Создание лида"""
        sql = """
            INSERT INTO leads 
            (telegram_id, username, first_name, last_name, source_channel, 
             interest_score, message_text, message_date, is_contacted, status,
             lead_quality, interests, buying_signals, urgency_level,
             estimated_budget, timeline, pain_points, decision_stage,
             contact_attempts, last_contact_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        parameters = (
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
        )
        
        result = await self._execute_query("lead_create", sql, parameters)
        
        # Инвалидируем связанный кэш
        self._invalidate_lead_cache(lead.telegram_id)
        
        return result
    
    async def batch_create(self, leads: List[Lead]) -> bool:
        """Batch создание лидов"""
        if not leads:
            return True
        
        sql = """
            INSERT INTO leads 
            (telegram_id, username, first_name, last_name, source_channel, 
             interest_score, message_text, message_date, is_contacted, status,
             lead_quality, interests, buying_signals, urgency_level,
             estimated_budget, timeline, pain_points, decision_stage,
             contact_attempts, last_contact_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        parameters_list = []
        for lead in leads:
            parameters = (
                lead.telegram_id, lead.username, lead.first_name, lead.last_name,
                lead.source_channel, lead.interest_score, lead.message_text,
                lead.message_date or datetime.now(), lead.is_contacted, lead.status,
                lead.lead_quality, lead.interests, lead.buying_signals,
                lead.urgency_level, lead.estimated_budget, lead.timeline,
                lead.pain_points, lead.decision_stage, lead.contact_attempts,
                lead.last_contact_date, lead.notes
            )
            parameters_list.append(parameters)
        
        result = await self._execute_batch("lead_batch_create", sql, parameters_list)
        
        # Инвалидируем кэш
        for lead in leads:
            self._invalidate_lead_cache(lead.telegram_id)
        
        return result
    
    @with_retry(max_attempts=2)
    async def get_all(self, limit: int = 50, offset: int = 0) -> List[Lead]:
        """Получение всех лидов с оптимизацией"""
        cache_key = f"leads_all_{limit}_{offset}"
        cached = query_cache.get(cache_key)
        if cached:
            return cached
        
        sql = """
            SELECT id, telegram_id, username, first_name, last_name, source_channel, 
                   interest_score, message_text, message_date, is_contacted, created_at, status,
                   lead_quality, interests, buying_signals, urgency_level,
                   estimated_budget, timeline, pain_points, decision_stage,
                   contact_attempts, last_contact_date, notes
            FROM leads 
            ORDER BY created_at DESC 
            LIMIT ? OFFSET ?
        """
        
        result = await self._execute_query("leads_get_all", sql, (limit, offset), True)
        
        leads = []
        for row in result:
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
        
        # Кэшируем на короткое время (статистика быстро меняется)
        query_cache.set(cache_key, leads)
        
        return leads
    
    async def get_by_telegram_id(self, telegram_id: int) -> Optional[Lead]:
        """Получение лида по Telegram ID"""
        cache_key = f"lead_by_user_{telegram_id}"
        cached = query_cache.get(cache_key)
        if cached:
            return cached
        
        sql = """
            SELECT id, telegram_id, username, first_name, last_name, source_channel, 
                   interest_score, message_text, message_date, is_contacted, created_at, status,
                   lead_quality, interests, buying_signals, urgency_level,
                   estimated_budget, timeline, pain_points, decision_stage,
                   contact_attempts, last_contact_date, notes
            FROM leads 
            WHERE telegram_id = ? 
            ORDER BY created_at DESC 
            LIMIT 1
        """
        
        result = await self._execute_query("lead_get_by_user", sql, (telegram_id,), True)
        
        if result:
            row = result[0]
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
            
            query_cache.set(cache_key, lead)
            return lead
        
        return None
    
    def _invalidate_lead_cache(self, telegram_id: int):
        """Инвалидация кэша лидов"""
        # Простая инвалидация - очищаем весь кэш
        # В продакшене можно сделать более точечную инвалидацию
        cache_keys_to_remove = [
            key for key in query_cache.cache.keys() 
            if f"user_{telegram_id}" in key or "leads_all" in key
        ]
        
        for key in cache_keys_to_remove:
            if key in query_cache.cache:
                del query_cache.cache[key]

class StatsRepository(BaseRepository):
    """Репозиторий статистики"""
    
    @with_retry(max_attempts=2)
    async def get_bot_stats(self) -> Dict[str, Any]:
        """Получение статистики бота с кэшированием"""
        cache_key = "bot_stats"
        cached = query_cache.get(cache_key)
        if cached:
            return cached
        
        sql = """
            SELECT 
                (SELECT COUNT(*) FROM users) as total_users,
                (SELECT COUNT(*) FROM messages) as total_messages,
                (SELECT COUNT(*) FROM leads) as total_leads,
                (SELECT COUNT(*) FROM leads WHERE created_at >= datetime('now', '-1 day')) as leads_today,
                (SELECT COUNT(*) FROM leads WHERE created_at >= datetime('now', '-7 days')) as leads_week,
                (SELECT COUNT(*) FROM users WHERE last_activity >= datetime('now', '-1 day')) as active_users_today,
                (SELECT AVG(interest_score) FROM leads) as avg_lead_score
        """
        
        result = await self._execute_query("bot_stats", sql, (), True)
        
        if result:
            row = result[0]
            stats = {
                'total_users': row[0] or 0,
                'total_messages': row[1] or 0,
                'total_leads': row[2] or 0,
                'leads_today': row[3] or 0,
                'leads_week': row[4] or 0,
                'active_users_today': row[5] or 0,
                'avg_lead_score': row[6] or 0
            }
            
            # Кэшируем на 2 минуты (статистика часто обновляется)
            query_cache.cache[cache_key] = (stats, time.time())
            
            return stats
        
        return {}
    
    async def get_leads_stats(self) -> Dict[str, Any]:
        """Получение детальной статистики лидов"""
        cache_key = "leads_stats"
        cached = query_cache.get(cache_key)
        if cached:
            return cached
        
        sql = """
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
        """
        
        result = await self._execute_query("leads_stats", sql, (), True)
        
        if result:
            row = result[0]
            stats = {
                'total_leads': row[0] or 0,
                'new_leads': row[1] or 0,
                'contacted_leads': row[2] or 0,
                'converted_leads': row[3] or 0,
                'hot_leads': row[4] or 0,
                'warm_leads': row[5] or 0,
                'cold_leads': row[6] or 0,
                'avg_score': row[7] or 0
            }
            
            query_cache.set(cache_key, stats)
            return stats
        
        return {}

# === ФАСАД ДЛЯ ОПЕРАЦИЙ БД (SOLID - Facade Pattern) ===

class DatabaseFacade:
    """Фасад для всех операций с БД"""
    
    def __init__(self):
        self.users = UserRepository()
        self.leads = LeadRepository()
        self.stats = StatsRepository()
    
    async def initialize(self, db_path: str = "data/bot.db", pool_size: int = 10):
        """Инициализация фасада"""
        await init_connection_pool(db_path, pool_size)
        logger.info("Database facade initialized")
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Получение метрик производительности"""
        return db_monitor.get_metrics()
    
    def clear_cache(self):
        """Очистка кэша"""
        query_cache.clear()
        logger.info("Database cache cleared")
    
    async def health_check(self) -> bool:
        """Проверка здоровья БД"""
        try:
            await self.stats.get_bot_stats()
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

# Глобальный фасад
db_facade = DatabaseFacade()

# === ВЫСОКОУРОВНЕВЫЕ ФУНКЦИИ (для обратной совместимости) ===

async def init_database(db_path: str = "data/bot.db", pool_size: int = 10):
    """Инициализация базы данных"""
    await db_facade.initialize(db_path, pool_size)

async def create_user(user: User, db_path: str = "data/bot.db"):
    """Создание пользователя"""
    return await db_facade.users.create_or_update(user)

async def get_user_by_telegram_id(telegram_id: int, db_path: str = "data/bot.db") -> Optional[User]:
    """Получение пользователя по Telegram ID"""
    return await db_facade.users.get_by_telegram_id(telegram_id)

async def get_users(limit: int = 50, offset: int = 0, db_path: str = "data/bot.db") -> List[User]:
    """Получение пользователей"""
    return await db_facade.users.get_all(limit, offset)

async def update_user_activity(telegram_id: int, db_path: str = "data/bot.db"):
    """Обновление активности пользователя"""
    return await db_facade.users.update_activity(telegram_id)

async def create_lead(lead: Lead, db_path: str = "data/bot.db"):
    """Создание лида"""
    return await db_facade.leads.create(lead)

async def get_leads(limit: int = 50, offset: int = 0, db_path: str = "data/bot.db") -> List[Lead]:
    """Получение лидов"""
    return await db_facade.leads.get_all(limit, offset)

async def get_lead_by_telegram_id(telegram_id: int, db_path: str = "data/bot.db") -> Optional[Lead]:
    """Получение лида по Telegram ID"""
    return await db_facade.leads.get_by_telegram_id(telegram_id)

async def get_bot_stats(db_path: str = "data/bot.db") -> Dict[str, Any]:
    """Получение статистики бота"""
    return await db_facade.stats.get_bot_stats()

async def get_leads_stats(db_path: str = "data/bot.db") -> Dict[str, Any]:
    """Получение статистики лидов"""
    return await db_facade.stats.get_leads_stats()

# === BATCH ОПЕРАЦИИ ===

async def batch_create_leads(leads: List[Lead], db_path: str = "data/bot.db") -> bool:
    """Batch создание лидов"""
    return await db_facade.leads.batch_create(leads)

async def batch_update_user_activity(user_ids: List[int], db_path: str = "data/bot.db") -> bool:
    """Batch обновление активности пользователей"""
    return await db_facade.users.batch_update_activity(user_ids)

# === УТИЛИТЫ ===

def get_database_metrics() -> Dict[str, Any]:
    """Получение метрик производительности БД"""
    return db_facade.get_performance_metrics()

def clear_database_cache():
    """Очистка кэша БД"""
    db_facade.clear_cache()

async def database_health_check() -> bool:
    """Проверка здоровья БД"""
    return await db_facade.health_check()

# === ЗАГЛУШКИ ДЛЯ ОСТАЛЬНЫХ ФУНКЦИЙ (для совместимости) ===

async def save_message(message: Message, db_path: str = "data/bot.db"):
    """Сохранение сообщения (заглушка - нужна реализация)"""
    # TODO: Реализовать через MessageRepository
    logger.warning("save_message not implemented in optimized version")
    return True

async def get_messages(user_id: int = None, limit: int = 50, offset: int = 0, db_path: str = "data/bot.db") -> List[Message]:
    """Получение сообщений (заглушка - нужна реализация)"""
    # TODO: Реализовать через MessageRepository
    logger.warning("get_messages not implemented in optimized version")
    return []

async def get_active_channels(db_path: str = "data/bot.db") -> List[ParsedChannel]:
    """Получение активных каналов (заглушка - нужна реализация)"""
    # TODO: Реализовать через ChannelRepository
    logger.warning("get_active_channels not implemented in optimized version")
    return []

async def update_channel_stats(channel_identifier: str, message_id: int, 
                             leads_count: int = 0, db_path: str = "data/bot.db"):
    """Обновление статистики канала (заглушка - нужна реализация)"""
    # TODO: Реализовать через ChannelRepository
    logger.warning("update_channel_stats not implemented in optimized version")
    return True

async def create_or_update_channel(channel: ParsedChannel, db_path: str = "data/bot.db"):
    """Создание или обновление канала (заглушка - нужна реализация)"""
    # TODO: Реализовать через ChannelRepository
    logger.warning("create_or_update_channel not implemented in optimized version")
    return True

async def get_lead_by_id(lead_id: int, db_path: str = "data/bot.db") -> Optional[Lead]:
    """Получение лида по ID (заглушка - нужна реализация)"""
    # TODO: Реализовать через LeadRepository
    logger.warning("get_lead_by_id not implemented in optimized version")
    return None

async def update_lead_status(lead_id: int, status: str, notes: str = None, db_path: str = "data/bot.db"):
    """Обновление статуса лида (заглушка - нужна реализация)"""
    # TODO: Реализовать через LeadRepository
    logger.warning("update_lead_status not implemented in optimized version")
    return True

async def search_leads(query: str, db_path: str = "data/bot.db") -> List[Lead]:
    """Поиск лидов (заглушка - нужна реализация)"""
    # TODO: Реализовать через LeadRepository
    logger.warning("search_leads not implemented in optimized version")
    return []

async def get_setting(key: str, default_value: str = None, db_path: str = "data/bot.db") -> Optional[str]:
    """Получение настройки (заглушка - нужна реализация)"""
    # TODO: Реализовать через SettingsRepository
    logger.warning("get_setting not implemented in optimized version")
    return default_value

async def set_setting(key: str, value: str, description: str = None, db_path: str = "data/bot.db"):
    """Установка настройки (заглушка - нужна реализация)"""
    # TODO: Реализовать через SettingsRepository
    logger.warning("set_setting not implemented in optimized version")
    return True

async def increment_contact_attempts(lead_id: int, db_path: str = "data/bot.db"):
    """Увеличение счетчика контактов (заглушка - нужна реализация)"""
    # TODO: Реализовать через LeadRepository
    logger.warning("increment_contact_attempts not implemented in optimized version")
    return True

async def delete_lead(lead_id: int, db_path: str = "data/bot.db"):
    """Удаление лида (заглушка - нужна реализация)"""
    # TODO: Реализовать через LeadRepository
    logger.warning("delete_lead not implemented in optimized version")
    return True

async def create_message(message: Message, db_path: str = "data/bot.db"):
    """Создание сообщения (алиас для save_message)"""
    return await save_message(message, db_path)

async def update_bot_stats(db_path: str = "data/bot.db"):
    """Обновление статистики бота (заглушка - нужна реализация)"""
    # TODO: Реализовать через StatsRepository
    logger.warning("update_bot_stats not implemented in optimized version")
    return True

async def export_leads_to_csv(db_path: str = "data/bot.db") -> str:
    """Экспорт лидов в CSV (заглушка - нужна реализация)"""
    # TODO: Реализовать через LeadRepository
    logger.warning("export_leads_to_csv not implemented in optimized version")
    return ""
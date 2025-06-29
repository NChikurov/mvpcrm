"""
Оптимизированные вспомогательные функции для AI-CRM бота
Структурированное логирование, производительность, кэширование
"""

import asyncio
import logging
import re
import time
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable, Union
from functools import wraps, lru_cache
from dataclasses import dataclass, asdict
from abc import ABC, abstractmethod
from enum import Enum
import contextvars

# === СТРУКТУРИРОВАННОЕ ЛОГИРОВАНИЕ ===

class LogLevel(Enum):
    """Уровни логирования"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

@dataclass
class LogEvent:
    """Структурированное событие лога"""
    timestamp: str
    level: str
    logger_name: str
    message: str
    user_id: Optional[int] = None
    chat_id: Optional[int] = None
    event_type: Optional[str] = None
    duration_ms: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

class StructuredLogger:
    """Структурированный логгер с контекстом"""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.context_var = contextvars.ContextVar('log_context', default={})
    
    def set_context(self, **context):
        """Установка контекста логирования"""
        current = self.context_var.get({})
        current.update(context)
        self.context_var.set(current)
    
    def clear_context(self):
        """Очистка контекста"""
        self.context_var.set({})
    
    def _log(self, level: LogLevel, message: str, **kwargs):
        """Базовый метод логирования"""
        context = self.context_var.get({})
        
        log_event = LogEvent(
            timestamp=datetime.now().isoformat(),
            level=level.value,
            logger_name=self.logger.name,
            message=message,
            **context,
            **kwargs
        )
        
        # Логируем как JSON для парсинга, но читаемо для консоли
        if self.logger.isEnabledFor(getattr(logging, level.value)):
            structured_data = asdict(log_event)
            # Убираем None значения
            structured_data = {k: v for k, v in structured_data.items() if v is not None}
            
            # Форматированное сообщение для консоли
            if structured_data.get('event_type'):
                console_msg = f"[{structured_data['event_type']}] {message}"
            else:
                console_msg = message
            
            # Добавляем контекст если есть
            if structured_data.get('user_id'):
                console_msg += f" | user:{structured_data['user_id']}"
            if structured_data.get('duration_ms'):
                console_msg += f" | {structured_data['duration_ms']:.1f}ms"
            
            # Логируем в зависимости от уровня
            log_method = getattr(self.logger, level.value.lower())
            log_method(console_msg, extra={'structured': structured_data})
    
    def debug(self, message: str, **kwargs):
        self._log(LogLevel.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        self._log(LogLevel.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self._log(LogLevel.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self._log(LogLevel.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        self._log(LogLevel.CRITICAL, message, **kwargs)

# === ДЕКОРАТОРЫ ПРОИЗВОДИТЕЛЬНОСТИ ===

def measure_performance(event_type: str = None, logger_name: str = None):
    """Декоратор для измерения производительности функций"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            logger = StructuredLogger(logger_name or func.__module__)
            
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                
                logger.info(
                    f"Function {func.__name__} completed",
                    event_type=event_type or f"function_call",
                    duration_ms=duration_ms
                )
                
                return result
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                logger.error(
                    f"Function {func.__name__} failed: {e}",
                    event_type=event_type or f"function_error",
                    duration_ms=duration_ms,
                    error_type=type(e).__name__
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            logger = StructuredLogger(logger_name or func.__module__)
            
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                
                logger.info(
                    f"Function {func.__name__} completed",
                    event_type=event_type or f"function_call",
                    duration_ms=duration_ms
                )
                
                return result
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                logger.error(
                    f"Function {func.__name__} failed: {e}",
                    event_type=event_type or f"function_error",
                    duration_ms=duration_ms,
                    error_type=type(e).__name__
                )
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

def rate_limit(max_calls: int, period: int, logger_name: str = None):
    """Оптимизированный декоратор для ограничения частоты вызовов"""
    calls = []
    logger = StructuredLogger(logger_name or __name__)
    
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            now = time.time()
            
            # Удаляем старые вызовы (оптимизировано)
            cutoff = now - period
            while calls and calls[0] < cutoff:
                calls.pop(0)
            
            # Проверяем лимит
            if len(calls) >= max_calls:
                logger.warning(
                    f"Rate limit exceeded for {func.__name__}",
                    event_type="rate_limit_exceeded",
                    current_calls=len(calls),
                    max_calls=max_calls,
                    period=period
                )
                raise Exception(f"Rate limit exceeded: {max_calls} calls per {period} seconds")
            
            # Добавляем текущий вызов
            calls.append(now)
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator

# === КЭШИРОВАНИЕ ===

class TTLCache:
    """Простой TTL кэш для функций"""
    
    def __init__(self, ttl: int = 300, maxsize: int = 128):
        self.ttl = ttl
        self.maxsize = maxsize
        self.cache = {}
        self.timestamps = {}
    
    def get(self, key):
        """Получение значения из кэша"""
        if key not in self.cache:
            return None
        
        # Проверяем TTL
        if time.time() - self.timestamps[key] > self.ttl:
            del self.cache[key]
            del self.timestamps[key]
            return None
        
        return self.cache[key]
    
    def set(self, key, value):
        """Сохранение значения в кэш"""
        # Очищаем место если кэш переполнен
        if len(self.cache) >= self.maxsize:
            # Удаляем самый старый элемент
            oldest_key = min(self.timestamps, key=self.timestamps.get)
            del self.cache[oldest_key]
            del self.timestamps[oldest_key]
        
        self.cache[key] = value
        self.timestamps[key] = time.time()
    
    def clear(self):
        """Очистка кэша"""
        self.cache.clear()
        self.timestamps.clear()

def ttl_cache(ttl: int = 300, maxsize: int = 128):
    """Декоратор TTL кэширования для функций"""
    cache = TTLCache(ttl, maxsize)
    
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Создаем ключ кэша
            cache_key = str(args) + str(sorted(kwargs.items()))
            
            # Проверяем кэш
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Выполняем функцию и кэшируем результат
            result = await func(*args, **kwargs)
            cache.set(cache_key, result)
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            cache_key = str(args) + str(sorted(kwargs.items()))
            
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            result = func(*args, **kwargs)
            cache.set(cache_key, result)
            return result
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

# === ОПТИМИЗИРОВАННЫЕ БАЗОВЫЕ ФУНКЦИИ ===

@lru_cache(maxsize=256)
def format_datetime(dt: datetime, format_type: str = "short") -> str:
    """Кэшированное форматирование даты и времени"""
    if not dt:
        return "неизвестно"
    
    formats = {
        "short": "%d.%m %H:%M",
        "date": "%d.%m.%Y",
        "time": "%H:%M",
        "full": "%d.%m.%Y %H:%M:%S",
        "iso": "%Y-%m-%dT%H:%M:%S"
    }
    
    return dt.strftime(formats.get(format_type, formats["short"]))

def time_ago(dt: datetime) -> str:
    """Оптимизированное время относительно текущего момента"""
    if not dt:
        return "никогда"
    
    now = datetime.now()
    diff = now - dt
    
    # Используем более эффективную логику
    total_seconds = diff.total_seconds()
    
    if total_seconds < 60:
        return "только что"
    elif total_seconds < 3600:
        return f"{int(total_seconds // 60)} мин. назад"
    elif total_seconds < 86400:
        return f"{int(total_seconds // 3600)} ч. назад"
    elif total_seconds < 2592000:  # 30 дней
        return f"{diff.days} дн. назад"
    else:
        return f"{diff.days // 30} мес. назад"

@lru_cache(maxsize=512)
def clean_username(username: str) -> str:
    """Кэшированная очистка username"""
    if not username:
        return ""
    
    # Убираем @ если есть и оставляем только допустимые символы
    username = re.sub(r'^@', '', username)
    return re.sub(r'[^a-zA-Z0-9_]', '', username)

def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Оптимизированное обрезание текста"""
    if not text or len(text) <= max_length:
        return text or ""
    
    return text[:max_length - len(suffix)] + suffix

@lru_cache(maxsize=256)
def extract_numbers(text: str) -> tuple:
    """Кэшированное извлечение чисел из текста"""
    if not text:
        return tuple()
    
    numbers = re.findall(r'\d+', text)
    return tuple(int(num) for num in numbers)

def sanitize_html(text: str) -> str:
    """Быстрая очистка HTML"""
    if not text:
        return ""
    
    # Используем dict для замены (быстрее множественных replace)
    replacements = {'<': '&lt;', '>': '&gt;', '&': '&amp;'}
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    return text

# === ФОРМАТИРОВАНИЕ И ОТОБРАЖЕНИЕ ===

@lru_cache(maxsize=128)
def format_score_emoji(score: int) -> str:
    """Кэшированное получение эмодзи по скору"""
    if score >= 90:
        return "🔥"
    elif score >= 80:
        return "🌶️"
    elif score >= 70:
        return "⭐"
    elif score >= 50:
        return "👍"
    elif score >= 30:
        return "😐"
    else:
        return "❄️"

def format_user_info(user_data: Dict[str, Any], include_score: bool = True) -> str:
    """Оптимизированное форматирование информации о пользователе"""
    name = user_data.get('first_name', 'Пользователь')
    username = user_data.get('username')
    score = user_data.get('interest_score', 0)
    
    parts = []
    
    if include_score:
        parts.append(format_score_emoji(score))
    
    parts.append(name)
    
    if username:
        parts.append(f"(@{username})")
    
    if include_score:
        parts.append(f"- {score}/100")
    
    return " ".join(parts)

@lru_cache(maxsize=64)
def validate_telegram_username(username: str) -> bool:
    """Кэшированная проверка корректности Telegram username"""
    if not username:
        return False
    
    username = username.replace("@", "")
    return bool(re.match(r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$', username))

# === ОБРАБОТКА ДАННЫХ ===

def chunk_list(lst: List, chunk_size: int) -> List[List]:
    """Оптимизированное разбиение списка на чанки"""
    if chunk_size <= 0:
        return [lst]
    
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

def safe_int(value: Any, default: int = 0) -> int:
    """Быстрое безопасное преобразование в int"""
    if isinstance(value, int):
        return value
    
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def safe_float(value: Any, default: float = 0.0) -> float:
    """Быстрое безопасное преобразование в float"""
    if isinstance(value, (int, float)):
        return float(value)
    
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def calculate_conversion_rate(converted: int, total: int) -> float:
    """Быстрый расчет коэффициента конверсии"""
    return (converted / total) * 100 if total > 0 else 0.0

@lru_cache(maxsize=128)
def format_large_number(number: int) -> str:
    """Кэшированное форматирование больших чисел"""
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}М"
    elif number >= 1_000:
        return f"{number / 1_000:.1f}К"
    else:
        return str(number)

def create_progress_bar(current: int, total: int, length: int = 20) -> str:
    """Оптимизированный текстовый прогресс-бар"""
    if total == 0:
        return "░" * length
    
    progress = min(current / total, 1.0)  # Ограничиваем до 100%
    filled_length = int(length * progress)
    
    bar = "█" * filled_length + "░" * (length - filled_length)
    percentage = progress * 100
    
    return f"{bar} {percentage:.1f}%"

# === КОНТЕКСТ ПОЛЬЗОВАТЕЛЕЙ ===

def generate_user_context(messages: List[Dict[str, Any]], max_messages: int = 5) -> str:
    """Оптимизированная генерация контекста пользователя"""
    if not messages:
        return ""
    
    # Берем последние сообщения более эффективно
    recent_messages = messages[-max_messages:] if len(messages) > max_messages else messages
    
    context_parts = []
    for msg in recent_messages:
        text = msg.get('text', '')
        if text:
            # Обрезаем длинные сообщения
            text = truncate_text(text, 150)
            context_parts.append(f"- {text}")
    
    return "\n".join(context_parts)

# === ОБРАБОТКА КОМАНД ===

def parse_command_args(text: str) -> List[str]:
    """Оптимизированный парсинг аргументов команды"""
    if not text:
        return []
    
    parts = text.strip().split()
    return parts[1:] if len(parts) > 1 else []

@lru_cache(maxsize=256)
def escape_markdown(text: str) -> str:
    """Кэшированное экранирование специальных символов для Markdown"""
    if not text:
        return ""
    
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    
    return text

# === THROTTLING ===

class OptimizedMessageThrottler:
    """Оптимизированный ограничитель частоты отправки сообщений"""
    
    def __init__(self, max_messages: int = 30, period: int = 60):
        self.max_messages = max_messages
        self.period = period
        self.messages = []
        self.logger = StructuredLogger(__name__)
    
    async def can_send(self, user_id: int = None) -> bool:
        """Проверка можно ли отправить сообщение"""
        current_time = time.time()
        cutoff = current_time - self.period
        
        # Удаляем старые сообщения эффективно
        while self.messages and self.messages[0] < cutoff:
            self.messages.pop(0)
        
        can_send = len(self.messages) < self.max_messages
        
        if not can_send:
            self.logger.warning(
                "Message throttle limit reached",
                event_type="throttle_limit",
                user_id=user_id,
                current_count=len(self.messages),
                max_messages=self.max_messages
            )
        
        return can_send
    
    async def add_message(self, user_id: int = None):
        """Добавление отправленного сообщения"""
        self.messages.append(time.time())
        
        self.logger.debug(
            "Message added to throttle",
            event_type="throttle_add",
            user_id=user_id,
            current_count=len(self.messages)
        )

# === БЕЗОПАСНАЯ ОТПРАВКА СООБЩЕНИЙ ===

# Глобальный throttler
message_throttler = OptimizedMessageThrottler()

@measure_performance("message_send")
async def safe_send_message(bot, chat_id: int, text: str, **kwargs) -> bool:
    """Безопасная отправка сообщения с проверкой лимитов и логированием"""
    logger = StructuredLogger(__name__)
    
    try:
        if not await message_throttler.can_send(chat_id):
            logger.warning(
                "Message send blocked by throttler",
                event_type="message_blocked",
                chat_id=chat_id
            )
            return False
        
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        await message_throttler.add_message(chat_id)
        
        logger.info(
            "Message sent successfully",
            event_type="message_sent",
            chat_id=chat_id,
            message_length=len(text)
        )
        return True
        
    except Exception as e:
        logger.error(
            f"Failed to send message: {e}",
            event_type="message_send_error",
            chat_id=chat_id,
            error_type=type(e).__name__
        )
        return False

# === КОНФИГУРАЦИЯ ===

def get_config_value(config: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Оптимизированное получение значения из вложенной конфигурации"""
    try:
        value = config
        for key in path.split('.'):
            value = value[key]
        return value
    except (KeyError, TypeError):
        return default

# === BATCH OPERATIONS ===

async def batch_operation(items: List[Any], operation: Callable, batch_size: int = 10, 
                         delay: float = 0.1) -> List[Any]:
    """Пакетная обработка операций с контролем нагрузки"""
    logger = StructuredLogger(__name__)
    results = []
    
    logger.info(
        f"Starting batch operation",
        event_type="batch_start",
        total_items=len(items),
        batch_size=batch_size
    )
    
    for i, batch in enumerate(chunk_list(items, batch_size)):
        try:
            batch_results = await asyncio.gather(*[operation(item) for item in batch])
            results.extend(batch_results)
            
            logger.debug(
                f"Batch {i+1} completed",
                event_type="batch_progress",
                batch_number=i+1,
                items_processed=len(batch)
            )
            
            # Пауза между батчами
            if delay > 0:
                await asyncio.sleep(delay)
                
        except Exception as e:
            logger.error(
                f"Batch {i+1} failed: {e}",
                event_type="batch_error",
                batch_number=i+1,
                error_type=type(e).__name__
            )
            raise
    
    logger.info(
        f"Batch operation completed",
        event_type="batch_complete",
        total_processed=len(results)
    )
    
    return results

# === КОНСТАНТЫ ДЛЯ ЭМОДЗИ (ОПТИМИЗИРОВАНЫ) ===

# Используем константы для избежания повторных строк
EMOJI_SUCCESS = "✅"
EMOJI_ERROR = "❌"
EMOJI_WARNING = "⚠️"
EMOJI_INFO = "ℹ️"
EMOJI_FIRE = "🔥"
EMOJI_STATS = "📊"
EMOJI_USER = "👤"
EMOJI_USERS = "👥"
EMOJI_MESSAGE = "💬"
EMOJI_LEAD = "🎯"
EMOJI_CHANNEL = "📺"
EMOJI_ADMIN = "🔧"
EMOJI_SETTINGS = "⚙️"
EMOJI_BROADCAST = "📢"

# Группировка эмодзи для быстрого доступа
EMOJI_GROUPS = {
    'status': {
        'success': EMOJI_SUCCESS,
        'error': EMOJI_ERROR,
        'warning': EMOJI_WARNING,
        'info': EMOJI_INFO
    },
    'business': {
        'fire': EMOJI_FIRE,
        'stats': EMOJI_STATS,
        'lead': EMOJI_LEAD
    },
    'social': {
        'user': EMOJI_USER,
        'users': EMOJI_USERS,
        'message': EMOJI_MESSAGE,
        'channel': EMOJI_CHANNEL
    }
}

def get_emoji(group: str, name: str) -> str:
    """Быстрое получение эмодзи по группе и имени"""
    return EMOJI_GROUPS.get(group, {}).get(name, "")

# === УТИЛИТЫ ДЛЯ ПРОИЗВОДИТЕЛЬНОСТИ ===

class PerformanceMonitor:
    """Монитор производительности для критических функций"""
    
    def __init__(self):
        self.metrics = {}
        self.logger = StructuredLogger(__name__)
    
    def record_execution(self, function_name: str, duration: float, success: bool):
        """Запись выполнения функции"""
        if function_name not in self.metrics:
            self.metrics[function_name] = {
                'total_calls': 0,
                'successful_calls': 0,
                'failed_calls': 0,
                'total_time': 0.0,
                'avg_time': 0.0,
                'max_time': 0.0,
                'min_time': float('inf')
            }
        
        metric = self.metrics[function_name]
        metric['total_calls'] += 1
        metric['total_time'] += duration
        metric['avg_time'] = metric['total_time'] / metric['total_calls']
        metric['max_time'] = max(metric['max_time'], duration)
        metric['min_time'] = min(metric['min_time'], duration)
        
        if success:
            metric['successful_calls'] += 1
        else:
            metric['failed_calls'] += 1
        
        # Логируем медленные операции
        if duration > 5.0:  # Более 5 секунд
            self.logger.warning(
                f"Slow operation detected: {function_name}",
                event_type="slow_operation",
                duration_ms=duration * 1000,
                function_name=function_name
            )
    
    def get_metrics(self) -> Dict[str, Any]:
        """Получение метрик производительности"""
        return self.metrics.copy()
    
    def reset_metrics(self):
        """Сброс метрик"""
        self.metrics.clear()

# Глобальный монитор производительности
performance_monitor = PerformanceMonitor()

def monitor_performance(func):
    """Декоратор для мониторинга производительности"""
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start_time = time.time()
        success = True
        
        try:
            result = await func(*args, **kwargs)
            return result
        except Exception as e:
            success = False
            raise
        finally:
            duration = time.time() - start_time
            performance_monitor.record_execution(func.__name__, duration, success)
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start_time = time.time()
        success = True
        
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            success = False
            raise
        finally:
            duration = time.time() - start_time
            performance_monitor.record_execution(func.__name__, duration, success)
    
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper
"""
Вспомогательные функции для AI-CRM бота
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from functools import wraps

logger = logging.getLogger(__name__)

def format_datetime(dt: datetime, format_type: str = "short") -> str:
    """Форматирование даты и времени"""
    if not dt:
        return "неизвестно"
    
    if format_type == "short":
        return dt.strftime("%d.%m %H:%M")
    elif format_type == "date":
        return dt.strftime("%d.%m.%Y")
    elif format_type == "time":
        return dt.strftime("%H:%M")
    elif format_type == "full":
        return dt.strftime("%d.%m.%Y %H:%M:%S")
    else:
        return dt.strftime("%d.%m.%Y %H:%M")

def time_ago(dt: datetime) -> str:
    """Показать время относительно текущего момента"""
    if not dt:
        return "никогда"
    
    now = datetime.now()
    diff = now - dt
    
    if diff.days > 30:
        return f"{diff.days // 30} мес. назад"
    elif diff.days > 0:
        return f"{diff.days} дн. назад"
    elif diff.seconds > 3600:
        return f"{diff.seconds // 3600} ч. назад"
    elif diff.seconds > 60:
        return f"{diff.seconds // 60} мин. назад"
    else:
        return "только что"

def clean_username(username: str) -> str:
    """Очистка username от лишних символов"""
    if not username:
        return ""
    
    # Убираем @ если есть
    username = username.replace("@", "")
    
    # Оставляем только буквы, цифры и подчеркивания
    username = re.sub(r'[^a-zA-Z0-9_]', '', username)
    
    return username

def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Обрезание текста до определенной длины"""
    if not text:
        return ""
    
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix

def extract_numbers(text: str) -> List[int]:
    """Извлечение чисел из текста"""
    numbers = re.findall(r'\d+', text)
    return [int(num) for num in numbers]

def sanitize_html(text: str) -> str:
    """Очистка текста от HTML тегов для безопасной отправки"""
    if not text:
        return ""
    
    # Заменяем потенциально опасные символы
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace("&", "&amp;")
    
    return text

def format_score_emoji(score: int) -> str:
    """Получение эмодзи по скору заинтересованности"""
    if score >= 90:
        return "🔥"  # Очень горячий лид
    elif score >= 80:
        return "🌶️"  # Горячий лид
    elif score >= 70:
        return "⭐"  # Заинтересованный
    elif score >= 50:
        return "👍"  # Потенциально заинтересованный
    elif score >= 30:
        return "😐"  # Нейтральный
    else:
        return "❄️"  # Холодный

def format_user_info(user_data: Dict[str, Any]) -> str:
    """Форматирование информации о пользователе"""
    name = user_data.get('first_name', 'Пользователь')
    username = user_data.get('username')
    score = user_data.get('interest_score', 0)
    
    info = f"{format_score_emoji(score)} {name}"
    
    if username:
        info += f" (@{username})"
    
    info += f" - {score}/100"
    
    return info

def validate_telegram_username(username: str) -> bool:
    """Проверка корректности Telegram username"""
    if not username:
        return False
    
    # Убираем @ если есть
    username = username.replace("@", "")
    
    # Проверяем регулярным выражением
    pattern = r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$'
    return bool(re.match(pattern, username))

def rate_limit(max_calls: int, period: int):
    """Декоратор для ограничения частоты вызовов функции"""
    calls = []
    
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            now = datetime.now()
            
            # Удаляем старые вызовы
            calls[:] = [call_time for call_time in calls if now - call_time < timedelta(seconds=period)]
            
            # Проверяем лимит
            if len(calls) >= max_calls:
                logger.warning(f"Rate limit exceeded for {func.__name__}")
                raise Exception(f"Rate limit exceeded: {max_calls} calls per {period} seconds")
            
            # Добавляем текущий вызов
            calls.append(now)
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator

async def retry_on_error(func, max_retries: int = 3, delay: float = 1.0):
    """Повторение функции при ошибке"""
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed after {max_retries} attempts: {e}")
                raise
            
            logger.warning(f"Attempt {attempt + 1} failed: {e}, retrying in {delay}s")
            await asyncio.sleep(delay)
            delay *= 2  # Экспоненциальная задержка

def chunk_list(lst: List, chunk_size: int) -> List[List]:
    """Разбиение списка на чанки"""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

def safe_int(value: Any, default: int = 0) -> int:
    """Безопасное преобразование в int"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def safe_float(value: Any, default: float = 0.0) -> float:
    """Безопасное преобразование в float"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def generate_user_context(messages: List[Dict[str, Any]], max_messages: int = 5) -> str:
    """Генерация контекста для пользователя из его сообщений"""
    if not messages:
        return ""
    
    # Берем последние сообщения
    recent_messages = messages[-max_messages:]
    
    context_parts = []
    for msg in recent_messages:
        text = msg.get('text', '')
        if text:
            # Обрезаем длинные сообщения
            text = truncate_text(text, 150)
            context_parts.append(f"- {text}")
    
    return "\n".join(context_parts)

def calculate_conversion_rate(converted: int, total: int) -> float:
    """Расчет коэффициента конверсии"""
    if total == 0:
        return 0.0
    return (converted / total) * 100

def format_large_number(number: int) -> str:
    """Форматирование больших чисел"""
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}М"
    elif number >= 1_000:
        return f"{number / 1_000:.1f}К"
    else:
        return str(number)

def create_progress_bar(current: int, total: int, length: int = 20) -> str:
    """Создание текстового прогресс-бара"""
    if total == 0:
        return "░" * length
    
    progress = current / total
    filled_length = int(length * progress)
    
    bar = "█" * filled_length + "░" * (length - filled_length)
    percentage = progress * 100
    
    return f"{bar} {percentage:.1f}%"

def parse_command_args(text: str) -> List[str]:
    """Парсинг аргументов команды"""
    if not text:
        return []
    
    # Убираем команду (первое слово)
    parts = text.split()
    if not parts:
        return []
    
    return parts[1:]  # Возвращаем все кроме первого слова

def escape_markdown(text: str) -> str:
    """Экранирование специальных символов для Markdown"""
    if not text:
        return ""
    
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    
    return text

class MessageThrottler:
    """Ограничитель частоты отправки сообщений"""
    
    def __init__(self, max_messages: int = 30, period: int = 60):
        self.max_messages = max_messages
        self.period = period
        self.messages = []
    
    async def can_send(self) -> bool:
        """Проверка можно ли отправить сообщение"""
        now = datetime.now()
        
        # Удаляем старые сообщения
        self.messages = [
            msg_time for msg_time in self.messages 
            if now - msg_time < timedelta(seconds=self.period)
        ]
        
        return len(self.messages) < self.max_messages
    
    async def add_message(self):
        """Добавление отправленного сообщения"""
        self.messages.append(datetime.now())

# Глобальный throttler для сообщений
message_throttler = MessageThrottler()

async def safe_send_message(bot, chat_id: int, text: str, **kwargs) -> bool:
    """Безопасная отправка сообщения с проверкой лимитов"""
    try:
        if not await message_throttler.can_send():
            logger.warning("Message rate limit exceeded")
            return False
        
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        await message_throttler.add_message()
        return True
        
    except Exception as e:
        logger.error(f"Failed to send message to {chat_id}: {e}")
        return False

def get_config_value(config: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Получение значения из вложенной конфигурации по пути"""
    try:
        keys = path.split('.')
        value = config
        
        for key in keys:
            value = value[key]
        
        return value
    except (KeyError, TypeError):
        return default

# Константы для форматирования
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

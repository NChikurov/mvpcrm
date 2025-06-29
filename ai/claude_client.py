"""
Оптимизированный клиент для работы с Claude API
Кэширование, retry механизмы, circuit breaker, метрики производительности
"""

import asyncio
import logging
import time
import hashlib
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Protocol
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from enum import Enum
from collections import defaultdict
import anthropic

logger = logging.getLogger(__name__)

# === КОНФИГУРАЦИИ И НАСТРОЙКИ ===

@dataclass
class CacheConfig:
    """Конфигурация кэша"""
    enabled: bool = True
    ttl_seconds: int = 1800  # 30 минут
    max_size: int = 1000
    cleanup_interval: int = 300  # 5 минут

@dataclass
class RetryConfig:
    """Конфигурация retry механизма"""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True

@dataclass
class CircuitBreakerConfig:
    """Конфигурация circuit breaker"""
    failure_threshold: int = 5
    success_threshold: int = 3
    timeout_seconds: int = 60

class CircuitState(Enum):
    """Состояния circuit breaker"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

# === ПРОТОКОЛЫ И ИНТЕРФЕЙСЫ ===

class AIAnalyzer(Protocol):
    """Протокол для AI анализаторов"""
    async def analyze_interest(self, message: str, context: List[str]) -> int: ...
    async def generate_response(self, message: str, context: List[str], interest_score: int) -> str: ...
    async def analyze_potential_lead(self, message: str, channel: str) -> int: ...

class CacheStorage(Protocol):
    """Протокол для хранилища кэша"""
    async def get(self, key: str) -> Optional[Any]: ...
    async def set(self, key: str, value: Any, ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def clear(self) -> None: ...

# === КЭШИРОВАНИЕ (SOLID - Single Responsibility) ===

@dataclass
class CacheEntry:
    """Запись кэша"""
    value: Any
    created_at: float
    ttl: int
    access_count: int = 0
    last_access: float = field(default_factory=time.time)

class InMemoryCache:
    """Оптимизированный in-memory кэш"""
    
    def __init__(self, config: CacheConfig):
        self.config = config
        self._storage: Dict[str, CacheEntry] = {}
        self._access_times: Dict[str, float] = {}
        self._last_cleanup = time.time()
        
        # Метрики
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'evictions': 0,
            'size': 0
        }
    
    async def get(self, key: str) -> Optional[Any]:
        """Получение значения из кэша"""
        if not self.config.enabled:
            return None
        
        await self._maybe_cleanup()
        
        entry = self._storage.get(key)
        if not entry:
            self.stats['misses'] += 1
            return None
        
        # Проверяем TTL
        if time.time() - entry.created_at > entry.ttl:
            await self.delete(key)
            self.stats['misses'] += 1
            return None
        
        # Обновляем статистику доступа
        entry.access_count += 1
        entry.last_access = time.time()
        self._access_times[key] = time.time()
        
        self.stats['hits'] += 1
        return entry.value
    
    async def set(self, key: str, value: Any, ttl: int) -> None:
        """Сохранение значения в кэш"""
        if not self.config.enabled:
            return
        
        # Проверяем размер кэша
        if len(self._storage) >= self.config.max_size:
            await self._evict_lru()
        
        entry = CacheEntry(
            value=value,
            created_at=time.time(),
            ttl=ttl
        )
        
        self._storage[key] = entry
        self._access_times[key] = time.time()
        self.stats['sets'] += 1
        self.stats['size'] = len(self._storage)
    
    async def delete(self, key: str) -> None:
        """Удаление из кэша"""
        if key in self._storage:
            del self._storage[key]
            self._access_times.pop(key, None)
            self.stats['size'] = len(self._storage)
    
    async def clear(self) -> None:
        """Очистка кэша"""
        self._storage.clear()
        self._access_times.clear()
        self.stats['size'] = 0
    
    async def _evict_lru(self):
        """Удаление наименее используемых записей"""
        if not self._access_times:
            return
        
        # Сортируем по времени последнего доступа
        sorted_keys = sorted(self._access_times.items(), key=lambda x: x[1])
        
        # Удаляем 20% записей
        evict_count = max(1, len(sorted_keys) // 5)
        for key, _ in sorted_keys[:evict_count]:
            await self.delete(key)
            self.stats['evictions'] += 1
    
    async def _maybe_cleanup(self):
        """Периодическая очистка устаревших записей"""
        current_time = time.time()
        
        if current_time - self._last_cleanup < self.config.cleanup_interval:
            return
        
        expired_keys = []
        for key, entry in self._storage.items():
            if current_time - entry.created_at > entry.ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            await self.delete(key)
        
        self._last_cleanup = current_time
        
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики кэша"""
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = (self.stats['hits'] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            **self.stats,
            'hit_rate': hit_rate,
            'total_requests': total_requests
        }

# === CIRCUIT BREAKER (SOLID - Open/Closed Principle) ===

class CircuitBreaker:
    """Circuit breaker для защиты от сбоев API"""
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0
        
        # Метрики
        self.stats = {
            'total_calls': 0,
            'successful_calls': 0,
            'failed_calls': 0,
            'circuit_opens': 0,
            'state_changes': 0
        }
    
    async def call(self, func, *args, **kwargs):
        """Выполнение функции через circuit breaker"""
        self.stats['total_calls'] += 1
        
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.config.timeout_seconds:
                self._transition_to_half_open()
            else:
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise
    
    async def _on_success(self):
        """Обработка успешного вызова"""
        self.stats['successful_calls'] += 1
        
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self._transition_to_closed()
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0
    
    async def _on_failure(self):
        """Обработка неудачного вызова"""
        self.stats['failed_calls'] += 1
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.CLOSED:
            if self.failure_count >= self.config.failure_threshold:
                self._transition_to_open()
        elif self.state == CircuitState.HALF_OPEN:
            self._transition_to_open()
    
    def _transition_to_open(self):
        """Переход в состояние OPEN"""
        self.state = CircuitState.OPEN
        self.stats['circuit_opens'] += 1
        self.stats['state_changes'] += 1
        logger.warning("Circuit breaker opened due to failures")
    
    def _transition_to_half_open(self):
        """Переход в состояние HALF_OPEN"""
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        self.stats['state_changes'] += 1
        logger.info("Circuit breaker transitioned to HALF_OPEN")
    
    def _transition_to_closed(self):
        """Переход в состояние CLOSED"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.stats['state_changes'] += 1
        logger.info("Circuit breaker closed after successful recovery")

# === RETRY МЕХАНИЗМ (SOLID - Strategy Pattern) ===

class RetryStrategy(ABC):
    """Базовая стратегия повторов"""
    
    @abstractmethod
    async def execute(self, func, *args, **kwargs):
        pass

class ExponentialBackoffRetry(RetryStrategy):
    """Стратегия экспоненциального отката"""
    
    def __init__(self, config: RetryConfig):
        self.config = config
    
    async def execute(self, func, *args, **kwargs):
        """Выполнение с экспоненциальным откатом"""
        last_exception = None
        
        for attempt in range(self.config.max_attempts):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                
                if attempt == self.config.max_attempts - 1:
                    break
                
                delay = min(
                    self.config.base_delay * (self.config.exponential_base ** attempt),
                    self.config.max_delay
                )
                
                # Добавляем jitter для избежания thundering herd
                if self.config.jitter:
                    import random
                    delay *= (0.5 + random.random() * 0.5)
                
                logger.warning(f"Attempt {attempt + 1} failed: {e}, retrying in {delay:.2f}s")
                await asyncio.sleep(delay)
        
        raise last_exception

# === ОПТИМИЗИРОВАННЫЙ CLAUDE CLIENT ===

class OptimizedClaudeClient:
    """Оптимизированный клиент Claude с кэшированием и защитными механизмами"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.claude_config = config.get('claude', {})
        self.prompts = config.get('prompts', {})
        
        # Инициализация компонентов
        self._init_client()
        self._init_cache()
        self._init_protective_mechanisms()
        
        # Метрики производительности
        self.metrics = {
            'api_calls': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'errors': 0,
            'avg_response_time': 0.0,
            'total_response_time': 0.0
        }
        
        # Статистика по типам запросов
        self.request_stats = defaultdict(lambda: {'count': 0, 'avg_time': 0.0, 'errors': 0})
    
    def _init_client(self):
        """Инициализация Claude клиента"""
        api_key = self.claude_config.get('api_key')
        if not api_key or api_key == 'your_claude_api_key_here':
            logger.warning("Claude API key not set, using simple mode")
            self.client = None
        else:
            try:
                self.client = anthropic.AsyncAnthropic(api_key=api_key)
                logger.info("Claude API client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Claude API: {e}")
                self.client = None
        
        # Настройки
        self.model = self.claude_config.get('model', 'claude-3-5-sonnet-20241022')
        self.max_tokens = self.claude_config.get('max_tokens', 1000)
        self.temperature = self.claude_config.get('temperature', 0.7)
    
    def _init_cache(self):
        """Инициализация кэша"""
        cache_config = CacheConfig(
            enabled=True,
            ttl_seconds=1800,  # 30 минут
            max_size=1000
        )
        self.cache = InMemoryCache(cache_config)
    
    def _init_protective_mechanisms(self):
        """Инициализация защитных механизмов"""
        # Circuit breaker
        circuit_config = CircuitBreakerConfig(
            failure_threshold=5,
            success_threshold=3,
            timeout_seconds=60
        )
        self.circuit_breaker = CircuitBreaker(circuit_config)
        
        # Retry strategy
        retry_config = RetryConfig(
            max_attempts=3,
            base_delay=1.0,
            max_delay=30.0
        )
        self.retry_strategy = ExponentialBackoffRetry(retry_config)
    
    def _generate_cache_key(self, method: str, *args, **kwargs) -> str:
        """Генерация ключа кэша"""
        key_data = f"{method}:{str(args)}:{str(sorted(kwargs.items()))}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    async def _make_request(self, prompt: str, max_tokens: Optional[int] = None,
                           request_type: str = "general") -> str:
        """Базовый запрос к Claude API с защитными механизмами"""
        if not self.client:
            return ""
        
        start_time = time.time()
        
        try:
            # Проверяем кэш
            cache_key = self._generate_cache_key("claude_request", prompt, max_tokens)
            cached_result = await self.cache.get(cache_key)
            
            if cached_result:
                self.metrics['cache_hits'] += 1
                return cached_result
            
            self.metrics['cache_misses'] += 1
            
            # Выполняем запрос через защитные механизмы
            async def api_call():
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens or self.max_tokens,
                    temperature=self.temperature,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.content[0].text if response.content else ""
            
            # Используем circuit breaker и retry
            result = await self.circuit_breaker.call(
                self.retry_strategy.execute, api_call
            )
            
            # Кэшируем результат
            await self.cache.set(cache_key, result, ttl=1800)
            
            # Обновляем метрики
            response_time = time.time() - start_time
            self._update_metrics(request_type, response_time, success=True)
            
            return result.strip()
            
        except Exception as e:
            response_time = time.time() - start_time
            self._update_metrics(request_type, response_time, success=False)
            logger.error(f"Claude API request failed: {e}")
            return ""
    
    def _update_metrics(self, request_type: str, response_time: float, success: bool):
        """Обновление метрик производительности"""
        self.metrics['api_calls'] += 1
        self.metrics['total_response_time'] += response_time
        self.metrics['avg_response_time'] = self.metrics['total_response_time'] / self.metrics['api_calls']
        
        if not success:
            self.metrics['errors'] += 1
        
        # Статистика по типам запросов
        stats = self.request_stats[request_type]
        stats['count'] += 1
        stats['avg_time'] = (stats['avg_time'] * (stats['count'] - 1) + response_time) / stats['count']
        
        if not success:
            stats['errors'] += 1
    
    async def analyze_user_interest(self, message: str, context: List[str] = None) -> int:
        """Анализ заинтересованности пользователя с кэшированием"""
        if self.client:
            try:
                context_str = ""
                if context:
                    context_str = "Предыдущие сообщения:\n" + "\n".join(context[-3:])
                
                prompt = self.prompts.get('analyze_interest', '').format(
                    message=message,
                    context=context_str
                )
                
                if prompt:
                    response = await self._make_request(prompt, max_tokens=10, request_type="interest_analysis")
                    
                    # Извлекаем число из ответа
                    score_text = ''.join(filter(str.isdigit, response))
                    if score_text:
                        score = int(score_text)
                        return max(0, min(100, score))
            except Exception as e:
                logger.error(f"Interest analysis error: {e}")
        
        # Fallback на простой анализ
        return self._analyze_interest_simple(message)
    
    async def generate_response(self, message: str, context: List[str] = None, 
                              interest_score: int = 0) -> str:
        """Генерация ответа с кэшированием"""
        if self.client:
            try:
                context_str = ""
                if context:
                    context_str = "Контекст беседы:\n" + "\n".join(context[-5:])
                
                prompt = self.prompts.get('generate_response', '').format(
                    message=message,
                    context=context_str,
                    interest_score=interest_score
                )
                
                if prompt:
                    response = await self._make_request(
                        prompt, 
                        max_tokens=self.max_tokens,
                        request_type="response_generation"
                    )
                    if response:
                        return response
            except Exception as e:
                logger.error(f"Response generation error: {e}")
        
        # Fallback на простую генерацию
        return self._generate_response_simple(message, interest_score)
    
    async def analyze_potential_lead(self, message: str, channel: str) -> int:
        """Анализ потенциального клиента с кэшированием"""
        if self.client:
            try:
                prompt = self.prompts.get('analyze_lead', '').format(
                    message=message,
                    channel=channel
                )
                
                if prompt:
                    response = await self._make_request(
                        prompt, 
                        max_tokens=10,
                        request_type="lead_analysis"
                    )
                    
                    score_text = ''.join(filter(str.isdigit, response))
                    if score_text:
                        score = int(score_text)
                        return max(0, min(100, score))
            except Exception as e:
                logger.error(f"Lead analysis error: {e}")
        
        # Fallback на простой анализ
        return self._analyze_lead_simple(message)
    
    def _analyze_interest_simple(self, message: str) -> int:
        """Простой анализ заинтересованности без AI"""
        message_lower = message.lower()
        
        high_interest_words = [
            'купить', 'заказать', 'цена', 'стоимость', 'сколько стоит', 
            'где купить', 'как заказать', 'хочу купить', 'нужно купить',
            'интересует цена', 'готов купить', 'хочу заказать'
        ]
        
        medium_interest_words = [
            'интересно', 'подойдет', 'расскажите', 'подробнее', 
            'возможно', 'рассмотрю', 'думаю', 'узнать больше',
            'как работает', 'что включено', 'условия'
        ]
        
        for word in high_interest_words:
            if word in message_lower:
                return 85
        
        for word in medium_interest_words:
            if word in message_lower:
                return 60
        
        if '?' in message:
            return 50
        
        return 40
    
    def _generate_response_simple(self, message: str, interest_score: int) -> str:
        """Простая генерация ответа без AI"""
        if interest_score >= 70:
            return "Отлично! Наш специалист свяжется с вами для обсуждения деталей!"
        elif interest_score >= 40:
            return "Спасибо за интерес! Готов ответить на ваши вопросы."
        else:
            return "Спасибо за сообщение! Обращайтесь, если понадобится помощь."
    
    def _analyze_lead_simple(self, message: str) -> int:
        """Простой анализ лида без AI"""
        message_lower = message.lower()
        
        business_words = [
            'crm', 'автоматизация', 'бизнес', 'продажи', 'клиенты', 
            'заявки', 'система', 'telegram bot', 'бот', 'интеграция'
        ]
        
        score = 40
        for word in business_words:
            if word in message_lower:
                score += 20
                break
        
        if any(kw in message_lower for kw in ['купить', 'заказать', 'цена']):
            score += 30
        
        return min(100, score)
    
    async def health_check(self) -> bool:
        """Проверка работоспособности с учетом circuit breaker"""
        if not self.client:
            return True
        
        try:
            if self.circuit_breaker.state == CircuitState.OPEN:
                return False
            
            response = await self._make_request(
                "Скажи 'работаю'", 
                max_tokens=10,
                request_type="health_check"
            )
            return bool(response and len(response) > 0)
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Получение расширенной статистики использования"""
        cache_stats = self.cache.get_stats()
        circuit_stats = self.circuit_breaker.stats
        
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "api_available": bool(self.client),
            "status": "ai_mode" if self.client else "simple_mode",
            "metrics": self.metrics,
            "cache": cache_stats,
            "circuit_breaker": {
                **circuit_stats,
                "state": self.circuit_breaker.state.value
            },
            "request_types": dict(self.request_stats)
        }
    
    async def clear_cache(self):
        """Очистка кэша"""
        await self.cache.clear()
        logger.info("Cache cleared")
    
    async def optimize_cache(self):
        """Оптимизация кэша"""
        await self.cache._maybe_cleanup()
        logger.info("Cache optimized")

# === ГЛОБАЛЬНЫЙ КЛИЕНТ (Singleton Pattern) ===

claude_client: Optional[OptimizedClaudeClient] = None

def init_claude_client(config: Dict[str, Any]) -> OptimizedClaudeClient:
    """Инициализация глобального клиента Claude"""
    global claude_client
    try:
        claude_client = OptimizedClaudeClient(config)
        logger.info("Optimized Claude client initialized")
        return claude_client
    except Exception as e:
        logger.error(f"Failed to initialize optimized Claude client: {e}")
        claude_client = OptimizedClaudeClient({'claude': {'api_key': ''}, 'prompts': {}})
        return claude_client

def get_claude_client() -> Optional[OptimizedClaudeClient]:
    """Получение глобального клиента Claude"""
    global claude_client
    if claude_client is None:
        claude_client = OptimizedClaudeClient({'claude': {'api_key': ''}, 'prompts': {}})
    return claude_client
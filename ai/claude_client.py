"""
Клиент для работы с Claude API
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any
import anthropic

logger = logging.getLogger(__name__)

class ClaudeClient:
    """Клиент для работы с Claude API"""
    
    def __init__(self, config: Dict[str, Any]):
        """Инициализация клиента"""
        self.config = config
        self.claude_config = config.get('claude', {})
        self.prompts = config.get('prompts', {})
        
        # Инициализация Anthropic клиента
        self.client = anthropic.AsyncAnthropic(
            api_key=self.claude_config.get('api_key')
        )
        
        # Настройки по умолчанию
        self.model = self.claude_config.get('model', 'claude-3-sonnet-20240229')
        self.max_tokens = self.claude_config.get('max_tokens', 1000)
        self.temperature = self.claude_config.get('temperature', 0.7)
        
        logger.info("Claude клиент инициализирован")

    async def _make_request(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Базовый запрос к Claude API"""
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens or self.max_tokens,
                temperature=self.temperature,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            content = response.content[0].text if response.content else ""
            return content.strip()
            
        except anthropic.APIError as e:
            logger.error(f"Ошибка Claude API: {e}")
            return ""
        except Exception as e:
            logger.error(f"Неожиданная ошибка при запросе к Claude: {e}")
            return ""

    async def analyze_user_interest(self, message: str, context: List[str] = None) -> int:
        """
        Анализ заинтересованности пользователя
        Возвращает скор от 0 до 100
        """
        context_str = ""
        if context:
            context_str = "Предыдущие сообщения:\n" + "\n".join(context[-3:])
        
        prompt = self.prompts.get('analyze_interest', '').format(
            message=message,
            context=context_str
        )
        
        if not prompt:
            logger.warning("Промпт analyze_interest не настроен")
            return 0
        
        try:
            response = await self._make_request(prompt, max_tokens=10)
            
            # Извлекаем число из ответа
            score_text = ''.join(filter(str.isdigit, response))
            if score_text:
                score = int(score_text)
                return max(0, min(100, score))  # Ограничиваем 0-100
            
        except Exception as e:
            logger.error(f"Ошибка анализа заинтересованности: {e}")
        
        return 0

    async def generate_response(self, message: str, context: List[str] = None, interest_score: int = 0) -> str:
        """
        Генерация ответа пользователю
        """
        context_str = ""
        if context:
            context_str = "Контекст беседы:\n" + "\n".join(context[-5:])
        
        prompt = self.prompts.get('generate_response', '').format(
            message=message,
            context=context_str,
            interest_score=interest_score
        )
        
        if not prompt:
            logger.warning("Промпт generate_response не настроен")
            return "Спасибо за ваше сообщение! Мы обязательно ответим."
        
        try:
            response = await self._make_request(prompt, max_tokens=self.max_tokens)
            
            if response:
                return response
            else:
                return "Извините, не могу сформулировать ответ. Попробуйте еще раз."
                
        except Exception as e:
            logger.error(f"Ошибка генерации ответа: {e}")
            return "Произошла ошибка. Попробуйте позже."

    async def analyze_potential_lead(self, message: str, channel: str) -> int:
        """
        Анализ потенциального клиента из канала
        Возвращает скор от 0 до 100
        """
        prompt = self.prompts.get('analyze_lead', '').format(
            message=message,
            channel=channel
        )
        
        if not prompt:
            logger.warning("Промпт analyze_lead не настроен")
            return 0
        
        try:
            response = await self._make_request(prompt, max_tokens=10)
            
            # Извлекаем число из ответа
            score_text = ''.join(filter(str.isdigit, response))
            if score_text:
                score = int(score_text)
                return max(0, min(100, score))  # Ограничиваем 0-100
            
        except Exception as e:
            logger.error(f"Ошибка анализа лида: {e}")
        
        return 0

    async def batch_analyze_messages(self, messages: List[Dict[str, str]]) -> List[int]:
        """
        Пакетный анализ сообщений для оптимизации
        """
        tasks = []
        for msg_data in messages:
            if msg_data.get('type') == 'user':
                task = self.analyze_user_interest(
                    msg_data['text'], 
                    msg_data.get('context', [])
                )
            elif msg_data.get('type') == 'lead':
                task = self.analyze_potential_lead(
                    msg_data['text'],
                    msg_data.get('channel', '')
                )
            else:
                task = asyncio.create_task(asyncio.coroutine(lambda: 0)())
            
            tasks.append(task)
        
        # Выполняем все запросы параллельно с ограничением
        results = []
        batch_size = 5  # Ограничиваем количество одновременных запросов
        
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i + batch_size]
            batch_results = await asyncio.gather(*batch, return_exceptions=True)
            
            for result in batch_results:
                if isinstance(result, Exception):
                    logger.error(f"Ошибка в пакетном анализе: {result}")
                    results.append(0)
                else:
                    results.append(result)
        
        return results

    async def health_check(self) -> bool:
        """Проверка работоспособности Claude API"""
        try:
            response = await self._make_request("Привет! Ответь одним словом: работаю", max_tokens=10)
            return bool(response and len(response) > 0)
        except Exception as e:
            logger.error(f"Проверка здоровья Claude API failed: {e}")
            return False

    def update_prompts(self, new_prompts: Dict[str, str]):
        """Обновление промптов без перезапуска"""
        self.prompts.update(new_prompts)
        logger.info("Промпты обновлены")

    def get_usage_stats(self) -> Dict[str, Any]:
        """Получение статистики использования (заглушка)"""
        # В реальной реализации здесь можно отслеживать статистику
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "status": "active"
        }

# Глобальный экземпляр клиента
claude_client: Optional[ClaudeClient] = None

def init_claude_client(config: Dict[str, Any]) -> ClaudeClient:
    """Инициализация глобального клиента Claude"""
    global claude_client
    claude_client = ClaudeClient(config)
    return claude_client

def get_claude_client() -> Optional[ClaudeClient]:
    """Получение глобального клиента Claude"""
    return claude_client

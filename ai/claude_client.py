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
        
        # Проверяем наличие API ключа
        api_key = self.claude_config.get('api_key')
        if not api_key:
            logger.warning("Claude API ключ не установлен, будет работать демо режим")
            self.client = None
        else:
            try:
                # Инициализация Anthropic клиента
                self.client = anthropic.AsyncAnthropic(api_key=api_key)
                logger.info("Claude API клиент успешно инициализирован")
            except Exception as e:
                logger.error(f"Ошибка инициализации Claude API: {e}")
                self.client = None
        
        # Настройки по умолчанию
        self.model = self.claude_config.get('model', 'claude-3-5-sonnet-20241022')
        self.max_tokens = self.claude_config.get('max_tokens', 1000)
        self.temperature = self.claude_config.get('temperature', 0.7)
        
        logger.info(f"Claude клиент настроен: model={self.model}, api_available={bool(self.client)}")

    async def _make_request(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Базовый запрос к Claude API"""
        if not self.client:
            logger.warning("Claude API недоступен, возвращаем демо ответ")
            return "Демо ответ от AI"
        
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
            return self._get_fallback_response(prompt)
        except Exception as e:
            logger.error(f"Неожиданная ошибка при запросе к Claude: {e}")
            return self._get_fallback_response(prompt)

    def _get_fallback_response(self, prompt: str) -> str:
        """Fallback ответ когда Claude API недоступен"""
        if "analyze_interest" in prompt.lower():
            return "50"  # Средний скор заинтересованности
        elif "analyze_lead" in prompt.lower():
            return "60"  # Средний скор для лида
        else:
            return "Спасибо за ваше сообщение! Мы обработаем его в ближайшее время."

    async def analyze_user_interest(self, message: str, context: List[str] = None) -> int:
        """
        Анализ заинтересованности пользователя
        Возвращает скор от 0 до 100
        """
        try:
            context_str = ""
            if context:
                context_str = "Предыдущие сообщения:\n" + "\n".join(context[-3:])
            
            prompt = self.prompts.get('analyze_interest', '').format(
                message=message,
                context=context_str
            )
            
            if not prompt:
                logger.warning("Промпт analyze_interest не настроен")
                return self._analyze_interest_simple(message)
            
            response = await self._make_request(prompt, max_tokens=10)
            
            # Извлекаем число из ответа
            score_text = ''.join(filter(str.isdigit, response))
            if score_text:
                score = int(score_text)
                return max(0, min(100, score))  # Ограничиваем 0-100
            else:
                return self._analyze_interest_simple(message)
                
        except Exception as e:
            logger.error(f"Ошибка анализа заинтересованности: {e}")
            return self._analyze_interest_simple(message)

    def _analyze_interest_simple(self, message: str) -> int:
        """Простой анализ заинтересованности без AI"""
        message_lower = message.lower()
        
        # Высокий интерес
        high_interest_words = ['купить', 'заказать', 'цена', 'стоимость', 'сколько стоит', 
                              'где купить', 'как заказать', 'хочу купить', 'нужно']
        
        # Средний интерес
        medium_interest_words = ['интересно', 'подойдет', 'расскажите', 'подробнее', 
                               'возможно', 'рассмотрю', 'думаю']
        
        # Низкий интерес
        low_interest_words = ['дорого', 'не нужно', 'не интересно', 'спам', 'отписаться']
        
        for word in high_interest_words:
            if word in message_lower:
                return 85
        
        for word in medium_interest_words:
            if word in message_lower:
                return 60
        
        for word in low_interest_words:
            if word in message_lower:
                return 20
        
        return 50  # Нейтральный скор по умолчанию

    async def generate_response(self, message: str, context: List[str] = None, interest_score: int = 0) -> str:
        """
        Генерация ответа пользователю
        """
        try:
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
                return self._generate_response_simple(message, interest_score)
            
            response = await self._make_request(prompt, max_tokens=self.max_tokens)
            
            if response and response != "Демо ответ от AI":
                return response
            else:
                return self._generate_response_simple(message, interest_score)
                
        except Exception as e:
            logger.error(f"Ошибка генерации ответа: {e}")
            return self._generate_response_simple(message, interest_score)

    def _generate_response_simple(self, message: str, interest_score: int) -> str:
        """Простая генерация ответа без AI"""
        message_lower = message.lower()
        
        if interest_score >= 70:
            if any(word in message_lower for word in ['цена', 'стоимость', 'сколько']):
                return "Отлично! Я вижу, что вас интересует стоимость. Наш менеджер свяжется с вами для обсуждения цен и специальных предложений. 📞"
            else:
                return "Замечательно! Вижу, что наши услуги вам интересны. Давайте обсудим детали - наш менеджер готов ответить на все вопросы! 🎯"
        elif interest_score >= 40:
            return "Спасибо за интерес! Если у вас есть вопросы о наших услугах, я буду рад помочь. 😊"
        else:
            return "Спасибо за сообщение! Если понадобится помощь, обращайтесь. 👍"

    async def analyze_potential_lead(self, message: str, channel: str) -> int:
        """
        Анализ потенциального клиента из канала
        Возвращает скор от 0 до 100
        """
        try:
            prompt = self.prompts.get('analyze_lead', '').format(
                message=message,
                channel=channel
            )
            
            if not prompt:
                logger.warning("Промпт analyze_lead не настроен")
                return self._analyze_lead_simple(message)
            
            response = await self._make_request(prompt, max_tokens=10)
            
            # Извлекаем число из ответа
            score_text = ''.join(filter(str.isdigit, response))
            if score_text:
                score = int(score_text)
                return max(0, min(100, score))  # Ограничиваем 0-100
            else:
                return self._analyze_lead_simple(message)
                
        except Exception as e:
            logger.error(f"Ошибка анализа лида: {e}")
            return self._analyze_lead_simple(message)

    def _analyze_lead_simple(self, message: str) -> int:
        """Простой анализ лида без AI"""
        message_lower = message.lower()
        
        # Ключевые слова для бизнеса
        business_words = ['crm', 'автоматизация', 'бизнес', 'продажи', 'клиенты', 
                         'заявки', 'обработка', 'система', 'telegram bot', 'бот']
        
        # Проблемы бизнеса
        problem_words = ['не успеваем', 'много заявок', 'нужна помощь', 'ищу решение',
                        'как автоматизировать', 'эффективность']
        
        score = 0
        for word in business_words:
            if word in message_lower:
                score += 30
        
        for word in problem_words:
            if word in message_lower:
                score += 40
        
        return min(100, score)

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
                # Создаем корутину которая возвращает 0
                async def zero_coro():
                    return 0
                task = zero_coro()
            
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
        if not self.client:
            return False
        
        try:
            response = await self._make_request("Привет! Ответь одним словом: работаю", max_tokens=10)
            return bool(response and len(response) > 0 and response != "Демо ответ от AI")
        except Exception as e:
            logger.error(f"Проверка здоровья Claude API failed: {e}")
            return False

    def update_prompts(self, new_prompts: Dict[str, str]):
        """Обновление промптов без перезапуска"""
        self.prompts.update(new_prompts)
        logger.info("Промпты обновлены")

    def get_usage_stats(self) -> Dict[str, Any]:
        """Получение статистики использования"""
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "api_available": bool(self.client),
            "status": "active" if self.client else "demo_mode"
        }

# Глобальный экземпляр клиента
claude_client: Optional[ClaudeClient] = None

def init_claude_client(config: Dict[str, Any]) -> ClaudeClient:
    """Инициализация глобального клиента Claude"""
    global claude_client
    try:
        claude_client = ClaudeClient(config)
        logger.info("Глобальный Claude клиент инициализирован")
        return claude_client
    except Exception as e:
        logger.error(f"Ошибка инициализации глобального Claude клиента: {e}")
        claude_client = None
        return None

def get_claude_client() -> Optional[ClaudeClient]:
    """Получение глобального клиента Claude"""
    return claude_client
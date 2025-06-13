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
        if not api_key or api_key == 'your_claude_api_key_here':
            logger.warning("Claude API ключ не установлен, используем простую логику")
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
            return ""
        
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
                    response = await self._make_request(prompt, max_tokens=10)
                    
                    # Извлекаем число из ответа
                    score_text = ''.join(filter(str.isdigit, response))
                    if score_text:
                        score = int(score_text)
                        return max(0, min(100, score))  # Ограничиваем 0-100
            except Exception as e:
                logger.error(f"Ошибка анализа заинтересованности: {e}")
        
        # Простой анализ без AI
        return self._analyze_interest_simple(message)

    def _analyze_interest_simple(self, message: str) -> int:
        """Простой анализ заинтересованности без AI"""
        message_lower = message.lower()
        
        # Высокий интерес
        high_interest_words = [
            'купить', 'заказать', 'цена', 'стоимость', 'сколько стоит', 
            'где купить', 'как заказать', 'хочу купить', 'нужно купить',
            'интересует цена', 'готов купить', 'хочу заказать'
        ]
        
        # Средний интерес
        medium_interest_words = [
            'интересно', 'подойдет', 'расскажите', 'подробнее', 
            'возможно', 'рассмотрю', 'думаю', 'узнать больше',
            'как работает', 'что включено', 'условия'
        ]
        
        # Низкий интерес
        low_interest_words = [
            'дорого', 'не нужно', 'не интересно', 'спам', 'отписаться',
            'не подходит', 'слишком дорого'
        ]
        
        # Проверяем на высокий интерес
        for word in high_interest_words:
            if word in message_lower:
                return 85
        
        # Проверяем на средний интерес
        for word in medium_interest_words:
            if word in message_lower:
                return 60
        
        # Проверяем на низкий интерес
        for word in low_interest_words:
            if word in message_lower:
                return 20
        
        # Если есть вопросительные слова - средний интерес
        question_words = ['как', 'что', 'где', 'когда', 'почему', 'зачем', '?']
        for word in question_words:
            if word in message_lower:
                return 50
        
        return 40  # Нейтральный скор по умолчанию

    async def generate_response(self, message: str, context: List[str] = None, interest_score: int = 0) -> str:
        """
        Генерация ответа пользователю
        """
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
                    response = await self._make_request(prompt, max_tokens=self.max_tokens)
                    if response:
                        return response
            except Exception as e:
                logger.error(f"Ошибка генерации ответа: {e}")
        
        # Простая генерация ответа без AI
        return self._generate_response_simple(message, interest_score)

    def _generate_response_simple(self, message: str, interest_score: int) -> str:
        """Простая генерация ответа без AI"""
        message_lower = message.lower()
        
        # Ответы для высокого интереса (70+)
        if interest_score >= 70:
            if any(word in message_lower for word in ['цена', 'стоимость', 'сколько']):
                return "Отлично! Вижу, что вас интересует стоимость наших услуг. Наш менеджер свяжется с вами в ближайшее время для обсуждения цен и специальных предложений! 📞"
            elif any(word in message_lower for word in ['купить', 'заказать']):
                return "Замечательно! Готовы помочь вам с заказом. Наш специалист свяжется с вами для оформления и ответит на все вопросы! 🎯"
            else:
                return "Вижу, что наши услуги вам действительно интересны! Давайте обсудим детали - наш менеджер готов предложить лучшие условия именно для вас! ⭐"
        
        # Ответы для среднего интереса (40-69)
        elif interest_score >= 40:
            if '?' in message:
                return "Отличный вопрос! Я буду рад помочь с информацией. Если нужны детали - наш специалист может проконсультировать более подробно. 😊"
            else:
                return "Спасибо за интерес к нашим услугам! Если у вас есть вопросы или нужна дополнительная информация - обращайтесь! 👍"
        
        # Ответы для низкого интереса (менее 40)
        else:
            if any(word in message_lower for word in ['дорого', 'не нужно']):
                return "Понимаю ваши сомнения. Возможно, у нас найдется подходящее решение в рамках вашего бюджета. Если передумаете - всегда рады помочь! 💭"
            else:
                return "Спасибо за сообщение! Если понадобится помощь или возникнут вопросы - обращайтесь в любое время! 🤝"

    async def analyze_potential_lead(self, message: str, channel: str) -> int:
        """
        Анализ потенциального клиента из канала
        Возвращает скор от 0 до 100
        """
        if self.client:
            try:
                prompt = self.prompts.get('analyze_lead', '').format(
                    message=message,
                    channel=channel
                )
                
                if prompt:
                    response = await self._make_request(prompt, max_tokens=10)
                    
                    # Извлекаем число из ответа
                    score_text = ''.join(filter(str.isdigit, response))
                    if score_text:
                        score = int(score_text)
                        return max(0, min(100, score))  # Ограничиваем 0-100
            except Exception as e:
                logger.error(f"Ошибка анализа лида: {e}")
        
        # Простой анализ лида без AI
        return self._analyze_lead_simple(message)

    def _analyze_lead_simple(self, message: str) -> int:
        """Простой анализ лида без AI"""
        message_lower = message.lower()
        
        # Ключевые слова для бизнеса
        business_words = [
            'crm', 'автоматизация', 'бизнес', 'продажи', 'клиенты', 
            'заявки', 'обработка', 'система', 'telegram bot', 'бот',
            'интернет-магазин', 'онлайн', 'сайт', 'маркетинг'
        ]
        
        # Проблемы бизнеса
        problem_words = [
            'не успеваем', 'много заявок', 'нужна помощь', 'ищу решение',
            'как автоматизировать', 'эффективность', 'оптимизация',
            'увеличить продажи', 'привлечь клиентов'
        ]
        
        # Намерения покупки
        intent_words = [
            'ищу', 'нужно', 'требуется', 'хочу заказать', 'планирую',
            'рассматриваю', 'интересует'
        ]
        
        score = 0
        
        # +30 за каждое бизнес-слово
        for word in business_words:
            if word in message_lower:
                score += 30
                break  # Чтобы не накапливать слишком много баллов
        
        # +40 за проблемы бизнеса
        for word in problem_words:
            if word in message_lower:
                score += 40
                break
        
        # +30 за намерения
        for word in intent_words:
            if word in message_lower:
                score += 30
                break
        
        return min(100, score)

    async def health_check(self) -> bool:
        """Проверка работоспособности Claude API"""
        if not self.client:
            return True  # Простая логика всегда работает
        
        try:
            response = await self._make_request("Привет! Ответь одним словом: работаю", max_tokens=10)
            return bool(response and len(response) > 0)
        except Exception as e:
            logger.error(f"Проверка здоровья Claude API failed: {e}")
            return False

    def get_usage_stats(self) -> Dict[str, Any]:
        """Получение статистики использования"""
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "api_available": bool(self.client),
            "status": "ai_mode" if self.client else "simple_mode"
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
        # Создаем экземпляр с простой логикой при ошибке
        claude_client = ClaudeClient({'claude': {'api_key': ''}, 'prompts': {}})
        return claude_client

def get_claude_client() -> Optional[ClaudeClient]:
    """Получение глобального клиента Claude"""
    global claude_client
    if claude_client is None:
        # Создаем простой клиент если не был инициализирован
        claude_client = ClaudeClient({'claude': {'api_key': ''}, 'prompts': {}})
    return claude_client
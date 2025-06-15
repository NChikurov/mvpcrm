"""
AI Context Parser - ИСПРАВЛЕННАЯ ВЕРСИЯ с обработкой ошибок
"""

import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from telegram import Update, User
from telegram.ext import ContextTypes

from database.operations import create_lead, update_channel_stats
from database.models import Lead
from ai.claude_client import get_claude_client

logger = logging.getLogger(__name__)

@dataclass
class UserContext:
    """Контекст пользователя для анализа"""
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    messages: List[Dict[str, Any]]
    first_seen: datetime
    last_activity: datetime
    channel_info: Dict[str, Any]

@dataclass
class AIAnalysisResult:
    """Результат AI анализа"""
    is_lead: bool
    confidence_score: int
    lead_quality: str
    interests: List[str]
    buying_signals: List[str]
    urgency_level: str
    recommended_action: str
    key_insights: List[str]
    estimated_budget: Optional[str]
    timeline: Optional[str]
    pain_points: List[str]
    decision_stage: str

class AIContextParser:
    """Интеллектуальный парсер на основе AI анализа"""
    
    def __init__(self, config):
        self.config = config
        self.parsing_config = config.get('parsing', {})
        
        # Настройки
        self.enabled = self.parsing_config.get('enabled', True)
        self.channels = self._parse_channels()
        self.min_confidence_score = self.parsing_config.get('min_confidence_score', 70)
        self.context_window_hours = self.parsing_config.get('context_window_hours', 24)
        self.min_messages_for_analysis = self.parsing_config.get('min_messages_for_analysis', 1)
        self.max_context_messages = self.parsing_config.get('max_context_messages', 10)
        
        # Контекст пользователей
        self.user_contexts: Dict[int, UserContext] = {}
        self.analysis_cache: Dict[str, AIAnalysisResult] = {}
        self.processed_leads: Dict[int, datetime] = {}
        
        logger.info(f"AI Context Parser инициализирован:")
        logger.info(f"  - Каналов: {len(self.channels)}")
        logger.info(f"  - Мин. уверенность: {self.min_confidence_score}%")
        logger.info(f"  - Окно контекста: {self.context_window_hours}ч")

    def _parse_channels(self) -> List[str]:
        """Парсинг каналов из конфигурации"""
        channels_raw = self.parsing_config.get('channels', [])
        if isinstance(channels_raw, list):
            return [str(ch) for ch in channels_raw]
        elif isinstance(channels_raw, (str, int)):
            return [str(channels_raw)]
        return []

    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Главная функция обработки сообщения с детальным логированием"""
        try:
            if not self.enabled:
                logger.info("❌ AI парсинг отключен")
                return
            
            chat_id = update.effective_chat.id
            user = update.effective_user
            message = update.message
            
            if not user or not message or not message.text:
                logger.warning("⚠️ Нет пользователя, сообщения или текста")
                return
            
            logger.info(f"🔍 Начинаем AI анализ сообщения:")
            logger.info(f"    👤 Пользователь: {user.first_name} (@{user.username})")
            logger.info(f"    💬 Текст: '{message.text}'")
            logger.info(f"    📍 Канал: {chat_id}")
            
            # Проверяем, что канал отслеживается
            if not self.is_channel_monitored(chat_id, update.effective_chat.username):
                logger.info("⏭️ Канал не отслеживается")
                return
            
            # Обновляем контекст пользователя
            await self._update_user_context(user, message, update.effective_chat)
            logger.info("✅ Контекст пользователя обновлен")
            
            # Получаем контекст для анализа
            user_context = self.user_contexts.get(user.id)
            if not user_context:
                logger.warning("❌ Не удалось получить контекст пользователя")
                return
            
            logger.info(f"📊 Контекст: {len(user_context.messages)} сообщений")
            
            # Проверяем готовность к анализу
            if not self._should_analyze_user(user_context):
                logger.info(f"⏳ Пользователь {user.id} не готов к анализу (недостаточно данных)")
                return
            
            # Проверяем, не анализировали ли недавно
            if self._was_recently_analyzed(user.id):
                logger.info(f"🔄 Пользователь {user.id} недавно анализировался")
                return
            
            logger.info("🤖 Запускаем AI анализ...")
            
            # Запускаем AI анализ
            analysis = await self._analyze_user_context(user_context)
            
            if analysis:
                logger.info(f"✅ AI анализ завершен:")
                logger.info(f"    🎯 Лид: {analysis.is_lead}")
                logger.info(f"    📊 Уверенность: {analysis.confidence_score}%")
                logger.info(f"    🔥 Качество: {analysis.lead_quality}")
                
                if analysis.is_lead and analysis.confidence_score >= self.min_confidence_score:
                    logger.info("🎯 СОЗДАЕМ ЛИДА!")
                    
                    # Создаем лид
                    await self._create_lead_from_analysis(user_context, analysis, context)
                    
                    # Запоминаем, что уже обработали
                    self.processed_leads[user.id] = datetime.now()
                    
                    # Обновляем статистику канала
                    await self._update_channel_stats(str(chat_id), message.message_id, True)
                else:
                    logger.info(f"❌ Не лид: score={analysis.confidence_score}, min={self.min_confidence_score}")
                    await self._update_channel_stats(str(chat_id), message.message_id, False)
            else:
                logger.warning("❌ AI анализ не удался")
                await self._update_channel_stats(str(chat_id), message.message_id, False)
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка в AI Context Parser: {e}")
            import traceback
            traceback.print_exc()

    async def _update_user_context(self, user: User, message, chat):
        """Обновление контекста пользователя"""
        try:
            user_id = user.id
            current_time = datetime.now()
            
            # Создаем или обновляем контекст
            if user_id not in self.user_contexts:
                logger.info(f"🆕 Создаем новый контекст для пользователя {user_id}")
                self.user_contexts[user_id] = UserContext(
                    user_id=user_id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    messages=[],
                    first_seen=current_time,
                    last_activity=current_time,
                    channel_info={
                        'id': chat.id,
                        'title': chat.title,
                        'username': chat.username,
                        'type': chat.type
                    }
                )
            
            user_context = self.user_contexts[user_id]
            
            # Добавляем новое сообщение
            message_data = {
                'text': message.text,
                'date': message.date.isoformat() if message.date else current_time.isoformat(),
                'message_id': message.message_id,
                'timestamp': current_time.isoformat()
            }
            
            user_context.messages.append(message_data)
            user_context.last_activity = current_time
            
            # Обновляем профиль пользователя
            user_context.username = user.username
            user_context.first_name = user.first_name
            user_context.last_name = user.last_name
            
            # Ограничиваем количество сообщений в контексте
            if len(user_context.messages) > self.max_context_messages:
                user_context.messages = user_context.messages[-self.max_context_messages:]
            
            logger.info(f"📝 Добавлено сообщение. Всего в контексте: {len(user_context.messages)}")
            
        except Exception as e:
            logger.error(f"Ошибка обновления контекста пользователя {user.id}: {e}")

    def _should_analyze_user(self, user_context: UserContext) -> bool:
        """Определяет, готов ли пользователь к анализу"""
        # Минимальное количество сообщений
        if len(user_context.messages) < self.min_messages_for_analysis:
            logger.info(f"❌ Недостаточно сообщений: {len(user_context.messages)} < {self.min_messages_for_analysis}")
            return False
        
        # Проверяем свежесть активности - для теста разрешаем анализ сразу
        time_since_last = datetime.now() - user_context.last_activity
        if time_since_last > timedelta(minutes=5):  # Уменьшили с 30 до 5 минут для теста
            logger.info(f"✅ Прошло достаточно времени: {time_since_last}")
            return True
        
        # Или если набралось достаточно сообщений
        if len(user_context.messages) >= 2:  # Уменьшили с 3 до 2 для теста
            logger.info(f"✅ Достаточно сообщений для анализа: {len(user_context.messages)}")
            return True
        
        logger.info(f"⏳ Не готов к анализу: {len(user_context.messages)} сообщений, последняя активность {time_since_last} назад")
        return False

    def _was_recently_analyzed(self, user_id: int) -> bool:
        """Проверяет, не анализировался ли пользователь недавно"""
        if user_id in self.processed_leads:
            last_analysis = self.processed_leads[user_id]
            time_diff = datetime.now() - last_analysis
            if time_diff < timedelta(hours=self.context_window_hours):
                logger.info(f"🔄 Недавний анализ: {time_diff} назад")
                return True
        return False

    async def _analyze_user_context(self, user_context: UserContext) -> Optional[AIAnalysisResult]:
        """AI анализ контекста пользователя"""
        try:
            logger.info("🤖 Начинаем AI анализ...")
            
            claude_client = get_claude_client()
            if not claude_client or not claude_client.client:
                logger.warning("❌ Claude API недоступен, используем простой анализ")
                return self._simple_analysis(user_context)
            
            # Создаем ключ для кэша
            messages_text = " | ".join([msg['text'] for msg in user_context.messages[-5:]])
            cache_key = f"{user_context.user_id}:{hash(messages_text)}"
            
            # Проверяем кэш
            if cache_key in self.analysis_cache:
                logger.info(f"💾 Используем кэшированный анализ для {user_context.user_id}")
                return self.analysis_cache[cache_key]
            
            # Подготавливаем данные для анализа
            context_data = self._prepare_context_for_ai(user_context)
            
            # Формируем промпт для Claude
            analysis_prompt = self._create_analysis_prompt(context_data)
            
            logger.info(f"📤 Отправляем запрос в Claude...")
            
            # Отправляем запрос в Claude с таймаутом
            try:
                response = await asyncio.wait_for(
                    claude_client.client.messages.create(
                        model=claude_client.model,
                        max_tokens=2000,
                        messages=[{"role": "user", "content": analysis_prompt}],
                        temperature=0.1
                    ),
                    timeout=15.0
                )
                
                logger.info("📥 Получен ответ от Claude")
                
                # Парсим ответ
                analysis_result = self._parse_ai_response(response.content[0].text)
                
                # Кэшируем результат
                self.analysis_cache[cache_key] = analysis_result
                
                logger.info(f"✅ AI анализ успешен: лид={analysis_result.is_lead}, уверенность={analysis_result.confidence_score}%")
                
                return analysis_result
                
            except asyncio.TimeoutError:
                logger.warning("⏰ AI анализ превысил таймаут, используем простой анализ")
                return self._simple_analysis(user_context)
            
        except Exception as e:
            logger.error(f"❌ Ошибка AI анализа: {e}")
            return self._simple_analysis(user_context)

    def _simple_analysis(self, user_context: UserContext) -> AIAnalysisResult:
        """Простой анализ без AI"""
        logger.info("🔧 Используем простой анализ...")
        
        # Объединяем все сообщения
        all_text = " ".join([msg['text'] for msg in user_context.messages]).lower()
        
        # Простые ключевые слова
        high_interest = ['купить', 'заказать', 'цена', 'стоимость', 'сколько стоит', 'crm', 'бот', 'автоматизация']
        medium_interest = ['интересно', 'подробнее', 'расскажите', 'как работает']
        
        score = 0
        interests = []
        buying_signals = []
        
        for word in high_interest:
            if word in all_text:
                score += 30
                interests.append(word)
                if word in ['купить', 'заказать', 'цена']:
                    buying_signals.append(f"Упоминание '{word}'")
        
        for word in medium_interest:
            if word in all_text:
                score += 15
                interests.append(word)
        
        score = min(100, score)
        is_lead = score >= 60
        
        if is_lead:
            lead_quality = "hot" if score >= 80 else "warm"
        else:
            lead_quality = "cold"
        
        result = AIAnalysisResult(
            is_lead=is_lead,
            confidence_score=score,
            lead_quality=lead_quality,
            interests=interests,
            buying_signals=buying_signals,
            urgency_level="medium" if score >= 70 else "low",
            recommended_action="Связаться с клиентом" if is_lead else "Продолжить наблюдение",
            key_insights=[f"Простой анализ дал score {score}"],
            estimated_budget=None,
            timeline=None,
            pain_points=[],
            decision_stage="consideration" if is_lead else "awareness"
        )
        
        logger.info(f"🔧 Простой анализ: score={score}, лид={is_lead}")
        return result

    def _prepare_context_for_ai(self, user_context: UserContext) -> Dict[str, Any]:
        """Подготовка контекста для AI анализа"""
        return {
            'user': {
                'id': user_context.user_id,
                'username': user_context.username,
                'first_name': user_context.first_name,
                'last_name': user_context.last_name,
                'first_seen': user_context.first_seen.isoformat(),
                'last_activity': user_context.last_activity.isoformat()
            },
            'messages': user_context.messages,
            'channel': user_context.channel_info,
            'messages_count': len(user_context.messages),
            'activity_span_hours': (user_context.last_activity - user_context.first_seen).total_seconds() / 3600
        }

    def _create_analysis_prompt(self, context_data: Dict[str, Any]) -> str:
        """Создание промпта для AI анализа"""
        
        messages_text = "\n".join([
            f"[{msg.get('date', 'unknown')}] {msg['text']}" 
            for msg in context_data['messages']
        ])
        
        return f"""Ты - эксперт по анализу потенциальных клиентов в сфере IT-услуг, CRM систем, автоматизации бизнеса и разработки Telegram ботов.

КОНТЕКСТ ПОЛЬЗОВАТЕЛЯ:
- Имя: {context_data['user']['first_name']} (@{context_data['user']['username']})
- Канал: {context_data['channel']['title']} ({context_data['channel']['type']})
- Количество сообщений: {context_data['messages_count']}
- Период активности: {context_data['activity_span_hours']:.1f} часов

СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ:
{messages_text}

ЗАДАЧА:
Проанализируй контекст и определи, является ли этот пользователь потенциальным клиентом для услуг:
- CRM систем и автоматизации бизнеса
- Разработки Telegram ботов
- IT-консалтинга и внедрения
- Интеграций и API разработки

ВЕРНИ РЕЗУЛЬТАТ СТРОГО В JSON ФОРМАТЕ:
{{
    "is_lead": boolean,
    "confidence_score": number (0-100),
    "lead_quality": "hot|warm|cold|not_lead",
    "interests": ["список интересов"],
    "buying_signals": ["сигналы покупательского намерения"],
    "urgency_level": "immediate|short_term|long_term|none",
    "recommended_action": "рекомендуемое действие",
    "key_insights": ["ключевые инсайты"],
    "estimated_budget": "примерный бюджет или null",
    "timeline": "временные рамки или null",
    "pain_points": ["проблемы клиента"],
    "decision_stage": "awareness|consideration|decision|post_purchase"
}}

КРИТЕРИИ ОЦЕНКИ:
- is_lead: true если есть явные признаки интереса к нашим услугам
- confidence_score: 90-100 = очевидный клиент, 70-89 = вероятный, 50-69 = возможный, <50 = маловероятный
- lead_quality: hot = готов покупать, warm = изучает рынок, cold = только начинает поиск
- urgency_level: насколько срочно нужно решение
- buying_signals: что указывает на готовность покупать
- pain_points: какие проблемы у клиента

ВАЖНО:
- Анализируй ВЕСЬ контекст, не отдельные сообщения
- Ищи скрытые потребности и подтекст
- Обращай внимание на бизнес-контекст
- Высокий confidence_score только при явных сигналах
- Будь объективным, не завышай оценки"""

    def _parse_ai_response(self, response_text: str) -> AIAnalysisResult:
        """Парсинг ответа от AI"""
        try:
            logger.info(f"📋 Парсим ответ AI: {response_text[:200]}...")
            
            # Ищем JSON в ответе
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                logger.warning("❌ JSON не найден в ответе AI")
                raise ValueError("JSON не найден в ответе AI")
            
            json_str = json_match.group()
            data = json.loads(json_str)
            
            logger.info(f"✅ JSON успешно распарсен: is_lead={data.get('is_lead')}, score={data.get('confidence_score')}")
            
            # Валидация и создание объекта результата
            return AIAnalysisResult(
                is_lead=bool(data.get('is_lead', False)),
                confidence_score=max(0, min(100, int(data.get('confidence_score', 0)))),
                lead_quality=data.get('lead_quality', 'not_lead'),
                interests=data.get('interests', []),
                buying_signals=data.get('buying_signals', []),
                urgency_level=data.get('urgency_level', 'none'),
                recommended_action=data.get('recommended_action', ''),
                key_insights=data.get('key_insights', []),
                estimated_budget=data.get('estimated_budget'),
                timeline=data.get('timeline'),
                pain_points=data.get('pain_points', []),
                decision_stage=data.get('decision_stage', 'awareness')
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга AI ответа: {e}")
            logger.debug(f"Ответ AI: {response_text}")
            
            # Возвращаем базовый результат
            return AIAnalysisResult(
                is_lead=False,
                confidence_score=0,
                lead_quality='not_lead',
                interests=[],
                buying_signals=[],
                urgency_level='none',
                recommended_action='Анализ не удался',
                key_insights=[],
                estimated_budget=None,
                timeline=None,
                pain_points=[],
                decision_stage='awareness'
            )

    async def _create_lead_from_analysis(self, user_context: UserContext, 
                                       analysis: AIAnalysisResult, 
                                       context: ContextTypes.DEFAULT_TYPE):
        """Создание лида на основе AI анализа"""
        try:
            logger.info("🎯 Создаем лида из AI анализа...")
            
            # Объединяем все сообщения пользователя
            all_messages = " | ".join([msg['text'] for msg in user_context.messages])
            
            # Создаем объект лида
            lead = Lead(
                telegram_id=user_context.user_id,
                username=user_context.username,
                first_name=user_context.first_name,
                last_name=user_context.last_name,
                source_channel=user_context.channel_info['title'] or str(user_context.channel_info['id']),
                interest_score=analysis.confidence_score,
                message_text=all_messages,
                message_date=user_context.last_activity,
                
                # AI поля
                lead_quality=analysis.lead_quality,
                interests=json.dumps(analysis.interests, ensure_ascii=False),
                buying_signals=json.dumps(analysis.buying_signals, ensure_ascii=False),
                urgency_level=analysis.urgency_level,
                estimated_budget=analysis.estimated_budget,
                timeline=analysis.timeline,
                pain_points=json.dumps(analysis.pain_points, ensure_ascii=False),
                decision_stage=analysis.decision_stage
            )
            
            # Сохраняем в базу
            await create_lead(lead)
            
            logger.info(f"✅ AI ЛИД СОЗДАН: {user_context.first_name} (@{user_context.username})")
            logger.info(f"   Качество: {analysis.lead_quality}")
            logger.info(f"   Уверенность: {analysis.confidence_score}%")
            logger.info(f"   Интересы: {', '.join(analysis.interests)}")
            
            # Отправляем уведомление админам
            await self._notify_admins_about_ai_lead(context, user_context, analysis)
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания лида: {e}")
            import traceback
            traceback.print_exc()

    async def _notify_admins_about_ai_lead(self, context: ContextTypes.DEFAULT_TYPE, 
                                         user_context: UserContext, 
                                         analysis: AIAnalysisResult):
        """Уведомление админов о новом AI лиде"""
        try:
            admin_ids = self.config.get('bot', {}).get('admin_ids', [])
            if not admin_ids:
                logger.warning("❌ Нет админов для уведомления")
                return
            
            # Определяем приоритет и эмодзи
            priority_config = {
                'hot': {'emoji': '🔥🔥🔥', 'text': 'ГОРЯЧИЙ ЛИД', 'color': '🟥'},
                'warm': {'emoji': '🔥🔥', 'text': 'ТЕПЛЫЙ ЛИД', 'color': '🟨'},
                'cold': {'emoji': '🔥', 'text': 'ХОЛОДНЫЙ ЛИД', 'color': '🟦'}
            }
            
            priority = priority_config.get(analysis.lead_quality, 
                                         {'emoji': '⭐', 'text': 'ПОТЕНЦИАЛЬНЫЙ ЛИД', 'color': '⬜'})
            
            # Форматируем списки
            interests_text = ', '.join(analysis.interests) if analysis.interests else 'не определены'
            pain_points_text = '\n• '.join(analysis.pain_points) if analysis.pain_points else 'не выявлены'
            buying_signals_text = '\n• '.join(analysis.buying_signals) if analysis.buying_signals else 'не обнаружены'
            
            # Формируем сообщение
            username_text = f"@{user_context.username}" if user_context.username else "без username"
            
            message = f"""{priority['emoji']} <b>{priority['text']}</b> {priority['color']}

🤖 <b>AI АНАЛИЗ ЗАВЕРШЕН</b>

👤 <b>Контакт:</b> {user_context.first_name} ({username_text})
🆔 <b>ID:</b> <code>{user_context.user_id}</code>
🎯 <b>Уверенность:</b> {analysis.confidence_score}% 
📊 <b>Качество:</b> {analysis.lead_quality.upper()}
📺 <b>Источник:</b> {user_context.channel_info['title']}
💬 <b>Сообщений:</b> {len(user_context.messages)}
⏰ <b>Период активности:</b> {(user_context.last_activity - user_context.first_seen).total_seconds() / 3600:.1f}ч

🎪 <b>Интересы:</b> {interests_text}

🚩 <b>Болевые точки:</b>
• {pain_points_text}

💰 <b>Покупательские сигналы:</b>
• {buying_signals_text}

⚡ <b>Срочность:</b> {analysis.urgency_level}
💵 <b>Бюджет:</b> {analysis.estimated_budget or 'не указан'}
📅 <b>Временные рамки:</b> {analysis.timeline or 'не указаны'}
🎭 <b>Стадия решения:</b> {analysis.decision_stage}

🎯 <b>Рекомендуемое действие:</b>
<i>{analysis.recommended_action}</i>

🔍 <b>Ключевые инсайты:</b>
{chr(10).join([f"• {insight}" for insight in analysis.key_insights])}

🔗 <b>Связаться:</b> <a href="tg://user?id={user_context.user_id}">Открыть диалог</a>"""

            # Отправляем всем админам
            successful_notifications = 0
            for admin_id in admin_ids:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=message,
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
                    successful_notifications += 1
                except Exception as e:
                    logger.error(f"❌ Не удалось отправить уведомление админу {admin_id}: {e}")
            
            logger.info(f"✅ AI уведомления отправлены {successful_notifications}/{len(admin_ids)} админам")
            
        except Exception as e:
            logger.error(f"❌ Ошибка отправки AI уведомлений: {e}")

    async def _update_channel_stats(self, channel_id: str, message_id: int, lead_found: bool):
        """Обновление статистики канала"""
        try:
            leads_count = 1 if lead_found else 0
            await update_channel_stats(channel_id, message_id, leads_count)
            logger.info(f"📊 Статистика канала обновлена: {channel_id}, лид={lead_found}")
        except Exception as e:
            logger.error(f"❌ Ошибка обновления статистики: {e}")

    def is_channel_monitored(self, chat_id: int, chat_username: str = None) -> bool:
        """Проверка мониторинга канала"""
        if not self.enabled:
            return False
        
        # Проверяем по ID
        if str(chat_id) in self.channels:
            return True
        
        # Проверяем по username
        if chat_username:
            username_variants = [f"@{chat_username}", chat_username]
            for variant in username_variants:
                if variant in self.channels:
                    return True
        
        return False

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса парсера"""
        return {
            'enabled': self.enabled,
            'channels_count': len(self.channels),
            'channels': self.channels,
            'min_confidence_score': self.min_confidence_score,
            'context_window_hours': self.context_window_hours,
            'active_users': len(self.user_contexts),
            'analysis_cache_size': len(self.analysis_cache),
            'processed_leads_count': len(self.processed_leads)
        }
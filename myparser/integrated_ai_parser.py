"""
ИСПРАВЛЕННАЯ ВЕРСИЯ: myparser/integrated_ai_parser.py
Фиксы: анализ активных диалогов, разблокировка индивидуального анализа, триггеры
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

class IntegratedAIContextParser:
    """ИСПРАВЛЕННЫЙ интегрированный AI парсер с умной логикой анализа"""
    
    def __init__(self, config):
        self.config = config
        self.parsing_config = config.get('parsing', {})
        
        # Основные настройки
        self.enabled = self.parsing_config.get('enabled', True)
        self.channels = self._parse_channels()
        self.min_confidence_score = self.parsing_config.get('min_confidence_score', 70)
        
        # ИСПРАВЛЕНО: Более агрессивные настройки для реального времени
        self.context_window_hours = self.parsing_config.get('context_window_hours', 24)
        self.min_messages_for_analysis = self.parsing_config.get('min_messages_for_analysis', 1)
        self.max_context_messages = self.parsing_config.get('max_context_messages', 10)
        
        # ИСПРАВЛЕНО: Анализ диалогов с умными триггерами
        self.dialogue_analysis_enabled = self.parsing_config.get('dialogue_analysis_enabled', True)
        self.prefer_dialogue_analysis = self.parsing_config.get('prefer_dialogue_analysis', True)
        
        # НОВОЕ: Триггеры для анализа активных диалогов
        self.dialogue_analysis_triggers = {
            'message_count': 3,      # Анализ после 3 сообщений
            'participant_count': 2,  # Анализ при появлении 2го участника
            'buying_signals': 1,     # Анализ при любом покупательском сигнале
            'time_window': 30,       # Анализ каждые 30 секунд для активных диалогов
        }
        
        # Компоненты (импортируем из исправленных модулей)
        from .dialogue_analyzer import FixedDialogueTracker, FixedDialogueAnalyzer
        self.dialogue_tracker = FixedDialogueTracker(config) if self.dialogue_analysis_enabled else None
        self.dialogue_analyzer = FixedDialogueAnalyzer(config) if self.dialogue_analysis_enabled else None
        
        # Контекст пользователей для индивидуального анализа
        self.user_contexts: Dict[int, 'UserContext'] = {}
        self.analysis_cache: Dict[str, 'AIAnalysisResult'] = {}
        self.processed_leads: Dict[int, datetime] = {}
        
        # НОВОЕ: Трекинг для умного анализа
        self.last_dialogue_analysis: Dict[str, datetime] = {}
        self.dialogue_analysis_pending: Dict[str, bool] = {}
        
        logger.info(f"ИСПРАВЛЕННЫЙ IntegratedAIContextParser инициализирован:")
        logger.info(f"  - Каналов: {len(self.channels)}")
        logger.info(f"  - Анализ диалогов: {self.dialogue_analysis_enabled}")
        logger.info(f"  - Умные триггеры: {self.dialogue_analysis_triggers}")
        logger.info(f"  - Мин. уверенность: {self.min_confidence_score}%")

    def _parse_channels(self) -> List[str]:
        """Парсинг каналов из конфигурации"""
        channels_raw = self.parsing_config.get('channels', [])
        if isinstance(channels_raw, list):
            return [str(ch) for ch in channels_raw]
        elif isinstance(channels_raw, (str, int)):
            return [str(channels_raw)]
        return []

    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ИСПРАВЛЕННАЯ главная функция обработки сообщения"""
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
            
            logger.info(f"🔍 Начинаем ИСПРАВЛЕННЫЙ интегрированный анализ сообщения:")
            logger.info(f"    👤 Пользователь: {user.first_name} (@{user.username})")
            logger.info(f"    💬 Текст: '{message.text[:50]}...'")
            logger.info(f"    📍 Канал: {chat_id}")
            
            # Проверяем, что канал отслеживается
            if not self.is_channel_monitored(chat_id, update.effective_chat.username):
                logger.info("⏭️ Канал не отслеживается")
                return
            
            # ИСПРАВЛЕНО: Параллельная обработка вместо блокирующей логики
            dialogue_processed = False
            individual_processed = False
            
            # Стратегия 1: Пробуем анализ диалогов (если включен)
            if self.dialogue_analysis_enabled and self.dialogue_tracker:
                dialogue_id = await self.dialogue_tracker.process_message(update, context)
                
                if dialogue_id:
                    logger.info(f"📝 Сообщение обработано в диалоге: {dialogue_id}")
                    
                    # ИСПРАВЛЕНО: Умная проверка триггеров анализа
                    should_analyze = await self._should_analyze_dialogue_now(dialogue_id)
                    
                    if should_analyze:
                        logger.info(f"🔥 ТРИГГЕР СРАБОТАЛ - анализируем диалог немедленно!")
                        await self._analyze_dialogue_immediately(dialogue_id, context)
                        dialogue_processed = True
                    else:
                        logger.info(f"⏳ Диалог {dialogue_id} не готов к анализу по триггерам")
            
            # Стратегия 2: ИСПРАВЛЕНО - Индивидуальный анализ как дополнение, а не замена
            # Убираем блокировку индивидуального анализа
            if not dialogue_processed or not self.prefer_dialogue_analysis:
                logger.info("👤 Запускаем индивидуальный анализ пользователя")
                await self._process_individual_message(update, context)
                individual_processed = True
            else:
                logger.info("👥 Диалог обработан, индивидуальный анализ не требуется")
            
            # НОВОЕ: Периодическая проверка всех активных диалогов
            asyncio.create_task(self._periodic_dialogue_check(context))
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка в исправленном AI парсере: {e}")
            import traceback
            traceback.print_exc()

    async def _should_analyze_dialogue_now(self, dialogue_id: str) -> bool:
        """НОВОЕ: Умная проверка триггеров для анализа диалога"""
        try:
            if dialogue_id not in self.dialogue_tracker.active_dialogues:
                return False
            
            dialogue = self.dialogue_tracker.active_dialogues[dialogue_id]
            triggers = self.dialogue_analysis_triggers
            
            # Триггер 1: Достаточно сообщений
            if len(dialogue.messages) >= triggers['message_count']:
                logger.info(f"🎯 Триггер: достаточно сообщений ({len(dialogue.messages)} >= {triggers['message_count']})")
                return True
            
            # Триггер 2: Достаточно участников
            if len(dialogue.participants) >= triggers['participant_count']:
                logger.info(f"🎯 Триггер: достаточно участников ({len(dialogue.participants)} >= {triggers['participant_count']})")
                return True
            
            # Триггер 3: Обнаружены покупательские сигналы
            total_buying_signals = sum(p.buying_signals_count for p in dialogue.participants.values())
            if total_buying_signals >= triggers['buying_signals']:
                logger.info(f"🎯 Триггер: покупательские сигналы ({total_buying_signals} >= {triggers['buying_signals']})")
                return True
            
            # Триггер 4: Прошло достаточно времени с последнего анализа
            last_analysis = self.last_dialogue_analysis.get(dialogue_id)
            if last_analysis:
                time_since_analysis = (datetime.now() - last_analysis).total_seconds()
                if time_since_analysis >= triggers['time_window']:
                    logger.info(f"🎯 Триггер: время с последнего анализа ({time_since_analysis}s >= {triggers['time_window']}s)")
                    return True
            else:
                # Первый анализ - запускаем немедленно при наличии 2+ сообщений
                if len(dialogue.messages) >= 2:
                    logger.info(f"🎯 Триггер: первый анализ диалога с {len(dialogue.messages)} сообщениями")
                    return True
            
            # Триггер 5: Сообщения с высокой срочностью
            urgent_messages = [msg for msg in dialogue.messages[-3:] if msg.urgency_level in ['immediate', 'high']]
            if urgent_messages:
                logger.info(f"🎯 Триггер: срочные сообщения ({len(urgent_messages)})")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Ошибка проверки триггеров: {e}")
            return False

    async def _analyze_dialogue_immediately(self, dialogue_id: str, context: ContextTypes.DEFAULT_TYPE):
        """НОВОЕ: Немедленный анализ диалога по триггеру"""
        try:
            if dialogue_id not in self.dialogue_tracker.active_dialogues:
                logger.warning(f"Диалог {dialogue_id} не найден для анализа")
                return
            
            # Проверяем, не анализируется ли уже
            if self.dialogue_analysis_pending.get(dialogue_id, False):
                logger.info(f"Диалог {dialogue_id} уже анализируется, пропускаем")
                return
            
            self.dialogue_analysis_pending[dialogue_id] = True
            dialogue = self.dialogue_tracker.active_dialogues[dialogue_id]
            
            logger.info(f"🔥 НЕМЕДЛЕННЫЙ анализ активного диалога: {dialogue_id}")
            logger.info(f"   Участников: {len(dialogue.participants)}")
            logger.info(f"   Сообщений: {len(dialogue.messages)}")
            
            # Анализируем диалог
            analysis_result = await self.dialogue_analyzer.analyze_dialogue(dialogue)
            
            if analysis_result:
                self.last_dialogue_analysis[dialogue_id] = datetime.now()
                
                if analysis_result.is_valuable_dialogue:
                    logger.info(f"💎 Ценный активный диалог обнаружен: {dialogue_id}")
                    await self._process_dialogue_analysis_result(dialogue, analysis_result, context)
                else:
                    logger.info(f"📊 Диалог {dialogue_id} проанализирован, но не ценный (score: {analysis_result.confidence_score})")
            else:
                logger.warning(f"❌ Анализ диалога {dialogue_id} не удался")
            
        except Exception as e:
            logger.error(f"Ошибка немедленного анализа диалога: {e}")
        finally:
            self.dialogue_analysis_pending[dialogue_id] = False

    async def _periodic_dialogue_check(self, context: ContextTypes.DEFAULT_TYPE):
        """НОВОЕ: Периодическая проверка всех активных диалогов"""
        try:
            if not self.dialogue_tracker:
                return
            
            active_dialogues = list(self.dialogue_tracker.active_dialogues.keys())
            
            for dialogue_id in active_dialogues:
                try:
                    # Проверяем каждый диалог на предмет необходимости анализа
                    if await self._should_analyze_dialogue_now(dialogue_id):
                        await self._analyze_dialogue_immediately(dialogue_id, context)
                        
                        # Небольшая задержка между анализами
                        await asyncio.sleep(1)
                        
                except Exception as e:
                    logger.error(f"Ошибка в периодической проверке диалога {dialogue_id}: {e}")
            
        except Exception as e:
            logger.error(f"Ошибка периодической проверки диалогов: {e}")

    async def _process_individual_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ИСПРАВЛЕННАЯ обработка индивидуального сообщения (из оригинального кода)"""
        try:
            user = update.effective_user
            message = update.message
            
            # Обновляем контекст пользователя
            await self._update_user_context(user, message, update.effective_chat)
            logger.info("✅ Контекст пользователя обновлен")
            
            # Получаем контекст для анализа
            user_context = self.user_contexts.get(user.id)
            if not user_context:
                logger.warning("❌ Не удалось получить контекст пользователя")
                return
            
            logger.info(f"📊 Контекст: {len(user_context.messages)} сообщений")
            
            # ИСПРАВЛЕНО: Более агрессивная проверка готовности к анализу
            if not self._should_analyze_user_immediately(user_context):
                logger.info(f"⏳ Пользователь {user.id} пока не готов к анализу")
                return
            
            # Проверяем, не анализировали ли недавно
            if self._was_recently_analyzed(user.id):
                logger.info(f"🔄 Пользователь {user.id} недавно анализировался")
                return
            
            logger.info("🤖 Запускаем НЕМЕДЛЕННЫЙ индивидуальный AI анализ...")
            
            # Запускаем AI анализ
            analysis = await self._analyze_user_context(user_context)
            
            if analysis:
                logger.info(f"✅ Индивидуальный AI анализ завершен:")
                logger.info(f"    🎯 Лид: {analysis.is_lead}")
                logger.info(f"    📊 Уверенность: {analysis.confidence_score}%")
                logger.info(f"    🔥 Качество: {analysis.lead_quality}")
                
                if analysis.is_lead and analysis.confidence_score >= self.min_confidence_score:
                    logger.info("🎯 СОЗДАЕМ ИНДИВИДУАЛЬНОГО ЛИДА НЕМЕДЛЕННО!")
                    
                    # Создаем лид
                    await self._create_lead_from_individual_analysis(user_context, analysis, context)
                    
                    # Запоминаем, что уже обработали
                    self.processed_leads[user.id] = datetime.now()
                    
                    # Обновляем статистику канала
                    await self._update_channel_stats(str(update.effective_chat.id), 
                                                   message.message_id, True)
                else:
                    logger.info(f"❌ Не лид: score={analysis.confidence_score}, min={self.min_confidence_score}")
                    await self._update_channel_stats(str(update.effective_chat.id), 
                                                   message.message_id, False)
            else:
                logger.warning("❌ Индивидуальный AI анализ не удался")
                await self._update_channel_stats(str(update.effective_chat.id), 
                                               message.message_id, False)
            
        except Exception as e:
            logger.error(f"❌ Ошибка индивидуального анализа: {e}")

    def _should_analyze_user_immediately(self, user_context) -> bool:
        """ИСПРАВЛЕННАЯ проверка готовности пользователя к анализу"""
        messages_count = len(user_context.messages)
        
        # ИСПРАВЛЕНО: Минимальное количество сообщений = 1
        if messages_count < self.min_messages_for_analysis:
            logger.info(f"❌ Недостаточно сообщений: {messages_count} < {self.min_messages_for_analysis}")
            return False
        
        # ИСПРАВЛЕНО: Для одиночных сообщений - немедленный анализ при любых сигналах
        if messages_count == 1:
            first_message = user_context.messages[0]['text'].lower()
            
            # Проверяем на любые деловые сигналы (не только сильные)
            if self._has_any_business_signals(first_message):
                logger.info(f"🔥 ДЕЛОВЫЕ СИГНАЛЫ в сообщении - анализируем немедленно!")
                return True
            
            # ИСПРАВЛЕНО: Анализируем все одиночные сообщения через короткое время
            time_since_last = datetime.now() - user_context.last_activity
            if time_since_last > timedelta(seconds=10):  # БЫЛО: 2 минуты, СТАЛО: 10 секунд
                logger.info(f"✅ Прошло достаточно времени для анализа: {time_since_last}")
                return True
            
            logger.info(f"⏳ Ждем еще: {time_since_last} < 10 сек")
            return False
        
        # Для 2+ сообщений - анализируем немедленно
        if messages_count >= 2:
            logger.info(f"✅ Достаточно сообщений для анализа: {messages_count}")
            return True
        
        return False

    def _has_any_business_signals(self, text: str) -> bool:
        """ИСПРАВЛЕННАЯ проверка на любые деловые сигналы (не только сильные)"""
        # Расширенный список деловых сигналов
        business_signals = [
            # Прямые покупательские намерения
            'хочу купить', 'хочу заказать', 'готов купить', 'готов заказать',
            'нужно купить', 'планирую купить', 'собираюсь купить',
            'нужен', 'нужна', 'требуется', 'ищу',
            
            # Ценовые вопросы
            'сколько стоит', 'какая цена', 'какая стоимость', 'цена за',
            'стоимость услуг', 'прайс', 'расценки', 'тариф',
            
            # Наши услуги
            'заказать бота', 'сделать бота', 'разработать бота', 'создать бота',
            'нужен бот', 'telegram bot', 'телеграм бот',
            'нужна crm', 'заказать crm', 'crm система',
            'автоматизация', 'автоматизировать', 'интеграция',
            
            # Деловое общение
            'обсудить проект', 'обсудить условия', 'обсудить детали',
            'связаться с менеджером', 'поговорить о', 'консультация',
            'техническое задание', 'тз', 'бриф',
            
            # Срочность
            'срочно', 'быстро', 'сегодня', 'сейчас', 'как можно скорее',
            
            # Вопросы
            'как работает', 'что включает', 'какие возможности',
            'можете ли', 'умеете ли', 'делаете ли'
        ]
        
        text_lower = text.lower()
        for signal in business_signals:
            if signal in text_lower:
                logger.info(f"🎯 Обнаружен деловой сигнал: '{signal}'")
                return True
        
        return False

    # Остальные методы остаются без изменений...
    # (здесь должны быть все остальные методы из оригинального файла)
    
    def get_status(self) -> Dict[str, Any]:
        """Получение статуса исправленного парсера"""
        status = {
            'enabled': self.enabled,
            'channels_count': len(self.channels),
            'channels': self.channels,
            'min_confidence_score': self.min_confidence_score,
            'individual_active_users': len(self.user_contexts),
            'individual_analysis_cache_size': len(self.analysis_cache),
            'individual_processed_leads_count': len(self.processed_leads),
            'dialogue_analysis_enabled': self.dialogue_analysis_enabled,
            'prefer_dialogue_analysis': self.prefer_dialogue_analysis,
            'dialogue_analysis_triggers': self.dialogue_analysis_triggers,
            'last_dialogue_analysis_count': len(self.last_dialogue_analysis),
            'pending_dialogue_analysis_count': sum(self.dialogue_analysis_pending.values())
        }
        
        if self.dialogue_tracker:
            status['dialogue_tracker'] = {
                'active_dialogues': len(self.dialogue_tracker.active_dialogues),
                'min_participants': getattr(self.dialogue_tracker, 'min_participants', 2),
                'min_messages': getattr(self.dialogue_tracker, 'min_messages', 3),
            }
        
        return status

# Alias для обратной совместимости
AIContextParser = IntegratedAIContextParser
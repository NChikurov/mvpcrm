"""
Обработчики пользователей
"""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from database.operations import (
    create_user, get_user_by_telegram_id, create_message,
    update_user_interest_score, increment_user_message_count,
    get_user_messages
)
from database.models import User, Message
from ai.claude_client import init_claude_client, get_claude_client

logger = logging.getLogger(__name__)

class UserHandler:
    """Обработчик пользовательских команд и сообщений"""
    
    def __init__(self, config):
        self.config = config
        self.messages_config = config.get('messages', {})
        self.features = config.get('features', {})
        
        # Инициализация Claude клиента
        try:
            init_claude_client(config)
            logger.info("Claude клиент инициализирован в UserHandler")
        except Exception as e:
            logger.error(f"Ошибка инициализации Claude клиента: {e}")
        
        # Callback handler
        self.callback_handler = CallbackQueryHandler(self.handle_callback)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /start"""
        try:
            logger.info(f"Команда /start от пользователя {update.effective_user.id}")
            
            user_data = update.effective_user
            
            # Создаем или обновляем пользователя
            user = User(
                telegram_id=user_data.id,
                username=user_data.username,
                first_name=user_data.first_name,
                last_name=user_data.last_name
            )
            
            await create_user(user)
            logger.info(f"Пользователь создан/обновлен: {user_data.id} (@{user_data.username})")
            
            # Отправляем приветственное сообщение
            welcome_message = self.messages_config.get('welcome', 
                '🤖 Добро пожаловать в AI-CRM бот!\n\nЯ помогу вам с информацией о наших услугах.\nНапишите мне что-нибудь!')
            
            keyboard = self._get_main_keyboard()
            
            await update.message.reply_text(
                welcome_message,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Ошибка в команде /start: {e}")
            await update.message.reply_text("Добро пожаловать! Произошла небольшая ошибка, но я готов работать.")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /help"""
        try:
            logger.info(f"Команда /help от пользователя {update.effective_user.id}")
            help_message = self.messages_config.get('help', 
                'ℹ️ Помощь:\n\n/start - начать работу\n/help - справка\n/menu - главное меню')
            await update.message.reply_text(help_message, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Ошибка в команде /help: {e}")
            await update.message.reply_text("Вы можете использовать команды:\n/start - начать\n/help - справка\n/menu - меню")

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /menu"""
        try:
            logger.info(f"Команда /menu от пользователя {update.effective_user.id}")
            menu_message = self.messages_config.get('menu', '📋 Главное меню:\n\nВыберите действие.')
            keyboard = self._get_main_keyboard()
            
            await update.message.reply_text(
                menu_message,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Ошибка в команде /menu: {e}")
            await update.message.reply_text("📋 Главное меню")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений пользователей"""
        try:
            user_data = update.effective_user
            message_text = update.message.text
            
            logger.info(f"Сообщение от пользователя {user_data.id}: {message_text[:50]}...")
            
            # Получаем пользователя из БД
            user = await get_user_by_telegram_id(user_data.id)
            if not user:
                # Создаем нового пользователя если не существует
                user = User(
                    telegram_id=user_data.id,
                    username=user_data.username,
                    first_name=user_data.first_name,
                    last_name=user_data.last_name
                )
                user = await create_user(user)
                logger.info(f"Создан новый пользователь: {user_data.id}")
            
            # Увеличиваем счетчик сообщений
            await increment_user_message_count(user_data.id)
            
            # Анализируем сообщение
            interest_score = 0
            ai_analysis = ""
            response_text = "Спасибо за ваше сообщение!"
            
            try:
                claude_client = get_claude_client()
                if claude_client:
                    # Получаем контекст предыдущих сообщений
                    recent_messages = await get_user_messages(user.id, limit=5)
                    context = [msg.text for msg in recent_messages if msg.text]
                    
                    # Анализируем заинтересованность
                    interest_score = await claude_client.analyze_user_interest(message_text, context)
                    
                    # Генерируем ответ
                    response_text = await claude_client.generate_response(message_text, context, interest_score)
                    
                    ai_analysis = f"Interest: {interest_score}/100"
                    
                    # Обновляем скор пользователя (берем максимальный)
                    if interest_score > user.interest_score:
                        await update_user_interest_score(user_data.id, interest_score)
                    
                    logger.info(f"AI анализ: score={interest_score}")
                
            except Exception as e:
                logger.error(f"Ошибка AI анализа: {e}")
                # Простой анализ без AI
                interest_score = self._simple_interest_analysis(message_text)
                response_text = self._simple_response_generation(message_text, interest_score)
            
            # Сохраняем сообщение в БД
            try:
                message = Message(
                    user_id=user.id,
                    telegram_message_id=update.message.message_id,
                    text=message_text,
                    ai_analysis=ai_analysis,
                    interest_score=interest_score,
                    response_sent=True
                )
                await create_message(message)
            except Exception as e:
                logger.error(f"Ошибка сохранения сообщения: {e}")
            
            # Отправляем ответ с соответствующей клавиатурой
            keyboard = None
            if interest_score >= 70:  # Высокая заинтересованность
                keyboard = self._get_interested_user_keyboard()
            elif interest_score <= 30:  # Низкая заинтересованность
                keyboard = self._get_help_keyboard()
            else:  # Средняя заинтересованность
                keyboard = self._get_main_keyboard()
            
            await update.message.reply_text(
                response_text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            
            logger.info(f"Ответ отправлен пользователю {user_data.id}: score={interest_score}")
            
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            import traceback
            traceback.print_exc()
            
            try:
                await update.message.reply_text("Спасибо за сообщение! Мы обработаем его в ближайшее время.")
            except:
                logger.error("Не удалось отправить сообщение об ошибке")

    def _simple_interest_analysis(self, message: str) -> int:
        """Простой анализ заинтересованности без AI"""
        message_lower = message.lower()
        
        # Высокий интерес
        high_words = ['купить', 'заказать', 'цена', 'стоимость', 'сколько стоит']
        # Средний интерес
        medium_words = ['интересно', 'подробнее', 'расскажите', 'как работает']
        # Низкий интерес
        low_words = ['дорого', 'не нужно', 'не интересно']
        
        for word in high_words:
            if word in message_lower:
                return 85
        
        for word in medium_words:
            if word in message_lower:
                return 60
        
        for word in low_words:
            if word in message_lower:
                return 20
        
        return 50

    def _simple_response_generation(self, message: str, interest_score: int) -> str:
        """Простая генерация ответа без AI"""
        if interest_score >= 70:
            return "Отлично! Вижу, что вас заинтересовали наши услуги. Наш менеджер свяжется с вами для обсуждения деталей! 📞"
        elif interest_score >= 40:
            return "Спасибо за интерес! Если у вас есть вопросы о наших услугах, я буду рад помочь. 😊"
        else:
            return "Спасибо за сообщение! Если понадобится помощь, обращайтесь. 👍"

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка callback запросов от инлайн кнопок"""
        query = update.callback_query
        try:
            await query.answer()
            
            data = query.data
            logger.info(f"Callback от пользователя {query.from_user.id}: {data}")
            
            if data == "main_menu":
                await self._show_main_menu(query)
            elif data == "help":
                await self._show_help(query)
            elif data == "contact":
                await self._show_contact(query)
            elif data == "about":
                await self._show_about(query)
            else:
                await query.edit_message_text("Неизвестная команда")
                
        except Exception as e:
            logger.error(f"Ошибка обработки callback: {e}")

    def _get_main_keyboard(self):
        """Основная клавиатура для пользователей"""
        keyboard = [
            [
                InlineKeyboardButton("📞 Контакты", callback_data="contact"),
                InlineKeyboardButton("ℹ️ Помощь", callback_data="help")
            ],
            [
                InlineKeyboardButton("📋 О компании", callback_data="about")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    def _get_interested_user_keyboard(self):
        """Клавиатура для заинтересованных пользователей"""
        keyboard = [
            [
                InlineKeyboardButton("💬 Связаться с менеджером", callback_data="contact"),
                InlineKeyboardButton("📋 Узнать больше", callback_data="about")
            ],
            [
                InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    def _get_help_keyboard(self):
        """Клавиатура с помощью"""
        keyboard = [
            [
                InlineKeyboardButton("ℹ️ Помощь", callback_data="help"),
                InlineKeyboardButton("📞 Контакты", callback_data="contact")
            ],
            [
                InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def _show_main_menu(self, query):
        """Показать главное меню"""
        menu_message = self.messages_config.get('menu', '📋 Главное меню:\n\nВыберите действие.')
        keyboard = self._get_main_keyboard()
        
        await query.edit_message_text(
            menu_message,
            reply_markup=keyboard,
            parse_mode='HTML'
        )

    async def _show_help(self, query):
        """Показать справку"""
        help_message = self.messages_config.get('help', 'ℹ️ Помощь:\n\n/start - начать работу\n/help - справка\n/menu - главное меню')
        keyboard = [
            [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
        ]
        
        await query.edit_message_text(
            help_message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    async def _show_contact(self, query):
        """Показать контактную информацию"""
        contact_message = self.messages_config.get('contact', 
            '📞 Контакты:\n\n• Telegram: @support\n• Email: support@example.com')
        keyboard = [
            [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
        ]
        
        await query.edit_message_text(
            contact_message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    async def _show_about(self, query):
        """Показать информацию о компании"""
        about_message = """📋 <b>О нашей компании</b>

Мы предоставляем качественные услуги и решения для бизнеса:

🔹 Профессиональный подход
🔹 Индивидуальные решения  
🔹 Поддержка 24/7
🔹 Гарантия качества

Свяжитесь с нами для получения консультации!"""
        
        keyboard = [
            [
                InlineKeyboardButton("💬 Связаться", callback_data="contact"),
                InlineKeyboardButton("🔙 Меню", callback_data="main_menu")
            ]
        ]
        
        await query.edit_message_text(
            about_message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
"""
Загрузчик конфигурации с поддержкой переменных окружения
"""

import os
import yaml
import logging
from typing import Dict, Any, List
from dotenv import load_dotenv
from pathlib import Path

logger = logging.getLogger(__name__)

def load_config(config_path: str = "config.yaml", env_path: str = ".env") -> Dict[str, Any]:
    """
    Загружает конфигурацию из YAML файла и переменных окружения
    Приоритет: переменные окружения > config.yaml > значения по умолчанию
    """
    
    # Загружаем переменные окружения из .env файла
    if Path(env_path).exists():
        load_dotenv(env_path)
        logger.info(f"Загружены переменные окружения из {env_path}")
    else:
        logger.warning(f"Файл {env_path} не найден, используются системные переменные окружения")
    
    # Загружаем базовую конфигурацию из YAML
    base_config = {}
    if Path(config_path).exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                base_config = yaml.safe_load(f) or {}
            logger.info(f"Загружена базовая конфигурация из {config_path}")
        except Exception as e:
            logger.error(f"Ошибка загрузки {config_path}: {e}")
    
    # Строим итоговую конфигурацию с приоритетом переменных окружения
    config = build_config_from_env(base_config)
    
    # Валидация обязательных параметров
    validate_config(config)
    
    return config

def build_config_from_env(base_config: Dict[str, Any]) -> Dict[str, Any]:
    """Строит конфигурацию из переменных окружения с fallback на базовую конфигурацию"""
    
    config = {
        'bot': {
            'name': os.getenv('BOT_NAME', base_config.get('bot', {}).get('name', 'AI CRM Bot')),
            'token': os.getenv('BOT_TOKEN', base_config.get('bot', {}).get('token', '')),
            'admin_ids': parse_admin_ids(
                os.getenv('ADMIN_IDS'), 
                base_config.get('bot', {}).get('admin_ids', [])
            )
        },
        
        'claude': {
            'api_key': os.getenv('CLAUDE_API_KEY', base_config.get('claude', {}).get('api_key', '')),
            'model': os.getenv('CLAUDE_MODEL', base_config.get('claude', {}).get('model', 'claude-3-5-sonnet-20241022')),
            'max_tokens': int(os.getenv('CLAUDE_MAX_TOKENS', base_config.get('claude', {}).get('max_tokens', 1000))),
            'temperature': float(os.getenv('CLAUDE_TEMPERATURE', base_config.get('claude', {}).get('temperature', 0.7)))
        },
        
        'database': {
            'path': os.getenv('DATABASE_PATH', base_config.get('database', {}).get('path', 'data/bot.db'))
        },
        
        'parsing': {
            'enabled': parse_bool(os.getenv('PARSING_ENABLED'), base_config.get('parsing', {}).get('enabled', True)),
            'channels': parse_channels(
                os.getenv('PARSING_CHANNELS'),
                base_config.get('parsing', {}).get('channels', [])
            ),
            'min_interest_score': int(os.getenv('PARSING_MIN_SCORE', base_config.get('parsing', {}).get('min_interest_score', 60))),
            'parse_interval': int(os.getenv('PARSING_INTERVAL', base_config.get('parsing', {}).get('parse_interval', 3600))),
            'max_messages_per_parse': int(os.getenv('PARSING_MAX_MESSAGES', base_config.get('parsing', {}).get('max_messages_per_parse', 50)))
        },
        
        'features': {
            'auto_response': parse_bool(os.getenv('AUTO_RESPONSE'), base_config.get('features', {}).get('auto_response', True)),
            'save_all_messages': parse_bool(os.getenv('SAVE_MESSAGES'), base_config.get('features', {}).get('save_all_messages', True)),
            'lead_notifications': parse_bool(os.getenv('LEAD_NOTIFICATIONS'), base_config.get('features', {}).get('lead_notifications', True)),
            'analytics': parse_bool(os.getenv('ANALYTICS'), base_config.get('features', {}).get('analytics', True))
        },
        
        # Сообщения и промпты берем из базовой конфигурации
        'messages': base_config.get('messages', get_default_messages()),
        'prompts': base_config.get('prompts', get_default_prompts())
    }
    
    return config

def parse_admin_ids(env_value: str, fallback: List[int]) -> List[int]:
    """Парсит admin_ids из строки переменной окружения"""
    if not env_value:
        return fallback
    
    try:
        # Поддерживаем разделение запятыми
        ids = [int(x.strip()) for x in env_value.split(',') if x.strip()]
        return ids
    except ValueError as e:
        logger.error(f"Ошибка парсинга ADMIN_IDS: {e}")
        return fallback

def parse_channels(env_value: str, fallback: List[str]) -> List[str]:
    """Парсит каналы из строки переменной окружения"""
    if not env_value:
        return fallback
    
    try:
        # Поддерживаем разделение запятыми
        channels = [x.strip() for x in env_value.split(',') if x.strip()]
        return channels
    except Exception as e:
        logger.error(f"Ошибка парсинга PARSING_CHANNELS: {e}")
        return fallback

def parse_bool(env_value: str, fallback: bool = True) -> bool:
    """Парсит boolean значение из строки"""
    if env_value is None:
        return fallback
    
    return env_value.lower() in ('true', '1', 'yes', 'on', 'enabled')

def validate_config(config: Dict[str, Any]) -> None:
    """Валидация обязательных параметров конфигурации"""
    errors = []
    
    # Проверяем обязательные параметры
    if not config['bot']['token']:
        errors.append("BOT_TOKEN не установлен")
    
    if not config['bot']['admin_ids']:
        errors.append("ADMIN_IDS не установлены")
    
    if not config['claude']['api_key'] or config['claude']['api_key'] == 'your_claude_api_key_here':
        logger.warning("CLAUDE_API_KEY не установлен, будет использован простой режим анализа")
    
    if config['parsing']['enabled'] and not config['parsing']['channels']:
        logger.warning("Парсинг включен, но каналы не настроены")
    
    if errors:
        error_msg = "Ошибки конфигурации:\n" + "\n".join(f"- {error}" for error in errors)
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    logger.info("Конфигурация успешно валидирована")

def get_default_messages() -> Dict[str, str]:
    """Сообщения по умолчанию"""
    return {
        'welcome': '''🤖 Добро пожаловать в AI-CRM бот!

Я помогу вам с информацией о наших услугах.
Напишите мне что-нибудь!''',
        
        'help': '''ℹ️ Помощь:

/start - начать работу
/help - справка
/menu - главное меню''',
        
        'menu': '''📋 Главное меню:

Выберите действие.''',
        
        'contact': '''📞 Контакты:

• Telegram: @support
• Email: support@example.com''',
        
        'error': '❌ Ошибка. Попробуйте позже.'
    }

def get_default_prompts() -> Dict[str, str]:
    """Промпты по умолчанию"""
    return {
        'analyze_interest': '''Оцени заинтересованность в покупке по шкале 0-100.

Высокий интерес: купить, заказать, цена
Средний интерес: интересно, подойдет
Низкий интерес: дорого, не нужно

Сообщение: "{message}"
Контекст: {context}

Ответь только числом 0-100.''',
        
        'generate_response': '''Ты - помощник CRM бота.

Ответь вежливо и профессионально.
Если высокий интерес - направляй к покупке.
Ответ до 200 слов.

Сообщение: "{message}"
Интерес: {interest_score}/100''',
        
        'analyze_lead': '''Оцени потенциального клиента 0-100.

Ищи проблемы, которые можем решить.

Сообщение: "{message}"
Канал: {channel}

Ответь числом 0-100.'''
    }

def print_config_summary(config: Dict[str, Any]) -> None:
    """Выводит краткую сводку по конфигурации"""
    logger.info("=== Сводка конфигурации ===")
    logger.info(f"Бот: {config['bot']['name']}")
    logger.info(f"Админов: {len(config['bot']['admin_ids'])}")
    logger.info(f"Claude API: {'✓' if config['claude']['api_key'] and config['claude']['api_key'] != 'your_claude_api_key_here' else '✗'}")
    logger.info(f"Парсинг: {'✓' if config['parsing']['enabled'] else '✗'}")
    logger.info(f"Каналов для парсинга: {len(config['parsing']['channels'])}")
    logger.info(f"Автоответы: {'✓' if config['features']['auto_response'] else '✗'}")
    logger.info("===========================")

def get_parsing_channels_info(config: Dict[str, Any]) -> str:
    """Возвращает информацию о настроенных каналах для парсинга"""
    channels = config.get('parsing', {}).get('channels', [])
    if not channels:
        return "Каналы для парсинга не настроены"
    
    info = f"Настроено каналов: {len(channels)}\n"
    for i, channel in enumerate(channels[:5], 1):  # Показываем максимум 5
        info += f"{i}. {channel}\n"
    
    if len(channels) > 5:
        info += f"... и еще {len(channels) - 5}"
    
    return info

def validate_channel_format(channel: str) -> bool:
    """Проверяет корректность формата канала"""
    if not channel:
        return False
    
    # Поддерживаем @username и -100123456789 форматы
    if channel.startswith('@'):
        # Проверяем username формат
        username = channel[1:]
        if len(username) >= 5 and username.replace('_', '').isalnum():
            return True
    elif channel.startswith('-100'):
        # Проверяем ID формат
        try:
            int(channel)
            return True
        except ValueError:
            pass
    
    return False

def get_config_validation_report(config: Dict[str, Any]) -> Dict[str, Any]:
    """Генерирует отчет о валидности конфигурации"""
    report = {
        'valid': True,
        'errors': [],
        'warnings': [],
        'info': {}
    }
    
    # Проверка бота
    if not config['bot']['token']:
        report['errors'].append("BOT_TOKEN не установлен")
        report['valid'] = False
    
    if not config['bot']['admin_ids']:
        report['errors'].append("ADMIN_IDS не установлены")
        report['valid'] = False
    
    # Проверка Claude
    if not config['claude']['api_key'] or config['claude']['api_key'] == 'your_claude_api_key_here':
        report['warnings'].append("Claude API не настроен - будет использоваться простой режим")
    
    # Проверка парсинга
    if config['parsing']['enabled']:
        if not config['parsing']['channels']:
            report['warnings'].append("Парсинг включен, но каналы не настроены")
        else:
            invalid_channels = []
            for channel in config['parsing']['channels']:
                if not validate_channel_format(str(channel)):
                    invalid_channels.append(channel)
            
            if invalid_channels:
                report['warnings'].append(f"Некорректный формат каналов: {invalid_channels}")
    
    # Информация
    report['info'] = {
        'bot_name': config['bot']['name'],
        'admin_count': len(config['bot']['admin_ids']),
        'claude_enabled': bool(config['claude']['api_key'] and config['claude']['api_key'] != 'your_claude_api_key_here'),
        'parsing_enabled': config['parsing']['enabled'],
        'channels_count': len(config['parsing']['channels']),
        'features': {
            'auto_response': config['features']['auto_response'],
            'save_messages': config['features']['save_all_messages'],
            'analytics': config['features']['analytics']
        }
    }
    
    return report
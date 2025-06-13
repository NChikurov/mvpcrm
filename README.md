# AI-CRM Telegram Bot

## Быстрый старт

1. Получите API ключи:
   - Telegram Bot Token у @BotFather
   - Claude API Key на console.anthropic.com
   - Ваш Telegram ID у @userinfobot

2. Настройте config.yaml:
   ```yaml
   bot:
     token: "YOUR_BOT_TOKEN"
     admin_ids: [YOUR_TELEGRAM_ID]
   
   claude:
     api_key: "YOUR_CLAUDE_API_KEY"
   ```

3. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

4. Скопируйте полные версии обработчиков из артефактов Claude

5. Запустите:
   ```bash
   python main.py
   ```

## Команды

### Пользователи:
- /start - начать
- /help - справка  
- /menu - меню

### Админы:
- /admin - панель
- /users - пользователи
- /leads - лиды
- /stats - статистика
- /broadcast - рассылка

# Multi-stage build для AI-CRM Bot с анализом диалогов
FROM python:3.11-slim as builder

# Установка системных зависимостей для сборки
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Создание виртуального окружения
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Копирование и установка Python зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Финальный образ
FROM python:3.11-slim

# Метаданные
LABEL maintainer="AI-CRM Bot Team"
LABEL description="AI-CRM Telegram Bot with Dialogue Analysis"
LABEL version="2.0.0"

# Установка runtime зависимостей
RUN apt-get update && apt-get install -y \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Создание пользователя для безопасности
RUN groupadd -r botuser && useradd -r -g botuser botuser

# Создание директорий
RUN mkdir -p /app /app/data /app/logs
WORKDIR /app

# Копирование виртуального окружения из builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Копирование кода приложения
COPY . .

# Создание файла .env по умолчанию если он не существует
RUN if [ ! -f .env ]; then cp .env.example .env; fi

# Установка прав доступа
RUN chown -R botuser:botuser /app
RUN chmod +x main.py

# Переключение на непривилегированного пользователя
USER botuser

# Порты (если планируется веб-интерфейс)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import aiosqlite; import asyncio; asyncio.run(aiosqlite.connect('/app/data/bot.db').close())" || exit 1

# Создание точек монтирования
VOLUME ["/app/data", "/app/logs"]

# Переменные окружения по умолчанию
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH="/app/data/bot.db"

# Команда по умолчанию
CMD ["python", "main.py"]

# Alternative commands for debugging
# CMD ["python", "-c", "import sys; print(sys.path); import main; main.main()"]
# CMD ["bash"]  # For debugging
# Telegram Бот для Инвентаризации

Telegram бот для управления инвентаризацией на складах с интеграцией Google Sheets.

## Возможности

- Управление складскими запасами через Telegram
- Синхронизация данных с Google Sheets
- Отслеживание товаров по категориям
- Обновление количества товаров в реальном времени

## Требования

- Python 3.7+
- Google Cloud аккаунт
- Telegram Bot Token

## Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/farakor/df-inventory-tg-bot.git
cd df-inventory-tg-bot
```

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Настройка Google Sheets API:
   - Перейдите в [Google Cloud Console](https://console.cloud.google.com/)
   - Создайте новый проект
   - Включите Google Sheets API для проекта
   - Создайте учетные данные (Service Account)
   - Скачайте JSON файл с учетными данными
   - Переименуйте файл в `credentials.json` и поместите его в корневую директорию проекта

4. Настройка Telegram бота:
   - Создайте нового бота через [@BotFather](https://t.me/botfather)
   - Получите токен бота
   - Добавьте токен в конфигурацию бота

## Конфигурация

1. Создайте файл `.env` в корневой директории проекта:
```
TELEGRAM_BOT_TOKEN=ваш_токен_бота
GOOGLE_SPREADSHEET_ID=ид_вашей_таблицы
```

2. Предоставьте доступ к Google Spreadsheet для сервисного аккаунта (email можно найти в credentials.json)

## Использование

Запустите бота:
```bash
python bot.py
```

## Безопасность

- Не публикуйте `credentials.json` в публичных репозиториях
- Храните токен бота в безопасном месте
- Регулярно обновляйте учетные данные

## Структура проекта

```
df-inventory-tg-bot/
├── bot.py           # Основной файл бота
├── config.py        # Конфигурация и константы
├── sheets.py        # Интеграция с Google Sheets
├── .env            # Переменные окружения
└── credentials.json # Учетные данные Google (не включены в репозиторий)
```

## Лицензия

MIT 
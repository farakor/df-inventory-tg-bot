# Telegram Bot для Инвентаризации

Этот бот предназначен для проведения инвентаризации на складах через Telegram. Он позволяет:
- Выбирать склад для инвентаризации
- Вводить количество товаров по категориям
- Сохранять результаты в Google Sheets
- Просматривать историю инвентаризаций

## Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/yourusername/df-inventory-tg-bot.git
cd df-inventory-tg-bot
```

2. Создайте виртуальное окружение и активируйте его:
```bash
python -m venv .venv
source .venv/bin/activate  # для Linux/Mac
.venv\Scripts\activate     # для Windows
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Создайте бота в Telegram через [@BotFather](https://t.me/botfather) и получите токен

5. Настройте Google Sheets API:
   - Создайте проект в [Google Cloud Console](https://console.cloud.google.com)
   - Включите Google Sheets API и Google Drive API
   - Создайте учетные данные (credentials.json)
   - Поместите файл credentials.json в корневую директорию проекта

6. Запустите бота:
```bash
python bot.py
```

## Использование

1. Отправьте команду `/start` боту
2. Поделитесь своим номером телефона
3. Введите ваше имя
4. Выберите склад для инвентаризации
5. Вводите количество товаров по категориям
6. После завершения проверьте итоги и сохраните результаты

## Структура проекта

- `bot.py` - основной файл бота
- `sheets.py` - функции для работы с Google Sheets
- `config.py` - конфигурация (списки складов и товаров)
- `requirements.txt` - зависимости проекта
- `credentials.json` - учетные данные Google API
- `token.json` - токен авторизации Google API

## Лицензия

MIT 
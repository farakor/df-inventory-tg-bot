import os
import logging
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from sheets import (
    get_google_sheets_service, get_drive_service, get_or_create_spreadsheet,
    create_new_sheet, save_inventory_data, get_inventory_history,
    move_existing_files_to_folder
)
from config import WAREHOUSES, PRODUCT_CATEGORIES
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
TELEGRAM_TOKEN = '7877667795:AAGL7oIUMWpztvw2N3TV2WBkjCmx7yqxI3c'  # Замените на ваш токен бота
CACHE_TIMEOUT = 300  # Увеличиваем время жизни кэша до 5 минут
REQUEST_TIMEOUT = 30  # Таймаут для запросов в секундах

# Словари для хранения данных пользователей и кэша
user_data = {}
sheets_cache = {}
drive_cache = {}

def get_cached_drive_files():
    try:
        current_time = time.time()
        if 'drive_files' in sheets_cache and current_time - sheets_cache['drive_files']['timestamp'] < CACHE_TIMEOUT:
            return sheets_cache['drive_files']['data']
        
        time.sleep(0.5)  # Добавляем задержку между запросами
        files = drive_service.files().list(
            q="mimeType='application/vnd.google-apps.spreadsheet'",
            fields='files(id, name)'
        ).execute()
        
        sheets_cache['drive_files'] = {
            'timestamp': current_time,
            'data': files.get('files', [])
        }
        return sheets_cache['drive_files']['data']
    except Exception as e:
        logging.error(f"Error getting drive files: {str(e)}")
        return sheets_cache.get('drive_files', {}).get('data', []) if 'drive_files' in sheets_cache else []

def get_cached_sheets(spreadsheet_id):
    try:
        cache_key = f'sheets_{spreadsheet_id}'
        current_time = time.time()
        if cache_key in sheets_cache and current_time - sheets_cache[cache_key]['timestamp'] < CACHE_TIMEOUT:
            return sheets_cache[cache_key]['data']
        
        time.sleep(0.5)  # Добавляем задержку между запросами
        result = sheets_service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields='sheets.properties.title'
        ).execute()
        
        sheets_cache[cache_key] = {
            'timestamp': current_time,
            'data': result.get('sheets', [])
        }
        return sheets_cache[cache_key]['data']
    except Exception as e:
        logging.error(f"Error getting sheets for {spreadsheet_id}: {str(e)}")
        return sheets_cache.get(f'sheets_{spreadsheet_id}', {}).get('data', []) if f'sheets_{spreadsheet_id}' in sheets_cache else []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало работы с ботом"""
    user_id = update.effective_user.id
    user_data[user_id] = {
        'step': 'phone',
        'inventory_data': {}
    }
    
    keyboard = [[InlineKeyboardButton("📝 Начать новую инвентаризацию", callback_data="new_inventory")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Добро пожаловать! Выберите действие:",
        reply_markup=reply_markup
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка callback запросов"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if query.data == "new_inventory":
        await start_new_inventory(update, context)
    elif query.data.startswith("warehouse_"):
        await handle_warehouse_selection(update, context)
    elif query.data.startswith("confirm_warehouse_"):
        await handle_warehouse_confirmation(update, context)
    elif query.data == "back_to_categories":
        user_data[user_id]['step'] = 'selecting_category'
        user_data[user_id]['category_path'] = []  # Сбрасываем путь категории
        
        # Отправляем новое сообщение с категориями
        reply_markup = get_product_category_keyboard(user_id)
        message = await query.message.reply_text(
            "Выберите категорию продукта:",
            reply_markup=reply_markup
        )
        user_data[user_id]['last_category_message_id'] = message.message_id
        
        await query.message.delete()
        await query.answer()
    elif query.data == "back_to_warehouse":
        # Возвращаемся к выбору склада
        user_data[user_id]['step'] = 'warehouse'
        await query.message.edit_text(
            "Выберите склад:",
            reply_markup=get_warehouse_keyboard()
        )
    elif query.data == "back_category":
        # Восстанавливаем предыдущий путь категории, если он был сохранен
        if 'previous_category_path' in user_data[user_id]:
            user_data[user_id]['category_path'] = user_data[user_id]['previous_category_path']
            del user_data[user_id]['previous_category_path']  # Очищаем сохраненный путь
            reply_markup = get_product_category_keyboard(user_id)
            await query.message.edit_text(
                "Выберите категорию продукта:",
                reply_markup=reply_markup
            )
        # Если нет сохраненного пути, возвращаемся на уровень выше
        elif 'category_path' in user_data[user_id] and user_data[user_id]['category_path']:
            user_data[user_id]['category_path'].pop()
            reply_markup = get_product_category_keyboard(user_id)
            await query.message.edit_text(
                "Выберите категорию продукта:",
                reply_markup=reply_markup
            )
        else:
            # Если мы находимся в корневом меню категорий, возвращаемся к выбору склада
            user_data[user_id]['step'] = 'warehouse'
            await query.message.edit_text(
                "Выберите склад:",
                reply_markup=get_warehouse_keyboard()
            )
    elif query.data.startswith("category_"):
        category_index = int(query.data[9:])
        categories = list(PRODUCT_CATEGORIES.keys())
        category = categories[category_index]
        
        # Инициализируем или очищаем путь категории
        user_data[user_id]['category_path'] = [category]
        user_data[user_id]['current_category'] = category
        user_data[user_id]['step'] = 'selecting_product'
        
        reply_markup = get_product_category_keyboard(user_id)
        await query.message.edit_text(
            f"Категория {category}:",
            reply_markup=reply_markup
        )
    elif query.data.startswith("subcat_"):
        _, index, subcat_name = query.data.split('_')
        
        # Добавляем подкатегорию в путь
        if 'category_path' not in user_data[user_id]:
            user_data[user_id]['category_path'] = []
        user_data[user_id]['category_path'].append(subcat_name)
        
        reply_markup = get_product_category_keyboard(user_id)
        await query.message.edit_text(
            f"Подкатегория {subcat_name}:",
            reply_markup=reply_markup
        )
    elif query.data == "confirm_save":
        await finish_inventory(update, context)
    elif query.data == "cancel_save":
        # Удаляем сообщение с итогами
        try:
            if 'summary_message_id' in user_data[user_id]:
                await context.bot.delete_message(
                    chat_id=query.message.chat_id,
                    message_id=user_data[user_id]['summary_message_id']
                )
        except Exception as e:
            logging.error(f"Error deleting summary message: {str(e)}")
        
        # Очищаем данные пользователя
        if user_id in user_data:
            del user_data[user_id]
        
        # Отправляем сообщение об отмене
        await query.message.reply_text(
            "❌ Инвентаризация отменена",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 Начать новую", callback_data="new_inventory")
            ]])
        )
    elif query.data == "finish":
        await show_inventory_summary(update, context)
    elif query.data.startswith("product_"):
        product_index = int(query.data[8:])
        
        # Получаем текущую категорию на основе пути
        current_category = PRODUCT_CATEGORIES
        for path_item in user_data[user_id]['category_path']:
            if isinstance(current_category, dict) and 'subcategories' in current_category:
                current_category = current_category['subcategories'][path_item]
            else:
                current_category = current_category[path_item]
        
        # Получаем список товаров
        items = current_category.get('items', []) if isinstance(current_category, dict) else current_category
        product = items[product_index]
        
        user_data[user_id]['current_product'] = product
        user_data[user_id]['step'] = 'entering_quantity'
        
        # Отправляем сообщение и сохраняем его ID
        message = await query.message.edit_text(
            f"Введите количество для {product}:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="back_category")
            ]])
        )
        user_data[user_id]['quantity_request_message_id'] = message.message_id
    elif query.data == "back_to_products":
        user_data[user_id]['step'] = 'selecting_product'
        await show_products(update, context)
    else:
        await query.answer("Неизвестная команда")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    user_id = update.effective_user.id
    message_text = update.message.text
    
    if user_id not in user_data:
        user_data[user_id] = {
            'step': 'phone',
            'inventory_data': {}
        }
    
    current_step = user_data[user_id]['step']
    
    if current_step == 'name':
        user_data[user_id]['name'] = message_text
        user_data[user_id]['date'] = datetime.now().strftime("%Y-%m-%d")
        user_data[user_id]['step'] = 'warehouse'
        await update.message.reply_text(
            "Выберите склад:", 
            reply_markup=get_warehouse_keyboard()
        )
    elif current_step == 'entering_quantity':
        try:
            quantity = float(message_text)
            if quantity < 0:
                await update.message.reply_text("Пожалуйста, введите положительное число:")
                return
                
            product = user_data[user_id]['current_product']
            user_data[user_id]['inventory_data'][product] = quantity
            user_data[user_id]['step'] = 'selecting_category'
            
            # Сохраняем ID сообщения с введенным количеством
            user_data[user_id]['quantity_message_id'] = update.message.message_id
            
            # Удаляем предыдущее сообщение с категориями, если оно есть
            try:
                if 'last_category_message_id' in user_data[user_id]:
                    await context.bot.delete_message(
                        chat_id=update.message.chat_id,
                        message_id=user_data[user_id]['last_category_message_id']
                    )
            except Exception as e:
                logging.error(f"Error deleting previous category message: {str(e)}")
            
            # Удаляем сообщение с запросом количества
            try:
                if 'quantity_request_message_id' in user_data[user_id]:
                    await context.bot.delete_message(
                        chat_id=update.message.chat_id,
                        message_id=user_data[user_id]['quantity_request_message_id']
                    )
            except Exception as e:
                logging.error(f"Error deleting quantity request message: {str(e)}")
            
            # Удаляем сообщение с введенным количеством
            try:
                await update.message.delete()
            except Exception as e:
                logging.error(f"Error deleting quantity message: {str(e)}")
            
            # Отправляем сообщение с категориями
            reply_markup = get_product_category_keyboard(user_id)
            message = await update.message.reply_text(
                f"✅ Количество для {product} сохранено: {quantity}\n\nВыберите следующую категорию продукта:",
                reply_markup=reply_markup
            )
            # Сохраняем ID нового сообщения с категориями
            user_data[user_id]['last_category_message_id'] = message.message_id
            
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите корректное число:")

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка получения контакта"""
    user_id = update.effective_user.id
    contact = update.message.contact
    
    if user_id not in user_data or user_data[user_id]['step'] != 'phone':
        return
    
    # Сохраняем номер телефона
    user_data[user_id]['phone'] = contact.phone_number
    user_data[user_id]['step'] = 'name'
    
    # Убираем клавиатуру с кнопкой "Поделиться номером"
    await update.message.reply_text(
        "Пожалуйста, введите Ваши Фамилию и Имя:",
        reply_markup=ReplyKeyboardRemove()
    )

async def show_history_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать меню истории инвентаризаций"""
    try:
        if not context.user_data.get('selected_warehouse'):
            await update.message.reply_text(
                "Пожалуйста, сначала выберите склад.",
                reply_markup=ReplyKeyboardMarkup([['Выбрать склад']], resize_keyboard=True)
            )
            return

        warehouse_name = context.user_data['selected_warehouse']
        
        # Получаем список файлов из кэша
        files = get_cached_drive_files()
        
        # Ищем нужный файл
        spreadsheet = next((file for file in files if file['name'] == warehouse_name), None)
        if not spreadsheet:
            await update.message.reply_text(
                f"Не найден файл для склада {warehouse_name}",
                reply_markup=ReplyKeyboardMarkup([['Выбрать склад']], resize_keyboard=True)
            )
            return

        # Получаем список листов из кэша
        sheets = get_cached_sheets(spreadsheet['id'])
        
        if not sheets:
            keyboard = [[InlineKeyboardButton("Начать новую", callback_data="new_inventory")]]
            await update.message.reply_text(
                "История инвентаризаций пуста.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Создаем клавиатуру с кнопками для каждого листа
        keyboard = []
        for i, sheet in enumerate(sheets):
            sheet_title = sheet['properties']['title']
            if sheet_title.startswith('Инвентаризация_'):
                date_str = sheet_title.split('_')[1]
                button = InlineKeyboardButton(
                    f"📋 {date_str}",
                    callback_data=f"h{i}"
                )
                keyboard.append([button])

        # Добавляем кнопку "Начать новую"
        keyboard.append([InlineKeyboardButton("Начать новую", callback_data="new_inventory")])

        # Сохраняем mapping для callback
        context.bot_data['sheet_mapping'] = {
            f"h{i}": sheet['properties']['title']
            for i, sheet in enumerate(sheets)
        }
        context.bot_data['current_spreadsheet_id'] = spreadsheet['id']

        await update.message.reply_text(
            f"📊 История инвентаризаций для склада {warehouse_name}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logging.error(f"Error in show_history_menu: {str(e)}")
        await update.message.reply_text(
            "Произошла ошибка при получении истории инвентаризаций. Пожалуйста, попробуйте позже."
        )

async def show_inventory_details(update: Update, context: ContextTypes.DEFAULT_TYPE, spreadsheet_id, sheet_title):
    """Показать детали инвентаризации"""
    sheets_service = get_google_sheets_service()
    
    # Получаем данные с листа
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_title}!A1:C50"
    ).execute()
    
    values = result.get('values', [])
    if not values:
        await update.message.reply_text(
            "Данные не найдены.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="view_history")]])
        )
        return
    
    # Форматируем сообщение
    message_parts = []
    
    # Добавляем заголовок
    try:
        date_str = sheet_title.split('_')[1]
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        formatted_date = date_obj.strftime('%d.%m.%Y')
        message_parts.append(f"📊 Инвентаризация от {formatted_date}\n")
    except (IndexError, ValueError):
        message_parts.append("📊 Инвентаризация\n")
    
    # Добавляем информацию о складе и ответственном лице
    warehouse_info = values[0][0] if len(values) > 0 and len(values[0]) > 0 else "Не указан"
    responsible_person = values[1][0] if len(values) > 1 and len(values[1]) > 0 else "Не указан"
    phone = values[2][0] if len(values) > 2 and len(values[2]) > 0 else "Не указан"
    
    message_parts.append(f"🏭 Склад: {warehouse_info}")
    message_parts.append(f"👤 Ответственное лицо: {responsible_person}")
    message_parts.append(f"📱 Телефон: {phone}\n")
    
    # Добавляем заголовок таблицы
    message_parts.append("📝 Результаты инвентаризации:")
    message_parts.append("№  |  Продукт  |  Количество")
    message_parts.append("-" * 40)
    
    # Добавляем данные о продуктах
    for i, row in enumerate(values[5:], 1):  # Пропускаем первые 5 строк (заголовки)
        if len(row) >= 2:
            product = row[1] if len(row) > 1 else ""
            quantity = row[2] if len(row) > 2 else ""
            message_parts.append(f"{i}. {product}: {quantity}")
    
    # Объединяем все части сообщения
    message = "\n".join(message_parts)
    
    # Добавляем кнопку "Назад"
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="view_history")]]
    
    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def start_edit_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования инвентаризации"""
    query = update.callback_query
    user_id = query.from_user.id
    sheet_title = query.data.split('_')[1]
    
    service = get_google_sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{sheet_title}!A1:E"
    ).execute()
    
    values = result.get('values', [])
    if not values:
        await query.edit_message_text("Данные не найдены.")
        return
    
    user_data[user_id]['editing_sheet'] = sheet_title
    user_data[user_id]['inventory_data'] = {}
    
    # Пропускаем заголовки
    for row in values[5:]:
        if len(row) >= 2:
            user_data[user_id]['inventory_data'][row[0]] = row[1]
    
    await query.edit_message_text(
        "Выберите категорию продукта для редактирования:",
        reply_markup=get_product_category_keyboard(user_id)
    )

async def handle_warehouse_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора склада"""
    query = update.callback_query
    user_id = query.from_user.id
    warehouse_index = int(query.data.split('_')[1])
    
    # Получаем оригинальное название склада по индексу
    original_warehouse = WAREHOUSES[warehouse_index]
    
    # Создаем клавиатуру для подтверждения
    keyboard = [
        [
            InlineKeyboardButton("✅ Да", callback_data=f"confirm_warehouse_{warehouse_index}"),
            InlineKeyboardButton("❌ Нет", callback_data="back_to_warehouse")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"Вы выбрали склад: {original_warehouse}\n\nПодтвердите ваш выбор:",
        reply_markup=reply_markup
    )

async def handle_warehouse_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка подтверждения выбора склада"""
    query = update.callback_query
    user_id = query.from_user.id
    warehouse_index = int(query.data.split('_')[2])
    
    # Получаем оригинальное название склада по индексу
    original_warehouse = WAREHOUSES[warehouse_index]
    
    user_data[user_id]['warehouse'] = original_warehouse
    user_data[user_id]['warehouse_index'] = warehouse_index  # Сохраняем индекс для кнопки "Назад"
    user_data[user_id]['step'] = 'product_category'
    
    # Отправляем сообщение с категориями и сохраняем его ID
    message = await query.edit_message_text(
        f"Склад {original_warehouse} выбран.\nВыберите категорию продукта:",
        reply_markup=get_product_category_keyboard(user_id)
    )
    user_data[user_id]['last_category_message_id'] = message.message_id

def get_warehouse_keyboard():
    """Создание клавиатуры со складами"""
    keyboard = []
    for i, warehouse in enumerate(WAREHOUSES):
        keyboard.append([InlineKeyboardButton(
            f"🏭 {warehouse}",
            callback_data=f"warehouse_{i}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="new_inventory")])
    return InlineKeyboardMarkup(keyboard)

def get_product_category_keyboard(user_id):
    """Создание клавиатуры с категориями продуктов"""
    keyboard = []
    
    # Получаем текущий путь категории из user_data
    current_category_path = user_data.get(user_id, {}).get('category_path', [])
    
    if not current_category_path:
        # Показываем корневые категории
        categories = list(PRODUCT_CATEGORIES.keys())
        category_emojis = {
            "Фрукты": "🍎",
            "Овощи": "🥕",
            "Мясо и мясные продукты": "🥩",
            "Молочные продукты": "🥛",
            "Крупы и бобовые": "🫛",
            "Мука и выпечка": "🍞",
            "Консервы": "🥫",
            "Напитки": "🥤",
            "Специи и приправы": "🧂",
            "Сладости и сухофрукты": "🍬",
            "Орехи семена": "🥜",
            "Бакалея": "🧈",
            "Магазин/Буфет": "🏪"
        }
        
        for i, category in enumerate(categories):
            emoji = category_emojis.get(category, "📦")
            keyboard.append([InlineKeyboardButton(
                f"{emoji} {category}",
                callback_data=f"category_{i}"
            )])
    else:
        # Показываем подкатегории и товары текущей категории
        current_category = PRODUCT_CATEGORIES
        for path_item in current_category_path:
            if isinstance(current_category, dict) and 'subcategories' in current_category:
                current_category = current_category['subcategories'][path_item]
            else:
                current_category = current_category[path_item]
        
        # Добавляем подкатегории
        if isinstance(current_category, dict) and 'subcategories' in current_category:
            for i, (subcat_name, _) in enumerate(current_category['subcategories'].items()):
                keyboard.append([InlineKeyboardButton(
                    f"📁 {subcat_name}",
                    callback_data=f"subcat_{i}_{subcat_name}"
                )])
        
        # Добавляем товары
        items = current_category.get('items', []) if isinstance(current_category, dict) else current_category
        for i, item in enumerate(items):
            keyboard.append([InlineKeyboardButton(
                f"📦 {item}",
                callback_data=f"product_{i}"
            )])
    
    # Добавляем кнопки навигации
    keyboard.append([InlineKeyboardButton("✅ Завершить инвентаризацию", callback_data="finish")])
    if current_category_path:
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_category")])
    else:
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_warehouse")])
    
    return InlineKeyboardMarkup(keyboard)

async def handle_product_category_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора категории продукта"""
    query = update.callback_query
    user_id = query.from_user.id
    category_index = int(query.data.split('_')[1])
    
    # Получаем оригинальное название категории по индексу
    categories = list(PRODUCT_CATEGORIES.keys())
    category = categories[category_index]
    
    user_data[user_id]['current_category'] = category
    user_data[user_id]['step'] = 'product'
    await query.edit_message_text("Выберите продукт:", reply_markup=get_product_keyboard(category))

def get_product_keyboard(category):
    """Создание клавиатуры с продуктами"""
    keyboard = []
    products = PRODUCT_CATEGORIES[category]
    for i, product in enumerate(products):
        keyboard.append([InlineKeyboardButton(
            f"📦 {product}",
            callback_data=f"product_{category}_{i}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="category")])
    return InlineKeyboardMarkup(keyboard)

async def handle_product_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора продукта"""
    query = update.callback_query
    user_id = query.from_user.id
    _, category, product_index = query.data.split('_')
    product_index = int(product_index)
    
    # Получаем оригинальное название продукта по индексу
    product = PRODUCT_CATEGORIES[category][product_index]
    
    user_data[user_id]['current_product'] = product
    user_data[user_id]['step'] = 'quantity'
    await query.edit_message_text(f"Введите количество остатка для продукта {product}:")

async def show_inventory_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать итоги инвентаризации перед сохранением"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Сохраняем текущий путь категории перед показом итогов
    if 'category_path' not in user_data[user_id]:
        user_data[user_id]['category_path'] = []
    
    # Сохраняем предыдущий путь для возврата
    user_data[user_id]['previous_category_path'] = user_data[user_id]['category_path'].copy()
    
    # Формируем сообщение с итогами
    message_parts = []
    
    # Добавляем заголовок
    message_parts.append("📊 Итоги инвентаризации")
    message_parts.append("=" * 40)
    
    # Добавляем информацию о складе и ответственном лице
    message_parts.append(f"🏭 Склад: {user_data[user_id]['warehouse']}")
    message_parts.append(f"👤 Ответственное лицо: {user_data[user_id]['name']}")
    message_parts.append(f"📱 Телефон: {user_data[user_id]['phone']}")
    message_parts.append(f"📅 Дата: {user_data[user_id]['date']}")
    message_parts.append("=" * 40)
    
    # Добавляем заголовок таблицы
    message_parts.append("📝 Результаты инвентаризации:")
    message_parts.append("№  |  Продукт  |  Количество")
    message_parts.append("-" * 40)
    
    # Добавляем данные о продуктах
    counter = 1
    for product, quantity in user_data[user_id]['inventory_data'].items():
        message_parts.append(f"{counter}. {product} | {quantity}")
        counter += 1
    
    # Объединяем все части сообщения
    message = "\n".join(message_parts)
    
    # Создаем клавиатуру для подтверждения
    keyboard = [
        [
            InlineKeyboardButton("✅ Сохранить", callback_data="confirm_save"),
            InlineKeyboardButton("⬅️ Назад", callback_data="back_category")
        ]
    ]
    
    try:
        # Удаляем сообщение с категориями
        if 'category_message_id' in user_data[user_id]:
            await context.bot.delete_message(
                chat_id=query.message.chat_id,
                message_id=user_data[user_id]['category_message_id']
            )
    except Exception as e:
        logging.error(f"Error deleting category message: {str(e)}")
    
    # Отправляем новое сообщение с итогами и сохраняем его ID
    summary_message = await query.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    user_data[user_id]['summary_message_id'] = summary_message.message_id
    
    # Удаляем текущее сообщение
    try:
        await query.message.delete()
    except Exception as e:
        logging.error(f"Error deleting current message: {str(e)}")
    
    # Отвечаем на callback query, чтобы убрать "часики" на кнопке
    await query.answer()

async def finish_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершение инвентаризации и сохранение данных"""
    query = update.callback_query
    user_id = query.from_user.id
    
    sheets_service = get_google_sheets_service()
    drive_service = get_drive_service()
    
    # Получаем или создаем таблицу для склада
    spreadsheet_id = get_or_create_spreadsheet(
        sheets_service,
        drive_service,
        user_data[user_id]['warehouse']
    )
    
    if 'editing_sheet' in user_data[user_id]:
        # Редактируем существующую инвентаризацию
        sheet_title = user_data[user_id]['editing_sheet']
        success = save_inventory_data(
            sheets_service,
            spreadsheet_id,
            user_data[user_id]['warehouse'],
            user_data[user_id]['date'],
            user_data[user_id]['name'],
            user_data[user_id]['phone'],
            user_data[user_id]['inventory_data']
        )
    else:
        # Создаем новую инвентаризацию
        success = create_new_sheet(
            sheets_service,
            spreadsheet_id,
            user_data[user_id]['warehouse'],
            user_data[user_id]['date']
        )
        if success:
            success = save_inventory_data(
                sheets_service,
                spreadsheet_id,
                user_data[user_id]['warehouse'],
                user_data[user_id]['date'],
                user_data[user_id]['name'],
                user_data[user_id]['phone'],
                user_data[user_id]['inventory_data']
            )
    
    if success:
        # Формируем сообщение с итогами
        message_parts = []
        message_parts.append("📊 Итоги инвентаризации")
        message_parts.append("=" * 40)
        message_parts.append(f"🏭 Склад: {user_data[user_id]['warehouse']}")
        message_parts.append(f"👤 Ответственное лицо: {user_data[user_id]['name']}")
        message_parts.append(f"📱 Телефон: {user_data[user_id]['phone']}")
        message_parts.append(f"📅 Дата: {user_data[user_id]['date']}")
        message_parts.append("=" * 40)
        message_parts.append("📝 Результаты инвентаризации:")
        message_parts.append("№  |  Продукт  |  Количество")
        message_parts.append("-" * 40)
        
        counter = 1
        for product, quantity in user_data[user_id]['inventory_data'].items():
            message_parts.append(f"{counter}. {product} | {quantity}")
            counter += 1
        
        message = "\n".join(message_parts)
        
        try:
            # Удаляем сообщение с итогами и кнопками подтверждения
            if 'summary_message_id' in user_data[user_id]:
                await context.bot.delete_message(
                    chat_id=query.message.chat_id,
                    message_id=user_data[user_id]['summary_message_id']
                )
        except Exception as e:
            logging.error(f"Error deleting summary message: {str(e)}")
        
        # Отправляем итоговое сообщение как постоянное сообщение в чат
        await query.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Начать новую", callback_data="new_inventory")]])
        )
        
        # Отвечаем на callback query
        await query.answer("✅ Инвентаризация успешно завершена!")
    else:
        await query.edit_message_text(
            "❌ Произошла ошибка при сохранении данных. Пожалуйста, попробуйте снова.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Начать новую", callback_data="new_inventory")]])
        )

async def start_new_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало новой инвентаризации"""
    query = update.callback_query
    user_id = query.from_user.id
    
    user_data[user_id] = {
        'step': 'phone',
        'inventory_data': {}
    }
    
    keyboard = [[KeyboardButton("Поделиться номером", request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await query.message.reply_text(
        "Для начала работы, пожалуйста, поделитесь вашим номером телефона.",
        reply_markup=reply_markup
    )
    await query.answer()

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список продуктов выбранной категории"""
    query = update.callback_query
    user_id = query.from_user.id
    category = user_data[user_id]['current_category']
    
    keyboard = []
    for i, product in enumerate(PRODUCT_CATEGORIES[category]):
        keyboard.append([InlineKeyboardButton(
            f"📦 {product}",
            callback_data=f"product_{i}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_categories")])
    
    await query.edit_message_text(
        f"Выберите продукт из категории {category}:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def main():
    """Запуск бота"""
    # Перемещаем существующие файлы в папку при запуске
    try:
        drive_service = get_drive_service()
        move_existing_files_to_folder(drive_service)
    except Exception as e:
        logging.error(f"Error moving existing files: {str(e)}")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main() 
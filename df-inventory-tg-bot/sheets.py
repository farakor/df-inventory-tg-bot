import os
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'service-account-key.json')

def get_google_sheets_service():
    """Получение сервиса Google Sheets"""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=SCOPES
        )
        return build('sheets', 'v4', credentials=credentials)
    except Exception as e:
        logging.error(f"Error creating sheets service: {str(e)}")
        raise

def get_drive_service():
    """Получение сервиса Google Drive"""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=SCOPES
        )
        return build('drive', 'v3', credentials=credentials)
    except Exception as e:
        logging.error(f"Error creating drive service: {str(e)}")
        raise

def get_or_create_folder(drive_service, folder_name="Инвентаризации ДФ Сервис"):
    """Получить или создать папку в Google Drive"""
    try:
        logging.info(f"Поиск папки '{folder_name}' в Google Drive")
        # Проверяем, существует ли папка
        results = drive_service.files().list(
            q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id, name)"
        ).execute()
        folders = results.get('files', [])
        
        if folders:
            logging.info(f"Папка '{folder_name}' найдена с ID: {folders[0]['id']}")
            # Папка существует, возвращаем её ID
            return folders[0]['id']
        else:
            logging.info(f"Папка '{folder_name}' не найдена, создаем новую")
            # Создаем новую папку
            folder_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = drive_service.files().create(
                body=folder_metadata,
                fields='id'
            ).execute()
            logging.info(f"Создана новая папка с ID: {folder.get('id')}")
            return folder.get('id')
    except Exception as e:
        logging.error(f"Ошибка при создании/поиске папки: {str(e)}")
        raise

def get_or_create_spreadsheet(sheets_service, drive_service, warehouse_name):
    """Получить или создать таблицу для склада"""
    try:
        logging.info(f"Поиск или создание таблицы для склада '{warehouse_name}'")
        # Получаем или создаем папку
        folder_id = get_or_create_folder(drive_service)
        logging.info(f"Получен ID папки: {folder_id}")
        
        # Ищем существующую таблицу в папке
        results = drive_service.files().list(
            q=f"name='{warehouse_name}' and mimeType='application/vnd.google-apps.spreadsheet' and '{folder_id}' in parents and trashed=false",
            fields="files(id, name)"
        ).execute()
        files = results.get('files', [])
        
        if files:
            logging.info(f"Найдена существующая таблица с ID: {files[0]['id']}")
            # Таблица существует
            return files[0]['id']
        
        logging.info("Создание новой таблицы")
        # Создаем новую таблицу
        spreadsheet = {
            'properties': {
                'title': warehouse_name
            }
        }
        spreadsheet = sheets_service.spreadsheets().create(
            body=spreadsheet,
            fields='spreadsheetId'
        ).execute()
        
        # Перемещаем таблицу в папку
        file_id = spreadsheet.get('spreadsheetId')
        logging.info(f"Создана новая таблица с ID: {file_id}")
        
        file = drive_service.files().get(
            fileId=file_id,
            fields='parents'
        ).execute()
        previous_parents = ",".join(file.get('parents', []))
        
        # Перемещаем файл в нужную папку
        drive_service.files().update(
            fileId=file_id,
            addParents=folder_id,
            removeParents=previous_parents,
            fields='id, parents'
        ).execute()
        logging.info(f"Таблица перемещена в папку {folder_id}")
        
        return file_id
    except Exception as e:
        logging.error(f"Ошибка при создании/поиске таблицы: {str(e)}")
        raise

def get_next_sheet_number(service, spreadsheet_id, base_title):
    """Получает следующий доступный номер для листа с указанным базовым названием"""
    try:
        # Получаем список всех листов в таблице
        spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = spreadsheet.get('sheets', [])
        
        # Создаем список существующих номеров для данного базового названия
        existing_numbers = []
        for sheet in sheets:
            title = sheet['properties']['title']
            if title.startswith(base_title):
                try:
                    # Пытаемся извлечь номер из названия
                    num = int(title.split('_')[-1])
                    existing_numbers.append(num)
                except (ValueError, IndexError):
                    # Если нет номера, считаем это первым листом
                    existing_numbers.append(1)
        
        if not existing_numbers:
            return 1
        
        # Возвращаем следующий номер
        return max(existing_numbers) + 1
    except Exception as e:
        print(f"Ошибка при получении следующего номера листа: {e}")
        return 1

def create_new_sheet(service, spreadsheet_id, warehouse, date):
    """Создает новый лист для инвентаризации"""
    try:
        # Формируем базовое название листа
        base_title = f"Инвентаризация {date}"
        
        # Получаем следующий доступный номер для листа
        next_number = get_next_sheet_number(service, spreadsheet_id, base_title)
        
        # Формируем полное название листа
        sheet_title = f"{base_title}_{next_number}"
        
        # Создаем новый лист
        body = {
            'requests': [{
                'addSheet': {
                    'properties': {
                        'title': sheet_title
                    }
                }
            }]
        }
        
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        ).execute()
        
        # Получаем ID созданного листа
        sheet_id = response['replies'][0]['addSheet']['properties']['sheetId']
        
        # Форматируем заголовки
        headers = [
            ['Продукт', 'Количество', 'Единица измерения']
        ]
        
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_title}!A1:C1",
            valueInputOption='RAW',
            body={'values': headers}
        ).execute()
        
        # Устанавливаем ширину столбцов
        column_widths = [
            {'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 1, 'pixelSize': 200},
            {'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': 1, 'endIndex': 2, 'pixelSize': 100},
            {'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': 2, 'endIndex': 3, 'pixelSize': 150}
        ]
        
        body = {
            'requests': [{
                'updateDimensionProperties': {
                    'range': {
                        'sheetId': sheet_id,
                        'dimension': 'COLUMNS',
                        'startIndex': i,
                        'endIndex': i + 1
                    },
                    'properties': {
                        'pixelSize': width['pixelSize']
                    },
                    'fields': 'pixelSize'
                }
            } for i, width in enumerate(column_widths)]
        }
        
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        ).execute()
        
        return True
    except Exception as e:
        print(f"Ошибка при создании нового листа: {e}")
        return False

def save_inventory_data(service, spreadsheet_id, warehouse_name, date, user_name, phone, inventory_data):
    """Сохранение данных инвентаризации в таблицу"""
    try:
        logging.info(f"Начало сохранения данных для склада {warehouse_name}")
        # Получаем название последнего созданного листа для этой даты
        base_title = f"Инвентаризация {date}"
        next_number = get_next_sheet_number(service, spreadsheet_id, base_title)
        sheet_title = f"{base_title}_{next_number-1}"  # Используем текущий лист
        logging.info(f"Используем лист: {sheet_title}")
        
        # Подготовка данных для записи
        header_values = [
            [f"Инвентаризация склада: {warehouse_name}"],
            [f"Материально ответственное лицо: {user_name}"],
            [f"Телефон: {phone}"],
            [f"Дата: {date}"],
            [""],  # Пустая строка для разделения
            ["№", "Продукт", "Количество остатка", "Единица измерения"]  # Заголовки с нумерацией
        ]
        
        # Добавление данных о продуктах с нумерацией
        product_values = []
        for i, (product, quantity) in enumerate(inventory_data.items(), 1):
            # Извлекаем единицу измерения из названия продукта
            unit = ""
            if "[" in product and "]" in product:
                unit = product[product.find("[")+1:product.find("]")]
                product = product[:product.find("[")].strip()
            product_values.append([i, product, quantity, unit])
        
        values = header_values + product_values
        logging.info(f"Подготовлено {len(values)} строк данных для записи")
        
        # Обновляем данные на листе
        logging.info("Начинаем запись данных в таблицу")
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_title}!A1:D{len(values)}",
            valueInputOption='RAW',
            body={'values': values}
        ).execute()
        logging.info("Данные успешно записаны в таблицу")
        
        # Получаем ID листа для форматирования
        logging.info("Получаем ID листа для форматирования")
        sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheet_id = None
        for sheet in sheet_metadata.get('sheets', ''):
            if sheet['properties']['title'] == sheet_title:
                sheet_id = sheet['properties']['sheetId']
                break
        
        if sheet_id:
            logging.info(f"Найден ID листа: {sheet_id}")
            # Форматирование таблицы
            requests = [
                # Объединяем ячейки в заголовке для каждой строки информации
                {
                    'mergeCells': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': i,
                            'endRowIndex': i + 1,
                            'startColumnIndex': 0,
                            'endColumnIndex': 4
                        },
                        'mergeType': 'MERGE_ALL'
                    }
                } for i in range(5)  # Для первых 5 строк (заголовок и информация)
            ]
            
            # Добавляем остальные запросы форматирования
            requests.extend([
                # Устанавливаем границы для всей таблицы
                {
                    'updateBorders': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 0,
                            'endRowIndex': len(values),
                            'startColumnIndex': 0,
                            'endColumnIndex': 4
                        },
                        'top': {'style': 'SOLID', 'width': 1},
                        'bottom': {'style': 'SOLID', 'width': 1},
                        'left': {'style': 'SOLID', 'width': 1},
                        'right': {'style': 'SOLID', 'width': 1},
                        'innerHorizontal': {'style': 'SOLID', 'width': 1},
                        'innerVertical': {'style': 'SOLID', 'width': 1}
                    }
                },
                # Устанавливаем ширину столбцов
                {
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': sheet_id,
                            'dimension': 'COLUMNS',
                            'startIndex': 0,
                            'endIndex': 1
                        },
                        'properties': {
                            'pixelSize': 50  # Ширина для столбца с номерами
                        },
                        'fields': 'pixelSize'
                    }
                },
                {
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': sheet_id,
                            'dimension': 'COLUMNS',
                            'startIndex': 1,
                            'endIndex': 2
                        },
                        'properties': {
                            'pixelSize': 300  # Ширина для столбца с продуктами
                        },
                        'fields': 'pixelSize'
                    }
                },
                {
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': sheet_id,
                            'dimension': 'COLUMNS',
                            'startIndex': 2,
                            'endIndex': 3
                        },
                        'properties': {
                            'pixelSize': 150  # Ширина для столбца с количеством
                        },
                        'fields': 'pixelSize'
                    }
                },
                {
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': sheet_id,
                            'dimension': 'COLUMNS',
                            'startIndex': 3,
                            'endIndex': 4
                        },
                        'properties': {
                            'pixelSize': 150  # Ширина для столбца с единицами измерения
                        },
                        'fields': 'pixelSize'
                    }
                },
                # Выравнивание текста
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 0,
                            'endRowIndex': len(values),
                            'startColumnIndex': 0,
                            'endColumnIndex': 4
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'horizontalAlignment': 'LEFT',
                                'verticalAlignment': 'MIDDLE',
                                'padding': {'top': 5, 'right': 5, 'bottom': 5, 'left': 5}
                            }
                        },
                        'fields': 'userEnteredFormat(horizontalAlignment,verticalAlignment,padding)'
                    }
                },
                # Выделяем заголовок жирным
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 5,
                            'endRowIndex': 6,
                            'startColumnIndex': 0,
                            'endColumnIndex': 4
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'textFormat': {'bold': True},
                                'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
                            }
                        },
                        'fields': 'userEnteredFormat(textFormat,backgroundColor)'
                    }
                }
            ])
            
            # Применяем форматирование
            logging.info("Применяем форматирование таблицы")
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': requests}
            ).execute()
            logging.info("Форматирование успешно применено")
        else:
            logging.warning("Не удалось найти ID листа для форматирования")
        
        logging.info("Сохранение данных успешно завершено")
        return True
    except Exception as e:
        logging.error(f"Ошибка при сохранении данных: {str(e)}")
        return False

def get_inventory_history(service, spreadsheet_id, warehouse_name):
    """Получение истории инвентаризаций для склада"""
    try:
        sheets = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        history = []
        
        for sheet in sheets.get('sheets', []):
            if sheet['properties']['title'].startswith('Инвентаризация'):
                sheet_title = sheet['properties']['title']
                date = sheet_title.split(' ')[1]
                
                # Получение данных с листа
                result = service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range=f"{sheet_title}!A1:C1"
                ).execute()
                
                values = result.get('values', [])
                if values and values[0][0] == f"Инвентаризация склада: {warehouse_name}":
                    history.append({
                        'date': date,
                        'sheet_title': sheet_title
                    })
        
        return sorted(history, key=lambda x: datetime.strptime(x['date'], '%Y-%m-%d'), reverse=True)
    except Exception as e:
        print(f"Ошибка при получении истории: {e}")
        return []

def move_existing_files_to_folder(drive_service):
    """Переместить существующие файлы инвентаризации в папку"""
    # Получаем или создаем папку
    folder_id = get_or_create_folder(drive_service)
    
    # Получаем список всех таблиц в корневом каталоге
    results = drive_service.files().list(
        q="mimeType='application/vnd.google-apps.spreadsheet' and 'root' in parents and trashed=false",
        fields="files(id, name)"
    ).execute()
    files = results.get('files', [])
    
    for file in files:
        try:
            # Получаем текущих родителей файла
            file_data = drive_service.files().get(
                fileId=file['id'],
                fields='parents'
            ).execute()
            previous_parents = ",".join(file_data.get('parents', []))
            
            # Перемещаем файл в папку
            drive_service.files().update(
                fileId=file['id'],
                addParents=folder_id,
                removeParents=previous_parents,
                fields='id, parents'
            ).execute()
        except Exception as e:
            logging.error(f"Error moving file {file['name']}: {str(e)}")
            continue 
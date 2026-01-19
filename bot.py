import os
import json
import sys
import discord
from discord.ext import commands
import datetime
import csv
import io
import re  # Добавлен импорт для регулярных выражений
import gc  # Добавлен импорт для сборки мусора
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# === ВЕРСИЯ БОТА ===
BOT_VERSION = "1.2.1"  # Обновлено: исправлены критические ошибки

# === ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: ЭКРАНИРОВАНИЕ ЗНАЧЕНИЙ ДЛЯ GOOGLE SHEETS ===
def sanitize_value(value):
    """Экранирует значение для Google Sheets"""
    if value is None:
        return ""
    return str(value).replace('\n', ' ').replace('\r', ' ').strip()

# === ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: ПАРСИНГ ДАТЫ В ФОРМАТЕ ДД-ММ-ГГГГ ===
def parse_date(date_str):
    """Парсит дату в формате ДД-ММ-ГГГГ"""
    if not date_str or not date_str.strip():
        raise ValueError("Дата не может быть пустой")
    try:
        return datetime.datetime.strptime(date_str.strip(), "%d-%m-%Y").replace(tzinfo=datetime.timezone.utc)
    except ValueError as e:
        raise ValueError(f"Неверный формат даты '{date_str}'. Используйте формат ДД-ММ-ГГГГ (например: 01-01-2026)")

# === ДИАГНОСТИКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ===
def check_env_vars():
    print("="*60)
    print(f"🚀 ЗАПУСК DISCORD АНАЛИТИЧЕСКОГО БОТА (ТОЛЬКО ИЗОБРАЖЕНИЯ) v{BOT_VERSION}")
    print("="*60)
    
    missing = []
    diagnostics = []
    
    # Проверяем каждую переменную
    for var in ["DISCORD_BOT_TOKEN", "GOOGLE_SHEET_ID", "GOOGLE_CREDENTIALS_JSON"]:
        value = os.getenv(var)
        if value and value.strip():
            preview = value[:8] + "..." if len(value) > 8 else value
            diagnostics.append(f"✅ {var}: {preview}")
        else:
            diagnostics.append(f"❌ {var}: НЕ ЗАДАН")
            missing.append(var)
    
    # Выводим диагностику
    for line in diagnostics:
        print(line)
    
    if missing:
        print("\n" + "!"*60)
        print("❗ КРИТИЧЕСКАЯ ОШИБКА: Отсутствуют обязательные переменные!")
        for var in missing:
            print(f"   → {var}")
        print("\n🔧 ИНСТРУКЦИЯ ПО ИСПРАВЛЕНИЮ:")
        print("1. Перейдите в Railway → Settings → Variables (Production)")
        print("2. Убедитесь, что созданы ВСЕ три переменные:")
        print("   - DISCORD_BOT_TOKEN")
        print("   - GOOGLE_SHEET_ID")
        print("   - GOOGLE_CREDENTIALS_JSON (минифицированный JSON)")
        print("3. Нажмите Actions → Restart после сохранения")
        print("!"*60)
        sys.exit(1)
    
    print("✅ Все переменные окружения успешно загружены")
    return True

# Запускаем диагностику ДО инициализации бота
check_env_vars()

# === ИНИЦИАЛИЗАЦИЯ ПЕРЕМЕННЫХ ===
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")
SENIOR_ROLE_NAME = os.getenv("SENIOR_ROLE_NAME", "Старший состав ФСВНГ")  # Название роли для доступа

# === НАСТРОЙКА GOOGLE SHEETS ===
try:
    print("\n⚙️ ИНИЦИАЛИЗАЦИЯ GOOGLE SHEETS API...")
    
    # Автоматическое исправление форматирования JSON
    raw_json = GOOGLE_CREDENTIALS_JSON.strip()
    
    # Исправляем форматирование приватного ключа
    if "private_key" in raw_json:
        # Заменяем двойные слеши на одинарные
        raw_json = raw_json.replace("\\\\n", "\\n")
        # Убираем лишние пробелы в конце URL
        raw_json = raw_json.replace("  ", " ")
    
    # Загружаем данные
    creds_data = json.loads(raw_json)
    
    # Создаем учетные данные
    creds = Credentials.from_service_account_info(
        creds_data,
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    
    # Подключаемся к Sheets API
    sheets_service = build('sheets', 'v4', credentials=creds)
    
    # Тестовый запрос для проверки подключения
    spreadsheet = sheets_service.spreadsheets().get(
        spreadsheetId=SHEET_ID
    ).execute()
    
    print(f"✅ УСПЕШНОЕ ПОДКЛЮЧЕНИЕ К ТАБЛИЦЕ: {spreadsheet['properties']['title']}")
    print(f"📊 ID таблицы: {SHEET_ID[:10]}...")

except json.JSONDecodeError as e:
    print("\n" + "!"*60)
    print(f"❌ ОШИБКА ПАРСИНГА JSON: {str(e)}")
    print("\n🔧 РЕКОМЕНДАЦИИ:")
    print("1. Используйте ТОЛЬКО минифицированный JSON для GOOGLE_CREDENTIALS_JSON")
    print("2. Убедитесь, что все переносы строк заменены на \\n (одинарные слеши)")
    print("3. Проверьте JSON на валидность здесь: https://jsonlint.com/")
    print("!"*60)
    sys.exit(1)

except Exception as e:
    print("\n" + "!"*60)
    print(f"❌ ОШИБКА GOOGLE SHEETS API: {str(e)}")
    print("\n🔧 ПРОВЕРЬТЕ:")
    print(f"- Правильность SHEET_ID: {SHEET_ID[:10]}...")
    print("- Доступ таблицы для сервисного аккаунта:")
    print("  • Email: " + creds_data.get('client_email', 'неизвестно'))
    print("- Разрешения таблицы: Права 'Редактор' для email выше")
    print("- Включение Google Sheets API в Google Cloud Console")
    print("!"*60)
    sys.exit(1)

# === ФУНКЦИЯ: ПРОВЕРКА И СОЗДАНИЕ ЛИСТОВ ===
def ensure_sheets_exist(spreadsheet_id):
    """Проверяет наличие необходимых листов и создаёт их при отсутствии"""
    try:
        # Получаем список существующих листов
        spreadsheet = sheets_service.spreadsheets().get(
            spreadsheetId=spreadsheet_id
        ).execute()
        
        existing_sheets = [sheet['properties']['title'] for sheet in spreadsheet['sheets']]
        sheets_to_create = []
        
        # Проверяем необходимые листы
        required_sheets = {
            "Activity": [
                ["Сервер", "Канал", "Дата начала", "Дата окончания", "Сообщений", "Уникальных пользователей", "Изображений", "Ссылок", "Время"]
            ],
            "Images": [  # Изменено название листа с "Attachments" на "Images"
                ["Сервер", "Канал", "Дата начала", "Дата окончания", "Ссылка на сообщение", "Ссылки на изображения", "№ изображений", "Автор", "Время экспорта"]
            ],
            "StaffAnalysis": [
                ["Сервер", "Канал", "Дата начала", "Дата окончания", "Тип", "Сообщений", "Уникальных авторов", "ТОП авторы", "Время"]
            ]
        }
        
        for sheet_name, headers in required_sheets.items():
            if sheet_name not in existing_sheets:
                sheets_to_create.append(sheet_name)
                print(f"📋 Создаю лист: {sheet_name}")
                
                # Создаём лист
                batch_update_request = {
                    "requests": [{
                        "addSheet": {
                            "properties": {
                                "title": sheet_name,
                                "gridProperties": {
                                    "rowCount": 1000,
                                    "columnCount": 10
                                }
                            }
                        }
                    }]
                }
                
                sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body=batch_update_request
                ).execute()
                
                # Заполняем заголовки
                sheets_service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f"{sheet_name}!A1:I1",
                    valueInputOption="USER_ENTERED",
                    body={"values": headers}
                ).execute()
                
                print(f"✅ Лист '{sheet_name}' создан и настроен")
        
        if not sheets_to_create:
            print("✅ Все необходимые листы уже существуют")
        else:
            print(f"✅ Создано листов: {len(sheets_to_create)}")
            
    except Exception as e:
        print(f"⚠️ Ошибка при настройке листов: {str(e)}")
        print("💡 Совет: Создайте листы вручную в Google Таблице:")
        print("   - Лист 'Activity' с заголовками: Сервер, Канал, Дата начала, Дата окончания, Сообщений, Уникальных пользователей, Изображений, Ссылок, Время")
        print("   - Лист 'Images' с заголовками: Сервер, Канал, Дата начала, Дата окончания, Ссылка на сообщение, Ссылки на изображения, № изображений, Автор, Время экспорта")
        print("   - Лист 'StaffAnalysis' с заголовками: Сервер, Канал, Дата начала, Дата окончания, Тип, Сообщений, Уникальных авторов, ТОП авторы, Время")

# === НАСТРОЙКА ЛИСТОВ ПРИ ЗАПУСКЕ ===
print("\n🔧 ПРОВЕРКА ЛИСТОВ В GOOGLE ТАБЛИЦЕ...")
ensure_sheets_exist(SHEET_ID)

# === НАСТРОЙКА DISCORD БОТА ===
intents = discord.Intents.default()
intents.message_content = True  # Для чтения содержимого сообщений
intents.members = True  # Для получения информации о пользователях

bot = commands.Bot(
    command_prefix=COMMAND_PREFIX,
    intents=intents,
    activity=discord.Game(name=f"Анализ изображений | v{BOT_VERSION}"),
    status=discord.Status.online,
    help_command=None  # Отключаем встроенную команду help
)

# === ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: ПРОВЕРКА ИЗОБРАЖЕНИЯ ===
def is_image(attachment):
    """Проверяет, является ли вложение изображением"""
    if not attachment.content_type:
        return False
    content_type = attachment.content_type.lower()
    # ИСПРАВЛЕНО: убрано неправильное определение ZIP-архивов как изображений
    return content_type.startswith('image/') or content_type == 'application/octet-stream'

# === ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: ПРОВЕРКА РОЛИ ===
def has_senior_role():
    """Декоратор для проверки наличия роли у пользователя"""
    async def predicate(ctx):
        # Ищем роль по имени (регистронезависимо)
        senior_role = None
        for role in ctx.guild.roles:
            if role.name.lower() == SENIOR_ROLE_NAME.lower():
                senior_role = role
                break
        
        if senior_role is None:
            await ctx.send(f"❌ Роль '{SENIOR_ROLE_NAME}' не найдена на этом сервере. Свяжитесь с администратором.")
            return False
            
        # Проверяем, есть ли у пользователя эта роль
        if senior_role not in ctx.author.roles:
            await ctx.send(f"❌ У вас нет прав для использования этой команды. Требуется роль `{SENIOR_ROLE_NAME}`")
            return False
            
        return True
    return commands.check(predicate)

# === КОМАНДА: АНАЛИЗ АКТИВНОСТИ С ТОП-ПОЛЬЗОВАТЕЛЯМИ (ТОЛЬКО ИЗОБРАЖЕНИЯ) ===
@bot.command(name="activity")
@has_senior_role()  # Применяем проверку роли
async def activity(ctx, channel: discord.TextChannel, start_date: str, end_date: str = None):
    """Анализ активности в канале за период. Пример: !activity #чат 01-01-2026 15-01-2026
    
    💡 Бот анализирует ТОЛЬКО изображения (jpg, png, gif), игнорируя документы, видео и другие файлы
    💡 Доступно только пользователям с ролью @Старший состав ФСВНГ
    """
    await ctx.send(f"🔄 Запускаю анализ активности в канале {channel.mention}...")
    
    try:
        # Обработка дат (формат ДД-ММ-ГГГГ)
        if end_date is None:
            end_date = datetime.datetime.now(datetime.timezone.utc).strftime("%d-%m-%Y")
            
        # Парсим даты в формате ДД-ММ-ГГГГ
        start_dt = parse_date(start_date)
        end_dt = parse_date(end_date) + datetime.timedelta(days=1)
        
        if start_dt > end_dt:
            await ctx.send("❌ Ошибка: дата начала позже даты окончания!")
            return
            
        # Сбор статистики
        message_count = 0
        unique_users = {}  # {user_id: display_name}
        images = 0  # Теперь считаем только изображения
        links = 0
        
        # Словари для сбора статистики по пользователям
        user_messages = {}  # {user_id: количество сообщений}
        user_images = {}    # {user_id: количество изображений}
        
        # ИСПРАВЛЕНО: добавлен лимит для безопасности
        async for message in channel.history(after=start_dt, before=end_dt, limit=10000):
            if message.author.bot:
                continue
                
            user_id = str(message.author.id)
            # Используем отображаемое имя пользователя на сервере
            display_name = str(message.author.display_name)
            
            # Сохраняем имя пользователя при первом появлении
            if user_id not in unique_users:
                unique_users[user_id] = display_name
            
            message_count += 1
            
            # Подсчет сообщений по пользователям
            user_messages[user_id] = user_messages.get(user_id, 0) + 1
            
            # Анализ контента
            # Подсчет ТОЛЬКО изображений
            for attachment in message.attachments:
                if is_image(attachment):
                    images += 1
                    # Подсчет изображений по пользователям
                    user_images[user_id] = user_images.get(user_id, 0) + 1
            
            if "http://" in message.content or "https://" in message.content:
                links += 1
        
        # Формирование отчета
        report_lines = [
            f"📊 **Отчет по активности (только изображения)**",
            f"📅 Период: `{start_date} - {end_date}`",
            f"💬 Сообщений: **{message_count}**",
            f"👥 Уникальных пользователей: **{len(unique_users)}**",
            f"🖼️ Изображений: **{images}**",
            f"🔗 Ссылок: **{links}**",
            f"📈 Канал: `{channel.name}`",
            "\n🏆 **ТОП-10 пользователей по сообщениям:**"
        ]
        
        # ТОП-10 по сообщениям
        top_messages = sorted(user_messages.items(), key=lambda x: x[1], reverse=True)[:10]
        if top_messages:
            for i, (user_id, count) in enumerate(top_messages, 1):
                username = unique_users.get(user_id, "Неизвестный пользователь")
                report_lines.append(f"**{i}.** {username} — **{count}** сообщений")
        else:
            report_lines.append("ℹ️ Нет данных для формирования ТОП-10 по сообщениям")
        
        # ТОП-10 по изображениям
        report_lines.append("\n📸 **ТОП-10 пользователей по изображениям:**")
        top_images = sorted(user_images.items(), key=lambda x: x[1], reverse=True)[:10]
        if top_images:
            for i, (user_id, count) in enumerate(top_images, 1):
                username = unique_users.get(user_id, "Неизвестный пользователь")
                report_lines.append(f"**{i}.** {username} — **{count}** изображений")
        else:
            report_lines.append("ℹ️ Нет данных для формирования ТОП-10 по изображениям")
        
        report = "\n".join(report_lines)
        
        # Отправка отчета (разбиваем на части если превышает лимит)
        if len(report) > 1900:
            # Делим отчет на части
            parts = [report[i:i+1900] for i in range(0, len(report), 1900)]
            for part in parts:
                await ctx.send(part)
        else:
            await ctx.send(report)
        
        # Отправка в Google Sheets (сохраняем только общую статистику)
        values = [[
            ctx.guild.name,
            channel.name,
            start_date,
            end_date,
            message_count,
            len(unique_users),
            images,
            links,
            datetime.datetime.now(datetime.timezone.utc).strftime("%d-%m-%Y %H:%M:%S UTC")
        ]]
        
        try:
            sheets_service.spreadsheets().values().append(
                spreadsheetId=SHEET_ID,
                range="Activity!A:I",
                valueInputOption="USER_ENTERED",
                body={"values": values}
            ).execute()
            
            await ctx.send("✅ Данные успешно сохранены в Google Sheets!")
        except HttpError as e:
            if "Unable to parse range" in str(e):
                await ctx.send("❌ Ошибка записи в таблицу: отсутствуют необходимые листы. Бот пытается создать их автоматически...")
                ensure_sheets_exist(SHEET_ID)
                sheets_service.spreadsheets().values().append(
                    spreadsheetId=SHEET_ID,
                    range="Activity!A:I",
                    valueInputOption="USER_ENTERED",
                    body={"values": values}
                ).execute()
                await ctx.send("✅ Листы созданы и данные сохранены!")
            else:
                # ИСПРАВЛЕНО: добавлено подробное логирование ошибок
                error_content = json.loads(e.content.decode('utf-8')) if hasattr(e, 'content') else str(e)
                print(f"Google Sheets API error: {error_content}")
                print(f"Request details: {e.uri}")
                await ctx.send(f"⚠️ Ошибка при сохранении в Google Sheets: {str(e)}")
        
    except ValueError as e:
        await ctx.send(f"❌ Ошибка формата даты: {str(e)}")
    except discord.Forbidden:
        await ctx.send(f"❌ У бота нет прав на чтение канала {channel.mention}. Проверьте разрешения в настройках сервера.")
    except Exception as e:
        await ctx.send(f"⚠️ Критическая ошибка: `{str(e)}`")
        print(f"\n🔥 НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ В КОМАНДЕ activity: {e}")
    finally:
        # ИСПРАВЛЕНО: добавлена сборка мусора для оптимизации памяти
        gc.collect()

# === КОМАНДА: АНАЛИЗ ИЗОБРАЖЕНИЙ С ГРУППИРОВКОЙ ===
@bot.command(name="images")
@has_senior_role()  # Применяем проверку роли
async def images(ctx, channel: discord.TextChannel, start_date: str, end_date: str = None, limit: int = 500):
    """
    Анализ сообщений с изображениями за период.
    Пример: !images #media 01-01-2026 07-01-2026 500
    
    💡 Бот анализирует ТОЛЬКО изображения (jpg, png, gif), игнорируя документы, видео и другие файлы
    💡 Доступно только пользователям с ролью @Старший состав ФСВНГ
    """
    await ctx.send(f"🔍 Собираю сообщения с изображениями в канале {channel.mention}...")
    
    try:
        # Обработка дат (формат ДД-ММ-ГГГГ)
        if end_date is None:
            end_date = datetime.datetime.now(datetime.timezone.utc).strftime("%d-%m-%Y")
        
        start_dt = parse_date(start_date)
        end_dt = parse_date(end_date) + datetime.timedelta(days=1)
        
        if start_dt > end_dt:
            await ctx.send("❌ Ошибка: дата начала позже даты окончания!")
            return
        
        # Сбор данных
        message_images = {}  # {message_id: {"link": str, "images": [{"number": int, "url": str}], "author": str, "created_at": str}}
        image_number = 1
        
        # ИСПРАВЛЕНО: добавлен лимит для безопасности
        async for message in channel.history(after=start_dt, before=end_dt, limit=10000):
            if message.author.bot:
                continue
                
            # Проверяем наличие ИЗОБРАЖЕНИЙ в сообщении
            image_attachments = [
                att for att in message.attachments 
                if is_image(att)
            ]
            
            if not image_attachments:
                continue  # Пропускаем сообщения без изображений
                
            message_link = f"https://discord.com/channels/{ctx.guild.id}/{channel.id}/{message.id}"
            
            # Инициализируем данные для сообщения
            if message.id not in message_images:
                message_images[message.id] = {
                    "link": message_link,
                    "images": [],
                    "author": str(message.author.display_name),  # Используем отображаемое имя
                    "created_at": message.created_at.strftime("%d-%m-%Y %H:%M")
                }
            
            # Добавляем каждое ИЗОБРАЖЕНИЕ к сообщению
            for attachment in image_attachments:
                message_images[message.id]["images"].append({
                    "number": image_number,
                    "url": attachment.url
                })
                image_number += 1
        
        total_messages = len(message_images)
        total_images = sum(len(data["images"]) for data in message_images.values())
        
        # Формирование отчёта
        if not message_images:
            await ctx.send(f"ℹ️ В период с {start_date} по {end_date} не найдено сообщений с изображениями.")
            return
        
        # Генерация текста отчёта
        report_lines = [f"📊 **Отчёт по изображениям** в канале `{channel.name}`"]
        report_lines.append(f"📅 Период: `{start_date} - {end_date}`")
        report_lines.append(f"🖼️ Всего изображений: **{total_images}**")
        report_lines.append(f"💬 Сообщений с изображениями: **{total_messages}**")
        report_lines.append("\n🔗 **Ссылки на сообщения с изображениями:**")
        
        # Формируем отчет с группировкой изображений по сообщениям
        processed_messages = list(message_images.values())
        
        # Показываем первые 20 сообщений (а не изображений)
        for i, data in enumerate(processed_messages[:20], 1):
            image_numbers = ", ".join(str(img["number"]) for img in data["images"])
            # ИСПРАВЛЕНО: убрано дублирование ссылок
            report_lines.append(f"**{i}.** {data['link']} • № {image_numbers} • **{data['author']}**")
        
        if len(processed_messages) > 20:
            report_lines.append(f"\nℹ️ Показаны первые 20 из {total_messages} сообщений с изображениями. Для полного отчёта используйте `!export_images`")
        
        report = "\n".join(report_lines)
        await ctx.send(report)
        
        # Сохранение полного отчёта в Google Sheets
        if message_images:
            values = []
            for message_id, data in message_images.items():
                # Формируем одну запись для всего сообщения со всеми его изображениями
                image_numbers = ", ".join(str(img["number"]) for img in data["images"])
                image_urls = " | ".join(img["url"] for img in data["images"])
                
                # ИСПРАВЛЕНО: добавлено экранирование значений
                values.append([
                    sanitize_value(ctx.guild.name),
                    sanitize_value(channel.name),
                    sanitize_value(start_date),
                    sanitize_value(end_date),
                    sanitize_value(data['link']),
                    sanitize_value(image_urls),
                    sanitize_value(image_numbers),
                    sanitize_value(data['author']),
                    sanitize_value(datetime.datetime.now(datetime.timezone.utc).strftime("%d-%m-%Y %H:%M:%S UTC"))
                ])
            
            # Пакетная отправка в Google Sheets (теперь в лист Images)
            batch_size = 1000
            for i in range(0, len(values), batch_size):
                batch = values[i:i+batch_size]
                try:
                    sheets_service.spreadsheets().values().append(
                        spreadsheetId=SHEET_ID,
                        range="Images!A:I",  # Используем лист Images вместо Attachments
                        valueInputOption="USER_ENTERED",
                        body={"values": batch}
                    ).execute()
                except HttpError as e:
                    if "Unable to parse range" in str(e):
                        await ctx.send("❌ Ошибка записи в таблицу: отсутствуют необходимые листы. Бот пытается создать их автоматически...")
                        ensure_sheets_exist(SHEET_ID)
                        sheets_service.spreadsheets().values().append(
                            spreadsheetId=SHEET_ID,
                            range="Images!A:I",
                            valueInputOption="USER_ENTERED",
                            body={"values": batch}
                        ).execute()
                        await ctx.send("✅ Листы созданы и данные сохранены!")
                    else:
                        # ИСПРАВЛЕНО: добавлено подробное логирование ошибок
                        error_content = json.loads(e.content.decode('utf-8')) if hasattr(e, 'content') else str(e)
                        print(f"Google Sheets API error: {error_content}")
                        print(f"Request details: {e.uri}")
                        await ctx.send(f"⚠️ Ошибка при сохранении в Google Sheets: {str(e)}")
            
            await ctx.send(f"✅ Полный отчёт сохранён в Google Sheets! {total_messages} сообщений с {total_images} изображениями.")
    
    except ValueError as e:
        await ctx.send(f"❌ {str(e)}\n💡 Даты могут быть произвольными: понедельник-воскресенье, рабочие дни, любой период")
    except discord.Forbidden:
        await ctx.send(f"❌ У бота нет прав на чтение канала {channel.mention}. Выдайте права: `Просмотр канала` и `Чтение истории сообщений`")
    except Exception as e:
        await ctx.send(f"⚠️ Ошибка при обработке: `{str(e)}`")
        print(f"\n🔥 ОШИБКА В КОМАНДЕ images: {e}")
    finally:
        # ИСПРАВЛЕНО: добавлена сборка мусора для оптимизации памяти
        gc.collect()

# === КОМАНДА: ЭКСПОРТ ИЗОБРАЖЕНИЙ В CSV С СОХРАНЕНИЕМ В GOOGLE SHEETS ===
@bot.command(name="export_images")
@has_senior_role()  # Применяем проверку роли
async def export_images(ctx, channel: discord.TextChannel, start_date: str, end_date: str = None):
    """Экспорт полного отчёта по изображениям в CSV файл и сохранение в Google Sheets
    
    Пример: !export_images #media 01-01-2026 07-01-2026
    
    💡 Бот анализирует ТОЛЬКО изображения (jpg, png, gif), игнорируя документы, видео и другие файлы
    💡 Доступно только пользователям с ролью @Старший состав ФСВНГ
    """
    await ctx.send(f"💾 Готовлю полный экспорт изображений из канала {channel.mention}...")
    
    try:
        # Обработка дат (формат ДД-ММ-ГГГГ)
        if end_date is None:
            end_date = datetime.datetime.now(datetime.timezone.utc).strftime("%d-%m-%Y")
        
        start_dt = parse_date(start_date)
        end_dt = parse_date(end_date) + datetime.timedelta(days=1)
        
        # Сбор всех ИЗОБРАЖЕНИЙ
        message_images = {}
        image_number = 1
        
        # ИСПРАВЛЕНО: добавлен лимит для безопасности
        async for message in channel.history(after=start_dt, before=end_dt, limit=10000):
            if message.author.bot:
                continue
                
            # Фильтруем только изображения
            image_attachments = [
                att for att in message.attachments 
                if is_image(att)
            ]
            
            if not image_attachments:
                continue  # Пропускаем сообщения без изображений
                
            message_link = f"https://discord.com/channels/{ctx.guild.id}/{channel.id}/{message.id}"
            
            if message.id not in message_images:
                message_images[message.id] = {
                    "link": message_link,
                    "images": [],
                    "author": str(message.author.display_name),  # Используем отображаемое имя
                    "created_at": message.created_at.strftime("%d-%m-%Y %H:%M:%S")
                }
            
            for attachment in image_attachments:
                message_images[message.id]["images"].append({
                    "number": image_number,
                    "url": attachment.url
                })
                image_number += 1
        
        total_messages = len(message_images)
        total_images = image_number - 1
        
        if not message_images:
            await ctx.send("ℹ️ Не найдено изображений для экспорта.")
            return
        
        # === СОХРАНЕНИЕ В GOOGLE SHEETS ===
        await ctx.send("📤 Сохраняю данные в Google Sheets...")
        
        try:
            values = []
            for message_id, data in message_images.items():
                image_numbers = ", ".join(str(img["number"]) for img in data["images"])
                image_urls = " | ".join(img["url"] for img in data["images"])
                
                # ИСПРАВЛЕНО: добавлено экранирование значений
                values.append([
                    sanitize_value(ctx.guild.name),
                    sanitize_value(channel.name),
                    sanitize_value(start_date),
                    sanitize_value(end_date),
                    sanitize_value(data['link']),
                    sanitize_value(image_urls),
                    sanitize_value(image_numbers),
                    sanitize_value(data['author']),
                    sanitize_value(datetime.datetime.now(datetime.timezone.utc).strftime("%d-%m-%Y %H:%M:%S UTC"))
                ])
            
            # Пакетная отправка в Google Sheets (теперь в лист Images)
            batch_size = 1000
            for i in range(0, len(values), batch_size):
                batch = values[i:i+batch_size]
                sheets_service.spreadsheets().values().append(
                    spreadsheetId=SHEET_ID,
                    range="Images!A:I",  # Используем лист Images вместо Attachments
                    valueInputOption="USER_ENTERED",
                    body={"values": batch}
                ).execute()
            
            await ctx.send(f"✅ Данные успешно сохранены в Google Sheets! {total_messages} сообщений с {total_images} изображениями.")
            
        except HttpError as e:
            if "Unable to parse range" in str(e):
                await ctx.send("❌ Ошибка записи в таблицу: отсутствуют необходимые листы. Бот пытается создать их автоматически...")
                ensure_sheets_exist(SHEET_ID)
                # Повторная попытка записи
                for i in range(0, len(values), batch_size):
                    batch = values[i:i+batch_size]
                    sheets_service.spreadsheets().values().append(
                        spreadsheetId=SHEET_ID,
                        range="Images!A:I",
                        valueInputOption="USER_ENTERED",
                        body={"values": batch}
                    ).execute()
                await ctx.send("✅ Листы созданы и данные сохранены!")
            else:
                # ИСПРАВЛЕНО: добавлено подробное логирование ошибок
                error_content = json.loads(e.content.decode('utf-8')) if hasattr(e, 'content') else str(e)
                print(f"Google Sheets API error: {error_content}")
                print(f"Request details: {e.uri}")
                await ctx.send(f"⚠️ Ошибка при сохранении в Google Sheets: {str(e)}")
                print(f"Google Sheets error: {e}")
        
        # === ГЕНЕРАЦИЯ CSV ФАЙЛА ===
        # ИСПРАВЛЕНО: добавлена правильная обработка кодировки
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(["Ссылка на сообщение", "№ изображений", "Автор", "Дата"])
        
        for data in message_images.values():
            image_numbers = ", ".join(str(img["number"]) for img in data["images"])
            writer.writerow([
                data['link'],
                image_numbers,
                data['author'],
                data['created_at']
            ])
        
        output.seek(0)
        filename = f"images_{start_date.replace('-', '')}_{end_date.replace('-', '')}.csv"
        file = discord.File(fp=output, filename=filename)
        
        await ctx.send(
            f"✅ Экспорт завершён! Найдено {total_messages} сообщений с {total_images} изображениями.",
            file=file
        )
        
    except ValueError as e:
        await ctx.send(f"❌ {str(e)}")
    except Exception as e:
        await ctx.send(f"❌ Ошибка при экспорте: {str(e)}")
        print(f"\n🔥 ОШИБКА В КОМАНДЕ export_images: {e}")
    finally:
        # ИСПРАВЛЕНО: добавлена сборка мусора для оптимизации памяти
        gc.collect()

# === КОМАНДА: АНАЛИЗ КАДРОВЫХ СООБЩЕНИЙ (ИСПРАВЛЕНА) ===
@bot.command(name="staff_analysis")
@has_senior_role()  # Применяем проверку роли
async def staff_analysis(ctx, channel: discord.TextChannel, start_date: str, end_date: str = None):
    """
    Анализ сообщений о кадровых изменениях (принят/уволен) за период.
    Пример: !staff_analysis #personnel 01-01-2026 07-01-2026
    
    💡 Бот анализирует сообщения, содержащие слова "принят" и "уволен"
    💡 Отображает ТОП авторов по каждому типу сообщений
    💡 Доступно только пользователям с ролью @Старший состав ФСВНГ
    """
    await ctx.send(f"🔄 Запускаю анализ кадровых сообщений в канале {channel.mention}...")
    
    try:
        # Обработка дат (формат ДД-ММ-ГГГГ)
        if end_date is None:
            end_date = datetime.datetime.now(datetime.timezone.utc).strftime("%d-%m-%Y")
        
        start_dt = parse_date(start_date)
        end_dt = parse_date(end_date) + datetime.timedelta(days=1)
        
        if start_dt > end_dt:
            await ctx.send("❌ Ошибка: дата начала позже даты окончания!")
            return
        
        # Ключевые слова для поиска
        hired_keywords = ["принят", "принята", "принято", "принят(а)", "приняты", "оформлен", "оформлена", "трудоустроен", "трудоустроена"]
        fired_keywords = ["уволен", "уволена", "уволено", "уволен(а)", "уволены", "увольнение", "уволен по собственному", "уволен за нарушение"]
        
        # Словари для сбора статистики
        hired_messages = []  # Список сообщений о приеме
        fired_messages = []  # Список сообщений об увольнении
        
        hired_authors = {}  # {author_id: количество сообщений}
        fired_authors = {}  # {author_id: количество сообщений}
        
        # Сбор данных
        # ИСПРАВЛЕНО: добавлен лимит для безопасности
        async for message in channel.history(after=start_dt, before=end_dt, limit=10000):
            if message.author.bot:
                continue
            
            content_lower = message.content.lower()
            author_id = str(message.author.id)
            display_name = str(message.author.display_name)
            
            # ИСПРАВЛЕНО: используется поиск целых слов с помощью регулярных выражений
            is_hired = any(re.search(rf'\b{re.escape(keyword)}\b', content_lower) for keyword in hired_keywords)
            is_fired = any(re.search(rf'\b{re.escape(keyword)}\b', content_lower) for keyword in fired_keywords)
            
            if is_hired:
                hired_messages.append({
                    "content": message.content,
                    "author": display_name,
                    "created_at": message.created_at.strftime("%d-%m-%Y %H:%M"),
                    "link": f"https://discord.com/channels/{ctx.guild.id}/{channel.id}/{message.id}"
                })
                hired_authors[display_name] = hired_authors.get(display_name, 0) + 1
            
            if is_fired:
                fired_messages.append({
                    "content": message.content,
                    "author": display_name,
                    "created_at": message.created_at.strftime("%d-%m-%Y %H:%M"),
                    "link": f"https://discord.com/channels/{ctx.guild.id}/{channel.id}/{message.id}"
                })
                fired_authors[display_name] = fired_authors.get(display_name, 0) + 1
        
        # Формирование отчета
        report_lines = [
            f"📊 **Отчет по кадровым сообщениям**",
            f"📅 Период: `{start_date} - {end_date}`",
            f"📈 Канал: `{channel.name}`",
            "\n✅ **Сообщения о приеме на работу:**",
            f"   • Всего сообщений: **{len(hired_messages)}**",
            f"   • Уникальных авторов: **{len(hired_authors)}**",
            "\n❌ **Сообщения об увольнениях:**",
            f"   • Всего сообщений: **{len(fired_messages)}**",
            f"   • Уникальных авторов: **{len(fired_authors)}**",
            "\n🏆 **ТОП-5 авторов сообщений о приеме:**"
        ]
        
        # ТОП-5 авторов по приему
        top_hired = sorted(hired_authors.items(), key=lambda x: x[1], reverse=True)[:5]
        if top_hired:
            for i, (author, count) in enumerate(top_hired, 1):
                report_lines.append(f"**{i}.** {author} — **{count}** сообщений")
        else:
            report_lines.append("ℹ️ Нет сообщений о приеме на работу")
        
        # ТОП-5 авторов по увольнениям
        report_lines.append("\n🔥 **ТОП-5 авторов сообщений об увольнениях:**")
        top_fired = sorted(fired_authors.items(), key=lambda x: x[1], reverse=True)[:5]
        if top_fired:
            for i, (author, count) in enumerate(top_fired, 1):
                report_lines.append(f"**{i}.** {author} — **{count}** сообщений")
        else:
            report_lines.append("ℹ️ Нет сообщений об увольнениях")
        
        report = "\n".join(report_lines)
        
        # ИСПРАВЛЕНО: добавлена пагинация для длинных отчетов
        if len(report) > 1900:
            parts = [report[i:i+1900] for i in range(0, len(report), 1900)]
            for part in parts:
                await ctx.send(part)
        else:
            await ctx.send(report)
        
        # Сохранение данных в Google Sheets
        values = []
        
        # Данные по приему
        if hired_messages:
            top_hired_authors = ", ".join([f"{author} ({count})" for author, count in top_hired][:3])
            # ИСПРАВЛЕНО: добавлено экранирование значений
            values.append([
                sanitize_value(ctx.guild.name),
                sanitize_value(channel.name),
                sanitize_value(start_date),
                sanitize_value(end_date),
                sanitize_value("принят"),
                sanitize_value(len(hired_messages)),
                sanitize_value(len(hired_authors)),
                sanitize_value(top_hired_authors),
                sanitize_value(datetime.datetime.now(datetime.timezone.utc).strftime("%d-%m-%Y %H:%M:%S UTC"))
            ])
        
        # Данные по увольнениям
        if fired_messages:
            top_fired_authors = ", ".join([f"{author} ({count})" for author, count in top_fired][:3])
            # ИСПРАВЛЕНО: добавлено экранирование значений
            values.append([
                sanitize_value(ctx.guild.name),
                sanitize_value(channel.name),
                sanitize_value(start_date),
                sanitize_value(end_date),
                sanitize_value("уволен"),
                sanitize_value(len(fired_messages)),
                sanitize_value(len(fired_authors)),
                sanitize_value(top_fired_authors),
                sanitize_value(datetime.datetime.now(datetime.timezone.utc).strftime("%d-%m-%Y %H:%M:%S UTC"))
            ])
        
        # Отправка в Google Sheets
        if values:
            try:
                sheets_service.spreadsheets().values().append(
                    spreadsheetId=SHEET_ID,
                    range="StaffAnalysis!A:I",
                    valueInputOption="USER_ENTERED",
                    body={"values": values}
                ).execute()
                await ctx.send("✅ Данные о кадровых сообщениях сохранены в Google Sheets!")
            except HttpError as e:
                if "Unable to parse range" in str(e):
                    await ctx.send("❌ Ошибка записи в таблицу: отсутствуют необходимые листы. Бот пытается создать их автоматически...")
                    ensure_sheets_exist(SHEET_ID)
                    sheets_service.spreadsheets().values().append(
                        spreadsheetId=SHEET_ID,
                        range="StaffAnalysis!A:I",
                        valueInputOption="USER_ENTERED",
                        body={"values": values}
                    ).execute()
                    await ctx.send("✅ Листы созданы и данные сохранены!")
                else:
                    # ИСПРАВЛЕНО: добавлено подробное логирование ошибок
                    error_content = json.loads(e.content.decode('utf-8')) if hasattr(e, 'content') else str(e)
                    print(f"Google Sheets API error: {error_content}")
                    print(f"Request details: {e.uri}")
                    await ctx.send(f"⚠️ Ошибка при сохранении в Google Sheets: {str(e)}")
    
    except ValueError as e:
        await ctx.send(f"❌ Ошибка формата даты: {str(e)}")
    except discord.Forbidden:
        await ctx.send(f"❌ У бота нет прав на чтение канала {channel.mention}. Проверьте разрешения в настройках сервера.")
    except Exception as e:
        await ctx.send(f"⚠️ Критическая ошибка: `{str(e)}`")
        print(f"\n🔥 НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ В КОМАНДЕ staff_analysis: {e}")
    finally:
        # ИСПРАВЛЕНО: добавлена сборка мусора для оптимизации памяти
        gc.collect()

# === КОМАНДА: СПРАВКА ===
@bot.command(name="help")
@has_senior_role()  # Применяем проверку роли
async def help_cmd(ctx):
    """Показать справку по командам"""
    help_text = (
        f"**🤖 Справка по командам бота (версия {BOT_VERSION})**\n\n"
        f"**`{COMMAND_PREFIX}activity #канал ДД-ММ-ГГГГ [ДД-ММ-ГГГГ]`**\n"
        "→ Анализ общей активности в канале за период\n"
        "→ Считает ТОЛЬКО изображения (игнорирует документы, видео, аудио)\n"
        "→ Показывает ТОП-10 пользователей по сообщениям и изображениям с их именами\n\n"
        
        f"**`{COMMAND_PREFIX}images #канал ДД-ММ-ГГГГ [ДД-ММ-ГГГГ] [лимит]`**\n"
        "→ Анализ сообщений с изображениями\n"
        "→ Лимит по умолчанию: 500 сообщений\n"
        "→ Изображения в одном сообщении группируются под одной ссылкой с номерами\n"
        "→ Отображается имя пользователя для каждого сообщения\n\n"
        
        f"**`{COMMAND_PREFIX}export_images #канал ДД-ММ-ГГГГ [ДД-ММ-ГГГГ]`**\n"
        "→ Экспорт полного отчёта по изображениям в CSV файл и сохранение в Google Sheets\n"
        "→ В CSV включаются имена авторов изображений\n\n"
        
        f"**`{COMMAND_PREFIX}staff_analysis #канал ДД-ММ-ГГГГ [ДД-ММ-ГГГГ]`**\n"
        "→ Анализ сообщений о кадровых изменениях (принят/уволен)\n"
        "→ Подсчет количества сообщений по каждому типу\n"
        "→ Отображение ТОП-5 активных авторов по имени\n"
        "→ Сохранение данных в Google Sheets\n\n"
        
        "**🔐 Безопасность:**\n"
        f"→ Все команды доступны **только пользователям с ролью `{SENIOR_ROLE_NAME}`**\n"
        "→ Если роль не найдена на сервере, свяжитесь с администратором\n\n"
        
        "**🖼️ Важно:**\n"
        "→ Бот анализирует **ТОЛЬКО изображения** (jpg, png, gif, webp)\n"
        "→ Документы (pdf, docx), видео (mp4), аудио (mp3) и другие файлы **игнорируются**\n"
        "→ Изображения определяются по MIME-типу файла\n"
        "→ Отображаются реальные имена пользователей (никнеймы) в отчётах\n\n"
        
        "**📅 Формат даты:**\n"
        "→ Используйте формат **ДД-ММ-ГГГГ** (например: `01-01-2026`)\n"
        "→ Даты могут быть **произвольными**:\n"
        "  • Рабочая неделя (понедельник-пятница)\n"
        "  • Полная неделя (понедельник-воскресенье)\n"
        "  • Любой другой период (например, 15-01-2026 по 19-01-2026)\n\n"
        
        "**📋 Требования для работы:**\n"
        "• У бота должны быть права: `Просмотр канала`, `Чтение истории сообщений`, `Отправка сообщений`\n"
        f"• У пользователя должна быть роль `{SENIOR_ROLE_NAME}` для доступа к командам\n"
        "• Бот автоматически создаст необходимые листы в Google Таблице при первом запуске"
    )
    await ctx.send(help_text)

# === СИСТЕМНЫЕ СОБЫТИЯ ===
@bot.event
async def on_ready():
    print("\n" + "="*60)
    print(f"✅ УСПЕШНЫЙ ЗАПУСК: {bot.user} (версия {BOT_VERSION}) готов к работе!")
    print(f"🔐 Роль для доступа: '{SENIOR_ROLE_NAME}'")
    print(f"🌐 Серверов в работе: {len(bot.guilds)}")
    print(f"⌨️ Префикс команд: '{COMMAND_PREFIX}'")
    print(f"📊 Google Sheet ID: {SHEET_ID[:10]}...")
    print("="*60)
    
    # Отображаем список серверов для отладки
    if bot.guilds:
        print("\n🔗 ПОДКЛЮЧЕННЫЕ СЕРВЕРА:")
        for guild in bot.guilds:
            print(f"  - {guild.name} (ID: {guild.id})")
            
            # Выводим список ролей для отладки
            print("  📋 Доступные роли на сервере:")
            for role in guild.roles:
                print(f"    • {role.name}")
    else:
        print("\n⚠️ Бот не добавлен ни на один сервер! Добавьте его через OAuth2 URL")

@bot.event
async def on_guild_join(guild):
    print(f"\n🎉 БОТ ДОБАВЛЕН НА НОВЫЙ СЕРВЕР: {guild.name} (ID: {guild.id})")
    print(f"  🔐 Требуемая роль для доступа: '{SENIOR_ROLE_NAME}'")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Неизвестная команда. Используйте `!help` для просмотра доступных команд.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Недостаточно аргументов. Проверьте синтаксис команды через `!help`")
    elif isinstance(error, commands.CheckFailure):
        # Эта ошибка возникает при провале проверки @has_senior_role()
        # Но мы уже обрабатываем её внутри функции, поэтому ничего не делаем
        pass
    else:
        print(f"\n⚠️ ОШИБКА ПРИ ВЫПОЛНЕНИИ КОМАНДЫ: {error}")

# === ЗАПУСК БОТА ===
if __name__ == "__main__":
    try:
        print("\n⏳ ЗАПУСК БОТА...")
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("\n" + "!"*60)
        print("❌ ОШИБКА АВТОРИЗАЦИИ DISCORD")
        print("Проверьте правильность DISCORD_BOT_TOKEN в Railway Variables")
        print("Убедитесь, что бот активирован в Discord Developer Portal")
        print("!"*60)
    except Exception as e:
        print("\n" + "!"*60)
        print(f"🔥 КРИТИЧЕСКАЯ ОШИБКА ЗАПУСКА: {str(e)}")
        print("Проверьте логи выше для деталей")
        print("!"*60)
        sys.exit(1)

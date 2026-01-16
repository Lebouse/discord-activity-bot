import os
import json
import sys
import discord
from discord.ext import commands
import datetime
import csv
import io
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# === ДИАГНОСТИКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ===
def check_env_vars():
    print("="*60)
    print("🚀 ЗАПУСК DISCORD АНАЛИТИЧЕСКОГО БОТА")
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
            "Attachments": [
                ["Сервер", "Канал", "Дата начала", "Дата окончания", "Ссылка на сообщение", "Ссылки на вложения", "№ вложений", "Автор", "Время экспорта"]
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
        print("   - Лист 'Attachments' с заголовками: Сервер, Канал, Дата начала, Дата окончания, Ссылка на сообщение, Ссылки на вложения, № вложений, Автор, Время экспорта")

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
    activity=discord.Game(name="Аналитика | !help"),
    status=discord.Status.online,
    help_command=None  # Отключаем встроенную команду help
)

# === КОМАНДА: АНАЛИЗ АКТИВНОСТИ С ТОП-ПОЛЬЗОВАТЕЛЯМИ ===
@bot.command(name="activity")
async def activity(ctx, channel: discord.TextChannel, start_date: str, end_date: str = None):
    """Анализ активности в канале за период. Пример: !activity #чат 01.01.2026 15.01.2026
    
    💡 Даты могут быть произвольными (например, с понедельника по воскресенье)
    """
    await ctx.send(f"🔄 Запускаю анализ активности в канале {channel.mention}...")
    
    try:
        # Обработка дат (формат ДД.ММ.ГГГГ)
        if end_date is None:
            end_date = datetime.datetime.now(datetime.timezone.utc).strftime("%d.%m.%Y")
            
        # Парсим даты в формате ДД.ММ.ГГГГ
        start_dt = datetime.datetime.strptime(start_date, "%d.%m.%Y").replace(tzinfo=datetime.timezone.utc)
        end_dt = datetime.datetime.strptime(end_date, "%d.%m.%Y").replace(tzinfo=datetime.timezone.utc) + datetime.timedelta(days=1)
        
        if start_dt > end_dt:
            await ctx.send("❌ Ошибка: дата начала позже даты окончания!")
            return
            
        # Сбор статистики
        message_count = 0
        unique_users = set()
        images = 0
        links = 0
        
        # Словари для сбора статистики по пользователям
        user_messages = {}  # {user_id: количество сообщений}
        user_attachments = {}  # {user_id: количество вложений}
        
        async for message in channel.history(after=start_dt, before=end_dt, limit=None):
            if message.author.bot:
                continue
                
            user_id = str(message.author)
            message_count += 1
            unique_users.add(user_id)
            
            # Подсчет сообщений по пользователям
            user_messages[user_id] = user_messages.get(user_id, 0) + 1
            
            # Анализ контента
            if message.attachments:
                images += 1
                # Подсчет вложений по пользователям
                user_attachments[user_id] = user_attachments.get(user_id, 0) + len(message.attachments)
                
            if "http://" in message.content or "https://" in message.content:
                links += 1
        
        # Формирование отчета
        report_lines = [
            f"📊 **Отчет по активности**",
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
            for i, (user, count) in enumerate(top_messages, 1):
                report_lines.append(f"**{i}.** {user} — **{count}** сообщений")
        else:
            report_lines.append("ℹ️ Нет данных для формирования ТОП-10 по сообщениям")
        
        # ТОП-10 по вложениям
        report_lines.append("\n📸 **ТОП-10 пользователей по вложениям:**")
        top_attachments = sorted(user_attachments.items(), key=lambda x: x[1], reverse=True)[:10]
        if top_attachments:
            for i, (user, count) in enumerate(top_attachments, 1):
                report_lines.append(f"**{i}.** {user} — **{count}** вложений")
        else:
            report_lines.append("ℹ️ Нет данных для формирования ТОП-10 по вложениям")
        
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
            datetime.datetime.now(datetime.timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC")
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
                raise e
        
    except ValueError:
        await ctx.send("❌ Ошибка формата даты. Используйте формат ДД.ММ.ГГГГ\nПример: `01.01.2026` или `15.01.2026`")
    except discord.Forbidden:
        await ctx.send(f"❌ У бота нет прав на чтение канала {channel.mention}. Проверьте разрешения в настройках сервера.")
    except Exception as e:
        await ctx.send(f"⚠️ Критическая ошибка: `{str(e)}`")
        print(f"\n🔥 НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ В КОМАНДЕ activity: {e}")

# === КОМАНДА: АНАЛИЗ ВЛОЖЕНИЙ С ГРУППИРОВКОЙ ===
@bot.command(name="attachments")
async def attachments(ctx, channel: discord.TextChannel, start_date: str, end_date: str = None, limit: int = 500):
    """
    Анализ сообщений с вложениями за период.
    Пример: !attachments #media 01.01.2026 07.01.2026 500
    
    💡 Даты могут быть произвольными (например, с понедельника по воскресенье)
    """
    await ctx.send(f"🔍 Собираю сообщения с вложениями в канале {channel.mention}...")
    
    try:
        # Обработка дат (формат ДД.ММ.ГГГГ)
        if end_date is None:
            end_date = datetime.datetime.now(datetime.timezone.utc).strftime("%d.%m.%Y")
        
        start_dt = datetime.datetime.strptime(start_date, "%d.%m.%Y").replace(tzinfo=datetime.timezone.utc)
        end_dt = datetime.datetime.strptime(end_date, "%d.%m.%Y").replace(tzinfo=datetime.timezone.utc) + datetime.timedelta(days=1)
        
        if start_dt > end_dt:
            await ctx.send("❌ Ошибка: дата начала позже даты окончания!")
            return
        
        # Сбор данных
        message_attachments = {}  # {message_id: {"link": str, "attachments": [{"number": int, "url": str}], "author": str, "created_at": str}}
        attachment_number = 1
        
        async for message in channel.history(after=start_dt, before=end_dt, limit=limit):
            if message.author.bot:
                continue
                
            if message.attachments:  # Проверяем наличие вложений
                message_link = f"https://discord.com/channels/{ctx.guild.id}/{channel.id}/{message.id}"
                
                # Инициализируем данные для сообщения
                if message.id not in message_attachments:
                    message_attachments[message.id] = {
                        "link": message_link,
                        "attachments": [],
                        "author": str(message.author),
                        "created_at": message.created_at.strftime("%d.%m.%Y %H:%M")
                    }
                
                # Добавляем каждое вложение к сообщению
                for attachment in message.attachments:
                    message_attachments[message.id]["attachments"].append({
                        "number": attachment_number,
                        "url": attachment.url
                    })
                    attachment_number += 1
        
        total_messages = len(message_attachments)
        total_attachments = sum(len(data["attachments"]) for data in message_attachments.values())
        
        # Формирование отчёта
        if not message_attachments:
            await ctx.send(f"ℹ️ В период с {start_date} по {end_date} не найдено сообщений с вложениями.")
            return
        
        # Генерация текста отчёта
        report_lines = [f"📊 **Отчёт по вложениям** в канале `{channel.name}`"]
        report_lines.append(f"📅 Период: `{start_date} - {end_date}`")
        report_lines.append(f"📎 Всего вложений: **{total_attachments}**")
        report_lines.append(f"💬 Сообщений с вложениями: **{total_messages}**")
        report_lines.append("\n🔗 **Ссылки на сообщения с вложениями:**")
        
        # Формируем отчет с группировкой вложений по сообщениям
        processed_messages = list(message_attachments.values())
        
        # Показываем первые 20 сообщений (а не вложений)
        for i, data in enumerate(processed_messages[:20], 1):
            attachment_numbers = ", ".join(str(att["number"]) for att in data["attachments"])
            report_lines.append(f"**{i}.** [{data['link']}]({data['link']}) • **№ {attachment_numbers}**")
        
        if len(processed_messages) > 20:
            report_lines.append(f"\nℹ️ Показаны первые 20 из {total_messages} сообщений с вложениями. Для полного отчёта используйте `!export_attachments`")
        
        report = "\n".join(report_lines)
        await ctx.send(report)
        
        # Сохранение полного отчёта в Google Sheets
        if message_attachments:
            values = []
            for message_id, data in message_attachments.items():
                # Формируем одну запись для всего сообщения со всеми его вложениями
                attachment_numbers = ", ".join(str(att["number"]) for att in data["attachments"])
                attachment_urls = " | ".join(att["url"] for att in data["attachments"])
                
                values.append([
                    ctx.guild.name,
                    channel.name,
                    start_date,
                    end_date,
                    data['link'],
                    attachment_urls,
                    attachment_numbers,
                    data['author'],
                    datetime.datetime.now(datetime.timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC")
                ])
            
            # Пакетная отправка в Google Sheets
            batch_size = 1000
            for i in range(0, len(values), batch_size):
                batch = values[i:i+batch_size]
                try:
                    sheets_service.spreadsheets().values().append(
                        spreadsheetId=SHEET_ID,
                        range="Attachments!A:I",  # Отдельный лист для вложений
                        valueInputOption="USER_ENTERED",
                        body={"values": batch}
                    ).execute()
                except HttpError as e:
                    if "Unable to parse range" in str(e):
                        await ctx.send("❌ Ошибка записи в таблицу: отсутствуют необходимые листы. Бот пытается создать их автоматически...")
                        ensure_sheets_exist(SHEET_ID)
                        sheets_service.spreadsheets().values().append(
                            spreadsheetId=SHEET_ID,
                            range="Attachments!A:I",
                            valueInputOption="USER_ENTERED",
                            body={"values": batch}
                        ).execute()
                        await ctx.send("✅ Листы созданы и данные сохранены!")
                    else:
                        raise e
            
            await ctx.send(f"✅ Полный отчёт сохранён в Google Sheets! {total_messages} сообщений с {total_attachments} вложениями.")
    
    except ValueError:
        await ctx.send("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ (например, 01.01.2026)\n💡 Даты могут быть произвольными: понедельник-воскресенье, рабочие дни, любой период")
    except discord.Forbidden:
        await ctx.send(f"❌ У бота нет прав на чтение канала {channel.mention}. Выдайте права: `Просмотр канала` и `Чтение истории сообщений`")
    except Exception as e:
        await ctx.send(f"⚠️ Ошибка при обработке: `{str(e)}`")
        print(f"\n🔥 ОШИБКА В КОМАНДЕ attachments: {e}")

# === КОМАНДА: ЭКСПОРТ ВЛОЖЕНИЙ В CSV ===
@bot.command(name="export_attachments")
async def export_attachments(ctx, channel: discord.TextChannel, start_date: str, end_date: str = None):
    """Экспорт полного отчёта по вложениям в CSV файл (без ссылок на вложения)
    
    Пример: !export_attachments #media 01.01.2026 07.01.2026
    
    💡 Даты могут быть произвольными (например, с понедельника по воскресенье)
    """
    await ctx.send(f"💾 Готовлю полный экспорт вложений из канала {channel.mention}...")
    
    try:
        # Обработка дат (формат ДД.ММ.ГГГГ)
        if end_date is None:
            end_date = datetime.datetime.now(datetime.timezone.utc).strftime("%d.%m.%Y")
        
        start_dt = datetime.datetime.strptime(start_date, "%d.%m.%Y").replace(tzinfo=datetime.timezone.utc)
        end_dt = datetime.datetime.strptime(end_date, "%d.%m.%Y").replace(tzinfo=datetime.timezone.utc) + datetime.timedelta(days=1)
        
        # Сбор всех вложений
        message_attachments = {}
        attachment_number = 1
        
        async for message in channel.history(after=start_dt, before=end_dt, limit=None):
            if message.author.bot:
                continue
                
            if message.attachments:
                message_link = f"https://discord.com/channels/{ctx.guild.id}/{channel.id}/{message.id}"
                
                if message.id not in message_attachments:
                    message_attachments[message.id] = {
                        "link": message_link,
                        "attachments": [],
                        "author": str(message.author),
                        "created_at": message.created_at.strftime("%d.%m.%Y %H:%M:%S")
                    }
                
                for attachment in message.attachments:
                    message_attachments[message.id]["attachments"].append({
                        "number": attachment_number,
                        "url": attachment.url  # Этот параметр больше не используется в экспорт, но оставлен для внутренних целей
                    })
                    attachment_number += 1
        
        if not message_attachments:
            await ctx.send("ℹ️ Не найдено вложений для экспорта.")
            return
        
        # Генерация CSV файла БЕЗ столбца со ссылками на вложения
        output = io.StringIO()
        writer = csv.writer(output)
        # Обновленные заголовки без "Ссылки на вложения"
        writer.writerow(["Ссылка на сообщение", "№ вложений", "Автор", "Дата"])
        
        for data in message_attachments.values():
            attachment_numbers = ", ".join(str(att["number"]) for att in data["attachments"])
            # Записываем только нужные поля
            writer.writerow([
                data['link'],
                attachment_numbers,
                data['author'],
                data['created_at']
            ])
        
        output.seek(0)
        file = discord.File(fp=output, filename=f"attachments_{start_date}_{end_date}.csv")
        
        await ctx.send(
            f"✅ Экспорт завершён! Найдено {len(message_attachments)} сообщений с {attachment_number-1} вложениями.",
            file=file
        )
        
    except Exception as e:
        await ctx.send(f"❌ Ошибка при экспорте: {str(e)}")

# === КОМАНДА: СПРАВКА ===
@bot.command(name="help")
async def help_cmd(ctx):
    """Показать справку по командам"""
    help_text = (
        "**🤖 Справка по командам бота**\n\n"
        f"**`{COMMAND_PREFIX}activity #канал ДД.ММ.ГГГГ [ДД.ММ.ГГГГ]`**\n"
        "→ Анализ общей активности в канале за период\n"
        "→ Если вторая дата не указана, анализ до текущего дня\n"
        "→ Включает ТОП-10 пользователей по сообщениям и вложениям\n\n"
        
        f"**`{COMMAND_PREFIX}attachments #канал ДД.ММ.ГГГГ [ДД.ММ.ГГГГ] [лимит]`**\n"
        "→ Анализ сообщений с вложениями\n"
        "→ Лимит по умолчанию: 500 сообщений\n"
        "→ Вложения в одном сообщении группируются под одной ссылкой\n\n"
        
        f"**`{COMMAND_PREFIX}export_attachments #канал ДД.ММ.ГГГГ [ДД.ММ.ГГГГ]`**\n"
        "→ Экспорт полного отчёта по вложениям в CSV файл (без ссылок на вложения)\n\n"
        
        "**📅 Формат даты:**\n"
        "→ Используйте формат **ДД.ММ.ГГГГ** (например: `01.01.2026`)\n"
        "→ Даты могут быть **произвольными**:\n"
        "  • Рабочая неделя (понедельник-пятница)\n"
        "  • Полная неделя (понедельник-воскресенье)\n"
        "  • Любой другой период (например, 15.01.2026-19.01.2026)\n\n"
        
        "**📋 Требования для работы:**\n"
        "• У бота должны быть права: `Просмотр канала`, `Чтение истории сообщений`, `Отправка сообщений`\n"
        "• Бот автоматически создаст необходимые листы в Google Таблице при первом запуске"
    )
    await ctx.send(help_text)

# === СИСТЕМНЫЕ СОБЫТИЯ ===
@bot.event
async def on_ready():
    print("\n" + "="*60)
    print(f"✅ УСПЕШНЫЙ ЗАПУСК: {bot.user} готов к работе!")
    print(f"🌐 Серверов в работе: {len(bot.guilds)}")
    print(f"⌨️ Префикс команд: '{COMMAND_PREFIX}'")
    print(f"📊 Google Sheet ID: {SHEET_ID[:10]}...")
    print("="*60)
    
    # Отображаем список серверов для отладки
    if bot.guilds:
        print("\n🔗 ПОДКЛЮЧЕННЫЕ СЕРВЕРА:")
        for guild in bot.guilds:
            print(f"  - {guild.name} (ID: {guild.id})")
    else:
        print("\n⚠️ Бот не добавлен ни на один сервер! Добавьте его через OAuth2 URL")

@bot.event
async def on_guild_join(guild):
    print(f"\n🎉 БОТ ДОБАВЛЕН НА НОВЫЙ СЕРВЕР: {guild.name} (ID: {guild.id})")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Неизвестная команда. Используйте `!help` для просмотра доступных команд.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Недостаточно аргументов. Проверьте синтаксис команды через `!help`")
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

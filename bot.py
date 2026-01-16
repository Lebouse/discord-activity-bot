import os
import json
import sys
import discord
from discord.ext import commands
import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# === ДИАГНОСТИКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ===
def check_env_vars():
    print("="*60)
    print("🚀 ЗАПУСК DISCORD-БОТА ДЛЯ АНАЛИТИКИ")
    print("="*60)
    
    # Проверка переменных
    missing = []
    for var in ["DISCORD_BOT_TOKEN", "GOOGLE_SHEET_ID", "GOOGLE_CREDENTIALS_JSON"]:
        if not os.getenv(var):
            missing.append(var)
    
    if missing:
        print("\n" + "!"*60)
        print("❗ ОТСУТСТВУЮТ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ:")
        for var in missing:
            print(f"   - {var}")
        print("\n🔧 ИНСТРУКЦИЯ:")
        print("1. Railway → Settings → Variables (Production)")
        print("2. Добавьте ВСЕ три переменные")
        print("3. Для GOOGLE_CREDENTIALS_JSON используйте ПРАВИЛЬНЫЙ ФОРМАТ:")
        print("   • Все \\n должны быть ОДИНАРНЫМИ (не двойными)")
        print("   • Нет лишних кавычек вокруг JSON")
        print("4. Actions → Restart")
        print("!"*60)
        sys.exit(1)
    
    print("✅ Все переменные окружения найдены")

# Запускаем диагностику
check_env_vars()

# === ИНИЦИАЛИЗАЦИЯ ===
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_RAW = os.getenv("GOOGLE_CREDENTIALS_JSON")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")

# === КРИТИЧЕСКИ ВАЖНО: ПРАВИЛЬНОЕ ФОРМАТИРОВАНИЕ JSON ===
def fix_credentials_json(raw_json):
    """Гарантированно исправляет формат JSON для Google Auth"""
    try:
        # Попытка загрузить как есть
        return json.loads(raw_json)
    except json.JSONDecodeError:
        # Исправляем распространенные ошибки форматирования
        fixed = raw_json.strip()
        
        # Убираем внешние кавычки если есть
        if fixed.startswith('"') and fixed.endswith('"'):
            fixed = fixed[1:-1]
        
        # Заменяем двойные слеши на одинарные (\\n → \n)
        fixed = fixed.replace("\\\\n", "\\n")
        fixed = fixed.replace("\\n", "\n")
        
        # Удаляем лишние пробелы вокруг URL
        fixed = fixed.replace("https://accounts.google.com/o/oauth2/auth  ", "https://accounts.google.com/o/oauth2/auth")
        fixed = fixed.replace("https://oauth2.googleapis.com/token  ", "https://oauth2.googleapis.com/token")
        fixed = fixed.replace("https://www.googleapis.com/oauth2/v1/certs  ", "https://www.googleapis.com/oauth2/v1/certs")
        fixed = fixed.replace("https://www.googleapis.com/robot/v1/metadata/x509/  ", "https://www.googleapis.com/robot/v1/metadata/x509/")
        
        try:
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            print("\n" + "!"*60)
            print(f"❌ ФАТАЛЬНАЯ ОШИБКА ФОРМАТА JSON: {str(e)}")
            print("\n📋 ПРИМЕР КОРРЕКТНОГО ФОРМАТА:")
            print('{"type":"service_account","private_key":"-----BEGIN PRIVATE KEY-----\\nMIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQ...\\n-----END PRIVATE KEY-----\\n", ...}')
            print("\n🔧 РЕКОМЕНДАЦИИ:")
            print("1. Скопируйте JSON из этого шаблона: https://pastebin.com/raw/9XcL3DzJ")
            print("2. ИЛИ используйте Railway CLI для установки переменной:")
            print("   railway variable set GOOGLE_CREDENTIALS_JSON=\"$(cat credentials.json)\"")
            print("!"*60)
            sys.exit(1)

# === НАСТРОЙКА GOOGLE SHEETS ===
try:
    print("\n⚙️ ПОДГОТОВКА УЧЕТНЫХ ДАННЫХ GOOGLE...")
    
    # Получаем корректный JSON-объект
    creds_data = fix_credentials_json(GOOGLE_CREDENTIALS_RAW)
    
    # Проверяем наличие приватного ключа
    if "private_key" not in creds_data or not creds_data["private_key"].strip():
        raise ValueError("Приватный ключ отсутствует в учетных данных")
    
    print(f"✅ Сервисный аккаунт: {creds_data.get('client_email', 'неизвестно')}")
    
    # Создаем учетные данные
    creds = Credentials.from_service_account_info(
        creds_data,
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    
    # Подключаемся к API
    sheets_service = build('sheets', 'v4', credentials=creds)
    
    # Тестовое чтение метаданных таблицы
    spreadsheet = sheets_service.spreadsheets().get(
        spreadsheetId=SHEET_ID
    ).execute()
    
    print(f"✅ УСПЕШНО ПОДКЛЮЧЕНО К ТАБЛИЦЕ: {spreadsheet['properties']['title']}")
    print(f"📊 Диапазон данных: A:G")

except Exception as e:
    print("\n" + "!"*60)
    print(f"❌ ОШИБКА GOOGLE SHEETS: {str(e)}")
    print("\n🔍 ДЕТАЛЬНАЯ ДИАГНОСТИКА:")
    print(f"- ID таблицы: {SHEET_ID[:10]}...")
    if 'creds_data' in locals():
        email = creds_data.get('client_email', 'неизвестно')
        print(f"- Email сервисного аккаунта: {email}")
        print("- Проверьте доступ таблицы для этого email")
    print("\n🔧 ЧЕК-ЛИСТ ИСПРАВЛЕНИЙ:")
    print("1. GOOGLE_CREDENTIALS_JSON должен содержать ОДИНАРНЫЕ \\n")
    print("2. Таблица должна быть доступна для email сервисного аккаунта")
    print("3. В Railway Variables нет лишних пробелов в начале/конце значений")
    print("!"*60)
    sys.exit(1)

# === НАСТРОЙКА DISCORD БОТА ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=COMMAND_PREFIX,
    intents=intents,
    activity=discord.Game(name="Аналитика | !help"),
    status=discord.Status.online,
    help_command=None  # Отключаем встроенную справку
)

# === КОМАНДЫ ===
@bot.command(name="activity")
async def activity(ctx, channel: discord.TextChannel, start_date: str, end_date: str = None):
    """Анализ активности в канале за период. Пример: !activity #чат 2026-01-01 2026-01-15"""
    await ctx.send(f"🔄 Собираю данные по каналу {channel.mention}...")
    
    try:
        # Обработка дат
        if end_date is None:
            end_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        
        start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
        end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc) + datetime.timedelta(days=1)
        
        if start_dt > end_dt:
            await ctx.send("❌ Ошибка: дата начала позже даты окончания!")
            return
        
        # Сбор статистики
        message_count = 0
        unique_users = set()
        
        async for message in channel.history(after=start_dt, before=end_dt, limit=None):
            if message.author.bot:
                continue
            message_count += 1
            unique_users.add(str(message.author))
        
        # Формирование отчета
        report = (
            f"📈 **Отчет по активности**\n"
            f"📅 Период: `{start_date}` – `{end_date}`\n"
            f"💬 Сообщений: **{message_count}**\n"
            f"👥 Уникальных пользователей: **{len(unique_users)}**\n"
            f"📌 Канал: `{channel.name}`"
        )
        await ctx.send(report)
        
        # Отправка в Google Sheets
        values = [[
            ctx.guild.name,
            channel.name,
            start_date,
            end_date,
            message_count,
            len(unique_users),
            datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        ]]
        
        sheets_service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range="A:G",
            valueInputOption="USER_ENTERED",
            body={"values": values}
        ).execute()
        
        await ctx.send("✅ Данные успешно сохранены в Google Таблицу!")
    
    except ValueError:
        await ctx.send("❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД (например, 2026-01-15)")
    except discord.Forbidden:
        await ctx.send(f"❌ У бота нет прав на чтение канала {channel.mention}. Выдайте права: `Просмотр канала` и `Чтение истории сообщений`")
    except Exception as e:
        await ctx.send(f"⚠️ Ошибка при обработке: `{str(e)}`")
        print(f"\n🔥 ОШИБКА В КОМАНДЕ activity: {e}")

@bot.command(name="help")
async def help_cmd(ctx):
    """Показать справку по командам"""
    help_text = (
        "**🤖 Справка по командам**\n\n"
        f"`{COMMAND_PREFIX}activity #канал ГГГГ-ММ-ДД [ГГГГ-ММ-ДД]`\n"
        "→ Анализ активности в канале за указанный период\n"
        "→ Если вторая дата не указана, анализ до текущего дня\n\n"
        f"`{COMMAND_PREFIX}help`\n"
        "→ Показать эту справку\n\n"
        "**⚙️ Требования**\n"
        "• Бот должен иметь права: `Просмотр канала`, `Чтение истории сообщений`\n"
        "• Формат даты: строго `ГГГГ-ММ-ДД`\n"
        "• Google Таблица должна быть доступна для сервисного аккаунта"
    )
    await ctx.send(help_text)

# === СИСТЕМНЫЕ СОБЫТИЯ ===
@bot.event
async def on_ready():
    print("\n" + "="*60)
    print(f"✅ БОТ {bot.user} УСПЕШНО ЗАПУЩЕН!")
    print(f"🔗 Количество серверов: {len(bot.guilds)}")
    print(f"⌨️ Префикс команд: '{COMMAND_PREFIX}'")
    print("="*60)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"❌ Неизвестная команда. Используйте `{COMMAND_PREFIX}help` для списка команд")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Недостаточно аргументов. Используйте `{COMMAND_PREFIX}help` для справки")

# === ЗАПУСК ===
if __name__ == "__main__":
    try:
        print("\n⏳ ЗАПУСК БОТА...")
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("\n" + "!"*60)
        print("❌ ОШИБКА АВТОРИЗАЦИИ DISCORD")
        print("Проверьте DISCORD_BOT_TOKEN в Railway Variables")
        print("!"*60)
    except Exception as e:
        print("\n" + "!"*60)
        print(f"🔥 КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
        print("!"*60)
        sys.exit(1)

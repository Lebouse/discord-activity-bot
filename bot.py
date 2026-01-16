import os
import json
import sys
import discord
from discord.ext import commands
import datetime
from dateutil import parser as date_parser
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import asyncio

# === ДИАГНОСТИКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ (ЗАПУСКАЕТСЯ ПЕРВЫМ) ===
def check_env_vars():
    print("="*60)
    print("🚀 ЗАПУСК ДИСКОРД-БОТА ДЛЯ АНАЛИТИКИ")
    print("="*60)
    print("🔍 ПРОВЕРКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ...")
    
    missing = []
    diagnostics = []
    
    # Проверяем каждую переменную
    for var in ["DISCORD_BOT_TOKEN", "GOOGLE_SHEET_ID", "GOOGLE_CREDENTIALS_JSON"]:
        value = os.getenv(var)
        if value:
            # Показываем только начало значения для безопасности
            preview = value[:8] + "..." if len(value) > 8 else value
            diagnostics.append(f"✅ {var}: {preview}")
        else:
            diagnostics.append(f"❌ {var}: НЕ ЗАДАН")
            missing.append(var)
    
    # Выводим диагностику
    for line in diagnostics:
        print(line)
    
    # Критическая проверка
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
        print("   - GOOGLE_CREDENTIALS_JSON")
        print("3. Для GOOGLE_CREDENTIALS_JSON используйте МИНИФИЦИРОВАННЫЙ JSON")
        print("4. Нажмите Actions → Restart после сохранения")
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
        raw_json = raw_json.replace("\\n", "\\\\n")  # Экранируем обратные слеши
    
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
    print("2. Убедитесь, что все переносы строк заменены на \\n")
    print("3. Проверьте JSON на валидность здесь: https://jsonlint.com/")
    print("!"*60)
    sys.exit(1)

except Exception as e:
    print("\n" + "!"*60)
    print(f"❌ ОШИБКА GOOGLE SHEETS API: {str(e)}")
    print("\n🔧 ПРОВЕРЬТЕ:")
    print(f"- Правильность SHEET_ID: {SHEET_ID[:10]}...")
    print("- Доступ таблицы для сервисного аккаунта:")
    print("  • Email: " + json.loads(GOOGLE_CREDENTIALS_JSON).get('client_email', 'неизвестно'))
    print("- Разрешения таблицы: Права 'Редактор' для email выше")
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
    help_command=None  # ОТКЛЮЧАЕМ ВСТРОЕННУЮ КОМАНДУ HELP
)

# === КОМАНДЫ БОТА ===
@bot.command(name="activity")
async def activity(ctx, channel: discord.TextChannel, start_date: str, end_date: str = None):
    """Анализ активности в канале за период. Пример: !activity #чат 2026-01-01 2026-01-15"""
    await ctx.send(f"🔄 Запускаю анализ канала {channel.mention}...")
    
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
            f"📊 **Отчет по активности**\n"
            f"📅 Период: `{start_date} - {end_date}`\n"
            f"💬 Сообщений: **{message_count}**\n"
            f"👥 Уникальных пользователей: **{len(unique_users)}**\n"
            f"📈 Канал: `{channel.name}`"
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
        
        await ctx.send("✅ Данные успешно сохранены в Google Sheets!")
        
    except ValueError:
        await ctx.send("❌ Ошибка формата даты. Используйте формат ГГГГ-ММ-ДД\nПример: `2026-01-15`")
    except discord.Forbidden:
        await ctx.send(f"❌ У бота нет прав на чтение канала {channel.mention}. Проверьте разрешения в настройках сервера.")
    except Exception as e:
        await ctx.send(f"⚠️ Критическая ошибка: `{str(e)}`")
        print(f"\n🔥 НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ В КОМАНДЕ activity: {e}")

@bot.command(name="help")
async def help_cmd(ctx):
    """Показать справку по командам"""
    help_text = (
        "**🤖 Справка по командам бота**\n\n"
        f"**`{COMMAND_PREFIX}activity #канал ДД.ММ.ГГГГ [ДД.ММ.ГГГГ]`**\n"
        "→ Анализ активности в указанном канале за период\n"
        "→ Если вторая дата не указана, используется текущая дата\n\n"
        f"**`{COMMAND_PREFIX}help`**\n"
        "→ Показать эту справку\n\n"
        "**📋 Требования для работы:**\n"
        "• У бота должны быть права: `Просмотр канала`, `Чтение истории сообщений`, `Отправка сообщений`\n"
        "• Даты указываются в формате `ГГГГ-ММ-ДД`\n"
        "• Бот должен иметь доступ к вашей Google Таблице"
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

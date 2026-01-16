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

# === ДИАГНОСТИКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ===
def check_env_vars():
    print("🔍 ДИАГНОСТИКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ")
    missing = []
    
    # Проверяем каждую переменную
    for var in ["DISCORD_BOT_TOKEN", "GOOGLE_SHEET_ID", "GOOGLE_CREDENTIALS_JSON"]:
        value = os.getenv(var)
        status = "✅" if value else "❌"
        preview = value[:8] + "..." if value and len(value) > 8 else "ПУСТО"
        print(f"{status} {var}: {preview}")
        
        if not value:
            missing.append(var)
    
    # Критическая проверка
    if missing:
        print("\n❗ КРИТИЧЕСКАЯ ОШИБКА: Отсутствуют переменные:")
        for var in missing:
            print(f"   - {var}")
        print("\n🔧 РЕШЕНИЕ:")
        print("1. Перейдите в Railway → Settings → Variables (Production)")
        print("2. Добавьте недостающие переменные")
        print("3. Нажмите Actions → Restart")
        sys.exit(1)
    
    print("✅ Все переменные окружения на месте")

# Запускаем диагностику ДО импорта библиотек
check_env_vars()

# === ИНИЦИАЛИЗАЦИЯ ===
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")

# === НАСТРОЙКА GOOGLE SHEETS ===
try:
    print("⚙️ Инициализация Google Sheets...")
    creds = Credentials.from_service_account_info(
        json.loads(GOOGLE_CREDENTIALS_JSON),
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    sheets_service = build('sheets', 'v4', credentials=creds)
    print("✅ Google Sheets подключен")
except json.JSONDecodeError:
    print("❌ ОШИБКА: GOOGLE_CREDENTIALS_JSON не является валидным JSON")
    print("   Совет: Используйте jsonformatter.org/json-minify для преобразования")
    sys.exit(1)
except Exception as e:
    print(f"❌ ОШИБКА Google API: {str(e)}")
    print("   Проверьте:")
    print("   - Правильность JSON-ключа")
    print("   - Доступ таблицы для email сервисного аккаунта")
    sys.exit(1)

# === НАСТРОЙКА DISCORD БОТА ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=COMMAND_PREFIX,
    intents=intents,
    activity=discord.Game(name="Аналитика | !help"),
    status=discord.Status.online
)

# === КОМАНДЫ ===
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
            unique_users.add(message.author.id)
        
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
            datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        ]]
        
        sheets_service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range="A:G",
            valueInputOption="USER_ENTERED",
            body={"values": values}
        ).execute()
        
        await ctx.send("✅ Данные сохранены в Google Sheets!")
        
    except ValueError as e:
        await ctx.send(f"❌ Ошибка формата даты. Используйте ГГГГ-ММ-ДД\nПример: `2026-01-15`")
    except discord.Forbidden:
        await ctx.send(f"❌ У бота нет прав на чтение канала {channel.mention}. Проверьте разрешения.")
    except Exception as e:
        await ctx.send(f"⚠️ Критическая ошибка: `{str(e)}`")
        print(f"[ОШИБКА] {e}")

@bot.command(name="help")
async def help_cmd(ctx):
    """Показать справку по командам"""
    help_text = (
        "**📋 Справка по командам**\n"
        "`!activity #канал ДД.ММ.ГГГГ ДД.ММ.ГГГГ` - Анализ активности за период\n"
        "`!help` - Показать эту справку\n\n"
        "**ℹ️ Требования**\n"
        "- У бота должны быть права: `Просмотр канала`, `Чтение истории сообщений`\n"
        "- Даты указывайте в формате ГГГГ-ММ-ДД"
    )
    await ctx.send(help_text)

# === СИСТЕМНЫЕ СОБЫТИЯ ===
@bot.event
async def on_ready():
    print(f"\n✅ {bot.user} УСПЕШНО ЗАПУЩЕН!")
    print(f"🔗 Серверов: {len(bot.guilds)}")
    print(f"⌨️ Префикс команд: '{COMMAND_PREFIX}'")
    print(f"📊 Google Sheet ID: {SHEET_ID[:10]}...")
    print("\n🚀 Бот готов к работе!")

@bot.event
async def on_guild_join(guild):
    print(f"🎉 Присоединился к новому серверу: {guild.name}")

# === ЗАПУСК ===
if __name__ == "__main__":
    print("\n" + "="*50)
    print("РАЗВОРАЧИВАНИЕ DISCORD АНАЛИТИЧЕСКОГО БОТА")
    print("="*50)
    
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("\n❌ ОШИБКА АВТОРИЗАЦИИ DISCORD")
        print("   - Проверьте DISCORD_BOT_TOKEN в Railway Variables")
        print("   - Убедитесь, что бот добавлен на сервер с правами:")
        print("     • Просмотр канала")
        print("     • Чтение истории сообщений")
        print("     • Отправка сообщений")
    except Exception as e:
        print(f"\n🔥 НЕОБРАБОТАННАЯ ОШИБКА: {str(e)}")
        sys.exit(1)

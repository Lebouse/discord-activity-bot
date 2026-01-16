import os
import json
import datetime
import asyncio
import discord
from discord.ext import commands
from dateutil import parser as date_parser
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# === ИНИЦИАЛИЗАЦИЯ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ===
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS_JSON")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")

if not all([DISCORD_TOKEN, SHEET_ID, GOOGLE_CREDENTIALS]):
    raise RuntimeError("❌ Отсутствуют критические переменные окружения! Проверьте Railway Variables.")

# === НАСТРОЙКА GOOGLE SHEETS ===
try:
    creds = Credentials.from_service_account_info(
        json.loads(GOOGLE_CREDENTIALS),
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    sheets_service = build('sheets', 'v4', credentials=creds)
except Exception as e:
    raise RuntimeError(f"❌ Ошибка инициализации Google Sheets: {str(e)}")

# === НАСТРОЙКА DISCORD БОТА ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Для анализа пользователей

bot = commands.Bot(
    command_prefix=COMMAND_PREFIX,
    intents=intents,
    activity=discord.Game(name="Аналитика сервера"),
    status=discord.Status.online
)

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def parse_human_date(date_str: str) -> datetime.datetime:
    """Парсит даты в форматах: "2026-01-01", "yesterday", "3 days ago" """
    try:
        # Пробуем стандартный формат YYYY-MM-DD
        return datetime.datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        try:
            # Пробуем относительные даты через dateutil
            return date_parser.parse(date_str, tzinfos={"UTC": datetime.timezone.utc})
        except:
            raise ValueError(f"Неподдерживаемый формат даты: {date_str}")

async def collect_channel_activity(channel, start_dt, end_dt):
    """Собирает детальную статистику по каналу за период"""
    stats = {
        "total_messages": 0,
        "images": 0,
        "links": 0,
        "mentions": 0,
        "unique_users": set(),
        "top_users": {}
    }

    async for message in channel.history(after=start_dt, before=end_dt, limit=None):
        if message.author.bot:
            continue
            
        stats["total_messages"] += 1
        stats["unique_users"].add(message.author.id)
        stats["top_users"][message.author.id] = stats["top_users"].get(message.author.id, 0) + 1
        
        # Анализ контента
        if message.attachments:
            stats["images"] += 1
        if "http://" in message.content or "https://" in message.content:
            stats["links"] += 1
        if message.mentions:
            stats["mentions"] += len(message.mentions)

    # Топ-3 пользователя по сообщениям
    top_users_sorted = sorted(
        [(uid, count) for uid, count in stats["top_users"].items()],
        key=lambda x: x[1],
        reverse=True
    )[:3]
    
    stats["top_users"] = top_users_sorted
    return stats

# === КОМАНДЫ БОТА ===
@bot.command(name="activity")
async def activity(ctx, channel: discord.TextChannel, start_date: str, end_date: str = None):
    """!activity #канал 2026-01-01 [2026-01-15]"""
    if end_date is None:
        end_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    
    await ctx.send(f"🔄 Запускаю анализ активности в {channel.mention}...")
    
    try:
        start_dt = parse_human_date(start_date).replace(hour=0, minute=0, second=0)
        end_dt = parse_human_date(end_date).replace(hour=23, minute=59, second=59)
        
        if start_dt > end_dt:
            await ctx.send("❌ Дата начала не может быть позже даты окончания!")
            return
            
        # Сбор статистики
        stats = await collect_channel_activity(channel, start_dt, end_dt)
        
        # Формирование отчета
        top_users_text = "\n".join([
            f"<@{user_id}>: {count} сообщений" 
            for user_id, count in stats["top_users"]
        ]) or "Нет активных пользователей"
        
        report = (
            f"📊 **Аналитика канала {channel.name}**\n"
            f"🕗 Период: `{start_dt.strftime('%Y-%m-%d')} — {end_dt.strftime('%Y-%m-%d')}`\n\n"
            f"💬 Всего сообщений: **{stats['total_messages']}**\n"
            f"👥 Уникальных участников: **{len(stats['unique_users'])}**\n"
            f"🖼️ Изображений: **{stats['images']}**\n"
            f"🔗 Ссылок: **{stats['links']}**\n"
            f"🔔 Упоминаний: **{stats['mentions']}**\n\n"
            f"🏆 **Топ-3 активных пользователя:**\n{top_users_text}"
        )
        
        await ctx.send(report)
        
        # Отправка в Google Sheets
        await log_to_sheets(ctx.guild.name, channel.name, start_dt, end_dt, stats)
        await ctx.send("✅ Данные сохранены в Google Sheets!")
        
    except Exception as e:
        await ctx.send(f"⚠️ Ошибка при анализе: `{str(e)}`")
        print(f"[ERROR] Activity command failed: {e}")

async def log_to_sheets(guild_name, channel_name, start_dt, end_dt, stats):
    """Отправляет данные в Google Sheets"""
    try:
        values = [[
            guild_name,
            channel_name,
            start_dt.strftime("%Y-%m-%d"),
            end_dt.strftime("%Y-%m-%d"),
            stats["total_messages"],
            len(stats["unique_users"]),
            stats["images"],
            stats["links"],
            datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        ]]
        
        body = {"values": values}
        sheets_service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range="A:I",
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()
    except Exception as e:
        print(f"[GOOGLE ERROR] Failed to log data: {e}")

# === СИСТЕМНЫЕ СОБЫТИЯ ===
@bot.event
async def on_ready():
    print(f"✅ {bot.user} успешно запущен!")
    print(f"🔗 Серверов в работе: {len(bot.guilds)}")
    await bot.tree.sync()  # Для слэш-команд (если добавите позже)

@bot.event
async def on_guild_join(guild):
    print(f"🎉 Присоединился к новому серверу: {guild.name}")

# === ЗАПУСК БОТА ===
if __name__ == "__main__":
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("❌ Неверный токен Discord! Проверьте переменную DISCORD_BOT_TOKEN в Railway")
    except Exception as e:
        print(f"🔥 Критическая ошибка: {str(e)}")
        exit(1)

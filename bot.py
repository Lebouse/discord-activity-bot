import discord
from discord.ext import commands
import datetime
import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from collections import defaultdict, Counter
import traceback
import os
import json
import asyncio
from pytz import timezone
import re

# === 1. ЗАГРУЗКА КОНФИГУРАЦИИ ===
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

DISCORD_TOKEN = config['DISCORD_TOKEN']
GOOGLE_INTEGRATION = config.get('GOOGLE_INTEGRATION', False)
SHEET_ID = config.get('SHEET_ID', '')
TIMEZONE = config.get('TIMEZONE', 'UTC')
PREDEFINED_GROUPS = config.get('PREDEFINED_GROUPS', {
    "media": ["media", "art", "screenshots"],
    "all_text": None
})

tz = timezone(TIMEZONE)

# === 2. ИНИЦИАЛИЗАЦИЯ ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Google Sheets сервис
sheets_service = None
if GOOGLE_INTEGRATION and os.path.exists('credentials.json'):
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        
        SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
        sheets_service = build('sheets', 'v4', credentials=creds)
        print("✅ Google Sheets интеграция активирована")
    except Exception as e:
        print(f"⚠️ Google Sheets отключён: {str(e)}")
        GOOGLE_INTEGRATION = False

# === 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def parse_date(date_str):
    """Преобразует строку YYYY-MM-DD в datetime (UTC)"""
    try:
        naive_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        localized_dt = tz.localize(naive_dt)
        return localized_dt.astimezone(datetime.timezone.utc)
    except ValueError:
        return None

async def ensure_google_sheet(sheet_name, headers):
    """Гарантирует наличие листа с заголовками"""
    if not GOOGLE_INTEGRATION or sheets_service is None:
        return False
    
    try:
        # Проверяем наличие листа
        spreadsheet = sheets_service.spreadsheets().get(
            spreadsheetId=SHEET_ID
        ).execute()
        
        sheet_exists = any(
            sheet['properties']['title'] == sheet_name 
            for sheet in spreadsheet['sheets']
        )
        
        if not sheet_exists:
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=SHEET_ID,
                body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
            ).execute()
        
        # Проверяем заголовки
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f"{sheet_name}!A1:Z1"
        ).execute()
        
        if 'values' not in result or len(result['values'][0]) < len(headers):
            sheets_service.spreadsheets().values().update(
                spreadsheetId=SHEET_ID,
                range=f"{sheet_name}!A1",
                valueInputOption="RAW",
                body={"values": [headers]}
            ).execute()
        
        return True
    except Exception as e:
        print(f"Ошибка создания листа {sheet_name}: {str(e)}")
        return False

def safe_filename(name):
    """Очищает имя файла от недопустимых символов"""
    return re.sub(r'[\\/*?:"<>|]', "", name)[:30]

# === 4. КОМАНДА: АНАЛИЗ АКТИВНОСТИ ===
@bot.command(name='activity')
async def activity(ctx, *args):
    """Анализ активности в каналах за период
    Примеры:
      !activity #general #media 2026-01-01 2026-01-15
      !activity media 2026-01-01 2026-01-15
    """
    await ctx.defer()  # Отправляет "бот печатает"
    try:
        if len(args) < 3:
            await ctx.send("❌ Неверное количество аргументов.\n"
                         "Пример: `!activity #channel1 группа YYYY-MM-DD YYYY-MM-DD`")
            return

        end_date_str = args[-1]
        start_date_str = args[-2]
        channel_args = args[:-2]

        start_dt = parse_date(start_date_str)
        end_dt = parse_date(end_date_str)
        
        if not start_dt or not end_dt:
            await ctx.send("❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД.")
            return

        end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)

        # === Определение каналов ===
        target_channels = []
        error_messages = []

        if len(channel_args) == 1 and channel_args[0] in PREDEFINED_GROUPS:
            group_name = channel_args[0]
            group_channels = PREDEFINED_GROUPS[group_name]
            
            if group_channels is None:  # all_text
                target_channels = [
                    ch for ch in ctx.guild.text_channels 
                    if ch.permissions_for(ctx.me).read_message_history
                ]
                if not target_channels:
                    error_messages.append("❌ Нет текстовых каналов с правами на чтение истории")
            else:
                for name in group_channels:
                    channel = discord.utils.get(ctx.guild.text_channels, name=name)
                    if channel and channel.permissions_for(ctx.me).read_message_history:
                        target_channels.append(channel)
                    else:
                        error_messages.append(f"⚠️ Канал `{name}` не найден или нет прав")
        else:
            for arg in channel_args:
                clean_arg = arg.lstrip('#')
                channel = None
                
                if arg.startswith('<#') and arg.endswith('>'):
                    try:
                        channel_id_str = arg[2:-1]  # Для "<#123>" → "123"
                        channel_id = int(channel_id_str)
                        channel = ctx.guild.get_channel(channel_id)
                    except (ValueError, TypeError):
                        error_messages.append(f"⚠️ Неверный ID канала в `{arg}`")
                
                if not channel:
                    channel = discord.utils.get(ctx.guild.text_channels, name=clean_arg)
                
                if channel and channel.permissions_for(ctx.me).read_message_history:
                    target_channels.append(channel)
                else:
                    error_messages.append(f"⚠️ Канал `{arg}` не найден или нет прав")

        if error_messages:
            for msg in error_messages[:5]:
                await ctx.send(msg)
        
        if not target_channels:
            await ctx.send("❌ Не удалось найти каналы для анализа")
            return

        await ctx.send(f"🔍 Анализирую **{len(target_channels)}** канал(ов): "
                      f"{', '.join(f'`{ch.name}`' for ch in target_channels)}\n"
                      f"за период: `{start_date_str}` – `{end_date_str}` ({TIMEZONE})")

        # === Сбор данных ===
        publications = []
        user_publications = defaultdict(set)
        user_attachment_count = defaultdict(int)
        daily_counts = Counter()
        total_messages = 0
        processed_channels = 0

        for channel in target_channels:
            processed_channels += 1
            try:
                async for message in channel.history(
                    after=start_dt, 
                    before=end_dt, 
                    limit=None,
                    oldest_first=True
                ):
                    total_messages += 1
                    if total_messages % 500 == 0:
                        await ctx.send(f"⏳ Обработано {total_messages} сообщений...")

                    if message.author.bot:
                        continue
                    
                    if message.attachments:
                        author_str = str(message.author)
                        msg_date = message.created_at.date()
                        daily_counts[msg_date] += 1

                        user_publications[author_str].add(message.id)
                        att_count = len(message.attachments)
                        user_attachment_count[author_str] += att_count

                        publications.append({
                            "author": author_str,
                            "user_id": message.author.id,
                            "message_url": message.jump_url,
                            "channel": channel.name,
                            "timestamp": message.created_at,
                            "attachments_count": att_count,
                            "files": [att.filename for att in message.attachments]
                        })
            except discord.Forbidden:
                await ctx.send(f"❌ Нет прав на чтение истории в канале `{channel.name}`")
            except Exception as e:
                await ctx.send(f"⚠️ Ошибка при обработке канала `{channel.name}`: {str(e)}")

        # === Формирование отчёта ===
        report_lines = [
            f"## 📊 Отчёт по активности\n"
            f"- **Период**: {start_date_str} – {end_date_str} ({TIMEZONE})\n"
            f"- **Каналы**: {len(target_channels)}\n"
            f"- **Обработано сообщений**: {total_messages}\n"
            f"- **Публикаций с вложениями**: {len(publications)}\n"
        ]

        if publications:
            current_num = 1
            for channel in target_channels:
                channel_pubs = [p for p in publications if p["channel"] == channel.name]
                if channel_pubs:
                    report_lines.append(f"\n### 📁 Канал: **#{channel.name}**")
                    for pub in channel_pubs:
                        report_lines.append(
                            f"{current_num}. **{pub['author']}** — "
                            f"[Сообщение]({pub['message_url']}) "
                            f"({pub['attachments_count']} вложений)"
                        )
                        current_num += 1

            ranking = sorted(
                user_publications.items(),
                key=lambda x: (len(x[1]), user_attachment_count[x[0]]),
                reverse=True
            )[:10]

            report_lines.append("\n### 🏆 Топ-10 по публикациям с вложениями")
            for i, (user, msg_ids) in enumerate(ranking, 1):
                pubs = len(msg_ids)
                atts = user_attachment_count[user]
                report_lines.append(f"{i}. **{user}** — {pubs} публикаций ({atts} вложений)")
        else:
            report_lines.append("\n📎 Вложений за указанный период не найдено.")

        full_report = "\n".join(report_lines)
        for chunk in [full_report[i:i+1900] for i in range(0, len(full_report), 1900)]:
            await ctx.send(chunk)

        # === Генерация CSV ===
        if publications:
            df_pub = pd.DataFrame(publications)
            df_pub.insert(0, 'number', range(1, len(df_pub) + 1))
            df_pub['timestamp'] = df_pub['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
            df_pub['files'] = df_pub['files'].apply(lambda x: '; '.join(x))

            csv_buffer = io.BytesIO()
            df_pub.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
            csv_buffer.seek(0)

            if csv_buffer.getbuffer().nbytes <= 8_000_000:
                safe_channel_name = safe_filename("_".join(ch.name for ch in target_channels[:3]))
                csv_file = discord.File(
                    csv_buffer, 
                    filename=f"activity_report_{safe_channel_name}_{start_date_str}_{end_date_str}.csv"
                )
                await ctx.send("📥 **Полные данные в CSV:**", file=csv_file)
            else:
                await ctx.send("⚠️ CSV-файл слишком большой для отправки через Discord (>8 МБ)")

        # === Генерация графика ===
        if publications and daily_counts:
            date_range = [
                start_dt.date() + datetime.timedelta(days=i)
                for i in range((end_dt.date() - start_dt.date()).days + 1)
            ]
            counts = [daily_counts[date] for date in date_range]

            try:
                fig, ax = plt.subplots(figsize=(12, 6))
                ax.bar(date_range, counts, color='#5865F2', edgecolor='white', width=0.8)
                ax.set_title("Активность по дням (публикации с вложениями)", fontsize=14, pad=20)
                ax.set_xlabel("Дата", fontsize=12, labelpad=10)
                ax.set_ylabel("Количество публикаций", fontsize=12, labelpad=10)
                plt.xticks(rotation=45, ha='right')
                ax.grid(axis='y', linestyle='--', alpha=0.7)
                plt.tight_layout()

                img_buffer = io.BytesIO()
                fig.savefig(img_buffer, format='png', dpi=120, bbox_inches='tight')
                img_buffer.seek(0)
            finally:
                plt.close(fig)

            if img_buffer.getbuffer().nbytes <= 8_000_000:
                chart_file = discord.File(img_buffer, filename="activity_chart.png")
                await ctx.send("📈 **График активности:**", file=chart_file)
            else:
                await ctx.send("⚠️ График слишком большой для отправки")

        # === Сохранение в Google Sheets ===
        if GOOGLE_INTEGRATION and publications and sheets_service:
            try:
                # Гарантируем наличие листов
                await ensure_google_sheet("Публикации", [
                    "№", "Дата экспорта", "Период", "Автор", "ID пользователя", 
                    "Ссылка на сообщение", "Канал", "Количество вложений"
                ])
                
                await ensure_google_sheet("Рейтинг", [
                    "Дата экспорта", "Автор", "Публикаций", "Вложений"
                ])

                # Запись публикаций
                pub_rows = []
                export_date = datetime.datetime.now(tz).strftime("%Y-%m-%d")
                for i, pub in enumerate(publications, 1):
                    pub_rows.append([
                        i,
                        export_date,
                        f"{start_date_str}–{end_date_str}",
                        pub["author"],
                        pub["user_id"],
                        pub["message_url"],
                        pub["channel"],
                        pub["attachments_count"]
                    ])
                
                sheets_service.spreadsheets().values().append(
                    spreadsheetId=SHEET_ID,
                    range="Публикации!A:H",
                    valueInputOption="RAW",
                    body={"values": pub_rows}
                ).execute()

                # Запись рейтинга
                rank_rows = []
                for user, msg_ids in user_publications.items():
                    rank_rows.append([
                        export_date,
                        user,
                        len(msg_ids),
                        user_attachment_count[user]
                    ])
                
                sheets_service.spreadsheets().values().append(
                    spreadsheetId=SHEET_ID,
                    range="Рейтинг!A:D",
                    valueInputOption="RAW",
                    body={"values": rank_rows}
                ).execute()

                await ctx.send("✅ Данные сохранены в Google Sheets")
            except Exception as e:
                await ctx.send(f"⚠️ Ошибка сохранения в Google Sheets: {str(e)}")

    except Exception as e:
        error_msg = f"❌ **Критическая ошибка в !activity:**\n```{traceback.format_exc()[:1000]}```"
        await ctx.send(error_msg)
        print(f"ACTIVITY ERROR: {traceback.format_exc()}")

# === 5. КОМАНДА: ЭКСПОРТ РОЛИ ===
@bot.command(name='export_role')
async def export_role(ctx, date_str: str, *, role_input: str):
    """Экспортирует пользователей с ролью
    Пример: !export_role 2026-01-15 "Media Team"
            !export_role 2026-01-15 @MediaTeam"""
    await ctx.defer()  # Отправляет "бот печатает"
    try:
        export_date = parse_date(date_str)
        if not export_date:
            await ctx.send("❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД.")
            return
        
        export_date = export_date.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Очистка ввода роли
        role_input = role_input.strip()
        if role_input.startswith('"') and role_input.endswith('"'):
            role_input = role_input[1:-1]
        elif role_input.startswith("'") and role_input.endswith("'"):
            role_input = role_input[1:-1]
        
        # Поиск роли
        role = None
        if role_input.startswith('<@&') and role_input.endswith('>'):
            try:
                role_id_str = role_input[3:-1]  # Для "<@&123>" → "123"
                role_id = int(role_id_str)
                role = ctx.guild.get_role(role_id)
            except (ValueError, TypeError):
                pass
        else:
            role = discord.utils.get(ctx.guild.roles, name=role_input)
        
        if not role:
            await ctx.send(f"❌ Роль `{role_input}` не найдена. Проверьте точное название или используйте упоминание (@Роль).")
            return

        await ctx.send(f"🔍 Собираю пользователей с ролью **{role.name}** на дату `{date_str}`...")

        # Сбор данных
        members_with_role = []
        total_members = len(ctx.guild.members)
        processed = 0

        for member in ctx.guild.members:
            processed += 1
            if processed % 100 == 0:
                await ctx.send(f"⏳ Обработано {processed}/{total_members} пользователей...")

            if member.bot:
                continue
                
            if role in member.roles:
                members_with_role.append({
                    "user_id": member.id,
                    "username": str(member),
                    "display_name": member.display_name,
                    "joined_at": member.joined_at.strftime("%Y-%m-%d %H:%M:%S") if member.joined_at else "Неизвестно",
                    "role_name": role.name
                })

        if not members_with_role:
            await ctx.send(f"👥 Пользователи с ролью **{role.name}** не найдены.")
            return

        # Текстовый отчёт
        report_lines = [
            f"## 📋 Экспорт роли: **{role.name}**",
            f"- **Дата экспорта**: {date_str} ({TIMEZONE})",
            f"- **Найдено пользователей**: {len(members_with_role)}",
            "\n### Список пользователей:"
        ]
        
        for i, member in enumerate(members_with_role, 1):
            report_lines.append(
                f"{i}. **{member['display_name']}** (`{member['username']}`)\n"
                f"   ID: `{member['user_id']}` • Вступил: {member['joined_at']}"
            )
        
        full_report = "\n".join(report_lines)
        for chunk in [full_report[i:i+1900] for i in range(0, len(full_report), 1900)]:
            await ctx.send(chunk)

        # CSV экспорт
        df = pd.DataFrame(members_with_role)
        df.insert(0, 'number', range(1, len(df) + 1))
        df['export_date'] = date_str

        csv_buffer = io.BytesIO()
        df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
        csv_buffer.seek(0)

        if csv_buffer.getbuffer().nbytes <= 8_000_000:
            safe_role_name = safe_filename(role.name)
            csv_file = discord.File(
                csv_buffer, 
                filename=f"role_export_{safe_role_name}_{date_str}.csv"
            )
            await ctx.send("📥 **Полный список в CSV:**", file=csv_file)
        else:
            await ctx.send("⚠️ CSV слишком большой для отправки через Discord")

        # Google Sheets
        if GOOGLE_INTEGRATION and sheets_service:
            try:
                await ensure_google_sheet("Роли", [
                    "Дата экспорта", "Роль", "ID пользователя", 
                    "Имя пользователя", "Отображаемое имя", 
                    "Дата вступления", "Дата сохранения"
                ])

                sheet_data = []
                save_time = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
                for member in members_with_role:
                    sheet_data.append([
                        date_str,
                        member['role_name'],
                        member['user_id'],
                        member['username'],
                        member['display_name'],
                        member['joined_at'],
                        save_time
                    ])

                sheets_service.spreadsheets().values().append(
                    spreadsheetId=SHEET_ID,
                    range="Роли!A:G",
                    valueInputOption="RAW",
                    body={"values": sheet_data}
                ).execute()

                await ctx.send("✅ Данные сохранены в Google Sheets (лист «Роли»)")
            except Exception as e:
                await ctx.send(f"⚠️ Ошибка сохранения в Google Sheets: {str(e)}")

    except Exception as e:
        error_msg = f"❌ **Ошибка в !export_role:**\n```{traceback.format_exc()[:1000]}```"
        await ctx.send(error_msg)
        print(f"ROLE EXPORT ERROR: {traceback.format_exc()}")

# === 6. СОБЫТИЯ И ЗАПУСК ===
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} успешно запущен!')
    print(f'🔗 Приглашение: https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=2147583040&scope=bot')
    print(f'🛠️ Серверов: {len(bot.guilds)}')
    print(f'👥 Пользователей: {sum(len(guild.members) for guild in bot.guilds)}')
    print(f'⏰ Часовой пояс: {TIMEZONE}')

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Неизвестная команда. Доступные команды:\n"
                      "`!activity` — анализ активности в каналах\n"
                      "`!export_role` — экспорт пользователей с ролью")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Пропущен обязательный аргумент: {error.param.name}")
    else:
        await ctx.send(f"❌ Ошибка выполнения команды: {str(error)}")

bot.run(DISCORD_TOKEN)

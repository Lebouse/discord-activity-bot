import os
import sys

# Диагностика переменных
print("🔍 Проверка переменных окружения...")
print(f"DISCORD_BOT_TOKEN: {'✅ установлен' if os.getenv('DISCORD_BOT_TOKEN') else '❌ ОТСУТСТВУЕТ'}")
print(f"GOOGLE_SHEET_ID: {'✅ установлен' if os.getenv('GOOGLE_SHEET_ID') else '❌ ОТСУТСТВУЕТ'}")
print(f"GOOGLE_CREDENTIALS_JSON: {'✅ установлен' if os.getenv('GOOGLE_CREDENTIALS_JSON') else '❌ ОТСУТСТВУЕТ'}")

# Выход, если чего-то нет
if not os.getenv("DISCORD_BOT_TOKEN"):
    print("❗ Ошибка: DISCORD_BOT_TOKEN не задан")
    sys.exit(1)
#if not os.getenv("GOOGLE_SHEET_ID"):
    print("❗ Ошибка: GOOGLE_SHEET_ID не задан")
    sys.exit(1)
#if not os.getenv("GOOGLE_CREDENTIALS_JSON"):
    print("❗ Ошибка: GOOGLE_CREDENTIALS_JSON не задан")
    sys.exit(1)

print("✅ Все переменные найдены. Запуск бота...")

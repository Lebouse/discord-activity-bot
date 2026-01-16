import os

print("🔥 ТЕКУЩИЕ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ:")
for key, value in os.environ.items():
    if "DISCORD" in key or "GOOGLE" in key:
        print(f"  {key}: {value[:4]}{'*' * (len(value)-4) if len(value) > 4 else ''}")

# ... остальной код

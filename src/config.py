import os

from dotenv import load_dotenv

load_dotenv()

# Токен бота от @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# ID админов через запятую (ТЫ — admin)
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "8587090554").split(",")
    if x.strip().lstrip("-").isdigit()
}

# Дополнительно: username админов (без @, регистр не важен)
ADMIN_USERNAMES = {
    x.strip().lstrip("@").lower()
    for x in os.getenv("ADMIN_USERNAMES", "desacratio").split(",")
    if x.strip()
}

# Необязательная бесплатная БД (Neon/Supabase). Если пусто — используется SQLite.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# Дефолтные настройки модерации
DEFAULT_WARN_LIMIT = int(os.getenv("DEFAULT_WARN_LIMIT", "3"))
DEFAULT_WARN_MUTE_MIN = int(os.getenv("DEFAULT_WARN_MUTE_MIN", "60"))
DEFAULT_FLOOD_MESSAGES = int(os.getenv("DEFAULT_FLOOD_MESSAGES", "5"))
DEFAULT_FLOOD_SECONDS = int(os.getenv("DEFAULT_FLOOD_SECONDS", "10"))
DEFAULT_SPAM_MESSAGES = int(os.getenv("DEFAULT_SPAM_MESSAGES", "3"))
DEFAULT_SPAM_SECONDS = int(os.getenv("DEFAULT_SPAM_SECONDS", "20"))

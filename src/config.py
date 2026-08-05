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

# Прокси для доступа к api.telegram.org (если Telegram заблокирован).
# Формат: http://user:pass@host:port или socks5://user:pass@host:port
# Для socks5 нужен пакет aiohttp_socks (см. requirements.txt). Пусто = без прокси.
BOT_PROXY = os.getenv("BOT_PROXY", "").strip()

# Базовый URL Bot API. По умолчанию https://api.telegram.org.
# Можно указать свой Cloudflare Worker-релей: https://<name>.workers.dev
BOT_API_BASE_URL = os.getenv("BOT_API_BASE_URL", "https://api.telegram.org").strip().rstrip("/")

# Дефолтные настройки модерации
DEFAULT_WARN_LIMIT = int(os.getenv("DEFAULT_WARN_LIMIT", "3"))
DEFAULT_WARN_MUTE_MIN = int(os.getenv("DEFAULT_WARN_MUTE_MIN", "60"))
DEFAULT_FLOOD_MESSAGES = int(os.getenv("DEFAULT_FLOOD_MESSAGES", "5"))
DEFAULT_FLOOD_SECONDS = int(os.getenv("DEFAULT_FLOOD_SECONDS", "10"))
DEFAULT_SPAM_MESSAGES = int(os.getenv("DEFAULT_SPAM_MESSAGES", "3"))
DEFAULT_SPAM_SECONDS = int(os.getenv("DEFAULT_SPAM_SECONDS", "20"))

# Опциональная нейро-модерация (OpenAI-совместимый API: GigaChat, OpenAI, Qwen и др.)
# Если не задано — правила типа «ai» неактивны, остальные работают локально.
AI_API_URL = os.getenv("AI_API_URL", "").strip()
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini").strip()
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "15"))
# Для GigaChat: AI_API_KEY — это Authorization Key (Base64 ClientID:Secret), а токен
# доступа (30 мин) получается на этом OAuth-эндпоинте. Остальное берётся автоматически.
AI_OAUTH_URL = os.getenv("AI_OAUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth").strip()
AI_OAUTH_SCOPE = os.getenv("AI_OAUTH_SCOPE", "GIGACHAT_API_PERS").strip()

# Каналы с таким числом подписчиков и больше считаются новостными — реклама их не бан.
NEWS_CHANNEL_THRESHOLD = int(os.getenv("NEWS_CHANNEL_THRESHOLD", "100000"))

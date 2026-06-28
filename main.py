import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Конфигурация из переменных окружения
# ---------------------------------------------------------------------------
TOKEN              = os.getenv("TOKEN", "")
CHANNEL_ID         = os.getenv("CHANNEL_ID", "").strip().strip("'\"")
MODERATOR_ID       = int(os.getenv("MODERATOR_ID", "0"))
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY", "")
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID", "0"))  # ID группы обсуждений канала
DATA_DIR           = os.getenv("DATA_DIR", "./data")

# ---------------------------------------------------------------------------
# Валидация обязательных переменных
# ---------------------------------------------------------------------------
_missing = [name for name, val in [("TOKEN", TOKEN), ("GEMINI_API_KEY", GEMINI_API_KEY)] if not val]
if _missing:
    raise EnvironmentError(f"Не заданы обязательные переменные окружения: {', '.join(_missing)}")

# ---------------------------------------------------------------------------
# Инфраструктура
# ---------------------------------------------------------------------------
os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Скрываем httpx логи — они содержат Telegram токен в URL
logging.getLogger("httpx").setLevel(logging.WARNING)

logger.info("Конфигурация загружена: CHANNEL_ID=%s, MODERATOR_ID=%s, DISCUSSION_GROUP_ID=%s, DATA_DIR=%s",
            CHANNEL_ID, MODERATOR_ID, DISCUSSION_GROUP_ID, DATA_DIR)

# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
genai.configure(api_key=GEMINI_API_KEY)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
model = genai.GenerativeModel(GEMINI_MODEL)

# Хранилище истории чатов (chat_id -> список сообщений)
chat_histories: dict[int, list] = {}

# ---------------------------------------------------------------------------
# Обработчики
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот на базе Gemini. Просто напиши мне что-нибудь 🤖\n"
        "Команды:\n"
        "/start — приветствие\n"
        "/clear — очистить историю диалога"
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_histories.pop(chat_id, None)
    await update.message.reply_text("История диалога очищена ✅")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        history = chat_histories.setdefault(chat_id, [])
        chat = model.start_chat(history=history)

        response = chat.send_message(user_text)
        reply_text = response.text

        chat_histories[chat_id] = chat.history

        await update.message.reply_text(reply_text)

    except Exception as e:
        logger.error("Ошибка при обращении к Gemini: %s", e, exc_info=True)
        await update.message.reply_text(
            f"⚠️ Ошибка: {type(e).__name__}: {e}"
        )


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()

# ver_0.0001
import os
import logging
import traceback
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

# ---------------------------------------------------------------------------
# Конфигурация из переменных окружения
# ---------------------------------------------------------------------------
TOKEN               = os.getenv("TOKEN", "")
CHANNEL_ID          = os.getenv("CHANNEL_ID", "").strip().strip("'\"")
MODERATOR_ID        = int(os.getenv("MODERATOR_ID", "0"))
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "")
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID", "0"))
DATA_DIR            = os.getenv("DATA_DIR", "./data")

# Список моделей для перебора при исчерпании квоты
GEMINI_MODELS = ["gemini-2.0-flash-lite", "gemini-2.0-flash", "gemini-1.5-flash-latest", "gemini-1.5-flash"]

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
logging.getLogger("httpx").setLevel(logging.WARNING)

logger.info("Конфигурация: CHANNEL_ID=%s, MODERATOR_ID=%s, DISCUSSION_GROUP_ID=%s, DATA_DIR=%s",
            CHANNEL_ID, MODERATOR_ID, DISCUSSION_GROUP_ID, DATA_DIR)
logger.info("Очередь моделей: %s", GEMINI_MODELS)

# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
genai.configure(api_key=GEMINI_API_KEY)

# Хранилище истории чатов: chat_id -> list
chat_histories: dict[int, list] = {}


async def gemini_send(history: list, user_text: str) -> tuple[str, list, str]:
    """
    Перебирает модели из GEMINI_MODELS по очереди при ResourceExhausted.
    Возвращает (текст_ответа, новая_история, имя_модели).
    При полном сбое всех моделей возвращает ("", history, "").
    """
    for model_name in GEMINI_MODELS:
        try:
            logger.info("Пробуем модель: %s", model_name)
            model = genai.GenerativeModel(model_name)
            chat = model.start_chat(history=history)
            response = chat.send_message(user_text)
            logger.info("Успех: модель=%s, длина ответа=%d", model_name, len(response.text))
            return response.text, chat.history, model_name
        except ResourceExhausted as e:
            logger.warning("Модель %s — квота исчерпана (limit=0), переходим к следующей", model_name)
            continue
        except Exception as e:
            logger.error("Модель %s — ошибка: %s\n%s", model_name, e, traceback.format_exc())
            continue

    logger.error("Все модели недоступны: %s", GEMINI_MODELS)
    return "", history, ""


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

    logger.info("Сообщение от chat_id=%s: %r", chat_id, user_text[:100])
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    history = chat_histories.setdefault(chat_id, [])
    reply_text, new_history, used_model = await gemini_send(history, user_text)

    if not reply_text:
        # Все модели недоступны — на ручную модерацию (аналог gemini_check fallback)
        logger.error("Полный сбой Gemini для chat_id=%s", chat_id)
        await update.message.reply_text(
            "⚠️ Все модели Gemini временно недоступны (квота исчерпана).\n"
            "Попробуйте позже."
        )
        return

    chat_histories[chat_id] = new_history
    await update.message.reply_text(reply_text)


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()

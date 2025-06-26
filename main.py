import asyncio
import requests
import os
import logging
from urllib.parse import quote
from telegram import (
    Bot, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton, Update,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters,
    CallbackQueryHandler
)
from telegram.error import BadRequest, TelegramError

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# Глобальные переменные состояния
last_track_id = None
channel_message_id = None
bot_active = False
bot_status_message_id = None

def get_inline_keyboard():
    """Генерирует inline-клавиатуру с кнопками управления"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Запустить трекер", callback_data="start_tracker"),
            InlineKeyboardButton("⏹️ Остановить трекер", callback_data="stop_tracker")
        ],
        [InlineKeyboardButton("🔄 Обновить статус", callback_data="refresh_status")]
    ])

# NEW: Упрощенная и корректная генерация ссылки song.link
def generate_multi_service_link(track_id: str) -> str:
    """Генерирует прямую ссылку на song.link по ID трека"""
    return f"https://song.link/ya/{track_id}"

def get_current_track():
    try:
        headers = {
            "ya-token": YANDEX_TOKEN,
            "User-Agent": "Mozilla/5.0"
        }
        r = requests.get(
            "https://api_1.mipoh.ru/get_current_track_beta", 
            headers=headers, 
            timeout=10, 
            verify=False
        )
        
        if r.status_code != 200:
            logger.warning(f"API вернул статус {r.status_code}")
            return None
            
        data = r.json()
        logger.debug(f"Полный ответ API: {data}")

        if not data.get("track"):
            logger.info("Трек не найден")
            return None
            
        t = data["track"]
        track_id = t.get("track_id")
        if not track_id:  # NEW: Проверка на наличие ID
            logger.error("Отсутствует ID трека в ответе API")
            return None

        artists = ", ".join(t["artist"]) if isinstance(t.get("artist"), list) else t.get("artist", "")
        
        return {
            "id": track_id,
            "title": t.get("title"),
            "artists": artists,
            "yandex_link": f"https://music.yandex.ru/track/{track_id}",
            "multi_link": generate_multi_service_link(track_id),  # NEW: Исправленный вызов
            "img": t.get("img")
        }
    except Exception as e:
        logger.error(f"Ошибка при получении трека: {e}", exc_info=True)
        return None

async def send_new_track_message(bot: Bot, track: dict) -> int:
    try:
        caption = f"{track['title']} — {track['artists']}"
        
        # NEW: Обновленная клавиатура с двумя кнопками
        keyboard = [
            [
                InlineKeyboardButton("🔊 Яндекс.Музыка", url=track['yandex_link']),
                InlineKeyboardButton("🌍 Все платформы", url=track['multi_link'])
            ]
        ]
        markup = InlineKeyboardMarkup(keyboard)
        
        msg = await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=track["img"],
            caption=caption,
            reply_markup=markup
        )
        logger.info(f"Отправлен трек: {caption}")
        return msg.message_id
    except Exception as e:
        logger.error(f"Ошибка отправки трека: {e}")
        return None

async def edit_track_message(bot: Bot, track: dict, msg_id: int) -> bool:
    try:
        caption = f"{track['title']} — {track['artists']}"
        media = InputMediaPhoto(media=track["img"], caption=caption)
        
        # NEW: Та же клавиатура, что и в send_new_track_message
        keyboard = [
            [
                InlineKeyboardButton("🔊 Яндекс.Музыка", url=track['yandex_link']),
                InlineKeyboardButton("🌍 Все платформы", url=track['multi_link'])
            ]
        ]
        markup = InlineKeyboardMarkup(keyboard)
        
        await bot.edit_message_media(
            chat_id=CHANNEL_ID,
            message_id=msg_id,
            media=media,
            reply_markup=markup
        )
        logger.info(f"Обновлен трек: {track['title']}")
        return True
    except Exception as e:
        logger.error(f"Ошибка обновления трека: {e}")
        return False

# ... (остальные функции без изменений: delete_message, update_status_message, track_checker, button_handler, start_command)

def main():
    # Проверка переменных окружения
    required_vars = ["TELEGRAM_BOT_TOKEN", "YANDEX_TOKEN", "CHANNEL_ID"]
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        logger.error(f"Отсутствуют переменные окружения: {', '.join(missing)}")
        return
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("Бот запущен и готов к работе")
    app.run_polling()

if __name__ == "__main__":
    main()

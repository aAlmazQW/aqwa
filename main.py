import asyncio
import requests
import os
import logging
from telegram import (
    Bot, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton, Update,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters
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
message_id = None
bot_active = False
is_paused = False
last_image = None

def get_reply_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("▶️ Запустить трекер"), KeyboardButton("⏹ Остановить трекер")]],
        resize_keyboard=True,
        one_time_keyboard=False
    )

def get_current_track():
    global is_paused
    
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

        if 'track' in data and data['track']:
            is_paused = False
            t = data["track"]
            return {
                "id": t.get("track_id"),
                "title": t.get("title"),
                "artists": ", ".join(t["artist"]) if isinstance(t.get("artist"), list) else t.get("artist", ""),
                "link": f"https://music.yandex.ru/track/{t.get('track_id')}",
                "img": t.get("img")
            }
        else:
            is_paused = True
            logger.info("Пауза: трек не найден в ответе API")
            return None
            
    except Exception as e:
        logger.error(f"Ошибка при получении трека: {e}", exc_info=True)
        return None

async def track_checker():
    global last_track_id, message_id, bot_active, is_paused, last_image
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    logger.info("Трекер запущен")
    
    last_status = None
    
    while bot_active:
        track = get_current_track()
        current_status = "pause" if is_paused else "play"
        
        if current_status != last_status:
            logger.info(f"Статус изменился: {last_status} → {current_status}")
            last_status = current_status
        
        if is_paused and current_status != last_status:
            logger.info("Обработка новой паузы")
            if message_id:
                if not await edit_to_pause_message(bot, message_id):
                    message_id = await send_pause_message(bot) or message_id
            else:
                message_id = await send_pause_message(bot)
        
        elif track and (track["id"] != last_track_id or current_status != last_status):
            logger.info("Обнаружен новый трек или возобновление воспроизведения")
            last_image = track["img"]
            
            if message_id:
                if not await edit_track_message(bot, track, message_id):
                    message_id = await send_new_track_message(bot, track)
            else:
                message_id = await send_new_track_message(bot, track)
            
            last_track_id = track["id"]
        
        await asyncio.sleep(5)

# ... (остальные функции остаются без изменений, как в предыдущем примере)

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Бот запущен и готов к работе")
    app.run_polling()

if __name__ == "__main__":
    main()

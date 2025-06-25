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

# Клавиатура для нижней панели
def get_reply_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("▶️ Запустить трекер"), 
             KeyboardButton("⏹ Остановить трекер")]
        ],
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
        logger.info(f"Полный ответ API: {data}")

        if data.get('paused', False):
            is_paused = True
            logger.info("Обнаружена пауза")
            return None
            
        if not data.get("track"):
            is_paused = True
            logger.info("Трек не найден - статус паузы")
            return None
            
        is_paused = False
        t = data["track"]
        return {
            "id": t.get("track_id"),
            "title": t.get("title"),
            "artists": ", ".join(t["artist"]) if isinstance(t.get("artist"), list) else t.get("artist", ""),
            "link": f"https://music.yandex.ru/track/{t.get('track_id')}",
            "img": t.get("img")
        }
    except Exception as e:
        logger.error(f"Ошибка при получении трека: {e}", exc_info=True)
        return None

async def send_new_track_message(bot: Bot, track: dict) -> int:
    try:
        caption = f"{track['title']} — {track['artists']}"
        keyboard = [[InlineKeyboardButton("🎧 Слушать", url=track["link"])]]
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

async def send_pause_message(bot: Bot) -> int:
    try:
        msg = await bot.send_message(
            chat_id=CHANNEL_ID,
            text="⏸️ Музыка на паузе"
        )
        logger.info("Отправлено сообщение о паузе")
        return msg.message_id
    except Exception as e:
        logger.error(f"Ошибка отправки паузы: {e}")
        return None

async def edit_track_message(bot: Bot, track: dict, msg_id: int) -> bool:
    try:
        media = InputMediaPhoto(media=track["img"], 
                             caption=f"{track['title']} — {track['artists']}")
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🎧 Слушать", url=track["link"])]])
        
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

async def edit_to_pause_message(bot: Bot, msg_id: int) -> bool:
    try:
        await bot.edit_message_caption(
            chat_id=CHANNEL_ID,
            message_id=msg_id,
            caption="⏸️ Музыка на паузе",
            reply_markup=None
        )
        logger.info("Сообщение изменено на паузу")
        return True
    except Exception as e:
        logger.error(f"Ошибка изменения на паузу: {e}")
        return False

async def delete_message(bot: Bot, msg_id: int):
    try:
        await bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
        logger.info(f"Сообщение {msg_id} удалено")
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")

async def track_checker():
    global last_track_id, message_id, bot_active, is_paused, last_image
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    logger.info("Трекер запущен")
    
    while bot_active:
        track = get_current_track()
        
        if is_paused:
            if message_id:
                if not await edit_to_pause_message(bot, message_id):
                    message_id = await send_pause_message(bot) or message_id
            else:
                message_id = await send_pause_message(bot)
        elif track:
            last_image = track["img"]
            
            if message_id:
                if track["id"] != last_track_id:
                    if not await edit_track_message(bot, track, message_id):
                        message_id = await send_new_track_message(bot, track)
                    last_track_id = track["id"]
            else:
                message_id = await send_new_track_message(bot, track)
                last_track_id = track["id"]
        
        await asyncio.sleep(5)

async def start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_active, message_id
    
    if bot_active:
        await update.message.reply_text(
            "🔴 Трекер уже работает!",
            reply_markup=get_reply_keyboard()
        )
        return
    
    bot_active = True
    message_id = None
    asyncio.create_task(track_checker())
    await update.message.reply_text(
        "🟢 Трекер запущен! Начинаю отслеживание...",
        reply_markup=get_reply_keyboard()
    )
    logger.info("Трекер запущен")

async def stop_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_active, message_id
    
    if not bot_active:
        await update.message.reply_text(
            "🔴 Трекер уже остановлен!",
            reply_markup=get_reply_keyboard()
        )
        return
    
    bot_active = False
    if message_id:
        await delete_message(Bot(token=TELEGRAM_BOT_TOKEN), message_id)
        message_id = None
    await update.message.reply_text(
        "⏹️ Трекер остановлен. Сообщение удалено.",
        reply_markup=get_reply_keyboard()
    )
    logger.info("Трекер остановлен")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "▶️ Запустить трекер":
        await start_bot(update, context)
    elif text == "⏹ Остановить трекер":
        await stop_bot(update, context)
    else:
        await update.message.reply_text(
            "Используйте кнопки для управления трекером",
            reply_markup=get_reply_keyboard()
        )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Добро пожаловать! Используйте кнопки для управления:",
        reply_markup=get_reply_keyboard()
    )

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Бот запущен и готов к работе")
    app.run_polling()

if __name__ == "__main__":
    main()

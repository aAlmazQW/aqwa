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

def generate_multi_service_link(track_title: str, artist: str, yandex_link: str) -> str:
    """Генерирует ссылку на мультисервисный поиск трека"""
    base_url = "https://song.link/ya/"
    query = f"{artist} - {track_title}"
    return f"{base_url}?q={quote(query)}&ref=yamusic_bot"

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
        yandex_link = f"https://music.yandex.ru/track/{t.get('track_id')}"
        artists = ", ".join(t["artist"]) if isinstance(t.get("artist"), list) else t.get("artist", "")
        
        return {
            "id": t.get("track_id"),
            "title": t.get("title"),
            "artists": artists,
            "yandex_link": yandex_link,
            "multi_link": generate_multi_service_link(t.get("title"), artists, yandex_link),
            "img": t.get("img")
        }
    except Exception as e:
        logger.error(f"Ошибка при получении трека: {e}", exc_info=True)
        return None

async def send_new_track_message(bot: Bot, track: dict) -> int:
    try:
        caption = f"{track['title']} — {track['artists']}"
        
        keyboard = [
            [InlineKeyboardButton("🎵 Слушать на всех платформах",
                                   url=track['multi_link'])]
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
        
        keyboard =[
            [InlineKeyboardButton("🎵 Слушать на всех платформах",
                                    url=track['multi_link'])]
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

async def delete_message(bot: Bot, chat_id: int, msg_id: int):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        logger.info(f"Сообщение {msg_id} удалено")
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")

async def update_status_message(bot: Bot, chat_id: int, text: str):
    global bot_status_message_id
    
    try:
        if bot_status_message_id:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=bot_status_message_id,
                text=text,
                reply_markup=get_inline_keyboard()
            )
        else:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=get_inline_keyboard()
            )
            bot_status_message_id = msg.message_id
    except Exception as e:
        logger.error(f"Ошибка обновления статуса: {e}")

async def track_checker():
    global last_track_id, channel_message_id, bot_active
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    logger.info("Трекер запущен")
    
    while bot_active:
        track = get_current_track()
        
        if track:
            if channel_message_id:
                if track["id"] != last_track_id:
                    if not await edit_track_message(bot, track, channel_message_id):
                        channel_message_id = await send_new_track_message(bot, track)
                    last_track_id = track["id"]
            else:
                channel_message_id = await send_new_track_message(bot, track)
                last_track_id = track["id"]
        
        await asyncio.sleep(5)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_active, channel_message_id
    query = update.callback_query
    await query.answer()
    
    if query.data == "start_tracker":
        if bot_active:
            await update_status_message(
                context.bot,
                query.message.chat.id,
                "🔴 Трекер уже работает!"
            )
            return
        
        bot_active = True
        channel_message_id = None
        asyncio.create_task(track_checker())
        await update_status_message(
            context.bot,
            query.message.chat.id,
            "🟢 Трекер запущен! Начинаю отслеживание..."
        )
    elif query.data == "stop_tracker":
        if not bot_active:
            await update_status_message(
                context.bot,
                query.message.chat.id,
                "🔴 Трекер уже остановлен!"
            )
            return
        
        bot_active = False
        if channel_message_id:
            await delete_message(
                context.bot,
                CHANNEL_ID,
                channel_message_id
            )
            channel_message_id = None
        
        await update_status_message(
            context.bot,
            query.message.chat.id,
            "⏹️ Трекер остановлен. Сообщение удалено."
        )
    elif query.data == "refresh_status":
        status_text = "🟢 Трекер активен" if bot_active else "🔴 Трекер остановлен"
        await update_status_message(
            context.bot,
            query.message.chat.id,
            f"{status_text}\n\nИспользуйте кнопки для управления:"
        )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    global bot_status_message_id
    
    if bot_status_message_id:
        try:
            await delete_message(
                context.bot,
                update.effective_chat.id,
                bot_status_message_id
            )
        except:
            pass
    
    msg = await update.message.reply_text(
        "🎵 Музыкальный трекер Яндекс.Музыки\n\n"
        "Используйте кнопки ниже для управления:",
        reply_markup=get_inline_keyboard()
    )
    bot_status_message_id = msg.message_id

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

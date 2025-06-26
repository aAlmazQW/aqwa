import asyncio
import requests
import os
import logging
from urllib.parse import quote
from telegram import (
    Bot, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton, Update
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler
)
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# Глобальные переменные состояния
last_track_id = None
channel_message_id = None
bot_active = False
bot_status_message_id = None

def get_inline_keyboard():
    """Генерирует клавиатуру управления"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Запустить", callback_data="start_tracker"),
            InlineKeyboardButton("⏹️ Остановить", callback_data="stop_tracker")
        ]
    ])

def generate_multi_link(track_id: str) -> str:
    """Генерирует ссылку на song.link"""
    return f"https://song.link/ya/{track_id}"

def generate_genius_url(title: str, artist: str) -> str:
    """Генерирует URL для поиска текста на Genius"""
    return f"https://genius.com/search?q={quote(title+' '+artist)}"

def get_current_track():
    """Получает текущий трек из Яндекс.Музыки"""
    try:
        headers = {"ya-token": YANDEX_TOKEN}
        response = requests.get(
            "https://api_1.mipoh.ru/get_current_track_beta",
            headers=headers,
            timeout=10
        )
        
        if response.status_code != 200:
            return None
            
        data = response.json()
        if not data.get("track"):
            return None
            
        track = data["track"]
        track_id = track.get("track_id")
        if not track_id:
            return None

        artists = ", ".join(track["artist"]) if isinstance(track.get("artist"), list) else track.get("artist", "")
        
        return {
            "id": track_id,
            "title": track.get("title"),
            "artists": artists,
            "yandex_link": f"https://music.yandex.ru/track/{track_id}",
            "multi_link": generate_multi_link(track_id),
            "genius_url": generate_genius_url(track.get("title"), artists),
            "img": track.get("img")
        }
    except Exception as e:
        logger.error(f"Ошибка API: {e}")
        return None

async def send_new_track_message(bot: Bot, track: dict) -> int:
    """Отправляет сообщение с треком"""
    try:
        keyboard = [
            [
                InlineKeyboardButton("🔊 Слушать", url=track['yandex_link']),
                InlineKeyboardButton("🌍 Все платформы", url=track['multi_link'])
            ],
            [InlineKeyboardButton("📝 Текст песни", url=track['genius_url'])]
        ]
        
        msg = await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=track["img"],
            caption=f"{track['title']} — {track['artists']}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return msg.message_id
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        return None

async def edit_track_message(bot: Bot, track: dict, msg_id: int) -> bool:
    """Обновляет сообщение с треком"""
    try:
        keyboard = [
            [
                InlineKeyboardButton("🔊 Слушать", url=track['yandex_link']),
                InlineKeyboardButton("🌍 Все платформы", url=track['multi_link'])
            ],
            [InlineKeyboardButton("📝 Текст песни", url=track['genius_url'])]
        ]
        
        await bot.edit_message_media(
            chat_id=CHANNEL_ID,
            message_id=msg_id,
            media=InputMediaPhoto(media=track["img"], caption=f"{track['title']} — {track['artists']}"),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка обновления: {e}")
        return False

async def track_checker():
    """Фоновая задача для отслеживания треков"""
    global last_track_id, channel_message_id, bot_active
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    logger.info("Трекер запущен")
    
    while bot_active:
        track = get_current_track()
        if track:
            if channel_message_id and track["id"] != last_track_id:
                if not await edit_track_message(bot, track, channel_message_id):
                    channel_message_id = await send_new_track_message(bot, track)
                last_track_id = track["id"]
            elif not channel_message_id:
                channel_message_id = await send_new_track_message(bot, track)
                last_track_id = track["id"]
        await asyncio.sleep(5)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок управления"""
    global bot_active, channel_message_id
    
    query = update.callback_query
    await query.answer()
    
    if query.data == "start_tracker" and not bot_active:
        bot_active = True
        channel_message_id = None
        asyncio.create_task(track_checker())
        await update.effective_message.reply_text("Трекер запущен 🎵")
        
    elif query.data == "stop_tracker" and bot_active:
        bot_active = False
        if channel_message_id:
            try:
                await Bot(token=TELEGRAM_BOT_TOKEN).delete_message(
                    chat_id=CHANNEL_ID,
                    message_id=channel_message_id
                )
            except:
                pass
            channel_message_id = None
        await update.effective_message.reply_text("Трекер остановлен ⏹️")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "🎵 Бот для отслеживания музыки\n\n"
        "Используйте кнопки ниже:",
        reply_markup=get_inline_keyboard()
    )

def main():
    """Запуск бота"""
    # Проверка переменных окружения
    required_vars = ["TELEGRAM_BOT_TOKEN", "YANDEX_TOKEN", "CHANNEL_ID"]
    if missing := [var for var in required_vars if not os.getenv(var)]:
        logger.error(f"Отсутствуют переменные: {', '.join(missing)}")
        return
    
    # Создание приложения
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Регистрация обработчиков
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()

import asyncio
import requests
import os
import logging
from urllib.parse import quote, unquote
from telegram import (
    Bot, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton, Update,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters,
    CallbackQueryHandler
)
from telegram.error import BadRequest, TelegramError
import lyricsgenius
from unidecode import unidecode
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
GENIUS_TOKEN = os.getenv("GENIUS_TOKEN")

# Инициализация Genius API
genius = None
if GENIUS_TOKEN:
    try:
        genius = lyricsgenius.Genius(
            GENIUS_TOKEN,
            timeout=15,
            remove_section_headers=True,
            skip_non_songs=True,
            excluded_terms=["(Remix)", "(Live)"]
        )
        genius.verbose = False
    except Exception as e:
        logger.error(f"Ошибка инициализации Genius API: {e}")

def get_inline_keyboard():
    """Генерирует inline-клавиатуру с кнопками управления"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Запустить трекер", callback_data="start_tracker"),
            InlineKeyboardButton("⏹️ Остановить трекер", callback_data="stop_tracker")
        ],
        [InlineKeyboardButton("🔄 Обновить статус", callback_data="refresh_status")]
    ])

def generate_multi_service_link(track_id: str) -> str:
    """Генерирует прямую ссылку на song.link по ID трека"""
    return f"https://song.link/ya/{track_id}"

def get_genius_song_url(title: str, artist: str) -> str:
    """Находит прямую ссылку на текст песни в Genius"""
    if not genius:
        return f"https://genius.com/search?q={quote(f'{artist} {title}')}"
    
    try:
        clean_title = unidecode(title.split('(')[0].split('-')[0].strip())
        clean_artist = unidecode(artist.split(',')[0].split('&')[0].strip())
        
        song = genius.search_song(clean_title, clean_artist)
        if song and song.url:
            return song.url
        
        return f"https://genius.com/search?q={quote(f'{clean_artist} {clean_title}')}"
    except Exception as e:
        logger.error(f"Ошибка поиска на Genius: {e}")
        return f"https://genius.com/search?q={quote(f'{artist} {title}')}"

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
            logger.warning(f"API статус {r.status_code}")
            return None
            
        data = r.json()
        if not data.get("track"):
            return None
            
        t = data["track"]
        track_id = t.get("track_id")
        if not track_id:
            return None

        artists = ", ".join(t["artist"]) if isinstance(t.get("artist"), list) else t.get("artist", "")
        title = t.get("title", "")
        
        return {
            "id": track_id,
            "title": title,
            "artists": artists,
            "yandex_link": f"https://music.yandex.ru/track/{track_id}",
            "multi_link": generate_multi_service_link(track_id),
            "img": t.get("img"),
            "genius_link": get_genius_song_url(title, artists)
        }
    except Exception as e:
        logger.error(f"Ошибка получения трека: {e}")
        return None

async def send_new_track_message(bot: Bot, track: dict) -> int:
    try:
        keyboard = [
            [
                InlineKeyboardButton("🔊 Яндекс", url=track['yandex_link']),
                InlineKeyboardButton("🌍 Все платформы", url=track['multi_link'])
            ],
            [InlineKeyboardButton("📝 Текст песни", url=track['genius_link'])]
        ]
        
        msg = await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=track["img"],
            caption=f"{track['title']} — {track['artists']}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return msg.message_id
    except Exception as e:
        logger.error(f"Ошибка отправки трека: {e}")
        return None

async def edit_track_message(bot: Bot, track: dict, msg_id: int) -> bool:
    try:
        keyboard = [
            [
                InlineKeyboardButton("🔊 Яндекс", url=track['yandex_link']),
                InlineKeyboardButton("🌍 Все платформы", url=track['multi_link'])
            ],
            [InlineKeyboardButton("📝 Текст песни", url=track['genius_link'])]
        ]
        
        await bot.edit_message_media(
            chat_id=CHANNEL_ID,
            message_id=msg_id,
            media=InputMediaPhoto(media=track["img"], caption=f"{track['title']} — {track['artists']}"),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка обновления трека: {e}")
        return False

# Остальные функции (delete_message, update_status_message, button_handler, 
# start_command, track_checker, main) остаются без изменений, как в вашем исходном коде

def main():
    # Проверка переменных окружения
    required_vars = ["TELEGRAM_BOT_TOKEN", "YANDEX_TOKEN", "CHANNEL_ID"]
    if missing := [var for var in required_vars if not os.getenv(var)]:
        logger.error(f"Отсутствуют обязательные переменные: {', '.join(missing)}")
        return
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()

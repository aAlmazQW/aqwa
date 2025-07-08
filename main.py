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
from telegram.error import TelegramError
import lyricsgenius
from unidecode import unidecode
from dotenv import load_dotenv

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
GENIUS_TOKEN = os.getenv("GENIUS_TOKEN")
LYRICS_CHANNEL_ID = os.getenv("LYRICS_CHANNEL_ID")

last_track_id = None
channel_message_id = None
lyrics_message_id = None
bot_active = False
bot_status_message_id = None

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

def generate_multi_service_link(track_id):
    return f"https://song.link/ya/{track_id}"

def get_genius_song_url(title, artist):
    if not genius:
        return f"https://genius.com/search?q={quote(f'{artist} {title}')}"
    try:
        clean_title = unidecode(title.split('(')[0].split('-')[0].strip())
        clean_artist = unidecode(artist.split(',')[0].split('&')[0].strip())
        song = genius.search_song(clean_title, clean_artist)
        return song.url if song and song.url else f"https://genius.com/search?q={quote(f'{clean_artist} {clean_title}')}"
    except Exception as e:
        logger.error(f"Ошибка поиска на Genius: {e}")
        return f"https://genius.com/search?q={quote(f'{artist} {title}')}"

def get_current_track():
    try:
        r = requests.get(
            "https://track.mipoh.ru/get_current_track_beta",
            headers={"ya-token": YANDEX_TOKEN, "User-Agent": "Mozilla/5.0"},
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

def fetch_lyrics(title, artist):
    # 1. Пытаемся через lrclib.net
    try:
        query = f"{title} {artist}"
        url = f"https://lrclib.net/api/search?q={quote(query)}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data:
            track_id = data[0]['track']['id']
            lyrics_data = requests.get(f"https://lrclib.net/api/get?track_id={track_id}", timeout=10).json()
            lyrics = lyrics_data.get("plainLyrics") or lyrics_data.get("syncedLyrics")
            if lyrics:
                return lyrics
    except Exception as e:
        logger.warning(f"lrclib.net не сработал: {e}")

    # 2. Пытаемся через Musixmatch
    try:
        params = {
            'q_track': title,
            'q_artist': artist,
            'apikey': 'IEJ5E8XFaHQvIQNfs7IC',
            'format': 'json'
        }
        r = requests.get(
            "https://apic-desktop.musixmatch.com/ws/1.1/matcher.lyrics.get",
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        if data and 'lyrics' in data['message']['body']:
            return data['message']['body']['lyrics']['lyrics_body'].split('...')[0].strip()
    except Exception as e:
        logger.warning(f"Musixmatch не сработал: {e}")

    return "⚠️ Текст песни не найден."

async def send_new_track_message(bot, track, lyrics_msg_id):
    keyboard = [
        [
            InlineKeyboardButton("🔊 Яндекс", url=track['yandex_link']),
            InlineKeyboardButton("🌍 Все платформы", url=track['multi_link'])
        ]
    ]
    if lyrics_msg_id:
        keyboard.append([InlineKeyboardButton("📝 Текст песни", url=f"https://t.me/{LYRICS_CHANNEL_ID.lstrip('@')}/{lyrics_msg_id}")])
    msg = await bot.send_photo(
        chat_id=CHANNEL_ID,
        photo=track["img"],
        caption=f"{track['title']} — {track['artists']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return msg.message_id

async def track_checker():
    global last_track_id, channel_message_id, bot_active, lyrics_message_id
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    while bot_active:
        track = get_current_track()
        if track and track['id'] != last_track_id:
            lyrics = fetch_lyrics(track['title'], track['artists'])
            if lyrics:
                if lyrics_message_id:
                    try:
                        await bot.edit_message_text(
                            chat_id=LYRICS_CHANNEL_ID,
                            message_id=lyrics_message_id,
                            text=f"<b>{track['title']} — {track['artists']}</b>\n\n{lyrics}",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось обновить текст песни: {e}")
                        lyrics_message_id = None
                if not lyrics_message_id:
                    msg = await bot.send_message(
                        chat_id=LYRICS_CHANNEL_ID,
                        text=f"<b>{track['title']} — {track['artists']}</b>\n\n{lyrics}",
                        parse_mode="HTML"
                    )
                    lyrics_message_id = msg.message_id
            if channel_message_id:
                try:
                    await bot.delete_message(chat_id=CHANNEL_ID, message_id=channel_message_id)
                except:
                    pass
            channel_message_id = await send_new_track_message(bot, track, lyrics_message_id)
            last_track_id = track['id']
        await asyncio.sleep(5)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_active, channel_message_id
    query = update.callback_query
    await query.answer()
    if query.data == "start_tracker":
        if not bot_active:
            bot_active = True
            channel_message_id = None
            asyncio.create_task(track_checker())
            await update_status_message(context.bot, query.message.chat.id, "🟢 Трекер запущен!")
    elif query.data == "stop_tracker":
        if bot_active:
            bot_active = False
            if channel_message_id:
                await delete_message(context.bot, CHANNEL_ID, channel_message_id)
                channel_message_id = None
            await update_status_message(context.bot, query.message.chat.id, "⏹️ Трекер остановлен")
    elif query.data == "refresh_status":
        status = "🟢 Активен" if bot_active else "🔴 Остановлен"
        await update_status_message(context.bot, query.message.chat.id, f"{status}\nУправление:")

async def update_status_message(bot: Bot, chat_id: int, text: str):
    global bot_status_message_id
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

def get_inline_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Запустить трекер", callback_data="start_tracker"),
            InlineKeyboardButton("⏹️ Остановить трекер", callback_data="stop_tracker")
        ],
        [InlineKeyboardButton("🔄 Обновить статус", callback_data="refresh_status")]
    ])

def main():
    if missing := [v for v in [TELEGRAM_BOT_TOKEN, YANDEX_TOKEN, CHANNEL_ID, LYRICS_CHANNEL_ID] if not v]:
        logger.error("Отсутствуют необходимые переменные окружения.")
        return
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Бот запущен")
    app.run_polling()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_status_message_id
    if bot_status_message_id:
        try:
            await context.bot.delete_message(update.effective_chat.id, bot_status_message_id)
        except:
            pass
    msg = await update.message.reply_text("🎵 Музыкальный трекер\nУправление:", reply_markup=get_inline_keyboard())
    bot_status_message_id = msg.message_id

async def delete_message(bot: Bot, chat_id: int, msg_id: int):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")

if __name__ == "__main__":
    main()

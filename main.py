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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
GENIUS_TOKEN = os.getenv("GENIUS_TOKEN")

# Инициализация Genius API
genius = lyricsgenius.Genius(
    GENIUS_TOKEN,
    timeout=15,
    remove_section_headers=True,
    skip_non_songs=True,
    excluded_terms=["(Remix)", "(Live)"]
)
genius.verbose = False

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

def generate_multi_service_link(track_id: str) -> str:
    """Генерирует прямую ссылку на song.link по ID трека"""
    return f"https://song.link/ya/{track_id}"

def get_lyrics(track_title: str, artist: str) -> str:
    """Получает текст песни с Genius"""
    try:
        # Очистка от спецсимволов и лишних частей
        clean_title = unidecode(track_title.split('(')[0].split('-')[0].strip())
        clean_artist = unidecode(artist.split(',')[0].split('&')[0].strip())
        
        # Поиск на Genius
        song = genius.search_song(clean_title, clean_artist)
        
        if not song:
            return f"Текст не найден 😢\nПопробуйте поискать вручную: https://genius.com/search?q={quote(f'{clean_artist} {clean_title}')}"
        
        # Очистка текста
        lyrics = song.lyrics.replace("Embed", "").replace("You might also like", "").strip()
        return lyrics[:4000]  # Обрезка под лимит Telegram
        
    except Exception as e:
        logger.error(f"Genius error: {str(e)[:100]}")
        return f"Ошибка при получении текста 😞\nПопробуйте позже или проверьте: https://genius.com/search?q={quote(f'{artist} {track_title}')}"

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
        if not track_id:
            logger.error("Отсутствует ID трека в ответе API")
            return None

        artists = ", ".join(t["artist"]) if isinstance(t.get("artist"), list) else t.get("artist", "")
        
        return {
            "id": track_id,
            "title": t.get("title"),
            "artists": artists,
            "yandex_link": f"https://music.yandex.ru/track/{track_id}",
            "multi_link": generate_multi_service_link(track_id),
            "img": t.get("img")
        }
    except Exception as e:
        logger.error(f"Ошибка при получении трека: {e}", exc_info=True)
        return None

async def send_new_track_message(bot: Bot, track: dict) -> int:
    try:
        caption = f"{track['title']} — {track['artists']}"
        
        keyboard = [
            [
                InlineKeyboardButton("🔊 Яндекс.Музыка", url=track['yandex_link']),
                InlineKeyboardButton("🌍 Все платформы", url=track['multi_link'])
            ],
            [InlineKeyboardButton("📝 Текст песни", 
                callback_data=f"lyrics_{track['id']}_{quote(track['title'])}_{quote(track['artists'])}")]
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
        
        keyboard = [
            [
                InlineKeyboardButton("🔊 Яндекс.Музыка", url=track['yandex_link']),
                InlineKeyboardButton("🌍 Все платформы", url=track['multi_link'])
            ],
            [InlineKeyboardButton("📝 Текст песни", 
                callback_data=f"lyrics_{track['id']}_{quote(track['title'])}_{quote(track['artists'])}")]
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

async def lyrics_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        _, track_id, title, artist = query.data.split('_', 3)
        title = unquote(title)
        artist = unquote(artist)
        
        # Показываем индикатор загрузки
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Ищем текст...", callback_data="loading")]
            ])
        )
        
        # Получаем текст
        lyrics = get_lyrics(title, artist)
        
        # Отправляем результат
        if len(lyrics) <= 1000:
            await query.message.reply_text(
                f"🎤 *{title}* — {artist}\n\n{lyrics}",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        else:
            # Разбиваем длинный текст на части
            parts = [lyrics[i:i+1000] for i in range(0, len(lyrics), 1000)]
            await query.message.reply_text(f"🎤 *{title}* — {artist}\n\n{parts[0]}", parse_mode="Markdown")
            for part in parts[1:]:
                await query.message.reply_text(part)
        
        # Обновляем кнопки
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔊 Слушать", url=f"https://music.yandex.ru/track/{track_id}"),
                    InlineKeyboardButton("📖 Полный текст", url=f"https://genius.com/search?q={quote(title+' '+artist)}")
                ]
            ])
        )
        
    except Exception as e:
        logger.error(f"Lyrics handler error: {e}")
        await query.message.reply_text("⚠️ Произошла ошибка. Попробуйте позже.")

# ... (остальные функции остаются без изменений: delete_message, update_status_message, 
# track_checker, button_handler, start_command)

def main():
    # Проверка переменных окружения
    required_vars = ["TELEGRAM_BOT_TOKEN", "YANDEX_TOKEN", "CHANNEL_ID", "GENIUS_TOKEN"]
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        logger.error(f"Отсутствуют переменные окружения: {', '.join(missing)}")
        return
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CallbackQueryHandler(lyrics_handler, pattern="^lyrics_"))
    
    logger.info("Бот запущен и готов к работе")
    app.run_polling()

if __name__ == "__main__":
    main()

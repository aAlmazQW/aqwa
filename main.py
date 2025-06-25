import asyncio
import requests
import os
import logging
from telegram import (
    Bot, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton, Update
)
from telegram.ext import Application, CommandHandler, ContextTypes
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

def get_current_track():
    logger.info(f"Полный ответ API: {data}")
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
        logger.debug(f"API response: {data}")
        
        # Основная проверка на паузу (если нет трека)
        if not data.get("track"):
            is_paused = True
            logger.info("Трек не найден - статус паузы")
            return None
        
        # Дополнительная проверка явного статуса паузы
        if data.get("is_paused", False):
            is_paused = True
            logger.info("Явный флаг паузы в API")
            return None
        
        # Если трек есть и нет паузы
        is_paused = False
        t = data["track"]
        return {
            "id": t.get("track_id"),
            "title": t.get("title"),
            "artists": t.get("artist") if isinstance(t.get("artist"), str) else ", ".join(t.get("artist", [])),
            "link": f"https://music.yandex.ru/track/{t.get('track_id')}",
            "img": t.get("img")
        }
    except Exception as e:
        logger.error(f"Ошибка при получении трека: {e}", exc_info=True)
        return None

async def send_new_track_message(bot: Bot, track: dict) -> int:
    """Отправляет новое сообщение с треком"""
    try:
        caption = f"{track['title']} — {track['artists']}"
        keyboard = [[InlineKeyboardButton("🎧 Слушать в Я.Музыке", url=track["link"])]]
        markup = InlineKeyboardMarkup(keyboard)
        
        msg = await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=track["img"],
            caption=caption,
            reply_markup=markup
        )
        logger.info(f"Новый трек отправлен: {caption}")
        return msg.message_id
    except Exception as e:
        logger.error(f"Ошибка отправки трека: {e}")
        return None

async def send_pause_message(bot: Bot) -> int:
    """Отправляет сообщение о паузе"""
    try:
        text = "⏸️ Музыка на паузе"
        msg = await bot.send_message(
            chat_id=CHANNEL_ID,
            text=text
        )
        logger.info("Сообщение о паузе отправлено")
        return msg.message_id
    except Exception as e:
        logger.error(f"Ошибка отправки паузы: {e}")
        return None

async def edit_track_message(bot: Bot, track: dict, msg_id: int) -> bool:
    """Обновляет сообщение с треком"""
    try:
        caption = f"{track['title']} — {track['artists']}"
        media = InputMediaPhoto(media=track["img"], caption=caption)
        keyboard = [[InlineKeyboardButton("🎧 Слушать в Я.Музыке", url=track["link"])]]
        markup = InlineKeyboardMarkup(keyboard)
        
        await bot.edit_message_media(
            chat_id=CHANNEL_ID,
            message_id=msg_id,
            media=media,
            reply_markup=markup
        )
        logger.info(f"Трек обновлен: {caption}")
        return True
    except Exception as e:
        logger.error(f"Ошибка обновления трека: {e}")
        return False

async def edit_to_pause_message(bot: Bot, msg_id: int, last_image: str) -> bool:
    """Изменяет сообщение на статус паузы"""
    try:
        if last_image:
            media = InputMediaPhoto(media=last_image, caption="⏸️ Музыка на паузе")
            await bot.edit_message_media(
                chat_id=CHANNEL_ID,
                message_id=msg_id,
                media=media,
                reply_markup=None
            )
        else:
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

async def delete_channel_message(bot: Bot, msg_id: int):
    """Удаляет сообщение в канале"""
    try:
        await bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
        logger.info(f"Сообщение {msg_id} удалено")
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")

async def track_checker():
    """Основной цикл отслеживания треков"""
    global last_track_id, message_id, bot_active, is_paused, last_image
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    logger.info("Трекер запущен")
    
    last_status = None
    
    while True:
        if not bot_active:
            await asyncio.sleep(5)
            continue
            
        track = get_current_track()
        current_status = "pause" if is_paused else "play"
        
        # Логируем изменение статуса
        if current_status != last_status:
            logger.info(f"Статус изменился: {last_status} → {current_status}")
            last_status = current_status
        
        # Обработка паузы
        if is_paused:
            if last_status != "pause":
                logger.info("Обработка паузы")
                
                if message_id:
                    if not await edit_to_pause_message(bot, message_id, last_image):
                        message_id = await send_pause_message(bot) or message_id
                else:
                    message_id = await send_pause_message(bot)
        
        # Обработка воспроизведения
        elif track:
            last_image = track["img"]
            
            if message_id is None:
                message_id = await send_new_track_message(bot, track)
                if message_id:
                    last_track_id = track["id"]
            elif track["id"] != last_track_id:
                if await edit_track_message(bot, track, message_id):
                    last_track_id = track["id"]
                else:
                    message_id = None
        
        await asyncio.sleep(5)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /start"""
    global bot_active, message_id
    
    if bot_active:
        await update.message.reply_text("🔴 Бот уже работает!")
        return
    
    bot_active = True
    message_id = None
    await update.message.reply_text("🟢 Бот запущен! Начинаю отслеживание...")
    logger.info("Бот запущен по команде /start")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /stop"""
    global bot_active, message_id, last_track_id, is_paused, last_image
    
    if not bot_active:
        await update.message.reply_text("🔴 Бот уже остановлен!")
        return
    
    bot_active = False
    
    if message_id:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await delete_channel_message(bot, message_id)
    
    message_id = None
    last_track_id = None
    is_paused = False
    last_image = None
    
    await update.message.reply_text("⏹️ Бот остановлен. Сообщение удалено.")
    logger.info("Бот остановлен по команде /stop")

def main():
    """Запуск приложения"""
    # Проверка переменных окружения
    required_vars = ["TELEGRAM_BOT_TOKEN", "YANDEX_TOKEN", "CHANNEL_ID"]
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        logger.error(f"Не хватает переменных: {', '.join(missing)}")
        return
    
    try:
        # Создаем и запускаем приложение
        loop = asyncio.get_event_loop()
        loop.create_task(track_checker())
        
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("stop", stop))
        
        logger.info("Бот готов к работе")
        app.run_polling()
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")

if __name__ == "__main__":
    main()

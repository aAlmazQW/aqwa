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
        
        # Проверяем статус воспроизведения
        if not data.get("track"):
             is_paused = True
        return None
        else:
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
    """Отправляет новое сообщение с треком и возвращает его ID"""
    try:
        caption = f"{track['title']} — {track['artists']}"
        keyboard = [[InlineKeyboardButton("🎧 Слушать в Я.Музыке", url=track["link"])]]
        markup = InlineKeyboardMarkup(keyboard)
        
        logger.info(f"Отправка нового сообщения в канал {CHANNEL_ID}")
        msg = await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=track["img"],
            caption=caption,
            reply_markup=markup
        )
        logger.info(f"Сообщение отправлено! ID: {msg.message_id}")
        return msg.message_id
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}", exc_info=True)
        return None

async def send_pause_message(bot: Bot) -> int:
    """Отправляет сообщение о паузе и возвращает его ID"""
    try:
        text = "⏸️ Музыка на паузе"
        logger.info(f"Отправка сообщения о паузе в канал {CHANNEL_ID}")
        msg = await bot.send_message(
            chat_id=CHANNEL_ID,
            text=text
        )
        logger.info(f"Сообщение о паузе отправлено! ID: {msg.message_id}")
        return msg.message_id
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения о паузе: {e}", exc_info=True)
        return None

async def edit_track_message(bot: Bot, track: dict, msg_id: int) -> bool:
    """Редактирует существующее сообщение с треком"""
    try:
        caption = f"{track['title']} — {track['artists']}"
        logger.info(f"Обновление трека: {caption}")
        
        media = InputMediaPhoto(media=track["img"], caption=caption)
        keyboard = [[InlineKeyboardButton("🎧 Слушать в Я.Музыке", url=track["link"])]]
        markup = InlineKeyboardMarkup(keyboard)
        
        logger.info(f"Редактирование сообщения ID: {msg_id}")
        await bot.edit_message_media(
            chat_id=CHANNEL_ID,
            message_id=msg_id,
            media=media,
            reply_markup=markup
        )
        logger.info("Сообщение успешно обновлено!")
        return True
    except BadRequest as e:
        if "Message to edit not found" in str(e) or "message_id_invalid" in str(e).lower():
            logger.warning(f"Сообщение не найдено: {e}")
            return False
        else:
            logger.error(f"Ошибка редактирования: {e}", exc_info=True)
            return False
    except TelegramError as e:
        logger.error(f"Ошибка Telegram API: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}", exc_info=True)
        return False

async def edit_to_pause_message(bot: Bot, msg_id: int, last_image: str) -> bool:
    """Редактирует сообщение, показывая статус паузы"""
    try:
        caption = "⏸️ Музыка на паузе"
        logger.info(f"Изменение сообщения на статус паузы, ID: {msg_id}")
        
        # Если есть последняя обложка, используем её
        if last_image:
            media = InputMediaPhoto(media=last_image, caption=caption)
            await bot.edit_message_media(
                chat_id=CHANNEL_ID,
                message_id=msg_id,
                media=media,
                reply_markup=None  # Убираем кнопку
            )
        else:
            # Если нет обложки, меняем только текст
            await bot.edit_message_caption(
                chat_id=CHANNEL_ID,
                message_id=msg_id,
                caption=caption,
                reply_markup=None
            )
            
        logger.info("Сообщение изменено на статус паузы")
        return True
    except Exception as e:
        logger.error(f"Ошибка при изменении на паузу: {e}", exc_info=True)
        return False

async def delete_channel_message(bot: Bot, msg_id: int):
    """Удаляет сообщение в канале"""
    try:
        logger.info(f"Попытка удаления сообщения ID: {msg_id}")
        await bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
        logger.info(f"Сообщение {msg_id} успешно удалено")
        return True
    except BadRequest as e:
        if "message to delete not found" in str(e).lower():
            logger.warning(f"Сообщение {msg_id} уже удалено")
        else:
            logger.error(f"Ошибка удаления сообщения: {e}", exc_info=True)
        return False
    except TelegramError as e:
        logger.error(f"Ошибка Telegram API при удалении: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при удалении: {e}", exc_info=True)
        return False

async def track_checker():
    """Основная задача отслеживания треков"""
    global last_track_id, message_id, bot_active, is_paused, last_image
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    logger.info("Задача отслеживания треков запущена")
    
    # Переменная для отслеживания предыдущего состояния
    was_paused = False
    
    while True:
        if not bot_active:
            await asyncio.sleep(5)
            continue
            
        track = get_current_track()
        
        # Если музыка на паузе
        if is_paused:
            if not was_paused:  # Только если статус изменился
                logger.info("Обнаружена пауза")
                
                if message_id:
                    # Пытаемся изменить существующее сообщение
                    success = await edit_to_pause_message(bot, message_id, last_image)
                    if not success:
                        # Если не удалось изменить, отправляем новое сообщение
                        new_msg_id = await send_pause_message(bot)
                        if new_msg_id:
                            message_id = new_msg_id
                else:
                    # Если сообщения нет, отправляем новое
                    new_msg_id = await send_pause_message(bot)
                    if new_msg_id:
                        message_id = new_msg_id
                
                was_paused = True
        else:
            # Если воспроизведение возобновлено
            if was_paused:
                logger.info("Воспроизведение возобновлено")
                was_paused = False
                
            # Обработка трека
            if track:
                # Сохраняем обложку на случай паузы
                last_image = track["img"]
                
                # Если сообщение не существует - создаем новое
                if message_id is None:
                    new_msg_id = await send_new_track_message(bot, track)
                    if new_msg_id:
                        message_id = new_msg_id
                        last_track_id = track["id"]
                    else:
                        logger.warning("Не удалось отправить сообщение, повторная попытка через 5 сек")
                else:
                    # Обновляем существующее сообщение
                    if track["id"] != last_track_id:
                        success = await edit_track_message(bot, track, message_id)
                        if success:
                            last_track_id = track["id"]
                        else:
                            logger.warning("Не удалось обновить сообщение, сбрасываю ID")
                            message_id = None  # Сбросить для создания нового сообщения
        
        await asyncio.sleep(5)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    global bot_active, message_id
    
    if bot_active:
        await update.message.reply_text("🔴 Бот уже работает!")
        return
    
    # Сброс состояния перед запуском
    bot_active = True
    message_id = None  # Сбрасываем ID сообщения для создания нового
    
    await update.message.reply_text("🟢 Бот запущен! Трек начал отслеживаться.")
    logger.info("Получена команда /start")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /stop"""
    global bot_active, message_id, last_track_id, is_paused, last_image
    
    if not bot_active:
        await update.message.reply_text("🔴 Бот уже остановлен!")
        return
    
    bot_active = False
    
    # Удаляем сообщение в канале
    if message_id:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await delete_channel_message(bot, message_id)
    
    # Сбрасываем все состояния
    message_id = None
    last_track_id = None
    is_paused = False
    last_image = None
    
    await update.message.reply_text("⏹️ Бот остановлен! Сообщение удалено.")
    logger.info("Получена команда /stop - сообщение удалено")

def main() -> None:
    """Запуск приложения"""
    # Проверка переменных окружения
    required_vars = ["TELEGRAM_BOT_TOKEN", "YANDEX_TOKEN", "CHANNEL_ID"]
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        logger.error(f"Отсутствуют переменные окружения: {', '.join(missing)}")
        return
    
    logger.info(f"Запуск бота для канала ID: {CHANNEL_ID}")
    
    # Создаем отдельную задачу для отслеживания треков
    loop = asyncio.get_event_loop()
    loop.create_task(track_checker())
    
    # Запускаем обработчик команд
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    
    logger.info("Бот готов к работе! Ожидание команд /start и /stop...")
    application.run_polling()

if __name__ == "__main__":
    main()

import asyncio
import requests
import os
from telegram import (
    Bot, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton, Update
)
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import BadRequest

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# Глобальные переменные состояния
last_track_id = None
message_id = None
bot_active = False  # Флаг активности бота
tracker_task = None  # Задача для отслеживания треков

def get_current_track():
    try:
        headers = {
            "ya-token": YANDEX_TOKEN,
            "User-Agent": "Mozilla/5.0"
        }
        r = requests.get("https://api_1.mipoh.ru/get_current_track_beta", 
                         headers=headers, timeout=10, verify=False)
        if r.status_code != 200:
            return None
        data = r.json()
        print("API:", data)
        if not data.get("track"):
            return None
        t = data["track"]
        return {
            "id": t.get("track_id"),
            "title": t.get("title"),
            "artists": t.get("artist") if isinstance(t.get("artist"), str) else ", ".join(t.get("artist", [])),
            "link": f"https://music.yandex.ru/track/{t.get('track_id')}",
            "img": t.get("img")
        }
    except Exception as e:
        print("Ошибка API:", e)
        return None

async def track_checker(bot: Bot):
    """Асинхронная задача для отслеживания треков"""
    global last_track_id, message_id, bot_active
    
    # Отправка начального сообщения
    if message_id is None:
        track = get_current_track()
        if track:
            caption = f"{track['title']} — {track['artists']}"
            keyboard = [[InlineKeyboardButton("🎧 Слушать в Я.Музыке", url=track["link"])]]
            markup = InlineKeyboardMarkup(keyboard)
            try:
                msg = await bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=track["img"],
                    caption=caption,
                    reply_markup=markup
                )
                message_id = msg.message_id
                last_track_id = track["id"]
                print("✅ Начальное сообщение отправлено")
            except Exception as e:
                print(f"🚨 Ошибка отправки сообщения: {e}")

    # Основной цикл отслеживания
    while bot_active:
        track = get_current_track()
        if isinstance(track, dict) and track["id"] != last_track_id:
            last_track_id = track["id"]
            caption = f"{track['title']} — {track['artists']}"
            print("🔄 Обновление трека:", caption)
            
            try:
                media = InputMediaPhoto(media=track["img"], caption=caption)
                keyboard = [[InlineKeyboardButton("🎧 Слушать в Я.Музыке", url=track["link"])]]
                markup = InlineKeyboardMarkup(keyboard)
                
                await bot.edit_message_media(
                    chat_id=CHANNEL_ID,
                    message_id=message_id,
                    media=media,
                    reply_markup=markup
                )
                print("✅ Сообщение обновлено")
            except BadRequest as e:
                if "Message to edit not found" in str(e):
                    print("⚠️ Сообщение не найдено, сбрасываю ID")
                    message_id = None  # Сброс для новой отправки
                else:
                    print("🚨 Ошибка редактирования:", e)
            except Exception as e:
                print("🚨 Неизвестная ошибка:", e)
        
        await asyncio.sleep(5)  # Проверка каждые 5 секунд

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    global bot_active, tracker_task
    
    if bot_active:
        await update.message.reply_text("🔴 Бот уже работает!")
        return
    
    bot_active = True
    tracker_task = asyncio.create_task(track_checker(context.bot))
    await update.message.reply_text("🟢 Бот запущен! Трек начал отслеживаться.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /stop"""
    global bot_active, tracker_task
    
    if not bot_active:
        await update.message.reply_text("🔴 Бот уже остановлен!")
        return
    
    bot_active = False
    if tracker_task:
        tracker_task.cancel()
    await update.message.reply_text("⏹️ Бот остановлен! Обновления прекращены.")

def main() -> None:
    """Запуск приложения"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    
    print("🤖 Бот запущен. Ожидание команд /start и /stop...")
    application.run_polling()

if __name__ == "__main__":
    main()
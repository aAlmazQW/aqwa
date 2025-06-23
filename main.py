
import asyncio
import requests
import os
from datetime import datetime
from telegram import (
    Bot, Update, InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

editing_active = False
last_track_id = None
message_id = None
editing_task = None

def get_current_track():
    try:
        headers = {
            "ya-token": YANDEX_TOKEN,
            "User-Agent": "Mozilla/5.0"
        }
        r = requests.get("https://api_1.mipoh.ru/get_current_track_beta", headers=headers, timeout=10, verify=False)
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
            "link": f"https://music.yandex.ru/track/{t.get("track_id")}"
        }
    except Exception as e:
        print("Ошибка API:", e)
        return None

async def track_loop(bot: Bot):
    global last_track_id, message_id, editing_active
    while editing_active:
        track = get_current_track()
        if isinstance(track, dict):
            if track["id"] != last_track_id:
                last_track_id = track["id"]
                text = f" {track['title']} — {track['artists']}"
                try:
                    keyboard = [[InlineKeyboardButton("🎧 Слушать в Я.Музыке", url=track["link"])]]
                    markup = InlineKeyboardMarkup(keyboard)
                    await bot.edit_message_text(chat_id=CHANNEL_ID, message_id=message_id, text=text, reply_markup=markup)
                    print("Обновлено:", text)
                except Exception as e:
                    print("Ошибка при редактировании:", e)
        await asyncio.sleep(5)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global editing_active, editing_task, message_id, last_track_id
    if editing_active:
        await update.message.reply_text("Уже отслеживаю 🎶")
        return
    editing_active = True
    last_track_id = None
    msg = await context.bot.send_message(chat_id=CHANNEL_ID, text="🎧 Ожидание трека...")
    message_id = msg.message_id
    editing_task = asyncio.create_task(track_loop(context.bot))
    await update.message.reply_text("Бот запущен 🚀")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global editing_active, editing_task, message_id
    editing_active = False
    if editing_task:
        editing_task.cancel()
        editing_task = None
    try:
        await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id)
    except Exception:
        pass
    await update.message.reply_text("Бот остановлен 🛑")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    print("Бот запущен с командами /start и /stop ✅")
    app.run_polling()

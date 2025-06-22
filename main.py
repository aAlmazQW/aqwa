
import asyncio
import requests
import os
from datetime import datetime
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

editing_active = False
last_track_id = None
editing_task = None
message_id = None

def get_current_track():
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "ya-token": YANDEX_TOKEN
        }
        r = requests.get("https://api_1.mipoh.ru/get_current_track_beta", headers=headers, timeout=10, verify=False)
        data = r.json()
        if r.status_code != 200 or "track" not in data:
            return None
        t = data["track"]
        track_id = t.get("track_id")
        return {
            "id": track_id,
            "title": t.get("title", "Неизвестно"),
            "artists": t.get("artist") if isinstance(t.get("artist"), str) else ", ".join(t.get("artist", [])),
            "link": f"https://music.yandex.ru/track/{track_id}"
        }
    except Exception as e:
        print("Ошибка получения трека:", e)
        return None

def save_track_to_history(title, artists):
    with open("track_history.txt", "a", encoding="utf-8") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        f.write(f"{timestamp} | {title} — {artists}\n")

async def track_loop(bot: Bot):
    global editing_active, last_track_id, message_id
    while editing_active:
        await asyncio.sleep(5)
        track = get_current_track()
        if not track:
            continue
        if track["id"] != last_track_id:
            last_track_id = track["id"]
            try:
                text = f"🎶 Сейчас играет: {track['title']} — {track['artists']}"
                save_track_to_history(track['title'], track['artists'])

                keyboard = [[InlineKeyboardButton("🎧 Слушать в Я.Музыке", url=track["link"])]]
                markup = InlineKeyboardMarkup(keyboard)

                await bot.edit_message_text(chat_id=CHANNEL_ID, message_id=message_id, text=text, reply_markup=markup)
                print("Обновлено:", text)
            except Exception as e:
                print("Ошибка при редактировании:", e)

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
    global editing_active, editing_task
    editing_active = False
    if editing_task:
        editing_task.cancel()
        editing_task = None
    await update.message.reply_text("Бот остановлен 🛑")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    print("Бот Railway готов 🚀")
    app.run_polling()

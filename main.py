import asyncio
import requests
import os
from datetime import datetime, timedelta
from collections import Counter
import matplotlib.pyplot as plt
from telegram import (
    Bot, Update, InputFile,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

editing_active = False
last_track_id = None
last_status = None
editing_task = None
message_id = None

HISTORY_FILE = "track_history.txt"

reply_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("🎧 История"), KeyboardButton("🔥 Топ")],
        [KeyboardButton("📈 График"), KeyboardButton("⏹️ Стоп")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

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
        if data.get("is_paused") or not data.get("track"):
            return "paused"
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
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        f.write(f"{timestamp} | {title} — {artists}\n")

async def track_loop(bot: Bot):
    global editing_active, last_track_id, message_id, last_status
    last_update_time = datetime.now()
    while editing_active:
        await asyncio.sleep(5)
        track = get_current_track()

        # Новый трек
        if isinstance(track, dict) and track["id"] != last_track_id:
            last_status = "playing"
            last_track_id = track["id"]
            last_update_time = datetime.now()
            try:
                text = f" {track['title']} — {track['artists']}"
                save_track_to_history(track['title'], track['artists'])
                keyboard = [[InlineKeyboardButton("🎧 Слушать в Я.Музыке", url=track["link"])]]
                markup = InlineKeyboardMarkup(keyboard)
                await bot.edit_message_text(chat_id=CHANNEL_ID, message_id=message_id, text=text, reply_markup=markup)
                print("Обновлено:", text)
            except Exception as e:
                print("Ошибка при редактировании:", e)

        # 5 минут без треков
        elif datetime.now() - last_update_time > timedelta(minutes=1) and last_status != "paused":
            last_status = "paused"
            try:
                await bot.edit_message_text(chat_id=CHANNEL_ID, message_id=message_id, text="⏸️ Сейчас ничего не играет")
                print("Обновлено: Пауза по таймеру")
            except Exception:
                pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global editing_active, editing_task, message_id, last_track_id
    if editing_active:
        await update.message.reply_text("Уже отслеживаю 🎶", reply_markup=reply_keyboard)
        return
    editing_active = True
    last_track_id = None
    msg = await context.bot.send_message(chat_id=CHANNEL_ID, text="🎧 Ожидание трека...")
    message_id = msg.message_id
    editing_task = asyncio.create_task(track_loop(context.bot))
    await update.message.reply_text("Бот запущен 🚀", reply_markup=reply_keyboard)
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🎧 История":
        await history(update, context)
    elif text == "🔥 Топ":
        await top(update, context)
    elif text == "📈 График":
        await chart(update, context)
    elif text == "⏹️ Стоп":
        await stop(update, context)

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
    await update.message.reply_text("Бот остановлен 🛑", reply_markup=reply_keyboard)

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(HISTORY_FILE):
        await update.message.reply_text("История ещё не сохранена.")
        return
    with open(HISTORY_FILE, encoding="utf-8") as f:
        lines = f.readlines()[-20:]
    history_text = "".join(lines).strip()
    if not history_text:
        history_text = "История пуста."
    await update.message.reply_text(f"📜 Последние треки:\n{history_text}")

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(HISTORY_FILE):
        await update.message.reply_text("История отсутствует.")
        return
    with open(HISTORY_FILE, encoding="utf-8") as f:
        lines = f.readlines()
    artists = [line.split("—")[-1].strip() for line in lines]
    count = Counter(artists)
    top_text = "\n".join([f"{i+1}. {name} — {qty}" for i, (name, qty) in enumerate(count.most_common(10))])
    await update.message.reply_text(f"🔥 Топ исполнителей:\n{top_text}")

async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(HISTORY_FILE):
        await update.message.reply_text("История отсутствует.")
        return
    hours = []
    with open(HISTORY_FILE, encoding="utf-8") as f:
        for line in f:
            if "|" in line:
                time_part = line.split("|")[0].strip()
                hour = int(time_part.split(" ")[1].split(":")[0])
                hours.append(hour)
    if not hours:
        await update.message.reply_text("Недостаточно данных.")
        return
    counter = Counter(hours)
    plt.figure(figsize=(8, 4))
    plt.bar(counter.keys(), counter.values(), color='skyblue')
    plt.title("🎧 Активность по часам")
    plt.xlabel("Час дня")
    plt.ylabel("Количество треков")
    plt.xticks(range(24))
    chart_path = "chart.png"
    plt.savefig(chart_path)
    plt.close()
    await update.message.reply_photo(photo=InputFile(chart_path))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    print("Бот с таймером запущен ⏰")
    app.run_polling()

import asyncio
import requests
import os
from datetime import datetime
from collections import Counter
import matplotlib.pyplot as plt
import logging
from telegram import (
    Bot, Update, InputFile,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# Проверка обязательных переменных
if not all([TELEGRAM_BOT_TOKEN, YANDEX_TOKEN, CHANNEL_ID]):
    raise ValueError("Не заданы обязательные переменные окружения!")

# Глобальные переменные
editing_active = False
last_track_id = None
last_status = None
editing_task = None
message_id = None
HISTORY_FILE = "track_history.txt"

# Клавиатура меню
reply_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("🎧 История"), KeyboardButton("🔥 Топ")],
        [KeyboardButton("📈 График"), KeyboardButton("⏹ Стоп")]
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
        
        response = requests.get(
            "https://api_1.mipoh.ru/get_current_track_beta",
            headers=headers,
            timeout=10,
            verify=False
        )
        
        if response.status_code != 200:
            logger.error(f"API вернуло статус {response.status_code}")
            return None
            
        data = response.json()
        
        if data.get("paused") or not data.get("track"):
            return "paused"
            
        track = data["track"]
        track_id = track.get("track_id")
        
        # Формируем ссылку на трек
        link = track.get("link") or f"https://music.yandex.ru/search?text={track['title']} {track['artists']}"
        
        return {
    "id": track_id,
    "title": track.get("title", "Неизвестно"),
    "artists": (
        track.get("artist") 
        if isinstance(track.get("artist"), str)
        else ", ".join(track.get("artist", [])) 
        if track.get("artist") 
        else "Неизвестный исполнитель"
    ),
    "link": link
}
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка сети: {e}")
        return None
    except ValueError as e:
        logger.error(f"Ошибка формата ответа: {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        return None

def save_track_to_history(title, artists):
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            f.write(f"{timestamp} | {title} — {artists}\n")
    except Exception as e:
        logger.error(f"Ошибка сохранения истории: {e}")

async def track_loop(bot: Bot):
    global editing_active, last_track_id, message_id, last_status
    
    while editing_active:
        try:
            await asyncio.sleep(5)
            track = get_current_track()
            
            if not track:
                continue
                
            if track == "paused":
                if last_status != "paused":
                    keyboard = [[InlineKeyboardButton("🎧 Открыть Я.Музыку", url="https://music.yandex.ru")]]
                    await bot.edit_message_text(
                        chat_id=CHANNEL_ID,
                        message_id=message_id,
                        text="⏸ Сейчас ничего не играет",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    last_status = "paused"
                    logger.info("Обновлено: Пауза")
                continue
                
            if isinstance(track, dict) and track["id"] != last_track_id:
                text = f"🎶 Сейчас играет: {track['title']} — {track['artists']}"
                keyboard = [[InlineKeyboardButton("🎧 Слушать", url=track["link"])]]
                
                await bot.edit_message_text(
                    chat_id=CHANNEL_ID,
                    message_id=message_id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                save_track_to_history(track['title'], track['artists'])
                last_track_id = track["id"]
                last_status = "playing"
                logger.info(f"Обновлено: {text}")
                
        except Exception as e:
            logger.error(f"Ошибка в track_loop: {e}")
            await asyncio.sleep(10)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global editing_active, editing_task, message_id, last_track_id
    
    if editing_active:
        await update.message.reply_text("Уже отслеживаю 🎶", reply_markup=reply_keyboard)
        return
        
    editing_active = True
    last_track_id = None
    
    try:
        msg = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="🎧 Ожидание трека...",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎧 Открыть Я.Музыку", url="https://music.yandex.ru")]])
        )
        message_id = msg.message_id
        editing_task = asyncio.create_task(track_loop(context.bot))
        await update.message.reply_text("Бот запущен 🚀", reply_markup=reply_keyboard)
        logger.info("Бот запущен пользователем %s", update.effective_user.full_name)
    except Exception as e:
        editing_active = False
        await update.message.reply_text(f"Ошибка запуска: {str(e)}")
        logger.error(f"Ошибка при запуске: {e}")

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        if text == "🎧 История":
            await history(update, context)
        elif text == "🔥 Топ":
            await top(update, context)
        elif text == "📈 График":
            await chart(update, context)
        elif text == "⏹ Стоп":
            await stop(update, context)
    except Exception as e:
        await update.message.reply_text(f"Произошла ошибка: {str(e)}")
        logger.error(f"Ошибка обработки кнопки {text}: {e}")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global editing_active, editing_task, message_id
    
    editing_active = False
    if editing_task:
        editing_task.cancel()
        editing_task = None
        
    try:
        await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id)
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение: {e}")
        
    await update.message.reply_text("Бот остановлен 🛑", reply_markup=reply_keyboard)
    logger.info("Бот остановлен пользователем %s", update.effective_user.full_name)

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not os.path.exists(HISTORY_FILE):
            await update.message.reply_text("История ещё не сохранена.")
            return
            
        with open(HISTORY_FILE, encoding="utf-8") as f:
            lines = f.readlines()[-20:]  # Последние 20 треков
            
        history_text = "".join(lines).strip() or "История пуста."
        await update.message.reply_text(f"📜 Последние треки:\n{history_text}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка чтения истории: {str(e)}")
        logger.error(f"Ошибка в функции history: {e}")

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not os.path.exists(HISTORY_FILE):
            await update.message.reply_text("История отсутствует.")
            return
            
        with open(HISTORY_FILE, encoding="utf-8") as f:
            lines = f.readlines()
            
        artists = [line.split("—")[-1].strip() for line in lines if "—" in line]
        count = Counter(artists)
        
        if not count:
            await update.message.reply_text("Недостаточно данных для топа.")
            return
            
        top_text = "\n".join([f"{i+1}. {name} — {qty}" for i, (name, qty) in enumerate(count.most_common(10))])
        await update.message.reply_text(f"🔥 Топ исполнителей:\n{top_text}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка составления топа: {str(e)}")
        logger.error(f"Ошибка в функции top: {e}")

async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not os.path.exists(HISTORY_FILE):
            await update.message.reply_text("История отсутствует.")
            return
            
        hours = []
        with open(HISTORY_FILE, encoding="utf-8") as f:
            for line in f:
                if "|" in line:
                    try:
                        time_part = line.split("|")[0].strip()
                        hour = int(time_part.split(" ")[1].split(":")[0])
                        hours.append(hour)
                    except (IndexError, ValueError):
                        continue
                        
        if not hours:
            await update.message.reply_text("Недостаточно данных.")
            return
            
        plt.figure(figsize=(10, 5))
        plt.bar(*zip(*sorted(Counter(hours).items())), color='skyblue')
        plt.title("🎧 Активность по часам")
        plt.xlabel("Час дня")
        plt.ylabel("Количество треков")
        plt.xticks(range(24))
        plt.grid(True, linestyle='--', alpha=0.7)
        
        chart_path = f"chart_{update.effective_user.id}.png"
        plt.savefig(chart_path, bbox_inches='tight')
        plt.close()
        
        await update.message.reply_photo(
            photo=InputFile(chart_path),
            caption="Ваша статистика прослушиваний"
        )
        
        try:
            os.remove(chart_path)
        except Exception as e:
            logger.warning(f"Не удалось удалить файл графика: {e}")
            
    except Exception as e:
        await update.message.reply_text(f"Ошибка построения графика: {str(e)}")
        logger.error(f"Ошибка в функции chart: {e}")

if __name__ == "__main__":
    try:
        app = ApplicationBuilder() \
            .token(TELEGRAM_BOT_TOKEN) \
            .post_init(lambda _: logger.info("Бот инициализирован")) \
            .build()
            
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
        
        logger.info("Бот запускается...")
        app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.critical(f"Фатальная ошибка: {e}")
        raise

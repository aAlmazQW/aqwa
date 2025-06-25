import asyncio
import requests
import os
from telegram import (
    Bot, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

last_track_id = None
message_id = None

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
            "link": f"https://music.yandex.ru/track/{t.get("track_id")}",
            "img": t.get("img")
        }
    except Exception as e:
        print("Ошибка API:", e)
        return None

async def main():
    global last_track_id, message_id
    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    # Отправляем первое фото-сообщение
    track = get_current_track()
    if track:
        caption = f"{track['title']} — {track['artists']}"
        keyboard = [[InlineKeyboardButton("🎧 Слушать в Я.Музыке", url=track["link"])]]
        markup = InlineKeyboardMarkup(keyboard)
        msg = await bot.send_photo(chat_id=CHANNEL_ID, photo=track["img"], caption=caption, reply_markup=markup)
        message_id = msg.message_id
        last_track_id = track["id"]

    while True:
        await asyncio.sleep(5)
        track = get_current_track()
        if isinstance(track, dict) and track["id"] != last_track_id:
            last_track_id = track["id"]
            caption = f"{track['title']} — {track['artists']}"
            print("▶️", caption)
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
            except Exception as e:
                print("Ошибка редактирования:", e)
if __name__ == "__main__":
    asyncio.run(main())
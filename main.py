

import asyncio
import requests
import os
from telegram import Bot

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

last_track_id = None

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

async def main():
    global last_track_id
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    while True:
        track = get_current_track()
        if isinstance(track, dict):
            if track["id"] != last_track_id:
                last_track_id = track["id"]
                text = f"🎶 Сейчас играет: {track['title']} — {track['artists']}"
                print("▶️", text)
                try:
                    await bot.send_message(chat_id=CHANNEL_ID, text=text)
                except Exception as e:
                    print("Ошибка отправки:", e)
        await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())

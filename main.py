import os
import time
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = None

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": chat_id,
        "text": text
    })

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    return requests.get(url, params=params).json()

def get_top():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": 10,
        "page": 1
    }

    data = requests.get(url, params=params).json()

    text = "📈 Топ монет:\n\n"

    for coin in data:
        text += f"{coin['symbol'].upper()}  ${coin['current_price']}\n"

    return text

def main():
    global CHAT_ID

    last_update = None

    while True:
        try:
            updates = get_updates(last_update)

            for item in updates.get("result", []):
                last_update = item["update_id"] + 1

                msg = item.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")

                CHAT_ID = chat_id

                if text == "/start":
                    send_message(chat_id, "✅ Бот работает")

                elif text == "/top":
                    send_message(chat_id, get_top())

            time.sleep(2)

        except Exception as e:
            print(e)
            time.sleep(5)

if __name__ == "__main__":
    main()

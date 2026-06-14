from flask import Flask
from threading import Thread
import os
import time
import requests
app = Flask('')
@app.route('/')
def home():
    return "Bot is alive"
def run():
    app.run(host='0.0.0.0', port=10000)
def keep_alive():
    t = Thread(target=run)
    t.start()
BOT_TOKEN = os.getenv("BOT_TOKEN")
def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text
        },
        timeout=20
    )
def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {
        "timeout": 30
    }
    if offset:
        params["offset"] = offset
    return requests.get(
        url,
        params=params,
        timeout=40
    ).json()
def get_top():
    try:
        url = "https://api.kucoin.com/api/v1/market/allTickers"
        response = requests.get(url, timeout=20)
        data = response.json()
        if data.get("code") != "200000":
            return f"KuCoin ошибка:\n{data}"
        tickers = data.get("data", {}).get("ticker", [])
        usdt_pairs = []
        for coin in tickers:
            symbol = coin.get("symbol", "")
            if symbol.endswith("-USDT"):
                usdt_pairs.append(coin)
        top = sorted(
            usdt_pairs,
            key=lambda x: float(x.get("volValue", 0) or 0),
            reverse=True
        )[:10]
        text = "📈 Топ монет KuCoin:\n\n"
        for coin in top:
            symbol = coin.get("symbol", "").replace("-USDT", "")
            price = coin.get("last", "0")
            change = float(coin.get("changeRate", 0) or 0) * 100
            text += (
                f"{symbol}: "
                f"${price} | "
                f"24ч: {change:.2f}%\n"
            )
        return text
    except Exception as e:
        return f"Ошибка /top:\n{e}"
def get_signal():
    try:
        url = "https://api.kucoin.com/api/v1/market/allTickers"
        response = requests.get(url, timeout=20)
        data = response.json()
        if data.get("code") != "200000":
            return f"KuCoin ошибка:\n{data}"
        tickers = data.get("data", {}).get("ticker", [])
        candidates = []
        for coin in tickers:
            symbol = coin.get("symbol", "")
            if not symbol.endswith("-USDT"):
                continue
            try:
                price = float(coin.get("last", 0) or 0)
                change = float(coin.get("changeRate", 0) or 0) * 100
                volume = float(coin.get("volValue", 0) or 0)
            except:
                continue
            if volume < 500000:
                continue
            score = 0
            reasons = []
            if change > 0:
                score += 20
                reasons.append("рост за 24ч")
            if change > 3:
                score += 25
                reasons.append("сильный импульс")
            if change > 8:
                score += 20
                reasons.append("возможен памп")
            if volume > 5000000:
                score += 25
                reasons.append("высокий объём")
            if change > 20:
                score -= 25
                reasons.append("перегрев")
            candidates.append({
                "symbol": symbol.replace("-USDT", ""),
                "price": price,
                "change": change,
                "score": score,
                "reasons": reasons
            })
        top = sorted(
            candidates,
            key=lambda x: x["score"],
            reverse=True
        )[:3]
        text = "🚀 Сигналы на рост:\n\n"
        for i, coin in enumerate(top, 1):
            text += (
                f"{i}. {coin['symbol']}\n"
                f"Цена: ${coin['price']}\n"
                f"24ч: {coin['change']:.2f}%\n"
                f"Оценка: {coin['score']}/100\n"
                f"Причины: {', '.join(coin['reasons'])}\n\n"
            )
        text += "⚠️ Не финсовет"
        return text
    except Exception as e:
        return f"Ошибка /signal:\n{e}"
def main():
    last_update = None
    while True:
        try:
            updates = get_updates(last_update)
            for item in updates.get("result", []):
                last_update = item["update_id"] + 1
                msg = item.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")
                if not chat_id:
                    continue
                if text == "/start":
                    send_message(
                        chat_id,
                        "✅ Бот работает\n\nКоманды:\n/top\n/signal"
                    )
                elif text == "/top":
                    send_message(chat_id, get_top())
                elif text == "/signal":
                    send_message(chat_id, get_signal())
            time.sleep(2)
        except Exception as e:
            print(e)
            time.sleep(5)
if __name__ == "__main__":
    keep_alive()
    main()

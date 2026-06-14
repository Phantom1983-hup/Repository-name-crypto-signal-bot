from flask import Flask
from threading import Thread
import os
import time
import requests
import statistics

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive"

def run():
    app.run(host='0.0.0.0', port=10000)

def keep_alive():
    Thread(target=run).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID_FILE = "chat_id.txt"

def save_chat_id(chat_id):
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))

def load_chat_id():
    try:
        with open(CHAT_ID_FILE, "r") as f:
            return f.read().strip()
    except:
        return None

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    keyboard = {
        "keyboard": [
            ["/top", "/signal"],
            ["/btc", "/sol"],
            ["/alerts", "/help"]
        ],
        "resize_keyboard": True
    }
    requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "reply_markup": keyboard
        },
        timeout=20
    )

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    return requests.get(url, params=params, timeout=40).json()

def kucoin_tickers():
    url = "https://api.kucoin.com/api/v1/market/allTickers"
    data = requests.get(url, timeout=20).json()
    if data.get("code") != "200000":
        raise Exception(data)
    return data.get("data", {}).get("ticker", [])

def get_candles(symbol):
    url = "https://api.kucoin.com/api/v1/market/candles"
    params = {"symbol": symbol, "type": "1hour"}
    data = requests.get(url, params=params, timeout=20).json()

    if data.get("code") != "200000":
        raise Exception(data)

    candles = data.get("data", [])
    candles = sorted(candles, key=lambda x: int(x[0]))

    closes = [float(c[2]) for c in candles]
    highs = [float(c[3]) for c in candles]
    lows = [float(c[4]) for c in candles]

    return closes, highs, lows

def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    result = values[0]
    for price in values[1:]:
        result = price * k + result * (1 - k)
    return result

def calc_rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = statistics.mean(gains[-period:])
    avg_loss = statistics.mean(losses[-period:])

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_macd(values):
    if len(values) < 26:
        return None

    ema12 = ema(values[-60:], 12)
    ema26 = ema(values[-60:], 26)

    if ema12 is None or ema26 is None:
        return None

    return ema12 - ema26

def analyze_symbol(symbol):
    tickers = kucoin_tickers()

    ticker = None
    for t in tickers:
        if t.get("symbol") == symbol:
            ticker = t
            break

    if not ticker:
        return f"Монета {symbol} не найдена."

    price = float(ticker.get("last", 0) or 0)
    change = float(ticker.get("changeRate", 0) or 0) * 100
    volume = float(ticker.get("volValue", 0) or 0)

    closes, highs, lows = get_candles(symbol)

    rsi = calc_rsi(closes)
    ema9 = ema(closes[-50:], 9)
    ema21 = ema(closes[-50:], 21)
    macd = calc_macd(closes)

    score = 0
    reasons = []

    if change > 0:
        score += 15
        reasons.append("рост за 24ч")

    if change > 3:
        score += 20
        reasons.append("сильный импульс")

    if ema9 and ema21 and ema9 > ema21:
        score += 20
        reasons.append("EMA9 выше EMA21")

    if rsi and 45 <= rsi <= 70:
        score += 20
        reasons.append("RSI нормальный")

    if macd and macd > 0:
        score += 15
        reasons.append("MACD положительный")

    if volume > 5000000:
        score += 10
        reasons.append("высокий объём")

    if rsi and rsi > 75:
        score -= 20
        reasons.append("RSI перегрет")

    if change > 20:
        score -= 25
        reasons.append("риск перегрева после пампа")

    support = min(lows[-24:]) if lows else 0
    resistance = max(highs[-24:]) if highs else 0

    if score >= 75:
        verdict = "🟢 Сильный сигнал"
    elif score >= 55:
        verdict = "🟡 Средний сигнал"
    else:
        verdict = "🔴 Слабый сигнал"

    name = symbol.replace("-USDT", "")

    return (
        f"📊 Анализ {name}\n\n"
        f"Цена: ${price}\n"
        f"24ч: {change:.2f}%\n"
        f"Объём: ${volume:,.0f}\n\n"
        f"RSI: {rsi:.1f}\n"
        f"EMA9: {ema9:.4f}\n"
        f"EMA21: {ema21:.4f}\n"
        f"MACD: {macd:.4f}\n\n"
        f"Поддержка 24ч: ${support:.4f}\n"
        f"Сопротивление 24ч: ${resistance:.4f}\n\n"
        f"Оценка: {score}/100\n"
        f"{verdict}\n\n"
        f"Причины: {', '.join(reasons)}\n\n"
        f"⚠️ Не финсовет"
    )

def get_top():
    try:
        tickers = kucoin_tickers()

        usdt_pairs = [c for c in tickers if c.get("symbol", "").endswith("-USDT")]

        top = sorted(
            usdt_pairs,
            key=lambda x: float(x.get("volValue", 0) or 0),
            reverse=True
        )[:10]

        text = "📈 Топ монет KuCoin по объёму:\n\n"

        for coin in top:
            symbol = coin.get("symbol", "").replace("-USDT", "")
            price = coin.get("last", "0")
            change = float(coin.get("changeRate", 0) or 0) * 100
            text += f"{symbol}: ${price} | 24ч: {change:.2f}%\n"

        return text

    except Exception as e:
        return f"Ошибка /top:\n{e}"

def get_signal():
    try:
        tickers = kucoin_tickers()
        candidates = []

        for coin in tickers:
            symbol = coin.get("symbol", "")

            if not symbol.endswith("-USDT"):
                continue

            price = float(coin.get("last", 0) or 0)
            change = float(coin.get("changeRate", 0) or 0) * 100
            volume = float(coin.get("volValue", 0) or 0)

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

        top = sorted(candidates, key=lambda x: x["score"], reverse=True)[:5]

        text = "🚀 Сигналы на рост 24ч:\n\n"

        for i, coin in enumerate(top, 1):
            text += (
                f"{i}. {coin['symbol']}\n"
                f"Цена: ${coin['price']}\n"
                f"24ч: {coin['change']:.2f}%\n"
                f"Оценка: {coin['score']}/100\n"
                f"Причины: {', '.join(coin['reasons'])}\n\n"
            )

        text += "⚠️ Не финсовет. Это фильтр импульса, не гарантия роста."

        return text

    except Exception as e:
        return f"Ошибка /signal:\n{e}"

def pump_alert():
    try:
        tickers = kucoin_tickers()
        alerts = []

        for coin in tickers:
            symbol = coin.get("symbol", "")

            if not symbol.endswith("-USDT"):
                continue

            change = float(coin.get("changeRate", 0) or 0) * 100
            volume = float(coin.get("volValue", 0) or 0)

            if change >= 10 and volume >= 1000000:
                alerts.append((symbol.replace("-USDT", ""), change, volume))

        alerts = sorted(alerts, key=lambda x: x[1], reverse=True)[:5]

        if not alerts:
            return None

        text = "🔥 Обнаружены сильные движения:\n\n"

        for symbol, change, volume in alerts:
            text += f"{symbol}: +{change:.2f}% | объём ${volume:,.0f}\n"

        text += "\n⚠️ Возможен памп/перегрев. Осторожно."

        return text

    except:
        return None

def help_text():
    return (
        "✅ Команды бота:\n\n"
        "/top — топ монет по объёму\n"
        "/signal — кандидаты на рост\n"
        "/btc — анализ BTC\n"
        "/sol — анализ SOL\n"
        "/alerts — проверка пампов\n"
        "/help — помощь\n\n"
        "Бот также будет раз в час присылать /signal."
    )

def main():
    last_update = None
    last_hourly_signal = 0
    last_pump_check = 0

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

                save_chat_id(chat_id)

                if text == "/start":
                    send_message(chat_id, "✅ Бот работает\n\n" + help_text())

                elif text == "/help":
                    send_message(chat_id, help_text())

                elif text == "/top":
                    send_message(chat_id, get_top())

                elif text == "/signal":
                    send_message(chat_id, get_signal())

                elif text == "/btc":
                    send_message(chat_id, analyze_symbol("BTC-USDT"))

                elif text == "/sol":
                    send_message(chat_id, analyze_symbol("SOL-USDT"))

                elif text == "/alerts":
                    alert = pump_alert()
                    send_message(chat_id, alert if alert else "Сильных пампов сейчас не найдено.")

            saved_chat_id = load_chat_id()

            if saved_chat_id:
                now = time.time()

                if now - last_hourly_signal > 3600:
                    send_message(saved_chat_id, get_signal())
                    last_hourly_signal = now

                if now - last_pump_check > 900:
                    alert = pump_alert()
                    if alert:
                        send_message(saved_chat_id, alert)
                    last_pump_check = now

            time.sleep(2)

        except Exception as e:
            print(e)
            time.sleep(5)

if __name__ == "__main__":
    keep_alive()
    main()

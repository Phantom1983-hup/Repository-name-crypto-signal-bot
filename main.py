from flask import Flask
from threading import Thread
import os, time, requests, statistics

app = Flask("")

@app.route("/")
def home():
    return "Bot is alive"

def run():
    app.run(host="0.0.0.0", port=10000)

def keep_alive():
    Thread(target=run).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID_FILE = "chat_id.txt"

AUTO_SIGNAL_EVERY = 6 * 60 * 60
AUTO_MARKET_EVERY = 24 * 60 * 60
AUTO_ALERT_EVERY = 60 * 60

def save_chat_id(chat_id):
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))

def load_chat_id():
    try:
        return open(CHAT_ID_FILE).read().strip()
    except:
        return None

def keyboard():
    return {
        "keyboard": [
            ["/signal", "/top"],
            ["/btc", "/sol"],
            ["/alerts", "/market"],
            ["/help"]
        ],
        "resize_keyboard": True
    }

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text, "reply_markup": keyboard()}, timeout=20)

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    return requests.get(url, params=params, timeout=40).json()

def kucoin_tickers():
    data = requests.get("https://api.kucoin.com/api/v1/market/allTickers", timeout=20).json()
    if data.get("code") != "200000":
        raise Exception(data)
    return data.get("data", {}).get("ticker", [])

def get_ticker(symbol):
    for t in kucoin_tickers():
        if t.get("symbol") == symbol:
            return t
    return None

def get_candles(symbol, interval="1hour"):
    url = "https://api.kucoin.com/api/v1/market/candles"
    data = requests.get(url, params={"symbol": symbol, "type": interval}, timeout=20).json()
    if data.get("code") != "200000":
        raise Exception(data)

    candles = sorted(data.get("data", []), key=lambda x: int(x[0]))
    closes = [float(c[2]) for c in candles]
    highs = [float(c[3]) for c in candles]
    lows = [float(c[4]) for c in candles]
    volumes = [float(c[5]) for c in candles]
    return closes, highs, lows, volumes

def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    result = values[0]
    for price in values[1:]:
        result = price * k + result * (1 - k)
    return result

def rsi(values, period=14):
    if len(values) < period + 1:
        return 0

    gains, losses = [], []
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

def macd(values):
    if len(values) < 35:
        return 0
    e12 = ema(values[-60:], 12)
    e26 = ema(values[-60:], 26)
    if not e12 or not e26:
        return 0
    return e12 - e26

def volume_spike(volumes):
    if len(volumes) < 20:
        return 1
    avg = statistics.mean(volumes[-20:-1])
    if avg == 0:
        return 1
    return volumes[-1] / avg

def trend_score(symbol, interval):
    closes, highs, lows, volumes = get_candles(symbol, interval)

    if len(closes) < 30:
        return {"score": 0, "rsi": 0, "macd": 0, "volume_x": 1, "support": 0, "resistance": 0}

    last = closes[-1]
    r = rsi(closes)
    e9 = ema(closes[-60:], 9)
    e21 = ema(closes[-60:], 21)
    m = macd(closes)
    vx = volume_spike(volumes)

    score = 0

    if e9 and e21 and e9 > e21:
        score += 25
    if 45 <= r <= 68:
        score += 25
    elif 68 < r <= 75:
        score += 10
    elif r > 78:
        score -= 25
    if m > 0:
        score += 20
    if vx >= 1.5:
        score += 20
    if vx >= 3:
        score += 15
    if last > max(closes[-5:-1]):
        score += 10

    return {
        "score": score,
        "rsi": r,
        "macd": m,
        "volume_x": vx,
        "support": min(lows[-24:]),
        "resistance": max(highs[-24:])
    }

def btc_market_filter():
    try:
        t = get_ticker("BTC-USDT")
        change = float(t.get("changeRate", 0) or 0) * 100
        h1 = trend_score("BTC-USDT", "1hour")
        h4 = trend_score("BTC-USDT", "4hour")

        score = 0
        if change > 0:
            score += 20
        if h1["score"] > 50:
            score += 30
        if h4["score"] > 50:
            score += 30
        if h1["rsi"] > 78:
            score -= 20

        if score >= 60:
            return "🟢 BTC фон бычий", 10, change
        elif score >= 35:
            return "🟡 BTC фон нейтральный", 0, change
        else:
            return "🔴 BTC фон слабый", -20, change
    except:
        return "⚪ BTC фон не определён", 0, 0

def potential_range(score, change, rsi_value, volume_x, btc_modifier):
    low = 0.5
    high = 2.0

    if score >= 90:
        low, high = 4.0, 9.0
    elif score >= 80:
        low, high = 3.0, 7.0
    elif score >= 70:
        low, high = 2.0, 5.0
    elif score >= 60:
        low, high = 1.0, 3.5
    else:
        low, high = 0.0, 2.0

    if volume_x >= 3:
        high += 2
    elif volume_x >= 2:
        high += 1

    if btc_modifier < 0:
        low -= 0.5
        high -= 1.5

    if rsi_value > 75:
        high -= 2
        low -= 0.5

    if change > 15:
        low = -3
        high = 3

    if change > 25:
        low = -8
        high = 2

    low = round(low, 1)
    high = round(max(high, low), 1)
    return low, high

def analyze_coin(symbol):
    ticker = get_ticker(symbol)
    if not ticker:
        return None

    price = float(ticker.get("last", 0) or 0)
    change = float(ticker.get("changeRate", 0) or 0) * 100
    volume = float(ticker.get("volValue", 0) or 0)

    m15 = trend_score(symbol, "15min")
    h1 = trend_score(symbol, "1hour")
    h4 = trend_score(symbol, "4hour")

    btc_status, btc_modifier, btc_change = btc_market_filter()

    score = 0
    reasons = []
    risks = []

    if change > 0:
        score += 10
        reasons.append("рост за 24ч")

    if 2 <= change <= 8:
        score += 20
        reasons.append("здоровый импульс 2–8%")

    if 8 < change <= 18:
        score += 10
        reasons.append("сильный импульс")

    if change > 20:
        score -= 30
        risks.append("монета уже сильно выросла")

    if volume > 1_000_000:
        score += 10
        reasons.append("объём > $1M")

    if volume > 5_000_000:
        score += 15
        reasons.append("объём > $5M")

    if m15["score"] >= 50:
        score += 15
        reasons.append("15m bullish")

    if h1["score"] >= 50:
        score += 20
        reasons.append("1h bullish")

    if h4["score"] >= 50:
        score += 20
        reasons.append("4h bullish")

    if h1["volume_x"] >= 2:
        score += 15
        reasons.append(f"объём x{h1['volume_x']:.1f}")

    if h1["rsi"] > 75:
        score -= 20
        risks.append("RSI перегрет")

    if h1["rsi"] < 35:
        score -= 10
        risks.append("импульс слабый")

    score += btc_modifier

    if btc_modifier < 0:
        risks.append("BTC фон слабый")

    score = max(0, min(100, score))

    support = h1["support"]
    resistance = h1["resistance"]

    pot_low, pot_high = potential_range(score, change, h1["rsi"], h1["volume_x"], btc_modifier)

    target_low = price * (1 + pot_low / 100)
    target_high = price * (1 + pot_high / 100)

    stop = support if support < price else price * 0.97
    downside = ((price / stop) - 1) * 100 if stop else 0

    if score >= 80:
        verdict = "🟢 Сильный сигнал"
        forecast = "вероятность роста выше средней"
    elif score >= 60:
        verdict = "🟡 Средний сигнал"
        forecast = "может расти, но нужен контроль риска"
    else:
        verdict = "🔴 Слабый сигнал"
        forecast = "лучше пропустить"

    if change > 18:
        forecast = "опасно: возможен откат после пампа"

    return {
        "symbol": symbol.replace("-USDT", ""),
        "price": price,
        "change": change,
        "volume": volume,
        "score": score,
        "verdict": verdict,
        "forecast": forecast,
        "target_low": target_low,
        "target_high": target_high,
        "pot_low": pot_low,
        "pot_high": pot_high,
        "stop": stop,
        "downside": downside,
        "rsi": h1["rsi"],
        "macd": h1["macd"],
        "volume_x": h1["volume_x"],
        "btc_status": btc_status,
        "btc_change": btc_change,
        "reasons": reasons,
        "risks": risks
    }

def get_signal():
    try:
        tickers = kucoin_tickers()
        usdt = []

        for coin in tickers:
            symbol = coin.get("symbol", "")
            if not symbol.endswith("-USDT"):
                continue

            volume = float(coin.get("volValue", 0) or 0)
            change = float(coin.get("changeRate", 0) or 0) * 100

            if volume < 800_000:
                continue

            preliminary = volume / 1_000_000 + max(change, 0) * 2
            usdt.append({"symbol": symbol, "preliminary": preliminary})

        preselected = sorted(usdt, key=lambda x: x["preliminary"], reverse=True)[:18]

        analyzed = []
        for item in preselected:
            try:
                result = analyze_coin(item["symbol"])
                if result:
                    analyzed.append(result)
                time.sleep(0.25)
            except:
                continue

        top = sorted(analyzed, key=lambda x: x["score"], reverse=True)[:3]

        if not top:
            return "Сейчас качественных сигналов нет."

        btc_status = top[0]["btc_status"]
        btc_change = top[0]["btc_change"]

        text = f"🚀 Прогноз /signal на 24ч\n{btc_status} | BTC 24ч: {btc_change:.2f}%\n\n"

        for i, c in enumerate(top, 1):
            text += (
                f"{i}. {c['symbol']} — {c['verdict']}\n"
                f"Цена: ${c['price']:.6g}\n"
                f"24ч: {c['change']:.2f}%\n"
                f"Оценка: {c['score']}/100\n"
                f"Прогноз: {c['forecast']}\n\n"
                f"📈 Потенциал 24ч: {c['pot_low']}%…{c['pot_high']}%\n"
                f"🎯 Диапазон цели: ${c['target_low']:.6g}…${c['target_high']:.6g}\n"
                f"🛑 Стоп-зона: ${c['stop']:.6g} (-{c['downside']:.2f}%)\n\n"
                f"RSI 1h: {c['rsi']:.1f}\n"
                f"MACD 1h: {c['macd']:.6g}\n"
                f"Объём 1h: x{c['volume_x']:.1f}\n\n"
                f"Почему: {', '.join(c['reasons']) if c['reasons'] else 'нет сильных причин'}\n"
                f"Риски: {', '.join(c['risks']) if c['risks'] else 'умеренные'}\n\n"
            )

        text += "⚠️ Это вероятностный прогноз, не гарантия."
        return text

    except Exception as e:
        return f"Ошибка /signal:\n{e}"

def get_top():
    try:
        tickers = kucoin_tickers()
        pairs = [x for x in tickers if x.get("symbol", "").endswith("-USDT")]
        top = sorted(pairs, key=lambda x: float(x.get("volValue", 0) or 0), reverse=True)[:10]

        text = "📈 Топ KuCoin по объёму:\n\n"
        for coin in top:
            symbol = coin.get("symbol", "").replace("-USDT", "")
            price = coin.get("last", "0")
            change = float(coin.get("changeRate", 0) or 0) * 100
            text += f"{symbol}: ${price} | 24ч: {change:.2f}%\n"

        return text
    except Exception as e:
        return f"Ошибка /top:\n{e}"

def single_analysis(symbol):
    try:
        c = analyze_coin(symbol)
        if not c:
            return "Монета не найдена."

        return (
            f"📊 Анализ {c['symbol']}\n\n"
            f"{c['btc_status']}\n"
            f"Цена: ${c['price']:.6g}\n"
            f"24ч: {c['change']:.2f}%\n"
            f"Объём: ${c['volume']:,.0f}\n\n"
            f"Оценка: {c['score']}/100\n"
            f"{c['verdict']}\n"
            f"Прогноз: {c['forecast']}\n\n"
            f"📈 Потенциал 24ч: {c['pot_low']}%…{c['pot_high']}%\n"
            f"🎯 Диапазон цели: ${c['target_low']:.6g}…${c['target_high']:.6g}\n"
            f"🛑 Стоп-зона: ${c['stop']:.6g} (-{c['downside']:.2f}%)\n\n"
            f"RSI 1h: {c['rsi']:.1f}\n"
            f"MACD 1h: {c['macd']:.6g}\n"
            f"Объём 1h: x{c['volume_x']:.1f}\n\n"
            f"Почему: {', '.join(c['reasons']) if c['reasons'] else 'нет сильных причин'}\n"
            f"Риски: {', '.join(c['risks']) if c['risks'] else 'умеренные'}\n\n"
            f"⚠️ Не финсовет"
        )
    except Exception as e:
        return f"Ошибка анализа:\n{e}"

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

            if change >= 18 and volume >= 5_000_000:
                alerts.append((symbol.replace("-USDT", ""), change, volume))

        alerts = sorted(alerts, key=lambda x: x[1], reverse=True)[:3]

        if not alerts:
            return None

        text = "🔥 Сильные движения рынка:\n\n"
        for symbol, change, volume in alerts:
            text += f"{symbol}: +{change:.2f}% | объём ${volume:,.0f}\n"

        text += "\n⚠️ Это не сигнал покупки. Возможен перегрев."
        return text

    except:
        return None

def market_status():
    try:
        btc = analyze_coin("BTC-USDT")
        eth = analyze_coin("ETH-USDT")
        sol = analyze_coin("SOL-USDT")

        text = "🌍 Суточный обзор рынка\n\n"
        for c in [btc, eth, sol]:
            text += f"{c['symbol']}: {c['score']}/100 | {c['change']:.2f}% | {c['verdict']}\n"

        text += "\nЕсли BTC слабый — альт-сигналы использовать осторожно."
        return text

    except Exception as e:
        return f"Ошибка /market:\n{e}"

def help_text():
    return (
        "✅ Команды:\n\n"
        "/signal — прогноз монет на 24ч\n"
        "/top — топ монет по объёму\n"
        "/btc — анализ BTC\n"
        "/sol — анализ SOL\n"
        "/alerts — ручная проверка сильных движений\n"
        "/market — обзор рынка\n"
        "/help — помощь\n\n"
        "Автоуведомления без спама:\n"
        "• /signal — 1 раз в 6 часов\n"
        "• /market — 1 раз в сутки\n"
        "• alert — не чаще 1 раза в час и только при сильном пампе"
    )

def main():
    last_update = None
    last_hourly_signal = time.time()
    last_market_report = time.time()
    last_pump_check = time.time()

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
                    send_message(chat_id, "⏳ Анализирую рынок, подожди 20–40 секунд...")
                    send_message(chat_id, get_signal())
                elif text == "/btc":
                    send_message(chat_id, single_analysis("BTC-USDT"))
                elif text == "/sol":
                    send_message(chat_id, single_analysis("SOL-USDT"))
                elif text == "/alerts":
                    alert = pump_alert()
                    send_message(chat_id, alert if alert else "Сильных пампов сейчас не найдено.")
                elif text == "/market":
                    send_message(chat_id, market_status())

            saved_chat_id = load_chat_id()

            if saved_chat_id:
                now = time.time()

                if now - last_hourly_signal > AUTO_SIGNAL_EVERY:
                    send_message(saved_chat_id, get_signal())
                    last_hourly_signal = now

                if now - last_market_report > AUTO_MARKET_EVERY:
                    send_message(saved_chat_id, market_status())
                    last_market_report = now

                if now - last_pump_check > AUTO_ALERT_EVERY:
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

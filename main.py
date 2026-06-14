from flask import Flask
from threading import Thread
import os
import time
import requests
import statistics
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
def save_chat_id(chat_id):
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))
def load_chat_id():
    try:
        with open(CHAT_ID_FILE, "r") as f:
            return f.read().strip()
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
    requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "reply_markup": keyboard()
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
def get_ticker(symbol):
    for t in kucoin_tickers():
        if t.get("symbol") == symbol:
            return t
    return None
def get_candles(symbol, interval="1hour"):
    url = "https://api.kucoin.com/api/v1/market/candles"
    params = {"symbol": symbol, "type": interval}
    data = requests.get(url, params=params, timeout=20).json()
    if data.get("code") != "200000":
        raise Exception(data)
    candles = data.get("data", [])
    candles = sorted(candles, key=lambda x: int(x[0]))
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
def macd(values):
    if len(values) < 35:
        return None
    e12 = ema(values[-60:], 12)
    e26 = ema(values[-60:], 26)
    if e12 is None or e26 is None:
        return None
    return e12 - e26
def volume_spike(volumes):
    if len(volumes) < 20:
        return 1
    current = volumes[-1]
    avg = statistics.mean(volumes[-20:-1])
    if avg == 0:
        return 1
    return current / avg
def trend_score(symbol, interval):
    closes, highs, lows, volumes = get_candles(symbol, interval)
    if len(closes) < 30:
        return {
            "score": 0,
            "rsi": 0,
            "macd": 0,
            "ema_fast": 0,
            "ema_slow": 0,
            "volume_x": 1,
            "support": 0,
            "resistance": 0
        }
    last = closes[-1]
    r = rsi(closes)
    e9 = ema(closes[-60:], 9)
    e21 = ema(closes[-60:], 21)
    m = macd(closes)
    vx = volume_spike(volumes)
    score = 0
    if e9 and e21 and e9 > e21:
        score += 25
    if r and 45 <= r <= 68:
        score += 25
    elif r and 68 < r <= 75:
        score += 10
    elif r and r > 78:
        score -= 20
    if m and m > 0:
        score += 20
    if vx >= 1.5:
        score += 20
    if vx >= 3:
        score += 15
    if last > max(closes[-5:-1]):
        score += 10
    return {
        "score": score,
        "rsi": r or 0,
        "macd": m or 0,
        "ema_fast": e9 or 0,
        "ema_slow": e21 or 0,
        "volume_x": vx,
        "support": min(lows[-24:]) if lows else 0,
        "resistance": max(highs[-24:]) if highs else 0
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
            status = "🟢 BTC фон бычий"
            modifier = 10
        elif score >= 35:
            status = "🟡 BTC фон нейтральный"
            modifier = 0
        else:
            status = "🔴 BTC фон слабый"
            modifier = -20
        return status, modifier, change
    except:
        return "⚪ BTC фон не определён", 0, 0
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
        score -= 25
        risks.append("монета уже сильно выросла")
    if volume > 1_000_000:
        score += 10
        reasons.append("объём > $1M")
    if volume > 5_000_000:
        score += 15
        reasons.append("высокий объём > $5M")
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
        risks.append("импульс слабый / перепроданность")
    score += btc_modifier
    if btc_modifier < 0:
        risks.append("BTC фон слабый")
    score = max(0, min(100, score))
    support = h1["support"]
    resistance = h1["resistance"]
    if resistance > price:
        target = resistance
    else:
        target = price * 1.035
    stop = support if support < price else price * 0.97
    upside = ((target / price) - 1) * 100 if price else 0
    downside = ((price / stop) - 1) * 100 if stop else 0
    if score >= 75:
        verdict = "🟢 Сильный сигнал"
        forecast = "вероятность роста выше средней"
    elif score >= 55:
        verdict = "🟡 Средний сигнал"
        forecast = "может расти, но нужен контроль риска"
    else:
        verdict = "🔴 Слабый сигнал"
        forecast = "лучше пропустить"
    if change > 18:
        forecast = "опасно: возможен резкий откат после пампа"
    return {
        "symbol": symbol.replace("-USDT", ""),
        "price": price,
        "change": change,
        "volume": volume,
        "score": score,
        "verdict": verdict,
        "forecast": forecast,
        "target": target,
        "stop": stop,
        "upside": upside,
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
        send_limit = 3
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
            usdt.append({
                "symbol": symbol,
                "volume": volume,
                "change": change,
                "preliminary": preliminary
            })
        preselected = sorted(
            usdt,
            key=lambda x: x["preliminary"],
            reverse=True
        )[:18]
        analyzed = []
        for item in preselected:
            try:
                result = analyze_coin(item["symbol"])
                if result:
                    analyzed.append(result)
                time.sleep(0.25)
            except:
                continue
        top = sorted(analyzed, key=lambda x: x["score"], reverse=True)[:send_limit]
        if not top:
            return "Сейчас качественных сигналов нет."
        btc_status = top[0]["btc_status"]
        btc_change = top[0]["btc_change"]
        text = (
            f"🚀 Прогноз /signal на 24ч\n"
            f"{btc_status} | BTC 24ч: {btc_change:.2f}%\n\n"
        )
        for i, c in enumerate(top, 1):
            text += (
                f"{i}. {c['symbol']} — {c['verdict']}\n"
                f"Цена: ${c['price']:.6g}\n"
                f"24ч: {c['change']:.2f}%\n"
                f"Оценка: {c['score']}/100\n"
                f"Прогноз: {c['forecast']}\n\n"
                f"Цель 24ч: ${c['target']:.6g} (+{c['upside']:.2f}%)\n"
                f"Стоп-зона: ${c['stop']:.6g} (-{c['downside']:.2f}%)\n"
                f"RSI 1h: {c['rsi']:.1f}\n"
                f"MACD 1h: {c['macd']:.6g}\n"
                f"Объём 1h: x{c['volume_x']:.1f}\n\n"
                f"Почему: {', '.join(c['reasons']) if c['reasons'] else 'нет сильных причин'}\n"
                f"Риски: {', '.join(c['risks']) if c['risks'] else 'умеренные'}\n\n"
            )
        text += "⚠️ Это не гарантия и не финсовет. Сигнал = вероятность, а не обещание роста."
        return text
    except Exception as e:
        return f"Ошибка /signal:\n{e}"
def get_top():
    try:
        tickers = kucoin_tickers()
        pairs = [x for x in tickers if x.get("symbol", "").endswith("-USDT")]
        top = sorted(
            pairs,
            key=lambda x: float(x.get("volValue", 0) or 0),
            reverse=True
        )[:10]
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
            f"Цель 24ч: ${c['target']:.6g} (+{c['upside']:.2f}%)\n"
            f"Стоп-зона: ${c['stop']:.6g} (-{c['downside']:.2f}%)\n\n"
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
            if change >= 12 and volume >= 1_000_000:
                alerts.append((symbol.replace("-USDT", ""), change, volume))
        alerts = sorted(alerts, key=lambda x: x[1], reverse=True)[:5]
        if not alerts:
            return "Сильных пампов сейчас не найдено."
        text = "🔥 Сильные движения:\n\n"
        for symbol, change, volume in alerts:
            text += f"{symbol}: +{change:.2f}% | объём ${volume:,.0f}\n"
        text += "\n⚠️ Это зона повышенного риска. Часто после таких движений бывает откат."
        return text
    except Exception as e:
        return f"Ошибка /alerts:\n{e}"
def market_status():
    try:
        btc = analyze_coin("BTC-USDT")
        eth = analyze_coin("ETH-USDT")
        sol = analyze_coin("SOL-USDT")
        text = "🌍 Состояние рынка\n\n"
        for c in [btc, eth, sol]:
            text += (
                f"{c['symbol']}: {c['score']}/100 | "
                f"{c['change']:.2f}% | {c['verdict']}\n"
            )
        text += "\nЕсли BTC слабый — альт-сигналы использовать осторожно."
        return text
    except Exception as e:
        return f"Ошибка /market:\n{e}"
def help_text():
    return (
        "✅ Команды:\n\n"
        "/signal — лучший прогноз монет на 24ч\n"
        "/top — топ монет по объёму\n"
        "/btc — анализ BTC\n"
        "/sol — анализ SOL\n"
        "/alerts — памп-алерты\n"
        "/market — состояние рынка\n"
        "/help — помощь\n\n"
        "Бот сам присылает /signal раз в час и памп-алерты раз в 15 минут."
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
                    send_message(chat_id, "⏳ Анализирую рынок, подожди 20–40 секунд...")
                    send_message(chat_id, get_signal())
                elif text == "/btc":
                    send_message(chat_id, single_analysis("BTC-USDT"))
                elif text == "/sol":
                    send_message(chat_id, single_analysis("SOL-USDT"))
                elif text == "/alerts":
                    send_message(chat_id, pump_alert())
                elif text == "/market":
                    send_message(chat_id, market_status())
            saved_chat_id = load_chat_id()
            if saved_chat_id:
                now = time.time()
                if now - last_hourly_signal > 3600:
                    send_message(saved_chat_id, get_signal())
                    last_hourly_signal = now
                if now - last_pump_check > 900:
                    alert = pump_alert()
                    if "Сильных пампов" not in alert:
                        send_message(saved_chat_id, alert)
                    last_pump_check = now
            time.sleep(2)
        except Exception as e:
            print(e)
            time.sleep(5)
if __name__ == "__main__":
    keep_alive()
    main()

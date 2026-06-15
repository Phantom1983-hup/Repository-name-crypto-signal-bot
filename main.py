from flask import Flask
from threading import Thread
import os, time, requests, statistics, json
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
HISTORY_FILE = "signal_history.json"
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
def load_history():
    try:
        return json.load(open(HISTORY_FILE))
    except:
        return {}
def save_history(data):
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f)
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
        json={"chat_id": chat_id, "text": text, "reply_markup": keyboard()},
        timeout=20
    )
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
def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 0
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        trs.append(tr)
    return statistics.mean(trs[-period:])
def volume_spike(volumes):
    if len(volumes) < 20:
        return 1
    avg = statistics.mean(volumes[-20:-1])
    if avg == 0:
        return 1
    return volumes[-1] / avg
def continuation_score(closes, highs, lows):
    if len(closes) < 20:
        return 0, []
    score = 0
    reasons = []
    last = closes[-1]
    prev_high = max(highs[-12:-1])
    prev_low = min(lows[-12:-1])
    if last > prev_high:
        score += 20
        reasons.append("пробой локального high")
    if lows[-1] > prev_low and lows[-3] > min(lows[-10:-3]):
        score += 15
        reasons.append("higher lows")
    if closes[-1] > closes[-2] > closes[-3]:
        score += 10
        reasons.append("3 свечи роста подряд")
    if closes[-1] > statistics.mean(closes[-20:]):
        score += 10
        reasons.append("цена выше средней 20 свечей")
    return score, reasons
def trend_score(symbol, interval):
    closes, highs, lows, volumes = get_candles(symbol, interval)
    if len(closes) < 30:
        return {
            "score": 0,
            "rsi": 0,
            "macd": 0,
            "volume_x": 1,
            "support": 0,
            "resistance": 0,
            "atr_pct": 0,
            "continuation": 0,
            "continuation_reasons": []
        }
    last = closes[-1]
    r = rsi(closes)
    e9 = ema(closes[-60:], 9)
    e21 = ema(closes[-60:], 21)
    e50 = ema(closes[-100:], 50)
    m = macd(closes)
    vx = volume_spike(volumes)
    a = atr(highs, lows, closes)
    atr_pct = (a / last) * 100 if last else 0
    cont_score, cont_reasons = continuation_score(closes, highs, lows)
    score = 0
    if e9 and e21 and e9 > e21:
        score += 20
    if e21 and e50 and e21 > e50:
        score += 20
    if 45 <= r <= 68:
        score += 25
    elif 68 < r <= 82:
        score += 12
    elif r > 82:
        score -= 5
    if m > 0:
        score += 20
    if vx >= 1.5:
        score += 15
    if vx >= 3:
        score += 15
    score += cont_score
    return {
        "score": score,
        "rsi": r,
        "macd": m,
        "volume_x": vx,
        "support": min(lows[-24:]),
        "resistance": max(highs[-24:]),
        "atr_pct": atr_pct,
        "continuation": cont_score,
        "continuation_reasons": cont_reasons
    }
def get_fear_greed():
    try:
        data = requests.get("https://api.alternative.me/fng/", timeout=10).json()
        value = int(data["data"][0]["value"])
        if value < 25:
            return value, "Extreme Fear", 5
        elif value < 45:
            return value, "Fear", 2
        elif value < 60:
            return value, "Neutral", 0
        elif value < 75:
            return value, "Greed", -2
        else:
            return value, "Extreme Greed", -6
    except:
        return 50, "no data", 0
def get_news_risk():
    try:
        url = "https://news.google.com/rss/search?q=iran+oil+hormuz+fed+trump+tariff+war+crypto+bitcoin&hl=en-US&gl=US&ceid=US:en"
        xml = requests.get(url, timeout=10).text.lower()
        words = {
            "iran": 2,
            "hormuz": 3,
            "strait": 2,
            "oil": 2,
            "war": 3,
            "attack": 2,
            "fed": 2,
            "inflation": 2,
            "tariff": 2,
            "sanction": 2,
            "trump": 1,
            "missile": 3
        }
        score = 0
        found = []
        for word, weight in words.items():
            if word in xml:
                score += weight
                found.append(word)
        if score >= 10:
            return "🔴 высокий", -6, list(set(found))[:6]
        elif score >= 5:
            return "🟠 средний", -3, list(set(found))[:6]
        else:
            return "🟢 низкий", 0, list(set(found))[:6]
    except:
        return "⚪ нет данных", 0, []
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
        if h1["rsi"] > 85:
            score -= 10
        if change < -2:
            score -= 25
        if score >= 60:
            return "🟢 BTC фон бычий", 10, change
        elif score >= 35:
            return "🟡 BTC фон нейтральный", 0, change
        else:
            return "🔴 BTC фон слабый", -15, change
    except:
        return "⚪ BTC фон не определён", 0, 0
def market_context():
    fg_value, fg_label, fg_mod = get_fear_greed()
    geo_label, geo_mod, geo_words = get_news_risk()
    btc_status, btc_mod, btc_change = btc_market_filter()
    total_mod = fg_mod + geo_mod + btc_mod
    if total_mod >= 8:
        state = "🟢 благоприятный"
    elif total_mod >= -5:
        state = "🟡 нейтральный/осторожный"
    else:
        state = "🔴 рискованный"
    return {
        "state": state,
        "fg_value": fg_value,
        "fg_label": fg_label,
        "geo_label": geo_label,
        "geo_words": geo_words,
        "btc_status": btc_status,
        "btc_mod": btc_mod,
        "btc_change": btc_change,
        "macro_mod": total_mod
    }
def get_signal_status(symbol, price, score):
    history = load_history()
    old = history.get(symbol)
    if not old:
        return "🆕 новый сигнал", 0
    old_price = old.get("price", price)
    old_score = old.get("score", score)
    old_time = old.get("time", time.time())
    hours = (time.time() - old_time) / 3600
    fact = ((price / old_price) - 1) * 100 if old_price else 0
    score_diff = score - old_score
    if score_diff >= 10:
        status = f"✅ усилился за {hours:.1f}ч"
    elif score_diff <= -15:
        status = f"⚠️ ухудшился за {hours:.1f}ч"
    else:
        status = f"↔️ подтверждается {hours:.1f}ч"
    return f"{status}, факт с прошлого сигнала: {fact:+.2f}%", fact
def save_signal_history(results):
    history = load_history()
    for c in results:
        history[c["symbol"]] = {
            "price": c["price"],
            "score": c["score"],
            "time": time.time(),
            "pot_low": c["pot_low"],
            "pot_high": c["pot_high"]
        }
    save_history(history)
def potential_range(score, change, rsi_value, volume_x, atr_pct, macro_mod, resistance_gap, continuation):
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
    high = min(high, max(2.0, atr_pct * 2.2))
    if continuation >= 25:
        low += 1.0
        high += 1.5
    if volume_x >= 3:
        high += 1.5
    elif volume_x >= 2:
        high += 0.8
    if macro_mod < -10:
        high -= 1.0
    elif macro_mod < 0:
        high -= 0.5
    elif macro_mod > 8:
        high += 0.8
    if rsi_value > 82:
        high -= 0.8
    if change > 25:
        low = -5
        high = min(high, 3)
    if resistance_gap > 0 and continuation < 25:
        high = min(high, max(1.0, resistance_gap))
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
    ctx = market_context()
    score = 0
    reasons = []
    risks = []
    if change > 0:
        score += 10
        reasons.append("рост за 24ч")
    if 2 <= change <= 8:
        score += 20
        reasons.append("здоровый импульс 2–8%")
    if 8 < change <= 15:
        score += 8
        reasons.append("сильный импульс")
    if change > 25:
        score -= 20
        risks.append("очень сильный памп")
    if volume > 1_000_000:
        score += 10
        reasons.append("ликвидность > $1M")
    if volume > 5_000_000:
        score += 15
        reasons.append("ликвидность > $5M")
    if m15["score"] >= 50:
        score += 10
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
    if h1["continuation"] >= 25:
        score += 20
        reasons += h1["continuation_reasons"]
    if 70 <= h1["rsi"] <= 82:
        score += 8
        reasons.append("RSI подтверждает сильный тренд")
    elif h1["rsi"] > 82:
        score -= 5
        reasons.append("очень сильный импульс")
        risks.append("возможен резкий откат")
    if h1["rsi"] < 35:
        score -= 10
        risks.append("импульс слабый")
    score += ctx["macro_mod"]
    if ctx["macro_mod"] < -8:
        risks.append("геополитическая нестабильность")
    score = max(0, min(100, score))
    support = h1["support"]
    resistance = h1["resistance"]
    resistance_gap = ((resistance / price) - 1) * 100 if resistance > price else 0
    pot_low, pot_high = potential_range(
        score,
        change,
        h1["rsi"],
        h1["volume_x"],
        h1["atr_pct"],
        ctx["macro_mod"],
        resistance_gap,
        h1["continuation"]
    )
    target_low = price * (1 + pot_low / 100)
    target_high = price * (1 + pot_high / 100)
    stop = support if support < price else price * 0.97
    downside = ((price / stop) - 1) * 100 if stop else 0
    if score >= 80:
        verdict = "🟢 сильный сигнал"
        probability = min(78, 50 + int(score / 4))
    elif score >= 60:
        verdict = "🟡 средний сигнал"
        probability = min(65, 42 + int(score / 5))
    else:
        verdict = "🔴 слабый сигнал"
        probability = min(50, 30 + int(score / 6))
    if pot_high <= 1.5:
        verdict = "🟡 потенциал ограничен сопротивлением"
    status, fact = get_signal_status(symbol.replace("-USDT", ""), price, score)
    return {
        "symbol": symbol.replace("-USDT", ""),
        "price": price,
        "change": change,
        "volume": volume,
        "score": score,
        "verdict": verdict,
        "probability": probability,
        "target_low": target_low,
        "target_high": target_high,
        "pot_low": pot_low,
        "pot_high": pot_high,
        "stop": stop,
        "downside": downside,
        "rsi": h1["rsi"],
        "macd": h1["macd"],
        "volume_x": h1["volume_x"],
        "atr_pct": h1["atr_pct"],
        "ctx": ctx,
        "status": status,
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
            if volume < 1_000_000:
                continue
            preliminary = volume / 1_000_000 + max(change, 0) * 2
            usdt.append({"symbol": symbol, "preliminary": preliminary})
        preselected = sorted(usdt, key=lambda x: x["preliminary"], reverse=True)[:20]
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
        save_signal_history(top)
        ctx = top[0]["ctx"]
        text = (
            f"🚀 Прогноз /signal на 24ч\n"
            f"Рынок: {ctx['state']}\n"
            f"{ctx['btc_status']} | BTC 24ч: {ctx['btc_change']:.2f}%\n"
            f"Fear & Greed: {ctx['fg_value']} ({ctx['fg_label']})\n"
            f"Геориск: {ctx['geo_label']}"
        )
        if ctx["geo_words"]:
            text += f" | темы: {', '.join(ctx['geo_words'])}"
        text += "\n\n"
        for i, c in enumerate(top, 1):
            text += (
                f"{i}. {c['symbol']} — {c['verdict']}\n"
                f"{c['status']}\n"
                f"Цена: ${c['price']:.6g}\n"
                f"24ч: {c['change']:.2f}%\n"
                f"Оценка: {c['score']}/100\n"
                f"Вероятность роста: ~{c['probability']}%\n\n"
                f"📈 Базовый сценарий 24ч: {c['pot_low']}%…{c['pot_high']}%\n"
                f"🎯 Диапазон цели: ${c['target_low']:.6g}…${c['target_high']:.6g}\n"
                f"🛑 Стоп-зона: ${c['stop']:.6g} (-{c['downside']:.2f}%)\n\n"
                f"RSI 1h: {c['rsi']:.1f}\n"
                f"MACD 1h: {c['macd']:.6g}\n"
                f"ATR 1h: {c['atr_pct']:.2f}%\n"
                f"Объём 1h: x{c['volume_x']:.1f}\n\n"
                f"Почему: {', '.join(c['reasons']) if c['reasons'] else 'нет сильных причин'}\n"
                f"Риски: {', '.join(c['risks']) if c['risks'] else 'умеренные'}\n\n"
            )
        text += "⚠️ Это вероятностный сценарий. Если BTC резко развернётся, прогноз отменяется."
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
    c = analyze_coin(symbol)
    if not c:
        return "Монета не найдена."
    return (
        f"📊 Анализ {c['symbol']}\n\n"
        f"{c['ctx']['btc_status']}\n"
        f"Геориск: {c['ctx']['geo_label']}\n"
        f"Цена: ${c['price']:.6g}\n"
        f"24ч: {c['change']:.2f}%\n\n"
        f"Оценка: {c['score']}/100\n"
        f"Вероятность роста: ~{c['probability']}%\n"
        f"{c['verdict']}\n\n"
        f"📈 Потенциал 24ч: {c['pot_low']}%…{c['pot_high']}%\n"
        f"🎯 Цель: ${c['target_low']:.6g}…${c['target_high']:.6g}\n"
        f"🛑 Стоп: ${c['stop']:.6g} (-{c['downside']:.2f}%)\n\n"
        f"RSI: {c['rsi']:.1f}\n"
        f"MACD: {c['macd']:.6g}\n"
        f"ATR: {c['atr_pct']:.2f}%\n"
        f"Объём: x{c['volume_x']:.1f}\n\n"
        f"Почему: {', '.join(c['reasons']) if c['reasons'] else 'нет сильных причин'}\n"
        f"Риски: {', '.join(c['risks']) if c['risks'] else 'умеренные'}"
    )
def pump_alert():
    try:
        alerts = []
        for coin in kucoin_tickers():
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
    ctx = market_context()
    return (
        f"🌍 Суточный обзор рынка\n\n"
        f"Рынок: {ctx['state']}\n"
        f"{ctx['btc_status']} | BTC 24ч: {ctx['btc_change']:.2f}%\n"
        f"Fear & Greed: {ctx['fg_value']} ({ctx['fg_label']})\n"
        f"Геориск: {ctx['geo_label']}\n"
        f"Темы: {', '.join(ctx['geo_words']) if ctx['geo_words'] else 'нет сильных триггеров'}\n\n"
        f"Если геориск высокий или BTC слабый — альт-сигналы использовать осторожно."
    )
def help_text():
    return (
        "✅ Команды:\n\n"
        "/signal — прогноз монет на 24ч\n"
        "/top — топ монет по объёму\n"
        "/btc — анализ BTC\n"
        "/sol — анализ SOL\n"
        "/alerts — сильные движения\n"
        "/market — макро и рынок\n"
        "/help — помощь\n\n"
        "В /signal учитывается: BTC фон, Fear & Greed, геополитика, RSI, MACD, ATR, объём, уровни, continuation и история прошлого сигнала."
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

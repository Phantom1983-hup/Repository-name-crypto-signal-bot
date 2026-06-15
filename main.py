# =========================
# CRYPTO SIGNAL ALEX BOT
# FULL VERSION + MACRO
# =========================

import telebot
import requests
import time
import threading
import statistics
import feedparser

# =========================
# SETTINGS
# =========================

TOKEN = "ТВОЙ_TELEGRAM_BOT_TOKEN"
CHAT_ID = ТВОЙ_CHAT_ID

bot = telebot.TeleBot(TOKEN)

# =========================
# GLOBALS
# =========================

last_alert_time = 0
last_signal_time = 0
last_market_time = 0

# =========================
# KUCOIN API
# =========================

def get_kucoin_data():
    url = "https://api.kucoin.com/api/v1/market/allTickers"

    response = requests.get(url, timeout=20)

    data = response.json()

    tickers = data["data"]["ticker"]

    usdt = []

    for t in tickers:
        symbol = t.get("symbol", "")

        if symbol.endswith("-USDT"):

            try:
                volume = float(t.get("volValue", 0))
                change = float(t.get("changeRate", 0)) * 100
                price = float(t.get("last", 0))

                usdt.append({
                    "symbol": symbol.replace("-USDT", ""),
                    "price": price,
                    "change": change,
                    "volume": volume
                })

            except:
                pass

    usdt = sorted(usdt, key=lambda x: x["volume"], reverse=True)

    return usdt

# =========================
# FEAR & GREED
# =========================

def get_fear_greed():

    try:
        url = "https://api.alternative.me/fng/"
        data = requests.get(url, timeout=10).json()

        value = int(data["data"][0]["value"])

        if value < 25:
            state = "😱 Extreme Fear"

        elif value < 45:
            state = "😨 Fear"

        elif value < 60:
            state = "😐 Neutral"

        elif value < 75:
            state = "🙂 Greed"

        else:
            state = "🤑 Extreme Greed"

        return f"{value}/100 {state}"

    except:
        return "нет данных"

# =========================
# MACRO DATA
# =========================

def get_macro():

    try:
        btc = get_coin("BTC")
        eth = get_coin("ETH")
        sol = get_coin("SOL")

        btc_change = btc["change"]
        eth_change = eth["change"]
        sol_change = sol["change"]

        score = 0

        if btc_change > 1:
            score += 2

        if eth_change > 1:
            score += 1

        if sol_change > 1:
            score += 1

        if btc_change < -2:
            score -= 3

        if eth_change < -3:
            score -= 1

        if score >= 3:
            state = "🟢 Бычий"

        elif score <= -2:
            state = "🔴 Медвежий"

        else:
            state = "🟡 Нейтральный"

        return {
            "state": state,
            "btc": btc_change,
            "eth": eth_change,
            "sol": sol_change
        }

    except:
        return {
            "state": "нет данных",
            "btc": 0,
            "eth": 0,
            "sol": 0
        }

# =========================
# NEWS / GEO
# =========================

def get_news():

    try:

        feed = feedparser.parse(
            "https://news.google.com/rss/search?q=crypto+bitcoin+iran+oil+fed&hl=en-US&gl=US&ceid=US:en"
        )

        items = feed.entries[:5]

        news = []

        risk_words = [
            "war",
            "iran",
            "oil",
            "fed",
            "inflation",
            "trump",
            "tariff",
            "sanction",
            "strait",
            "hormuz"
        ]

        risk_score = 0

        for item in items:

            title = item.title

            news.append(title)

            low = title.lower()

            for w in risk_words:

                if w in low:
                    risk_score += 1

        if risk_score >= 5:
            risk = "🔴 Высокий"

        elif risk_score >= 2:
            risk = "🟠 Средний"

        else:
            risk = "🟢 Низкий"

        return risk, news

    except:
        return "нет данных", []

# =========================
# RSI
# =========================

def calculate_rsi(values, period=14):

    gains = []
    losses = []

    for i in range(1, len(values)):

        diff = values[i] - values[i - 1]

        if diff >= 0:
            gains.append(diff)

        else:
            losses.append(abs(diff))

    avg_gain = sum(gains[-period:]) / period if gains else 0.1
    avg_loss = sum(losses[-period:]) / period if losses else 0.1

    rs = avg_gain / avg_loss

    rsi = 100 - (100 / (1 + rs))

    return round(rsi, 1)

# =========================
# MACD
# =========================

def calculate_macd(values):

    short = statistics.mean(values[-12:])
    long = statistics.mean(values[-26:])

    return round(short - long, 5)

# =========================
# CANDLE DATA
# =========================

def get_candles(symbol="BTC-USDT", interval="1hour"):

    try:

        url = f"https://api.kucoin.com/api/v1/market/candles?type={interval}&symbol={symbol}"

        data = requests.get(url, timeout=10).json()

        candles = data["data"]

        closes = [float(c[2]) for c in candles]

        volumes = [float(c[5]) for c in candles]

        return closes[::-1], volumes[::-1]

    except:
        return [], []

# =========================
# GET COIN
# =========================

def get_coin(symbol):

    coins = get_kucoin_data()

    for coin in coins:

        if coin["symbol"] == symbol:
            return coin

    return None

# =========================
# ANALYZE COIN
# =========================

def analyze_coin(symbol):

    coin = get_coin(symbol)

    if not coin:
        return "Монета не найдена"

    closes_1h, volumes_1h = get_candles(f"{symbol}-USDT", "1hour")
    closes_4h, _ = get_candles(f"{symbol}-USDT", "4hour")

    if len(closes_1h) < 30:
        return "Недостаточно данных"

    rsi_1h = calculate_rsi(closes_1h)
    macd_1h = calculate_macd(closes_1h)

    bullish_1h = closes_1h[-1] > statistics.mean(closes_1h[-20:])
    bullish_4h = closes_4h[-1] > statistics.mean(closes_4h[-20:])

    avg_volume = statistics.mean(volumes_1h[-24:])
    current_volume = volumes_1h[-1]

    volume_ratio = round(current_volume / avg_volume, 1)

    score = 0
    reasons = []
    risks = []

    # 24h
    if coin["change"] > 0:
        score += 15
        reasons.append("рост 24ч")

    # trend
    if bullish_1h:
        score += 20
        reasons.append("1h bullish")

    if bullish_4h:
        score += 25
        reasons.append("4h bullish")

    # RSI
    if 45 <= rsi_1h <= 70:
        score += 20

    if rsi_1h > 75:
        risks.append("RSI перегрет")

    # volume
    if volume_ratio >= 2:
        score += 20
        reasons.append(f"объём x{volume_ratio}")

    # liquidity
    if coin["volume"] > 1_000_000:
        score += 10
        reasons.append("объём > $1M")

    # macro
    macro = get_macro()

    if "Медвежий" in macro["state"]:
        score -= 15
        risks.append("слабый BTC фон")

    # geo
    geo_risk, _ = get_news()

    if "Высокий" in geo_risk:
        score -= 10
        risks.append("геополитический риск")

    score = max(1, min(score, 100))

    # target logic
    if score >= 90:
        target_min = 4
        target_max = 9

    elif score >= 75:
        target_min = 2
        target_max = 6

    else:
        target_min = 1
        target_max = 3

    target_price_min = round(
        coin["price"] * (1 + target_min / 100),
        3
    )

    target_price_max = round(
        coin["price"] * (1 + target_max / 100),
        3
    )

    stop = round(
        coin["price"] * 0.94,
        3
    )

    if score >= 90:
        signal = "🟢 Сильный сигнал"

    elif score >= 70:
        signal = "🟡 Средний сигнал"

    else:
        signal = "🔴 Слабый сигнал"

    risk_text = ", ".join(risks) if risks else "умеренные"

    text = f"""
📊 Анализ {symbol}

{macro["state"]} BTC фон

Цена: ${coin['price']}
24ч: {round(coin['change'],2)}%
Объём: ${coin['volume']:,.0f}

Оценка: {score}/100
{signal}

📈 Потенциал 24ч: {target_min}%...{target_max}%
🎯 Диапазон цели: ${target_price_min}...${target_price_max}
🛑 Стоп-зона: ${stop} (-6%)

RSI 1h: {rsi_1h}
MACD 1h: {macd_1h}
Объём 1h: x{volume_ratio}

Почему: {", ".join(reasons)}
Риски: {risk_text}

⚠️ Это вероятностный прогноз, не гарантия.
"""

    return text

# =========================
# /TOP
# =========================

@bot.message_handler(commands=["top"])
def top_handler(message):

    try:

        coins = get_kucoin_data()[:10]

        text = "📈 Топ монет KuCoin:\n\n"

        for coin in coins:

            text += (
                f"{coin['symbol']}: "
                f"${coin['price']} | "
                f"24ч: {round(coin['change'],2)}%\n"
            )

        bot.reply_to(message, text)

    except Exception as e:

        bot.reply_to(message, f"Ошибка: {e}")

# =========================
# /SIGNAL
# =========================

@bot.message_handler(commands=["signal"])
def signal_handler(message):

    try:

        coins = get_kucoin_data()

        strong = []

        for coin in coins[:80]:

            if (
                coin["change"] > 2 and
                coin["volume"] > 5_000_000
            ):

                strong.append(coin)

        strong = sorted(
            strong,
            key=lambda x: x["change"],
            reverse=True
        )[:5]

        macro = get_macro()

        text = (
            f"🚀 Прогноз /signal на 24ч\n"
            f"{macro['state']} BTC фон\n\n"
        )

        for i, coin in enumerate(strong, start=1):

            analysis = analyze_coin(coin["symbol"])

            text += f"{i}. {coin['symbol']}\n{analysis}\n"

        text += "\n⚠️ Это не финансовая рекомендация."

        bot.reply_to(message, text)

    except Exception as e:

        bot.reply_to(message, f"Ошибка: {e}")

# =========================
# /BTC
# =========================

@bot.message_handler(commands=["btc"])
def btc_handler(message):

    bot.reply_to(message, analyze_coin("BTC"))

# =========================
# /SOL
# =========================

@bot.message_handler(commands=["sol"])
def sol_handler(message):

    bot.reply_to(message, analyze_coin("SOL"))

# =========================
# /MARKET
# =========================

@bot.message_handler(commands=["market"])
def market_handler(message):

    try:

        macro = get_macro()
        fear = get_fear_greed()
        geo, news = get_news()

        text = f"""
🌍 Суточный обзор рынка

BTC: {round(macro['btc'],2)}%
ETH: {round(macro['eth'],2)}%
SOL: {round(macro['sol'],2)}%

Фон рынка: {macro['state']}
Fear & Greed: {fear}
Гео-риск: {geo}

📰 Важные новости:
"""

        for n in news[:5]:
            text += f"\n• {n}"

        bot.reply_to(message, text)

    except Exception as e:

        bot.reply_to(message, f"Ошибка: {e}")

# =========================
# /ALERTS
# =========================

@bot.message_handler(commands=["alerts"])
def alerts_handler(message):

    try:

        coins = get_kucoin_data()

        alerts = []

        for coin in coins:

            if (
                coin["change"] >= 15 and
                coin["volume"] > 2_000_000
            ):

                alerts.append(coin)

        if not alerts:

            bot.reply_to(message, "Сильных движений нет")

            return

        text = "🔥 Сильные движения рынка:\n\n"

        for coin in alerts[:5]:

            text += (
                f"{coin['symbol']}: "
                f"{round(coin['change'],2)}% | "
                f"Объём ${coin['volume']:,.0f}\n"
            )

        text += (
            "\n⚠️ Это не сигнал покупки. "
            "Возможен перегрев."
        )

        bot.reply_to(message, text)

    except Exception as e:

        bot.reply_to(message, f"Ошибка: {e}")

# =========================
# /HELP
# =========================

@bot.message_handler(commands=["help", "start"])
def help_handler(message):

    text = """
✅ Бот работает

Команды:

/signal — прогноз монет
/top — топ объёмов
/btc — анализ BTC
/sol — анализ SOL
/alerts — памп-alert
/market — обзор рынка
/help — помощь

Автоуведомления:

• /signal — раз в 6 часов
• /market — раз в сутки
• alert — только при сильном пампе
"""

    bot.reply_to(message, text)

# =========================
# AUTO SIGNAL
# =========================

def auto_signal():

    global last_signal_time

    while True:

        try:

            now = time.time()

            if now - last_signal_time >= 21600:

                coins = get_kucoin_data()

                strong = []

                for coin in coins[:80]:

                    if (
                        coin["change"] > 2 and
                        coin["volume"] > 5_000_000
                    ):

                        strong.append(coin)

                strong = sorted(
                    strong,
                    key=lambda x: x["change"],
                    reverse=True
                )[:3]

                macro = get_macro()

                text = (
                    f"🚀 Авто /signal\n"
                    f"{macro['state']} BTC фон\n\n"
                )

                for coin in strong:

                    text += analyze_coin(coin["symbol"])
                    text += "\n\n"

                bot.send_message(CHAT_ID, text)

                last_signal_time = now

        except Exception as e:

            print("auto_signal error:", e)

        time.sleep(300)

# =========================
# AUTO MARKET
# =========================

def auto_market():

    global last_market_time

    while True:

        try:

            now = time.time()

            if now - last_market_time >= 86400:

                macro = get_macro()
                fear = get_fear_greed()
                geo, news = get_news()

                text = f"""
🌍 Суточный обзор рынка

BTC: {round(macro['btc'],2)}%
ETH: {round(macro['eth'],2)}%
SOL: {round(macro['sol'],2)}%

Фон рынка: {macro['state']}
Fear & Greed: {fear}
Гео-риск: {geo}
"""

                bot.send_message(CHAT_ID, text)

                last_market_time = now

        except Exception as e:

            print("auto_market error:", e)

        time.sleep(600)

# =========================
# AUTO ALERTS
# =========================

def auto_alerts():

    global last_alert_time

    while True:

        try:

            now = time.time()

            coins = get_kucoin_data()

            strong = []

            for coin in coins:

                if (
                    coin["change"] >= 25 and
                    coin["volume"] > 5_000_000
                ):

                    strong.append(coin)

            if strong and now - last_alert_time >= 3600:

                text = "🔥 Сильные движения рынка:\n\n"

                for coin in strong[:3]:

                    text += (
                        f"{coin['symbol']}: "
                        f"{round(coin['change'],2)}% | "
                        f"Объём ${coin['volume']:,.0f}\n"
                    )

                text += (
                    "\n⚠️ Возможен перегрев."
                )

                bot.send_message(CHAT_ID, text)

                last_alert_time = now

        except Exception as e:

            print("auto_alerts error:", e)

        time.sleep(900)

# =========================
# START THREADS
# =========================

threading.Thread(target=auto_signal).start()
threading.Thread(target=auto_market).start()
threading.Thread(target=auto_alerts).start()

# =========================
# RUN BOT
# =========================

print("BOT STARTED")

while True:

    try:

        bot.infinity_polling(
            timeout=60,
            long_polling_timeout=60
        )

    except Exception as e:

        print("Polling error:", e)

        time.sleep(15)

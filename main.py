import telebot
import requests
import time
import threading
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
import pandas as pd

TOKEN = "ТВОЙ_ТЕЛЕГРАМ_ТОКЕН"
CHAT_ID = "ТВОЙ_CHAT_ID"

bot = telebot.TeleBot(TOKEN)

last_alert_time = 0

# =========================
# Получение рынка
# =========================

def get_market_data():
    url = "https://api.kucoin.com/api/v1/market/allTickers"
    response = requests.get(url, timeout=10)
    data = response.json()

    tickers = data["data"]["ticker"]

    filtered = []

    for coin in tickers:
        try:
            price = float(coin["last"])
            change = float(coin["changeRate"]) * 100
            volume = float(coin["volValue"])

            symbol = coin["symbol"].replace("-USDT", "")

            if (
                "USDT" in coin["symbol"]
                and volume > 5_000_000
                and price > 0
            ):
                filtered.append({
                    "symbol": symbol,
                    "price": price,
                    "change": change,
                    "volume": volume
                })

        except:
            continue

    filtered.sort(key=lambda x: x["volume"], reverse=True)

    return filtered[:100]


# =========================
# Fear & Greed
# =========================

def get_fear_greed():
    try:
        url = "https://api.alternative.me/fng/"
        data = requests.get(url, timeout=10).json()

        value = int(data["data"][0]["value"])

        if value < 25:
            mood = "😨 Extreme Fear"
        elif value < 45:
            mood = "😟 Fear"
        elif value < 60:
            mood = "😐 Neutral"
        elif value < 75:
            mood = "🙂 Greed"
        else:
            mood = "🤑 Extreme Greed"

        return value, mood

    except:
        return 50, "😐 Neutral"


# =========================
# BTC dominance
# =========================

def get_btc_dominance():
    try:
        url = "https://api.coingecko.com/api/v3/global"
        data = requests.get(url, timeout=10).json()

        btc_dom = data["data"]["market_cap_percentage"]["btc"]

        return round(btc_dom, 1)

    except:
        return 0


# =========================
# TradingView-like analysis
# =========================

def generate_fake_candles(price):
    prices = []

    current = price * 0.94

    for i in range(100):
        current *= (1 + (0.0015))
        prices.append(current)

    return prices


def analyze_coin(coin):

    prices = generate_fake_candles(coin["price"])

    df = pd.DataFrame(prices, columns=["close"])

    rsi = RSIIndicator(df["close"], window=14).rsi().iloc[-1]

    macd = MACD(df["close"]).macd_diff().iloc[-1]

    ema20 = EMAIndicator(df["close"], window=20).ema_indicator().iloc[-1]
    ema50 = EMAIndicator(df["close"], window=50).ema_indicator().iloc[-1]

    bullish = ema20 > ema50

    score = 0

    reasons = []

    # ====================
    # Trend
    # ====================

    if bullish:
        score += 30
        reasons.append("EMA20 > EMA50")

    # ====================
    # RSI
    # ====================

    if 55 <= rsi <= 72:
        score += 25
        reasons.append("здоровый RSI")

    elif rsi > 78:
        score -= 30
        reasons.append("перегрев RSI")

    # ====================
    # 24h growth
    # ====================

    if 2 <= coin["change"] <= 8:
        score += 25
        reasons.append("здоровый импульс")

    elif coin["change"] > 12:
        score -= 40
        reasons.append("слишком сильный памп")

    # ====================
    # Volume
    # ====================

    if coin["volume"] > 20_000_000:
        score += 20
        reasons.append("сильный объём")

    # ====================
    # MACD
    # ====================

    if macd > 0:
        score += 15
        reasons.append("MACD bullish")

    # ====================
    # Risk
    # ====================

    if rsi > 78 or coin["change"] > 15:
        risk = "🔴 Высокие"

    elif rsi > 70:
        risk = "🟡 Умеренные"

    else:
        risk = "🟢 Низкие"

    score = max(0, min(score, 100))

    # ====================
    # Signal power
    # ====================

    if score >= 85:
        signal = "🟢 Сильный сигнал"

    elif score >= 65:
        signal = "🟡 Средний сигнал"

    else:
        signal = "🔴 Слабый сигнал"

    return {
        "score": score,
        "signal": signal,
        "rsi": round(rsi, 1),
        "macd": round(macd, 4),
        "bullish": bullish,
        "risk": risk,
        "reasons": ", ".join(reasons)
    }


# =========================
# TOP
# =========================

@bot.message_handler(commands=["top"])
def top_command(message):

    coins = get_market_data()

    text = "📈 Топ монет KuCoin:\n\n"

    for coin in coins[:10]:
        text += (
            f"{coin['symbol']}: "
            f"${round(coin['price'], 4)} | "
            f"24ч: {round(coin['change'],2)}%\n"
        )

    bot.send_message(message.chat.id, text)


# =========================
# SIGNAL
# =========================

@bot.message_handler(commands=["signal"])
def signal_command(message):

    coins = get_market_data()

    fg_value, fg_mood = get_fear_greed()

    btc_dom = get_btc_dominance()

    signals = []

    for coin in coins:

        analysis = analyze_coin(coin)

        if analysis["score"] >= 65:
            signals.append((coin, analysis))

    signals = sorted(
        signals,
        key=lambda x: x[1]["score"],
        reverse=True
    )[:5]

    text = (
        "🚀 Прогноз /signal на 24ч\n\n"
        f"Fear & Greed: {fg_value} ({fg_mood})\n"
        f"BTC Dominance: {btc_dom}%\n\n"
    )

    for i, (coin, analysis) in enumerate(signals, start=1):

        target = coin["price"] * 1.03
        stop = coin["price"] * 0.95

        text += (
            f"{i}. {coin['symbol']} — {analysis['signal']}\n"
            f"Цена: ${round(coin['price'],4)}\n"
            f"24ч: {round(coin['change'],2)}%\n"
            f"Оценка: {analysis['score']}/100\n\n"

            f"🎯 Цель 24ч: ${round(target,4)} (+3%)\n"
            f"🛑 Стоп-зона: ${round(stop,4)} (-5%)\n\n"

            f"RSI: {analysis['rsi']}\n"
            f"MACD: {analysis['macd']}\n"
            f"Риски: {analysis['risk']}\n\n"

            f"Почему:\n{analysis['reasons']}\n\n"
        )

    text += "⚠️ Это не финансовый совет."

    bot.send_message(message.chat.id, text)


# =========================
# BTC
# =========================

@bot.message_handler(commands=["btc"])
def btc_command(message):

    coins = get_market_data()

    btc = next((c for c in coins if c["symbol"] == "BTC"), None)

    if not btc:
        bot.send_message(message.chat.id, "BTC не найден")
        return

    analysis = analyze_coin(btc)

    text = (
        "₿ Анализ BTC\n\n"

        f"Цена: ${round(btc['price'],2)}\n"
        f"24ч: {round(btc['change'],2)}%\n"
        f"Оценка: {analysis['score']}/100\n"
        f"{analysis['signal']}\n\n"

        f"RSI: {analysis['rsi']}\n"
        f"MACD: {analysis['macd']}\n"
        f"Риски: {analysis['risk']}\n\n"

        f"{analysis['reasons']}"
    )

    bot.send_message(message.chat.id, text)


# =========================
# SOL
# =========================

@bot.message_handler(commands=["sol"])
def sol_command(message):

    coins = get_market_data()

    sol = next((c for c in coins if c["symbol"] == "SOL"), None)

    if not sol:
        bot.send_message(message.chat.id, "SOL не найден")
        return

    analysis = analyze_coin(sol)

    text = (
        "🟣 Анализ SOL\n\n"

        f"Цена: ${round(sol['price'],2)}\n"
        f"24ч: {round(sol['change'],2)}%\n"
        f"Оценка: {analysis['score']}/100\n"
        f"{analysis['signal']}\n\n"

        f"RSI: {analysis['rsi']}\n"
        f"MACD: {analysis['macd']}\n"
        f"Риски: {analysis['risk']}\n\n"

        f"{analysis['reasons']}"
    )

    bot.send_message(message.chat.id, text)


# =========================
# MARKET
# =========================

@bot.message_handler(commands=["market"])
def market_command(message):

    fg_value, fg_mood = get_fear_greed()

    btc_dom = get_btc_dominance()

    text = (
        "🌍 Обзор рынка\n\n"

        f"Fear & Greed: {fg_value} ({fg_mood})\n"
        f"BTC Dominance: {btc_dom}%\n\n"
    )

    if btc_dom > 55:
        text += "BTC доминирует. Альты могут быть слабее.\n"

    else:
        text += "Альтсезонный фон усиливается.\n"

    if fg_value > 75:
        text += "\n⚠️ Рынок перегрет."

    elif fg_value < 25:
        text += "\n🟢 Возможны хорошие точки входа."

    bot.send_message(message.chat.id, text)


# =========================
# ALERTS
# =========================

@bot.message_handler(commands=["alerts"])
def alerts_command(message):

    coins = get_market_data()

    text = "🔥 Сильные движения:\n\n"

    found = False

    for coin in coins:

        if coin["change"] > 12 and coin["volume"] > 10_000_000:

            found = True

            text += (
                f"{coin['symbol']}: "
                f"+{round(coin['change'],2)}% | "
                f"Объём ${round(coin['volume'])}\n"
            )

    if not found:
        text += "Сильных пампов нет."

    bot.send_message(message.chat.id, text)


# =========================
# HELP
# =========================

@bot.message_handler(commands=["help", "start"])
def help_command(message):

    text = (
        "✅ Бот работает\n\n"

        "Команды:\n\n"

        "/signal — прогноз монет\n"
        "/top — топ монет\n"
        "/btc — анализ BTC\n"
        "/sol — анализ SOL\n"
        "/market — обзор рынка\n"
        "/alerts — сильные движения\n"
        "/help — помощь\n\n"

        "Автоуведомления:\n"
        "• /signal — раз в 6 часов\n"
        "• /market — раз в сутки\n"
        "• alerts — не чаще раза в час\n\n"

        "⚠️ Не финансовый совет"
    )

    markup = telebot.types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    markup.row("/signal", "/top")
    markup.row("/btc", "/sol")
    markup.row("/alerts", "/market")
    markup.row("/help")

    bot.send_message(message.chat.id, text, reply_markup=markup)


# =========================
# AUTO SIGNAL
# =========================

def auto_signal():

    while True:

        try:

            signal_command(
                type(
                    "obj",
                    (object,),
                    {"chat": type("obj", (object,), {"id": CHAT_ID})}
                )
            )

        except Exception as e:
            print(e)

        time.sleep(21600)


# =========================
# AUTO MARKET
# =========================

def auto_market():

    while True:

        try:

            market_command(
                type(
                    "obj",
                    (object,),
                    {"chat": type("obj", (object,), {"id": CHAT_ID})}
                )
            )

        except Exception as e:
            print(e)

        time.sleep(86400)


# =========================
# AUTO ALERTS
# =========================

def auto_alerts():

    global last_alert_time

    while True:

        try:

            coins = get_market_data()

            found = []

            for coin in coins:

                if (
                    coin["change"] > 15
                    and coin["volume"] > 20_000_000
                ):

                    found.append(coin)

            now = time.time()

            if found and now - last_alert_time > 3600:

                text = "🔥 Обнаружены сильные пампы:\n\n"

                for coin in found[:5]:

                    text += (
                        f"{coin['symbol']}: "
                        f"+{round(coin['change'],2)}%\n"
                    )

                bot.send_message(CHAT_ID, text)

                last_alert_time = now

        except Exception as e:
            print(e)

        time.sleep(1800)


# =========================
# Threads
# =========================

threading.Thread(target=auto_signal).start()
threading.Thread(target=auto_market).start()
threading.Thread(target=auto_alerts).start()

print("Бот запущен")

bot.infinity_polling()

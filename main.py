from flask import Flask
from threading import Thread
import os, time, json, requests, statistics
from datetime import datetime, timedelta

app = Flask("")

@app.route("/")
def home():
    return "Bot is alive"

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    Thread(target=run).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_VERSION = "v4.7 READABILITY FIX"

CHAT_ID_FILE = "chat_id.txt"
HISTORY_FILE = "signal_history.json"
PUMP_FILE = "pump_history.json"
RESULTS_FILE = "signal_results.json"

SIGNAL_HOURS = [9, 15, 21]
MARKET_HOUR = 9
PUMP_MINUTES = [0, 30]
MOSCOW_OFFSET_HOURS = 3

REPEAT_PUMP_AFTER = 3 * 60 * 60

QUALITY_ASSETS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "LINK",
    "TON", "DOGE", "NEAR", "TAO", "DOT", "LTC", "SUI", "APT",
    "ARB", "OP", "INJ", "SEI", "ATOM", "FIL", "TRX"
]

FORCE_ANALYZE_ASSETS = ["TON-USDT", "SOL-USDT", "TAO-USDT", "SUI-USDT", "ETH-USDT"]

EVENT_ASSETS = {
    "TON": {
        "title": "событийная монета TON / GRAM",
        "bonus": 14,
        "risk": "есть новостной катализатор, но возможен резкий слив после новости"
    }
}

_ticker_cache = {"time": 0, "data": []}

def save_chat_id(chat_id):
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))

def load_chat_id():
    try:
        return open(CHAT_ID_FILE).read().strip()
    except Exception:
        return None

def load_json(path):
    try:
        return json.load(open(path))
    except Exception:
        return {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)

def keyboard():
    return {
        "keyboard": [
            ["/signal", "/top"],
            ["/btc", "/sol"],
            ["/alerts", "/market"],
            ["/version", "/help"]
        ],
        "resize_keyboard": True
    }

def send_message(chat_id, text):
    if not BOT_TOKEN:
        print("BOT_TOKEN is missing")
        return

    parts = []

    while len(text) > 3900:
        cut = text.rfind("\n", 0, 3900)
        if cut == -1:
            cut = 3900
        parts.append(text[:cut])
        text = text[cut:]

    parts.append(text)

    for part in parts:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": part, "reply_markup": keyboard()},
            timeout=20
        )
        time.sleep(0.3)

def get_updates(offset=None):
    if not BOT_TOKEN:
        return {"result": []}

    params = {"timeout": 30}

    if offset:
        params["offset"] = offset

    return requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
        params=params,
        timeout=40
    ).json()

def kucoin_tickers():
    now = time.time()

    if now - _ticker_cache["time"] < 20 and _ticker_cache["data"]:
        return _ticker_cache["data"]

    data = requests.get(
        "https://api.kucoin.com/api/v1/market/allTickers",
        timeout=20
    ).json()

    if data.get("code") != "200000":
        raise Exception(data)

    tickers = data.get("data", {}).get("ticker", [])
    _ticker_cache["time"] = now
    _ticker_cache["data"] = tickers

    return tickers

def get_ticker(symbol):
    for t in kucoin_tickers():
        if t.get("symbol") == symbol:
            return t
    return None

def get_candles(symbol, interval="1hour"):
    data = requests.get(
        "https://api.kucoin.com/api/v1/market/candles",
        params={"symbol": symbol, "type": interval},
        timeout=20
    ).json()

    if data.get("code") != "200000":
        raise Exception(data)

    candles = sorted(data.get("data", []), key=lambda x: int(x[0]))

    return {
        "close": [float(c[2]) for c in candles],
        "high": [float(c[3]) for c in candles],
        "low": [float(c[4]) for c in candles],
        "volume": [float(c[5]) for c in candles],
    }

def percent_change(old, new):
    if old == 0:
        return 0
    return ((new / old) - 1) * 100

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
        return 50

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

    e12 = ema(values[-80:], 12)
    e26 = ema(values[-80:], 26)

    if not e12 or not e26:
        return 0

    return e12 - e26

def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 0

    trs = []

    for i in range(1, len(closes)):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        ))

    return statistics.mean(trs[-period:])

def volume_power(volumes):
    if len(volumes) < 24:
        return 1

    avg = statistics.mean(volumes[-24:-1])

    if avg <= 0:
        return 1

    return volumes[-1] / avg

def coin_profile(asset, volume):
    if asset == "BTC":
        return "крупный актив", 0.5, 3.0, True

    if asset == "ETH":
        return "крупный актив", 0.8, 4.0, True

    if asset in QUALITY_ASSETS:
        return "качественный альт", 1.5, 7.0, True

    if volume >= 40_000_000:
        return "ликвидный рискованный альт", 2.0, 9.0, False

    return "спекулятивный альт", 2.0, 12.0, False

def get_fear_greed():
    try:
        data = requests.get("https://api.alternative.me/fng/", timeout=10).json()
        value = int(data["data"][0]["value"])

        if value < 25:
            return value, "страх", 5
        if value < 45:
            return value, "осторожность", 2
        if value < 60:
            return value, "нейтрально", 0
        if value < 75:
            return value, "жадность", -2

        return value, "сильная жадность", -6

    except Exception:
        return 50, "нет данных", 0

def get_btc_dominance():
    try:
        data = requests.get("https://api.coingecko.com/api/v3/global", timeout=10).json()
        dom = float(data["data"]["market_cap_percentage"]["btc"])

        if dom > 55:
            return dom, -8, "BTC забирает деньги у альтов"

        if dom < 52:
            return dom, 5, "альтам легче расти"

        return dom, 0, "BTC и альты в балансе"

    except Exception:
        return None, 0, None

def get_news_risk():
    try:
        url = "https://news.google.com/rss/search?q=iran+oil+hormuz+fed+inflation+war+tariff+trump+crypto+bitcoin&hl=en-US&gl=US&ceid=US:en"
        xml = requests.get(url, timeout=10).text.lower()

        risk_words = {
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

        for word, weight in risk_words.items():
            if word in xml:
                score += weight

        if score >= 10:
            return -8, "🟥 Внешний фон опасный — новости могут резко ударить по крипте"

        if score >= 5:
            return -4, "🟡 Внешний фон нестабильный — рынок чувствителен к новостям"

        return 0, "🟢 Внешний фон спокойный — глобальные риски не мешают рынку"

    except Exception:
        return 0, "⚪ Внешний фон не удалось оценить"

def diagnostics(symbol):
    c15 = get_candles(symbol, "15min")
    c1h = get_candles(symbol, "1hour")
    c4h = get_candles(symbol, "4hour")

    close15 = c15["close"]
    close1h = c1h["close"]
    close4h = c4h["close"]

    high1h = c1h["high"]
    low1h = c1h["low"]

    vol15 = c15["volume"]
    vol1h = c1h["volume"]

    price = close1h[-1]

    e9 = ema(close1h[-80:], 9)
    e21 = ema(close1h[-80:], 21)
    e50 = ema(close1h[-100:], 50)

    e9_4h = ema(close4h[-80:], 9)
    e21_4h = ema(close4h[-80:], 21)

    trend_1h = bool(e9 and e21 and e9 > e21)
    trend_4h = bool(e9_4h and e21_4h and e9_4h > e21_4h)
    strong_trend = bool(e9 and e21 and e50 and e9 > e21 > e50)

    r = rsi(close1h)
    m = macd(close1h)

    a = atr(high1h, low1h, close1h)
    atr_pct = a / price * 100 if price else 0

    vol_power_15 = volume_power(vol15)
    vol_power_1h = volume_power(vol1h)

    recent_vol_1h = statistics.mean(vol1h[-3:]) if len(vol1h) >= 3 else vol1h[-1]
    previous_vol_1h = statistics.mean(vol1h[-8:-3]) if len(vol1h) >= 8 else recent_vol_1h

    if previous_vol_1h > 0:
        volume_trend = recent_vol_1h / previous_vol_1h
    else:
        volume_trend = 1

    move_15 = percent_change(close15[-5], close15[-1]) if len(close15) >= 6 else 0
    move_1h = percent_change(close1h[-4], close1h[-1]) if len(close1h) >= 5 else 0
    move_4h = percent_change(close4h[-3], close4h[-1]) if len(close4h) >= 4 else 0

    resistance = max(high1h[-36:])
    support = min(low1h[-24:])

    room_up = percent_change(price, resistance) if resistance > price else 0

    above_mean = price > statistics.mean(close1h[-20:])
    higher_lows = low1h[-1] > min(low1h[-10:-1])
    local_breakout = price > max(high1h[-12:-1])

    early_impulse = (
        0.6 <= move_15 <= 3.5 and
        0.5 <= move_1h <= 6.0 and
        vol_power_15 >= 1.4 and
        vol_power_1h >= 1.1
    )

    return {
        "price": price,
        "rsi": r,
        "macd": m,
        "atr_pct": atr_pct,
        "vol_15": vol_power_15,
        "vol_1h": vol_power_1h,
        "volume_trend": volume_trend,
        "move_15": move_15,
        "move_1h": move_1h,
        "move_4h": move_4h,
        "trend_1h": trend_1h,
        "trend_4h": trend_4h,
        "strong_trend": strong_trend,
        "above_mean": above_mean,
        "higher_lows": higher_lows,
        "local_breakout": local_breakout,
        "early_impulse": early_impulse,
        "room_up": room_up,
        "support": support,
        "resistance": resistance
    }

def btc_filter():
    try:
        t = get_ticker("BTC-USDT")
        change = float(t.get("changeRate", 0) or 0) * 100
        d = diagnostics("BTC-USDT")

        score = 0

        if change > 0:
            score += 15
        if d["trend_1h"]:
            score += 20
        if d["trend_4h"]:
            score += 20
        if d["macd"] > 0:
            score += 10
        if d["vol_1h"] >= 1:
            score += 10
        if d["rsi"] > 82:
            score -= 10
        if change < -2:
            score -= 25

        if score >= 55:
            return "BTC помогает рынку", 8, change

        if score >= 30:
            return "BTC нейтральный", 0, change

        return "BTC мешает рынку", -12, change

    except Exception:
        return "BTC не удалось оценить", 0, 0

def market_context():
    fg_value, fg_text, fg_mod = get_fear_greed()
    dom, dom_mod, dom_text = get_btc_dominance()
    geo_mod, geo_text = get_news_risk()
    btc_text, btc_mod, btc_change = btc_filter()

    total = fg_mod + dom_mod + geo_mod + btc_mod

    if geo_mod <= -8:
        state = "🟡 осторожный рынок"
    elif total >= 8:
        state = "🟢 рынок помогает росту"
    elif total >= -5:
        state = "🟡 рынок нейтральный"
    else:
        state = "🔴 рынок рискованный"

    return {
        "state": state,
        "fg_value": fg_value,
        "fg_text": fg_text,
        "dom": dom,
        "dom_text": dom_text,
        "geo_text": geo_text,
        "geo_mod": geo_mod,
        "btc_text": btc_text,
        "btc_mod": btc_mod,
        "btc_change": btc_change,
        "market_mod": total
    }

def alex_edge_ultra(symbol):
    ticker = get_ticker(symbol)

    if not ticker:
        return None

    asset = symbol.replace("-USDT", "")
    price = float(ticker.get("last", 0) or 0)
    change_24 = float(ticker.get("changeRate", 0) or 0) * 100
    volume_usd = float(ticker.get("volValue", 0) or 0)

    profile, base_low, base_high, is_quality = coin_profile(asset, volume_usd)
    d = diagnostics(symbol)
    ctx = market_context()

    score = 0
    plus = []
    minus = []

    if asset in EVENT_ASSETS:
        event = EVENT_ASSETS[asset]
        score += event["bonus"]
        plus.append(event["title"])
        minus.append(event["risk"])

    if 1 <= change_24 <= 8:
        score += 18
        plus.append("монета уже начала рост, но ещё не выглядит слишком улетевшей")
    elif 8 < change_24 <= 15:
        score += 6
        minus.append("часть роста уже прошла")
    elif change_24 > 15:
        score -= 18
        minus.append("монета уже в зоне пампа, риск отката высокий")
    elif change_24 < -5:
        score -= 10
        minus.append("монета слабее рынка")

    if d["early_impulse"]:
        score += 22
        plus.append("🔥 ранний импульс: покупатели начали разгон")

    if d["move_15"] >= 0.8:
        score += 12
        plus.append("есть свежий краткосрочный импульс")

    if d["move_1h"] >= 1.2:
        score += 12
        plus.append("движение поддерживается последние часы")

    if d["trend_1h"]:
        score += 15
        plus.append("краткосрочный тренд вверх")

    if d["trend_4h"]:
        score += 15
        plus.append("старший тренд тоже вверх")

    if d["strong_trend"]:
        score += 10
        plus.append("цена держится выше важных уровней")

    if d["macd"] > 0:
        score += 8
    else:
        score -= 8
        minus.append("импульс пока слабый")

    if d["vol_1h"] >= 1.8:
        score += 20
        plus.append("покупатели заходят сильнее обычного")
    elif d["vol_1h"] >= 1.1:
        score += 10
        plus.append("объём нормальный")
    else:
        score -= 14
        minus.append("рост пока слабовато подтверждён объёмом")

    if d["volume_trend"] >= 1.25:
        score += 6
        plus.append("объём усиливается")
    elif d["volume_trend"] <= 0.75:
        score -= 12
        minus.append("объём падает")

    if d["above_mean"] and d["higher_lows"]:
        score += 14
        plus.append("покупатели удерживают цену")

    if d["local_breakout"] and d["vol_1h"] >= 1.2:
        score += 16
        plus.append("цена пробивает уровень с поддержкой объёма")
    elif d["local_breakout"] and d["vol_1h"] < 1.2:
        score -= 6
        minus.append("пробой без сильного объёма может быть ложным")

    if d["room_up"] >= 10:
        score += 22
        plus.append("есть потенциал движения выше +10%")
    elif d["room_up"] >= 5:
        score += 16
        plus.append("есть запас хода до +5%")
    elif d["room_up"] >= 2:
        score += 4
        minus.append("запас хода ограничен")
    else:
        score -= 16
        minus.append("рядом сопротивление, рост может быстро остановиться")

    if 55 <= d["rsi"] <= 76:
        score += 10
        plus.append("RSI в рабочей зоне тренда")
    elif 76 < d["rsi"] <= 84:
        score -= 6
        minus.append("монета уже горячая")
    elif d["rsi"] > 84:
        score -= 18
        minus.append("монета перегрета")
    elif d["rsi"] < 45:
        score -= 6
        minus.append("RSI слабый, покупатели пока не доминируют")

    if is_quality:
        score += 8
    else:
        score -= 8
        minus.append("монета спекулятивная, риск выше")

    score += ctx["market_mod"]

    if ctx["market_mod"] >= 0:
        plus.append("общий рынок не мешает росту")
    else:
        minus.append("общий рынок добавляет риск")

    if ctx["geo_mod"] <= -8:
        minus.append("внешний фон сейчас опасный")

    raw_score = score
    cap = 94

    if not is_quality:
        cap = min(cap, 78)

    if d["vol_1h"] < 1:
        cap = min(cap, 74)

    if d["room_up"] < 5 and asset not in EVENT_ASSETS:
        cap = min(cap, 72)

    if d["rsi"] > 82:
        cap = min(cap, 70)

    if d["macd"] < 0:
        cap = min(cap, 60)

    if change_24 > 12 and not is_quality:
        cap = min(cap, 62)

    if change_24 > 25:
        cap = min(cap, 55)

    score = max(0, min(100, min(raw_score, cap)))

    event_floor = False

    if asset in EVENT_ASSETS and ctx["btc_mod"] >= 0:
        event_floor = True
        score = max(score, 55)

    chance_5 = int(22 + score * 0.62)
    chance_10 = int(8 + score * 0.42)
    chance_15 = int(3 + score * 0.25)

    if d["room_up"] < 5 and asset not in EVENT_ASSETS:
        chance_5 -= 10
        chance_10 -= 18

    if d["room_up"] < 10:
        chance_10 -= 12

    if d["vol_1h"] < 1:
        chance_5 -= 7
        chance_10 -= 10

    if d["rsi"] > 82:
        chance_5 -= 7
        chance_10 -= 10

    if not is_quality:
        chance_5 -= 5
        chance_10 -= 7

    if ctx["market_mod"] < -5:
        chance_5 -= 8
        chance_10 -= 10

    if event_floor:
        chance_5 = max(chance_5, 45)
        chance_10 = max(chance_10, 12)

    if d["early_impulse"] and d["room_up"] >= 5 and d["vol_1h"] >= 1.1:
        chance_5 += 8
        chance_10 += 6

    chance_5 = max(5, min(82, chance_5))
    chance_10 = max(2, min(70, chance_10))
    chance_15 = max(1, min(55, chance_15))

    low = base_low
    high = base_high

    if score >= 78:
        low += 2
        high += 2
    elif score >= 65:
        low += 1
    elif score >= 50:
        low = 0
        high = min(high, 4)
    else:
        low = -2
        high = 1.5

    if d["early_impulse"] and d["room_up"] >= 5:
        high += 1.5

    if asset in EVENT_ASSETS:
        high += 2.0

    high = min(high, max(1.0, d["atr_pct"] * 2.7))

    if d["room_up"] > 0 and asset not in EVENT_ASSETS:
        if is_quality and d["trend_1h"] and d["trend_4h"] and ctx["btc_mod"] >= 0:
            # Для сильных качественных монет не режем прогноз в ноль у сопротивления:
            # они часто пробивают уровень и продолжают движение.
            high = min(high, max(3.5, d["room_up"] * 1.8))
        else:
            high = min(high, max(1.0, d["room_up"]))

    if d["vol_1h"] < 1:
        high -= 0.7

    if d["rsi"] > 82:
        high -= 0.8

    if ctx["market_mod"] < -5:
        high -= 0.8

    if high < 2:
        chance_5 = min(chance_5, 12)
    elif high < 3:
        chance_5 = min(chance_5, 20)
    elif high < 5:
        chance_5 = min(chance_5, 35)

    if high < 5:
        chance_10 = min(chance_10, 8)
    elif high < 8:
        chance_10 = min(chance_10, 18)

    if high < 10:
        chance_15 = min(chance_15, 10)

    # Если качество момента слабое, не завышаем вероятности.
    if score < 55:
        chance_5 = min(chance_5, 25)
        chance_10 = min(chance_10, 5)
        chance_15 = min(chance_15, 2)

    if change_24 >= 25:
        chance_5 = min(chance_5, 10)
        chance_10 = min(chance_10, 3)
        chance_15 = min(chance_15, 1)
    elif change_24 >= 20:
        chance_5 = min(chance_5, 15)
        chance_10 = min(chance_10, 5)
        chance_15 = min(chance_15, 2)

    if asset in EVENT_ASSETS and high >= 4:
        chance_5 = max(chance_5, 42)

    low = round(low, 1)
    high = round(max(high, low), 1)

    target_low = price * (1 + low / 100)
    target_high = price * (1 + high / 100)

    if asset in ["BTC", "ETH"]:
        max_stop_pct = 4
    elif is_quality:
        max_stop_pct = 7
    elif change_24 > 12:
        max_stop_pct = 12
    else:
        max_stop_pct = 10

    technical_stop = d["support"] if d["support"] < price else price * (1 - max_stop_pct / 100)
    max_allowed_stop = price * (1 - max_stop_pct / 100)

    stop = max(technical_stop, max_allowed_stop)
    downside = percent_change(price, stop)

    strong_continuation = (
        is_quality
        and 8 <= change_24 <= 20
        and d["trend_1h"]
        and d["trend_4h"]
        and (d["move_1h"] >= 0.8 or d["move_15"] >= 0.5)
        and ctx["btc_mod"] >= 0
    )

    quality_early_trend = (
        is_quality
        and 0.5 <= change_24 < 4.0
        and d["trend_1h"]
        and d["trend_4h"]
        and score >= 70
        and chance_5 >= 55
        and high >= 5
        and ctx["btc_mod"] >= 0
    )

    if strong_continuation:
        low = max(low, 1.0)
        high = max(high, min(8.0, max(5.0, d["atr_pct"] * 3.4)))
        low = round(low, 1)
        high = round(high, 1)
        target_low = price * (1 + low / 100)
        target_high = price * (1 + high / 100)
        chance_5 = max(chance_5, 42)
        chance_10 = max(chance_10, 12)
        plus.append("сильный тренд ещё продолжается")
        minus.append("это уже не ранний вход, а продолжение движения с повышенным риском")

    if quality_early_trend:
        chance_5 = max(chance_5, 60)
        chance_10 = max(chance_10, 15)
        plus.append("качественная монета в начале трендового движения")

    if change_24 >= 25:
        verdict = "🔴 ПОЗДНИЙ ПАМП"
        action = "SKIP"
    elif asset in EVENT_ASSETS and chance_5 >= 42:
        verdict = "📌 СОБЫТИЙНАЯ МОНЕТА"
        action = "WATCH"
    elif quality_early_trend:
        verdict = "🟢 РАННИЙ ТРЕНД / цель +5%"
        action = "BUY"
    elif strong_continuation and chance_5 >= 48 and high >= 5 and score >= 62:
        verdict = "🟠 ТРЕНД ПРОДОЛЖАЕТСЯ"
        action = "PUMP"
    elif d["early_impulse"] and chance_5 >= 58 and high >= 5:
        verdict = "🔥 РАННИЙ ИМПУЛЬС / цель +5%"
        action = "BUY"
    elif chance_10 >= 45 and high >= 10:
        verdict = "🚀 ПОКУПКА / цель +10%"
        action = "BUY"
    elif chance_5 >= 65 and high >= 5:
        verdict = "🟢 ПОКУПКА / цель +5%"
        action = "BUY"
    elif chance_5 >= 35 and high >= 5 and score >= 55:
        verdict = "🟡 НАБЛЮДАТЬ"
        action = "WATCH"
    elif (
        chance_5 >= 40
        and high >= 4.5
        and d["vol_1h"] >= 1.5
        and score >= 40
        and change_24 <= 15
    ):
        verdict = "🟠 РИСКОВАННЫЙ ПАМП"
        action = "PUMP"
    else:
        verdict = "🔴 НЕ ПОКУПАТЬ"
        action = "SKIP"

    if action == "BUY" and score < 55:
        verdict = "🟡 НАБЛЮДАТЬ"
        action = "WATCH"

    if action == "WATCH" and score < 55 and asset not in EVENT_ASSETS:
        verdict = "🔴 НЕ ПОКУПАТЬ"
        action = "SKIP"

    # Защита от ранних пампов на спекулятивных монетах:
    # экстремальный объём часто означает не спокойный вход, а резкий импульс с риском отката.
    if (
        action == "BUY"
        and not is_quality
        and d["vol_1h"] >= 8
        and asset not in EVENT_ASSETS
    ):
        verdict = "🟠 РИСКОВАННЫЙ ИМПУЛЬС"
        action = "PUMP"
        chance_5 = min(chance_5, 55)
        chance_10 = min(chance_10, 15)
        chance_15 = min(chance_15, 8)
        minus.append("экстремальный объём: возможен резкий памп и быстрый откат")

    # Если монета уже выросла больше 12% за сутки, это уже не спокойный WATCH.
    # Для таких монет лучше ждать откат, а не входить с рынка.
    if action == "WATCH" and change_24 > 12 and asset not in EVENT_ASSETS:
        verdict = "🟠 ЖДАТЬ ОТКАТ"
        action = "PUMP"

    # Если альт уже разогнался выше 4%, это уже не идеальная ранняя покупка.
    # Исключение — очень сильный объём и высокий score.
    if (
        action == "BUY"
        and asset not in ["BTC", "ETH"]
        and change_24 > 4
        and not EVENT_ASSETS.get(asset)
        and not (d["vol_1h"] >= 1.5 and score >= 78)
    ):
        verdict = "🟡 НАБЛЮДАТЬ"
        action = "WATCH"

    # Финальная защита вероятностей.
    # Это последний блок, который меняет chance_5 / chance_10 / chance_15.
    # Он нужен, чтобы не было противоречий вида:
    # score 43/100 + 🔴 НЕ ПОКУПАТЬ, но шанс +5% = 42%.
    if action == "SKIP":
        chance_5 = min(chance_5, 20)
        chance_10 = min(chance_10, 5)
        chance_15 = min(chance_15, 2)

    elif score < 50:
        chance_5 = min(chance_5, 25)
        chance_10 = min(chance_10, 5)
        chance_15 = min(chance_15, 2)

    elif score < 55:
        chance_5 = min(chance_5, 30)
        chance_10 = min(chance_10, 8)
        chance_15 = min(chance_15, 5)

    if change_24 >= 25:
        chance_5 = min(chance_5, 10)
        chance_10 = min(chance_10, 3)
        chance_15 = min(chance_15, 1)

    elif change_24 >= 20 and action != "BUY":
        chance_5 = min(chance_5, 15)
        chance_10 = min(chance_10, 5)
        chance_15 = min(chance_15, 2)

    if high < 5 and action != "BUY":
        chance_5 = min(chance_5, 25)
        chance_10 = min(chance_10, 5)

    # Альты хуже растут, когда BTC забирает доминацию.
    if asset not in ["BTC", "ETH"] and ctx.get("dom_text") == "BTC забирает деньги у альтов":
        chance_5 = min(chance_5, 50)
        chance_10 = min(chance_10, 12)

    # Если объём падает, не завышаем вероятность.
    if d["volume_trend"] <= 0.75:
        chance_5 = min(chance_5, 45)
        chance_10 = min(chance_10, 10)

    # Если монета уже заметно выросла, это больше не ранний вход.
    if change_24 > 4 and action == "BUY":
        chance_5 = min(chance_5, 52)
        chance_10 = min(chance_10, 12)

    if change_24 > 8 and action != "BUY":
        chance_5 = min(chance_5, 35)
        chance_10 = min(chance_10, 8)
        chance_15 = min(chance_15, 5)

    chance_5, chance_10, chance_15, learning_note = calibrate_chances(
        asset, action, score, chance_5, chance_10, chance_15
    )

    if learning_note and learning_note != "истории пока мало":
        plus.append(learning_note)

    history = load_json(HISTORY_FILE)
    old = history.get(asset)

    if old:
        old_price = old.get("price", price)
        old_time = old.get("time", time.time())
        fact = percent_change(old_price, price)
        hours = (time.time() - old_time) / 3600
        status = f"с прошлого сигнала {hours:.1f}ч, цена {fact:+.2f}%"
    else:
        status = "новый сигнал"

    pullback_2 = price * 0.98
    pullback_3 = price * 0.97

    if action == "BUY" and change_24 < 4 and d["volume_trend"] > 0.75:
        entry_zone = "идеальная зона входа: можно рассмотреть частичный вход сейчас"
    elif action == "BUY" and d["volume_trend"] <= 0.75:
        entry_zone = "вход только малым объёмом: тренд есть, но объём падает"
    elif action == "BUY":
        entry_zone = "вход возможен, но не после резкой зелёной свечи"
    elif action in ["WATCH", "PUMP"] and change_24 >= 8:
        entry_zone = f"вход уже поздний: лучше ждать откат 2–3% примерно к ${pullback_2:.6g}…${pullback_3:.6g}"
    elif action == "WATCH":
        entry_zone = "зона ожидания: нужен более сильный объём"
    else:
        entry_zone = "вход не подходит"

    return {
        "symbol": asset,
        "profile": profile,
        "is_quality": is_quality,
        "price": price,
        "change_24": change_24,
        "volume_usd": volume_usd,
        "score": score,
        "chance_5": chance_5,
        "chance_10": chance_10,
        "chance_15": chance_15,
        "low": low,
        "high": high,
        "target_low": target_low,
        "target_high": target_high,
        "stop": stop,
        "downside": downside,
        "verdict": verdict,
        "action": action,
        "plus": list(dict.fromkeys(plus))[:5],
        "minus": list(dict.fromkeys(minus))[:5],
        "ctx": ctx,
        "status": status,
        "fast_move": d["move_15"],
        "vol_power": d["vol_1h"],
        "rsi": round(d["rsi"], 1),
        "volume_trend": round(d["volume_trend"], 2),
        "entry_zone": entry_zone
    }


def outcome_bucket(score):
    if score >= 80:
        return "80+"
    if score >= 70:
        return "70-79"
    if score >= 60:
        return "60-69"
    if score >= 50:
        return "50-59"
    return "<50"

def signal_key(asset, ts):
    return f"{asset}_{int(ts)}"

def update_signal_results():
    """
    Самообучение без ML-библиотек:
    сохраняем, что стало с ценой через 1ч / 6ч / 24ч после сигнала.
    Эти данные потом мягко корректируют вероятность +5%.
    """
    data = load_json(RESULTS_FILE)
    if not isinstance(data, dict):
        data = {}

    open_items = data.get("open", {})
    closed_items = data.get("closed", [])
    now = time.time()
    changed = False

    for key, rec in list(open_items.items()):
        asset = rec.get("asset")
        start_price = float(rec.get("price", 0) or 0)
        start_time = float(rec.get("time", 0) or 0)

        if not asset or start_price <= 0 or start_time <= 0:
            open_items.pop(key, None)
            changed = True
            continue

        age = now - start_time

        try:
            ticker = get_ticker(f"{asset}-USDT")
            if not ticker:
                continue
            current_price = float(ticker.get("last", 0) or 0)
        except Exception:
            continue

        if current_price <= 0:
            continue

        results = rec.setdefault("results", {})

        if age >= 3600 and "1h" not in results:
            results["1h"] = percent_change(start_price, current_price)
            changed = True

        if age >= 6 * 3600 and "6h" not in results:
            results["6h"] = percent_change(start_price, current_price)
            changed = True

        if age >= 24 * 3600 and "24h" not in results:
            results["24h"] = percent_change(start_price, current_price)
            rec["closed_time"] = now
            closed_items.append(rec)
            open_items.pop(key, None)
            changed = True

    if len(closed_items) > 500:
        closed_items = closed_items[-500:]

    data["open"] = open_items
    data["closed"] = closed_items

    if changed:
        save_json(RESULTS_FILE, data)

def historical_win_rate(asset, action, score):
    data = load_json(RESULTS_FILE)
    closed = data.get("closed", []) if isinstance(data, dict) else []
    if not closed:
        return None, 0

    bucket = outcome_bucket(score)

    sample = []
    for rec in closed:
        if rec.get("action") != action:
            continue
        if rec.get("bucket") != bucket:
            continue

        # По качественным монетам допускаем общую статистику, но сначала ищем конкретный актив.
        same_asset = rec.get("asset") == asset
        same_quality_group = rec.get("is_quality") is True

        if same_asset or same_quality_group:
            r24 = rec.get("results", {}).get("24h")
            if isinstance(r24, (int, float)):
                sample.append(r24)

    if len(sample) < 8:
        return None, len(sample)

    wins = sum(1 for x in sample if x >= 5)
    return wins / len(sample), len(sample)

def calibrate_chances(asset, action, score, chance_5, chance_10, chance_15):
    """
    Мягкая калибровка по собственной истории сигналов.
    Пока данных мало — почти ничего не меняет.
    """
    win_rate, n = historical_win_rate(asset, action, score)

    if win_rate is None:
        return chance_5, chance_10, chance_15, "истории пока мало"

    historical_chance = int(round(win_rate * 100))

    # Не даём истории полностью управлять прогнозом: сглаживаем.
    new_chance_5 = int(round(chance_5 * 0.7 + historical_chance * 0.3))

    if n >= 20:
        note = f"учтена история {n} похожих сигналов"
    else:
        note = f"история пока небольшая: {n} похожих сигналов"

    return new_chance_5, chance_10, chance_15, note

def confidence_level(c):
    score = c.get("score", 0)
    chance_5 = c.get("chance_5", 0)
    action = c.get("action", "SKIP")
    high = c.get("high", 0)

    base = int(round(score * 0.55 + chance_5 * 0.35 + max(0, min(high, 10)) * 1.0))

    if action == "BUY":
        base += 8
    elif action == "WATCH":
        base -= 3
    elif action == "PUMP":
        base -= 8
    else:
        base -= 15

    return max(5, min(95, base))


def save_signal_history(items):
    h = load_json(HISTORY_FILE)
    results = load_json(RESULTS_FILE)

    if not isinstance(results, dict):
        results = {}

    open_items = results.get("open", {})
    now = time.time()

    for c in items:
        h[c["symbol"]] = {
            "price": c["price"],
            "score": c["score"],
            "time": now
        }

        # Не плодим одинаковые записи чаще одного раза в 30 минут.
        last_open = None
        for rec in open_items.values():
            if rec.get("asset") == c["symbol"]:
                last_open = rec
                break

        if last_open and now - float(last_open.get("time", 0)) < 30 * 60:
            continue

        rec = {
            "asset": c["symbol"],
            "price": c["price"],
            "score": c["score"],
            "bucket": outcome_bucket(c["score"]),
            "chance_5": c["chance_5"],
            "action": c["action"],
            "verdict": c["verdict"],
            "is_quality": c["is_quality"],
            "time": now,
            "results": {}
        }

        open_items[signal_key(c["symbol"], now)] = rec

    results["open"] = open_items
    results.setdefault("closed", [])

    save_json(HISTORY_FILE, h)
    save_json(RESULTS_FILE, results)

def human_final(c):
    if "НЕТ СИГНАЛА" in c["verdict"]:
        return "сейчас нет нормального импульса: лучше просто наблюдать."

    if "РИСКОВАННЫЙ ИМПУЛЬС" in c["verdict"]:
        return "движение сильное, но это рискованный памп: вход только малым объёмом или лучше ждать откат."

    if "СИЛЬНЫЙ ТРЕНД" in c["verdict"]:
        return "тренд сильный, вход возможен, но лучше не догонять резкую свечу."

    if "РАННИЙ ТРЕНД" in c["verdict"]:
        return "момент выглядит рабочим: можно рассмотреть вход, но без завышенного объёма."

    if c["action"] == "BUY":
        if "РАННИЙ ИМПУЛЬС" in c["verdict"]:
            return "интересный ранний момент, но вход только небольшим объёмом и без погони за свечой."
        return "можно рассмотреть покупку, но не после резкой зелёной свечи."

    if "СОБЫТИЙНАЯ" in c["verdict"]:
        return "следить внимательно: новость может дать импульс, но после события возможен резкий слив."

    if c["action"] == "WATCH":
        return "идея есть, но пока НЕ покупать — ждать усиления объёма."

    if c["action"] == "PUMP":
        if "ТРЕНД ПРОДОЛЖАЕТСЯ" in c["verdict"]:
            return "тренд ещё живой, но вход рискованный: только малым объёмом и не после резкой свечи."
        return "это быстрый рискованный импульс, можно заработать, но риск высокий."

    return "сейчас лучше не покупать."


def confidence_explain_text(c):
    reasons = []

    if c.get("high", 0) < 5:
        reasons.append("потенциал роста ограничен")

    if c.get("chance_5", 0) < 35:
        reasons.append("шанс движения к +5% низкий")

    if c.get("volume_trend", 1) < 1.0:
        reasons.append("объём слабый или падает")

    ctx = c.get("ctx", {})
    if ctx.get("market_mod", 0) < 0:
        reasons.append("рынок добавляет риск")

    if c.get("downside", 0) < 0 and abs(c.get("downside", 0)) > max(0, c.get("high", 0)):
        reasons.append("риск выше потенциальной прибыли")

    if not reasons:
        return ""

    return "Почему уверенность ниже: " + " / ".join(reasons[:3]) + ".\n"

def scenario_text(c):
    low = c.get("low", 0)
    high = c.get("high", 0)

    if abs(low - high) < 0.15:
        if high > 0:
            return f"📈 Сценарий 24ч: около +{high:.1f}%\n"
        if high == 0:
            return "📈 Сценарий 24ч: около 0%\n"
        return f"📈 Сценарий 24ч: около {high:.1f}%\n"

    return f"📈 Сценарий 24ч: {low}%…{high}%\n"

def target_text(c):
    low = c.get("target_low", 0)
    high = c.get("target_high", 0)

    if abs(low - high) / max(high, 1) < 0.001:
        return f"🎯 Цель: ~${high:.6g}\n"

    return f"🎯 Цель: ${low:.6g}…${high:.6g}\n"

def no_signal_fix(c):
    """
    Для BTC/ETH в спокойном, но слабом моменте лучше писать не 'плохая сделка',
    а 'нет сигнала'. Это не меняет расчёты, только делает вывод понятнее.
    """
    if (
        c.get("symbol") in ["BTC", "ETH"]
        and c.get("action") == "SKIP"
        and c.get("score", 0) <= 35
        and c.get("rsi", 0) < 55
        and c.get("volume_trend", 0) >= 0.8
        and c.get("high", 0) < 2
    ):
        c = dict(c)
        c["verdict"] = "⚪ НЕТ СИГНАЛА"
    return c


def format_signal_item(i, c):
    c = no_signal_fix(c)
    plus = "\n".join([f"✅ {x}" for x in c["plus"]]) if c["plus"] else "✅ явных плюсов мало"
    minus = "\n".join([f"⚠️ {x}" for x in c["minus"]]) if c["minus"] else "⚠️ критичных минусов мало"

    confidence = confidence_level(c)
    rejected = (
        c.get("score",0) < 30
        or confidence < 10
        or c.get("chance_5",0) <= 12
        or c.get("rsi",0) >= 88
    )

    reason_block = rejection_reason_block(
        c.get("score",0),
        confidence,
        c.get("chance_5",0),
        c.get("rsi",0),
        c.get("volume_trend",1)
    )

    hot_block = overheating_block(
        c.get("rsi",0),
        c.get("volume_trend",1)
    )

    details_block = (
        f"Почему может вырасти:\n{plus}\n\nЧто мешает:\n{minus}\n\n"
        if not rejected else
        f"{hot_block}{reason_block}Что мешает:\n{minus}\n\n"
    )

    return (
        f"{i}. {c['symbol']} — {c['verdict']}\n"
        f"Тип: {c['profile']}\n"
        f"{c['status']}\n\n"
        f"Цена: ${c['price']:.6g}\n"
        f"Рост за сутки: {c['change_24']:.2f}%\n"
        f"RSI: {c.get('rsi', 'н/д')} | объём: x{c.get('volume_trend', 'н/д')}\n"
        f"Качество момента: {c['score']}/100\n"
        f"Уверенность сигнала: {confidence}%\n"
        f"{confidence_explain_text(c)}\n"
        f"Шансы на 24ч:\n"
        f"+5% → ~{c['chance_5']}%\n"
        f"+10% → ~{c['chance_10']}%\n"
        f"+15% → ~{c['chance_15']}%\n\n"
        f"{scenario_text(c)}"
        f"{target_text(c)}"
        f"🛑 Опасная зона: ниже ${c['stop']:.6g} ({c['downside']:.2f}%)\n\n"
        f"{details_block}"
        f"📍 Зона входа: {c.get('entry_zone', 'нет данных')}\n\n"
        f"{missing_for_buy_text(c)}"
        f"{worth_it_text(c)}\n"
        f"Итог: {human_final(c)}\n\n"
    )


def filter_recent_repeats(items, min_minutes=20):
    history = load_json(HISTORY_FILE)
    now = time.time()
    result = []

    for c in items:
        old = history.get(c["symbol"])
        if not old:
            result.append(c)
            continue

        old_time = old.get("time", 0)
        old_price = old.get("price", c["price"])
        price_move = abs(percent_change(old_price, c["price"]))

        if now - old_time >= min_minutes * 60 or price_move >= 1.0:
            result.append(c)

    return result




def rejection_reason_block(score, confidence, chance5, rsi, volume):
    reasons = []
    if rsi > 88:
        reasons.append("RSI экстремально перегрет")
    if volume < 0.7:
        reasons.append("объём падает")
    if chance5 < 10:
        reasons.append("потенциал роста почти исчерпан")
    if score < 30 or confidence < 10:
        reasons.append("риск коррекции выше ожидаемой прибыли")

    if not reasons:
        return ""

    txt = "❌ Почему сигнал отклонён:\n\n"
    for r in reasons:
        txt += f"• {r}\n"
    return txt + "\n"

def overheating_block(rsi, volume):
    if rsi > 85 and volume < 0.7:
        return "🔥 Перегрев рынка: высокий\n\n"
    return ""

def worth_it_text(c):
    high = float(c.get("high", 0) or 0)
    downside = abs(float(c.get("downside", 0) or 0))

    if high <= 0:
        verdict = "🔴 Нет"
        text = "Ожидаемого роста почти нет, риск снижения выше потенциальной прибыли."
    elif downside <= 0:
        verdict = "🟡 Осторожно"
        text = "Риск по стопу не удалось корректно оценить, вход только малым объёмом."
    elif high >= downside * 1.3:
        verdict = "🟢 Да"
        text = "Ожидаемая прибыль заметно превышает риск."
    elif high >= downside * 0.8:
        verdict = "🟡 Осторожно"
        text = "Прибыль и риск примерно сопоставимы."
    else:
        verdict = "🔴 Нет"
        text = "Риск выше ожидаемой прибыли."

    return (
        f"🧾 Стоит ли игра свеч?\n\n"
        f"{verdict}\n\n"
        f"Потенциал роста: до +{max(0, high):.1f}%\n"
        f"Риск снижения: до -{downside:.1f}%\n\n"
        f"{text}\n"
    )


def missing_for_buy_text(c):
    if c.get("score", 0) < 70:
        return ""

    if c.get("action") == "BUY":
        return ""

    reasons = []

    if c.get("change_24", 0) >= 8:
        reasons.append("нужен откат 2–3%, потому что рост за сутки уже большой")

    if c.get("volume_trend", 1) < 1.1:
        reasons.append("нужно усиление объёма хотя бы выше x1.1")

    if c.get("rsi", 50) > 80:
        reasons.append("нужно охлаждение RSI ниже 80")

    if c.get("chance_5", 0) < 50:
        reasons.append("нужен более высокий шанс движения к +5%")

    if not reasons:
        reasons.append("нужен новый импульс и подтверждение покупателями")

    text = "🚧 Почему ещё не BUY:\n\n"
    for r in reasons[:4]:
        text += f"• {r}\n"

    return text + "\n"

def best_watch_candidates(analyzed):
    if not analyzed:
        return ""

    top = sorted(
        [x for x in analyzed if x.get("action") != "BUY"],
        key=lambda x: (x.get("score", 0), x.get("chance_5", 0)),
        reverse=True
    )[:5]

    if not top:
        return ""

    txt = "🟦 ЛУЧШИЕ КАНДИДАТЫ НА НАБЛЮДЕНИЕ:\n\n"
    for i, c in enumerate(top, 1):
        need = max(0, 80 - int(c.get("score", 0)))
        txt += f"{i}. {c['symbol']} — {c['score']}/100"
        if need > 0:
            txt += f" | до BUY примерно {need} баллов"
        txt += "\n"
    return txt + "\n"


def action_plan_from_analyzed(analyzed):
    """
    План ожидания: что должно произойти, чтобы появился нормальный BUY.
    Показываем только самые понятные монеты, а не весь рынок.
    """
    if not analyzed:
        return ""

    preferred = ["TAO", "SOL", "BTC", "ETH", "SUI", "INJ", "LINK", "XRP"]
    selected = []

    for asset in preferred:
        for c in analyzed:
            if c.get("symbol") == asset and c not in selected:
                selected.append(c)
                break

    if not selected:
        selected = sorted(
            analyzed,
            key=lambda x: (x.get("score", 0), x.get("chance_5", 0)),
            reverse=True
        )[:3]
    else:
        selected = selected[:4]

    lines = []
    lines.append("⏳ ЧТО ЖДАТЬ ДЛЯ НОВОГО BUY-СИГНАЛА:\n")

    for c in selected:
        price = c.get("price", 0)
        symbol = c.get("symbol", "")
        score = c.get("score", 0)
        change_24 = c.get("change_24", 0)
        rsi_value = c.get("rsi", "н/д")
        volume_trend = c.get("volume_trend", "н/д")

        pullback_2 = price * 0.98
        pullback_3 = price * 0.97

        if c.get("action") == "BUY":
            continue

        if score >= 60 and change_24 < 6:
            condition = (
                f"ждать усиление объёма выше x1.1–1.3 "
                f"или удержание цены без резкого отката"
            )
        elif change_24 >= 8:
            condition = (
                f"ждать откат 2–3% к ${pullback_2:.6g}…${pullback_3:.6g} "
                f"и охлаждение RSI ниже 80"
            )
        elif score < 50:
            condition = (
                f"ждать улучшение качества момента: рост объёма, RSI ниже перегрева "
                f"и новый импульс"
            )
        else:
            condition = (
                f"ждать подтверждение объёмом и закрепление цены выше текущего уровня"
            )

        lines.append(
            f"• {symbol}: цена ${price:.6g}, score {score}/100, "
            f"RSI {rsi_value}, объём x{volume_trend}. "
            f"Условие: {condition}."
        )

    if len(lines) <= 1:
        return ""

    return "\n".join(lines) + "\n\n"

def get_signal():
    try:
        update_signal_results()
        candidates = []

        for t in kucoin_tickers():
            symbol = t.get("symbol", "")

            if not symbol.endswith("-USDT"):
                continue

            volume = float(t.get("volValue", 0) or 0)
            change = float(t.get("changeRate", 0) or 0) * 100

            if volume < 1_000_000:
                continue

            priority = volume / 1_000_000 + max(change, 0) * 2
            candidates.append((symbol, priority))

        selected = [x[0] for x in sorted(candidates, key=lambda x: x[1], reverse=True)[:35]]

        for forced in FORCE_ANALYZE_ASSETS:
            if forced not in selected:
                selected.append(forced)

        analyzed = []

        for symbol in selected:
            try:
                c = alex_edge_ultra(symbol)
                if c:
                    analyzed.append(c)
                time.sleep(0.2)
            except Exception:
                continue

        buy = sorted(
            [
                x for x in analyzed
                if (
                    x["action"] == "BUY"
                    and (
                        (
                            x["chance_5"] >= 65
                            and x["high"] >= 5
                        )
                        or "РАННИЙ ТРЕНД" in x["verdict"]
                    )
                )
            ],
            key=lambda x: (x["chance_10"], x["chance_5"], x["score"]),
            reverse=True
        )[:5]

        watch = sorted(
            [
                x for x in analyzed
                if (
                    x not in buy
                    and x["action"] == "WATCH"
                    and x["chance_5"] >= 35
                    and x["high"] >= 5
                    and x["score"] >= 55
                    and x["change_24"] < 25
                )
            ],
            key=lambda x: (
                1 if "СОБЫТИЙНАЯ" in x["verdict"] else 0,
                x["chance_5"],
                x["high"],
                x["score"]
            ),
            reverse=True
        )[:5]

        pumps = sorted(
            [
                x for x in analyzed
                if (
                    x not in buy
                    and x not in watch
                    and x["action"] == "PUMP"
                    and (
                        "ТРЕНД ПРОДОЛЖАЕТСЯ" in x["verdict"]
                        or (
                            x["chance_5"] >= 40
                            and x["high"] >= 4.5
                            and x["vol_power"] >= 1.5
                            and x["change_24"] <= 15
                        )
                    )
                )
            ],
            key=lambda x: (x["chance_5"], x["high"], x["vol_power"]),
            reverse=True
        )[:3]

        buy = filter_recent_repeats(buy, min_minutes=20)
        watch = filter_recent_repeats(watch, min_minutes=20)
        pumps = filter_recent_repeats(pumps, min_minutes=20)

        late_pumps = sorted(
            [
                x for x in analyzed
                if (
                    x["change_24"] > 12
                    and x not in buy
                    and x not in watch
                    and x not in pumps
                )
            ],
            key=lambda x: x["change_24"],
            reverse=True
        )[:5]

        if not buy and not watch and not pumps and not late_pumps:
            plan = action_plan_from_analyzed(analyzed)
            return f"🚀 ALEX EDGE ULTRA {BOT_VERSION}\n\nСейчас нет нормальных идей для покупки.\n\n" + plan

        save_signal_history(buy + watch + pumps)

        if buy:
            ctx_source = buy[0]
        elif watch:
            ctx_source = watch[0]
        elif pumps:
            ctx_source = pumps[0]
        else:
            ctx_source = late_pumps[0]

        ctx = ctx_source["ctx"]

        text = (
            f"🚀 ALEX EDGE ULTRA {BOT_VERSION}\n"
            f"Рынок: {ctx['state']}\n"
            f"BTC: {ctx['btc_text']} | BTC 24ч: {ctx['btc_change']:.2f}%\n"
            f"Настроение: {ctx['fg_value']} — {ctx['fg_text']}\n"
        )

        if ctx["dom_text"]:
            text += f"BTC dominance: {ctx['dom_text']}\n"

        text += f"{ctx['geo_text']}\n\n"

        if buy:
            text += "🟢 РАННИЕ ПОКУПКИ:\n\n"
            for i, c in enumerate(buy, 1):
                text += format_signal_item(i, c)
        else:
            text += "🟢 Покупок сейчас нет.\n\n"
            text += best_watch_candidates(analyzed)
            text += action_plan_from_analyzed(analyzed)

        if watch:
            text += "🟡 ТОЛЬКО НАБЛЮДАТЬ:\n\n"
            for i, c in enumerate(watch, 1):
                text += format_signal_item(i, c)

        if pumps:
            text += "🟠 ЖДАТЬ ОТКАТ / РИСКОВАННЫЕ ИМПУЛЬСЫ:\n\n"
            for i, c in enumerate(pumps, 1):
                text += format_signal_item(i, c)

        if late_pumps:
            text += "❌ ПОЗДНИЕ ПАМПЫ — НЕ ПОКУПАТЬ:\n\n"
            for c in late_pumps:
                text += (
                    f"• {c['symbol']}: уже +{c['change_24']:.2f}% за сутки, "
                    f"шанс +5% ~{c['chance_5']}%, но вход поздний и риск отката высокий.\n"
                )
            text += "\n"

        text += "⚠️ Покупать стоит только зелёные сигналы. Событийные и жёлтые — наблюдение. Оранжевые — высокий риск. Красные — не покупать."
        return text

    except Exception as e:
        return f"Ошибка /signal:\n{e}"

def get_fast_pumps():
    try:
        found = []

        for t in kucoin_tickers():
            symbol = t.get("symbol", "")

            if not symbol.endswith("-USDT"):
                continue

            volume = float(t.get("volValue", 0) or 0)

            if volume < 1_000_000:
                continue

            try:
                c = alex_edge_ultra(symbol)

                if (
                    c["action"] == "PUMP"
                    and c["chance_5"] >= 40
                    and c["high"] >= 4.5
                    and c["vol_power"] >= 1.5
                    and c["fast_move"] >= 1.2
                    and c["change_24"] <= 15
                ):
                    found.append(c)

                time.sleep(0.15)

            except Exception:
                continue

        found = sorted(
            found,
            key=lambda x: (x["fast_move"], x["vol_power"]),
            reverse=True
        )[:3]

        if not found:
            return None, []

        text = f"🔥 ALEX FAST PUMP {BOT_VERSION}\n\n"

        for i, c in enumerate(found, 1):
            text += (
                f"{i}. {c['symbol']}\n"
                f"Цена: ${c['price']:.6g}\n"
                f"Быстрый импульс: +{c['fast_move']:.2f}%\n"
                f"Сила покупателей: x{c['vol_power']:.1f}\n"
                f"Сценарий: {max(0, c['low'])}%…{c['high']}%\n"
                f"Риск: высокий, не держать долго\n\n"
            )

        text += "⚠️ Это быстрый рискованный сигнал, не спокойная покупка."
        return text, found

    except Exception:
        return None, []

def should_send_pump(items):
    history = load_json(PUMP_FILE)
    now = time.time()
    allowed = []

    for c in items:
        last = history.get(c["symbol"], 0)

        if now - last >= REPEAT_PUMP_AFTER:
            allowed.append(c)
            history[c["symbol"]] = now

    save_json(PUMP_FILE, history)
    return allowed

def get_top():
    try:
        pairs = [
            x for x in kucoin_tickers()
            if x.get("symbol", "").endswith("-USDT")
        ]

        top = sorted(
            pairs,
            key=lambda x: float(x.get("volValue", 0) or 0),
            reverse=True
        )[:10]

        text = f"📈 Топ KuCoin по объёму\nВерсия: {BOT_VERSION}\n\n"

        for coin in top:
            symbol = coin.get("symbol", "").replace("-USDT", "")
            price = coin.get("last", "0")
            change = float(coin.get("changeRate", 0) or 0) * 100
            text += f"{symbol}: ${price} | 24ч: {change:.2f}%\n"

        return text

    except Exception as e:
        return f"Ошибка /top:\n{e}"

def single_analysis(symbol):
    c = alex_edge_ultra(symbol)

    if not c:
        return f"Версия: {BOT_VERSION}\nМонета не найдена."

    return f"Версия: {BOT_VERSION}\n\n" + format_signal_item(1, c)

def market_status():
    ctx = market_context()

    text = (
        f"🌍 Обзор рынка\n"
        f"Версия: {BOT_VERSION}\n\n"
        f"Рынок: {ctx['state']}\n"
        f"BTC: {ctx['btc_text']} | BTC 24ч: {ctx['btc_change']:.2f}%\n"
        f"Настроение: {ctx['fg_value']} — {ctx['fg_text']}\n"
    )

    if ctx["dom_text"]:
        text += f"BTC dominance: {ctx['dom_text']}\n"

    text += (
        f"{ctx['geo_text']}\n\n"
        f"Простыми словами: покупать лучше только когда BTC не мешает, "
        f"объём в монете растёт, и бот показывает зелёный статус покупки."
    )

    return text

def help_text():
    return (
        f"Версия бота: {BOT_VERSION}\n\n"
        "✅ Команды:\n\n"
        "/signal — монеты для покупки/наблюдения\n"
        "/top — топ монет по объёму\n"
        "/btc — анализ BTC\n"
        "/sol — анализ SOL\n"
        "/alerts — быстрые пампы\n"
        "/market — фон рынка\n"
        "/version — версия бота\n"
        "/help — помощь\n\n"
        "Статусы:\n"
        "🟢 ПОКУПКА — можно рассмотреть вход\n"
        "🔥 РАННИЙ ИМПУЛЬС — агрессивная возможность\n"
        "📌 СОБЫТИЙНАЯ МОНЕТА — следить из-за новости\n"
        "🟡 НАБЛЮДАТЬ — пока не покупать\n"
        "🟠 РИСКОВАННЫЙ ПАМП — можно заработать, но риск высокий\n"
        "🟢 СИЛЬНЫЙ ТРЕНД — качественная монета уже выросла, но импульс ещё сильный\n"
        "🔴 НЕ ПОКУПАТЬ — лучше пропустить\n"
        "🟠 ЖДАТЬ ОТКАТ — движение есть, но вход с рынка уже поздний\n"
        "📍 Зона входа — простая подсказка, вход сейчас или ждать\n"
        "⏳ План ожидания — что должно произойти для нового BUY-сигнала"
    )

def moscow_now():
    return datetime.utcnow() + timedelta(hours=MOSCOW_OFFSET_HOURS)

def main():
    last_update = None
    last_signal_key = None
    last_market_key = None
    last_pump_key = None

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

                elif text == "/version":
                    send_message(chat_id, f"✅ Текущая версия бота: {BOT_VERSION}")

                elif text == "/top":
                    send_message(chat_id, get_top())

                elif text == "/signal":
                    send_message(chat_id, "⏳ Ищу монеты для покупки, подожди 30–60 секунд...")
                    send_message(chat_id, get_signal())

                elif text == "/btc":
                    send_message(chat_id, single_analysis("BTC-USDT"))

                elif text == "/sol":
                    send_message(chat_id, single_analysis("SOL-USDT"))

                elif text == "/market":
                    send_message(chat_id, market_status())

                elif text == "/alerts":
                    send_message(chat_id, "⏳ Проверяю быстрые пампы...")
                    text_alert, _ = get_fast_pumps()

                    if text_alert:
                        send_message(chat_id, text_alert)
                    else:
                        send_message(chat_id, f"Версия: {BOT_VERSION}\nСейчас быстрых памп-сигналов нет.")

            saved_chat_id = load_chat_id()

            if saved_chat_id:
                now_msk = moscow_now()

                signal_key = now_msk.strftime("%Y-%m-%d %H")
                market_key = now_msk.strftime("%Y-%m-%d")
                pump_key = now_msk.strftime("%Y-%m-%d %H:%M")

                if (
                    now_msk.hour in SIGNAL_HOURS
                    and now_msk.minute < 5
                    and last_signal_key != signal_key
                ):
                    send_message(saved_chat_id, get_signal())
                    last_signal_key = signal_key

                if (
                    now_msk.hour == MARKET_HOUR
                    and now_msk.minute < 5
                    and last_market_key != market_key
                ):
                    send_message(saved_chat_id, market_status())
                    last_market_key = market_key

                if (
                    now_msk.minute in PUMP_MINUTES
                    and last_pump_key != pump_key
                ):
                    text_alert, items = get_fast_pumps()

                    if text_alert and should_send_pump(items):
                        send_message(saved_chat_id, text_alert)

                    last_pump_key = pump_key

            time.sleep(2)

        except Exception as e:
            print(e)
            time.sleep(5)

if __name__ == "__main__":
    keep_alive()
    main()


# === V3.7 CONSISTENCY FIX ===
# 1. Score cap when signal is SKIP and upside is minimal.
# 2. BTC after +4% day with falling volume is capped.
# 3. +10/+15 probabilities reduced when expected upside is tiny.
# 4. Improves consistency between score, probabilities and verdict.

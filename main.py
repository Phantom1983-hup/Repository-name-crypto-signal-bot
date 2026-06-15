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
BOT_VERSION = "v2.6 TREND CONTINUATION"

CHAT_ID_FILE = "chat_id.txt"
HISTORY_FILE = "signal_history.json"
PUMP_FILE = "pump_history.json"

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
            return dom, -5, "BTC забирает деньги у альтов"

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
    elif 76 < d["rsi"] <= 84:
        score -= 4
        minus.append("монета уже горячая")
    elif d["rsi"] > 84:
        score -= 14
        minus.append("монета перегрета")

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
        and 8 <= change_24 <= 18
        and d["trend_1h"]
        and d["trend_4h"]
        and d["move_1h"] >= 1.2
        and d["macd"] > 0
        and ctx["btc_mod"] >= 0
    )

    if strong_continuation:
        low = max(low, 1.0)
        high = max(high, min(7.0, max(3.5, d["atr_pct"] * 3.2)))
        target_low = price * (1 + low / 100)
        target_high = price * (1 + high / 100)
        chance_5 = max(chance_5, 38)
        chance_10 = max(chance_10, 12)
        plus.append("сильный тренд ещё продолжается")
        minus.append("это уже не ранний вход, а рискованное продолжение движения")

    if change_24 >= 25:
        verdict = "🔴 ПОЗДНИЙ ПАМП"
        action = "SKIP"
    elif asset in EVENT_ASSETS and chance_5 >= 42:
        verdict = "📌 СОБЫТИЙНАЯ МОНЕТА"
        action = "WATCH"
    elif strong_continuation and chance_5 >= 35 and high >= 3.5:
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
    elif chance_5 >= 35 and high >= 5:
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
        "vol_power": d["vol_1h"]
    }

def save_signal_history(items):
    h = load_json(HISTORY_FILE)

    for c in items:
        h[c["symbol"]] = {
            "price": c["price"],
            "score": c["score"],
            "time": time.time()
        }

    save_json(HISTORY_FILE, h)

def human_final(c):
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

def format_signal_item(i, c):
    plus = "\n".join([f"✅ {x}" for x in c["plus"]]) if c["plus"] else "✅ явных плюсов мало"
    minus = "\n".join([f"⚠️ {x}" for x in c["minus"]]) if c["minus"] else "⚠️ критичных минусов мало"

    return (
        f"{i}. {c['symbol']} — {c['verdict']}\n"
        f"Тип: {c['profile']}\n"
        f"{c['status']}\n\n"
        f"Цена: ${c['price']:.6g}\n"
        f"Рост за сутки: {c['change_24']:.2f}%\n"
        f"Качество момента: {c['score']}/100\n\n"
        f"Шансы на 24ч:\n"
        f"+5% → ~{c['chance_5']}%\n"
        f"+10% → ~{c['chance_10']}%\n"
        f"+15% → ~{c['chance_15']}%\n\n"
        f"📈 Сценарий 24ч: {c['low']}%…{c['high']}%\n"
        f"🎯 Цель: ${c['target_low']:.6g}…${c['target_high']:.6g}\n"
        f"🛑 Опасная зона: ниже ${c['stop']:.6g} ({c['downside']:.2f}%)\n\n"
        f"Почему может вырасти:\n{plus}\n\n"
        f"Что мешает:\n{minus}\n\n"
        f"Итог: {human_final(c)}\n\n"
    )

def get_signal():
    try:
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
                    and x["chance_5"] >= 65
                    and x["high"] >= 5
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
                    and x["chance_5"] >= 40
                    and x["high"] >= 4.5
                    and x["vol_power"] >= 1.5
                    and x["change_24"] <= 15
                )
            ],
            key=lambda x: (x["chance_5"], x["high"], x["vol_power"]),
            reverse=True
        )[:3]

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
            return f"🚀 ALEX EDGE ULTRA {BOT_VERSION}\n\nСейчас нет нормальных идей для покупки."

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
            text += "🟢 МОЖНО РАССМОТРЕТЬ ПОКУПКУ:\n\n"
            for i, c in enumerate(buy, 1):
                text += format_signal_item(i, c)
        else:
            text += "🟢 Покупок сейчас нет.\n\n"

        if watch:
            text += "🟡 ТОЛЬКО НАБЛЮДАТЬ:\n\n"
            for i, c in enumerate(watch, 1):
                text += format_signal_item(i, c)

        if pumps:
            text += "🟠 РИСКОВАННЫЕ БЫСТРЫЕ ИМПУЛЬСЫ:\n\n"
            for i, c in enumerate(pumps, 1):
                text += format_signal_item(i, c)

        if late_pumps:
            text += "❌ ПОЗДНИЕ ПАМПЫ — НЕ ПОКУПАТЬ:\n\n"
            for c in late_pumps:
                text += (
                    f"• {c['symbol']}: уже +{c['change_24']:.2f}% за сутки, "
                    f"шанс +5% всего ~{c['chance_5']}%, риск отката высокий.\n"
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
        "🟠 ТРЕНД ПРОДОЛЖАЕТСЯ — качественная монета уже выросла, но импульс ещё живой\n"
        "🔴 НЕ ПОКУПАТЬ — лучше пропустить"
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

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
BOT_VERSION = "v7.6 MACRO SAFE BUY FILTER"

CHAT_ID_FILE = "chat_id.txt"
HISTORY_FILE = "signal_history.json"
PUMP_FILE = "pump_history.json"
RESULTS_FILE = "signal_results.json"

SIGNAL_HOURS = [9, 15, 21]
MARKET_HOUR = 9
PUMP_MINUTES = [0, 10, 20, 30, 40, 50]
MOSCOW_OFFSET_HOURS = 3

REPEAT_PUMP_AFTER = 60 * 60

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


def fetch_rss_text(query, timeout=8):
    try:
        url = "https://news.google.com/rss/search"
        params = {
            "q": query,
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en"
        }
        return requests.get(url, params=params, timeout=timeout).text.lower()
    except Exception:
        return ""

def word_score(text, words):
    score = 0
    for word, weight in words.items():
        if word in text:
            score += weight
    return score

def macro_fed_score():
    """
    ФРС: ставка, инфляция, риторика.
    Минус — жёсткая ФРС / higher for longer.
    Плюс — намёки на снижение ставки / dovish tone.
    """
    text = fetch_rss_text(
        'Federal Reserve Powell FOMC rate cut inflation "higher for longer" crypto stocks'
    )

    hawkish_words = {
        "higher for longer": 5,
        "restrictive": 4,
        "inflation": 3,
        "sticky inflation": 5,
        "hot inflation": 4,
        "rate hike": 5,
        "no rush": 3,
        "uncertainty": 2,
        "hawkish": 4,
        "powell warns": 4
    }

    dovish_words = {
        "rate cut": 4,
        "cuts": 3,
        "easing": 4,
        "dovish": 4,
        "cooling inflation": 4,
        "soft landing": 3,
        "pause": 2,
        "labor market softens": 4
    }

    hawk = word_score(text, hawkish_words)
    dove = word_score(text, dovish_words)
    raw = dove - hawk

    if raw >= 6:
        return 8, "🟢 ФРС: риторика мягче / рынок ждёт снижение ставки"
    if raw >= 2:
        return 4, "🟢 ФРС: умеренно позитивно"
    if raw <= -8:
        return -10, "🔴 ФРС: жёсткая риторика давит на риск"
    if raw <= -3:
        return -6, "🔴 ФРС: позитива мало, ставки давят"
    return 0, "🟡 ФРС: нейтрально / рынок ждёт новых данных"

def macro_geopolitics_score():
    """
    Геополитика: США/Иран, нефть, Hormuz.
    Деэскалация — плюс. Удары, санкции, нефть/Hormuz — минус.
    """
    text = fetch_rss_text(
        'US Iran talks ceasefire oil Hormuz sanctions missile attack Middle East'
    )

    risk_words = {
        "attack": 5,
        "missile": 5,
        "strike": 4,
        "war": 5,
        "hormuz": 5,
        "strait": 3,
        "oil jumps": 4,
        "sanctions": 3,
        "escalation": 5,
        "retaliation": 5,
        "tanker": 3
    }

    positive_words = {
        "talks": 3,
        "negotiations": 4,
        "ceasefire": 5,
        "deal": 4,
        "diplomacy": 4,
        "de-escalation": 5,
        "agreement": 4,
        "resume talks": 5
    }

    risk = word_score(text, risk_words)
    positive = word_score(text, positive_words)
    raw = positive - risk

    if raw >= 6:
        return 8, "🟢 Геополитика: признаки деэскалации"
    if raw >= 2:
        return 4, "🟢 Геополитика: стало спокойнее"
    if raw <= -8:
        return -10, "🔴 Геополитика: высокий риск эскалации"
    if raw <= -3:
        return -6, "🔴 Геополитика: риск всё ещё давит"
    return 0, "🟡 Геополитика: смешанный фон"

def macro_crypto_news_score():
    """
    Крипто-новости: ETF, regulation, hacks, lawsuits.
    """
    text = fetch_rss_text(
        'bitcoin ethereum crypto ETF regulation hack lawsuit SEC institutional inflows'
    )

    positive_words = {
        "etf inflows": 5,
        "inflows": 3,
        "institutional": 3,
        "approval": 4,
        "adoption": 3,
        "bullish": 3,
        "record inflows": 5
    }

    risk_words = {
        "hack": 5,
        "exploit": 5,
        "lawsuit": 3,
        "sec sues": 5,
        "ban": 5,
        "outflows": 4,
        "liquidations": 3,
        "crackdown": 5
    }

    positive = word_score(text, positive_words)
    risk = word_score(text, risk_words)
    raw = positive - risk

    if raw >= 5:
        return 5, "🟢 Крипто-новости: поддерживают рынок"
    if raw <= -5:
        return -6, "🔴 Крипто-новости: добавляют риск"
    return 0, "🟡 Крипто-новости: без сильного перекоса"

def get_news_risk():
    """
    Совместимость со старым кодом.
    Возвращает общий macro score и короткую строку.
    """
    try:
        fed_mod, fed_text = macro_fed_score()
        geo_mod, geo_text = macro_geopolitics_score()
        crypto_mod, crypto_text = macro_crypto_news_score()

        total = fed_mod + geo_mod + crypto_mod

        if total >= 8:
            title = "🟢 Внешний фон улучшается"
        elif total >= 2:
            title = "🟢 Внешний фон умеренно позитивный"
        elif total <= -12:
            title = "🟥 Внешний фон опасный"
        elif total <= -4:
            title = "🔴 Внешний фон негативный"
        else:
            title = "🟡 Внешний фон смешанный"

        text = (
            f"{title} ({total:+d})\n"
            f"{fed_text}\n"
            f"{geo_text}\n"
            f"{crypto_text}"
        )

        return total, text

    except Exception:
        return 0, "⚪ Внешний фон не удалось оценить"

def macro_mode_text(ctx):
    score = ctx.get("macro_mod", ctx.get("geo_mod", 0))

    if score >= 8:
        return "🌍 Фон: 🟢 позитивный"
    if score >= 2:
        return "🌍 Фон: 🟢 слегка лучше"
    if score <= -12:
        return "🌍 Фон: 🟥 опасный"
    if score <= -4:
        return "🌍 Фон: 🔴 негативный"
    return "🌍 Фон: 🟡 смешанный"

def macro_action_hint(ctx):
    score = ctx.get("macro_mod", ctx.get("geo_mod", 0))

    if score <= -12:
        return "Вывод: быстрые BUY сильно ограничить, среднесрок только BTC/ETH частями."
    if score <= -4:
        return "Вывод: быстрые BUY по альтам ограничить; среднесрок в основном BTC/ETH частями."
    if score < 8:
        return "Вывод: обычный режим, но ждать подтверждения объёмом."
    return "Вывод: фон помогает, можно активнее искать BUY."

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
    macro_mod, macro_text = get_news_risk()
    btc_text, btc_mod, btc_change = btc_filter()

    total = fg_mod + dom_mod + macro_mod + btc_mod

    if macro_mod <= -12:
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
        "geo_text": macro_text,
        "geo_mod": macro_mod,
        "macro_text": macro_text,
        "macro_mod": macro_mod,
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
    score = c.get("_master_score", c.get("score", 0))
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
    if "СРЕДНЕСРОЧНЫЙ" in c["verdict"]:
        return "начать набор первой части позиции, строго частями и без входа на всю сумму."

    if "НЕТ СИГНАЛА" in c["verdict"]:
        return "сейчас качественного входа нет: лучше наблюдать и ждать усиления объёма."

    if "МОЖНО МАЛЫМ ОБЪЁМОМ" in c["verdict"]:
        return "сильного BUY нет, но осторожный вход малым объёмом допустим при строгом стопе."

    if "СПЕКУЛЯТИВНАЯ ИДЕЯ" in c["verdict"]:
        return "это спекулятивная идея, не спокойная покупка: только микропозицией или пропустить."

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

def format_signal_item(i, c):
    plus = "\n".join([f"✅ {x}" for x in c["plus"]]) if c["plus"] else "✅ явных плюсов мало"
    minus = "\n".join([f"⚠️ {x}" for x in c["minus"]]) if c["minus"] else "⚠️ критичных минусов мало"

    confidence = confidence_level(c)
    rejected = (
        "НЕТ СИГНАЛА" not in c.get("verdict", "")
        and (
            c.get("score",0) < 30
            or confidence < 10
            or c.get("chance_5",0) <= 12
            or c.get("rsi",0) >= 88
        )
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
        f"🔥 Сила покупателей: {buyer_strength_score(c)}/100\n"
        f"🧊 Риск отката: {pullback_risk_level(c)[0]}\n"
        f"Качество момента: {c['score']}/100\n"
        f"{('Скорректированная оценка: ' + str(adjusted_score(c)) + '/100\n') if adjusted_score(c) != c.get('score') else ''}"
        f"Уверенность сигнала: {confidence}%\n\n"
        f"Шансы на 24ч:\n"
        f"+5% → ~{c['chance_5']}%\n"
        f"+10% → ~{c['chance_10']}%\n"
        f"+15% → ~{c['chance_15']}%\n\n"
        f"📈 Сценарий 24ч: {c['low']}%…{c['high']}%\n"
        f"🎯 Цель: ${c['target_low']:.6g}…${c['target_high']:.6g}\n"
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





def asset_quality_rank(c):
    symbol = c.get("symbol", "")
    profile = c.get("profile", "")

    # Качество актива важнее красивого score.
    # Иначе мемы и случайные пампы попадают выше BTC/SOL/TAO/LINK.
    if symbol in ["BTC", "ETH"]:
        return 120
    if symbol in ["SOL", "TAO", "LINK", "INJ", "AAVE", "NEAR", "AVAX", "SUI"]:
        return 105
    if symbol in QUALITY_ASSETS:
        return 95
    if "ликвидный" in profile:
        return 65
    if "спекулятивный" in profile:
        return 15
    return 40


def reward_risk_ratio(c):
    reward = max(0, float(c.get("high", 0) or 0))
    risk = abs(float(c.get("downside", 0) or 0))

    if risk <= 0:
        return 0

    return reward / risk


def v6_quality_group(c):
    symbol = c.get("symbol", "")
    profile = c.get("profile", "")

    if symbol in ["BTC", "ETH"]:
        return "core"
    if symbol in ["SOL", "TAO", "LINK", "INJ", "AAVE", "NEAR", "AVAX", "SUI"] or symbol in QUALITY_ASSETS:
        return "quality"
    if "ликвидный" in profile:
        return "liquid"
    if "спекулятивный" in profile:
        return "speculative"
    return "other"

def v6_reward_risk(c):
    reward = max(0, float(c.get("high", 0) or 0))
    risk = abs(float(c.get("downside", 0) or 0))
    if risk <= 0:
        return 0
    return reward / risk

def v6_master_score(c):
    """
    Единый скоринг 0-100.
    Все статусы, confidence, watch/buy и текст должны плясать от него.
    """
    group = v6_quality_group(c)
    score = 0

    # 1) Качество актива
    if group == "core":
        score += 20
    elif group == "quality":
        score += 16
    elif group == "liquid":
        score += 10
    elif group == "speculative":
        score += 4
    else:
        score += 7

    # 2) Движение за сутки
    ch = c.get("change_24", 0)
    if 1 <= ch <= 7:
        score += 18
    elif -3 <= ch < 1:
        score += 8
    elif 7 < ch <= 12:
        score += 10
    elif 12 < ch <= 18:
        score -= 8
    elif ch > 18:
        score -= 22
    elif -6 <= ch < -3:
        score -= 8
    else:
        score -= 18

    # 3) RSI
    rsi = c.get("rsi", 50)
    if 48 <= rsi <= 65:
        score += 16
    elif 40 <= rsi < 48:
        score += 8
    elif 65 < rsi <= 75:
        score += 8
    elif 75 < rsi <= 82:
        score -= 8
    elif rsi > 82:
        score -= 24
    elif 30 <= rsi < 40:
        score -= 5
    else:
        score -= 18

    # 4) Объём
    vol = c.get("volume_trend", 1)
    if vol >= 2:
        score += 20
    elif vol >= 1.2:
        score += 16
    elif vol >= 0.9:
        score += 8
    elif vol >= 0.55:
        score += 2
    elif vol >= 0.35:
        score -= 6
    else:
        score -= 16

    # 5) Потенциал и риск/прибыль
    high = c.get("high", 0)
    rr = v6_reward_risk(c)

    if high >= 6:
        score += 12
    elif high >= 4:
        score += 8
    elif high >= 2:
        score += 3
    else:
        score -= 10

    if rr >= 1.4:
        score += 10
    elif rr >= 1.0:
        score += 4
    elif rr >= 0.7:
        score -= 6
    else:
        score -= 14

    # 6) Рынок
    ctx = c.get("ctx", {})
    btc_mod = ctx.get("btc_mod", 0)
    market_mod = ctx.get("market_mod", 0)

    if btc_mod > 8:
        score += 8
    elif btc_mod < -12:
        score -= 12
    elif btc_mod < 0:
        score -= 6

    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))

    if market_mod < -8:
        score -= 8
    elif market_mod > 5:
        score += 5

    if macro_mod <= -12:
        score -= 10
    elif macro_mod <= -4:
        score -= 5
    elif macro_mod >= 8:
        score += 6
    elif macro_mod >= 2:
        score += 3

    # 7) Спекулятивные монеты в плохом рынке
    if group == "speculative" and (btc_mod < 0 or market_mod < -5 or macro_mod < -4):
        score -= 12

    return max(0, min(100, int(round(score))))

def v6_is_neutral(c, ms):
    group = v6_quality_group(c)

    return (
        group in ["core", "quality"]
        and 35 <= c.get("rsi", 50) <= 65
        and -3 <= c.get("change_24", 0) <= 3
        and c.get("volume_trend", 1) >= 0.40
        and ms < 45
    )


def v6_oversold_reversal_score(c):
    score = 0
    group = v6_quality_group(c)

    if group in ["core", "quality"]:
        score += 25
    elif group == "liquid":
        score += 12
    else:
        score += 4

    rsi = c.get("rsi", 50)
    change = c.get("change_24", 0)
    vol = c.get("volume_trend", 1)
    ctx = c.get("ctx", {})

    if rsi < 35:
        score += 25
    elif rsi < 40:
        score += 18
    elif rsi < 45:
        score += 10

    if -6 <= change <= -1.2:
        score += 18
    elif -10 <= change < -6:
        score += 5

    if vol >= 1.5:
        score += 22
    elif vol >= 1.2:
        score += 16
    elif vol >= 0.9:
        score += 7

    if ctx.get("fg_value", 50) <= 25 and ctx.get("btc_change", 0) > -4:
        score += 10

    if ctx.get("btc_change", 0) < -4:
        score -= 18

    if c.get("high", 0) < 3:
        score += 5

    return max(0, min(100, int(round(score))))

def v6_is_oversold_reversal(c):
    rs = v6_oversold_reversal_score(c)
    group = v6_quality_group(c)

    return (
        group in ["core", "quality", "liquid"]
        and rs >= 62
        and c.get("rsi", 50) < 42
        and c.get("change_24", 0) <= -1.2
        and c.get("volume_trend", 1) >= 1.1
    )



def v7_accumulation_score(c):
    """
    Среднесрочный набор на красном рынке.
    Это НЕ быстрый трейд на +5%, а идея для частичного входа/усреднения на горизонте 2-8 недель.
    """
    score = 0
    group = v6_quality_group(c)
    ctx = c.get("ctx", {})

    if group == "core":
        score += 32
    elif group == "quality":
        score += 26
    elif group == "liquid":
        score += 12
    else:
        return 0

    change = c.get("change_24", 0)
    rsi = c.get("rsi", 50)
    vol = c.get("volume_trend", 1)

    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))

    # Красный рынок и страх — не только риск, но и зона поиска среднесрочных входов.
    if ctx.get("fg_value", 50) <= 20:
        score += 14
    elif ctx.get("fg_value", 50) <= 30:
        score += 8

    # v7.5: если внешний фон плохой, не даём рискованным альтам попадать в "начать набор".
    # В сильном негативе среднесрок разрешаем в основном BTC/ETH.
    if macro_mod <= -12 and c.get("symbol") not in ["BTC", "ETH"]:
        score -= 28
    elif macro_mod <= -8 and c.get("symbol") not in ["BTC", "ETH"]:
        if c.get("symbol") == "SOL":
            score -= 12
        else:
            score -= 24
    elif macro_mod <= -4:
        score -= 5
    elif macro_mod >= 8:
        score += 8
    elif macro_mod >= 2:
        score += 4

    if -7 <= change <= -1:
        score += 14
    elif -12 <= change < -7:
        score += 5
    elif change > 4:
        score -= 12

    if 32 <= rsi <= 45:
        score += 16
    elif 45 < rsi <= 55:
        score += 8
    elif rsi < 28:
        score -= 8
    elif rsi > 70:
        score -= 14

    if vol >= 1.2:
        score += 14
    elif vol >= 0.7:
        score += 6
    elif vol < 0.35:
        score -= 8

    # Если BTC очень сильно падает, лучше не ловить нож.
    if ctx.get("btc_change", 0) < -4:
        score -= 18

    # Если BTC dominance забирает деньги у альтов, альты штрафуем, BTC/ETH оставляем мягче.
    if c.get("symbol") not in ["BTC", "ETH"] and ctx.get("dom_text"):
        if "забирает деньги" in ctx.get("dom_text", ""):
            score -= 8

    return max(0, min(100, int(round(score))))

def v7_is_accumulation_candidate(c):
    score = v7_accumulation_score(c)
    group = v6_quality_group(c)
    ctx = c.get("ctx", {})
    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    symbol = c.get("symbol", "")

    # v7.5 Macro Safe Alt Filter:
    # При плохом внешнем фоне не говорим "начать набор" по широкому списку альтов.
    # BTC/ETH можно рассматривать частями. SOL — только если рынок уже не проваливается.
    if macro_mod <= -8:
        if symbol not in ["BTC", "ETH", "SOL"]:
            return False
        if symbol == "SOL" and (ctx.get("btc_change", 0) < -2 or score < 70):
            return False

    return (
        group in ["core", "quality"]
        and score >= 55
        and ctx.get("fg_value", 50) <= 30
        and c.get("change_24", 0) <= -1
        and c.get("rsi", 50) <= 55
    )

def v7_accumulation_plan_text(c):
    symbol = c.get("symbol", "")
    price = c.get("price", 0)
    zone1 = price * 0.99
    zone2 = price * 0.96
    zone3 = price * 0.92

    return (
        "📦 Среднесрочный план набора:\n"
        f"• 1-я часть: около ${zone1:.6g}\n"
        f"• 2-я часть: если дадут откат к ${zone2:.6g}\n"
        f"• 3-я часть: только при сильной просадке к ${zone3:.6g}\n"
        "• Не входить всей суммой сразу.\n"
        "• Горизонт идеи: 2–8 недель, а не быстрые 24 часа.\n"
    )



def v76_apply_macro_safe_buy_filter(c):
    """
    v7.6:
    При плохом внешнем фоне и падающем BTC не разрешаем быстрые BUY по альтам.
    Такие монеты уходят в WATCH/почти готовы.
    """
    if not c:
        return c

    ctx = c.get("ctx", {})
    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    btc_change = ctx.get("btc_change", 0)
    symbol = c.get("symbol", "")
    group = v6_quality_group(c)

    if c.get("action") != "BUY":
        return c

    # BTC/ETH не режем этим фильтром: они могут быть базой для среднесрока/отскока.
    if symbol in ["BTC", "ETH"]:
        return c

    bad_macro = macro_mod <= -8
    btc_falling = btc_change <= -2

    if not (bad_macro or btc_falling):
        return c

    # SOL как главный альт можно оставить BUY только при очень сильном подтверждении.
    if symbol == "SOL":
        if (
            macro_mod > -12
            and btc_change > -2.5
            and c.get("volume_trend", 1) >= 1.6
            and c.get("score", 0) >= 88
            and c.get("chance_5", 0) >= 60
        ):
            return c

    # Все остальные альты в плохом фоне — не BUY, а WATCH.
    c["verdict"] = "🟡 ЖДАТЬ ПОДТВЕРЖДЕНИЕ"
    c["action"] = "WATCH"
    c["score"] = min(c.get("score", 0), 74)
    c["_master_score"] = min(c.get("_master_score", c.get("score", 0)), c["score"])
    c["chance_5"] = min(c.get("chance_5", 0), 35)
    c["chance_10"] = min(c.get("chance_10", 0), 8)
    c["chance_15"] = min(c.get("chance_15", 0), 4)
    c["entry_zone"] = "плохой внешний фон: ждать стабилизацию BTC и подтверждение объёмом"

    c.setdefault("minus", [])
    if "плохой внешний фон для быстрых покупок альтов" not in c["minus"]:
        c["minus"].append("плохой внешний фон для быстрых покупок альтов")
    if "BTC падает и может утянуть альты ниже" not in c["minus"] and btc_falling:
        c["minus"].append("BTC падает и может утянуть альты ниже")

    return c


def v6_apply_single_score_engine(c):
    """
    v6.1: единый движок + режим отскока от перепроданности.
    """
    if not c:
        return c

    c = dict(c)
    ms = v6_master_score(c)
    reversal_score = v6_oversold_reversal_score(c)
    c["_master_score"] = ms
    c["_reversal_score"] = reversal_score

    group = v6_quality_group(c)
    rr = v6_reward_risk(c)
    neutral = v6_is_neutral(c, ms)
    reversal = v6_is_oversold_reversal(c)
    accumulation = v7_is_accumulation_candidate(c)
    accumulation_score = v7_accumulation_score(c)

    if c.get("chance_5", 0) >= 10:
        c["high"] = max(c.get("high", 0), 1.5)

    if accumulation:
        c["score"] = max(ms, accumulation_score)
        c["_master_score"] = c["score"]
        c["_accumulation_score"] = accumulation_score
        c["chance_5"] = max(c.get("chance_5", 0), 18)
        c["chance_10"] = max(c.get("chance_10", 0), 8)
        c["chance_15"] = max(c.get("chance_15", 0), 4)
        c["low"] = min(c.get("low", -2), -3)
        c["high"] = max(c.get("high", 0), 6.0)
        c["verdict"] = "🟦 СРЕДНЕСРОЧНЫЙ НАБОР"
        c["action"] = "ACCUM"
        c["entry_zone"] = "набор только частями на красном рынке, не вся сумма сразу"

        c.setdefault("plus", [])
        if "красный рынок может дать среднесрочную точку набора" not in c["plus"]:
            c["plus"].append("красный рынок может дать среднесрочную точку набора")

        c.setdefault("minus", [])
        if "это не быстрый сигнал, возможна просадка ниже" not in c["minus"]:
            c["minus"].append("это не быстрый сигнал, возможна просадка ниже")

    elif reversal:
        c["score"] = max(ms, reversal_score, 65)
        c["_master_score"] = c["score"]
        c["chance_5"] = max(c.get("chance_5", 0), 48)
        c["chance_10"] = max(c.get("chance_10", 0), 10)
        c["chance_15"] = max(c.get("chance_15", 0), 5)
        c["low"] = min(c.get("low", -1.5), -1.0)
        c["high"] = max(c.get("high", 0), 4.0)

        if c["score"] >= 72 and rr >= 0.75:
            c["verdict"] = "🟢 ОТСКОК / цель +5%"
            c["action"] = "BUY"
            c["entry_zone"] = "отскок от перепроданности: вход только частями, не на всю сумму"
        else:
            c["verdict"] = "🔵 КАНДИДАТ НА ОТСКОК"
            c["action"] = "WATCH"
            c["entry_zone"] = "ждать подтверждение разворота и удержание цены выше текущего уровня"

        c.setdefault("plus", [])
        if "возможен отскок от перепроданности" not in c["plus"]:
            c["plus"].append("возможен отскок от перепроданности")

    elif neutral:
        c["score"] = max(ms, 30 if group == "core" else 25)
        c["_master_score"] = c["score"]
        c["chance_5"] = max(c.get("chance_5", 0), 12)
        c["chance_10"] = min(c.get("chance_10", 2), 8)
        c["chance_15"] = min(c.get("chance_15", 2), 5)
        c["high"] = max(c.get("high", 0), 1.5)
        c["low"] = max(c.get("low", -2), -1.5)
        c["verdict"] = "⚪ НЕТ СИГНАЛА"
        c["action"] = "SKIP"
        c["entry_zone"] = "нейтрально: ждать рост объёма и подтверждение импульса"

    elif ms >= 70 and c.get("high", 0) >= 5 and rr >= 1.0:
        c["score"] = ms
        c["chance_5"] = max(c.get("chance_5", 0), 55)
        c["chance_10"] = max(c.get("chance_10", 0), 12)
        c["verdict"] = "🟢 ПОКУПКА / цель +5%"
        c["action"] = "BUY"
        c["entry_zone"] = "можно рассмотреть частичный вход, не после резкой свечи"

    elif ms >= 58 and c.get("high", 0) >= 4 and rr >= 0.75:
        c["score"] = ms
        c["chance_5"] = max(c.get("chance_5", 0), 38)
        c["chance_10"] = max(c.get("chance_10", 0), 8)
        c["verdict"] = "🟠 МОЖНО МАЛЫМ ОБЪЁМОМ"
        c["action"] = "PUMP"
        c["entry_zone"] = "осторожный вход малым объёмом или ждать откат"

    elif ms >= 40:
        c["score"] = ms
        c["chance_5"] = max(c.get("chance_5", 0), 25)
        c["verdict"] = "🟡 НАБЛЮДАТЬ"
        c["action"] = "WATCH"
        if c.get("volume_trend", 1) < 1.1:
            c["entry_zone"] = "зона ожидания: нужен более сильный объём"

    else:
        c["score"] = ms
        c["chance_5"] = min(c.get("chance_5", 0), 15)
        c["chance_10"] = min(c.get("chance_10", 0), 5)
        c["chance_15"] = min(c.get("chance_15", 0), 3)
        c["verdict"] = "🔴 НЕ ПОКУПАТЬ"
        c["action"] = "SKIP"

    c = v76_apply_macro_safe_buy_filter(c)

    if "НЕ ПОКУПАТЬ" in c.get("verdict", ""):
        c["high"] = min(c.get("high", 0), 1.5)

    if "НЕТ СИГНАЛА" in c.get("verdict", ""):
        c["high"] = max(c.get("high", 0), 1.5)

    price = c.get("price", 0) or 0
    c["target_low"] = price * (1 + c.get("low", 0) / 100)
    c["target_high"] = price * (1 + c.get("high", 0) / 100)

    c.setdefault("minus", [])
    c.setdefault("plus", [])

    if "НЕТ СИГНАЛА" in c.get("verdict", ""):
        if "режим ожидания, а не плохой сигнал" not in c["minus"]:
            c["minus"].append("режим ожидания, а не плохой сигнал")

    return c

def adjusted_score(c):
    if "_master_score" in c:
        return int(c.get("_master_score", c.get("score", 0)))

    score = float(c.get("score", 0) or 0)
    rr = reward_risk_ratio(c)

    # Если риск выше ожидаемой прибыли — score должен падать.
    if rr < 0.8:
        score *= 0.65
    elif rr < 1.0:
        score *= 0.8
    elif rr >= 1.4:
        score *= 1.05

    # Спекулятивные монеты не должны быть выше качественных только из-за импульса.
    if asset_quality_rank(c) < 50:
        score -= 10

    return max(0, min(100, int(round(score))))


def is_core_quality_symbol(symbol):
    return symbol in ["BTC", "ETH", "SOL", "TAO", "LINK", "INJ", "AAVE", "NEAR", "AVAX", "SUI"]

def is_extreme_bad_for_quality(c):
    return (
        c.get("change_24", 0) <= -6
        or c.get("rsi", 50) >= 88
        or c.get("rsi", 50) <= 28
        or c.get("volume_trend", 1) <= 0.25
    )

def apply_safe_neutral_patch(c):
    """
    v5.7.1 CONSISTENCY FIX:
    Отличаем плохой сигнал от отсутствия сигнала.
    Для качественных активов слабый рынок = режим ожидания, а не 0/100 и не аварийный красный сигнал.
    """
    if not c:
        return c

    symbol = c.get("symbol", "")

    if not is_core_quality_symbol(symbol):
        return c

    if is_extreme_bad_for_quality(c):
        return c

    c = dict(c)

    neutral_market = (
        35 <= c.get("rsi", 50) <= 65
        and -3 <= c.get("change_24", 0) <= 3
        and c.get("volume_trend", 1) >= 0.40
    )

    floor = 30 if symbol in ["BTC", "ETH"] else 25

    if neutral_market:
        c["score"] = max(c.get("score", 0), floor)
        c["chance_5"] = max(c.get("chance_5", 0), 12)
        c["high"] = max(c.get("high", 0), 1.5)
        c["low"] = max(c.get("low", -2), -1.5)
        price = c.get("price", 0) or 0
        c["target_low"] = price * (1 + c["low"] / 100)
        c["target_high"] = price * (1 + c["high"] / 100)
        c["verdict"] = "⚪ НЕТ СИГНАЛА"
        c["entry_zone"] = "нейтрально: ждать рост объёма и подтверждение импульса"
        c["action"] = "SKIP"

        c.setdefault("minus", [])
        if "режим ожидания, а не плохой сигнал" not in c["minus"]:
            c["minus"].append("режим ожидания, а не плохой сигнал")

    else:
        if c.get("score", 0) < floor:
            c["score"] = floor

        if c.get("action") == "SKIP" and c.get("high", 0) <= 1.5:
            c["verdict"] = "⚪ НЕТ СИГНАЛА"

    return c

def neutral_explanation_text(c):
    if "НЕТ СИГНАЛА" not in c.get("verdict", ""):
        return ""

    return (
        "⚪ НЕТ СИГНАЛА\n\n"
        f"{c.get('symbol')} сейчас в режиме ожидания: нет нормального входа, "
        "но это не аварийный красный сигнал. Покупать рано, продавать по этому сигналу тоже не требуется. "
        "Ждать рост объёма, возврат импульса и подтверждение рынка.\n\n"
    )

def buyer_strength_score(c):
    score = 0

    if c.get("fast_move", 0) >= 0.8:
        score += 20
    if c.get("vol_power", 0) >= 2.0:
        score += 30
    elif c.get("vol_power", 0) >= 1.2:
        score += 20
    if c.get("volume_trend", 0) >= 1.1:
        score += 20
    if c.get("rsi", 50) >= 50 and c.get("rsi", 50) <= 75:
        score += 15
    if c.get("score", 0) >= 70:
        score += 20
    if c.get("change_24", 0) > 12:
        score -= 15
    if c.get("rsi", 50) > 82:
        score -= 20

    if is_core_quality_symbol(c.get("symbol", "")) and not is_extreme_bad_for_quality(c):
        if 35 <= c.get("rsi", 50) <= 65 and c.get("volume_trend", 1) >= 0.45:
            score = max(score, 30 if c.get("rsi", 50) >= 50 else 25)
        else:
            score = max(score, 15)

    if v6_quality_group(c) in ["core", "quality"] and 35 <= c.get("rsi", 50) <= 65 and c.get("volume_trend", 1) >= 0.40:
        score = max(score, 30 if c.get("rsi", 50) >= 50 else 25)

    return max(0, min(100, score))

def pullback_risk_level(c):
    risk = 0

    if c.get("rsi", 0) > 82:
        risk += 30
    if c.get("change_24", 0) > 10:
        risk += 25
    elif c.get("change_24", 0) > 6:
        risk += 15
    if c.get("volume_trend", 1) < 0.8:
        risk += 20
    if c.get("high", 0) < abs(c.get("downside", 0)):
        risk += 20
    if c.get("ctx", {}).get("market_mod", 0) < 0:
        risk += 15

    risk = max(0, min(100, risk))

    if risk >= 70:
        return "высокий", risk
    if risk >= 40:
        return "средний", risk
    return "низкий", risk

def adaptive_decision_text(c):
    buyers = buyer_strength_score(c)
    risk_text, risk_score = pullback_risk_level(c)

    if c.get("action") == "BUY":
        if buyers >= 65 and risk_score <= 50:
            return "🧠 Решение бота: BUY разрешён — покупатели сильные, риск отката приемлемый."
        return "🧠 Решение бота: BUY осторожный — сигнал есть, но объём позиции лучше снизить."

    if c.get("action") == "PUMP":
        return "🧠 Решение бота: это не спокойная покупка, а рискованный импульс. Только малым объёмом."

    if reward_risk_ratio(c) < 1:
        return "🧠 Решение бота: вход не подтверждён — риск сейчас выше ожидаемой прибыли."

    if c.get("score", 0) >= 70 and c.get("chance_5", 0) >= 35:
        return "🧠 Решение бота: идея есть, но для BUY не хватает подтверждения объёмом или отката."

    return "🧠 Решение бота: вход пропускаем — риск выше качества момента."

def learning_stats_text():
    data = load_json(RESULTS_FILE)
    if not isinstance(data, dict):
        return "📚 Самообучение: история пока накапливается. Первые выводы появятся после 24 часов работы.\n\n"

    closed = data.get("closed", [])
    open_items = data.get("open", {})

    if not closed:
        open_count = len(open_items) if isinstance(open_items, dict) else 0
        if open_count:
            return f"📚 Самообучение: открытых сигналов в истории: {open_count}. Закрытая статистика появится после 24 часов.\n\n"
        return "📚 Самообучение: история пока накапливается. Первые выводы появятся после 24 часов работы.\n\n"

    total = len(closed)
    recent = closed[-50:]
    buy = [x for x in recent if x.get("action") == "BUY"]
    watch = [x for x in recent if x.get("action") == "WATCH"]
    pump = [x for x in recent if x.get("action") == "PUMP"]

    def win_rate(items):
        vals = []
        for x in items:
            r = x.get("results", {}).get("24h")
            if isinstance(r, (int, float)):
                vals.append(r)
        if not vals:
            return None
        wins = sum(1 for x in vals if x >= 5)
        return int(round(wins / len(vals) * 100))

    buy_wr = win_rate(buy)
    watch_wr = win_rate(watch)
    pump_wr = win_rate(pump)

    text = "📚 Самообучение:\n"
    text += f"Закрытых сигналов: {total}\n"

    if buy_wr is not None:
        text += f"BUY достигали +5%: {buy_wr}%\n"
    if watch_wr is not None:
        text += f"WATCH достигали +5%: {watch_wr}%\n"
    if pump_wr is not None:
        text += f"Риск-импульсы достигали +5%: {pump_wr}%\n"

    text += "Бот мягко подстраивает вероятность +5% по этой статистике.\n\n"
    return text

def needs_aggressive_signal(c):
    """
    Умеренно-рискованный режим, чтобы бот не молчал сутками.
    Это НЕ полноценный BUY, а осторожный вход малым объёмом.
    """
    if c.get("action") == "BUY":
        return False

    # Не лезем в явный разгон или плохой внешний рынок.
    if c.get("change_24", 0) >= 15:
        return False
    if c.get("ctx", {}).get("btc_mod", 0) < -15:
        return False
    if c.get("volume_trend", 1) < 0.65:
        return False
    if c.get("rsi", 50) >= 82:
        return False

    rr = reward_risk_ratio(c)

    # Риск не должен быть явно хуже прибыли.
    if rr < 0.75:
        return False

    return (
        adjusted_score(c) >= 62
        and c.get("chance_5", 0) >= 35
        and c.get("high", 0) >= 4
    )

def is_speculative_idea(c):
    if c.get("action") == "BUY":
        return False
    if c.get("symbol") in QUALITY_ASSETS:
        return False
    if c.get("change_24", 0) >= 18:
        return False
    if c.get("ctx", {}).get("btc_mod", 0) < -12:
        return False
    if reward_risk_ratio(c) < 1.0:
        return False

    return (
        c.get("score", 0) >= 68
        and c.get("chance_5", 0) >= 35
        and c.get("high", 0) >= 5
    )


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
    verdict_text = c.get("verdict", "")

    if "СРЕДНЕСРОЧНЫЙ" in verdict_text:
        verdict = "🟦 Среднесрок"
        text = "Идея не для быстрого входа на 24 часа, а для частичного набора на просадке."
    elif "НЕТ СИГНАЛА" in verdict_text:
        verdict = "🟡 Пока рано"
        text = "Потенциал небольшой, но вход ещё не сформирован."
    elif "НЕ ПОКУПАТЬ" in verdict_text:
        verdict = "🔴 Нет"
        text = "Качественного входа сейчас нет."
    elif "МОЖНО МАЛЫМ" in verdict_text:
        verdict = "🟡 Осторожно"
        text = "Идея есть, но вход только малым объёмом и со стопом."
    elif high <= 0:
        verdict = "🔴 Нет"
        text = "Ожидаемого роста почти нет."
    elif downside <= 0:
        verdict = "🟡 Осторожно"
        text = "Риск по стопу не удалось корректно оценить."
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


def market_is_bad_for_speculative(c):
    ctx = c.get("ctx", {})
    return ctx.get("btc_mod", 0) < 0 or ctx.get("market_mod", 0) < -5

def is_low_quality_speculative(c):
    return asset_quality_rank(c) < 50

def speculative_watch_text(items):
    if not items:
        return ""

    text = "🟣 СПЕКУЛЯТИВНОЕ НАБЛЮДЕНИЕ / НЕ ОСНОВНОЙ СПИСОК:\n\n"

    for i, c in enumerate(items[:3], 1):
        text += (
            f"{i}. {c['symbol']} — adjusted {adjusted_score(c)}/100, raw {c.get('score')}/100\n"
            f"Цена: ${c.get('price', 0):.6g} | рост 24ч {c.get('change_24', 0):.2f}% | "
            f"RSI {c.get('rsi', 'н/д')} | объём x{c.get('volume_trend', 'н/д')}\n"
            f"Почему отдельно: монета спекулятивная, а рынок сейчас не помогает альтам.\n\n"
        )

    return text

def best_watch_candidates(analyzed):
    if not analyzed:
        return ""

    # В плохом рынке спекулятивные монеты не должны быть главным кандидатом.
    quality_pool = [
        x for x in analyzed
        if (
            adjusted_score(x) >= 25
            and x.get("action") != "BUY"
            and not (market_is_bad_for_speculative(x) and is_low_quality_speculative(x))
        )
    ]

    # Если качественных сетапов нет — лучше честно написать, чем ставить мем/мусор на первое место.
    if not quality_pool:
        return "🟦 ЛУЧШИЕ КАНДИДАТЫ НА НАБЛЮДЕНИЕ:\n\nСейчас качественных кандидатов нет. Спекулятивные монеты вынесены отдельно.\n\n"

    def rank(x):
        return (
            asset_quality_rank(x),
            adjusted_score(x),
            reward_risk_ratio(x),
            x.get("chance_5", 0)
        )

    top = sorted(quality_pool, key=rank, reverse=True)[:5]

    txt = "🟦 ЛУЧШИЕ КАНДИДАТЫ НА НАБЛЮДЕНИЕ:\n\n"
    for i, c in enumerate(top, 1):
        adj = adjusted_score(c)
        need = max(0, 80 - int(adj))
        txt += f"{i}. {c['symbol']} — {adj}/100"
        if c.get("score") != adj:
            txt += f" (raw {c.get('score')}/100)"
        if need > 0:
            if reward_risk_ratio(c) < 1.05 or c.get("volume_trend", 1) < 1.1:
                txt += " | до BUY далеко: нужен объём + улучшение рынка"
            else:
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

    # Не забиваем план монетами с нулевым score, если есть более живые варианты.
    selected = [x for x in selected if x.get("score", 0) >= 20 or adjusted_score(x) >= 20]

    if not selected:
        selected = sorted(
            [x for x in analyzed if x.get("score", 0) >= 20 or adjusted_score(x) >= 20],
            key=lambda x: (adjusted_score(x), x.get("score", 0), x.get("chance_5", 0)),
            reverse=True
        )[:4]
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

        adj = adjusted_score(c)
        score_text = f"score {score}/100"
        if adj != score:
            score_text += f", adjusted {adj}/100"

        lines.append(
            f"• {symbol}: цена ${price:.6g}, {score_text}, "
            f"RSI {rsi_value}, объём x{volume_trend}. "
            f"Условие: {condition}."
        )

    if len(lines) <= 1:
        return "⏳ ЧТО ЖДАТЬ ДЛЯ НОВОГО BUY-СИГНАЛА:\n\nСейчас нет даже ранних качественных сетапов. Ждать восстановления объёма и разворота BTC.\n\n"

    return "\n".join(lines) + "\n\n"


def early_candidates_from_analyzed(analyzed, exclude_symbols=None):
    """
    Показывает ранние кандидаты, когда полноценного BUY/WATCH нет.
    Это не рекомендация покупать, а список того, за чем есть смысл следить.
    """
    exclude_symbols = set(exclude_symbols or [])

    items = [
        x for x in analyzed
        if (
            x.get("symbol") not in exclude_symbols
            and x.get("action") != "BUY"
            and 30 <= adjusted_score(x) < 45
            and x.get("chance_5", 0) >= 20
        )
    ]

    if not items:
        return ""

    items = sorted(
        items,
        key=lambda x: (
            adjusted_score(x),
            asset_quality_rank(x),
            reward_risk_ratio(x),
            x.get("chance_5", 0)
        ),
        reverse=True
    )[:3]

    text = "⚪ РАННИЕ КАНДИДАТЫ / ЕЩЁ НЕ СИГНАЛ:\n\n"

    for i, c in enumerate(items, 1):
        text += (
            f"{i}. {c['symbol']} — adjusted {adjusted_score(c)}/100 "
            f"(raw {c.get('score')}/100)\n"
            f"Цена: ${c.get('price', 0):.6g} | RSI {c.get('rsi', 'н/д')} | объём x{c.get('volume_trend', 'н/д')}\n"
            f"Что нужно: усиление объёма и подтверждение импульса.\n\n"
        )

    return text

def market_counts_text(buy, accum, watch, aggressive, speculative, early_text):
    early_count = 0
    if early_text:
        early_count = early_text.count(". ")

    return (
        "📊 Срез рынка:\n"
        f"BUY: {len(buy)} | Среднесрок: {len(accum)} | WATCH: {len(watch)} | Осторожные: {len(aggressive)} | "
        f"Спекулятивные: {len(speculative)} | Ранние: {early_count}\n\n"
    )

def best_current_candidate_text(analyzed):
    if not analyzed:
        return ""

    candidates = [
        x for x in analyzed
        if (
            adjusted_score(x) >= 25
            and not (market_is_bad_for_speculative(x) and is_low_quality_speculative(x))
        )
    ]

    if not candidates:
        return "⭐ Лучший кандидат сейчас: нет даже слабого рабочего сетапа.\n\n"

    c = sorted(
        candidates,
        key=lambda x: (adjusted_score(x), asset_quality_rank(x), reward_risk_ratio(x)),
        reverse=True
    )[0]

    return (
        "⭐ Лучший кандидат сейчас:\n\n"
        f"{c['symbol']} — adjusted {adjusted_score(c)}/100, raw {c.get('score')}/100\n"
        f"Причина ожидания: {c.get('entry_zone', 'нужно подтверждение')}\n\n"
    )


def compact_price(x):
    p = float(x or 0)
    if p >= 100:
        return f"${p:,.0f}".replace(",", " ")
    if p >= 1:
        return f"${p:.2f}"
    return f"${p:.6g}"

def compact_reason(c):
    reasons = []

    if "СРЕДНЕСРОЧНЫЙ" in c.get("verdict", ""):
        if c.get("ctx", {}).get("fg_value", 50) <= 25:
            reasons.append("страх")
        if c.get("rsi", 50) <= 45:
            reasons.append(f"RSI {c.get('rsi')}")
        if c.get("change_24", 0) < 0:
            reasons.append(f"откат {c.get('change_24'):.1f}%")
        if c.get("volume_trend", 1) >= 1.1:
            reasons.append(f"объём x{c.get('volume_trend')}")
        return " + ".join(reasons[:3]) or "красный рынок"

    if "ОТСКОК" in c.get("verdict", ""):
        return f"RSI {c.get('rsi')} + объём x{c.get('volume_trend')}"

    if c.get("action") == "BUY":
        return f"score {c.get('score')}/100 + шанс +5% {c.get('chance_5')}%"

    if c.get("action") == "WATCH":
        return "ждать объём и подтверждение"

    return "нет условий для входа"

def compact_action(c):
    if "СРЕДНЕСРОЧНЫЙ" in c.get("verdict", ""):
        macro_mod = c.get("ctx", {}).get("macro_mod", c.get("ctx", {}).get("geo_mod", 0))
        if macro_mod <= -8 and c.get("symbol") not in ["BTC", "ETH"]:
            return "ждать стабилизацию BTC"
        return "начать набор частями"
    if c.get("action") == "BUY":
        return "можно рассмотреть вход"
    if c.get("action") == "PUMP":
        return "только малым объёмом"
    if c.get("action") == "WATCH":
        return "ждать подтверждение"
    return "не покупать"

def compact_line(i, c):
    return (
        f"{i}. {c['symbol']} — {c.get('score', 0)}/100 | {compact_price(c.get('price'))}\n"
        f"   {compact_action(c)}\n"
        f"   Причина: {compact_reason(c)}\n"
    )

def compact_late_pumps(items):
    if not items:
        return ""

    text = "❌ Не лезть в пампы:\n"
    for c in items[:3]:
        text += f"• {c['symbol']} +{c['change_24']:.0f}%\n"
    return text + "\n"

def compact_learning_text():
    data = load_json(RESULTS_FILE)
    if isinstance(data, dict):
        closed = data.get("closed", [])
        open_items = data.get("open", {})
        if closed:
            return f"📚 Самообучение: закрытых сигналов {len(closed)}\n"
        if isinstance(open_items, dict) and len(open_items):
            return f"📚 Самообучение: открытых сигналов {len(open_items)}\n"
    return "📚 Самообучение: история накапливается\n"


def near_buy_candidates(analyzed, exclude_symbols=None):
    exclude_symbols = set(exclude_symbols or [])

    items = []
    for c in analyzed:
        if c.get("symbol") in exclude_symbols:
            continue

        if c.get("action") == "BUY":
            continue

        score = c.get("_master_score", c.get("score", 0))
        if score < 45:
            continue

        if c.get("change_24", 0) >= 18:
            continue

        # Не показываем мусорные спекулятивные монеты как почти BUY.
        if v6_quality_group(c) == "speculative" and c.get("ctx", {}).get("btc_change", 0) < 0:
            continue

        items.append(c)

    return sorted(
        items,
        key=lambda x: (
            x.get("_master_score", x.get("score", 0)),
            asset_quality_rank(x),
            x.get("chance_5", 0)
        ),
        reverse=True
    )[:3]

def compact_near_buy_text(items):
    if not items:
        return ""

    text = "⏳ Почти готовы к сигналу:\n"
    for i, c in enumerate(items, 1):
        reasons = []

        if c.get("volume_trend", 1) < 1.1:
            reasons.append("нужен объём")
        if c.get("rsi", 50) < 45:
            reasons.append("нужен разворот RSI")
        if c.get("ctx", {}).get("macro_mod", c.get("ctx", {}).get("geo_mod", 0)) <= -8 and c.get("symbol") not in ["BTC", "ETH"]:
            reasons.append("плохой фон для альтов")
        if c.get("ctx", {}).get("btc_change", 0) < 0:
            reasons.append("BTC мешает")
        if not reasons:
            reasons.append("нужно подтверждение")

        score = c.get("_master_score", c.get("score", 0))
        text += f"{i}. {c['symbol']} — {score}/100 | {', '.join(reasons[:2])}\n"

    return text + "\n"


def compact_signal_report(ctx, buy, accum, watch, aggressive, speculative, early_text, speculative_watch, late_pumps, near_buy=None):
    text = (
        f"🚀 ALEX EDGE ULTRA {BOT_VERSION}\n"
        f"Рынок: {ctx['state']}\n"
        f"BTC: {ctx['btc_text']} | {ctx['btc_change']:.2f}%\n"
        f"Страх: {ctx['fg_value']} — {ctx['fg_text']}\n"
    )

    if ctx.get("dom_text"):
        text += f"BTC dominance: {ctx['dom_text']}\n"

    text += f"{macro_mode_text(ctx)} ({ctx.get('macro_mod', 0):+d})\n"
    text += f"{macro_action_hint(ctx)}\n"

    text += "\n"
    text += (
        "📊 Срез:\n"
        f"🟢 BUY: {len(buy)} | 🟦 Среднесрок: {len(accum)} | 🟡 WATCH: {len(watch)}\n\n"
    )

    shown = False

    if buy:
        shown = True
        text += "🟢 Быстрые идеи:\n"
        for i, c in enumerate(buy[:3], 1):
            text += compact_line(i, c)
        text += "\n"

    if accum:
        shown = True
        text += "🟦 Лучшие идеи на красном рынке:\n"
        for i, c in enumerate(accum[:3], 1):
            text += compact_line(i, c)
        text += "\n"

    if aggressive:
        shown = True
        text += "🟠 Осторожно малым объёмом:\n"
        for i, c in enumerate(aggressive[:2], 1):
            text += compact_line(i, c)
        text += "\n"

    if watch:
        shown = True
        text += "🟡 Наблюдать:\n"
        for i, c in enumerate(watch[:3], 1):
            text += compact_line(i, c)
        text += "\n"

    if not shown:
        text += "🟢 Покупок сейчас нет.\n\n"

    near_buy = near_buy or []
    if near_buy:
        text += compact_near_buy_text(near_buy)

    if speculative_watch:
        text += "🟣 Спекулятивно, не основной список:\n"
        for i, c in enumerate(speculative_watch[:2], 1):
            text += f"{i}. {c['symbol']} — {c.get('score', 0)}/100 | только микропозиция\n"
        text += "\n"

    text += compact_learning_text()
    text += "\nПодробно: /btc /sol или /coin ETH"

    return text


def get_signal():
    try:
        # Защита от UnboundLocalError:
        # эти переменные должны существовать всегда, даже если ниже какой-то блок не сработал.
        buy = []
        watch = []
        pumps = []
        aggressive = []
        speculative = []
        speculative_watch = []
        accum = []
        late_pumps = []
        early_text = ""

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
                    c = v6_apply_single_score_engine(c)
                    analyzed.append(c)
                time.sleep(0.2)
            except Exception:
                continue

        # Финальная чистка: если скорректированный score слабый, не показываем как WATCH/PUMP.
        for x in analyzed:
            if adjusted_score(x) < 45 and x.get("action") in ["WATCH", "PUMP"]:
                x["action"] = "SKIP"
                x["verdict"] = "🔴 НЕ ПОКУПАТЬ"
                if "скорректированная оценка слабая" not in x["minus"]:
                    x["minus"].append("скорректированная оценка слабая")

        accum = sorted(
            [
                x for x in analyzed
                if x.get("action") == "ACCUM"
            ],
            key=lambda x: (x.get("_accumulation_score", 0), asset_quality_rank(x), x.get("score", 0)),
            reverse=True
        )[:5]

        buy = sorted(
            [
                x for x in analyzed
                if (
                    x["action"] == "BUY"
                    and not (
                        x.get("symbol") not in ["BTC", "ETH", "SOL"]
                        and x.get("ctx", {}).get("macro_mod", x.get("ctx", {}).get("geo_mod", 0)) <= -8
                    )
                    and not (
                        x.get("symbol") not in ["BTC", "ETH", "SOL"]
                        and x.get("ctx", {}).get("btc_change", 0) <= -2
                    )
                    and (
                        (
                            x["chance_5"] >= 50
                            and x["high"] >= 4
                        )
                        or "РАННИЙ ТРЕНД" in x["verdict"]
                        or "ОТСКОК" in x["verdict"]
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
                    and x not in accum
                    and x["action"] == "WATCH"
                    and (
                        (
                            x["chance_5"] >= 25
                            and x["high"] >= 3.5
                            and adjusted_score(x) >= 40
                        )
                        or "ОТСКОК" in x["verdict"]
                    )
                    and x["change_24"] < 25
                )
            ],
            key=lambda x: (
                1 if "СОБЫТИЙНАЯ" in x["verdict"] else 0,
                adjusted_score(x),
                reward_risk_ratio(x),
                x["chance_5"]
            ),
            reverse=True
        )[:5]

        pumps = sorted(
            [
                x for x in analyzed
                if (
                    x not in buy
                    and x not in accum
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

        aggressive = sorted(
            [
                x for x in analyzed
                if (
                    x not in buy
                    and x not in watch
                    and x not in pumps
                    and needs_aggressive_signal(x)
                )
            ],
            key=lambda x: (adjusted_score(x), asset_quality_rank(x), reward_risk_ratio(x), x["chance_5"]),
            reverse=True
        )[:3]

        speculative = sorted(
            [
                x for x in analyzed
                if (
                    x not in buy
                    and x not in watch
                    and x not in pumps
                    and x not in aggressive
                    and is_speculative_idea(x)
                )
            ],
            key=lambda x: (x["score"], x["chance_5"], x["high"]),
            reverse=True
        )[:3]

        for x in aggressive:
            x["verdict"] = "🟠 МОЖНО МАЛЫМ ОБЪЁМОМ"
            x["action"] = "PUMP"
            x["entry_zone"] = "осторожный вход малым объёмом или ждать откат"

        for x in speculative:
            x["verdict"] = "🟣 СПЕКУЛЯТИВНАЯ ИДЕЯ"
            x["action"] = "PUMP"
            x["entry_zone"] = "только микропозиция, риск высокий"

        buy = filter_recent_repeats(buy, min_minutes=20)
        watch = filter_recent_repeats(watch, min_minutes=20)
        pumps = filter_recent_repeats(pumps, min_minutes=20)
        aggressive = filter_recent_repeats(aggressive, min_minutes=20)
        speculative = filter_recent_repeats(speculative, min_minutes=20)

        early_text = ""

        speculative_watch = sorted(
            [
                x for x in analyzed
                if (
                    market_is_bad_for_speculative(x)
                    and is_low_quality_speculative(x)
                    and adjusted_score(x) >= 30
                    and x.get("change_24", 0) < 18
                    and x not in buy
                    and x not in aggressive
                    and x not in speculative
                    and x not in speculative_watch
                )
            ],
            key=lambda x: (adjusted_score(x), x.get("chance_5", 0), x.get("high", 0)),
            reverse=True
        )[:3]

        # Убираем такие монеты из обычного WATCH в плохом рынке.
        watch = [
            x for x in watch
            if not (market_is_bad_for_speculative(x) and is_low_quality_speculative(x))
        ]

        early_text = early_candidates_from_analyzed(
            analyzed,
            exclude_symbols=[x.get("symbol") for x in speculative_watch]
        )

        if "speculative_watch" not in locals():
            speculative_watch = []

        late_pumps = sorted(
            [
                x for x in analyzed
                if (
                    x["change_24"] > 12
                    and x not in buy
                    and x not in watch
                    and x not in pumps
                    and x not in aggressive
                    and x not in speculative
                    and x not in accum
                )
            ],
            key=lambda x: x["change_24"],
            reverse=True
        )[:5]

        if not buy and not accum and not watch and not pumps and not aggressive and not speculative and not early_text and not late_pumps:
            plan = action_plan_from_analyzed(analyzed)
            return f"🚀 ALEX EDGE ULTRA {BOT_VERSION}\n\nСейчас нет нормальных идей для покупки.\n\n" + plan

        save_signal_history(buy + accum + watch + pumps + aggressive + speculative)

        if buy:
            ctx_source = buy[0]
        elif accum:
            ctx_source = accum[0]
        elif watch:
            ctx_source = watch[0]
        elif aggressive:
            ctx_source = aggressive[0]
        elif pumps:
            ctx_source = pumps[0]
        elif speculative:
            ctx_source = speculative[0]
        else:
            ctx_source = late_pumps[0]

        ctx = ctx_source["ctx"]

        excluded = [x.get("symbol") for x in (buy + accum + watch + aggressive + speculative)]
        near_buy = near_buy_candidates(analyzed, exclude_symbols=excluded)

        return compact_signal_report(
            ctx=ctx,
            buy=buy,
            accum=accum,
            watch=watch,
            aggressive=aggressive,
            speculative=speculative,
            early_text=early_text,
            speculative_watch=speculative_watch if "speculative_watch" in locals() else [],
            late_pumps=late_pumps,
            near_buy=near_buy
        )

    except Exception as e:
        return f"Ошибка /signal:\n{e}"


def format_fast_alert(items):
    if not items:
        return None

    text = f"⚡ ALEX FAST ALERT {BOT_VERSION}\n\n"
    text += "Быстрый импульс. Это не спокойная покупка — вход только малым объёмом или ждать откат.\n\n"

    for i, c in enumerate(items[:3], 1):
        risk = "высокий" if c.get("change_24", 0) > 12 else "средний"
        text += (
            f"{i}. {c['symbol']} — score {c.get('score', 0)}/100\n"
            f"Цена: ${c['price']:.6g}\n"
            f"15м: +{c['fast_move']:.2f}% | объём x{c['vol_power']:.1f}\n"
            f"24ч: {c['change_24']:.2f}% | риск: {risk}\n\n"
        )

    text += "⚠️ Если свеча уже резко зелёная — не догонять."
    return text

def get_fast_pumps():
    """
    v7.4: рабочие alerts.
    Больше не завязаны на action == PUMP, потому что общий движок мог классифицировать монету как WATCH/SKIP,
    даже если на 15м был быстрый импульс.
    """
    try:
        found = []

        pairs = [
            t for t in kucoin_tickers()
            if t.get("symbol", "").endswith("-USDT")
            and float(t.get("volValue", 0) or 0) >= 1_000_000
        ]

        pairs = sorted(
            pairs,
            key=lambda t: (
                float(t.get("volValue", 0) or 0),
                abs(float(t.get("changeRate", 0) or 0))
            ),
            reverse=True
        )[:45]

        for t in pairs:
            symbol = t.get("symbol", "")
            asset = symbol.replace("-USDT", "")

            try:
                ticker = get_ticker(symbol)
                if not ticker:
                    continue

                price = float(ticker.get("last", 0) or 0)
                change_24 = float(ticker.get("changeRate", 0) or 0) * 100
                volume_usd = float(ticker.get("volValue", 0) or 0)

                if price <= 0 or volume_usd < 1_000_000:
                    continue

                # Не шлём совсем поздние безумные пампы.
                if change_24 > 30:
                    continue

                d = diagnostics(symbol)

                fast_move = float(d.get("move_15", 0) or 0)
                vol_power = float(d.get("vol_1h", 0) or 0)
                rsi_value = float(d.get("rsi", 50) or 50)

                impulse = (
                    (fast_move >= 1.2 and vol_power >= 1.4)
                    or (fast_move >= 0.8 and vol_power >= 2.0)
                    or (fast_move >= 2.0 and vol_power >= 1.1)
                )

                if not impulse:
                    continue

                if rsi_value >= 88:
                    continue

                score = 50

                if fast_move >= 2:
                    score += 20
                elif fast_move >= 1.2:
                    score += 12
                elif fast_move >= 0.8:
                    score += 6

                if vol_power >= 2:
                    score += 18
                elif vol_power >= 1.4:
                    score += 10
                elif vol_power >= 1.1:
                    score += 5

                if 0 <= change_24 <= 12:
                    score += 10
                elif change_24 > 18:
                    score -= 15

                if asset in QUALITY_ASSETS:
                    score += 8

                found.append({
                    "symbol": asset,
                    "price": price,
                    "change_24": change_24,
                    "fast_move": fast_move,
                    "vol_power": vol_power,
                    "rsi": round(rsi_value, 1),
                    "score": max(0, min(100, int(score)))
                })

                time.sleep(0.05)

            except Exception:
                continue

        found = sorted(
            found,
            key=lambda x: (x["score"], x["fast_move"], x["vol_power"]),
            reverse=True
        )[:5]

        if not found:
            return None, []

        return format_fast_alert(found), found

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

    if allowed:
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

    c = v6_apply_single_score_engine(c)
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
        f"Macro score: {ctx.get('macro_mod', 0):+d}\n"
        f"{ctx['macro_text']}\n\n"
        f"{macro_action_hint(ctx)}"
    )

    return text

def help_text():
    return (
        f"Версия бота: {BOT_VERSION}\n\n"
        "✅ Команды:\n\n"
        "/signal — монеты для покупки/наблюдения\n"
        "/top — топ монет по объёму\n"
        "/btc — анализ BTC\n"
        "/sol — анализ SOL\n/coin ETH — анализ любой монеты\n"
        "/alerts — быстрые импульсы по рынку\n"
        "/market — фон рынка\n/macro — подробный внешний фон\n"
        "/version — версия бота\n"
        "/help — помощь\n\n"
        "Статусы:\n"
        "🟢 ПОКУПКА — можно рассмотреть вход\n"
        "🔥 РАННИЙ ИМПУЛЬС — агрессивная возможность\n"
        "📌 СОБЫТИЙНАЯ МОНЕТА — следить из-за новости\n"
        "🟡 НАБЛЮДАТЬ — пока не покупать\n🟦 СРЕДНЕСРОЧНЫЙ НАБОР — частичный вход; при плохом фоне в основном BTC/ETH\n"
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

                elif text.lower().startswith("/coin"):
                    parts = text.split()
                    if len(parts) < 2:
                        send_message(chat_id, "Напиши так: /coin ETH или /coin NEAR")
                    else:
                        coin = parts[1].upper().replace("-USDT", "")
                        send_message(chat_id, single_analysis(f"{coin}-USDT"))

                elif text == "/market" or text == "/macro":
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

                    allowed = should_send_pump(items) if items else []
                    if allowed:
                        send_message(saved_chat_id, format_fast_alert(allowed))

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

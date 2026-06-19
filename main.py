from flask import Flask
from threading import Thread
import os, time, json, requests, statistics, re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

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
BOT_VERSION = "v10.4 ALERTS VISIBILITY FIX"

CHAT_ID_FILE = "chat_id.txt"
HISTORY_FILE = "signal_history.json"
PUMP_FILE = "pump_history.json"
RESULTS_FILE = "signal_results.json"

SIGNAL_HOURS = [9, 15, 21]
MARKET_HOUR = 9
PUMP_MINUTES = [0]
MOSCOW_OFFSET_HOURS = 3

REPEAT_PUMP_AFTER = 4 * 60 * 60

QUALITY_ASSETS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "LINK",
    "GRAM", "DOGE", "NEAR", "TAO", "DOT", "LTC", "SUI", "APT",
    "ARB", "OP", "INJ", "SEI", "ATOM", "FIL", "TRX"
]

FORCE_ANALYZE_ASSETS = ["GRAM-USDT", "SOL-USDT", "TAO-USDT", "SUI-USDT", "ETH-USDT"]

EVENT_ASSETS = {
    "GRAM": {
        "title": "событийная монета GRAM / TON",
        "bonus": 14,
        "risk": "есть новостной катализатор, но возможен резкий слив после новости"
    }
}

_ticker_cache = {"time": 0, "data": []}
_news_cache = {"time": 0, "data": None}

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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

BUTTON_TO_COMMAND = {
    "📊 Сигнал": "/signal",
    "🔎 Монета": "/coin",
    "🟠 BTC": "/btc",
    "🟣 SOL": "/sol",
    "₿ BTC": "/btc",      # старая кнопка, оставлена как alias
    "◎ SOL": "/sol",      # старая кнопка, оставлена как alias
    "🌍 Рынок": "/market",
    "⚡ Alerts": "/alerts",
    "📚 Обучение": "/learning",
    "🏆 Топ": "/top",
    "📈 Топ": "/top",     # старая кнопка, оставлена как alias
    "⚙️ Версия": "/version",
    "❓ Помощь": "/help",
}

POPULAR_COINS = [
    "BTC", "ETH", "SOL",
    "SUI", "LINK", "GRAM",
    "BNB", "XRP", "ADA",
    "DOT", "TAO", "NEAR",
    "AVAX", "SEI", "INJ"
]

COIN_ALIASES = {
    # TON — название сети, на KuCoin тикер монеты теперь GRAM.
    "TON": "GRAM",
    "TONCOIN": "GRAM",
}

SEARCH_BUTTONS = {"🔎 Монета", "монета", "поиск монеты", "/coin"}
MANUAL_COIN_BUTTONS = {"✍️ Ввести вручную", "ввести вручную", "ручной ввод"}
BACK_BUTTONS = {"⬅️ Назад", "назад", "в меню"}

def normalize_button_text(text):
    text = (text or "").strip()
    return BUTTON_TO_COMMAND.get(text, text)

def normalize_coin_input(text):
    t = (text or "").strip().upper()
    t = t.replace("$", "")
    t = t.replace("/", "-")
    t = t.replace(" ", "")
    t = t.replace("_", "-")

    if t.endswith("-USDT"):
        t = t[:-5]
    elif t.endswith("USDT") and len(t) > 4:
        t = t[:-4]

    # Оставляем только буквы и цифры, чтобы ETH, SOL, SUI, 1INCH работали безопасно.
    t = re.sub(r"[^A-Z0-9]", "", t)
    return t

def resolve_coin_symbol(text):
    coin = normalize_coin_input(text)
    return COIN_ALIASES.get(coin, coin)

def coin_search_prompt():
    return (
        "🔎 Поиск монеты\n\n"
        "Выбери популярную монету кнопкой ниже или нажми ✍️ Ввести вручную.\n\n"
        "Можно также просто написать тикер сообщением: ETH, SUI, LINK, GRAM.\n"
        "Команду /coin ETH писать больше не обязательно."
    )

def keyboard():
    return {
        "keyboard": [
            ["📊 Сигнал", "🔎 Монета"],
            ["🟠 BTC", "🟣 SOL"],
            ["🌍 Рынок", "⚡ Alerts"],
            ["📚 Обучение", "🏆 Топ"],
            ["⚙️ Версия", "❓ Помощь"]
        ],
        "resize_keyboard": True
    }

def coin_keyboard():
    return {
        "keyboard": [
            ["BTC", "ETH", "SOL"],
            ["SUI", "LINK", "GRAM"],
            ["BNB", "XRP", "ADA"],
            ["DOT", "TAO", "NEAR"],
            ["AVAX", "SEI", "INJ"],
            ["✍️ Ввести вручную"],
            ["⬅️ Назад"]
        ],
        "resize_keyboard": True
    }

def send_message(chat_id, text, reply_markup=None):
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
            json={"chat_id": chat_id, "text": part, "reply_markup": reply_markup or keyboard()},
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



def clamp(value, low, high):
    return max(low, min(high, value))

def moscow_time_label():
    return (datetime.utcnow() + timedelta(hours=MOSCOW_OFFSET_HOURS)).strftime("%H:%M")

def fetch_google_news_items(query, hours=12, max_items=12, timeout=8):
    """
    Берём свежие заголовки из Google News RSS.
    Без API-ключей, подходит для Render.
    """
    try:
        url = "https://news.google.com/rss/search"
        params = {
            "q": f"{query} when:{hours}h",
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en"
        }

        xml_text = requests.get(url, params=params, timeout=timeout).text
        root = ET.fromstring(xml_text)

        items = []
        now = datetime.utcnow()

        for item in root.findall(".//item")[:max_items * 2]:
            title = (item.findtext("title") or "").strip()
            source = (item.findtext("source") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            link = (item.findtext("link") or "").strip()

            if not title:
                continue

            age_h = None
            if pub:
                try:
                    dt = parsedate_to_datetime(pub)
                    if dt.tzinfo:
                        dt = dt.astimezone().replace(tzinfo=None)
                    age_h = (now - dt).total_seconds() / 3600
                except Exception:
                    age_h = None

            if age_h is not None and age_h > hours:
                continue

            items.append({
                "title": title,
                "source": source,
                "link": link,
                "age_h": age_h,
                "text": f"{title} {source}".lower()
            })

            if len(items) >= max_items:
                break

        return items

    except Exception:
        return []


TRUSTED_NEWS_SOURCES = [
    "reuters", "associated press", "ap news", "bloomberg", "cnbc",
    "wall street journal", "wsj", "financial times", "ft.com",
    "coindesk", "cointelegraph", "the block", "decrypt",
    "federal reserve", "fomc", "sec.gov", "treasury"
]

WEAK_NEWS_SOURCES = [
    "intellectia", "benzinga", "investing.com", "fxstreet",
    "u.today", "ambcrypto", "be in crypto", "beincrypto",
    "cryptopolitan", "watcher guru", "coinpedia", "the crypto basic",
    "bitcoinist", "newsbtc", "daily hodl"
]

def source_weight(item):
    """
    v9.6:
    Не все источники одинаковые. Слабые агрегаторы/AI-сайты учитываем слабее,
    проверенные источники — сильнее.
    """
    source = (item.get("source") or "").lower()
    title = (item.get("title") or "").lower()
    text = f"{source} {title}"

    if any(x in text for x in TRUSTED_NEWS_SOURCES):
        return 1.2

    if any(x in text for x in WEAK_NEWS_SOURCES):
        return 0.45

    return 1.0

def text_has_any(text, words):
    return any(w in text for w in words)

def news_item_score(item, positive_words, risk_words, positive_override=None, risk_override=None):
    """
    Смотрим смысл конкретного заголовка.
    Если есть сильная позитивная фраза типа 'end war / ceasefire / reopen Hormuz',
    она перебивает отдельные опасные слова 'war / Hormuz'.
    """
    text = item.get("text", "")
    weight = source_weight(item)

    positive_override = positive_override or []
    risk_override = risk_override or []

    pos = 0
    risk = 0

    for word, points in positive_words.items():
        if word in text:
            pos += points

    for word, points in risk_words.items():
        if word in text:
            risk += points

    if text_has_any(text, positive_override):
        # Сильный смысловой позитив должен перебить слова war / Hormuz / Iran.
        pos += 10
        risk = min(risk, 2)

    if text_has_any(text, risk_override):
        risk += 10
        pos = min(pos, 2)

    return int(round((pos - risk) * weight)), int(round(pos * weight)), int(round(risk * weight))

def headline_word_score(items, words):
    """
    Старый интерфейс оставлен для совместимости.
    """
    score = 0

    for item in items:
        text = item.get("text", "")
        w = source_weight(item)

        for word, weight in words.items():
            if word in text:
                score += int(round(weight * w))
                break

    return score

def matched_headlines(items, words, limit=2, positive_override=None, risk_override=None):
    rows = []
    positive_override = positive_override or []
    risk_override = risk_override or []

    for item in items:
        text = item.get("text", "")
        source = (item.get("source") or "").strip()
        title = item.get("title", "").strip()
        age = item.get("age_h")
        w = source_weight(item)

        matched = False
        boost = 0

        if text_has_any(text, positive_override) or text_has_any(text, risk_override):
            matched = True
            boost = 10

        if not matched:
            for word, points in words.items():
                if word in text:
                    matched = True
                    boost = points
                    break

        if not matched:
            continue

        if source and source.lower() not in title.lower():
            title = f"{title} — {source}"

        if age is not None:
            title = f"{title} ({age:.0f}ч назад)"

        if w < 0.7:
            title = f"{title} [слабый источник]"

        rows.append((boost * w, title))

    rows = sorted(rows, key=lambda x: x[0], reverse=True)
    return [x[1] for x in rows[:limit]]

def news_category_score(items, positive_words, risk_words, pos_cap=8, risk_cap=-10, positive_override=None, risk_override=None):
    positive_override = positive_override or []
    risk_override = risk_override or []

    raw = 0
    positive = 0
    risk = 0

    for item in items:
        item_raw, item_pos, item_risk = news_item_score(
            item,
            positive_words,
            risk_words,
            positive_override=positive_override,
            risk_override=risk_override
        )
        raw += item_raw
        positive += item_pos
        risk += item_risk

    if raw >= 8:
        mod = pos_cap
    elif raw >= 3:
        mod = max(2, int(pos_cap / 2))
    elif raw <= -10:
        mod = risk_cap
    elif raw <= -4:
        mod = min(-4, int(risk_cap / 2))
    else:
        mod = 0

    return mod, raw, positive, risk

def macro_fed_score_live():
    items = fetch_google_news_items(
        'Federal Reserve OR Powell OR FOMC rate cut inflation yields stocks crypto',
        hours=18,
        max_items=10
    )

    if not items:
        return 0, "🟡 ФРС: свежих новостей не найдено", []

    risk_words = {
        "higher for longer": 5,
        "restrictive": 4,
        "hot inflation": 5,
        "sticky inflation": 5,
        "rate hike": 5,
        "no rush": 3,
        "hawkish": 4,
        "inflation worries": 4,
        "yields rise": 4,
        "treasury yields rise": 4,
        "dollar rises": 3,
        "uncertainty": 2
    }

    positive_words = {
        "rate cut": 5,
        "rate cuts": 5,
        "cut rates": 5,
        "dovish": 4,
        "cooling inflation": 5,
        "inflation cools": 5,
        "soft landing": 3,
        "yields fall": 4,
        "dollar falls": 3,
        "easing": 4
    }

    mod, raw, pos, risk = news_category_score(items, positive_words, risk_words, 8, -10)

    if mod >= 6:
        text = "🟢 ФРС: свежие новости помогают рисковым активам"
    elif mod > 0:
        text = "🟢 ФРС: умеренно лучше"
    elif mod <= -8:
        text = "🔴 ФРС: свежие новости давят на риск"
    elif mod < 0:
        text = "🔴 ФРС: фон скорее негативный"
    else:
        text = "🟡 ФРС: свежий фон нейтральный"

    triggers = matched_headlines(items, risk_words if mod < 0 else positive_words, 2)
    return mod, f"{text} ({mod:+d})", triggers

def macro_geopolitics_score_live():
    items = fetch_google_news_items(
        'Iran Israel US Middle East ceasefire talks oil Hormuz missile strike escalation',
        hours=12,
        max_items=12
    )

    if not items:
        return 0, "🟡 Геополитика: свежих новостей не найдено", []

    risk_words = {
        "attack": 5,
        "missile": 5,
        "strike": 5,
        "strikes": 5,
        "war": 5,
        "hormuz": 5,
        "oil jumps": 5,
        "oil rises": 4,
        "escalation": 5,
        "retaliation": 5,
        "tanker": 4,
        "sanctions": 3,
        "threat": 3,
        "evacuate": 4
    }

    positive_words = {
        "ceasefire": 6,
        "talks": 3,
        "negotiations": 4,
        "deal": 4,
        "diplomacy": 4,
        "de-escalation": 6,
        "agreement": 4,
        "resume talks": 5,
        "oil falls": 4
    }

    positive_override = [
        "end war", "end the war", "end iran war", "sign deal", "signed deal",
        "peace deal", "reopen hormuz", "reopens hormuz", "reopen the strait",
        "ceasefire", "de-escalation", "deescalation", "stop fighting",
        "halt strikes", "resume talks", "diplomatic breakthrough"
    ]

    risk_override = [
        "new strikes", "missile strike", "missile strikes", "oil tanker hit",
        "closes hormuz", "close hormuz", "blockade hormuz", "attack on",
        "retaliatory strike", "war expands", "escalates"
    ]

    mod, raw, pos, risk = news_category_score(
        items,
        positive_words,
        risk_words,
        8,
        -10,
        positive_override=positive_override,
        risk_override=risk_override
    )

    if mod >= 6:
        text = "🟢 Геополитика: есть признаки деэскалации"
    elif mod > 0:
        text = "🟢 Геополитика: стало немного спокойнее"
    elif mod <= -8:
        text = "🔴 Геополитика: свежий риск эскалации"
    elif mod < 0:
        text = "🔴 Геополитика: риск всё ещё давит"
    else:
        text = "🟡 Геополитика: свежий фон смешанный"

    triggers = matched_headlines(
        items,
        risk_words if mod < 0 else positive_words,
        2,
        positive_override=positive_override,
        risk_override=risk_override
    )
    return mod, f"{text} ({mod:+d})", triggers

def macro_crypto_news_score_live():
    items = fetch_google_news_items(
        'Bitcoin Ethereum crypto ETF inflows outflows liquidation hack SEC regulation institutional',
        hours=8,
        max_items=12
    )

    if not items:
        return 0, "🟡 Крипто-новости: свежих новостей не найдено", []

    positive_words = {
        "etf inflows": 5,
        "inflows": 4,
        "record inflows": 6,
        "institutional": 3,
        "approval": 4,
        "adoption": 3,
        "bullish": 3,
        "accumulation": 3,
        "rally": 3
    }

    risk_words = {
        "outflows": 5,
        "liquidations": 5,
        "sell-off": 5,
        "selloff": 5,
        "hack": 6,
        "exploit": 6,
        "lawsuit": 4,
        "sec sues": 5,
        "ban": 5,
        "crackdown": 5,
        "plunges": 4,
        "falls": 3
    }

    mod, raw, pos, risk = news_category_score(items, positive_words, risk_words, 6, -6)

    if mod >= 5:
        text = "🟢 Крипто-новости: свежие заголовки поддерживают рынок"
    elif mod > 0:
        text = "🟢 Крипто-новости: умеренно позитивно"
    elif mod <= -5:
        text = "🔴 Крипто-новости: свежие заголовки добавляют риск"
    elif mod < 0:
        text = "🔴 Крипто-новости: умеренно негативно"
    else:
        text = "🟡 Крипто-новости: свежий фон без перекоса"

    triggers = matched_headlines(items, risk_words if mod < 0 else positive_words, 2)
    return mod, f"{text} ({mod:+d})", triggers

def get_news_risk():
    """
    v9.5 LIVE NEWS MACRO:
    Реально проверяет свежие заголовки, а не держит один и тот же -11 весь день.
    Кэш 15 минут, чтобы не перегружать Render и Google News.
    """
    try:
        now = time.time()

        if _news_cache.get("data") and now - float(_news_cache.get("time", 0) or 0) < 15 * 60:
            return _news_cache["data"]

        fed_mod, fed_text, fed_triggers = macro_fed_score_live()
        geo_mod, geo_text, geo_triggers = macro_geopolitics_score_live()
        crypto_mod, crypto_text, crypto_triggers = macro_crypto_news_score_live()

        total = clamp(fed_mod + geo_mod + crypto_mod, -20, 18)

        if total >= 8:
            title = "🟢 Новостной фон улучшается"
        elif total >= 2:
            title = "🟢 Новостной фон умеренно позитивный"
        elif total <= -12:
            title = "🟥 Новостной фон опасный"
        elif total <= -4:
            title = "🔴 Новостной фон негативный"
        else:
            title = "🟡 Новостной фон смешанный"

        text = (
            f"{title} ({total:+d})\n"
            f"📰 Новости: обновлено {moscow_time_label()} МСК, свежие заголовки 8–18ч\n"
            f"{fed_text}\n"
            f"{geo_text}\n"
            f"{crypto_text}"
        )

        triggers = []
        for name, rows in [
            ("ФРС", fed_triggers),
            ("Гео", geo_triggers),
            ("Крипто", crypto_triggers),
        ]:
            for h in rows[:1]:
                triggers.append(f"{name}: {h}")

        if triggers:
            text += "\nКлючевые заголовки:\n"
            for h in triggers[:3]:
                if len(h) > 150:
                    h = h[:147] + "..."
                text += f"• {h}\n"

        result = (int(total), text.strip())
        _news_cache["time"] = now
        _news_cache["data"] = result
        return result

    except Exception as e:
        return 0, f"⚪ Внешний фон не удалось оценить: {e}"

def macro_mode_text(ctx):
    score = ctx.get("macro_mod", ctx.get("geo_mod", 0))

    if score >= 8:
        return "📰 Новости: 🟢 позитивные"
    if score >= 2:
        return "📰 Новости: 🟢 слегка лучше"
    if score <= -12:
        return "📰 Новости: 🟥 опасные"
    if score <= -4:
        return "📰 Новости: 🔴 негативные"
    return "📰 Новости: 🟡 смешанные"

def compact_market_risk_line(ctx):
    level = market_risk_level(ctx)
    btc_change = ctx.get("btc_change", 0)
    fg_value = ctx.get("fg_value", 50)

    if level == "danger":
        return f"⚠️ Риск рынка: 🔴 опасный — BTC {btc_change:.2f}%, страх {fg_value}"
    if level == "caution":
        return f"⚠️ Риск рынка: 🟡 осторожно — BTC {btc_change:.2f}%, страх {fg_value}"
    if level == "positive":
        return f"⚠️ Риск рынка: 🟢 фон помогает — BTC {btc_change:.2f}%, страх {fg_value}"
    return f"⚠️ Риск рынка: 🟡 нейтральный — BTC {btc_change:.2f}%, страх {fg_value}"


def market_risk_level(ctx):
    """
    v9.8:
    Режим рынка считаем по BTC + страху + новостям.
    Итог должен быть короткий и практичный.
    """
    news_score = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    market_score = ctx.get("market_mod", 0)
    btc_change = ctx.get("btc_change", 0)
    fg_value = ctx.get("fg_value", 50)

    if btc_change <= -4:
        return "danger"
    if btc_change <= -3 and fg_value <= 25:
        return "danger"
    if btc_change <= -3 and news_score <= 2:
        return "danger"
    if news_score <= -12 and btc_change <= -1:
        return "danger"
    if fg_value <= 20 and btc_change <= -2:
        return "danger"

    if btc_change <= -2 or news_score <= -6 or fg_value <= 25 or market_score <= -8:
        return "caution"

    if news_score >= 8 and btc_change >= 0 and fg_value > 35:
        return "positive"

    return "neutral"

def macro_action_hint(ctx):
    level = market_risk_level(ctx)

    if level == "danger":
        return "Решение: BUY запрещены. BTC/ETH — только после стабилизации. Альты — не трогать, только наблюдать."

    if level == "caution":
        return "Решение: осторожно. Быстрые входы ограничить, ждать подтверждение объёмом и стабилизацию BTC."

    if level == "positive":
        return "Решение: фон помогает. Можно искать BUY, но вход только частями."

    return "Решение: нейтрально. Входы только по подтверждённым сетапам."

def compact_news_line(ctx):
    score = ctx.get("macro_mod", 0)
    text = ctx.get("macro_text", "")

    fed = "нейтрально"
    geo = "нейтрально"
    crypto = "нет свежих данных"

    for line in text.splitlines():
        if "ФРС:" in line:
            if "🔴" in line:
                fed = "давит"
            elif "🟢" in line:
                fed = "помогает"
            else:
                fed = "нейтрально"

        if "Геополитика:" in line:
            if "🔴" in line:
                geo = "давит"
            elif "🟢" in line:
                geo = "улучшилась"
            else:
                geo = "смешанно"

        if "Крипто-новости:" in line:
            if "🔴" in line:
                crypto = "негатив"
            elif "🟢" in line:
                crypto = "позитив"
            elif "свежих новостей не найдено" in line:
                crypto = "нет свежих данных"
            else:
                crypto = "нейтрально"

    if score <= -8:
        label = "негатив"
    elif score >= 6:
        label = "позитив"
    else:
        label = "смешанно"

    return f"{label} ({score:+d}) — ФРС {fed}, гео {geo}, крипто {crypto}"

def market_improvement_plan(ctx):
    items = []
    btc_change = ctx.get("btc_change", 0)
    fg_value = ctx.get("fg_value", 50)
    news_score = ctx.get("macro_mod", 0)

    if btc_change <= -3:
        items.append("BTC должен перестать падать хотя бы 3–4 часа")
    elif btc_change < 0:
        items.append("BTC должен выйти хотя бы в нейтральную динамику")

    if fg_value <= 25:
        items.append("страх должен ослабнуть")

    if news_score < 0:
        items.append("новостной фон должен стать хотя бы нейтральным")

    if not items:
        items.append("нужно подтверждение объёмом и удержание цены")

    return items[:3]

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
    """
    v10.2:
    BTC-фильтр не должен возвращать 0.00%, если сломалась только диагностика свечей.
    Сначала берём 24ч изменение из ticker, потом пробуем теханализ.
    Если diagnostics упал — всё равно используем changeRate.
    """
    change = 0.0

    try:
        t = get_ticker("BTC-USDT")
        change = float(t.get("changeRate", 0) or 0) * 100
    except Exception:
        return "BTC не удалось оценить", 0, 0

    try:
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
        # Fallback: ticker работает, но свечи/RSI не пришли.
        # Это лучше, чем показывать BTC 0.00%.
        if change <= -2:
            return "BTC мешает рынку", -12, change
        if change < 0:
            return "BTC слабый", -6, change
        if change >= 2:
            return "BTC помогает рынку", 6, change
        return "BTC нейтральный", 0, change

def market_context():
    fg_value, fg_text, fg_mod = get_fear_greed()
    dom, dom_mod, dom_text = get_btc_dominance()
    macro_mod, macro_text = get_news_risk()
    btc_text, btc_mod, btc_change = btc_filter()

    total = fg_mod + dom_mod + macro_mod + btc_mod

    temp_ctx = {
        "fg_value": fg_value,
        "fg_text": fg_text,
        "macro_mod": macro_mod,
        "geo_mod": macro_mod,
        "btc_change": btc_change,
        "market_mod": total,
    }

    level = market_risk_level(temp_ctx)

    if level == "danger":
        state = "🔴 рынок рискованный"
    elif level == "caution":
        state = "🟡 осторожный рынок"
    elif level == "positive":
        state = "🟢 рынок помогает росту"
    else:
        state = "🟡 рынок нейтральный"

    return {
        "state": state,
        "risk_level": level,
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

    # v10.2 fallback для самого BTC:
    # если общий market_context почему-то не оценил BTC, берём 24ч из текущей монеты.
    if asset == "BTC" and (ctx.get("btc_change", 0) == 0 or "не удалось" in ctx.get("btc_text", "")):
        ctx = dict(ctx)
        ctx["btc_change"] = change_24
        if change_24 <= -2:
            ctx["btc_text"] = "BTC мешает рынку"
            ctx["btc_mod"] = -12
        elif change_24 < 0:
            ctx["btc_text"] = "BTC слабый"
            ctx["btc_mod"] = -6
        elif change_24 >= 2:
            ctx["btc_text"] = "BTC помогает рынку"
            ctx["btc_mod"] = 6
        else:
            ctx["btc_text"] = "BTC нейтральный"
            ctx["btc_mod"] = 0

        ctx["market_mod"] = ctx.get("fg_value", 50) + ctx.get("macro_mod", 0) + ctx.get("btc_mod", 0)
        ctx["risk_level"] = market_risk_level(ctx)
        ctx["state"] = "🔴 рынок рискованный" if ctx["risk_level"] == "danger" else ctx.get("state", "🟡 осторожный рынок")

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

def learning_market_bucket(ctx):
    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    btc_change = ctx.get("btc_change", 0)

    if macro_mod <= -8 and btc_change < 0:
        return "bad_macro_btc_down"
    if macro_mod <= -8:
        return "bad_macro"
    if btc_change <= -2:
        return "btc_down"
    if macro_mod >= 5 and btc_change >= 0:
        return "good_macro_btc_ok"
    return "neutral"

def learning_signal_type(c):
    action = c.get("action", "SKIP")
    symbol = c.get("symbol", "")

    if action == "ACCUM":
        return "ACCUM"
    if action == "BUY":
        return "BUY"
    if action == "WATCH":
        return "WATCH"
    if action == "PUMP":
        return "IMPULSE"

    return "SKIP"

def learning_tags(c):
    ctx = c.get("ctx", {})
    tags = []

    if ctx.get("macro_mod", ctx.get("geo_mod", 0)) <= -8:
        tags.append("bad_macro")
    if ctx.get("btc_change", 0) < 0:
        tags.append("btc_down")
    if c.get("rsi", 50) <= 35:
        tags.append("oversold")
    if c.get("volume_trend", 1) >= 1.2:
        tags.append("volume_ok")
    if c.get("symbol") in ["BTC", "ETH", "SOL"]:
        tags.append("core_asset")
    elif c.get("is_quality"):
        tags.append("quality_alt")
    else:
        tags.append("speculative")

    return tags

def signal_key(asset, ts):
    return f"{asset}_{int(ts)}"

def learning_success_threshold(action):
    # WATCH оцениваем мягче: правильно, если бот не дал BUY и монета не улетела вниз.
    if action == "WATCH":
        return 1.0
    if action == "ACCUM":
        return 2.0
    return 3.0

def classify_learning_result(rec):
    results = rec.get("results", {})
    action = rec.get("action", "SKIP")

    r24 = results.get("24h")
    r48 = results.get("48h")
    r6 = results.get("6h")

    main = r48 if isinstance(r48, (int, float)) else r24
    if not isinstance(main, (int, float)):
        return "open"

    best = max([x for x in [r6, r24, r48] if isinstance(x, (int, float))] or [main])
    worst = min([x for x in [r6, r24, r48] if isinstance(x, (int, float))] or [main])
    threshold = learning_success_threshold(action)

    if action == "WATCH":
        if worst <= -5:
            return "watch_saved"  # правильно, что не купили
        if best >= 5:
            return "missed_move"  # слишком осторожно
        return "neutral"

    if action == "ACCUM":
        if best >= 3 and worst > -6:
            return "success"
        if worst <= -7:
            return "bad"
        return "neutral"

    if action in ["BUY", "PUMP"]:
        if best >= 5:
            return "success"
        if worst <= -4 or main <= -2:
            return "bad"
        return "neutral"

    return "neutral"


def v87_cleanup_open_learning_duplicates(open_items):
    """
    Одна монета = одно открытое наблюдение до закрытия 48ч.
    Если старые версии уже создали дубли, оставляем самую раннюю запись.
    """
    if not isinstance(open_items, dict):
        return {}, False

    by_asset = {}
    changed = False

    # Сортируем по времени: первая запись по монете остаётся, остальные удаляются.
    rows = sorted(
        list(open_items.items()),
        key=lambda kv: float(kv[1].get("time", 0) or 0)
    )

    cleaned = {}
    for key, rec in rows:
        asset = rec.get("asset")
        if not asset:
            cleaned[key] = rec
            continue

        if asset in by_asset:
            changed = True
            continue

        by_asset[asset] = key
        cleaned[key] = rec

    return cleaned, changed


def update_signal_results():
    """
    v8.3 SELF LEARNING JOURNAL:
    бот проверяет свои сигналы через 1ч / 6ч / 24ч / 48ч.
    Закрываем запись только после 48ч, чтобы видеть не только быстрый шум.
    """
    data = load_json(RESULTS_FILE)
    if not isinstance(data, dict):
        data = {}

    open_items = data.get("open", {})
    closed_items = data.get("closed", [])
    open_items, dedup_changed = v87_cleanup_open_learning_duplicates(open_items)
    now = time.time()
    changed = bool(dedup_changed)

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

        checkpoints = [
            ("1h", 3600),
            ("6h", 6 * 3600),
            ("24h", 24 * 3600),
            ("48h", 48 * 3600),
        ]

        for name, seconds in checkpoints:
            if age >= seconds and name not in results:
                results[name] = round(percent_change(start_price, current_price), 2)
                changed = True

        # Закрываем только после 48 часов.
        if age >= 48 * 3600 and "48h" in results:
            rec["closed_time"] = now
            rec["outcome"] = classify_learning_result(rec)
            closed_items.append(rec)
            open_items.pop(key, None)
            changed = True

    if len(closed_items) > 800:
        closed_items = closed_items[-800:]

    data["open"] = open_items
    data["closed"] = closed_items
    data.setdefault("version", BOT_VERSION)

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

        same_asset = rec.get("asset") == asset
        same_quality_group = rec.get("is_quality") is True

        if same_asset or same_quality_group:
            r48 = rec.get("results", {}).get("48h")
            r24 = rec.get("results", {}).get("24h")
            result = r48 if isinstance(r48, (int, float)) else r24
            if isinstance(result, (int, float)):
                sample.append(result)

    if len(sample) < 8:
        return None, len(sample)

    wins = sum(1 for x in sample if x >= learning_success_threshold(action))
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
    new_chance_5 = int(round(chance_5 * 0.75 + historical_chance * 0.25))

    if n >= 20:
        note = f"учтена история {n} похожих сигналов"
    else:
        note = f"история пока небольшая: {n} похожих сигналов"

    return new_chance_5, chance_10, chance_15, note

def learning_sample_for(c):
    data = load_json(RESULTS_FILE)
    closed = data.get("closed", []) if isinstance(data, dict) else []
    if not closed:
        return []

    symbol = c.get("symbol")
    action = learning_signal_type(c)
    ctx = c.get("ctx", {})
    bucket = learning_market_bucket(ctx)
    tags = set(learning_tags(c))

    sample = []
    for rec in closed:
        rec_action = rec.get("learning_type", rec.get("action"))
        if rec_action != action:
            continue

        rec_tags = set(rec.get("tags", []))
        same_asset = rec.get("asset") == symbol
        same_market = rec.get("market_bucket") == bucket
        tag_overlap = len(tags & rec_tags) >= 2

        if same_asset or (same_market and tag_overlap):
            sample.append(rec)

    return sample[-80:]

def v83_learning_adjustment(c):
    """
    Простое самообучение без опасного автотрейдинга:
    если похожие сигналы часто проваливались — режем score;
    если часто работали — чуть повышаем уверенность.
    """
    sample = learning_sample_for(c)

    if len(sample) < 10:
        return 0, f"самообучение: мало истории ({len(sample)})"

    outcomes = [classify_learning_result(x) for x in sample]

    success = outcomes.count("success")
    bad = outcomes.count("bad")
    missed = outcomes.count("missed_move")
    watch_saved = outcomes.count("watch_saved")

    n = len(sample)

    # WATCH: если бот часто "спасал" от падения — усиливаем осторожность.
    if c.get("action") == "WATCH":
        if watch_saved >= max(4, n * 0.35):
            return -4, f"самообучение: похожие WATCH часто спасали от падения ({watch_saved}/{n})"
        if missed >= max(4, n * 0.35):
            return +4, f"самообучение: похожие WATCH часто пропускали рост ({missed}/{n})"

    # BUY / ACCUM / IMPULSE.
    if bad >= max(4, n * 0.35):
        return -8, f"самообучение: похожие сигналы часто проваливались ({bad}/{n})"

    if success >= max(5, n * 0.45):
        return +5, f"самообучение: похожие сигналы часто работали ({success}/{n})"

    return 0, f"самообучение: статистика смешанная ({n})"

def v83_apply_self_learning(c):
    if not c:
        return c

    c = dict(c)
    delta, note = v83_learning_adjustment(c)
    c["_learning_delta"] = delta
    c["_learning_note"] = note

    # Не даём истории ломать базовую защиту. Только мягкая коррекция.
    if delta:
        old_score = c.get("score", 0)
        c["score"] = max(0, min(100, old_score + delta))
        c["_master_score"] = max(0, min(100, c.get("_master_score", old_score) + delta))

        if delta < 0:
            c["chance_5"] = max(5, c.get("chance_5", 0) + delta)
            c.setdefault("minus", [])
            if note not in c["minus"]:
                c["minus"].append(note)
        else:
            c["chance_5"] = min(80, c.get("chance_5", 0) + max(1, delta // 2))
            c.setdefault("plus", [])
            if note not in c["plus"]:
                c["plus"].append(note)

    price = c.get("price", 0) or 0
    c["target_low"] = price * (1 + c.get("low", 0) / 100)
    c["target_high"] = price * (1 + c.get("high", 0) / 100)

    return c

def learning_age_text(seconds):
    seconds = max(0, int(seconds or 0))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    if hours <= 0:
        return f"{minutes}м"

    if minutes <= 0:
        return f"{hours}ч"

    return f"{hours}ч {minutes}м"

def learning_price_now(asset):
    try:
        ticker = get_ticker(f"{asset}-USDT")
        if not ticker:
            return None
        price = float(ticker.get("last", 0) or 0)
        return price if price > 0 else None
    except Exception:
        return None

def learning_result_icon(value, action):
    if not isinstance(value, (int, float)):
        return "⏳"

    if action == "WATCH":
        if value <= -5:
            return "🛡"
        if value >= 5:
            return "⚠️"
        return "🟡"

    if action == "ACCUM":
        if value >= 3:
            return "✅"
        if value <= -7:
            return "🔴"
        return "🟡"

    if action in ["BUY", "PUMP"]:
        if value >= 5:
            return "✅"
        if value <= -2:
            return "🔴"
        return "🟡"

    return "🟡"

def learning_checkpoint_status(rec, now):
    results = rec.get("results", {}) if isinstance(rec.get("results", {}), dict) else {}
    start_time = float(rec.get("time", 0) or 0)
    action = rec.get("action", "SKIP")

    checkpoints = [
        ("1ч", "1h", 3600),
        ("6ч", "6h", 6 * 3600),
        ("24ч", "24h", 24 * 3600),
        ("48ч", "48h", 48 * 3600),
    ]

    parts = []
    age = max(0, now - start_time)

    for label, key, seconds in checkpoints:
        value = results.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{label}: {learning_result_icon(value, action)} {value:+.2f}%")
        else:
            left = max(0, seconds - age)
            parts.append(f"{label}: ждём {learning_age_text(left)}")

    return " | ".join(parts)

def learning_open_rows(open_items):
    if not isinstance(open_items, dict) or not open_items:
        return "Открытых наблюдений нет.\n"

    now = time.time()
    rows = sorted(
        list(open_items.values()),
        key=lambda r: float(r.get("time", 0) or 0)
    )

    text = ""
    for rec in rows[:6]:
        asset = rec.get("asset", "?")
        start_price = float(rec.get("price", 0) or 0)
        current_price = learning_price_now(asset)
        age = now - float(rec.get("time", 0) or 0)
        close_left = max(0, 48 * 3600 - age)

        if current_price and start_price > 0:
            now_pct = percent_change(start_price, current_price)
            price_line = f"цена: ${start_price:.6g} → ${current_price:.6g} ({now_pct:+.2f}%)"
        else:
            price_line = f"цена записи: ${start_price:.6g}, текущую цену не удалось получить"

        action = rec.get("action", "н/д")
        score = rec.get("score", "н/д")
        verdict = rec.get("verdict", "н/д")
        seen_count = int(rec.get("seen_count", 1) or 1)

        text += (
            f"• {asset}: {action}, score {score}/100\n"
            f"  статус: {verdict}\n"
            f"  {price_line}\n"
            f"  прошло: {learning_age_text(age)} | закрытие через: {learning_age_text(close_left)} | встречалось: {seen_count} раз\n"
            f"  проверки: {learning_checkpoint_status(rec, now)}\n"
        )

    if len(rows) > 6:
        text += f"…ещё открытых наблюдений: {len(rows) - 6}\n"

    return text

def learning_report():
    update_signal_results()

    data = load_json(RESULTS_FILE)
    if not isinstance(data, dict):
        return (
            f"📚 Самообучение ALEX EDGE\n"
            f"Версия: {BOT_VERSION}\n\n"
            "Истории пока нет.\n"
            "Возможная причина: файл истории ещё не создан или сбросился после деплоя Render."
        )

    closed = data.get("closed", [])
    open_items = data.get("open", {})

    total = len(closed)
    outcomes = [classify_learning_result(x) for x in closed]
    success = outcomes.count("success")
    bad = outcomes.count("bad")
    neutral = outcomes.count("neutral")
    missed = outcomes.count("missed_move")
    watch_saved = outcomes.count("watch_saved")

    text = (
        f"📚 Самообучение ALEX EDGE\n"
        f"Версия: {BOT_VERSION}\n\n"
        f"Статус: обучение работает, данные копятся.\n"
        f"Открытых наблюдений: {len(open_items)}\n"
        f"Закрытых 48ч результатов: {total}\n\n"
    )

    text += "🔎 Открытые наблюдения:\n"
    text += learning_open_rows(open_items)
    text += "\n"

    if total == 0:
        text += (
            "Итог пока: закрытых 48ч результатов нет, поэтому бот ещё не меняет веса по статистике.\n"
            "Он уже проверяет открытые наблюдения через 1ч / 6ч / 24ч / 48ч.\n"
            "Если после деплоя Render история стала пустой — файл signal_results.json мог сброситься."
        )
        return text

    by_asset = {}
    for rec in closed:
        a = rec.get("asset", "?")
        by_asset.setdefault(a, {"n": 0, "success": 0, "bad": 0, "watch_saved": 0, "missed": 0})
        by_asset[a]["n"] += 1
        outcome = classify_learning_result(rec)
        if outcome == "success":
            by_asset[a]["success"] += 1
        if outcome == "bad":
            by_asset[a]["bad"] += 1
        if outcome == "watch_saved":
            by_asset[a]["watch_saved"] += 1
        if outcome == "missed_move":
            by_asset[a]["missed"] += 1

    ranked = sorted(
        by_asset.items(),
        key=lambda kv: (kv[1]["success"] + kv[1]["watch_saved"] - kv[1]["bad"] - kv[1]["missed"], kv[1]["n"]),
        reverse=True
    )[:5]

    text += (
        "📊 Закрытые результаты 48ч:\n"
        f"✅ Сработали: {success}\n"
        f"🟡 Нейтрально: {neutral}\n"
        f"🔴 Ошиблись: {bad}\n"
        f"🛡 WATCH спас от падения: {watch_saved}\n"
        f"⚠️ WATCH пропустил рост: {missed}\n\n"
    )

    if ranked:
        text += "Лучше по истории:\n"
        for asset, s in ranked:
            text += (
                f"• {asset}: ✅{s['success']} / 🔴{s['bad']} / "
                f"🛡{s['watch_saved']} / ⚠️{s['missed']} / всего {s['n']}\n"
            )

    text += "\nКак бот учится: похожие провальные сигналы режут score, похожие успешные чуть повышают доверие. Автопокупки не включены."
    return text

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
    open_items, _ = v87_cleanup_open_learning_duplicates(open_items)
    now = time.time()

    for c in items:
        if c.get("action") in ["SKIP"]:
            continue

        h[c["symbol"]] = {
            "price": c["price"],
            "score": c["score"],
            "time": now
        }

        # v8.7: не создаём новый открытый сигнал, если по этой монете уже есть наблюдение.
        # Иначе /signal раздувает статистику и портит обучение.
        existing_key = None
        existing_rec = None

        for key, rec in open_items.items():
            if rec.get("asset") == c["symbol"]:
                existing_key = key
                existing_rec = rec
                break

        if existing_rec:
            existing_rec["last_seen"] = now
            existing_rec["last_price"] = round(float(c.get("price", 0) or 0), 8)
            existing_rec["last_score"] = c.get("score", 0)
            existing_rec["last_action"] = c.get("action")
            existing_rec["last_verdict"] = c.get("verdict")
            existing_rec["seen_count"] = int(existing_rec.get("seen_count", 1) or 1) + 1

            # v9.4: если старая версия успела записать BTC/ETH как BUY в падающем рынке,
            # переписываем открытое наблюдение в безопасный режим, чтобы не портить обучение.
            if c.get("_falling_market_no_buy"):
                existing_rec["action"] = c.get("action")
                existing_rec["verdict"] = c.get("verdict")
                existing_rec["score"] = c.get("score", existing_rec.get("score", 0))
                existing_rec["master_score"] = c.get("_master_score", c.get("score", existing_rec.get("score", 0)))
                existing_rec["chance_5"] = c.get("chance_5", existing_rec.get("chance_5", 0))
                existing_rec["chance_10"] = c.get("chance_10", existing_rec.get("chance_10", 0))
                existing_rec["chance_15"] = c.get("chance_15", existing_rec.get("chance_15", 0))
                existing_rec["learning_type"] = learning_signal_type(c)
                existing_rec["learning_note"] = "v9.4: BUY заменён на ожидание из-за падающего рынка"
                existing_rec["tags"] = learning_tags(c)

            open_items[existing_key] = existing_rec
            continue

        ctx = c.get("ctx", {})
        rec = {
            "asset": c["symbol"],
            "price": round(float(c.get("price", 0) or 0), 8),
            "score": c.get("score", 0),
            "master_score": c.get("_master_score", c.get("score", 0)),
            "bucket": outcome_bucket(c.get("score", 0)),
            "chance_5": c.get("chance_5", 0),
            "chance_10": c.get("chance_10", 0),
            "chance_15": c.get("chance_15", 0),
            "action": c.get("action"),
            "learning_type": learning_signal_type(c),
            "verdict": c.get("verdict"),
            "is_quality": c.get("is_quality"),
            "profile": c.get("profile"),
            "rsi": c.get("rsi"),
            "volume_trend": c.get("volume_trend"),
            "change_24": round(float(c.get("change_24", 0) or 0), 2),
            "btc_change": round(float(ctx.get("btc_change", 0) or 0), 2),
            "macro_mod": ctx.get("macro_mod", ctx.get("geo_mod", 0)),
            "market_bucket": learning_market_bucket(ctx),
            "tags": learning_tags(c),
            "learning_delta": c.get("_learning_delta", 0),
            "learning_note": c.get("_learning_note", ""),
            "time": now,
            "last_seen": now,
            "seen_count": 1,
            "results": {}
        }

        open_items[signal_key(c["symbol"], now)] = rec

    results["open"] = open_items
    results.setdefault("closed", [])
    results["version"] = BOT_VERSION

    save_json(HISTORY_FILE, h)
    save_json(RESULTS_FILE, results)

def human_final(c):
    if c.get("_falling_knife"):
        return "ждать стабилизацию, не ловить нож."

    if c.get("_cautious_accum"):
        return "наблюдать набор, первая часть только после стабилизации."

    if "СРЕДНЕСРОЧНЫЙ" in c["verdict"]:
        return "только после стабилизации, малой первой частью и без входа всей суммой."

    if c.get("action") == "WATCH":
        ctx = c.get("ctx", {})
        if ctx.get("macro_mod", ctx.get("geo_mod", 0)) <= -8 and c.get("symbol") not in ["BTC", "ETH"]:
            return "пока наблюдать: плохой фон для альтов и BTC давит на рынок."
        return "идея есть, но пока НЕ входить — ждать подтверждения."

    if "НЕТ СИГНАЛА" in c["verdict"] or "НЕ ПОКУПАТЬ" in c["verdict"]:
        return "сейчас качественного входа нет."

    if c["action"] == "BUY":
        return "можно рассмотреть вход, но только частями и без погони за свечой."

    if c["action"] == "PUMP":
        return "это рискованный импульс, лучше не догонять и ждать откат."

    return "сейчас лучше не входить."

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



def v78_apply_watch_score_and_falling_knife_filter(c):
    """
    v7.8:
    1) Если альт ушёл в WATCH из-за плохого macro/BTC — score не должен выглядеть как BUY.
    2) Если BTC/ETH сильно перепроданы и BTC продолжает падать — не пишем агрессивно "начать набор".
    """
    if not c:
        return c

    ctx = c.get("ctx", {})
    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    btc_change = ctx.get("btc_change", 0)
    symbol = c.get("symbol", "")

    # WATCH по альтам в плохом фоне: cap score, чтобы не было "86/100, но ждать".
    if (
        c.get("action") == "WATCH"
        and symbol not in ["BTC", "ETH"]
        and (macro_mod <= -8 or btc_change <= -2)
    ):
        c["score"] = min(c.get("score", 0), 74)
        c["_master_score"] = min(c.get("_master_score", c.get("score", 0)), c["score"])
        c["chance_5"] = min(c.get("chance_5", 0), 35)
        c["chance_10"] = min(c.get("chance_10", 0), 8)
        c["chance_15"] = min(c.get("chance_15", 0), 4)
        c["entry_zone"] = "плохой фон для альтов: ждать стабилизацию BTC и подтверждение объёмом"

        c.setdefault("minus", [])
        if "плохой фон для альтов" not in c["minus"]:
            c["minus"].append("плохой фон для альтов")
        if btc_change < 0 and "BTC падает и может утянуть альты ниже" not in c["minus"]:
            c["minus"].append("BTC падает и может утянуть альты ниже")

    # Falling knife: BTC/ETH можно оставить в среднесроке, но подать осторожнее.
    if (
        c.get("action") == "ACCUM"
        and symbol in ["BTC", "ETH"]
        and c.get("rsi", 50) < 28
        and btc_change <= -2.5
    ):
        c["entry_zone"] = "не ловить нож: первая часть только после остановки падения / стабилизации"
        c["_falling_knife"] = True
        c["score"] = min(c.get("score", 0), 68)
        c["_master_score"] = min(c.get("_master_score", c.get("score", 0)), c["score"])
        c.setdefault("minus", [])
        if "сильная перепроданность, но падение ещё не остановилось" not in c["minus"]:
            c["minus"].append("сильная перепроданность, но падение ещё не остановилось")

    # Если среднесрочный сигнал слабый по score, подаём его осторожнее.
    if (
        c.get("action") == "ACCUM"
        and symbol in ["BTC", "ETH"]
        and c.get("score", 0) < 70
    ):
        c["_cautious_accum"] = True
        c["entry_zone"] = "наблюдать набор: первая часть только после стабилизации цены"
        c.setdefault("minus", [])
        if "score ниже 70, вход только после стабилизации" not in c["minus"]:
            c["minus"].append("score ниже 70, вход только после стабилизации")

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
    c = v78_apply_watch_score_and_falling_knife_filter(c)

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
            return f"📚 Самообучение: открытых наблюдений в истории: {open_count}. Закрытая статистика появится после 24 часов.\n\n"
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


def macro_blocks_aggressive_alt(c):
    """
    v8.1:
    В плохом macro-фоне и при падающем BTC не показываем альты как
    "осторожно малым объёмом" в основном /signal.
    """
    if not c:
        return False

    symbol = c.get("symbol", "")
    ctx = c.get("ctx", {})
    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    btc_change = ctx.get("btc_change", 0)

    return (
        symbol not in ["BTC", "ETH"]
        and macro_mod <= -8
        and btc_change < 0
    )


def needs_aggressive_signal(c):
    """
    Умеренно-рискованный режим, чтобы бот не молчал сутками.
    Это НЕ полноценный BUY, а осторожный вход малым объёмом.
    v8.0: в плохом macro-фоне альты не попадают в этот блок.
    """
    if c.get("action") == "BUY":
        return False

    if macro_blocks_aggressive_alt(c):
        return False

    # Не лезем в явный разгон или плохой внешний рынок.
    if c.get("change_24", 0) >= 15:
        return False
    if c.get("ctx", {}).get("btc_mod", 0) < -15:
        return False
    if c.get("ctx", {}).get("macro_mod", c.get("ctx", {}).get("geo_mod", 0)) <= -12 and c.get("symbol") not in ["BTC", "ETH", "SOL"]:
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
    ctx = c.get("ctx", {})
    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    btc_change = ctx.get("btc_change", 0)

    if c.get("_danger_market_cap"):
        return "страх высокий + BTC падает + риск рынка опасный"

    if c.get("_danger_alt_cap"):
        return "после разворота рынка + нужна стабилизация BTC"

    if c.get("_quality_alt_danger_watch"):
        parts = ["BTC падает", "рынок опасный"]
        if c.get("volume_trend", 1) < 1.1:
            parts.append("объём слабый")
        if c.get("rsi", 50) < 35:
            parts.append("RSI ещё не развернулся")
        return " + ".join(parts[:4])

    if c.get("_falling_market_no_buy"):
        if c.get("symbol") in ["BTC", "ETH"]:
            return "BTC падает >3%, RSI/объём могут быть капитуляцией"
        return "рынок падает, быстрый вход запрещён"

    if c.get("_btc_core_watch"):
        return "сильная перепроданность, ждать стабилизацию"

    if c.get("_eth_core_watch"):
        return "перепроданность, ждать подтверждение"

    if c.get("_red_market_cap") and c.get("action") == "ACCUM":
        if c.get("volume_trend", 1) < 1.1:
            return "страх + слабый объём + ждать стабилизацию"
        return "страх + откат + слабый фон"

    # WATCH должен объясняться статусом ожидания, а не красивыми RSI/объёмом.
    if c.get("action") == "WATCH":
        if macro_mod <= -8 and c.get("symbol") not in ["BTC", "ETH"]:
            if btc_change < 0:
                return "плохой фон для альтов + BTC падает"
            return "плохой фон для альтов"

        if btc_change < -2 and c.get("symbol") not in ["BTC", "ETH"]:
            return "BTC мешает альтам"

        if c.get("volume_trend", 1) < 1.1:
            return "нужен объём + подтверждение"

        if c.get("rsi", 50) < 28:
            return "перепроданность, нужен разворот"

        return "ждать подтверждение"

    if "СРЕДНЕСРОЧНЫЙ" in c.get("verdict", ""):
        if c.get("_falling_knife"):
            return "сильная перепроданность, не ловить нож"

        if c.get("_cautious_accum"):
            return "рынок падает, ждём остановку"

        if ctx.get("fg_value", 50) <= 25:
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

    if c.get("action") == "PUMP":
        if macro_blocks_aggressive_alt(c):
            return "плохой фон для альтов + BTC падает"
        if c.get("volume_trend", 1) >= 1.1:
            return "импульс есть, но риск высокий"
        return "риск выше нормы"

    return "нет условий для входа"

def compact_action(c):
    if c.get("_danger_market_cap"):
        return "без входа сейчас; ждать стабилизацию"

    if c.get("_danger_alt_cap"):
        return "после разворота рынка / нужна стабилизация BTC"

    if c.get("_falling_market_no_buy"):
        return "ждать стабилизацию, не ловить нож"

    if c.get("_btc_core_watch"):
        return "наблюдать / ждать стабилизацию"

    if c.get("_eth_core_watch"):
        return "наблюдать / ждать подтверждение"

    if "СРЕДНЕСРОЧНЫЙ" in c.get("verdict", ""):
        ctx = c.get("ctx", {})
        macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
        btc_change = ctx.get("btc_change", 0)

        if c.get("_falling_knife"):
            return "ждать стабилизацию"

        if c.get("_cautious_accum"):
            return "ждать стабилизацию"

        if macro_mod <= -8 and c.get("symbol") not in ["BTC", "ETH"]:
            return "ждать стабилизацию BTC"

        if macro_mod <= -8 or btc_change < 0:
            return "первая малая часть после стабилизации"

        return "начать малой частью"
    if c.get("action") == "BUY":
        return "можно рассмотреть вход"
    if c.get("action") == "PUMP":
        return "наблюдать / не догонять"
    if c.get("action") == "WATCH":
        return "ждать подтверждение"
    return "не покупать"

def compact_line(i, c):
    note = c.get("_learning_note", "")
    learning = ""
    if note and "мало истории" not in note:
        learning = f"   📚 {note}\n"

    return (
        f"{i}. {c['symbol']} — {c.get('score', 0)}/100 | {compact_price(c.get('price'))}\n"
        f"   {compact_action(c)}\n"
        f"   Причина: {compact_reason(c)}\n"
        f"{learning}"
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
            outcomes = [classify_learning_result(x) for x in closed]
            success = outcomes.count("success")
            bad = outcomes.count("bad")
            watch_saved = outcomes.count("watch_saved")
            return f"📚 Самообучение: открытых {len(open_items)} | закрытых {len(closed)} | ✅ {success} | 🔴 {bad} | 🛡 {watch_saved}\n"

        if isinstance(open_items, dict) and len(open_items):
            return f"📚 Самообучение: открытых наблюдений {len(open_items)}, ждём 24/48ч результаты\n"

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

    ctx = items[0].get("ctx", {}) if items else {}
    if market_risk_level(ctx) == "danger":
        text = "⏳ Кандидаты после разворота рынка:\n"
    else:
        text = "⏳ Близко к сигналу, но ждём подтверждение:\n"
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
    text += f"{compact_market_risk_line(ctx)}\n"
    text += f"{macro_action_hint(ctx)}\n"

    text += "\n"
    accum_label = "🟦 Активы для наблюдения" if market_risk_level(ctx) == "danger" else "🟦 Среднесрок"
    text += (
        "📊 Срез:\n"
        f"🟢 BUY: {len(buy)} | {accum_label}: {len(accum)} | 🟡 WATCH: {len(watch)}\n\n"
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
        text += "🟦 Активы для наблюдения:\n"
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

    # Спекулятивные импульсы убраны из /signal, чтобы основной отчёт не шумел.
    # Они остаются в /alerts.
    text += compact_learning_text()
    text += "\nПодробно: /btc /sol или /coin ETH\nСамообучение: /learning"

    return text



def v87_bad_macro_for_alts(ctx):
    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    btc_change = ctx.get("btc_change", 0)
    return macro_mod <= -8 or btc_change < 0

def v87_priority_watch_asset(symbol):
    # При плохом фоне в WATCH показываем только самые понятные/ликвидные альты.
    return symbol in [
        "SOL", "LINK", "SUI", "BNB", "ADA", "XRP", "AVAX",
        "NEAR", "TON", "DOT", "TAO", "SEI", "INJ", "APT"
    ]

def v87_apply_alt_accum_fix(c):
    """
    v8.7:
    В красном macro-фоне среднесрок в /signal — только BTC/ETH.
    SOL и другие альты не должны попадать в "лучшие идеи на красном рынке",
    если действие по смыслу: ждать стабилизацию BTC.
    """
    if not c:
        return c

    c = dict(c)
    symbol = c.get("symbol", "")
    ctx = c.get("ctx", {})
    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    btc_change = ctx.get("btc_change", 0)

    if (
        c.get("action") == "ACCUM"
        and symbol not in ["BTC", "ETH"]
        and (macro_mod <= -8 or btc_change < 0)
    ):
        c["verdict"] = "🟡 НАБЛЮДАТЬ / ЖДАТЬ BTC"
        c["action"] = "WATCH"
        c["score"] = min(c.get("score", 0), 74)
        c["_master_score"] = min(c.get("_master_score", c.get("score", 0)), c["score"])
        c["chance_5"] = min(c.get("chance_5", 0), 35)
        c["chance_10"] = min(c.get("chance_10", 0), 8)
        c["chance_15"] = min(c.get("chance_15", 0), 4)
        c["entry_zone"] = "альт в плохом фоне: ждать стабилизацию BTC"

        c.setdefault("minus", [])
        if "альт не подходит для среднесрочного набора в плохом фоне" not in c["minus"]:
            c["minus"].append("альт не подходит для среднесрочного набора в плохом фоне")
        if "BTC должен стабилизироваться" not in c["minus"]:
            c["minus"].append("BTC должен стабилизироваться")

    return c



def v88_apply_red_market_score_cap(c):
    """
    v8.8:
    В красном рынке score не должен выглядеть как сильный BUY,
    если действие по смыслу: ждать стабилизацию.
    """
    if not c:
        return c

    c = dict(c)
    symbol = c.get("symbol", "")
    ctx = c.get("ctx", {})
    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    btc_change = ctx.get("btc_change", 0)
    volume_trend = c.get("volume_trend", 1)

    bad_red_market = macro_mod <= -8
    not_stabilized = btc_change < 0 or volume_trend < 1.1

    # BTC/ETH среднесрок в плохом рынке: это осторожная идея, не сильный вход.
    if (
        c.get("action") == "ACCUM"
        and symbol in ["BTC", "ETH"]
        and bad_red_market
        and not_stabilized
    ):
        cap = 77

        # Если совсем слабый объём — ещё осторожнее.
        if volume_trend < 0.7:
            cap = 74

        c["score"] = min(c.get("score", 0), cap)
        c["_master_score"] = min(c.get("_master_score", c.get("score", 0)), c["score"])
        c["_accumulation_score"] = min(c.get("_accumulation_score", c.get("score", 0)), c["score"])
        c["chance_5"] = min(c.get("chance_5", 0), 35)
        c["chance_10"] = min(c.get("chance_10", 0), 10)
        c["chance_15"] = min(c.get("chance_15", 0), 5)
        c["_red_market_cap"] = True

        c.setdefault("minus", [])
        if "красный рынок: score ограничен до стабилизации" not in c["minus"]:
            c["minus"].append("красный рынок: score ограничен до стабилизации")

    # Альты в WATCH в плохом фоне — максимум 74, чтобы не выглядело как BUY.
    if (
        c.get("action") == "WATCH"
        and symbol not in ["BTC", "ETH"]
        and (bad_red_market or btc_change < 0)
    ):
        c["score"] = min(c.get("score", 0), 74)
        c["_master_score"] = min(c.get("_master_score", c.get("score", 0)), c["score"])
        c["chance_5"] = min(c.get("chance_5", 0), 35)
        c["_red_market_cap"] = True

    price = c.get("price", 0) or 0
    c["target_low"] = price * (1 + c.get("low", 0) / 100)
    c["target_high"] = price * (1 + c.get("high", 0) / 100)

    return c



def v94_falling_market(ctx):
    """
    v9.4:
    Если BTC резко падает и внешний фон красный, любые быстрые BUY запрещены.
    RSI < 30 + высокий объём в такой ситуации = возможная капитуляция/падающий нож,
    а не автоматический вход.
    """
    if not isinstance(ctx, dict):
        return False

    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    btc_change = ctx.get("btc_change", 0)
    return macro_mod <= -8 and btc_change <= -3

def v94_apply_falling_market_no_buy(c):
    if not c:
        return c

    c = dict(c)
    ctx = c.get("ctx", {})
    symbol = c.get("symbol", "")

    if not v94_falling_market(ctx):
        return c

    # BTC/ETH: не BUY, а осторожный среднесрок/наблюдение только после стабилизации.
    if symbol in ["BTC", "ETH"] and c.get("action") in ["BUY", "PUMP", "ACCUM", "WATCH"]:
        cap = 74 if symbol == "BTC" else 72

        c["action"] = "ACCUM"
        c["verdict"] = "🟦 СРЕДНЕСРОЧНЫЙ НАБОР / ЖДАТЬ СТАБИЛИЗАЦИЮ"
        c["score"] = min(c.get("score", 0), cap)
        c["_master_score"] = min(c.get("_master_score", c.get("score", 0)), c["score"])
        c["_accumulation_score"] = min(c.get("_accumulation_score", c.get("score", 0)), c["score"])
        c["chance_5"] = min(c.get("chance_5", 0), 25)
        c["chance_10"] = min(c.get("chance_10", 0), 6)
        c["chance_15"] = min(c.get("chance_15", 0), 3)
        c["high"] = min(c.get("high", 0), 4.0)
        c["low"] = min(c.get("low", -2.0), -4.0)
        c["entry_zone"] = "сильное падение BTC: ждать стабилизацию, не ловить нож"
        c["_falling_market_no_buy"] = True
        c["_red_market_cap"] = True

        c.setdefault("minus", [])
        if "BTC падает сильнее -3%: быстрый BUY запрещён" not in c["minus"]:
            c["minus"].append("BTC падает сильнее -3%: быстрый BUY запрещён")
        if "RSI/объём могут быть капитуляцией, нужен разворот" not in c["minus"]:
            c["minus"].append("RSI/объём могут быть капитуляцией, нужен разворот")

    # Альты: никаких BUY/PUMP в падающем рынке.
    elif symbol not in ["BTC", "ETH"] and c.get("action") in ["BUY", "PUMP"]:
        c["action"] = "WATCH"
        c["verdict"] = "🟡 НАБЛЮДАТЬ / РЫНОК ПАДАЕТ"
        c["score"] = min(c.get("score", 0), 68)
        c["_master_score"] = min(c.get("_master_score", c.get("score", 0)), c["score"])
        c["chance_5"] = min(c.get("chance_5", 0), 20)
        c["chance_10"] = min(c.get("chance_10", 0), 4)
        c["chance_15"] = min(c.get("chance_15", 0), 2)
        c["entry_zone"] = "рынок падает: только наблюдать"
        c["_falling_market_no_buy"] = True

        c.setdefault("minus", [])
        if "BTC падает сильнее -3%: BUY по альтам запрещён" not in c["minus"]:
            c["minus"].append("BTC падает сильнее -3%: BUY по альтам запрещён")

    price = c.get("price", 0) or 0
    c["target_low"] = price * (1 + c.get("low", 0) / 100)
    c["target_high"] = price * (1 + c.get("high", 0) / 100)

    return c

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
                    c = v84_apply_btc_core_asset_fix(c)
                    c = v87_apply_alt_accum_fix(c)
                    c = v83_apply_self_learning(c)
                    c = v88_apply_red_market_score_cap(c)
                    c = v94_apply_falling_market_no_buy(c)
                    c = v101_apply_danger_market_score_cap(c)
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
                if (
                    x.get("action") == "ACCUM"
                    and (
                        x.get("symbol") in ["BTC", "ETH"]
                        or not v87_bad_macro_for_alts(x.get("ctx", {}))
                    )
                )
            ],
            key=lambda x: (x.get("_accumulation_score", 0), asset_quality_rank(x), x.get("score", 0)),
            reverse=True
        )[:5]

        buy = sorted(
            [
                x for x in analyzed
                if (
                    x["action"] == "BUY"
                    and not v94_falling_market(x.get("ctx", {}))
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
                    and (
                        not v87_bad_macro_for_alts(x.get("ctx", {}))
                        or v87_priority_watch_asset(x.get("symbol", ""))
                    )
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

        # v8.0: альты, которые технически выглядят живо, но заблокированы плохим macro-фоном,
        # показываем в WATCH, а не в "осторожно малым объёмом".
        macro_blocked_watch = sorted(
            [
                x for x in analyzed
                if (
                    x not in buy
                    and x not in accum
                    and x not in watch
                    and macro_blocks_aggressive_alt(x)
                    and v87_priority_watch_asset(x.get("symbol", ""))
                    and adjusted_score(x) >= 50
                    and x.get("change_24", 0) < 15
                )
            ],
            key=lambda x: (adjusted_score(x), asset_quality_rank(x), x.get("chance_5", 0)),
            reverse=True
        )[:3]

        for x in macro_blocked_watch:
            x["verdict"] = "🟡 ЖДАТЬ ПОДТВЕРЖДЕНИЕ"
            x["action"] = "WATCH"
            x["score"] = min(x.get("score", 0), 74)
            x["_master_score"] = min(x.get("_master_score", x.get("score", 0)), x["score"])
            x["chance_5"] = min(x.get("chance_5", 0), 35)
            x["chance_10"] = min(x.get("chance_10", 0), 8)
            x["entry_zone"] = "плохой фон для альтов: ждать стабилизацию BTC"

        watch = (watch + macro_blocked_watch)[:5]

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
                    and x not in accum
                    and x not in watch
                    and x not in pumps
                    and not macro_blocks_aggressive_alt(x)
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



def is_quality_alert_asset(symbol):
    return symbol in [
        "BTC", "ETH", "SOL", "BNB", "LINK", "SUI", "TAO", "AAVE",
        "INJ", "NEAR", "AVAX", "TON", "ADA", "XRP", "DOT", "SEI"
    ]

def alert_kind(symbol):
    return "quality" if is_quality_alert_asset(symbol) else "speculative"

def cap_alert_score(symbol, score, macro_mod=0, btc_change=0):
    score = int(score)

    if is_quality_alert_asset(symbol):
        if macro_mod <= -8 and symbol not in ["BTC", "ETH", "SOL"]:
            return min(score, 72)
        return min(score, 92)

    # Неизвестные/мелкие монеты не должны выглядеть как 90/100.
    if macro_mod <= -8 or btc_change <= -2:
        return min(score, 52)

    return min(score, 58)

def format_fast_alert(items):
    if not items:
        return None

    quality = [x for x in items if x.get("alert_type") == "quality" or (x.get("kind") == "quality" and not x.get("manual_only"))]
    watch = [x for x in items if x.get("alert_type") == "watch" or x.get("manual_only")]
    speculative = [x for x in items if x.get("kind") == "speculative" and not x.get("manual_only")]

    text = f"⚡ ALEX FAST ALERT {BOT_VERSION}\n\n"
    text += "Быстрые импульсы по рынку. Это не команда покупать и не повод догонять свечу.\n\n"

    if quality:
        text += "🟢 Качественный импульс:\n"
        for i, c in enumerate(quality[:3], 1):
            risk = "повышенный" if c.get("change_24", 0) > 10 else "средний"
            if c.get("market_danger"):
                action = "наблюдать; без входа сейчас, ждать стабилизацию BTC/откат"
            else:
                action = "наблюдать; вход только после отката/подтверждения"
            text += (
                f"{i}. {c['symbol']} — {c.get('score', 0)}/100\n"
                f"15м: {c['fast_move']:+.2f}% | объём x{c['vol_power']:.1f}\n"
                f"Цена: ${c['price']:.6g} | 24ч: {c['change_24']:.2f}% | RSI {c.get('rsi', 'н/д')}\n"
                f"Действие: {action}. Риск: {risk}.\n\n"
            )

    if watch:
        text += "🟡 Ближайшие наблюдения / не вход:\n"
        for i, c in enumerate(watch[:3], 1):
            text += (
                f"{i}. {c['symbol']} — {c.get('score', 0)}/100\n"
                f"15м: {c['fast_move']:+.2f}% | объём x{c['vol_power']:.1f}\n"
                f"Цена: ${c['price']:.6g} | 24ч: {c['change_24']:.2f}% | RSI {c.get('rsi', 'н/д')}\n"
                "Действие: без входа сейчас; ждать стабилизацию BTC, рост объёма и откат/подтверждение.\n\n"
            )

    if speculative:
        text += "🟣 Спекулятивный импульс:\n"
        for i, c in enumerate(speculative[:3], 1):
            text += (
                f"{i}. {c['symbol']} — {c.get('score', 0)}/100\n"
                f"15м: {c['fast_move']:+.2f}% | объём x{c['vol_power']:.1f}\n"
                f"Цена: ${c['price']:.6g} | 24ч: {c['change_24']:.2f}%\n"
                "Действие: не догонять. Только наблюдать. Вход рассматривать не раньше отката и повторного подтверждения. Риск высокий.\n\n"
            )

    text += "⚠️ Главное правило: резкую зелёную свечу не догонять."
    return text

def alerts_empty_status(ctx):
    return (
        f"⚡ ALEX FAST ALERT {BOT_VERSION}\n\n"
        "Сильных быстрых импульсов сейчас нет.\n"
        f"{compact_market_risk_line(ctx)}\n"
        f"{macro_mode_text(ctx)} ({ctx.get('macro_mod', 0):+d})\n\n"
        "Это нормально: фильтр не должен присылать сигнал просто ради шума.\n"
        "Что ждать: рост объёма, стабилизацию BTC и импульс без перегрева RSI."
    )

def get_fast_pumps():
    """
    v10.4 ALERTS VISIBILITY FIX:
    - /alerts больше не молчит: если сильных импульсов нет, показывает статус и ближайшие наблюдения;
    - качественные активы ловятся мягче, но без агрессивных формулировок;
    - спекулятивные монеты остаются строго ограниченными.
    """
    try:
        found = []
        watchlist = []
        ctx = market_context()
        macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
        btc_change = ctx.get("btc_change", 0)
        market_danger = market_risk_level(ctx) == "danger" or btc_change < 0

        pairs = [
            t for t in kucoin_tickers()
            if t.get("symbol", "").endswith("-USDT")
            and float(t.get("volValue", 0) or 0) >= 1_000_000
        ]

        pairs = sorted(
            pairs,
            key=lambda t: (
                1 if alert_kind(t.get("symbol", "").replace("-USDT", "")) == "quality" else 0,
                float(t.get("volValue", 0) or 0),
                abs(float(t.get("changeRate", 0) or 0))
            ),
            reverse=True
        )[:60]

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

                # Совсем поздние пампы не шлём.
                if change_24 > 30:
                    continue

                d = diagnostics(symbol)

                fast_move = float(d.get("move_15", 0) or 0)
                vol_power = float(d.get("vol_1h", 0) or 0)
                rsi_value = float(d.get("rsi", 50) or 50)

                if rsi_value >= 88:
                    continue

                kind = alert_kind(asset)

                # Качественные активы: мягче, чтобы alerts не умерли полностью.
                if kind == "quality":
                    impulse = (
                        (fast_move >= 0.65 and vol_power >= 1.15)
                        or (fast_move >= 0.35 and vol_power >= 1.65)
                        or (fast_move >= 1.10 and vol_power >= 1.00)
                    )
                else:
                    impulse = (
                        (fast_move >= 2.0 and vol_power >= 1.5)
                        or (fast_move >= 3.0 and vol_power >= 1.2)
                    )

                score = 45

                if fast_move >= 3:
                    score += 22
                elif fast_move >= 2:
                    score += 16
                elif fast_move >= 1.2:
                    score += 10
                elif fast_move >= 0.65:
                    score += 6
                elif fast_move >= 0.35:
                    score += 3

                if vol_power >= 2.5:
                    score += 18
                elif vol_power >= 1.8:
                    score += 13
                elif vol_power >= 1.3:
                    score += 8
                elif vol_power >= 1.1:
                    score += 4

                if 0 <= change_24 <= 10:
                    score += 8
                elif change_24 > 18:
                    score -= 12
                elif change_24 < -6:
                    score -= 5

                if kind == "quality":
                    score += 10
                else:
                    score -= 8

                if macro_mod <= -8 and kind == "speculative":
                    score -= 8

                score = cap_alert_score(asset, score, macro_mod=macro_mod, btc_change=btc_change)
                score = max(0, min(100, int(score)))

                item = {
                    "symbol": asset,
                    "kind": kind,
                    "alert_type": "quality" if kind == "quality" else "speculative",
                    "price": price,
                    "change_24": change_24,
                    "fast_move": fast_move,
                    "vol_power": vol_power,
                    "rsi": round(rsi_value, 1),
                    "score": score,
                    "market_danger": market_danger,
                    "manual_only": False
                }

                if impulse:
                    found.append(item)
                elif kind == "quality":
                    # Ручной /alerts должен показать ближайшие наблюдения, даже если импульс слабый.
                    watch_score = min(max(score, 45), 62 if market_danger else 65)
                    if (
                        watch_score >= 48
                        and (
                            abs(change_24) >= 1.0
                            or fast_move >= 0.15
                            or vol_power >= 1.05
                            or rsi_value <= 40
                        )
                    ):
                        w = dict(item)
                        w["score"] = watch_score
                        w["alert_type"] = "watch"
                        w["manual_only"] = True
                        watchlist.append(w)

                time.sleep(0.05)

            except Exception:
                continue

        found = sorted(
            found,
            key=lambda x: (
                1 if x.get("kind") == "quality" else 0,
                x["score"],
                x["fast_move"],
                x["vol_power"]
            ),
            reverse=True
        )[:5]

        if found:
            return format_fast_alert(found), found

        watchlist = sorted(
            watchlist,
            key=lambda x: (
                x.get("score", 0),
                x.get("vol_power", 0),
                abs(x.get("fast_move", 0))
            ),
            reverse=True
        )[:3]

        if watchlist:
            text = format_fast_alert(watchlist)
            if text:
                text = text.replace("Быстрые импульсы по рынку.", "Сильных быстрых импульсов нет. Ниже — ближайшие наблюдения.")
            return text, watchlist

        return alerts_empty_status(ctx), []

    except Exception as e:
        return f"⚡ ALEX FAST ALERT {BOT_VERSION}\n\nОшибка проверки alerts: {e}", []

def should_send_pump(items):
    """
    v8.6 QUIET ALERT MODE:
    Авто-push должен быть редким и только по качественным активам.
    Спекулятивные LAB/H/мелкие монеты остаются только в ручном /alerts.
    """
    history = load_json(PUMP_FILE)
    if not isinstance(history, dict):
        history = {}

    now = time.time()
    allowed = []

    # Общий лимит: максимум один auto-alert в час.
    last_auto = float(history.get("_last_auto_alert", 0) or 0)
    if now - last_auto < 60 * 60:
        return []

    try:
        ctx = market_context()
    except Exception:
        ctx = {}

    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    btc_change = ctx.get("btc_change", 0)

    for c in items:
        symbol = c.get("symbol", "")
        kind = c.get("kind", alert_kind(symbol))

        # Ручные наблюдения из /alerts не пушим автоматически.
        if c.get("manual_only") or c.get("alert_type") == "watch":
            continue

        # Главное: спекулятивные монеты больше НЕ пушим автоматически.
        # Они видны только по ручной команде /alerts.
        if kind != "quality":
            continue

        # В плохом фоне пушим только качественные импульсы, но не душим alerts полностью.
        if macro_mod <= -8 or btc_change < 0:
            if c.get("score", 0) < 65:
                continue
            if c.get("fast_move", 0) < 0.7:
                continue
            if c.get("vol_power", 0) < 1.2:
                continue
        else:
            if c.get("score", 0) < 64:
                continue
            if c.get("fast_move", 0) < 0.6:
                continue
            if c.get("vol_power", 0) < 1.15:
                continue

        # Не повторяем одну и ту же монету чаще 4 часов.
        last = float(history.get(symbol, 0) or 0)
        if now - last < REPEAT_PUMP_AFTER:
            continue

        allowed.append(c)
        history[symbol] = now

    # Один авто-alert — максимум 2 монеты, чтобы не было шума.
    allowed = sorted(
        allowed,
        key=lambda x: (x.get("score", 0), x.get("fast_move", 0), x.get("vol_power", 0)),
        reverse=True
    )[:2]

    if allowed:
        history["_last_auto_alert"] = now
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


def v82_apply_single_coin_consistency(c):
    """
    v8.2:
    /btc /sol /coin должны быть согласованы с /signal.
    Качественный альт в плохом macro-фоне — это WATCH, а не "0/100 НЕ ПОКУПАТЬ".
    """
    if not c:
        return c

    c = dict(c)
    ctx = c.get("ctx", {})
    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    btc_change = ctx.get("btc_change", 0)
    symbol = c.get("symbol", "")
    group = v6_quality_group(c)

    # Качественные альты в плохом фоне: не BUY, но и не "0/100".
    if (
        symbol not in ["BTC", "ETH"]
        and group in ["quality", "core", "liquid"]
        and macro_mod <= -8
        and btc_change < 0
    ):
        base = 58

        if symbol == "SOL":
            base += 6
        if c.get("rsi", 50) <= 35:
            base += 6
        if c.get("volume_trend", 1) >= 1.1:
            base += 5

        safe_score = min(74, max(c.get("score", 0), base))

        c["score"] = safe_score
        c["_master_score"] = safe_score
        c["verdict"] = "🟡 НАБЛЮДАТЬ / ФОН ПРОТИВ АЛЬТОВ"
        c["action"] = "WATCH"
        c["chance_5"] = min(max(c.get("chance_5", 0), 18), 35)
        c["chance_10"] = min(max(c.get("chance_10", 0), 4), 8)
        c["chance_15"] = min(max(c.get("chance_15", 0), 2), 4)
        c["high"] = max(c.get("high", 0), 2.0)
        c["low"] = min(c.get("low", -1.5), -2.0)
        c["entry_zone"] = "ждать стабилизацию BTC и улучшение внешнего фона"

        c.setdefault("plus", [])
        c.setdefault("minus", [])

        if "технически монета перепродана / близка к отскоку" not in c["plus"] and c.get("rsi", 50) <= 35:
            c["plus"].append("технически монета перепродана / близка к отскоку")

        if "плохой внешний фон для альтов" not in c["minus"]:
            c["minus"].append("плохой внешний фон для альтов")
        if "BTC падает и может утянуть альты ниже" not in c["minus"]:
            c["minus"].append("BTC падает и может утянуть альты ниже")

    # Не даём single-отчёту показывать противоречие: WATCH с очень высоким score.
    if (
        c.get("action") == "WATCH"
        and symbol not in ["BTC", "ETH"]
        and (macro_mod <= -8 or btc_change <= -2)
    ):
        c["score"] = min(c.get("score", 0), 74)
        c["_master_score"] = min(c.get("_master_score", c.get("score", 0)), c["score"])

    price = c.get("price", 0) or 0
    c["target_low"] = price * (1 + c.get("low", 0) / 100)
    c["target_high"] = price * (1 + c.get("high", 0) / 100)

    return c

def single_coin_action_text(c):
    if c.get("_danger_market_cap"):
        return "без входа сейчас; ждать остановку падения"

    if c.get("_danger_alt_cap"):
        return "наблюдать, без входа; вернуться после разворота рынка"

    if c.get("_quality_alt_danger_watch"):
        return "наблюдать, без входа; ждать стабилизацию BTC"

    if c.get("_falling_market_no_buy"):
        return "ждать стабилизацию, быстрый вход запрещён, не ловить нож"

    if c.get("_btc_core_watch"):
        return "наблюдать, ждать стабилизацию, не ловить нож"

    if c.get("_eth_core_watch"):
        return "наблюдать, вход только после подтверждения"

    if c.get("_falling_knife"):
        return "ждать стабилизацию, не ловить нож"
    if c.get("action") == "ACCUM":
        ctx = c.get("ctx", {})
        macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
        btc_change = ctx.get("btc_change", 0)

        if c.get("_cautious_accum"):
            return "наблюдать набор, первая часть только после стабилизации"

        if macro_mod <= -8 or btc_change < 0:
            return "первая малая часть только после стабилизации"

        return "можно начать очень малой частью"
    if c.get("action") == "WATCH":
        return "наблюдать, вход только после подтверждения"
    if c.get("action") == "BUY":
        return "можно рассмотреть вход, но без погони за свечой"
    if c.get("action") == "PUMP":
        return "не догонять, только ждать откат"
    return "не входить"

def single_coin_conditions_text(c):
    ctx = c.get("ctx", {})
    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    btc_change = ctx.get("btc_change", 0)
    symbol = c.get("symbol", "")

    items = []

    if symbol not in ["BTC", "ETH"] and macro_mod <= -8:
        items.append("фон должен улучшиться хотя бы до смешанного")
    if symbol == "BTC" and btc_change < 0:
        items.append("BTC должен перестать падать / закрепиться выше текущей зоны")

    if symbol not in ["BTC", "ETH"] and btc_change < 0:
        items.append("BTC должен перестать падать")
    if c.get("volume_trend", 1) < 1.1:
        items.append("нужен объём выше x1.1")
    if c.get("rsi", 50) < 35:
        if symbol == "BTC":
            items.append("нужна остановка падения после перепроданности")
        else:
            items.append("нужен разворот RSI, а не просто перепроданность")

    if not items:
        items.append("нужно подтверждение движением цены и объёмом")

    text = "Что нужно для улучшения:\n"
    for x in items[:4]:
        text += f"• {x}\n"
    return text

def format_single_coin_report(c):
    ctx = c.get("ctx", {})

    text = (
        f"Версия: {BOT_VERSION}\n\n"
        f"{c['symbol']} — {c.get('verdict', 'нет статуса')}\n"
        f"Тип: {c.get('profile', 'н/д')}\n\n"
        f"Цена: {compact_price(c.get('price'))}\n"
        f"24ч: {c.get('change_24', 0):.2f}%\n"
        f"RSI: {c.get('rsi', 'н/д')} | объём: x{c.get('volume_trend', 'н/д')}\n"
        f"Оценка: {c.get('score', 0)}/100\n"
        f"📚 {c.get('_learning_note', 'самообучение: история накапливается')}\n\n"
        f"{macro_mode_text(ctx)} ({ctx.get('macro_mod', 0):+d})\n"
        f"{compact_market_risk_line(ctx)}\n"
        f"BTC: {ctx.get('btc_text', 'н/д')} | {ctx.get('btc_change', 0):.2f}%\n\n"
        f"Действие: {single_coin_action_text(c)}\n"
        f"Причина: {compact_reason(c)}\n\n"
        f"Сценарий 24ч: {c.get('low', 0)}%…{c.get('high', 0)}%\n"
        f"Диапазон 24ч: ${c.get('target_low', 0):.6g}…${c.get('target_high', 0):.6g}\n\n"
        f"{single_coin_conditions_text(c)}\n"
    )

    if c.get("_danger_market_cap"):
        if c.get("symbol") == "BTC":
            text += "Итог: BTC наблюдать, входа сейчас нет. Вернуться после стабилизации 3–4 часа, роста объёма и прекращения падения."
        elif c.get("symbol") == "ETH":
            text += "Итог: ETH наблюдать, входа сейчас нет. Нужна стабилизация BTC и подтверждение объёмом."
        else:
            text += f"Итог: {c.get('symbol')} только после разворота рынка. Сейчас без входа."
    elif c.get("_danger_alt_cap"):
        text += f"Итог: {c.get('symbol')} — только кандидат после разворота рынка. Сейчас без входа; нужна стабилизация BTC."
    elif c.get("_quality_alt_danger_watch"):
        text += f"Итог: {c.get('symbol')} — качественный актив, но рынок опасный. Сейчас без входа; вернуться после стабилизации BTC, роста объёма и разворота RSI."
    elif c.get("_falling_market_no_buy"):
        if c.get("symbol") in ["BTC", "ETH"]:
            text += "Итог: быстрый BUY запрещён. Перепроданность есть, но рынок падает — ждать стабилизацию и не ловить нож."
        else:
            text += "Итог: рынок падает, по альтам сейчас только наблюдение. Вход после стабилизации BTC."
    elif c.get("_btc_core_watch"):
        text += "Итог: BTC перепродан, но покупать сразу рано. Ждать стабилизацию и не ловить нож."
    elif c.get("action") == "WATCH":
        text += "Итог: сейчас лучше наблюдать. Вход только после стабилизации BTC/фона и подтверждения объёмом."
    elif c.get("action") == "ACCUM":
        if c.get("symbol") == "BTC":
            text += "Итог: BTC интересен только как осторожное наблюдение/среднесрок. Вход после стабилизации, не ловить нож."
        elif c.get("_red_market_cap"):
            text += "Итог: идея только после стабилизации рынка. Пока score ограничен из-за плохого фона."
        else:
            text += "Итог: идея только для частичного набора после стабилизации. Без входа всей суммой."
    elif c.get("action") == "BUY":
        text += "Итог: сигнал есть, но вход только частями и без погони за свечой."
    else:
        text += "Итог: сейчас вход не подходит."

    return text



def v84_apply_btc_core_asset_fix(c):
    """
    v8.4:
    BTC/ETH — базовые активы. При сильной перепроданности они не должны
    превращаться в "0/100 НЕ ПОКУПАТЬ". Это не BUY, а режим наблюдения /
    осторожного набора только после стабилизации.
    """
    if not c:
        return c

    c = dict(c)
    symbol = c.get("symbol", "")
    ctx = c.get("ctx", {})
    fg_value = ctx.get("fg_value", 50)
    btc_change = ctx.get("btc_change", 0)
    rsi_value = c.get("rsi", 50)
    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))

    # Главный фикс: BTC при RSI < 30 и страхе не должен быть 0/100.
    if (
        symbol == "BTC"
        and rsi_value < 30
        and fg_value <= 30
        and c.get("action") not in ["BUY", "ACCUM"]
    ):
        base_score = 61 if rsi_value < 28 else 58
        if btc_change <= -2.5:
            base_score = 64

        c["score"] = max(c.get("score", 0), base_score)
        c["_master_score"] = max(c.get("_master_score", c.get("score", 0)), c["score"])
        c["score"] = min(c["score"], 68)
        c["_master_score"] = min(c["_master_score"], c["score"])

        c["verdict"] = "🟡 НАБЛЮДАТЬ / BTC ПЕРЕПРОДАН"
        c["action"] = "WATCH"
        c["_btc_core_watch"] = True
        c["chance_5"] = max(c.get("chance_5", 0), 25)
        c["chance_10"] = max(c.get("chance_10", 0), 6)
        c["chance_15"] = max(c.get("chance_15", 0), 3)
        c["low"] = min(c.get("low", -1.5), -2.5)
        c["high"] = max(c.get("high", 0), 3.5)
        c["entry_zone"] = "ждать стабилизацию BTC: не ловить нож, первая часть только после остановки падения"

        c.setdefault("plus", [])
        c.setdefault("minus", [])

        if "BTC сильно перепродан по RSI" not in c["plus"]:
            c["plus"].append("BTC сильно перепродан по RSI")
        if "страх на рынке может дать среднесрочную точку" not in c["plus"]:
            c["plus"].append("страх на рынке может дать среднесрочную точку")

        if btc_change < 0 and "падение BTC ещё не остановилось" not in c["minus"]:
            c["minus"].append("падение BTC ещё не остановилось")
        if macro_mod <= -8 and "плохой внешний фон добавляет риск" not in c["minus"]:
            c["minus"].append("плохой внешний фон добавляет риск")

    # ETH тоже не обнуляем, если он перепродан, но среднесрочный режим почему-то не включился.
    if (
        symbol == "ETH"
        and rsi_value < 35
        and fg_value <= 30
        and c.get("action") not in ["BUY", "ACCUM", "WATCH"]
    ):
        c["score"] = max(c.get("score", 0), 62)
        c["_master_score"] = max(c.get("_master_score", c.get("score", 0)), c["score"])
        c["score"] = min(c["score"], 72)
        c["_master_score"] = min(c["_master_score"], c["score"])

        c["verdict"] = "🟡 НАБЛЮДАТЬ / ETH ПЕРЕПРОДАН"
        c["action"] = "WATCH"
        c["_eth_core_watch"] = True
        c["chance_5"] = max(c.get("chance_5", 0), 25)
        c["chance_10"] = max(c.get("chance_10", 0), 7)
        c["chance_15"] = max(c.get("chance_15", 0), 3)
        c["low"] = min(c.get("low", -1.5), -2.5)
        c["high"] = max(c.get("high", 0), 3.5)
        c["entry_zone"] = "ждать стабилизацию: первая малая часть только после подтверждения"

        c.setdefault("plus", [])
        c.setdefault("minus", [])
        if "ETH перепродан и может дать отскок" not in c["plus"]:
            c["plus"].append("ETH перепродан и может дать отскок")
        if "рынок ещё слабый, вход только после стабилизации" not in c["minus"]:
            c["minus"].append("рынок ещё слабый, вход только после стабилизации")

    price = c.get("price", 0) or 0
    c["target_low"] = price * (1 + c.get("low", 0) / 100)
    c["target_high"] = price * (1 + c.get("high", 0) / 100)

    return c



def v100_apply_single_coin_danger_watch_fix(c):
    """
    v10.0:
    В подробном отчёте по качественным альтам не показываем 0/100 и "🔴 НЕ ПОКУПАТЬ",
    если монета нормальная, но рынок опасный. Это не BUY, а режим WATCH.
    """
    if not c:
        return c

    c = dict(c)
    symbol = c.get("symbol", "")
    ctx = c.get("ctx", {})

    if symbol in ["BTC", "ETH"]:
        return c

    group = v6_quality_group(c)
    danger = market_risk_level(ctx) == "danger" or v94_falling_market(ctx)

    if not danger:
        return c

    if group not in ["quality", "liquid"]:
        return c

    # Исправляем только грубый SKIP/0, чтобы не ломать реальные WATCH/BUY-ограничения.
    if c.get("action") in ["SKIP", "WATCH"] or c.get("score", 0) < 45 or "НЕ ПОКУПАТЬ" in c.get("verdict", ""):
        base = 58

        if symbol in ["SOL", "LINK", "SUI", "AAVE", "BNB", "XRP", "ADA", "AVAX", "NEAR", "INJ", "TAO"]:
            base = 60

        if c.get("change_24", 0) <= -8:
            base -= 4

        if c.get("volume_trend", 1) < 0.6:
            base -= 3

        if c.get("rsi", 50) < 30:
            base -= 2

        score = max(c.get("score", 0), base)
        score = max(55, min(65, int(score)))

        c["score"] = score
        c["_master_score"] = score
        c["action"] = "WATCH"
        c["verdict"] = "🟡 НАБЛЮДАТЬ / РЫНОК ОПАСНЫЙ"
        c["_quality_alt_danger_watch"] = True

        c["chance_5"] = min(max(c.get("chance_5", 0), 12), 22)
        c["chance_10"] = min(max(c.get("chance_10", 0), 2), 5)
        c["chance_15"] = min(max(c.get("chance_15", 0), 1), 3)

        c["low"] = min(c.get("low", -2.0), -3.0)
        c["high"] = min(max(c.get("high", 0), 1.5), 2.0)
        c["entry_zone"] = "без входа: ждать стабилизацию BTC, рост объёма и разворот RSI"

        c.setdefault("minus", [])
        for reason in [
            "рынок опасный: BTC падает и страх высокий",
            "для альта нужен разворот BTC",
            "объём/RSI пока не подтверждают вход"
        ]:
            if reason not in c["minus"]:
                c["minus"].append(reason)

        price = c.get("price", 0) or 0
        c["target_low"] = price * (1 + c.get("low", 0) / 100)
        c["target_high"] = price * (1 + c.get("high", 0) / 100)

    return c


def v101_apply_danger_market_score_cap(c):
    """
    v10.1:
    Если риск рынка 🔴 опасный, позитивные новости не должны перебивать страх и падение BTC.
    BTC/ETH и альты не должны выглядеть как сильный сигнал при BUY запрещены.
    """
    if not c:
        return c

    c = dict(c)
    symbol = c.get("symbol", "")
    ctx = c.get("ctx", {})

    btc_change = ctx.get("btc_change", 0)
    fg_value = ctx.get("fg_value", 50)

    if symbol == "BTC" and (btc_change == 0 or "не удалось" in ctx.get("btc_text", "")):
        btc_change = c.get("change_24", btc_change)
        ctx = dict(ctx)
        ctx["btc_change"] = btc_change
        if btc_change <= -2:
            ctx["btc_text"] = "BTC мешает рынку"
            ctx["btc_mod"] = -12
        ctx["risk_level"] = market_risk_level(ctx)
        c["ctx"] = ctx

    danger = market_risk_level(ctx) == "danger"
    if not danger:
        return c

    # BTC/ETH: только наблюдение/стабилизация, без "первая часть" и без 90+ score.
    if symbol in ["BTC", "ETH"] and c.get("action") in ["BUY", "PUMP", "ACCUM", "WATCH", "SKIP"]:
        cap = 68 if symbol == "BTC" else 70

        # При совсем слабом рынке ещё жёстче.
        if btc_change <= -4 or fg_value <= 15:
            cap = 65 if symbol == "BTC" else 68

        # Не обнуляем базовые активы, но и не оставляем 74/98.
        current = int(c.get("score", 0) or 0)
        score = min(max(current, 55), cap)

        c["score"] = score
        c["_master_score"] = score
        c["_accumulation_score"] = score

        # В /signal можно оставить в разделе наблюдения за крупными активами,
        # но в тексте не называем это среднесрочным входом.
        c["action"] = "ACCUM"
        c["verdict"] = "🟡 НАБЛЮДАТЬ / ЖДАТЬ СТАБИЛИЗАЦИЮ"
        c["_danger_market_cap"] = True
        c["_red_market_cap"] = True

        c["chance_5"] = min(max(c.get("chance_5", 0), 10), 22)
        c["chance_10"] = min(max(c.get("chance_10", 0), 2), 5)
        c["chance_15"] = min(max(c.get("chance_15", 0), 1), 3)

        c["low"] = min(c.get("low", -2.0), -3.0)
        c["high"] = min(max(c.get("high", 0), 1.5), 2.8 if symbol == "BTC" else 3.0)

        c["entry_zone"] = "без входа сейчас: ждать остановку падения, стабилизацию 3–4 часа и рост объёма"

        c.setdefault("minus", [])
        for reason in [
            "риск рынка опасный: страх высокий и BTC падает",
            "позитивные новости не перебивают риск",
            "без входа сейчас, ждать стабилизацию"
        ]:
            if reason not in c["minus"]:
                c["minus"].append(reason)

    # Альты: кандидаты только после разворота, score не должен выглядеть как почти BUY.
    elif symbol not in ["BTC", "ETH"]:
        if c.get("score", 0) >= 50 or c.get("action") in ["BUY", "PUMP", "WATCH", "ACCUM"]:
            current = int(c.get("score", 0) or 0)
            score = min(max(current, 55), 65)

            c["score"] = score
            c["_master_score"] = score
            c["action"] = "WATCH"
            c["verdict"] = "🟡 КАНДИДАТ ПОСЛЕ РАЗВОРОТА РЫНКА"
            c["_danger_alt_cap"] = True
            c["_red_market_cap"] = True

            c["chance_5"] = min(max(c.get("chance_5", 0), 10), 20)
            c["chance_10"] = min(max(c.get("chance_10", 0), 2), 5)
            c["chance_15"] = min(max(c.get("chance_15", 0), 1), 3)
            c["high"] = min(max(c.get("high", 0), 1.5), 2.5)
            c["low"] = min(c.get("low", -2.0), -3.0)
            c["entry_zone"] = "после разворота рынка: нужна стабилизация BTC и подтверждение объёмом"

            c.setdefault("minus", [])
            for reason in [
                "после разворота рынка",
                "нужна стабилизация BTC",
                "без входа сейчас"
            ]:
                if reason not in c["minus"]:
                    c["minus"].append(reason)

    price = c.get("price", 0) or 0
    c["target_low"] = price * (1 + c.get("low", 0) / 100)
    c["target_high"] = price * (1 + c.get("high", 0) / 100)

    return c

def single_analysis(symbol):
    c = alex_edge_ultra(symbol)

    if not c:
        return f"Версия: {BOT_VERSION}\nМонета не найдена."

    c = v6_apply_single_score_engine(c)
    c = v82_apply_single_coin_consistency(c)
    c = v84_apply_btc_core_asset_fix(c)
    c = v87_apply_alt_accum_fix(c)
    c = v83_apply_self_learning(c)
    c = v88_apply_red_market_score_cap(c)
    c = v94_apply_falling_market_no_buy(c)
    c = v100_apply_single_coin_danger_watch_fix(c)
    c = v101_apply_danger_market_score_cap(c)

    return format_single_coin_report(c)

def market_status():
    ctx = market_context()
    level = ctx.get("risk_level", "neutral")

    if level == "danger":
        status = "🔴 ОПАСНЫЙ РЫНОК"
    elif level == "caution":
        status = "🟡 ОСТОРОЖНО"
    elif level == "positive":
        status = "🟢 ФОН ПОМОГАЕТ"
    else:
        status = "🟡 НЕЙТРАЛЬНО"

    btc_change = ctx.get("btc_change", 0)
    fg_value = ctx.get("fg_value", 50)

    text = (
        f"🌍 Рынок\n"
        f"Версия: {BOT_VERSION}\n\n"
        f"Статус: {status}\n"
        f"BTC 24ч: {btc_change:.2f}% — {ctx.get('btc_text', 'н/д')}\n"
        f"Страх/жадность: {fg_value} — {ctx.get('fg_text', 'н/д')}\n"
    )

    if ctx.get("dom_text"):
        text += f"Dominance: {ctx['dom_text']}\n"

    text += (
        f"Новости: {compact_news_line(ctx)}\n\n"
        f"{macro_action_hint(ctx)}\n\n"
        f"Что ждём для улучшения:\n"
    )

    for item in market_improvement_plan(ctx):
        text += f"• {item}\n"

    return text.strip()

def help_text():
    return (
        f"Версия бота: {BOT_VERSION}\n\n"
        "Главные кнопки:\n"
        "📊 Сигнал — общий отчёт\n"
        "🔎 Монета — список популярных монет + ручной поиск\n"
        "🟠 BTC / 🟣 SOL — быстрый подробный анализ\n"
        "🌍 Рынок — внешний фон\n"
        "⚡ Alerts — ручная проверка быстрых импульсов\n"
        "📚 Обучение — результаты самообучения\n"
        "🏆 Топ — топ монет по объёму\n"
        "⚙️ Версия — текущая версия\n\n"
        "Команды тоже работают:\n"
        "/signal, /btc, /sol, /coin ETH, /market, /alerts, /learning, /top\n"
        "TON вводить можно: бот автоматически откроет GRAM.\n\n"
        "Статусы:\n"
        "🟢 ПОКУПКА — можно рассмотреть вход частями\n"
        "🟦 СРЕДНЕСРОЧНЫЙ НАБОР — сначала стабилизация, потом малая часть\n"
        "🟡 НАБЛЮДАТЬ — пока не покупать\n"
        "🟠 ЖДАТЬ ОТКАТ — движение есть, но вход с рынка поздний\n"
        "🔴 НЕ ПОКУПАТЬ — лучше пропустить\n\n"
        "🤖 Автопокупки выключены: бот только анализирует и учится\n"
        "🔕 Auto-alerts тихие: только качественные монеты, максимум 1 раз в час\n"
        "📚 Обучение без дублей: одна монета = одно открытое наблюдение до 48ч\n"
        "🧯 Красный рынок: score BTC/ETH ограничен до стабилизации\n"
        "📰 Новости: ФРС/геополитика/крипто обновляются по RSS-заголовкам каждые 15 минут\n🧠 v9.6: deal/ceasefire/end war/reopen Hormuz считаются деэскалацией, слабые источники получают меньший вес; v10.4: /alerts больше не молчит — показывает статус, ближайшие наблюдения и мягче ловит качественные импульсы"
    )


def coin_analyze_wait_text(coin):
    return f"⏳ Анализирую {coin}, подожди 10–30 секунд..."

def moscow_now():
    return datetime.utcnow() + timedelta(hours=MOSCOW_OFFSET_HOURS)

def main():
    last_update = None
    last_signal_key = None
    last_market_key = None
    last_pump_key = None
    coin_search_waiting = set()
    last_coin_search_prompt_time = {}
    last_coin_analysis_time = {}
    last_manual_market_time = 0

    while True:
        try:
            updates = get_updates(last_update)

            for item in updates.get("result", []):
                last_update = item["update_id"] + 1

                msg = item.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                raw_text = (msg.get("text", "") or "").strip()
                text = normalize_button_text(raw_text)

                if not chat_id:
                    continue

                save_chat_id(chat_id)

                if raw_text in SEARCH_BUTTONS:
                    coin_search_waiting.add(chat_id)
                    now_ts = time.time()
                    if now_ts - float(last_coin_search_prompt_time.get(chat_id, 0) or 0) > 3:
                        send_message(chat_id, coin_search_prompt(), reply_markup=coin_keyboard())
                        last_coin_search_prompt_time[chat_id] = now_ts
                    continue

                if raw_text in BACK_BUTTONS:
                    coin_search_waiting.discard(chat_id)
                    send_message(chat_id, "Главное меню.", reply_markup=keyboard())
                    continue

                if raw_text in MANUAL_COIN_BUTTONS:
                    coin_search_waiting.add(chat_id)
                    send_message(
                        chat_id,
                        "✍️ Введи тикер монеты обычным сообщением. Например: ETH, SUI, LINK, GRAM.",
                        reply_markup=keyboard()
                    )
                    continue

                if chat_id in coin_search_waiting and not text.startswith("/"):
                    coin = resolve_coin_symbol(raw_text)

                    if coin in POPULAR_COINS or (coin and len(coin) >= 2 and len(coin) <= 12):
                        coin_search_waiting.discard(chat_id)
                        coin_key = f"{chat_id}:{coin}"
                        now_ts = time.time()

                        # Защита от дубля: иногда Telegram/Render может прислать одно нажатие дважды.
                        if now_ts - float(last_coin_analysis_time.get(coin_key, 0) or 0) > 8:
                            last_coin_analysis_time[coin_key] = now_ts
                            send_message(chat_id, coin_analyze_wait_text(coin))
                            send_message(chat_id, single_analysis(f"{coin}-USDT"))
                    else:
                        send_message(chat_id, "Не понял тикер. Напиши, например: ETH, SOL, SUI или LINK.")

                    continue

                if resolve_coin_symbol(raw_text) in POPULAR_COINS:
                    coin = resolve_coin_symbol(raw_text)
                    coin_key = f"{chat_id}:{coin}"
                    now_ts = time.time()

                    if now_ts - float(last_coin_analysis_time.get(coin_key, 0) or 0) > 8:
                        last_coin_analysis_time[coin_key] = now_ts
                        send_message(chat_id, coin_analyze_wait_text(coin))
                        send_message(chat_id, single_analysis(f"{coin}-USDT"))
                    continue

                if text.startswith("/") and chat_id in coin_search_waiting:
                    coin_search_waiting.discard(chat_id)

                if text == "/start":
                    send_message(chat_id, "✅ Бот работает\nНижнее меню обновлено: аккуратные кнопки BTC/SOL и список монет с GRAM.\n\n" + help_text())

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
                        coin_search_waiting.add(chat_id)
                        send_message(chat_id, coin_search_prompt(), reply_markup=coin_keyboard())
                    else:
                        coin = resolve_coin_symbol(parts[1])
                        coin_key = f"{chat_id}:{coin}"
                        now_ts = time.time()

                        if now_ts - float(last_coin_analysis_time.get(coin_key, 0) or 0) > 8:
                            last_coin_analysis_time[coin_key] = now_ts
                            send_message(chat_id, coin_analyze_wait_text(coin))
                            send_message(chat_id, single_analysis(f"{coin}-USDT"))

                elif text == "/market" or text == "/macro":
                    now_ts = time.time()
                    if now_ts - last_manual_market_time > 20:
                        send_message(chat_id, market_status())
                        last_manual_market_time = now_ts

                elif text == "/learning":
                    send_message(chat_id, learning_report())

                elif text == "/alerts":
                    send_message(chat_id, "⏳ Проверяю быстрые пампы...")
                    text_alert, _ = get_fast_pumps()

                    if text_alert:
                        send_message(chat_id, text_alert)
                    else:
                        send_message(chat_id, f"Версия: {BOT_VERSION}\nСейчас быстрых импульсов нет.")

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

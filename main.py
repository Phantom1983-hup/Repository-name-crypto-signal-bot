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

QUALITY_ASSETS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX",
    "LINK", "TON", "DOGE", "NEAR", "TAO", "DOT", "LTC"
]

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
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text, "reply_markup": keyboard()},
        timeout=20
    )

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    return requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
        params=params,
        timeout=40
    ).json()

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
    data = requests.get(
        "https://api.kucoin.com/api/v1/market/candles",
        params={"symbol": symbol, "type": interval},
        timeout=20
    ).json()

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

def coin_profile(asset, volume):
    if asset == "BTC":
        return "надежный крупный актив", 0.5, 2.8, True

    if asset == "ETH":
        return "крупный актив", 0.8, 3.8, True

    if asset in QUALITY_ASSETS:
        return "крупный альт", 1.2, 6.0, True

    if volume >= 30_000_000:
        return "ликвидный, но рискованный альт", 1.5, 7.0, False

    return "спекулятивный альт", 1.5, 8.0, False

def rsi_series(closes, period=14):
    result = []

    for i in range(len(closes)):
        if i < period + 1:
            result.append(50)
        else:
            result.append(rsi(closes[:i + 1], period))

    return result

def divergence_check(closes, rsi_values):
    if len(closes) < 20 or len(rsi_values) < 20:
        return 0

    price_recent = max(closes[-6:])
    price_prev = max(closes[-18:-6])

    rsi_recent = max(rsi_values[-6:])
    rsi_prev = max(rsi_values[-18:-6])

    if price_recent > price_prev and rsi_recent < rsi_prev:
        return -12

    if price_recent < price_prev and rsi_recent > rsi_prev:
        return 8

    return 0

def trend_score(symbol, interval):
    closes, highs, lows, volumes = get_candles(symbol, interval)

    if len(closes) < 30:
        return {
            "score": 0,
            "rsi": 50,
            "macd": 0,
            "volume_x": 1,
            "support": 0,
            "resistance": 0,
            "atr_pct": 0,
            "buyers": "непонятно",
            "overheat": "непонятно",
            "trend": "непонятно"
        }

    last = closes[-1]
    r = rsi(closes)
    rsis = rsi_series(closes)
    div = divergence_check(closes, rsis)

    e9 = ema(closes[-60:], 9)
    e21 = ema(closes[-60:], 21)
    e50 = ema(closes[-100:], 50)
    m = macd(closes)
    vx = volume_spike(volumes)
    a = atr(highs, lows, closes)
    atr_pct = (a / last) * 100 if last else 0

    score = 0

    if e9 and e21 and e9 > e21:
        score += 15

    if e21 and e50 and e21 > e50:
        score += 15

    if m > 0:
        score += 15

    if vx >= 2:
        score += 18
    elif vx >= 1.2:
        score += 8
    elif vx < 0.8:
        score -= 20

    if 45 <= r <= 70:
        score += 18
    elif 70 < r <= 78:
        score += 8
    elif 78 < r <= 86:
        score -= 5
    elif r > 86:
        score -= 18

    price_above_mean = last > statistics.mean(closes[-20:])
    higher_lows = lows[-1] > min(lows[-10:-1])
    local_breakout = last > max(highs[-12:-1])

    if price_above_mean:
        score += 8

    if higher_lows:
        score += 8

    if local_breakout and vx >= 1.2:
        score += 12
    elif local

from flask import Flask
from threading import Thread, Lock
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
import os, time, json, requests, statistics, re, base64
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
BOT_VERSION = "v18.0 ALEX EDGE CORE"

# === v11.0 persistent storage ===
# Для Render Persistent Disk лучше указать DATA_DIR=/var/data.
# Если /var/data есть — используем его автоматически. Иначе файлы будут рядом с main.py.
DATA_DIR = (os.getenv("DATA_DIR") or "").strip()
if not DATA_DIR:
    DATA_DIR = "/var/data" if os.path.isdir("/var/data") else "."

try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = "."

def data_path(name):
    return os.path.join(DATA_DIR, name)

CHAT_ID_FILE = data_path("chat_id.txt")
HISTORY_FILE = data_path("signal_history.json")
PUMP_FILE = data_path("pump_history.json")
RESULTS_FILE = data_path("signal_results.json")
RESULTS_BACKUP_FILE = data_path("signal_results_backup.json")
FROZEN_RESULTS_FILE = data_path("frozen_learning_results.json")
WEEKDAY_FILE = data_path("weekday_market_stats.json")
BACKTEST_FILE = data_path("historical_backtest_stats.json")
PAPER_TRADES_FILE = data_path("paper_trades.json")
ADMIN_STATE_FILE = data_path("admin_deploy_state.json")
ADMIN_UPLOAD_FILE = data_path("admin_uploaded_main.py")
ADMIN_UPLOAD_LOCK_FILE = data_path("admin_upload_lock.json")
LAST_UPDATE_FILE = data_path("last_update_id.txt")
SIGNAL_LOCK_FILE = data_path("signal_lock.json")
DEPLOY_NOTIFY_FILE = data_path("deploy_notify.json")
SIGNAL_JOB_FILE = data_path("signal_job.json")
SIGNAL_LOCK_TTL = int(os.getenv("SIGNAL_LOCK_TTL", "600"))

# === v11.0 admin auto deploy ===
# Все секреты хранить только в Render Environment.
ADMIN_CHAT_ID = (os.getenv("ADMIN_CHAT_ID") or "").strip()
GITHUB_TOKEN = (os.getenv("GITHUB_TOKEN") or "").strip()
GITHUB_REPO = (os.getenv("GITHUB_REPO") or "").strip()          # example: owner/repo
GITHUB_BRANCH = (os.getenv("GITHUB_BRANCH") or "main").strip()
GITHUB_PATH = (os.getenv("GITHUB_PATH") or "main.py").strip()
RENDER_DEPLOY_HOOK_URL = (os.getenv("RENDER_DEPLOY_HOOK_URL") or "").strip()

# === v11.1 free storage option ===
# Для бесплатного Render Persistent Disk недоступен.
# Поэтому можно хранить json-статистику в GitHub repo: data/*.json.
GITHUB_DATA_STORAGE = (os.getenv("GITHUB_DATA_STORAGE") or "").strip().lower() in ["1", "true", "yes", "on"]
GITHUB_DATA_DIR = (os.getenv("GITHUB_DATA_DIR") or "data").strip().strip("/")
_GITHUB_JSON_CACHE = {}
_GITHUB_DIRTY_FILES = set()
_GITHUB_LAST_SYNC = {}

SIGNAL_HOURS = [9, 15, 21]
MARKET_HOUR = 9
PUMP_MINUTES = [0]

# v13.8:
# Автоматические сообщения по расписанию выключены по умолчанию.
# Причина: утренний auto-scheduler запускал старый background /signal и мог присылать
# дубли/устаревший отчёт с BUY по спекулятивным монетам.
# Ручные кнопки 📊 Сигнал / 🌍 Рынок / ⚡ Alerts продолжают работать.
AUTO_REPORTS_ENABLED = (os.getenv("AUTO_REPORTS_ENABLED") or "").strip().lower() in ["1", "true", "yes", "on"]

# === v15.0 fast learning ===
# 48ч остаётся финальной проверкой, но бот копит короткие checkpoints,
# чтобы обучение не простаивало по 2 суток.
FAST_LEARNING_BACKGROUND_ENABLED = (os.getenv("FAST_LEARNING_BACKGROUND_ENABLED") or "1").strip().lower() in ["1", "true", "yes", "on"]
FAST_LEARNING_BACKGROUND_INTERVAL = int(os.getenv("FAST_LEARNING_BACKGROUND_INTERVAL", "1800"))  # v17.6.2: 30 минут, чтобы fast-learning быстрее ловил 15м/30м/1ч checkpoints
_fast_learning_background_last = 0


MOSCOW_OFFSET_HOURS = 3

REPEAT_PUMP_AFTER = 4 * 60 * 60
ANALYZE_LIMIT = int(os.getenv("ANALYZE_LIMIT", "35"))
COIN_ANALYSIS_WORKERS = int(os.getenv("COIN_ANALYSIS_WORKERS", "8"))
SIGNAL_TIME_BUDGET = int(os.getenv("SIGNAL_TIME_BUDGET", "75"))
SIGNAL_HARD_TIMEOUT = int(os.getenv("SIGNAL_HARD_TIMEOUT", "130"))
SIGNAL_QUICK_COINS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "NEAR-USDT", "SUI-USDT", "LINK-USDT"]
QUALITY_LEARNING_ASSETS = {"BTC", "ETH", "SOL", "BNB", "LINK", "SUI", "NEAR", "TAO", "AAVE", "ADA", "AVAX", "INJ"}
STABLE_SKIP_ASSETS = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDD", "USDP", "USD1"}
CANDLE_TIMEOUT = int(os.getenv("CANDLE_TIMEOUT", "5"))
NEWS_TIMEOUT = int(os.getenv("NEWS_TIMEOUT", "4"))
ALERTS_ANALYZE_LIMIT = int(os.getenv("ALERTS_ANALYZE_LIMIT", "28"))
ALERTS_WORKERS = int(os.getenv("ALERTS_WORKERS", "8"))
ALERTS_TIME_BUDGET = int(os.getenv("ALERTS_TIME_BUDGET", "35"))
ALERTS_CANDLE_TIMEOUT = int(os.getenv("ALERTS_CANDLE_TIMEOUT", "3"))

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
_market_context_cache = {"time": 0, "data": None}

def github_storage_enabled():
    return bool(GITHUB_DATA_STORAGE and GITHUB_TOKEN and GITHUB_REPO and GITHUB_BRANCH)

def github_storage_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

def github_storage_repo_path(local_path):
    name = os.path.basename(str(local_path))
    return f"{GITHUB_DATA_DIR}/{name}"

def github_storage_contents_url(repo_path):
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_path}"

def github_storage_get_raw(local_path):
    if not github_storage_enabled():
        return None, None

    repo_path = github_storage_repo_path(local_path)

    r = requests.get(
        github_storage_contents_url(repo_path),
        headers=github_storage_headers(),
        params={"ref": GITHUB_BRANCH},
        timeout=30
    )

    if r.status_code == 404:
        return None, None

    if r.status_code >= 300:
        raise Exception(f"GitHub storage GET error {r.status_code}: {r.text[:500]}")

    info = r.json()
    content = base64.b64decode(info.get("content", "") or b"")
    return content, info.get("sha")

def github_storage_put_raw(local_path, content_bytes, message=None):
    if not github_storage_enabled():
        return False

    repo_path = github_storage_repo_path(local_path)

    try:
        _, sha = github_storage_get_raw(local_path)
    except Exception:
        sha = None

    payload = {
        "message": message or f"update storage {os.path.basename(str(local_path))}",
        "content": base64.b64encode(content_bytes).decode("ascii"),
        "branch": GITHUB_BRANCH
    }

    if sha:
        payload["sha"] = sha

    r = requests.put(
        github_storage_contents_url(repo_path),
        headers=github_storage_headers(),
        json=payload,
        timeout=40
    )

    if r.status_code >= 300:
        raise Exception(f"GitHub storage PUT error {r.status_code}: {r.text[:700]}")

    return True

def mark_github_dirty(path):
    if github_storage_enabled():
        _GITHUB_DIRTY_FILES.add(str(path))

def sync_github_storage_now(paths=None, max_files=6):
    """
    v11.2:
    GitHub storage не должен тормозить /signal.
    Поэтому save_json только пишет локально и помечает файл dirty,
    а sync в GitHub делается пачкой после тяжёлой команды.
    """
    if not github_storage_enabled():
        return 0

    if paths:
        todo = [str(p) for p in paths if p]
    else:
        todo = list(_GITHUB_DIRTY_FILES)

    synced = 0

    for path in todo[:max_files]:
        if not os.path.exists(path):
            continue

        try:
            with open(path, "rb") as f:
                content = f.read()

            github_storage_put_raw(
                path,
                content,
                f"update storage {os.path.basename(str(path))}"
            )

            _GITHUB_DIRTY_FILES.discard(str(path))
            _GITHUB_LAST_SYNC[str(path)] = time.time()
            synced += 1

        except Exception as e:
            print(f"GitHub storage sync error {path}: {e}")

    return synced

def background_github_sync(paths=None, max_files=5):
    """
    v11.7:
    GitHub sync не должен задерживать ответ /signal.
    Синхронизацию запускаем в отдельном потоке после отправки отчёта.
    """
    if not github_storage_enabled():
        return False

    def _run():
        try:
            sync_github_storage_now(paths, max_files=max_files)
        except Exception as e:
            print(f"background github sync error: {e}")

    try:
        Thread(target=_run, daemon=True).start()
        return True
    except Exception as e:
        print(f"background sync start error: {e}")
        return False

def save_chat_id(chat_id):
    text = str(chat_id)

    old = None
    try:
        old = open(CHAT_ID_FILE, encoding="utf-8").read().strip()
    except Exception:
        old = None

    try:
        with open(CHAT_ID_FILE, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass

    if text != old:
        mark_github_dirty(CHAT_ID_FILE)

def load_chat_id():
    # В обычной работе читаем локально — это быстро.
    # В GitHub идём только если после redeploy локального файла ещё нет.
    try:
        text = open(CHAT_ID_FILE, encoding="utf-8").read().strip()
        if text:
            return text
    except Exception:
        pass

    if github_storage_enabled():
        try:
            raw, _ = github_storage_get_raw(CHAT_ID_FILE)
            if raw:
                text = raw.decode("utf-8", errors="ignore").strip()
                if text:
                    try:
                        with open(CHAT_ID_FILE, "w", encoding="utf-8") as f:
                            f.write(text)
                    except Exception:
                        pass
                    return text
        except Exception:
            pass

    return None

def save_last_update_id(update_id):
    text = str(update_id)

    try:
        with open(LAST_UPDATE_FILE, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass

    mark_github_dirty(LAST_UPDATE_FILE)

def load_last_update_id():
    try:
        text = open(LAST_UPDATE_FILE, encoding="utf-8").read().strip()
        if text:
            return int(text)
    except Exception:
        pass

    # GitHub storage: после redeploy подтягиваем последний обработанный update_id.
    if github_storage_enabled():
        try:
            raw, _ = github_storage_get_raw(LAST_UPDATE_FILE)
            if raw:
                text = raw.decode("utf-8", errors="ignore").strip()
                if text:
                    try:
                        with open(LAST_UPDATE_FILE, "w", encoding="utf-8") as f:
                            f.write(text)
                    except Exception:
                        pass
                    return int(text)
        except Exception:
            pass

    return None

def is_stale_telegram_message(msg, max_age_seconds=240):
    """
    v11.3:
    После redeploy Telegram может отдать старые нажатия кнопки /signal.
    Такие старые команды нельзя выполнять, иначе бот часами шлёт "Ищу монеты...".
    """
    try:
        msg_date = int(msg.get("date", 0) or 0)
        return msg_date > 0 and time.time() - msg_date > max_age_seconds
    except Exception:
        return False

def load_json(path):
    # GitHub storage: бесплатная замена Render Persistent Disk.
    # Важно: читаем из GitHub только если локального файла нет.
    cache_key = str(path)
    cached = _GITHUB_JSON_CACHE.get(cache_key)

    if cached and time.time() - cached.get("time", 0) < 10:
        return cached.get("data", {})

    try:
        data = json.load(open(path, encoding="utf-8"))
        _GITHUB_JSON_CACHE[cache_key] = {"time": time.time(), "data": data}
        return data
    except Exception:
        pass

    if github_storage_enabled():
        try:
            raw, _ = github_storage_get_raw(path)
            if raw:
                data = json.loads(raw.decode("utf-8", errors="ignore"))
                _GITHUB_JSON_CACHE[cache_key] = {"time": time.time(), "data": data}
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
                return data
        except Exception:
            pass

    return {}

def _raw_load_json_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _results_counts(data):
    if not isinstance(data, dict):
        return 0, 0
    open_items = data.get("open", {})
    closed_items = data.get("closed", [])
    open_n = len(open_items) if isinstance(open_items, dict) else 0
    closed_n = len(closed_items) if isinstance(closed_items, list) else 0
    return open_n, closed_n

def _closed_identity(rec):
    if not isinstance(rec, dict):
        return None
    asset = str(rec.get("asset", "?")).upper()
    try:
        ts = int(float(rec.get("time", 0) or 0))
    except Exception:
        ts = 0
    try:
        price = round(float(rec.get("price", 0) or 0), 8)
    except Exception:
        price = 0
    return f"{asset}:{ts}:{price}"

def _merge_closed_records(*lists):
    merged = []
    seen = set()
    for items in lists:
        if not isinstance(items, list):
            continue
        for rec in items:
            if not isinstance(rec, dict):
                continue
            key = _closed_identity(rec) or str(id(rec))
            if key in seen:
                continue
            seen.add(key)
            merged.append(rec)
    return merged[-800:]

def _closed_from_frozen_store_data(store):
    out = []
    try:
        records = store.get("records", {}) if isinstance(store, dict) else {}
        if not isinstance(records, dict):
            return []
        for key, fr in records.items():
            if not isinstance(fr, dict):
                continue
            results = fr.get("results") if isinstance(fr.get("results"), dict) else {}
            if not results:
                continue
            rec = {
                "asset": str(fr.get("asset", "?")),
                "time": float(fr.get("time", 0) or 0),
                "price": fr.get("price", 0),
                "score": fr.get("score", 0),
                "master_score": fr.get("score", 0),
                "action": fr.get("action", "WATCH"),
                "verdict": fr.get("verdict", ""),
                "results": dict(results),
                "frozen_results": dict(results),
                "result_details": fr.get("result_details", {}) if isinstance(fr.get("result_details"), dict) else {},
                "frozen_result_details": fr.get("result_details", {}) if isinstance(fr.get("result_details"), dict) else {},
                "outcome": fr.get("outcome"),
                "frozen_outcome": fr.get("outcome"),
                "frozen_at": fr.get("frozen_at", time.time()),
                "closed_time": fr.get("frozen_at", time.time()),
                "learning_restored_from": "frozen_learning_results",
            }
            out.append(rec)
    except Exception as e:
        print(f"frozen store restore error: {e}")
    return out

def _open_identity(rec):
    if not isinstance(rec, dict):
        return None
    asset = str(rec.get("asset", "?")).upper()
    try:
        ts = int(float(rec.get("time", 0) or 0))
    except Exception:
        ts = 0
    return f"{asset}:{ts}"

def _merge_open_records(preferred, backup, closed):
    if not isinstance(preferred, dict):
        preferred = {}
    if not isinstance(backup, dict):
        backup = {}
    closed_ids = set(_closed_identity(r) for r in closed if isinstance(r, dict))
    closed_asset_times = set()
    for r in closed:
        if isinstance(r, dict):
            closed_asset_times.add(_open_identity(r))
    merged = dict(preferred)
    now_ts = time.time()
    for key, rec in backup.items():
        if not isinstance(rec, dict):
            continue
        rid = _open_identity(rec)
        if rid in closed_asset_times:
            continue
        try:
            age = now_ts - float(rec.get("time", 0) or 0)
        except Exception:
            age = 0
        # Не оживляем очень старые открытые записи, но защищаем текущие 48ч наблюдения.
        if age > 60 * 3600:
            continue
        asset = str(rec.get("asset", "")).upper()
        duplicate_asset = any(str(x.get("asset", "")).upper() == asset for x in merged.values() if isinstance(x, dict))
        if duplicate_asset:
            continue
        merged[key] = rec
    return merged

def repair_learning_data_from_backup_and_frozen(data):
    """v17.5: never let a short /signal write erase learning history.
    Restores closed 48h from frozen_learning_results.json and protects open observations
    from accidental collapse after redeploy/GitHub cache races.
    """
    if not isinstance(data, dict):
        data = {}
    changed = False

    backup = _raw_load_json_file(RESULTS_BACKUP_FILE)
    frozen_store = _raw_load_json_file(FROZEN_RESULTS_FILE)

    data_open = data.get("open", {}) if isinstance(data.get("open", {}), dict) else {}
    data_closed = data.get("closed", []) if isinstance(data.get("closed", []), list) else []
    backup_open = backup.get("open", {}) if isinstance(backup.get("open", {}), dict) else {}
    backup_closed = backup.get("closed", []) if isinstance(backup.get("closed", []), list) else []
    frozen_closed = _closed_from_frozen_store_data(frozen_store)

    merged_closed = _merge_closed_records(data_closed, backup_closed, frozen_closed)
    if len(merged_closed) > len(data_closed):
        data["closed"] = merged_closed
        changed = True

    merged_open = _merge_open_records(data_open, backup_open, data.get("closed", []))
    if len(merged_open) > len(data_open):
        data["open"] = merged_open
        changed = True

    data.setdefault("open", data_open)
    data.setdefault("closed", data_closed)
    data["version"] = BOT_VERSION
    if changed:
        data["learning_guard_note"] = "v17.5 restored/protected learning data from backup/frozen store"
        data["learning_guard_time"] = time.time()
    return data, changed

def _update_results_backup(existing, candidate):
    try:
        ex_open, ex_closed = _results_counts(existing)
        bk = _raw_load_json_file(RESULTS_BACKUP_FILE)
        bk_open, bk_closed = _results_counts(bk)
        # Backup should keep the richest recent learning state, especially closed 48h.
        if ex_open + ex_closed * 10 >= bk_open + bk_closed * 10 and (ex_open or ex_closed):
            with open(RESULTS_BACKUP_FILE, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            mark_github_dirty(RESULTS_BACKUP_FILE)
    except Exception as e:
        print(f"learning backup update error: {e}")

def save_json(path, data):
    # v17.5: guard learning data before writes. A short /signal or cache race must not
    # erase open observations or frozen closed 48h history.
    try:
        if os.path.basename(str(path)) == "signal_results.json":
            existing = _raw_load_json_file(path)
            _update_results_backup(existing, data)
            data, guard_changed = repair_learning_data_from_backup_and_frozen(data)
            if isinstance(data, dict) and isinstance(data.get("open"), dict):
                data["open"], dedupe_changed = v87_cleanup_open_learning_duplicates(data.get("open", {}))
                guard_changed = bool(guard_changed or dedupe_changed)
            if guard_changed:
                mark_github_dirty(RESULTS_BACKUP_FILE)
    except Exception as e:
        print(f"learning data guard error: {e}")

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    _GITHUB_JSON_CACHE[str(path)] = {"time": time.time(), "data": data}
    mark_github_dirty(path)

def is_admin(chat_id):
    return bool(ADMIN_CHAT_ID) and str(chat_id) == str(ADMIN_CHAT_ID)

def file_info_line(path, title):
    try:
        if os.path.exists(path):
            size = os.path.getsize(path)
            mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
            return f"✅ {title}: {size} байт, изменён {mtime}"
        return f"❌ {title}: файла нет"
    except Exception as e:
        return f"⚠️ {title}: ошибка {e}"


def signal_lock_left():
    data = load_json(SIGNAL_LOCK_FILE)
    if not isinstance(data, dict):
        return 0, {}

    ts = float(data.get("started_at", 0) or 0)
    if ts <= 0:
        return 0, data

    left = int(SIGNAL_LOCK_TTL - (time.time() - ts))
    if left <= 0:
        return 0, data

    return left, data

def signal_lock_message(left, data=None):
    minutes = max(1, int((left + 59) // 60))
    return (
        "⏳ Уже выполняется тяжёлый анализ или Telegram догоняет очередь.\n"
        f"Команда не потерялась: дождись текущего отчёта. Если очередь зависла — /flush. Примерно {minutes} мин."
    )

def try_start_signal_lock(chat_id, update_id=None):
    """
    v11.6:
    Постоянный lock для /signal.
    Нужен, чтобы после redeploy или нескольких нажатий Telegram не запускал 5 анализов подряд.
    """
    left, data = signal_lock_left()
    if left > 0:
        return False, signal_lock_message(left, data)

    data = {
        "status": "running",
        "chat_id": str(chat_id),
        "update_id": str(update_id or ""),
        "started_at": time.time(),
        "version": BOT_VERSION,
    }

    save_json(SIGNAL_LOCK_FILE, data)

    # Для Free Render важно синхронизировать lock сразу, до тяжёлого /signal.
    sync_github_storage_now([SIGNAL_LOCK_FILE, LAST_UPDATE_FILE, CHAT_ID_FILE], max_files=3)

    return True, ""

def finish_signal_lock(ok=True):
    data = load_json(SIGNAL_LOCK_FILE)
    if not isinstance(data, dict):
        data = {}

    # Не очищаем lock сразу. Оставляем cooldown, чтобы queued /signal не стартовали следом.
    data["status"] = "cooldown" if ok else "error_cooldown"
    data["finished_at"] = time.time()
    data["version"] = BOT_VERSION

    save_json(SIGNAL_LOCK_FILE, data)
    background_github_sync([SIGNAL_LOCK_FILE, LAST_UPDATE_FILE, CHAT_ID_FILE], max_files=3)

def force_clear_signal_lock():
    data = {
        "status": "cleared",
        "started_at": 0,
        "finished_at": time.time(),
        "version": BOT_VERSION,
    }
    save_json(SIGNAL_LOCK_FILE, data)
    sync_github_storage_now([SIGNAL_LOCK_FILE, LAST_UPDATE_FILE, CHAT_ID_FILE], max_files=3)

def notify_deploy_started():
    """
    v11.9:
    После Render deploy бот запускается заново.
    Если версия изменилась — отправляем админу уведомление, что новая версия реально стартовала.
    """
    try:
        chat_id = ADMIN_CHAT_ID or load_chat_id()
        if not chat_id:
            return

        data = load_json(DEPLOY_NOTIFY_FILE)
        if not isinstance(data, dict):
            data = {}

        previous_version = data.get("version")
        current_version = BOT_VERSION

        # Не спамим при обычном рестарте той же версии.
        if previous_version == current_version:
            return

        commit = (
            os.getenv("RENDER_GIT_COMMIT")
            or os.getenv("RENDER_COMMIT")
            or os.getenv("COMMIT_SHA")
            or ""
        )
        commit_short = commit[:8] if commit else ""

        lines = [
            "✅ Render запустил новую версию бота",
            f"Версия: {current_version}",
        ]

        if previous_version:
            lines.append(f"Было: {previous_version}")

        if commit_short:
            lines.append(f"Commit: {commit_short}")

        lines.append("")
        lines.append("Проверь: /version")
        lines.append("Если нужно очистить очередь: /flush")

        send_message(chat_id, "\n".join(lines))

        save_json(DEPLOY_NOTIFY_FILE, {
            "version": current_version,
            "previous_version": previous_version,
            "notified_at": time.time(),
            "commit": commit_short,
        })

        background_github_sync([DEPLOY_NOTIFY_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=3)

    except Exception as e:
        print(f"deploy notify error: {e}")

def storage_report():
    lines = [
        f"💾 Хранилище ALEX EDGE",
        f"Версия: {BOT_VERSION}",
        "",
        f"DATA_DIR: {DATA_DIR}",
        f"GitHub storage: {'✅ включён' if github_storage_enabled() else '❌ выключен'}",
        f"GitHub dirty files: {len(_GITHUB_DIRTY_FILES)}",
        f"GitHub data path: {GITHUB_REPO}/{GITHUB_DATA_DIR}/*.json" if github_storage_enabled() else "GitHub data path: не используется",
        "",
        file_info_line(RESULTS_FILE, "signal_results.json / обучение"),
        file_info_line(FROZEN_RESULTS_FILE, "frozen_learning_results.json / заморозка 48ч"),
        file_info_line(RESULTS_BACKUP_FILE, "signal_results_backup.json / резерв обучения"),
        file_info_line(HISTORY_FILE, "signal_history.json / история сигналов"),
        file_info_line(PUMP_FILE, "pump_history.json / alerts"),
        file_info_line(WEEKDAY_FILE, "weekday_market_stats.json / дни недели"),
        file_info_line(BACKTEST_FILE, "historical_backtest_stats.json / быстрый исторический backtest"),
        file_info_line(CHAT_ID_FILE, "chat_id.txt"),
        file_info_line(LAST_UPDATE_FILE, "last_update_id.txt / анти-дубли Telegram"),
        file_info_line(SIGNAL_LOCK_FILE, "signal_lock.json / анти-дубли /signal"),
        file_info_line(DEPLOY_NOTIFY_FILE, "deploy_notify.json / уведомление о deploy"),
        file_info_line(SIGNAL_JOB_FILE, "signal_job.json / статус фонового /signal"),
        file_info_line(ADMIN_UPLOAD_LOCK_FILE, "admin_upload_lock.json / локальная защита загрузки main.py"),
        "",
        "Для Free Render: включи GITHUB_DATA_STORAGE=1 и json будет храниться в GitHub.",
        "Для платного Render Persistent Disk: mount path /var/data и env DATA_DIR=/var/data."
    ]
    return "\n".join(lines)

def send_document(chat_id, file_path, caption=""):
    if not BOT_TOKEN:
        return False
    if not os.path.exists(file_path):
        send_message(chat_id, f"Файл не найден: {file_path}")
        return False

    try:
        with open(file_path, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                data={"chat_id": chat_id, "caption": caption},
                files={"document": f},
                timeout=60
            )
        return r.status_code == 200
    except Exception as e:
        send_message(chat_id, f"Ошибка отправки файла: {e}")
        return False

def send_backup_files(chat_id):
    files = [
        (RESULTS_FILE, "📚 backup learning"),
        (FROZEN_RESULTS_FILE, "🧊 backup frozen 48h results"),
        (RESULTS_BACKUP_FILE, "📚 backup learning safe copy"),
        (PAPER_TRADES_FILE, "🧪 backup paper trades"),
        (HISTORY_FILE, "📊 backup signal history"),
        (PUMP_FILE, "⚡ backup alerts"),
        (WEEKDAY_FILE, "📅 backup weekday stats"),
        (BACKTEST_FILE, "🧠 backup historical backtest"),
    ]

    sent = 0
    for path, caption in files:
        if os.path.exists(path):
            if send_document(chat_id, path, caption):
                sent += 1

    if sent == 0:
        send_message(chat_id, "Файлов backup пока нет.")
    else:
        send_message(chat_id, f"✅ Backup отправлен: файлов {sent}")

def admin_help():
    return (
        f"🛠 Admin deploy\n"
        f"Версия: {BOT_VERSION}\n\n"
        "Команды:\n"
        "/storage — проверить постоянное хранилище\n"
        "/backup — прислать json-файлы статистики\n"
        "/weekday — статистика по дням недели\n"
        "/admin_update или кнопка ⬆️ Обновить — начать загрузку main.py\n"
        "Можно быстрее: просто отправь main*.py документом от ADMIN_CHAT_ID\n"
        "/admin_cancel — отменить загрузку\n"
        "/rollback — вернуть последний backup из GitHub\n"
        "/signal_unlock — аварийно снять lock /signal\n"
        "После Render deploy бот сам пришлёт уведомление о новой версии\n\n"
        "Нужные ENV на Render:\n"
        "ADMIN_CHAT_ID — твой Telegram chat_id\n"
        "GITHUB_TOKEN — GitHub token с правом Contents write\n"
        "GITHUB_REPO — owner/repo\n"
        "GITHUB_BRANCH — main\n"
        "GITHUB_PATH — main.py\n"
        "RENDER_DEPLOY_HOOK_URL — deploy hook, если хочешь запускать deploy вручную\n"
        "DATA_DIR — /var/data для Persistent Disk, если платный Render\n"
        "GITHUB_DATA_STORAGE=1 — бесплатное хранение json в GitHub\n"
        "GITHUB_DATA_DIR=data — папка для json-файлов"
    )

def load_admin_state():
    data = load_json(ADMIN_STATE_FILE)
    return data if isinstance(data, dict) else {}

def save_admin_state(data):
    save_json(ADMIN_STATE_FILE, data or {})

def github_ready():
    return bool(GITHUB_TOKEN and GITHUB_REPO and GITHUB_BRANCH and GITHUB_PATH)

def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

def github_contents_url(path=None):
    p = path or GITHUB_PATH
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{p}"

def github_get_file(path=None):
    if not github_ready():
        raise Exception("GitHub ENV не заполнены: GITHUB_TOKEN, GITHUB_REPO, GITHUB_BRANCH, GITHUB_PATH")

    r = requests.get(
        github_contents_url(path),
        headers=github_headers(),
        params={"ref": GITHUB_BRANCH},
        timeout=30
    )

    if r.status_code == 404:
        return None

    if r.status_code >= 300:
        raise Exception(f"GitHub GET error {r.status_code}: {r.text[:500]}")

    return r.json()

def github_put_file(path, content_bytes, message, sha=None):
    """
    v15.8:
    GitHub Contents API требует актуальный sha файла.
    Если два admin upload или background sync почти одновременно меняют main.py,
    GitHub возвращает 409: expected old sha, file already at new sha.
    В этом случае берём свежий sha и повторяем PUT.
    """
    last_error = None

    for attempt in range(3):
        payload = {
            "message": message,
            "content": base64.b64encode(content_bytes).decode("ascii"),
            "branch": GITHUB_BRANCH
        }

        if sha:
            payload["sha"] = sha

        r = requests.put(
            github_contents_url(path),
            headers=github_headers(),
            json=payload,
            timeout=40
        )

        if r.status_code < 300:
            return r.json()

        last_error = f"GitHub PUT error {r.status_code}: {r.text[:800]}"

        if r.status_code == 409:
            try:
                fresh = github_get_file(path)
                sha = fresh.get("sha") if fresh else None
                time.sleep(1 + attempt)
                continue
            except Exception as e:
                last_error = f"GitHub PUT 409 retry failed: {e}"
                break

        break

    raise Exception(last_error or "GitHub PUT failed")

def trigger_render_deploy():
    if not RENDER_DEPLOY_HOOK_URL:
        return "Render hook не задан; если Auto Deploy включён, Render сам подхватит GitHub push."

    r = requests.post(RENDER_DEPLOY_HOOK_URL, timeout=30)
    if r.status_code >= 300:
        raise Exception(f"Render deploy hook error {r.status_code}: {r.text[:500]}")

    return "Render deploy hook вызван."

def python_compile_file(path):
    txt = open(path, "r", encoding="utf-8", errors="ignore").read()
    compile(txt, path, "exec")
    return txt

def admin_upload_lock_left(ttl=120):
    """
    v16.4:
    Локальная защита от двойной обработки main*.py.
    ВАЖНО: этот lock НЕ синхронизируется в GitHub.
    В v15.8-v16.3 синхронизация admin_upload_lock.json могла создавать лишний commit,
    запускать Render redeploy раньше загрузки main.py и обрывать обновление.
    """
    data = load_json(ADMIN_UPLOAD_LOCK_FILE)
    if not isinstance(data, dict):
        return 0, {}

    if data.get("status") != "running":
        return 0, data

    started = float(data.get("started_at", 0) or 0)
    left = int(ttl - (time.time() - started))
    if left <= 0:
        return 0, data

    return left, data

def clear_admin_upload_lock():
    try:
        if os.path.exists(ADMIN_UPLOAD_LOCK_FILE):
            os.remove(ADMIN_UPLOAD_LOCK_FILE)
    except Exception as e:
        print(f"clear admin upload lock error: {e}")

def acquire_admin_upload_lock(chat_id, filename):
    left, data = admin_upload_lock_left()
    if left > 0:
        return False, left

    data = {
        "status": "running",
        "chat_id": str(chat_id),
        "filename": str(filename or ""),
        "started_at": time.time(),
        "version": BOT_VERSION,
    }
    save_json(ADMIN_UPLOAD_LOCK_FILE, data)
    # v16.4: не отправляем lock в GitHub, чтобы не провоцировать Render redeploy до замены main.py.
    return True, 0

def release_admin_upload_lock(status="done", error=""):
    data = load_json(ADMIN_UPLOAD_LOCK_FILE)
    if not isinstance(data, dict):
        data = {}
    data["status"] = status
    data["finished_at"] = time.time()
    data["error"] = str(error or "")
    data["version"] = BOT_VERSION
    save_json(ADMIN_UPLOAD_LOCK_FILE, data)
    # v16.4: не синхронизируем lock в GitHub.

def admin_start_update(chat_id):
    if not is_admin(chat_id):
        return "⛔ Нет доступа. ADMIN_CHAT_ID не совпадает."

    if not github_ready():
        return (
            "⛔ GitHub ENV не заполнены.\n"
            "Нужно: GITHUB_TOKEN, GITHUB_REPO, GITHUB_BRANCH, GITHUB_PATH.\n"
            "Токены в чат не присылай — только в Render Environment."
        )

    save_admin_state({
        "waiting_file": True,
        "chat_id": str(chat_id),
        "started_at": time.time(),
        "last_backup_path": load_admin_state().get("last_backup_path", "")
    })

    return (
        "🛠 Режим обновления включён.\n\n"
        "Теперь отправь мне файл Python как документ, лучше с именем main.py.\n"
        "В v11.8 можно ещё быстрее: админ может просто отправить main*.py без команды /admin_update.\n"
        "Я проверю compile, сделаю backup старого main.py в GitHub, загружу новый файл и вызову Render deploy hook.\n\n"
        "Отмена: /admin_cancel"
    )

def admin_cancel_update(chat_id):
    if not is_admin(chat_id):
        return "⛔ Нет доступа."
    state = load_admin_state()
    state["waiting_file"] = False
    save_admin_state(state)
    return "✅ Загрузка обновления отменена."

def telegram_download_file(file_id, dest_path):
    r = requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
        params={"file_id": file_id},
        timeout=30
    ).json()

    if not r.get("ok"):
        raise Exception(f"Telegram getFile error: {r}")

    file_path = r.get("result", {}).get("file_path")
    if not file_path:
        raise Exception("Telegram не вернул file_path")

    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    content = requests.get(url, timeout=60).content

    with open(dest_path, "wb") as f:
        f.write(content)

    return dest_path

def admin_handle_document(chat_id, msg):
    if not is_admin(chat_id):
        return "⛔ Нет доступа."

    state = load_admin_state()

    doc = msg.get("document") or {}
    file_id = doc.get("file_id")
    filename = doc.get("file_name", "main.py")

    # v11.8:
    # Быстрый режим: админ может просто отправить main*.py документом,
    # без предварительной команды /admin_update.
    direct_quick_update = (
        is_admin(chat_id)
        and filename.endswith(".py")
        and filename.lower().startswith("main")
    )

    if not state.get("waiting_file") and not direct_quick_update:
        return None

    if not file_id:
        return "Не вижу file_id у документа."

    if not filename.endswith(".py"):
        return "⛔ Нужен Python-файл .py"

    locked, left = acquire_admin_upload_lock(chat_id, filename)
    if not locked:
        return f"⏳ Обновление уже обрабатывается. Подожди примерно {max(1, left)} сек и проверь /version."

    try:
        # v15.7: перед заменой кода принудительно фиксируем и отправляем learning JSON в GitHub.
        # Иначе при быстром deploy Render может подняться из старой копии без frozen_results,
        # и закрытые 48ч проценты снова начнут плавать.
        try:
            persist_closed_learning_freeze(sync_now=False)
        except Exception as _freeze_e:
            print(f"predeploy learning freeze sync error: {_freeze_e}")

        telegram_download_file(file_id, ADMIN_UPLOAD_FILE)

        uploaded_text = python_compile_file(ADMIN_UPLOAD_FILE)
        version_match = re.search(r'BOT_VERSION\s*=\s*"([^"]+)"', uploaded_text)
        upload_version = version_match.group(1) if version_match else "версия не найдена"

        current = github_get_file(GITHUB_PATH)
        backup_path = ""

        if current and current.get("content"):
            current_bytes = base64.b64decode(current["content"])
            backup_path = f"backups/main_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.py"
            github_put_file(
                backup_path,
                current_bytes,
                f"backup before deploy {upload_version}"
            )

        new_bytes = open(ADMIN_UPLOAD_FILE, "rb").read()
        current_sha = current.get("sha") if current else None

        github_put_file(
            GITHUB_PATH,
            new_bytes,
            f"deploy {upload_version}",
            sha=current_sha
        )

        deploy_msg = trigger_render_deploy()

        save_admin_state({
            "waiting_file": False,
            "chat_id": str(chat_id),
            "last_backup_path": backup_path,
            "last_deploy_version": upload_version,
            "last_deploy_at": time.time()
        })

        release_admin_upload_lock("done")

        return (
            f"✅ Новый main.py отправлен в GitHub.\n"
            f"Версия файла: {upload_version}\n"
            f"Backup: {backup_path or 'не создан'}\n"
            f"{deploy_msg}\n\n"
            "Через 1–3 минуты проверь /version.\n\n"
            "v11.8: в следующий раз можно нажать кнопку ⬆️ Обновить "
            "или просто отправить main*.py документом."
        )

    except Exception as e:
        release_admin_upload_lock("error", str(e))
        return f"⛔ Обновление остановлено: {e}"

def admin_rollback(chat_id):
    if not is_admin(chat_id):
        return "⛔ Нет доступа."

    if not github_ready():
        return "⛔ GitHub ENV не заполнены."

    state = load_admin_state()
    backup_path = state.get("last_backup_path")

    if not backup_path:
        return "Backup для rollback не найден."

    try:
        backup = github_get_file(backup_path)
        current = github_get_file(GITHUB_PATH)

        if not backup or not backup.get("content"):
            return "Backup-файл в GitHub не найден."

        backup_bytes = base64.b64decode(backup["content"])
        current_sha = current.get("sha") if current else None

        github_put_file(
            GITHUB_PATH,
            backup_bytes,
            f"rollback to {backup_path}",
            sha=current_sha
        )

        deploy_msg = trigger_render_deploy()

        return f"✅ Rollback выполнен: {backup_path}\n{deploy_msg}\nПроверь /version через 1–3 минуты."

    except Exception as e:
        return f"⛔ Rollback не выполнен: {e}"

# === v11.0 weekday statistics ===
WEEKDAY_ASSETS = ["BTC", "ETH", "SOL", "SUI", "LINK", "TAO", "NEAR", "AAVE", "BNB", "ADA", "AVAX", "INJ"]
WEEKDAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

def get_daily_candles_raw(symbol):
    data = requests.get(
        "https://api.kucoin.com/api/v1/market/candles",
        params={"symbol": symbol, "type": "1day"},
        timeout=20
    ).json()

    if data.get("code") != "200000":
        raise Exception(data)

    candles = sorted(data.get("data", []), key=lambda x: int(x[0]))

    result = []
    for c in candles[-370:]:
        try:
            ts = int(c[0])
            result.append({
                "date": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"),
                "weekday": datetime.utcfromtimestamp(ts).weekday(),
                "open": float(c[1]),
                "close": float(c[2]),
                "high": float(c[3]),
                "low": float(c[4]),
            })
        except Exception:
            continue

    return result

def update_weekday_stats():
    data = load_json(WEEKDAY_FILE)
    if not isinstance(data, dict):
        data = {}

    data.setdefault("records", {})
    data["updated_at"] = datetime.utcnow().isoformat()

    added = 0

    for asset in WEEKDAY_ASSETS:
        symbol = f"{asset}-USDT"
        try:
            candles = get_daily_candles_raw(symbol)

            # Последняя дневная свеча может быть ещё неполной, поэтому берём все кроме самой последней.
            for c in candles[:-1]:
                if c["open"] <= 0 or c["low"] <= 0:
                    continue

                key = f"{asset}:{c['date']}"

                if key in data["records"]:
                    continue

                intraday_drop = (c["low"] / c["open"] - 1) * 100
                rebound_from_low = (c["close"] / c["low"] - 1) * 100
                daily_change = (c["close"] / c["open"] - 1) * 100

                data["records"][key] = {
                    "asset": asset,
                    "date": c["date"],
                    "weekday": c["weekday"],
                    "open": c["open"],
                    "low": c["low"],
                    "high": c["high"],
                    "close": c["close"],
                    "intraday_drop": intraday_drop,
                    "rebound_from_low": rebound_from_low,
                    "daily_change": daily_change,
                }
                added += 1

            time.sleep(0.05)

        except Exception:
            continue

    save_json(WEEKDAY_FILE, data)
    return added, data

def avg(values):
    return sum(values) / len(values) if values else 0

def median_value(values):
    try:
        vals = [float(x) for x in values if isinstance(x, (int, float))]
        return statistics.median(vals) if vals else 0
    except Exception:
        return 0

def weekday_confidence(n):
    try:
        n = int(n or 0)
    except Exception:
        n = 0
    if n >= 40:
        return "уверенность высокая"
    if n >= 25:
        return "уверенность средняя"
    if n >= 14:
        return "можно учитывать осторожно"
    return "данных мало"

def weekday_report():
    added, data = update_weekday_stats()
    sync_github_storage_now([WEEKDAY_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE])
    records = list((data.get("records") or {}).values())

    def asset_weekday_stats(asset):
        rows = [r for r in records if r.get("asset") == asset]
        stats = []

        for wd in range(7):
            rr = [r for r in rows if int(r.get("weekday", -1)) == wd]
            if not rr:
                continue

            drops = [r.get("intraday_drop", 0) for r in rr]
            rebounds = [r.get("rebound_from_low", 0) for r in rr]
            dailies = [r.get("daily_change", 0) for r in rr]

            stats.append({
                "wd": wd,
                "n": len(rr),
                "drop": avg(drops),
                "median_drop": median_value(drops),
                "rebound": avg(rebounds),
                "median_rebound": median_value(rebounds),
                "daily": avg(dailies),
                "prob_drop_2": sum(1 for x in drops if x <= -2.0) / len(drops) * 100 if drops else 0,
                "prob_rebound_1": sum(1 for x in rebounds if x >= 1.0) / len(rebounds) * 100 if rebounds else 0,
                "prob_green_close": sum(1 for x in dailies if x > 0) / len(dailies) * 100 if dailies else 0,
            })

        return stats

    def best_for_asset(asset):
        stats = asset_weekday_stats(asset)
        if not stats:
            return None
        return sorted(stats, key=lambda x: (x["drop"], -x["rebound"]))[0]

    def basket_recommendation(assets):
        """
        v13.4:
        Для DCA нужна не таблица по каждой монете, а один день недели для корзины.
        Считаем голосование: в какой день чаще выпадает локальный минимум у выбранных активов.
        Затем смотрим среднюю просадку/отскок по корзине.
        """
        best_by_asset = {}
        votes = {wd: 0 for wd in range(7)}
        basket_rows = {wd: [] for wd in range(7)}

        for asset in assets:
            stats = asset_weekday_stats(asset)
            if not stats:
                continue

            best = sorted(stats, key=lambda x: (x["drop"], -x["rebound"]))[0]
            best_by_asset[asset] = best
            votes[best["wd"]] += 1

            for s in stats:
                basket_rows[s["wd"]].append(s)

        candidates = []
        for wd in range(7):
            rows = basket_rows.get(wd) or []
            if not rows:
                continue

            candidates.append({
                "wd": wd,
                "votes": votes.get(wd, 0),
                "assets_n": len(rows),
                "drop": avg([r["drop"] for r in rows]),
                "rebound": avg([r["rebound"] for r in rows]),
                "daily": avg([r["daily"] for r in rows]),
            })

        if not candidates:
            return None

        # Приоритет: большинство активов, потом более глубокая средняя просадка, потом отскок.
        best_day = sorted(candidates, key=lambda x: (-x["votes"], x["drop"], -x["rebound"]))[0]
        second = sorted(candidates, key=lambda x: (x["drop"], -x["rebound"]))[0]

        return {
            "best_day": best_day,
            "best_by_asset": best_by_asset,
            "deepest_day": second,
            "candidates": candidates,
        }

    dca_assets = ["BTC", "ETH", "SOL"]
    dca = basket_recommendation(dca_assets)
    all_major = basket_recommendation(WEEKDAY_ASSETS[:12])

    # v15.0: делаем отчёт понятнее — показываем период статистики и защиту от дублей.
    dates = sorted([str(r.get("date")) for r in records if r.get("date")])
    period_line = f"Период статистики: {dates[0]} — {dates[-1]}\n" if dates else "Период статистики: данных пока нет\n"
    per_asset_counts = {}
    for r in records:
        a = r.get("asset")
        if a:
            per_asset_counts[a] = per_asset_counts.get(a, 0) + 1
    avg_per_asset = int(round(avg(list(per_asset_counts.values())))) if per_asset_counts else 0

    text = (
        f"📅 Статистика по дням недели\n"
        f"Версия: {BOT_VERSION}\n"
        f"Файл: {WEEKDAY_FILE}\n"
        f"{period_line}"
        f"Новых записей за запуск: {added}\n"
        f"Всего наблюдений: {len(records)}\n"
        f"Монет в статистике: {len(per_asset_counts)} | записей на монету в среднем: {avg_per_asset}\n"
        f"Дубли не добавляются: ключ = монета + дата закрытой дневной свечи.\n"
        f"v18.0: история расширена до ~365 закрытых дней, добавлены медианы/вероятности/confidence.\n\n"
    )

    if dca:
        best = dca["best_day"]
        deepest = dca["deepest_day"]

        text += "🎯 Итог для еженедельной DCA-покупки BTC/ETH/SOL\n"
        text += (
            f"Рекомендуемый день: {WEEKDAY_NAMES[best['wd']]} "
            f"(совпадает у {best['votes']} из {len(dca_assets)} активов)\n"
        )
        text += (
            f"Средняя просадка корзины в этот день: {best['drop']:.2f}% | "
            f"средний отскок: +{best['rebound']:.2f}% | итог дня: {best['daily']:+.2f}%\n"
        )

        if deepest["wd"] != best["wd"]:
            text += (
                f"Альтернатива по самой глубокой средней просадке: "
                f"{WEEKDAY_NAMES[deepest['wd']]} "
                f"({deepest['drop']:.2f}%, отскок +{deepest['rebound']:.2f}%).\n"
            )

        text += "Разбивка по твоей корзине:\n"

        for asset in dca_assets:
            b = dca["best_by_asset"].get(asset)
            if b:
                text += f"• {asset}: {WEEKDAY_NAMES[b['wd']]} — просадка {b['drop']:.2f}%, отскок +{b['rebound']:.2f}%\n"

        if dca["best_day"]["wd"] == 1:
            text += "Вывод: для одной покупки в неделю логичнее ставить DCA на вторник.\n"
        else:
            text += f"Вывод: для одной покупки в неделю логичнее ставить DCA на {WEEKDAY_NAMES[best['wd']]}.\n"

        text += "Если можно разделить покупку: BTC/SOL — по своему лучшему дню, ETH — по своему.\n\n"

    if all_major:
        best_all = all_major["best_day"]
        text += "🌐 День локальных минимумов по большинству основных монет\n"
        text += (
            f"Большинство сейчас указывает на: {WEEKDAY_NAMES[best_all['wd']]} "
            f"({best_all['votes']} совпадений среди основных активов).\n"
        )
        text += (
            f"Средняя просадка по рынку в этот день: {best_all['drop']:.2f}% | "
            f"средний отскок: +{best_all['rebound']:.2f}%\n\n"
        )

    text += "📌 Детально по монетам:\n\n"

    for asset in WEEKDAY_ASSETS[:12]:
        best = best_for_asset(asset)
        if not best:
            continue

        reliability = weekday_confidence(best["n"])

        text += f"{asset}: вероятный день локальных минимумов — {WEEKDAY_NAMES[best['wd']]} ({reliability})\n"
        text += (
            f"  наблюдений: {best['n']} | средняя просадка: {best['drop']:.2f}% "
            f"(медиана {best.get('median_drop', 0):.2f}%) | отскок: +{best['rebound']:.2f}% "
            f"(медиана +{best.get('median_rebound', 0):.2f}%) | итог дня: {best['daily']:+.2f}%\n"
        )
        text += (
            f"  вероятность просадки >2%: {best.get('prob_drop_2', 0):.0f}% | "
            f"отскока от минимума >1%: {best.get('prob_rebound_1', 0):.0f}% | "
            f"зелёного закрытия: {best.get('prob_green_close', 0):.0f}%\n\n"
        )

    text += (
        "Важно: это статистика наблюдений, а не команда покупать. "
        "Для DCA это помогает выбрать день недели, но учитывать нужно вместе с BTC, страхом, объёмом и текущим риском рынка."
    )

    return text

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
    "🧪 Paper": "/paper",
    "📚 Полное обучение": "/learning_full",

    # v12.9: одна служебная кнопка вместо россыпи админ-кнопок.
    "🛠 Сервис": "/service",
    "🛠 Admin": "/service",   # старое название как alias
    "☰ Ещё": "/service",      # старое название как alias

    # сервисное меню
    "🧹 Очистить": "/flush",
    "💾 Хранилище": "/storage",
    "📅 Дни недели": "/weekday",
    "🔄 Sync": "/sync_storage",
    "⚙️ Версия": "/version",

    # команды оставлены как скрытые/ручные, но не в главном меню
    "🏆 Топ": "/top",
    "📈 Топ": "/top",
    "❓ Помощь": "/help",
    "⬆️ Обновить": "/admin_update",
    "🔓 Unlock": "/signal_unlock",
    "📡 Signal status": "/signal_status",
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

def duplicate_command_cooldown(text):
    """
    v13.7:
    Защита от двойного нажатия одной кнопки / повторной доставки Telegram.
    Возвращает паузу в секундах для одинаковой команды.
    """
    if text in ["/signal", "/signal_full"]:
        return 15
    if text in ["/btc", "/sol"] or text.lower().startswith("/coin"):
        return 12
    if text in ["/alerts", "/market", "/macro", "/weekday", "/stats"]:
        return 10
    if text in ["/learning", "/storage", "/service", "/more", "/admin", "/paper", "/paper_trading", "/virtual"]:
        return 6
    if text in ["/version", "/flush", "/sync_storage", "/signal_status", "/signal_unlock"]:
        return 4
    return 5

def should_skip_duplicate_command(chat_id, text, last_command_time):
    """
    True — если это та же команда от того же чата слишком быстро.
    Молча пропускаем, чтобы бот не присылал два одинаковых отчёта подряд.
    """
    if not text or not str(text).startswith("/"):
        return False

    key = f"{chat_id}:{text}"
    now_ts = time.time()
    cooldown = duplicate_command_cooldown(text)
    prev = float(last_command_time.get(key, 0) or 0)

    if now_ts - prev < cooldown:
        return True

    last_command_time[key] = now_ts
    return False

def should_skip_service_message(chat_id, last_service_time):
    """
    v17.6.1:
    Жёсткая защита именно для кнопки 🛠 Сервис.
    Telegram иногда присылает одно нажатие дважды или разными alias (/service, /more, /admin).
    Держим общий cooldown по chat_id, чтобы не отправлять два одинаковых сервисных меню.
    """
    now_ts = time.time()
    key = str(chat_id)
    try:
        prev = float(last_service_time.get(key, last_service_time.get(chat_id, 0)) or 0)
    except Exception:
        prev = 0

    if now_ts - prev < 20:
        return True

    last_service_time[key] = now_ts
    last_service_time[chat_id] = now_ts
    return False

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

# === v17.7.1 command pool / batch commands HOTFIX ===
# Пользователь может отправить одним сообщением несколько команд строками:
# /paper
# /signal
# /learning
# Бот разложит их на очередь и выполнит по порядку.
COMMAND_POOL_ALIASES = {
    "signal": "/signal",
    "сигнал": "/signal",
    "📊 сигнал": "/signal",
    "paper": "/paper",
    "пейпер": "/paper",
    "виртуальные сделки": "/paper",
    "🧪 paper": "/paper",
    "обучение": "/learning",
    "learning": "/learning",
    "learning_full": "/learning_full",
    "обучение полное": "/learning_full",
    "полное обучение": "/learning_full",
    "📚 обучение": "/learning",
    "alerts": "/alerts",
    "алерты": "/alerts",
    "⚡ alerts": "/alerts",
    "рынок": "/market",
    "market": "/market",
    "🌍 рынок": "/market",
    "btc": "/btc",
    "биткоин": "/btc",
    "🟠 btc": "/btc",
    "sol": "/sol",
    "solana": "/sol",
    "🟣 sol": "/sol",
    "weekday": "/weekday",
    "дни недели": "/weekday",
    "📅 дни недели": "/weekday",
    "storage": "/storage",
    "хранилище": "/storage",
    "service": "/service",
    "сервис": "/service",
    "🛠 сервис": "/service",
}

def _strip_pool_line_prefix(line):
    line = (line or "").strip()
    # Убираем нумерацию/буллеты: "1) /paper", "- /signal", "• BTC".
    line = re.sub(r"^[\s\-–—•*]+", "", line)
    line = re.sub(r"^\d+[\.\)]\s*", "", line)
    return line.strip()

def command_pool_line_to_command(line):
    raw = _strip_pool_line_prefix(line)
    if not raw:
        return None

    normalized = normalize_button_text(raw).strip()
    low = normalized.lower().strip()

    if low in COMMAND_POOL_ALIASES:
        return COMMAND_POOL_ALIASES[low]

    # Команда с аргументом: /coin ETH.
    if low.startswith("/coin"):
        parts = normalized.split()
        if len(parts) >= 2:
            coin = resolve_coin_symbol(parts[1])
            if coin:
                return f"/coin {coin}"
        return "/coin"

    if normalized.startswith("/"):
        # Оставляем только первую команду + один аргумент, чтобы мусор после команды не ломал обработчик.
        # v17.7.1: Telegram иногда присылает команды как /paper@BotName — отрезаем @BotName.
        parts = normalized.split()
        base_cmd = parts[0].lower().split("@", 1)[0]
        if len(parts) >= 2 and base_cmd == "/coin":
            return f"/coin {resolve_coin_symbol(parts[1])}"
        return base_cmd

    # Отдельная строка с тикером тоже работает как команда анализа монеты.
    coin = resolve_coin_symbol(raw)
    if coin in POPULAR_COINS:
        if coin == "BTC":
            return "/btc"
        if coin == "SOL":
            return "/sol"
        return f"/coin {coin}"

    return None

def parse_command_pool(raw_text):
    """
    Возвращает список команд, если одно сообщение похоже на пул команд.
    Безопасность: пул включается только когда найдено минимум 2 понятные команды.
    Обычный текст пользователя не превращаем в команды.
    """
    raw = (raw_text or "").strip()
    if not raw or len(raw) > 1500:
        return []

    candidates = []

    if "\n" in raw or ";" in raw or "," in raw:
        candidates = [x.strip() for x in re.split(r"[\n;,]+", raw) if x.strip()]
    else:
        # Поддержка строки вида: /paper /signal /learning /alerts
        slash_matches = re.findall(r"/coin\s+[A-Za-z0-9$_\.\-]+|/[A-Za-z_]+", raw, flags=re.IGNORECASE)
        if len(slash_matches) >= 2:
            candidates = slash_matches
        else:
            # Поддержка короткой строки: paper signal learning alerts
            tokens = raw.split()
            if 2 <= len(tokens) <= 12:
                candidates = tokens

    commands = []
    for c in candidates:
        cmd = command_pool_line_to_command(c)
        if cmd:
            commands.append(cmd)

    if len(commands) < 2:
        return []

    # Ограничение, чтобы случайный текст не запускал огромную очередь.
    return commands[:12]

def expand_command_pool_updates(items):
    """
    Превращает одно Telegram-сообщение с пулом команд в несколько виртуальных updates.
    Существующий обработчик ниже выполняет их последовательно, как будто пользователь нажал кнопки по очереди.
    """
    expanded = []
    for item in items:
        try:
            msg = item.get("message", {}) or {}
            raw = (msg.get("text", "") or "").strip()
            commands = parse_command_pool(raw)
        except Exception:
            commands = []

        if not commands:
            expanded.append(item)
            continue

        for idx, cmd in enumerate(commands, start=1):
            clone = json.loads(json.dumps(item))
            clone_msg = clone.setdefault("message", {})
            clone_msg["text"] = cmd
            clone_msg["_command_pool"] = True
            clone_msg["_pool_index"] = idx
            clone_msg["_pool_total"] = len(commands)
            clone_msg["_pool_original_text"] = raw[:500]
            expanded.append(clone)

    return expanded

def command_pool_ack_text(total):
    return (
        f"📦 Пул команд принят: {total}. Выполняю по очереди.\n"
        "Команды не теряются: сначала будет первый отчёт, затем следующий. Новые нажатия уйдут в очередь.\n"
        f"Версия обработчика: {BOT_VERSION}."
    )

def coin_search_prompt():
    return (
        "🔎 Поиск монеты\n\n"
        "Выбери популярную монету кнопкой ниже или нажми ✍️ Ввести вручную.\n\n"
        "Можно также просто написать тикер сообщением: ETH, SUI, LINK, GRAM.\n"
        "Команду /coin ETH писать больше не обязательно."
    )

def keyboard(chat_id=None):
    """
    v17.8.5:
    Главное меню без кнопки отчёта.
    Для ускорения тестов Paper вынесен на главный экран, а редкое осталось в 🛠 Сервис.
    """
    return {
        "keyboard": [
            ["📊 Сигнал", "🔎 Монета"],
            ["🟠 BTC", "🟣 SOL"],
            ["🌍 Рынок", "⚡ Alerts"],
            ["📚 Обучение", "🧪 Paper"],
            ["🛠 Сервис"],
        ],
        "resize_keyboard": True
    }

def service_keyboard(chat_id=None):
    rows = [
        ["🧹 Очистить", "💾 Хранилище"],
        ["📅 Дни недели", "⚙️ Версия"],
        ["🧪 Paper"],
    ]

    if chat_id and is_admin(chat_id):
        rows.append(["🔄 Sync"])

    rows.append(["⬅️ Назад"])

    return {
        "keyboard": rows,
        "resize_keyboard": True
    }

# Старые имена оставлены, чтобы код и старые кнопки не ломались.
def more_keyboard(chat_id=None):
    return service_keyboard(chat_id)

def admin_keyboard():
    return service_keyboard(ADMIN_CHAT_ID)

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
            json={"chat_id": chat_id, "text": part, "reply_markup": reply_markup or keyboard(chat_id)},
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

def get_updates_now(offset=None):
    """
    v13.0:
    Быстрый одноразовый getUpdates без long-poll.
    Нужен, чтобы после deploy не догонять старые нажатия кнопок.
    """
    if not BOT_TOKEN:
        return {"result": []}

    params = {"timeout": 0, "limit": 100}

    if offset:
        params["offset"] = offset

    return requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
        params=params,
        timeout=8
    ).json()

def is_admin_main_py_document_update(item):
    """
    v15.6:
    Приоритетная проверка админского файла main*.py в очереди Telegram.
    Нужна, чтобы обновление бота не терялось за тяжёлыми /signal, /alerts, /learning.
    """
    try:
        msg = item.get("message", {}) or {}
        chat_id = msg.get("chat", {}).get("id")
        doc = msg.get("document") or {}
        filename = (doc.get("file_name") or "").strip().lower()

        return bool(
            doc
            and is_admin(chat_id)
            and filename.endswith(".py")
            and filename.startswith("main")
        )
    except Exception:
        return False

def discard_pending_updates_on_startup(last_update):
    """
    v13.0:
    После Render deploy в Telegram могут остаться кнопки, нажатые во время перезапуска.
    Мы молча подтверждаем их offset, чтобы бот не присылал пачкой BTC/SOL/Market/Alerts.
    """
    try:
        updates = get_updates_now(last_update)
        items = updates.get("result", []) or []

        if not items:
            return last_update

        # v15.6:
        # Никогда не выкидываем из Telegram backlog админский main*.py.
        # Иначе файл, отправленный во время перезапуска Render, мог быть молча пропущен.
        if any(is_admin_main_py_document_update(item) for item in items):
            print("startup pending admin upload found — keep backlog for priority handler")
            return last_update

        max_update = last_update or 0
        for item in items:
            try:
                max_update = max(max_update, int(item.get("update_id", 0)) + 1)
            except Exception:
                pass

        if max_update:
            save_last_update_id(max_update)
            return max_update

    except Exception as e:
        print(f"discard_pending_updates_on_startup error: {e}")

    return last_update

def kucoin_tickers():
    now = time.time()

    if now - _ticker_cache["time"] < 20 and _ticker_cache["data"]:
        return _ticker_cache["data"]

    data = requests.get(
        "https://api.kucoin.com/api/v1/market/allTickers",
        timeout=8
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
        timeout=CANDLE_TIMEOUT
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
        data = requests.get("https://api.alternative.me/fng/", timeout=5).json()
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
        data = requests.get("https://api.coingecko.com/api/v3/global", timeout=5).json()
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

def fetch_google_news_items(query, hours=12, max_items=12, timeout=NEWS_TIMEOUT):
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
        "evacuate": 4,
        "kill": 6,
        "kills": 6,
        "killed": 6,
        "dead": 5,
        "death": 5,
        "airstrike": 5,
        "airstrikes": 5,
        "despite ceasefire": 8,
        "despite reported ceasefire": 8,
        "ceasefire violation": 8,
        "violates ceasefire": 8,
        "violate ceasefire": 8
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
        # v13.11: одно слово "ceasefire" больше НЕ является override.
        # Иначе заголовок вида "strikes kill despite ceasefire" ошибочно становился зелёным.
        "agree ceasefire", "agreed ceasefire", "ceasefire agreed",
        "ceasefire deal", "ceasefire agreement", "ceasefire talks",
        "de-escalation", "deescalation", "stop fighting",
        "halt strikes", "resume talks", "diplomatic breakthrough"
    ]

    risk_override = [
        "new strikes", "missile strike", "missile strikes", "oil tanker hit",
        "closes hormuz", "close hormuz", "blockade hormuz", "attack on",
        "retaliatory strike", "war expands", "escalates",
        "strikes kill", "strike kills", "strikes killed", "strike killed",
        "kills civilians", "kill civilians", "killed civilians",
        "kill eight", "kills eight", "killed eight",
        "despite ceasefire", "despite reported ceasefire",
        "ceasefire violation", "violates ceasefire", "violate ceasefire",
        "war returns", "us strikes", "u.s. strikes"
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
    if v106_safe_caution(ctx):
        return f"⚠️ Риск рынка: 🟠 safe-caution — BTC {btc_change:.2f}%, страх {fg_value}"
    if v115_extreme_fear_btc_weak(ctx):
        return f"⚠️ Риск рынка: 🟡 extreme-fear caution — BTC {btc_change:.2f}%, страх {fg_value}"
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

    # v17.4: hard-risk threshold.
    # Если BTC уже падает примерно -2.5% и ниже, страх остается высоким,
    # а новости отрицательные, это нельзя показывать как обычный осторожный рынок.
    # BUY и агрессивные формулировки должны оставаться заблокированы,
    # а рынок должен называться рискованным/опасным.
    if btc_change <= -2.5 and fg_value <= 25 and news_score <= -6:
        return "danger"

    # Если BTC почти -3% даже при смешанных новостях и страхе, это hard-risk режим.
    if btc_change <= -2.8 and fg_value <= 25:
        return "danger"

    # v10.9: BTC ниже -2.3% + экстремальный страх — уже danger.
    # Иначе бот может снова дать ETH/BTC 80–90/100 и "первая малая часть".
    if btc_change <= -2.3 and fg_value <= 15:
        return "danger"

    # BTC падает сильнее -2.2%, страх высокий и новости негативные — опасный рынок.
    if btc_change <= -2.2 and fg_value <= 20 and news_score <= -6:
        return "danger"

    if news_score <= -12 and btc_change <= -1:
        return "danger"

    # Просто -2% при страхе 14 — это не всегда danger; это граница safe-caution.
    if btc_change <= -2 or news_score <= -6 or fg_value <= 25 or market_score <= -8:
        return "caution"

    if news_score >= 8 and btc_change >= 0 and fg_value > 35:
        return "positive"

    return "neutral"

def v106_safe_caution(ctx):
    """
    v10.9:
    Safe-caution — только пограничный режим до -2.2%.
    При BTC <= -2.3% и страхе 14–15 уже danger.
    """
    if not isinstance(ctx, dict):
        return False

    fg_value = ctx.get("fg_value", 50)
    btc_change = ctx.get("btc_change", 0)
    btc_text = str(ctx.get("btc_text", ""))
    news_score = ctx.get("macro_mod", ctx.get("geo_mod", 0))

    # Если рынок уже danger по основному движку — safe-caution не перехватывает метку.
    if market_risk_level(ctx) == "danger":
        return False

    return (
        fg_value <= 15
        and -2.2 < btc_change <= -1.6
        and news_score > -8
        and (
            "мешает" in btc_text
            or btc_change <= -1.6
        )
    )

def v115_extreme_fear_btc_weak(ctx):
    """
    v11.5:
    Даже если BTC падает всего около -1%, при страхе 14–15 нельзя писать
    "Среднесрок", "первая малая часть" и ETH/BTC 90/82.
    Это не danger, но это режим только наблюдения.
    """
    if not isinstance(ctx, dict):
        return False

    fg_value = ctx.get("fg_value", 50)
    btc_change = ctx.get("btc_change", 0)
    news_score = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    btc_text = str(ctx.get("btc_text", ""))

    if market_risk_level(ctx) == "danger":
        return False

    if v106_safe_caution(ctx):
        return False

    return (
        fg_value <= 15
        and btc_change < 0
        and news_score <= 3
        and ("мешает" in btc_text or btc_change < 0)
    )

def macro_action_hint(ctx):
    level = market_risk_level(ctx)

    if level == "danger":
        return "Решение: BUY запрещены. BTC/ETH — только после стабилизации. Альты — не трогать, только наблюдать."

    if v106_safe_caution(ctx):
        return "Решение: safe-caution. BUY запрещены до стабилизации BTC. BTC/ETH — наблюдать, альты — только после разворота рынка."

    if v115_extreme_fear_btc_weak(ctx):
        return "Решение: экстремальный страх. BUY запрещены. BTC/ETH — только наблюдать, без первой части."

    if level == "caution":
        if ctx.get("macro_mod", ctx.get("geo_mod", 0)) <= -15 and ctx.get("btc_change", 0) >= 0:
            return "Решение: повышенная осторожность. BUY запрещены до улучшения новостей и подтверждения BTC/объёма."
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
        clean = line.lower().strip()
        # Берём только агрегированные строки компонентов, а не headline-строки.
        # Иначе заголовок с фразой "end war" мог перебить зелёную геополитику.
        is_component = (
            clean.startswith("🔴 фрс:") or clean.startswith("🟡 фрс:") or clean.startswith("🟢 фрс:")
            or clean.startswith("🔴 геополитика:") or clean.startswith("🟡 геополитика:") or clean.startswith("🟢 геополитика:")
            or clean.startswith("🔴 крипто-новости:") or clean.startswith("🟡 крипто-новости:") or clean.startswith("🟢 крипто-новости:")
        )
        if not is_component:
            continue

        if "фрс:" in clean:
            if "🟢" in line or "лучше" in clean or "помог" in clean or "cut" in clean:
                fed = "помогает"
            elif "🔴" in line or "дав" in clean or "негатив" in clean or "ужесточ" in clean or "hike" in clean:
                fed = "давит"
            else:
                fed = "нейтрально"

        if "геополитика:" in clean:
            if "🟢" in line or "деэскала" in clean or "ceasefire" in clean or "спокой" in clean:
                geo = "улучшилась"
            elif "🔴" in line or "эскалац" in clean or "strike" in clean or "kill" in clean:
                geo = "давит"
            elif "свежих новостей не найдено" in clean:
                geo = "нет свежих данных"
            else:
                geo = "смешанно"

        if "крипто-новости:" in clean:
            if "🟢" in line:
                crypto = "позитив"
            elif "🔴" in line:
                crypto = "негатив"
            elif "свежих новостей не найдено" in clean:
                crypto = "нет свежих данных"
            else:
                crypto = "нейтрально"

    if score <= -15:
        label = "опасно"
    elif score <= -6:
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

def market_context(force_refresh=False):
    """
    v11.7.1:
    Не пересчитываем рынок для каждой монеты.
    Один /signal может анализировать 35+ монет, но market_context нужен один раз в 60 секунд.
    """
    now_ts = time.time()
    if (
        not force_refresh
        and _market_context_cache.get("data")
        and now_ts - float(_market_context_cache.get("time", 0) or 0) < 60
    ):
        return dict(_market_context_cache["data"])

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
        "btc_text": btc_text,
        "btc_mod": btc_mod,
        "btc_change": btc_change,
        "market_mod": total,
    }

    level = market_risk_level(temp_ctx)

    if level == "danger":
        state = "🔴 рынок рискованный"
    elif v106_safe_caution(temp_ctx):
        state = "🟠 safe-caution / ждать BTC"
    elif v115_extreme_fear_btc_weak(temp_ctx):
        state = "🟡 extreme-fear / только наблюдать"
    elif level == "caution" and macro_mod <= -15 and btc_change >= 0:
        state = "🟠 повышенная осторожность — опасные новости, BTC пока держится"
    elif level == "caution":
        state = "🟡 осторожный рынок"
    elif level == "positive":
        state = "🟢 рынок помогает росту"
    else:
        state = "🟡 рынок нейтральный"

    result = {
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

    _market_context_cache["time"] = now_ts
    _market_context_cache["data"] = dict(result)

    return result

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

def closed_learning_key(rec):
    """v16.1: stable key for immutable closed 48h snapshot."""
    if not isinstance(rec, dict):
        return "unknown"
    asset = str(rec.get("asset", "?")).upper()
    try:
        ts = int(float(rec.get("time", 0) or 0))
    except Exception:
        ts = 0
    try:
        price = round(float(rec.get("price", 0) or 0), 8)
    except Exception:
        price = 0
    return f"{asset}:{ts}:{price}"


def load_frozen_results_store():
    data = load_json(FROZEN_RESULTS_FILE)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("records", {})
    return data


def save_frozen_results_store(data, sync_now=False):
    if not isinstance(data, dict):
        data = {"records": {}}
    data.setdefault("records", {})
    save_json(FROZEN_RESULTS_FILE, data)
    if sync_now:
        sync_github_storage_now([FROZEN_RESULTS_FILE, RESULTS_FILE, RESULTS_BACKUP_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=4)


def learning_results_for_eval(rec):
    """v16.1: for closed records prefer external immutable frozen file.
    This prevents old 48h results from floating after redeploy/GitHub cache refresh.
    """
    if not isinstance(rec, dict):
        return {}

    try:
        store = load_frozen_results_store()
        key = closed_learning_key(rec)
        frozen_rec = (store.get("records") or {}).get(key)
        if isinstance(frozen_rec, dict):
            frozen = frozen_rec.get("results")
            if isinstance(frozen, dict) and frozen:
                return frozen
    except Exception:
        pass

    frozen = rec.get("frozen_results")
    if isinstance(frozen, dict) and frozen:
        return frozen
    results = rec.get("results")
    return results if isinstance(results, dict) else {}


def freeze_closed_learning_record(rec, frozen_store=None):
    """v16.1: one-time immutable closed result snapshot.
    The source of truth is frozen_learning_results.json, not recalculated current prices.
    """
    if not isinstance(rec, dict):
        return rec, False

    changed = False
    key = closed_learning_key(rec)

    if frozen_store is None:
        frozen_store = load_frozen_results_store()
    frozen_store.setdefault("records", {})
    store_records = frozen_store["records"]

    existing = store_records.get(key)

    if isinstance(existing, dict) and isinstance(existing.get("results"), dict) and existing.get("results"):
        # External frozen file wins. Do not overwrite it with live recalculation.
        frozen_results = dict(existing.get("results") or {})
        frozen_details = existing.get("result_details") if isinstance(existing.get("result_details"), dict) else {}
        frozen_outcome = existing.get("outcome") or rec.get("frozen_outcome") or rec.get("outcome")

        if rec.get("frozen_results") != frozen_results:
            rec["frozen_results"] = dict(frozen_results)
            changed = True
        if rec.get("results") != frozen_results:
            rec["results"] = dict(frozen_results)
            changed = True
        if frozen_details and rec.get("frozen_result_details") != frozen_details:
            try:
                rec["frozen_result_details"] = json.loads(json.dumps(frozen_details))
            except Exception:
                rec["frozen_result_details"] = dict(frozen_details)
            changed = True
        if frozen_outcome:
            if rec.get("outcome") != frozen_outcome:
                rec["outcome"] = frozen_outcome
                changed = True
            if rec.get("frozen_outcome") != frozen_outcome:
                rec["frozen_outcome"] = frozen_outcome
                changed = True
        if not rec.get("frozen_at"):
            rec["frozen_at"] = existing.get("frozen_at", float(rec.get("closed_time", time.time()) or time.time()))
            changed = True
        return rec, changed

    # First time seeing this closed record: freeze current stored checkpoints.
    results = rec.get("frozen_results") if isinstance(rec.get("frozen_results"), dict) and rec.get("frozen_results") else rec.get("results")
    if not isinstance(results, dict):
        results = {}

    if rec.get("frozen_results") != results:
        rec["frozen_results"] = dict(results)
        changed = True
    if rec.get("results") != results:
        rec["results"] = dict(results)
        changed = True

    details = rec.get("frozen_result_details") if isinstance(rec.get("frozen_result_details"), dict) and rec.get("frozen_result_details") else rec.get("result_details")
    if not isinstance(details, dict):
        details = {}
    if details and rec.get("frozen_result_details") != details:
        try:
            rec["frozen_result_details"] = json.loads(json.dumps(details))
        except Exception:
            rec["frozen_result_details"] = dict(details)
        changed = True

    if not rec.get("frozen_at"):
        rec["frozen_at"] = float(rec.get("closed_time", time.time()) or time.time())
        changed = True

    # outcome computed from the frozen results now stored in rec.
    fixed_outcome = classify_learning_result(rec)
    if rec.get("outcome") != fixed_outcome:
        rec["outcome"] = fixed_outcome
        changed = True
    if rec.get("frozen_outcome") != fixed_outcome:
        rec["frozen_outcome"] = fixed_outcome
        changed = True

    store_records[key] = {
        "asset": str(rec.get("asset", "?")),
        "time": float(rec.get("time", 0) or 0),
        "price": rec.get("price", 0),
        "score": rec.get("score", 0),
        "action": rec.get("action", "WATCH"),
        "verdict": rec.get("verdict", ""),
        "results": dict(rec.get("frozen_results", {}) or {}),
        "result_details": rec.get("frozen_result_details", {}) if isinstance(rec.get("frozen_result_details"), dict) else {},
        "outcome": rec.get("frozen_outcome", rec.get("outcome")),
        "frozen_at": rec.get("frozen_at", time.time()),
        "version": BOT_VERSION,
    }
    changed = True

    return rec, changed


def normalize_closed_learning_records(closed_items, sync_now=False):
    if not isinstance(closed_items, list):
        return [], False
    changed = False
    frozen_store = load_frozen_results_store()
    new_items = []
    for rec in closed_items:
        rec, ch = freeze_closed_learning_record(rec, frozen_store=frozen_store)
        changed = changed or ch
        new_items.append(rec)
    if changed:
        save_frozen_results_store(frozen_store, sync_now=sync_now)
    return new_items, changed


def persist_closed_learning_freeze(sync_now=False):
    """v16.1: persist immutable closed 48h results to a separate file."""
    try:
        data = load_json(RESULTS_FILE)
        if not isinstance(data, dict):
            return False, 0

        closed = data.get("closed", [])
        if not isinstance(closed, list) or not closed:
            return False, 0

        closed, changed = normalize_closed_learning_records(closed, sync_now=sync_now)
        data["closed"] = closed
        data.setdefault("version", BOT_VERSION)

        if changed or sync_now:
            save_json(RESULTS_FILE, data)
            if sync_now:
                sync_github_storage_now([FROZEN_RESULTS_FILE, RESULTS_FILE, RESULTS_BACKUP_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=4)
            return changed, len(closed)

        if sync_now:
            sync_github_storage_now([FROZEN_RESULTS_FILE, RESULTS_FILE, RESULTS_BACKUP_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=4)
        return False, len(closed)
    except Exception as e:
        print(f"persist closed learning freeze error: {e}")
        return False, 0

def classify_learning_result(rec):
    results = learning_results_for_eval(rec)
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
    v17.6.1:
    Одна монета = одно открытое наблюдение до закрытия 48ч.
    Если частые кнопки/фоновые сканы создали дубли, оставляем самую раннюю запись,
    но не теряем факт повторного появления: переносим seen_count/last_seen/last_price.
    """
    if not isinstance(open_items, dict):
        return {}, False

    by_asset = {}
    changed = False

    def norm_asset(rec, fallback=""):
        asset = str((rec or {}).get("asset") or (rec or {}).get("symbol") or fallback or "").upper()
        asset = asset.replace("-USDT", "").strip()
        return asset

    def safe_time(rec):
        try:
            return float((rec or {}).get("time", 0) or 0)
        except Exception:
            return 0.0

    # Сортируем по времени: первая запись по монете остаётся, остальные сливаются в неё.
    rows = sorted(list(open_items.items()), key=lambda kv: safe_time(kv[1]))

    cleaned = {}
    for key, rec in rows:
        if not isinstance(rec, dict):
            changed = True
            continue

        asset = norm_asset(rec, key)
        if not asset:
            cleaned[key] = rec
            continue

        rec["asset"] = asset

        if asset in by_asset:
            keep_key = by_asset[asset]
            keep = cleaned.get(keep_key, {})
            try:
                keep_seen = int(float(keep.get("seen_count", 1) or 1))
            except Exception:
                keep_seen = 1
            try:
                drop_seen = int(float(rec.get("seen_count", 1) or 1))
            except Exception:
                drop_seen = 1
            keep["seen_count"] = max(1, min(learning_seen_count_cap(keep), keep_seen + drop_seen))

            # last_seen/last_price берём из более свежей записи, если она есть.
            try:
                if float(rec.get("last_seen", 0) or 0) >= float(keep.get("last_seen", 0) or 0):
                    for fld in ["last_seen", "last_price", "last_score", "last_action", "last_verdict"]:
                        if fld in rec:
                            keep[fld] = rec.get(fld)
            except Exception:
                pass

            # price_points объединяем, чтобы checkpoints не потеряли снимки.
            try:
                pts = learning_price_points(keep) + learning_price_points(rec)
                uniq = {}
                for pt in pts:
                    uniq[float(pt.get("time", 0) or 0)] = pt
                keep["price_points"] = [uniq[k] for k in sorted(uniq.keys())][-500:]
            except Exception:
                pass

            cleaned[keep_key] = keep
            changed = True
            continue

        by_asset[asset] = key
        cleaned[key] = rec

    return cleaned, changed



def learning_price_points(rec):
    """v15.1: безопасно получаем историю коротких price snapshots для честных fast-checkpoints."""
    pts = rec.get("price_points", [])
    if not isinstance(pts, list):
        pts = []
    clean = []
    for pt in pts:
        try:
            t = float(pt.get("time", 0) or 0)
            price = float(pt.get("price", 0) or 0)
            if t > 0 and price > 0:
                clean.append({"time": t, "price": price})
        except Exception:
            continue
    clean.sort(key=lambda x: x["time"])
    return clean[-500:]


def append_learning_price_point(rec, price, now=None, min_gap_seconds=60):
    """v15.1: сохраняет короткую историю цен, но не раздувает файл каждую секунду."""
    try:
        price = float(price or 0)
    except Exception:
        price = 0
    if price <= 0:
        return rec
    if now is None:
        now = time.time()

    pts = learning_price_points(rec)
    if pts:
        last = pts[-1]
        try:
            last_time = float(last.get("time", 0) or 0)
            last_price = float(last.get("price", 0) or 0)
        except Exception:
            last_time = 0
            last_price = 0
        # Не пишем дубль чаще 1 минуты, если цена почти не изменилась.
        if now - last_time < min_gap_seconds and abs(percent_change(last_price, price)) < 0.05:
            rec["price_points"] = pts
            return rec

    pts.append({"time": float(now), "price": round(price, 8)})
    rec["price_points"] = pts[-500:]
    return rec


def checkpoint_price_from_points(rec, target_ts, current_price, now):
    """v15.1: для 15м/30м/1ч берём цену около момента checkpoint, а не текущую цену спустя час.
    Если точной точки нет, используем ближайшую после target_ts; если её нет — текущую цену с пометкой late_estimate.
    """
    pts = learning_price_points(rec)
    if pts:
        after = [pt for pt in pts if float(pt.get("time", 0) or 0) >= target_ts]
        if after:
            chosen = min(after, key=lambda pt: abs(float(pt.get("time", 0) or 0) - target_ts))
            return float(chosen["price"]), float(chosen["time"]), "snapshot"
        before = [pt for pt in pts if float(pt.get("time", 0) or 0) < target_ts]
        if before:
            chosen = max(before, key=lambda pt: float(pt.get("time", 0) or 0))
            # Если ближайшая точка до checkpoint совсем рядом, её можно использовать как приближение.
            if target_ts - float(chosen.get("time", 0) or 0) <= 5 * 60:
                return float(chosen["price"]), float(chosen["time"]), "near_snapshot"
    return float(current_price), float(now), "late_estimate"


def should_count_learning_seen(existing_rec, now, min_gap_seconds=60 * 60):
    """v15.2: seen_count — это редкое повторное появление в настоящем /signal, а не внутренние пересчёты.
    Минимальный шаг увеличен до 1 часа, чтобы fast-learning/background не раздувал счётчик десятками.
    """
    try:
        last_counted = float(existing_rec.get("last_seen_counted", existing_rec.get("time", 0)) or 0)
    except Exception:
        last_counted = 0
    if last_counted <= 0:
        return True
    return (float(now) - last_counted) >= min_gap_seconds


def learning_seen_count_cap(rec, now=None):
    """v15.2 hard cap: старые/фоновые пересчёты могли раздуть seen_count (например 50+ за час).
    Для честного обучения показываем не больше одного counted-появления в час жизни наблюдения.
    """
    if now is None:
        now = time.time()
    try:
        start_time = float(rec.get("time", 0) or 0)
    except Exception:
        start_time = 0
    if start_time <= 0:
        return 1
    age = max(0, float(now) - start_time)
    # 0-59 минут = 1, 1-2 часа = 2 и т.д.; максимум ограничен, чтобы отчёт не выглядел раздутым.
    return max(1, min(24, int(age // 3600) + 1))


def normalize_learning_seen_count(rec, now=None):
    """v15.2: чинит уже раздутые открытые наблюдения и не даёт счётчику расти нереалистично."""
    if now is None:
        now = time.time()
    changed = False
    try:
        seen = int(float(rec.get("seen_count", 1) or 1))
    except Exception:
        seen = 1
    cap = learning_seen_count_cap(rec, now)
    if seen < 1:
        rec["seen_count"] = 1
        changed = True
    elif seen > cap:
        rec["seen_count"] = cap
        rec["seen_count_note"] = "v15.2: раздутый счётчик встречаемости ограничен по возрасту наблюдения"
        # После нормализации не увеличиваем снова сразу на этом же цикле.
        rec["last_seen_counted"] = float(now)
        changed = True
    return rec, changed


_LEARNING_BG_LOCK = Lock()
_LEARNING_BG_LAST_START = 0

def background_learning_update(reason="learning"):
    """v16.2: /learning не должен ждать KuCoin/GitHub.
    Тяжёлое обновление checkpoints запускается фоном и не блокирует ответ пользователю.
    """
    global _LEARNING_BG_LAST_START
    now_ts = time.time()
    if now_ts - float(_LEARNING_BG_LAST_START or 0) < 45:
        return False
    _LEARNING_BG_LAST_START = now_ts

    def _run():
        acquired = False
        try:
            acquired = _LEARNING_BG_LOCK.acquire(False)
            if not acquired:
                return
            update_signal_results()
            # Отдельная frozen-база тоже обновляется фоном, без блокировки Telegram.
            try:
                data = load_json(RESULTS_FILE)
                if isinstance(data, dict):
                    closed = data.get("closed", [])
                    if isinstance(closed, list) and closed:
                        closed2, ch = normalize_closed_learning_records(closed, sync_now=False)
                        if ch:
                            data["closed"] = closed2
                            save_json(RESULTS_FILE, data)
                background_github_sync([FROZEN_RESULTS_FILE, RESULTS_FILE, RESULTS_BACKUP_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=4)
            except Exception as e:
                print(f"background learning freeze error: {e}")
        except Exception as e:
            print(f"background learning update error: {e}")
        finally:
            if acquired:
                try:
                    _LEARNING_BG_LOCK.release()
                except Exception:
                    pass

    try:
        Thread(target=_run, daemon=True).start()
        return True
    except Exception as e:
        print(f"background learning update start error: {e}")
        return False

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

        # v15.1: собираем короткую историю цен для честных fast-checkpoints.
        rec = append_learning_price_point(rec, current_price, now=now, min_gap_seconds=60)

        results = rec.setdefault("results", {})
        result_details = rec.setdefault("result_details", {})

        for _label, name, seconds in learning_checkpoints():
            # v15.1 freeze/snapshot: checkpoint фиксируется один раз и не плавает дальше.
            # Для 15м/30м/1ч стараемся брать цену около фактического времени checkpoint,
            # а не текущую цену на момент позднего вызова /learning.
            if age >= seconds and name not in results:
                target_ts = start_time + seconds
                checkpoint_price, checkpoint_time, checkpoint_source = checkpoint_price_from_points(
                    rec, target_ts, current_price, now
                )
                pct = round(percent_change(start_price, checkpoint_price), 2)
                results[name] = pct
                result_details[name] = {
                    "checkpoint_time": checkpoint_time,
                    "target_time": target_ts,
                    "checkpoint_price": round(checkpoint_price, 8),
                    "checkpoint_pct": pct,
                    "source": checkpoint_source
                }
                changed = True

        # Закрываем только после 48 часов.
        if age >= 48 * 3600 and "48h" in results:
            rec["closed_time"] = now
            # v15.4: фиксируем checkpoints закрытой записи один раз.
            rec["frozen_results"] = dict(results)
            try:
                rec["frozen_result_details"] = json.loads(json.dumps(result_details))
            except Exception:
                rec["frozen_result_details"] = dict(result_details)
            rec["frozen_at"] = float(now)
            rec["outcome"] = classify_learning_result(rec)
            rec["frozen_outcome"] = rec["outcome"]
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

# === v17.0 fast self-learning / historical bootstrap ===
_BACKTEST_BG_LOCK = Lock()
_BACKTEST_BG_LAST_START = 0

BACKTEST_ASSETS = ["BTC", "ETH", "SOL", "SUI", "LINK", "TAO", "NEAR", "AAVE", "BNB", "ADA", "AVAX", "INJ"]


def backtest_file_summary():
    data = load_json(BACKTEST_FILE)
    if not isinstance(data, dict) or not data.get("assets"):
        return "исторический backtest ещё не собран"
    try:
        updated = data.get("updated_at_msk") or data.get("updated_at", "?")
        assets_n = len(data.get("assets", {}) or {})
        samples = int(data.get("total_samples", 0) or 0)
        return f"исторический backtest: {assets_n} монет, {samples} проверок, обновлено {updated}"
    except Exception:
        return "исторический backtest есть, но сводка недоступна"


def fetch_daily_candles_for_backtest(asset, limit=120):
    """v17.0: отдельный быстрый загрузчик дневных свечей для backtest, не влияет на /weekday."""
    symbol = f"{asset}-USDT"
    try:
        data = requests.get(
            "https://api.kucoin.com/api/v1/market/candles",
            params={"symbol": symbol, "type": "1day"},
            timeout=8,
        ).json()
        if data.get("code") != "200000":
            return []
        candles = sorted(data.get("data", []), key=lambda x: int(x[0]))[-limit:]
        out = []
        for c in candles:
            try:
                ts = int(c[0])
                out.append({
                    "ts": ts,
                    "date": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"),
                    "weekday": datetime.utcfromtimestamp(ts).weekday(),
                    "open": float(c[1]),
                    "close": float(c[2]),
                    "high": float(c[3]),
                    "low": float(c[4]),
                })
            except Exception:
                continue
        return out
    except Exception as e:
        print(f"backtest daily candles error {asset}: {e}")
        return []


def _avg(vals, default=0.0):
    vals = [float(x) for x in vals if isinstance(x, (int, float))]
    if not vals:
        return default
    return round(sum(vals) / len(vals), 3)


def run_historical_backtest_update(days=90, assets=None):
    """v17.0: быстрый исторический bootstrap.
    Не создаёт реальные BUY-сигналы и не включает автоторговлю.
    Собирает дневные сценарии 24/48ч и даёт самообучению ранний ориентир.
    """
    if assets is None:
        assets = BACKTEST_ASSETS
    now = time.time()
    result = {
        "version": BOT_VERSION,
        "updated_at": datetime.utcnow().isoformat(),
        "updated_at_msk": moscow_now().strftime("%Y-%m-%d %H:%M"),
        "days": int(days),
        "assets": {},
        "total_samples": 0,
        "note": "Исторический дневной backtest: быстрый ориентир для весов, не торговая гарантия.",
    }

    for asset in assets:
        candles = fetch_daily_candles_for_backtest(asset, limit=max(30, int(days) + 5))
        # Нужны минимум 3 свечи: старт + 24ч + 48ч.
        if len(candles) < 10:
            continue

        samples = []
        # Последние 2 свечи не используем как 48ч финал.
        for i in range(0, max(0, len(candles) - 2)):
            c0, c1, c2 = candles[i], candles[i + 1], candles[i + 2]
            start = float(c0.get("open", 0) or 0)
            if start <= 0:
                continue
            try:
                pct24 = percent_change(start, float(c1.get("close", 0) or 0))
                pct48 = percent_change(start, float(c2.get("close", 0) or 0))
                low48 = min(float(c1.get("low", start) or start), float(c2.get("low", start) or start))
                high48 = max(float(c1.get("high", start) or start), float(c2.get("high", start) or start))
                dd48 = percent_change(start, low48)
                runup48 = percent_change(start, high48)
                samples.append({
                    "weekday": int(c0.get("weekday", 0)),
                    "24h": round(pct24, 3),
                    "48h": round(pct48, 3),
                    "drawdown48": round(dd48, 3),
                    "runup48": round(runup48, 3),
                })
            except Exception:
                continue

        if not samples:
            continue

        by_wd = {}
        for wd in range(7):
            rr = [x for x in samples if x.get("weekday") == wd]
            if not rr:
                continue
            by_wd[str(wd)] = {
                "n": len(rr),
                "avg_48h": _avg([x.get("48h") for x in rr]),
                "avg_drawdown48": _avg([x.get("drawdown48") for x in rr]),
                "avg_runup48": _avg([x.get("runup48") for x in rr]),
            }

        good48 = sum(1 for x in samples if x.get("48h", 0) >= 1.5)
        bad48 = sum(1 for x in samples if x.get("48h", 0) <= -2.5)
        strong_dd = sum(1 for x in samples if x.get("drawdown48", 0) <= -5)
        result["assets"][asset] = {
            "n": len(samples),
            "avg_24h": _avg([x.get("24h") for x in samples]),
            "avg_48h": _avg([x.get("48h") for x in samples]),
            "avg_drawdown48": _avg([x.get("drawdown48") for x in samples]),
            "avg_runup48": _avg([x.get("runup48") for x in samples]),
            "good48_rate": round(good48 / len(samples), 3),
            "bad48_rate": round(bad48 / len(samples), 3),
            "strong_drawdown_rate": round(strong_dd / len(samples), 3),
            "weekday": by_wd,
        }
        result["total_samples"] += len(samples)

    save_json(BACKTEST_FILE, result)
    background_github_sync([BACKTEST_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=3)
    return result


def maybe_run_backtest_background(force=False):
    """v17.0: запускает исторический bootstrap в фоне, не блокируя Telegram."""
    global _BACKTEST_BG_LAST_START
    now_ts = time.time()
    if (not force) and now_ts - float(_BACKTEST_BG_LAST_START or 0) < 12 * 3600:
        return False
    _BACKTEST_BG_LAST_START = now_ts

    def _run():
        acquired = False
        try:
            acquired = _BACKTEST_BG_LOCK.acquire(False)
            if not acquired:
                return
            run_historical_backtest_update(days=90)
        except Exception as e:
            print(f"historical backtest background error: {e}")
        finally:
            if acquired:
                try:
                    _BACKTEST_BG_LOCK.release()
                except Exception:
                    pass

    try:
        Thread(target=_run, daemon=True).start()
        return True
    except Exception as e:
        print(f"historical backtest start error: {e}")
        return False


def learn_fast_report(start=False):
    if start:
        started = maybe_run_backtest_background(force=True)
        if started:
            return (
                f"🧠 Ускоренное обучение запущено\n"
                f"Версия: {BOT_VERSION}\n\n"
                "Бот в фоне собирает исторический дневной backtest по BTC/ETH/SOL/SUI/LINK/TAO/NEAR/AAVE/BNB/ADA/AVAX/INJ.\n"
                "Это не включает автопокупки. Результат появится в /learning через 1–3 минуты."
            )
        return f"Версия: {BOT_VERSION}\nBacktest уже запущен или недавно запускался. Сводка: {backtest_file_summary()}"
    return f"🧠 Ускоренное обучение\nВерсия: {BOT_VERSION}\n{backtest_file_summary()}"


# === v17.1 paper trading / виртуальные сделки ===
_PAPER_BG_LOCK = Lock()


def paper_store():
    data = load_json(PAPER_TRADES_FILE)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", BOT_VERSION)
    data.setdefault("open", {})
    data.setdefault("closed", [])
    return data


def save_paper_store(data, sync=False):
    if not isinstance(data, dict):
        return
    data["version"] = BOT_VERSION
    save_json(PAPER_TRADES_FILE, data)
    if sync:
        background_github_sync([PAPER_TRADES_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=3)
    else:
        mark_github_dirty(PAPER_TRADES_FILE)


def paper_trade_key(asset, virtual_type, entry_ts):
    return f"{str(asset).upper()}:{virtual_type}:{int(float(entry_ts or 0) // 3600)}"


def paper_virtual_type(c):
    asset = str(c.get("symbol", "")).upper()
    action = str(c.get("action", "WATCH") or "WATCH").upper()
    change24 = float(c.get("change_24", c.get("change", 0)) or 0)
    is_quality = bool(c.get("is_quality")) or asset in QUALITY_LEARNING_ASSETS
    if (not is_quality) and change24 >= 12:
        return "AVOID_PUMP_TEST"
    if action == "BUY":
        return "VIRTUAL_BUY_TEST"
    if action in ["ACCUM", "WATCH"]:
        return "VIRTUAL_WATCH_ENTRY_TEST"
    return "VIRTUAL_OBSERVE_TEST"


def paper_open_from_signal_items(items, max_new=20):
    """Создаёт виртуальные сделки из текущих сигналов.
    Реальных покупок нет: это paper trading для ускоренного обучения.
    """
    data = paper_store()
    open_trades = data.get("open", {}) if isinstance(data.get("open", {}), dict) else {}
    now = time.time()
    created = 0

    # Один открытый paper-тест на монету, чтобы не раздувать историю от частых кнопок.
    already_assets = {str(t.get("asset", "")).upper() for t in open_trades.values() if isinstance(t, dict)}

    for c in items or []:
        try:
            asset = str(c.get("symbol", "")).upper()
            if not asset or asset in STABLE_SKIP_ASSETS:
                continue
            if asset in already_assets:
                continue
            price = float(c.get("price", 0) or 0)
            if price <= 0:
                continue
            score = int(float(c.get("score", 0) or 0))
            change24 = float(c.get("change_24", c.get("change", 0)) or 0)
            is_quality = bool(c.get("is_quality")) or asset in QUALITY_LEARNING_ASSETS

            # Берём только информативные случаи: качественные наблюдения или пампы, которые запрещаем догонять.
            if is_quality:
                if score < 50 and str(c.get("action", "")) != "BUY":
                    continue
            else:
                if change24 < 10:
                    continue

            vtype = paper_virtual_type(c)
            key = paper_trade_key(asset, vtype, now)
            if key in open_trades:
                continue

            ctx = c.get("ctx", {}) if isinstance(c.get("ctx", {}), dict) else {}
            open_trades[key] = {
                "id": key,
                "asset": asset,
                "entry_time": now,
                "entry_price": round(price, 10),
                "score": score,
                "master_score": c.get("_master_score", score),
                "source_action": c.get("action", "WATCH"),
                "virtual_type": vtype,
                "verdict": c.get("verdict", ""),
                "is_quality": bool(is_quality),
                "change_24": round(change24, 3),
                "btc_change": round(float(ctx.get("btc_change", 0) or 0), 3),
                "macro_mod": ctx.get("macro_mod", ctx.get("geo_mod", 0)),
                "results": {},
                "result_details": {},
                "status": "open",
                "note": "paper trading only: реальные сделки и автопокупки выключены",
            }
            already_assets.add(asset)
            created += 1
            if created >= max_new:
                break
        except Exception as e:
            print(f"paper open error: {e}")
            continue

    if created:
        data["open"] = open_trades
        data["last_created_at"] = now
        save_paper_store(data, sync=False)
    return created


def _paper_learning_rec_by_asset():
    data = load_json(RESULTS_FILE)
    out = {}
    if not isinstance(data, dict):
        return out
    open_items = data.get("open", {})
    if not isinstance(open_items, dict):
        return out
    for rec in open_items.values():
        if not isinstance(rec, dict):
            continue
        asset = str(rec.get("asset", "")).upper()
        if asset:
            out[asset] = rec
    return out


def paper_outcome(trade):
    res = trade.get("results", {}) if isinstance(trade.get("results", {}), dict) else {}
    vtype = str(trade.get("virtual_type", ""))
    r48 = res.get("48h")
    r24 = res.get("24h")
    value = r48 if isinstance(r48, (int, float)) else r24
    if not isinstance(value, (int, float)):
        return "open"
    if vtype == "AVOID_PUMP_TEST":
        if value <= -3:
            return "avoid_saved"
        if value >= 5:
            return "avoid_missed"
        return "avoid_neutral"
    if value >= 2.5:
        return "paper_win"
    if value <= -3:
        return "paper_loss"
    return "paper_neutral"


def paper_update_from_cache(close_after_seconds=48 * 3600):
    """Быстро обновляет paper trades по локальному learning-cache.
    Не ждёт сеть, поэтому /paper и /learning не должны зависать.
    """
    data = paper_store()
    open_trades = data.get("open", {}) if isinstance(data.get("open", {}), dict) else {}
    closed = data.get("closed", []) if isinstance(data.get("closed", []), list) else []
    if not open_trades:
        return False, 0, 0

    now = time.time()
    rec_by_asset = _paper_learning_rec_by_asset()
    changed = False
    updated = 0
    closed_n = 0

    for key, trade in list(open_trades.items()):
        if not isinstance(trade, dict):
            open_trades.pop(key, None)
            changed = True
            continue
        asset = str(trade.get("asset", "")).upper()
        entry_price = float(trade.get("entry_price", 0) or 0)
        entry_time = float(trade.get("entry_time", 0) or 0)
        if not asset or entry_price <= 0 or entry_time <= 0:
            open_trades.pop(key, None)
            changed = True
            continue

        rec = rec_by_asset.get(asset)
        current_price, price_ts, source = (None, 0, "none")
        if rec:
            current_price, price_ts, source = learning_cached_price_for_report(rec)
        try:
            current_price = float(current_price or 0)
            price_ts = float(price_ts or 0)
        except Exception:
            current_price, price_ts = 0, 0
        if current_price <= 0 or price_ts <= 0:
            continue

        age = max(0, now - entry_time)
        results = trade.setdefault("results", {})
        details = trade.setdefault("result_details", {})
        for label, name, seconds in learning_checkpoints():
            if age >= seconds and name not in results:
                pct = round(percent_change(entry_price, current_price), 2)
                results[name] = pct
                details[name] = {
                    "checkpoint_time": price_ts,
                    "checkpoint_price": round(current_price, 10),
                    "source": f"learning_cache:{source}",
                }
                changed = True
                updated += 1
        trade["last_price"] = round(current_price, 10)
        trade["last_price_time"] = price_ts
        trade["last_pct"] = round(percent_change(entry_price, current_price), 2)

        if age >= close_after_seconds and "48h" in results:
            trade["status"] = "closed"
            trade["closed_time"] = now
            trade["outcome"] = paper_outcome(trade)
            closed.append(trade)
            open_trades.pop(key, None)
            changed = True
            closed_n += 1
        else:
            open_trades[key] = trade

    if len(closed) > 1000:
        closed = closed[-1000:]
    if changed:
        data["open"] = open_trades
        data["closed"] = closed
        data["last_update_at"] = now
        save_paper_store(data, sync=False)
    return changed, updated, closed_n


def paper_summary_line():
    data = paper_store()
    open_n = len(data.get("open", {}) or {})
    closed = data.get("closed", []) if isinstance(data.get("closed", []), list) else []
    if not open_n and not closed:
        return "Виртуальные сделки: пока нет"
    wins = sum(1 for t in closed if paper_outcome(t) == "paper_win")
    losses = sum(1 for t in closed if paper_outcome(t) == "paper_loss")
    saved = sum(1 for t in closed if paper_outcome(t) == "avoid_saved")
    missed = sum(1 for t in closed if paper_outcome(t) == "avoid_missed")
    return f"Виртуальные сделки: открыто {open_n} | закрыто {len(closed)} | ✅ {wins} | 🔴 {losses} | 🛡 {saved} | ⚠️ {missed}"


def _paper_safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def paper_report():
    """Быстрый и устойчивый отчёт по виртуальным сделкам.
    v17.2: /paper не должен молча пропадать даже при битой записи в paper_trades.json.
    """
    update_note = ""
    try:
        paper_update_from_cache()
    except Exception as e:
        update_note = f"⚠️ Быстрое обновление paper-кэша не выполнено: {str(e)[:120]}\n"

    try:
        data = paper_store()
    except Exception as e:
        return (
            f"🧪 Paper trading ALEX EDGE\n"
            f"Версия: {BOT_VERSION}\n\n"
            "Режим: виртуальные сделки без реальных денег. Автопокупки выключены.\n"
            f"⚠️ Не смог прочитать paper_trades.json: {str(e)[:160]}\n"
        )

    raw_open = data.get("open", {}) if isinstance(data, dict) else {}
    open_trades = raw_open if isinstance(raw_open, dict) else {}
    raw_closed = data.get("closed", []) if isinstance(data, dict) else []
    closed = raw_closed if isinstance(raw_closed, list) else []

    try:
        summary = paper_summary_line()
    except Exception:
        summary = f"Виртуальные сделки: открыто {len(open_trades)} | закрыто {len(closed)}"

    text = (
        f"🧪 Paper trading ALEX EDGE\n"
        f"Версия: {BOT_VERSION}\n\n"
        "Режим: виртуальные сделки без реальных денег. Автопокупки выключены.\n"
        "Цель: проверить, что было бы при виртуальном входе/пропуске сигнала, без риска для денег.\n"
        f"{update_note}"
        f"{summary}\n"
        "📌 AVOID PUMP TEST: это не оценка упущенной прибыли. Он проверяет риск догонять резкий памп без отката; 24ч checkpoint учитывается как ранняя проверка, финальное закрытие и основной вывод — после 48ч.\n\n"
    )

    if open_trades:
        text += "🔎 Открытые виртуальные сделки:\n"
        shown = 0
        for t in list(open_trades.values())[:10]:
            if not isinstance(t, dict):
                continue
            asset = str(t.get("asset", "?")).upper()
            typ = str(t.get("virtual_type", "?")).replace("_", " ")
            entry = _paper_safe_float(t.get("entry_price"), 0)
            last = _paper_safe_float(t.get("last_price"), 0)
            pct = t.get("last_pct")
            age_seconds = max(0, time.time() - _paper_safe_float(t.get("entry_time"), time.time()))
            try:
                age = learning_age_text(age_seconds)
            except Exception:
                age = f"{int(age_seconds // 60)}м"
            if isinstance(pct, (int, float)) and last > 0:
                text += f"• {asset}: {typ} | ${entry:.6g} → ${last:.6g} ({pct:+.2f}%) | прошло {age}\n"
            elif last > 0:
                lpct = percent_change(entry, last) if entry > 0 else 0
                text += f"• {asset}: {typ} | ${entry:.6g} → ${last:.6g} ({lpct:+.2f}%) | прошло {age}\n"
            else:
                text += f"• {asset}: {typ} | вход ${entry:.6g} | прошло {age}\n"
            shown += 1
        if len(open_trades) > shown:
            text += f"…ещё открытых: {len(open_trades) - shown}\n"
        text += "\n"
    else:
        text += "Открытых paper-сделок пока нет. Нажми /signal, чтобы бот создал виртуальные проверки.\n\n"

    if closed:
        text += "📊 Последние закрытые paper-сделки:\n"
        for t in closed[-7:]:
            if not isinstance(t, dict):
                continue
            out = paper_outcome(t)
            r48 = (t.get("results", {}) or {}).get("48h")
            if isinstance(r48, (int, float)):
                text += f"• {t.get('asset','?')}: {out} | 48ч {r48:+.2f}%\n"
            else:
                text += f"• {t.get('asset','?')}: {out}\n"
    else:
        has_24h_open = False
        try:
            now_ts = time.time()
            for _t in open_trades.values():
                if isinstance(_t, dict) and now_ts - _paper_safe_float(_t.get("entry_time"), now_ts) >= 24 * 3600:
                    has_24h_open = True
                    break
        except Exception:
            has_24h_open = False

        if has_24h_open:
            text += "Закрытых paper-сделок пока нет. 24ч чекпоинты уже учитываются; финальное закрытие сделок и основной вывод будут после 48ч.\n"
        else:
            text += "Закрытых paper-сделок пока нет. Ранние чекпоинты копятся по ходу сделки; финальное закрытие и основной вывод будут после 48ч.\n"

    return text


def background_paper_update(reason="paper"):
    def _run():
        acquired = False
        try:
            acquired = _PAPER_BG_LOCK.acquire(False)
            if not acquired:
                return
            paper_update_from_cache()
            background_github_sync([PAPER_TRADES_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=3)
        except Exception as e:
            print(f"background paper update error {reason}: {e}")
        finally:
            if acquired:
                try:
                    _PAPER_BG_LOCK.release()
                except Exception:
                    pass
    try:
        Thread(target=_run, daemon=True).start()
    except Exception as e:
        print(f"paper background start error: {e}")


def backtest_learning_adjustment(c):
    """Мягкий исторический fallback, пока реальных закрытых 48ч наблюдений мало."""
    try:
        data = load_json(BACKTEST_FILE)
        assets = data.get("assets", {}) if isinstance(data, dict) else {}
        asset = str(c.get("symbol", "")).upper()
        stats = assets.get(asset)
        if not isinstance(stats, dict):
            return 0, "исторический backtest ещё не собран"

        n = int(stats.get("n", 0) or 0)
        if n < 30:
            return 0, f"исторический backtest: мало данных ({n})"

        avg48 = float(stats.get("avg_48h", 0) or 0)
        bad_rate = float(stats.get("bad48_rate", 0) or 0)
        good_rate = float(stats.get("good48_rate", 0) or 0)
        dd_rate = float(stats.get("strong_drawdown_rate", 0) or 0)
        is_quality = bool(c.get("is_quality")) or asset in QUALITY_LEARNING_ASSETS
        change24 = float(c.get("change_24", c.get("change", 0)) or 0)

        # Неизвестные/спекулятивные пампы: исторический слой усиливает осторожность.
        if (not is_quality) and change24 >= 12:
            return -3, f"исторический backtest: пампы часто откатываются, усиливаю осторожность ({n})"

        # Качественный актив, но история по 48ч плохая/просадочная — лёгкий cap вниз.
        if is_quality and (bad_rate >= 0.42 or dd_rate >= 0.45 or avg48 <= -0.7):
            return -2, f"исторический backtest: у похожего режима слабый 48ч профиль ({n})"

        # Качественный актив с устойчивым профилем — только маленький плюс и не в плохом рынке.
        ctx = c.get("ctx", {}) if isinstance(c.get("ctx", {}), dict) else {}
        macro = float(ctx.get("macro_mod", ctx.get("geo_mod", 0)) or 0)
        btc_ch = float(ctx.get("btc_change", 0) or 0)
        if is_quality and good_rate >= 0.45 and avg48 >= 0.5 and macro >= -4 and btc_ch >= 0:
            return +1, f"исторический backtest: умеренно положительный 48ч профиль ({n})"

        return 0, f"исторический backtest: нейтральный профиль ({n})"
    except Exception as e:
        print(f"backtest learning adjustment error: {e}")
        return 0, "исторический backtest недоступен"


def v83_learning_adjustment(c):
    """
    Простое самообучение без опасного автотрейдинга:
    если похожие сигналы часто проваливались — режем score;
    если часто работали — чуть повышаем уверенность.
    """
    sample = learning_sample_for(c)

    if len(sample) < 10:
        hist_delta, hist_note = backtest_learning_adjustment(c)
        if hist_delta:
            return hist_delta, f"самообучение: закрытых live-результатов пока {len(sample)}; открытые наблюдения копятся; {hist_note}"
        return 0, f"самообучение: закрытых live-результатов пока {len(sample)}; открытые наблюдения копятся; {hist_note}"

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

def russian_raz_word(n):
    """Правильное склонение для строки seen_count: 1 раз, 2 раза, 5 раз."""
    try:
        n = abs(int(n))
    except Exception:
        n = 0
    if n % 100 in [11, 12, 13, 14]:
        return "раз"
    if n % 10 == 1:
        return "раз"
    if n % 10 in [2, 3, 4]:
        return "раза"
    return "раз"

def learning_price_now(asset):
    try:
        ticker = get_ticker(f"{asset}-USDT")
        if not ticker:
            return None
        price = float(ticker.get("last", 0) or 0)
        return price if price > 0 else None
    except Exception:
        return None


def learning_cached_price_for_report(rec):
    """v16.2: быстрый /learning не ходит в сеть за текущей ценой.
    Берём последний сохранённый snapshot из price_points. Если его нет — стартовую цену.
    """
    try:
        pts = learning_price_points(rec)
        if pts:
            last = pts[-1]
            return float(last.get("price", 0) or 0), float(last.get("time", 0) or 0), "snapshot"
    except Exception:
        pass
    try:
        price = float(rec.get("last_price", 0) or rec.get("current_price", 0) or 0)
        if price > 0:
            return price, float(rec.get("last_price_time", 0) or 0), "cached"
    except Exception:
        pass
    try:
        start_price = float(rec.get("price", 0) or 0)
        if start_price > 0:
            return start_price, float(rec.get("time", 0) or 0), "start"
    except Exception:
        pass
    return None, 0, "none"

def freeze_due_learning_checkpoints_from_cache(max_snapshot_age_seconds=3 * 3600):
    """v16.3: быстрый /learning не ходит в KuCoin, но если checkpoint уже наступил,
    фиксируем его из последнего локального price_points/cache.
    Это убирает ситуацию "6ч: ждём 0м" без возврата зависаний.
    """
    data = load_json(RESULTS_FILE)
    if not isinstance(data, dict):
        return False
    open_items = data.get("open", {})
    if not isinstance(open_items, dict) or not open_items:
        return False

    now = time.time()
    changed = False

    for key, rec in list(open_items.items()):
        if not isinstance(rec, dict):
            continue
        try:
            start_price = float(rec.get("price", 0) or 0)
            start_time = float(rec.get("time", 0) or 0)
        except Exception:
            continue
        if start_price <= 0 or start_time <= 0:
            continue

        age = now - start_time
        if age <= 0:
            continue

        current_price, price_ts, price_source = learning_cached_price_for_report(rec)
        try:
            current_price = float(current_price or 0)
            price_ts = float(price_ts or 0)
        except Exception:
            current_price = 0
            price_ts = 0
        if current_price <= 0 or price_ts <= 0:
            continue
        # Если кэш совсем старый, не фиксируем новый checkpoint по нему.
        # Но старые checkpoints не трогаем.
        if now - price_ts > max_snapshot_age_seconds:
            continue

        results = rec.setdefault("results", {})
        if not isinstance(results, dict):
            results = {}
            rec["results"] = results
        result_details = rec.setdefault("result_details", {})
        if not isinstance(result_details, dict):
            result_details = {}
            rec["result_details"] = result_details

        for _label, name, seconds in learning_checkpoints():
            if age >= seconds and name not in results:
                target_ts = start_time + seconds
                checkpoint_price, checkpoint_time, checkpoint_source = checkpoint_price_from_points(
                    rec, target_ts, current_price, price_ts
                )
                pct = round(percent_change(start_price, checkpoint_price), 2)
                results[name] = pct
                result_details[name] = {
                    "checkpoint_time": float(checkpoint_time),
                    "target_time": float(target_ts),
                    "checkpoint_price": round(float(checkpoint_price), 8),
                    "checkpoint_pct": pct,
                    "source": f"cache_due_{checkpoint_source}",
                    "cache_price_time": float(price_ts),
                    "cache_price_source": str(price_source),
                }
                changed = True

        open_items[key] = rec

    if changed:
        data["open"] = open_items
        data.setdefault("version", BOT_VERSION)
        save_json(RESULTS_FILE, data)
        background_github_sync([RESULTS_FILE, RESULTS_BACKUP_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=3)
    return changed

def learning_checkpoints():
    # v15.0: быстрые точки обучения. 48ч — финальная, остальные дают раннюю статистику.
    return [
        ("15м", "15m", 15 * 60),
        ("30м", "30m", 30 * 60),
        ("1ч", "1h", 3600),
        ("3ч", "3h", 3 * 3600),
        ("6ч", "6h", 6 * 3600),
        ("12ч", "12h", 12 * 3600),
        ("24ч", "24h", 24 * 3600),
        ("48ч", "48h", 48 * 3600),
    ]

def learning_outcome_text(outcome, rec=None):
    if outcome == "success":
        return "✅ сработало"
    if outcome == "bad":
        return "🔴 ошибся"
    if outcome == "watch_saved":
        return "🛡 WATCH спас от падения"
    if outcome == "missed_move":
        if rec and str(rec.get("asset", "")).upper() not in QUALITY_LEARNING_ASSETS:
            return "⚠️ спекулятивный рост, не приравнивать к качественному BUY"
        return "⚠️ WATCH пропустил рост"
    if outcome == "neutral":
        return "🟡 нейтрально"
    return "⏳ открыто"

def closed_learning_detail_rows(closed, limit=8):
    if not closed:
        return ""

    rows = sorted(
        closed[-limit:],
        key=lambda r: float(r.get("closed_time", r.get("time", 0)) or 0),
        reverse=True
    )

    text = "\n🔍 Детально по закрытым 48ч:\n"
    for rec in rows:
        asset = str(rec.get("asset", "?")).upper()
        results = learning_results_for_eval(rec)
        r48 = results.get("48h")
        r24 = results.get("24h")
        r6 = results.get("6h")
        start_price = rec.get("price", 0)
        score = rec.get("score", "н/д")
        action = learning_display_action(rec.get("action", "WATCH"), rec.get("verdict", ""))
        outcome = classify_learning_result(rec)

        parts = []
        if isinstance(r6, (int, float)):
            parts.append(f"6ч {r6:+.2f}%")
        if isinstance(r24, (int, float)):
            parts.append(f"24ч {r24:+.2f}%")
        if isinstance(r48, (int, float)):
            parts.append(f"48ч {r48:+.2f}%")

        detail = " | ".join(parts) if parts else "нет checkpoints"
        text += (
            f"• {asset}: {learning_outcome_text(outcome, rec)} | "
            f"старт ${float(start_price or 0):.6g} | score {score}/100 | {action}\n"
            f"  {detail}\n"
        )

        if outcome == "neutral" and asset in ["BTC", "ETH"]:
            text += "  вывод: умеренный плюс по наблюдению допустим, но это не был BUY-сигнал.\n"
        elif outcome == "missed_move" and asset in QUALITY_LEARNING_ASSETS:
            text += "  вывод: качественный актив вырос — в будущем можно раньше переводить сильный WATCH в приоритетное наблюдение.\n"
        elif outcome == "missed_move":
            text += "  вывод: рост был спекулятивный; не усиливать BUY так же, как по качественным активам.\n"
        elif outcome == "watch_saved":
            text += "  вывод: осторожность была полезной, памп/риск подтвердился.\n"

    return text

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

    checkpoints = learning_checkpoints()

    parts = []
    age = max(0, now - start_time)

    for label, key, seconds in checkpoints:
        value = results.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{label}: {learning_result_icon(value, action)} {value:+.2f}%")
        else:
            left = max(0, seconds - age)
            if left <= 0:
                parts.append(f"{label}: ожидает кэш/фон")
            else:
                parts.append(f"{label}: ждём {learning_age_text(left)}")

    return " | ".join(parts)

def learning_display_action(action, verdict=""):
    verdict_text = str(verdict or "")
    if action == "ACCUM" and ("НАБЛЮДАТЬ" in verdict_text or ("КАНДИДАТ" in verdict_text or "АКТИВ К НАБЛЮДЕНИЮ" in verdict_text) or "СПЕКУЛЯТИВ" in verdict_text):
        return "НАБЛЮДЕНИЕ"
    if action == "WATCH":
        return "НАБЛЮДЕНИЕ"
    if action == "ACCUM":
        return "НАБЛЮДЕНИЕ / НЕ ВХОД"
    return action or "н/д"

def normalize_learning_open_records(open_items):
    """
    v12.5:
    Обучение не должно хранить GRAM/LAB/мелкие монеты как сильный среднесрочный набор.
    Неизвестные/спекулятивные монеты cap 55/100 и только наблюдение.
    Качественные альты в страхе/сомнительном рынке cap 68/100 и без "Среднесрок".
    """
    if not isinstance(open_items, dict):
        return {}, False, 0

    changed = False
    fixed = 0

    now_norm = time.time()

    for key, rec in list(open_items.items()):
        rec, seen_changed = normalize_learning_seen_count(rec, now=now_norm)
        if seen_changed:
            open_items[key] = rec
            changed = True
            fixed += 1

        asset = str(rec.get("asset") or rec.get("symbol") or key).upper()
        score = int(float(rec.get("score", 0) or 0))
        master = int(float(rec.get("master_score", score) or score))
        action = rec.get("action", "")
        verdict = str(rec.get("verdict", ""))

        if asset in STABLE_SKIP_ASSETS:
            open_items.pop(key, None)
            changed = True
            fixed += 1
            continue

        unsafe_medium = (
            "СРЕДНЕСРОЧ" in verdict
            or "первая" in str(rec).lower()
            or action in ["BUY", "PUMP"]
            or score >= 75
        )

        # BTC/ETH после старых версий: не показываем как набор.
        if asset in ["BTC", "ETH"] and unsafe_medium:
            cap = 68 if asset == "BTC" else 70
            rec["score"] = min(score, cap)
            rec["master_score"] = min(master, cap)
            rec["action"] = "WATCH"
            rec["verdict"] = "🟡 НАБЛЮДАТЬ / ЖДАТЬ СТАБИЛИЗАЦИЮ"
            rec["learning_type"] = "WATCH"
            rec["learning_note"] = "v12.5 repair: крупный актив переведён в наблюдение"
            rec.setdefault("tags", [])
            if "v12_5_learning_repair" not in rec["tags"]:
                rec["tags"].append("v12_5_learning_repair")
            open_items[key] = rec
            changed = True
            fixed += 1
            continue

        # Качественные альты: TAO/SOL/NEAR и т.п. — только кандидат после стабилизации, не "Среднесрок".
        if asset in QUALITY_LEARNING_ASSETS and asset not in ["BTC", "ETH"]:
            if unsafe_medium or score > 68 or "СРЕДНЕСРОЧ" in verdict:
                rec["score"] = min(score, 68)
                rec["master_score"] = min(master, 68)
                rec["action"] = "WATCH"
                rec["verdict"] = "🟡 АКТИВ К НАБЛЮДЕНИЮ ПОСЛЕ СТАБИЛИЗАЦИИ BTC"
                rec["learning_type"] = "WATCH"
                rec["learning_note"] = "v12.5 repair: качественный альт оставлен только как наблюдение"
                rec.setdefault("tags", [])
                if "v12_5_quality_alt_cap" not in rec["tags"]:
                    rec["tags"].append("v12_5_quality_alt_cap")
                open_items[key] = rec
                changed = True
                fixed += 1
            continue

        # Неизвестные/спекулятивные монеты: GRAM/LAB/мелкие монеты не должны быть 84/100.
        if asset not in QUALITY_LEARNING_ASSETS:
            if unsafe_medium or score > 55 or "СРЕДНЕСРОЧ" in verdict:
                rec["score"] = min(score, 55)
                rec["master_score"] = min(master, 55)
                rec["action"] = "WATCH"
                rec["verdict"] = "🟡 СПЕКУЛЯТИВНОЕ НАБЛЮДЕНИЕ / НЕ ДОГОНЯТЬ"
                rec["learning_type"] = "WATCH"
                rec["learning_note"] = "v12.5 repair: неизвестная/спекулятивная монета ограничена до 55/100"
                rec.setdefault("tags", [])
                for tag in ["speculative", "v12_5_speculative_cap"]:
                    if tag not in rec["tags"]:
                        rec["tags"].append(tag)
                open_items[key] = rec
                changed = True
                fixed += 1

    return open_items, changed, fixed


def v18_checkpoint_values(rec):
    results = rec.get("results", {}) if isinstance(rec.get("results", {}), dict) else {}
    ordered = []
    for name in ["15m", "30m", "1h", "3h", "6h", "12h", "24h", "48h"]:
        v = results.get(name)
        if isinstance(v, (int, float)):
            ordered.append((name, float(v)))
    return ordered

def v18_learning_decision_class(rec, final_only=False):
    """v18.0: единый классификатор решения, пока без агрессивной смены весов.
    48ч остаётся золотым стандартом; ранние checkpoints дают только предварительный вывод.
    """
    if not isinstance(rec, dict):
        return "open", "⏳ данных нет"

    action = str(rec.get("action", "WATCH") or "WATCH").upper()
    verdict = str(rec.get("verdict", "") or "")
    values = v18_checkpoint_values(rec)
    if final_only:
        values = [(k, v) for k, v in values if k in ["24h", "48h"]]
    if not values:
        return "open", "⏳ ждём checkpoints"

    best_name, best = max(values, key=lambda kv: kv[1])
    worst_name, worst = min(values, key=lambda kv: kv[1])
    last_name, last = values[-1]
    is_avoid_pump = ("НЕ ДОГОНЯТЬ" in verdict) or ("СПЕКУЛЯТИВ" in verdict)

    if action == "WATCH":
        if is_avoid_pump:
            if worst <= -5.0:
                return "avoid_pump_saved", f"🛡 не догонять было правильно: просадка {worst:+.2f}% на {worst_name}"
            if best >= 8.0 and last >= 5.0:
                return "avoid_pump_missed", f"⚠️ памп продолжился: лучший рост {best:+.2f}% на {best_name}"
            if best >= 5.0:
                return "avoid_pump_watch", f"🟡 памп ещё спорный: был рост {best:+.2f}% на {best_name}, ждём 24/48ч"
            return "avoid_pump_neutral", f"🟡 памп под наблюдением: текущий checkpoint {last_name} {last:+.2f}%"
        if worst <= -4.0:
            return "watch_saved", f"🛡 WATCH спас от просадки {worst:+.2f}% на {worst_name}"
        if best >= 5.0 and last >= 3.0:
            return "watch_missed", f"⚠️ WATCH мог быть слишком осторожным: {best:+.2f}% на {best_name}"
        return "watch_neutral", f"🟡 WATCH нейтрально: {last_name} {last:+.2f}%"

    if action in ["BUY", "ACCUM"]:
        if worst <= -5.0:
            return "entry_bad", f"🔴 вход был плохой: просадка {worst:+.2f}% на {worst_name}"
        if best >= 3.0:
            return "entry_good", f"✅ вход работал: лучший рост {best:+.2f}% на {best_name}"
        return "entry_neutral", f"🟡 вход нейтральный: {last_name} {last:+.2f}%"

    return "neutral", f"🟡 нейтрально: {last_name} {last:+.2f}%"

def v18_learning_core_summary(data):
    if not isinstance(data, dict):
        return ""
    open_items = data.get("open", {}) if isinstance(data.get("open", {}), dict) else {}
    closed = data.get("closed", []) if isinstance(data.get("closed", []), list) else []

    classes = {}
    preview = []
    for rec in open_items.values():
        cls, note = v18_learning_decision_class(rec)
        classes[cls] = classes.get(cls, 0) + 1
        vals = v18_checkpoint_values(rec)
        if vals:
            preview.append((str(rec.get("asset", "?")).upper(), cls, note, vals[-1][0]))

    if not open_items and not closed:
        return ""

    saved = classes.get("avoid_pump_saved", 0) + classes.get("watch_saved", 0)
    missed = classes.get("avoid_pump_missed", 0) + classes.get("watch_missed", 0)
    neutral = sum(v for k, v in classes.items() if "neutral" in k or k in ["avoid_pump_watch"])

    lines = [
        "🧠 v18.0 ALEX EDGE CORE",
        "Режим: уникальное ядро обучения включено; ранние checkpoints учитываются как предварительные выводы, веса меняются только после закрытых 48ч результатов.",
        f"Ранние выводы по открытым наблюдениям: 🛡 спасло/не догонять правильно {saved} | ⚠️ возможно слишком осторожно {missed} | 🟡 нейтрально/спорно {neutral}",
    ]

    if preview:
        lines.append("Ключевые ранние кейсы:")
        for asset, cls, note, last_cp in preview[:5]:
            lines.append(f"• {asset}: {note}")

    if closed:
        outcomes = [classify_learning_result(x) for x in closed]
        lines.append(
            f"Закрытые 48ч: всего {len(closed)} | ✅ {outcomes.count('success')} | 🛡 {outcomes.count('watch_saved')} | ⚠️ {outcomes.count('missed_move')} | 🔴 {outcomes.count('bad')}"
        )
    else:
        lines.append("Закрытых 48ч пока 0: адаптивные веса только готовятся, без опасных резких изменений.")

    return "\n".join(lines) + "\n\n"

def learning_open_rows(open_items, limit=6):
    if not isinstance(open_items, dict) or not open_items:
        return "Открытых наблюдений нет.\n"

    now = time.time()
    rows = sorted(
        list(open_items.values()),
        key=lambda r: float(r.get("time", 0) or 0)
    )

    text = ""
    for rec in (rows if limit is None else rows[:limit]):
        asset = rec.get("asset", "?")
        start_price = float(rec.get("price", 0) or 0)
        current_price, price_ts, price_source = learning_cached_price_for_report(rec)
        age = now - float(rec.get("time", 0) or 0)
        close_left = max(0, 48 * 3600 - age)

        if current_price and start_price > 0:
            now_pct = percent_change(start_price, current_price)
            if price_source in ["snapshot", "cached"] and price_ts:
                stale_min = max(0, int((now - float(price_ts)) // 60))
                price_note = f"снимок {stale_min}м назад"
            elif price_source == "start":
                price_note = "стартовая цена, ждём фоновое обновление"
            else:
                price_note = "кэш"
            price_line = f"цена: ${start_price:.6g} → ${current_price:.6g} ({now_pct:+.2f}%) | {price_note}"
        else:
            price_line = f"цена записи: ${start_price:.6g}, кэш цены пуст"

        action = rec.get("action", "н/д")
        score = rec.get("score", "н/д")
        verdict = rec.get("verdict", "н/д")
        action_label = learning_display_action(action, verdict)
        seen_count = int(rec.get("seen_count", 1) or 1)

        text += (
            f"• {asset}: {action_label}, score {score}/100\n"
            f"  статус: {verdict}\n"
            f"  {price_line}\n"
            f"  прошло: {learning_age_text(age)} | закрытие через: {learning_age_text(close_left)} | встречалось: {seen_count} {russian_raz_word(seen_count)}\n"
            f"  проверки: {learning_checkpoint_status(rec, now)}\n"
        )

    if limit is not None and len(rows) > limit:
        text += f"…ещё открытых наблюдений: {len(rows) - limit}\n"

    return text

def learning_report(sync_github=False, full=False):
    # v16.2:
    # /learning должен отвечать мгновенно. Не ждём KuCoin и GitHub в пользовательском ответе.
    # Обычный /learning читает локальный кэш, а обновление checkpoints запускает фоном.
    if sync_github:
        update_signal_results()
        sync_github_storage_now([FROZEN_RESULTS_FILE, RESULTS_FILE, RESULTS_BACKUP_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=4)
    else:
        background_learning_update("manual_learning")

    data = load_json(RESULTS_FILE)
    if not isinstance(data, dict):
        return (
            f"📚 Самообучение ALEX EDGE\n"
            f"Версия: {BOT_VERSION}\n\n"
            "Истории пока нет.\n"
            "Возможная причина: файл истории ещё не создан или сбросился после деплоя Render."
        )

    # v17.5: если после /signal/GitHub-cache race история внезапно стала короче,
    # восстанавливаем закрытые 48ч из frozen store и открытые наблюдения из backup.
    data, _guard_changed = repair_learning_data_from_backup_and_frozen(data)
    if _guard_changed:
        save_json(RESULTS_FILE, data)
        background_github_sync([FROZEN_RESULTS_FILE, RESULTS_FILE, RESULTS_BACKUP_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=5)

    # v16.3: если 6ч/12ч/24ч уже наступили, фиксируем checkpoint из локального кэша
    # без сетевых запросов. Это быстро и убирает "ждём 0м".
    if freeze_due_learning_checkpoints_from_cache():
        data = load_json(RESULTS_FILE)
        if not isinstance(data, dict):
            data = {}

    open_items = data.get("open", {})
    open_items, dedup_changed = v87_cleanup_open_learning_duplicates(open_items)
    open_items, normalized, fixed_count = normalize_learning_open_records(open_items)
    if dedup_changed or normalized:
        data["open"] = open_items
        save_json(RESULTS_FILE, data)
        background_github_sync([RESULTS_FILE, RESULTS_BACKUP_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=3)

    closed = data.get("closed", [])
    closed, closed_normalized = normalize_closed_learning_records(closed, sync_now=sync_github)
    if closed_normalized:
        data["closed"] = closed
        save_json(RESULTS_FILE, data)
        # v16.2: обычный /learning не ждёт GitHub. Синхронизация только фоном.
        if sync_github:
            sync_github_storage_now([FROZEN_RESULTS_FILE, RESULTS_FILE, RESULTS_BACKUP_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=4)
        else:
            background_github_sync([FROZEN_RESULTS_FILE, RESULTS_FILE, RESULTS_BACKUP_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=4)
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
        f"Режим отчёта: быстрый кэш; наступившие checkpoints фиксируются из кэша, тяжёлое обновление идёт фоном.\n"
        f"v18.0: learning core классифицирует WATCH/AVOID/BUY по ранним и 48ч результатам.\n"
        f"Ускорение: {backtest_file_summary()}\n"
        f"Paper trading: {paper_summary_line()}\n"
        f"Открытых наблюдений: {len(open_items)}\n"
        f"Закрытых 48ч результатов: {total}\n\n"
    )

    text += v18_learning_core_summary(data)
    text += "🔎 Открытые наблюдения:\n"
    text += learning_open_rows(open_items, limit=None if full else 6)
    text += "\n"

    if total == 0:
        text += (
            "Итог пока: закрытых 48ч результатов нет, поэтому бот ещё не меняет веса по статистике.\n"
            "Fast-learning уже проверяет наблюдения через 15м / 30м / 1ч / 3ч / 6ч / 12ч / 24ч / 48ч.\n"
            "48ч остаётся финальной оценкой качества прогноза."
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
        f"⚠️ WATCH пропустил рост: {missed}\n"
    )

    text += closed_learning_detail_rows(closed, limit=8) + "\n"

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
            current_price_for_seen = round(float(c.get("price", 0) or 0), 8)
            existing_rec["last_seen"] = now
            existing_rec["last_price"] = current_price_for_seen
            existing_rec["last_score"] = c.get("score", 0)
            existing_rec["last_action"] = c.get("action")
            existing_rec["last_verdict"] = c.get("verdict")

            # v15.1: price snapshots нужны для честных 15м/30м/1ч checkpoints.
            existing_rec = append_learning_price_point(existing_rec, current_price_for_seen, now=now, min_gap_seconds=60)

            # v15.2: seen_count не должен расти от каждого внутреннего пересчёта/фонового скана.
            existing_rec, _seen_fixed = normalize_learning_seen_count(existing_rec, now=now)
            if should_count_learning_seen(existing_rec, now, min_gap_seconds=60 * 60):
                cap = learning_seen_count_cap(existing_rec, now=now)
                existing_rec["seen_count"] = min(cap, int(existing_rec.get("seen_count", 1) or 1) + 1)
                existing_rec["last_seen_counted"] = now

            # Если старая версия успела записать сигнал слишком оптимистично,
            # переписываем открытое наблюдение в безопасный режим, чтобы не портить обучение.
            if (
                c.get("_falling_market_no_buy")
                or c.get("_danger_market_cap")
                or c.get("_danger_alt_cap")
                or c.get("_safe_caution_cap")
                or c.get("_safe_caution_alt_cap")
            ):
                existing_rec["action"] = c.get("action")
                existing_rec["verdict"] = c.get("verdict")
                existing_rec["score"] = c.get("score", existing_rec.get("score", 0))
                existing_rec["master_score"] = c.get("_master_score", c.get("score", existing_rec.get("score", 0)))
                existing_rec["chance_5"] = c.get("chance_5", existing_rec.get("chance_5", 0))
                existing_rec["chance_10"] = c.get("chance_10", existing_rec.get("chance_10", 0))
                existing_rec["chance_15"] = c.get("chance_15", existing_rec.get("chance_15", 0))
                existing_rec["learning_type"] = learning_signal_type(c)
                existing_rec["learning_note"] = "safe-fix: сигнал переведён в наблюдение из-за слабого BTC/страха"
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
            "last_seen_counted": now,
            "seen_count": 1,
            "results": {},
            "price_points": [{"time": now, "price": round(float(c.get("price", 0) or 0), 8)}]
        }

        open_items[signal_key(c["symbol"], now)] = rec

    # v17.7.2: финальный cleanup после добавления новых записей.
    # Это защищает fast-learning и command pool от скрытых дублей, если одна монета пришла
    # из /signal, /coin и фонового scan почти одновременно.
    open_items, _dedup_changed = v87_cleanup_open_learning_duplicates(open_items)
    results["open"] = open_items
    results.setdefault("closed", [])
    results["version"] = BOT_VERSION

    save_json(HISTORY_FILE, h)
    save_json(RESULTS_FILE, results)

    # v17.1: каждый /signal параллельно открывает виртуальные paper-тесты.
    # Это ускоряет самообучение без реальных сделок.
    try:
        paper_open_from_signal_items(items, max_new=20)
        background_paper_update("signal_history")
    except Exception as e:
        print(f"paper from signal error: {e}")

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

    if c.get("_extreme_fear_cap"):
        return "экстремальный страх + BTC в минусе + ждать стабилизацию"

    if c.get("_extreme_fear_alt_cap"):
        return "после стабилизации BTC + экстремальный страх"

    if c.get("_safe_caution_cap"):
        return "страх экстремальный + BTC почти -2% + ждать стабилизацию"

    if c.get("_safe_caution_alt_cap"):
        return "после стабилизации BTC + нужен разворот рынка"

    if c.get("_danger_market_cap"):
        if btc_change <= -2.5 and macro_mod <= -6:
            return "BTC падает почти -3% + страх + негативные новости"
        if btc_change <= -2.5:
            return "BTC падает почти -3% + страх"
        if btc_change <= -2.3:
            return "BTC падает сильнее -2.3% + страх"
        return "страх высокий + BTC падает + риск рынка опасный"

    if c.get("_danger_alt_cap"):
        return "после разворота рынка + нужна стабилизация BTC"

    if c.get("_bad_news_quality_alt_watch"):
        return "опасные новости, BTC держится, но вход не подтверждён"

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

    if c.get("_btc_drop_wording_guard"):
        return "BTC падает около -2%, перепроданность без стабилизации не является входом"

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
    if c.get("_extreme_fear_cap"):
        return "без входа сейчас; ждать стабилизацию"

    if c.get("_extreme_fear_alt_cap"):
        return "после стабилизации BTC / без входа"

    if c.get("_safe_caution_cap"):
        return "без входа сейчас; ждать стабилизацию"

    if c.get("_safe_caution_alt_cap"):
        return "после стабилизации BTC / без входа"

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
            return f"📚 Самообучение: открытых {len(open_items)} | закрытых {len(closed)} | ✅ {success} | 🔴 {bad} | 🛡 {watch_saved} | fast 15м–48ч\n"

        if isinstance(open_items, dict) and len(open_items):
            return f"📚 Самообучение: открытых наблюдений {len(open_items)}, fast-checkpoints 15м–48ч\n"

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
    elif v106_safe_caution(ctx) or v115_extreme_fear_btc_weak(ctx):
        text = "⏳ Кандидаты после стабилизации BTC:\n"
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

        if v106_safe_caution(c.get("ctx", {})) or v115_extreme_fear_btc_weak(c.get("ctx", {})):
            if "после стабилизации BTC" not in reasons:
                reasons.insert(0, "после стабилизации BTC")
            score = min(c.get("_master_score", c.get("score", 0)), 68)
        else:
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
    accum_label = "🟦 Активы для наблюдения" if (market_risk_level(ctx) == "danger" or v106_safe_caution(ctx) or v115_extreme_fear_btc_weak(ctx)) else "🟦 Среднесрок"
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


def v115_apply_extreme_fear_wording_fix(c):
    """
    v11.5:
    Страх 14–15 + BTC в минусе = без среднесрока и первой части.
    Режим не обязательно danger, но это строгое наблюдение.
    """
    if not c:
        return c

    c = dict(c)
    ctx = c.get("ctx", {})
    symbol = c.get("symbol", "")

    if not v115_extreme_fear_btc_weak(ctx):
        return c

    if symbol in ["BTC", "ETH"] and c.get("action") in ["BUY", "PUMP", "ACCUM", "WATCH", "SKIP"]:
        cap = 68 if symbol == "BTC" else 70
        current = int(c.get("score", 0) or 0)
        score = min(max(current, 55), cap)

        c["score"] = score
        c["_master_score"] = score
        c["_accumulation_score"] = score
        c["action"] = "ACCUM"
        c["verdict"] = "🟡 НАБЛЮДАТЬ / ЖДАТЬ СТАБИЛИЗАЦИЮ"
        c["_extreme_fear_cap"] = True
        c["_red_market_cap"] = True

        c["chance_5"] = min(max(c.get("chance_5", 0), 8), 22)
        c["chance_10"] = min(max(c.get("chance_10", 0), 2), 5)
        c["chance_15"] = min(max(c.get("chance_15", 0), 1), 3)

        c["low"] = min(c.get("low", -2.0), -2.5)
        c["high"] = min(max(c.get("high", 0), 1.2), 2.5 if symbol == "BTC" else 2.8)
        c["entry_zone"] = "без входа сейчас: экстремальный страх, ждать стабилизацию BTC и рост объёма"

        c.setdefault("minus", [])
        for reason in [
            "экстремальный страх",
            "BTC в минусе",
            "первая часть запрещена до стабилизации"
        ]:
            if reason not in c["minus"]:
                c["minus"].append(reason)

    elif symbol not in ["BTC", "ETH"]:
        if c.get("score", 0) >= 45 or c.get("action") in ["BUY", "PUMP", "WATCH", "ACCUM"]:
            current = int(c.get("score", 0) or 0)
            score = min(max(current, 50), 68)

            c["score"] = score
            c["_master_score"] = score
            c["action"] = "WATCH"
            c["verdict"] = "🟡 АКТИВ К НАБЛЮДЕНИЮ ПОСЛЕ СТАБИЛИЗАЦИИ BTC"
            c["_extreme_fear_alt_cap"] = True
            c["_red_market_cap"] = True

            c["chance_5"] = min(max(c.get("chance_5", 0), 8), 20)
            c["chance_10"] = min(max(c.get("chance_10", 0), 2), 5)
            c["chance_15"] = min(max(c.get("chance_15", 0), 1), 3)

            c["high"] = min(max(c.get("high", 0), 1.2), 2.5)
            c["low"] = min(c.get("low", -2.0), -2.8)
            c["entry_zone"] = "после стабилизации BTC: нужен разворот рынка и подтверждение объёмом"

            c.setdefault("minus", [])
            for reason in [
                "после стабилизации BTC",
                "экстремальный страх",
                "без входа сейчас"
            ]:
                if reason not in c["minus"]:
                    c["minus"].append(reason)

    price = c.get("price", 0) or 0
    c["target_low"] = price * (1 + c.get("low", 0) / 100)
    c["target_high"] = price * (1 + c.get("high", 0) / 100)

    return c


def v173_apply_btc_drop_wording_guard(c):
    """
    v17.3:
    Если BTC уже падает примерно на -2% при страхе рынка, нельзя в single-отчёте писать
    "СРЕДНЕСРОЧНЫЙ НАБОР", "наблюдать набор", "первая часть" или "BTC интересен".
    Это не запрет наблюдения за BTC, а защита wording: только ждать стабилизацию.
    """
    if not c:
        return c

    c = dict(c)
    symbol = c.get("symbol", "")
    ctx = c.get("ctx", {}) or {}
    btc_change = float(ctx.get("btc_change", c.get("change_24", 0)) or 0)
    fg_value = float(ctx.get("fg_value", 50) or 50)
    rsi_value = float(c.get("rsi", 50) or 50)
    macro_mod = int(ctx.get("macro_mod", ctx.get("geo_mod", 0)) or 0)

    # Основной кейс из теста: BTC около -2%, страх высокий, RSI перепродан.
    btc_drop_guard = (
        symbol == "BTC"
        and btc_change <= -1.8
        and fg_value <= 30
        and rsi_value <= 35
    )

    # ETH как рыночный якорь тоже не должен выглядеть как идея набора, если BTC тянет вниз.
    eth_drop_guard = (
        symbol == "ETH"
        and btc_change <= -1.8
        and fg_value <= 30
        and c.get("change_24", 0) <= -1.0
    )

    if not (btc_drop_guard or eth_drop_guard):
        return c

    cap = 62 if symbol == "BTC" else 60
    floor = 55 if symbol == "BTC" else 52
    if btc_change <= -2.3 or macro_mod <= -6:
        cap = min(cap, 60)

    current = int(c.get("score", 0) or 0)
    score = min(max(current, floor), cap)

    c["score"] = score
    c["_master_score"] = score
    c["_accumulation_score"] = score
    c["action"] = "WATCH"
    c["verdict"] = "🟡 НАБЛЮДАТЬ / ЖДАТЬ СТАБИЛИЗАЦИЮ BTC" if symbol == "BTC" else "🟡 НАБЛЮДАТЬ / ЖДАТЬ BTC"
    c["_btc_drop_wording_guard"] = True
    c["_red_market_cap"] = True

    c["chance_5"] = min(max(c.get("chance_5", 0), 8), 18)
    c["chance_10"] = min(max(c.get("chance_10", 0), 1), 4)
    c["chance_15"] = min(max(c.get("chance_15", 0), 0), 2)

    low = -3.5 if symbol == "BTC" else -4.0
    high = 0.8 if symbol == "BTC" else 0.9
    c["low"] = min(c.get("low", -2.0), low)
    c["high"] = min(max(c.get("high", 0), 0.5), high)

    c["entry_zone"] = "без входа сейчас: ждать остановку падения BTC, стабилизацию 3–4 часа и подтверждение объёма"
    c.setdefault("minus", [])
    for reason in [
        "BTC падает около -2% и мешает рынку",
        "перепроданность сама по себе не является входом",
        "без входа сейчас: ждать стабилизацию BTC"
    ]:
        if reason not in c["minus"]:
            c["minus"].append(reason)

    # Чистим опасные старые формулировки, если они где-то уже успели сформироваться.
    if "entry_zone" in c:
        c["entry_zone"] = str(c["entry_zone"]).replace("первая часть", "вход").replace("наблюдать набор", "наблюдать стабилизацию")

    price = float(c.get("price", 0) or 0)
    c["target_low"] = price * (1 + float(c.get("low", 0) or 0) / 100)
    c["target_high"] = price * (1 + float(c.get("high", 0) or 0) / 100)

    return c

def repair_learning_open_records():
    """
    v12.5:
    Чистит открытые наблюдения: GRAM/LAB/мелкие монеты не могут быть 84/100
    и "Среднесрочный набор"; качественные альты не должны выглядеть как вход в страхе.
    """
    data = load_json(RESULTS_FILE)
    if not isinstance(data, dict):
        return "История обучения пока не найдена."

    open_items = data.get("open", {})
    if not isinstance(open_items, dict) or not open_items:
        return "Открытых наблюдений нет."

    open_items, changed, fixed = normalize_learning_open_records(open_items)
    data["open"] = open_items

    if changed:
        save_json(RESULTS_FILE, data)
        sync_github_storage_now([RESULTS_FILE, RESULTS_BACKUP_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE])
        return f"✅ Обучение исправлено: безопасно переписано открытых наблюдений: {fixed}."

    return "✅ Проверил обучение: опасных записей GRAM/TAO/спекулятивных монет не найдено."


def analyze_symbol_for_signal(symbol):
    """
    v12.0:
    Один анализ монеты для /signal.
    Используется в ThreadPoolExecutor, чтобы один зависший KuCoin candle request
    не блокировал весь отчёт.
    """
    c = alex_edge_ultra(symbol)
    if not c:
        return None

    c = v6_apply_single_score_engine(c)
    c = v84_apply_btc_core_asset_fix(c)
    c = v87_apply_alt_accum_fix(c)
    c = v88_apply_red_market_score_cap(c)
    c = v94_apply_falling_market_no_buy(c)
    c = v101_apply_danger_market_score_cap(c)
    c = v106_apply_safe_caution_border_fix(c)
    c = v115_apply_extreme_fear_wording_fix(c)
    c = v173_apply_btc_drop_wording_guard(c)

    return c

def _safe_price(symbol):
    try:
        t = get_ticker(symbol)
        return float(t.get("last", 0) or 0) if t else 0
    except Exception:
        return 0

def save_signal_job(status, chat_id=None, detail="", started_at=None):
    data = load_json(SIGNAL_JOB_FILE)
    if not isinstance(data, dict):
        data = {}

    if started_at is None:
        started_at = data.get("started_at") or time.time()

    data.update({
        "status": status,
        "chat_id": str(chat_id or data.get("chat_id", "")),
        "detail": str(detail or ""),
        "started_at": started_at,
        "updated_at": time.time(),
        "version": BOT_VERSION,
    })

    save_json(SIGNAL_JOB_FILE, data)
    background_github_sync([SIGNAL_JOB_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=3)
    return data

def signal_status_report():
    data = load_json(SIGNAL_JOB_FILE)
    if not isinstance(data, dict) or not data:
        return (
            f"📡 Статус /signal\n"
            f"Версия: {BOT_VERSION}\n\n"
            "Фоновых задач /signal сейчас не найдено."
        )

    started_at = float(data.get("started_at", 0) or 0)
    age = int(time.time() - started_at) if started_at else 0

    return (
        f"📡 Статус /signal\n"
        f"Версия: {BOT_VERSION}\n\n"
        f"Статус: {data.get('status', 'unknown')}\n"
        f"Детали: {data.get('detail', '')}\n"
        f"Прошло: {age} сек\n"
        f"Обновлено: {time.strftime('%H:%M:%S', time.localtime(float(data.get('updated_at', 0) or time.time())))}"
    )

def immediate_signal_failsafe_report():
    """
    v12.2:
    Этот отчёт вообще не делает внешних API-запросов.
    Он нужен, чтобы бот НЕ молчал даже если KuCoin/News/API/потоки зависли.
    """
    return (
        f"⚠️ ALEX EDGE ULTRA {BOT_VERSION}\n"
        "Предварительный безопасный режим /signal\n\n"
        "Полный анализ 35 монет запущен в фоне.\n"
        "Пока полный отчёт не пришёл, бот НЕ даёт BUY.\n\n"
        "Решение сейчас:\n"
        "• BTC/ETH/SOL — только наблюдать\n"
        "• вход не открывать\n"
        "• ждать полный отчёт или стабилизацию рынка\n\n"
        "Если полный отчёт не придёт за 2–3 минуты:\n"
        "• /signal_status — посмотреть статус\n"
        "• /signal_unlock — снять блокировку\n"
        "• /flush — очистить очередь"
    )

def emergency_signal_report_no_api(reason="полный анализ не завершился вовремя"):
    """
    v12.2:
    Аварийный отчёт без внешних API. Не может зависнуть на market_context/get_ticker.
    """
    return (
        f"🚨 ALEX EDGE ULTRA {BOT_VERSION}\n"
        "Аварийный безопасный отчёт /signal\n\n"
        f"Причина: {reason}.\n"
        "Внешний API или поток анализа не вернул результат вовремя.\n\n"
        "BUY запрещены.\n"
        "BTC/ETH/SOL — только наблюдать.\n"
        "Новые входы не открывать до нормального полного отчёта.\n\n"
        "Что сделать:\n"
        "1. /signal_status\n"
        "2. /signal_unlock\n"
        "3. /flush\n"
        "4. повторить /signal через 1–2 минуты"
    )

def emergency_signal_report(reason="полный анализ не завершился вовремя"):
    """
    v12.2:
    Не используем внешние API в аварийном отчёте, иначе fallback сам может зависнуть.
    """
    return emergency_signal_report_no_api(reason)

    try:
        ctx = market_context()
    except Exception:
        ctx = {
            "state": "unknown",
            "risk_level": "unknown",
            "fg_value": "?",
            "fg_text": "нет данных",
            "btc_text": "BTC: данные недоступны",
            "btc_change": 0,
            "macro_text": "новости: нет данных",
            "macro_mod": 0,
        }

    btc_price = _safe_price("BTC-USDT")
    eth_price = _safe_price("ETH-USDT")
    sol_price = _safe_price("SOL-USDT")

    fg = ctx.get("fg_value", "?")
    btc_change = ctx.get("btc_change", 0)
    macro_text = ctx.get("macro_text", ctx.get("geo_text", "нет данных"))
    risk = ctx.get("risk_level", ctx.get("state", "unknown"))

    lines = [
        f"🚀 ALEX EDGE ULTRA {BOT_VERSION}",
        "⚠️ Аварийный безопасный отчёт /signal",
        "",
        f"Причина: {reason}.",
        "Полный анализ 35 монет не успел завершиться, поэтому бот НЕ выдаёт BUY.",
        "",
        f"Рынок: {ctx.get('state', 'unknown')}",
        f"BTC: {ctx.get('btc_text', 'нет данных')} | {btc_change:+.2f}%",
        f"Страх: {fg} — {ctx.get('fg_text', 'нет данных')}",
        f"Новости: {macro_text}",
        f"Риск рынка: {risk}",
        "",
        "Решение: без входа сейчас. Ждать стабилизацию BTC и нормальный полный отчёт.",
        "",
        "🟦 Активы для наблюдения:",
    ]

    if eth_price:
        lines.append(f"1. ETH — наблюдать | ${eth_price:,.0f}".replace(",", " "))
    else:
        lines.append("1. ETH — наблюдать | цена недоступна")

    if btc_price:
        lines.append(f"2. BTC — наблюдать | ${btc_price:,.0f}".replace(",", " "))
    else:
        lines.append("2. BTC — наблюдать | цена недоступна")

    if sol_price:
        lines.append(f"3. SOL — только после стабилизации BTC | ${sol_price:,.2f}".replace(",", " "))
    else:
        lines.append("3. SOL — только после стабилизации BTC")

    lines += [
        "",
        "Что сделать:",
        "1. /flush",
        "2. через 1–2 минуты повторить /signal",
        "3. если повторится — проблема во внешнем API, а не в очереди Telegram",
    ]

    return "\n".join(lines)

def format_usd_price(price):
    try:
        price = float(price or 0)
    except Exception:
        return "цена недоступна"

    if price <= 0:
        return "цена недоступна"

    if price >= 1000:
        return f"${price:,.0f}".replace(",", " ")

    if price >= 100:
        return f"${price:,.2f}".replace(",", " ")

    if price >= 1:
        return f"${price:,.3f}".replace(",", " ")

    return f"${price:,.5f}".replace(",", " ")

def ru_rows_word(n):
    """
    v13.5:
    Правильное окончание для строк отчёта:
    1 строка, 2-4 строки, 5+ строк.
    """
    try:
        n = abs(int(n))
        if n % 10 == 1 and n % 100 != 11:
            return "строка"
        if n % 10 in [2, 3, 4] and n % 100 not in [12, 13, 14]:
            return "строки"
    except Exception:
        pass
    return "строк"

def v15_prepare_ticker_learning_items(rows, display_rows, ctx):
    """
    v15.0: чтобы обучение не простаивало 48ч по нескольким монетам,
    каждый /signal создаёт дополнительные теневые наблюдения по важным активам.
    Они не являются сигналами на вход и не спамят Telegram.
    """
    result = []
    seen = set()

    def add_from_row(r, action="WATCH", verdict=None, mode="shadow"):
        base = r.get("base")
        if not base or base in seen or base in STABLE_SKIP_ASSETS:
            return
        seen.add(base)
        score = int(r.get("score", 0) or 0)
        is_core = bool(r.get("is_core"))
        change = float(r.get("change", 0) or 0)
        if verdict is None:
            if base in ["BTC", "ETH"]:
                verdict = "🟡 НАБЛЮДАТЬ / ЖДАТЬ СТАБИЛИЗАЦИЮ"
            elif (not is_core) and change >= 12:
                verdict = "🟡 СПЕКУЛЯТИВНОЕ НАБЛЮДЕНИЕ / НЕ ДОГОНЯТЬ"
                action = "WATCH"
            elif is_core:
                verdict = "🟡 АКТИВ К НАБЛЮДЕНИЮ ПОСЛЕ СТАБИЛИЗАЦИИ BTC"
            else:
                verdict = "🟡 ТЕНЕВОЕ НАБЛЮДЕНИЕ / НЕ ВХОД"

        result.append({
            "symbol": base,
            "price": float(r.get("price", 0) or 0),
            "score": score,
            "_master_score": score,
            "chance_5": 0,
            "chance_10": 0,
            "chance_15": 0,
            "action": action,
            "verdict": verdict,
            "is_quality": is_core,
            "profile": "крупный актив" if base in ["BTC", "ETH"] else ("качественный альт" if is_core else "спекулятивный альт"),
            "rsi": 50,
            "volume_trend": 1.0,
            "change_24": round(change, 2),
            "ctx": ctx,
            "_learning_delta": 0,
            "_learning_note": "fast-learning: теневое наблюдение, не сигнал на вход",
            "_learning_mode": mode,
        })

    # Всегда учим рынок: BTC/ETH.
    for base in ["BTC", "ETH"]:
        for r in rows:
            if r.get("base") == base:
                add_from_row(r, mode="core")
                break

    # Учим то, что реально показали пользователю.
    for r in display_rows:
        add_from_row(r, mode="display")

    # Учим 3–5 качественных активов с заметным движением/score, даже если они не попали в короткий список.
    quality = sorted(
        [r for r in rows if r.get("is_core") and r.get("base") not in seen and r.get("score", 0) >= 56],
        key=lambda x: (x.get("score", 0), abs(float(x.get("change", 0) or 0))),
        reverse=True
    )[:8]
    for r in quality:
        add_from_row(r, mode="quality_shadow")

    # Учим пампы отдельно: это нужно для анти-догоняй логики.
    pumps = sorted(
        [r for r in rows if (not r.get("is_core")) and r.get("base") not in seen and float(r.get("change", 0) or 0) >= 12],
        key=lambda x: float(x.get("change", 0) or 0),
        reverse=True
    )[:6]
    for r in pumps:
        add_from_row(r, action="WATCH", verdict="🟡 СПЕКУЛЯТИВНОЕ НАБЛЮДЕНИЕ / НЕ ДОГОНЯТЬ", mode="pump_shadow")

    # v17.0: больше теневых наблюдений за запуск, но всё ещё без дублей: максимум одно открытое наблюдение на монету.
    return result[:20]

def full_ticker_signal_report():
    """
    v12.4:
    Надёжный полный сигнал по 35 монетам без свечей.
    Использует один быстрый запрос allTickers и не зависает на candles.
    Это менее глубокий теханализ, чем старый полный режим, но он стабильно отвечает.
    """
    try:
        ctx = market_context(force_refresh=True)
    except Exception as e:
        print(f"full ticker market_context error: {e}")
        ctx = {
            "state": "unknown",
            "risk_level": "unknown",
            "fg_value": "?",
            "fg_text": "нет данных",
            "btc_text": "BTC: данные недоступны",
            "btc_change": 0,
            "macro_text": "новости: нет данных",
            "macro_mod": 0,
            "market_mod": 0,
        }

    try:
        tickers = kucoin_tickers()
    except Exception as e:
        return emergency_signal_report_no_api(f"KuCoin allTickers не ответил: {e}")

    fg_value = ctx.get("fg_value", "?")
    fg_text = ctx.get("fg_text", "нет данных")
    btc_change = float(ctx.get("btc_change", 0) or 0)
    btc_text = ctx.get("btc_text", "BTC: нет данных")
    macro_text = ctx.get("macro_text", ctx.get("geo_text", "новости: нет данных"))
    risk = ctx.get("risk_level", ctx.get("state", "unknown"))

    try:
        extreme = isinstance(fg_value, (int, float)) and fg_value <= 15 and btc_change < 0
    except Exception:
        extreme = False

    # v13.0: если заголовок уже extreme-fear, строка риска не должна оставаться "caution".
    if extreme:
        risk = "extreme-fear / no-buy"

    rows_raw = []
    for t in tickers:
        symbol = t.get("symbol", "")
        if not symbol.endswith("-USDT"):
            continue

        base = symbol.replace("-USDT", "")

        try:
            volume = float(t.get("volValue", 0) or 0)
            change = float(t.get("changeRate", 0) or 0) * 100
            price = float(t.get("last", 0) or 0)
        except Exception:
            continue

        if volume < 1_000_000 or price <= 0:
            continue

        if base in STABLE_SKIP_ASSETS:
            continue

        is_core = base in QUALITY_LEARNING_ASSETS
        quality_bonus = 10 if is_core else 0

        # Тикерный скоринг: быстрый, но без свечей. Поэтому BUY не выдаём.
        score = 45 + quality_bonus
        score += min(max(change, -5), 8) * 2
        score += min(volume / 20_000_000, 8)

        if extreme:
            if base == "BTC":
                score = min(score, 55)
            elif base in ["ETH", "SOL", "BNB", "LINK", "SUI", "NEAR", "TAO", "AAVE", "ADA", "AVAX", "INJ"]:
                score = min(score, 68)
            else:
                score = min(score, 55)
        else:
            score = min(max(score, 20), 72)
            if not is_core:
                score = min(score, 55)

        score = int(round(score))

        priority = (
            (100 if base == "BTC" else 0)
            + (95 if base == "ETH" else 0)
            + (90 if base == "SOL" else 0)
            + quality_bonus * 5
            + volume / 1_000_000
            + max(change, 0) * 3
        )

        rows_raw.append({
            "base": base,
            "symbol": symbol,
            "price": price,
            "volume": volume,
            "change": change,
            "score": score,
            "priority": priority,
            "is_core": is_core,
        })

    preferred = ["BTC", "ETH", "SOL", "BNB", "LINK", "SUI", "NEAR", "TAO", "AAVE", "ADA", "AVAX", "INJ"]
    selected = []

    for base in preferred:
        for r in rows_raw:
            if r["base"] == base and r not in selected:
                selected.append(r)
                break

    for r in sorted(rows_raw, key=lambda x: x["priority"], reverse=True):
        if len(selected) >= ANALYZE_LIMIT:
            break
        if r not in selected:
            selected.append(r)

    selected = selected[:ANALYZE_LIMIT]

    # v13.3:
    # Сканируем 35 монет, но показываем только:
    # 1) BTC/ETH как индикаторы рынка;
    # 2) реальные кандидаты, если рынок позволяет;
    # 3) 1-2 памповые монеты только как предупреждение "не догонять".
    def _compact_signal_rows(rows):
        by_base = {r["base"]: r for r in rows}
        result = []

        def add(base):
            r = by_base.get(base)
            if r and r not in result:
                result.append(r)

        # BTC/ETH — не "кандидаты на вход", а состояние рынка.
        add("BTC")
        add("ETH")

        if extreme:
            # При extreme-fear не делаем длинный watchlist.
            # Показываем только рынок + максимум 2 предупреждения о сильных пампах.
            pumped = [
                r for r in rows
                if (not r["is_core"]) and r["change"] >= 20 and r["base"] not in ["USDT", "USDC", "DAI"]
            ]
            pumped = sorted(pumped, key=lambda x: x["change"], reverse=True)[:2]
            for r in pumped:
                if r not in result:
                    result.append(r)

            return result[:4]

        # В обычном/осторожном рынке показываем только настоящих кандидатов.
        quality_order = ["SOL", "LINK", "SUI", "TAO", "NEAR", "AAVE", "BNB", "ADA", "AVAX", "INJ", "RENDER"]
        for base in quality_order:
            r = by_base.get(base)
            if not r:
                continue

            # Кандидат — это не просто любая монета из списка, а монета с достаточной оценкой
            # или заметной контролируемой просадкой по качественному активу.
            if r["score"] >= 58 or (r["is_core"] and -6.0 <= r["change"] <= -3.0 and r["score"] >= 50):
                add(base)

            if len(result) >= 7:
                break

        # Памповые/спекулятивные — отдельно и ограниченно, только предупреждение.
        pumped = [
            r for r in rows
            if (not r["is_core"]) and r["change"] >= 12 and r["base"] not in ["USDT", "USDC", "DAI"]
        ]
        pumped = sorted(pumped, key=lambda x: x["change"], reverse=True)[:2]
        for r in pumped:
            if r not in result and len(result) < 9:
                result.append(r)

        return result

    display_selected = _compact_signal_rows(selected)

    # v15.0: создаём fast-learning / shadow-наблюдения без спама в Telegram.
    try:
        save_signal_history(v15_prepare_ticker_learning_items(selected, display_selected, ctx))
    except Exception as e:
        print(f"v15 fast learning save skipped: {e}")

    def _compact_24h_forecast(r):
        """
        v13.12:
        Асимметричный 24ч-сценарий.
        Прогноз больше не рисуется одинаковым "-2…+2" для всех.
        Он учитывает:
        • режим страха;
        • BTC как якорь рынка;
        • свежий новостной фон;
        • рост/перегрев самой монеты;
        • качество актива;
        • поздний памп.
        """
        base = r.get("base", "")
        change = float(r.get("change", 0) or 0)
        score = int(r.get("score", 0) or 0)
        is_core = bool(r.get("is_core"))

        try:
            macro_mod = int(ctx.get("macro_mod", 0) or 0)
        except Exception:
            macro_mod = 0

        try:
            fear_num = int(fg_value)
        except Exception:
            fear_num = 50

        weak_fear = fear_num <= 25
        bad_news = macro_mod < 0
        good_news = macro_mod >= 6
        btc_strong = btc_change >= 1.5
        btc_weak = btc_change <= -0.7

        # Опасный режим: верх ограничен, низ шире.
        if extreme or btc_weak:
            if base in ["BTC", "ETH"]:
                return "-3.5%…+0.8% риск рынка"
            if (not is_core) and change >= 12:
                return "-16.0%…+1.5% риск отката"
            return "-5.0%…+1.0% ждать стабилизацию BTC"

        # Поздний памп / спекулятивный актив: главный сценарий — откат, а не рост.
        if (not is_core) and change >= 50:
            return "-18.0%…+2.0% поздний памп"
        if (not is_core) and change >= 20:
            return "-12.0%…+2.5% риск отката"
        if (not is_core) and change >= 12:
            return "-8.0%…+2.0% не догонять"

        # BTC/ETH — якорь рынка, в страхе потенциал роста ограничен.
        if base in ["BTC", "ETH"]:
            if bad_news:
                return "-2.5%…+0.9% новости давят"
            if weak_fear and btc_strong:
                return "-2.0%…+1.2% рост ограничен страхом"
            if good_news and btc_strong:
                return "-1.0%…+2.2%"
            if change >= 1.0:
                return "-1.4%…+1.7%"
            if change <= -1.0:
                return "-2.4%…+1.1%"
            return "-1.2%…+1.4%"

        # Качественный актив уже вырос: лучше ждать откат, риск вниз шире.
        if is_core and change >= 5:
            return "-4.5%…+1.3% перегрето, ждать откат"
        if is_core and change >= 3:
            return "-3.5%…+1.6% ждать откат"
        if is_core and change >= 2:
            if bad_news or weak_fear:
                return "-3.0%…+1.4% осторожно"
            return "-2.0%…+2.2%"

        # Качественный актив с умеренным score и без перегрева.
        if is_core and score >= 62:
            if good_news and not weak_fear:
                return "-1.2%…+3.4%"
            if bad_news:
                return "-2.8%…+1.5%"
            return "-1.8%…+2.6%"
        if is_core and score >= 58:
            if bad_news:
                return "-2.7%…+1.2%"
            return "-1.8%…+2.2%"

        # Просадка качественного актива — возможен отскок, но только после стабилизации BTC.
        if is_core and -6.0 <= change <= -3.0:
            if bad_news or weak_fear:
                return "-3.5%…+2.0% только после стабилизации"
            return "-2.0%…+4.0% возможен отскок"

        if change <= -4:
            return "-3.5%…+2.0% нужен разворот"

        return "-1.5%…+1.8%"

    # Считаем реальные активные кандидаты, чтобы не создавать иллюзию,
    # что каждая показанная монета "стоит наблюдения".
    if extreme:
        active_candidate_count = 0
    else:
        active_candidate_count = len([
            r for r in display_selected
            if r["base"] not in ["BTC", "ETH"] and not ((not r["is_core"]) and r["change"] >= 12)
        ])

    title_state = "🟡 extreme-fear / только наблюдать" if extreme else ctx.get("state", "unknown")
    if extreme:
        decision = "Экстремальный страх. BUY запрещены. Вход только после стабилизации BTC."
    else:
        decision = "Сейчас только наблюдение. Вход только после подтверждения объёма, отката и стабилизации BTC."

    lines = [
        f"🚀 ALEX EDGE ULTRA {BOT_VERSION}",
        "📊 Короткий сигнал: только нужное",
        "",
        f"Рынок: {title_state}",
        f"BTC: {btc_text} | {btc_change:+.2f}%",
        f"Страх: {fg_value} — {fg_text}",
        f"Новости: {macro_text}",
        f"Риск рынка: {risk}",
        f"Решение: {decision}",
        "",
        f"📊 Срез: просканировано {len(selected)} монет, показано {len(display_selected)} {ru_rows_word(len(display_selected))}",
        f"🟢 BUY: 0 | 🟦 альтов для мониторинга без входа: {active_candidate_count} (BTC/ETH не считаются)",
        "",
        "🟦 Что реально важно сейчас:",
    ]

    for i, r in enumerate(display_selected, start=1):
        base = r["base"]
        action = "наблюдать"
        if risk == "danger" and base not in ["BTC", "ETH"]:
            action = "только мониторинг, без входа; ждать стабилизацию BTC"
        if base in ["BTC", "ETH"]:
            # BTC/ETH в коротком отчёте — это якоря рынка, а не кандидаты.
            action = "индикатор рынка; вход только после подтверждения"
            if extreme:
                action = "индикатор рынка; без входа сейчас"
        elif extreme:
            if r["change"] > 8:
                action = "не догонять; НЕ кандидат сейчас"
            elif r["change"] < -4:
                action = "не кандидат сейчас; ждать разворот BTC"
            else:
                action = "не кандидат сейчас; ждать стабилизацию BTC"
        elif r["change"] > 8:
            action = "не догонять; только предупреждение"
        elif r["change"] < -4:
            action = "наблюдать только после стабилизации"
        elif r["is_core"] and r["change"] >= 4.5:
            action = "перегретый актив к наблюдению / без входа"
            r["score"] = min(r.get("score", 0), 65)
        elif r["is_core"] and r["score"] >= 60:
            action = "актив к наблюдению; нужен объём"

        lines.append(
            f"{i}. {base} — {r['score']}/100 | {format_usd_price(r['price'])} | 24ч {r['change']:+.2f}%\n"
            f"   {action}\n"
            f"   прогноз 24ч: {_compact_24h_forecast(r)}"
        )

    lines += [
        "",
        "Важно: список короткий. Прогноз 24ч — асимметричный сценарий, а не обещание роста.",
        "Это не все монеты, а только рынок/наблюдение/предупреждения.",
        "Для точечного анализа: /btc /sol или /coin ETH",
        "Самообучение: /learning",
    ]

    return "\n".join(lines)

def unified_signal_report():
    """
    v12.6:
    Одна кнопка 📊 Сигнал.
    Возвращает быстрый полный ticker-safe отчёт по 35 монетам без отдельной кнопки.
    """
    return full_ticker_signal_report()

def quick_signal_report():
    """
    v12.3:
    Быстрый безопасный /signal без фонового полного скана.
    Команда всегда должна быстро дать пользователю безопасный ответ.
    Полный тяжёлый скан 35 монет вынесен в /signal_full.
    """
    try:
        ctx = market_context(force_refresh=True)
    except Exception as e:
        print(f"quick market_context error: {e}")
        ctx = {
            "state": "unknown",
            "risk_level": "unknown",
            "fg_value": "?",
            "fg_text": "нет данных",
            "btc_text": "BTC: данные недоступны",
            "btc_change": 0,
            "macro_text": "новости: нет данных",
            "macro_mod": 0,
            "market_mod": 0,
        }

    state = ctx.get("state", "unknown")
    fg_value = ctx.get("fg_value", "?")
    fg_text = ctx.get("fg_text", "нет данных")
    btc_change = float(ctx.get("btc_change", 0) or 0)
    btc_text = ctx.get("btc_text", "BTC: нет данных")
    macro_text = ctx.get("macro_text", ctx.get("geo_text", "новости: нет данных"))
    risk = ctx.get("risk_level", state)

    extreme = False
    try:
        extreme = isinstance(fg_value, (int, float)) and fg_value <= 15 and btc_change < 0
    except Exception:
        extreme = False

    rows = []
    for i, sym in enumerate(SIGNAL_QUICK_COINS, start=1):
        base = sym.replace("-USDT", "")
        price = _safe_price(sym)
        score = 55
        action = "наблюдать"

        if base == "BTC":
            score = 55 if extreme else 62
            action = "без входа сейчас; ждать стабилизацию" if extreme else "наблюдать"
        elif base == "ETH":
            score = 70 if extreme else 65
            action = "без входа сейчас; ждать стабилизацию" if extreme else "наблюдать"
        elif base == "SOL":
            score = 68 if extreme else 63
            action = "после стабилизации BTC" if extreme else "наблюдать"
        else:
            score = 68 if extreme else 60
            action = "после стабилизации BTC" if extreme else "наблюдать"

        price_text = format_usd_price(price)
        rows.append(f"{i}. {base} — {score}/100 | {price_text}\n   {action}")

    if extreme:
        decision = "Экстремальный страх. BUY запрещены. BTC/ETH — только наблюдать, без первой части."
        title_state = "🟡 extreme-fear / только наблюдать"
    else:
        decision = "BUY только после подтверждения объёма, отката и стабилизации BTC."
        title_state = state

    return (
        f"🚀 ALEX EDGE ULTRA {BOT_VERSION}\n"
        "⚡ Быстрый безопасный сигнал\n\n"
        f"Рынок: {title_state}\n"
        f"BTC: {btc_text} | {btc_change:+.2f}%\n"
        f"Страх: {fg_value} — {fg_text}\n"
        f"Новости: {macro_text}\n"
        f"Риск рынка: {risk}\n"
        f"Решение: {decision}\n\n"
        "📊 Срез:\n"
        "🟢 BUY: 0 | 🟦 Активы для наблюдения: 2–6 | 🟡 WATCH: 0\n\n"
        "🟦 Активы для наблюдения:\n"
        + "\n".join(rows)
        + "\n\n"
        "Полный быстрый список 35 монет: /signal_full\n"
        "Статус полного скана: /signal_status\n"
        "Самообучение: /learning"
    )

def run_signal_background(chat_id, update_id=None):
    """
    v12.2:
    /signal запускается в фоне, но пользователь сразу получает безопасный предварительный отчёт.
    Отдельный watchdog гарантирует, что при зависании полного анализа будет отправлен fallback без API.
    """
    started_at = time.time()
    save_signal_job("started", chat_id, "Фоновый /signal запущен", started_at=started_at)

    # Сразу даём пользователю не просто ожидание, а безопасное решение.
    send_message(chat_id, immediate_signal_failsafe_report())

    state = {
        "done": False,
        "sent": False,
    }

    def _watchdog():
        time.sleep(SIGNAL_HARD_TIMEOUT)
        if state.get("done") or state.get("sent"):
            return

        state["sent"] = True
        save_signal_job(
            "timeout_fallback_sent",
            chat_id,
            f"Полный анализ не завершился за {SIGNAL_HARD_TIMEOUT} сек",
            started_at=started_at,
        )

        try:
            send_message(
                chat_id,
                emergency_signal_report_no_api(
                    f"полный анализ завис дольше {SIGNAL_HARD_TIMEOUT} секунд"
                )
            )
        finally:
            finish_signal_lock(ok=False)

    def _job():
        Thread(target=_watchdog, daemon=True).start()

        try:
            save_signal_job("running", chat_id, "Идёт полный анализ 35 монет", started_at=started_at)
            text = get_signal()

            if state.get("sent"):
                save_signal_job("finished_after_timeout", chat_id, "Полный отчёт пришёл после fallback", started_at=started_at)
                return

            state["sent"] = True
            state["done"] = True
            send_message(chat_id, text)
            save_signal_job("finished", chat_id, "Полный отчёт отправлен", started_at=started_at)
            finish_signal_lock(ok=True)

        except Exception as e:
            if not state.get("sent"):
                state["sent"] = True
                send_message(chat_id, f"Ошибка /signal:\n{e}")
            save_signal_job("error", chat_id, str(e), started_at=started_at)
            finish_signal_lock(ok=False)

    Thread(target=_job, daemon=True).start()


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

        selected = [x[0] for x in sorted(candidates, key=lambda x: x[1], reverse=True)[:ANALYZE_LIMIT]]

        for forced in FORCE_ANALYZE_ASSETS:
            if forced not in selected:
                selected.append(forced)

        analyzed = []

        # v12.0:
        # Полный список 35 монет сохраняем, но анализ идёт параллельно и с общим timebox.
        # Если KuCoin/свечи зависли по отдельной монете — бот не висит бесконечно,
        # а отдаёт отчёт по тем монетам, которые успел обработать.
        try:
            market_context(force_refresh=True)
        except Exception as e:
            print(f"market_context pre-cache error: {e}")

        started_at = time.time()
        executor = ThreadPoolExecutor(max_workers=max(1, COIN_ANALYSIS_WORKERS))
        futures = {
            executor.submit(analyze_symbol_for_signal, symbol): symbol
            for symbol in selected
        }

        try:
            for future in as_completed(futures, timeout=SIGNAL_TIME_BUDGET):
                if time.time() - started_at > SIGNAL_TIME_BUDGET:
                    break

                symbol = futures.get(future, "?")

                try:
                    c = future.result(timeout=1)
                except Exception as e:
                    print(f"coin analysis skipped {symbol}: {e}")
                    continue

                if c:
                    analyzed.append(c)

        except FuturesTimeoutError:
            print(f"/signal timebox reached: {len(analyzed)}/{len(selected)} coins analyzed")

        finally:
            for future in futures:
                if not future.done():
                    future.cancel()

            executor.shutdown(wait=False, cancel_futures=True)

        # v11.4+: обучение записываем только ПОСЛЕ всех risk-cap фиксов.
        # v12.0: делаем это в основном потоке, без гонки между worker-потоками.
        safe_analyzed = []
        for c in analyzed:
            try:
                safe_analyzed.append(v83_apply_self_learning(c))
            except Exception as e:
                print(f"learning write skipped {c.get('symbol', '?')}: {e}")
                safe_analyzed.append(c)

        analyzed = safe_analyzed

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
            background_github_sync([RESULTS_FILE, HISTORY_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE, SIGNAL_LOCK_FILE], max_files=5)
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

        result_text = compact_signal_report(
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

        background_github_sync([RESULTS_FILE, HISTORY_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE, SIGNAL_LOCK_FILE], max_files=5)
        return result_text

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

    quality = [
        x for x in items
        if x.get("alert_type") == "quality" or (x.get("kind") == "quality" and not x.get("manual_only"))
    ]
    watch = [x for x in items if x.get("alert_type") == "watch"]
    oversold = [x for x in items if x.get("alert_type") == "oversold"]
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
                f"{i}. {c['symbol']} — fast alert score {c.get('score', 0)}/100\n"
                f"15м: {c['fast_move']:+.2f}% | объём x{c['vol_power']:.1f}\n"
                f"Цена: ${c['price']:.6g} | 24ч: {c['change_24']:.2f}% | RSI {c.get('rsi', 'н/д')}\n"
                f"Действие: {action}. Риск: {risk}.\n\n"
            )

    if watch:
        text += "🟡 Ближайшие качественные наблюдения / не вход:\n"
        for i, c in enumerate(watch[:3], 1):
            text += (
                f"{i}. {c['symbol']} — fast alert score {c.get('score', 0)}/100\n"
                f"15м: {c['fast_move']:+.2f}% | объём x{c['vol_power']:.1f}\n"
                f"Цена: ${c['price']:.6g} | 24ч: {c['change_24']:.2f}% | RSI {c.get('rsi', 'н/д')}\n"
                "Действие: без входа сейчас; ждать стабилизацию BTC, рост объёма и откат/подтверждение.\n\n"
            )

    if oversold:
        text += "🔵 Перепроданность / без входа:\n"
        for i, c in enumerate(oversold[:2], 1):
            text += (
                f"{i}. {c['symbol']} — fast alert score {c.get('score', 0)}/100\n"
                f"15м: {c['fast_move']:+.2f}% | объём x{c['vol_power']:.1f}\n"
                f"Цена: ${c['price']:.6g} | 24ч: {c['change_24']:.2f}% | RSI {c.get('rsi', 'н/д')}\n"
                "Действие: не вход; ждать остановку падения, стабилизацию BTC и разворот RSI.\n\n"
            )

    if speculative:
        text += "🟣 Спекулятивный импульс:\n"
        for i, c in enumerate(speculative[:3], 1):
            text += (
                f"{i}. {c['symbol']} — fast alert score {c.get('score', 0)}/100\n"
                f"15м: {c['fast_move']:+.2f}% | объём x{c['vol_power']:.1f}\n"
                f"Цена: ${c['price']:.6g} | 24ч: {c['change_24']:.2f}%\n"
                "Действие: не догонять. Только наблюдать. Вход рассматривать не раньше отката и повторного подтверждения. Риск высокий.\n\n"
            )

    text += "⚠️ Главное правило: резкую зелёную свечу не догонять."
    return text

def alerts_empty_status(ctx):
    return (
        f"⚡ ALEX FAST ALERT {BOT_VERSION}\n\n"
        "Сильных импульсов и качественных наблюдений сейчас нет.\n"
        f"{compact_market_risk_line(ctx)}\n"
        f"{macro_mode_text(ctx)} ({ctx.get('macro_mod', 0):+d})\n\n"
        "Это нормально: лучше тишина, чем слабые монеты с низким объёмом.\n"
        "Что ждать: положительный 15м импульс, объём хотя бы x0.8–1.0, стабилизацию BTC и RSI без перегрева."
    )


def get_candles_alert(symbol, interval="1hour"):
    """
    v15.9: лёгкие свечи только для /alerts.
    Старый /alerts вызывал полноценный diagnostics() по 70 монетам,
    а diagnostics делает 15m/1h/4h candle requests. При задержке KuCoin команда
    могла висеть 3–5 минут. Для alerts достаточно 15m и 1h с коротким timeout.
    """
    data = requests.get(
        "https://api.kucoin.com/api/v1/market/candles",
        params={"symbol": symbol, "type": interval},
        timeout=ALERTS_CANDLE_TIMEOUT
    ).json()

    if data.get("code") != "200000":
        raise Exception(data)

    candles = sorted(data.get("data", []), key=lambda x: int(x[0]))

    return {
        "close": [float(c[2]) for c in candles],
        "volume": [float(c[5]) for c in candles],
    }


def diagnostics_alert(symbol):
    """
    v15.9: быстрая диагностика для /alerts без 4h свечей.
    Возвращает только то, что реально нужно alerts: 15м импульс, 1ч объём, RSI.
    """
    c15 = get_candles_alert(symbol, "15min")
    c1h = get_candles_alert(symbol, "1hour")

    close15 = c15.get("close", [])
    close1h = c1h.get("close", [])
    vol1h = c1h.get("volume", [])

    if len(close15) < 6 or len(close1h) < 16 or len(vol1h) < 8:
        raise Exception("not enough alert candles")

    return {
        "move_15": percent_change(close15[-5], close15[-1]),
        "vol_1h": volume_power(vol1h),
        "rsi": rsi(close1h),
    }


def get_fast_pumps():
    """
    v16.0 ALERTS INSTANT SAFE MODE:
    /alerts больше не делает свечные запросы и не вызывает market_context/news.
    Причина: KuCoin candles/news могут зависать, а команда Alerts должна отвечать быстро.
    Теперь используется только один быстрый allTickers-запрос KuCoin + локальный кэш рынка, если он уже есть.
    Это менее глубокая проверка, но надёжная: лучше быстрый безопасный статус, чем 4 минуты ожидания.
    """
    try:
        # Никаких market_context(), diagnostics(), get_candles(), news RSS внутри /alerts.
        # Только allTickers, который уже используется по всему боту и имеет короткий timeout.
        tickers = kucoin_tickers()

        # Берём контекст только из локального кэша, без сетевых запросов.
        cached_ctx = _market_context_cache.get("data") if isinstance(_market_context_cache, dict) else None
        ctx = dict(cached_ctx) if isinstance(cached_ctx, dict) else {}
        macro_mod = int(ctx.get("macro_mod", 0) or 0)

        btc_change = 0.0
        for t in tickers:
            if t.get("symbol") == "BTC-USDT":
                try:
                    btc_change = float(t.get("changeRate", 0) or 0) * 100
                except Exception:
                    btc_change = 0.0
                break

        try:
            fg_value = int(ctx.get("fg_value", 50) or 50)
        except Exception:
            fg_value = 50
        cached_risk = str(ctx.get("risk_level", "") or "").lower()
        market_danger = (
            cached_risk == "danger"
            or btc_change <= -2.3
            or (btc_change <= -1.5 and macro_mod <= -8)
            or (btc_change <= -1.0 and fg_value <= 20 and macro_mod <= -5)
        )
        market_caution = market_danger or btc_change < 0 or macro_mod <= -8

        rows = []
        for t in tickers:
            symbol = t.get("symbol", "")
            if not symbol.endswith("-USDT"):
                continue
            asset = symbol.replace("-USDT", "")
            if asset in STABLE_SKIP_ASSETS:
                continue
            try:
                price = float(t.get("last", 0) or 0)
                change_24 = float(t.get("changeRate", 0) or 0) * 100
                volume_usd = float(t.get("volValue", 0) or 0)
            except Exception:
                continue
            if price <= 0 or volume_usd < 1_000_000:
                continue
            kind = alert_kind(asset)
            score = 40
            if kind == "quality":
                score += 12
            else:
                score -= 6

            # 24ч движение — это не fast 15м, поэтому не выдаём BUY.
            if 0.5 <= change_24 <= 4:
                score += 12
            elif 4 < change_24 <= 8:
                score += 8
            elif 8 < change_24 <= 18:
                score -= 2
            elif change_24 > 18:
                score -= 10
            elif -4 <= change_24 < 0.5:
                score += 2
            else:
                score -= 6

            if volume_usd >= 80_000_000:
                score += 10
            elif volume_usd >= 30_000_000:
                score += 7
            elif volume_usd >= 10_000_000:
                score += 4

            if market_danger and kind == "speculative":
                score -= 10
            if market_danger and kind == "quality":
                score -= 3

            score = cap_alert_score(asset, score, macro_mod=macro_mod, btc_change=btc_change)
            score = max(0, min(100, int(score)))

            rows.append({
                "symbol": asset,
                "kind": kind,
                "price": price,
                "change_24": change_24,
                "volume_usd": volume_usd,
                "score": score,
                "market_danger": market_danger,
            })

        # Качественные активы для наблюдения: без входа, только если есть умеренное движение/объём.
        quality_watch = sorted(
            [r for r in rows if r["kind"] == "quality" and r["score"] >= 50 and -4 <= r["change_24"] <= 8],
            key=lambda x: (x["score"], x["volume_usd"], x["change_24"]),
            reverse=True
        )[:4]

        # Спекулятивные пампы — только предупреждение, не догонять.
        speculative_pumps = sorted(
            [r for r in rows if r["kind"] == "speculative" and r["change_24"] >= 12],
            key=lambda x: (x["change_24"], x["volume_usd"]),
            reverse=True
        )[:4]

        if not quality_watch and not speculative_pumps:
            text = (
                f"⚡ ALEX FAST ALERT {BOT_VERSION}\n\n"
                "Сильных быстрых импульсов сейчас нет.\n"
                "Режим: быстрый безопасный alerts без свечей, чтобы команда не зависала.\n\n"
                f"BTC 24ч: {btc_change:+.2f}%\n"
                f"{('Фон: 🔴 опасный — BUY запрещены, только наблюдение до стабилизации BTC.' if market_danger else ('Фон: 🟠 осторожный — вход только после подтверждения и отката.' if market_caution else 'Фон: без явного аварийного сигнала по BTC.'))}\n"
                "Что ждать: качественный актив, умеренный рост, высокий объём и подтверждение в /signal или /coin.\n"
                "Главное правило: резкую зелёную свечу не догонять."
            )
            return text, []

        text = f"⚡ ALEX FAST ALERT {BOT_VERSION}\n\n"
        text += "Режим: мгновенная безопасная проверка без свечных запросов.\n"
        text += "Это не команда покупать, а фильтр: что наблюдать и какие пампы не догонять.\n\n"
        text += f"BTC 24ч: {btc_change:+.2f}%\n"
        if market_danger:
            text += "Фон: 🔴 опасный — BUY запрещены, только наблюдение до стабилизации BTC.\n\n"
        elif market_caution:
            text += "Фон: 🟠 осторожный — вход только после подтверждения и отката.\n\n"
        else:
            text += "Фон: без явного аварийного сигнала по BTC.\n\n"

        if quality_watch:
            text += "🟡 Качественные активы к наблюдению / не вход:\n"
            for i, r in enumerate(quality_watch, 1):
                action = "наблюдать; вход только после подтверждения в /coin"
                if market_danger:
                    action = "без входа сейчас; ждать стабилизацию BTC/фона"
                text += (
                    f"{i}. {r['symbol']} — fast alert score {r['score']}/100 | {format_usd_price(r['price'])}\n"
                    f"24ч: {r['change_24']:+.2f}% | объём ${r['volume_usd']/1_000_000:.1f}M\n"
                    f"Действие: {action}.\n\n"
                )

        if speculative_pumps:
            text += "🟣 Спекулятивные пампы / не догонять:\n"
            for i, r in enumerate(speculative_pumps, 1):
                text += (
                    f"{i}. {r['symbol']} — fast alert score {r['score']}/100 | {format_usd_price(r['price'])}\n"
                    f"24ч: {r['change_24']:+.2f}% | объём ${r['volume_usd']/1_000_000:.1f}M\n"
                    "Действие: не догонять; только предупреждение, ждать откат.\n\n"
                )

        text += "⚠️ Для точного входа используй /coin SOL или /signal."
        return text, quality_watch + speculative_pumps

    except Exception as e:
        # Даже при ошибке отвечаем сразу безопасно, а не зависаем.
        return (
            f"⚡ ALEX FAST ALERT {BOT_VERSION}\n\n"
            f"Быстрый alerts не смог получить данные: {e}\n\n"
            "BUY запрещены. Ничего не догонять. Повтори /alerts через 1–2 минуты или смотри /signal."
        ), []

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
        if c.get("manual_only") or c.get("alert_type") in ["watch", "oversold"]:
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
        sync_github_storage_now([PUMP_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE])

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
    if c.get("_extreme_fear_cap"):
        return "без входа сейчас; ждать стабилизацию BTC"

    if c.get("_extreme_fear_alt_cap"):
        return "наблюдать, без входа; вернуться после стабилизации BTC"

    if c.get("_safe_caution_cap"):
        return "без входа сейчас; ждать стабилизацию BTC"

    if c.get("_safe_caution_alt_cap"):
        return "наблюдать, без входа; вернуться после стабилизации BTC"

    if c.get("_danger_market_cap"):
        return "без входа сейчас; ждать остановку падения"

    if c.get("_danger_alt_cap"):
        return "наблюдать, без входа; вернуться после разворота рынка"

    if c.get("_quality_alt_danger_watch"):
        return "наблюдать, без входа; ждать стабилизацию BTC"

    if c.get("_bad_news_quality_alt_watch"):
        return "наблюдать, без входа; опасные новости"

    if c.get("_bad_alt_entry_cap"):
        return "наблюдать, без входа; фон против альтов"

    if c.get("_falling_market_no_buy"):
        return "ждать стабилизацию, быстрый вход запрещён, не ловить нож"

    if c.get("_btc_drop_wording_guard"):
        return "наблюдать, без входа; ждать остановку падения BTC"

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
    vol = c.get("volume_trend", 1)
    if vol < 1.1:
        items.append("нужен объём выше x1.1")
    elif vol >= 1.3:
        items.append("объём появился, нужно удержание цены/объёма 1–2 свечи")
    if c.get("rsi", 50) < 35:
        if symbol == "BTC":
            items.append("нужна остановка падения после перепроданности")
        else:
            items.append("нужен разворот RSI, а не просто перепроданность")

    if not items:
        items.append("нужно подтверждение ценой и удержанием объёма")

    text = "Что нужно для улучшения:\n"
    for x in items[:4]:
        text += f"• {x}\n"
    return text

def format_signed_pct_value(v):
    try:
        v = float(v)
    except Exception:
        v = 0.0
    return f"{v:+.1f}%"


def format_single_coin_report(c):
    ctx = c.get("ctx", {})

    text = (
        f"Версия: {BOT_VERSION}\n\n"
        f"{c['symbol']} — {c.get('verdict', 'нет статуса')}\n"
        f"Тип: {c.get('profile', 'н/д')}\n\n"
        f"Цена: {compact_price(c.get('price'))}\n"
        f"24ч: {c.get('change_24', 0):.2f}%\n"
        f"RSI: {c.get('rsi', 'н/д')} | объём: x{c.get('volume_trend', 'н/д')}\n"
        f"Оценка входа: {c.get('score', 0)}/100\n"
        f"{('ℹ️ score снижен за плохой момент входа, не за качество актива\n') if c.get('_quality_alt_score_floor') else ''}"
        f"{('ℹ️ score снижен за плохой фон/BTC, не за качество актива\n') if c.get('_bad_alt_entry_cap') else ''}"
        f"{('ℹ️ это наблюдение из-за опасных новостей, не вход\n') if c.get('_bad_news_quality_alt_watch') else ''}"
        f"📚 {c.get('_learning_note', 'самообучение: история накапливается')}\n\n"
        f"{macro_mode_text(ctx)} ({ctx.get('macro_mod', 0):+d})\n"
        f"{compact_market_risk_line(ctx)}\n"
        f"BTC: {ctx.get('btc_text', 'н/д')} | {ctx.get('btc_change', 0):.2f}%\n\n"
        f"Действие: {single_coin_action_text(c)}\n"
        f"Причина: {compact_reason(c)}\n\n"
        f"Сценарий 24ч: {format_signed_pct_value(c.get('low', 0))}…{format_signed_pct_value(c.get('high', 0))}"
        f"{(' — ' + c.get('_forecast_note')) if c.get('_forecast_note') else ''}\n"
        f"Диапазон 24ч: ${c.get('target_low', 0):.6g}…${c.get('target_high', 0):.6g}\n\n"
        f"{single_coin_conditions_text(c)}\n"
    )

    if c.get("_extreme_fear_cap"):
        if c.get("symbol") == "BTC":
            text += "Итог: BTC наблюдать, входа сейчас нет. Страх экстремальный, BTC в минусе — ждать стабилизацию и рост объёма."
        elif c.get("symbol") == "ETH":
            text += "Итог: ETH наблюдать, входа сейчас нет. Экстремальный страх — вход только после стабилизации BTC и объёма."
        else:
            text += f"Итог: {c.get('symbol')} только после стабилизации BTC. Сейчас без входа."
    elif c.get("_extreme_fear_alt_cap"):
        text += f"Итог: {c.get('symbol')} — только актив к наблюдению после стабилизации BTC. Сейчас без входа; рынок в экстремальном страхе."
    elif c.get("_safe_caution_cap"):
        if c.get("symbol") == "BTC":
            text += "Итог: BTC наблюдать, входа сейчас нет. Страх экстремальный, BTC мешает рынку — ждать стабилизацию 3–4 часа и рост объёма."
        elif c.get("symbol") == "ETH":
            text += "Итог: ETH наблюдать, входа сейчас нет. Нужна стабилизация BTC и подтверждение объёмом."
        else:
            text += f"Итог: {c.get('symbol')} только после стабилизации BTC. Сейчас без входа."
    elif c.get("_safe_caution_alt_cap"):
        text += f"Итог: {c.get('symbol')} — только актив к наблюдению после стабилизации BTC. Сейчас без входа; нужен разворот рынка."
    elif c.get("_danger_market_cap"):
        if c.get("symbol") == "BTC":
            text += "Итог: BTC наблюдать, входа сейчас нет. Вернуться после стабилизации 3–4 часа, роста объёма и прекращения падения."
        elif c.get("symbol") == "ETH":
            text += "Итог: ETH наблюдать, входа сейчас нет. Нужна стабилизация BTC и подтверждение объёмом."
        else:
            text += f"Итог: {c.get('symbol')} только после разворота рынка. Сейчас без входа."
    elif c.get("_danger_alt_cap"):
        text += f"Итог: {c.get('symbol')} — только актив к наблюдению после разворота рынка. Сейчас без входа; нужна стабилизация BTC."
    elif c.get("_quality_alt_danger_watch"):
        text += f"Итог: {c.get('symbol')} — качественный актив, но рынок опасный. Сейчас без входа; вернуться после стабилизации BTC, роста объёма и разворота RSI."
    elif c.get("_falling_market_no_buy"):
        if c.get("symbol") in ["BTC", "ETH"]:
            text += "Итог: быстрый BUY запрещён. Перепроданность есть, но рынок падает — ждать стабилизацию и не ловить нож."
        else:
            text += "Итог: рынок падает, по альтам сейчас только наблюдение. Вход после стабилизации BTC."
    elif c.get("_btc_drop_wording_guard"):
        if c.get("symbol") == "BTC":
            text += "Итог: BTC только наблюдать. Входа сейчас нет: сначала остановка падения, стабилизация 3–4 часа и подтверждение объёмом."
        else:
            text += "Итог: входа сейчас нет. Ждать стабилизацию BTC и подтверждение объёмом."
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
            c["verdict"] = "🟡 АКТИВ К НАБЛЮДЕНИЮ ПОСЛЕ РАЗВОРОТА РЫНКА"
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


def v106_apply_safe_caution_border_fix(c):
    """
    v10.6:
    Если страх 14–15 и BTC около -1.8…-2.0%, не даём BTC 76/100,
    "Среднесрок" и "первая малая часть". Альты "почти сигнал" режем до 65–68.
    """
    if not c:
        return c

    c = dict(c)
    symbol = c.get("symbol", "")
    ctx = c.get("ctx", {})

    if not v106_safe_caution(ctx):
        return c

    btc_change = ctx.get("btc_change", 0)
    fg_value = ctx.get("fg_value", 50)

    if symbol in ["BTC", "ETH"] and c.get("action") in ["BUY", "PUMP", "ACCUM", "WATCH", "SKIP"]:
        cap = 68 if symbol == "BTC" else 70
        current = int(c.get("score", 0) or 0)
        score = min(max(current, 55), cap)

        c["score"] = score
        c["_master_score"] = score
        c["_accumulation_score"] = score

        # Оставляем в блоке "Активы для наблюдения", но без идеи входа сейчас.
        c["action"] = "ACCUM"
        c["verdict"] = "🟡 НАБЛЮДАТЬ / ЖДАТЬ СТАБИЛИЗАЦИЮ"
        c["_safe_caution_cap"] = True
        c["_red_market_cap"] = True

        c["chance_5"] = min(max(c.get("chance_5", 0), 10), 24)
        c["chance_10"] = min(max(c.get("chance_10", 0), 2), 6)
        c["chance_15"] = min(max(c.get("chance_15", 0), 1), 3)

        c["low"] = min(c.get("low", -2.0), -2.8)
        c["high"] = min(max(c.get("high", 0), 1.5), 2.8 if symbol == "BTC" else 3.0)
        c["entry_zone"] = "без входа сейчас: ждать стабилизацию BTC 3–4 часа и рост объёма"

        c.setdefault("minus", [])
        for reason in [
            f"safe-caution: страх {fg_value} и BTC {btc_change:.2f}%",
            "BTC мешает рынку, вход сейчас запрещён",
            "нужна стабилизация BTC"
        ]:
            if reason not in c["minus"]:
                c["minus"].append(reason)

    elif symbol not in ["BTC", "ETH"]:
        if c.get("score", 0) >= 45 or c.get("action") in ["BUY", "PUMP", "WATCH", "ACCUM"]:
            current = int(c.get("score", 0) or 0)
            score = min(max(current, 50), 68)

            c["score"] = score
            c["_master_score"] = score
            c["action"] = "WATCH"
            c["verdict"] = "🟡 АКТИВ К НАБЛЮДЕНИЮ ПОСЛЕ СТАБИЛИЗАЦИИ BTC"
            c["_safe_caution_alt_cap"] = True
            c["_red_market_cap"] = True

            c["chance_5"] = min(max(c.get("chance_5", 0), 10), 22)
            c["chance_10"] = min(max(c.get("chance_10", 0), 2), 5)
            c["chance_15"] = min(max(c.get("chance_15", 0), 1), 3)

            c["high"] = min(max(c.get("high", 0), 1.5), 2.5)
            c["low"] = min(c.get("low", -2.0), -3.0)
            c["entry_zone"] = "после стабилизации BTC: нужен разворот рынка и подтверждение объёмом"

            c.setdefault("minus", [])
            for reason in [
                "после стабилизации BTC",
                "страх экстремальный",
                "без входа сейчас"
            ]:
                if reason not in c["minus"]:
                    c["minus"].append(reason)

    price = c.get("price", 0) or 0
    c["target_low"] = price * (1 + c.get("low", 0) / 100)
    c["target_high"] = price * (1 + c.get("high", 0) / 100)

    return c


def v136_apply_core_no_red_neutral(c):
    """
    v13.6:
    BTC/ETH не должны получать 🔴 НЕ ПОКУПАТЬ и 15/100 просто из-за слабого объёма,
    если рынок не danger и BTC не падает опасно.
    Это не BUY и не WATCH, а нейтральный "нет сигнала".
    """
    if not c:
        return c

    c = dict(c)
    symbol = c.get("symbol", "")
    ctx = c.get("ctx", {}) or {}

    if symbol not in ["BTC", "ETH"]:
        return c

    verdict = str(c.get("verdict", ""))
    score = int(c.get("score", 0) or 0)
    risk_level = ctx.get("risk_level", "")
    btc_change = float(ctx.get("btc_change", 0) or 0)
    fg_value = ctx.get("fg_value", 50)

    try:
        extreme = isinstance(fg_value, (int, float)) and fg_value <= 15 and btc_change < 0
    except Exception:
        extreme = False

    # В настоящем опасном рынке красный запрет оставляем.
    if risk_level == "danger" or extreme or btc_change <= -1.6:
        return c

    # Если причина только "нет условий / нет объёма", это должен быть нейтральный отказ.
    if "НЕ ПОКУПАТЬ" in verdict and score <= 25:
        c["verdict"] = "⚪ НЕТ СИГНАЛА"
        c["score"] = 30
        c["_master_score"] = 30
        c["action"] = "SKIP"
        c["low"] = max(c.get("low", -2.0), -1.5)
        c["high"] = min(max(c.get("high", 1.5), 1.5), 1.5)
        c["_core_no_red_neutral"] = True

        c.setdefault("minus", [])
        if "нет подтверждения объёмом" not in c["minus"]:
            c["minus"].append("нет подтверждения объёмом")

    return c


def v1314_apply_quality_alt_score_floor(c):
    """
    v13.14:
    Качественный альт (SOL/LINK/TAO/NEAR/AAVE и т.п.) не должен получать 0/100,
    если решение "НЕ ПОКУПАТЬ" вызвано перегревом/слабым объёмом/плохими новостями.
    0/100 визуально звучит как "монета мусор", хотя правильно: "момент входа плохой".
    BUY-логику не смягчаем: вход всё равно запрещён.
    """
    if not c:
        return c

    c = dict(c)
    symbol = c.get("symbol", "")
    is_quality = bool(c.get("is_quality")) or symbol in QUALITY_LEARNING_ASSETS
    score = int(c.get("score", 0) or 0)
    verdict = str(c.get("verdict", ""))

    if not is_quality:
        return c

    if symbol in ["BTC", "ETH"]:
        return c

    if score <= 20 and ("НЕ ПОКУПАТЬ" in verdict or c.get("action") == "SKIP"):
        c["score"] = 20
        c["_master_score"] = max(int(c.get("_master_score", 0) or 0), 20)
        c["_quality_alt_score_floor"] = True
        c["action"] = "SKIP"

        # Не меняем запрет на вход, только делаем причину понятнее.
        c.setdefault("minus", [])
        if "плохой момент входа, а не плохой актив" not in c["minus"]:
            c["minus"].append("плохой момент входа, а не плохой актив")

    return c


def v1313_apply_single_asymmetric_forecast(c):
    """
    v13.13:
    Приводит подробный /btc /sol /coin к той же асимметричной логике,
    что и короткий /signal.
    До этого общий /signal уже показывал "-2.5…+0.9 новости давят",
    а /btc мог оставаться старым "-1.5…+1.5".
    """
    if not c:
        return c

    c = dict(c)
    ctx = c.get("ctx", {}) or {}
    symbol = c.get("symbol", "")
    price = float(c.get("price", 0) or 0)
    change = float(c.get("change_24", 0) or 0)
    score = int(c.get("score", 0) or 0)
    is_quality = bool(c.get("is_quality"))

    if price <= 0:
        return c

    try:
        macro_mod = int(ctx.get("macro_mod", ctx.get("geo_mod", 0)) or 0)
    except Exception:
        macro_mod = 0

    try:
        fear_num = int(ctx.get("fg_value", 50) or 50)
    except Exception:
        fear_num = 50

    try:
        btc_change = float(ctx.get("btc_change", 0) or 0)
    except Exception:
        btc_change = 0

    risk_level = ctx.get("risk_level", ctx.get("state", ""))
    weak_fear = fear_num <= 25
    bad_news = macro_mod <= -5
    very_bad_news = macro_mod <= -8
    good_news = macro_mod >= 6
    btc_strong = btc_change >= 1.5
    btc_weak = btc_change <= -0.7
    extreme = (
        risk_level == "danger"
        or (fear_num <= 15 and btc_change < 0)
        or btc_weak
    )

    note = ""

    # v15.0: single coin forecast не должен откатываться к симметричному -1.5…+1.5
    # при плохом фоне, слабом BTC/страхе или слабом объёме.
    if (symbol not in ["BTC", "ETH"] and is_quality and (bad_news or weak_fear or btc_change < 0) and c.get("volume_trend", 1) < 1.1):
        if change >= 3 or c.get("rsi", 50) >= 65:
            low, high, note = -3.5, 1.5, "ждать откат"
        else:
            if risk_level == "danger":
                low, high, note = -2.7, 1.2, "BTC слабый, рынок опасный"
            else:
                low, high, note = -2.7, 1.2, "BTC слабый, фон осторожный"
        c["low"] = low
        c["high"] = high
        c["target_low"] = price * (1 + low / 100)
        c["target_high"] = price * (1 + high / 100)
        c["_forecast_note"] = note
        return c

    if extreme:
        if symbol in ["BTC", "ETH"]:
            low, high, note = -3.5, 0.8, "риск рынка"
        elif (not is_quality) and change >= 12:
            low, high, note = -16.0, 1.5, "риск отката"
        else:
            low, high, note = -5.0, 1.0, "ждать стабилизацию BTC"

    elif (not is_quality) and change >= 50:
        low, high, note = -18.0, 2.0, "поздний памп"
    elif (not is_quality) and change >= 20:
        low, high, note = -12.0, 2.5, "риск отката"
    elif (not is_quality) and change >= 12:
        low, high, note = -8.0, 2.0, "не догонять"

    elif symbol in ["BTC", "ETH"]:
        if very_bad_news:
            low, high, note = -2.5, 0.9, "новости давят"
        elif bad_news:
            low, high, note = -2.0, 1.0, "фон осторожный"
        elif weak_fear and btc_strong:
            low, high, note = -2.0, 1.2, "рост ограничен страхом"
        elif good_news and btc_strong:
            low, high, note = -1.0, 2.2, ""
        elif change >= 1.0:
            low, high, note = -1.4, 1.7, ""
        elif change <= -1.0:
            low, high, note = -2.4, 1.1, ""
        else:
            low, high, note = -1.2, 1.4, ""

    elif is_quality and change >= 5:
        low, high, note = -4.5, 1.3, "перегрето, ждать откат"
    elif is_quality and change >= 3:
        low, high, note = -3.5, 1.6, "ждать откат"
    elif is_quality and change >= 2:
        if bad_news or weak_fear:
            low, high, note = -3.0, 1.4, "осторожно"
        else:
            low, high, note = -2.0, 2.2, ""
    elif is_quality and score >= 62:
        if good_news and not weak_fear:
            low, high, note = -1.2, 3.4, ""
        elif bad_news:
            low, high, note = -2.8, 1.5, "новости давят"
        else:
            low, high, note = -1.8, 2.6, ""
    elif is_quality and score >= 58:
        if bad_news:
            low, high, note = -2.7, 1.2, "новости давят"
        else:
            low, high, note = -1.8, 2.2, ""
    elif is_quality and -6.0 <= change <= -3.0:
        if bad_news or weak_fear:
            low, high, note = -3.5, 2.0, "только после стабилизации"
        else:
            low, high, note = -2.0, 4.0, "возможен отскок"
    elif change <= -4:
        low, high, note = -3.5, 2.0, "нужен разворот"
    else:
        low, high, note = -1.5, 1.8, ""

    # Если монета в SKIP / нет сигнала, не даём чрезмерно оптимистичный верх.
    if c.get("action") == "SKIP":
        high = min(high, 1.5 if symbol not in ["BTC", "ETH"] else high)

    low = round(float(low), 1)
    high = round(float(high), 1)

    c["low"] = low
    c["high"] = high
    c["target_low"] = price * (1 + low / 100)
    c["target_high"] = price * (1 + high / 100)
    if note:
        c["_forecast_note"] = note

    return c



def v153_apply_quality_alt_entry_cap(c):
    """
    v15.3 QUALITY ALT ENTRY CAP:
    Если качественный альт (SOL/LINK/TAO/NEAR/AAVE и т.п.) находится в плохом фоне
    (опасные/негативные новости + BTC в минусе + страх), не показываем высокую
    "Оценку входа" 60+ рядом с текстом "вход только после подтверждения".
    Это не ухудшает качество актива, а снижает именно качество текущей точки входа.
    """
    if not c:
        return c

    c = dict(c)
    symbol = c.get("symbol", "")
    if symbol in ["BTC", "ETH"]:
        return c

    ctx = c.get("ctx", {}) or {}
    macro_mod = ctx.get("macro_mod", ctx.get("geo_mod", 0))
    btc_change = ctx.get("btc_change", 0)
    fg_value = ctx.get("fg_value", 50)
    volume = c.get("volume_trend", 1) or 1
    rsi = c.get("rsi", 50) or 50
    change_24 = c.get("change_24", 0) or 0
    group = v6_quality_group(c)

    bad_alt_env = (
        group in ["quality", "core", "liquid"]
        and c.get("action") in ["WATCH", "SKIP"]
        and (
            (macro_mod <= -12 and btc_change < 0)
            or (macro_mod <= -8 and btc_change < 0 and fg_value <= 25)
        )
    )

    if not bad_alt_env:
        return c

    # В плохом фоне это не вход, а наблюдение. Score не должен выглядеть почти как сигнал.
    cap = 55
    if volume < 1.1:
        cap = min(cap, 52)
    if rsi >= 62 or change_24 < 0:
        cap = min(cap, 50)

    old_score = int(c.get("score", 0) or 0)
    if old_score > cap:
        c["score"] = cap
        c["_master_score"] = min(int(c.get("_master_score", old_score) or old_score), cap)
        c["_bad_alt_entry_cap"] = True

    c["action"] = "WATCH"
    c["verdict"] = "🟡 НАБЛЮДАТЬ / ФОН ПРОТИВ АЛЬТОВ"

    c.setdefault("minus", [])
    if "плохой фон для альтов + BTC слабеет" not in c["minus"]:
        c["minus"].append("плохой фон для альтов + BTC слабеет")

    # Прогноз тоже должен оставаться асимметричным, а не мягким/симметричным.
    price = c.get("price", 0) or 0
    low = min(float(c.get("low", -1.5) or -1.5), -2.7)
    high = min(float(c.get("high", 1.5) or 1.5), 1.2)
    c["low"] = round(low, 1)
    c["high"] = round(high, 1)
    c["target_low"] = price * (1 + c["low"] / 100)
    c["target_high"] = price * (1 + c["high"] / 100)
    c["_forecast_note"] = "BTC слабый, фон против альтов"
    c["entry_zone"] = "без входа; ждать стабилизацию BTC, улучшение фона и подтверждение объёмом"

    return c


def v155_apply_single_watch_score_consistency(c):
    """
    v15.5 SINGLE WATCH SCORE CONSISTENCY:
    В подробных /btc /sol /coin нельзя показывать "Оценка входа" 75-85/100,
    если итоговое действие всё равно "наблюдать / вход только после подтверждения".
    Высокий технический импульс может быть хорошим признаком, но при страхе/смешанном фоне
    это не готовая точка входа. Поэтому капаем именно отображаемую оценку входа,
    не ухудшая качество самого актива.
    """
    if not c:
        return c

    c = dict(c)
    action = c.get("action")
    symbol = c.get("symbol", "")
    score = int(c.get("score", 0) or 0)

    if action != "WATCH" or score < 70:
        return c

    ctx = c.get("ctx", {}) or {}
    try:
        macro_mod = int(ctx.get("macro_mod", ctx.get("geo_mod", 0)) or 0)
    except Exception:
        macro_mod = 0
    try:
        fg_value = int(ctx.get("fg_value", 50) or 50)
    except Exception:
        fg_value = 50
    try:
        btc_change = float(ctx.get("btc_change", 0) or 0)
    except Exception:
        btc_change = 0.0

    risk_level = str(ctx.get("risk_level", ""))
    verdict = str(c.get("verdict", ""))
    group = v6_quality_group(c)
    is_quality = bool(c.get("is_quality"))
    vol_power = float(c.get("vol_power", c.get("volume_trend", 1)) or 1)

    # Если это не BUY, а фон всё ещё осторожный, высокая оценка входа вводит в заблуждение.
    caution_env = (
        fg_value <= 25
        or macro_mod < 0
        or risk_level in ["caution", "danger"]
        or btc_change < 0.5
    )

    if not caution_env:
        return c

    if symbol in ["BTC", "ETH"]:
        cap = 58
    elif group in ["quality", "core", "liquid"] or is_quality:
        # Если BTC уже помогает и объём высокий — оставляем хороший watch-score,
        # но не 80+, потому что это ещё не вход, а подтверждение нужно 1-2 свечи.
        if btc_change >= 0.5 and vol_power >= 1.5 and macro_mod >= -4:
            cap = 65
        else:
            cap = 58
    else:
        cap = 55

    if score > cap:
        c["score"] = cap
        c["_master_score"] = min(int(c.get("_master_score", score) or score), cap)
        c["_single_watch_score_cap"] = True
        c.setdefault("minus", [])
        note = "оценка входа снижена: это наблюдение, не готовый вход"
        if note not in c["minus"]:
            c["minus"].append(note)

    # Подчищаем формулировку, чтобы 65/100 не выглядело как почти BUY.
    if "ПОКУП" not in verdict:
        if symbol not in ["BTC", "ETH"] and (group in ["quality", "core", "liquid"] or is_quality):
            c["verdict"] = "🟡 НАБЛЮДАТЬ / ЖДАТЬ ПОДТВЕРЖДЕНИЕ"
        else:
            c["verdict"] = "🟡 НАБЛЮДАТЬ"

    return c


def v161_apply_bad_news_quality_alt_watch(c):
    """v16.1:
    Quality alts with dangerous news and BTC still positive should be WATCH, not red 20/100 SKIP.
    This keeps the entry forbidden, but avoids saying the asset is bad.
    """
    if not c:
        return c

    c = dict(c)
    symbol = c.get("symbol", "")
    if symbol in ["BTC", "ETH"]:
        return c

    ctx = c.get("ctx", {}) or {}
    group = v6_quality_group(c)
    is_quality = bool(c.get("is_quality")) or symbol in QUALITY_LEARNING_ASSETS
    if not (group in ["quality", "core", "liquid"] or is_quality):
        return c

    try:
        macro_mod = int(ctx.get("macro_mod", ctx.get("geo_mod", 0)) or 0)
    except Exception:
        macro_mod = 0
    try:
        btc_change = float(ctx.get("btc_change", 0) or 0)
    except Exception:
        btc_change = 0.0
    try:
        fg_value = int(ctx.get("fg_value", 50) or 50)
    except Exception:
        fg_value = 50

    action = c.get("action")
    verdict = str(c.get("verdict", ""))
    score = int(c.get("score", 0) or 0)
    rsi_value = float(c.get("rsi", 50) or 50)
    vol = float(c.get("volume_trend", 1) or 1)
    change_24 = float(c.get("change_24", 0) or 0)

    bad_news_but_btc_holds = (
        macro_mod <= -12
        and fg_value <= 25
        and btc_change >= 0
        and change_24 < 5.0
        and rsi_value < 76
    )

    if not bad_news_but_btc_holds:
        return c

    # Only repair cases where single report became too red/low while /signal shows watch.
    if action == "SKIP" or "НЕ ПОКУПАТЬ" in verdict or score <= 35:
        watch_score = 55
        if vol >= 1.3 and btc_change >= 0.5:
            watch_score = 58
        if rsi_value >= 68:
            watch_score = min(watch_score, 55)

        c["score"] = max(score, watch_score)
        c["_master_score"] = max(int(c.get("_master_score", 0) or 0), c["score"])
        c["action"] = "WATCH"
        c["verdict"] = "🟡 НАБЛЮДАТЬ / ОПАСНЫЕ НОВОСТИ"
        c["_bad_news_quality_alt_watch"] = True
        c["_bad_alt_entry_cap"] = True
        c["chance_5"] = min(max(c.get("chance_5", 0), 15), 28)
        c["chance_10"] = min(max(c.get("chance_10", 0), 3), 6)
        c["chance_15"] = min(max(c.get("chance_15", 0), 1), 3)

        low = -2.8
        high = 1.5
        c["low"] = low
        c["high"] = high
        price = float(c.get("price", 0) or 0)
        c["target_low"] = price * (1 + low / 100)
        c["target_high"] = price * (1 + high / 100)
        c["_forecast_note"] = "новости давят"
        c["entry_zone"] = "без входа: опасные новости, ждать удержание цены/объёма 1–2 свечи и улучшение фона"

        c.setdefault("minus", [])
        for reason in [
            "опасные новости против альтов",
            "BTC держится, но фон не даёт вход",
            "это наблюдение, не готовый вход"
        ]:
            if reason not in c["minus"]:
                c["minus"].append(reason)

    return c

def single_analysis(symbol):
    c = alex_edge_ultra(symbol)

    if not c:
        return f"Версия: {BOT_VERSION}\nМонета не найдена."

    c = v6_apply_single_score_engine(c)
    c = v82_apply_single_coin_consistency(c)
    c = v84_apply_btc_core_asset_fix(c)
    c = v87_apply_alt_accum_fix(c)
    c = v88_apply_red_market_score_cap(c)
    c = v94_apply_falling_market_no_buy(c)
    c = v100_apply_single_coin_danger_watch_fix(c)
    c = v101_apply_danger_market_score_cap(c)
    c = v106_apply_safe_caution_border_fix(c)
    c = v115_apply_extreme_fear_wording_fix(c)
    c = v136_apply_core_no_red_neutral(c)
    c = v1314_apply_quality_alt_score_floor(c)
    c = v1313_apply_single_asymmetric_forecast(c)
    c = v153_apply_quality_alt_entry_cap(c)
    c = v161_apply_bad_news_quality_alt_watch(c)
    c = v155_apply_single_watch_score_consistency(c)
    c = v173_apply_btc_drop_wording_guard(c)

    # v11.4+: learning note/updates только после safety caps.
    c = v83_apply_self_learning(c)

    return format_single_coin_report(c)

def market_status():
    ctx = market_context()
    level = ctx.get("risk_level", "neutral")

    if level == "danger":
        status = "🔴 ОПАСНЫЙ РЫНОК"
    elif v106_safe_caution(ctx):
        status = "🟠 SAFE-CAUTION / ЖДАТЬ BTC"
    elif v115_extreme_fear_btc_weak(ctx):
        status = "🟡 EXTREME-FEAR / ТОЛЬКО НАБЛЮДАТЬ"
    elif level == "caution" and ctx.get("macro_mod", ctx.get("geo_mod", 0)) <= -15 and ctx.get("btc_change", 0) >= 0:
        status = "🟠 ПОВЫШЕННАЯ ОСТОРОЖНОСТЬ"
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
        "🧪 Paper — виртуальные сделки без реальных денег\n"
        "🏆 Топ — топ монет по объёму\n"
        "⚙️ Версия — текущая версия\n\n"
        "Команды тоже работают:\n"
        "/signal, /btc, /sol, /coin ETH, /market, /alerts, /learning, /top\n"
        "📦 Можно отправить пул команд одним сообщением, каждая с новой строки: /paper, /signal, /learning, /alerts. Бот выполнит их по очереди.\n"
        "/storage, /backup, /weekday, /learn_fast, /paper, /flush, /signal, /signal_unlock, /signal_status, /learning_sync, /sync_storage, /admin_update, /rollback\n"
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
        "📰 Новости: ФРС/геополитика/крипто обновляются по RSS-заголовкам каждые 15 минут\n🧠 v9.6: deal/ceasefire/end war/reopen Hormuz считаются деэскалацией, слабые источники получают меньший вес; v17.8.5: кнопка отчёта убрана, command pool работает, Paper на главном экране, доп. cleanup дублей обучения, danger-wording для single coin forecast, fast-learning 15м/30м/1ч/3ч/6ч/12ч/24ч/48ч, background scan каждые 30м"
    )


def coin_analyze_wait_text(coin):
    return f"⏳ Анализирую {coin}, подожди 10–30 секунд..."

def moscow_now():
    return datetime.utcnow() + timedelta(hours=MOSCOW_OFFSET_HOURS)

def run_fast_learning_background_scan():
    """v15.0: фоновый сбор обучения без Telegram-спама."""
    global _fast_learning_background_last
    if not FAST_LEARNING_BACKGROUND_ENABLED:
        return
    now_ts = time.time()
    if now_ts - float(_fast_learning_background_last or 0) < FAST_LEARNING_BACKGROUND_INTERVAL:
        return
    _fast_learning_background_last = now_ts

    def _run():
        try:
            # full_ticker_signal_report сам сохраняет fast-learning наблюдения.
            full_ticker_signal_report()
            maybe_run_backtest_background(force=False)
            background_github_sync([RESULTS_FILE, HISTORY_FILE, BACKTEST_FILE, CHAT_ID_FILE, LAST_UPDATE_FILE], max_files=5)
            print("v15 fast-learning background scan completed")
        except Exception as e:
            print(f"v15 fast-learning background scan error: {e}")

    Thread(target=_run, daemon=True).start()

def main():
    last_update = load_last_update_id()

    # v13.0: при старте после deploy не догоняем старые нажатия кнопок.
    last_update = discard_pending_updates_on_startup(last_update)

    # v11.9: уведомляем админа, когда Render реально запустил новую версию.
    notify_deploy_started()

    last_signal_key = None
    last_market_key = None
    last_pump_key = None
    coin_search_waiting = set()
    last_coin_search_prompt_time = {}
    last_coin_analysis_time = {}
    last_command_time = {}
    last_service_time = {}
    # v17.7.1: защита от старого service-callback рядом с тяжёлыми командами.
    last_non_service_command_time = {}
    last_manual_market_time = 0
    last_manual_signal_time = 0

    while True:
        try:
            updates = get_updates(last_update)
            items = updates.get("result", []) or []

            # v15.6 ADMIN UPLOAD PRIORITY FIX:
            # Если в пачке Telegram есть админский main*.py, сначала обрабатываем именно его,
            # а все старые кнопки/тяжёлые команды из этой же пачки пропускаем.
            # Так обновление не теряется за /signal, /alerts, /learning.
            priority_uploads = [item for item in items if is_admin_main_py_document_update(item)]
            if priority_uploads:
                priority_item = max(priority_uploads, key=lambda x: int(x.get("update_id", 0) or 0))
                priority_msg = priority_item.get("message", {}) or {}
                priority_chat_id = priority_msg.get("chat", {}).get("id")

                if priority_chat_id:
                    try:
                        force_clear_signal_lock()
                    except Exception:
                        pass

                    left, _lock_data = admin_upload_lock_left()
                    if left > 0:
                        send_message(
                            priority_chat_id,
                            f"⏳ Файл обновления уже обрабатывается. Второй дубль не запускаю. Подожди примерно {max(1, left)} сек и проверь /version."
                        )
                    else:
                        send_message(
                            priority_chat_id,
                            "📥 Файл обновления получил. Приоритетно загружаю main.py, старые команды из очереди пропускаю."
                        )
                        admin_result = admin_handle_document(priority_chat_id, priority_msg)
                        if admin_result:
                            send_message(priority_chat_id, admin_result)

                max_update = last_update or 0
                for queued_item in items:
                    try:
                        max_update = max(max_update, int(queued_item.get("update_id", 0) or 0) + 1)
                    except Exception:
                        pass

                if max_update:
                    last_update = max_update
                    save_last_update_id(last_update)

                continue

            # v17.7 COMMAND POOL:
            # Одно текстовое сообщение может содержать сразу несколько команд.
            # Раскладываем его в виртуальные updates, чтобы ниже сработала обычная проверенная логика.
            items = expand_command_pool_updates(items)

            # v17.6.2 SERVICE ROUTING FIX:
            # Если Telegram/Render прислал пачку быстрых нажатий, не даём старой кнопке 🛠 Сервис
            # всплывать перед Paper/Signal/Learning. Сервисное меню показываем только когда последняя
            # команда чата в текущей пачке действительно /service.
            batch_latest_command_by_chat = {}
            for _batch_item in items:
                try:
                    _msg = _batch_item.get("message", {}) or {}
                    _chat = _msg.get("chat", {}).get("id")
                    _raw = (_msg.get("text", "") or "").strip()
                    _cmd = normalize_button_text(_raw)
                    if _chat and _cmd:
                        batch_latest_command_by_chat[_chat] = _cmd
                except Exception:
                    pass

            for item in items:
                last_update = item["update_id"] + 1
                save_last_update_id(last_update)

                msg = item.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                raw_text = (msg.get("text", "") or "").strip()
                text = normalize_button_text(raw_text)

                # v11.3: старые команды после redeploy пропускаем.
                if is_stale_telegram_message(msg):
                    if chat_id:
                        # Не шлём ответ на старые команды, просто подтверждаем offset.
                        pass
                    continue

                if not chat_id:
                    continue

                save_chat_id(chat_id)

                if msg.get("_command_pool") and int(msg.get("_pool_index", 0) or 0) == 1:
                    send_message(chat_id, command_pool_ack_text(int(msg.get("_pool_total", 0) or 0)))

                if msg.get("document"):
                    admin_result = admin_handle_document(chat_id, msg)
                    if admin_result:
                        send_message(chat_id, admin_result)
                    continue

                # v13.7: защита от двойного тапа / повторной доставки одной и той же команды.
                if not msg.get("_command_pool") and should_skip_duplicate_command(chat_id, text, last_command_time):
                    continue

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

                if text.startswith("/") and text not in ["/service", "/more", "/admin"]:
                    last_non_service_command_time[chat_id] = time.time()

                if text == "/start":
                    send_message(chat_id, "✅ Бот работает\nМеню упрощено: ежедневные кнопки внизу, всё редкое в 🛠 Сервис. Файл обновления можно просто отправлять документом — теперь main*.py обрабатывается приоритетно.\n\n" + help_text())

                elif text == "/help":
                    send_message(chat_id, help_text())

                elif text == "/version":
                    send_message(chat_id, (
                        f"✅ Текущая версия бота: {BOT_VERSION}\n"
                        "📦 Пул команд: включён\n"
                        "🧾 Кнопка отчёта: убрана\n"
                        "🧪 Paper: на главном экране\n"
                        "🧠 v18.0 Core: ранняя классификация learning включена\n"
                        "📚 /learning_full: полный аудит открытых наблюдений"
                    ))

                elif text == "/flush":
                    if is_admin(chat_id) or not ADMIN_CHAT_ID:
                        save_last_update_id(last_update or 0)
                        force_clear_signal_lock()
                        clear_admin_upload_lock()
                        last_command_time.clear()
                        last_service_time.clear()
                        sync_github_storage_now([LAST_UPDATE_FILE, CHAT_ID_FILE, SIGNAL_LOCK_FILE], max_files=3)
                        send_message(chat_id, "✅ Очередь Telegram очищена, дубли кнопок, signal_lock и upload_lock сброшены.")
                    else:
                        send_message(chat_id, "⛔ /flush доступен только ADMIN_CHAT_ID.")

                elif text == "/signal_status":
                    send_message(chat_id, signal_status_report())

                elif text == "/signal_unlock":
                    if is_admin(chat_id) or not ADMIN_CHAT_ID:
                        force_clear_signal_lock()
                        save_signal_job("unlocked", chat_id, "signal_lock очищен пользователем")
                        send_message(chat_id, "✅ signal_lock очищен. Теперь /signal можно запускать заново.")
                    else:
                        send_message(chat_id, "⛔ /signal_unlock доступен только ADMIN_CHAT_ID.")

                elif text in ["/upload_unlock", "/admin_upload_unlock"]:
                    if is_admin(chat_id) or not ADMIN_CHAT_ID:
                        clear_admin_upload_lock()
                        send_message(chat_id, "✅ upload_lock очищен. Теперь можно отправить main.py заново.")
                    else:
                        send_message(chat_id, "⛔ /upload_unlock доступен только ADMIN_CHAT_ID.")

                elif text == "/sync_storage":
                    send_message(chat_id, "⏳ Синхронизирую dirty-файлы с GitHub...")
                    n = sync_github_storage_now(max_files=8)
                    send_message(chat_id, f"✅ GitHub sync завершён. Синхронизировано файлов: {n}")

                elif text == "/storage":
                    send_message(chat_id, storage_report())

                elif text == "/backup":
                    if is_admin(chat_id):
                        send_backup_files(chat_id)
                    else:
                        send_message(chat_id, "⛔ Backup доступен только ADMIN_CHAT_ID.")

                elif text == "/weekday" or text == "/stats":
                    send_message(chat_id, "⏳ Собираю статистику по дням недели, это может занять 20–40 секунд...")
                    send_message(chat_id, weekday_report())

                elif text in ["/service", "/more", "/admin"]:
                    if not msg.get("_command_pool"):
                        latest_cmd = batch_latest_command_by_chat.get(chat_id)
                        if latest_cmd not in ["/service", "/more", "/admin"]:
                            # В той же пачке уже есть более новая команда пользователя (/paper, /signal, /learning и т.п.).
                            # Не показываем устаревшее сервисное меню перед нужным отчётом.
                            continue

                        # v17.7.1: если сразу перед service была тяжёлая команда, это часто старый callback/эхо Telegram.
                        # Не даём ему всплывать перед Paper/Signal/Learning/Alerts.
                        prev_non_service = float(last_non_service_command_time.get(chat_id, 0) or 0)
                        if prev_non_service and time.time() - prev_non_service < 4:
                            continue

                    if should_skip_service_message(chat_id, last_service_time):
                        continue

                    send_message(
                        chat_id,
                        "🛠 Сервис: редкие служебные действия.",
                        reply_markup=service_keyboard(chat_id)
                    )

                elif text == "/admin_update":
                    send_message(chat_id, admin_start_update(chat_id))

                elif text == "/admin_cancel":
                    send_message(chat_id, admin_cancel_update(chat_id))

                elif text == "/rollback":
                    send_message(chat_id, admin_rollback(chat_id))

                elif text == "/top":
                    send_message(chat_id, get_top())

                elif text == "/signal":
                    # v12.6: снова одна кнопка.
                    # /signal сразу формирует полный быстрый ticker-safe отчёт по 35 монетам.
                    send_message(chat_id, "⏳ Формирую единый сигнал по 35 монетам...")
                    send_message(chat_id, unified_signal_report())
                    background_learning_update("manual_signal_v17_6_2")
                    background_paper_update("manual_signal_v17_6_2")

                elif text == "/signal_full":
                    # Скрытая ручная команда для отладки. Делает то же самое, что /signal.
                    send_message(chat_id, "⏳ Формирую единый сигнал по 35 монетам...")
                    send_message(chat_id, unified_signal_report())
                    background_learning_update("manual_signal_full_v17_6_2")
                    background_paper_update("manual_signal_full_v17_6_2")

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

                elif text == "/repair_learning":
                    send_message(chat_id, repair_learning_open_records())

                elif text == "/learning_sync":
                    send_message(chat_id, "⏳ Синхронизирую обучение с GitHub...")
                    send_message(chat_id, learning_report(sync_github=True))

                elif text == "/learning":
                    send_message(chat_id, learning_report(sync_github=False, full=False))

                elif text in ["/learning_full", "/learning_audit"]:
                    send_message(chat_id, learning_report(sync_github=False, full=True))

                elif text in ["/learn_fast", "/backtest", "/learning_fast"]:
                    send_message(chat_id, learn_fast_report(start=True))

                elif text in ["/paper", "/paper_trading", "/virtual"]:
                    send_message(chat_id, "⏳ Формирую отчёт по виртуальным сделкам...")
                    background_learning_update("manual_paper_v17_6_2")
                    try:
                        send_message(chat_id, paper_report())
                    except Exception as e:
                        send_message(
                            chat_id,
                            f"🧪 Paper trading ALEX EDGE\n"
                            f"Версия: {BOT_VERSION}\n\n"
                            f"⚠️ Отчёт /paper не сформировался: {str(e)[:180]}\n"
                            "Виртуальные сделки не трогают реальные деньги. Проверь /learning — там есть краткая строка paper trading."
                        )

                elif text == "/alerts":
                    send_message(chat_id, "⏳ Проверяю быстрые пампы...")
                    text_alert, _ = get_fast_pumps()
                    background_learning_update("manual_alerts_v17_6_2")

                    if text_alert:
                        send_message(chat_id, text_alert)
                    else:
                        send_message(chat_id, f"Версия: {BOT_VERSION}\nСейчас быстрых импульсов нет.")

            saved_chat_id = load_chat_id()

            # v13.8:
            # Автоматический scheduler отключён по умолчанию.
            # Он больше не запускает старый run_signal_background и не шлёт утренние дубли.
            # Если когда-нибудь понадобится вернуть авто-отчёты, включить env:
            # AUTO_REPORTS_ENABLED=1. Даже тогда /signal должен использовать только unified_signal_report().
            if saved_chat_id and AUTO_REPORTS_ENABLED:
                now_msk = moscow_now()

                signal_key = now_msk.strftime("%Y-%m-%d %H")
                market_key = now_msk.strftime("%Y-%m-%d")
                pump_key = now_msk.strftime("%Y-%m-%d %H:%M")

                if (
                    now_msk.hour in SIGNAL_HOURS
                    and now_msk.minute < 5
                    and last_signal_key != signal_key
                ):
                    send_message(saved_chat_id, unified_signal_report())
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

            run_fast_learning_background_scan()
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


# === v17.3 BTC DROP WORDING GUARD ===
# BTC около -2% + страх: single BTC не пишет СРЕДНЕСРОЧНЫЙ НАБОР / первая часть.
# Market news summary не путает деэскалацию с давлением из headline-строк.

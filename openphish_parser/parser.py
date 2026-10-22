import requests
import sqlite3
import pandas as pd
import time
import schedule
from datetime import datetime, timedelta
from pathlib import Path

# ---------- НАСТРОЙКИ ----------
FEED_URL = "https://openphish.com/feed.txt"
DB_PATH = "data/phishing.db"
EXCEL_PATH = "data/phishing_report.xlsx"
DURATION_MINUTES = 20          # период сбора (минут)
INTERVAL_MINUTES = 5           # интервал опроса (минут)
# --------------------------------

# Эвристический словарь для определения бренда по URL
BRAND_KEYWORDS = {
    "paypal": "PayPal",
    "microsoft": "Microsoft",
    "office365": "Office365",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "apple": "Apple",
    "amazon": "Amazon",
    "netflix": "Netflix",
    "google": "Google",
    "dropbox": "Dropbox",
    "dhl": "DHL",
    "fedex": "FedEx",
    "bank": "Bank (generic)",
    "crypto": "Crypto/Wallet",
    "wallet": "Crypto/Wallet",
    "roblox": "Roblox",
    "steam": "Steam",
    "binance": "Binance",
}

def guess_brand(url: str) -> str:
    """Пытается угадать целевой бренд по строке URL."""
    lower = url.lower()
    for keyword, brand in BRAND_KEYWORDS.items():
        if keyword in lower:
            return brand
    return "Unknown"

def init_db():
    """Создаёт таблицу, если её нет."""
    Path("data").mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS phishing_urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            brand TEXT,
            first_seen TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_to_db(urls_with_time):
    """Сохраняет новые URL в SQLite. Возвращает количество добавленных."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    added = 0
    for url, seen_time, brand in urls_with_time:
        try:
            cur.execute(
                "INSERT OR IGNORE INTO phishing_urls (url, brand, first_seen) VALUES (?, ?, ?)",
                (url, brand, seen_time)
            )
            if cur.rowcount > 0:
                added += 1
        except sqlite3.Error as e:
            print(f"DB error: {e}")
    conn.commit()
    conn.close()
    return added

def fetch_feed():
    """Загружает feed.txt и возвращает список URL."""
    try:
        resp = requests.get(FEED_URL, timeout=15)
        resp.raise_for_status()
        return [line.strip() for line in resp.text.splitlines() if line.strip()]
    except requests.RequestException as e:
        print(f"[!] Ошибка запроса: {e}")
        return []

def collect_once():
    """Один цикл сбора: запрос фида, разбор, сохранение в БД."""
    print(f"[{datetime.now():%H:%M:%S}] Запрос фида...")
    urls = fetch_feed()
    if not urls:
        print("   Фид пуст или недоступен.")
        return

    now = datetime.now()
    rows = [(u, now, guess_brand(u)) for u in urls]
    added = save_to_db(rows)
    print(f"   Получено URL: {len(urls)}, новых сохранено: {added}")

def generate_report(start_time: datetime, end_time: datetime):
    """Формирует Excel-отчёт и выводит статистику."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT url, brand, first_seen FROM phishing_urls", conn)
    conn.close()

    if df.empty:
        print("Нет данных для отчёта.")
        return

    # Основные метрики
    total_urls = len(df)
    unique_urls = df["url"].nunique()

    # Топ-3 брендов (исключая Unknown, если нужно)
    brand_counts = df["brand"].value_counts().head(3)
    top_brands = "\n".join([f"   {i+1}. {brand} — {count} URL" 
                           for i, (brand, count) in enumerate(brand_counts.items())])

    print("\n" + "="*60)
    print("📊 ИТОГОВЫЙ ОТЧЁТ")
    print("="*60)
    print(f"Время начала парсинга : {start_time:%Y-%m-%d %H:%M:%S}")
    print(f"Время окончания      : {end_time:%Y-%m-%d %H:%M:%S}")
    print(f"Всего URL собрано    : {total_urls}")
    print(f"Уникальных URL       : {unique_urls}")
    print(f"\nТоп-3 брендов (эвристика):")
    print(top_brands)
    print("="*60)

    # Сохранение в Excel
    df.to_excel(EXCEL_PATH, index=False)
    print(f"\n✅ Данные сохранены в Excel: {EXCEL_PATH}")
    print(f"✅ Данные сохранены в SQLite: {DB_PATH}")

def main():
    init_db()
    start_time = datetime.now()
    end_time = start_time + timedelta(minutes=DURATION_MINUTES)

    print(f"Старт парсинга: {start_time:%H:%M:%S}. Период: {DURATION_MINUTES} мин.")
    print(f"Интервал опроса: {INTERVAL_MINUTES} мин.\n")

    # Планировщик: первый запуск сразу, затем каждые INTERVAL_MINUTES
    schedule.every(INTERVAL_MINUTES).minutes.do(collect_once)
    collect_once()  # первый сбор без ожидания

    while datetime.now() < end_time:
        schedule.run_pending()
        time.sleep(1)

    schedule.clear()
    generate_report(start_time, end_time)

if __name__ == "__main__":
    main()

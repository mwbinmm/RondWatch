#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rond_watcher.py
----------------
این اسکریپت برای هر کد از پیش‌شماره‌ی ۰۹۱۲ (یعنی ۰۹۱۲۰ تا ۰۹۱۲۹)، صفحه‌ی
مربوطه رو در سایت rond.ir چک می‌کنه و شماره‌هایی که قیمتشون زیر سقفِ
مخصوصِ همون کد باشه رو پیدا می‌کنه. فقط شماره‌های "جدید" (که قبلاً اطلاع
داده نشدن) با ربات تلگرام برات فرستاده می‌شن.

تنظیمات (سقف قیمت هر کد) پایین همین فایل، توی بخش CONFIG هست — هر وقت
خواستی سقف قیمت یه کد رو عوض کنی یا کدی رو غیرفعال کنی، همون‌جا دستکاری کن.
"""

import json
import os
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ============================== CONFIG ==============================
BASE_URL = "https://rond.ir/SimLanding/Mci/0912/{code}"

# سقف قیمت به تومان، برای هر کد از 0912. هر کدی که این‌جا نباشه چک نمی‌شه.
CODE_PRICE_CEILINGS = {
    "0": 60_000_000,
    "1": 430_000_000,
    "2": 220_000_000,
    "3": 155_000_000,
    "4": 124_000_000,
    "5": 110_000_000,
    "6": 95_000_000,
    "7": 90_000_000,
    "8": 83_000_000,
    "9": 70_000_000,
}

# فایلی که شماره‌های قبلاً دیده‌شده رو نگه می‌داره تا دوباره پیام تکراری نفرسته
STATE_FILE = Path(__file__).parent / "state.json"

# اطلاعات ربات تلگرام از متغیرهای محیطی (در GitHub Secrets تنظیم می‌شن)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
# ======================================================================


def load_state() -> set:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return set(data.get("seen_numbers", []))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_state(seen_numbers: set) -> None:
    STATE_FILE.write_text(
        json.dumps({"seen_numbers": sorted(seen_numbers)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fetch_listings(url: str) -> list[dict]:
    """صفحه‌ی یک کد رو می‌گیره و لیست شماره‌هاش رو استخراج می‌کنه."""
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    number_pattern = re.compile(r"^09\d{2}[\d\s]{6,11}\d$")
    price_pattern = re.compile(r"([\d,]{5,15})\s*تومان")

    listings = []
    current = None

    for line in lines:
        if number_pattern.match(line):
            current = {"number_raw": line, "status": None, "terms": None, "price": None}
            continue

        if current is not None and "|" in line and current["status"] is None:
            parts = line.split("|")
            current["status"] = parts[0].strip()
            current["terms"] = parts[1].strip() if len(parts) > 1 else ""
            continue

        if current is not None and "تومان" in line and current["price"] is None:
            m = price_pattern.search(line)
            if m:
                price_str = m.group(1).replace(",", "")
                try:
                    current["price"] = int(price_str)
                except ValueError:
                    current["price"] = None
            if current["price"] is not None:
                digits = re.sub(r"\D", "", current["number_raw"])
                current["number"] = digits
                listings.append(current)
            current = None

    return listings


def send_telegram_message(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️  TELEGRAM_BOT_TOKEN یا TELEGRAM_CHAT_ID تنظیم نشده — پیام ارسال نشد.")
        print(text)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"❌ خطا در ارسال پیام تلگرام: {e}")
        return False


def format_number(digits: str) -> str:
    if len(digits) == 11:
        return f"{digits[0:4]} {digits[4:7]} {digits[7:9]} {digits[9:11]}"
    return digits


def main() -> int:
    seen = load_state()
    total_new = 0

    for code, ceiling in CODE_PRICE_CEILINGS.items():
        url = BASE_URL.format(code=code)
        prefix = f"0912{code}"

        try:
            listings = fetch_listings(url)
        except requests.RequestException as e:
            print(f"❌ خطا در دریافت صفحه‌ی کد {code}: {e}")
            continue

        if not listings:
            print(f"کد {code}: چیزی استخراج نشد (شاید ساختار سایت تغییر کرده).")
            continue

        new_matches = []
        for item in listings:
            number = item["number"]
            price = item["price"]

            if not number.startswith(prefix):
                continue
            if price is None or price > ceiling:
                continue
            if number in seen:
                continue

            new_matches.append(item)
            seen.add(number)

        if new_matches:
            for item in new_matches:
                price_fmt = f"{item['price']:,}"
                msg = (
                    f"🎯 <b>خط رند جدید زیر سقف قیمت (کد {code})</b>\n\n"
                    f"📱 شماره: <code>{format_number(item['number'])}</code>\n"
                    f"💰 قیمت: {price_fmt} تومان (سقف کد {code}: {ceiling:,} تومان)\n"
                    f"📋 وضعیت: {item['status']}\n"
                    f"💳 شرایط: {item['terms']}\n\n"
                    f"🔗 {url}"
                )
                send_telegram_message(msg)
                print(f"✅ اطلاع‌رسانی شد: {item['number']} — {price_fmt} تومان")
                total_new += 1
        else:
            print(f"کد {code}: موردی جدید زیر سقف {ceiling:,} تومان پیدا نشد.")

    save_state(seen)
    print(f"\nپایان اجرا. تعداد اطلاع‌رسانی‌های جدید: {total_new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Alifbo bot: Kirill / eski lotin / yangi lotin (Ö Ğ Ş Ç) o'rtasida matn o'giradi.

Konvertatsiya: https://pypi.org/project/alifbo/ (MIT).
Matnlar saqlanmaydi, faqat statistika (user_id, manba yozuv, belgilar soni).
"""
import asyncio
import html
import logging
import os
import re
import sqlite3
import time

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from alifbo import from_cyrillic, to_cyrillic, to_new_latin, to_old_latin
from dotenv import load_dotenv

load_dotenv()

MAX_CHARS = 20_000
CHUNK = 3_000
BIG_TEXT = 1_500  # katta matn = B2B signal (statistikada alohida sanaladi)

NEW_LABEL = "Yangi lotin (Ö Ğ Ş Ç)"
OLD_LABEL = "Eski lotin"
CYR_LABEL = "Kirill"
SRC_NAMES = {"cyr": CYR_LABEL, "old": OLD_LABEL, "new": NEW_LABEL}

CYR = re.compile(r"[\u0400-\u04FF]")
LAT = re.compile(r"[A-Za-z]")
NEW = re.compile(r"[ÖöĞğŞşÇç]")

db = sqlite3.connect(os.getenv("DB_PATH", "stats.db"))
db.execute("CREATE TABLE IF NOT EXISTS events (ts INTEGER, user_id INTEGER, src TEXT, chars INTEGER)")
db.commit()

dp = Dispatcher()


def detect(text: str) -> str:
    if len(CYR.findall(text)) > len(LAT.findall(text)):
        return "cyr"
    if NEW.search(text):
        return "new"
    return "old"


def convert(text: str):
    """Matn qaysi yozuvda bo'lsa, qolgan ikkitasiga o'giradi."""
    src = detect(text)
    if src == "cyr":
        new = from_cyrillic(text)
        old = to_old_latin(new.text)
        results = [(NEW_LABEL, new.text), (OLD_LABEL, old.text)]
        warns = len(new.warnings) + len(old.warnings)
    elif src == "old":
        new = to_new_latin(text)
        cyr = to_cyrillic(new.text)
        results = [(NEW_LABEL, new.text), (CYR_LABEL, cyr.text)]
        warns = len(new.warnings) + len(cyr.warnings)
    else:
        old = to_old_latin(text)
        cyr = to_cyrillic(text)
        results = [(OLD_LABEL, old.text), (CYR_LABEL, cyr.text)]
        warns = len(old.warnings) + len(cyr.warnings)
    return src, results, warns


def chunks(text: str, size: int = CHUNK):
    buf = ""
    for line in text.splitlines(keepends=True):
        while len(line) > size:  # juda uzun bitta qator
            if buf:
                yield buf
                buf = ""
            yield line[:size]
            line = line[size:]
        if len(buf) + len(line) > size:
            yield buf
            buf = ""
        buf += line
    if buf:
        yield buf


@dp.message(CommandStart())
@dp.message(Command("help"))
async def start(m: Message):
    await m.answer(
        "Salom! Menga o'zbekcha matn yuboring, men uni qolgan yozuvlarga o'giraman:\n"
        "• Kirill → yangi lotin + eski lotin\n"
        "• Eski lotin → yangi lotin + Kirill\n"
        "• Yangi lotin → eski lotin + Kirill\n\n"
        "Natijani bosib nusxalash mumkin. Yozuv avtomatik aniqlanadi."
    )


@dp.message(Command("stats"))
async def stats(m: Message):
    if m.from_user.id != int(os.getenv("ADMIN_ID", "0")):
        return
    now = int(time.time())
    total, users = db.execute("SELECT COUNT(*), COUNT(DISTINCT user_id) FROM events").fetchone()
    week = db.execute(
        "SELECT COUNT(DISTINCT user_id) FROM events WHERE ts > ?", (now - 7 * 86400,)
    ).fetchone()[0]
    returning = db.execute(
        "SELECT COUNT(*) FROM (SELECT user_id FROM events GROUP BY user_id "
        "HAVING COUNT(DISTINCT date(ts, 'unixepoch')) >= 2)"
    ).fetchone()[0]
    big = db.execute("SELECT COUNT(*) FROM events WHERE chars >= ?", (BIG_TEXT,)).fetchone()[0]
    await m.answer(
        f"Konvertatsiyalar: {total}\nFoydalanuvchilar: {users} (7 kunda: {week})\n"
        f"Qaytib kelganlar (2+ kun): {returning}\nKatta matnlar (>={BIG_TEXT} belgi): {big}"
    )


@dp.message(F.text & ~F.text.startswith("/"))
async def on_text(m: Message):
    text = m.text.strip()
    if len(text) > MAX_CHARS:
        await m.answer(f"Matn juda uzun (maksimum {MAX_CHARS} belgi). Bo'laklab yuboring.")
        return

    src, results, warns = convert(text)
    db.execute(
        "INSERT INTO events VALUES (?, ?, ?, ?)", (int(time.time()), m.from_user.id, src, len(text))
    )
    db.commit()

    await m.answer(f"Aniqlangan yozuv: <b>{SRC_NAMES[src]}</b>")
    for label, out in results:
        for i, part in enumerate(chunks(out)):
            head = f"<b>{label}</b>\n" if i == 0 else ""
            await m.answer(f"{head}<code>{html.escape(part)}</code>")
    if warns:
        await m.answer(
            f"⚠️ {warns} ta joyda bir nechta variant bor (masalan, Kirill «е» → e/ye). "
            "Natijani tekshirib chiqing."
        )


@dp.message()
async def fallback(m: Message):
    await m.answer("Iltimos, matn yuboring.")


async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(os.environ["BOT_TOKEN"], default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

"""Alifbo platform: Production Suite, AI Support Concierge, and Fast Transliteration API.

Powered by FastAPI, aiogram 3, alifbo, and Google Gemini.
"""
import asyncio
from contextlib import asynccontextmanager
import csv
import html
import io
import json
import logging
import os
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from alifbo import from_cyrillic, to_cyrillic, to_new_latin, to_old_latin
from dotenv import load_dotenv
from fastapi import FastAPI, Header, Request, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.api.admin import router as admin_router
from app.api.chat import router as chat_router
from app.database import get_connection, init_db
from app.services.concierge_service import ConciergeService
from app.services.purchase_service import PurchaseService
from app.services.quota_service import QuotaService

load_dotenv()

logging.basicConfig(level=logging.INFO)

MAX_CHARS = 20_000
CHUNK = 3_000
BIG_TEXT = 1_500

NEW_LABEL = "Yangi lotin (Ö Ğ Ş Ç)"
OLD_LABEL = "Eski lotin"
CYR_LABEL = "Kirill"
SRC_NAMES = {"cyr": CYR_LABEL, "old": OLD_LABEL, "new": NEW_LABEL}

CYR = re.compile(r"[\u0400-\u04FF]")
LAT = re.compile(r"[A-Za-z]")
NEW = re.compile(r"[ÖöĞğŞşÇç]")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0").strip() or 0)

# Local Telegram Bot API configuration
TELEGRAM_API_SERVER = os.getenv("TELEGRAM_API_SERVER", "").rstrip("/")

# Webhook configuration
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "").rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
if not WEBHOOK_PATH.startswith("/"):
    WEBHOOK_PATH = f"/{WEBHOOK_PATH}"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Initialize Bot with local Bot API server or standard Telegram cloud
if TELEGRAM_API_SERVER:
    custom_server = TelegramAPIServer.from_base(TELEGRAM_API_SERVER, is_local=True)
    session = AiohttpSession(api=custom_server)
    bot = Bot(
        token=os.environ["BOT_TOKEN"],
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    logging.info(f"Initialized bot with local Telegram Bot API: {TELEGRAM_API_SERVER}")
else:
    bot = Bot(
        token=os.environ["BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

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
        while len(line) > size:
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
    if m.from_user:
        QuotaService.ensure_user(
            user_id=m.from_user.id,
            username=m.from_user.username,
            first_name=m.from_user.first_name,
        )

    await m.answer(
        "Salom! Menga o'zbekcha matn yuboring, men uni qolgan yozuvlarga o'giraman:\n"
        "• Kirill → yangi lotin (Ö Ğ Ş Ç) + eski lotin\n"
        "• Eski lotin → yangi lotin + Kirill\n"
        "• Yangi lotin → eski lotin + Kirill\n\n"
        "Rasm ostidagi matnlar, kanaldan forward xabarlar va .txt fayllar ham qabul qilinadi!\n\n"
        "Buyruqlar:\n"
        "/tariflar — Hamyonbop tarif rejalari va paketlar\n"
        "/support — 24/7 AI Yordamchi Konsyerj bilan suhbat"
    )


def get_tariffs_keyboard() -> InlineKeyboardMarkup:
    """Build interactive tariff options keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎓 Talaba & O'quvchi — 12 000 so'm", callback_data="order_tier:student")],
        [InlineKeyboardButton(text="🚀 Muallim & Pro — 25 000 so'm", callback_data="order_tier:pro")],
        [InlineKeyboardButton(text="🏢 Tashkilot & Nashriyot — 75 000 so'm", callback_data="order_tier:business")],
        [InlineKeyboardButton(text="💬 AI Yordamchi bilan bog'lanish", callback_data="open_support")],
    ])


TARIFFS_OVERVIEW_TEXT = (
    "🌟 <b>Alifbo Hamyonbop Tarif Rejalari & Paketlari</b>\n\n"
    "1. <b>Oddiy / Bepul</b> — <b>0 so'm</b>\n"
    "• Standart tezlik, 20 000 belgigacha bir martalik transliteratsiya\n"
    "• Rasm osti va kanaldan forward xabarlar\n\n"
    "2. <b>Talaba & O'quvchi</b> — <b>12 000 so'm / oy</b>\n"
    "• Kunlik 100 000 belgi hajmi\n"
    "• .docx va .txt hujjatlarni to'liq o'girish\n"
    "• Alifbo ta'lim modullari va harflar qoidalari\n"
    "• 24/7 AI Support Concierge yordamchisi\n\n"
    "3. <b>Muallim & Pro</b> — <b>25 000 so'm / oy</b>\n"
    "• Kunlik 500 000 belgi (katta kitob va darsliklar)\n"
    "• Interaktiv Alifbo viktorinalari va testlari\n"
    "• CSV va DOCX formatda eksport\n"
    "• Tezyurar ustuvor navbat\n\n"
    "4. <b>Tashkilot & Nashriyot</b> — <b>75 000 so'm / oy</b>\n"
    "• Cheksiz oylik paket (2M+ belgilar)\n"
    "• Kitob sahifalaridan matnni ajratish (OCR)\n"
    "• Tashqi saytlarga ulash uchun REST API kaliti\n"
    "• 24/7 VIP shaxsiy admin konsyerji\n\n"
    "<i>O'zingizga ma'qul tarifni tanlab, to'g'ridan-to'g'ri xarid so'rovini adminga yuborishingiz mumkin:</i>"
)


@dp.message(Command("tariflar"))
@dp.message(Command("tariffs"))
async def show_tariffs(m: Message):
    """Show realistic, affordable pricing plans."""
    if m.from_user:
        QuotaService.ensure_user(
            user_id=m.from_user.id,
            username=m.from_user.username,
            first_name=m.from_user.first_name,
        )
    await m.answer(TARIFFS_OVERVIEW_TEXT, reply_markup=get_tariffs_keyboard())


@dp.callback_query(F.data == "back_to_tariffs")
async def on_back_to_tariffs(call: CallbackQuery):
    """Return to tariffs main list."""
    try:
        await call.message.edit_text(TARIFFS_OVERVIEW_TEXT, reply_markup=get_tariffs_keyboard())
    except Exception:
        pass
    await call.answer()


@dp.callback_query(F.data.startswith("order_tier:"))
async def on_order_tier_prompt(call: CallbackQuery):
    """Show selected tariff summary with creative presentation and options."""
    tier_id = call.data.split(":")[1]
    conn = get_connection()
    try:
        tier = conn.execute("SELECT * FROM tiers WHERE id = ?", (tier_id,)).fetchone()
    finally:
        conn.close()

    if not tier:
        await call.answer("Kechirasiz, bunday tarif topilmadi!", show_alert=True)
        return

    features = []
    if tier["features"]:
        try:
            features = json.loads(tier["features"])
        except Exception:
            features = [tier["features"]]
    features_text = "\n".join([f"✨ {f}" for f in features])

    tier_icons = {
        "student": "🎓",
        "pro": "⚡️",
        "business": "🏢",
    }
    tier_icon = tier_icons.get(tier_id, "💎")

    tier_ctas = {
        "student": "🎓 Talaba obunasini faollashtirish",
        "pro": "⚡️ Pro imkoniyatlarini ochish",
        "business": "🏢 Tashkilot paketiga ulanish",
    }
    cta_text = tier_ctas.get(tier_id, "⚡️ Obunani faollashtirish")

    text = (
        f"{tier_icon} <b>Alifbo {tier['name']} — Premium A'zolik</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Oylik investitsiya:</b> <b>{tier['price_uzs']:,} so'm</b>\n"
        f"⚡️ <b>Kunlik quvvat:</b> <b>{tier['daily_char_limit']:,}</b> belgi transliteratsiya\n\n"
        f"💎 <b>Sizga ochiladigan imkoniyatlar:</b>\n"
        f"{features_text}\n\n"
        f"🚀 <i>Obunani 1-bosishda rasmiylashtiring yoki karta orqali to'lov rekvizitlarini oling:</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🚀 {cta_text}", callback_data=f"confirm_order:{tier_id}")],
        [InlineKeyboardButton(text="💳 Karta orqali to'lov rekvizitlari", callback_data=f"pay_details:{tier_id}")],
        [
            InlineKeyboardButton(text="💬 Konsyerj maslahati", callback_data="open_support"),
            InlineKeyboardButton(text="↩️ Boshqa tariflar", callback_data="back_to_tariffs"),
        ],
    ])
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        await call.message.answer(text, reply_markup=kb)
    await call.answer()


@dp.callback_query(F.data.startswith("pay_details:"))
async def on_pay_details(call: CallbackQuery):
    """Show realistic payment details and instant activation option."""
    tier_id = call.data.split(":")[1]
    conn = get_connection()
    try:
        tier = conn.execute("SELECT * FROM tiers WHERE id = ?", (tier_id,)).fetchone()
    finally:
        conn.close()

    if not tier:
        await call.answer("Tarif topilmadi!", show_alert=True)
        return

    text = (
        f"💳 <b>Alifbo Rasmiy To'lov Rekvizitlari</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Tanlangan tarif:</b> <b>{tier['name']}</b>\n"
        f"💵 <b>To'lov miqdori:</b> <b>{tier['price_uzs']:,} so'm</b>\n\n"
        f"Istalgan ilova (Payme, Click, Uzum Bank) orqali to'lov qilishingiz mumkin:\n"
        f"💳 Karta: <code>8600 5304 1234 5678</code>\n"
        f"👤 Qabul qiluvchi: <b>Alifbo Platformasi</b>\n\n"
        f"To'lovni amalga oshirgach, chekni /support orqali yuborishingiz yoki quyidagi tugma orqali hisobingizni faollashtirish so'rovini qoldirishingiz mumkin:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ To'lov qildim, hisobimni yoqing!", callback_data=f"confirm_order:{tier_id}")],
        [InlineKeyboardButton(text="↩️ Ortga qaytish", callback_data=f"order_tier:{tier_id}")],
    ])
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        await call.message.answer(text, reply_markup=kb)
    await call.answer()


@dp.callback_query(F.data.startswith("confirm_order:"))
async def on_confirm_order(call: CallbackQuery, bot: Bot):
    """Process tariff order and dispatch creative notification to admin with 1-click actions."""
    tier_id = call.data.split(":")[1]
    user = call.from_user
    user_id = user.id
    username = user.username
    first_name = user.first_name

    try:
        order = PurchaseService.create_request(
            user_id=user_id,
            username=username,
            first_name=first_name,
            tier_id=tier_id,
        )
    except Exception as e:
        await call.answer(f"Xatolik yuz berdi: {e}", show_alert=True)
        return

    req_id = order["id"]
    tier_name = order["tier_name"]
    price_uzs = order["price_uzs"]
    daily_char_limit = order["daily_char_limit"]

    user_conf_text = (
        f"🎉 <b>Ajoyib tanlov! Obunangiz rasmiylashtirilmoqda!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Buyurtma kodi:</b> <code>#ALF-{req_id}</code>\n"
        f"📦 <b>Tanlangan tarif:</b> <b>{tier_name}</b>\n"
        f"💰 <b>Oylik investitsiya:</b> <b>{price_uzs:,} so'm</b>\n"
        f"⏳ <b>Holat:</b> <i>Konsyerj tekshiruvida...</i>\n\n"
        f"✨ <i>Administratorimiz so'rovingizni ko'rib chiqmoqda. Tasdiqlanishi bilan profilingiz barcha kengaytirilgan imkoniyatlar bilan bir zumda faollashadi!</i>\n\n"
        f"Savol yoki to'lov cheki qoldirish uchun: /support"
    )
    user_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 AI Konsyerj / Chek yuborish", callback_data="open_support")],
        [InlineKeyboardButton(text="↩️ Tariflarga qaytish", callback_data="back_to_tariffs")],
    ])
    try:
        await call.message.edit_text(user_conf_text, reply_markup=user_kb)
    except Exception:
        await call.message.answer(user_conf_text, reply_markup=user_kb)
    await call.answer("Buyurtmangiz qabul qilindi va konsyerjga yetkazildi!", show_alert=True)

    # Notify ADMIN_ID with rich CRM ticket details and 1-click inline actions
    if ADMIN_ID:
        req_details = PurchaseService.get_request(req_id) or {}
        current_tier = req_details.get("current_tier", "free")
        credits_balance = req_details.get("credits_balance", 20000)
        req_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(order["created_at"]))

        admin_msg = (
            f"🚀 <b>YANGI OBUNA BUYURTMASI! #ALF-{req_id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Mijoz:</b> <b>{html.escape(first_name or 'Noma’lum')}</b>\n"
            f"• Username: @{username or 'yoq'}\n"
            f"• Telegram ID: <code>{user_id}</code>\n"
            f"• Hozirgi tarifi: <code>{current_tier}</code> ({credits_balance:,} belgi)\n\n"
            f"📦 <b>Xarid qilinayotgan paket:</b>\n"
            f"• Tarif: <b>{tier_name}</b>\n"
            f"• Narxi: <b>{price_uzs:,} so'm / oy</b>\n"
            f"• Yangi kunlik limit: <b>+{daily_char_limit:,} belgi</b>\n"
            f"• Buyurtma vaqti: <b>{req_time}</b>\n\n"
            f"⚡️ <b>1-Bosishda boshqarish:</b>"
        )

        user_link = f"https://t.me/{username}" if username else f"tg://user?id={user_id}"
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="⚡️ Darhol Faollashtirish", callback_data=f"adm_approve:{req_id}"),
                InlineKeyboardButton(text="🛑 Rad etish", callback_data=f"adm_reject:{req_id}"),
            ],
            [InlineKeyboardButton(text="💬 Mijozga yozish", url=user_link)],
        ])
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=admin_msg, reply_markup=admin_kb)
        except Exception as e:
            logging.error(f"Failed to deliver purchase request to admin: {e}")


@dp.callback_query(F.data.startswith("adm_approve:"))
async def on_admin_approve_order(call: CallbackQuery, bot: Bot):
    """Handle 1-click admin approval of tariff purchase."""
    if call.from_user.id != ADMIN_ID:
        await call.answer("Faqat admin uchun!", show_alert=True)
        return

    req_id = int(call.data.split(":")[1])
    order = PurchaseService.get_request(req_id)
    if not order:
        await call.answer("So'rov topilmadi!", show_alert=True)
        return

    if order["status"] == "approved":
        await call.answer("Bu so'rov allaqachon tasdiqlangan!", show_alert=True)
        return
    if order["status"] == "rejected":
        await call.answer("Bu so'rov avval rad etilgan! Qayta ko'rib chiqish uchun admin panelidan foydalaning.", show_alert=True)
        return

    try:
        updated = PurchaseService.approve_request(req_id, actor=f"admin_{call.from_user.id}")
    except Exception as e:
        await call.answer(f"Xatolik: {e}", show_alert=True)
        return

    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    admin_approved_text = (
        f"✅ <b>BUYURTMA TASDIQLANDI #ALF-{req_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Mijoz: <b>{html.escape(order.get('first_name') or '')}</b> (<code>{order['user_id']}</code>)\n"
        f"📦 Yangi tarif: <b>{order['tier_name']}</b> ({order['price_uzs']:,} so'm)\n"
        f"👨‍💻 Tasdiqladi: <b>{call.from_user.first_name}</b>\n"
        f"🕒 Vaqt: <b>{now_str}</b>\n\n"
        f"<i>Foydalanuvchi akkaunti muvaffaqiyatli yangi tarifga o'tkazildi va unga tabrik xabari yetkazildi!</i>"
    )
    try:
        await call.message.edit_text(admin_approved_text)
    except Exception:
        pass
    await call.answer("Buyurtma tasdiqlandi va tarif darhol faollashtirildi!")

    # Notify user on Telegram
    try:
        user_congrats = (
            f"🎉 <b>Tabriklaymiz! Sizning obunangiz faollashtirildi!</b>\n\n"
            f"🆔 Buyurtma kodi: <code>#ALF-{req_id}</code>\n"
            f"📦 Yangi darajangiz: <b>{order['tier_name']}</b>\n"
            f"⚡️ Kunlik quvvat: <b>{updated.get('daily_char_limit', 0):,} belgi</b>\n\n"
            f"Endi barcha imkoniyatlar siz uchun to'liq ochiq! /start"
        )
        await bot.send_message(chat_id=order["user_id"], text=user_congrats)
    except Exception as e:
        logging.warning(f"Could not notify user {order['user_id']} of approval: {e}")


@dp.callback_query(F.data.startswith("adm_reject:"))
async def on_admin_reject_order(call: CallbackQuery, bot: Bot):
    """Handle 1-click admin rejection of tariff purchase."""
    if call.from_user.id != ADMIN_ID:
        await call.answer("Faqat admin uchun!", show_alert=True)
        return

    req_id = int(call.data.split(":")[1])
    order = PurchaseService.get_request(req_id)
    if not order:
        await call.answer("So'rov topilmadi!", show_alert=True)
        return

    if order["status"] in ["approved", "rejected"]:
        await call.answer(f"Bu so'rov allaqachon ko'rib chiqilgan ({order['status']})!", show_alert=True)
        return

    try:
        PurchaseService.reject_request(req_id, actor=f"admin_{call.from_user.id}", reason="Administrator tomonidan rad etildi")
    except Exception as e:
        await call.answer(f"Xatolik: {e}", show_alert=True)
        return

    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    admin_reject_text = (
        f"❌ <b>BUYURTMA RAD ETILDI #ALF-{req_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Mijoz: <b>{html.escape(order.get('first_name') or '')}</b> (<code>{order['user_id']}</code>)\n"
        f"📦 Tarif: <b>{order['tier_name']}</b>\n"
        f"👨‍💻 Rad etdi: <b>{call.from_user.first_name}</b>\n"
        f"🕒 Vaqt: <b>{now_str}</b>"
    )
    try:
        await call.message.edit_text(admin_reject_text)
    except Exception:
        pass
    await call.answer("Buyurtma rad etildi.")

    # Notify user on Telegram
    try:
        user_notice = (
            f"ℹ️ <b>Buyurtma holati bo'yicha ma'lumot</b>\n\n"
            f"Sizning <code>#ALF-{req_id}</code> raqamli <b>{order['tier_name']}</b> tarifi uchun so'rovingiz ko'rib chiqildi va rad etildi.\n\n"
            f"Batafsil ma'lumot olish yoki boshqa to'lov turini kelishish uchun: /support"
        )
        await bot.send_message(chat_id=order["user_id"], text=user_notice)
    except Exception as e:
        logging.warning(f"Could not notify user {order['user_id']} of rejection: {e}")


@dp.callback_query(F.data == "open_support")
async def on_support_callback(call: CallbackQuery):
    await call.message.answer(
        "Alifbo AI Konsyerjiga xush kelibsiz! Menga tariflar, yangi harflar qoidalari yoki platforma bo'yicha istalgan savolingizni yuborishingiz mumkin:"
    )
    await call.answer()


ACTIVE_SUPPORT_SESSIONS: set[int] = set()


def build_concierge_kb(suggested_actions: Optional[list] = None) -> Optional[InlineKeyboardMarkup]:
    if not suggested_actions:
        return None
    rows = []
    current_row = []
    for act in suggested_actions:
        current_row.append(InlineKeyboardButton(text=act["text"], callback_data=act["callback_data"]))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(Command("support"))
async def support_command(m: Message):
    """Start interactive AI Support Concierge session in Telegram."""
    user_id = m.from_user.id if m.from_user else 0
    if user_id:
        QuotaService.ensure_user(
            user_id=user_id,
            username=m.from_user.username,
            first_name=m.from_user.first_name,
        )
        ACTIVE_SUPPORT_SESSIONS.add(user_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Buyurtmam holati", callback_data="support_check_order"),
            InlineKeyboardButton(text="💳 To'lov rekvizitlari", callback_data="support_pay_card"),
        ],
        [
            InlineKeyboardButton(text="🚀 Tariflar katalogi", callback_data="show_tariffs"),
            InlineKeyboardButton(text="👨‍💼 Operator kerak", callback_data="support_call_admin"),
        ],
        [
            InlineKeyboardButton(text="❌ Suhbatni yakunlash", callback_data="support_exit"),
        ]
    ])

    await m.answer(
        "👋 <b>Assalomu alaykum! Men Alifbo AI Yordamchi Konsyerjiman.</b>\n\n"
        "Men sizga platforma xizmatlari, tariflar, to'lovlar, buyurtma holati hamda yangi lotin yozuvi (Ö Ğ Ş Ç) bo'yicha yordam berishga tayyorman.\n\n"
        "💬 <i>Savolingizni to'g'ridan-to'g'ri yozib qoldiring yoki quyidagi tezkor amallardan birini tanlang:</i>",
        reply_markup=kb,
    )


@dp.callback_query(F.data == "support_check_order")
async def support_check_order_callback(call: CallbackQuery):
    user_id = call.from_user.id if call.from_user else 0
    session_id = f"tg_{user_id}"
    res = await ConciergeService.generate_response(
        session_id=session_id,
        message="Buyurtmam holati qanday?",
        user_id=user_id,
        channel="telegram",
    )
    kb = build_concierge_kb(res.get("suggested_actions"))
    await call.message.answer(f"🤖 <b>Alifbo AI Konsyerj</b>:\n\n{res['response']}", reply_markup=kb)
    await call.answer()


@dp.callback_query(F.data == "support_pay_card")
async def support_pay_card_callback(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Barcha Tariflar", callback_data="show_tariffs")],
        [InlineKeyboardButton(text="👨‍💼 Operatorga ulanish", callback_data="support_call_admin")],
        [InlineKeyboardButton(text="❌ Chiqish", callback_data="support_exit")],
    ])
    await call.message.answer(
        "💳 <b>Alifbo Rasmiy To'lov Rekvizitlari</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "• Karta raqami: <code>8600 5304 1234 5678</code>\n"
        "• Karta egasi: <b>Alifbo Ta'lim MChJ</b>\n"
        "• To'lov turlari: <b>Payme, Click, Uzum, Bank kartalari</b>\n\n"
        "📌 <b>To'lov qilgach:</b>\n"
        "Chek skrinshotini to'g'ridan-to'g'ri shu chatga <b>rasm (photo)</b> sifatida yuboring. Administratorimiz tasdiqlashi bilan hisobingiz darhol faollashadi!",
        reply_markup=kb,
    )
    await call.answer()


@dp.callback_query(F.data == "support_call_admin")
async def support_call_admin_callback(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id if call.from_user else 0
    username = call.from_user.username if call.from_user else None
    first_name = call.from_user.first_name if call.from_user else None
    session_id = f"tg_{user_id}"

    ticket_id = ConciergeService.create_support_ticket(
        session_id=session_id,
        user_id=user_id,
        subject="Foydalanuvchi inson operatori bilan bog'lanishni so'radi",
        reason="Mijoz qo'lda operator chaqirish tugmasini bosdi",
        priority="high",
    )

    if ADMIN_ID:
        user_link = f"https://t.me/{username}" if username else f"tg://user?id={user_id}"
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Mijozga yozish", url=user_link)]
        ])
        try:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🚨 <b>Yangi Tezkor Operator Chaqiruv Chiptasi #{ticket_id}</b>\n\n"
                    f"👤 <b>Mijoz:</b> {html.escape(first_name or 'Noma’lum')} (@{username or 'yoq'})\n"
                    f"🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n"
                    f"📌 <b>Holat:</b> Mijoz zudlik bilan inson operatori yordamini so'ramoqda.\n\n"
                    f"Boshqaruv paneli: <code>http://localhost:8000/admin</code>"
                ),
                reply_markup=admin_kb,
            )
        except Exception as e:
            logging.error(f"Failed to notify admin of call_admin: {e}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Suhbatni yakunlash", callback_data="support_exit")]
    ])
    await call.message.answer(
        f"👨‍💼 <b>Murojaatingiz qabul qilindi (Chipta #{ticket_id})!</b>\n\n"
        "Bosh administratorimizga xabar yetkazildi. Tez orada siz bilan Telegram orqali bog'lanishadi. "
        "Iltimos, aloqada bo'ling!",
        reply_markup=kb,
    )
    await call.answer()


@dp.callback_query(F.data == "support_exit")
async def support_exit_callback(call: CallbackQuery):
    user_id = call.from_user.id if call.from_user else 0
    ACTIVE_SUPPORT_SESSIONS.discard(user_id)
    await call.message.answer(
        "✅ <b>AI Konsyerj sessiyasi yakunlandi.</b>\n\n"
        "Endi matnlaringizni bemalol transliteratsiya qilishingiz mumkin. "
        "Yana savol yoki yordam kerak bo'lsa, istalgan vaqt /support buyrug'ini yuboring!"
    )
    await call.answer()


@dp.message(Command("stats"))
async def stats(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    conn = get_connection()
    try:
        now = int(time.time())
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        users = conn.execute("SELECT COUNT(DISTINCT user_id) FROM events").fetchone()[0]
        week = conn.execute("SELECT COUNT(DISTINCT user_id) FROM events WHERE ts > ?", (now - 7 * 86400,)).fetchone()[0]
        returning = conn.execute(
            "SELECT COUNT(*) FROM (SELECT user_id FROM events GROUP BY user_id HAVING COUNT(DISTINCT date(ts, 'unixepoch')) >= 2)"
        ).fetchone()[0]
        big = conn.execute("SELECT COUNT(*) FROM events WHERE chars >= ?", (BIG_TEXT,)).fetchone()[0]
        tickets = conn.execute("SELECT COUNT(*) FROM support_tickets WHERE status = 'open'").fetchone()[0]

        await m.answer(
            f"📊 <b>Alifbo Real-Vaqt Statistikasi</b>:\n\n"
            f"• Konvertatsiyalar: {total}\n"
            f"• Foydalanuvchilar: {users} (7 kunda faol: {week})\n"
            f"• Qaytib kelganlar (2+ kun): {returning}\n"
            f"• Katta matnlar (>={BIG_TEXT} belgi): {big}\n"
            f"• Ochiq qo'llab-quvvatlash chiptalari: {tickets}\n\n"
            f"Admin portaliga kirish: <code>http://localhost:8000/admin</code>"
        )
    finally:
        conn.close()


@dp.message(Command("export"))
async def export_stats(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    conn = get_connection()
    try:
        rows = conn.execute("SELECT ts, user_id, src, chars FROM events ORDER BY ts ASC").fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["timestamp", "user_id", "source", "char_count"])
        writer.writerows([tuple(r) for r in rows])

        file_bytes = output.getvalue().encode("utf-8")
        filename = f"alifbo_stats_{int(time.time())}.csv"
        doc = BufferedInputFile(file_bytes, filename=filename)
        await m.answer_document(doc, caption="Statistika ma'lumotlari (CSV)")
    finally:
        conn.close()


async def extract_text(m: Message, bot: Bot) -> str | None:
    """Extract text from messages regardless of format (text, media caption, or .txt file)."""
    if m.text:
        return m.text
    if m.caption:
        return m.caption
    if m.document and m.document.file_name and m.document.file_name.lower().endswith(".txt"):
        if m.document.file_size and m.document.file_size <= 500_000:
            try:
                file_io = io.BytesIO()
                await bot.download(m.document, destination=file_io)
                return file_io.getvalue().decode("utf-8", errors="replace")
            except Exception as e:
                logging.warning(f"Failed to read txt document: {e}")
    return None


@dp.message(F.photo)
async def handle_photo(m: Message, bot: Bot):
    """Handle photo messages as payment receipts or transliteration captions."""
    user_id = m.from_user.id if m.from_user else (m.sender_chat.id if m.sender_chat else 0)
    username = m.from_user.username if m.from_user else None
    first_name = m.from_user.first_name if m.from_user else None
    if user_id:
        QuotaService.ensure_user(user_id=user_id, username=username, first_name=first_name)

    caption = m.caption.strip() if m.caption else ""

    # Check recent order status for receipt matching
    conn = get_connection()
    latest_order = None
    try:
        if user_id:
            latest_order = conn.execute(
                "SELECT * FROM purchase_requests WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
    finally:
        conn.close()

    is_receipt = (
        user_id in ACTIVE_SUPPORT_SESSIONS
        or (latest_order and latest_order["status"] in ["pending", "rejected"])
        or any(w in caption.lower() for w in ["chek", "to'lov", "tolov", "pul", "admin", "tasdiq", "kvitansiya", "payme", "click", "uzum"])
    )

    if is_receipt:
        if ADMIN_ID:
            order_ref = f"#ALF-{latest_order['id']} ({latest_order['tier_name']})" if latest_order else "To'lov cheki"
            admin_caption = (
                f"📸 <b>MIJOZ TO'LOV CHEKI YUBORDI!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Mijoz:</b> {html.escape(first_name or 'Noma’lum')} (@{username or 'yoq'})\n"
                f"🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n"
                f"📦 <b>Buyurtma:</b> <b>{order_ref}</b>\n"
                f"📝 <b>Izoh:</b> <i>{html.escape(caption or 'Izohsiz chek')}</i>"
            )
            user_link = f"https://t.me/{username}" if username else f"tg://user?id={user_id}"
            admin_buttons = []
            if latest_order and latest_order["status"] != "approved":
                admin_buttons.append([
                    InlineKeyboardButton(text="⚡️ Darhol Tasdiqlash", callback_data=f"adm_approve:{latest_order['id']}"),
                    InlineKeyboardButton(text="🛑 Rad etish", callback_data=f"adm_reject:{latest_order['id']}"),
                ])
            admin_buttons.append([InlineKeyboardButton(text="💬 Mijozga yozish", url=user_link)])

            try:
                await bot.send_photo(
                    chat_id=ADMIN_ID,
                    photo=m.photo[-1].file_id,
                    caption=admin_caption,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=admin_buttons),
                )
            except Exception as e:
                logging.error(f"Failed to forward receipt photo to admin: {e}")

        await m.answer(
            "📸 <b>To'lov cheki qabul qilindi!</b>\n\n"
            "Rasm zudlik bilan bosh administratorimizga yetkazildi. "
            "Ma'lumotlar tekshirilgach, hisobingiz avtomatik tarzda yangi tarifga faollashtiriladi!\n\n"
            "Boshqa savollaringiz bo'lsa, bemalol yozishingiz mumkin: /support"
        )
        return

    # If caption is provided and not a receipt, transliterate caption
    if caption:
        m.text = caption
        await handle_message(m, bot)
    else:
        await m.answer(
            "Rasm qabul qilindi. Agar bu to'lov cheki bo'lsa, u ma'muriyatga yetkazildi.\n"
            "Agar rasmdagi matnni transliteratsiya qilmoqchi bo'lsangiz, iltimos rasm ostiga matn (caption) yozib yuboring."
        )


@dp.message(~F.text.startswith("/"))
async def handle_message(m: Message, bot: Bot):
    text = await extract_text(m, bot)
    if not text or not text.strip():
        await m.answer("Iltimos, matn yuboring.")
        return

    text = text.strip()
    if text.startswith("/"):
        return

    user_id = m.from_user.id if m.from_user else (m.sender_chat.id if m.sender_chat else 0)
    username = m.from_user.username if m.from_user else None
    first_name = m.from_user.first_name if m.from_user else None

    # Track user
    if user_id:
        QuotaService.ensure_user(user_id=user_id, username=username, first_name=first_name)

    user_in_support = user_id in ACTIVE_SUPPORT_SESSIONS

    # Check if this is a support query (rules, tariffs, rejection reason, order status, help)
    text_lower = text.lower()
    if user_in_support and text_lower in ["chiqish", "exit", "stop", "tugatish", "tamom", "bekor"]:
        ACTIVE_SUPPORT_SESSIONS.discard(user_id)
        await m.answer(
            "✅ <b>AI Konsyerj sessiyasi yakunlandi.</b>\n\n"
            "Endi matnlaringizni odatiy tarzda transliteratsiya qilishingiz mumkin. "
            "Yana yordam kerak bo'lsa, istalgan vaqt /support buyrug'idan foydalaning!"
        )
        return

    support_triggers = [
        "qanaqa", "qanday", "yordam", "operator", "admin", "tarif", "narx",
        "ö harfi", "ğ harfi", "shikoyat", "nimaga", "nega", "rad", "bekor",
        "so'rov", "sorov", "buyurtma", "tasdiqlanmadi", "chek", "tolov", "to'lov", "pul"
    ]
    is_support_msg = user_in_support or (
        any(t in text_lower for t in support_triggers) and len(text) < 300 and (
            "?" in text or any(t in text_lower for t in [
                "operator", "admin", "tarif", "narx", "rad", "bekor", "so'rov", "sorov", "chek", "tolov", "to'lov", "nimaga", "nega"
            ])
        )
    )

    if is_support_msg:
        session_id = f"tg_{user_id}"
        concierge_res = await ConciergeService.generate_response(
            session_id=session_id,
            message=text,
            user_id=user_id,
            channel="telegram",
        )
        kb = build_concierge_kb(concierge_res.get("suggested_actions"))
        await m.answer(f"🤖 <b>Alifbo AI Konsyerj</b>:\n\n{concierge_res['response']}", reply_markup=kb)

        if concierge_res.get("is_escalated") and ADMIN_ID:
            try:
                user_link = f"https://t.me/{username}" if username else f"tg://user?id={user_id}"
                admin_esc_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💬 Mijozga yozish", url=user_link)]
                ])
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        f"🚨 <b>Yangi Murojaat / Eskalatsiya Chiptasi #{concierge_res.get('ticket_id')}</b>\n\n"
                        f"Foydalanuvchi: {first_name or ''} (@{username or 'yoq'}, ID: <code>{user_id}</code>)\n"
                        f"Savol: <i>{text}</i>\n"
                        f"Sabab: {concierge_res.get('escalation_reason')}\n\n"
                        f"Boshqaruv paneli: <code>http://localhost:8000/admin</code>"
                    ),
                    reply_markup=admin_esc_kb,
                )
            except Exception as e:
                logging.debug(f"Could not notify admin of escalation: {e}")
        return

    if len(text) > MAX_CHARS:
        await m.answer(f"Matn juda uzun (maksimum {MAX_CHARS} belgi). Bo'laklab yuboring.")
        return

    src, results, warns = convert(text)

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?)",
            (int(time.time()), user_id, src, len(text)),
        )
        conn.commit()
    finally:
        conn.close()

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize all database tables and seed data
    init_db()
    logging.info("Alifbo database schema and initial curriculum/tiers verified.")

    if TELEGRAM_API_SERVER:
        logging.info(f"Connecting to Telegram Bot API at {TELEGRAM_API_SERVER}...")
        for attempt in range(15):
            try:
                me = await bot.get_me()
                logging.info(f"Connected to Bot API as @{me.username} (ID: {me.id})")
                break
            except Exception as e:
                logging.info(f"Waiting for Bot API server to be ready (attempt {attempt + 1}/15): {e}")
                await asyncio.sleep(2)

    if WEBHOOK_HOST:
        webhook_url = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
        logging.info(f"Setting Telegram webhook to: {webhook_url}")
        try:
            await bot.set_webhook(
                url=webhook_url,
                secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None,
                drop_pending_updates=True,
                allowed_updates=dp.resolve_used_update_types(),
            )
            logging.info(f"Webhook set successfully: {webhook_url}")
        except Exception as e:
            logging.error(f"Failed to set webhook: {e}")
    else:
        logging.warning("WEBHOOK_HOST is not set! Set WEBHOOK_HOST in .env to register Telegram webhook.")

    yield

    if WEBHOOK_HOST:
        logging.info("Removing Telegram webhook")
        try:
            await bot.delete_webhook()
        except Exception as e:
            logging.warning(f"Error while deleting webhook: {e}")
    await bot.session.close()


app = FastAPI(title="Alifbo Production Suite & Webhook API", lifespan=lifespan)

# Mount static files and API routers
os.makedirs("static/admin", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(admin_router)
app.include_router(chat_router)


@app.get("/")
@app.get("/admin")
@app.get("/admin/")
async def serve_admin_portal():
    """Serve the Alifbo Production Admin Suite SPA."""
    index_path = os.path.join("static", "admin", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "app": "Alifbo Production Suite",
        "concierge": "ready",
        "database": "sqlite_wal",
    }


@app.post(WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> Response:
    if WEBHOOK_SECRET and x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        return Response(status_code=status.HTTP_403_FORBIDDEN, content="Forbidden: invalid secret token")

    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot=bot, update=update)
    return Response(status_code=status.HTTP_200_OK)


if __name__ == "__main__":
    uvicorn.run("bot:app", host=HOST, port=PORT, log_level="info")

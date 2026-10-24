"""Alifbo AI Support Concierge Agent with Gemini, persistent memory, and escalation engine."""
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from app.database import get_connection

logger = logging.getLogger(__name__)

ALIFBO_SYSTEM_PROMPT = """
Sen "Alifbo" ta'lim va matn transliteratsiyasi platformasining rasmiy AI Yordamchi Konsyerjisan (Alifbo Support Concierge).
Sening vazifang - foydalanuvchilarga do'stona, o'ta aniq va xushmuomala tarzda o'zbek tilida yordam berish.

ALIFBO HAQIDA TO'LIQ MA'LUMOTLAR:
1. Asosiy imkoniyat:
   - O'zbek tilidagi matnlarni Kirill, Eski lotin (O', G', Sh, Ch) va Yangi lotin (Ö, Ğ, Ş, Ç) yozuvlari o'rtasida bir zumda o'girib beradi.
   - Rasmlar ostidagi matnlar (caption) va forward qilingan postlar matnlarini ham avtomatik aniqlaydi.
   - .txt va .docx matn fayllarini qabul qiladi.

2. Yangi harflar qoidalari (Ö Ğ Ş Ç):
   - Ö ö: Kirillcha "Ў / ў", eski lotincha "Oʻ / oʻ" o'rniga qo'llanadi (Misol: Ördak, qöl, Özbekiston).
   - Ğ ğ: Kirillcha "Ғ / ғ", eski lotincha "Gʻ / gʻ" o'rniga qo'llanadi (Misol: Ğalaba, boğ, toğ).
   - Ş ş: Kirillcha "Ш / ш", eski lotincha "Sh / sh" o'rniga qo'llanadi (Misol: Şahar, quş, quyöş).
   - Ç ç: Kirillcha "Ч / ч", eski lotincha "Ch / ch" o'rniga qo'llanadi (Misol: Çoy, çiroyli, quvönç).

3. Hamyonbop va real Tariflar:
   - 1. "Oddiy / Bepul": 0 so'm. Barcha hozirgi asosiy imkoniyatlar (20 000 belgigacha bir martalik limit).
   - 2. "Talaba & O'quvchi": 12 000 so'm / oy. Kunlik 100 000 belgi, .docx va .txt fayllarni o'girish, Alifbo ta'lim modullari, 24/7 AI konsyerj.
   - 3. "Muallim & Pro": 25 000 so'm / oy. Kunlik 500 000 belgi (katta kitoblar), interaktiv viktorinalar, CSV/DOCX eksport, ustuvor navbat.
   - 4. "Tashkilot & Nashriyot": 75 000 so'm / oy. Cheksiz paket (2M+ belgi), kitob va hujjat rasmlarini o'girish (OCR), REST API kaliti, shaxsiy admin ko'magi.

ESKALATSIYA QOIDALARI:
- Agar foydalanuvchi inson (operator, admin) bilan gaplashmoqchi bo'lsa, shikoyat qilsa yoki to'lov/hisobda muammoga duch kelsa, bosiqlik bilan murojaat navbatga olinganini va admin tez orada bog'lanishini ayt.
- Hech qachon yolg'on ma'lumot to'qima. Doim Alifbo bilimlari asosida aniq gapir.
"""

FRUSTRATION_KEYWORDS = [
    r"operator", r"admin", r"inson", r"odam bilan", r"shikoyat", r"pulim", r"qaytaring",
    r"ishlamayapti", r"aldov", r"yordam bermayapsiz", r"tushunmayapsan", r"xato", r"yomon"
]


class ConciergeService:
    @staticmethod
    def calculate_frustration(message: str) -> Tuple[float, bool, Optional[str]]:
        """Analyze message sentiment and detect explicit human escalation triggers."""
        msg_lower = message.lower()
        score = 0.0
        reason = None

        for pattern in FRUSTRATION_KEYWORDS:
            if re.search(pattern, msg_lower):
                score += 0.4
                if not reason:
                    reason = f"Foydalanuvchi so'rovi: '{pattern}' kalit so'zi aniqlandi"

        if len(message) > 5 and message.isupper():
            score += 0.3  # ALL CAPS implies shouting

        if "?" in message and ("nega" in msg_lower or "qachon" in msg_lower or "nimaga" in msg_lower):
            score += 0.1

        is_escalated = score >= 0.7 or any(w in msg_lower for w in ["operator", "admin chaqir", "inson bilan", "odam kerak"])
        return min(1.0, score), is_escalated, reason

    @staticmethod
    def get_dialogue_history(session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT role, message, created_at FROM support_dialogues
                WHERE session_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
            return [{"role": r["role"], "message": r["message"]} for r in rows]
        finally:
            conn.close()

    @staticmethod
    def save_dialogue_turn(
        session_id: str,
        user_id: Optional[int],
        channel: str,
        role: str,
        message: str,
        frustration_score: float = 0.0,
        is_escalated: bool = False,
    ) -> None:
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO support_dialogues (session_id, user_id, channel, role, message, frustration_score, is_escalated, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    channel,
                    role,
                    message,
                    frustration_score,
                    1 if is_escalated else 0,
                    int(time.time()),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def create_support_ticket(
        session_id: str,
        user_id: Optional[int],
        subject: str,
        reason: str,
        priority: str = "normal",
    ) -> int:
        conn = get_connection()
        try:
            now = int(time.time())
            cur = conn.execute(
                """
                INSERT INTO support_tickets (user_id, session_id, subject, status, priority, escalated_reason, created_at, updated_at)
                VALUES (?, ?, ?, 'open', ?, ?, ?, ?)
                """,
                (user_id, session_id, subject, priority, reason, now, now),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    @staticmethod
    def get_user_context(user_id: Optional[int], message: str = "") -> Dict[str, Any]:
        """Fetch real-time user profile, latest purchase requests, and support status."""
        if not user_id:
            return {}
        conn = get_connection()
        try:
            user_row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

            # Check if specific order ID is mentioned in the message (#ORD-2, #ALF-2, ORD-2, ALF-2, #2)
            specific_order = None
            order_id_match = re.search(r"(?:#?alf-|#?ord-)?#?(\d+)", message, re.IGNORECASE)
            if order_id_match:
                try:
                    target_id = int(order_id_match.group(1))
                    specific_order = conn.execute(
                        "SELECT * FROM purchase_requests WHERE id = ? AND (user_id = ? OR ? IS NULL)",
                        (target_id, user_id, user_id),
                    ).fetchone()
                except Exception:
                    pass

            latest_order = specific_order or conn.execute(
                "SELECT * FROM purchase_requests WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()

            recent_ticket = conn.execute(
                "SELECT * FROM support_tickets WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()

            return {
                "user": dict(user_row) if user_row else None,
                "latest_order": dict(latest_order) if latest_order else None,
                "recent_ticket": dict(recent_ticket) if recent_ticket else None,
            }
        finally:
            conn.close()

    @staticmethod
    async def generate_response(
        session_id: str,
        message: str,
        user_id: Optional[int] = None,
        channel: str = "web",
    ) -> Dict[str, Any]:
        """Generate response via Gemini or intelligent grounded Alifbo fallback with full user context."""
        frustration_score, is_escalated, escalation_reason = ConciergeService.calculate_frustration(message)

        # 1. Fetch user context & recent orders from database
        user_ctx = ConciergeService.get_user_context(user_id, message)
        latest_order = user_ctx.get("latest_order")
        user_profile = user_ctx.get("user")

        msg_lower = message.lower()

        # Check for order / rejection / purchase status inquiry
        is_order_inquiry = any(
            w in msg_lower
            for w in [
                "rad", "bekor", "so'rov", "sorov", "buyurtma", "tasdiqlanmadi",
                "rad etildi", "nega rad", "nimaga rad", "qani", "nima bo'ldi",
                "nima boldi", "holat", "qachon yoqiladi", "faollashmadi",
                "tolovim", "to'lovim", "hisobim", "obunam", "ochilmadi"
            ]
        ) or any(prefix in msg_lower for prefix in ["#alf-", "#ord-", "alf-", "ord-"]) or (
            latest_order is not None and any(w in msg_lower for w in ["nega", "nimaga", "sabab", "qachon", "qachongacha", "nima uchun"])
        )

        is_receipt_submission = any(
            w in msg_lower
            for w in [
                "chek", "check", "to'lov qildim", "tolov qildim", "to'ladim", "toladim",
                "skrinshot", "kvitansiya", "pul tashladim", "pul o'tkazdim", "otkazdim"
            ]
        )

        if is_order_inquiry and latest_order and latest_order["status"] == "rejected":
            is_escalated = True
            escalation_reason = f"Mijoz rad etilgan #{latest_order['id']} buyurtmasi sababini suradi"

        # 2. Save user message to persistent dialogue memory
        ConciergeService.save_dialogue_turn(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            role="user",
            message=message,
            frustration_score=frustration_score,
            is_escalated=is_escalated,
        )

        ticket_id = None
        if is_escalated:
            ticket_id = ConciergeService.create_support_ticket(
                session_id=session_id,
                user_id=user_id,
                subject=f"Eskalatsiya: {message[:50]}...",
                reason=escalation_reason or "Inson operatori talab qilindi",
                priority="high" if frustration_score >= 0.7 else "normal",
            )

        # 3. Try Gemini API first if configured, passing real user and order context
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        reply_text = None

        if gemini_api_key:
            try:
                from google import genai
                client = genai.Client(api_key=gemini_api_key)

                history = ConciergeService.get_dialogue_history(session_id, limit=6)
                contents = []
                for turn in history[:-1]:  # Exclude the one just saved
                    contents.append(f"{turn['role'].capitalize()}: {turn['message']}")
                contents.append(f"User: {message}")

                user_context_str = f"MIJOZ REAL HOLATI:\n- ID: {user_id}\n- Ism: {user_profile.get('first_name', 'Mijoz') if user_profile else 'Mijoz'}\n- Joriy tarifi: {user_profile.get('tier', 'free') if user_profile else 'free'}\n"
                if latest_order:
                    user_context_str += (
                        f"- OXIRGI BUYURTMA: ID=#ALF-{latest_order['id']}, Tarif={latest_order['tier_name']}, "
                        f"Holat={latest_order['status']}, Sabab/Izoh={latest_order.get('notes') or 'Korsatilmagan'}, "
                        f"Vaqti={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(latest_order['created_at']))}\n"
                    )

                prompt_input = f"{ALIFBO_SYSTEM_PROMPT}\n\n{user_context_str}\n\nSuhbat tarixi:\n" + "\n".join(contents) + "\n\nAssistant javobi:"

                resp = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt_input,
                )
                if resp and resp.text:
                    reply_text = resp.text.strip()
            except Exception as e:
                logger.warning(f"Gemini API invocation error, switching to grounded fallback: {e}")

        # 4. Context-Aware Grounded Fallback (Deterministic & Accurate)
        suggested_actions: List[Dict[str, str]] = []

        if not reply_text:
            if is_order_inquiry:
                if latest_order:
                    ord_id = latest_order["id"]
                    tier_name = latest_order["tier_name"]
                    ord_status = latest_order["status"]
                    tier_id = latest_order.get("tier_id", "pro")
                    price_uzs = latest_order.get("price_uzs", 0)
                    reason = latest_order.get("notes") or "Administrator tomonidan to'lov cheki yoki ma'lumotlar tasdiqlanmagan"
                    date_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(latest_order["created_at"]))

                    if ord_status == "rejected":
                        reply_text = (
                            f"Hurmatli mijoz, sizning <b>#ALF-{ord_id}</b> raqamli <b>{tier_name}</b> ({price_uzs:,} so'm/oy) tarifi uchun xarid so'rovingiz ko'rib chiqilgan va <b>rad etilgan</b>.\n\n"
                            f"📝 <b>Qayd etilgan sabab:</b> <i>{reason}</i>\n"
                            f"🕒 <b>Ko'rib chiqilgan vaqti:</b> {date_str}\n\n"
                            "💡 <b>Nima uchun bunday bo'ladi?</b>\n"
                            "Odatda buyurtmalar quyidagi sabablarga ko'ra rad etiladi:\n"
                            "1. To'lov amalga oshirilgach, to'lov cheki (kvitansiya) administratorga taqdim etilmagan.\n"
                            "2. To'lov summasi to'liq tushmagan yoki to'lovchi ma'lumotlari mos kelmagan.\n\n"
                            "🚀 <b>Muammoni qanday hal qilish mumkin?</b>\n"
                            "• <b>To'lov qilgan bo'lsangiz:</b> Payme, Click, Uzum yoki bank cheki skrinshotini to'g'ridan-to'g'ri shu yerga <b>rasm (photo)</b> ko'rinishida yuboring! Men uni darhol adminga yetkazaman va tarifingiz yoqiladi.\n"
                            "• <b>Qayta so'rov qoldirish uchun:</b> /tariflar buyrug'ini bosing.\n"
                            "• <b>Admin bilan bog'lanish:</b> «Operator kerak» tugmasi orqali tezkor aloqaga chiqing."
                        )
                        suggested_actions = [
                            {"text": "💳 To'lov rekvizitlari", "callback_data": f"pay_details:{tier_id}"},
                            {"text": "🚀 Boshqa tarif tanlash", "callback_data": "show_tariffs"},
                            {"text": "👨‍💼 Operator kerak", "callback_data": "support_call_admin"},
                            {"text": "❌ Chiqish", "callback_data": "support_exit"},
                        ]
                    elif ord_status == "pending":
                        reply_text = (
                            f"Sizning <b>#ALF-{ord_id}</b> raqamli <b>{tier_name}</b> tarifi uchun so'rovingiz ayni damda ⏳ <b>Ko'rib chiqilmoqda (Kutilmoqda)</b> holatida.\n\n"
                            "Administratorimiz to'lov ma'lumotlarini tekshirishi bilanoq profilingiz darhol yangi tarifga o'tkaziladi. "
                            "Jarayonni tezlashtirish uchun to'lov cheki skrinshotini shu yerga rasm sifatida yuboring!"
                        )
                        suggested_actions = [
                            {"text": "💳 To'lov rekvizitlari", "callback_data": f"pay_details:{tier_id}"},
                            {"text": "👨‍💼 Operator kerak", "callback_data": "support_call_admin"},
                            {"text": "❌ Chiqish", "callback_data": "support_exit"},
                        ]
                    else:  # approved
                        reply_text = (
                            f"Sizning <b>#ALF-{ord_id}</b> raqamli <b>{tier_name}</b> tarifi uchun xarid buyurtmangiz muvaffaqiyatli tasdiqlangan va profilingizga biriktirilgan!\n\n"
                            "Kengaytirilgan imkoniyatlardan to'liq foydalanishingiz mumkin. Savolingiz bo'lsa bajonidil yordam beraman!"
                        )
                        suggested_actions = [
                            {"text": "🚀 Tariflar", "callback_data": "show_tariffs"},
                            {"text": "❌ Chiqish", "callback_data": "support_exit"},
                        ]
                else:
                    reply_text = (
                        "Sizning hisobingiz bo'yicha hali faol xarid buyurtmasi topilmadi.\n\n"
                        "Agar yangi tarif xarid qilmoqchi bo'lsangiz, /tariflar buyrug'i orqali o'zingizga ma'qul tarifni tanlashingiz mumkin. "
                        "Agar to'lov qilgan bo'lsangiz, chek skrinshotini shu yerga yuboring, men uni adminga yetkazaman!"
                    )
                    suggested_actions = [
                        {"text": "🚀 Tariflarni ko'rish", "callback_data": "show_tariffs"},
                        {"text": "👨‍💼 Operator kerak", "callback_data": "support_call_admin"},
                        {"text": "❌ Chiqish", "callback_data": "support_exit"},
                    ]
            elif is_receipt_submission:
                reply_text = (
                    "Rahmat! Sizning to'lov cheki/ma'lumotingiz qabul qilindi va zudlik bilan administratorimizga yetkazildi. "
                    "Mas'ul xodimimiz chekni tekshirib, tez orada tarifingizni faollashtiradi!"
                )
                suggested_actions = [
                    {"text": "📋 Buyurtmam holati", "callback_data": "support_check_order"},
                    {"text": "👨‍💼 Operator kerak", "callback_data": "support_call_admin"},
                    {"text": "❌ Chiqish", "callback_data": "support_exit"},
                ]
            elif any(w in msg_lower for w in ["operator", "admin chaqir", "inson kerak", "odam kerak", "shikoyat"]):
                reply_text = (
                    f"Hurmatli foydalanuvchi, sizning murojaatingiz #{ticket_id or 'qabul'} raqami bilan navbatga olindi "
                    "va bosh ma'muriyatimizga yetkazildi. Tez orada operatorimiz siz bilan bog'lanadi. "
                    "Keltirilgan noqulaylik uchun uzr so'raymiz."
                )
                suggested_actions = [
                    {"text": "📋 Buyurtmam holati", "callback_data": "support_check_order"},
                    {"text": "❌ Suhbatni yakunlash", "callback_data": "support_exit"},
                ]
            elif any(w in msg_lower for w in ["qanday tarif", "tariflar qanaqa", "narxlar qancha", "obuna qancha", "barcha tariflar", "tariflar ro'yxati", "qaysi tarif"]):
                reply_text = (
                    "Alifbo platformasida hozirda 4 ta hamyonbop tarif mavjud:\n\n"
                    "1. <b>Oddiy / Bepul</b>: 0 so'm (20 000 belgigacha bepul transliteratsiya).\n"
                    "2. <b>Talaba & O'quvchi</b>: 12 000 so'm/oy (Kunlik 100K belgi, .docx/.txt fayllar, ta'lim modullari).\n"
                    "3. <b>Muallim & Pro</b>: 25 000 so'm/oy (Kunlik 500K belgi, viktorinalar, CSV/DOCX eksport, ustuvor navbat).\n"
                    "4. <b>Tashkilot & Nashriyot</b>: 75 000 so'm/oy (Cheksiz 2M+ belgi, OCR, REST API kalit).\n\n"
                    "Batafsil ko'rish va obunani boshlash uchun /tariflar buyrug'ini yuborishingiz mumkin!"
                )
                suggested_actions = [
                    {"text": "🚀 Tariflarni ochish", "callback_data": "show_tariffs"},
                    {"text": "📋 Buyurtmam holati", "callback_data": "support_check_order"},
                    {"text": "❌ Chiqish", "callback_data": "support_exit"},
                ]
            elif any(w in msg_lower for w in ["harf", "ö", "ğ", "ş", "ç", "qoida"]):
                reply_text = (
                    "Yangi o'zbek lotin alifbosidagi 4 ta asosiy yangi harf:\n\n"
                    "• <b>Ö ö</b> — Eski «Oʻ/oʻ» va Kirill «Ў/ў» o'rniga (Masalan: <i>Ördak, qöl, Özbekiston</i>)\n"
                    "• <b>Ğ ğ</b> — Eski «Gʻ/gʻ» va Kirill «Ғ/ғ» o'rniga (Masalan: <i>Ğalaba, toğ</i>)\n"
                    "• <b>Ş ş</b> — Eski «Sh/sh» va Kirill «Ш/ш» o'rniga (Masalan: <i>Şahar, quş</i>)\n"
                    "• <b>Ç ç</b> — Eski «Ch/ch» va Kirill «Ч/ч» o'rniga (Masalan: <i>Çoy, çiroyli</i>)\n\n"
                    "Ushbu harflar tutuq belgilari chalkashligini bartaraf etadi va xalqaro turkiy standartga mos keladi."
                )
                suggested_actions = [
                    {"text": "🚀 Tariflar", "callback_data": "show_tariffs"},
                    {"text": "❌ Chiqish", "callback_data": "support_exit"},
                ]
            elif any(w in msg_lower for w in ["salom", "assalomu", "qalesiz", "start"]):
                reply_text = (
                    "Assalomu alaykum! Men Alifbo AI Yordamchisiman. "
                    "Yangi lotin yozuvi (Ö Ğ Ş Ç) qoidalari, matn o'girish, tariflar yoki platforma imkoniyatlari "
                    "bo'yicha barcha savollaringizga mamnuniyat bilan javob beraman!"
                )
                suggested_actions = [
                    {"text": "📋 Buyurtmam holati", "callback_data": "support_check_order"},
                    {"text": "💳 To'lov rekvizitlari", "callback_data": "support_pay_card"},
                    {"text": "🚀 Tariflar", "callback_data": "show_tariffs"},
                    {"text": "❌ Chiqish", "callback_data": "support_exit"},
                ]
            else:
                reply_text = (
                    "Alifbo platformasi orqali matnlaringizni Kirill, Eski lotin va Yangi lotin (Ö Ğ Ş Ç) yozuvlariga o'girishingiz mumkin. "
                    "Menga matn yuborishingiz yoki yangi alifbo qoidalari, tariflar bo'yicha savol berishingiz mumkin. "
                    "Agar inson yordami kerak bo'lsa, 'Operator kerak' deb yozsangiz adminlarimiz bilan bog'layman."
                )
                suggested_actions = [
                    {"text": "📋 Buyurtmam holati", "callback_data": "support_check_order"},
                    {"text": "💳 To'lov rekvizitlari", "callback_data": "support_pay_card"},
                    {"text": "👨‍💼 Operator kerak", "callback_data": "support_call_admin"},
                    {"text": "❌ Chiqish", "callback_data": "support_exit"},
                ]

        # 4. Save assistant response into dialogue history
        ConciergeService.save_dialogue_turn(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            role="assistant",
            message=reply_text,
            frustration_score=frustration_score,
            is_escalated=is_escalated,
        )

        return {
            "response": reply_text,
            "session_id": session_id,
            "is_escalated": is_escalated,
            "ticket_id": ticket_id,
            "escalation_reason": escalation_reason,
            "suggested_actions": suggested_actions,
        }

    @staticmethod
    def get_tickets(status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            if status_filter and status_filter != "all":
                rows = conn.execute(
                    "SELECT * FROM support_tickets WHERE status = ? ORDER BY created_at DESC",
                    (status_filter,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM support_tickets ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def update_ticket(ticket_id: int, status: str, assigned_to: Optional[str] = None) -> bool:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE support_tickets SET status = ?, assigned_to = COALESCE(?, assigned_to), updated_at = ? WHERE id = ?",
                (status, assigned_to, int(time.time()), ticket_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

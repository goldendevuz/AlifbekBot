"""Database initialization and connection management for Alifbo platform."""
import json
import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def get_db_path() -> str:
    db_path = os.getenv("DB_PATH", "stats.db")
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    return db_path


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    """Initialize all tables and pre-populate essential default data."""
    conn = get_connection()
    try:
        # 1. Existing events table for raw conversion telemetry
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                ts INTEGER,
                user_id INTEGER,
                src TEXT,
                chars INTEGER
            )
        """)

        # 2. Users table with quota, tier, and role management
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                role TEXT DEFAULT 'user',
                tier TEXT DEFAULT 'free',
                credits_balance INTEGER DEFAULT 20000,
                unlimited_quota INTEGER DEFAULT 0,
                is_blocked INTEGER DEFAULT 0,
                created_at INTEGER,
                last_active_at INTEGER
            )
        """)

        # 3. Tiers & Pricing Plans
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tiers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price_uzs INTEGER NOT NULL,
                billing_period TEXT NOT NULL,
                daily_char_limit INTEGER NOT NULL,
                single_request_limit INTEGER NOT NULL,
                features TEXT NOT NULL,
                badge TEXT NOT NULL
            )
        """)

        # 4. Curriculum Modules (Alifbo Core)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS curriculum_modules (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                level TEXT DEFAULT 'beginner',
                order_num INTEGER DEFAULT 1,
                is_published INTEGER DEFAULT 1
            )
        """)

        # 5. Curriculum Lessons & Letters
        conn.execute("""
            CREATE TABLE IF NOT EXISTS curriculum_lessons (
                id TEXT PRIMARY KEY,
                module_id TEXT NOT NULL,
                title TEXT NOT NULL,
                letter_char TEXT,
                phonetic_guide TEXT,
                audio_url TEXT,
                cyrillic_equiv TEXT,
                old_latin_equiv TEXT,
                rules_content TEXT,
                quiz_data TEXT,
                order_num INTEGER DEFAULT 1,
                FOREIGN KEY (module_id) REFERENCES curriculum_modules(id) ON DELETE CASCADE
            )
        """)

        # 6. Support Dialogues (Persistent Memory)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS support_dialogues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_id INTEGER,
                channel TEXT DEFAULT 'web',
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                frustration_score REAL DEFAULT 0.0,
                is_escalated INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            )
        """)

        # 7. Support Tickets (Escalated to human admins)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                session_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                priority TEXT DEFAULT 'normal',
                escalated_reason TEXT,
                assigned_to TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)

        # 8. Audit Logs (Audit Trail & 1-Click Rollback)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                details TEXT,
                rollback_payload TEXT,
                is_rolled_back INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            )
        """)

        # 9. Announcements / Broadcasts
        conn.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                target_tier TEXT DEFAULT 'all',
                sent_by TEXT NOT NULL,
                recipient_count INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            )
        """)

        # 10. Purchase Requests (Tariff Order Submissions & Approvals)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS purchase_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                tier_id TEXT NOT NULL,
                tier_name TEXT NOT NULL,
                price_uzs INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                handled_by TEXT,
                notes TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_purchase_requests_user ON purchase_requests(user_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_purchase_requests_status ON purchase_requests(status);")

        conn.commit()

        # Seed realistic pricing tiers if not already present
        seed_tiers(conn)
        seed_curriculum(conn)

    except Exception as e:
        logger.error(f"Error during database initialization: {e}")
        raise
    finally:
        conn.close()


def seed_tiers(conn: sqlite3.Connection) -> None:
    """Seed real, accessible Uzbek pricing tiers into database."""
    count = conn.execute("SELECT COUNT(*) FROM tiers").fetchone()[0]
    if count == 0:
        tiers_data = [
            (
                "free",
                "Oddiy / Bepul",
                0,
                "forever",
                20000,
                20000,
                json.dumps([
                    "Kirill ↔ Eski Lotin ↔ Yangi Lotin (Ö Ğ Ş Ç)",
                    "Maksimal 20 000 belgi / so'rov",
                    "Rasm osti va kanaldan forward xabarlarni o'girish",
                    "Asosiy transliteratsiya tezligi"
                ]),
                "STANDART"
            ),
            (
                "student",
                "Talaba & O'quvchi",
                12000,
                "monthly",
                100000,
                50000,
                json.dumps([
                    "Kunlik 100 000 belgi hajmi",
                    ".docx va .txt hujjatlarni to'liq o'girish",
                    "Alifbo ta'lim modullari va harflar qoidalari",
                    "24/7 AI Support Concierge yordamchisi",
                    "Arzon va qulay oylik obuna"
                ]),
                "OMMABOP"
            ),
            (
                "pro",
                "Muallim & Pro",
                25000,
                "monthly",
                500000,
                150000,
                json.dumps([
                    "Kunlik 500 000 belgi (katta kitob va darsliklar)",
                    "Interaktiv Alifbo viktorinalari va testlari",
                    "Natijalarni toza formatda CSV / DOCX yuklash",
                    "Ustuvor navbat va tezyurar konvertatsiya",
                    "AI xatolik tahlili va murakkab imlo tushuntirishlari"
                ]),
                "TAVSIYA ETILADI"
            ),
            (
                "business",
                "Tashkilot & Nashriyot",
                75000,
                "monthly",
                2000000,
                500000,
                json.dumps([
                    "Cheksiz oylik paket (2M+ belgilar)",
                    "Rasmlar va kitob sahifalaridan matnni ajratish (OCR)",
                    "Tashqi sayt va ilovalarga ulash uchun REST API kalit",
                    "Jamoaviy boshqaruv va hisobotlar",
                    "24/7 VIP shaxsiy admin konsyerji"
                ]),
                "BIZNES"
            )
        ]
        conn.executemany("""
            INSERT OR REPLACE INTO tiers 
            (id, name, price_uzs, billing_period, daily_char_limit, single_request_limit, features, badge)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, tiers_data)
        conn.commit()


def seed_curriculum(conn: sqlite3.Connection) -> None:
    """Seed official Alifbo curriculum modules and lessons."""
    count = conn.execute("SELECT COUNT(*) FROM curriculum_modules").fetchone()[0]
    if count == 0:
        modules = [
            ("mod_basics", "Yangi Alifbo Asoslari (Ö Ğ Ş Ç)", "O'zbek tilining yangilangan lotin alifbosi harflari va to'g'ri yozish qoidalari", "beginner", 1, 1),
            ("mod_practice", "Imlo va Matn O'girish Qoidalari", "Kirill va lotin yozuvidagi murakkab holatlar (e/ye, ts, s) va rasmiy uslub", "intermediate", 2, 1),
            ("mod_expert", "Muharrirlar va Nashriyotlar Uchun", "Katta hajmli matnlar, kitoblar va rasmiy hujjatlar bilan ishlash standarti", "advanced", 3, 1),
        ]
        conn.executemany("""
            INSERT OR REPLACE INTO curriculum_modules (id, title, description, level, order_num, is_published)
            VALUES (?, ?, ?, ?, ?, ?)
        """, modules)

        lessons = [
            (
                "les_o_umlaut",
                "mod_basics",
                "Ö ö harfi (O'zbek alifbosining 29-harfi)",
                "Ö",
                "Lablangan, til oldi, o'rta-keng unli tovush. Eski 'Oʻ / oʻ' o'rniga qo'llanadi.",
                "/static/audio/o_sound.mp3",
                "Ў, ў",
                "Oʻ, oʻ",
                "Yangi lotin alifbosida o'zbek tilidagi 'oʻ' tovushi bitta yaxlit 'Ö ö' harfi orqali ifodalanadi. Misollar: Ördak (o'rdak), qöl (qo'l), gözal (go'zal). Bu belgi apostrof bilan yozishdagi barcha texnik xatoliklarni bartaraf etadi.",
                json.dumps({
                    "question": "'Oʻzbekiston' so'zi yangi lotin alifbosida qanday yoziladi?",
                    "options": ["Ozbekiston", "Özbekiston", "O'zbekiston", "Uzbekistan"],
                    "answer": 1
                }),
                1
            ),
            (
                "les_g_breve",
                "mod_basics",
                "Ğ ğ harfi (Yumshoq jarangli undosh)",
                "Ğ",
                "Chuqur til orqa, sirg'aluvchi jarangli undosh tovush. Eski 'Gʻ / gʻ' o'rniga qo'llanadi.",
                "/static/audio/g_sound.mp3",
                "Ғ, ғ",
                "Gʻ, gʻ",
                "Yangi lotin yozuvida tutuq belgili 'Gʻ' harfi o'rniga 'Ğ ğ' kiritilgan. Misollar: Ğalaba (g'alaba), boğ (bog'), toğ (tog'). Matn terishda qulay va xalqaro turkiy standartga mos keladi.",
                json.dumps({
                    "question": "'G'alaba' so'zi qaysi variantda to'g'ri yozilgan?",
                    "options": ["Galaba", "Ğalaba", "Ghabala", "G'alaba"],
                    "answer": 1
                }),
                2
            ),
            (
                "les_sh_cedilla",
                "mod_basics",
                "Ş ş harfi (Jarangiz sirg'aluvchi undosh)",
                "Ş",
                "Til oldi, tanglay sirg'aluvchi shovqinli undosh. Eski 'Sh / sh' digrafi o'rniga qo'llanadi.",
                "/static/audio/sh_sound.mp3",
                "Ш, ш",
                "Sh, sh",
                "Ikkita harfdan iborat 'Sh' digrafi o'rniga bir dona yaxlit 'Ş ş' harfi qabul qilingan. Bu harflar chalkashligini (masalan, s va h alohida o'qilishi: Is-hoq) yo'qotadi. Misollar: Şahar (shahar), quş (qush).",
                json.dumps({
                    "question": "'Shahar' so'zining to'g'ri yozilishini toping:",
                    "options": ["Sahar", "Şahar", "Shahar", "Shaxar"],
                    "answer": 1
                }),
                3
            ),
            (
                "les_ch_cedilla",
                "mod_basics",
                "Ç ç harfi (Jarangiz qorishiq undosh)",
                "Ç",
                "Til oldi, tanglay qorishiq (affrikata) undosh tovush. Eski 'Ch / ch' o'rniga qo'llanadi.",
                "/static/audio/ch_sound.mp3",
                "Ч, ч",
                "Ch, ch",
                "Eski ikki harfli 'Ch' o'rniga ixcham 'Ç ç' belgisi kiritilgan. Misollar: Çoy (choy), çiroyli (chiroyli), quvönç (quvonch).",
                json.dumps({
                    "question": "'Chaqmoq' so'zi yangi alifboda qanday yoziladi?",
                    "options": ["Chaqmoq", "Çaqmoq", "Cakmok", "Sakmoq"],
                    "answer": 1
                }),
                4
            ),
            (
                "les_complex_rules",
                "mod_practice",
                "Kirill «Е/е» va «Ц/ц» harflarini o'girish nozikliklari",
                "E / Ts",
                "So'z boshida yoki unlidan keyin 'ye', undoshdan keyin 'e'.",
                "",
                "Е, е / Ц, ц",
                "E, e / Ye, ye",
                "Kirillcha «е» so'z boshida va unlilardan keyin «ye» tarzida o'giriladi (masalan, «Ер» → «Yer», «Daryo» so'zidagi kabi). Undoshdan keyin esa «e» bo'ladi («Керак» → «Kerak»). «Ц» harfi esa o'zbekcha so'zlarda «s» («konstitutsiya»), ayrim xalqaro atamalarda esa «ts» sifatida qo'llanadi.",
                json.dumps({
                    "question": "«Етакчи» so'zi lotin yozuviga qanday o'giriladi?",
                    "options": ["Etakçi", "Yetakçi", "Yetakchi", "Ietakchi"],
                    "answer": 1
                }),
                5
            )
        ]
        conn.executemany("""
            INSERT OR REPLACE INTO curriculum_lessons 
            (id, module_id, title, letter_char, phonetic_guide, audio_url, cyrillic_equiv, old_latin_equiv, rules_content, quiz_data, order_num)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, lessons)
        conn.commit()

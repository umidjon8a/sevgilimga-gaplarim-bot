"""
@sevgilimga_gaplarim kanal boti
Funksiyalar:
- Taklif va shikoyatlar qabul qilish
- Anonim yoki ochiq yuborish
- Referal tizimi (kim nechta obunachi taklif qildi)
- Top tavsiyachilar reytingi
- Admin panel (statistika, broadcast, ko'rib chiqish)
- Foydalanuvchi statistikasi
- Kunlik eslatmalar va aktiv foydalanuvchi tizimi

O'rnatish:
    pip install aiogram aiosqlite

Ishga tushirish:
    python sevgilimga_gaplarim_bot.py
"""

import asyncio
import aiosqlite
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# ===================== SOZLAMALAR =====================
TOKEN = "8859689988:AAEgk5Bk8KhrL8bnoHC0i8hYr1JIWeg9spM"           # BotFather dan olgan tokenni shu yerga yozing
ADMIN_IDS = [8859689988]             # O'z Telegram ID ingizni yozing (https://t.me/userinfobot dan olsa bo'ladi)
CHANNEL_USERNAME = "@sevgilimga_gaplarim"
DB_PATH = "bot.db"
# ======================================================


# =================== MA'LUMOTLAR BAZASI ====================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                full_name   TEXT,
                referrals   INTEGER DEFAULT 0,
                join_date   TEXT,
                ref_by      INTEGER,
                is_blocked  INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS suggestions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER,
                stype        TEXT,
                text         TEXT,
                status       TEXT DEFAULT 'pending',
                date         TEXT,
                is_anonymous INTEGER DEFAULT 0,
                admin_note   TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                suggestion_id INTEGER,
                user_id       INTEGER,
                vote          INTEGER,
                PRIMARY KEY (suggestion_id, user_id)
            )
        """)
        await db.commit()


async def db_get_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            return await cur.fetchone()


async def db_add_user(user_id, username, full_name, ref_by=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name, join_date, ref_by) VALUES (?,?,?,?,?)",
            (user_id, username or "", full_name, now(), ref_by)
        )
        if ref_by:
            await db.execute(
                "UPDATE users SET referrals = referrals + 1 WHERE user_id = ?", (ref_by,)
            )
        await db.commit()


async def db_add_suggestion(user_id, stype, text, is_anonymous=0):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO suggestions (user_id, stype, text, date, is_anonymous) VALUES (?,?,?,?,?)",
            (user_id, stype, text, now(), is_anonymous)
        )
        await db.commit()
        return cur.lastrowid


async def db_update_status(suggestion_id, status, admin_note=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE suggestions SET status=?, admin_note=? WHERE id=?",
            (status, admin_note, suggestion_id)
        )
        await db.commit()


async def db_get_suggestion(suggestion_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM suggestions WHERE id=?", (suggestion_id,)) as cur:
            return await cur.fetchone()


async def db_user_stats(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT referrals FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            referrals = row[0] if row else 0
        async with db.execute(
            "SELECT stype, COUNT(*) FROM suggestions WHERE user_id=? GROUP BY stype", (user_id,)
        ) as cur:
            counts = {r[0]: r[1] for r in await cur.fetchall()}
    return {
        "referrals": referrals,
        "taklif": counts.get("taklif", 0),
        "shikoyat": counts.get("shikoyat", 0),
    }


async def db_top_referrers(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, username, full_name, referrals FROM users ORDER BY referrals DESC LIMIT ?",
            (limit,)
        ) as cur:
            return await cur.fetchall()


async def db_my_suggestions(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, stype, text, status, date FROM suggestions WHERE user_id=? ORDER BY date DESC LIMIT 10",
            (user_id,)
        ) as cur:
            return await cur.fetchall()


async def db_global_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            users = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM suggestions WHERE stype='taklif'") as cur:
            takliflar = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM suggestions WHERE stype='shikoyat'") as cur:
            shikoyatlar = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM suggestions WHERE status='pending'") as cur:
            pending = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_blocked=0") as cur:
            active = (await cur.fetchone())[0]
    return {
        "users": users, "active": active,
        "takliflar": takliflar, "shikoyatlar": shikoyatlar, "pending": pending
    }


async def db_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE is_blocked=0") as cur:
            return [r[0] for r in await cur.fetchall()]


async def db_vote(suggestion_id, user_id, vote):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO votes (suggestion_id, user_id, vote) VALUES (?,?,?)",
                (suggestion_id, user_id, vote)
            )
            await db.commit()
            return True
        except Exception:
            return False  # Allaqachon ovoz bergan


async def db_vote_counts(suggestion_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT SUM(CASE WHEN vote=1 THEN 1 ELSE 0 END), SUM(CASE WHEN vote=0 THEN 1 ELSE 0 END) FROM votes WHERE suggestion_id=?",
            (suggestion_id,)
        ) as cur:
            row = await cur.fetchone()
            return (row[0] or 0, row[1] or 0)


# =================== YORDAMCHI FUNKSIYALAR ====================
def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def main_keyboard(is_admin=False):
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="💡 Taklif yozish"))
    b.add(KeyboardButton(text="📢 Shikoyat yozish"))
    b.add(KeyboardButton(text="📊 Mening statistikam"))
    b.add(KeyboardButton(text="🏆 Top tavsiyachilar"))
    b.add(KeyboardButton(text="🔗 Referal havolam"))
    b.add(KeyboardButton(text="📋 Takliflarim tarixi"))
    if is_admin:
        b.add(KeyboardButton(text="⚙️ Admin panel"))
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)


def anon_keyboard():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="👤 Ismim bilan", callback_data="send_named"))
    b.add(InlineKeyboardButton(text="🎭 Anonim", callback_data="send_anon"))
    b.adjust(2)
    return b.as_markup()


def action_keyboard(sid, uid):
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="✅ Qabul", callback_data=f"approve_{sid}_{uid}"))
    b.add(InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_{sid}_{uid}"))
    b.add(InlineKeyboardButton(text="📊 Ovozlar", callback_data=f"votes_{sid}"))
    b.adjust(2, 1)
    return b.as_markup()


def vote_keyboard(sid):
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="👍 Qo'llayman", callback_data=f"vote_up_{sid}"))
    b.add(InlineKeyboardButton(text="👎 Qo'llamayman", callback_data=f"vote_down_{sid}"))
    b.adjust(2)
    return b.as_markup()


STATUS_LABELS = {
    "pending": "⏳ Kutilmoqda",
    "approved": "✅ Qabul qilindi",
    "rejected": "❌ Rad etildi"
}
MEDALS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


# =================== STATE ====================
class Form(StatesGroup):
    text = State()
    anon = State()


# =================== BOT & DISPATCHER ====================
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# =================== HANDLERLAR ====================

@dp.message(CommandStart())
async def cmd_start(msg: types.Message):
    uid = msg.from_user.id
    uname = msg.from_user.username
    fname = msg.from_user.full_name

    ref_by = None
    parts = msg.text.split()
    if len(parts) > 1:
        try:
            ref_by = int(parts[1])
            if ref_by == uid:
                ref_by = None
        except ValueError:
            pass

    existing = await db_get_user(uid)
    if not existing:
        await db_add_user(uid, uname, fname, ref_by)
        if ref_by:
            try:
                await bot.send_message(
                    ref_by,
                    "🎉 Siz tavsiya qilgan yangi foydalanuvchi botga qo'shildi!\n"
                    "Statistikangizga +1 qo'shildi."
                )
            except Exception:
                pass

    is_admin = uid in ADMIN_IDS
    await msg.answer(
        f"Assalomu alaykum, *{fname}*! 🌹\n\n"
        f"*{CHANNEL_USERNAME}* kanalining rasmiy botiga xush kelibsiz!\n\n"
        "Bu bot orqali siz:\n"
        "💡 Kanal uchun taklif yuborishingiz\n"
        "📢 Shikoyat bildira olishingiz\n"
        "🏆 Eng faol tavsiyachilar reytingini ko'rishingiz\n"
        "🔗 Do'stlarni taklif qilib reyting to'plashingiz mumkin\n\n"
        "Quyidagi tugmani tanlang:",
        parse_mode="Markdown",
        reply_markup=main_keyboard(is_admin)
    )


# --- TAKLIF ---
@dp.message(F.text == "💡 Taklif yozish")
async def taklif_start(msg: types.Message, state: FSMContext):
    await state.set_data({"stype": "taklif"})
    await state.set_state(Form.text)
    await msg.answer(
        "💡 *Taklifingizni yozing:*\n\n"
        "Kanal uchun qanday g'oya yoki taklifingiz bor?\n"
        "Iloji boricha batafsil yozing — bu taklifingiz ko'rib chiqilishiga yordam beradi.",
        parse_mode="Markdown"
    )


# --- SHIKOYAT ---
@dp.message(F.text == "📢 Shikoyat yozish")
async def shikoyat_start(msg: types.Message, state: FSMContext):
    await state.set_data({"stype": "shikoyat"})
    await state.set_state(Form.text)
    await msg.answer(
        "📢 *Shikoyatingizni yozing:*\n\n"
        "Muammo yoki noroziliklaringizni batafsil yozing.\n"
        "Har qanday xabar adminlar tomonidan ko'rib chiqiladi.",
        parse_mode="Markdown"
    )


@dp.message(Form.text)
async def receive_text(msg: types.Message, state: FSMContext):
    await state.update_data(text=msg.text)
    await state.set_state(Form.anon)
    await msg.answer(
        "Xabaringizni qanday yubormoqchisiz?",
        reply_markup=anon_keyboard()
    )


@dp.callback_query(F.data.in_(["send_named", "send_anon"]))
async def send_suggestion(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    is_anon = 1 if cb.data == "send_anon" else 0
    stype = data.get("stype", "taklif")
    text = data.get("text", "")

    sid = await db_add_suggestion(cb.from_user.id, stype, text, is_anon)
    await state.clear()

    emoji = "💡" if stype == "taklif" else "📢"
    if is_anon:
        sender = "🎭 *Anonim*"
    else:
        u = cb.from_user
        sender = f"👤 *{u.full_name}*"
        if u.username:
            sender += f" (@{u.username})"

    admin_msg = (
        f"{emoji} *Yangi {stype} #{sid}*\n\n"
        f"Yuboruvchi: {sender}\n"
        f"📝 Matn:\n{text}\n\n"
        f"🕐 {now()}"
    )

    for aid in ADMIN_IDS:
        try:
            await bot.send_message(
                aid, admin_msg, parse_mode="Markdown",
                reply_markup=action_keyboard(sid, cb.from_user.id)
            )
        except Exception:
            pass

    await cb.message.edit_text(
        f"✅ *{stype.capitalize()}ingiz yuborildi!*\n\n"
        f"📋 Raqam: *#{sid}*\n"
        "Adminlar ko'rib chiqib javob beradi. Sabr qiling 🙏",
        parse_mode="Markdown"
    )


# --- ADMIN: QABUL / RAD ---
@dp.callback_query(F.data.startswith("approve_") | F.data.startswith("reject_"))
async def handle_action(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("❌ Sizda admin huquqi yo'q!", show_alert=True)
        return

    parts = cb.data.split("_")
    action, sid, uid = parts[0], int(parts[1]), int(parts[2])
    status = "approved" if action == "approve" else "rejected"
    await db_update_status(sid, status)

    if status == "approved":
        label = "✅ Qabul qilindi"
        user_msg = f"✅ *#{sid}* raqamli {('taklif' if action else 'shikoyat')}ingiz admin tomonidan **qabul qilindi**! 🎉"
        # Qabul qilingan taklifni ovozga qo'yamiz
        row = await db_get_suggestion(sid)
        if row:
            try:
                await bot.send_message(
                    uid,
                    f"💡 Sizning taklifingiz ommaviy ovozga qo'yildi! Boshqalar ham ovoz bera oladi.",
                    reply_markup=vote_keyboard(sid)
                )
            except Exception:
                pass
    else:
        label = "❌ Rad etildi"
        user_msg = f"ℹ️ *#{sid}* raqamli xabaringiz ko'rib chiqildi, lekin hozircha qabul qilinmadi."

    try:
        await bot.send_message(uid, user_msg, parse_mode="Markdown")
    except Exception:
        pass

    new_text = cb.message.text + f"\n\n─────────────\n{label}\n👤 Admin: {cb.from_user.full_name}"
    await cb.message.edit_text(new_text, parse_mode="Markdown")
    await cb.answer(label)


# --- ADMIN: OVOZLAR ---
@dp.callback_query(F.data.startswith("votes_"))
async def show_votes(cb: types.CallbackQuery):
    sid = int(cb.data.split("_")[1])
    ups, downs = await db_vote_counts(sid)
    await cb.answer(f"👍 {ups}  |  👎 {downs}", show_alert=True)


# --- FOYDALANUVCHI OVOZ BERISHI ---
@dp.callback_query(F.data.startswith("vote_up_") | F.data.startswith("vote_down_"))
async def user_vote(cb: types.CallbackQuery):
    parts = cb.data.split("_")
    vote = 1 if parts[1] == "up" else 0
    sid = int(parts[2])

    success = await db_vote(sid, cb.from_user.id, vote)
    if success:
        ups, downs = await db_vote_counts(sid)
        await cb.answer(f"Ovozingiz qabul qilindi!\n👍 {ups}  |  👎 {downs}", show_alert=True)
    else:
        await cb.answer("❗ Siz allaqachon ovoz bergansiz!", show_alert=True)


# --- STATISTIKA ---
@dp.message(F.text == "📊 Mening statistikam")
async def my_stats(msg: types.Message):
    stats = await db_user_stats(msg.from_user.id)
    user = await db_get_user(msg.from_user.id)
    join = user[4] if user else "Noma'lum"

    await msg.answer(
        f"📊 *Sizning statistikangiz*\n\n"
        f"👤 Ism: {msg.from_user.full_name}\n"
        f"📅 Qo'shilgan: {join}\n\n"
        f"🔗 Tavsiya qilgan obunachilар: *{stats['referrals']} ta*\n"
        f"💡 Yuborilgan takliflar: *{stats['taklif']} ta*\n"
        f"📢 Yuborilgan shikoyatlar: *{stats['shikoyat']} ta*",
        parse_mode="Markdown"
    )


# --- TOP TAVSIYACHILAR ---
@dp.message(F.text == "🏆 Top tavsiyachilar")
async def top_list(msg: types.Message):
    top = await db_top_referrers(10)
    if not top:
        await msg.answer("Hali hech kim tavsiya qilmagan. Birinchi bo'ling! 🚀")
        return

    lines = ["🏆 *Top 10 tavsiyachilar:*\n"]
    for i, (uid, uname, fname, refs) in enumerate(top):
        medal = MEDALS[i] if i < len(MEDALS) else f"{i+1}."
        name = fname or uname or "Noma'lum"
        lines.append(f"{medal} {name} — *{refs} ta* obunachi")

    await msg.answer("\n".join(lines), parse_mode="Markdown")


# --- REFERAL HAVOLA ---
@dp.message(F.text == "🔗 Referal havolam")
async def referal_link(msg: types.Message):
    info = await bot.get_me()
    link = f"https://t.me/{info.username}?start={msg.from_user.id}"
    stats = await db_user_stats(msg.from_user.id)

    await msg.answer(
        f"🔗 *Sizning referal havolangiz:*\n\n"
        f"`{link}`\n\n"
        f"Bu havolani do'stlaringizga yuboring.\n"
        f"Har yangi foydalanuvchi uchun statistikangizga *+1* qo'shiladi.\n\n"
        f"📊 Hozircha: *{stats['referrals']} ta* tavsiya",
        parse_mode="Markdown"
    )


# --- TAKLIFLAR TARIXI ---
@dp.message(F.text == "📋 Takliflarim tarixi")
async def my_history(msg: types.Message):
    rows = await db_my_suggestions(msg.from_user.id)
    if not rows:
        await msg.answer("Siz hali hech narsa yubormadingiz.")
        return

    lines = ["📋 *So'nggi 10 ta xabaringiz:*\n"]
    for sid, stype, text, status, date in rows:
        e = "💡" if stype == "taklif" else "📢"
        short = text[:45] + "…" if len(text) > 45 else text
        s = STATUS_LABELS.get(status, status)
        lines.append(f"{e} *#{sid}* {s}\n📝 {short}\n🕐 {date}\n")

    await msg.answer("\n".join(lines), parse_mode="Markdown")


# --- ADMIN PANEL ---
@dp.message(F.text == "⚙️ Admin panel")
async def admin_panel(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    stats = await db_global_stats()
    await msg.answer(
        f"⚙️ *Admin Panel — {CHANNEL_USERNAME}*\n\n"
        f"👥 Jami foydalanuvchilar: *{stats['users']} ta*\n"
        f"✅ Faol foydalanuvchilar: *{stats['active']} ta*\n\n"
        f"💡 Jami takliflar: *{stats['takliflar']} ta*\n"
        f"📢 Jami shikoyatlar: *{stats['shikoyatlar']} ta*\n"
        f"⏳ Ko'rib chiqilmagan: *{stats['pending']} ta*\n\n"
        f"📣 Broadcast: /broadcast <xabar>\n"
        f"👤 Foydalanuvchi info: /userinfo <user_id>\n"
        f"🚫 Bloklash: /block <user_id>\n"
        f"✅ Blokdan chiqarish: /unblock <user_id>",
        parse_mode="Markdown"
    )


# --- BROADCAST ---
@dp.message(Command("broadcast"))
async def broadcast_cmd(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    text = msg.text[len("/broadcast "):].strip()
    if not text:
        await msg.answer("Ishlatish: /broadcast <xabar matni>")
        return

    users = await db_all_users()
    sent, failed = 0, 0
    for uid in users:
        try:
            await bot.send_message(uid, f"📣 *Kanal xabari:*\n\n{text}", parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1

    await msg.answer(
        f"✅ Xabar yuborildi!\n📤 Muvaffaqiyatli: {sent}\n❌ Yuborilmadi: {failed}"
    )


# --- USERINFO ---
@dp.message(Command("userinfo"))
async def userinfo_cmd(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    parts = msg.text.split()
    if len(parts) < 2:
        await msg.answer("Ishlatish: /userinfo <user_id>")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        await msg.answer("Noto'g'ri ID")
        return

    user = await db_get_user(uid)
    if not user:
        await msg.answer("Foydalanuvchi topilmadi.")
        return

    stats = await db_user_stats(uid)
    blocked = "🚫 Ha" if user[6] else "✅ Yo'q"
    await msg.answer(
        f"👤 *Foydalanuvchi ma'lumotlari:*\n\n"
        f"ID: `{user[0]}`\n"
        f"Ism: {user[2]}\n"
        f"Username: @{user[1] or 'yo\'q'}\n"
        f"Qo'shilgan: {user[4]}\n"
        f"Bloklangan: {blocked}\n\n"
        f"🔗 Tavsiyalar: {stats['referrals']} ta\n"
        f"💡 Takliflar: {stats['taklif']} ta\n"
        f"📢 Shikoyatlar: {stats['shikoyat']} ta",
        parse_mode="Markdown"
    )


# --- BLOCK ---
@dp.message(Command("block"))
async def block_cmd(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    parts = msg.text.split()
    if len(parts) < 2:
        await msg.answer("Ishlatish: /block <user_id>")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        await msg.answer("Noto'g'ri ID")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (uid,))
        await db.commit()
    await msg.answer(f"🚫 {uid} ID li foydalanuvchi bloklandi.")


# --- UNBLOCK ---
@dp.message(Command("unblock"))
async def unblock_cmd(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    parts = msg.text.split()
    if len(parts) < 2:
        await msg.answer("Ishlatish: /unblock <user_id>")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        await msg.answer("Noto'g'ri ID")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_blocked=0 WHERE user_id=?", (uid,))
        await db.commit()
    await msg.answer(f"✅ {uid} ID li foydalanuvchi blokdan chiqarildi.")


# =================== ISHGA TUSHIRISH ====================
async def main():
    await init_db()
    print("✅ Bot ishga tushdi!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

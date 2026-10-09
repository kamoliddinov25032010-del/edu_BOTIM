import os
import asyncio
import json
import random
from datetime import datetime, timedelta

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
)

# ==================== SOZLAMALAR ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "BU_YERGA_TOKENINGIZNI_QOYING")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "123456789").split(",") if x.strip()]
DB_PATH = os.getenv("DB_PATH", "edu_bot.db")
PAGE_SIZE = 6

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ==================== BAZA ====================
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY, full_name TEXT, username TEXT, phone TEXT,
    role TEXT DEFAULT 'student', group_id INTEGER, is_blocked INTEGER DEFAULT 0,
    points INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, schedule TEXT,
    description TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER, title TEXT, text TEXT,
    file_id TEXT, file_type TEXT, is_pinned INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS homework (
    id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER, title TEXT,
    description TEXT, deadline TEXT, is_pinned INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, homework_id INTEGER, student_id INTEGER,
    content TEXT, file_id TEXT, status TEXT DEFAULT 'pending', grade TEXT,
    comment TEXT, points INTEGER DEFAULT 0, submitted_at TEXT
);
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER, text TEXT,
    is_pinned INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER, title TEXT,
    question TEXT, options TEXT, correct TEXT, points INTEGER DEFAULT 1,
    is_active INTEGER DEFAULT 1, created_at TEXT
);
CREATE TABLE IF NOT EXISTS test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT, test_id INTEGER, student_id INTEGER,
    answer TEXT, is_correct INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER, student_id INTEGER,
    date TEXT, status TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS titles (
    id INTEGER PRIMARY KEY AUTOINCREMENT, emoji TEXT, name TEXT UNIQUE,
    description TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS user_titles (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title_id INTEGER, given_at TEXT
);
CREATE TABLE IF NOT EXISTS appeals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT,
    is_read INTEGER DEFAULT 0, created_at TEXT
);
"""


async def ensure_columns(db):
    """Eski bazalarga yetishmagan ustunlarni qo'shish"""
    checks = [
        ("users", "points", "INTEGER DEFAULT 0"),
        ("users", "phone", "TEXT"),
        ("materials", "is_pinned", "INTEGER DEFAULT 0"),
        ("materials", "file_type", "TEXT"),
        ("homework", "is_pinned", "INTEGER DEFAULT 0"),
        ("submissions", "points", "INTEGER DEFAULT 0"),
        ("groups", "description", "TEXT"),
    ]
    for table, col, typ in checks:
        try:
            cur = await db.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in await cur.fetchall()]
            if col not in cols:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                print(f"➕ Qo'shildi: {table}.{col}")
        except Exception as e:
            print(f"⚠️ {table}.{col}: {e}")


async def init_db():
    # Railway volume papkasini yaratish
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await ensure_columns(db)
        # Boshlang'ich unvonlar
        cursor = await db.execute("SELECT COUNT(*) FROM titles")
        r = await cursor.fetchone()
        if r[0] == 0:
            defaults = [
                ("🏆", "Faol o'quvchi", "Darsda faol qatnashgan"),
                ("⭐", "A'lochi", "Vazifalarni a'lo bajargan"),
                ("🎯", "Test qiroli", "Testlarda yuqori natija"),
                ("🔥", "Seriya", "Ketma-ket topshirgan"),
                ("💎", "Sifatli", "Sifatli ish"),
                ("🌟", "Yulduz", "Eng yaxshi o'quvchi"),
                ("🚀", "Raketa", "Tez o'suvchi"),
                ("👑", "Qirol", "Guruh sardori"),
            ]
            for em, nm, desc in defaults:
                await db.execute("INSERT INTO titles(emoji,name,description,created_at) VALUES(?,?,?,?)",
                                 (em, nm, desc, datetime.now().isoformat()))
        await db.commit()


async def q(sql, p=()):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql, p)
        await db.commit()
        return cur.lastrowid


async def one(sql, p=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, p) as cur:
            return await cur.fetchone()


async def all_(sql, p=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, p) as cur:
            return await cur.fetchall()


async def cnt(sql, p=()):
    r = await one(sql, p)
    return r[0] if r else 0


def is_admin(uid):
    return uid in ADMIN_IDS


# ==================== KLAVIATURALAR ====================
def admin_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="👥 O'quvchilar")],
        [KeyboardButton(text="📚 Guruhlar"), KeyboardButton(text="🏅 Unvonlar")],
        [KeyboardButton(text="📢 E'lonlar"), KeyboardButton(text="📖 Materiallar")],
        [KeyboardButton(text="📝 Vazifalar"), KeyboardButton(text="🎯 Testlar")],
        [KeyboardButton(text="✋ Davomat"), KeyboardButton(text="📥 Topshiriqlar")],
        [KeyboardButton(text="⭐ Ballar"), KeyboardButton(text="🎲 Random o'quvchi")],
        [KeyboardButton(text="💬 Murojaatlar"), KeyboardButton(text="📅 Jadval")],
        [KeyboardButton(text="⚙️ Sozlamalar"), KeyboardButton(text="📢 Xabar yuborish")],
    ], resize_keyboard=True)


def student_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📢 E'lonlar"), KeyboardButton(text="📖 Materiallar")],
        [KeyboardButton(text="📝 Vazifalarim"), KeyboardButton(text="🎯 Testlar")],
        [KeyboardButton(text="📊 Natijalarim"), KeyboardButton(text="🏆 Reyting")],
        [KeyboardButton(text="🏅 Unvonlarim"), KeyboardButton(text="👤 Profilim")],
        [KeyboardButton(text="💬 Adminga yozish")],
    ], resize_keyboard=True)


def cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]], resize_keyboard=True)


def ikb(rows, back=None):
    kb = [[InlineKeyboardButton(text=t, callback_data=d)] for t, d in rows]
    if back:
        kb.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def confirm_kb(yes_d, no_d="cancel"):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ha", callback_data=yes_d),
        InlineKeyboardButton(text="❌ Yo'q", callback_data=no_d)]])


def page_kb(rows, page, total, prefix, back=None):
    kb = [[InlineKeyboardButton(text=t, callback_data=d)] for t, d in rows]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}_p:{page-1}"))
    pages = max(1, (total - 1) // PAGE_SIZE + 1)
    nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}_p:{page+1}"))
    if nav:
        kb.append(nav)
    if back:
        kb.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ==================== STATES ====================
class A(StatesGroup):
    grp_name = State(); grp_sched = State(); grp_desc = State()
    grp_e_name = State(); grp_e_sched = State(); grp_e_desc = State()
    st_search = State(); st_e_name = State(); st_e_phone = State(); st_msg = State()
    mat_gid = State(); mat_title = State(); mat_body = State()
    mat_e_title = State(); mat_e_text = State()
    hw_gid = State(); hw_title = State(); hw_desc = State(); hw_deadline = State()
    hw_e_title = State(); hw_e_desc = State(); hw_e_deadline = State()
    grade_val = State(); grade_cmt = State(); grade_points = State()
    bc_text = State()
    ann_gid = State(); ann_text = State()
    test_gid = State(); test_title = State(); test_q = State()
    test_opts = State(); test_correct = State(); test_points = State()
    title_emoji = State(); title_name = State(); title_desc = State()
    pts_amount = State(); pts_reason = State()


class S(StatesGroup):
    submit = State()
    edit_name = State()
    edit_phone = State()
    appeal = State()


# ==================== HELPERS ====================
def un(u):
    if not u:
        return "?"
    name = u["full_name"] or "?"
    uname = u["username"]
    return f"{name} (@{uname})" if uname else name


async def safe_send(uid, text, **kw):
    try:
        await bot.send_message(uid, text, **kw)
        return True
    except Exception:
        return False


async def safe_copy(uid, msg):
    try:
        await msg.copy_to(uid)
        return True
    except Exception:
        return False


async def get_user(uid):
    return await one("SELECT * FROM users WHERE tg_id=?", (uid,))


async def get_group(gid):
    return await one("SELECT * FROM groups WHERE id=?", (gid,))


async def add_points(uid, amount, reason=""):
    u = await get_user(uid)
    if not u:
        return
    new = (u["points"] or 0) + amount
    await q("UPDATE users SET points=? WHERE tg_id=?", (new, uid))
    if amount > 0:
        await safe_send(uid, f"⭐ <b>+{amount} ball!</b>\n💬 {reason}\n\n📊 Jami: <b>{new}</b>")


async def user_titles_str(uid):
    ts = await all_("""SELECT t.emoji, t.name FROM user_titles ut
                       JOIN titles t ON t.id=ut.title_id WHERE ut.user_id=?""", (uid,))
    if not ts:
        return ""
    return " ".join([f"{t['emoji']}{t['name']}" for t in ts])


# ==================== START ====================
@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    u = await get_user(m.from_user.id)
    if not u:
        await q("INSERT INTO users(tg_id,full_name,username,created_at) VALUES(?,?,?,?)",
                (m.from_user.id, m.from_user.full_name, m.from_user.username,
                 datetime.now().isoformat()))
        for aid in ADMIN_IDS:
            await safe_send(aid,
                f"🆕 <b>Yangi o'quvchi</b>\n👤 {m.from_user.full_name}\n"
                f"🔗 @{m.from_user.username or '—'}\n🆔 <code>{m.from_user.id}</code>")
        u = await get_user(m.from_user.id)
    else:
        await q("UPDATE users SET username=? WHERE tg_id=?",
                (m.from_user.username, m.from_user.id))

    if u["is_blocked"]:
        return await m.answer("🚫 Siz bloklangansiz.")
    if is_admin(m.from_user.id):
        await m.answer("👨‍💼 <b>Admin panel</b>\nXush kelibsiz!", reply_markup=admin_menu())
    else:
        await m.answer(f"🎓 <b>Salom, {m.from_user.full_name}!</b>\n\nMenyudan tanlang 👇",
                       reply_markup=student_menu())


@dp.message(Command("admin"))
async def admin_cmd(m: Message):
    if is_admin(m.from_user.id):
        await m.answer("👨‍💼 Admin panel", reply_markup=admin_menu())


# ==================== BEKOR QILISH ====================
@dp.message(F.text == "❌ Bekor qilish")
async def cancel_state(m: Message, state: FSMContext):
    await state.clear()
    kb = admin_menu() if is_admin(m.from_user.id) else student_menu()
    await m.answer("❌ Bekor qilindi.", reply_markup=kb)


@dp.callback_query(F.data == "noop")
async def noop(c: CallbackQuery):
    await c.answer()


@dp.callback_query(F.data == "cancel")
async def cancel_cb(c: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await c.message.delete()
    except Exception:
        pass
    await c.answer("❌")


@dp.callback_query(F.data == "admin_root")
async def admin_root(c: CallbackQuery):
    try:
        await c.message.delete()
    except Exception:
        pass
    await c.message.answer("👨‍💼 Admin panel", reply_markup=admin_menu())
    await c.answer()


# ==================== 📊 STATISTIKA ====================
@dp.message(F.text == "📊 Statistika")
async def stats(m: Message):
    if not is_admin(m.from_user.id):
        return
    total_u = await cnt("SELECT COUNT(*) FROM users WHERE role='student'")
    grps = await cnt("SELECT COUNT(*) FROM groups")
    hw = await cnt("SELECT COUNT(*) FROM homework")
    subs = await cnt("SELECT COUNT(*) FROM submissions")
    pend = await cnt("SELECT COUNT(*) FROM submissions WHERE status='pending'")
    mats = await cnt("SELECT COUNT(*) FROM materials")
    pins = await cnt("SELECT COUNT(*) FROM materials WHERE is_pinned=1")
    tests = await cnt("SELECT COUNT(*) FROM tests")
    ann = await cnt("SELECT COUNT(*) FROM announcements")
    titles = await cnt("SELECT COUNT(*) FROM titles")
    appeals = await cnt("SELECT COUNT(*) FROM appeals WHERE is_read=0")
    today = datetime.now().date().isoformat()
    today_new = await cnt("SELECT COUNT(*) FROM users WHERE created_at LIKE ?", (today + "%",))
    txt = (f"📊 <b>STATISTIKA</b>\n{'─'*25}\n\n"
           f"👥 O'quvchilar: <b>{total_u}</b>\n"
           f"   🆕 Bugun: {today_new}\n\n"
           f"📚 Guruhlar: <b>{grps}</b>\n"
           f"📢 E'lonlar: <b>{ann}</b>\n"
           f"📖 Materiallar: <b>{mats}</b> (📌 {pins})\n"
           f"📝 Vazifalar: <b>{hw}</b>\n"
           f"🎯 Testlar: <b>{tests}</b>\n"
           f"🏅 Unvonlar: <b>{titles}</b>\n"
           f"📥 Topshiriqlar: <b>{subs}</b>\n"
           f"   ⏳ Tekshirilmagan: {pend}\n\n"
           f"💬 Yangi murojaatlar: <b>{appeals}</b>\n")
    await m.answer(txt, reply_markup=ikb([("🔄 Yangilash", "stats_refresh")]))


@dp.callback_query(F.data == "stats_refresh")
async def stats_r(c: CallbackQuery):
    await c.message.delete()
    await stats(c.message)
    await c.answer("✅")


# ==================== 🏅 UNVONLAR ====================
@dp.message(F.text == "🏅 Unvonlar")
async def titles_root(m: Message):
    if not is_admin(m.from_user.id):
        return
    ts = await all_("SELECT * FROM titles ORDER BY name")
    rows = [
        ("➕ Yangi unvon yaratish", "title_new"),
        ("🏆 Unvonlar reytingi", "title_rating"),
        ("📋 Unvonlar kutubxonasi", "title_lib:0"),
        ("🎁 O'quvchiga unvon berish", "title_give"),
    ]
    await m.answer(f"🏅 <b>Unvonlar boshqaruvi</b>\nJami: <b>{len(ts)}</b>",
                   reply_markup=ikb(rows, back="admin_root"))


@dp.callback_query(F.data == "title_lib")
async def title_lib_root(c: CallbackQuery):
    ts = await all_("SELECT * FROM titles ORDER BY name")
    rows = [(f"{t['emoji']} {t['name']}", f"title_v:{t['id']}") for t in ts]
    await c.message.edit_text(f"📋 <b>Unvonlar kutubxonasi</b> ({len(ts)})",
                              reply_markup=ikb(rows, back="admin_root"))
    await c.answer()


@dp.callback_query(F.data.startswith("title_lib:"))
async def title_lib(c: CallbackQuery):
    page = int(c.data.split(":")[1])
    ts = await all_("SELECT * FROM titles ORDER BY name")
    items = ts[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [(f"{t['emoji']} {t['name']}", f"title_v:{t['id']}") for t in items]
    try:
        await c.message.edit_text(f"📋 <b>Unvonlar</b> ({len(ts)})",
            reply_markup=page_kb(rows, page, len(ts), "title_lib", back="admin_root"))
    except Exception:
        pass
    await c.answer()


@dp.callback_query(F.data == "title_new")
async def title_new(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Emoji yuboring (masalan: 🏆, ⭐, 🎯):", reply_markup=cancel_kb())
    await state.set_state(A.title_emoji)
    await c.answer()


@dp.message(A.title_emoji)
async def title_emoji(m: Message, state: FSMContext):
    await state.update_data(emoji=m.text.strip())
    await m.answer("Unvon nomi:", reply_markup=cancel_kb())
    await state.set_state(A.title_name)


@dp.message(A.title_name)
async def title_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip())
    await m.answer("Tavsif:", reply_markup=cancel_kb())
    await state.set_state(A.title_desc)


@dp.message(A.title_desc)
async def title_desc(m: Message, state: FSMContext):
    d = await state.get_data()
    try:
        await q("INSERT INTO titles(emoji,name,description,created_at) VALUES(?,?,?,?)",
                (d["emoji"], d["name"], m.text, datetime.now().isoformat()))
        await m.answer(f"✅ <b>{d['emoji']} {d['name']}</b> yaratildi!",
                       reply_markup=admin_menu())
    except Exception as e:
        await m.answer(f"❌ Xato: {e}", reply_markup=admin_menu())
    await state.clear()


@dp.callback_query(F.data.startswith("title_v:"))
async def title_v(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    t = await one("SELECT * FROM titles WHERE id=?", (tid,))
    if not t:
        return await c.answer("Topilmadi", show_alert=True)
    owners = await all_("""SELECT u.full_name, u.username, u.tg_id FROM user_titles ut
                           JOIN users u ON u.tg_id=ut.user_id
                           WHERE ut.title_id=? ORDER BY ut.given_at DESC""", (tid,))
    txt = f"{t['emoji']} <b>{t['name']}</b>\n\n📝 {t['description'] or '—'}\n\n"
    txt += f"👥 Egalari: <b>{len(owners)}</b>"
    if owners:
        txt += "\n"
        for o in owners[:10]:
            uname = f" (@{o['username']})" if o['username'] else ""
            txt += f"\n• {o['full_name']}{uname}"
    rows = [
        ("🎁 Berish", f"title_give_one:{tid}"),
        ("🗑 O'chirish", f"title_del_ask:{tid}"),
    ]
    await c.message.answer(txt, reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("title_del_ask:"))
async def title_del_ask(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    await c.message.edit_text("🗑 O'chirilsinmi?",
        reply_markup=confirm_kb(f"title_del_yes:{tid}", "admin_root"))
    await c.answer()


@dp.callback_query(F.data.startswith("title_del_yes:"))
async def title_del_yes(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    await q("DELETE FROM titles WHERE id=?", (tid,))
    await q("DELETE FROM user_titles WHERE title_id=?", (tid,))
    await c.message.edit_text("🗑 O'chirildi.")
    await c.answer()


@dp.callback_query(F.data == "title_rating")
async def title_rating(c: CallbackQuery):
    rs = await all_("""SELECT u.full_name, u.username, u.tg_id, COUNT(ut.id) c
                       FROM users u LEFT JOIN user_titles ut ON ut.user_id=u.tg_id
                       WHERE u.role='student'
                       GROUP BY u.tg_id HAVING c>0
                       ORDER BY c DESC LIMIT 20""")
    if not rs:
        return await c.answer("Hech kimda unvon yo'q", show_alert=True)
    txt = "🏆 <b>Unvonlar reytingi</b>\n\n"
    for i, r in enumerate(rs, 1):
        icon = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
        uname = f" (@{r['username']})" if r['username'] else ""
        titles_str = await user_titles_str(r["tg_id"])
        txt += f"{icon} {r['full_name']}{uname} — <b>{r['c']}</b>\n"
        if titles_str:
            txt += f"   {titles_str}\n"
    await c.message.edit_text(txt, reply_markup=ikb([("⬅️ Orqaga", "admin_root")]))
    await c.answer()


@dp.callback_query(F.data == "title_give")
async def title_give(c: CallbackQuery):
    us = await all_("SELECT * FROM users WHERE role='student' ORDER BY full_name LIMIT 30")
    if not us:
        return await c.answer("O'quvchi yo'q", show_alert=True)
    rows = [(f"👤 {un(u)[:25]}", f"title_give_u:{u['tg_id']}") for u in us]
    await c.message.edit_text("Kimga unvon berish?",
                              reply_markup=ikb(rows, back="admin_root"))
    await c.answer()


@dp.callback_query(F.data.startswith("title_give_u:"))
async def title_give_u(c: CallbackQuery):
    uid = int(c.data.split(":")[1])
    ts = await all_("SELECT * FROM titles ORDER BY name")
    if not ts:
        return await c.answer("Unvon yo'q", show_alert=True)
    rows = [(f"{t['emoji']} {t['name']}", f"title_do:{uid}:{t['id']}") for t in ts]
    await c.message.edit_text("Qaysi unvon?", reply_markup=ikb(rows, back="admin_root"))
    await c.answer()


@dp.callback_query(F.data.startswith("title_give_one:"))
async def title_give_one(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    us = await all_("SELECT * FROM users WHERE role='student' ORDER BY full_name LIMIT 30")
    rows = [(f"👤 {un(u)[:25]}", f"title_do:{u['tg_id']}:{tid}") for u in us]
    await c.message.edit_text("Kimga berish?", reply_markup=ikb(rows, back="admin_root"))
    await c.answer()


@dp.callback_query(F.data.startswith("title_do:"))
async def title_do(c: CallbackQuery):
    _, uid, tid = c.data.split(":")
    uid, tid = int(uid), int(tid)
    t = await one("SELECT * FROM titles WHERE id=?", (tid,))
    old = await one("SELECT id FROM user_titles WHERE user_id=? AND title_id=?",
                    (uid, tid))
    if old:
        await q("DELETE FROM user_titles WHERE id=?", (old["id"],))
        await c.answer("Olib tashlandi")
        await safe_send(uid, f"😢 <b>{t['emoji']} {t['name']}</b> unvoni olib tashlandi")
    else:
        await q("INSERT INTO user_titles(user_id,title_id,given_at) VALUES(?,?,?)",
                (uid, tid, datetime.now().isoformat()))
        await c.answer("✅ Berildi")
        await safe_send(uid, f"🎉 <b>Tabriklaymiz!</b>\n\n"
                             f"Sizga yangi unvon: <b>{t['emoji']} {t['name']}</b>\n"
                             f"📝 {t['description'] or ''}")


# ==================== 👥 O'QUVCHILAR ====================
@dp.message(F.text == "👥 O'quvchilar")
async def st_root(m: Message):
    if not is_admin(m.from_user.id):
        return
    total = await cnt("SELECT COUNT(*) FROM users WHERE role='student'")
    rows = [
        ("📋 Barcha o'quvchilar", "st_list:0"),
        ("🏆 TOP-10 reyting", "st_top"),
        ("🔥 Hafta faollari", "st_weekly"),
        ("🔍 Qidirish", "st_search"),
        ("📚 Guruh bo'yicha", "st_bygrp"),
        ("🚫 Bloklanganlar", "st_blocked"),
    ]
    await m.answer(f"👥 <b>O'quvchilar</b> — {total} ta",
                   reply_markup=ikb(rows, back="admin_root"))


@dp.callback_query(F.data.startswith("st_list:"))
async def st_list(c: CallbackQuery):
    page = int(c.data.split(":")[1])
    us = await all_("SELECT * FROM users WHERE role='student' ORDER BY points DESC, created_at DESC")
    items = us[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = []
    for u in items:
        icon = "🚫" if u["is_blocked"] else "✅"
        uname = f"@{u['username']}" if u['username'] else ""
        rows.append((f"{icon} {u['full_name'][:12]} {uname[:10]} | ⭐{u['points']}",
                     f"st_view:{u['tg_id']}"))
    try:
        await c.message.edit_text(f"👥 <b>O'quvchilar</b> ({len(us)})",
            reply_markup=page_kb(rows, page, len(us), "st_list", back="admin_root"))
    except Exception:
        pass
    await c.answer()


@dp.callback_query(F.data == "st_top")
async def st_top(c: CallbackQuery):
    us = await all_("SELECT * FROM users WHERE role='student' ORDER BY points DESC LIMIT 10")
    txt = "🏆 <b>TOP-10 reyting</b>\n\n"
    for i, u in enumerate(us, 1):
        icon = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
        ts = await user_titles_str(u["tg_id"])
        uname = f" @{u['username']}" if u['username'] else ""
        txt += f"{icon} {u['full_name']}{uname} — <b>{u['points']}</b> ⭐\n"
        if ts:
            txt += f"   {ts}\n"
    await c.message.edit_text(txt, reply_markup=ikb([("⬅️ Orqaga", "admin_root")]))
    await c.answer()


@dp.callback_query(F.data == "st_weekly")
async def st_weekly(c: CallbackQuery):
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    rs = await all_("""SELECT u.full_name, u.username, u.tg_id,
                       COUNT(DISTINCT s.id) s_cnt,
                       COUNT(DISTINCT tr.id) t_cnt
                       FROM users u
                       LEFT JOIN submissions s ON s.student_id=u.tg_id AND s.submitted_at>=?
                       LEFT JOIN test_results tr ON tr.student_id=u.tg_id AND tr.created_at>=?
                       WHERE u.role='student'
                       GROUP BY u.tg_id
                       HAVING s_cnt>0 OR t_cnt>0
                       ORDER BY (s_cnt+t_cnt) DESC LIMIT 15""", (week_ago, week_ago))
    if not rs:
        return await c.answer("Bu hafta faol o'quvchi yo'q", show_alert=True)
    txt = "🔥 <b>Bu hafta eng faol o'quvchilar</b>\n\n"
    for i, r in enumerate(rs, 1):
        icon = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
        uname = f" @{r['username']}" if r['username'] else ""
        txt += f"{icon} {r['full_name']}{uname}\n"
        txt += f"   📝 {r['s_cnt']} vazifa | 🎯 {r['t_cnt']} test\n"
    await c.message.edit_text(txt, reply_markup=ikb([("⬅️ Orqaga", "admin_root")]))
    await c.answer()


@dp.callback_query(F.data == "st_blocked")
async def st_blocked(c: CallbackQuery):
    us = await all_("SELECT * FROM users WHERE is_blocked=1")
    if not us:
        return await c.answer("Yo'q", show_alert=True)
    rows = [(f"🚫 {un(u)[:25]}", f"st_view:{u['tg_id']}") for u in us]
    await c.message.edit_text(f"🚫 <b>Bloklanganlar</b> ({len(us)})",
                              reply_markup=ikb(rows, back="admin_root"))
    await c.answer()


@dp.callback_query(F.data == "st_search")
async def st_search(c: CallbackQuery, state: FSMContext):
    await c.message.answer("🔍 Ism, username yoki ID:", reply_markup=cancel_kb())
    await state.set_state(A.st_search)
    await c.answer()


@dp.message(A.st_search)
async def st_search_do(m: Message, state: FSMContext):
    await state.clear()
    term = f"%{m.text.strip().lstrip('@')}%"
    us = await all_("""SELECT * FROM users
                       WHERE (full_name LIKE ? OR username LIKE ? OR CAST(tg_id AS TEXT) LIKE ?)
                       AND role='student' LIMIT 20""", (term, term, term))
    if not us:
        return await m.answer("Topilmadi.", reply_markup=admin_menu())
    rows = [(f"👤 {un(u)[:25]}", f"st_view:{u['tg_id']}") for u in us]
    await m.answer(f"🔍 {len(us)} ta:", reply_markup=ikb(rows, back="admin_root"))


@dp.callback_query(F.data == "st_bygrp")
async def st_bygrp(c: CallbackQuery):
    gs = await all_("SELECT * FROM groups")
    if not gs:
        return await c.answer("Guruh yo'q", show_alert=True)
    rows = [(f"📚 {g['name']}", f"st_grp:0:{g['id']}") for g in gs]
    await c.message.edit_text("Guruhni tanlang:", reply_markup=ikb(rows, back="admin_root"))
    await c.answer()


@dp.callback_query(F.data.startswith("st_grp:"))
async def st_grp(c: CallbackQuery):
    _, page, gid = c.data.split(":")
    page, gid = int(page), int(gid)
    us = await all_("SELECT * FROM users WHERE group_id=? ORDER BY full_name", (gid,))
    g = await get_group(gid)
    items = us[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [(f"👤 {un(u)[:25]}", f"st_view:{u['tg_id']}") for u in items]
    try:
        await c.message.edit_text(f"📚 <b>{g['name']}</b> — {len(us)}",
            reply_markup=page_kb(rows, page, len(us), f"st_grp_x_{gid}", back="st_bygrp"))
    except Exception:
        pass
    await c.answer()


@dp.callback_query(F.data.startswith("st_grp_x_"))
async def st_grp_x(c: CallbackQuery):
    gid = int(c.data.split("_x_")[1].split(":")[0])
    page = int(c.data.split(":")[-1])
    us = await all_("SELECT * FROM users WHERE group_id=? ORDER BY full_name", (gid,))
    g = await get_group(gid)
    items = us[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [(f"👤 {un(u)[:25]}", f"st_view:{u['tg_id']}") for u in items]
    try:
        await c.message.edit_text(f"📚 <b>{g['name']}</b> — {len(us)}",
            reply_markup=page_kb(rows, page, len(us), f"st_grp_x_{gid}", back="st_bygrp"))
    except Exception:
        pass
    await c.answer()


@dp.callback_query(F.data.startswith("st_view:"))
async def st_view(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    u = await get_user(tid)
    if not u:
        return await c.answer("Topilmadi", show_alert=True)
    g = await get_group(u["group_id"]) if u["group_id"] else None
    subs = await cnt("SELECT COUNT(*) FROM submissions WHERE student_id=?", (tid,))
    graded = await cnt("SELECT COUNT(*) FROM submissions WHERE student_id=? AND status='graded'", (tid,))
    titles_str = await user_titles_str(tid)
    attended = await cnt("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='qatnashdi'", (tid,))
    tests_ok = await cnt("SELECT COUNT(*) FROM test_results WHERE student_id=? AND is_correct=1", (tid,))
    rank = 0
    if u["group_id"]:
        ss = await all_("SELECT tg_id FROM users WHERE group_id=? ORDER BY points DESC",
                        (u["group_id"],))
        for i, r in enumerate(ss, 1):
            if r["tg_id"] == tid:
                rank = i
                break
    uname = f"@{u['username']}" if u['username'] else "—"
    txt = (f"👤 <b>{u['full_name']}</b>\n{'─'*25}\n"
           f"🔗 {uname}\n"
           f"🆔 <code>{u['tg_id']}</code>\n"
           f"📞 {u['phone'] or '—'}\n"
           f"📚 Guruh: <b>{g['name'] if g else '—'}</b>\n"
           f"🏆 Reyting: {rank or '—'}\n\n"
           f"⭐ Ball: <b>{u['points'] or 0}</b>\n"
           f"🏅 Unvonlar: {titles_str or '—'}\n\n"
           f"📥 Topshiriqlar: {subs} | ✅ {graded}\n"
           f"🎯 To'g'ri testlar: {tests_ok}\n"
           f"✋ Qatnashgan: {attended}\n"
           f"🚫 Blok: {'Ha' if u['is_blocked'] else 'Yoq'}")
    rows = [
        ("✏️ Ism", f"st_e_name:{tid}"),
        ("📞 Telefon", f"st_e_phone:{tid}"),
        ("📚 Guruhni o'zgartirish", f"st_grp_ch:{tid}"),
        ("⭐ Ball qo'shish", f"st_pts:{tid}"),
        ("🏅 Unvon berish", f"st_title:{tid}"),
        ("📈 Statistika", f"st_stats:{tid}"),
        ("💬 Xabar", f"st_msg:{tid}"),
        ("🔓 Unblock" if u["is_blocked"] else "🚫 Bloklash", f"st_block:{tid}"),
        ("🗑 O'chirish", f"st_del_ask:{tid}"),
    ]
    await c.message.answer(txt, reply_markup=ikb(rows, back="admin_root"))
    await c.answer()


@dp.callback_query(F.data.startswith("st_stats:"))
async def st_stats(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    u = await get_user(tid)
    if not u:
        return await c.answer("Topilmadi", show_alert=True)
    week_ago = (datetime.now().date() - timedelta(days=7)).isoformat()
    att_present = await cnt("""SELECT COUNT(*) FROM attendance
                               WHERE student_id=? AND status='qatnashdi' AND date>=?""",
                            (tid, week_ago))
    att_absent = await cnt("""SELECT COUNT(*) FROM attendance
                              WHERE student_id=? AND status='qatnashmadi' AND date>=?""",
                           (tid, week_ago))
    month_ago = (datetime.now() - timedelta(days=30)).isoformat()
    subs_month = await cnt("SELECT COUNT(*) FROM submissions WHERE student_id=? AND submitted_at>=?",
                            (tid, month_ago))
    tests_month = await cnt("SELECT COUNT(*) FROM test_results WHERE student_id=? AND created_at>=?",
                             (tid, month_ago))
    tests_ok_month = await cnt("""SELECT COUNT(*) FROM test_results
                                  WHERE student_id=? AND is_correct=1 AND created_at>=?""",
                                (tid, month_ago))
    ts = await user_titles_str(tid)
    txt = (f"📈 <b>Statistika: {u['full_name']}</b>\n{'─'*25}\n\n"
           f"✋ <b>Oxirgi 7 kunlik davomat:</b>\n"
           f"   ✅ Qatnashdi: {att_present}\n"
           f"   ❌ Qatnashmadi: {att_absent}\n\n"
           f"📝 <b>Oxirgi 30 kunlik:</b>\n"
           f"   📥 Topshirilgan: {subs_month}\n"
           f"   🎯 Testlar: {tests_month} (✅ {tests_ok_month})\n\n"
           f"⭐ <b>Jami ball:</b> {u['points'] or 0}\n"
           f"🏅 <b>Unvonlar:</b> {ts or '—'}")
    await c.message.answer(txt, reply_markup=ikb([("⬅️ Orqaga", "admin_root")]))
    await c.answer()


@dp.callback_query(F.data.startswith("st_title:"))
async def st_title(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    ts = await all_("SELECT * FROM titles ORDER BY name")
    if not ts:
        return await c.answer("Unvon yo'q", show_alert=True)
    rows = [(f"{t['emoji']} {t['name']}", f"title_do:{tid}:{t['id']}") for t in ts]
    await c.message.answer("Unvonni tanlang (yana bossangiz — o'chiriladi):",
                           reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("st_e_name:"))
async def st_e_name(c: CallbackQuery, state: FSMContext):
    await state.update_data(tid=int(c.data.split(":")[1]))
    await c.message.answer("Yangi ism:", reply_markup=cancel_kb())
    await state.set_state(A.st_e_name)
    await c.answer()


@dp.message(A.st_e_name)
async def st_e_name_do(m: Message, state: FSMContext):
    d = await state.get_data()
    await q("UPDATE users SET full_name=? WHERE tg_id=?", (m.text, d["tid"]))
    await state.clear()
    await m.answer("✅", reply_markup=admin_menu())


@dp.callback_query(F.data.startswith("st_e_phone:"))
async def st_e_phone(c: CallbackQuery, state: FSMContext):
    await state.update_data(tid=int(c.data.split(":")[1]))
    await c.message.answer("Yangi telefon:", reply_markup=cancel_kb())
    await state.set_state(A.st_e_phone)
    await c.answer()


@dp.message(A.st_e_phone)
async def st_e_phone_do(m: Message, state: FSMContext):
    d = await state.get_data()
    await q("UPDATE users SET phone=? WHERE tg_id=?", (m.text, d["tid"]))
    await state.clear()
    await m.answer("✅", reply_markup=admin_menu())


@dp.callback_query(F.data.startswith("st_grp_ch:"))
async def st_grp_ch(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    gs = await all_("SELECT * FROM groups")
    rows = [(f"📚 {g['name']}", f"st_grp_set:{tid}:{g['id']}") for g in gs]
    rows.append(("🚫 Guruhsiz", f"st_grp_set:{tid}:0"))
    await c.message.answer("Guruh:", reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("st_grp_set:"))
async def st_grp_set(c: CallbackQuery):
    _, tid, gid = c.data.split(":")
    tid, gid = int(tid), int(gid)
    if gid == 0:
        await q("UPDATE users SET group_id=NULL WHERE tg_id=?", (tid,))
        await c.message.edit_text("✅ Guruhsiz.")
    else:
        await q("UPDATE users SET group_id=? WHERE tg_id=?", (gid, tid))
        g = await get_group(gid)
        await c.message.edit_text(f"✅ {g['name']}")
        await safe_send(tid, f"🎉 Siz <b>{g['name']}</b> guruhiga qo'shildingiz!")
    await c.answer()


@dp.callback_query(F.data.startswith("st_pts:"))
async def st_pts(c: CallbackQuery, state: FSMContext):
    await state.update_data(tid=int(c.data.split(":")[1]))
    await c.message.answer("Ball (masalan: 5 yoki -3):", reply_markup=cancel_kb())
    await state.set_state(A.pts_amount)
    await c.answer()


@dp.message(A.pts_amount)
async def st_pts_do(m: Message, state: FSMContext):
    try:
        amt = int(m.text)
    except ValueError:
        return await m.answer("Faqat raqam!")
    await state.update_data(amt=amt)
    await m.answer("Sabab:", reply_markup=cancel_kb())
    await state.set_state(A.pts_reason)


@dp.message(A.pts_reason)
async def st_pts_reason(m: Message, state: FSMContext):
    d = await state.get_data()
    await add_points(d["tid"], d["amt"], m.text)
    await state.clear()
    await m.answer("✅", reply_markup=admin_menu())


@dp.callback_query(F.data.startswith("st_msg:"))
async def st_msg(c: CallbackQuery, state: FSMContext):
    await state.update_data(tid=int(c.data.split(":")[1]))
    await c.message.answer("Xabar:", reply_markup=cancel_kb())
    await state.set_state(A.st_msg)
    await c.answer()


@dp.message(A.st_msg)
async def st_msg_do(m: Message, state: FSMContext):
    d = await state.get_data()
    ok = await safe_copy(d["tid"], m)
    await state.clear()
    await m.answer("✅" if ok else "❌", reply_markup=admin_menu())


@dp.callback_query(F.data.startswith("st_block:"))
async def st_block(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    u = await get_user(tid)
    new = 0 if u["is_blocked"] else 1
    await q("UPDATE users SET is_blocked=? WHERE tg_id=?", (new, tid))
    await c.answer("✅ Bloklandi" if new else "🔓 Unblock")
    await st_view(c)


@dp.callback_query(F.data.startswith("st_del_ask:"))
async def st_del_ask(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    u = await get_user(tid)
    await c.message.edit_text(f"🗑 <b>{u['full_name']}</b> o'chirilsinmi?",
        reply_markup=confirm_kb(f"st_del_yes:{tid}", "admin_root"))
    await c.answer()


@dp.callback_query(F.data.startswith("st_del_yes:"))
async def st_del_yes(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    await q("DELETE FROM users WHERE tg_id=?", (tid,))
    await q("DELETE FROM submissions WHERE student_id=?", (tid,))
    await q("DELETE FROM user_titles WHERE user_id=?", (tid,))
    await c.message.edit_text("🗑 O'chirildi.")
    await c.answer()


# ==================== 📚 GURUHLAR ====================
@dp.message(F.text == "📚 Guruhlar")
async def grp_root(m: Message):
    if not is_admin(m.from_user.id):
        return
    gs = await all_("SELECT * FROM groups ORDER BY name")
    rows = [("➕ Yangi guruh", "grp_add")]
    for g in gs:
        c_ = await cnt("SELECT COUNT(*) FROM users WHERE group_id=?", (g["id"],))
        rows.append((f"📚 {g['name']} ({c_})", f"grp_view:{g['id']}"))
    await m.answer(f"📚 <b>Guruhlar</b> ({len(gs)})", reply_markup=ikb(rows, back="admin_root"))


@dp.callback_query(F.data == "grp_add")
async def grp_add(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Guruh nomi:", reply_markup=cancel_kb())
    await state.set_state(A.grp_name)
    await c.answer()


@dp.message(A.grp_name)
async def grp_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text)
    await m.answer("Jadval (masalan: Du/Cho/Fr 18:00):", reply_markup=cancel_kb())
    await state.set_state(A.grp_sched)


@dp.message(A.grp_sched)
async def grp_sched(m: Message, state: FSMContext):
    await state.update_data(sched=m.text)
    await m.answer("Tavsif (yoki '-'):", reply_markup=cancel_kb())
    await state.set_state(A.grp_desc)


@dp.message(A.grp_desc)
async def grp_desc(m: Message, state: FSMContext):
    d = await state.get_data()
    try:
        await q("INSERT INTO groups(name,schedule,description,created_at) VALUES(?,?,?,?)",
                (d["name"], d["sched"], m.text, datetime.now().isoformat()))
        await m.answer(f"✅ <b>{d['name']}</b> qo'shildi!", reply_markup=admin_menu())
    except Exception as e:
        await m.answer(f"❌ {e}", reply_markup=admin_menu())
    await state.clear()


@dp.callback_query(F.data.startswith("grp_view:"))
async def grp_view(c: CallbackQuery):
    gid = int(c.data.split(":")[1])
    g = await get_group(gid)
    if not g:
        return await c.answer("Topilmadi", show_alert=True)
    c_ = await cnt("SELECT COUNT(*) FROM users WHERE group_id=?", (gid,))
    h_ = await cnt("SELECT COUNT(*) FROM homework WHERE group_id=?", (gid,))
    m_ = await cnt("SELECT COUNT(*) FROM materials WHERE group_id=?", (gid,))
    t_ = await cnt("SELECT COUNT(*) FROM tests WHERE group_id=?", (gid,))
    a_ = await cnt("SELECT COUNT(*) FROM announcements WHERE group_id=?", (gid,))
    txt = (f"📚 <b>{g['name']}</b>\n{'─'*25}\n"
           f"🗓 {g['schedule'] or '—'}\n📝 {g['description'] or '—'}\n\n"
           f"👥 O'quvchilar: {c_}\n📢 E'lonlar: {a_}\n"
           f"📖 Materiallar: {m_}\n📝 Vazifalar: {h_}\n🎯 Testlar: {t_}")
    rows = [
        ("👥 O'quvchilar", f"st_grp:0:{gid}"),
        ("🎲 Random o'quvchi", f"rand_grp:{gid}"),
        ("📊 Statistika", f"grp_stats:{gid}"),
        ("📢 E'lon yuborish", f"grp_ann:{gid}"),
        ("📖 Materiallar", f"mat_list:0:{gid}"),
        ("📝 Vazifalar", f"hw_list:0:{gid}"),
        ("🎯 Testlar", f"test_list:0:{gid}"),
        ("✏️ Tahrirlash", f"grp_edit:{gid}"),
        ("🗑 O'chirish", f"grp_del_ask:{gid}"),
    ]
    await c.message.answer(txt, reply_markup=ikb(rows, back="admin_root"))
    await c.answer()


@dp.callback_query(F.data.startswith("grp_stats:"))
async def grp_stats(c: CallbackQuery):
    gid = int(c.data.split(":")[1])
    g = await get_group(gid)
    if not g:
        return await c.answer("Topilmadi", show_alert=True)
    total = await cnt("SELECT COUNT(*) FROM users WHERE group_id=?", (gid,))
    week_ago = (datetime.now().date() - timedelta(days=7)).isoformat()
    att = await cnt("""SELECT COUNT(*) FROM attendance
                       WHERE group_id=? AND status='qatnashdi' AND date>=?""",
                    (gid, week_ago))
    subs = await cnt("""SELECT COUNT(*) FROM submissions s
                        JOIN users u ON u.tg_id=s.student_id
                        WHERE u.group_id=? AND s.submitted_at>=?""", (gid, week_ago))
    tests = await cnt("""SELECT COUNT(*) FROM test_results tr
                         JOIN users u ON u.tg_id=tr.student_id
                         WHERE u.group_id=? AND tr.created_at>=?""", (gid, week_ago))
    total_pts = await one("SELECT COALESCE(SUM(points),0) s FROM users WHERE group_id=?",
                          (gid,))
    avg_pts = round(total_pts["s"] / total, 1) if total else 0
    txt = (f"📊 <b>{g['name']}</b> statistikasi\n{'─'*25}\n\n"
           f"👥 O'quvchilar: <b>{total}</b>\n\n"
           f"<b>Oxirgi 7 kun:</b>\n"
           f"✋ Qatnashdi: {att}\n"
           f"📥 Topshiriqlar: {subs}\n"
           f"🎯 Testlar: {tests}\n\n"
           f"⭐ O'rtacha ball: <b>{avg_pts}</b>\n"
           f"📊 Jami ball: {total_pts['s']}")
    await c.message.answer(txt, reply_markup=ikb([("⬅️ Orqaga", "admin_root")]))
    await c.answer()


@dp.callback_query(F.data.startswith("grp_edit:"))
async def grp_edit(c: CallbackQuery):
    gid = int(c.data.split(":")[1])
    rows = [("✏️ Nom", f"grp_e_name:{gid}"), ("🗓 Jadval", f"grp_e_sched:{gid}"),
            ("📝 Tavsif", f"grp_e_desc:{gid}")]
    await c.message.answer("Nimani tahrirlash?", reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("grp_e_name:"))
async def grp_e_name(c: CallbackQuery, state: FSMContext):
    await state.update_data(gid=int(c.data.split(":")[1]))
    await c.message.answer("Yangi nom:", reply_markup=cancel_kb())
    await state.set_state(A.grp_e_name)
    await c.answer()


@dp.message(A.grp_e_name)
async def grp_e_name_do(m: Message, state: FSMContext):
    d = await state.get_data()
    await q("UPDATE groups SET name=? WHERE id=?", (m.text, d["gid"]))
    await state.clear()
    await m.answer("✅", reply_markup=admin_menu())


@dp.callback_query(F.data.startswith("grp_e_sched:"))
async def grp_e_sched(c: CallbackQuery, state: FSMContext):
    await state.update_data(gid=int(c.data.split(":")[1]))
    await c.message.answer("Yangi jadval:", reply_markup=cancel_kb())
    await state.set_state(A.grp_e_sched)
    await c.answer()


@dp.message(A.grp_e_sched)
async def grp_e_sched_do(m: Message, state: FSMContext):
    d = await state.get_data()
    await q("UPDATE groups SET schedule=? WHERE id=?", (m.text, d["gid"]))
    await state.clear()
    await m.answer("✅", reply_markup=admin_menu())


@dp.callback_query(F.data.startswith("grp_e_desc:"))
async def grp_e_desc(c: CallbackQuery, state: FSMContext):
    await state.update_data(gid=int(c.data.split(":")[1]))
    await c.message.answer("Yangi tavsif:", reply_markup=cancel_kb())
    await state.set_state(A.grp_e_desc)
    await c.answer()


@dp.message(A.grp_e_desc)
async def grp_e_desc_do(m: Message, state: FSMContext):
    d = await state.get_data()
    await q("UPDATE groups SET description=? WHERE id=?", (m.text, d["gid"]))
    await state.clear()
    await m.answer("✅", reply_markup=admin_menu())


@dp.callback_query(F.data.startswith("grp_ann:"))
async def grp_ann(c: CallbackQuery, state: FSMContext):
    await state.update_data(gid=int(c.data.split(":")[1]))
    await c.message.answer("E'lon matni:", reply_markup=cancel_kb())
    await state.set_state(A.ann_text)
    await c.answer()


@dp.callback_query(F.data.startswith("grp_del_ask:"))
async def grp_del_ask(c: CallbackQuery):
    gid = int(c.data.split(":")[1])
    g = await get_group(gid)
    c_ = await cnt("SELECT COUNT(*) FROM users WHERE group_id=?", (gid,))
    await c.message.edit_text(f"🗑 <b>{g['name']}</b> o'chirilsinmi?\n⚠️ {c_} ta guruhsiz qoladi!",
        reply_markup=confirm_kb(f"grp_del_yes:{gid}", "admin_root"))
    await c.answer()


@dp.callback_query(F.data.startswith("grp_del_yes:"))
async def grp_del_yes(c: CallbackQuery):
    gid = int(c.data.split(":")[1])
    await q("UPDATE users SET group_id=NULL WHERE group_id=?", (gid,))
    await q("DELETE FROM groups WHERE id=?", (gid,))
    await c.message.edit_text("🗑 O'chirildi.")
    await c.answer()


# ==================== 🎲 RANDOM O'QUVCHI ====================
@dp.message(F.text == "🎲 Random o'quvchi")
async def rand_root(m: Message):
    if not is_admin(m.from_user.id):
        return
    gs = await all_("SELECT * FROM groups")
    if not gs:
        return await m.answer("Guruh yo'q.")
    rows = [("👥 Barcha guruhlar", "rand_grp:0")]
    rows += [(f"📚 {g['name']}", f"rand_grp:{g['id']}") for g in gs]
    await m.answer("🎲 <b>Tasodifiy o'quvchi</b>\nQaysi guruhdan?",
                   reply_markup=ikb(rows, back="admin_root"))


@dp.callback_query(F.data.startswith("rand_grp:"))
async def rand_grp(c: CallbackQuery):
    gid = int(c.data.split(":")[1])
    if gid:
        us = await all_("SELECT * FROM users WHERE group_id=? AND is_blocked=0", (gid,))
    else:
        us = await all_("SELECT * FROM users WHERE role='student' AND is_blocked=0")
    if not us:
        return await c.answer("O'quvchi yo'q", show_alert=True)
    u = random.choice(us)
    ts = await user_titles_str(u["tg_id"])
    uname = f" @{u['username']}" if u['username'] else ""
    txt = (f"🎲 <b>Tasodifiy o'quvchi:</b>\n\n"
           f"👤 <b>{u['full_name']}</b>{uname}\n"
           f"⭐ Ball: {u['points']}\n")
    if ts:
        txt += f"🏅 {ts}\n"
    txt += f"\n🆔 <code>{u['tg_id']}</code>"
    rows = [("🎲 Yana", f"rand_grp:{gid}")]
    await c.message.edit_text(txt, reply_markup=ikb(rows, back="admin_root"))
    await c.answer("🎲")


# ==================== 📢 E'LONLAR ====================
@dp.message(F.text == "📢 E'lonlar")
async def ann_root(m: Message):
    if not is_admin(m.from_user.id):
        return
    anns = await all_("SELECT * FROM announcements ORDER BY is_pinned DESC, created_at DESC LIMIT 20")
    rows = [("➕ Yangi e'lon", "ann_add")]
    for a in anns:
        g = await get_group(a["group_id"]) if a["group_id"] else None
        icon = "📌" if a["is_pinned"] else "📢"
        gn = g["name"] if g else "Hamma"
        txt_short = (a["text"] or "")[:20].replace("\n", " ")
        rows.append((f"{icon} [{gn}] {txt_short}", f"ann_view:{a['id']}"))
    await m.answer(f"📢 <b>E'lonlar</b> ({len(anns)})", reply_markup=ikb(rows, back="admin_root"))


@dp.callback_query(F.data == "ann_add")
async def ann_add(c: CallbackQuery):
    gs = await all_("SELECT * FROM groups")
    rows = [("👥 Hamma", "ann_gid:0")]
    for g in gs:
        rows.append((f"📚 {g['name']}", f"ann_gid:{g['id']}"))
    await c.message.answer("Kimga?", reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("ann_gid:"))
async def ann_gid(c: CallbackQuery, state: FSMContext):
    await state.update_data(gid=int(c.data.split(":")[1]))
    await c.message.answer("E'lon matni:", reply_markup=cancel_kb())
    await state.set_state(A.ann_text)
    await c.answer()


@dp.message(A.ann_text)
async def ann_text(m: Message, state: FSMContext):
    d = await state.get_data()
    gid = d.get("gid")
    gid = gid if gid else None
    await q("INSERT INTO announcements(group_id,text,created_at) VALUES(?,?,?)",
            (gid, m.text, datetime.now().isoformat()))
    if gid:
        us = await all_("SELECT tg_id FROM users WHERE group_id=? AND is_blocked=0", (gid,))
    else:
        us = await all_("SELECT tg_id FROM users WHERE role='student' AND is_blocked=0")
    for u in us:
        await safe_send(u["tg_id"], f"📢 <b>Yangi e'lon!</b>\n\n{m.text}")
        await asyncio.sleep(0.04)
    await m.answer(f"✅ {len(us)} ta", reply_markup=admin_menu())
    await state.clear()


@dp.callback_query(F.data.startswith("ann_view:"))
async def ann_view(c: CallbackQuery):
    aid = int(c.data.split(":")[1])
    a = await one("SELECT * FROM announcements WHERE id=?", (aid,))
    if not a:
        return await c.answer("Topilmadi", show_alert=True)
    g = await get_group(a["group_id"]) if a["group_id"] else None
    txt = (f"{'📌' if a['is_pinned'] else '📢'} <b>E'lon</b>\n"
           f"Kimga: {g['name'] if g else 'Hamma'}\n📅 {a['created_at'][:16]}\n\n{a['text']}")
    rows = [
        ("📌 Unpin" if a["is_pinned"] else "📌 Pin", f"ann_pin:{aid}"),
        ("🗑 O'chirish", f"ann_del_ask:{aid}"),
    ]
    await c.message.answer(txt, reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("ann_pin:"))
async def ann_pin(c: CallbackQuery):
    aid = int(c.data.split(":")[1])
    a = await one("SELECT is_pinned FROM announcements WHERE id=?", (aid,))
    new = 0 if a["is_pinned"] else 1
    await q("UPDATE announcements SET is_pinned=? WHERE id=?", (new, aid))
    await c.answer("📌 Pin" if new else "Unpin")


@dp.callback_query(F.data.startswith("ann_del_ask:"))
async def ann_del_ask(c: CallbackQuery):
    aid = int(c.data.split(":")[1])
    await c.message.edit_text("🗑 O'chirilsinmi?",
        reply_markup=confirm_kb(f"ann_del_yes:{aid}", "admin_root"))
    await c.answer()


@dp.callback_query(F.data.startswith("ann_del_yes:"))
async def ann_del_yes(c: CallbackQuery):
    aid = int(c.data.split(":")[1])
    await q("DELETE FROM announcements WHERE id=?", (aid,))
    await c.message.edit_text("🗑 O'chirildi.")
    await c.answer()


# ==================== 📖 MATERIAL QO'SHISH ====================
@dp.message(F.text == "📖 Materiallar")
async def mats_root(m: Message):
    if not is_admin(m.from_user.id):
        return
    rows = [("➕ Material qo'shish", "mat_add")]
    gs = await all_("SELECT * FROM groups")
    for g in gs:
        c_ = await cnt("SELECT COUNT(*) FROM materials WHERE group_id=?", (g["id"],))
        rows.append((f"📚 {g['name']} ({c_})", f"mat_list:0:{g['id']}"))
    await m.answer("📖 <b>Materiallar</b>", reply_markup=ikb(rows, back="admin_root"))


@dp.callback_query(F.data == "mat_add")
async def mat_add(c: CallbackQuery):
    gs = await all_("SELECT * FROM groups")
    if not gs:
        return await c.answer("Guruh yo'q", show_alert=True)
    rows = [(f"📚 {g['name']}", f"mat_add_g:{g['id']}") for g in gs]
    await c.message.answer("Guruh:", reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("mat_add_g:"))
async def mat_add_g(c: CallbackQuery, state: FSMContext):
    await state.update_data(gid=int(c.data.split(":")[1]))
    await c.message.answer("Sarlavha:", reply_markup=cancel_kb())
    await state.set_state(A.mat_title)
    await c.answer()


@dp.message(A.mat_title)
async def mat_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await m.answer("Matn yoki fayl/rasm/video:", reply_markup=cancel_kb())
    await state.set_state(A.mat_body)


@dp.message(A.mat_body)
async def mat_body(m: Message, state: FSMContext):
    d = await state.get_data()
    text = m.text or m.caption or ""
    fid = ftype = None
    if m.document:
        fid, ftype = m.document.file_id, "doc"
    elif m.video:
        fid, ftype = m.video.file_id, "video"
    elif m.photo:
        fid, ftype = m.photo[-1].file_id, "photo"
    await q("INSERT INTO materials(group_id,title,text,file_id,file_type,created_at) VALUES(?,?,?,?,?,?)",
            (d["gid"], d["title"], text, fid, ftype, datetime.now().isoformat()))
    us = await all_("SELECT tg_id FROM users WHERE group_id=? AND is_blocked=0", (d["gid"],))
    ok = 0
    for u in us:
        try:
            if fid:
                if ftype == "video":
                    await bot.send_video(u["tg_id"], fid, caption=f"📖 <b>{d['title']}</b>\n\n{text}")
                elif ftype == "photo":
                    await bot.send_photo(u["tg_id"], fid, caption=f"📖 <b>{d['title']}</b>\n\n{text}")
                else:
                    await bot.send_document(u["tg_id"], fid, caption=f"📖 <b>{d['title']}</b>\n\n{text}")
            else:
                await bot.send_message(u["tg_id"], f"📖 <b>{d['title']}</b>\n\n{text}")
            ok += 1
        except Exception:
            pass
    await m.answer(f"✅ {ok}/{len(us)}", reply_markup=admin_menu())
    await state.clear()


@dp.callback_query(F.data.startswith("mat_list:"))
async def mat_list(c: CallbackQuery):
    _, page, gid = c.data.split(":")
    page, gid = int(page), int(gid)
    ms = await all_("SELECT * FROM materials WHERE group_id=? ORDER BY is_pinned DESC, created_at DESC", (gid,))
    g = await get_group(gid)
    items = ms[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [(f"{'📌' if x['is_pinned'] else '📄'} {x['title'][:25]}", f"mat_view:{x['id']}") for x in items]
    try:
        await c.message.edit_text(f"📖 <b>{g['name']}</b> — {len(ms)}",
            reply_markup=page_kb(rows, page, len(ms), f"mat_list_x_{gid}", back="admin_root"))
    except Exception:
        pass
    await c.answer()


@dp.callback_query(F.data.startswith("mat_list_x_"))
async def mat_list_x(c: CallbackQuery):
    gid = int(c.data.split("_x_")[1].split(":")[0])
    page = int(c.data.split(":")[-1])
    ms = await all_("SELECT * FROM materials WHERE group_id=? ORDER BY is_pinned DESC, created_at DESC", (gid,))
    g = await get_group(gid)
    items = ms[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [(f"{'📌' if x['is_pinned'] else '📄'} {x['title'][:25]}", f"mat_view:{x['id']}") for x in items]
    try:
        await c.message.edit_text(f"📖 <b>{g['name']}</b> — {len(ms)}",
            reply_markup=page_kb(rows, page, len(ms), f"mat_list_x_{gid}", back="admin_root"))
    except Exception:
        pass
    await c.answer()


@dp.callback_query(F.data.startswith("mat_view:"))
async def mat_view(c: CallbackQuery):
    mid = int(c.data.split(":")[1])
    x = await one("SELECT * FROM materials WHERE id=?", (mid,))
    if not x:
        return await c.answer("Topilmadi", show_alert=True)
    txt = (f"{'📌' if x['is_pinned'] else '📖'} <b>{x['title']}</b>\n\n"
           f"{x['text'] or '(fayl)'}\n\n📅 {x['created_at'][:16]}")
    rows = [
        ("📌 Unpin" if x["is_pinned"] else "📌 Pin", f"mat_pin:{mid}"),
        ("✏️ Sarlavha", f"mat_e_title:{mid}"),
        ("✏️ Matn", f"mat_e_text:{mid}"),
        ("🗑 O'chirish", f"mat_del_ask:{mid}"),
    ]
    await c.message.answer(txt, reply_markup=ikb(rows))
    if x["file_id"]:
        try:
            if x["file_type"] == "video":
                await bot.send_video(c.from_user.id, x["file_id"])
            elif x["file_type"] == "photo":
                await bot.send_photo(c.from_user.id, x["file_id"])
            else:
                await bot.send_document(c.from_user.id, x["file_id"])
        except Exception:
            pass
    await c.answer()


@dp.callback_query(F.data.startswith("mat_pin:"))
async def mat_pin(c: CallbackQuery):
    mid = int(c.data.split(":")[1])
    x = await one("SELECT is_pinned, group_id, title FROM materials WHERE id=?", (mid,))
    new = 0 if x["is_pinned"] else 1
    await q("UPDATE materials SET is_pinned=? WHERE id=?", (new, mid))
    if new:
        us = await all_("SELECT tg_id FROM users WHERE group_id=? AND is_blocked=0", (x["group_id"],))
        for u in us:
            await safe_send(u["tg_id"], f"📌 <b>Muhim material!</b>\n\n{x['title']}")
        await c.answer("📌 Pin + xabar")
    else:
        await c.answer("Unpin")


@dp.callback_query(F.data.startswith("mat_e_title:"))
async def mat_e_title(c: CallbackQuery, state: FSMContext):
    await state.update_data(eid=int(c.data.split(":")[1]))
    await c.message.answer("Yangi sarlavha:", reply_markup=cancel_kb())
    await state.set_state(A.mat_e_title)
    await c.answer()


@dp.message(A.mat_e_title)
async def mat_e_title_do(m: Message, state: FSMContext):
    d = await state.get_data()
    await q("UPDATE materials SET title=? WHERE id=?", (m.text, d["eid"]))
    await state.clear()
    await m.answer("✅", reply_markup=admin_menu())


@dp.callback_query(F.data.startswith("mat_e_text:"))
async def mat_e_text(c: CallbackQuery, state: FSMContext):
    await state.update_data(eid=int(c.data.split(":")[1]))
    await c.message.answer("Yangi matn:", reply_markup=cancel_kb())
    await state.set_state(A.mat_e_text)
    await c.answer()


@dp.message(A.mat_e_text)
async def mat_e_text_do(m: Message, state: FSMContext):
    d = await state.get_data()
    await q("UPDATE materials SET text=? WHERE id=?", (m.text, d["eid"]))
    await state.clear()
    await m.answer("✅", reply_markup=admin_menu())


@dp.callback_query(F.data.startswith("mat_del_ask:"))
async def mat_del_ask(c: CallbackQuery):
    mid = int(c.data.split(":")[1])
    await c.message.edit_text("🗑 O'chirilsinmi?", reply_markup=confirm_kb(f"mat_del_yes:{mid}"))
    await c.answer()


@dp.callback_query(F.data.startswith("mat_del_yes:"))
async def mat_del_yes(c: CallbackQuery):
    mid = int(c.data.split(":")[1])
    await q("DELETE FROM materials WHERE id=?", (mid,))
    await c.message.edit_text("🗑 O'chirildi.")
    await c.answer()


# ==================== 📝 VAZIFALAR ====================
@dp.message(F.text == "📝 Vazifalar")
async def hw_root(m: Message):
    if not is_admin(m.from_user.id):
        return
    rows = [("➕ Yangi vazifa", "hw_add")]
    gs = await all_("SELECT * FROM groups")
    for g in gs:
        c_ = await cnt("SELECT COUNT(*) FROM homework WHERE group_id=?", (g["id"],))
        rows.append((f"📚 {g['name']} ({c_})", f"hw_list:0:{g['id']}"))
    await m.answer("📝 <b>Vazifalar</b>", reply_markup=ikb(rows, back="admin_root"))


@dp.callback_query(F.data == "hw_add")
async def hw_add(c: CallbackQuery):
    gs = await all_("SELECT * FROM groups")
    if not gs:
        return await c.answer("Guruh yo'q", show_alert=True)
    rows = [(f"📚 {g['name']}", f"hw_add_g:{g['id']}") for g in gs]
    await c.message.answer("Guruh:", reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("hw_add_g:"))
async def hw_add_g(c: CallbackQuery, state: FSMContext):
    await state.update_data(gid=int(c.data.split(":")[1]))
    await c.message.answer("Sarlavha:", reply_markup=cancel_kb())
    await state.set_state(A.hw_title)
    await c.answer()


@dp.message(A.hw_title)
async def hw_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await m.answer("Tavsif:", reply_markup=cancel_kb())
    await state.set_state(A.hw_desc)


@dp.message(A.hw_desc)
async def hw_desc(m: Message, state: FSMContext):
    await state.update_data(desc=m.text)
    await m.answer("Muddat (yoki 'yoq'):", reply_markup=cancel_kb())
    await state.set_state(A.hw_deadline)


@dp.message(A.hw_deadline)
async def hw_deadline(m: Message, state: FSMContext):
    d = await state.get_data()
    await q("INSERT INTO homework(group_id,title,description,deadline,created_at) VALUES(?,?,?,?,?)",
            (d["gid"], d["title"], d["desc"], m.text, datetime.now().isoformat()))
    us = await all_("SELECT tg_id FROM users WHERE group_id=? AND is_blocked=0", (d["gid"],))
    for u in us:
        await safe_send(u["tg_id"],
            f"📝 <b>Yangi vazifa!</b>\n\n<b>{d['title']}</b>\n{d['desc']}\n\n⏰ {m.text}")
    await m.answer(f"✅ {len(us)}", reply_markup=admin_menu())
    await state.clear()


@dp.callback_query(F.data.startswith("hw_list:"))
async def hw_list(c: CallbackQuery):
    _, page, gid = c.data.split(":")
    page, gid = int(page), int(gid)
    hs = await all_("SELECT * FROM homework WHERE group_id=? ORDER BY is_pinned DESC, created_at DESC", (gid,))
    g = await get_group(gid)
    items = hs[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [(f"{'📌' if x['is_pinned'] else '📝'} {x['title'][:25]}", f"hw_view:{x['id']}") for x in items]
    try:
        await c.message.edit_text(f"📝 <b>{g['name']}</b> — {len(hs)}",
            reply_markup=page_kb(rows, page, len(hs), f"hw_list_x_{gid}", back="admin_root"))
    except Exception:
        pass
    await c.answer()


@dp.callback_query(F.data.startswith("hw_list_x_"))
async def hw_list_x(c: CallbackQuery):
    gid = int(c.data.split("_x_")[1].split(":")[0])
    page = int(c.data.split(":")[-1])
    hs = await all_("SELECT * FROM homework WHERE group_id=? ORDER BY is_pinned DESC, created_at DESC", (gid,))
    g = await get_group(gid)
    items = hs[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [(f"{'📌' if x['is_pinned'] else '📝'} {x['title'][:25]}", f"hw_view:{x['id']}") for x in items]
    try:
        await c.message.edit_text(f"📝 <b>{g['name']}</b> — {len(hs)}",
            reply_markup=page_kb(rows, page, len(hs), f"hw_list_x_{gid}", back="admin_root"))
    except Exception:
        pass
    await c.answer()


@dp.callback_query(F.data.startswith("hw_view:"))
async def hw_view(c: CallbackQuery):
    hid = int(c.data.split(":")[1])
    h = await one("SELECT * FROM homework WHERE id=?", (hid,))
    if not h:
        return await c.answer("Topilmadi", show_alert=True)
    subs = await cnt("SELECT COUNT(*) FROM submissions WHERE homework_id=?", (hid,))
    pend = await cnt("SELECT COUNT(*) FROM submissions WHERE homework_id=? AND status='pending'", (hid,))
    txt = (f"{'📌' if h['is_pinned'] else '📝'} <b>{h['title']}</b>\n{'─'*25}\n\n"
           f"{h['description']}\n\n⏰ {h['deadline']}\n\n📥 {subs} | ⏳ {pend}")
    rows = [
        ("📥 Topshiriqlarni ko'rish", f"hw_subs:0:{hid}"),
        ("📌 Unpin" if h["is_pinned"] else "📌 Pin", f"hw_pin:{hid}"),
        ("✏️ Sarlavha", f"hw_e_title:{hid}"),
        ("✏️ Tavsif", f"hw_e_desc:{hid}"),
        ("✏️ Muddat", f"hw_e_deadline:{hid}"),
        ("🗑 O'chirish", f"hw_del_ask:{hid}"),
    ]
    await c.message.answer(txt, reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("hw_pin:"))
async def hw_pin(c: CallbackQuery):
    hid = int(c.data.split(":")[1])
    h = await one("SELECT is_pinned, group_id, title FROM homework WHERE id=?", (hid,))
    new = 0 if h["is_pinned"] else 1
    await q("UPDATE homework SET is_pinned=? WHERE id=?", (new, hid))
    if new:
        us = await all_("SELECT tg_id FROM users WHERE group_id=? AND is_blocked=0", (h["group_id"],))
        for u in us:
            await safe_send(u["tg_id"], f"📌 <b>Muhim vazifa!</b>\n\n{h['title']}")
        await c.answer("📌 Pin + xabar")
    else:
        await c.answer("Unpin")


@dp.callback_query(F.data.startswith("hw_e_title:"))
async def hw_e_title(c: CallbackQuery, state: FSMContext):
    await state.update_data(eid=int(c.data.split(":")[1]))
    await c.message.answer("Yangi sarlavha:", reply_markup=cancel_kb())
    await state.set_state(A.hw_e_title)
    await c.answer()


@dp.message(A.hw_e_title)
async def hw_e_title_do(m: Message, state: FSMContext):
    d = await state.get_data()
    await q("UPDATE homework SET title=? WHERE id=?", (m.text, d["eid"]))
    await state.clear()
    await m.answer("✅", reply_markup=admin_menu())


@dp.callback_query(F.data.startswith("hw_e_desc:"))
async def hw_e_desc(c: CallbackQuery, state: FSMContext):
    await state.update_data(eid=int(c.data.split(":")[1]))
    await c.message.answer("Yangi tavsif:", reply_markup=cancel_kb())
    await state.set_state(A.hw_e_desc)
    await c.answer()


@dp.message(A.hw_e_desc)
async def hw_e_desc_do(m: Message, state: FSMContext):
    d = await state.get_data()
    await q("UPDATE homework SET description=? WHERE id=?", (m.text, d["eid"]))
    await state.clear()
    await m.answer("✅", reply_markup=admin_menu())


@dp.callback_query(F.data.startswith("hw_e_deadline:"))
async def hw_e_deadline(c: CallbackQuery, state: FSMContext):
    await state.update_data(eid=int(c.data.split(":")[1]))
    await c.message.answer("Yangi muddat:", reply_markup=cancel_kb())
    await state.set_state(A.hw_e_deadline)
    await c.answer()


@dp.message(A.hw_e_deadline)
async def hw_e_deadline_do(m: Message, state: FSMContext):
    d = await state.get_data()
    await q("UPDATE homework SET deadline=? WHERE id=?", (m.text, d["eid"]))
    await state.clear()
    await m.answer("✅", reply_markup=admin_menu())


@dp.callback_query(F.data.startswith("hw_del_ask:"))
async def hw_del_ask(c: CallbackQuery):
    hid = int(c.data.split(":")[1])
    await c.message.edit_text("🗑 O'chirilsinmi?", reply_markup=confirm_kb(f"hw_del_yes:{hid}"))
    await c.answer()


@dp.callback_query(F.data.startswith("hw_del_yes:"))
async def hw_del_yes(c: CallbackQuery):
    hid = int(c.data.split(":")[1])
    await q("DELETE FROM homework WHERE id=?", (hid,))
    await q("DELETE FROM submissions WHERE homework_id=?", (hid,))
    await c.message.edit_text("🗑 O'chirildi.")
    await c.answer()


# ==================== 🎯 TESTLAR ====================
@dp.message(F.text == "🎯 Testlar")
async def test_root(m: Message):
    if not is_admin(m.from_user.id):
        return
    rows = [("➕ Yangi test", "test_add")]
    gs = await all_("SELECT * FROM groups")
    for g in gs:
        c_ = await cnt("SELECT COUNT(*) FROM tests WHERE group_id=?", (g["id"],))
        rows.append((f"📚 {g['name']} ({c_})", f"test_list:0:{g['id']}"))
    await m.answer("🎯 <b>Testlar</b>", reply_markup=ikb(rows, back="admin_root"))


@dp.callback_query(F.data == "test_add")
async def test_add(c: CallbackQuery):
    gs = await all_("SELECT * FROM groups")
    rows = [(f"📚 {g['name']}", f"test_add_g:{g['id']}") for g in gs]
    await c.message.answer("Guruh:", reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("test_add_g:"))
async def test_add_g(c: CallbackQuery, state: FSMContext):
    await state.update_data(gid=int(c.data.split(":")[1]))
    await c.message.answer("Test sarlavhasi:", reply_markup=cancel_kb())
    await state.set_state(A.test_title)
    await c.answer()


@dp.message(A.test_title)
async def test_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await m.answer("Savol:", reply_markup=cancel_kb())
    await state.set_state(A.test_q)


@dp.message(A.test_q)
async def test_q(m: Message, state: FSMContext):
    await state.update_data(question=m.text)
    await m.answer("Variantlar (vergul bilan):\n<code>Olma, Banan, Uzum, Anor</code>",
                   reply_markup=cancel_kb())
    await state.set_state(A.test_opts)


@dp.message(A.test_opts)
async def test_opts(m: Message, state: FSMContext):
    opts = [o.strip() for o in m.text.split(",") if o.strip()]
    if len(opts) < 2:
        return await m.answer("Kamida 2 ta!")
    await state.update_data(options=opts)
    letters = "ABCDEFGH"
    txt = "To'g'ri javob:\n\n"
    for i, o in enumerate(opts):
        txt += f"<b>{letters[i]})</b> {o}\n"
    rows = [(f"{letters[i]}) {o[:25]}", f"test_ok:{letters[i]}") for i, o in enumerate(opts)]
    await m.answer(txt, reply_markup=ikb(rows))
    await state.set_state(A.test_correct)


@dp.callback_query(F.data.startswith("test_ok:"))
async def test_ok(c: CallbackQuery, state: FSMContext):
    correct = c.data.split(":")[1]
    await state.update_data(correct=correct)
    await c.message.edit_text(f"✅ To'g'ri: <b>{correct}</b>")
    await c.message.answer("Nechi ball?", reply_markup=cancel_kb())
    await state.set_state(A.test_points)
    await c.answer()


@dp.message(A.test_points)
async def test_points(m: Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("Raqam!")
    d = await state.get_data()
    opts_json = json.dumps(d["options"], ensure_ascii=False)
    await q("INSERT INTO tests(group_id,title,question,options,correct,points,created_at) VALUES(?,?,?,?,?,?,?)",
            (d["gid"], d["title"], d["question"], opts_json, d["correct"], int(m.text), datetime.now().isoformat()))
    us = await all_("SELECT tg_id FROM users WHERE group_id=? AND is_blocked=0", (d["gid"],))
    for u in us:
        await safe_send(u["tg_id"], f"🎯 <b>Yangi test!</b>\n\n📝 {d['title']}\n\n👉 Testlar bo'limida")
    await m.answer(f"✅ {len(us)} ta xabar", reply_markup=admin_menu())
    await state.clear()


@dp.callback_query(F.data.startswith("test_list:"))
async def test_list(c: CallbackQuery):
    _, page, gid = c.data.split(":")
    page, gid = int(page), int(gid)
    ts = await all_("SELECT * FROM tests WHERE group_id=? ORDER BY created_at DESC", (gid,))
    g = await get_group(gid)
    items = ts[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [(f"🎯 {x['title'][:25]}", f"test_view:{x['id']}") for x in items]
    try:
        await c.message.edit_text(f"🎯 <b>{g['name']}</b> — {len(ts)}",
            reply_markup=page_kb(rows, page, len(ts), f"test_list_x_{gid}", back="admin_root"))
    except Exception:
        pass
    await c.answer()


@dp.callback_query(F.data.startswith("test_list_x_"))
async def test_list_x(c: CallbackQuery):
    gid = int(c.data.split("_x_")[1].split(":")[0])
    page = int(c.data.split(":")[-1])
    ts = await all_("SELECT * FROM tests WHERE group_id=? ORDER BY created_at DESC", (gid,))
    g = await get_group(gid)
    items = ts[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [(f"🎯 {x['title'][:25]}", f"test_view:{x['id']}") for x in items]
    try:
        await c.message.edit_text(f"🎯 <b>{g['name']}</b> — {len(ts)}",
            reply_markup=page_kb(rows, page, len(ts), f"test_list_x_{gid}", back="admin_root"))
    except Exception:
        pass
    await c.answer()


@dp.callback_query(F.data.startswith("test_view:"))
async def test_view(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    t = await one("SELECT * FROM tests WHERE id=?", (tid,))
    if not t:
        return await c.answer("Topilmadi", show_alert=True)
    try:
        opts = json.loads(t["options"])
    except Exception:
        opts = []
    res_count = await cnt("SELECT COUNT(*) FROM test_results WHERE test_id=?", (tid,))
    correct_count = await cnt("SELECT COUNT(*) FROM test_results WHERE test_id=? AND is_correct=1", (tid,))
    txt = f"🎯 <b>{t['title']}</b>\n{'─'*25}\n\n❓ {t['question']}\n\n"
    for i, o in enumerate(opts):
        letter = "ABCDEFGH"[i]
        mark = "✅" if letter == t["correct"] else "▫️"
        txt += f"{mark} <b>{letter})</b> {o}\n"
    txt += f"\n⭐ Ball: {t['points']}\n📊 Javoblar: {res_count} | ✅ {correct_count}\nHolat: {'🟢' if t['is_active'] else '🔴'}"
    rows = [
        ("🔴 Nofaol" if t["is_active"] else "🟢 Faol", f"test_toggle:{tid}"),
        ("📊 Natijalar", f"test_results:{tid}"),
        ("🗑 O'chirish", f"test_del_ask:{tid}"),
    ]
    await c.message.answer(txt, reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("test_toggle:"))
async def test_toggle(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    t = await one("SELECT is_active FROM tests WHERE id=?", (tid,))
    new = 0 if t["is_active"] else 1
    await q("UPDATE tests SET is_active=? WHERE id=?", (new, tid))
    await c.answer("🟢 Faol" if new else "🔴 Nofaol")


@dp.callback_query(F.data.startswith("test_results:"))
async def test_results(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    rs = await all_("""SELECT tr.*, u.full_name, u.username FROM test_results tr
                       JOIN users u ON u.tg_id=tr.student_id
                       WHERE tr.test_id=? ORDER BY tr.created_at DESC""", (tid,))
    if not rs:
        return await c.answer("Yo'q", show_alert=True)
    txt = f"📊 <b>Natijalar</b> ({len(rs)})\n\n"
    for r in rs:
        icon = "✅" if r["is_correct"] else "❌"
        uname = f" @{r['username']}" if r['username'] else ""
        txt += f"{icon} {r['full_name']}{uname} — {r['answer']}\n"
    await c.message.answer(txt)
    await c.answer()


@dp.callback_query(F.data.startswith("test_del_ask:"))
async def test_del_ask(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    await c.message.edit_text("🗑 O'chirilsinmi?", reply_markup=confirm_kb(f"test_del_yes:{tid}"))
    await c.answer()


@dp.callback_query(F.data.startswith("test_del_yes:"))
async def test_del_yes(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    await q("DELETE FROM tests WHERE id=?", (tid,))
    await q("DELETE FROM test_results WHERE test_id=?", (tid,))
    await c.message.edit_text("🗑 O'chirildi.")
    await c.answer()


# ==================== ✋ DAVOMAT ====================
@dp.message(F.text == "✋ Davomat")
async def att_root(m: Message):
    if not is_admin(m.from_user.id):
        return
    gs = await all_("SELECT * FROM groups")
    if not gs:
        return await m.answer("Guruh yo'q.")
    rows = [("📊 Bugungi davomat ro'yxati", "att_today")]
    rows += [(f"📚 {g['name']}", f"att_grp:{g['id']}") for g in gs]
    await m.answer("✋ <b>Davomat</b>", reply_markup=ikb(rows, back="admin_root"))


@dp.callback_query(F.data == "att_today")
async def att_today(c: CallbackQuery):
    today = datetime.now().date().isoformat()
    rs = await all_("""SELECT a.status, u.full_name, u.username FROM attendance a
                       JOIN users u ON u.tg_id=a.student_id
                       WHERE a.date=? ORDER BY a.created_at DESC""", (today,))
    if not rs:
        return await c.answer("Bugun belgilanmagan", show_alert=True)
    txt = f"📊 <b>Bugungi davomat</b> ({today})\n\n"
    for r in rs:
        icon = "✅" if r["status"] == "qatnashdi" else "❌"
        uname = f" @{r['username']}" if r['username'] else ""
        txt += f"{icon} {r['full_name']}{uname}\n"
    await c.message.answer(txt)
    await c.answer()


@dp.callback_query(F.data.startswith("att_grp:"))
async def att_grp(c: CallbackQuery):
    gid = int(c.data.split(":")[1])
    today = datetime.now().date().isoformat()
    us = await all_("SELECT * FROM users WHERE group_id=? AND is_blocked=0 ORDER BY full_name", (gid,))
    if not us:
        return await c.answer("O'quvchi yo'q", show_alert=True)
    rows = []
    for u in us:
        att = await one("SELECT * FROM attendance WHERE student_id=? AND group_id=? AND date=?",
                        (u["tg_id"], gid, today))
        icon = "✅" if att and att["status"] == "qatnashdi" else ("❌" if att else "▫️")
        rows.append((f"{icon} {un(u)[:25]}", f"att_set:{gid}:{u['tg_id']}"))
    await c.message.answer(f"✋ <b>Bugungi davomat</b>\n📅 {today}\n\nBelgilang:",
                           reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("att_set:"))
async def att_set(c: CallbackQuery):
    _, gid, tid = c.data.split(":")
    gid, tid = int(gid), int(tid)
    rows = [
        ("✅ Qatnashdi", f"att_mark:qatnashdi:{gid}:{tid}"),
        ("❌ Qatnashmadi", f"att_mark:qatnashmadi:{gid}:{tid}"),
    ]
    await c.message.answer("Belgilang:", reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("att_mark:"))
async def att_mark(c: CallbackQuery):
    _, status, gid, tid = c.data.split(":")
    gid, tid = int(gid), int(tid)
    today = datetime.now().date().isoformat()
    old = await one("SELECT id, status FROM attendance WHERE student_id=? AND group_id=? AND date=?",
                    (tid, gid, today))
    if old:
        if old["status"] == status:
            await q("DELETE FROM attendance WHERE id=?", (old["id"],))
            await c.answer("O'chirildi")
            return
        await q("UPDATE attendance SET status=? WHERE id=?", (status, old["id"]))
    else:
        await q("INSERT INTO attendance(group_id,student_id,date,status,created_at) VALUES(?,?,?,?,?)",
                (gid, tid, today, status, datetime.now().isoformat()))
    icon = "✅" if status == "qatnashdi" else "❌"
    await c.answer(f"{icon} Belgilandi")
    if status == "qatnashdi":
        await add_points(tid, 1, "Darsda qatnashdi")


# ==================== 💬 MUROJAATLAR ====================
@dp.message(F.text == "💬 Murojaatlar")
async def appeals_root(m: Message):
    if not is_admin(m.from_user.id):
        return
    as_ = await all_("""SELECT a.*, u.full_name, u.username FROM appeals a
                        JOIN users u ON u.tg_id=a.user_id
                        ORDER BY a.is_read, a.created_at DESC LIMIT 30""")
    if not as_:
        return await m.answer("Murojaat yo'q.", reply_markup=admin_menu())
    rows = []
    for a in as_:
        icon = "🆕" if not a["is_read"] else "📩"
        uname = f"@{a['username']}" if a['username'] else a['full_name'][:12]
        preview = (a["text"] or "")[:20].replace("\n", " ")
        rows.append((f"{icon} {uname}: {preview}", f"appeal_v:{a['id']}"))
    await m.answer(f"💬 <b>Murojaatlar</b> ({len(as_)})",
                   reply_markup=ikb(rows, back="admin_root"))


@dp.callback_query(F.data.startswith("appeal_v:"))
async def appeal_v(c: CallbackQuery):
    aid = int(c.data.split(":")[1])
    a = await one("""SELECT a.*, u.full_name, u.username FROM appeals a
                     JOIN users u ON u.tg_id=a.user_id WHERE a.id=?""", (aid,))
    if not a:
        return await c.answer("Topilmadi", show_alert=True)
    await q("UPDATE appeals SET is_read=1 WHERE id=?", (aid,))
    uname = f"@{a['username']}" if a['username'] else "—"
    txt = (f"💬 <b>Murojaat</b>\n{'─'*25}\n"
           f"👤 {a['full_name']}\n🔗 {uname}\n"
           f"🆔 <code>{a['user_id']}</code>\n"
           f"📅 {a['created_at'][:16]}\n\n{a['text']}")
    rows = [
        ("💌 Javob berish", f"appeal_reply:{a['user_id']}"),
        ("🗑 O'chirish", f"appeal_del:{aid}"),
    ]
    await c.message.answer(txt, reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("appeal_reply:"))
async def appeal_reply(c: CallbackQuery, state: FSMContext):
    uid = int(c.data.split(":")[1])
    await state.update_data(appeal_uid=uid)
    await c.message.answer("Javobingizni yozing:", reply_markup=cancel_kb())
    await state.set_state(A.st_msg)
    await c.answer()


@dp.callback_query(F.data.startswith("appeal_del:"))
async def appeal_del(c: CallbackQuery):
    aid = int(c.data.split(":")[1])
    await q("DELETE FROM appeals WHERE id=?", (aid,))
    await c.message.edit_text("🗑 O'chirildi.")
    await c.answer()


# ==================== ⭐ BALLAR ====================
@dp.message(F.text == "⭐ Ballar")
async def pts_root(m: Message):
    if not is_admin(m.from_user.id):
        return
    us = await all_("SELECT * FROM users WHERE role='student' ORDER BY points DESC LIMIT 20")
    txt = "⭐ <b>Ballar reytingi</b>\n\n"
    for i, u in enumerate(us, 1):
        icon = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
        ts = await user_titles_str(u["tg_id"])
        uname = f" @{u['username']}" if u['username'] else ""
        txt += f"{icon} {u['full_name']}{uname} — <b>{u['points']}</b>\n"
        if ts:
            txt += f"   {ts}\n"
    await m.answer(txt, reply_markup=ikb([("🔄 Yangilash", "pts_refresh")]))


@dp.callback_query(F.data == "pts_refresh")
async def pts_refresh(c: CallbackQuery):
    await c.message.delete()
    await pts_root(c.message)
    await c.answer("✅")


# ==================== 📅 JADVAL ====================
@dp.message(F.text == "📅 Jadval")
async def sched_root(m: Message):
    if not is_admin(m.from_user.id):
        return
    gs = await all_("SELECT * FROM groups")
    if not gs:
        return await m.answer("Guruh yo'q.")
    txt = "📅 <b>Dars jadvali</b>\n\n"
    for g in gs:
        c_ = await cnt("SELECT COUNT(*) FROM users WHERE group_id=?", (g["id"],))
        txt += f"📚 <b>{g['name']}</b> ({c_} o'quvchi)\n🗓 {g['schedule'] or '—'}\n\n"
    await m.answer(txt)


# ==================== 📥 TOPSHIRIQLAR ====================
@dp.message(F.text == "📥 Topshiriqlar")
async def subs_root(m: Message):
    if not is_admin(m.from_user.id):
        return
    pend = await cnt("SELECT COUNT(*) FROM submissions WHERE status='pending'")
    total = await cnt("SELECT COUNT(*) FROM submissions")
    rows = [
        (f"⏳ Tekshirilmagan ({pend})", "subs_list:0:pending"),
        (f"✅ Baholanganlar ({total-pend})", "subs_list:0:graded"),
        (f"📋 Barchasi ({total})", "subs_list:0:all"),
    ]
    await m.answer("📥 <b>Topshiriqlar</b>", reply_markup=ikb(rows, back="admin_root"))


@dp.callback_query(F.data.startswith("subs_list:"))
async def subs_list(c: CallbackQuery):
    _, page, filt = c.data.split(":")
    page = int(page)
    where = {"pending": "WHERE s.status='pending'", "graded": "WHERE s.status='graded'"}.get(filt, "")
    ss = await all_(f"""SELECT s.*, u.full_name, u.username, h.title FROM submissions s
                        JOIN users u ON u.tg_id=s.student_id
                        JOIN homework h ON h.id=s.homework_id
                        {where} ORDER BY s.submitted_at DESC""")
    items = ss[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = []
    for s in items:
        icon = "⏳" if s["status"] == "pending" else "✅"
        rows.append((f"{icon} {s['full_name'][:15]} — {s['title'][:15]}", f"sub_view:{s['id']}"))
    try:
        await c.message.edit_text(f"📥 {filt}: {len(ss)}",
            reply_markup=page_kb(rows, page, len(ss), f"subs_list_x_{filt}", back="subs_root_cb"))
    except Exception:
        pass
    await c.answer()


@dp.callback_query(F.data == "subs_root_cb")
async def subs_root_cb(c: CallbackQuery):
    pend = await cnt("SELECT COUNT(*) FROM submissions WHERE status='pending'")
    total = await cnt("SELECT COUNT(*) FROM submissions")
    rows = [
        (f"⏳ Tekshirilmagan ({pend})", "subs_list:0:pending"),
        (f"✅ Baholanganlar ({total-pend})", "subs_list:0:graded"),
        (f"📋 Barchasi ({total})", "subs_list:0:all"),
    ]
    await c.message.edit_text("📥 <b>Topshiriqlar</b>", reply_markup=ikb(rows, back="admin_root"))
    await c.answer()


@dp.callback_query(F.data.startswith("subs_list_x_"))
async def subs_list_x(c: CallbackQuery):
    parts = c.data.split("_x_")[1].split(":")
    filt, page = parts[0], int(parts[1])
    where = {"pending": "WHERE s.status='pending'", "graded": "WHERE s.status='graded'"}.get(filt, "")
    ss = await all_(f"""SELECT s.*, u.full_name, u.username, h.title FROM submissions s
                        JOIN users u ON u.tg_id=s.student_id
                        JOIN homework h ON h.id=s.homework_id
                        {where} ORDER BY s.submitted_at DESC""")
    items = ss[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = []
    for s in items:
        icon = "⏳" if s["status"] == "pending" else "✅"
        rows.append((f"{icon} {s['full_name'][:15]} — {s['title'][:15]}", f"sub_view:{s['id']}"))
    try:
        await c.message.edit_text(f"📥 {filt}: {len(ss)}",
            reply_markup=page_kb(rows, page, len(ss), f"subs_list_x_{filt}", back="subs_root_cb"))
    except Exception:
        pass
    await c.answer()


@dp.callback_query(F.data.startswith("hw_subs:"))
async def hw_subs(c: CallbackQuery):
    _, page, hid = c.data.split(":")
    page, hid = int(page), int(hid)
    ss = await all_("""SELECT s.*, u.full_name, u.username FROM submissions s
                       JOIN users u ON u.tg_id=s.student_id
                       WHERE s.homework_id=? ORDER BY s.submitted_at DESC""", (hid,))
    if not ss:
        return await c.answer("Yo'q", show_alert=True)
    items = ss[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [(f"{'⏳' if x['status']=='pending' else '✅'} {x['full_name'][:25]}", f"sub_view:{x['id']}") for x in items]
    await c.message.answer(f"📥 {len(ss)}",
                           reply_markup=page_kb(rows, page, len(ss), f"hw_subs_x_{hid}"))
    await c.answer()


@dp.callback_query(F.data.startswith("hw_subs_x_"))
async def hw_subs_x(c: CallbackQuery):
    hid = int(c.data.split("_x_")[1].split(":")[0])
    page = int(c.data.split(":")[-1])
    ss = await all_("""SELECT s.*, u.full_name, u.username FROM submissions s
                       JOIN users u ON u.tg_id=s.student_id
                       WHERE s.homework_id=? ORDER BY s.submitted_at DESC""", (hid,))
    items = ss[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [(f"{'⏳' if x['status']=='pending' else '✅'} {x['full_name'][:25]}", f"sub_view:{x['id']}") for x in items]
    try:
        await c.message.edit_text(f"📥 {len(ss)}",
            reply_markup=page_kb(rows, page, len(ss), f"hw_subs_x_{hid}"))
    except Exception:
        pass
    await c.answer()


@dp.callback_query(F.data.startswith("sub_view:"))
async def sub_view(c: CallbackQuery):
    sid = int(c.data.split(":")[1])
    s = await one("""SELECT s.*, u.full_name, u.username, h.title FROM submissions s
                     JOIN users u ON u.tg_id=s.student_id
                     JOIN homework h ON h.id=s.homework_id WHERE s.id=?""", (sid,))
    if not s:
        return await c.answer("Topilmadi", show_alert=True)
    uname = f"@{s['username']}" if s['username'] else "—"
    txt = (f"👤 <b>{s['full_name']}</b>\n🔗 {uname}\n📝 {s['title']}\n{'─'*25}\n\n"
           f"💬 {s['content'] or '(fayl)'}\n\n"
           f"📅 {s['submitted_at'][:16]}\nHolat: {'⏳' if s['status']=='pending' else '✅'}")
    if s["grade"]:
        txt += f"\n⭐ {s['grade']}"
        if s["points"]:
            txt += f" (+{s['points']})"
        txt += f"\n💭 {s['comment'] or '—'}"
    rows = [(("✏️ Qayta baholash" if s["grade"] else "⭐ Baholash"), f"grade:{sid}")]
    if s["status"] == "graded":
        rows.append(("🔄 Bekor qilish", f"ungrade:{sid}"))
    await c.message.answer(txt, reply_markup=ikb(rows))
    if s["file_id"]:
        try:
            await bot.send_document(c.from_user.id, s["file_id"])
        except Exception:
            pass
    await c.answer()


@dp.callback_query(F.data.startswith("ungrade:"))
async def ungrade(c: CallbackQuery):
    sid = int(c.data.split(":")[1])
    await q("UPDATE submissions SET status='pending', grade=NULL, comment=NULL, points=0 WHERE id=?", (sid,))
    await c.message.edit_text("🔄 Bekor qilindi.")
    await c.answer()


@dp.callback_query(F.data.startswith("grade:"))
async def grade(c: CallbackQuery, state: FSMContext):
    await state.update_data(sid=int(c.data.split(":")[1]))
    await c.message.answer("Baho:", reply_markup=cancel_kb())
    await state.set_state(A.grade_val)
    await c.answer()


@dp.message(A.grade_val)
async def grade_val(m: Message, state: FSMContext):
    await state.update_data(grade=m.text)
    await m.answer("Izoh:", reply_markup=cancel_kb())
    await state.set_state(A.grade_cmt)


@dp.message(A.grade_cmt)
async def grade_cmt(m: Message, state: FSMContext):
    await state.update_data(comment=m.text)
    await m.answer("Nechi ball? (0 = yo'q):", reply_markup=cancel_kb())
    await state.set_state(A.grade_points)


@dp.message(A.grade_points)
async def grade_points(m: Message, state: FSMContext):
    try:
        pts = int(m.text)
    except ValueError:
        return await m.answer("Raqam!")
    d = await state.get_data()
    await q("UPDATE submissions SET status='graded', grade=?, comment=?, points=? WHERE id=?",
            (d["grade"], d["comment"], pts, d["sid"]))
    s = await one("SELECT * FROM submissions WHERE id=?", (d["sid"],))
    txt = f"✅ <b>Baholandi!</b>\n\n⭐ {d['grade']}\n💭 {d['comment']}"
    if pts:
        txt += f"\n\n🎁 +{pts} ball"
    await safe_send(s["student_id"], txt)
    if pts:
        await add_points(s["student_id"], pts, "Vazifa bahosi")
    await m.answer("✅", reply_markup=admin_menu())
    await state.clear()


# ==================== 📢 BROADCAST ====================
@dp.message(F.text == "📢 Xabar yuborish")
async def bc_root(m: Message):
    if not is_admin(m.from_user.id):
        return
    rows = [("👥 Barcha o'quvchilarga", "bc_all"), ("📚 Guruhga", "bc_grp")]
    await m.answer("📢 <b>Xabar</b>\nKimga?", reply_markup=ikb(rows, back="admin_root"))


@dp.callback_query(F.data == "bc_all")
async def bc_all(c: CallbackQuery, state: FSMContext):
    await state.update_data(bc_gid=None)
    await c.message.answer("Xabar:", reply_markup=cancel_kb())
    await state.set_state(A.bc_text)
    await c.answer()


@dp.callback_query(F.data == "bc_grp")
async def bc_grp(c: CallbackQuery):
    gs = await all_("SELECT * FROM groups")
    rows = [(f"📚 {g['name']}", f"bc_grp_sel:{g['id']}") for g in gs]
    await c.message.edit_text("Guruh:", reply_markup=ikb(rows, back="admin_root"))
    await c.answer()


@dp.callback_query(F.data.startswith("bc_grp_sel:"))
async def bc_grp_sel(c: CallbackQuery, state: FSMContext):
    await state.update_data(bc_gid=int(c.data.split(":")[1]))
    await c.message.answer("Xabar:", reply_markup=cancel_kb())
    await state.set_state(A.bc_text)
    await c.answer()


@dp.message(A.bc_text)
async def bc_send(m: Message, state: FSMContext):
    d = await state.get_data()
    if d.get("bc_gid"):
        us = await all_("SELECT tg_id FROM users WHERE group_id=? AND is_blocked=0", (d["bc_gid"],))
    else:
        us = await all_("SELECT tg_id FROM users WHERE role='student' AND is_blocked=0")
    ok = 0
    for u in us:
        if await safe_copy(u["tg_id"], m):
            ok += 1
        await asyncio.sleep(0.04)
    await m.answer(f"✅ {ok}/{len(us)}", reply_markup=admin_menu())
    await state.clear()


# ==================== 📤 EXPORT ====================
@dp.message(Command("export"))
async def export_cmd(m: Message):
    if not is_admin(m.from_user.id):
        return
    await export_report(m)


async def export_report(m: Message):
    us = await all_("""SELECT u.*, g.name as group_name FROM users u
                       LEFT JOIN groups g ON g.id=u.group_id
                       WHERE u.role='student' ORDER BY u.points DESC""")
    if not us:
        return await m.answer("O'quvchi yo'q.")
    import io
    csv = "Ism,Username,ID,Guruh,Ball,Blok,Sana\n"
    for u in us:
        name = (u["full_name"] or "").replace(",", " ")
        uname = (u["username"] or "").replace(",", " ")
        grp = (u["group_name"] or "").replace(",", " ")
        csv += f"{name},{uname},{u['tg_id']},{grp},{u['points'] or 0},{'Ha' if u['is_blocked'] else 'Yoq'},{u['created_at'][:10]}\n"
    buf = io.BytesIO(csv.encode("utf-8-sig"))
    from aiogram.types import BufferedInputFile
    await m.answer_document(
        BufferedInputFile(buf.read(), filename=f"oquvchilar_{datetime.now().date()}.csv"),
        caption=f"📤 <b>Eksport</b>\n\n👥 {len(us)} ta o'quvchi\n📅 {datetime.now().date()}")


# ==================== ⚙️ SOZLAMALAR ====================
@dp.message(F.text == "⚙️ Sozlamalar")
async def settings(m: Message):
    if not is_admin(m.from_user.id):
        return
    total = await cnt("SELECT COUNT(*) FROM users")
    txt = (f"⚙️ <b>Sozlamalar</b>\n\n"
           f"👤 Sizning ID: <code>{m.from_user.id}</code>\n"
           f"👑 Adminlar: {len(ADMIN_IDS)}\n"
           f"👥 Jami foydalanuvchilar: {total}\n"
           f"🗄 Baza: {DB_PATH}")
    rows = [
        ("📤 Baza yuklab olish", "db_dump"),
        ("📊 Batafsil hisobot", "detail_report"),
        ("📥 O'quvchilar (CSV)", "csv_export"),
    ]
    await m.answer(txt, reply_markup=ikb(rows, back="admin_root"))


@dp.callback_query(F.data == "db_dump")
async def db_dump(c: CallbackQuery):
    from aiogram.types import FSInputFile
    try:
        await c.message.answer_document(FSInputFile(DB_PATH), caption="📤 Baza nusxasi")
    except Exception as e:
        await c.message.answer(f"❌ Xato: {e}")
    await c.answer()


@dp.callback_query(F.data == "csv_export")
async def csv_export(c: CallbackQuery):
    await export_report(c.message)
    await c.answer("✅")


@dp.callback_query(F.data == "detail_report")
async def detail_report(c: CallbackQuery):
    today = datetime.now().date()
    week_ago = (today - timedelta(days=7)).isoformat()
    month_ago = (today - timedelta(days=30)).isoformat()
    u_week = await cnt("SELECT COUNT(*) FROM users WHERE created_at >= ?", (week_ago,))
    u_month = await cnt("SELECT COUNT(*) FROM users WHERE created_at >= ?", (month_ago,))
    sub_week = await cnt("SELECT COUNT(*) FROM submissions WHERE submitted_at >= ?", (week_ago,))
    att_week = await cnt("SELECT COUNT(*) FROM attendance WHERE date >= ? AND status='qatnashdi'", (week_ago,))
    tests_week = await cnt("SELECT COUNT(*) FROM test_results WHERE created_at >= ?", (week_ago,))
    tests_ok = await cnt("SELECT COUNT(*) FROM test_results WHERE created_at >= ? AND is_correct=1", (week_ago,))
    titles_given = await cnt("SELECT COUNT(*) FROM user_titles")
    txt = (f"📊 <b>BATAFSIL HISOBOT</b>\n{'─'*25}\n\n"
           f"👥 <b>Yangi o'quvchilar:</b>\n"
           f"   • Haftada: {u_week}\n"
           f"   • Oyida: {u_month}\n\n"
           f"✋ <b>Davomat (hafta):</b> {att_week}\n"
           f"📥 <b>Topshiriqlar (hafta):</b> {sub_week}\n"
           f"🎯 <b>Testlar (hafta):</b> {tests_week} (✅ {tests_ok})\n\n"
           f"🏅 <b>Umumiy berilgan unvonlar:</b> {titles_given}\n")
    await c.message.edit_text(txt, reply_markup=ikb([("⬅️ Orqaga", "admin_root")]))
    await c.answer()


# ==================== ℹ️ YORDAM ====================
@dp.message(F.text == "ℹ️ Yordam")
async def help_(m: Message):
    if is_admin(m.from_user.id):
        txt = ("ℹ️ <b>Admin yordam</b>\n\n"
               "📊 Statistika — umumiy raqamlar\n"
               "👥 O'quvchilar — boshqarish, unvon berish\n"
               "📚 Guruhlar — guruhlar boshqaruvi\n"
               "🏅 Unvonlar — unvon yaratish va berish\n"
               "📢 E'lonlar — e'lon taxtasi\n"
               "📖 Materiallar — pin qilish bilan\n"
               "📝 Vazifalar — pin bilan\n"
               "🎯 Testlar — avtomatik baholash\n"
               "✋ Davomat — qatnashdi/qatnashmadi\n"
               "📥 Topshiriqlar — baholash + ball\n"
               "⭐ Ballar — reyting\n"
               "🎲 Random — tasodifiy o'quvchi\n"
               "💬 Murojaatlar — o'quvchi savollari\n"
               "📢 Xabar — broadcast\n"
               "📅 Jadval — dars jadvali\n"
               "/export — CSV fayl\n\n"
               "❌ Har joyda Bekor qilish bor\n"
               "📌 Material va vazifalarni pin qilish mumkin")
    else:
        txt = ("ℹ️ <b>Yordam</b>\n\n"
               "📢 E'lonlar — yangi e'lonlar\n"
               "📖 Materiallar — darsliklar\n"
               "📝 Vazifalarim — topshirish\n"
               "🎯 Testlar — test ishlash\n"
               "📊 Natijalarim — baholar\n"
               "🏆 Reyting — guruhda o'rin\n"
               "🏅 Unvonlarim — sizning unvonlaringiz\n"
               "👤 Profilim — ma'lumot\n"
               "💬 Adminga yozish — savol\n\n"
               "📌 belgili materiallar — muhim!")
    await m.answer(txt)


# ==================== 🎓 O'QUVCHI PANELI ====================
@dp.message(F.text == "📢 E'lonlar")
async def s_ann(m: Message):
    u = await get_user(m.from_user.id)
    if not u:
        return
    anns = await all_("""SELECT * FROM announcements
                         WHERE group_id IS NULL OR group_id=?
                         ORDER BY is_pinned DESC, created_at DESC LIMIT 20""",
                      (u["group_id"],))
    if not anns:
        return await m.answer("📢 Hozircha e'lon yo'q.")
    for a in anns:
        icon = "📌" if a["is_pinned"] else "📢"
        await m.answer(f"{icon} <b>E'lon</b>\n📅 {a['created_at'][:16]}\n\n{a['text']}")


@dp.message(F.text == "📖 Materiallar")
async def s_mats(m: Message):
    u = await get_user(m.from_user.id)
    if not u or not u["group_id"]:
        return await m.answer("Guruhga biriktirilmagansiz.")
    ms = await all_("SELECT * FROM materials WHERE group_id=? ORDER BY is_pinned DESC, created_at DESC",
                    (u["group_id"],))
    if not ms:
        return await m.answer("📖 Material yo'q.")
    rows = [(f"{'📌' if x['is_pinned'] else '📄'} {x['title'][:30]}", f"s_mat:{x['id']}") for x in ms[:20]]
    await m.answer(f"📖 <b>Materiallar</b> ({len(ms)})", reply_markup=ikb(rows))


@dp.callback_query(F.data.startswith("s_mat:"))
async def s_mat(c: CallbackQuery):
    mid = int(c.data.split(":")[1])
    x = await one("SELECT * FROM materials WHERE id=?", (mid,))
    cap = f"{'📌' if x['is_pinned'] else '📖'} <b>{x['title']}</b>\n\n{x['text'] or ''}"
    if x["file_id"]:
        try:
            if x["file_type"] == "video":
                await bot.send_video(c.from_user.id, x["file_id"], caption=cap[:1024])
            elif x["file_type"] == "photo":
                await bot.send_photo(c.from_user.id, x["file_id"], caption=cap[:1024])
            else:
                await bot.send_document(c.from_user.id, x["file_id"], caption=cap[:1024])
        except Exception:
            await c.message.answer(cap)
    else:
        await c.message.answer(cap)
    await c.answer()


@dp.message(F.text == "📝 Vazifalarim")
async def s_hw(m: Message):
    u = await get_user(m.from_user.id)
    if not u or not u["group_id"]:
        return await m.answer("Guruhga biriktirilmagansiz.")
    hs = await all_("SELECT * FROM homework WHERE group_id=? ORDER BY is_pinned DESC, created_at DESC",
                    (u["group_id"],))
    if not hs:
        return await m.answer("📝 Vazifa yo'q.")
    rows = []
    for h in hs:
        sub = await one("SELECT * FROM submissions WHERE homework_id=? AND student_id=?",
                        (h["id"], m.from_user.id))
        icon = "✅" if sub and sub["status"] == "graded" else ("⏳" if sub else "🆕")
        pin = "📌" if h["is_pinned"] else ""
        rows.append((f"{pin}{icon} {h['title'][:22]} | {h['deadline']}", f"s_hw:{h['id']}"))
    await m.answer("📝 <b>Vazifalarim</b>", reply_markup=ikb(rows))


@dp.callback_query(F.data.startswith("s_hw:"))
async def s_hw_view(c: CallbackQuery):
    hid = int(c.data.split(":")[1])
    h = await one("SELECT * FROM homework WHERE id=?", (hid,))
    sub = await one("SELECT * FROM submissions WHERE homework_id=? AND student_id=?",
                    (hid, c.from_user.id))
    txt = f"{'📌' if h['is_pinned'] else '📝'} <b>{h['title']}</b>\n{'─'*25}\n\n{h['description']}\n\n⏰ {h['deadline']}"
    rows = []
    if sub:
        txt += f"\n\n📤 <b>Javobingiz:</b>\n{sub['content'] or '(fayl)'}\n\n"
        if sub["grade"]:
            txt += f"✅ Baholangan\n⭐ {sub['grade']}"
            if sub["points"]:
                txt += f" (+{sub['points']})"
            txt += f"\n💭 {sub['comment'] or '—'}"
        else:
            txt += "⏳ Tekshirilmoqda..."
        rows.append(("🔁 Qayta topshirish", f"s_sbmt:{hid}"))
    else:
        rows.append(("📤 Topshirish", f"s_sbmt:{hid}"))
    await c.message.answer(txt, reply_markup=ikb(rows))
    await c.answer()


@dp.callback_query(F.data.startswith("s_sbmt:"))
async def s_sbmt(c: CallbackQuery, state: FSMContext):
    await state.update_data(hid=int(c.data.split(":")[1]))
    await c.message.answer("Javob yoki fayl:", reply_markup=cancel_kb())
    await state.set_state(S.submit)
    await c.answer()


@dp.message(S.submit)
async def s_sbmt_save(m: Message, state: FSMContext):
    d = await state.get_data()
    text = m.text or m.caption or ""
    fid = None
    if m.document:
        fid = m.document.file_id
    elif m.photo:
        fid = m.photo[-1].file_id
    elif m.video:
        fid = m.video.file_id
    old = await one("SELECT id FROM submissions WHERE homework_id=? AND student_id=?",
                    (d["hid"], m.from_user.id))
    if old:
        await q("""UPDATE submissions SET content=?, file_id=?, status='pending',
                   grade=NULL, comment=NULL, points=0, submitted_at=? WHERE id=?""",
                (text, fid, datetime.now().isoformat(), old["id"]))
    else:
        await q("""INSERT INTO submissions(homework_id,student_id,content,file_id,submitted_at)
                   VALUES(?,?,?,?,?)""",
                (d["hid"], m.from_user.id, text, fid, datetime.now().isoformat()))
    for aid in ADMIN_IDS:
        await safe_send(aid, f"📥 <b>Yangi topshiriq!</b>\n👤 {m.from_user.full_name}\n"
                             f"🔗 @{m.from_user.username or '—'}")
    await m.answer("✅ Topshirildi!", reply_markup=student_menu())
    await state.clear()


@dp.message(F.text == "🎯 Testlar")
async def s_tests(m: Message):
    u = await get_user(m.from_user.id)
    if not u or not u["group_id"]:
        return await m.answer("Guruhga biriktirilmagansiz.")
    ts = await all_("SELECT * FROM tests WHERE group_id=? AND is_active=1 ORDER BY created_at DESC",
                    (u["group_id"],))
    if not ts:
        return await m.answer("🎯 Faol test yo'q.")
    rows = []
    for t in ts:
        res = await one("SELECT * FROM test_results WHERE test_id=? AND student_id=?",
                        (t["id"], m.from_user.id))
        icon = "✅" if res and res["is_correct"] else ("❌" if res else "🆕")
        rows.append((f"{icon} {t['title'][:25]} ({t['points']}⭐)", f"s_test:{t['id']}"))
    await m.answer(f"🎯 <b>Testlar</b> ({len(ts)})", reply_markup=ikb(rows))


@dp.callback_query(F.data.startswith("s_test:"))
async def s_test(c: CallbackQuery):
    tid = int(c.data.split(":")[1])
    t = await one("SELECT * FROM tests WHERE id=?", (tid,))
    if not t:
        return await c.answer("Topilmadi", show_alert=True)
    res = await one("SELECT * FROM test_results WHERE test_id=? AND student_id=?",
                    (tid, c.from_user.id))
    if res:
        icon = "✅ To'g'ri" if res["is_correct"] else "❌ Noto'g'ri"
        return await c.message.answer(f"🎯 <b>{t['title']}</b>\n\n{icon}\nSizning javob: {res['answer']}")
    try:
        opts = json.loads(t["options"])
    except Exception:
        opts = []
    txt = f"🎯 <b>{t['title']}</b>\n{'─'*25}\n\n❓ {t['question']}\n\n⭐ {t['points']} ball"
    rows = [(f"{'ABCDEFGH'[i]}) {o[:25]}", f"s_ans:{tid}:{'ABCDEFGH'[i]}") for i, o in enumerate(opts)]
    await c.message.answer(txt, reply_markup=ikb(rows))
    await c.answer()

@dp.callback_query(F.data.startswith("s_ans:"))
async def s_ans(c: CallbackQuery):
    _, tid, ans = c.data.split(":")
    tid = int(tid)
    t = await one("SELECT * FROM tests WHERE id=?", (tid,))
    if not t:
        return await c.answer("Topilmadi", show_alert=True)
    is_correct = 1 if ans == t["correct"] else 0
    await q("INSERT INTO test_results(test_id,student_id,answer,is_correct,created_at) VALUES(?,?,?,?,?)",
            (tid, c.from_user.id, ans, is_correct, datetime.now().isoformat()))
    if is_correct:
        await add_points(c.from_user.id, t["points"], f"Test: {t['title']}")
        await c.message.edit_text(f"✅ <b>To'g'ri!</b>\n\n+{t['points']} ball")
    else:
        await c.message.edit_text(f"❌ <b>Noto'g'ri.</b>\n\nTo'g'ri: <b>{t['correct']}</b>")
    await c.answer()


@dp.message(F.text == "📊 Natijalarim")
async def s_results(m: Message):
    ss = await all_("""SELECT s.*, h.title FROM submissions s
                       JOIN homework h ON h.id=s.homework_id
                       WHERE s.student_id=? ORDER BY s.submitted_at DESC""", (m.from_user.id,))
    trs = await all_("""SELECT tr.*, t.title FROM test_results tr
                        JOIN tests t ON t.id=tr.test_id
                        WHERE tr.student_id=? ORDER BY tr.created_at DESC""", (m.from_user.id,))
    att = await cnt("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='qatnashdi'", (m.from_user.id,))
    txt = "📊 <b>Natijalarim</b>\n{'─'*25}\n\n"
    if ss:
        txt += "📝 <b>Vazifalar:</b>\n"
        for s in ss:
            icon = "✅" if s["status"] == "graded" else "⏳"
            txt += f"{icon} {s['title'][:25]}: {s['grade'] or '—'}\n"
        txt += "\n"
    if trs:
        txt += "🎯 <b>Testlar:</b>\n"
        for t in trs:
            icon = "✅" if t["is_correct"] else "❌"
            txt += f"{icon} {t['title'][:25]}\n"
    if not ss and not trs:
        txt += "Hali natijalar yo'q."
    u = await get_user(m.from_user.id)
    ts = await user_titles_str(m.from_user.id)
    txt += f"\n\n✋ Qatnashgan: {att}"
    txt += f"\n⭐ <b>Jami ball:</b> {u['points'] or 0}"
    if ts:
        txt += f"\n🏅 {ts}"
    await m.answer(txt)


@dp.message(F.text == "🏆 Reyting")
async def s_rating(m: Message):
    u = await get_user(m.from_user.id)
    if not u or not u["group_id"]:
        return await m.answer("Guruhga biriktirilmagansiz.")
    top = await all_("""SELECT full_name, username, points, tg_id FROM users
                        WHERE group_id=? ORDER BY points DESC LIMIT 10""",
                     (u["group_id"],))
    txt = "🏆 <b>Guruh reytingi</b>\n\n"
    for i, r in enumerate(top, 1):
        icon = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
        ts = await user_titles_str(r["tg_id"])
        me = " 👈" if r["tg_id"] == m.from_user.id else ""
        txt += f"{icon} {r['full_name']} — {r['points']} ⭐{me}\n"
        if ts:
            txt += f"   {ts}\n"
    all_sorted = await all_("SELECT tg_id FROM users WHERE group_id=? ORDER BY points DESC",
                             (u["group_id"],))
    for i, r in enumerate(all_sorted, 1):
        if r["tg_id"] == m.from_user.id:
            txt += f"\n📍 Sizning o'rningiz: <b>{i}</b>"
            break
    await m.answer(txt)


@dp.message(F.text == "🏅 Unvonlarim")
async def s_my_titles(m: Message):
    rs = await all_("""SELECT t.emoji, t.name, t.description, ut.given_at FROM user_titles ut
                       JOIN titles t ON t.id=ut.title_id
                       WHERE ut.user_id=? ORDER BY ut.given_at DESC""", (m.from_user.id,))
    if not rs:
        return await m.answer("🏅 Sizda hali unvon yo'q.\n\nFaol bo'ling — unvon oling! 💪")
    txt = f"🏅 <b>Mening unvonlarim</b> ({len(rs)})\n{'─'*25}\n\n"
    for r in rs:
        txt += f"{r['emoji']} <b>{r['name']}</b>\n"
        if r['description']:
            txt += f"📝 {r['description']}\n"
        txt += f"📅 {r['given_at'][:10]}\n\n"
    await m.answer(txt)


@dp.message(F.text == "👤 Profilim")
async def s_profile(m: Message):
    u = await get_user(m.from_user.id)
    if not u:
        return await m.answer("Iltimos /start")
    g = await get_group(u["group_id"]) if u["group_id"] else None
    subs = await cnt("SELECT COUNT(*) FROM submissions WHERE student_id=?", (m.from_user.id,))
    graded = await cnt("SELECT COUNT(*) FROM submissions WHERE student_id=? AND status='graded'", (m.from_user.id,))
    tests = await cnt("SELECT COUNT(*) FROM test_results WHERE student_id=? AND is_correct=1", (m.from_user.id,))
    att = await cnt("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='qatnashdi'", (m.from_user.id,))
    titles_cnt = await cnt("SELECT COUNT(*) FROM user_titles WHERE user_id=?", (m.from_user.id,))
    rank = 0
    if u["group_id"]:
        all_sorted = await all_("SELECT tg_id FROM users WHERE group_id=? ORDER BY points DESC",
                                 (u["group_id"],))
        for i, r in enumerate(all_sorted, 1):
            if r["tg_id"] == m.from_user.id:
                rank = i
                break
    ts = await user_titles_str(m.from_user.id)
    uname = f"@{u['username']}" if u['username'] else "—"
    txt = (f"👤 <b>Profilim</b>\n{'─'*25}\n"
           f"Ism: <b>{u['full_name']}</b>\n"
           f"🔗 {uname}\n"
           f"🆔 <code>{u['tg_id']}</code>\n"
           f"📞 {u['phone'] or '—'}\n"
           f"📚 Guruh: <b>{g['name'] if g else '—'}</b>\n"
           f"🏆 Reyting: {rank or '—'}\n\n"
           f"⭐ <b>Ball:</b> {u['points'] or 0}\n"
           f"🏅 <b>Unvonlar:</b> {titles_cnt} ta\n"
           f"   {ts or '—'}\n\n"
           f"📥 Topshiriqlar: {subs} | ✅ {graded}\n"
           f"🎯 To'g'ri testlar: {tests}\n"
           f"✋ Qatnashgan: {att}")
    rows = [("✏️ Ism", "s_e_name"), ("📞 Telefon", "s_e_phone")]
    await m.answer(txt, reply_markup=ikb(rows))


@dp.callback_query(F.data == "s_e_name")
async def s_e_name(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Yangi ism:", reply_markup=cancel_kb())
    await state.set_state(S.edit_name)
    await c.answer()


@dp.message(S.edit_name)
async def s_e_name_do(m: Message, state: FSMContext):
    await q("UPDATE users SET full_name=? WHERE tg_id=?", (m.text, m.from_user.id))
    await state.clear()
    await m.answer("✅", reply_markup=student_menu())


@dp.callback_query(F.data == "s_e_phone")
async def s_e_phone(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Yangi telefon:", reply_markup=cancel_kb())
    await state.set_state(S.edit_phone)
    await c.answer()


@dp.message(S.edit_phone)
async def s_e_phone_do(m: Message, state: FSMContext):
    await q("UPDATE users SET phone=? WHERE tg_id=?", (m.text, m.from_user.id))
    await state.clear()
    await m.answer("✅ Saqlandi.", reply_markup=student_menu())


@dp.message(F.text == "💬 Adminga yozish")
async def s_appeal(m: Message, state: FSMContext):
    await m.answer("💬 Adminga xabaringizni yozing:", reply_markup=cancel_kb())
    await state.set_state(S.appeal)


@dp.message(S.appeal)
async def s_appeal_save(m: Message, state: FSMContext):
    text = m.text or m.caption or ""
    if not text:
        return await m.answer("Iltimos, matn yozing.")
    await q("INSERT INTO appeals(user_id,text,created_at) VALUES(?,?,?)",
            (m.from_user.id, text, datetime.now().isoformat()))
    for aid in ADMIN_IDS:
        await safe_send(aid,
            f"💬 <b>Yangi murojaat!</b>\n"
            f"👤 {m.from_user.full_name}\n"
            f"🔗 @{m.from_user.username or '—'}\n"
            f"🆔 <code>{m.from_user.id}</code>\n\n"
            f"{text[:200]}")
    await state.clear()
    await m.answer("✅ Murojaatingiz adminga yuborildi!", reply_markup=student_menu())


# ==================== MAIN ====================
async def main():
    await init_db()
    print("🤖 Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
import os
import json
import sqlite3
import asyncio
import requests
import threading
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

load_dotenv()

# ============================================================
#  НАСТРОЙКИ
# ============================================================
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
AI_API_KEY = os.getenv("AI_API_KEY")
AI_URL = "https://openrouter.ai/api/v1/chat/completions"
AI_MODEL = "minimax/minimax-m3:free"
ADMIN_ID = 6519043402

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ============================================================
#  БАЗА ДАННЫХ
# ============================================================
DB = "kinoclub.db"

def db_init():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS polls(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT, options TEXT, creator INTEGER)""")
        c.execute("""CREATE TABLE IF NOT EXISTS votes(
            poll_id INTEGER, user_id INTEGER, option INTEGER,
            UNIQUE(poll_id, user_id))""")
db_init()

# ============================================================
#  СОСТОЯНИЯ ДЛЯ СОЗДАНИЯ ОПРОСА
# ============================================================
class CreatePoll(StatesGroup):
    waiting_question = State()
    waiting_options = State()

# ============================================================
#  ИИ-ответ
# ============================================================
def ask_ai(question):
    try:
        r = requests.post(
            AI_URL,
            headers={
                "Authorization": f"Bearer {AI_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost",
                "X-Title": "Kinoclub Bot"
            },
            json={
                "model": AI_MODEL,
                "messages": [{"role": "user", "content": question}]
            },
            timeout=30
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        else:
            return "Извините, техработы, попробуйте позже."
    except Exception as e:
        return "Извините, техработы, попробуйте позже."

# ============================================================
#  МЕНЮ И КОМАНДЫ
# ============================================================
def main_menu_kb():
    kb = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📅 Расписание"), types.KeyboardButton(text="📊 Итоги голосов")],
            [types.KeyboardButton(text="❓ Помощь"), types.KeyboardButton(text="🎬 Спросить ИИ")],
            [types.KeyboardButton(text="📋 Создать опрос")]
        ],
        resize_keyboard=True
    )
    return kb

def cancel_kb():
    kb = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )
    return kb

MENU_BUTTONS = [
    "📅 Расписание", "📊 Итоги голосов", "❓ Помощь", 
    "🎬 Спросить ИИ", "📋 Создать опрос", "❌ Отмена"
]

@dp.message(Command("start"))
@dp.message(Command("меню"))
@dp.message(F.text == "📅 Расписание")
@dp.message(F.text == "📊 Итоги голосов")
@dp.message(F.text == "❓ Помощь")
@dp.message(F.text == "🎬 Спросить ИИ")
@dp.message(F.text == "📋 Создать опрос")
async def cmd_menu(m: types.Message, state: FSMContext):
    if m.text == "📅 Расписание":
        await m.answer(
            "📅 **Расписание киноклуба:**\n"
            "• В 19:00 в любой день по итогам голосования\n"
            "• Место встречи — Кинозал ДК или см. в закрепе канала при изменении\n"
        )
    elif m.text == "📊 Итоги голосов":
        await cmd_results(m)
    elif m.text == "❓ Помощь":
        await m.answer(
            "🤖 **Команды бота КИНОман:**\n\n"
            "• /start или /меню — главное меню\n"
            "• /создать_опрос — создать голосование (только админ)\n"
            "• /активное — показать текущее голосование\n"
            "• /итоги — результаты последнего голосования\n"
            "• /отмена — отменить создание опроса (только админ)\n"
            "• /помощь — эта справка\n\n"
            "💬 **ИИ-помощник:** напиши любой вопрос про кино, и я отвечу!\n"
            "Например: «Какой фильм посоветуешь на вечер?»"
        )
    elif m.text == "🎬 Спросить ИИ":
        await m.answer(
            "Здравствуйте! Я готов помочь. Задавайте ваши вопросы — постараюсь ответить максимально полезно. 😊\n\n"
            "Обращайтесь ко мне — **бро**!"
        )
    elif m.text == "📋 Создать опрос":
        if m.from_user.id != ADMIN_ID:
            await m.answer("⛔ Эта функция доступна только администратору!")
            return
        await m.answer(
            "🎬 **Создание нового голосования**\n\n"
            "Напиши вопрос для голосования, например:\n"
            "«Какой фильм смотрим в пятницу?»\n\n"
            "💡 В любой момент напиши /отмена или нажми ❌ Отмена, чтобы выйти.",
            reply_markup=cancel_kb()
        )
        await state.set_state(CreatePoll.waiting_question)
    else:
        await m.answer(
            "Привет! Я бот КИНОман 🎬\n\n"
            "**Что я умею:**\n"
            "• 📅 Расписание — узнать, когда встречи\n"
            "• 📊 Итоги голосов — результаты последнего голосования\n"
            "• ❓ Помощь — список команд\n"
            "• 📋 Создать опрос — создать новое голосование (админ)\n\n"
            "💬 **А ещё:** я отвечаю на любые вопросы про кино!\n"
            "Просто напиши мне, например: «Какой фильм посоветуешь на вечер?»\n\n"
            "Выбери раздел ниже 👇",
            reply_markup=main_menu_kb()
        )

# ============================================================
#  КОМАНДА: ПОКАЗАТЬ АКТИВНОЕ ГОЛОСОВАНИЕ
# ============================================================
@dp.message(Command("активное"))
async def cmd_active_poll(m: types.Message):
    with sqlite3.connect(DB) as c:
        poll = c.execute(
            "SELECT id, question, options FROM polls ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not poll:
        await m.answer("📭 Сейчас нет активных голосований.")
        return
    pid, q_text, opts = poll
    options = json.loads(opts)
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"{i+1}. {opt}", callback_data=f"vote:{pid}:{i}")]
        for i, opt in enumerate(options)
    ])
    await m.answer(
        f"🗳 **Активное голосование #{pid}**\n\n"
        f"**{q_text}**\n\n"
        "Нажмите кнопку, чтобы проголосовать:",
        reply_markup=kb
    )

# ============================================================
#  КОМАНДА ОТМЕНЫ (только для админа)
# ============================================================
@dp.message(Command("отмена"))
@dp.message(F.text == "❌ Отмена")
async def cmd_cancel(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        await m.answer("⛔ Эта команда доступна только администратору!")
        return
    current_state = await state.get_state()
    if current_state is None:
        await m.answer("ℹ️ Сейчас нечего отменять. Создание опроса не активно.")
        return
    await state.clear()
    await m.answer(
        "❌ **Создание опроса отменено.**\n\n"
        "Меню восстановлено 👇",
        reply_markup=main_menu_kb()
    )

# ============================================================
#  АДМИН-КОМАНДА: СОЗДАНИЕ ОПРОСА
# ============================================================
@dp.message(Command("создать_опрос"))
async def cmd_create_poll(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        await m.answer("⛔ Эта команда доступна только администратору!")
        return
    await m.answer(
        "🎬 **Создание нового голосования**\n\n"
        "Напиши вопрос для голосования, например:\n"
        "«Какой фильм смотрим в пятницу?»\n\n"
        "💡 В любой момент напиши /отмена или нажми ❌ Отмена, чтобы выйти.",
        reply_markup=cancel_kb()
    )
    await state.set_state(CreatePoll.waiting_question)

@dp.message(CreatePoll.waiting_question)
async def process_question(m: types.Message, state: FSMContext):
    if m.text == "❌ Отмена":
        return await cmd_cancel(m, state)
    await state.update_data(question=m.text)
    await m.answer(
        "✅ Вопрос принят!\n\n"
        "Теперь напиши варианты ответов через запятую, например:\n"
        "«Дюна 2, Оппенгеймер, Барби, Бойцовский клуб»\n\n"
        "💡 Для отмены напиши /отмена или нажми ❌ Отмена",
        reply_markup=cancel_kb()
    )
    await state.set_state(CreatePoll.waiting_options)

@dp.message(CreatePoll.waiting_options)
async def process_options(m: types.Message, state: FSMContext):
    if m.text == "❌ Отмена":
        return await cmd_cancel(m, state)
    data = await state.get_data()
    question = data["question"]
    options = [opt.strip() for opt in m.text.split(",") if opt.strip()]
    if len(options) < 2:
        await m.answer("❌ Нужно минимум 2 варианта! Попробуй ещё раз:")
        return
    with sqlite3.connect(DB) as c:
        cur = c.execute(
            "INSERT INTO polls(question, options, creator) VALUES(?,?,?)",
            (question, json.dumps(options, ensure_ascii=False), m.from_user.id)
        )
        poll_id = cur.lastrowid
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"{i+1}. {opt}", callback_data=f"vote:{poll_id}:{i}")]
        for i, opt in enumerate(options)
    ])
    await m.answer(
        f"🗳 **Голосование #{poll_id} создано!**\n\n"
        f"**{question}**\n\n"
        "Нажмите кнопку (анонимно, 1 голос на человека):",
        reply_markup=kb
    )
    await m.answer("Выбери раздел 👇", reply_markup=main_menu_kb())
    await state.clear()

# ============================================================
#  ГОЛОСОВАНИЕ
# ============================================================
@dp.callback_query(F.data.startswith("vote:"))
async def on_vote(q: types.CallbackQuery):
    _, poll_id, opt = q.data.split(":")
    poll_id, opt = int(poll_id), int(opt)
    with sqlite3.connect(DB) as c:
        try:
            c.execute("INSERT INTO votes(poll_id, user_id, option) VALUES(?,?,?)",
                      (poll_id, q.from_user.id, opt))
        except sqlite3.IntegrityError:
            await q.answer("Вы уже голосовали в этом опросе 😉", show_alert=True)
            return
    await q.answer("Голос учтён! Спасибо (анонимно)", show_alert=True)

@dp.message(Command("итоги"))
async def cmd_results(m: types.Message):
    with sqlite3.connect(DB) as c:
        poll = c.execute("SELECT id, question, options FROM polls ORDER BY id DESC LIMIT 1").fetchone()
        if not poll:
            await m.answer("📊 Активных голосований пока нет.")
            return
        pid, q_text, opts = poll
        options = json.loads(opts)
        rows = c.execute(
            "SELECT option, COUNT(*) FROM votes WHERE poll_id=? GROUP BY option", (pid,)
        ).fetchall()
    counts = {i: 0 for i in range(len(options))}
    total = 0
    for o, n in rows:
        counts[o] = n
        total += n
    lines = [f"📊 **Итоги голосования #{pid}**", f"«{q_text}»", ""]
    for i, opt in enumerate(options):
        pct = round(counts[i] / total * 100) if total else 0
        lines.append(f"{opt}: {'█' * counts[i]} {counts[i]} ({pct}%)")
    lines.append(f"\n**Всего голосов: {total}**")
    await m.answer("\n".join(lines))

# ============================================================
#  ЛЮБОЙ ДРУГОЙ ТЕКСТ → ОТВЕТ ИИ
# ============================================================
@dp.message(F.text)
async def free_answer(m: types.Message):
    if m.text and m.text.startswith("/"):
        return
    if m.text in MENU_BUTTONS:
        return
    is_reply_to_bot = (
        m.reply_to_message and 
        m.reply_to_message.from_user.id == bot.id
    )
    bot_username = (await bot.get_me()).username
    mention = f"@{bot_username}"
    trigger_word = "бро"
    is_mentioned = mention in m.text.lower() or trigger_word in m.text.lower()
    is_private = m.chat.type == "private"
    if not (is_reply_to_bot or is_mentioned or is_private):
        return
    await bot.send_chat_action(m.chat.id, "typing")
    await m.answer(ask_ai(m.text))

# ============================================================
#  ЗАПУСК
# ============================================================
app = Flask('')

@app.route('/')
def home():
    return "Бот КИНОман жив и работает! 🎬"

def run_server():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

async def main():
    threading.Thread(target=run_server).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

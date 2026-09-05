import os
import json
import sqlite3
import asyncio
import requests
import threading
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command

# ============================================================
#  НАСТРОЙКИ
# ============================================================
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
AI_API_KEY = os.getenv("AI_API_KEY")
AI_URL     = "https://openrouter.ai/api/v1/chat/completions"
AI_MODEL = "minimax/minimax-m3:free"

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

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
            [types.KeyboardButton(text="/расписание"), types.KeyboardButton(text="/голосовать")],
            [types.KeyboardButton(text="/итоги"), types.KeyboardButton(text="/помощь")]
        ],
        resize_keyboard=True
    )
    return kb

@dp.message(Command("start"))
@dp.message(Command("меню"))
@dp.message(F.text == "/меню")
async def cmd_menu(m: types.Message):
    await m.answer(
        "Привет! Я бот КИНОман 🎬\n\n"
        "**Что я умею:**\n"
        "• /расписание — узнать, когда встречи\n"
        "• /голосовать — создать опрос для выбора фильма или дня\n"
        "• /итоги — посмотреть результаты последнего голосования\n"
        "• /помощь — список всех команд\n\n"
        "💬 **А ещё:** я отвечаю на любые вопросы про кино!\n"
        "Просто напиши мне, например: «Какой фильм посоветуешь на вечер?»\n\n"
        "Выбери раздел ниже ",
        reply_markup=main_menu_kb()
    )

@dp.message(F.text == "/расписание")
async def cmd_schedule(m: types.Message):
    await m.answer(
        "📅 Расписание киноклуба:\n"
        "• В 19:00 в любой день по итогам голосования\n"
        "• Место встречи — Кинозал ДК или см. в закрепе канала при изменении\n"
        )

@dp.message(F.text == "/помощь")
async def cmd_help(m: types.Message):
    await m.answer(
        "Команды:\n/меню — главное меню\n/расписание — когда встречи\n"
        "/голосовать — создать опрос\n/итоги — результаты\n"
        "На любой другой вопрос отвечу как ИИ 💬")

# ============================================================
#  ГОЛОСОВАНИЯ
# ============================================================
@dp.message(F.text == "/голосовать")
async def cmd_vote(m: types.Message):
    question = "В какой день собёремся на фильм?"
    options  = ["Вторник", "Среда", "Четверг", "Пятница", "Воскресенье"]
    with sqlite3.connect(DB) as c:
        cur = c.execute("INSERT INTO polls(question,options,creator) VALUES(?,?,?)",
                        (question, json.dumps(options, ensure_ascii=False), m.from_user.id))
        poll_id = cur.lastrowid
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"{i+1}. {opt}", callback_data=f"vote:{poll_id}:{i}")]
        for i, opt in enumerate(options)    ])
    await m.answer(f"🗳 Голосование #{poll_id}\n\n{question}\n\n"
                   "Нажмите кнопку (анонимно, 1 голос на человека):", reply_markup=kb)

@dp.callback_query(F.data.startswith("vote:"))
async def on_vote(q: types.CallbackQuery):
    _, poll_id, opt = q.data.split(":")
    poll_id, opt = int(poll_id), int(opt)
    with sqlite3.connect(DB) as c:
        try:
            c.execute("INSERT INTO votes(poll_id,user_id,option) VALUES(?,?,?)",
                      (poll_id, q.from_user.id, opt))
        except sqlite3.IntegrityError:
            await q.answer("Вы уже голосовали в этом опросе 😉", show_alert=True)
            return
    await q.answer("Голос учтён! Спасибо 🙌 (анонимно)", show_alert=True)

@dp.message(F.text == "/итоги")
async def cmd_results(m: types.Message):
    with sqlite3.connect(DB) as c:
        poll = c.execute("SELECT id,question,options FROM polls ORDER BY id DESC LIMIT 1").fetchone()
        if not poll:
            await m.answer("Активных голосований пока нет.")
            return
        pid, q_text, opts = poll
        options = json.loads(opts)
        rows = c.execute(
            "SELECT option, COUNT(*) FROM votes WHERE poll_id=? GROUP BY option", (pid,)).fetchall()
    counts = {i: 0 for i in range(len(options))}
    total = 0
    for o, n in rows:
        counts[o] = n; total += n
    lines = [f"📊 Итоги голосования #{pid}", f"«{q_text}»", ""]
    for i, opt in enumerate(options):
        pct = round(counts[i] / total * 100) if total else 0
        lines.append(f"{opt}: {'█'*counts[i]} {counts[i]} ({pct}%)")
    lines.append(f"\nВсего голосов: {total}")
    await m.answer("\n".join(lines))

# ============================================================
#  ЛЮБОЙ ДРУГОЙ ТЕКСТ → ОТВЕТ ИИ
# ============================================================
@dp.message(F.text)
async def free_answer(m: types.Message):
    if m.text and m.text.startswith("/"):
        return
    await bot.send_chat_action(m.chat.id, "typing")
    await m.answer(ask_ai(m.text))

# ============================================================
#  ЗАПУСК (БОТ + МИНИ-СЕРВЕР ДЛЯ RENDER)
# ============================================================
app = Flask('')
@app.route('/')
def home():
    return "Бот КИНОман жив и работает! 🎬"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

async def main():
    # Запускаем сервер в фоне, чтобы Render не убивал процесс
    threading.Thread(target=run_server).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

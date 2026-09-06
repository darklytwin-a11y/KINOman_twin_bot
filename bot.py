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
#  СОСТОЯНИЯ И ИИ
# ============================================================
class CreatePoll(StatesGroup):
    waiting_question = State()
    waiting_options = State()

def ask_ai(question):    try:
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
        return "Извините, техработы, попробуйте позже."
    except Exception:
        return "Извините, техработы, попробуйте позже."

# ============================================================
#  КЛАВИАТУРЫ
# ============================================================
def main_menu_kb():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📅 Расписание"), types.KeyboardButton(text="📊 Итоги голосов")],
            [types.KeyboardButton(text=" Помощь"), types.KeyboardButton(text=" Спросить ИИ")],
            [types.KeyboardButton(text="📋 Создать опрос")]
        ],
        resize_keyboard=True
    )

def cancel_kb():
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

# Ключевые слова для игнорирования в ИИ
MENU_KEYWORDS = ["Расписание", "Итоги голосов", "Помощь", "Спросить ИИ", "Создать опрос", "Отмена"]

# ============================================================
#  ГЛАВНОЕ МЕНЮ И КНОПКИ (Разбито на отдельные функции!)
# ============================================================

@dp.message(Command("start"), Command("меню"))
async def cmd_start(m: types.Message):
    await m.answer(        "Привет! Я бот КИНОман 🎬\n\n"
        "Выбери раздел ниже 👇",
        reply_markup=main_menu_kb()
    )

@dp.message(F.text.endswith("Расписание"))
async def menu_schedule(m: types.Message):
    await m.answer(
        "📅 **Расписание киноклуба:**\n"
        "• В 19:00 в любой день по итогам голосования\n"
        "• Место встречи — Кинозал ДК или см. в закрепе канала при изменении\n"
    )

@dp.message(F.text.endswith("Итоги голосов"))
async def menu_results(m: types.Message):
    await cmd_results(m)

@dp.message(F.text.endswith("Помощь"))
async def menu_help(m: types.Message):
    await m.answer(
        "🤖 **Команды бота КИНОман:**\n\n"
        "• /start или /меню — главное меню\n"
        "• /создать_опрос — создать голосование (только админ)\n"
        "• /активное — показать текущее голосование\n"
        "• /итоги — результаты последнего голосования\n"
        "• /отмена — отменить создание опроса (только админ)\n\n"
        "💬 **ИИ-помощник:** напиши любой вопрос про кино, и я отвечу!\n"
        "Например: «Какой фильм посоветуешь на вечер?»"
    )

@dp.message(F.text.endswith("Спросить ИИ"))
async def menu_ai(m: types.Message):
    await m.answer(
        "Здравствуйте! Я готов помочь. Задавайте ваши вопросы — постараюсь ответить максимально полезно. 😊\n\n"
        "Обращайтесь ко мне — **бро**!\n\n"
        "Например: «Бро, какой фильм посоветуешь на вечер?»"
    )

@dp.message(F.text.endswith("Создать опрос"))
async def menu_create(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        await m.answer("⛔ Эта функция доступна только администратору!")
        return
    
    await m.answer(
        "🎬 **Создание нового голосования**\n\n"
        "Напиши вопрос для голосования, например:\n"
        "«Какой фильм смотрим в пятницу?»\n\n"
        "💡 В любой момент напиши /отмена или нажми ❌ Отмена, чтобы выйти.",
        reply_markup=cancel_kb()    )
    await state.set_state(CreatePoll.waiting_question)

@dp.message(F.text.endswith("Отмена"), Command("отмена"))
async def menu_cancel(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        await m.answer("⛔ Эта команда доступна только администратору!")
        return
    
    current_state = await state.get_state()
    if current_state is None:
        await m.answer("ℹ️ Сейчас нечего отменять.")
        return
    
    await state.clear()
    await m.answer("❌ **Создание опроса отменено.**", reply_markup=main_menu_kb())

# ============================================================
#  СОЗДАНИЕ ОПРОСА (Шаги)
# ============================================================
@dp.message(Command("создать_опрос"))
async def cmd_create_poll(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        await m.answer("⛔ Только админ!")
        return
    await m.answer("Напиши вопрос:", reply_markup=cancel_kb())
    await state.set_state(CreatePoll.waiting_question)

@dp.message(CreatePoll.waiting_question)
async def process_question(m: types.Message, state: FSMContext):
    if m.text and m.text.endswith("Отмена"):
        return await menu_cancel(m, state)
    
    await state.update_data(question=m.text)
    await m.answer(
        "✅ Вопрос принят!\n\nТеперь напиши варианты через запятую:\n«Дюна 2, Оппенгеймер, Барби»",
        reply_markup=cancel_kb()
    )
    await state.set_state(CreatePoll.waiting_options)

@dp.message(CreatePoll.waiting_options)
async def process_options(m: types.Message, state: FSMContext):
    if m.text and m.text.endswith("Отмена"):
        return await menu_cancel(m, state)
    
    data = await state.get_data()
    options = [opt.strip() for opt in m.text.split(",") if opt.strip()]
    
    if len(options) < 2:
        await m.answer("❌ Нужно минимум 2 варианта!")        return
    
    with sqlite3.connect(DB) as c:
        cur = c.execute(
            "INSERT INTO polls(question, options, creator) VALUES(?,?,?)",
            (data["question"], json.dumps(options, ensure_ascii=False), m.from_user.id)
        )
        poll_id = cur.lastrowid
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"{i+1}. {opt}", callback_data=f"vote:{poll_id}:{i}")]
        for i, opt in enumerate(options)
    ])
    
    await m.answer(
        f"🗳 **Голосование #{poll_id} создано!**\n\n**{data['question']}**\n\nНажмите кнопку:",
        reply_markup=kb
    )
    await m.answer("Меню 👇", reply_markup=main_menu_kb())
    await state.clear()

# ============================================================
#  ГОЛОСОВАНИЕ И ИТОГИ
# ============================================================
@dp.callback_query(F.data.startswith("vote:"))
async def on_vote(q: types.CallbackQuery):
    _, poll_id, opt = q.data.split(":")
    poll_id, opt = int(poll_id), int(opt)
    
    with sqlite3.connect(DB) as c:
        try:
            c.execute("INSERT INTO votes(p

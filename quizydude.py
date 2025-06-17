#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import random
import sqlite3
import asyncio
import copy
from contextlib import closing

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, PollAnswer
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command, CommandStart, PollAnswer as PollFilter
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils import rate_limits

# -------------------------------
# PRODUCTION-READY QUIZ BOT (Aiogram)
# - Python 3.13+
# - aiogram v3.0+
# - SQLite3 for persistence
# -------------------------------

# Logging
logging.basicConfig(
    format="%(asctime)s | %(levelname)8s | %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database
DB_PATH = os.environ.get("DATABASE_URL", "quizbot.sqlite3")
with sqlite3.connect(DB_PATH) as conn:
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id   INTEGER PRIMARY KEY,
            username  TEXT,
            wins      INTEGER DEFAULT 0,
            losses    INTEGER DEFAULT 0
        )
    """)

def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)

# Quizzes
quizzes = {
    "xquiz": [("Question X1?", ["A","B","C"], 0)],
    "hquiz": [("Question H1?", ["A","B","C"], 1)],
    "fquiz": [("Question F1?", ["A","B","C"], 2)],
    "lolquiz": [("Question L1?", ["A","B","C"], 0)],
    "cquiz": [("Question C1?", ["A","B","C"], 1)],
    "squiz": [("Question S1?", ["A","B","C"], 2)],
}
all_q = [q for lst in quizzes.values() for q in lst]
quizzes["aquiz"] = all_q

shuffled_quizzes: dict[str, list] = {}
def reset_shuffled(key: str):
    shuffled_quizzes[key] = copy.deepcopy(quizzes[key])
    random.shuffle(shuffled_quizzes[key])
for k in quizzes:
    reset_shuffled(k)

# User management
def ensure_user_sync(user_id: int, username: str):
    with closing(get_connection()) as conn, conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        if not cur.fetchone():
            cur.execute("INSERT INTO users(user_id,username) VALUES(?,?)", (user_id,username))

async def ensure_user(user: types.User):
    await asyncio.to_thread(ensure_user_sync, user.id, user.username or user.full_name)

def update_score(user_id: int, correct: bool):
    with closing(get_connection()) as conn, conn, conn.cursor() as cur:
        if correct:
            cur.execute("UPDATE users SET wins=wins+1 WHERE user_id=?", (user_id,))
        else:
            cur.execute("UPDATE users SET losses=losses+1 WHERE user_id=?", (user_id,))

# Bot setup
BOT_TOKEN = os.environ["BOT_TOKEN"]
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# Rate limit decorator
def rate_limit(limit: int):
    def decorator(func):
        return rate_limits.ThrottlingMiddleware(limit=limit)(func)
    return decorator

# /start handler
@dp.message(CommandStart())
@rate_limit(1)
async def cmd_start(msg: types.Message):
    await ensure_user(msg.from_user)
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="Updates", url="https://t.me/WorkGlows"),
        InlineKeyboardButton(text="Support", url="https://t.me/TheCryptoElders")
    )
    kb.row(InlineKeyboardButton(text="➕ Add to Group", url=f"https://t.me/{(await bot.get_me()).username}?startgroup=true"))
    text = (
        f"👋 Hey {msg.from_user.mention_html()}!\n\n"
        "✨ Welcome to the Ultimate Quiz Challenge Bot! ✨\n\n"
        "🎯 Categories:\n"
        " • /xquiz — Steamy Sex Quiz 🔥\n"
        " • /hquiz — Horny Quiz 😏\n"
        " • /fquiz — Flirty Quiz 💋\n"
        " • /lolquiz — Funny Quiz 😂\n"
        " • /cquiz — Crazy Quiz 🤪\n"
        " • /squiz — Study Quiz 📚\n"
        " • /aquiz — Random Mix 🎲\n\n"
        "🏆 Climb the leaderboard!\n"
        "👉 /help for commands."
    )
    await msg.answer(text, reply_markup=kb.as_markup())

# /help handler
@dp.message(Command(commands=["help"]))
@rate_limit(1)
async def cmd_help(msg: types.Message):
    text = (
        "<b>📚 Quiz Bot Help</b>\n\n"
        "Answer polls to earn wins and avoid losses!\n\n"
        "Commands:\n"
        " • /xquiz /hquiz /fquiz /lolquiz /cquiz /squiz /aquiz\n"
        " • /statistics — Leaderboard 🏆\n"
        " • /help — Show this help"
    )
    await msg.answer(text)

# quiz sender
async def send_quiz(message: types.Message, key: str):
    if not shuffled_quizzes.get(key):
        reset_shuffled(key)
    if not shuffled_quizzes[key]:
        await message.answer("❌ No more questions!")
        return
    q, opts, correct = shuffled_quizzes[key].pop()
    poll = await bot.send_poll(
        chat_id=message.chat.id,
        question=q,
        options=opts,
        type="quiz",
        correct_option_id=correct,
        is_anonymous=False,
        open_period=60,
    )
    # store correct answer in bot_data
    dp.bot_data[poll.poll.id] = correct

# command handlers for each quiz
for cmd in quizzes.keys():
    @dp.message(Command(commands=[cmd]))
    async def _quiz(msg: types.Message, command=cmd):
        await send_quiz(msg, command)

# poll answer handler
@dp.poll_answer(PollFilter())
async def handle_answer(poll_answer: PollAnswer):
    user = poll_answer.user
    await ensure_user(user)
    selected = poll_answer.option_ids[0]
    correct = dp.bot_data.get(poll_answer.poll_id)
    update_score(user.id, selected == correct)

# /statistics handler
@dp.message(Command(commands=["statistics"]))
@rate_limit(1)
async def cmd_stats(msg: types.Message):
    with closing(get_connection()) as conn, conn, conn.cursor() as cur:
        cur.execute(
            "SELECT user_id, username, wins, losses FROM users "
            "ORDER BY wins DESC, losses ASC LIMIT 10"
        )
        rows = cur.fetchall()

    if not rows:
        return await msg.answer("No players yet!")

    text = "<b>🏆 Leaderboard 🏆</b>\n\n"
    for i, (uid, uname, wins, losses) in enumerate(rows, start=1):
        medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}"
        try:
            chat = await bot.get_chat(uid)
            mention = chat.mention_html()
        except TelegramBadRequest:
            mention = f"<i>{uname or 'Unknown'}</i>"
        text += f"{medal} {mention} — W: {wins} | L: {losses}\n"
    await msg.answer(text)

# global error handler
@dp.errors()
async def global_error_handler(update, exception):
    logger.exception("Update: %s\nError: %s", update, exception)

# startup
async def on_startup():
    commands = [
        types.BotCommand(command, cmd.capitalize()) for command in
        ["start","help","xquiz","hquiz","fquiz","lolquiz","cquiz","squiz","aquiz","statistics"]
    ]
    await bot.set_my_commands(commands)
    logger.info("Bot started.")

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot, on_startup=on_startup))
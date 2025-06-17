#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import random
import sqlite3
import asyncio
import copy
from contextlib import closing

from telegram import (
    Update,
    Poll,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    PollAnswerHandler,
    ContextTypes,
    AIORateLimiter,
)

# --------------------------------
# PRODUCTION-READY QUIZ BOT
# - Python 3.13+
# - python-telegram-bot >=20.7
# - SQLite3 for persistence
# --------------------------------

# --- LOGGING SETUP ---
logging.basicConfig(
    format="%(asctime)s | %(levelname)8s | %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- DATABASE SETUP ---
DB_PATH = os.environ.get("DATABASE_URL", "quizbot.sqlite3")
# Ensure WAL mode for concurrency
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
    """Return a thread-safe SQLite connection."""
    return sqlite3.connect(DB_PATH, check_same_thread=False)

# --- QUIZ QUESTIONS SETUP ---
quizzes = {
    "xquiz": [("Question X1?", ["A", "B", "C"], 0)],
    "hquiz": [("Question H1?", ["A", "B", "C"], 1)],
    "fquiz": [("Question F1?", ["A", "B", "C"], 2)],
    "lolquiz": [("Question L1?", ["A", "B", "C"], 0)],
    "cquiz": [("Question C1?", ["A", "B", "C"], 1)],
    "squiz": [("Question S1?", ["A", "B", "C"], 2)],
}
# Merge into “aquiz”
all_questions = [q for lst in quizzes.values() for q in lst]
quizzes["aquiz"] = all_questions

# Prepare shuffled copies
shuffled_quizzes: dict[str, list] = {}
def reset_shuffled(quiz_type: str) -> None:
    shuffled_quizzes[quiz_type] = copy.deepcopy(quizzes[quiz_type])
    random.shuffle(shuffled_quizzes[quiz_type])

for qt in quizzes:
    reset_shuffled(qt)

# --- USER MANAGEMENT ---
def ensure_user_sync(user_id: int, username: str) -> None:
    with closing(get_connection()) as conn, conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO users (user_id, username) VALUES (?, ?)",
                (user_id, username),
            )

async def ensure_user(user_id: int, username: str) -> None:
    await asyncio.to_thread(ensure_user_sync, user_id, username)

def update_score(user_id: int, correct: bool) -> None:
    with closing(get_connection()) as conn, conn, conn.cursor() as cur:
        if correct:
            cur.execute("UPDATE users SET wins = wins + 1 WHERE user_id = ?", (user_id,))
        else:
            cur.execute("UPDATE users SET losses = losses + 1 WHERE user_id = ?", (user_id,))

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await ensure_user(user.id, user.username or user.first_name)

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Updates", url="https://t.me/WorkGlows"),
            InlineKeyboardButton("Support", url="https://t.me/TheCryptoElders"),
        ],
        [
            InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{context.bot.username}?startgroup=true")
        ],
    ])
    welcome = (
        f"👋 Hey {user.mention_html()}!\n\n"
        "✨ Welcome to the Ultimate Quiz Challenge Bot! ✨\n\n"
        "🎯 Choose a category:\n"
        " • /xquiz — Steamy Sex Quiz 🔥\n"
        " • /hquiz — Horny Quiz 😏\n"
        " • /fquiz — Flirty Quiz 💋\n"
        " • /lolquiz — Funny Quiz 😂\n"
        " • /cquiz — Crazy Quiz 🤪\n"
        " • /squiz — Study Quiz 📚\n"
        " • /aquiz — Random Mix 🎲\n\n"
        "🏆 Climb the leaderboard with correct answers!\n"
        "👉 /help for more info."
    )
    await update.message.reply_html(welcome, reply_markup=kb)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    help_text = (
        "<b>📚 Quiz Bot Help</b>\n\n"
        "Answer poll quizzes to earn wins and avoid losses!\n\n"
        "📝 <b>Commands:</b>\n"
        " • /xquiz — Steamy Sex Quiz 🔥\n"
        " • /hquiz — Horny Quiz 😏\n"
        " • /fquiz — Flirty Quiz 💋\n"
        " • /lolquiz — Funny Quiz 😂\n"
        " • /cquiz — Crazy Quiz 🤪\n"
        " • /squiz — Study Quiz 📚\n"
        " • /aquiz — Random Mix 🎲\n"
        " • /statistics — Leaderboard 🏆\n"
        " • /help — This help message\n"
    )
    await update.message.reply_html(help_text)

async def send_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_type: str) -> None:
    if quiz_type not in quizzes:
        return
    if not shuffled_quizzes.get(quiz_type):
        reset_shuffled(quiz_type)
    if not shuffled_quizzes[quiz_type]:
        await update.message.reply_text("❌ No more questions!")
        return

    q, opts, correct = shuffled_quizzes[quiz_type].pop()
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    poll = await context.bot.send_poll(
        chat_id=update.effective_chat.id,
        question=q,
        options=opts,
        type=Poll.QUIZ,
        correct_option_id=correct,
        is_anonymous=False,
        open_period=60,
    )
    context.bot_data[poll.poll.id] = correct

async def xquiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_quiz(update, context, "xquiz")

async def hquiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_quiz(update, context, "hquiz")

async def fquiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_quiz(update, context, "fquiz")

async def lolquiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_quiz(update, context, "lolquiz")

async def cquiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_quiz(update, context, "cquiz")

async def squiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_quiz(update, context, "squiz")

async def aquiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_quiz(update, context, "aquiz")

async def receive_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    answer = update.poll_answer
    user_id = answer.user.id
    selected = answer.option_ids[0]
    correct = context.bot_data.get(answer.poll_id)
    await ensure_user(user_id, answer.user.username or answer.user.first_name)
    update_score(user_id, selected == correct)

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    with closing(get_connection()) as conn, conn, conn.cursor() as cur:
        cur.execute(
            "SELECT user_id, username, wins, losses FROM users "
            "ORDER BY wins DESC, losses ASC LIMIT 10"
        )
        rows = cur.fetchall()

    if not rows:
        await update.message.reply_text("No players yet!")
        return

    text = "<b>🏆 Global Leaderboard 🏆</b>\n\n"
    for idx, (uid, uname, wins, losses) in enumerate(rows, start=1):
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}"
        try:
            chat = await context.bot.get_chat(uid)
            mention = chat.mention_html()
        except:
            mention = f"<i>{uname or 'Unknown'}</i>"
        text += f"{medal} {mention} — W: {wins} | L: {losses}\n"
    await update.message.reply_html(text)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Exception caught in handler: %s", context.error)

# --- MAIN ENTRYPOINT ---
def main() -> None:
    token = os.environ["BOT_TOKEN"]
    app = (
        ApplicationBuilder()
        .token(token)
        .rate_limiter(AIORateLimiter())
        .build()
    )

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("xquiz", xquiz))
    app.add_handler(CommandHandler("hquiz", hquiz))
    app.add_handler(CommandHandler("fquiz", fquiz))
    app.add_handler(CommandHandler("lolquiz", lolquiz))
    app.add_handler(CommandHandler("cquiz", cquiz))
    app.add_handler(CommandHandler("squiz", squiz))
    app.add_handler(CommandHandler("aquiz", aquiz))
    app.add_handler(CommandHandler("statistics", show_statistics))
    app.add_handler(PollAnswerHandler(receive_poll_answer))
    app.add_error_handler(error_handler)

    # Bot commands shown in Telegram UI
    commands = [
        BotCommand("start", "Start the quiz bot"),
        BotCommand("help", "Show help"),
        BotCommand("xquiz", "Steamy Sex Quiz 🔥"),
        BotCommand("hquiz", "Horny Quiz 😏"),
        BotCommand("fquiz", "Flirty Quiz 💋"),
        BotCommand("lolquiz", "Funny Quiz 😂"),
        BotCommand("cquiz", "Crazy Quiz 🤪"),
        BotCommand("squiz", "Study Quiz 📚"),
        BotCommand("aquiz", "Random Mix 🎲"),
        BotCommand("statistics", "Show leaderboard 🏆"),
    ]
    async def set_my_commands(app):
        await app.bot.set_my_commands(commands)
    app.post_init = set_my_commands

    # Run
    logger.info("Starting Quiz Bot...")
    app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
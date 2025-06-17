l#!/usr/bin/env python3
import os
import logging
import random
import copy
import asyncio
import signal
import sys

import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, BotCommand, Poll
from aiogram.filters import Command

# ----------------------------
# Logging configuration
# ----------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------------------
# Database setup
# ----------------------------
DATABASE_PATH = os.environ.get("DATABASE_PATH", "quiz.db")
db: aiosqlite.Connection

async def init_db():
    """Initialize a single long‐lived SQLite connection and ensure the users table exists."""
    global db
    db = await aiosqlite.connect(DATABASE_PATH)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id   INTEGER PRIMARY KEY,
            username  TEXT,
            wins      INTEGER DEFAULT 0,
            losses    INTEGER DEFAULT 0
        )
    """)
    await db.commit()

async def close_db():
    """Close the shared database connection."""
    await db.close()

async def ensure_user(user_id: int, username: str):
    """Insert a new user if not exists."""
    cursor = await db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
    exists = await cursor.fetchone()
    if not exists:
        await db.execute(
            "INSERT INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username)
        )
        await db.commit()

async def update_score(user_id: int, correct: bool):
    """Increment wins or losses for a user."""
    column = "wins" if correct else "losses"
    await db.execute(
        f"UPDATE users SET {column} = {column} + 1 WHERE user_id = ?",
        (user_id,)
    )
    await db.commit()

# ----------------------------
# Quiz data setup
# ----------------------------
quizzes = {
    "xquiz": [("Question X1❔", ["A", "B", "C"], 0)],
    "hquiz": [("Question H1❔", ["A", "B", "C"], 1)],
    "fquiz": [("Question F1❔", ["A", "B", "C"], 2)],
    "lolquiz": [("Question L1❔", ["A", "B", "C"], 0)],
    "cquiz": [("Question C1❔", ["A", "B", "C"], 1)],
    "squiz": [("Question S1❔", ["A", "B", "C"], 2)],
}
# Build the mixed "aquiz"
quizzes["aquiz"] = [q for qs in quizzes.values() for q in qs]

shuffled_quizzes: dict[str, list] = {}

def reset_shuffled(quiz_type: str):
    shuffled_quizzes[quiz_type] = copy.deepcopy(quizzes[quiz_type])
    random.shuffle(shuffled_quizzes[quiz_type])

for qt in quizzes:
    reset_shuffled(qt)

# ----------------------------
# Bot handlers
# ----------------------------
async def cmd_start(message: types.Message):
    user = message.from_user
    await ensure_user(user.id, user.username or user.full_name)

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton(text="Updates", url="https://t.me/WorkGlows"),
        InlineKeyboardButton(text="Support", url="https://t.me/TheCryptoElders"),
    )
    kb.add(
        InlineKeyboardButton(
            text="Add Me To Your Group",
            url=f"https://t.me/{(await bot.get_me()).username}?startgroup=true"
        )
    )

    text = (
        f"👋 Hey {user.get_mention(as_html=True)}!\n\n"
        "✨ Welcome to the Ultimate Quiz Challenge Bot! ✨\n\n"
        "🎯 Categories you can explore:\n"
        " - /xquiz — Steamy Sex Quiz 🔥\n"
        " - /hquiz — Horny Quiz 😏\n"
        " - /fquiz — Flirty Quiz 💋\n"
        " - /lolquiz — Funny Quiz 😂\n"
        " - /cquiz — Crazy Quiz 🤪\n"
        " - /squiz — Study Quiz 📚\n"
        " - /aquiz — Random Mix 🎲\n\n"
        "🏆 Correct answers will boost your rank on the leaderboard!\n"
        "❌ Wrong answers? No worries, practice makes perfect!\n\n"
        "👉 Use /help if you need guidance.\n\n"
        "🎉 LET'S PLAY & HAVE FUN!"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

async def cmd_help(message: types.Message):
    text = (
        "<b>📚 Quiz Bot Help</b>\n\n"
        "📝 <b>Quiz Categories:</b>\n"
        "/xquiz — Sex Quiz 🔥\n"
        "/hquiz — Horny Quiz 😏\n"
        "/fquiz — Flirty Quiz 💋\n"
        "/lolquiz — Funny Quiz 😂\n"
        "/cquiz — Crazy Quiz 🤪\n"
        "/squiz — Study Quiz 📚\n"
        "/aquiz — Random Mixed Quiz 🎲\n\n"
        "🏆 <b>Leaderboard:</b>\n"
        "/statistics — See the current leaderboard 📊\n\n"
        "💡 <b>Tip:</b> Answer polls correctly to climb the leaderboard! 🚀"
    )
    await message.answer(text, parse_mode="HTML")

async def send_quiz(message: types.Message, quiz_type: str):
    if quiz_type not in quizzes:
        return

    if not shuffled_quizzes.get(quiz_type):
        reset_shuffled(quiz_type)
    if not shuffled_quizzes[quiz_type]:
        await message.answer("No more questions in this category!")
        return

    q_text, options, correct_id = shuffled_quizzes[quiz_type].pop()
    try:
        poll_msg = await message.answer_poll(
            question=q_text,
            options=options,
            type=Poll.QUIZ,
            correct_option_id=correct_id,
            is_anonymous=False,
            open_period=60,
        )
        dp.data[poll_msg.poll.id] = {
            "correct_option_id": correct_id,
            "message_id": poll_msg.message_id,
            "chat_id": message.chat.id,
        }
    except Exception as e:
        logger.error("Failed to send quiz poll: %s", e)

# Command shortcuts
async def cmd_xquiz(message: types.Message):  await send_quiz(message, "xquiz")
async def cmd_hquiz(message: types.Message):  await send_quiz(message, "hquiz")
async def cmd_fquiz(message: types.Message):  await send_quiz(message, "fquiz")
async def cmd_lolquiz(message: types.Message):await send_quiz(message, "lolquiz")
async def cmd_cquiz(message: types.Message):  await send_quiz(message, "cquiz")
async def cmd_squiz(message: types.Message):  await send_quiz(message, "squiz")
async def cmd_aquiz(message: types.Message):  await send_quiz(message, "aquiz")

async def handle_poll_answer(event: types.PollAnswer):
    user_id = event.user.id
    selected = event.option_ids[0]
    info = dp.data.get(event.poll_id, {})
    correct = (selected == info.get("correct_option_id", -1))
    await ensure_user(user_id, event.user.username or event.user.full_name)
    await update_score(user_id, correct)

async def cmd_statistics(message: types.Message):
    rows = await db.execute_fetchall(
        "SELECT user_id, username, wins, losses "
        "FROM users ORDER BY wins DESC, losses ASC LIMIT 10"
    )
    if not rows:
        temp = await message.answer("No players yet!")
        await asyncio.sleep(60)
        await temp.delete()
        return

    text = "<b>🏆 Quiz Global Leaderboard 🏆</b>\n\n"
    for i, (uid, username, wins, losses) in enumerate(rows, start=1):
        try:
            user = await bot.get_chat(uid)
            mention = user.get_mention(as_html=True)
        except:
            mention = f"<i>{username or 'Unknown'}</i>"
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}"
        text += f"{medal} {mention} — W: {wins} & L: {losses}\n"

    msg = await message.answer(text, parse_mode="HTML")
    await asyncio.sleep(60)
    await msg.delete()

# ----------------------------
# Main entrypoint
# ----------------------------
async def main():
    global bot, dp
    TOKEN = os.environ["BOT_TOKEN"]
    bot = Bot(TOKEN, parse_mode="HTML")
    dp = Dispatcher()

    # Init DB
    await init_db()

    # Register handlers
    dp.message.register(cmd_start,     Command(commands=["start"]))
    dp.message.register(cmd_help,      Command(commands=["help"]))
    dp.message.register(cmd_xquiz,     Command(commands=["xquiz"]))
    dp.message.register(cmd_hquiz,     Command(commands=["hquiz"]))
    dp.message.register(cmd_fquiz,     Command(commands=["fquiz"]))
    dp.message.register(cmd_lolquiz,   Command(commands=["lolquiz"]))
    dp.message.register(cmd_cquiz,     Command(commands=["cquiz"]))
    dp.message.register(cmd_squiz,     Command(commands=["squiz"]))
    dp.message.register(cmd_aquiz,     Command(commands=["aquiz"]))
    dp.message.register(cmd_statistics,Command(commands=["statistics"]))
    dp.poll_answer.register(handle_poll_answer)

    # Set bot commands
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("help", "How to use the bot"),
        BotCommand("xquiz","Sex Quiz 🔥"),
        BotCommand("hquiz","Horny Quiz 😏"),
        BotCommand("fquiz","Flirty Quiz 💋"),
        BotCommand("lolquiz","Funny Quiz 😂"),
        BotCommand("cquiz","Crazy Quiz 🤪"),
        BotCommand("squiz","Study Quiz 📚"),
        BotCommand("aquiz","Random Quiz 🎲"),
        BotCommand("statistics","Show leaderboard 📊"),
    ]
    await bot.set_my_commands(commands)

    # Graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    # Start polling
    await dp.start_polling(bot)

async def shutdown():
    """Cleanup tasks on shutdown."""
    logger.info("Shutting down, closing database...")
    await close_db()
    await bot.session.close()
    sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
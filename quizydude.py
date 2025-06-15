import os
import logging
import random
import sqlite3
import asyncio
import copy
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, Poll, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, CommandHandler, PollAnswerHandler, ContextTypes

# ─── Logging Setup ──────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.WARNING
)
logger = logging.getLogger(__name__)

# ─── Database Setup ─────────────────────────────
DB_PATH = "quizbot.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    return conn

# ─── Quiz Questions ─────────────────────────────
quizzes = {
    "xquiz": [("Question X1?", ["A", "B", "C"], 0)],
    "hquiz": [("Question H1?", ["A", "B", "C"], 1)],
    "fquiz": [("Question F1?", ["A", "B", "C"], 2)],
    "lolquiz": [("Question L1?", ["A", "B", "C"], 0)],
    "cquiz": [("Question C1?", ["A", "B", "C"], 1)],
    "squiz": [("Question S1?", ["A", "B", "C"], 2)],
}
all_questions = []
for lst in quizzes.values():
    all_questions.extend(lst)
quizzes["aquiz"] = all_questions

shuffled_quizzes = {}
def reset_shuffled(quiz_type):
    shuffled_quizzes[quiz_type] = copy.deepcopy(quizzes[quiz_type])
    random.shuffle(shuffled_quizzes[quiz_type])
for quiz_type in quizzes:
    reset_shuffled(quiz_type)

# ─── User Management ─────────────────────────────
def ensure_user_sync(user_id, username):
    conn_local = get_connection()
    cur = conn_local.cursor()
    try:
        cur.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO users (user_id, username, wins, losses) VALUES (?, ?, 0, 0)",
                (user_id, username),
            )
        conn_local.commit()
    finally:
        cur.close()
        conn_local.close()

async def ensure_user(user_id, username):
    await asyncio.to_thread(ensure_user_sync, user_id, username)

def update_score(user_id: int, correct: bool):
    conn_local = get_connection()
    cur = conn_local.cursor()
    try:
        if correct:
            cur.execute("UPDATE users SET wins = wins + 1 WHERE user_id=?", (user_id,))
        else:
            cur.execute("UPDATE users SET losses = losses + 1 WHERE user_id=?", (user_id,))
        conn_local.commit()
    finally:
        cur.close()
        conn_local.close()

# ─── Command Handlers ─────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await ensure_user(user.id, user.username or user.first_name)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Updates", url="https://t.me/WorkGlows"),
            InlineKeyboardButton("Support", url="https://t.me/TheCryptoElders"),
        ],
        [
            InlineKeyboardButton("Add Me To Your Group", url="https://t.me/quizydudebot?startgroup=true")
        ],
    ])

    msg = (
        f"👋 Hey {user.mention_html()}!\n\n"
        "✨ Welcome to the Ultimate Quiz Challenge Bot! ✨\n\n"
        "🎯 Categories:\n"
        " - 🔥 /xquiz — Steamy Sex Quiz\n"
        " - ❤️ /hquiz — Horny Quiz\n"
        " - 💋 /fquiz — Flirty Quiz\n"
        " - 😂 /lolquiz — Funny Quiz\n"
        " - 🤪 /cquiz — Crazy Quiz\n"
        " - 📚 /squiz — Study Quiz\n"
        " - 🎲 /aquiz — Random Mix\n\n"
        "🏆 Answer right, climb the leaderboard!\n"
        "❌ Wrong? No worries, try again!\n\n"
        "👉 Use /help if needed.\n🎉 LET'S PLAY!"
    )
    await update.message.reply_html(msg, reply_markup=keyboard)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
<b>📚 Quiz Bot Help</b>

📝 <b>Quiz Categories:</b>
- /xquiz <i>Sex Quiz</i> 🔥
- /hquiz <i>Horny Quiz</i> 😏
- /fquiz <i>Flirty Quiz</i> 💋
- /lolquiz <i>Funny Quiz</i> 😂
- /cquiz <i>Crazy Quiz</i> 🤪
- /squiz <i>Study Quiz</i> 📚
- /aquiz <i>Random Mix</i> 🎲

🏆 /statistics — View leaderboard
"""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    await update.message.reply_html(help_text)

async def send_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_type: str):
    if quiz_type not in quizzes:
        return
    if not shuffled_quizzes.get(quiz_type):
        reset_shuffled(quiz_type)
    if not shuffled_quizzes[quiz_type]:
        await update.message.reply_text("No more questions in this category!")
        return

    question = shuffled_quizzes[quiz_type].pop()
    q_text, options, correct_id = question

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    msg = await context.bot.send_poll(
        chat_id=update.effective_chat.id,
        question=q_text,
        options=options,
        type=Poll.QUIZ,
        correct_option_id=correct_id,
        is_anonymous=False,
        allows_multiple_answers=False,
        open_period=60,
    )
    payload = {
        msg.poll.id: {
            "correct_option_id": correct_id,
            "message_id": msg.message_id,
            "chat_id": update.effective_chat.id,
        }
    }
    context.bot_data.update(payload)

async def xquiz(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_quiz(update, context, "xquiz")
async def hquiz(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_quiz(update, context, "hquiz")
async def fquiz(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_quiz(update, context, "fquiz")
async def lolquiz(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_quiz(update, context, "lolquiz")
async def cquiz(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_quiz(update, context, "cquiz")
async def squiz(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_quiz(update, context, "squiz")
async def aquiz(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_quiz(update, context, "aquiz")

async def receive_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    user_id = answer.user.id
    selected = answer.option_ids[0]
    poll_id = answer.poll_id
    correct_option_id = context.bot_data.get(poll_id, {}).get("correct_option_id")
    await ensure_user(user_id, answer.user.username or answer.user.first_name)
    update_score(user_id, correct=(selected == correct_option_id))

async def delete_after_delay(msg, delay: int):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except:
        pass

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    conn_local = get_connection()
    cur = conn_local.cursor()
    try:
        cur.execute("SELECT user_id, username, wins, losses FROM users ORDER BY wins DESC, losses ASC LIMIT 10")
        top_users = cur.fetchall()
    finally:
        cur.close()
        conn_local.close()

    if not top_users:
        msg = await update.message.reply_text("No players yet!")
        asyncio.create_task(delete_after_delay(msg, 60))
        return

    text = "<b>🏆 Quiz Global Leaderboard 🏆</b>\n\n"
    for i, row in enumerate(top_users, start=1):
        uid, username, wins, losses = row["user_id"], row["username"], row["wins"], row["losses"]
        try:
            user = await context.bot.get_chat(uid)
            mention = f"{user.mention_html()}"
        except:
            mention = f"<i>{username or 'Unknown'}</i>"
        icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}"
        text += f"{icon} {mention} — W: {wins} & L: {losses}\n"

    msg = await update.message.reply_html(text)
    asyncio.create_task(delete_after_delay(msg, 60))

# ─── Dummy HTTP Server ─────────────────────────────
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"AFK bot is alive!")

async def start_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    print(f"Dummy server listening on port {port}")
    await asyncio.to_thread(server.serve_forever)

# ─── Main Entrypoint ─────────────────────────────
async def run_bot():
    TOKEN = os.environ.get("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()

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

    async def set_commands(application):
        await application.bot.set_my_commands([
            BotCommand("start", "Start the bot"),
            BotCommand("help", "How to use the bot"),
            BotCommand("xquiz", "Sex Quiz"),
            BotCommand("hquiz", "Horny Quiz"),
            BotCommand("fquiz", "Flirty Quiz"),
            BotCommand("lolquiz", "Funny Quiz"),
            BotCommand("cquiz", "Crazy Quiz"),
            BotCommand("squiz", "Study Quiz"),
            BotCommand("aquiz", "All Random Quiz"),
            BotCommand("statistics", "Show leaderboard"),
        ])
    app.post_init = set_commands

    # Create DB on startup
    conn_init = get_connection()
    cur_init = conn_init.cursor()
    cur_init.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0
        )
    """)
    conn_init.commit()
    cur_init.close()
    conn_init.close()

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

async def main():
    await asyncio.gather(
        run_bot(),
        start_http_server()
    )

if __name__ == "__main__":
    asyncio.run(main())
import os  
import logging  
import random  
import sqlite3  
import asyncio  
import copy  

from telegram import Update, Poll, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup  
from telegram.constants import ChatAction  
from telegram.ext import ApplicationBuilder, CommandHandler, PollAnswerHandler, ContextTypes  

# --------------------------------  
# 1) LOGGING  
# --------------------------------  
logging.basicConfig(  
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  
    level=logging.WARNING  
)  
logger = logging.getLogger(__name__)  

# --------------------------------  
# 2) DATABASE (SQLite)  
# --------------------------------  
DB_PATH = "quiz.db"

def get_connection():  
    return sqlite3.connect(DB_PATH)

# --- QUIZ QUESTIONS PLACEHOLDER ---  
quizzes = {
    "xquiz": [("Question X1?", ["A", "B", "C"], 0)],
    "hquiz": [("Question H1?", ["A", "B", "C"], 1)],
    "fquiz": [("Question F1?", ["A", "B", "C"], 2)],
    "lolquiz": [("Question L1?", ["A", "B", "C"], 0)],
    "cquiz": [("Question C1?", ["A", "B", "C"], 1)],
    "squiz": [("Question S1?", ["A", "B", "C"], 2)],
}

# Merge all quizzes into one
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

# --------------------------------  
# 3) USER MANAGEMENT  
# --------------------------------  
def ensure_user_sync(user_id, username):  
    conn = get_connection()  
    cur = conn.cursor()  
    try:  
        cur.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))  
        if not cur.fetchone():  
            cur.execute(  
                "INSERT INTO users (user_id, username, wins, losses) VALUES (?, ?, 0, 0)",  
                (user_id, username),  
            )  
        conn.commit()  
    finally:  
        cur.close()  
        conn.close()  

async def ensure_user(user_id, username):  
    await asyncio.to_thread(ensure_user_sync, user_id, username)  

def update_score(user_id: int, correct: bool):  
    conn = get_connection()  
    cur = conn.cursor()  
    try:  
        if correct:  
            cur.execute("UPDATE users SET wins = wins + 1 WHERE user_id = ?", (user_id,))  
        else:  
            cur.execute("UPDATE users SET losses = losses + 1 WHERE user_id = ?", (user_id,))  
        conn.commit()  
    finally:  
        cur.close()  
        conn.close()  

# --------------------------------  
# 4) HANDLERS  
# --------------------------------  
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
        " - 🔥 /xquiz\n - ❤️ /hquiz\n - 💋 /fquiz\n - 😂 /lolquiz\n - 🤪 /cquiz\n - 📚 /squiz\n - 🎲 /aquiz\n\n"  
        "🏆 Answer correctly to climb the leaderboard!\n❌ Mistakes help you learn!\n\n"  
        "👉 Use /help for guidance.\n🎉 LET'S PLAY & HAVE FUN!"  
    )  
    await update.message.reply_html(msg, reply_markup=keyboard)  

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):  
    text = """<b>📚 Quiz Bot Help</b>  
  
📝 Quiz Categories:
/xquiz 🔥  /hquiz ❤️  /fquiz 💋  
/lolquiz 😂  /cquiz 🤪  /squiz 📚  
/aquiz 🎲 - Random Mix  

🏆 Leaderboard: /statistics  
💡 Answer polls correctly to win!"""  
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)  
    await update.message.reply_html(text)  

async def send_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_type: str):  
    if quiz_type not in quizzes: return  
    if not shuffled_quizzes.get(quiz_type):  
        reset_shuffled(quiz_type)  
    if not shuffled_quizzes[quiz_type]:  
        await update.message.reply_text("No more questions!")  
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
        open_period=60,  
    )  
    context.bot_data[msg.poll.id] = {  
        "correct_option_id": correct_id,  
        "message_id": msg.message_id,  
        "chat_id": update.effective_chat.id  
    }  

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
    try: await msg.delete()  
    except: pass  

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):  
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)  
    conn = get_connection()  
    cur = conn.cursor()  
    try:  
        cur.execute("SELECT * FROM users ORDER BY wins DESC, losses ASC LIMIT 10")  
        top_users = cur.fetchall()  
    finally:  
        cur.close()  
        conn.close()  
  
    if not top_users:  
        msg = await update.message.reply_text("No players yet!")  
        asyncio.create_task(delete_after_delay(msg, 60))  
        return  
  
    text = "<b>🏆 Quiz Global Leaderboard 🏆</b>\n\n"  
    for i, (uid, username, wins, losses) in enumerate(top_users, start=1):  
        try:  
            user = await context.bot.get_chat(uid)  
            mention = user.mention_html()  
        except:  
            mention = f"<i>{username or 'Unknown'}</i>"  
        icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}"  
        text += f"{icon} {mention} — W: {wins} & L: {losses}\n"  
  
    msg = await update.message.reply_html(text)  
    asyncio.create_task(delete_after_delay(msg, 60))  

# --------------------------------  
# 5) MAIN ENTRYPOINT  
# --------------------------------  
def main():  
    TOKEN = os.environ.get("BOT_TOKEN")  
    app = ApplicationBuilder().token(TOKEN).build()  

    # Create database table (once)  
    conn = get_connection()  
    cur = conn.cursor()  
    cur.execute("""  
        CREATE TABLE IF NOT EXISTS users (  
            user_id INTEGER PRIMARY KEY,  
            username TEXT,  
            wins INTEGER DEFAULT 0,  
            losses INTEGER DEFAULT 0  
        )  
    """)  
    conn.commit()  
    cur.close()  
    conn.close()  

    app.add_handler(CommandHandler("start", start))  
    app.add_handler(CommandHandler("help", help_command))  
    app.add_handler(CommandHandler("xquiz", lambda u, c: send_quiz(u, c, "xquiz")))  
    app.add_handler(CommandHandler("hquiz", lambda u, c: send_quiz(u, c, "hquiz")))  
    app.add_handler(CommandHandler("fquiz", lambda u, c: send_quiz(u, c, "fquiz")))  
    app.add_handler(CommandHandler("lolquiz", lambda u, c: send_quiz(u, c, "lolquiz")))  
    app.add_handler(CommandHandler("cquiz", lambda u, c: send_quiz(u, c, "cquiz")))  
    app.add_handler(CommandHandler("squiz", lambda u, c: send_quiz(u, c, "squiz")))  
    app.add_handler(CommandHandler("aquiz", lambda u, c: send_quiz(u, c, "aquiz")))  
    app.add_handler(CommandHandler("statistics", show_statistics))  
    app.add_handler(PollAnswerHandler(receive_poll_answer))  

    commands = [  
        BotCommand("start", "Start the bot"),  
        BotCommand("help", "How to use the bot"),  
        BotCommand("statistics", "Show leaderboard"),  
    ]  
    async def set_commands(application):  
        await application.bot.set_my_commands(commands)  
    app.post_init = set_commands  

    app.run_polling()  

if __name__ == "__main__":  
    main()
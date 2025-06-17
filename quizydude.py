import os
import logging
import random
import copy
import asyncio
import signal
import sys
from typing import Dict, List, Tuple, Optional, Any

import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from aiogram.enums import PollType, ParseMode
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

# ----------------------------
# Logging configuration
# ----------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("quiz_bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# ----------------------------
# Configuration
# ----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "quiz.db")
POLL_TIMEOUT = int(os.getenv("POLL_TIMEOUT", "60"))
LEADERBOARD_SIZE = int(os.getenv("LEADERBOARD_SIZE", "10"))
MESSAGE_DELETE_DELAY = int(os.getenv("MESSAGE_DELETE_DELAY", "60"))

if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable is required!")
    sys.exit(1)

# ----------------------------
# Global variables
# ----------------------------
db: Optional[aiosqlite.Connection] = None
bot: Optional[Bot] = None
dp = Dispatcher()

# ----------------------------
# Database setup and management
# ----------------------------
async def init_db() -> None:
    """Initialize database connection and create tables if they don't exist."""
    global db
    try:
        db = await aiosqlite.connect(DATABASE_PATH)
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id   INTEGER PRIMARY KEY,
                username  TEXT,
                first_name TEXT,
                last_name TEXT,
                wins      INTEGER DEFAULT 0,
                losses    INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS quiz_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id TEXT UNIQUE,
                correct_option_id INTEGER,
                message_id INTEGER,
                chat_id INTEGER,
                quiz_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

async def close_db() -> None:
    """Close the database connection."""
    global db
    if db:
        try:
            await db.close()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error(f"Error closing database: {e}")

async def ensure_user(user_id: int, username: Optional[str] = None, 
                     first_name: Optional[str] = None, last_name: Optional[str] = None) -> None:
    """Insert or update user information."""
    if not db:
        raise RuntimeError("Database not initialized")
    
    try:
        await db.execute(
            """INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, wins, losses, created_at, updated_at) 
               VALUES (?, ?, ?, ?, 
                       COALESCE((SELECT wins FROM users WHERE user_id = ?), 0),
                       COALESCE((SELECT losses FROM users WHERE user_id = ?), 0),
                       COALESCE((SELECT created_at FROM users WHERE user_id = ?), CURRENT_TIMESTAMP),
                       CURRENT_TIMESTAMP)""",
            (user_id, username, first_name, last_name, user_id, user_id, user_id)
        )
        await db.commit()
    except Exception as e:
        logger.error(f"Error ensuring user {user_id}: {e}")
        raise

async def update_score(user_id: int, correct: bool) -> None:
    """Update user's score (wins/losses)."""
    if not db:
        raise RuntimeError("Database not initialized")
    
    try:
        column = "wins" if correct else "losses"
        await db.execute(
            f"UPDATE users SET {column} = {column} + 1, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()
        logger.info(f"Updated score for user {user_id}: {'win' if correct else 'loss'}")
    except Exception as e:
        logger.error(f"Error updating score for user {user_id}: {e}")
        raise

async def store_poll_session(poll_id: str, correct_option_id: int, message_id: int, 
                           chat_id: int, quiz_type: str) -> None:
    """Store poll session data."""
    if not db:
        raise RuntimeError("Database not initialized")
    
    try:
        await db.execute(
            """INSERT OR REPLACE INTO quiz_sessions 
               (poll_id, correct_option_id, message_id, chat_id, quiz_type) 
               VALUES (?, ?, ?, ?, ?)""",
            (poll_id, correct_option_id, message_id, chat_id, quiz_type)
        )
        await db.commit()
    except Exception as e:
        logger.error(f"Error storing poll session {poll_id}: {e}")
        raise

async def get_poll_session(poll_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve poll session data."""
    if not db:
        raise RuntimeError("Database not initialized")
    
    try:
        cursor = await db.execute(
            """SELECT correct_option_id, message_id, chat_id, quiz_type 
               FROM quiz_sessions WHERE poll_id = ?""",
            (poll_id,)
        )
        row = await cursor.fetchone()
        if row:
            return {
                "correct_option_id": row[0],
                "message_id": row[1],
                "chat_id": row[2],
                "quiz_type": row[3]
            }
        return None
    except Exception as e:
        logger.error(f"Error retrieving poll session {poll_id}: {e}")
        return None

# ----------------------------
# Quiz data and management
# ----------------------------
QUIZ_DATA: Dict[str, List[Tuple[str, List[str], int]]] = {
    "xquiz": [
        ("What's the most important thing in a romantic relationship? 💕", 
         ["Communication", "Physical attraction", "Money"], 0),
        ("Which factor matters most for intimacy? 🔥", 
         ["Trust", "Experience", "Looks"], 0),
        ("What makes a relationship last? 💑", 
         ["Mutual respect", "Great chemistry", "Similar interests"], 0),
        ("Best way to resolve conflicts in relationships? 🤝", 
         ["Open communication", "Ignoring the issue", "Compromise"], 0),
        ("What builds stronger emotional connection? 💞", 
         ["Shared experiences", "Physical attraction", "Financial stability"], 0),
    ],
    "hquiz": [
        ("What's the key to attraction? 😏", 
         ["Confidence", "Appearance", "Wealth"], 0),
        ("Which compliment works best? 💋", 
         ["You're intelligent", "You're gorgeous", "You're funny"], 0),
        ("What's most appealing in a partner? 🔥", 
         ["Sense of humor", "Physical fitness", "Success"], 0),
        ("Best way to show genuine interest? 😍", 
         ["Active listening", "Expensive gifts", "Physical compliments"], 0),
        ("What creates lasting attraction? ✨", 
         ["Emotional connection", "Physical appearance", "Social status"], 0),
    ],
    "fquiz": [
        ("Best way to show interest? 💕", 
         ["Genuine conversation", "Expensive gifts", "Physical gestures"], 0),
        ("Most attractive quality? ✨", 
         ["Kindness", "Confidence", "Wealth"], 0),
        ("Perfect first date activity? 💫", 
         ["Coffee and conversation", "Fancy restaurant", "Adventure activity"], 0),
        ("How to make someone feel special? 🌟", 
         ["Remember small details", "Buy expensive things", "Constant compliments"], 0),
        ("Best flirting technique? 😊", 
         ["Playful teasing", "Direct approach", "Showing off"], 0),
    ],
    "lolquiz": [
        ("Why don't scientists trust atoms? 🤔", 
         ["Because they make up everything", "They're too small", "They're unstable"], 0),
        ("What do you call a bear with no teeth? 😂", 
         ["A gummy bear", "A sad bear", "A hungry bear"], 0),
        ("Why did the scarecrow win an award? 🏆", 
         ["He was outstanding in his field", "He was very scary", "He worked hard"], 0),
        ("What do you call a fake noodle? 🍜", 
         ["An impasta", "A fake pasta", "A lie noodle"], 0),
        ("Why don't eggs tell jokes? 🥚", 
         ["They'd crack each other up", "They're too serious", "They can't talk"], 0),
    ],
    "cquiz": [
        ("What's the craziest thing humans do? 🤪", 
         ["Pay for water in bottles", "Work to live", "Sleep 8 hours daily"], 0),
        ("Most absurd invention? 🙃", 
         ["Silent alarm clock", "Waterproof tea bags", "Solar-powered flashlight"], 0),
        ("Weirdest human behavior? 🤨", 
         ["Saying 'what' when we heard clearly", "Checking the fridge multiple times", "Both are equally weird"], 2),
        ("Strangest thing people collect? 🗂️", 
         ["Belly button lint", "Used tissues", "Expired coupons"], 0),
        ("Most ridiculous fear? 😱", 
         ["Fear of long words (Hippopotomonstrosesquippedaliophobia)", "Fear of clowns", "Fear of heights"], 0),
    ],
    "squiz": [
        ("What's the capital of Australia? 🇦🇺", 
         ["Canberra", "Sydney", "Melbourne"], 0),
        ("Which planet is closest to the Sun? ☀️", 
         ["Mercury", "Venus", "Earth"], 0),
        ("Who wrote 'Romeo and Juliet'? 📖", 
         ["William Shakespeare", "Charles Dickens", "Jane Austen"], 0),
        ("What's the largest ocean on Earth? 🌊", 
         ["Pacific Ocean", "Atlantic Ocean", "Indian Ocean"], 0),
        ("Which element has the chemical symbol 'O'? ⚗️", 
         ["Oxygen", "Gold", "Silver"], 0),
    ],
}

# Build mixed quiz
QUIZ_DATA["aquiz"] = []
for quiz_questions in QUIZ_DATA.values():
    QUIZ_DATA["aquiz"].extend(quiz_questions)

# Runtime quiz management
shuffled_quizzes: Dict[str, List[Tuple[str, List[str], int]]] = {}

def reset_shuffled_quiz(quiz_type: str) -> None:
    """Reset and shuffle quiz questions for a category."""
    if quiz_type in QUIZ_DATA:
        shuffled_quizzes[quiz_type] = copy.deepcopy(QUIZ_DATA[quiz_type])
        random.shuffle(shuffled_quizzes[quiz_type])
        logger.info(f"Reset shuffled quiz for {quiz_type}")

# Initialize all quiz types
for quiz_type in QUIZ_DATA:
    reset_shuffled_quiz(quiz_type)

# ----------------------------
# Utility functions
# ----------------------------
def get_user_display_name(user: types.User) -> str:
    """Get a proper display name for a user."""
    if user.username:
        return f"@{user.username}"
    elif user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    elif user.first_name:
        return user.first_name
    else:
        return f"User{user.id}"

async def safe_delete_message(chat_id: int, message_id: int, delay: int = 0) -> None:
    """Safely delete a message after optional delay."""
    try:
        if delay > 0:
            await asyncio.sleep(delay)
        if bot:
            await bot.delete_message(chat_id, message_id)
    except TelegramAPIError as e:
        logger.warning(f"Could not delete message {message_id}: {e}")

# ----------------------------
# Bot command handlers
# ----------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    """Handle /start command."""
    user = message.from_user
    if not user:
        return
    
    try:
        await ensure_user(user.id, user.username, user.first_name, user.last_name)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📢 Updates", url="https://t.me/WorkGlows"),
                InlineKeyboardButton(text="💬 Support", url="https://t.me/TheCryptoElders"),
            ],
            [
                InlineKeyboardButton(
                    text="➕ Add Me To Your Group",
                    url=f"https://t.me/{(await bot.get_me()).username}?startgroup=true"
                ) if bot else InlineKeyboardButton(text="Add Me", url="https://t.me/")
            ]
        ])

        welcome_text = (
            f"👋 Hey {user.mention_html()}!\n\n"
            "✨ <b>Welcome to the Ultimate Quiz Challenge Bot!</b> ✨\n\n"
            "🎯 <b>Available Quiz Categories:</b>\n"
            "🔥 /xquiz — Relationship Quiz\n"
            "😏 /hquiz — Attraction Quiz\n"
            "💕 /fquiz — Romance Quiz\n"
            "😂 /lolquiz — Comedy Quiz\n"
            "🤪 /cquiz — Crazy Quiz\n"
            "📚 /squiz — Study Quiz\n"
            "🎲 /aquiz — Mixed Random Quiz\n\n"
            "🏆 <b>How it works:</b>\n"
            "• Correct answers boost your leaderboard rank!\n"
            "• Wrong answers help you learn and improve!\n"
            "• Check your progress with /statistics\n\n"
            "💡 Use /help for detailed guidance\n\n"
            "🎉 <b>Ready to challenge your knowledge?</b>"
        )
        
        await message.answer(welcome_text, reply_markup=kb)
        
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await message.answer("❌ An error occurred. Please try again later.")

@dp.message(Command("help"))
async def cmd_help(message: types.Message) -> None:
    """Handle /help command."""
    try:
        help_text = (
            "📚 <b>Quiz Bot Help Guide</b>\n\n"
            "🎯 <b>Available Quiz Categories:</b>\n\n"
            "🔥 <code>/xquiz</code> — Relationship Quiz\n"
            "😏 <code>/hquiz</code> — Attraction Quiz\n"
            "💕 <code>/fquiz</code> — Romance Quiz\n"
            "😂 <code>/lolquiz</code> — Comedy Quiz\n"
            "🤪 <code>/cquiz</code> — Crazy Quiz\n"
            "📚 <code>/squiz</code> — Educational Quiz\n"
            "🎲 <code>/aquiz</code> — Mixed Random Quiz\n\n"
            "📊 <b>Statistics & Leaderboard:</b>\n"
            "<code>/statistics</code> — View current leaderboard\n\n"
            "ℹ️ <b>How to Play:</b>\n"
            "1. Choose a quiz category\n"
            "2. Answer the poll questions\n"
            "3. Get points for correct answers\n"
            "4. Climb the leaderboard!\n\n"
            "🔄 <b>Quiz Management:</b>\n"
            "• Questions are shuffled randomly\n"
            "• Each category resets when empty\n"
            "• Mixed quiz includes all categories\n\n"
            "💡 <b>Tips:</b>\n"
            "• Read questions carefully\n"
            "• Answer quickly (60 second limit)\n"
            "• Practice makes perfect!\n\n"
            "🎯 <b>Start playing now with any quiz command!</b>"
        )
        
        await message.answer(help_text)
        
    except Exception as e:
        logger.error(f"Error in help command: {e}")
        await message.answer("❌ An error occurred. Please try again later.")

async def send_quiz(message: types.Message, quiz_type: str) -> None:
    """Send a quiz question for the specified category."""
    if quiz_type not in QUIZ_DATA:
        await message.answer("❌ Invalid quiz category!")
        return
    
    user = message.from_user
    if not user:
        return
    
    try:
        await ensure_user(user.id, user.username, user.first_name, user.last_name)
        
        # Check if we need to reset the shuffled quiz
        if not shuffled_quizzes.get(quiz_type):
            reset_shuffled_quiz(quiz_type)
        
        if not shuffled_quizzes[quiz_type]:
            await message.answer(
                f"🎉 Congratulations! You've completed all questions in this category!\n"
                f"🔄 Questions have been reshuffled. Try again!"
            )
            reset_shuffled_quiz(quiz_type)
            return
        
        # Get next question
        question_text, options, correct_id = shuffled_quizzes[quiz_type].pop()
        
        # Send poll
        poll_msg = await message.answer_poll(
            question=question_text,
            options=options,
            type=PollType.QUIZ,
            correct_option_id=correct_id,
            is_anonymous=False,
            open_period=POLL_TIMEOUT,
        )
        
        # Store poll session
        await store_poll_session(
            poll_msg.poll.id, 
            correct_id, 
            poll_msg.message_id, 
            message.chat.id, 
            quiz_type
        )
        
        logger.info(f"Sent {quiz_type} quiz to user {user.id} in chat {message.chat.id}")
        
    except TelegramBadRequest as e:
        logger.error(f"Telegram API error sending quiz: {e}")
        await message.answer("❌ Failed to send quiz. Please try again.")
    except Exception as e:
        logger.error(f"Error sending quiz {quiz_type}: {e}")
        await message.answer("❌ An error occurred. Please try again later.")

# Quiz command handlers
@dp.message(Command("xquiz"))
async def cmd_xquiz(message: types.Message) -> None:
    await send_quiz(message, "xquiz")

@dp.message(Command("hquiz"))
async def cmd_hquiz(message: types.Message) -> None:
    await send_quiz(message, "hquiz")

@dp.message(Command("fquiz"))
async def cmd_fquiz(message: types.Message) -> None:
    await send_quiz(message, "fquiz")

@dp.message(Command("lolquiz"))
async def cmd_lolquiz(message: types.Message) -> None:
    await send_quiz(message, "lolquiz")

@dp.message(Command("cquiz"))
async def cmd_cquiz(message: types.Message) -> None:
    await send_quiz(message, "cquiz")

@dp.message(Command("squiz"))
async def cmd_squiz(message: types.Message) -> None:
    await send_quiz(message, "squiz")

@dp.message(Command("aquiz"))
async def cmd_aquiz(message: types.Message) -> None:
    await send_quiz(message, "aquiz")

@dp.poll_answer()
async def handle_poll_answer(poll_answer: types.PollAnswer) -> None:
    """Handle poll answers and update user scores."""
    try:
        user_id = poll_answer.user.id
        selected_option = poll_answer.option_ids[0] if poll_answer.option_ids else -1
        
        # Get poll session data
        session_data = await get_poll_session(poll_answer.poll_id)
        if not session_data:
            logger.warning(f"No session data found for poll {poll_answer.poll_id}")
            return
        
        correct_option_id = session_data["correct_option_id"]
        is_correct = selected_option == correct_option_id
        
        # Ensure user exists and update score
        await ensure_user(
            user_id, 
            poll_answer.user.username, 
            poll_answer.user.first_name, 
            poll_answer.user.last_name
        )
        await update_score(user_id, is_correct)
        
        logger.info(f"User {user_id} answered poll {poll_answer.poll_id}: {'correct' if is_correct else 'incorrect'}")
        
    except Exception as e:
        logger.error(f"Error handling poll answer: {e}")

@dp.message(Command("statistics"))
async def cmd_statistics(message: types.Message) -> None:
    """Show leaderboard statistics with proper user mentions."""
    if not db:
        await message.answer("❌ Database not available!")
        return
    
    try:
        cursor = await db.execute(
            """SELECT user_id, username, first_name, last_name, wins, losses 
               FROM users 
               WHERE wins > 0 OR losses > 0 
               ORDER BY wins DESC, losses ASC 
               LIMIT ?""",
            (LEADERBOARD_SIZE,)
        )
        rows = await cursor.fetchall()
        
        if not rows:
            temp_msg = await message.answer(
                "📊 <b>Quiz Global Leaderboard</b> 📊\n\n"
                "🎯 No players have participated yet!\n"
                "🚀 Be the first to play and claim the top spot!\n\n"
                "💡 Use any quiz command to start playing!"
            )
            await safe_delete_message(message.chat.id, temp_msg.message_id, MESSAGE_DELETE_DELAY)
            return

        # Build leaderboard text with href links for user mentions
        leaderboard_text = "🏆 <b>Quiz Global Leaderboard</b> 🏆\n\n"
        
        for rank, (user_id, username, first_name, last_name, wins, losses) in enumerate(rows, 1):
            # Medal emoji based on rank
            if rank == 1:
                medal = "🥇"
            elif rank == 2:
                medal = "🥈"
            elif rank == 3:
                medal = "🥉"
            else:
                medal = f"{rank}."
            
            # Determine display name
            if first_name and last_name:
                display_name = f"{first_name} {last_name}"
            elif first_name:
                display_name = first_name
            elif username:
                display_name = username
            else:
                display_name = f"User{user_id}"
            
            # Calculate win rate
            total_games = wins + losses
            win_rate = (wins / total_games * 100) if total_games > 0 else 0
            
            # Create href mention link with display name
            user_mention = f'<a href="tg://user?id={user_id}">{display_name}</a>'
            
            # Add rank line with href mention
            leaderboard_text += f"{medal} {user_mention} — ✅ {wins} | ❌ {losses} | 📈 {win_rate:.1f}%\n"

        leaderboard_text += (
            "\n🎯 <b>Keep playing to climb higher!</b>\n"
            "💡 Use any quiz command to earn more points!"
        )

        # Send leaderboard message with href mentions
        leaderboard_msg = await message.answer(leaderboard_text)
        
        # Auto-delete after delay
        await safe_delete_message(message.chat.id, leaderboard_msg.message_id, MESSAGE_DELETE_DELAY)
        
    except Exception as e:
        logger.error(f"Error in statistics command: {e}")
        await message.answer("❌ An error occurred while fetching statistics.")

# ----------------------------
# Bot setup and lifecycle
# ----------------------------
async def setup_bot() -> None:
    """Set up bot commands and configuration."""
    try:
        commands = [
            BotCommand(command="start", description="🚀 Start the quiz bot"),
            BotCommand(command="help", description="📚 Get help and instructions"),
            BotCommand(command="xquiz", description="🔥 Relationship Quiz"),
            BotCommand(command="hquiz", description="😏 Attraction Quiz"),
            BotCommand(command="fquiz", description="💕 Romance Quiz"),
            BotCommand(command="lolquiz", description="😂 Comedy Quiz"),
            BotCommand(command="cquiz", description="🤪 Crazy Quiz"),
            BotCommand(command="squiz", description="📚 Educational Quiz"),
            BotCommand(command="aquiz", description="🎲 Mixed Random Quiz"),
            BotCommand(command="statistics", description="📊 View leaderboard"),
        ]
        
        await bot.set_my_commands(commands)
        logger.info("Bot commands set successfully")
        
    except Exception as e:
        logger.error(f"Error setting up bot commands: {e}")

async def graceful_shutdown() -> None:
    """Handle graceful shutdown."""
    logger.info("Initiating graceful shutdown...")
    
    try:
        # Close database connection
        await close_db()
        
        # Close bot session
        if bot:
            await bot.session.close()
            
        logger.info("Graceful shutdown completed")
        
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
    
    finally:
        # Force exit
        sys.exit(0)

async def main() -> None:
    """Main application entry point."""
    global bot
    
    try:
        # Initialize bot
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        
        # Initialize database
        await init_db()
        
        # Set up bot commands
        await setup_bot()
        
        # Set up signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig, 
                lambda: asyncio.create_task(graceful_shutdown())
            )
        
        logger.info("Bot starting up...")
        logger.info(f"Bot username: {(await bot.get_me()).username}")
        
        # Start polling
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        await graceful_shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
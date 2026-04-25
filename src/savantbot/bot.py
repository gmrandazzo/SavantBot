import os
import logging
import httpx
import re
from dotenv import load_dotenv
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("SAVANT_API_KEY")
API_BASE_URL = os.getenv("API_URL", "http://0.0.0.0:8124")

# Ensure API_URL doesn't end with /chat for auth calls
if API_BASE_URL.endswith("/chat"):
    API_BASE_URL = API_BASE_URL[:-5]

CHAT_API_URL = f"{API_BASE_URL}/chat"
AUTH_API_URL = f"{API_BASE_URL}/api/auth"

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Headers for API requests
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

def clean_response(text: str) -> str:
    """Removes LLM internal reasoning tags and special tokens."""
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    cleaned = cleaned.replace("<|im_start|>", "").replace("<|im_end|>", "")
    return cleaned.strip()

async def is_authorized(update: Update) -> bool:
    """Verifies if the user is authorized by calling the FastAPI backend."""
    user = update.effective_user
    if not user:
        return False
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{AUTH_API_URL}/{user.id}", headers=HEADERS)
            if response.status_code == 200:
                return bool(response.json().get("allowed", False))
            else:
                logger.error(f"Auth API returned status {response.status_code}")
                return False
    except Exception as e:
        logger.error(f"Error checking authorization: {e}")
        # In case of API failure, we fail-closed for security
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    if not update.message or not update.effective_user:
        return

    if not await is_authorized(update):
        await update.message.reply_text(f"⛔ Unauthorized. Your ID: {update.effective_user.id}")
        return
    await update.message.reply_text("SavantBot is online. Send me a message to start chatting!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming text messages and routes them to the RAG API."""
    message = update.message or update.channel_post
    if not message or not message.text or not update.effective_user:
        return

    if not await is_authorized(update):
        await message.reply_text(f"⛔ Permission denied. Your ID: {update.effective_user.id}")
        return

    user_text = message.text
    chat_type = message.chat.type
    bot_username = context.bot.username

    # Decide if we should reply (DM or mention/reply in group)
    should_reply = chat_type == 'private'
    if not should_reply:
        if bot_username and f"@{bot_username}" in user_text:
            should_reply = True
            user_text = user_text.replace(f"@{bot_username}", "").strip()
        elif message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == context.bot.id:
            should_reply = True

    if not should_reply:
        return

    await context.bot.send_chat_action(chat_id=message.chat.id, action=constants.ChatAction.TYPING)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(CHAT_API_URL, json={"message": user_text}, headers=HEADERS)
            
            if response.status_code == 200:
                raw_reply = response.json().get("response", "...")
                final_reply = clean_response(raw_reply) or "..."
                await message.reply_text(final_reply)
            else:
                logger.error(f"API Error: {response.status_code}")
                await message.reply_text("⚠️ Backend error. Please try again later.")

    except httpx.ReadTimeout:
        await message.reply_text("⌛ Response timed out. The model is taking too long.")
    except Exception as e:
        logger.error(f"Connection error: {e}")
        await message.reply_text("🔌 Cannot connect to the backend server.")

def main():
    """Main entry point for the Telegram Bot."""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN not found in environment variables!")
        return

    logger.info("SavantBot is starting...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logger.info("Polling for updates...")
    app.run_polling()

if __name__ == '__main__':
    main()

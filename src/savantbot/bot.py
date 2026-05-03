import logging
import os
import re
import time

import httpx
from dotenv import load_dotenv
from telegram import Update, constants
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_BASE_URL = os.getenv("API_URL", "http://0.0.0.0:8124")

# Ensure API_URL doesn't end with /chat for auth calls
if API_BASE_URL.endswith("/chat"):
    API_BASE_URL = API_BASE_URL[:-5]
elif API_BASE_URL.endswith("/chat/"):
    API_BASE_URL = API_BASE_URL[:-6]

CHAT_API_URL = f"{API_BASE_URL}/chat/stream"
AUTH_API_URL = f"{API_BASE_URL}/api/auth"

# Logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def clean_response(text: str) -> str:
    """Removes LLM internal reasoning tags and special tokens."""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = cleaned.replace("<|im_start|>", "").replace("<|im_end|>", "")
    return cleaned.strip()


async def is_authorized(update: Update) -> bool:
    """Verifies if the user is authorized by calling the FastAPI backend."""
    user = update.effective_user
    if not user:
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{AUTH_API_URL}/{user.id}")
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
        await update.message.reply_text(
            f"⛔ Unauthorized. Your ID: {update.effective_user.id}"
        )
        return
    await update.message.reply_text(
        "SavantBot is online. Send me a message to start chatting!"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming text messages and routes them to the RAG API."""
    message = update.message or update.channel_post
    if not message or not message.text or not update.effective_user:
        return

    if not await is_authorized(update):
        await message.reply_text(
            f"⛔ Permission denied. Your ID: {update.effective_user.id}"
        )
        return

    user_text = message.text
    chat_type = message.chat.type
    bot_username = context.bot.username

    # Decide if we should reply (DM or mention/reply in group)
    should_reply = chat_type == "private"
    if not should_reply:
        if bot_username and f"@{bot_username}" in user_text:
            should_reply = True
            user_text = user_text.replace(f"@{bot_username}", "").strip()
        elif (
            message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.id == context.bot.id
        ):
            should_reply = True

    if not should_reply:
        return

    await context.bot.send_chat_action(
        chat_id=message.chat.id, action=constants.ChatAction.TYPING
    )

    # Send initial "Thinking..." message
    placeholder_message = await message.reply_text("Thinking...")
    full_response = ""
    last_update_time = time.time()
    update_interval = 1.5  # Seconds between edits to avoid rate limits

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", CHAT_API_URL, json={"message": user_text}
            ) as response:
                if response.status_code != 200:
                    logger.error(f"API Error: {response.status_code}")
                    await placeholder_message.edit_text(
                        "⚠️ Backend error. Please try again later."
                    )
                    return

                async for chunk in response.aiter_text():
                    full_response += chunk

                    # Periodic update to Telegram
                    if time.time() - last_update_time > update_interval:
                        display_text = clean_response(full_response)
                        if display_text:
                            try:
                                await placeholder_message.edit_text(
                                    display_text + "..."
                                )
                                last_update_time = time.time()
                            except BadRequest as e:
                                if "Message is not modified" not in str(e):
                                    logger.error(f"Telegram error during stream: {e}")

                # Final update
                final_text = clean_response(full_response) or "..."
                try:
                    await placeholder_message.edit_text(final_text)
                except BadRequest as e:
                    if "Message is not modified" not in str(e):
                        logger.error(f"Final Telegram error: {e}")

    except Exception as e:
        logger.error(f"Connection error: {e}")
        await placeholder_message.edit_text("🔌 Cannot connect to the backend server.")


def main():
    """Main entry point for the Telegram Bot."""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN not found in environment variables!")
        return

    logger.info("SavantBot is starting...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    logger.info("Polling for updates...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

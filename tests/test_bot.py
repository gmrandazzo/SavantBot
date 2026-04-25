import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock telegram
sys.modules["telegram"] = MagicMock()
sys.modules["telegram.ext"] = MagicMock()
sys.modules["telegram.constants"] = MagicMock()

from savantbot.bot import clean_response, handle_message, is_authorized  # noqa: E402


def test_clean_response():
    text = "Thinking... <think>I should say hello</think> Hello there!"
    assert clean_response(text) == "Thinking...  Hello there!"

    special_tokens = "<|im_start|>user\nHello<|im_end|>"
    assert clean_response(special_tokens) == "user\nHello"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_is_authorized_api_call(mock_get):
    # Mock API allowing the user
    mock_get.return_value = MagicMock(status_code=200)
    mock_get.return_value.json.return_value = {"allowed": True}

    update = MagicMock()
    update.effective_user.id = 12345

    result = await is_authorized(update)
    assert result is True


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_is_authorized_denied(mock_get):
    mock_get.return_value = MagicMock(status_code=200)
    mock_get.return_value.json.return_value = {"allowed": False}

    update = MagicMock()
    update.effective_user.id = 999

    result = await is_authorized(update)
    assert result is False


@pytest.mark.asyncio
@patch("savantbot.bot.is_authorized", return_value=True)
@patch("httpx.AsyncClient.post")
async def test_handle_message_flow(mock_post, mock_auth):
    # Mock API response
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {"response": "Hi!"}

    update = MagicMock()
    update.message.text = "Hello"
    update.message.chat.type = "private"
    update.message.chat.id = 123
    update.message.reply_text = AsyncMock()  # Must be AsyncMock

    context = MagicMock()
    context.bot.send_chat_action = AsyncMock()  # Must be AsyncMock

    await handle_message(update, context)

    # Verify the bot replied
    update.message.reply_text.assert_called_with("Hi!")

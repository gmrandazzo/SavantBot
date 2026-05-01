import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock telegram
sys.modules["telegram"] = MagicMock()
sys.modules["telegram.ext"] = MagicMock()
sys.modules["telegram.constants"] = MagicMock()
sys.modules["telegram.error"] = MagicMock()

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
@patch("httpx.AsyncClient.stream")
async def test_handle_message_flow(mock_stream, mock_auth):
    # Mock streaming response
    mock_response = MagicMock()
    mock_response.status_code = 200
    
    async def mock_aiter_text():
        yield "Hi"
        yield "!"

    mock_response.aiter_text = mock_aiter_text
    
    # Mock context manager
    mock_stream.return_value.__aenter__.return_value = mock_response

    update = MagicMock()
    update.message.text = "Hello"
    update.message.chat.type = "private"
    update.message.chat.id = 123
    
    # reply_text returns a Message object that has edit_text
    placeholder_message = AsyncMock()
    update.message.reply_text = AsyncMock(return_value=placeholder_message)

    context = MagicMock()
    context.bot.send_chat_action = AsyncMock()

    await handle_message(update, context)

    # Verify the initial reply
    update.message.reply_text.assert_called_with("Thinking...")
    
    # Verify the final edit
    placeholder_message.edit_text.assert_called_with("Hi!")

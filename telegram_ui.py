"""Bounded recovery for callback acknowledgements and idempotent menu edits."""
import asyncio
import logging

from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError

logger = logging.getLogger(__name__)


async def retry_menu_request(request):
    # Only use for acknowledgements/edits, never customer sends or whole handlers.
    for attempt in range(3):
        try:
            return await request()
        except TelegramNetworkError:
            if attempt == 2:
                raise
            logger.warning("Telegram menu connection interrupted; retry %s/2", attempt + 1)
            await asyncio.sleep(0.5 * (attempt + 1))


async def acknowledge(callback):
    try:
        await retry_menu_request(callback.answer)
    except TelegramNetworkError:
        logger.warning("Telegram callback acknowledgement unavailable; continuing menu update")
    except TelegramBadRequest as error:
        if not any(term in error.message.lower() for term in ("query is too old", "query id is invalid", "query_id_invalid")):
            raise


async def update_panel(callback, text, keyboard):
    await acknowledge(callback)
    try:
        await retry_menu_request(lambda: callback.message.edit_text(
            text, reply_markup=keyboard, parse_mode="HTML"))
    except TelegramBadRequest as error:
        message = error.message.lower()
        if "message is not modified" in message:
            return
        if not any(term in message for term in (
            "message can't be edited", "message to edit not found",
            "message can not be edited", "there is no text in the message to edit",
        )):
            raise
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")

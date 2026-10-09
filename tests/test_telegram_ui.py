import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import AnswerCallbackQuery, EditMessageText
from telegram_ui import update_panel


class TelegramUITests(unittest.IsolatedAsyncioTestCase):
    def callback(self):
        return SimpleNamespace(answer=AsyncMock(), message=SimpleNamespace(
            edit_text=AsyncMock(), answer=AsyncMock()))

    def network(self):
        return TelegramNetworkError(method=AnswerCallbackQuery(callback_query_id="q"), message="connection reset")

    def bad(self, text):
        return TelegramBadRequest(method=EditMessageText(chat_id=1, message_id=1, text="x"), message=text)

    async def test_ack_reconnects(self):
        cb = self.callback()
        cb.answer.side_effect = [self.network(), True]
        with patch("telegram_ui.asyncio.sleep", new_callable=AsyncMock):
            await update_panel(cb, "menu", None)
        self.assertEqual(cb.answer.await_count, 2)
        cb.message.edit_text.assert_awaited_once()
        cb.message.answer.assert_not_awaited()

    async def test_failed_ack_does_not_block_screen(self):
        cb = self.callback()
        cb.answer.side_effect = self.network()
        with patch("telegram_ui.asyncio.sleep", new_callable=AsyncMock):
            await update_panel(cb, "menu", None)
        self.assertEqual(cb.answer.await_count, 3)
        cb.message.edit_text.assert_awaited_once()

    async def test_edit_retries_without_duplicate_send(self):
        cb = self.callback()
        cb.message.edit_text.side_effect = [self.network(), True]
        with patch("telegram_ui.asyncio.sleep", new_callable=AsyncMock):
            await update_panel(cb, "menu", None)
        self.assertEqual(cb.message.edit_text.await_count, 2)
        cb.message.answer.assert_not_awaited()

    async def test_edit_failure_propagates_without_fallback(self):
        cb = self.callback()
        cb.message.edit_text.side_effect = self.network()
        with patch("telegram_ui.asyncio.sleep", new_callable=AsyncMock):
            with self.assertRaises(TelegramNetworkError):
                await update_panel(cb, "menu", None)
        cb.message.answer.assert_not_awaited()

    async def test_not_modified_is_success(self):
        cb = self.callback()
        cb.message.edit_text.side_effect = self.bad("message is not modified")
        await update_panel(cb, "menu", None)
        cb.message.answer.assert_not_awaited()

    async def test_uneditable_message_uses_single_fallback(self):
        cb = self.callback()
        cb.message.edit_text.side_effect = self.bad("message can't be edited")
        await update_panel(cb, "menu", None)
        cb.message.answer.assert_awaited_once()

    async def test_invalid_markup_is_not_hidden(self):
        cb = self.callback()
        cb.message.edit_text.side_effect = self.bad("can't parse entities")
        with self.assertRaises(TelegramBadRequest):
            await update_panel(cb, "menu", None)
        cb.message.answer.assert_not_awaited()

    async def test_expired_callback_does_not_block_screen(self):
        cb = self.callback()
        cb.answer.side_effect = self.bad("query is too old and response timeout expired")
        await update_panel(cb, "menu", None)
        cb.message.edit_text.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

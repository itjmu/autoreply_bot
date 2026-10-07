import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_regressions  # Sets test configuration before importing the bot.
from aiogram import Bot
from aiogram.types import User
from bot import build_ref_link


class ReferralTests(unittest.IsolatedAsyncioTestCase):
    async def test_link_uses_active_bot_without_startup_global_and_caches_get_me(self):
        bot = Bot("123456:TEST_NOT_A_REAL_TOKEN")
        me = User(id=123456, is_bot=True, first_name="Test", username="ActualReplyBot")
        try:
            with patch.object(bot, "get_me", AsyncMock(return_value=me)) as get_me:
                self.assertEqual(await build_ref_link(6385155030, bot), "https://t.me/ActualReplyBot?start=ref_6385155030")
                self.assertEqual(await build_ref_link(2, bot), "https://t.me/ActualReplyBot?start=ref_2")
                get_me.assert_awaited_once()
        finally:
            await bot.session.close()

    async def test_missing_username_never_generates_a_broken_link(self):
        for username in (None, "", "@invalid", "https://t.me/wrong"):
            bot = SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username=username)))
            with self.assertRaises(ValueError):
                await build_ref_link(6385155030, bot)

    async def test_username_belongs_to_the_bot_that_sends_the_link(self):
        first = SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username="FirstBot")))
        second = SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username="SecondBot")))
        self.assertEqual(await build_ref_link(1, first), "https://t.me/FirstBot?start=ref_1")
        self.assertEqual(await build_ref_link(1, second), "https://t.me/SecondBot?start=ref_1")


if __name__ == "__main__":
    unittest.main()

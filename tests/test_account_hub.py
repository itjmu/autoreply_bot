import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_regressions as regression
import test_experience as interface
import database as db
import extensions as ext
import account_hub as hub
import experience as ux
from button_layout import faq_rows


class FaqGridTests(unittest.TestCase):
    def test_three_two_and_one_columns_preserve_order(self):
        labels = ["a", "bb", "ccc", "dddd", "1234567890", "12345678901", "1234567890123456", "short"]
        faqs = [{"id": index, "question": label} for index, label in enumerate(labels)]
        rows = faq_rows(faqs)
        self.assertEqual([len(row) for row in rows], [3, 1, 2, 1, 1])
        self.assertEqual([data for row in rows for _, data in row], [f"ux:faq:{index}" for index in range(len(faqs))])

    def test_boundary_lengths_and_remote_prefix(self):
        faqs = [{"id": index, "question": "x" * count} for index, count in enumerate((9, 9, 9, 10, 10, 15, 15, 16, 16))]
        rows = faq_rows(faqs, "hub:faq:2:")
        self.assertEqual([len(row) for row in rows], [3, 2, 2, 1, 1])
        self.assertEqual(rows[0][0][1], "hub:faq:2:0")


class HubTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = regression.DatabaseTests.asyncSetUp
    callback = interface.InterfaceTests.callback
    state = interface.InterfaceTests.state

    async def asyncTearDown(self):
        await hub.shutdown()
        await regression.BusinessTests.asyncTearDown(self)

    async def business(self, owner=1):
        await db.ensure_user(owner)
        await ext.set_option(owner, "ui_mode", "business")

    async def connect(self, child=2):
        await self.business()
        await db.ensure_user(child)
        token = await hub.create_request(1, child)
        await hub.decide(child, token, "yes")
        return token

    async def test_consent_required_and_wrong_actor_cannot_accept(self):
        await self.business()
        token = await hub.create_request(1, 2)
        self.assertFalse(await hub.can_manage(1, 2))
        with self.assertRaises(ValueError):
            await hub.decide(1, token, "yes")
        self.assertFalse(await hub.can_manage(1, 2))
        await hub.decide(2, token, "yes")
        self.assertTrue(await hub.can_manage(1, 2))
        with self.assertRaises(ValueError):
            await hub.decide(2, token, "yes")

    async def test_unknown_id_is_not_registered_by_invite(self):
        await self.business()
        with self.assertRaises(ValueError):
            await hub.create_request(1, 999)
        self.assertIsNone(await hub.known(999))
        with self.assertRaises(ValueError):
            await hub.create_request(1, 1)

    async def test_decline_report_and_expiry_do_not_grant_access(self):
        await self.business()
        token = await hub.create_request(1, 2)
        await hub.decide(2, token, "report")
        self.assertFalse(await hub.can_manage(1, 2))
        with self.assertRaises(ValueError):
            await hub.create_request(1, 2)
        await db.ensure_user(3)
        token = await hub.create_request(1, 3)
        async with db._connect() as conn:
            await conn.execute("UPDATE account_link_requests SET expires_at=datetime('now','-1 second') WHERE token=?", (token,))
            await conn.commit()
        with self.assertRaises(ValueError):
            await hub.decide(3, token, "yes")

    async def test_business_one_and_premium_three_extra_accounts(self):
        await self.connect()
        await db.ensure_user(3)
        with self.assertRaises(ValueError):
            await hub.create_request(1, 3)
        await db.set_premium(1, 30)
        for child in (3, 4):
            await db.ensure_user(child)
            token = await hub.create_request(1, child)
            await hub.decide(child, token, "yes")
        self.assertEqual(len(await hub.linked(1)), 3)
        await db.ensure_user(5)
        with self.assertRaises(ValueError):
            await hub.create_request(1, 5)

    async def test_atomic_accept_after_premium_downgrade(self):
        await self.business()
        await db.set_premium(1, 30)
        await db.ensure_user(3)
        tokens = [await hub.create_request(1, child) for child in (2, 3)]
        async with db._connect() as conn:
            await conn.execute("UPDATE users SET premium_until='2000-01-01T00:00:00+00:00' WHERE telegram_id=1")
            await conn.commit()
        results = await asyncio.gather(*(hub.decide(child, token, "yes") for child, token in zip((2, 3), tokens)), return_exceptions=True)
        self.assertEqual(sum(not isinstance(result, Exception) for result in results), 1)
        self.assertEqual(len(await hub.linked(1)), 1)

    async def test_child_or_parent_can_revoke_unrelated_actor_cannot(self):
        await self.connect()
        await hub.revoke(3, 2)
        self.assertTrue(await hub.can_manage(1, 2))
        await hub.revoke(2, 2)
        self.assertFalse(await hub.can_manage(1, 2))
        self.assertEqual(await hub.linked(1), [])

    async def test_personal_or_downgraded_parent_does_not_read_extra_profiles(self):
        await self.connect()
        await db.set_premium(1, 30)
        await db.ensure_user(3)
        token = await hub.create_request(1, 3)
        await hub.decide(3, token, "yes")
        async with db._connect() as conn:
            await conn.execute("UPDATE users SET premium_until='2000-01-01T00:00:00+00:00' WHERE telegram_id=1")
            await conn.commit()
        self.assertFalse(await hub.can_manage(1, 3))
        self.assertEqual(len(await hub.linked(1)), 2)
        await ext.set_option(1, "ui_mode", "personal")
        self.assertFalse(await hub.can_manage(1, 2))

    async def test_nested_and_conflicting_management_rejected(self):
        await self.connect()
        await self.business(2)
        await db.ensure_user(3)
        with self.assertRaises(ValueError):
            await hub.create_request(2, 3)
        await self.business(4)
        with self.assertRaises(ValueError):
            await hub.create_request(4, 2)

    async def test_remote_faq_saved_to_child_database_with_entities(self):
        await self.connect()
        spec = {"type": "text", "text": "Price 10", "entities": [{"type": "bold", "offset": 0, "length": 5}]}
        await hub.save_managed_faq(1, 2, "Price?", spec)
        self.assertEqual(await db.get_faqs(1), [])
        faqs = await db.get_faqs(2)
        self.assertEqual(faqs[0]["answer"], "Price 10")
        self.assertEqual(json.loads(faqs[0]["answer_entities"]), spec["entities"])
        await hub.revoke(2, 2)
        with self.assertRaises(ValueError):
            await hub.save_managed_faq(1, 2, "Another?", spec)
        self.assertEqual(len(await db.get_faqs(2)), 1)

    async def test_notifications_have_account_chat_and_both_directions(self):
        await self.connect()
        await db.save_business_connection("child-conn", 2, True)
        await db.remember_chat(2, 100, peer_name="Customer")
        bot = AsyncMock()
        await hub.record_activity(bot, 2, 100, "child-conn", "incoming", "Question?")
        await hub.record_activity(bot, 2, 100, "child-conn", "outgoing", "Answer")
        await asyncio.gather(*list(hub._notice_tasks))
        self.assertEqual(bot.send_message.await_count, 2)
        text = "\n".join(call.args[1] for call in bot.send_message.await_args_list)
        self.assertIn("ID 2", text)
        self.assertIn("ID 100", text)
        self.assertIn("Question?", text)
        self.assertIn("Answer", text)
        await hub.revoke(2, 2)
        bot.reset_mock()
        await hub.record_activity(bot, 2, 100, "child-conn", "incoming", "Private now")
        bot.send_message.assert_not_awaited()

    async def test_manager_reply_uses_child_connection_and_pauses_bot(self):
        await self.connect()
        await db.save_business_connection("child-conn", 2, True)
        await db.remember_chat(2, 100, peer_name="Customer")
        bot = AsyncMock()
        bot.get_business_connection.return_value = SimpleNamespace(is_enabled=True, user=SimpleNamespace(id=2), rights=SimpleNamespace(can_reply=True), can_reply=True)
        await hub.record_activity(bot, 2, 100, "child-conn", "incoming", "Question")
        with patch("bot.send_faq_answer", AsyncMock()) as send:
            await hub.manager_reply(bot, 1, 2, 100, {"type": "text", "text": "Human reply"})
        self.assertEqual(send.await_args.args[1:3], (100, "child-conn"))
        self.assertTrue(await ext.is_handoff(2, 100))
        self.assertFalse(await ext.is_handoff(1, 100))
        self.assertEqual((await db.get_chat_history(2, 100, 5))[-1]["content"], "Human reply")
        await hub.revoke(2, 2)
        with self.assertRaises(ValueError):
            await hub.manager_reply(bot, 1, 2, 100, {"type": "text", "text": "No access"})

    async def test_settings_categories_and_business_account_shortcut(self):
        callback = self.callback("settings")
        await ux.navigation(callback, self.state())
        buttons = callback.message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
        routes = {b.callback_data for row in buttons for b in row}
        self.assertTrue({"ux:response_settings", "ux:language_settings", "ux:connection_settings", "ux:advanced", "ux:account"}.issubset(routes))
        await self.business()
        routes = {b.callback_data for row in (await ux.home_markup(1)).inline_keyboard for b in row}
        self.assertIn("hub:home", routes)

    async def test_private_history_routes_validate_access(self):
        await self.business()
        callback = self.callback("unused")
        callback.data = "hub:faqs:2:0"
        await hub.hub_navigation(callback, self.state())
        callback.answer.assert_awaited()
        callback.message.edit_text.assert_not_awaited()

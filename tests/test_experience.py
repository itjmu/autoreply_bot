import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_regressions as regression
import database as db
import extensions as ext
import experience as ux
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from fsm_storage import SQLiteStorage


class InterfaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_faq_answer_prompt_hides_album_finish(self):
        state = self.state()
        message = SimpleNamespace(from_user=self.callback("unused").from_user, text="Question", answer=AsyncMock())
        await ux.faq_question(message, state)
        buttons = message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        self.assertNotIn("album_finish", {b.callback_data for row in buttons for b in row})

    async def test_command_buttons_are_saved_exported_and_owner_scoped(self):
        await ext.set_option(1, "ui_mode", "business")
        await ext.append_faq(1, "Price", {"type": "text", "text": "10", "payload": {"command": "/prices"}})
        await ext.append_faq(1, "Welcome", {"type": "text", "text": "Welcome"})
        faqs = await db.get_faqs(1)
        source = next(f for f in faqs if f["question"] == "Welcome")
        state = self.state()
        await ux.navigation(self.callback(f"faq_command_button:{source['id']}"), state)
        message = SimpleNamespace(from_user=self.callback("unused").from_user, text="Our prices\n/prices", answer=AsyncMock())
        await ux.save_faq_command(message, state)
        await ext.import_owner(1, await ext.export_owner(1))
        source = next(f for f in await db.get_faqs(1) if f["question"] == "Welcome")
        self.assertEqual(json.loads(source["answer_payload"])["buttons"], [{"text": "Our prices", "command": "/prices"}])
        from bot import send_faq_answer
        bot = AsyncMock()
        await send_faq_answer(bot, 100, "connection", source)
        button = bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.callback_data, f"fqcall:1:{source['id']}:prices")
        callback = self.callback("unused")
        callback.data = f"fqcall:1:{source['id']}:prices"
        callback.message.chat = SimpleNamespace(id=1)
        with patch("bot.send_faq_answer", AsyncMock()) as send:
            await ux.call_faq_button(callback)
            send.assert_awaited_once()
            self.assertEqual(send.await_args.args[3]["answer"], "10")
            send.reset_mock()
            callback.from_user.id = 2
            await ux.call_faq_button(callback)
            send.assert_not_awaited()
    async def test_new_faq_ignore_button_preserves_question_and_saves_action(self):
        state = self.state()
        await state.set_state(ux.Flow.faq_question)
        message = SimpleNamespace(from_user=self.callback("unused").from_user, text="ОК", answer=AsyncMock())
        await ux.faq_question(message, state)
        await ux.navigation(self.callback("faq_ignore_draft"), state)
        faqs = await db.get_faqs(1)
        self.assertEqual(faqs[0]["question"], "ОК")
        self.assertTrue(json.loads(faqs[0]["answer_payload"])["ignore"])
        self.assertIsNone(await state.get_state())

    async def test_draft_delay_keeps_question_and_accepts_business_hour(self):
        await ext.set_option(1, "ui_mode", "business")
        state = self.state()
        await state.set_state(ux.Flow.faq_answer)
        await state.set_data({"question": "Price"})
        await ux.navigation(self.callback("delay:draft"), state)
        message = SimpleNamespace(from_user=self.callback("unused").from_user, text="3600", answer=AsyncMock())
        await ux.save_reply_delay(message, state)
        self.assertEqual((await state.get_data())["question"], "Price")
        self.assertEqual((await state.get_data())["faq_delay"], 3600)
        await ux.navigation(self.callback("faq_ignore_draft"), state)
        self.assertTrue(json.loads((await db.get_faqs(1))[0]["answer_payload"])["ignore"])

    async def test_personal_settings_do_not_offer_business_and_faq_back_is_home(self):
        callback = self.callback("settings")
        await ux.navigation(callback, self.state())
        buttons = callback.message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
        data = {b.callback_data for row in buttons for b in row}
        self.assertNotIn("ux:business_tools", data)
        self.assertNotIn("ux:schedule", data)
        callback = self.callback("faqs")
        await ux.navigation(callback, self.state())
        self.assertEqual(callback.message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard[-1][0].callback_data, "ux:home")

    async def test_mode_switch_preserves_shared_faq_timezone_and_native_language(self):
        await ext.append_faq(1, "Price", {"type": "text", "text": "10"})
        await db.set_preference(1, "timezone", "Asia/Karachi")
        await db.update_profile_field(1, "native_language", "Tajik")
        await ext.set_option(1, "setup_done", 1)
        for mode in ("business", "personal", "business"):
            await ux.navigation(self.callback("interface:" + mode), self.state())
            self.assertEqual((await db.get_faqs(1))[0]["answer"], "10")
            self.assertEqual((await db.get_preferences(1))["timezone"], "Asia/Karachi")
            self.assertEqual((await db.get_profile(1))["native_language"], "Tajik")

    async def test_delay_limits_and_storage_are_separate_for_modes(self):
        state = self.state()
        await ux.navigation(self.callback("delay:ai"), state)
        message = SimpleNamespace(from_user=self.callback("unused").from_user, text="3600", answer=AsyncMock())
        await ux.save_reply_delay(message, state)
        self.assertEqual(await state.get_state(), ux.Flow.reply_delay.state)
        message.text = "5"
        await ux.save_reply_delay(message, state)
        await ext.set_option(1, "ui_mode", "business")
        await ux.navigation(self.callback("delay:ai"), state)
        message.text = "3600"
        await ux.save_reply_delay(message, state)
        settings = await ext.business_settings(1)
        self.assertEqual(settings["personal_ai_delay"], 5)
        self.assertEqual(settings["ai_delay"], 3600)
        await ext.import_owner(1, await ext.export_owner(1))
        self.assertEqual((await ext.business_settings(1))["ai_delay"], 3600)

    async def test_menu_keeps_ai_toggle_next_to_configuration_and_settings_last(self):
        keyboard = await ux.home_markup(1)
        self.assertEqual([button.callback_data for button in keyboard.inline_keyboard[2]], ["ux:ai_toggle", "ux:ai"])
        self.assertEqual(keyboard.inline_keyboard[-1][0].callback_data, "ux:settings")

    async def test_takeover_pauses_only_selected_chat_and_offers_telegram_link(self):
        await db.remember_chat(1, 100, peer_name="Customer", username="customer")
        callback = self.callback("takeover:100")
        await ux.navigation(callback, self.state())
        self.assertTrue(await ext.is_handoff(1, 100))
        self.assertFalse(await ext.is_handoff(2, 100))
        button = callback.message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.url, "tg://user?id=100")
        await ux.navigation(self.callback("resume:100"), self.state())
        self.assertFalse(await ext.is_handoff(1, 100))
    async def test_personal_selection_skips_setup(self):
        state = self.state()
        callback = self.callback("interface:personal")
        await ux.navigation(callback, state)
        self.assertIsNone(await state.get_state())
        self.assertEqual((await ext.options(1))["ui_mode"], "personal")
        self.assertIn("Chat Automation", callback.message.edit_text.await_args.args[0])

    async def test_business_setup_requests_timezone(self):
        state = self.state()
        await ux.navigation(self.callback("setup_lang:en"), state)
        self.assertEqual(await state.get_state(), ux.Flow.setup_timezone.state)

    async def test_saved_fallback_round_trip_and_owner_isolation(self):
        spec = {"type": "photo", "file_id": "photo", "text": "Hello", "entities": [{"type": "bold", "offset": 0, "length": 5}]}
        await ext.save_fallback(1, 2, spec)
        exported = await ext.export_owner(1)
        await ext.save_fallback(1, 2, {"type": "text", "text": "changed"})
        await ext.import_owner(1, exported)
        self.assertEqual((await ext.fallback_messages(1))[2], spec)
        self.assertEqual(await ext.fallback_messages(2), {})

    async def test_sequence_sends_answers_with_entities_and_buttons(self):
        from bot import send_faq_answer
        bot = AsyncMock()
        entities = [{"type": "bold", "offset": 0, "length": 5}]
        item = {"answer_type": "sequence", "answer_payload": json.dumps({"items": [{"type": "text", "text": "Hello", "entities": entities}, {"type": "photo", "file_id": "photo"}], "buttons": [{"text": "Site", "url": "https://example.com"}]})}
        await send_faq_answer(bot, 100, "connection", item)
        bot.send_message.assert_awaited_once()
        bot.send_photo.assert_awaited_once()
        self.assertEqual(bot.send_message.await_args.kwargs["entities"][0].type, "bold")
        self.assertEqual(bot.send_photo.await_args.kwargs["reply_markup"].inline_keyboard[0][0].url, "https://example.com")

    async def test_business_fallback_cycles_two_messages_with_referral_button(self):
        from bot import send_fallback_message
        await ext.set_option(1, "ui_mode", "business")
        for slot in range(3):
            await ext.save_fallback(1, slot, {"type": "text", "text": str(slot)})
        bot = AsyncMock()
        bot.me.return_value = SimpleNamespace(username="test_bot")
        for _ in range(4):
            self.assertTrue(await send_fallback_message(bot, 1, 100, "connection", await db.get_profile(1)))
        self.assertEqual([call.kwargs["text"] for call in bot.send_message.await_args_list], ["0", "1", "0", "1"])
        self.assertEqual(bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0][0].url, "https://t.me/test_bot?start=ref_1")

    async def test_fallback_album_recovers_from_storage(self):
        state = self.state()
        await state.set_state(ux.Flow.fallback)
        await state.set_data({"slot": 1, "album_token": "draft", "album_draft": [{"type": "photo", "file_id": "photo"}]})
        await ux.commit_draft(self.state(), 1, 1, AsyncMock(), "draft")
        self.assertEqual((await ext.fallback_messages(1))[1]["type"], "media_group")

    async def test_forward_from_other_owner_is_rejected(self):
        with self.assertRaises(ValueError):
            await ext.import_owner(1, {"format": "autoreply-v1", "faqs": [{"question": "forward", "answer_type": "forward", "answer_payload": json.dumps({"from_chat_id": 2, "message_id": 10, "copy": {"type": "text", "text": "secret"}})}]})

    async def test_report_schedule_is_owner_scoped(self):
        await ext.save_business_setting(1, "report_time", "08:30")
        await ext.save_business_setting(1, "reminders", ["11:00", "15:00", "18:00"])
        exported = await ext.export_owner(1)
        self.assertEqual(exported["business_settings"]["report_time"], "08:30")
        self.assertEqual((await ext.business_settings(2))["report_time"], "09:00")

    async def test_forwarded_answer_uses_copy_for_connected_account(self):
        from bot import send_faq_answer
        bot = AsyncMock()
        item = {"answer_type": "forward", "answer_payload": json.dumps({"from_chat_id": 1, "message_id": 5, "copy": {"type": "photo", "file_id": "photo", "text": "caption"}})}
        await send_faq_answer(bot, 100, "connection", item)
        bot.forward_message.assert_not_awaited()
        bot.send_photo.assert_awaited_once()
        await send_faq_answer(bot, 100, None, item)
        bot.forward_message.assert_awaited_once_with(chat_id=100, from_chat_id=1, message_id=5)

    async def test_contact_report_includes_chats_without_bot_reply(self):
        await db.remember_chat(1, 100, peer_name="Customer", username="customer")
        await db.add_chat_message(1, 100, "user", "Question")
        self.assertEqual([c["chat_id"] for c in await ext.today_contacts(1, "UTC")], [100])
        self.assertEqual(await ext.today_contacts(2, "UTC"), [])

    async def test_album_buttons_are_sent_below_album(self):
        from bot import send_faq_answer
        bot = AsyncMock()
        item = {"answer_type": "media_group", "answer_payload": json.dumps({"items": [{"type": "photo", "file_id": "one"}, {"type": "photo", "file_id": "two"}], "buttons": [{"text": "Site", "url": "https://example.com"}]})}
        await send_faq_answer(bot, 100, "connection", item)
        bot.send_media_group.assert_awaited_once()
        self.assertNotIn("reply_markup", bot.send_media_group.await_args.kwargs)
        bot.send_message.assert_awaited_once()

    async def test_broadcast_album_preparation_preserves_all_ids(self):
        from bot import _finish_broadcast_album
        state = self.state()
        from states import Broadcast
        await state.set_state(Broadcast.waiting)
        await state.set_data({"broadcast_album_token": "token", "broadcast_album_ids": [12, 10, 11, 11]})
        message = SimpleNamespace(model_copy=lambda **kwargs: "album-message")
        with patch("bot.asyncio.sleep", AsyncMock()), patch("bot.broadcast_message_handler", AsyncMock()) as prepare:
            await _finish_broadcast_album(message, state, AsyncMock(), "token")
        self.assertEqual(prepare.await_args.kwargs["album_ids"], [10, 11, 12])

    async def test_interface_switch_preserves_reply_settings(self):
        await ext.set_option(1, "setup_done", 1)
        before = await ext.export_owner(1)
        for mode in ("business", "personal"):
            await ux.navigation(self.callback("interface:" + mode), self.state())
            keyboard = await ux.home_markup(1)
            callbacks = {button.callback_data for row in keyboard.inline_keyboard for button in row}
            self.assertTrue({"ux:auto_toggle", "ux:faq_add", "ux:faqs", "ux:settings", "ux:ai", "ux:ai_toggle"} <= callbacks)
            self.assertEqual("ux:business_tools" in callbacks, mode == "business")
            after = await ext.export_owner(1)
            self.assertEqual(before["profile"], after["profile"])
            self.assertEqual(before["preferences"], after["preferences"])
            self.assertEqual(before["faqs"], after["faqs"])
            self.assertEqual(after["options"]["ui_mode"], mode)
            self.assertEqual(
                before["options"]["collect_requests"],
                after["options"]["collect_requests"],
            )

    async def test_ui_language_preserves_existing_reply_language(self):
        await db.update_profile_field(1, "native_language", "Tajik")
        await ux.navigation(self.callback("lang:en"), self.state())
        self.assertEqual((await db.get_profile(1))["native_language"], "Tajik")

    async def test_album_draft_recovers_after_restart(self):
        state = self.state()
        await state.set_state(ux.Flow.faq_answer)
        await state.set_data(
            {
                "question": "Photo",
                "album_token": "draft",
                "album_draft": [
                    {"type": "photo", "file_id": "file", "text": "", "entities": []}
                ],
            }
        )
        fresh = self.state()
        await ux.commit_draft(fresh, 1, 1, AsyncMock(), "draft")
        faq = (await db.get_faqs(1))[0]
        self.assertEqual(faq["answer_type"], "media_group")
        self.assertEqual(
            json.loads(faq["answer_payload"])["items"][0]["file_id"], "file"
        )
        self.assertIsNone(await fresh.get_state())

    async def test_cancelled_album_is_not_saved(self):
        state = self.state()
        await state.set_state(ux.Flow.faq_answer)
        await state.set_data(
            {
                "question": "Photo",
                "album_token": "draft",
                "album_draft": [{"type": "photo", "file_id": "file"}],
            }
        )
        await state.clear()
        await ux.commit_draft(state, 1, 1, AsyncMock(), "draft")
        self.assertEqual(await db.count_faqs(1), 0)

    asyncSetUp = regression.DatabaseTests.asyncSetUp
    asyncTearDown = regression.DatabaseTests.asyncTearDown

    def callback(self, action):
        return SimpleNamespace(
            data="ux:" + action,
            bot=SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username="test_bot"))),
            from_user=SimpleNamespace(id=1, language_code="en"),
            answer=AsyncMock(),
            message=SimpleNamespace(
                edit_text=AsyncMock(), answer=AsyncMock(), answer_document=AsyncMock()
            ),
        )

    def state(self):
        return FSMContext(
            storage=SQLiteStorage(), key=StorageKey(bot_id=1, chat_id=1, user_id=1)
        )

    async def test_menu_routes_render_valid_text_and_buttons(self):
        await db.save_business_connection("conn", 1, True)
        await db.remember_chat(1, 100, peer_name="<Customer>", username="customer")
        await ext.record_event(1, 100, "fallback", "What does this cost?")
        request_id = await ext.save_request(1, 100, "booking", "Friday")
        await ext.append_faq(1, "Price", {"type": "text", "text": "10"})
        faq_id = (await db.get_faqs(1))[0]["id"]
        actions = [
            "ai",
            "ai_setup",
            "ai_behavior",
            "setup",
            "status",
            "knowledge",
            "settings",
            "templates",
            "stats",
            "requests",
            "premium",
            "referrals",
            "schedule",
            "inbox:0",
            "chat:100",
            f"faq:{faq_id}",
            f"delete_confirm:{faq_id}",
            "suggestions",
            f"request:{request_id}",
            "forget_confirm:100",
        ]
        for action in actions:
            with self.subTest(action=action):
                callback = self.callback(action)
                await ux.navigation(callback, self.state())
                callback.message.edit_text.assert_awaited_once()
                call = callback.message.edit_text.await_args
                self.assertLessEqual(len(call.args[0].encode("utf-16-le")) // 2, 4096)
                for row in call.kwargs["reply_markup"].inline_keyboard:
                    for button in row:
                        self.assertLessEqual(len(button.callback_data.encode()), 64)

    async def test_modes_and_undo(self):
        callback = self.callback("mode:paused")
        await ux.navigation(callback, self.state())
        self.assertFalse((await db.get_preferences(1))["autoreply_enabled"])
        await ux.navigation(self.callback("undo"), self.state())
        self.assertTrue((await db.get_preferences(1))["autoreply_enabled"])
        await ux.navigation(self.callback("mode:faq"), self.state())
        self.assertFalse((await db.get_profile(1))["ai_enabled"])
        await ux.navigation(self.callback("mode:ai"), self.state())
        self.assertTrue((await db.get_profile(1))["ai_enabled"])

    async def test_language_uses_telegram_then_manual_choice(self):
        self.assertEqual(await ux.language(self.callback("setup").from_user), "en")
        await ux.navigation(self.callback("lang:ru"), self.state())
        self.assertEqual((await ext.options(1))["language"], "ru")
        self.assertEqual((await db.get_profile(1))["native_language"], "Русский")

    async def test_export_document_has_no_secrets(self):
        callback = self.callback("export")
        await ux.navigation(callback, self.state())
        document = callback.message.answer_document.await_args.args[0]
        data = json.loads(document.data)
        self.assertEqual(data["format"], "autoreply-v1")
        self.assertNotIn("ai_providers", data)

    async def test_import_requires_pending_confirmation(self):
        callback = self.callback("unused")
        state = self.state()
        await ux.apply_import(callback, state)
        self.assertEqual(await db.count_faqs(1), 0)
        await state.set_state(ux.Flow.imported)
        await state.set_data(
            {
                "import_data": {
                    "format": "autoreply-v1",
                    "faqs": [{"question": "Price", "answer": "10"}],
                }
            }
        )
        await ux.apply_import(callback, state)
        self.assertEqual(await db.count_faqs(1), 1)
        self.assertIsNone(await state.get_state())

    async def test_sandbox_faq_does_not_consume_ai_quota(self):
        await ext.options(1, "en")
        await ext.append_faq(1, "Price", {"type": "text", "text": "10"})
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=1, language_code="en"),
            text="Price",
            answer=AsyncMock(),
            bot=AsyncMock(),
            chat=SimpleNamespace(id=1),
        )
        with patch("ai_service.get_ai_reply", AsyncMock()) as generate:
            await ux.test_reply(message, self.state())
            generate.assert_not_called()
        self.assertIn("Source: FAQ", message.answer.await_args.args[0])
        message.bot.send_message.assert_awaited_once()
        self.assertEqual((await db.get_user_quota_status(1))["used"], 0)


if __name__ == "__main__":
    unittest.main()

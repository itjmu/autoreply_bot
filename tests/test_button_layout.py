import asyncio
import json
import unittest
from difflib import SequenceMatcher
from unittest.mock import AsyncMock, patch

import test_regressions as regression
import test_experience as interface
import database as db
import extensions as ext
import experience as ux
import business_runtime as runtime
from button_layout import button_rows, parse_rows, menu_rows


class LayoutTests(unittest.TestCase):
    def test_optimized_matcher_preserves_reference_results(self):
        from matcher import normalize_text, find_direct_answer
        faqs = [{"question": text} for text in ("Price", "Price?", "Cancel order", "Hello there", "Shipping time", "Payment methods", "", "да", "Where is my order", "Return policy")]
        def reference_score(first, second):
            first, second = normalize_text(first), normalize_text(second)
            if not first or not second:
                return 0.0
            if first == second:
                return 1.0
            if (len(first) >= 5 and first in second) or (len(second) >= 5 and second in first):
                return 0.0
            return SequenceMatcher(None, first, second).ratio()
        for query in ("Price?", "Do not cancel order", "Hello", "How long does shipping take?", "Payment method", "", "да", "Order location", "abcdefgh", "policy return"):
            scores = [reference_score(query, item["question"]) for item in faqs]
            best = max(scores)
            for threshold in (0.2, 0.78, 1.0):
                expected = faqs[scores.index(best)] if best > 0 and best >= threshold else None
                result, score = find_direct_answer(query, faqs, threshold)
                self.assertEqual(result, expected)
                self.assertEqual(score, best)

    def test_custom_rows_and_default_pairs(self):
        self.assertEqual(parse_rows("1 2\n3", 3), [[0, 1], [2]])
        buttons = [{"text": str(i), "url": "https://example.com"} for i in range(5)]
        self.assertEqual([len(r) for r in button_rows({"buttons": buttons})], [2, 2, 1])
        self.assertEqual(button_rows({"buttons": buttons, "button_rows": [[2, 0, 1], [4, 3]]})[0], [buttons[2], buttons[0], buttons[1]])

    def test_invalid_rows_rejected(self):
        for text in ("", "1 1\n2", "1", "0 1 2", "1 2 4", "1 2 3 4", "1\n\n2 3", "x y z"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_rows(text, 3)

    def test_compact_menu_preserves_actions_and_back(self):
        rows = [[("Export", "ux:export")], [("Import", "ux:import")], [("Back", "ux:home")]]
        compact = menu_rows(rows)
        self.assertEqual([len(row) for row in compact], [2, 1])
        self.assertEqual(compact[0][0][0], "📤 Export")
        self.assertEqual([data for row in compact for _, data in row], ["ux:export", "ux:import", "ux:home"])


class StoredLayoutTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = regression.DatabaseTests.asyncSetUp
    asyncTearDown = regression.DatabaseTests.asyncTearDown
    callback = interface.InterfaceTests.callback
    state = interface.InterfaceTests.state

    async def test_layout_save_export_and_real_render(self):
        from bot import send_faq_answer
        await ext.set_option(1, "ui_mode", "business")
        buttons = [{"text": "One", "url": "https://example.com"}, {"text": "Two", "command": "/two"}, {"text": "Three", "url": "https://example.org"}]
        await ext.append_faq(1, "Hello", {"type": "text", "text": "Hello", "payload": {"buttons": buttons}})
        faq = (await db.get_faqs(1))[0]
        state = self.state()
        await ux.navigation(self.callback(f"faq_layout:{faq['id']}"), state)
        message = self.callback("unused").message
        message.from_user = self.callback("unused").from_user
        message.text = "1 2\n3"
        await ux.save_faq_layout(message, state)
        await ext.import_owner(1, await ext.export_owner(1))
        faq = (await db.get_faqs(1))[0]
        self.assertEqual(json.loads(faq["answer_payload"])["button_rows"], [[0, 1], [2]])
        bot = AsyncMock()
        await send_faq_answer(bot, 100, "conn", faq)
        rows = bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard
        self.assertEqual([len(row) for row in rows], [2, 1])
        self.assertTrue(rows[0][1].callback_data.startswith("fqcall:1:"))

    async def test_preview_is_private_and_does_not_reserve_ai(self):
        await ext.append_faq(1, "Hello", {"type": "text", "text": "Hello"})
        faq = (await db.get_faqs(1))[0]
        callback = self.callback(f"faq_preview:{faq['id']}")
        with patch("bot.send_faq_answer", AsyncMock()) as send, patch("database.reserve_user_ai_slot", AsyncMock()) as reserve:
            await ux.navigation(callback, self.state())
        self.assertEqual(send.await_args.args[1:3], (1, None))
        reserve.assert_not_awaited()

    async def test_layout_rejects_changed_buttons_and_bad_export(self):
        spec = {"type": "text", "text": "Hello", "payload": {"buttons": [{"text": "One", "url": "https://example.com"}], "button_rows": [[0, 0]]}}
        with self.assertRaises(ValueError):
            await ext.append_faq(1, "Hello", spec)
        self.assertEqual(await db.count_faqs(1), 0)


class DelayWakeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = regression.DatabaseTests.asyncSetUp
    asyncTearDown = regression.BusinessTests.asyncTearDown
    ready = regression.BusinessTests.ready
    message = regression.BusinessTests.message

    async def test_new_question_interrupts_an_hour_long_old_delay(self):
        await self.ready()
        await ext.set_option(1, "ui_mode", "business")
        await ext.append_faq(1, "First", {"type": "text", "text": "Old", "payload": {"delay": 3600}})
        await ext.append_faq(1, "Next", {"type": "text", "text": "New", "payload": {"delay": 1}})
        bot = AsyncMock()
        with patch.object(runtime, "CHAT_DEBOUNCE", 0), patch.object(runtime, "AUTO_REPLY_DELAY", 0), patch("bot.send_faq_answer", AsyncMock()) as send:
            await runtime.enqueue(self.message(text="First"), bot)
            async def wait_for_delay():
                while (1, 100) not in runtime._wake:
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(wait_for_delay(), 10)
            await runtime.enqueue(self.message(number=2, text="Next"), bot)
            await asyncio.wait_for(runtime._workers[(1, 100)], 10)
            send.assert_awaited_once()
            self.assertEqual(send.await_args.args[3]["answer"], "New")
        self.assertNotIn((1, 100), runtime._wake)

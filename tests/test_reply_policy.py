import json
import unittest
from unittest.mock import AsyncMock, patch

import test_regressions as regression
import business_runtime as runtime
import extensions as ext
from reply_policy import match_faq, validate_delay, mode_faq, mode_delay


class ReplyPolicyTests(unittest.TestCase):
    def test_command_calls_faq_without_question_similarity(self):
        faq = {"question": "How much?", "answer_payload": json.dumps({"command": "/prices"})}
        self.assertIs(match_faq("/prices", [faq], 0.99)[0], faq)
        self.assertIsNone(match_faq("/prices", [faq], 0.99, allow_commands=False)[0])

    def test_ai_trailing_ok_is_removed_but_single_ok_is_preserved(self):
        from reply_safety import sanitize_reply
        self.assertEqual(sanitize_reply("Ответ на вопрос.\nОК"), "Ответ на вопрос.")
        self.assertEqual(sanitize_reply("Answer.\n\nOK."), "Answer.")
        self.assertEqual(sanitize_reply("OK"), "OK")
        self.assertEqual(sanitize_reply("Нажмите ОК для подтверждения."), "Нажмите ОК для подтверждения.")
    def test_modes_use_shared_faq_without_mutating_business_extensions(self):
        faq = {"answer_type": "sequence", "answer_payload": json.dumps({"items": [{"type": "text", "text": "First"}, {"type": "text", "text": "Second"}], "buttons": [{"text": "Site", "url": "https://example.com"}], "delay": 3600})}
        personal = mode_faq(faq, "personal")
        self.assertEqual(personal["answer"], "First")
        self.assertNotIn("buttons", json.loads(personal["answer_payload"]))
        self.assertEqual(mode_faq(faq, "business"), faq)
        self.assertEqual(mode_delay({}, "personal", "faq", faq), 60)
        self.assertEqual(mode_delay({}, "business", "faq", faq), 3600)
        self.assertEqual(mode_delay({"ai_delay": 3600, "personal_ai_delay": 5}, "personal", "ai"), 5)

    def test_ignore_is_exact_and_does_not_swallow_a_question(self):
        ignored = {"question": "ОК", "answer_payload": json.dumps({"ignore": True})}
        self.assertIs(match_faq("ок!", [ignored], 0.5)[0], ignored)
        self.assertIsNone(match_faq("ОК, когда доставка?", [ignored], 0.5)[0])

    def test_delay_bounds(self):
        for value in (1, 60):
            self.assertEqual(validate_delay(value), value)
        for value in (0, 61, True, "3", 1.5):
            with self.assertRaises(ValueError):
                validate_delay(value)


class RuntimeReplyPolicyTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = regression.DatabaseTests.asyncSetUp
    asyncTearDown = regression.BusinessTests.asyncTearDown
    ready = regression.BusinessTests.ready
    message = regression.BusinessTests.message

    async def test_ignored_faq_never_calls_ai_or_fallback(self):
        await self.ready()
        await ext.append_faq(1, "ОК", {"type": "text", "text": "[Не отвечать]", "payload": {"ignore": True}})
        runtime._generation[(1, 100)] = 1
        with patch("bot.send_faq_answer", AsyncMock()) as faq, patch("ai_service.get_ai_reply", AsyncMock()) as ai, patch("bot.send_fallback_message", AsyncMock()) as fallback:
            await runtime._reply((1, 100), 1, self.message(text="ОК"), "ОК", AsyncMock())
        faq.assert_not_awaited()
        ai.assert_not_awaited()
        fallback.assert_not_awaited()

    async def test_owner_pause_during_faq_delay_prevents_send(self):
        await self.ready()
        await ext.append_faq(1, "Цена", {"type": "text", "text": "100", "payload": {"delay": 60}})
        runtime._generation[(1, 100)] = 1
        async def pause_during_sleep(seconds):
            self.assertGreater(seconds, 50)
            await ext.handoff(1, 100, True, "owner")
        with patch.object(runtime.asyncio, "sleep", side_effect=pause_during_sleep), patch("bot.send_faq_answer", AsyncMock()) as send:
            await runtime._reply((1, 100), 1, self.message(text="Цена"), "Цена", AsyncMock())
        send.assert_not_awaited()

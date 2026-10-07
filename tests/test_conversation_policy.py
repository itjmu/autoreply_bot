import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import test_regressions as regression
import business_runtime as runtime
import database as db
import extensions as ext
from conversation_policy import is_acknowledgement, should_silence_acknowledgement


class AcknowledgementTests(unittest.TestCase):
    def test_short_acknowledgements_after_closing_reply_are_silent(self):
        for text in (
            "ок",
            "ОКЕЙ!",
            "понял",
            "поняла, спасибо",
            "Хорошо, подожду",
            "жду",
            "ясно",
            "принято",
            "хорошо буду ждать",
            "спасибо за информацию",
            "👍",
            "👍🏻",
            "фаҳмо",
            "хуб",
            "rahmat",
            "xo'p",
        ):
            with self.subTest(text=text):
                self.assertTrue(
                    should_silence_acknowledgement(
                        text, "Этот вопрос уточнит владелец."
                    )
                )

    def test_questions_and_new_information_are_not_silenced(self):
        for text in (
            "когда",
            "как передал",
            "когда он ответит?",
            "ок, а когда",
            "ок?",
            "окей, изменился адрес",
            "спасибо, сколько стоит доставка",
            "хорошо подожду 2 часа",
            "нет",
            "/booking Friday",
        ):
            with self.subTest(text=text):
                self.assertFalse(is_acknowledgement(text))

    def test_first_message_is_not_silenced(self):
        self.assertFalse(should_silence_acknowledgement("хорошо", ""))

    def test_answer_to_a_clarifying_question_is_not_silenced(self):
        self.assertFalse(should_silence_acknowledgement("да", "Вам удобно завтра?"))
        self.assertFalse(
            should_silence_acknowledgement("хорошо", "Подтвердите выбранную дату.")
        )


class ConversationRuntimeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = regression.DatabaseTests.asyncSetUp
    asyncTearDown = regression.BusinessTests.asyncTearDown
    ready = regression.BusinessTests.ready
    message = regression.BusinessTests.message

    async def test_acknowledgement_does_not_call_ai_or_faq_and_keeps_history(self):
        await self.ready()
        await db.add_chat_message(1, 100, "assistant", "Этот вопрос уточнит владелец.")
        await ext.append_faq(1, "ок", {"type": "text", "text": "Do not repeat this"})
        bot = AsyncMock()
        with (
            patch("ai_service.get_ai_reply", AsyncMock()) as ai,
            patch("bot.send_faq_answer", AsyncMock()) as faq,
        ):
            for number, text in enumerate(
                ("хорошо", "ок", "понял", "подожду", "жду"), 1
            ):
                await runtime.enqueue(self.message(number=number, text=text), bot)
        ai.assert_not_awaited()
        faq.assert_not_awaited()
        bot.send_message.assert_not_awaited()
        self.assertNotIn((1, 100), runtime._workers)
        self.assertFalse(await ext.is_handoff(1, 100))
        self.assertEqual((await db.get_user_quota_status(1))["used"], 0)
        self.assertEqual((await db.get_chat_history(1, 100, 10))[-1]["content"], "жду")

    async def test_new_question_after_acknowledgement_can_receive_faq(self):
        await self.ready()
        await db.add_chat_message(1, 100, "assistant", "Этот вопрос уточнит владелец.")
        await ext.append_faq(
            1, "Когда?", {"type": "text", "text": "Ответ в рабочие часы."}
        )
        bot = AsyncMock()
        with (
            patch.object(runtime, "CHAT_DEBOUNCE", 0),
            patch.object(runtime, "AUTO_REPLY_DELAY", 0),
            patch("bot.send_faq_answer", AsyncMock()) as faq,
        ):
            await runtime.enqueue(self.message(text="ок"), bot)
            await runtime.enqueue(self.message(number=2, text="Когда?"), bot)
            await asyncio.wait_for(runtime._workers[(1, 100)], 10)
        faq.assert_awaited_once()
        self.assertFalse(await ext.is_handoff(1, 100))

    async def test_question_never_releases_an_owner_pause(self):
        await self.ready()
        await runtime.takeover(1, 100)
        bot = AsyncMock()
        await runtime.enqueue(self.message(text="когда?"), bot)
        self.assertTrue(await ext.is_handoff(1, 100))
        self.assertNotIn((1, 100), runtime._workers)
        bot.send_message.assert_not_awaited()

    async def test_late_worker_check_suppresses_an_already_queued_ack(self):
        await self.ready()
        await db.add_chat_message(1, 100, "assistant", "Этот вопрос уточнит владелец.")
        runtime._generation[(1, 100)] = 1
        with (
            patch("bot._send_business_answer", AsyncMock()) as send,
            patch("ai_service.get_ai_reply", AsyncMock()) as ai,
        ):
            await runtime._reply(
                (1, 100), 1, self.message(text="ок"), "ок", AsyncMock()
            )
        send.assert_not_awaited()
        ai.assert_not_awaited()
        runtime._generation.pop((1, 100), None)


if __name__ == "__main__":
    unittest.main()

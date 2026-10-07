import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_regressions as regression
import test_experience as experience_tests
import ai_service as ai
import database as db
import extensions as ext
import experience as ux
from assistant_rules import (
    DEFAULTS,
    FALLBACK_SIGNAL,
    ambiguous_greeting,
    build_prompt,
    greeting_reply,
    validate_settings,
)


class PromptTests(unittest.TestCase):
    def test_ambiguous_greeting_uses_primary_language(self):
        self.assertEqual(
            greeting_reply("салом!", ["Русский", "Таджикский"]),
            "Привет! Чем могу помочь?",
        )
        self.assertTrue(
            greeting_reply("salom", ["Таджикский", "Русский"]).startswith("Салом!")
        )
        self.assertEqual(
            greeting_reply("салом", ["English", "Русский"]), "Hello! How can I help?"
        )

    def test_ambiguity_does_not_override_a_real_question(self):
        for text in (
            "салом сколько стоит ремонт",
            "салом 123",
            "салом, можно записаться?",
        ):
            self.assertFalse(ambiguous_greeting(text))
            self.assertIsNone(greeting_reply(text, ["Русский"]))

    def test_ambiguous_greeting_overrides_customer_language_guess(self):
        prompt = build_prompt(
            {}, [], ["Русский"], {"language": "customer"}, user_text="салом"
        )
        self.assertIn("Не определяй язык по этому слову", prompt)
        self.assertIn('"primary_language": "Русский"', prompt)

    def test_primary_language_is_consistent_with_preferences(self):
        prompt = build_prompt(
            {"native_language": "English"}, [], ["Таджикский", "Русский"]
        )
        self.assertIn('"primary_language": "Таджикский"', prompt)

    def test_facts_rules_and_examples_have_separate_sections(self):
        prompt = build_prompt(
            {"ai_description": "Legacy facts"},
            [],
            ["English"],
            {
                "facts": "Open 9–18",
                "rules": "No discounts",
                "examples": "Friendly example",
            },
        )
        self.assertIn('"owner_facts": "Open 9–18"', prompt)
        self.assertIn('"owner_rules": "No discounts"', prompt)
        self.assertIn('"style_examples": "Friendly example"', prompt)
        self.assertIn('"legacy_description": "Legacy facts"', prompt)
        self.assertIn("Не выдавай себя за владельца", prompt)

    def test_ai_sees_all_faq_sequence_captions(self):
        faq = {
            "question": "Services",
            "answer_type": "sequence",
            "answer_payload": json.dumps(
                {
                    "items": [
                        {"type": "text", "text": "Repair"},
                        {
                            "type": "photo",
                            "text": "Diagnostic: 100",
                            "file_id": "photo",
                        },
                    ]
                }
            ),
        }
        prompt = build_prompt({}, [faq], ["English"])
        self.assertIn("Repair", prompt)
        self.assertIn("Diagnostic: 100", prompt)
        self.assertNotIn('"file_id"', prompt)

    def test_invalid_settings_are_rejected(self):
        for settings in (
            {"style": "random"},
            {"memory": 1},
            {"facts": "x" * 4001},
            {"api_key": "secret"},
        ):
            with self.assertRaises(ValueError):
                validate_settings(settings)


class AssistantFlowTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = regression.DatabaseTests.asyncSetUp
    asyncTearDown = regression.DatabaseTests.asyncTearDown
    state = experience_tests.InterfaceTests.state
    callback = experience_tests.InterfaceTests.callback

    async def test_connected_account_greeting_does_not_use_ai_or_quota(self):
        import business_runtime as runtime

        await db.save_business_connection("conn", 1, True)
        await db.remember_chat(1, 100, peer_name="Customer", username="customer")
        await db.set_preference(1, "primary_language", "Таджикский")
        if not (await db.get_profile(1))["ai_enabled"]:
            await db.toggle_ai(1)
        key = (1, 100)
        runtime._generation[key] = 1
        message = SimpleNamespace(business_connection_id="conn")
        try:
            with patch("bot._send_business_answer", AsyncMock()) as send, patch("ai_service.get_ai_reply", AsyncMock()) as generate:
                await runtime._reply(key, 1, message, "салом", AsyncMock())
            generate.assert_not_awaited()
            send.assert_awaited_once()
            self.assertTrue(send.await_args.args[3].startswith("Салом!"))
            self.assertEqual((await db.get_user_quota_status(1))["used"], 0)
            self.assertEqual((await ext.statistics(1))[0][0], "greeting")
        finally:
            runtime._generation.pop(key, None)

    async def test_settings_are_owner_scoped_and_survive_export_undo(self):
        await ext.save_assistant_settings(1, {"facts": "Open 9–18", "style": "formal"})
        self.assertEqual((await ext.assistant_settings(2))["facts"], "")
        exported = await ext.export_owner(1)
        await ext.save_undo(1)
        await ext.save_assistant_settings(1, {"facts": "Changed"})
        await ext.restore_undo(1)
        self.assertEqual((await ext.assistant_settings(1))["facts"], "Open 9–18")
        await ext.import_owner(2, exported)
        self.assertEqual((await ext.assistant_settings(2))["style"], "formal")

    async def test_wizard_does_not_save_until_confirmation(self):
        state = self.state()
        before = await ext.assistant_settings(1)
        await ux.navigation(self.callback("ai_preset:shop"), state)
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=1, language_code="en"),
            text="Verified facts",
            answer=AsyncMock(),
        )
        await ux.assistant_setup_value(message, state)
        message.text = "Do not confirm orders"
        await ux.assistant_setup_value(message, state)
        self.assertEqual(await ext.assistant_settings(1), before)
        await ux.confirm_assistant(self.callback("ai_confirm"), state)
        self.assertEqual((await ext.assistant_settings(1))["facts"], "Verified facts")
        self.assertEqual(
            (await ext.assistant_settings(1))["rules"], "Do not confirm orders"
        )
        self.assertIsNone(await state.get_state())

    async def test_cancelled_wizard_cannot_be_confirmed(self):
        state = self.state()
        await ux.navigation(self.callback("ai_preset:shop"), state)
        await state.clear()
        await ux.confirm_assistant(self.callback("ai_confirm"), state)
        self.assertEqual(await ext.assistant_settings(1), DEFAULTS)

    async def test_prompt_uses_saved_settings_and_disables_memory(self):
        await ext.save_assistant_settings(1, {"facts": "Actual facts", "memory": False})
        captured = {}

        async def generate(**kwargs):
            captured.update(kwargs)
            captured["history"] = ai._history.get()
            return ai.AIResult(ok=True, text="Reply")

        with patch.object(ai, "generate_ai", generate):
            await ai.get_ai_reply(
                user_text="Question",
                profile=await db.get_profile(1),
                faq_context=[],
                languages=["Русский"],
                history=[{"role": "user", "content": "Earlier"}],
            )
        self.assertIn("Actual facts", captured["system_prompt"])
        self.assertEqual(captured["history"], [])
        self.assertEqual(ai._history.get(), [])

    async def test_fallback_signal_is_not_exposed_as_an_answer(self):
        await ext.save_assistant_settings(1, {"unknown": "fallback"})
        with patch.object(
            ai,
            "generate_ai",
            AsyncMock(return_value=ai.AIResult(ok=True, text=FALLBACK_SIGNAL)),
        ):
            result = await ai.get_ai_reply(
                user_text="Unknown question",
                profile=await db.get_profile(1),
                faq_context=[],
                languages=["Русский"],
            )
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "needs_owner")
        self.assertIsNone(result.text)

    async def test_greeting_is_local_and_test_quota_is_unchanged(self):
        await ext.options(1, "en")
        await db.set_preference(1, "primary_language", "Таджикский")
        profile = await db.get_profile(1)
        if not profile["ai_enabled"]:
            await db.toggle_ai(1)
        state = self.state()
        await state.set_state(ux.Flow.test)
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=1, language_code="en"),
            text="салом",
            answer=AsyncMock(),
            chat=SimpleNamespace(id=1),
            bot=AsyncMock(),
        )
        with patch.object(ai, "generate_ai", AsyncMock()) as generate:
            await ux.test_reply(message, state)
        generate.assert_not_awaited()
        self.assertIn("Салом!", message.answer.await_args.args[0])
        self.assertEqual((await db.get_user_quota_status(1))["used"], 0)
        self.assertEqual(len((await state.get_data())["test_history"]), 2)

    async def test_feedback_is_saved_as_style_not_verified_facts(self):
        state = self.state()
        await state.set_state(ux.Flow.ai_feedback)
        await state.set_data({"feedback_question": "салом"})
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=1, language_code="en"),
            text="Салом!",
            answer=AsyncMock(),
        )
        await ux.save_assistant_feedback(message, state)
        settings = await ext.assistant_settings(1)
        self.assertIn("Салом!", settings["examples"])
        self.assertEqual(settings["facts"], "")


if __name__ == "__main__":
    unittest.main()

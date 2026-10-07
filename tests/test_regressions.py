import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["BOT_TOKEN"] = "123456:TEST_NOT_A_REAL_TOKEN"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

import database as db
import extensions as ext
import ai_service as ai
from matcher import find_direct_answer, similarity
from policy import find_blocked_topic
from backup_db import backup, restore


class PureTests(unittest.TestCase):
    def test_overnight_schedule(self):
        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 5, 23, 0, tzinfo=tz)

        prefs = {
            "schedule_enabled": 1,
            "timezone": "Asia/Karachi",
            "schedule_start": "22:00",
            "schedule_end": "06:00",
        }
        with patch.object(db, "datetime", Frozen):
            self.assertTrue(db.schedule_is_active(prefs))
            prefs.update(schedule_start="09:00", schedule_end="18:00")
            self.assertFalse(db.schedule_is_active(prefs))

    def test_reasoning_filter_fails_closed(self):
        from bot import _strip_reasoning

        self.assertEqual(
            _strip_reasoning("<think>secret</think>Final answer"), "Final answer"
        )
        self.assertEqual(_strip_reasoning("<reasoning>unclosed secret"), "")
        self.assertEqual(
            _strip_reasoning("Final answer<analysis>unclosed secret"), "Final answer"
        )

    def test_negated_substring_does_not_match(self):
        self.assertEqual(similarity("cancel order", "do not cancel order"), 0)

    def test_exact_faq(self):
        item, score = find_direct_answer(
            "Price?", [{"question": "price", "answer": "10"}], 0.78
        )
        self.assertEqual(score, 1)
        self.assertIsNotNone(item)

    def test_blocked_word_boundary(self):
        self.assertIsNone(find_blocked_topic("classification", "ass"))
        self.assertEqual(find_blocked_topic("buy drugs now", "drugs"), "drugs")

    def test_subscription_extends_current_expiry(self):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        current = now + timedelta(days=20)
        self.assertEqual(
            datetime.fromisoformat(ext.extended_expiry(current.isoformat(), 7, now)),
            current + timedelta(days=7),
        )

    def test_subscription_extends_expired_from_now(self):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        self.assertEqual(
            datetime.fromisoformat(ext.extended_expiry("", 7, now)),
            now + timedelta(days=7),
        )

    def test_backup_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            src = Path(directory) / "source.db"
            with closing(sqlite3.connect(src)) as c:
                c.execute("CREATE TABLE sample(value TEXT)")
                c.execute("INSERT INTO sample VALUES('saved')")
                c.commit()
            copied = backup(src, Path(directory) / "backup.db")
            restored = restore(copied, Path(directory) / "restored.db")
            with closing(sqlite3.connect(restored)) as c:
                self.assertEqual(
                    c.execute("SELECT value FROM sample").fetchone()[0], "saved"
                )
            with self.assertRaises(ValueError):
                restore(copied, src)

    def test_import_rejects_privileged_fields(self):
        with self.assertRaises(ValueError):
            ext.validate_export(
                {"format": "autoreply-v1", "profile": {"plan": "premium"}}
            )


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_receipt_is_reconciled_and_idempotent(self):
        payload = await ext.recover_legacy_invoice(
            "premium:week", 1, "XTR", 25, "legacy-charge"
        )
        expiry, applied = await ext.apply_payment(
            payload, 1, "XTR", 25, "legacy-charge"
        )
        self.assertTrue(applied)
        _, applied = await ext.apply_payment(payload, 1, "XTR", 25, "legacy-charge")
        self.assertFalse(applied)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = db.DB_PATH
        db.DB_PATH = str(Path(self.temp.name) / "test.db")
        await db.init_db()
        await ext.init_schema()
        await db.ensure_user(1)
        await db.ensure_user(2)

    async def asyncTearDown(self):
        db.DB_PATH = self.old
        self.temp.cleanup()

    async def test_additive_migration_idempotent(self):
        await db.update_profile_field(1, "owner_name", "Original")
        await db.init_db()
        await ext.init_schema()
        self.assertEqual((await db.get_profile(1))["owner_name"], "Original")

    async def test_payment_replay_only_activates_once(self):
        payload = await ext.issue_invoice(1, "week", 7, 25)
        self.assertTrue(await ext.validate_invoice(payload, 1, "XTR", 25))
        expiry, applied = await ext.apply_payment(payload, 1, "XTR", 25, "charge-1")
        self.assertTrue(applied)
        again, applied = await ext.apply_payment(payload, 1, "XTR", 25, "charge-1")
        self.assertEqual(again, expiry)
        self.assertFalse(applied)
        self.assertFalse(await ext.validate_invoice(payload, 1, "XTR", 25))

    async def test_payment_terms_and_owner_validation(self):
        payload = await ext.issue_invoice(1, "week", 7, 25)
        for owner, currency, amount in [(2, "XTR", 25), (1, "USD", 25), (1, "XTR", 1)]:
            self.assertFalse(
                await ext.validate_invoice(payload, owner, currency, amount)
            )
            with self.assertRaises(ValueError):
                await ext.apply_payment(payload, owner, currency, amount, "charge-bad")

    async def test_renewal_keeps_paid_days(self):
        first = await db.set_premium(1, 30)
        second = await db.set_premium(1, 7)
        self.assertEqual(
            datetime.fromisoformat(second) - datetime.fromisoformat(first),
            timedelta(days=7),
        )

    async def test_quota_atomic_and_original_day_release(self):
        await db.set_global_setting("free_ai_daily_limit", "1")
        results = await asyncio.gather(
            db.reserve_user_ai_slot(1), db.reserve_user_ai_slot(1)
        )
        self.assertEqual(sum(r["allowed"] for r in results), 1)
        reservation = next(r for r in results if r["allowed"])
        with patch.object(db, "_owner_usage_day", AsyncMock(return_value="2099-01-01")):
            await db.release_user_ai_slot(1, reservation["day"])
        self.assertEqual((await db.get_user_quota_status(1))["used"], 0)

    async def test_handoff_scoped_and_persistent(self):
        await ext.handoff(1, 100)
        self.assertTrue(await ext.is_handoff(1, 100))
        self.assertFalse(await ext.is_handoff(2, 100))
        await ext.init_schema()
        self.assertTrue(await ext.is_handoff(1, 100))
        await ext.handoff(1, 100, False)
        self.assertFalse(await ext.is_handoff(1, 100))

    async def test_message_deduplication(self):
        self.assertTrue(await ext.claim_message("connection", 100, 1))
        self.assertFalse(await ext.claim_message("connection", 100, 1))
        self.assertTrue(await ext.claim_message("other", 100, 1))

    async def test_owner_export_no_secrets(self):
        await db.upsert_provider(
            "secret", "compatible", "SECRET", "https://example.com", "model"
        )
        data = await ext.export_owner(1)
        self.assertNotIn("SECRET", json.dumps(data))
        self.assertNotIn("plan", data["profile"])

    async def test_import_atomic_limit_and_owner_scope(self):
        await db.set_global_setting("free_faq_limit", "1")
        data = {
            "format": "autoreply-v1",
            "profile": {"owner_name": "Changed"},
            "faqs": [
                {"question": "A", "answer": "B"},
                {"question": "C", "answer": "D"},
            ],
        }
        with self.assertRaises(ValueError):
            await ext.import_owner(1, data)
        self.assertEqual((await db.get_profile(1))["owner_name"], "")
        data["faqs"] = data["faqs"][:1]
        self.assertEqual(await ext.import_owner(1, data), 1)
        self.assertEqual(await ext.import_owner(1, data), 0)
        self.assertEqual(await db.count_faqs(2), 0)

    async def test_undo_restores_profile_and_faq(self):
        await ext.append_faq(1, "Price", {"type": "text", "text": "10"})
        await ext.save_undo(1)
        await db.update_profile_field(1, "owner_name", "Changed")
        await db.delete_faq(1, (await db.get_faqs(1))[0]["id"])
        self.assertTrue(await ext.restore_undo(1))
        self.assertEqual(await db.count_faqs(1), 1)
        self.assertEqual((await db.get_profile(1))["owner_name"], "")

    async def test_request_owner_scope(self):
        request_id = await ext.save_request(1, 100, "booking", "Tomorrow 10:00")
        await ext.complete_request(2, request_id)
        self.assertEqual(len(await ext.requests(1)), 1)
        await ext.complete_request(1, request_id)
        self.assertEqual(await ext.requests(1), [])

    async def test_fsm_survives_new_storage(self):
        from fsm_storage import SQLiteStorage
        from aiogram.fsm.storage.base import StorageKey

        key = StorageKey(bot_id=1, chat_id=1, user_id=1)
        storage = SQLiteStorage()
        await storage.set_state(key, "setup")
        await storage.set_data(key, {"field": "name"})
        fresh = SQLiteStorage()
        self.assertEqual(await fresh.get_state(key), "setup")
        self.assertEqual(await fresh.get_data(key), {"field": "name"})

    async def test_forget_chat_owner_scope(self):
        await db.add_chat_message(1, 100, "user", "private")
        await db.add_chat_message(2, 100, "user", "other")
        await ext.forget_chat(1, 100)
        self.assertEqual(await db.get_chat_history(1, 100), [])
        self.assertEqual(len(await db.get_chat_history(2, 100)), 1)

    async def test_referral_race_awards_once(self):
        results = await asyncio.gather(
            db.record_referral(1, 2), db.record_referral(1, 2)
        )
        self.assertEqual(sum(results), 1)
        self.assertEqual((await db.get_profile(1))["bonus_ai_limit"], 1)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_internal_error_returns_fallback_result(self):
        with patch.object(
            ai, "_generate_ai", AsyncMock(side_effect=RuntimeError("mock failure"))
        ):
            result = await ai.generate_ai(system_prompt="test", user_text="test")
            self.assertFalse(result.ok)
            self.assertEqual(result.error_type, "internal")

    async def test_disable_all_is_respected(self):
        with patch.object(
            ai,
            "get_provider_list",
            AsyncMock(return_value=[{"name": "openai", "enabled": 0}]),
        ):
            self.assertEqual(await ai.active_provider_order({"openai": {}}), [])

    async def test_cooldown_provider_never_called(self):
        with (
            patch.object(
                ai, "get_all_providers", AsyncMock(return_value={"broken": {}})
            ),
            patch.object(
                ai, "active_provider_order", AsyncMock(return_value=["broken"])
            ),
            patch.object(ai, "_in_cooldown", return_value=True),
            patch.object(ai, "_call_provider", AsyncMock()) as call,
        ):
            result = await ai.generate_ai(system_prompt="test", user_text="test")
            self.assertFalse(result.ok)
            call.assert_not_called()

    async def test_overall_deadline(self):
        async def slow(**kwargs):
            await asyncio.sleep(2)

        with (
            patch.object(ai, "AI_TOTAL_TIMEOUT", 1),
            patch.object(ai, "_generate_ai", slow),
        ):
            result = await ai.generate_ai(system_prompt="test", user_text="test")
            self.assertEqual(result.error_type, "timeout")

    async def test_untrusted_history_not_in_system_prompt(self):
        captured = {}

        async def fake(**kwargs):
            captured.update(kwargs)
            captured["history"] = ai._history.get()
            return ai.AIResult(ok=True, text="ok")

        with patch.object(ai, "generate_ai", fake):
            await ai.get_ai_reply(
                user_text="Current",
                profile={},
                faq_context=[],
                languages=["English"],
                history=[
                    {"role": "user", "content": "INJECTED_UNTRUSTED"},
                    {"role": "user", "content": "Current"},
                ],
            )
        self.assertNotIn("INJECTED_UNTRUSTED", captured["system_prompt"])
        self.assertEqual(
            captured["history"], [{"role": "user", "content": "INJECTED_UNTRUSTED"}]
        )
        self.assertEqual(ai._history.get(), [])


class BusinessTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = DatabaseTests.asyncSetUp

    async def asyncTearDown(self):
        import business_runtime as runtime

        await runtime.shutdown()
        await DatabaseTests.asyncTearDown(self)

    def message(self, number=1, text="Question", user_id=3):
        return SimpleNamespace(
            business_connection_id="conn",
            sender_business_bot=None,
            from_user=SimpleNamespace(
                id=user_id, full_name="Customer", username="customer"
            ),
            chat=SimpleNamespace(id=100),
            message_id=number,
            text=text,
            caption=None,
            contact=None,
            date=datetime.now(timezone.utc),
        )

    async def ready(self):
        await db.save_business_connection("conn", 1, True)
        await db.remember_chat(1, 100, peer_name="Customer", username="customer")

    async def test_owner_reply_cancels_work_and_pauses(self):
        import business_runtime as runtime

        await self.ready()
        key = (1, 100)
        task = asyncio.create_task(asyncio.sleep(100))
        runtime._workers[key] = task
        runtime._generation[key] = 1
        await runtime.enqueue(self.message(text="Owner answer", user_id=1), AsyncMock())
        await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(await ext.is_handoff(*key))
        self.assertTrue(task.cancelled())
        runtime._workers.pop(key, None)
        runtime._generation.pop(key, None)

    async def test_owner_pause_silences_stop_and_request_confirmations(self):
        import business_runtime as runtime
        await self.ready()
        await ext.set_option(1, "collect_requests", 1)
        await runtime.takeover(1, 100)
        bot = AsyncMock()
        for number, text in enumerate(("stop ai", "/booking Friday", "Question"), 1):
            await runtime.enqueue(self.message(number=number, text=text), bot)
        bot.send_message.assert_not_awaited()
        self.assertEqual(await ext.requests(1), [])
        self.assertNotIn((1, 100), runtime._workers)

    async def test_takeover_invalidates_before_waiting_for_database(self):
        import business_runtime as runtime
        await self.ready()
        key = (1, 100)
        runtime._generation[key] = 1
        entered = asyncio.Event()
        release = asyncio.Event()

        async def persist(*args):
            entered.set()
            await release.wait()

        with patch.object(ext, "handoff", persist):
            task = asyncio.create_task(runtime.takeover(*key))
            await asyncio.wait_for(entered.wait(), 10)
            self.assertIn(key, runtime._taking_over)
            self.assertFalse(await runtime._can_send(key, 1))
            release.set()
            await task
        self.assertNotIn(key, runtime._taking_over)

    async def test_send_guard_rechecks_version_after_database_waits(self):
        import business_runtime as runtime
        await self.ready()
        key = (1, 100)
        runtime._generation[key] = 1

        async def allowed(*args):
            runtime.invalidate(*key)
            return True, None, None

        with patch.object(db, "should_autoreply", allowed):
            self.assertFalse(await runtime._can_send(key, 1))

    async def test_owner_pause_notification_is_sent_once(self):
        import business_runtime as runtime
        await self.ready()
        bot = AsyncMock()
        await runtime.enqueue(self.message(text="My reply", user_id=1), bot)
        await runtime.enqueue(self.message(number=2, text="More", user_id=1), bot)
        bot.send_message.assert_awaited_once()
        button = bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.callback_data, "ux:resume:100")

    async def test_takeover_cancels_ai_and_refunds_its_reserved_quota(self):
        import business_runtime as runtime
        await self.ready()
        key = (1, 100)
        runtime._generation[key] = 1
        entered = asyncio.Event()

        async def generate(**kwargs):
            entered.set()
            await asyncio.Event().wait()

        with patch("ai_service.get_ai_reply", generate), patch("bot._send_business_answer", AsyncMock()) as send:
            task = asyncio.create_task(runtime._reply(key, 1, self.message(), "Question", AsyncMock()))
            runtime._workers[key] = task
            await asyncio.wait_for(entered.wait(), 10)
            await runtime.takeover(*key)
            await asyncio.gather(task, return_exceptions=True)
            self.assertTrue(task.cancelled())
            send.assert_not_awaited()
            self.assertEqual((await db.get_user_quota_status(1))["used"], 0)
            await runtime.resume_chat(*key)
            self.assertFalse(await ext.is_handoff(*key))
        runtime._workers.pop(key, None)
        runtime._generation.pop(key, None)

    async def test_customer_stop_pauses_all_replies(self):
        import business_runtime as runtime

        await self.ready()
        with patch("bot._send_business_answer", AsyncMock()) as send:
            await runtime.enqueue(self.message(text="stop ai"), AsyncMock())
            self.assertTrue(await ext.is_handoff(1, 100))
            send.assert_awaited_once()
            await runtime.enqueue(self.message(number=2, text="Price?"), AsyncMock())
            self.assertNotIn((1, 100), runtime._workers)

    async def test_failed_faq_sends_fallback(self):
        import business_runtime as runtime

        await self.ready()
        await db.toggle_ai(1)
        await ext.append_faq(1, "Question", {"type": "text", "text": "FAQ answer"})
        key = (1, 100)
        runtime._generation[key] = 1
        with (
            patch(
                "bot.send_faq_answer",
                AsyncMock(side_effect=RuntimeError("mock send failure")),
            ),
            patch("bot._send_business_answer", AsyncMock()) as send,
        ):
            await runtime._reply(key, 1, self.message(), "Question", AsyncMock())
            send.assert_awaited_once()
            self.assertNotEqual(send.await_args.args[3], "FAQ answer")
        runtime._generation.pop(key, None)

    async def test_new_message_suppresses_stale_ai_and_refunds(self):
        import business_runtime as runtime

        await self.ready()
        began = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def generate(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                began.set()
                await release.wait()
            return ai.AIResult(ok=True, text="Reply " + kwargs["user_text"])

        with (
            patch.object(runtime, "CHAT_DEBOUNCE", 0),
            patch.object(runtime, "AUTO_REPLY_DELAY", 0),
            patch("ai_service.get_ai_reply", generate),
            patch("bot._send_business_answer", AsyncMock()) as send,
        ):
            await runtime.enqueue(self.message(text="First"), AsyncMock())
            # SQLite connections can take longer on a busy Windows runner.
            await asyncio.wait_for(began.wait(), 10)
            await runtime.enqueue(self.message(number=2, text="Second"), AsyncMock())
            task = runtime._workers[(1, 100)]
            release.set()
            await asyncio.wait_for(task, 10)
            send.assert_awaited_once()
            self.assertEqual(send.await_args.args[3], "Reply Second")
            self.assertEqual((await db.get_user_quota_status(1))["used"], 1)

    async def test_failed_ai_send_refunds_quota(self):
        import business_runtime as runtime

        await self.ready()
        key = (1, 100)
        runtime._generation[key] = 1
        with (
            patch(
                "ai_service.get_ai_reply",
                AsyncMock(return_value=ai.AIResult(ok=True, text="Reply")),
            ),
            patch(
                "bot._send_business_answer",
                AsyncMock(side_effect=RuntimeError("mock failure")),
            ),
        ):
            with self.assertRaises(RuntimeError):
                await runtime._reply(key, 1, self.message(), "Question", AsyncMock())
        self.assertEqual((await db.get_user_quota_status(1))["used"], 0)
        runtime._generation.pop(key, None)

    async def test_split_emoji_by_telegram_length(self):
        from bot import _send_business_answer

        bot = AsyncMock()
        await _send_business_answer(bot, 100, "conn", "🙂" * 3000)
        self.assertEqual(bot.send_message.await_count, 2)
        for call in bot.send_message.await_args_list:
            self.assertLessEqual(
                len(call.kwargs["text"].encode("utf-16-le")) // 2, 4000
            )

    async def test_booking_is_request_not_confirmation(self):
        import business_runtime as runtime

        await self.ready()
        await ext.set_option(1, "ui_mode", "business")
        await ext.set_option(1, "collect_requests", 1)
        with patch("bot._send_business_answer", AsyncMock()) as send:
            await runtime.enqueue(
                self.message(text="/booking Friday 10:00"), AsyncMock()
            )
            self.assertEqual(len(await ext.requests(1)), 1)
            self.assertTrue(await ext.is_handoff(1, 100))
            self.assertIn("confirm availability", send.await_args.args[3])


if __name__ == "__main__":
    unittest.main()

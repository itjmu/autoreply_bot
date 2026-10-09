"""Bounded per-chat processing, persistent takeover, and reply accounting."""

import asyncio
import logging
import time
from datetime import datetime, timezone

import database as db
import extensions as ext
from config import (
    ADMIN_IDS,
    AUTO_REPLY_DELAY,
    CHAT_DEBOUNCE,
    FAQ_MATCH_THRESHOLD,
    HISTORY_RETENTION_DAYS,
    USE_AI,
)
from matcher import find_direct_answer, select_ai_context
from policy import find_blocked_topic
from account_hub import record_activity, describe_spec

logger = logging.getLogger(__name__)
_workers = {}
_pending = {}
_generation = {}
_wake = {}
_taking_over = set()
_MAX_CHATS = 128
_MAX_PENDING = 20
_last_alert = 0


async def alert_admins(bot, reason):
    global _last_alert
    if time.monotonic() - _last_alert < 900:
        return
    _last_alert = time.monotonic()
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"AutoReply needs attention: {reason}. Check server logs. Customer contents and keys are omitted.",
            )
        except Exception:
            logger.warning("Admin alert failed")


async def notify_owner(bot, owner_id, chat_id, text, *, resume=False):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    try:
        await bot.send_message(
            owner_id,
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🤖 Пусть отвечает бот / Let bot reply" if resume else "🙋 Я отвечаю / I'll reply",
                            callback_data=f"ux:resume:{chat_id}" if resume else f"ux:takeover:{chat_id}",
                        )
                    ]
                ]
            ),
        )
    except Exception:
        logger.warning("Owner notification failed owner=%s", owner_id)


def invalidate(owner_id, chat_id):
    key = (owner_id, chat_id)
    _generation[key] = _generation.get(key, 0) + 1
    if key in _wake:
        _wake[key].set()
    _pending.pop(key, None)
    task = _workers.get(key)
    if task:
        task.cancel()
    if not task:
        _generation.pop(key, None)
        _wake.pop(key, None)


async def takeover(owner_id, chat_id, reason="owner replied"):
    """Block sends immediately, then persist the handoff before releasing the barrier."""
    key = (owner_id, chat_id)
    _taking_over.add(key)
    invalidate(owner_id, chat_id)
    try:
        already_paused = await ext.is_handoff(owner_id, chat_id)
        await ext.handoff(owner_id, chat_id, True, reason)
    except BaseException:
        # Keep the barrier if persistence fails; allowing a reply would interrupt the owner.
        raise
    else:
        _taking_over.discard(key)
        return not already_paused


async def resume_chat(owner_id, chat_id):
    key = (owner_id, chat_id)
    _taking_over.add(key)
    task = _workers.get(key)
    invalidate(owner_id, chat_id)
    if task:
        await asyncio.gather(task, return_exceptions=True)
    await ext.handoff(owner_id, chat_id, False)
    _taking_over.discard(key)


async def enqueue(message, bot):
    connection_id = message.business_connection_id
    if not connection_id or message.sender_business_bot:
        return
    owner_id = await db.get_owner_by_connection(connection_id)
    if not owner_id:
        try:
            connection = await bot.get_business_connection(connection_id)
            if not connection.is_enabled:
                return
            owner_id = connection.user.id
            await db.save_business_connection(connection.id, owner_id, True)
        except Exception:
            logger.exception("Business connection unavailable")
            return
    chat_id = message.chat.id
    if message.from_user and message.from_user.id == owner_id:
        changed = await takeover(owner_id, chat_id)
        await db.add_chat_message(
            owner_id, chat_id, "assistant", message.text or message.caption or "[media]"
        )
        await record_activity(bot, owner_id, chat_id, connection_id, "owner", message.text or message.caption or "[media]")
        if changed:
            await notify_owner(bot, owner_id, chat_id,
                "🙋 Вы начали отвечать сами. Бот больше не отправляет AI, FAQ и запасные сообщения в этот чат. Чтобы вернуть его, нажмите кнопку ниже. / Your reply paused the bot in this chat. Tap below to resume.", resume=True)
        return
    if not await ext.claim_message(connection_id, chat_id, message.message_id):
        return
    # Ignore old business messages while still preserving queued payment updates at startup.
    if (
        message.date
        and (datetime.now(timezone.utc) - message.date).total_seconds() > 3600
    ):
        return
    user = message.from_user
    await db.remember_chat(
        owner_id,
        chat_id,
        peer_name=user.full_name if user else "",
        username=user.username or "" if user else "",
    )
    profile = await db.get_profile(owner_id)
    if profile["blocked"]:
        return
    text = (message.text or message.caption or "").strip()
    await db.add_chat_message(owner_id, chat_id, "user", text or "[media]")
    await record_activity(bot, owner_id, chat_id, connection_id, "incoming", text or "[" + str(getattr(message, "content_type", "media")) + "]")
    # Silence every automatic path while the owner handles this conversation,
    # including stop acknowledgements and request confirmations.
    if (owner_id, chat_id) in _taking_over or await ext.is_handoff(owner_id, chat_id):
        await ext.record_event(owner_id, chat_id, "handoff", text)
        return
    from conversation_policy import is_acknowledgement, should_silence_acknowledgement
    if message.text and is_acknowledgement(text):
        previous_reply = await ext.last_assistant_reply(owner_id, chat_id)
        if should_silence_acknowledgement(text, previous_reply):
            await ext.record_event(owner_id, chat_id, "acknowledgement", text)
            return
    if text.lower() in {
        "стоп ии",
        "стоп ai",
        "stop ai",
        "stop ии",
        "стоп-ии",
        "/stop",
        "human",
        "оператор",
        "человек",
    }:
        await ext.handoff(owner_id, chat_id, True, "customer requested human")
        invalidate(owner_id, chat_id)
        await ext.record_event(owner_id, chat_id, "handoff", text)
        from bot import _send_business_answer

        await _send_business_answer(
            bot,
            chat_id,
            connection_id,
            "Автоответчик приостановлен. Владелец уведомлён. / Replies paused. The owner has been notified.",
        )
        await notify_owner(
            bot,
            owner_id,
            chat_id,
            "Customer requested a human / Клиент просит ответить лично.",
        )
        return
    opts = await ext.options(owner_id)
    kind = None
    if opts["collect_requests"] and opts["ui_mode"] == "business":
        lowered = text.lower()
        if lowered.startswith(("/booking ", "/запись ")):
            kind = "booking"
        elif lowered.startswith(("/order ", "/заказ ")):
            kind = "order"
        elif lowered.startswith(("/contact ", "/контакт ")) or message.contact:
            kind = "contact"
    if kind:
        details = (
            text.split(" ", 1)[-1]
            if not message.contact
            else f"{message.contact.first_name}: {message.contact.phone_number}"
        )
        await ext.save_request(owner_id, chat_id, kind, details)
        await ext.handoff(owner_id, chat_id, True, "request awaiting owner")
        invalidate(owner_id, chat_id)
        from bot import _send_business_answer

        await _send_business_answer(
            bot,
            chat_id,
            connection_id,
            "Запрос передан владельцу. Запись подтвердит человек. / Request sent to the owner. A person will confirm availability.",
        )
        await notify_owner(
            bot,
            owner_id,
            chat_id,
            f"New {kind} request / Новый запрос: {details[:1000]}",
        )
        return
    allowed = await _autoreply_allowed(owner_id, chat_id)
    if not allowed:
        return
    key = (owner_id, chat_id)
    if key not in _workers and len(_workers) >= _MAX_CHATS:
        await ext.record_event(owner_id, chat_id, "error", text, False)
        return
    if len(_pending.get(key, [])) >= _MAX_PENDING:
        await ext.record_event(owner_id, chat_id, "error", text, False)
        return
    _pending.setdefault(key, []).append(message)
    _generation[key] = _generation.get(key, 0) + 1
    if key in _wake:
        _wake[key].set()
    if key not in _workers:
        _workers[key] = asyncio.create_task(_worker(key, bot))


async def _worker(key, bot):
    try:
        while _pending.get(key):
            await asyncio.sleep(max(0, CHAT_DEBOUNCE, AUTO_REPLY_DELAY))
            batch = _pending.pop(key, [])
            version = _generation[key]
            text = "\n".join((m.text or m.caption or "") for m in batch).strip()[-4000:]
            if getattr(batch[-1], "reply_command", False):
                text = batch[-1].text
            try:
                await _reply(key, version, batch[-1], text, bot)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Chat processing failed owner=%s chat=%s", *key)
                await ext.record_event(*key, "error", text, False)
                await alert_admins(bot, "reply processing failed")
    finally:
        _workers.pop(key, None)
        _pending.pop(key, None)
        _generation.pop(key, None)
        _wake.pop(key, None)


async def _autoreply_allowed(owner_id, chat_id):
    allowed, reason, _ = await db.should_autoreply(owner_id, chat_id)
    if reason == "schedule" and (await ext.options(owner_id))["ui_mode"] == "personal":
        return True
    return allowed


async def _can_send(key, version):
    if key in _taking_over or _generation.get(key) != version or await ext.is_handoff(*key):
        return False
    allowed = await _autoreply_allowed(*key)
    profile = await db.get_profile(key[0])
    if not allowed or profile["blocked"] or await ext.is_handoff(*key):
        return False
    return key not in _taking_over and _generation.get(key) == version


async def _delay_until(key, version, started, seconds):
    remaining = max(0, seconds - (time.monotonic() - started))
    if remaining and _generation.get(key) == version:
        wake = _wake.setdefault(key, asyncio.Event())
        wake.clear()
        sleeper = asyncio.create_task(asyncio.sleep(remaining))
        changed = asyncio.create_task(wake.wait())
        try:
            await asyncio.wait((sleeper, changed), return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (sleeper, changed):
                if not task.done():
                    task.cancel()
            await asyncio.gather(sleeper, changed, return_exceptions=True)
    return await _can_send(key, version)


async def _reply(key, version, message, text, bot):
    from bot import (
        send_faq_answer,
        pick_fallback_text,
        _send_business_answer,
        _strip_reasoning,
        send_fallback_message,
    )
    from ai_service import get_ai_reply

    started = time.monotonic()
    owner_id, chat_id = key
    connection_id = message.business_connection_id
    reservation = None
    delivered = False
    source = "fallback"
    try:
        if not await _can_send(key, version):
            return
        if await db.get_owner_by_connection(connection_id) != owner_id:
            return
        from conversation_policy import is_acknowledgement, should_silence_acknowledgement
        if is_acknowledgement(text) and should_silence_acknowledgement(text, await ext.last_assistant_reply(owner_id, chat_id)):
            await ext.record_event(owner_id, chat_id, "acknowledgement", text)
            return
        profile = await db.get_profile(owner_id)
        prefs = await db.get_preferences(owner_id)
        settings = await db.get_global_settings()
        faqs = await db.get_faqs(owner_id)
        from reply_policy import match_faq, payload, mode_delay, mode_faq
        reply_settings = await ext.business_settings(owner_id)
        ui_mode = (await ext.options(owner_id))["ui_mode"]
        blocked = find_blocked_topic(text, settings["blocked_topics"])
        faq, _ = await asyncio.to_thread(match_faq, text, faqs, FAQ_MATCH_THRESHOLD, allow_commands=ui_mode == "business") if text else (None, 0)
        if getattr(message, "reply_command", False) and not faq:
            await ext.record_event(owner_id, chat_id, "command_unavailable", text, False)
            return
        if blocked and faq and not payload(faq).get("ignore"):
            faq = None
        if faq:
            if payload(faq).get("ignore"):
                await ext.record_event(owner_id, chat_id, "ignored_faq", text)
                return
            if not await _delay_until(key, version, started, mode_delay(reply_settings, ui_mode, "faq", faq)):
                return
            if (await ext.options(owner_id))["ui_mode"] != ui_mode:
                return
            try:
                await send_faq_answer(bot, chat_id, connection_id, mode_faq(faq, ui_mode))
            except Exception:
                logger.exception("FAQ failed; trying fallback")
            else:
                delivered = True
                source = "faq"
                await db.set_fallback_stage(owner_id, chat_id, 0)
                await db.add_chat_message(
                    owner_id, chat_id, "assistant", faq.get("answer") or "[media]"
                )
                await db.mark_bot_reply(owner_id, chat_id)
                await record_activity(bot, owner_id, chat_id, connection_id, "outgoing", describe_spec(faq))
                await ext.record_event(
                    owner_id, chat_id, source, text, True, time.monotonic() - started
                )
                return
        answer = settings["blocked_reply"] if blocked else None
        source = "policy" if blocked else "fallback"
        from assistant_rules import ambiguous_greeting, greeting_reply
        if not blocked and ambiguous_greeting(text) and USE_AI and profile["ai_enabled"] and settings["ai_global_enabled"] == "1" and not await db.is_ai_paused(*key):
            answer = greeting_reply(text, db.get_allowed_languages(prefs, profile["plan"]), await ext.assistant_settings(owner_id))
            if answer:
                source = "greeting"
        if (
            not answer
            and text
            and USE_AI
            and profile["ai_enabled"]
            and not await db.is_ai_paused(*key)
        ):
            reservation = await db.reserve_user_ai_slot(owner_id)
            if reservation["allowed"]:
                chat = await db.get_chat_settings(*key)
                result = await get_ai_reply(
                    user_text=text,
                    profile=profile,
                    faq_context=await asyncio.to_thread(select_ai_context, text, [mode_faq(f, ui_mode) for f in faqs if not payload(f).get("ignore")]),
                    languages=db.get_allowed_languages(prefs, profile["plan"]),
                    blocked_topics=settings["blocked_topics"],
                    blocked_reply=settings["blocked_reply"],
                    chat_role=(chat or {}).get("role", "")
                    if profile["plan"] == "premium"
                    else "",
                    history=await db.get_chat_history(*key, 10) if ui_mode == "business" else [],
                )
                answer = _strip_reasoning(result.text) if result.ok else None
                if answer:
                    source = "ai"
                    if result.provider == "local":
                        source = "greeting"
                elif result.error_type != "needs_owner":
                    await alert_admins(
                        bot, "AI unavailable or unusable; fallback active"
                    )
        if not await _can_send(key, version):
            return
        if await db.get_owner_by_connection(connection_id) != owner_id:
            return
        if source in {"ai", "greeting"}:
            latest_profile = await db.get_profile(owner_id)
            latest_settings = await db.get_global_settings()
            if (
                not latest_profile["ai_enabled"]
                or latest_settings["ai_global_enabled"] != "1"
                or await db.is_ai_paused(*key)
            ):
                answer = None
                source = "fallback"
        is_html = not answer
        delay = mode_delay(reply_settings, ui_mode, "ai" if source in {"ai", "greeting"} else "fallback")
        if not await _delay_until(key, version, started, delay):
            return
        if (await ext.options(owner_id))["ui_mode"] != ui_mode:
            return
        if source == "fallback" and not answer:
            try:
                sent_fallback = await send_fallback_message(bot, owner_id, chat_id, connection_id, profile)
            except Exception:
                logger.exception("Media fallback failed; trying plain fallback")
                sent_fallback = False
            if sent_fallback:
                await db.mark_bot_reply(owner_id, chat_id)
                await db.add_chat_message(owner_id, chat_id, "assistant", "[Запасное сообщение]")
                await ext.record_event(owner_id, chat_id, source, text, True, time.monotonic() - started)
                return
        answer = answer or await pick_fallback_text(owner_id, chat_id, profile, bot)
        if not answer:
            await ext.record_event(
                owner_id, chat_id, "error", text, False, time.monotonic() - started
            )
            return
        if not await _can_send(key, version):
            return
        await _send_business_answer(bot, chat_id, connection_id, answer, is_html)
        delivered = source == "ai"
        await db.mark_bot_reply(owner_id, chat_id)
        await db.add_chat_message(owner_id, chat_id, "assistant", answer)
        await record_activity(bot, owner_id, chat_id, connection_id, "outgoing", answer)
        if source != "fallback":
            await db.set_fallback_stage(owner_id, chat_id, 0)
        await ext.record_event(
            owner_id, chat_id, source, text, True, time.monotonic() - started
        )
    finally:
        if reservation and reservation.get("allowed") and not delivered:
            await asyncio.shield(db.release_user_ai_slot(owner_id, reservation["day"]))


async def maintenance_loop():
    last_backup = 0
    while True:
        try:
            await ext.maintenance(HISTORY_RETENTION_DAYS)
            if time.monotonic() - last_backup >= 86400:
                from backup_db import backup

                await asyncio.to_thread(backup, db.DB_PATH)
                last_backup = time.monotonic()
        except Exception:
            logger.exception("Retention cleanup failed")
        await asyncio.sleep(3600)


async def shutdown():
    tasks = list(_workers.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _taking_over.clear()

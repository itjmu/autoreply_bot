"""Consent-based management of independent Telegram bot accounts."""
import asyncio
import html
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

import aiosqlite
from aiogram import F, Router
from aiogram.fsm.state import State, StatesGroup

import database as db
import extensions as ext
from config import ADMIN_IDS

router = Router(name="account_hub")
logger = logging.getLogger(__name__)
_album_tasks = {}
_notice_tasks = set()


class Hub(StatesGroup):
    invite = State()
    reply = State()
    question = State()
    answer = State()


async def known(owner_id):
    async with db._connect() as conn:
        conn.row_factory = aiosqlite.Row
        row = await (await conn.execute("SELECT telegram_id,username,first_name,blocked FROM users WHERE telegram_id=?", (owner_id,))).fetchone()
    return dict(row) if row else None


async def limit_for(parent_id):
    user = await known(parent_id)
    if not user or user["blocked"] or (await ext.options(parent_id))["ui_mode"] != "business":
        return 0
    return 3 if (await db.get_profile(parent_id))["plan"] == "premium" else 1


async def linked(parent_id):
    async with db._connect() as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (await conn.execute("SELECT l.*,u.username,u.first_name FROM account_links l JOIN users u ON u.telegram_id=l.child_id WHERE parent_id=? ORDER BY l.created_at,l.child_id", (parent_id,))).fetchall()
    return [dict(row) for row in rows]


async def can_manage(parent_id, child_id):
    limit = await limit_for(parent_id)
    children = (await linked(parent_id))[:limit]
    child = await known(child_id)
    return bool(child and not child["blocked"] and any(row["child_id"] == child_id for row in children))


async def require_access(parent_id, child_id):
    if not await can_manage(parent_id, child_id):
        raise ValueError("Нет доступа к аккаунту / Account access unavailable")


async def create_request(parent_id, child_id):
    limit = await limit_for(parent_id)
    child = await known(child_id)
    if not limit:
        raise ValueError("Управление доступно в бизнес-режиме / Business mode required")
    if parent_id == child_id or not child or child["blocked"]:
        raise ValueError("Укажите другой аккаунт, уже зарегистрированный в боте / Choose another registered account")
    token = secrets.token_urlsafe(12)
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    async with db._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        if await (await conn.execute("SELECT 1 FROM account_links WHERE child_id IN (?,?) OR parent_id=?", (parent_id, child_id, child_id))).fetchone():
            raise ValueError("Аккаунт уже связан. Вложенные подключения не поддерживаются / Account already linked; nested management unavailable")
        if await (await conn.execute("SELECT 1 FROM account_link_requests WHERE parent_id=? AND child_id=? AND (status='reported' OR (status<>'delivery_failed' AND created_at>=datetime('now','-1 day')))", (parent_id, child_id))).fetchone():
            raise ValueError("Запрос уже отправлялся. Повтор возможен через сутки / Request already sent; retry after 24 hours")
        count = (await (await conn.execute("SELECT COUNT(*) FROM account_links WHERE parent_id=?", (parent_id,))).fetchone())[0]
        pending = (await (await conn.execute("SELECT COUNT(*) FROM account_link_requests WHERE parent_id=? AND status='pending' AND expires_at>CURRENT_TIMESTAMP", (parent_id,))).fetchone())[0]
        if count + pending >= limit:
            raise ValueError(f"Лимит: {limit}. Отключите аккаунт или отмените ожидающий запрос / Limit: {limit}")
        await conn.execute("INSERT INTO account_link_requests(token,parent_id,child_id,expires_at) VALUES(?,?,?,?)", (token, parent_id, child_id, expires))
        await conn.commit()
    return token


async def decide(child_id, token, decision):
    if decision not in {"yes", "no", "report"}:
        raise ValueError("Invalid decision")
    async with db._connect() as conn:
        conn.row_factory = aiosqlite.Row
        request = await (await conn.execute("SELECT * FROM account_link_requests WHERE token=? AND child_id=? AND status='pending' AND expires_at>CURRENT_TIMESTAMP", (token, child_id))).fetchone()
    if not request:
        raise ValueError("Запрос истёк или уже обработан / Request expired or handled")
    parent_id = request["parent_id"]
    limit = await limit_for(parent_id) if decision == "yes" else 0
    async with db._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        still_pending = await (await conn.execute("SELECT 1 FROM account_link_requests WHERE token=? AND child_id=? AND status='pending' AND expires_at>CURRENT_TIMESTAMP", (token, child_id))).fetchone()
        if not still_pending:
            raise ValueError("Запрос уже обработан / Request already handled")
        if decision == "yes":
            user = await known(child_id)
            if not limit or not user or user["blocked"]:
                raise ValueError("Подключение сейчас недоступно / Linking unavailable")
            if await (await conn.execute("SELECT 1 FROM account_links WHERE child_id IN (?,?) OR parent_id=?", (parent_id, child_id, child_id))).fetchone():
                raise ValueError("Аккаунт уже связан / Account already linked")
            count = (await (await conn.execute("SELECT COUNT(*) FROM account_links WHERE parent_id=?", (parent_id,))).fetchone())[0]
            if count >= limit:
                raise ValueError("Лимит подключённых аккаунтов исчерпан / Account limit reached")
            await conn.execute("INSERT INTO account_links(child_id,parent_id) VALUES(?,?)", (child_id, parent_id))
        status = {"yes": "accepted", "no": "declined", "report": "reported"}[decision]
        await conn.execute("UPDATE account_link_requests SET status=? WHERE token=?", (status, token))
        await conn.commit()
    return parent_id


async def revoke(actor_id, child_id):
    async with db._connect() as conn:
        await conn.execute("DELETE FROM account_links WHERE child_id=? AND (parent_id=? OR child_id=?)", (child_id, actor_id, actor_id))
        await conn.commit()


async def record_activity(bot, owner_id, chat_id, connection_id, direction, content):
    """Delivery notifications are best-effort and never interrupt customer replies."""
    try:
        async with db._connect() as conn:
            row = await (await conn.execute("SELECT parent_id FROM account_links WHERE child_id=?", (owner_id,))).fetchone()
        if not row or not await can_manage(row[0], owner_id):
            return
        parent_id = row[0]
        async with db._connect() as conn:
            await conn.execute("INSERT INTO hub_events(owner_id,chat_id,connection_id,direction,content) VALUES(?,?,?,?,?)", (owner_id, chat_id, connection_id, direction, content[:4000]))
            await conn.commit()
        account = await known(owner_id)
        chat = await db.get_chat_settings(owner_id, chat_id)
        moment = datetime.now(timezone.utc)
        from zoneinfo import ZoneInfo
        moment = moment.astimezone(ZoneInfo((await db.get_preferences(parent_id))["timezone"]))
        who = "👤 Собеседник / Customer" if direction == "incoming" else "✍️ Ответ владельца / Owner reply" if direction == "owner" else "🤖 Ответ бота / Bot reply"
        account_name = account.get("username") or account.get("first_name") or str(owner_id)
        peer = (chat or {}).get("peer_name") or str(chat_id)
        text = f"👥 {html.escape(account_name)} · ID {owner_id}\n{html.escape(peer)} · ID {chat_id}\n{moment:%Y-%m-%d %H:%M:%S %Z}\n{who}\n\n{html.escape(content[:1800])}"
        if not await can_manage(parent_id, owner_id):
            return
        from experience import markup
        if len(_notice_tasks) >= 128:
            logger.warning("Hub notification capacity reached")
            return
        async def deliver():
            try:
                if await can_manage(parent_id, owner_id):
                    await bot.send_message(parent_id, text, parse_mode="HTML", reply_markup=markup([[("💬 Открыть диалог / Open chat", f"hub:chat:{owner_id}:{chat_id}")]]))
            except Exception:
                logger.warning("Hub delivery unavailable for manager=%s", parent_id)
        task = asyncio.create_task(deliver())
        _notice_tasks.add(task)
        task.add_done_callback(_notice_tasks.discard)
    except Exception:
        logger.warning("Managed account activity notification failed owner=%s chat=%s", owner_id, chat_id)


async def manager_reply(bot, actor_id, child_id, chat_id, spec):
    await require_access(actor_id, child_id)
    async with db._connect() as conn:
        row = await (await conn.execute("SELECT connection_id FROM hub_events WHERE owner_id=? AND chat_id=? ORDER BY id DESC LIMIT 1", (child_id, chat_id))).fetchone()
    if not row or await db.get_owner_by_connection(row[0]) != child_id:
        raise ValueError("Подключение недоступно / Business connection unavailable")
    connection_id = row[0]
    connection = await bot.get_business_connection(connection_id)
    if not connection.is_enabled or connection.user.id != child_id or not (getattr(connection.rights, "can_reply", False) or connection.can_reply):
        raise ValueError("Telegram не разрешает ответ / Telegram reply permission unavailable")
    from business_runtime import takeover
    await takeover(child_id, chat_id, "managed owner replied")
    await require_access(actor_id, child_id)
    from bot import send_faq_answer
    item = {"answer_type": spec["type"], "answer": spec.get("text", ""), "answer_file_id": spec.get("file_id", ""), "answer_entities": json.dumps(spec.get("entities", [])), "answer_payload": json.dumps(spec.get("payload", {}))}
    await send_faq_answer(bot, chat_id, connection_id, item)
    content = spec.get("text") or "[" + spec["type"] + "]"
    await db.add_chat_message(child_id, chat_id, "assistant", content)
    await db.mark_bot_reply(child_id, chat_id)
    await record_activity(bot, child_id, chat_id, connection_id, "owner", content)


async def save_managed_faq(actor_id, child_id, question, spec):
    await require_access(actor_id, child_id)
    await ext.save_undo(child_id)
    await require_access(actor_id, child_id)
    await ext.append_faq(child_id, question, spec)


def identity(user):
    return html.escape(user.get("first_name") or "Telegram account") + (" @" + html.escape(user["username"]) if user.get("username") else "") + f" · ID {user['telegram_id']}"


async def safe_notice(bot, owner_id, text):
    try:
        await bot.send_message(owner_id, text, parse_mode="HTML")
    except Exception:
        logger.warning("Account hub notice unavailable for %s", owner_id)


@router.callback_query(F.data.startswith("hub:"))
async def hub_navigation(callback, state):
    from experience import markup, panel, back, language, choose
    actor = callback.from_user.id
    lang = await language(callback.from_user)
    action = callback.data[4:]
    await state.clear()
    try:
        if action == "home":
            limit = await limit_for(actor)
            links = await linked(actor)
            text = choose(lang, f"👥 <b>Мои аккаунты</b>\nДополнительных аккаунтов: {len(links)}/{limit}.\nБизнес: 1, Premium: 3. Доступ появляется только после согласия владельца.\n", f"👥 <b>My accounts</b>\nAdditional accounts: {len(links)}/{limit}.\nBusiness: 1, Premium: 3. Owner consent is required.\n")
            rows = []
            for index, link in enumerate(links):
                label = link["username"] or link["first_name"] or str(link["child_id"])
                label = ("🟢 " if index < limit else "⏸ ") + label[:30]
                rows.append([(label, f"hub:profile:{link['child_id']}")])
            if limit:
                rows.append([(choose(lang, "➕ Добавить аккаунт", "➕ Add account"), "hub:add")])
            async with db._connect() as conn:
                manager = await (await conn.execute("SELECT parent_id FROM account_links WHERE child_id=?", (actor,))).fetchone()
                pending = await (await conn.execute("SELECT token,child_id FROM account_link_requests WHERE parent_id=? AND status='pending' AND expires_at>CURRENT_TIMESTAMP", (actor,))).fetchall()
                incoming = await (await conn.execute("SELECT token,parent_id FROM account_link_requests WHERE child_id=? AND status='pending' AND expires_at>CURRENT_TIMESTAMP", (actor,))).fetchall()
            if manager:
                text += choose(lang, f"\nУправляющий аккаунт: {manager[0]}", f"\nManager account: {manager[0]}")
                rows.append([(choose(lang, "🔓 Отозвать доступ", "🔓 Revoke access"), f"hub:unlink:{actor}")])
            for token, child_id in pending:
                rows.append([(f"⏳ {child_id} · " + choose(lang, "Отменить запрос", "Cancel request"), f"hub:cancel:{token}")])
            for token, parent_id in incoming:
                rows.append([(f"📨 {parent_id}", f"hub:request:{token}")])
            rows.append(back(lang, "ux:account"))
        elif action == "add":
            if not await limit_for(actor):
                raise ValueError("Для управления выберите бизнес-режим / Choose Business mode")
            await state.set_state(Hub.invite)
            await panel(callback, choose(lang, "Введите Telegram ID другого аккаунта. Он должен уже запустить бота. Владелец получит запрос; без согласия доступ не появится.", "Enter another account's Telegram ID. It must have started the bot. Its owner receives a consent request."), [back(lang, "hub:home")])
            return
        elif action.startswith("request:"):
            token = action.split(":")[1]
            async with db._connect() as conn:
                request = await (await conn.execute("SELECT parent_id FROM account_link_requests WHERE token=? AND child_id=? AND status='pending' AND expires_at>CURRENT_TIMESTAMP", (token, actor))).fetchone()
            if not request:
                raise ValueError("Запрос недоступен / Request unavailable")
            parent = await known(request[0])
            text = consent_text(parent, lang)
            rows = consent_rows(token, lang)
        elif action.startswith("decide:"):
            _, token, decision = action.split(":")
            parent = await decide(actor, token, decision)
            text = choose(lang, "✅ Аккаунт подключён." if decision == "yes" else "Запрос отклонён.", "✅ Account linked." if decision == "yes" else "Request declined.")
            await safe_notice(callback.bot, parent, f"👥 ID {actor}: " + ("✅ Согласие получено / Accepted" if decision == "yes" else "❌ Запрос отклонён / Declined"))
            if decision == "report":
                parent_user = await known(parent)
                for admin in ADMIN_IDS:
                    await safe_notice(callback.bot, admin, f"🚩 Жалоба на запрос управления / Management request report\nОт / From: {actor}\nОтправитель / Sender: {identity(parent_user)}\nRequest: {html.escape(token)}")
                text += choose(lang, "\nЖалоба сохранена и передана администраторам.", "\nReport recorded and sent to administrators.")
            rows = [back(lang, "hub:home")]
        elif action.startswith("cancel:"):
            token = action.split(":")[1]
            async with db._connect() as conn:
                await conn.execute("UPDATE account_link_requests SET status='cancelled' WHERE token=? AND parent_id=? AND status='pending'", (token, actor))
                await conn.commit()
            text, rows = choose(lang, "Запрос отменён.", "Request cancelled."), [back(lang, "hub:home")]
        elif action.startswith("unlink:"):
            child = int(action.split(":")[1])
            async with db._connect() as conn:
                row = await (await conn.execute("SELECT parent_id FROM account_links WHERE child_id=? AND (parent_id=? OR child_id=?)", (child, actor, actor))).fetchone()
            if not row:
                raise ValueError("Нет доступа / Access unavailable")
            await revoke(actor, child)
            await safe_notice(callback.bot, child if actor != child else row[0], f"🔓 Управление ID {child} отключено / Account management disconnected")
            text, rows = choose(lang, "Доступ отозван. Данные аккаунта сохранены.", "Access revoked. Account data preserved."), [back(lang, "hub:home")]
        elif action.startswith("profile:"):
            child = int(action.split(":")[1])
            user = await known(child)
            links = await linked(actor)
            if not user or not any(link["child_id"] == child for link in links):
                raise ValueError("Нет доступа / Access unavailable")
            active = await can_manage(actor, child)
            text = "👤 " + identity(user) + "\n" + choose(lang, "Управление активно" if active else "Доступ приостановлен: проверьте режим и лимит.", "Management active" if active else "Access suspended: check mode and limit.")
            rows = []
            if active:
                rows += [[(choose(lang, "💬 Диалоги", "💬 Conversations"), f"hub:chats:{child}:0"), (choose(lang, "📚 FAQ", "📚 FAQ"), f"hub:faqs:{child}:0")], [(choose(lang, "➕ Добавить FAQ", "➕ Add FAQ"), f"hub:addfaq:{child}")]]
            rows += [[(choose(lang, "🔓 Отключить", "🔓 Disconnect"), f"hub:unlink:{child}")], back(lang, "hub:home")]
        elif action.startswith(("chats:", "faqs:")):
            kind, child, offset = action.split(":")
            child, offset = int(child), max(0, int(offset))
            await require_access(actor, child)
            text = choose(lang, f"👤 Аккаунт {child} → " + ("Диалоги" if kind == "chats" else "FAQ"), f"👤 Account {child} → " + ("Conversations" if kind == "chats" else "FAQ"))
            if kind == "chats":
                chats = await ext.inbox(child, offset)
                rows = [[((c.get("peer_name") or str(c["chat_id"]))[:40], f"hub:chat:{child}:{c['chat_id']}")] for c in chats]
            else:
                from button_layout import faq_rows
                faqs = await db.get_faqs(child)
                rows = faq_rows(faqs[offset:offset + 30], prefix=f"hub:faq:{child}:")
                rows.append([(choose(lang, "➕ Добавить FAQ", "➕ Add FAQ"), f"hub:addfaq:{child}")])
            rows += [[("◀️", f"hub:{kind}:{child}:{max(0, offset-30 if kind == 'faqs' else offset-10)}"), ("▶️", f"hub:{kind}:{child}:{offset+30 if kind == 'faqs' else offset+10}")], back(lang, f"hub:profile:{child}")]
        elif action.startswith("faq:"):
            _, child, faq_id = action.split(":")
            child, faq_id = int(child), int(faq_id)
            await require_access(actor, child)
            faq = next((f for f in await db.get_faqs(child) if f["id"] == faq_id), None)
            if not faq:
                raise ValueError("FAQ удалён / FAQ deleted")
            text = f"👤 {child}\n" + html.escape(faq["question"]) + "\n\n" + html.escape((faq["answer"] or "[" + faq["answer_type"] + "]")[:2500])
            rows = [[(choose(lang, "➕ Добавить FAQ", "➕ Add FAQ"), f"hub:addfaq:{child}")], back(lang, f"hub:faqs:{child}:0")]
        elif action.startswith("chat:"):
            _, child, chat_id = action.split(":")
            child, chat_id = int(child), int(chat_id)
            await require_access(actor, child)
            chat = await db.get_chat_settings(child, chat_id)
            if not chat:
                raise ValueError("Диалог недоступен / Chat unavailable")
            history = await db.get_chat_history(child, chat_id, 15)
            text = f"👤 Аккаунт / Account {child}\n💬 " + html.escape(chat.get("peer_name") or str(chat_id)) + f" · {chat_id}\n\n"
            text += choose(lang, "Последние сообщения (время истории UTC):\n", "Latest messages (history timestamps UTC):\n")
            for item in reversed(history):
                chunk = ("👤 " if item["role"] == "user" else "🤖 ") + html.escape(str(item.get("created_at", ""))) + "\n" + html.escape(item["content"][:160]) + "\n\n"
                if len(text) + len(chunk) > 3600:
                    break
                text += chunk
            rows = [[(choose(lang, "✍️ Ответить", "✍️ Reply"), f"hub:reply:{child}:{chat_id}"), (choose(lang, "🤖 Вернуть бота", "🤖 Resume bot"), f"hub:resume:{child}:{chat_id}")], [(choose(lang, "➕ Добавить FAQ", "➕ Add FAQ"), f"hub:addfaq:{child}")], back(lang, f"hub:chats:{child}:0")]
        elif action.startswith(("reply:", "resume:")):
            kind, child, chat_id = action.split(":")
            child, chat_id = int(child), int(chat_id)
            await require_access(actor, child)
            if not await db.get_chat_settings(child, chat_id):
                raise ValueError("Диалог недоступен / Chat unavailable")
            if kind == "resume":
                from business_runtime import resume_chat
                await resume_chat(child, chat_id)
                text, rows = choose(lang, "Бот возобновлён.", "Bot resumed."), [back(lang, f"hub:chat:{child}:{chat_id}")]
            else:
                from business_runtime import takeover
                await takeover(child, chat_id, "manager preparing reply")
                await state.set_state(Hub.reply)
                await state.set_data({"child": child, "chat_id": chat_id})
                await panel(callback, choose(lang, "Бот в этом диалоге на паузе. Отправьте текст или медиа для ответа от имени выбранного аккаунта. Альбом поддерживается. Отмена не снимает паузу.", "Bot paused in this conversation. Send text or media to reply as the selected account. Albums are supported. Cancelling keeps the pause."), [back(lang, f"hub:chat:{child}:{chat_id}")])
                return
        elif action.startswith("addfaq:"):
            child = int(action.split(":")[1])
            await require_access(actor, child)
            await state.set_state(Hub.question)
            await state.set_data({"child": child})
            await panel(callback, choose(lang, f"Введите вопрос для FAQ аккаунта {child} (1–500 символов).", f"Enter a FAQ question for account {child} (1–500 characters)."), [back(lang, f"hub:profile:{child}")])
            return
        else:
            await callback.answer()
            return
        await panel(callback, text, rows)
    except (ValueError, IndexError) as error:
        await callback.answer(str(error)[:180], show_alert=True)


def consent_text(parent, lang):
    from experience import choose
    return choose(lang, "👥 <b>Запрос управления аккаунтом</b>\n\n", "👥 <b>Account management request</b>\n\n") + identity(parent) + choose(lang, "\n\nХочет читать ваши диалоги с клиентами и ответы бота, получать уведомления, отвечать от вашего подключённого аккаунта и добавлять FAQ в вашу базу.\n\nЭто ваш основной аккаунт или доверенный управляющий? Согласие можно отозвать в «Аккаунт → Мои аккаунты». Запрос действует сутки.", "\n\nWants to read your customer conversations and bot replies, receive notifications, reply as your connected account and add FAQ entries to your database.\n\nIs this your primary account or a trusted manager? Revoke consent in Account → My accounts. Request expires in 24 hours.")


def consent_rows(token, lang):
    from experience import choose
    return [[(choose(lang, "✅ Да", "✅ Accept"), f"hub:decide:{token}:yes"), (choose(lang, "❌ Нет", "❌ Decline"), f"hub:decide:{token}:no")], [(choose(lang, "🚩 Пожаловаться", "🚩 Report"), f"hub:decide:{token}:report")]]


@router.message(Hub.invite)
async def invite_value(message, state):
    from experience import language, choose, markup, back
    actor = message.from_user.id
    lang = await language(message.from_user)
    token = None
    try:
        text = (message.text or "").strip()
        if not text.isdigit():
            raise ValueError("Введите числовой Telegram ID / Enter a numeric Telegram ID")
        child = int(text)
        token = await create_request(actor, child)
        parent = await known(actor)
        await message.bot.send_message(child, consent_text(parent, (await ext.options(child))["language"]), parse_mode="HTML", reply_markup=markup(consent_rows(token, (await ext.options(child))["language"])))
    except Exception as error:
        if token:
            async with db._connect() as conn:
                await conn.execute("UPDATE account_link_requests SET status='delivery_failed' WHERE token=? AND status='pending'", (token,))
                await conn.commit()
        description = str(error) if isinstance(error, ValueError) else "Не удалось доставить запрос. Второй аккаунт должен открыть бота и разрешить сообщения / Could not deliver; target must start and unblock this bot"
        await message.answer(description)
        return
    await state.clear()
    await message.answer(choose(lang, "📨 Запрос отправлен. Управление появится после согласия.", "📨 Request sent. Access starts after consent."), reply_markup=markup([back(lang, "hub:home")]))


@router.message(Hub.question)
async def question_value(message, state):
    from experience import language, choose, markup, back
    data = await state.get_data()
    try:
        await require_access(message.from_user.id, data["child"])
    except ValueError as error:
        await state.clear()
        await message.answer(str(error))
        return
    question = (message.text or "").strip()
    if not 1 <= len(question) <= 500:
        await message.answer("Вопрос: 1–500 символов / Question: 1–500 characters")
        return
    await state.update_data(question=question)
    await state.set_state(Hub.answer)
    lang = await language(message.from_user)
    await message.answer(choose(lang, "Отправьте ответ: текст с форматированием, медиа или альбом. Он сохранится в FAQ выбранного аккаунта.", "Send an answer: formatted text, media or album. It is saved in the selected account's FAQ."), reply_markup=markup([back(lang, f"hub:profile:{data['child']}")]))


async def commit_content(state, actor, bot, chat_id, spec):
    from experience import markup, back, language
    data = await state.get_data()
    child = data.get("child")
    if not child:
        return
    try:
        if await state.get_state() == Hub.reply.state:
            await manager_reply(bot, actor, child, data["chat_id"], spec)
            target = f"hub:chat:{child}:{data['chat_id']}"
        elif await state.get_state() == Hub.answer.state:
            await save_managed_faq(actor, child, data["question"], spec)
            target = f"hub:faqs:{child}:0"
        else:
            return
    except Exception as error:
        text = str(error) if isinstance(error, ValueError) else "Отправка не удалась. Данные не подтверждены; проверьте подключение / Send failed; check connection"
        await bot.send_message(chat_id, text)
        if not isinstance(error, ValueError):
            logger.exception("Managed content failed actor=%s child=%s", actor, child)
        return
    await state.clear()
    lang = (await ext.options(actor))["language"]
    await bot.send_message(chat_id, "✅ Сохранено / Sent or saved", reply_markup=markup([back(lang, target)]))


@router.message(Hub.reply)
@router.message(Hub.answer)
async def content_value(message, state):
    from bot import serialize_answer
    spec = serialize_answer(message)
    if not spec:
        await message.answer("Неподдерживаемый тип сообщения / Unsupported message")
        return
    data = await state.get_data()
    try:
        await require_access(message.from_user.id, data["child"])
    except (ValueError, KeyError):
        await state.clear()
        await message.answer("Доступ отозван / Access revoked")
        return
    if message.media_group_id:
        items = data.get("album", [])
        if len(items) >= 10:
            return
        items.append(spec)
        token = secrets.token_urlsafe(8)
        await state.update_data(album=items, album_token=token)
        task = _album_tasks.get(state.key)
        if task:
            task.cancel()
        _album_tasks[state.key] = asyncio.create_task(flush_album(state, message.from_user.id, message.bot, message.chat.id, token))
        return
    if data.get("album"):
        await message.answer("Дождитесь сохранения альбома / Wait for the album to finish")
        return
    await commit_content(state, message.from_user.id, message.bot, message.chat.id, spec)


async def flush_album(state, actor, bot, chat_id, token):
    try:
        await asyncio.sleep(2.5)
        data = await state.get_data()
        if data.get("album_token") == token and data.get("album"):
            await commit_content(state, actor, bot, chat_id, {"type": "media_group", "payload": {"items": data["album"]}})
    finally:
        if _album_tasks.get(state.key) is asyncio.current_task():
            _album_tasks.pop(state.key, None)


async def shutdown():
    tasks = list(_album_tasks.values()) + list(_notice_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _album_tasks.clear()
    _notice_tasks.clear()


def describe_spec(spec):
    kind = spec.get("type", spec.get("answer_type", "text"))
    payload = spec.get("payload")
    if payload is None:
        payload = json.loads(spec.get("answer_payload") or "{}")
    if kind in {"sequence", "media_group"}:
        return "\n".join(describe_spec(item) for item in payload.get("items", []))[:4000]
    if kind == "forward":
        return describe_spec(payload.get("copy", {}))
    return (spec.get("text") or spec.get("answer") or "[" + kind + "]")[:4000]

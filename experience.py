"""Bilingual customer-facing flows, layered over the existing admin interface."""

import asyncio
import html
import io
import json
import logging
import secrets

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BufferedInputFile,
)

import database as db
import extensions as ext
from config import ADMIN_IDS, FAQ_MATCH_THRESHOLD, USE_AI
from matcher import find_direct_answer, select_ai_context
from policy import find_blocked_topic

router = Router(name="experience")
_album_tasks = {}
logger = logging.getLogger(__name__)


class Flow(StatesGroup):
    reply_delay = State()
    test = State()
    details = State()
    faq_question = State()
    faq_answer = State()
    imported = State()
    setting = State()
    suggestion = State()
    setup_timezone = State()
    fallback = State()
    faq_extra = State()
    faq_buttons = State()
    faq_command = State()
    faq_command_button = State()
    faq_layout = State()
    reports = State()
    ai_field = State()
    ai_setup_facts = State()
    ai_setup_rules = State()
    ai_feedback = State()


def mode_description(lang):
    return choose(lang,
        "Выберите режим.\n\n👤 Личный — простое меню, один ответ на FAQ, один запасной ответ, AI и задержки до минуты. Рекомендуем, если вы не работаете с клиентами.\n\n💼 Бизнес — несколько ответов на один FAQ, URL-кнопки, два запасных ответа, задержки до часа, профиль, расписание, история и память AI, заявки и отчёты. Повышенные лимиты FAQ и AI доступны с платным Premium; выбор режима бесплатный.\n\nРежим меняется в настройках. FAQ, часовой пояс и основной язык общие; бизнес-расширения сохраняются при переключении.",
        "Choose a mode.\n\n👤 Personal — simple menu, one reply per FAQ, one fallback, AI and delays up to a minute. Recommended if you do not work with customers.\n\n💼 Business — multiple replies per FAQ, URL buttons, two fallbacks, delays up to an hour, profile, schedule, history and AI memory, requests and reports. Higher FAQ and AI quotas require paid Premium; choosing a mode is free.\n\nSwitch in Settings. FAQ, timezone and primary language are shared; Business extensions are preserved when switching.")


def connection_help(lang):
    return choose(lang,
        "Подключение: Telegram → Настройки → Автоматизация чатов (в некоторых версиях: Аккаунт → Автоматизация чатов). Добавьте этого бота и разрешите отвечать в нужных чатах. В старых версиях пункт находится в Telegram Business → Чат-боты. Подключение бота не требует Telegram Premium.",
        "Connect: Telegram → Settings → Chat Automation (in some versions under Account). Add this bot and allow replies in the chats you choose. Older versions use Telegram Business → Chatbots. Connecting a bot does not require Telegram Premium.")


def choose(lang, ru, en):
    return en if lang == "en" else ru


async def language(user):
    return (await ext.options(user.id, user.language_code))["language"]


def markup(rows):
    from button_layout import menu_rows
    rows = menu_rows(rows)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=label, **({"url": data} if data.startswith(("https://", "tg://")) else {"callback_data": data}))
                for label, data in row
            ]
            for row in rows
        ]
    )


def back(lang, target="ux:home"):
    return [(choose(lang, "⬅️ Назад", "⬅️ Back"), target)]


def mode_rows(lang):
    return [
        [
            (choose(lang, "Личный", "Personal"), "ux:interface:personal"),
            (choose(lang, "Бизнес", "Business"), "ux:interface:business"),
        ]
    ]


async def home_text(owner_id):
    opts = await ext.options(owner_id)
    lang = opts["language"]
    prefs = await db.get_preferences(owner_id)
    profile = await db.get_profile(owner_id)
    name = (
        choose(lang, "Бизнес", "Business")
        if opts["ui_mode"] == "business"
        else choose(lang, "Личный", "Personal")
    )
    status = (
        choose(lang, "Пауза", "Paused")
        if not prefs["autoreply_enabled"]
        else ("FAQ + AI" if profile["ai_enabled"] else "FAQ")
    )
    return f"🤖 AutoReply · {name}\n{status}\n\n" + choose(lang, "FAQ отвечает первым, AI помогает, если готового ответа нет.\nНачали отвечать сами — бот ставит этот чат на паузу.", "FAQ replies first; AI helps when there is no saved answer.\nYour own reply pauses the bot in that conversation.")


async def home_markup(owner_id):
    opts = await ext.options(owner_id)
    lang = opts["language"]
    business = opts["ui_mode"] == "business"
    prefs = await db.get_preferences(owner_id)
    profile = await db.get_profile(owner_id)
    quota = await db.get_user_quota_status(owner_id)
    global_settings = await db.get_global_settings()
    rows = [
        [(choose(lang, "Автоответ всем", "Auto-reply to everyone") + (" 🟢" if prefs["autoreply_enabled"] else " 🔴"), "ux:auto_toggle")],
        [(choose(lang, "+ Добавить", "+ Add"), "ux:faq_add"), (choose(lang, "Готовые FAQ", "Saved FAQ"), "ux:faqs")],
        [(f"☑️ AI 🟢 {quota['used']}/{quota['limit']}" if profile["ai_enabled"] and global_settings["ai_global_enabled"] == "1" else "☐ AI 🔴", "ux:ai_toggle"), (choose(lang, "🧠 Настроить AI", "🧠 Configure AI"), "ux:ai")],
        [(choose(lang, "💬 Чаты / Я отвечаю", "💬 Chats / I'll reply"), "ux:inbox:0"), (choose(lang, "Запасные ответы" if business else "Запасной ответ", "Fallback replies" if business else "Fallback reply"), "ux:fallbacks" if business else "ux:edit:fallback_text")],
    ]
    if business:
        rows.append([(choose(lang, "💼 Бизнес-инструменты", "💼 Business tools"), "ux:business_tools")])
    if owner_id in ADMIN_IDS:
        rows.append([(choose(lang, "👑 Админ", "👑 Admin"), "admin")])
    rows.append([(choose(lang, "⚙️ Настройки", "⚙️ Settings"), "ux:settings")])
    return markup(rows)


async def show_welcome(message):
    opts = await ext.options(message.from_user.id, message.from_user.language_code)
    if not opts["mode_chosen"]:
        lang = opts["language"]
        await message.answer(
            mode_description(lang),
            reply_markup=markup(mode_rows(lang)),
        )
    else:
        await message.answer(
            await home_text(message.from_user.id),
            reply_markup=await home_markup(message.from_user.id),
        )


async def panel(callback, text, rows):
    await callback.answer()
    try:
        await callback.message.edit_text(
            text, reply_markup=markup(rows), parse_mode="HTML"
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=markup(rows), parse_mode="HTML"
        )


async def prompt(callback, state, target, text, values=None, back_target="ux:home"):
    await state.clear()
    await state.set_state(target)
    if values:
        await state.update_data(**values)
    lang = await language(callback.from_user)
    await panel(callback, text, [back(lang, back_target)])


def assistant_summary(settings, lang):
    labels = [("role", "Кто отвечает", "Who replies"), ("facts", "Что знает", "Verified facts"), ("rules", "Правила", "Rules")]
    return "\n\n".join(choose(lang, ru, en) + ":\n" + html.escape(settings[field][:650] or choose(lang, "Пока не заполнено", "Not set yet")) for field, ru, en in labels)


async def assistant_panel(owner, lang):
    settings = await ext.assistant_settings(owner)
    profile = await db.get_profile(owner)
    prefs = await db.get_preferences(owner)
    quota = await db.get_user_quota_status(owner)
    global_settings = await db.get_global_settings()
    active = profile["ai_enabled"] and global_settings["ai_global_enabled"] == "1" and USE_AI
    text = choose(lang, "🧠 <b>Помощник AI</b>", "🧠 <b>AI assistant</b>")
    text += "\n" + ("🟢" if active else "🔴") + f" · {quota['used']}/{quota['limit']}\n"
    text += choose(lang, "Основной язык: ", "Primary language: ") + html.escape(prefs["primary_language"])
    text += choose(lang, "\nДля «салом» и других неоднозначных приветствий отвечает на этом языке.\n\n1. Кто отвечает — роль.\n2. Что знает — проверенные факты и FAQ.\n3. Как отвечает — стиль и правила.\n4. Проверка — пробный вопрос без отправки клиенту.", "\nAmbiguous greetings like 'salom' use this language.\n\n1. Who replies — role.\n2. What it knows — verified facts and FAQ.\n3. How it replies — style and rules.\n4. Test — a question without sending anything to customers.")
    if not settings["facts"] and not await db.count_faqs(owner) and not profile.get("ai_description"):
        text += choose(lang, "\n\nДобавьте факты: без них помощник не знает ваших цен, услуг и условий.", "\n\nAdd facts: the assistant does not know your prices, services or terms yet.")
    rows = [
        [(choose(lang, "Настроить за 3 шага", "Set up in 3 steps"), "ux:ai_setup")],
        [(choose(lang, "1. Кто отвечает", "1. Who replies"), "ux:ai_edit:role"), (choose(lang, "2. Что знает", "2. Verified facts"), "ux:ai_edit:facts")],
        [(choose(lang, "3. Стиль ответа", "3. Reply style"), "ux:ai_behavior"), (choose(lang, "Правила", "Rules"), "ux:ai_edit:rules")],
        [(choose(lang, "4. Проверить ответ", "4. Test reply"), "ux:test"), (choose(lang, "Мои FAQ", "My FAQ"), "ux:faqs")],
        [(choose(lang, "Выключить AI", "Turn AI off") if profile["ai_enabled"] else choose(lang, "Включить AI", "Turn AI on"), "ux:ai_power")], back(lang),
    ]
    return text, rows


@router.callback_query(F.data == "ux:ai_confirm")
async def confirm_assistant(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    draft = data.get("assistant_draft")
    lang = await language(callback.from_user)
    if await state.get_state() != Flow.ai_setup_rules.state or not data.get("assistant_ready") or not draft:
        await callback.answer(choose(lang, "Настройка устарела. Начните заново.", "Setup expired. Start again."), show_alert=True)
        return
    await ext.save_undo(callback.from_user.id)
    await ext.save_assistant_settings(callback.from_user.id, draft)
    await state.clear()
    await panel(callback, choose(lang, "Помощник настроен ✅ Теперь проверьте приветствие, вопрос с известным ответом и вопрос без ответа.", "Assistant configured ✅ Test a greeting, a known question and a question without an answer."), [[(choose(lang, "Проверить", "Test"), "ux:test")], back(lang, "ux:ai")])


@router.callback_query(F.data == "ux:ai_feedback")
async def assistant_feedback(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = await language(callback.from_user)
    if await state.get_state() != Flow.test.state or not data.get("sandbox_question"):
        await callback.answer(choose(lang, "Сначала проверьте ответ.", "Test a reply first."), show_alert=True)
        return
    await prompt(callback, state, Flow.ai_feedback, choose(lang, "Напишите, как помощник должен был ответить (до 1000 символов). Сохраним это как пример стиля. Реальные цены и условия добавляйте отдельно в «Что знает» или FAQ.", "Write the reply you wanted (up to 1000 characters). It will become a style example. Add actual prices and terms separately in Facts or FAQ."), {"feedback_question": data["sandbox_question"]}, back_target="ux:ai")


def sandbox_markup(lang):
    return markup([[(choose(lang, "Ответ плохой → исправить", "Bad reply → improve"), "ux:ai_feedback")], back(lang, "ux:ai")])


async def remember_sandbox(state, question, answer):
    data = await state.get_data()
    history = data.get("test_history", [])
    history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer}])
    await state.update_data(test_history=history[-10:], sandbox_question=question)


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    lang = await language(message.from_user)
    await message.answer(
        choose(lang, "Отменено.", "Cancelled."),
        reply_markup=await home_markup(message.from_user.id),
    )


@router.callback_query(F.data == "main")
@router.callback_query(F.data == "ux:home")
async def home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        await home_text(callback.from_user.id),
        reply_markup=await home_markup(callback.from_user.id),
    )


@router.callback_query(F.data.startswith("ux:"))
async def navigation(callback: CallbackQuery, state: FSMContext):
    owner = callback.from_user.id
    lang = await language(callback.from_user)
    action = callback.data[3:]
    business = (await ext.options(owner))["ui_mode"] == "business"
    business_only = {"business_tools", "reports", "report_edit", "requests", "collect", "stats", "suggestions", "details", "fallbacks", "schedule", "schedule_toggle"}
    if not business and (action in business_only or action.startswith(("faq_extra:", "faq_buttons:", "faq_command:", "faq_command_button:", "faq_button_types:", "faq_layout:", "history:", "memory:", "request:", "request_done:", "suggest:"))):
        await state.clear()
        await panel(callback, choose(lang, "Эта функция доступна в бизнес-режиме. Общие FAQ и настройки сохранятся при переключении.", "This feature is available in Business. Shared FAQ and settings are preserved when switching."), [[(choose(lang, "Выбрать режим", "Choose mode"), "ux:interface")], back(lang)])
        return
    p = await db.get_profile(owner)
    prefs = await db.get_preferences(owner)
    if p["blocked"] and owner not in ADMIN_IDS:
        await callback.answer(
            choose(lang, "Вы заблокированы", "You are blocked"), show_alert=True
        )
        return
    if action not in {"faq_ignore_draft", "delay:draft"}:
        await state.clear()
    if action == "ai":
        text, rows = await assistant_panel(owner, lang)
    elif action == "ai_setup":
        text = choose(lang, "Шаг 1 из 3. Для чего нужен помощник? Затем добавим факты и правила. Текущие настройки сохранятся до подтверждения.", "Step 1 of 3. What is your assistant for? Next add facts and rules. Current settings stay active until confirmation.")
        text += "\n\n" + choose(lang, "Основной язык ответов: ", "Primary reply language: ") + html.escape(prefs["primary_language"])
        rows = [[(choose(lang, ru, en), "ux:ai_preset:" + key)] for key, ru, en in [("personal", "Личная переписка", "Personal messages"), ("shop", "Магазин", "Shop"), ("services", "Услуги и запись", "Services & bookings"), ("support", "Поддержка", "Support")]] + [back(lang, "ux:ai")]
    elif action.startswith("ai_preset:"):
        from assistant_rules import PRESETS
        key = action.split(":")[1]
        if key not in PRESETS:
            await callback.answer()
            return
        draft = {**(await ext.assistant_settings(owner)), **PRESETS[key]}
        await prompt(callback, state, Flow.ai_setup_facts,
            choose(lang, "Шаг 2 из 3. Что помощник знает точно?\nУкажите проверенные факты: чем занимаетесь, цены, часы, контакты. Для личного режима — что можно сообщать о вас. Не пишите выдуманные примеры цен.\nДо 4000 символов. «-» — оставить прежние факты.", "Step 2 of 3. What does the assistant know for sure?\nAdd verified facts: services, prices, hours, contacts. For Personal, what may be shared about you. Do not add invented example prices.\nUp to 4000 characters. '-' keeps existing facts."), {"assistant_draft": draft}, back_target="ux:ai")
        return
    elif action.startswith("ai_edit:"):
        from assistant_rules import TEXT_LIMITS
        field = action.split(":")[1]
        if field not in TEXT_LIMITS:
            await callback.answer()
            return
        hints = {
            "role": ("Кто отвечает и чем помогает? Пример: помощник мастерской, объясняет услуги. Не добавляйте сюда цены.", "Who replies, and what do they help with? Example: a repair shop assistant explaining services. Put prices in Facts."),
            "facts": ("Что известно точно? Услуги, реальные цены, адрес, часы, контакты. Это знания, а не команды. FAQ имеет приоритет при расхождениях.", "What is known for sure? Services, real prices, address, hours, contacts. These are facts, not commands. FAQ takes priority on conflicts."),
            "rules": ("Что помощнику можно и нельзя? Пример: задавай один вопрос за раз; скидки согласует владелец; не подтверждай запись.", "What may the assistant do? Example: ask one question at a time; the owner approves discounts; do not confirm bookings."),
            "examples": ("Покажите желаемый стиль: Вопрос: … / Хороший ответ: … . Примеры не считаются фактами о ценах или наличии.", "Show the desired style: Question: … / Good answer: … . Examples are not facts about prices or stock."),
        }
        current = (await ext.assistant_settings(owner))[field]
        text = choose(lang, *hints[field]) + f"\n\n{TEXT_LIMITS[field]} " + choose(lang, "символов. «-» — очистить поле.", "characters. '-' clears the field.")
        if current:
            text += "\n\n" + html.escape(current[:1200])
        await prompt(callback, state, Flow.ai_field, text, {"assistant_field": field}, back_target="ux:ai")
        return
    elif action == "ai_behavior":
        settings = await ext.assistant_settings(owner)
        text = choose(lang, "Как отвечает помощник?\nДля «салом» и других неоднозначных приветствий всегда используется основной язык. История помогает помнить разговор, но старые ответы AI не подтверждают факты.", "How should the assistant reply?\nAmbiguous greetings like 'salom' always use the primary language. History provides context; earlier AI replies are not verified facts.")
        rows = [
            [(choose(lang, "Дружелюбно", "Friendly") + (" ✓" if settings["style"] == "friendly" else ""), "ux:ai_set:style:friendly"), (choose(lang, "Нейтрально", "Neutral") + (" ✓" if settings["style"] == "neutral" else ""), "ux:ai_set:style:neutral"), (choose(lang, "Деловой", "Formal") + (" ✓" if settings["style"] == "formal" else ""), "ux:ai_set:style:formal")],
            [(choose(lang, "Кратко", "Short") + (" ✓" if settings["length"] == "short" else ""), "ux:ai_set:length:short"), (choose(lang, "Подробнее", "Detailed") + (" ✓" if settings["length"] == "detailed" else ""), "ux:ai_set:length:detailed")],
            [(choose(lang, "Язык: основной", "Language: primary") + (" ✓" if settings["language"] == "owner" else ""), "ux:ai_set:language:owner"), (choose(lang, "Язык: собеседника", "Language: customer") + (" ✓" if settings["language"] == "customer" else ""), "ux:ai_set:language:customer")],
            [(choose(lang, "Изменить основной язык", "Set primary language"), "ux:edit:primary_language")],
            [(choose(lang, "Нет ответа → владелец", "Unknown → owner") + (" ✓" if settings["unknown"] == "owner" else ""), "ux:ai_set:unknown:owner")],
            [(choose(lang, "Нет ответа → уточнить", "Unknown → clarify") + (" ✓" if settings["unknown"] == "clarify" else ""), "ux:ai_set:unknown:clarify"), (choose(lang, "Нет ответа → запасной", "Unknown → fallback") + (" ✓" if settings["unknown"] == "fallback" else ""), "ux:ai_set:unknown:fallback")],
            [(choose(lang, "Память: ", "Memory: ") + ("🟢" if settings["memory"] else "🔴"), "ux:ai_set:memory:" + ("off" if settings["memory"] else "on"))],
            [(choose(lang, "Примеры хороших ответов", "Good reply examples"), "ux:ai_edit:examples")], back(lang, "ux:ai"),
        ]
        if not business:
            rows = [row for row in rows if not any(button[1].startswith("ux:ai_set:memory:") for button in row)]
    elif action.startswith("ai_set:"):
        from assistant_rules import CHOICES
        parts = action.split(":")
        if len(parts) != 3:
            await callback.answer()
            return
        field, value = parts[1:]
        if field == "memory" and not business:
            await callback.answer()
            return
        if field == "memory" and value in {"on", "off"}:
            value = value == "on"
        elif field not in CHOICES or value not in CHOICES[field]:
            await callback.answer()
            return
        await ext.save_undo(owner)
        await ext.save_assistant_settings(owner, {field: value})
        text = choose(lang, "Настройка применена ✅", "Setting applied ✅")
        rows = [back(lang, "ux:ai_behavior"), [(choose(lang, "Проверить ответ", "Test reply"), "ux:test")]]
    elif action == "ai_feedback":
        await callback.answer(choose(lang, "Начните с проверки ответа.", "Test a reply first."), show_alert=True)
        return
    elif action in {"auto_toggle", "ai_toggle", "ai_power"}:
        if action == "auto_toggle":
            await db.toggle_autoreply(owner)
        else:
            await db.toggle_ai(owner)
        await callback.answer()
        if action == "ai_power":
            text, rows = await assistant_panel(owner, lang)
            await callback.message.edit_text(text, reply_markup=markup(rows), parse_mode="HTML")
        else:
            await callback.message.edit_text(await home_text(owner), reply_markup=await home_markup(owner))
        return
    elif action == "connect":
        text = connection_help(lang)
        rows = [back(lang)]
    elif action in {"interface", "setup"}:
        text = mode_description(lang)
        rows = mode_rows(lang) + [back(lang)]
    elif action.startswith("interface:"):
        value = action.split(":")[1]
        if value not in {"personal", "business"}:
            return
        opts = await ext.options(owner)
        await ext.set_option(owner, "ui_mode", value)
        await ext.set_option(owner, "mode_chosen", 1)
        if value == "personal":
            await callback.answer()
            await callback.message.edit_text(await home_text(owner) + "\n\n" + connection_help(lang), reply_markup=await home_markup(owner))
            return
        if not opts["setup_done"]:
            action = "connect"
            text = connection_help(lang)
            rows = [[(choose(lang, "Далее", "Next"), "ux:setup_language")], back(lang)]
        else:
            text = await home_text(owner)
            await callback.answer()
            await callback.message.edit_text(
                text, reply_markup=await home_markup(owner)
            )
            return
    elif action == "setup_language":
        text = choose(
            lang, "Выберите язык интерфейса.", "Choose the interface language."
        )
        rows = [
            [("Русский", "ux:setup_lang:ru"), ("English", "ux:setup_lang:en")],
            back(lang),
        ]
    elif action.startswith("setup_lang:"):
        value = action.split(":")[1]
        if value not in {"ru", "en"}:
            return
        await ext.set_option(owner, "language", value)
        lang = value
        await prompt(callback, state, Flow.setup_timezone, choose(lang, "Укажите часовой пояс бизнеса, например Asia/Karachi или Europe/Moscow.", "Enter your business timezone, e.g. Asia/Karachi or Europe/London."))
        return
    elif action == "setup_details":
        text = choose(
            lang,
            "Добавьте информацию для ответов, затем проверьте результат.",
            "Add information for replies, then test the result.",
        )
        rows = [
            [(choose(lang, "Добавить информацию", "Add details"), "ux:details")],
            [(choose(lang, "Проверить ответ", "Test a reply"), "ux:test")],
            back(lang),
        ]
    elif action == "premium":
        settings = await db.get_global_settings()
        text = choose(
            lang,
            "💎 <b>Premium</b>\nБольше FAQ и AI-ответов. Покупка продлевает оставшееся время.",
            "💎 <b>Premium</b>\nMore FAQ and AI replies. Purchases extend your remaining subscription.",
        )
        text += f"\nFAQ: {settings['premium_faq_limit']}\nAI/day: {settings['premium_ai_daily_limit']}"
        rows = [
            [
                (
                    choose(lang, "Неделя", "Week")
                    + f" · {settings['premium_price_week']} ⭐",
                    "buy_premium:week",
                )
            ],
            [
                (
                    choose(lang, "Месяц", "Month")
                    + f" · {settings['premium_price_month']} ⭐",
                    "buy_premium:month",
                )
            ],
            back(lang),
        ]
    elif action == "referrals":
        from bot import build_ref_link

        link = await build_ref_link(owner, callback.bot)
        count = await db.get_referral_count(owner)
        text = (
            choose(
                lang,
                "🎁 <b>Рефералы</b>\nПригласите друга: после проверки каждый получает +1 AI к дневному лимиту.\n",
                "🎁 <b>Referrals</b>\nInvite a friend: after verification, each receives +1 daily AI reply.\n",
            )
            + html.escape(link)
            + f"\n{count}"
        )
        rows = [back(lang)]
    elif action.startswith("lang:"):
        value = action.split(":")[1]
        if value not in {"ru", "en"}:
            return
        await ext.set_option(owner, "language", value)
        if not p["native_language"]:
            await db.update_profile_field(
                owner, "native_language", "English" if value == "en" else "Русский"
            )
        await panel(
            callback,
            choose(value, "Язык сохранён ✅", "Language saved ✅"),
            [back(value, "ux:setup")],
        )
        return
    elif action == "status":
        connections = await db.get_connections(owner)
        providers = await __import__("ai_service").get_all_providers()
        quota = await db.get_user_quota_status(owner)
        mode = (
            "paused"
            if not prefs["autoreply_enabled"]
            else ("ai" if p["ai_enabled"] else "faq")
        )
        modes = {
            "paused": choose(lang, "Пауза", "Paused"),
            "ai": "FAQ + AI",
            "faq": choose(lang, "Только FAQ + запасной ответ", "FAQ + fallback"),
        }
        text = (
            choose(lang, "<b>Статус</b>", "<b>Status</b>")
            + f"\n{modes[mode]}\nBusiness: "
            + ("✅" if any(c["enabled"] for c in connections) else "❌")
        )
        text += choose(lang, "\nAI осталось: ", "\nAI remaining: ") + str(
            quota["remaining"]
        )
        if not providers or not USE_AI or not quota["global_enabled"]:
            text += choose(
                lang,
                "\n⚠️ AI недоступен. FAQ и запасные ответы работают.",
                "\n⚠️ AI unavailable. FAQ and fallback replies remain available.",
            )
        text += choose(
            lang,
            "\n\nЕсли Business отключён: подключите бота заново и разрешите отправку сообщений. После ответа владельца чат остаётся на паузе до ручного возобновления.",
            "\n\nIf Business is disconnected: reconnect the bot and allow sending messages. When the owner replies, that chat stays paused until manually resumed.",
        )
        rows = [
            [
                (choose(lang, "FAQ", "FAQ"), "ux:mode:faq"),
                ("FAQ + AI", "ux:mode:ai"),
                (choose(lang, "Пауза", "Pause"), "ux:mode:paused"),
            ],
            back(lang),
        ]
    elif action.startswith("mode:"):
        value = action.split(":")[1]
        if value not in {"faq", "ai", "paused"}:
            return
        await ext.save_undo(owner)
        async with db._connect() as conn:
            await conn.execute(
                "UPDATE user_preferences SET autoreply_enabled=? WHERE owner_id=?",
                (int(value != "paused"), owner),
            )
            await conn.execute(
                "UPDATE users SET ai_enabled=? WHERE telegram_id=?",
                (int(value == "ai"), owner),
            )
            await conn.commit()
        await panel(
            callback,
            choose(lang, "Режим сохранён ✅", "Mode saved ✅"),
            [
                [(choose(lang, "↩️ Отменить изменение", "↩️ Undo change"), "ux:undo")],
                back(lang, "ux:status"),
            ],
        )
        return
    elif action == "undo":
        restored = await ext.restore_undo(owner)
        await panel(
            callback,
            choose(
                lang,
                "Восстановлено ✅" if restored else "Нечего отменять.",
                "Restored ✅" if restored else "Nothing to undo.",
            ),
            [back(lang)],
        )
        return
    elif action == "delays":
        from reply_policy import mode_delay
        settings = await ext.business_settings(owner)
        maximum = 3600 if business else 60
        mode = "business" if business else "personal"
        text = choose(lang, f"Задержки бизнес-режима: 1–{maximum} сек. (до часа)." if business else "Задержки личного режима: 1–60 сек.", f"{'Business' if business else 'Personal'} delays: 1–{maximum} seconds.")
        text += choose(lang, "\nДля FAQ задержка задаётся в карточке вопроса.", "\nSet FAQ delays in each question card.")
        rows = [[(f"AI: {mode_delay(settings, mode, 'ai')} s", "ux:delay:ai"), (choose(lang, "Запасной", "Fallback") + f": {mode_delay(settings, mode, 'fallback')} s", "ux:delay:fallback")], back(lang, "ux:settings")]
    elif action.startswith("delay:"):
        target = action.split(":", 1)[1]
        if target not in {"ai", "fallback", "draft"} and not (target.startswith("faq:") and target[4:].isdigit()):
            return
        draft = await state.get_data() if target == "draft" else {}
        if target == "draft" and (await state.get_state() != Flow.faq_answer.state or not draft.get("question") or draft.get("album_draft")):
            await callback.answer(choose(lang, "Задайте задержку до отправки альбома.", "Set delay before sending an album."))
            return
        maximum = 3600 if business else 60
        await prompt(callback, state, Flow.reply_delay, choose(lang, f"Введите задержку: 1–{maximum} секунд.", f"Enter delay: 1–{maximum} seconds."), {**draft, "delay_target": target, "delay_mode": "business" if business else "personal"}, back_target=f"ux:faq:{target[4:]}" if target.startswith("faq:") else "ux:delays" if target != "draft" else "ux:home")
        return
    elif action == "faq_ignore_draft":
        data = await state.get_data()
        if await state.get_state() != Flow.faq_answer.state or not data.get("question"):
            await callback.answer(choose(lang, "Добавление FAQ уже завершено. Начните заново через «Добавить».", "This FAQ draft has expired. Start again with 'Add'."), show_alert=True)
            return
        await ext.save_undo(owner)
        await ext.append_faq(owner, data["question"], {"type": "text", "text": "[Не отвечать]", "payload": {"ignore": True}})
        await state.clear()
        await panel(callback, choose(lang, "Сохранено: бот не отвечает на эту фразу целиком, даже через AI или запасной ответ.", "Saved: no FAQ, AI or fallback reply to this exact phrase."), [back(lang, "ux:faqs")])
        return
    elif action.startswith("faq_ignore:"):
        faq_id = int(action.split(":")[1])
        faq = next((f for f in await db.get_faqs(owner) if f["id"] == faq_id), None)
        if not faq:
            return
        await ext.save_undo(owner)
        data = json.loads(faq["answer_payload"] or "{}")
        data["ignore"] = not data.get("ignore", False)
        async with db._connect() as conn:
            await conn.execute("UPDATE faq SET answer_payload=? WHERE owner_id=? AND id=?", (json.dumps(data), owner, faq_id))
            await conn.commit()
        await panel(callback, choose(lang, "Действие сохранено ✅", "Action saved ✅"), [[(choose(lang, "Открыть FAQ", "Open FAQ"), f"ux:faq:{faq_id}")]])
        return
    elif action == "settings":
        text = choose(lang, "⚙️ <b>Настройки бизнеса</b>" if business else "⚙️ <b>Личные настройки</b>", "⚙️ <b>Business settings</b>" if business else "⚙️ <b>Personal settings</b>")
        rows = [
            [(choose(lang, "⏱ Задержки ответов", "⏱ Reply delays"), "ux:delays")],
            [(choose(lang, "Основной язык ответа", "Primary reply language"), "ux:edit:primary_language")],
            [(choose(lang, "🧠 Настроить AI", "🧠 Configure AI"), "ux:ai")],
            [(choose(lang, "Подключить бота", "Connect bot"), "ux:connect"), (choose(lang, "Профиль и ответы", "Profile & replies"), "ux:knowledge")],
            [(choose(lang, "Бизнес-функции", "Business tools"), "ux:business_tools")],
            [
                (
                    choose(
                        lang,
                        "Интерфейс: Личный / Бизнес",
                        "Interface: Personal / Business",
                    ),
                    "ux:interface",
                )
            ],
            [("Русский", "ux:lang:ru"), ("English", "ux:lang:en")],
            [
                (choose(lang, "Расписание", "Schedule"), "ux:schedule"),
                (choose(lang, "Часовой пояс", "Timezone"), "ux:edit:timezone"),
            ],
            [
                (choose(lang, "Дополнительно", "Advanced"), "ux:advanced"),
                (choose(lang, "Аккаунт", "Account"), "ux:account"),
            ],
            back(lang),
        ]
        if not business:
            rows = [[button for button in row if button[1] not in {"ux:business_tools", "ux:schedule", "ux:knowledge"}] for row in rows]
            rows = [row for row in rows if row]
    elif action == "advanced":
        text = choose(lang, "Дополнительные настройки", "Advanced settings")
        rows = [
            [
                (choose(lang, "Экспорт", "Export"), "ux:export"),
                (choose(lang, "Импорт", "Import"), "ux:import"),
            ],
            [(choose(lang, "Повторить настройку", "Guided setup"), "ux:setup")],
            back(lang, "ux:settings"),
        ]
    elif action == "business_tools":
        text = choose(lang, "Бизнес-инструменты. Повышенные лимиты FAQ и AI доступны с Premium.", "Business tools. Higher FAQ and AI quotas are available with Premium.")
        rows = [[(choose(lang, "История и память AI", "History & AI memory"), "ux:inbox:0"), (choose(lang, "Статистика", "Statistics"), "ux:stats")], [(choose(lang, "Заявки", "Requests"), "ux:requests"), (choose(lang, "Сбор заявок", "Collect requests"), "ux:collect")], [(choose(lang, "Тест ответов", "Test replies"), "ux:test"), (choose(lang, "График", "Schedule"), "ux:schedule")], back(lang)]
        rows.insert(-1, [(choose(lang, "Отчёты и напоминания", "Reports & reminders"), "ux:reports")])
        rows.insert(0, [(choose(lang, "Профиль и ответы", "Profile & replies"), "ux:knowledge"), (choose(lang, "Заявки", "Requests"), "ux:requests")])
    elif action == "reports":
        settings = await ext.business_settings(owner)
        text = choose(lang, "Утренний отчёт: ", "Morning report: ") + settings["report_time"] + "\n" + choose(lang, "Три напоминания: ", "Three reminders: ") + ", ".join(settings["reminders"]) + "\n" + prefs["timezone"]
        rows = [[(choose(lang, "Изменить время", "Change times"), "ux:report_edit")], back(lang, "ux:business_tools")]
    elif action == "report_edit":
        await prompt(callback, state, Flow.reports, choose(lang, "Введите 4 времени: утренний отчёт и три напоминания. Например: 09:00 12:00 16:00 19:00. Используется ваш часовой пояс.", "Enter 4 times: morning report and three reminders. Example: 09:00 12:00 16:00 19:00. Uses your timezone."))
        return
    elif action == "account":
        text = choose(lang, "Аккаунт", "Account")
        rows = [
            [
                ("Premium", "ux:premium"),
                (choose(lang, "Рефералы", "Referrals"), "ux:referrals"),
            ],
            back(lang, "ux:settings"),
        ]
    elif action == "fallbacks":
        text = choose(lang, "💼 Запасные ответы бизнеса\nДва сообщения чередуются, когда нет подходящего FAQ или ответа AI.", "💼 Business fallbacks\nTwo replies alternate when FAQ or AI has no suitable answer.")
        rows = [[(choose(lang, "Запасной 1", "Fallback 1"), "ux:edit:fallback_text"), (choose(lang, "Запасной 2", "Fallback 2"), "ux:edit:fallback_text2")], [(choose(lang, "⏱ Задержка", "⏱ Delay"), "ux:delay:fallback")], back(lang)]
    elif action == "details":
        await prompt(
            callback,
            state,
            Flow.details,
            choose(
                lang,
                "Опишите ответы: ваша роль, стиль и полезные факты. Для бизнеса добавьте услуги, цены, часы и контакты. Максимум 2000 символов. Пример: «Ремонт телефонов. Работаем 9–18. Цены уточняет мастер». Не добавляйте пароли или ключи.",
                "Describe how to reply: your role, tone and useful facts. For business, add services, prices, hours and contacts. Maximum 2000 characters. Example: “Phone repair. Open 9–18. Technician confirms prices.” Do not include passwords or keys.",
            ),
        )
        return
    elif action.startswith("edit:"):
        field = action.split(":")[1]
        if field.startswith("fallback_text"):
            slot = {"fallback_text": 0, "fallback_text2": 1, "fallback_text3": 2}.get(field)
            if slot is None or slot == 2 or (slot and not business):
                await callback.answer()
                return
            await prompt(callback, state, Flow.fallback, choose(lang, "Отправьте запасное сообщение с форматированием или медиа.", "Send a fallback message with formatting or media."), {"slot": slot}, back_target="ux:fallbacks" if business else "ux:home")
            return
        if field not in {"timezone", "schedule_range", "fallback_text", "primary_language"}:
            return
        if field == "schedule_range" and not business:
            await callback.answer()
            return
        hints = {
            "primary_language": choose(lang, "Введите основной язык ответа, например Русский, Tajik или Uzbek.", "Enter your primary reply language, for example English, Tajik or Uzbek."),
            "timezone": choose(
                lang,
                "Часовой пояс, например Asia/Karachi.",
                "Timezone, for example Asia/Karachi.",
            ),
            "schedule_range": choose(
                lang,
                "Время, например 09:00-18:00. Ночной график: 22:00-06:00.",
                "Hours, for example 09:00-18:00. Overnight: 22:00-06:00.",
            ),
            "fallback_text": choose(
                lang,
                "Запасной ответ, максимум 2000 символов.",
                "Fallback reply, maximum 2000 characters.",
            ),
        }
        await prompt(callback, state, Flow.setting, hints[field], {"field": field}, back_target="ux:schedule" if field == "schedule_range" else "ux:settings")
        return
    elif action == "schedule":
        text = (
            choose(
                lang,
                "<b>Расписание</b>\nОтветы разрешены только в заданные часы.",
                "<b>Schedule</b>\nReplies are allowed only during these hours.",
            )
            + f"\n{html.escape(prefs['timezone'])}: {prefs['schedule_start']}–{prefs['schedule_end']}\n"
            + ("✅" if prefs["schedule_enabled"] else "❌")
        )
        rows = [
            [
                (
                    choose(lang, "Включить / выключить", "Enable / disable"),
                    "ux:schedule_toggle",
                )
            ],
            [(choose(lang, "Изменить часы", "Change hours"), "ux:edit:schedule_range")],
            back(lang, "ux:business_tools"),
        ]
    elif action == "schedule_toggle":
        await ext.save_undo(owner)
        await db.toggle_schedule(owner)
        await panel(
            callback,
            choose(lang, "Расписание сохранено ✅", "Schedule saved ✅"),
            [
                [(choose(lang, "Отменить", "Undo"), "ux:undo")],
                back(lang, "ux:schedule"),
            ],
        )
        return
    elif action == "collect":
        await ext.set_option(
            owner,
            "collect_requests",
            int(not (await ext.options(owner))["collect_requests"]),
        )
        text = choose(
            lang,
            "Сбор заявок переключён. Шаблоны для клиентов:\n/booking дата | услуга | имя | телефон\n/order товар | количество | имя | телефон\n/contact имя | телефон\nЗаявку подтверждает владелец.",
            "Request collection toggled. Customer templates:\n/booking date | service | name | phone\n/order product | quantity | name | phone\n/contact name | phone\nThe owner confirms each request.",
        )
        rows = [back(lang, "ux:business_tools")]
    elif action == "knowledge":
        business = (await ext.options(owner))["ui_mode"] == "business"
        text = (
            choose(
                lang,
                "📚 Знания" if business else "💬 Ответы",
                "📚 Knowledge" if business else "💬 Replies",
            )
            + f"\nFAQ: {await db.count_faqs(owner)}"
        )
        rows = [
            [(choose(lang, "Режим ответов", "Reply behavior"), "ux:status")],
            [
                (choose(lang, "Добавить вопрос", "Add question"), "ux:faq_add"),
                (choose(lang, "Мои ответы", "My answers"), "ux:faqs"),
            ],
            [
                (choose(lang, "Настроить AI", "Configure AI"), "ux:ai"),
                (choose(lang, "Шаблоны", "Templates"), "ux:templates"),
            ],
            [
                (
                    choose(lang, "Запасной ответ", "Fallback reply"),
                    "ux:edit:fallback_text",
                )
            ],
        ]
        if business:
            rows.append([(choose(lang, "Описание бизнеса", "Business description"), "ux:details")])
            rows.append([(choose(lang, "Запасные ответы", "Fallback replies"), "ux:fallbacks")])
            rows.append(
                [(choose(lang, "Предложения FAQ", "FAQ suggestions"), "ux:suggestions")]
            )
        rows.append(back(lang, "ux:business_tools" if business else "ux:home"))
        if not business:
            text = choose(lang, "Личные FAQ и ответы", "Personal FAQ & replies")
            rows = [[(choose(lang, "+ Добавить FAQ", "+ Add FAQ"), "ux:faq_add"), (choose(lang, "Готовые FAQ", "Saved FAQ"), "ux:faqs")], [(choose(lang, "Настроить AI", "Configure AI"), "ux:ai"), (choose(lang, "Запасной ответ", "Fallback reply"), "ux:edit:fallback_text")], back(lang)]
    elif action == "faq_add":
        await prompt(
            callback,
            state,
            Flow.faq_question,
            choose(
                lang,
                "Введите вопрос клиента (до 500 символов).",
                "Enter a customer question (up to 500 characters).",
            ),
        )
        return
    elif action == "faqs":
        faqs = await db.get_faqs(owner)
        text = choose(
            lang,
            "<b>FAQ</b>\nНажмите вопрос для просмотра или удаления.",
            "<b>FAQ</b>\nSelect a question to view or delete it.",
        )
        rows = [[(f["question"][:50], f"ux:faq:{f['id']}")] for f in faqs[:50]] + [
            back(lang)
        ]
    elif action.startswith("faq:"):
        from reply_policy import mode_delay
        faq = next(
            (
                f
                for f in await db.get_faqs(owner)
                if str(f["id"]) == action.split(":")[1]
            ),
            None,
        )
        if not faq:
            await callback.answer()
            return
        text = (
            html.escape(faq["question"][:500])
            + "\n\n"
            + html.escape((faq["answer"] or "[" + faq["answer_type"] + "]")[:2000])
        )
        if not business and faq["answer_type"] == "sequence":
            text += choose(lang, "\n\n👤 В личном режиме отправляется только первый ответ. Остальные ответы и URL-кнопки сохранены для бизнеса.", "\n\n👤 Personal sends only the first reply. Other replies and URL buttons are preserved for Business.")
        rows = [
            [(choose(lang, "👁 Предпросмотр", "👁 Preview"), f"ux:faq_preview:{faq['id']}")],
            [(choose(lang, "🔇 Не отвечать", "🔇 Do not reply") + (" ✓" if json.loads(faq["answer_payload"] or "{}").get("ignore") else ""), f"ux:faq_ignore:{faq['id']}"), (choose(lang, "⏱ Задержка", "⏱ Delay") + f" {mode_delay({}, 'business' if business else 'personal', 'faq', faq)} s", f"ux:delay:faq:{faq['id']}")],
            [(choose(lang, "Удалить?", "Delete?"), f"ux:delete_confirm:{faq['id']}")],
            back(lang, "ux:faqs"),
        ]
        if (await ext.options(owner))["ui_mode"] == "business":
            rows.insert(0, [(choose(lang, "+ Ещё ответ", "+ Another answer"), f"ux:faq_extra:{faq['id']}"), (choose(lang, "Инлайн-кнопки", "Inline buttons"), f"ux:faq_button_types:{faq['id']}")])
            command = json.loads(faq["answer_payload"] or "{}").get("command", "—")
            rows.insert(1, [(choose(lang, "Команда: ", "Command: ") + command, f"ux:faq_command:{faq['id']}")])
    elif action.startswith("faq_button_types:"):
        faq_id = int(action.split(":")[1])
        text = choose(lang, "Выберите тип кнопки. URL открывает ссылку; команда вызывает сохранённый FAQ. Всего до 5 кнопок.", "Choose a button type. URL opens a link; command calls a saved FAQ. Up to 5 buttons total.")
        rows = [[("🔗 URL", f"ux:faq_buttons:{faq_id}"), (choose(lang, "⌨️ Команда", "⌨️ Command"), f"ux:faq_command_button:{faq_id}")], [(choose(lang, "▦ Расположение", "▦ Layout"), f"ux:faq_layout:{faq_id}"), (choose(lang, "👁 Предпросмотр", "👁 Preview"), f"ux:faq_preview:{faq_id}")], back(lang, f"ux:faq:{faq_id}")]
    elif action.startswith("faq_preview:"):
        from reply_policy import mode_faq, payload
        faq_id = int(action.split(":")[1])
        faq = next((f for f in await db.get_faqs(owner) if f["id"] == faq_id), None)
        if not faq:
            await callback.answer(choose(lang, "FAQ удалён", "FAQ deleted"))
            return
        await callback.answer()
        if payload(faq).get("ignore"):
            await callback.message.answer(choose(lang, "🔇 Предпросмотр: этот FAQ ничего не отправляет.", "🔇 Preview: this FAQ sends nothing."), reply_markup=markup([back(lang, f"ux:faq:{faq_id}")]))
            return
        from bot import send_faq_answer
        await callback.message.answer(choose(lang, "👁 Предпросмотр для вас. Задержка здесь пропущена.", "👁 Preview for you. Delay is skipped here."))
        try:
            await send_faq_answer(callback.bot, callback.from_user.id, None, mode_faq(faq, "business" if business else "personal"))
        except Exception:
            await callback.message.answer(choose(lang, "Не удалось показать ответ. Проверьте доступность сохранённого медиа.", "Could not preview the reply. Check the saved media is still available."))
        await callback.message.answer(choose(lang, "Настроить ответ", "Edit reply"), reply_markup=markup([back(lang, f"ux:faq:{faq_id}")]))
        return
    elif action.startswith("faq_layout:"):
        faq_id = int(action.split(":")[1])
        faq = next((f for f in await db.get_faqs(owner) if f["id"] == faq_id), None)
        buttons = json.loads(faq["answer_payload"] or "{}").get("buttons", []) if faq else []
        if not buttons:
            await callback.answer(choose(lang, "Сначала добавьте кнопки", "Add buttons first"), show_alert=True)
            return
        text = choose(lang, "Каждая строка — ряд кнопок. Введите их номера, до трёх в ряд.\nПример:\n1 2\n3\n\nКнопки:\n", "Each line is a button row. Enter button numbers, up to three per row.\nExample:\n1 2\n3\n\nButtons:\n")
        text += "\n".join(f"{index + 1}. {html.escape(button['text'])}" for index, button in enumerate(buttons))
        await prompt(callback, state, Flow.faq_layout, text, {"faq_id": faq_id, "layout_buttons": buttons}, back_target=f"ux:faq_button_types:{faq_id}")
        return
    elif action.startswith(("faq_command:", "faq_command_button:")):
        faq_id = int(action.split(":")[1])
        if not any(f["id"] == faq_id for f in await db.get_faqs(owner)):
            await callback.answer()
            return
        button = action.startswith("faq_command_button:")
        await prompt(callback, state, Flow.faq_command_button if button else Flow.faq_command, choose(lang, "Две строки: название кнопки, затем команда другого FAQ.\nНапример:\nНаши цены\n/prices", "Two lines: button label, then another FAQ's command.\nExample:\nOur prices\n/prices") if button else choose(lang, "Введите команду для вызова этого FAQ, например /prices. Латинские буквы, цифры и _. «-» удаляет команду.", "Enter a command for this FAQ, e.g. /prices. Latin letters, digits and _. '-' removes the command."), {"faq_id": faq_id}, back_target=f"ux:faq:{faq_id}")
        return
    elif action.startswith(("faq_extra:", "faq_buttons:")):
        if (await ext.options(owner))["ui_mode"] != "business":
            await callback.answer()
            return
        faq_id = int(action.split(":")[1])
        if not any(f["id"] == faq_id for f in await db.get_faqs(owner)):
            await callback.answer()
            return
        buttons = action.startswith("faq_buttons:")
        await prompt(callback, state, Flow.faq_buttons if buttons else Flow.faq_extra,
            choose(lang, "Кнопки: одна строка на кнопку, Название | https://ссылка. До 5 кнопок.", "Buttons: one per line, Label | https://url. Up to 5 buttons.") if buttons else choose(lang, "Отправьте дополнительный ответ. Telegram разрешает пересылку от бота, но от подключённого аккаунта сообщение отправляется копией с сохранением медиа и форматирования.", "Send another answer. Telegram allows forwarding as a bot; replies on behalf of a connected account are copies preserving media and formatting."), {"faq_id": faq_id})
        return
    elif action.startswith("delete_confirm:"):
        faq_id = int(action.split(":")[1])
        text = choose(
            lang,
            "Удалить этот FAQ? Можно отменить последнее изменение.",
            "Delete this FAQ? You can undo the last change.",
        )
        rows = [
            [(choose(lang, "Да, удалить", "Yes, delete"), f"ux:delete:{faq_id}")],
            back(lang, "ux:faqs"),
        ]
    elif action.startswith("delete:"):
        await ext.save_undo(owner)
        await db.delete_faq(owner, int(action.split(":")[1]))
        text = choose(lang, "Удалено.", "Deleted.")
        rows = [[(choose(lang, "Отменить", "Undo"), "ux:undo")], back(lang, "ux:faqs")]
    elif action == "test":
        await prompt(
            callback,
            state,
            Flow.test,
            choose(
                lang,
                "Напишите как клиент: сначала «салом», затем вопрос об услуге и вопрос без известного ответа. Можно отправить несколько сообщений подряд — это отдельный тестовый разговор. Ответы видны только вам. AI расходует дневной лимит; FAQ и готовое приветствие бесплатны.",
                "Write as a customer: first 'salom', then a service question and a question without a known answer. Send several messages to simulate a separate test conversation. Replies are visible only to you. AI uses your quota; FAQ and the built-in greeting are free.",
            ),
        )
        return
    elif action == "templates":
        text = choose(
            lang,
            "Выберите роль помощника. Затем добавим проверенные факты и ваши правила.",
            "Choose an assistant role. Next add verified facts and your rules.",
        )
        rows = [
            [(choose(lang, ru, en), "ux:ai_preset:" + key)]
            for key, ru, en in [
                ("shop", "Магазин", "Shop"),
                ("services", "Услуги", "Services"),
                ("support", "Поддержка", "Support"),
                ("personal", "Личный помощник", "Personal assistant"),
            ]
        ] + [back(lang)]
    elif action.startswith("template:"):
        key = action.split(":")[1]
        templates = {
            "shop": (
                "Помогай выбрать товар. Используй только подтверждённые цены и наличие из FAQ. Заказы подтверждает владелец.",
                "Help customers choose products. Use only verified FAQ prices and availability. The owner confirms orders.",
            ),
            "services": (
                "Уточняй услугу и желаемую дату. Не обещай свободное время и стоимость без FAQ. Запись подтверждает владелец.",
                "Ask which service and date the customer wants. Do not promise availability or prices outside the FAQ. The owner confirms bookings.",
            ),
            "support": (
                "Уточняй проблему одним вопросом. Предлагай проверенные шаги из FAQ. Если решение неизвестно, передай вопрос владельцу.",
                "Ask one clarifying question about the issue. Offer verified FAQ steps. If the solution is unknown, refer to the owner.",
            ),
            "personal": (
                "Отвечай кратко и дружелюбно. Не раскрывай личные данные. Не обещай ничего от имени владельца без подтверждения.",
                "Reply briefly and kindly. Do not disclose private details. Do not make commitments without owner confirmation.",
            ),
        }
        if key not in templates:
            return
        await ext.save_undo(owner)
        await ext.save_assistant_settings(owner, {"role": templates[key][int(lang == "en")]})
        text = choose(
            lang,
            "Шаблон сохранён ✅ Добавьте факты о бизнесе и FAQ.",
            "Template saved ✅ Add your business facts and FAQ.",
        )
        rows = [
            [(choose(lang, "Отменить", "Undo"), "ux:undo")],
            [(choose(lang, "Проверенные факты", "Verified facts"), "ux:ai_edit:facts")],
            back(lang),
        ]
    elif action.startswith("inbox:"):
        offset = max(0, int(action.split(":")[1]))
        chats = await ext.inbox(owner, offset)
        text = choose(
            lang,
            "💬 <b>Чаты</b>\nВыберите чат и нажмите «Я отвечаю» перед переходом в Telegram.\n🙋 — отвечаете вы; ⚠️ — нужен ответ; ✅ — бот ответил.",
            "💬 <b>Chats</b>\nSelect a chat and tap 'I'll reply' before opening it in Telegram.\n🙋 you reply; ⚠️ needs attention; ✅ bot replied.",
        )
        rows = [
            [
                (
                    (
                        "🙋 "
                        if c["paused"]
                        else (
                            "⚠️ "
                            if c["source"] in {"fallback", "error", "handoff", None}
                            else "✅ "
                        )
                    )
                    + (c["peer_name"] or str(c["chat_id"]))[:45],
                    f"ux:chat:{c['chat_id']}",
                )
            ]
            for c in chats
        ]
        rows.append(
            [
                (
                    choose(lang, "Предыдущие", "Previous"),
                    f"ux:inbox:{max(0, offset - 10)}",
                ),
                (choose(lang, "Следующие", "Next"), f"ux:inbox:{offset + 10}"),
            ]
        )
        if (await ext.options(owner))["ui_mode"] == "business":
            rows.extend(
                [
                    [
                        (choose(lang, "Запросы", "Requests"), "ux:requests"),
                        (choose(lang, "Статистика", "Statistics"), "ux:stats"),
                    ],
                    [(choose(lang, "Сбор запросов", "Collect requests"), "ux:collect")],
                ]
            )
        rows.append(back(lang))
    elif action.startswith("chat:"):
        chat_id = int(action.split(":")[1])
        chat = await db.get_chat_settings(owner, chat_id)
        if not chat:
            await callback.answer()
            return
        history = await db.get_chat_history(owner, chat_id, 5) if business else []
        paused = await ext.is_handoff(owner, chat_id)
        text = (
            html.escape(chat.get("peer_name") or str(chat_id))
            + "\n"
            + choose(lang, "🙋 Отвечаете вы. Бот молчит." if paused else "🤖 Отвечает бот.", "🙋 You reply. Bot is paused." if paused else "🤖 Bot replies.")
            + "\n" + choose(lang, "Открытие чата само по себе не ставит бота на паузу. Нажмите «Я отвечаю» или отправьте своё сообщение.", "Opening a chat alone does not pause the bot. Tap 'I'll reply' or send your own message.")
            + "\n\n"
        )
        text += "\n\n".join(
            ("👤 " if h["role"] == "user" else "🤖 ") + html.escape(h["content"][:400])
            for h in history
        )
        rows = [
            [
                (choose(lang, "🙋 Я отвечаю", "🙋 I'll reply"), f"ux:takeover:{chat_id}"),
                (choose(lang, "🤖 Пусть отвечает бот", "🤖 Let bot reply"), f"ux:resume:{chat_id}"),
            ],
            [
                (
                    choose(lang, "Удалить данные чата", "Delete chat data"),
                    f"ux:forget_confirm:{chat_id}",
                )
            ],
            back(lang, "ux:inbox:0"),
        ]
    elif action.startswith(("pause:", "takeover:", "resume:")):
        chat_id = int(action.split(":")[1])
        chat = await db.get_chat_settings(owner, chat_id)
        if not chat:
            await callback.answer()
            return
        paused = not action.startswith("resume:")
        from business_runtime import takeover, resume_chat
        if paused:
            await takeover(owner, chat_id, "manual")
        else:
            await resume_chat(owner, chat_id)
        text = choose(
            lang,
            "🙋 Теперь отвечаете вы. AI, FAQ и запасные сообщения отключены только в этом чате. Бот вернётся после кнопки «Пусть отвечает бот»."
            if paused
            else "Чат возобновлён. Глобальный режим и расписание продолжают действовать.",
            "🙋 You reply now. AI, FAQ and fallbacks are paused only in this chat. Tap 'Let bot reply' to resume."
            if paused
            else "Conversation resumed. Global mode and schedule still apply.",
        )
        rows = [back(lang, f"ux:chat:{chat_id}")]
        if paused:
            rows.insert(0, [(choose(lang, "Открыть чат в Telegram", "Open chat in Telegram"), f"tg://user?id={chat_id}")])
    elif action.startswith("forget_confirm:"):
        chat_id = int(action.split(":")[1])
        text = choose(
            lang,
            "Удалить историю и запросы этого чата? Это нельзя отменить.",
            "Delete history and requests for this chat? This cannot be undone.",
        )
        rows = [
            [(choose(lang, "Подтверждаю", "Confirm"), f"ux:forget:{chat_id}")],
            back(lang, f"ux:chat:{chat_id}"),
        ]
    elif action.startswith("forget:"):
        chat_id = int(action.split(":")[1])
        from business_runtime import invalidate

        invalidate(owner, chat_id)
        await ext.forget_chat(owner, chat_id)
        text = choose(lang, "Данные чата удалены.", "Chat data deleted.")
        rows = [back(lang, "ux:inbox:0")]
    elif action == "suggestions":
        questions = await ext.unanswered(owner)
        text = choose(
            lang,
            "<b>Предложения FAQ</b>\nВыберите вопрос и напишите проверенный ответ. Ничего не публикуется автоматически.",
            "<b>FAQ suggestions</b>\nSelect a question and write a verified answer. Nothing is published automatically.",
        )
        rows = [[(q["question"][:50], f"ux:suggest:{q['id']}")] for q in questions] + [
            back(lang, "ux:knowledge")
        ]
    elif action.startswith("suggest:"):
        item = next(
            (
                q
                for q in await ext.unanswered(owner)
                if str(q["id"]) == action.split(":")[1]
            ),
            None,
        )
        if not item:
            await callback.answer()
            return
        await prompt(
            callback,
            state,
            Flow.suggestion,
            choose(
                lang,
                "Напишите проверенный ответ для FAQ:\n",
                "Write a verified FAQ answer:\n",
            )
            + html.escape(item["question"][:500]),
            {"question": item["question"][:500]},
        )
        return
    elif action == "stats":
        stats = await ext.statistics(owner)
        quota = await db.get_user_quota_status(owner)
        text = (
            choose(lang, "📊 <b>Последние 7 дней</b>", "📊 <b>Last 7 days</b>")
            + "\n"
            + choose(lang, "AI осталось сегодня: ", "AI remaining today: ")
            + str(quota["remaining"])
        )
        labels = {
            "faq": "FAQ",
            "greeting": choose(lang, "Приветствия", "Greetings"),
            "acknowledgement": choose(lang, "Подтверждения без ответа", "Acknowledgements without a reply"),
            "ai": "AI",
            "fallback": choose(lang, "Нужен ответ", "Needs attention"),
            "handoff": choose(lang, "Передано человеку", "Handed off"),
            "error": choose(lang, "Ошибки", "Errors"),
            "policy": choose(lang, "Стоп-темы", "Blocked topics"),
        }
        for source, total, success, latency in stats:
            text += f"\n{labels.get(source, source)}: {total} · {latency or 0}s"
        rows = [back(lang)]
    elif action == "requests":
        items = await ext.requests(owner)
        text = choose(
            lang,
            "📋 <b>Заявки</b>\nШаблоны: /booking дата | услуга | имя | телефон, /order товар | количество | имя | телефон, /contact имя | телефон. Включите сбор в бизнес-инструментах. Заявку подтверждает владелец.",
            "📋 <b>Requests</b>\nTemplates: /booking date | service | name | phone, /order product | quantity | name | phone, /contact name | phone. Enable collection in Business tools. The owner confirms each request.",
        )
        rows = [
            [(f"#{r['id']} {r['kind']}: {r['details'][:30]}", f"ux:request:{r['id']}")]
            for r in items
        ] + [back(lang)]
    elif action.startswith("request:"):
        item = next(
            (
                r
                for r in await ext.requests(owner)
                if str(r["id"]) == action.split(":")[1]
            ),
            None,
        )
        if not item:
            await callback.answer()
            return
        text = html.escape(item["details"][:2000])
        rows = [
            [
                (
                    choose(lang, "Обработано", "Mark handled"),
                    f"ux:request_done:{item['id']}",
                )
            ],
            back(lang, "ux:requests"),
        ]
    elif action.startswith("request_done:"):
        await ext.complete_request(owner, int(action.split(":")[1]))
        text = choose(lang, "Обработано ✅", "Handled ✅")
        rows = [back(lang, "ux:requests")]
    elif action == "export":
        data = await ext.export_owner(owner)
        await callback.answer()
        await callback.message.answer_document(
            BufferedInputFile(
                json.dumps(data, ensure_ascii=False, indent=2).encode(),
                filename="autoreply-settings.json",
            ),
            caption=choose(
                lang,
                "FAQ и настройки. Без API-ключей, платежей и переписки.",
                "FAQ and settings. Excludes API keys, payments and conversations.",
            ),
        )
        return
    elif action == "import":
        await prompt(
            callback,
            state,
            Flow.imported,
            choose(
                lang,
                "Отправьте JSON-экспорт (до 1 МБ). FAQ будут добавлены; дубликаты вопросов пропускаются. Настройки применяются после подтверждения.",
                "Send a JSON export (up to 1 MB). FAQ entries are appended; duplicate questions are skipped. Settings are applied after confirmation.",
            ),
        )
        return
    elif action == "import_confirm":
        # Handled by a dedicated callback below, registered ahead of this general route.
        return
    else:
        await callback.answer()
        return
    await panel(callback, text, rows)


@router.message(Flow.ai_feedback)
async def save_assistant_feedback(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    lang = await language(message.from_user)
    if not value or len(value) > 1000:
        await message.answer(choose(lang, "Нужен ответ до 1000 символов.", "Enter a reply up to 1000 characters."))
        return
    data = await state.get_data()
    settings = await ext.assistant_settings(message.from_user.id)
    example = "\n\nВопрос: " + data.get("feedback_question", "")[:500] + "\nХороший ответ: " + value
    if len(settings["examples"] + example) > 2000:
        await message.answer(choose(lang, "Примеры заполнены. Сократите их в «Стиль ответа → Примеры хороших ответов».", "Examples are full. Shorten them in Reply style → Good reply examples."), reply_markup=markup([back(lang, "ux:ai_behavior")]))
        return
    await ext.save_undo(message.from_user.id)
    await ext.save_assistant_settings(message.from_user.id, {"examples": (settings["examples"] + example).strip()})
    await state.clear()
    await message.answer(choose(lang, "Пример сохранён. Проверьте ответ снова. Это инструкция для будущих ответов, а не переобучение модели.", "Example saved. Test again. This guides future replies; it does not retrain the model."), reply_markup=markup([[(choose(lang, "Проверить", "Test"), "ux:test")], back(lang, "ux:ai")]))


@router.message(Flow.ai_field)
async def assistant_field_value(message: Message, state: FSMContext):
    from assistant_rules import TEXT_LIMITS
    lang = await language(message.from_user)
    field = (await state.get_data()).get("assistant_field")
    value = (message.text or "").strip()
    if field not in TEXT_LIMITS or not value or len(value) > TEXT_LIMITS[field]:
        await message.answer(choose(lang, "Нужен текст в указанном лимите.", "Enter text within the stated limit."))
        return
    await ext.save_undo(message.from_user.id)
    await ext.save_assistant_settings(message.from_user.id, {field: "" if value == "-" else value})
    await state.clear()
    await message.answer(choose(lang, "Сохранено ✅ Проверьте, как изменился ответ.", "Saved ✅ Test how the reply changed."), reply_markup=markup([[(choose(lang, "Проверить", "Test"), "ux:test")], back(lang, "ux:ai")]))


@router.message(Flow.ai_setup_facts)
@router.message(Flow.ai_setup_rules)
async def assistant_setup_value(message: Message, state: FSMContext):
    lang = await language(message.from_user)
    data = await state.get_data()
    draft = data.get("assistant_draft")
    if not draft:
        await state.clear()
        return
    facts_step = await state.get_state() == Flow.ai_setup_facts.state
    field = "facts" if facts_step else "rules"
    value = (message.text or "").strip()
    if not value or len(value) > (4000 if facts_step else 2000):
        await message.answer(choose(lang, "Нужен текст в указанном лимите. «-» — пропустить.", "Enter text within the limit. '-' skips this step."))
        return
    if value != "-":
        draft[field] = value
    await state.update_data(assistant_draft=draft)
    if facts_step:
        await state.set_state(Flow.ai_setup_rules)
        await message.answer(choose(lang, "Шаг 3 из 3. Ваши правила.\nНапример: не обещай скидку; уточняй один вопрос за раз; не подтверждай запись.\nДо 2000 символов. «-» — оставить прежние правила.\nЗащита от выдуманных цен, обещаний и путаницы с языком уже включена.", "Step 3 of 3. Your rules.\nExample: do not promise discounts; ask one question at a time; do not confirm bookings.\nUp to 2000 characters. '-' keeps existing rules.\nRules against invented facts, promises and language confusion are already included."), reply_markup=markup([back(lang, "ux:ai")]))
    else:
        await state.update_data(assistant_ready=True)
        await message.answer(choose(lang, "Проверьте настройку перед сохранением:\n\n", "Review before saving:\n\n") + assistant_summary(draft, lang), parse_mode="HTML", reply_markup=markup([[(choose(lang, "Сохранить и проверить", "Save and test"), "ux:ai_confirm")], back(lang, "ux:ai")]))


@router.message(Flow.reports)
async def report_times(message: Message, state: FSMContext):
    values = (message.text or "").split()
    lang = await language(message.from_user)
    if len(values) != 4 or len(set(values)) != 4 or not all(db.validate_time(v) for v in values):
        await message.answer(choose(lang, "Нужны четыре разных времени HH:MM.", "Enter four different HH:MM times."))
        return
    await ext.save_undo(message.from_user.id)
    await ext.save_business_setting(message.from_user.id, "report_time", values[0])
    await ext.save_business_setting(message.from_user.id, "reminders", values[1:])
    await state.clear()
    await message.answer(choose(lang, "График отчётов сохранён ✅", "Report schedule saved ✅"), reply_markup=await home_markup(message.from_user.id))


@router.message(Flow.faq_layout)
async def save_faq_layout(message: Message, state: FSMContext):
    from button_layout import parse_rows
    owner = message.from_user.id
    lang = await language(message.from_user)
    data = await state.get_data()
    faq = next((f for f in await db.get_faqs(owner) if f["id"] == data.get("faq_id")), None)
    if not faq or (await ext.options(owner))["ui_mode"] != "business":
        await state.clear()
        return
    payload = json.loads(faq["answer_payload"] or "{}")
    if payload.get("buttons", []) != data.get("layout_buttons"):
        await state.clear()
        await message.answer(choose(lang, "Кнопки изменились. Откройте расположение заново.", "Buttons changed. Open Layout again."))
        return
    try:
        payload["button_rows"] = parse_rows(message.text or "", len(payload.get("buttons", [])))
    except ValueError:
        await message.answer(choose(lang, "Укажите каждый номер ровно один раз, по 1–3 кнопки в строке.", "Use each number exactly once, with 1–3 buttons per line."))
        return
    await ext.save_undo(owner)
    async with db._connect() as conn:
        await conn.execute("UPDATE faq SET answer_payload=? WHERE owner_id=? AND id=?", (json.dumps(payload, ensure_ascii=False), owner, faq["id"]))
        await conn.commit()
    await state.clear()
    await message.answer(choose(lang, "Расположение сохранено ✅", "Layout saved ✅"), reply_markup=markup([[(choose(lang, "👁 Предпросмотр", "👁 Preview"), f"ux:faq_preview:{faq['id']}")], back(lang, f"ux:faq:{faq['id']}")]))


@router.message(Flow.faq_command)
@router.message(Flow.faq_command_button)
async def save_faq_command(message: Message, state: FSMContext):
    from reply_policy import payload, valid_command
    owner = message.from_user.id
    lang = await language(message.from_user)
    data = await state.get_data()
    faqs = await db.get_faqs(owner)
    faq = next((f for f in faqs if f["id"] == data.get("faq_id")), None)
    if not faq or (await ext.options(owner))["ui_mode"] != "business":
        await state.clear()
        return
    current = payload(faq)
    value = (message.text or "").strip()
    if await state.get_state() == Flow.faq_command_button.state:
        lines = value.splitlines()
        command = lines[1].strip().lower() if len(lines) == 2 else ""
        if len(lines) != 2 or not 1 <= len(lines[0].strip()) <= 64 or not valid_command(command):
            await message.answer(choose(lang, "Нужны две строки: название кнопки и /команда латиницей.", "Enter two lines: label and /command using Latin letters."))
            return
        if not any(payload(f).get("command") == command for f in faqs):
            await message.answer(choose(lang, "Сначала назначьте эту команду нужному FAQ в его карточке.", "Assign this command to the target FAQ first."))
            return
        buttons = current.get("buttons", [])
        if len(buttons) >= 5:
            await message.answer(choose(lang, "Уже добавлено 5 кнопок.", "Five buttons already configured."))
            return
        current["buttons"] = buttons + [{"text": lines[0].strip(), "command": command}]
        current.pop("button_rows", None)
    elif value == "-":
        current.pop("command", None)
    else:
        command = value.lower()
        if not valid_command(command):
            await message.answer(choose(lang, "Пример команды: /prices. До 32 символов после /, начинается с латинской буквы.", "Example: /prices. Up to 32 characters after /, starting with a Latin letter."))
            return
        if any(f["id"] != faq["id"] and payload(f).get("command") == command for f in faqs):
            await message.answer(choose(lang, "Эта команда уже назначена другому FAQ.", "This command belongs to another FAQ."))
            return
        current["command"] = command
    await ext.save_undo(owner)
    async with db._connect() as conn:
        await conn.execute("UPDATE faq SET answer_payload=? WHERE owner_id=? AND id=?", (json.dumps(current, ensure_ascii=False), owner, faq["id"]))
        await conn.commit()
    await state.clear()
    await message.answer(choose(lang, "Сохранено ✅", "Saved ✅"), reply_markup=markup([back(lang, f"ux:faq:{faq['id']}")]))


@router.callback_query(F.data.startswith("fqcall:"))
async def call_faq_button(callback: CallbackQuery):
    from reply_policy import payload, valid_command
    parts = callback.data.split(":")
    if len(parts) != 4 or not parts[1].isdigit() or not parts[2].isdigit():
        await callback.answer("Invalid button", show_alert=True)
        return
    owner, source_id = int(parts[1]), int(parts[2])
    command = "/" + parts[3]
    faqs = await db.get_faqs(owner)
    source = next((f for f in faqs if f["id"] == source_id), None)
    target = next((f for f in faqs if payload(f).get("command") == command), None)
    message = callback.message
    if not valid_command(command) or not source or not target or (await ext.options(owner))["ui_mode"] != "business" or not any(b.get("command") == command for b in payload(source).get("buttons", [])):
        await callback.answer("Кнопка больше не доступна / Button unavailable", show_alert=True)
        return
    connection = getattr(message, "business_connection_id", None)
    if connection:
        if await db.get_owner_by_connection(connection) != owner:
            await callback.answer("Button unavailable", show_alert=True)
            return
        if await ext.is_handoff(owner, message.chat.id):
            await callback.answer("Сейчас отвечает владелец / Owner is replying")
            return
        await callback.answer()
        from datetime import datetime, timezone
        from business_runtime import enqueue
        synthetic = message.model_copy(update={"text": command, "caption": None, "from_user": callback.from_user, "sender_business_bot": None, "date": datetime.now(timezone.utc), "message_id": -secrets.randbits(50), "reply_command": True})
        await enqueue(synthetic, callback.bot)
    elif message and callback.from_user.id == owner and message.chat.id == owner:
        await callback.answer()
        if payload(target).get("ignore"):
            return
        from bot import send_faq_answer
        await send_faq_answer(callback.bot, message.chat.id, None, target)
    else:
        await callback.answer("Button unavailable", show_alert=True)


@router.message(Flow.faq_extra)
@router.message(Flow.faq_buttons)
async def faq_extension(message: Message, state: FSMContext):
    from bot import serialize_answer
    owner = message.from_user.id
    lang = await language(message.from_user)
    data = await state.get_data()
    faq = next((f for f in await db.get_faqs(owner) if f["id"] == data.get("faq_id")), None)
    if not faq or (await ext.options(owner))["ui_mode"] != "business":
        await state.clear()
        return
    payload = json.loads(faq["answer_payload"] or "{}")
    if await state.get_state() == Flow.faq_buttons.state:
        from urllib.parse import urlsplit
        buttons = []
        for line in (message.text or "").splitlines():
            label, sep, url = line.partition("|")
            url = url.strip()
            parsed = urlsplit(url)
            if not sep or not label.strip() or len(label.strip()) > 64 or parsed.scheme not in {"https", "http"} or not parsed.netloc:
                await message.answer(choose(lang, "Формат: Название | https://example.com", "Format: Label | https://example.com"))
                return
            buttons.append({"text": label.strip(), "url": url})
        if not 1 <= len(buttons) <= 5:
            await message.answer(choose(lang, "Нужно от 1 до 5 кнопок.", "Enter 1 to 5 buttons."))
            return
        buttons = [b for b in payload.get("buttons", []) if "command" in b] + buttons
        if len(buttons) > 5:
            await message.answer(choose(lang, "Всего допускается 5 URL- и командных кнопок.", "Up to 5 URL and command buttons total."))
            return
        payload["buttons"] = buttons
        payload.pop("button_rows", None)
        answer_type = faq["answer_type"]
    else:
        spec = serialize_answer(message)
        if message.forward_origin and spec and not message.has_protected_content:
            spec = {"type": "forward", "payload": {"from_chat_id": message.chat.id, "message_id": message.message_id, "copy": spec}}
        if not spec:
            await message.answer(choose(lang, "Неподдерживаемый тип сообщения.", "Unsupported message type."))
            return
        if faq["answer_type"] == "sequence":
            items = payload.get("items", [])
        else:
            items = [{"type": faq["answer_type"], "text": faq["answer"], "file_id": faq["answer_file_id"], "entities": json.loads(faq["answer_entities"] or "[]"), "payload": {k: v for k, v in payload.items() if k not in {"buttons", "button_rows", "command", "delay", "ignore"}}}]
        if len(items) >= 10:
            await message.answer(choose(lang, "Максимум 10 ответов на вопрос.", "Maximum 10 answers per question."))
            return
        items.append(spec)
        payload = {**{k: v for k, v in payload.items() if k in {"buttons", "button_rows", "delay", "ignore", "command"}}, "items": items}
        answer_type = "sequence"
    await ext.save_undo(owner)
    async with db._connect() as conn:
        await conn.execute("UPDATE faq SET answer_type=?,answer_payload=? WHERE owner_id=? AND id=?", (answer_type, json.dumps(payload, ensure_ascii=False), owner, faq["id"]))
        await conn.commit()
    await state.clear()
    await message.answer(choose(lang, "FAQ обновлён ✅", "FAQ updated ✅"), reply_markup=markup([back(lang, f"ux:faq:{faq['id']}")]))


@router.message(Flow.setup_timezone)
async def setup_timezone(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    lang = await language(message.from_user)
    if not db.validate_timezone(value):
        await message.answer(choose(lang, "Неизвестный часовой пояс. Пример: Asia/Karachi.", "Unknown timezone. Example: Asia/Karachi."))
        return
    await db.set_preference(message.from_user.id, "timezone", value)
    await state.set_state(Flow.details)
    await message.answer(choose(lang, "Расскажите о бизнесе: товары или услуги, цены, контакты, часы работы и стиль общения (до 2000 символов).", "Describe your business: products or services, prices, contacts, opening hours and tone (up to 2000 characters)."), reply_markup=markup([back(lang)]))


@router.message(Flow.fallback)
async def fallback_value(message: Message, state: FSMContext):
    from bot import serialize_answer
    lang = await language(message.from_user)
    spec = serialize_answer(message)
    if not spec:
        await message.answer(choose(lang, "Этот тип сообщения Telegram не позволяет отправлять ботом.", "This message type cannot be sent by this bot."))
        return
    if message.media_group_id:
        data = await state.get_data()
        draft = data.get("album_draft", [])
        if len(draft) >= 10:
            return
        draft.append(spec)
        token = secrets.token_urlsafe(8)
        await state.update_data(album_draft=draft, album_token=token)
        old = _album_tasks.get(state.key)
        if old:
            old.cancel()
        _album_tasks[state.key] = asyncio.create_task(flush_draft(state, message.from_user.id, message.chat.id, message.bot, token))
        return
    slot = (await state.get_data()).get("slot", 0)
    try:
        await ext.save_undo(message.from_user.id)
        await ext.save_fallback(message.from_user.id, slot, spec)
    except ValueError as error:
        await message.answer(str(error))
        return
    await state.clear()
    await message.answer(choose(lang, "Запасное сообщение сохранено ✅", "Fallback saved ✅"), reply_markup=await home_markup(message.from_user.id))


@router.message(Flow.details)
@router.message(Flow.setting)
async def setting_value(message: Message, state: FSMContext):
    lang = await language(message.from_user)
    owner = message.from_user.id
    value = (message.text or "").strip()
    data = await state.get_data()
    field = data.get("field", "ai_description")
    if not value or len(value) > 2000:
        await message.answer(
            choose(
                lang,
                "Нужен текст до 2000 символов.",
                "Enter text up to 2000 characters.",
            )
        )
        return
    if field == "timezone" and not db.validate_timezone(value):
        await message.answer(
            choose(
                lang,
                "Неизвестный часовой пояс. Пример: Asia/Karachi.",
                "Unknown timezone. Example: Asia/Karachi.",
            )
        )
        return
    if field == "schedule_range":
        parts = value.replace(" ", "").replace("–", "-").split("-")
        if len(parts) != 2 or not all(db.validate_time(x) for x in parts):
            await message.answer("09:00-18:00")
            return
    await ext.save_undo(owner)
    if field in {"timezone", "primary_language"}:
        await db.set_preference(owner, field, value)
    elif field == "schedule_range":
        async with db._connect() as conn:
            await conn.execute(
                "UPDATE user_preferences SET schedule_start=?,schedule_end=? WHERE owner_id=?",
                (*parts, owner),
            )
            await conn.commit()
    else:
        await db.update_profile_field(owner, field, value)
    if field == "ai_description":
        await ext.set_option(owner, "setup_done", 1)
    await state.clear()
    await message.answer(
        choose(lang, "Сохранено ✅", "Saved ✅"),
        reply_markup=markup(
            [
                [(choose(lang, "Проверить ответ", "Test a reply"), "ux:test")],
                [(choose(lang, "Отменить", "Undo"), "ux:undo")],
                back(lang),
            ]
        ),
    )


@router.message(Flow.reply_delay)
async def save_reply_delay(message: Message, state: FSMContext):
    from reply_policy import validate_delay
    lang = await language(message.from_user)
    owner = message.from_user.id
    data = await state.get_data()
    business = (await ext.options(owner))["ui_mode"] == "business"
    maximum = 3600 if business else 60
    if data.get("delay_mode", "business" if business else "personal") != ("business" if business else "personal"):
        await state.clear()
        await message.answer(choose(lang, "Режим изменён. Откройте настройку задержки заново.", "Mode changed. Open the delay setting again."), reply_markup=await home_markup(owner))
        return
    try:
        value = validate_delay(int((message.text or "").strip()), maximum)
    except ValueError:
        await message.answer(choose(lang, f"Введите целое число от 1 до {maximum}.", f"Enter an integer from 1 to {maximum}."))
        return
    target = data["delay_target"]
    if target == "draft":
        await state.update_data(faq_delay=value)
        await state.set_state(Flow.faq_answer)
        await message.answer(choose(lang, f"Задержка: {value} сек. Теперь отправьте ответ или выберите «Не отвечать».", f"Delay: {value} seconds. Send the answer or choose 'Do not reply'."), reply_markup=markup([[(choose(lang, "🔇 Не отвечать", "🔇 Do not reply"), "ux:faq_ignore_draft")], back(lang)]))
        return
    await ext.save_undo(owner)
    if target.startswith("faq:"):
        faq_id = int(target[4:])
        faq = next((f for f in await db.get_faqs(owner) if f["id"] == faq_id), None)
        if not faq:
            await state.clear()
            return
        payload = json.loads(faq["answer_payload"] or "{}")
        payload["delay"] = value
        async with db._connect() as conn:
            await conn.execute("UPDATE faq SET answer_payload=? WHERE owner_id=? AND id=?", (json.dumps(payload), owner, faq_id))
            await conn.commit()
        back_target = f"ux:faq:{faq_id}"
    else:
        await ext.save_business_setting(owner, ("" if business else "personal_") + target + "_delay", value)
        back_target = "ux:delays"
    await state.clear()
    await message.answer(choose(lang, "Задержка сохранена ✅", "Delay saved ✅"), reply_markup=markup([back(lang, back_target)]))


@router.message(Flow.faq_question)
async def faq_question(message: Message, state: FSMContext):
    lang = await language(message.from_user)
    value = (message.text or "").strip()
    if not value or len(value) > 500:
        await message.answer(
            choose(lang, "Вопрос: 1–500 символов.", "Question: 1–500 characters.")
        )
        return
    await state.update_data(question=value)
    await state.set_state(Flow.faq_answer)
    await message.answer(
        choose(
            lang,
            "Теперь ответ (до 4096 символов) с форматированием или медиа: фото, видео, альбом, документ, GIF, аудио, голосовое, кружок, стикер, контакт, геолокация или опрос.",
            "Now the answer (up to 4096 characters) with formatting or media: photo, video, album, document, GIF, audio, voice, video note, sticker, contact, location or poll.",
        ),
        reply_markup=markup(
            [
                [(choose(lang, "🔇 Не отвечать", "🔇 Do not reply"), "ux:faq_ignore_draft"), (choose(lang, "⏱ Задержка", "⏱ Delay"), "ux:delay:draft")],
                back(lang),
            ]
        ),
    )


@router.message(Flow.faq_answer)
@router.message(Flow.suggestion)
async def faq_answer(message: Message, state: FSMContext):
    from bot import serialize_answer

    lang = await language(message.from_user)
    data = await state.get_data()
    spec = serialize_answer(message)
    if spec and not message.media_group_id and message.forward_origin and not message.has_protected_content and (await ext.options(message.from_user.id))["ui_mode"] == "business":
        spec = {"type": "forward", "payload": {"from_chat_id": message.chat.id, "message_id": message.message_id, "copy": spec}}
    if message.media_group_id:
        if not spec:
            return
        draft = data.get("album_draft", [])
        if len(draft) >= 10:
            await message.answer(
                choose(lang, "Максимум 10 файлов.", "Maximum 10 files.")
            )
            return
        draft.append(spec)
        token = secrets.token_urlsafe(8)
        await state.update_data(album_draft=draft, album_token=token)
        old = _album_tasks.get(state.key)
        if old:
            old.cancel()
        _album_tasks[state.key] = asyncio.create_task(
            flush_draft(
                state, message.from_user.id, message.chat.id, message.bot, token
            )
        )
        return
    if not spec or len(spec.get("text", "")) > 4096:
        await message.answer(
            choose(
                lang,
                "Неподдерживаемый ответ или текст длиннее 4096 символов.",
                "Unsupported answer or text longer than 4096 characters.",
            )
        )
        return
    await ext.save_undo(message.from_user.id)
    try:
        if data.get("faq_delay"):
            spec.setdefault("payload", {})["delay"] = data["faq_delay"]
        await ext.append_faq(message.from_user.id, data["question"], spec)
    except ValueError as error:
        await message.answer(str(error))
        return
    await state.clear()
    await message.answer(
        choose(lang, "FAQ сохранён ✅", "FAQ saved ✅"),
        reply_markup=markup(
            [
                [(choose(lang, "Отменить", "Undo"), "ux:undo")],
                back(lang, "ux:knowledge"),
            ]
        ),
    )


async def flush_draft(state, owner_id, chat_id, bot, token):
    try:
        await asyncio.sleep(2.5)
        await commit_draft(state, owner_id, chat_id, bot, token)
    finally:
        if _album_tasks.get(state.key) is asyncio.current_task():
            _album_tasks.pop(state.key, None)


async def commit_draft(state, owner_id, chat_id, bot, token):
    data = await state.get_data()
    current_state = await state.get_state()
    if (
        current_state not in {Flow.faq_answer.state, Flow.fallback.state}
        or data.get("album_token") != token
        or not data.get("album_draft")
    ):
        return
    lang = (await ext.options(owner_id))["language"]
    try:
        if current_state == Flow.fallback.state:
            await ext.save_undo(owner_id)
            await ext.save_fallback(owner_id, data.get("slot", 0), {"type": "media_group", "payload": {"items": data["album_draft"]}})
            await state.clear()
            await bot.send_message(chat_id, choose(lang, "Запасной альбом сохранён ✅", "Fallback album saved ✅"), reply_markup=await home_markup(owner_id))
            return
        await ext.save_undo(owner_id)
        await ext.append_faq(
            owner_id,
            data["question"],
            {
                "type": "media_group",
                "text": "",
                "payload": {"items": data["album_draft"], "delay": data.get("faq_delay", 1)},
            },
        )
        await state.clear()
        await bot.send_message(
            chat_id,
            choose(lang, "Альбом сохранён ✅", "Album saved ✅"),
            reply_markup=await home_markup(owner_id),
        )
    except Exception:
        logger.exception("Album save failed")
        await bot.send_message(
            chat_id,
            choose(
                lang,
                "Не удалось сохранить альбом. Проверьте лимит FAQ и повторите.",
                "Could not save the album. Check your FAQ limit and retry.",
            ),
        )


@router.callback_query(F.data == "album_finish")
async def finish_album(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("album_draft"):
        lang = await language(callback.from_user)
        await callback.answer(
            choose(lang, "Нет сохранённого альбома.", "No saved album."),
            show_alert=True,
        )
        return
    old = _album_tasks.pop(state.key, None)
    if old:
        old.cancel()
        await asyncio.gather(old, return_exceptions=True)
    await callback.answer()
    await commit_draft(
        state,
        callback.from_user.id,
        callback.message.chat.id,
        callback.bot,
        data.get("album_token"),
    )


async def shutdown_albums():
    tasks = list(_album_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@router.message(Flow.test)
async def test_reply(message: Message, state: FSMContext):
    from ai_service import get_ai_reply
    from bot import _strip_reasoning, send_faq_answer, send_fallback_message

    owner = message.from_user.id
    lang = await language(message.from_user)
    text = (message.text or "").strip()
    if not text or len(text) > 2000:
        await message.answer(
            choose(
                lang, "Вопрос: до 2000 символов.", "Question: up to 2000 characters."
            )
        )
        return
    from conversation_policy import should_silence_acknowledgement
    sandbox_history = (await state.get_data()).get("test_history", [])
    previous_reply = next((item.get("content", "") for item in reversed(sandbox_history) if item.get("role") == "assistant"), "")
    if should_silence_acknowledgement(text, previous_reply):
        sandbox_history.append({"role": "user", "content": text})
        await state.update_data(test_history=sandbox_history[-10:])
        await message.answer(choose(lang, "🔇 Подтверждение принято. В реальном чате бот ничего не отправит. Новый вопрос продолжит разговор.", "🔇 Acknowledgement accepted. In a real chat the bot sends nothing. A new question continues the conversation."), reply_markup=markup([back(lang, "ux:ai")]))
        return
    faqs = await db.get_faqs(owner)
    profile = await db.get_profile(owner)
    prefs = await db.get_preferences(owner)
    settings = await db.get_global_settings()
    from reply_policy import match_faq, payload, mode_faq
    faq, _ = await asyncio.to_thread(match_faq, text, faqs, FAQ_MATCH_THRESHOLD, allow_commands=(await ext.options(owner))["ui_mode"] == "business")
    if faq and payload(faq).get("ignore"):
        await message.answer(choose(lang, "🔇 FAQ: не отвечать. В реальном чате бот ничего не отправит.", "🔇 FAQ: do not reply. Nothing is sent in a real chat."), reply_markup=sandbox_markup(lang))
        return
    if faq:
        faq = mode_faq(faq, (await ext.options(owner))["ui_mode"])
    source = "FAQ"
    answer = None
    reservation = None
    used = False
    result = None
    test_history = (await state.get_data()).get("test_history", [])
    try:
        if find_blocked_topic(text, settings["blocked_topics"]):
            source = choose(lang, "Стоп-тема", "Blocked topic")
            answer = settings["blocked_reply"]
        elif faq:
            answer = faq["answer"] or "[" + faq["answer_type"] + "]"
        elif USE_AI and profile["ai_enabled"] and settings["ai_global_enabled"] == "1":
            from assistant_rules import greeting_reply
            answer = greeting_reply(text, db.get_allowed_languages(prefs, profile["plan"]), await ext.assistant_settings(owner))
            if answer:
                source = choose(lang, "Приветствие на основном языке", "Greeting in the primary language")
        if not answer and not faq and not find_blocked_topic(text, settings["blocked_topics"]) and USE_AI and profile["ai_enabled"] and settings["ai_global_enabled"] == "1":
            reservation = await db.reserve_user_ai_slot(owner)
            if reservation["allowed"]:
                result = await get_ai_reply(
                    user_text=text,
                    profile=profile,
                    faq_context=await asyncio.to_thread(select_ai_context, text, [f for f in faqs if not payload(f).get("ignore")]),
                    languages=db.get_allowed_languages(prefs, profile["plan"]),
                    blocked_topics=settings["blocked_topics"],
                    blocked_reply=settings["blocked_reply"],
                    history=test_history,
                )
                answer = _strip_reasoning(result.text) if result.ok else None
                if answer:
                    source = "AI"
        if not answer:
            source = choose(lang, "Запасной ответ", "Fallback")
            if await send_fallback_message(message.bot, owner, message.chat.id, None, profile):
                await remember_sandbox(state, text, "[Запасное сообщение]")
                await message.answer(choose(lang, "Источник: запасное сообщение", "Source: fallback"), reply_markup=sandbox_markup(lang))
                return
            answer = profile["fallback_text"] or choose(
                lang, "Нет запасного ответа.", "No fallback configured."
            )
        if source == "FAQ" and faq:
            from assistant_rules import faq_facts
            await remember_sandbox(state, text, faq_facts(faq) or "[media]")
            await message.answer(choose(lang, "Источник: FAQ", "Source: FAQ"), reply_markup=sandbox_markup(lang))
            await send_faq_answer(message.bot, message.chat.id, None, faq)
            return
        await message.answer(
            choose(lang, "Источник: ", "Source: ") + source + "\n\n" + answer[:3000],
            reply_markup=sandbox_markup(lang),
        )
        await remember_sandbox(state, text, answer)
        used = source == "AI" and result is not None and result.provider != "local"
    finally:
        if reservation and reservation["allowed"] and not used:
            await asyncio.shield(db.release_user_ai_slot(owner, reservation["day"]))


@router.message(Flow.imported)
async def import_file(message: Message, state: FSMContext):
    lang = await language(message.from_user)
    if not message.document or (message.document.file_size or 0) > 1_000_000:
        await message.answer(
            choose(lang, "Нужен JSON-файл до 1 МБ.", "Send a JSON file up to 1 MB.")
        )
        return
    try:
        buffer = io.BytesIO()
        await message.bot.download(message.document, destination=buffer)
        if buffer.tell() > 1_000_000:
            raise ValueError("File too large")
        data = json.loads(buffer.getvalue())
        ext.validate_export(data)
    except (ValueError, TypeError, KeyError):
        await message.answer(
            choose(
                lang,
                "Некорректный экспорт. Используйте файл из этого бота.",
                "Invalid export. Use a file exported by this bot.",
            )
        )
        return
    await state.update_data(import_data=data)
    await message.answer(
        choose(
            lang,
            "Применить настройки и добавить FAQ?",
            "Apply settings and append FAQ?",
        ),
        reply_markup=markup(
            [[(choose(lang, "Подтвердить", "Confirm"), "import_apply")], back(lang)]
        ),
    )


@router.callback_query(F.data == "import_apply")
async def apply_import(callback: CallbackQuery, state: FSMContext):
    lang = await language(callback.from_user)
    data = (await state.get_data()).get("import_data")
    if await state.get_state() != Flow.imported.state or not data:
        await callback.answer()
        return
    try:
        await ext.save_undo(callback.from_user.id)
        count = await ext.import_owner(callback.from_user.id, data)
    except ValueError as error:
        await callback.answer(str(error)[:180], show_alert=True)
        return
    await state.clear()
    await panel(
        callback,
        choose(lang, "Импорт завершён. Добавлено FAQ: ", "Import complete. FAQ added: ")
        + str(count),
        [[(choose(lang, "Отменить", "Undo"), "ux:undo")], back(lang)],
    )

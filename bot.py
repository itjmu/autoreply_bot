import asyncio
import html
import json
import logging
import random


from aiogram import (
    Bot,
    Dispatcher,
    F,
    Router,
)

from aiogram.filters import (
    Command,
    CommandStart,
)

from aiogram.fsm.context import (
    FSMContext,
)

from aiogram.fsm.storage.memory import (
    MemoryStorage,
)

from aiogram.types import (
    BusinessConnection,
    CallbackQuery,
    ContentType,
    InputMediaAnimation,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    InputPollOption,
    LabeledPrice,
    Message,
    MessageEntity,
    PreCheckoutQuery,
)


from ai_service import (
    get_ai_reply,
    get_configured_providers,
)

from config import (
    ADMIN_IDS,
    AI_PROVIDER_ORDER,
    AUTO_REPLY_DELAY,
    BOT_TOKEN,
    FAQ_MATCH_THRESHOLD,
    USE_AI,
)

from database import (
    add_faq,
    add_guide_message,
    clear_guide_messages,
    count_chat_roles,
    count_faqs,
    count_guide_messages,
    count_users,
    delete_faq,
    delete_guide_message,
    ensure_user,
    get_admin_stats,
    get_all_user_ids,
    get_allowed_languages,
    get_chat_settings,
    get_chats_for_roles,
    get_connections,
    get_fallback_stage,
    get_faqs,
    get_global_settings,
    get_guide_messages,
    get_owner_by_connection,
    get_preferences,
    get_profile,
    get_provider_list,
    get_referral_count,
    get_user_quota_status,
    get_users_for_admin,
    init_db,
    init_providers,
    is_referred,
    record_referral,
    release_user_ai_slot,
    remember_chat,
    reserve_user_ai_slot,
    reset_daily_usage,
    save_business_connection,
    set_chat_role,
    set_fallback_stage,
    set_global_setting,
    set_preference,
    set_premium,
    set_provider_order,
    set_show_promo,
    should_autoreply,
    toggle_ai,
    toggle_autoreply,
    toggle_chat,
    toggle_global_ai,
    toggle_provider,
    toggle_schedule,
    toggle_user_plan,
    update_profile_field,
    user_exists,
    validate_time,
    validate_timezone,
)

from keyboards import (
    admin_back,
    admin_guide_keyboard,
    admin_menu,
    admin_premium_menu,
    admin_providers_keyboard,
    admin_users_keyboard,
    back_main,
    broadcast_confirm_keyboard,
    chat_manage_menu,
    chat_roles_keyboard,
    faq_list_keyboard,
    guide_adding_keyboard,
    languages_menu,
    main_menu,
    manual_payment_keyboard,
    premium_buy_keyboard,
    profile_menu,
    referral_menu,
    schedule_menu,
    settings_menu,
    timezone_menu,
)

from matcher import (
    find_direct_answer,
    select_ai_context,
)

from policy import (
    find_blocked_topic,
    parse_blocked_topics,
)

from states import (
    AddFAQ,
    AdminEdit,
    AdminUserSearch,
    Broadcast,
    Captcha,
    ChatRole,
    Guide,
    PreferenceEdit,
    ProfileEdit,
    ProviderOrder,
)


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
)


logger = logging.getLogger(
    "AutoReply"
)


router = Router(
    name="main"
)


_bot_username = ""


# =========================================================
# HELPERS
# =========================================================

def is_admin(
    user_id: int,
):

    return (
        user_id in ADMIN_IDS
    )


async def notify_admins_new_user(
    bot: Bot,
    telegram_id: int,
    first_name: str,
    username: str,
):

    name = (
        html.escape(
            first_name or "Без имени"
        )
    )


    username_line = (
        f"@{html.escape(username)}"
        if username
        else "нет"
    )


    total = await count_users()


    text = (
        "🆕 <b>Новый пользователь</b>\n\n"
        f"Имя: <b>{name}</b>\n"
        f"Username: {username_line}\n"
        f"ID: <code>{telegram_id}</code>\n\n"
        f"Всего пользователей: <b>{total}</b>"
    )


    for admin_id in ADMIN_IDS:

        try:

            await bot.send_message(
                admin_id,
                text,
                parse_mode="HTML",
            )

        except Exception as error:

            logger.warning(
                "New-user notify failed "
                "for admin %s: %s",
                admin_id,
                error,
            )


async def build_main_markup(
    user_id: int,
):

    profile = await get_profile(
        user_id
    )


    quota = (
        await get_user_quota_status(
            user_id
        )
    )


    prefs = await get_preferences(
        user_id
    )


    return main_menu(

        ai_enabled=bool(
            profile[
                "ai_enabled"
            ]
        ),

        ai_used=(
            quota["used"]
        ),

        ai_limit=(
            quota["limit"]
        ),

        global_ai_enabled=(
            quota[
                "global_enabled"
            ]
        ),

        autoreply_enabled=bool(
            prefs[
                "autoreply_enabled"
            ]
        ),

        is_admin=(
            is_admin(
                user_id
            )
        ),
    )


async def show_main_callback(
    callback: CallbackQuery,
):

    await callback.message.edit_text(

        "🤖 <b>AutoReply</b>\n\n"

        "Настройте личный автоответчик "
        "для Telegram Business.",

        reply_markup=(
            await build_main_markup(
                callback.from_user.id
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer()


async def delete_user_message(
    message: Message,
):

    try:

        await message.delete()

    except Exception:

        pass


def profile_text(
    profile: dict,
):

    return (

        "👤 <b>ПРОФИЛЬ AI</b>\n\n"

        f"Имя / роль: <b>"
        f"{html.escape(profile['owner_name'] or 'не указано')}"
        f"</b>\n"

        f"Возраст: <b>"
        f"{html.escape(profile['age'] or 'не указан')}"
        f"</b>\n"

        f"Пол: <b>"
        f"{html.escape(profile['gender'] or 'не указан')}"
        f"</b>\n\n"

        f"💬 <b>Темы владельца:</b>\n"
        f"{html.escape(profile['topics'] or 'не указаны')}\n\n"

        f"🧠 <b>Характеристика помощника:</b>\n"
        f"{html.escape(profile['ai_description'] or 'не указана')}\n\n"

        f"🆘 <b>Запасной ответ:</b>\n"
        f"{html.escape(profile['fallback_text'])}"
    )


async def settings_text(
    user_id: int,
):

    prefs = await get_preferences(
        user_id
    )


    profile = await get_profile(
        user_id
    )


    languages = (
        get_allowed_languages(
            prefs,
            profile["plan"],
        )
    )


    if prefs[
        "schedule_enabled"
    ]:

        schedule = (
            f"{prefs['schedule_start']} – "
            f"{prefs['schedule_end']}"
        )

    else:

        schedule = (
            "выключен — бот работает 24/7"
        )


    text = (

        "⚙️ <b>НАСТРОЙКИ АВТООТВЕТЧИКА</b>\n\n"

        f"🤖 Автоответчик: <b>"
        f"{'ВКЛ' if prefs['autoreply_enabled'] else 'ВЫКЛ'}"
        f"</b>\n\n"

        f"🌍 Языки:\n"
        f"<b>{html.escape(', '.join(languages))}</b>\n\n"

        f"🕐 Часовой пояс:\n"
        f"<b>{html.escape(prefs['timezone'])}</b>\n\n"

        f"📅 График:\n"
        f"<b>{html.escape(schedule)}</b>\n\n"

        f"Тариф: <b>"
        f"{'⭐ Premium' if profile['plan'] == 'premium' else '🆓 Free'}"
        f"</b>"
    )


    return (
        text,
        prefs,
    )


async def build_admin_text():

    settings = (
        await get_global_settings()
    )


    stats = (
        await get_admin_stats()
    )


    blocked_count = len(
        parse_blocked_topics(
            settings[
                "blocked_topics"
            ]
        )
    )


    status = (
        "🟢 Включён"
        if settings[
            "ai_global_enabled"
        ] == "1"
        else
        "🔴 Выключен"
    )


    return (

        "👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n"

        f"🤖 AI глобально: <b>{status}</b>\n\n"

        f"👥 Пользователей: "
        f"<b>{stats['users']}</b>\n"

        f"🆓 Free: "
        f"<b>{stats['free_users']}</b>\n"

        f"⭐ Premium: "
        f"<b>{stats['premium_users']}</b>\n"

        f"📚 FAQ: "
        f"<b>{stats['faq_count']}</b>\n\n"

        f"🧠 AI-попыток сегодня: "
        f"<b>{stats['provider_attempts']}</b>\n"

        f"✅ Успешных AI-ответов провайдеров: "
        f"<b>{stats['provider_successes']}</b>\n\n"

        f"5️⃣ Free лимит: "
        f"<b>{settings['free_ai_daily_limit']}/день</b>\n"

        f"⭐ Premium лимит: "
        f"<b>{settings['premium_ai_daily_limit']}/день</b>\n\n"

        f"🚫 Запрещённых тем: "
        f"<b>{blocked_count}</b>\n\n"

        "FAQ-ответы AI-лимит не расходуют."
    )


def build_admin_premium_text(
    settings: dict,
):

    manual_on = (
        settings.get(
            "manual_payment_enabled"
        )
        == "1"
    )

    manual_status = (
        "🟢 Включён"
        if manual_on
        else "⚪ Выключен"
    )

    manual_preview = html.escape(
        settings.get(
            "manual_payment_text"
        )
        or "не заполнен"
    )


    return (

        "💎 <b>PREMIUM — УПРАВЛЕНИЕ</b>\n\n"

        f"⭐ Цена за 1 неделю: "
        f"<b>{settings['premium_price_week']}</b>\n"

        f"⭐ Цена за 1 месяц: "
        f"<b>{settings['premium_price_month']}</b>\n\n"

        f"📚 FAQ Free: "
        f"<b>{settings['free_faq_limit']}</b>\n"

        f"📚 FAQ Premium: "
        f"<b>{settings['premium_faq_limit']}</b>\n"

        f"🎭 Ролей Free: "
        f"<b>{settings.get('free_chat_roles', '1')}</b>\n"

        f"🎭 Макс. ролей Premium: "
        f"<b>{settings['max_chat_roles']}</b>\n\n"

        f"💳 Ручной способ оплаты: "
        f"<b>{manual_status}</b>\n"

        f"Текст способа:\n"
        f"<code>{manual_preview}</code>\n\n"

        f"⏱ Интервал рассылки: "
        f"<b>{html.escape(str(settings.get('broadcast_interval', '1')))}с</b>\n\n"

        f"📣 Рекламная подпись:\n"
        f"<code>"
        f"{html.escape(settings.get('promo_signature_text') or 'не заполнена')}"
        f"</code>"
    )


# =========================================================
# /START / MAIN
# =========================================================

@router.message(
    Command("myid")
)
async def my_id_handler(
    message: Message,
):

    await message.answer(

        "🆔 Ваш Telegram ID:\n\n"

        f"<code>"
        f"{message.from_user.id}"
        f"</code>",

        parse_mode="HTML",
    )


@router.message(
    CommandStart()
)
async def start_handler(
    message: Message,
    state: FSMContext,
):

    await state.clear()


    is_new_user = not (
        await user_exists(
            message.from_user.id
        )
    )


    await ensure_user(

        message.from_user.id,

        username=(
            message.from_user.username
            or ""
        ),

        first_name=(
            message.from_user.first_name
            or ""
        ),
    )


    if is_new_user:

        await notify_admins_new_user(

            message.bot,

            message.from_user.id,

            message.from_user.first_name
            or "",

            message.from_user.username
            or "",
        )


    text = (
        message.text
        or ""
    )


    parts = text.split(
        maxsplit=1
    )


    payload = (
        parts[1]
        if len(parts) > 1
        else ""
    )


    # =====================================
    # MANAGE BOT / BUSINESS CHAT
    # =====================================

    if payload.startswith(
        "bizChat"
    ):

        raw_chat_id = payload[
            len("bizChat"):
        ]


        try:

            chat_id = int(
                raw_chat_id
            )

        except ValueError:

            chat_id = None


        if chat_id is not None:

            chat_settings = (
                await get_chat_settings(

                    message.from_user.id,

                    chat_id,
                )
            )


            if chat_settings:

                peer_name = (
                    chat_settings[
                        "peer_name"
                    ]

                    or (

                        f"@{chat_settings['username']}"

                        if chat_settings[
                            "username"
                        ]

                        else
                        f"ID {chat_id}"
                    )
                )


                await message.answer(

                    "💬 <b>УПРАВЛЕНИЕ ДИАЛОГОМ</b>\n\n"

                    f"Клиент:\n"
                    f"<b>{html.escape(peer_name)}</b>\n\n"

                    f"Автоответчик для этого чата:\n"
                    f"<b>"
                    f"{'🟢 Включён' if chat_settings['enabled'] else '🔴 Выключен'}"
                    f"</b>\n\n"

                    "Эта настройка действует "
                    "только для этого диалога.",

                    reply_markup=(
                        chat_manage_menu(

                            chat_id,

                            bool(
                                chat_settings[
                                    "enabled"
                                ]
                            ),
                        )
                    ),

                    parse_mode="HTML",
                )


                return


            await message.answer(

                "Этот Business-диалог пока "
                "не найден в базе бота.\n\n"

                "Он появится после получения "
                "сообщения через подключённый "
                "Telegram Business.",

                reply_markup=back_main(),
            )


            return


    # =====================================
    # REFERRAL + CAPTCHA
    # =====================================

    if payload.startswith("ref_"):

        try:

            referrer_id = int(
                payload[4:]
            )

        except ValueError:

            referrer_id = None


        if (
            referrer_id
            and referrer_id
            != message.from_user.id
            and not await is_referred(
                message.from_user.id
            )
        ):

            a = random.randint(2, 15)
            b = random.randint(2, 15)

            await state.update_data(
                referrer_id=referrer_id,
                captcha_answer=a + b,
                captcha_attempts=0,
            )

            await state.set_state(
                Captcha.answer
            )

            await message.answer(
                "🔐 <b>Проверка</b>\n\n"
                f"Сколько будет "
                f"<b>{a} + {b}</b>?\n\n"
                "Отправьте число.",
                parse_mode="HTML",
            )

            return


    # =====================================
    # NORMAL START
    # =====================================

    await message.answer(

        "🤖 <b>AutoReply</b>\n\n"

        "Создавайте свои вопросы и ответы, "
        "настраивайте AI, языки, график "
        "и Telegram Business.",

        reply_markup=(
            await build_main_markup(
                message.from_user.id
            )
        ),

        parse_mode="HTML",
    )


@router.callback_query(
    F.data == "main"
)
async def main_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.clear()

    await show_main_callback(
        callback
    )


# =========================================================
# CAPTCHA
# =========================================================

@router.message(
    Captcha.answer
)
async def captcha_handler(
    message: Message,
    state: FSMContext,
):

    if not message.text:
        return

    data = await state.get_data()

    correct = data.get(
        "captcha_answer"
    )

    referrer_id = data.get(
        "referrer_id"
    )

    attempts = data.get(
        "captcha_attempts",
        0,
    )

    try:

        user_answer = int(
            message.text.strip()
        )

    except ValueError:

        user_answer = None

    if user_answer == correct:

        await state.clear()

        await ensure_user(
            message.from_user.id,
            username=(
                message.from_user.username
                or ""
            ),
            first_name=(
                message.from_user.first_name
                or ""
            ),
        )

        await record_referral(
            referrer_id,
            message.from_user.id,
        )

        await message.answer(
            "✅ <b>Проверка пройдена!</b>\n\n"
            "🎁 Вы получили <b>+1</b> "
            "бонусный AI-ответ!\n\n"
            "🤖 <b>AutoReply</b>\n\n"
            "Создавайте свои вопросы и ответы, "
            "настраивайте AI, языки, график "
            "и Telegram Business.",
            reply_markup=(
                await build_main_markup(
                    message.from_user.id
                )
            ),
            parse_mode="HTML",
        )

        return

    attempts += 1

    if attempts >= 3:

        await state.clear()

        await message.answer(
            "❌ Слишком много ошибок.\n\n"
            "Нажмите /start чтобы начать заново.",
        )

        return

    a = random.randint(2, 15)
    b = random.randint(2, 15)

    await state.update_data(
        captcha_answer=a + b,
        captcha_attempts=attempts,
    )

    await message.answer(
        f"❌ Неверно. Попробуйте ещё.\n\n"
        f"Сколько будет <b>{a} + {b}</b>?\n\n"
        f"Осталось попыток: "
        f"<b>{3 - attempts}</b>",
        parse_mode="HTML",
    )


# =========================================================
# REFERRALS
# =========================================================

@router.callback_query(
    F.data == "referrals"
)
async def referrals_callback(
    callback: CallbackQuery,
):

    user_id = (
        callback.from_user.id
    )

    count = await get_referral_count(
        user_id
    )

    link = (
        f"https://t.me/{_bot_username}"
        f"?start=ref_{user_id}"
    )

    await callback.message.edit_text(
        "🎁 <b>РЕФЕРАЛЫ</b>\n\n"
        f"Приглашено: <b>{count}</b>\n"
        f"Бонус к лимиту: "
        f"<b>+{count}</b> AI-ответов/день\n\n"
        f"Ваша ссылка:\n"
        f"<code>{link}</code>\n\n"
        "За каждого приглашённого вы получаете "
        "+1 к дневному AI-лимиту.\n\n"
        "Новый пользователь после капчи "
        "тоже получает +1 бонусный ответ.",
        reply_markup=referral_menu(),
        parse_mode="HTML",
    )

    await callback.answer()


# =========================================================
# FAQ ADD
# =========================================================

@router.callback_query(
    F.data == "faq_add"
)
async def faq_add_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.clear()


    profile = await get_profile(
        callback.from_user.id
    )


    is_premium = (
        profile["plan"] == "premium"
    )


    settings = (
        await get_global_settings()
    )


    free_faq_limit = int(
        settings["free_faq_limit"]
    )

    premium_faq_limit = int(
        settings["premium_faq_limit"]
    )


    faq_limit = (
        premium_faq_limit
        if is_premium
        else free_faq_limit
    )


    faq_count = await count_faqs(
        callback.from_user.id
    )


    if faq_count >= faq_limit:

        if is_premium:

            text = (
                "⛔ <b>Лимит FAQ достигнут</b>\n\n"

                f"У вас уже "
                f"<b>{faq_count}</b> из "
                f"<b>{faq_limit}</b> вопросов "
                f"(максимум для Premium).\n\n"

                "Удалите лишний вопрос, "
                "чтобы добавить новый."
            )

        else:

            text = (
                "⛔ <b>Лимит FAQ достигнут</b>\n\n"

                f"У вас уже "
                f"<b>{faq_count}</b> из "
                f"<b>{faq_limit}</b> вопросов "
                f"(бесплатный лимит).\n\n"

                f"⭐ С тарифом <b>Premium</b> "
                f"можно до "
                f"<b>{premium_faq_limit}</b> "
                f"вопросов."
            )


        await callback.message.edit_text(

            text,

            reply_markup=back_main(),

            parse_mode="HTML",
        )


        await callback.answer()

        return


    await state.update_data(
        panel_message_id=(
            callback.message.message_id
        )
    )


    await state.set_state(
        AddFAQ.question
    )


    await callback.message.edit_text(

        "➕ <b>НОВЫЙ ВОПРОС</b>\n\n"

        "Отправьте вопрос, который "
        "может написать клиент.\n\n"

        "Например:\n"
        "<code>Сколько стоит доставка?</code>",

        reply_markup=back_main(),

        parse_mode="HTML",
    )


    await callback.answer()


@router.message(
    AddFAQ.question
)
async def faq_question_handler(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not message.text:
        return


    question = (
        message.text.strip()
    )


    await state.update_data(
        question=question
    )


    data = (
        await state.get_data()
    )


    await state.set_state(
        AddFAQ.answer
    )


    try:

        await bot.edit_message_text(

            chat_id=(
                message.chat.id
            ),

            message_id=(
                data[
                    "panel_message_id"
                ]
            ),

            text=(
                "✅ Вопрос:\n\n"
                f"<b>"
                f"{html.escape(question)}"
                f"</b>\n\n"
                "Теперь отправьте готовый ответ.\n\n"
                "Поддерживается всё: текст "
                "<b>с любым форматированием</b> "
                "(жирный, курсив, спойлер, ссылки, "
                "код и т.д.), фото, видео, GIF, "
                "документ, аудио, голосовое, "
                "видеокружок, стикер, альбом, "
                "локация, контакт и опрос.\n\n"
                "Форматирование и тип сообщения "
                "сохранятся как есть."
            ),

            reply_markup=back_main(),

            parse_mode="HTML",
        )

    except Exception:

        pass


    await delete_user_message(
        message
    )


ANSWER_TYPE_LABELS = {
    "text": "💬 Текст",
    "photo": "🖼 Фото",
    "video": "🎬 Видео",
    "animation": "🎞 GIF",
    "document": "📄 Документ",
    "audio": "🎵 Аудио",
    "voice": "🎤 Голосовое",
    "video_note": "⭕ Видеокружок",
    "sticker": "😀 Стикер",
    "media_group": "🖼 Альбом",
    "location": "📍 Локация",
    "venue": "🏢 Место",
    "contact": "👤 Контакт",
    "poll": "📊 Опрос",
    "dice": "🎲 Дайс",
}


def _entities_to_dicts(
    entities,
):

    if not entities:

        return []


    return [
        entity.model_dump(mode="json")
        for entity in entities
    ]


def _dicts_to_entities(
    dicts,
):

    if not dicts:

        return None


    return [
        MessageEntity(**item)
        for item in dicts
    ]


def _parse_entities_json(
    raw,
):

    if not raw:

        return None


    try:

        data = json.loads(raw)

    except (
        ValueError,
        TypeError,
    ):

        return None


    return _dicts_to_entities(data)


def _parse_payload_json(
    raw,
):

    if not raw:

        return {}


    try:

        data = json.loads(raw)

    except (
        ValueError,
        TypeError,
    ):

        return {}


    return data if isinstance(data, dict) else {}


def serialize_answer(
    message: Message,
):

    if message.photo:

        return {
            "type": "photo",
            "text": message.caption or "",
            "entities": _entities_to_dicts(
                message.caption_entities
            ),
            "file_id": (
                message.photo[-1].file_id
            ),
            "payload": {},
        }

    if message.video:

        return {
            "type": "video",
            "text": message.caption or "",
            "entities": _entities_to_dicts(
                message.caption_entities
            ),
            "file_id": message.video.file_id,
            "payload": {},
        }

    if message.animation:

        return {
            "type": "animation",
            "text": message.caption or "",
            "entities": _entities_to_dicts(
                message.caption_entities
            ),
            "file_id": (
                message.animation.file_id
            ),
            "payload": {},
        }

    if message.document:

        return {
            "type": "document",
            "text": message.caption or "",
            "entities": _entities_to_dicts(
                message.caption_entities
            ),
            "file_id": (
                message.document.file_id
            ),
            "payload": {},
        }

    if message.audio:

        return {
            "type": "audio",
            "text": message.caption or "",
            "entities": _entities_to_dicts(
                message.caption_entities
            ),
            "file_id": message.audio.file_id,
            "payload": {},
        }

    if message.voice:

        return {
            "type": "voice",
            "text": "",
            "entities": [],
            "file_id": message.voice.file_id,
            "payload": {},
        }

    if message.video_note:

        return {
            "type": "video_note",
            "text": "",
            "entities": [],
            "file_id": (
                message.video_note.file_id
            ),
            "payload": {},
        }

    if message.sticker:

        return {
            "type": "sticker",
            "text": "",
            "entities": [],
            "file_id": message.sticker.file_id,
            "payload": {},
        }

    if message.location:

        location = message.location

        return {
            "type": "location",
            "text": "",
            "entities": [],
            "file_id": "",
            "payload": {
                "latitude": location.latitude,
                "longitude": location.longitude,
            },
        }

    if message.venue:

        venue = message.venue

        return {
            "type": "venue",
            "text": "",
            "entities": [],
            "file_id": "",
            "payload": {
                "latitude": (
                    venue.location.latitude
                ),
                "longitude": (
                    venue.location.longitude
                ),
                "title": venue.title,
                "address": venue.address,
            },
        }

    if message.contact:

        contact = message.contact

        return {
            "type": "contact",
            "text": "",
            "entities": [],
            "file_id": "",
            "payload": {
                "phone_number": (
                    contact.phone_number
                ),
                "first_name": (
                    contact.first_name
                ),
                "last_name": (
                    contact.last_name or ""
                ),
                "vcard": contact.vcard or "",
            },
        }

    if message.poll:

        poll = message.poll

        options = [
            {
                "text": option.text,
                "entities": (
                    _entities_to_dicts(
                        option.text_entities
                    )
                ),
            }
            for option in poll.options
        ]

        return {
            "type": "poll",
            "text": "",
            "entities": [],
            "file_id": "",
            "payload": {
                "question": poll.question,
                "options": options,
                "is_anonymous": (
                    poll.is_anonymous
                ),
                "type": poll.type,
                "allow_multiple_answers": (
                    poll.allows_multiple_answers
                ),
            },
        }

    if message.dice:

        return {
            "type": "dice",
            "text": "",
            "entities": [],
            "file_id": "",
            "payload": {
                "emoji": message.dice.emoji,
            },
        }

    if message.text:

        return {
            "type": "text",
            "text": message.text,
            "entities": _entities_to_dicts(
                message.entities
            ),
            "file_id": "",
            "payload": {},
        }

    return None


def answer_preview_parts(
    item: dict,
):

    answer_type = (
        item.get("type")
        or item.get("answer_type")
        or "text"
    )


    label = (
        ANSWER_TYPE_LABELS.get(
            answer_type,
            "Сообщение",
        )
    )


    if answer_type == "media_group":

        payload = (
            item.get("payload")
            or {}
        )

        count = len(
            payload.get("items", [])
        )

        return (
            f"{label} ({count} шт.)",
            "",
        )


    text = (
        item.get("text")
        or item.get("answer")
        or ""
    )


    return (
        label,
        text,
    )


def format_answer_preview(
    item: dict,
) -> str:

    answer_type = (
        item.get("type")
        or item.get("answer_type")
        or "text"
    )


    label, text = (
        answer_preview_parts(item)
    )


    if answer_type == "text":

        if text:

            return (
                f"💬 {html.escape(text)}"
            )

        return label


    if text:

        return (
            f"{label}\n"
            f"💬 {html.escape(text)}"
        )


    return label


async def _finalize_faq(
    owner_id: int,
    data: dict,
    chat_id: int,
    spec: dict,
    bot: Bot,
    state: FSMContext,
    delete_msg: Message = None,
):

    question = data.get(
        "question",
        "",
    )

    panel_message_id = data.get(
        "panel_message_id"
    )


    await add_faq(

        owner_id=owner_id,

        question=question,

        answer=spec.get("text", ""),

        answer_type=spec["type"],

        answer_file_id=spec.get(
            "file_id",
            "",
        ),

        answer_entities=(
            json.dumps(
                spec.get("entities") or [],
                ensure_ascii=False,
            )
        ),

        answer_payload=(
            json.dumps(
                spec.get("payload") or {},
                ensure_ascii=False,
            )
        ),
    )


    await state.clear()


    preview = format_answer_preview(
        spec
    )


    try:

        await bot.edit_message_text(

            chat_id=chat_id,

            message_id=panel_message_id,

            text=(
                "✅ <b>ВОПРОС СОХРАНЁН</b>\n\n"

                f"❓ {html.escape(question)}\n\n"

                f"{preview}"
            ),

            reply_markup=(
                await build_main_markup(
                    owner_id
                )
            ),

            parse_mode="HTML",
        )

    except Exception:

        pass


    if delete_msg is not None:

        await delete_user_message(
            delete_msg
        )


_pending_albums = {}


async def _flush_album(
    key: tuple,
):

    await asyncio.sleep(2.5)


    buf = _pending_albums.pop(
        key,
        None,
    )


    if not buf or not buf["items"]:

        return


    spec = {
        "type": "media_group",
        "text": "",
        "entities": [],
        "file_id": "",
        "payload": {
            "items": buf["items"],
        },
    }


    await _finalize_faq(
        buf["owner_id"],
        buf["data"],
        buf["chat_id"],
        spec,
        buf["bot"],
        buf["state"],
        delete_msg=None,
    )


async def _buffer_album_item(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    spec = serialize_answer(
        message
    )


    if spec is None:

        return


    owner_id = message.from_user.id

    key = (
        owner_id,
        message.media_group_id,
    )


    buf = _pending_albums.get(key)


    if buf is None:

        data = await state.get_data()

        buf = {
            "items": [],
            "owner_id": owner_id,
            "data": data,
            "chat_id": message.chat.id,
            "bot": bot,
            "state": state,
            "task": None,
        }

        _pending_albums[key] = buf


    buf["items"].append(spec)


    if buf["task"] is not None:

        buf["task"].cancel()


    buf["task"] = asyncio.create_task(
        _flush_album(key)
    )


    await delete_user_message(
        message
    )


@router.message(
    AddFAQ.answer
)
async def faq_answer_handler(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if message.media_group_id:

        await _buffer_album_item(
            message,
            state,
            bot,
        )

        return


    spec = serialize_answer(
        message
    )


    if spec is None:

        try:

            await bot.send_message(
                message.chat.id,
                "⚠️ Такой тип сообщения не "
                "поддерживается как ответ.\n\n"
                "Отправьте текст, фото, видео, "
                "GIF, документ, аудио, голосовое, "
                "видеокружок, стикер, альбом, "
                "локацию, контакт или опрос.",
            )

        except Exception:

            pass


        return


    await _finalize_faq(
        message.from_user.id,
        await state.get_data(),
        message.chat.id,
        spec,
        bot,
        state,
        delete_msg=message,
    )


# =========================================================
# FAQ LIST / DELETE
# =========================================================

@router.callback_query(
    F.data == "faq_list"
)
async def faq_list_callback(
    callback: CallbackQuery,
):

    faqs = await get_faqs(
        callback.from_user.id
    )


    if not faqs:

        text = (
            "📚 <b>МОИ ВОПРОСЫ</b>\n\n"
            "Пока ничего не добавлено."
        )

    else:

        parts = [
            "📚 <b>МОИ ВОПРОСЫ</b>\n"
        ]


        for number, faq in enumerate(
            faqs[:10],
            start=1,
        ):

            question = (
                faq["question"][:100]
            )

            answer = (
                faq["answer"][:220]
            )


            faq_type = (
                faq.get("answer_type")
                or "text"
            )


            label = (
                ANSWER_TYPE_LABELS.get(
                    faq_type,
                    "Сообщение",
                )
            )


            if faq_type == "media_group":

                payload = (
                    _parse_payload_json(
                        faq.get(
                            "answer_payload"
                        )
                    )
                )

                count = len(
                    payload.get(
                        "items",
                        [],
                    )
                )

                answer_line = (
                    f"{label} ({count} шт.)"
                )

            elif faq_type == "text":

                answer_line = (
                    html.escape(answer)
                )

            else:

                answer_line = label

                if answer:

                    answer_line += (
                        f" — {html.escape(answer)}"
                    )


            parts.append(
                (
                    f"\n<b>{number}.</b> "
                    f"{html.escape(question)}\n"
                    f"→ {answer_line}"
                )
            )


        parts.append(
            "\n\nНажмите кнопку с вопросом, "
            "чтобы удалить его."
        )


        text = "".join(
            parts
        )


    await callback.message.edit_text(

        text,

        reply_markup=(
            faq_list_keyboard(
                faqs
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data.startswith(
        "faq_delete:"
    )
)
async def faq_delete_callback(
    callback: CallbackQuery,
):

    try:

        faq_id = int(
            callback.data.split(
                ":",
                1,
            )[1]
        )

    except ValueError:

        await callback.answer(
            "Ошибка",
            show_alert=True,
        )

        return


    await delete_faq(

        callback.from_user.id,

        faq_id,
    )


    faqs = await get_faqs(
        callback.from_user.id
    )


    text = (

        "✅ Запись удалена.\n\n"

        "📚 <b>МОИ ВОПРОСЫ</b>\n\n"
    )


    if not faqs:

        text += (
            "Пока ничего не добавлено."
        )

    else:

        for number, faq in enumerate(
            faqs[:10],
            start=1,
        ):

            text += (

                f"<b>{number}.</b> "

                f"{html.escape(faq['question'][:100])}\n"

                f"→ "

                f"{html.escape(faq['answer'][:220])}\n\n"
            )


    await callback.message.edit_text(

        text,

        reply_markup=(
            faq_list_keyboard(
                faqs
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer(
        "Удалено"
    )


# =========================================================
# PROFILE
# =========================================================

@router.callback_query(
    F.data == "profile"
)
async def profile_callback(
    callback: CallbackQuery,
):

    profile = await get_profile(
        callback.from_user.id
    )


    await callback.message.edit_text(

        profile_text(
            profile
        ),

        reply_markup=profile_menu(
            is_admin=is_admin(
                callback.from_user.id
            ),
            is_premium=(
                profile["plan"] == "premium"
            ),
            show_promo=bool(
                profile.get("show_promo", 1)
            ),
        ),

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data == "toggle_promo"
)
async def toggle_promo_callback(
    callback: CallbackQuery,
):

    profile = await get_profile(
        callback.from_user.id
    )


    if profile["plan"] != "premium":

        await callback.answer(
            "Только для Premium",
            show_alert=True,
        )

        return


    new_value = not bool(
        profile.get("show_promo", 1)
    )


    await set_show_promo(
        callback.from_user.id,
        new_value,
    )


    profile = await get_profile(
        callback.from_user.id
    )


    await callback.message.edit_text(

        profile_text(
            profile
        ),

        reply_markup=profile_menu(
            is_admin=is_admin(
                callback.from_user.id
            ),
            is_premium=True,
            show_promo=new_value,
        ),

        parse_mode="HTML",
    )


    await callback.answer(
        "Реклама: "
        + (
            "вкл"
            if new_value
            else "выкл"
        )
    )


PROFILE_LABELS = {

    "owner_name":
        "имя или роль",

    "age":
        "возраст",

    "gender":
        "пол",

    "topics":
        "темы владельца",

    "ai_description":
        "характеристику AI",

    "fallback_text":
        "запасной ответ",

    "fallback_text2":
        "второй запасной ответ",
}


@router.callback_query(
    F.data.startswith(
        "profile_edit:"
    )
)
async def profile_edit_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    field = callback.data.split(
        ":",
        1,
    )[1]


    if field not in PROFILE_LABELS:

        await callback.answer(
            "Ошибка",
            show_alert=True,
        )

        return


    await state.clear()


    await state.update_data(

        profile_field=field,

        panel_message_id=(
            callback.message.message_id
        ),
    )


    await state.set_state(
        ProfileEdit.value
    )


    await callback.message.edit_text(

        "✏️ Отправьте новое значение.\n\n"

        f"Редактируем: "
        f"<b>{PROFILE_LABELS[field]}</b>",

        reply_markup=back_main(),

        parse_mode="HTML",
    )


    await callback.answer()


@router.message(
    ProfileEdit.value
)
async def profile_value_handler(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not message.text:
        return


    data = await state.get_data()


    field = data.get(
        "profile_field"
    )


    panel_message_id = data.get(
        "panel_message_id"
    )


    if field not in PROFILE_LABELS:

        await state.clear()

        return


    await update_profile_field(

        message.from_user.id,

        field,

        message.text.strip(),
    )


    await state.clear()


    profile = await get_profile(
        message.from_user.id
    )


    await delete_user_message(
        message
    )


    try:

        await bot.edit_message_text(

            chat_id=(
                message.chat.id
            ),

            message_id=(
                panel_message_id
            ),

            text=profile_text(
                profile
            ),

            reply_markup=profile_menu(
                is_admin=is_admin(
                    message.from_user.id
                ),
                is_premium=(
                    profile["plan"] == "premium"
                ),
                show_promo=bool(
                    profile.get("show_promo", 1)
                ),
            ),

            parse_mode="HTML",
        )

    except Exception:

        pass


# =========================================================
# CHAT ROLES (PREMIUM)
# =========================================================

def chat_roles_text(
    chats: list,
):

    with_role = [
        chat
        for chat in chats
        if chat["role"]
    ]


    return (

        "🎭 <b>РОЛИ ЧАТОВ</b>\n\n"

        "Укажите, с кем и как общаться "
        "в конкретном чате.\n\n"

        "Например:\n"

        "<i>«Это моя любовь — говори с ней "
        "нежно, о любви, делай комплименты»</i>,\n"

        "<i>«Это друг — шути с ним»</i>,\n"

        "<i>«Это папа / мама»</i>.\n\n"

        f"🎭 С ролью: <b>{len(with_role)}</b>\n"

        f"💬 Всего чатов: <b>{len(chats)}</b>\n\n"

        "Нажми на чат, чтобы задать роль."
    )


async def render_chat_roles(
    owner_id: int,
):

    chats = (
        await get_chats_for_roles(
            owner_id
        )
    )


    return (

        chat_roles_text(
            chats
        ),

        chat_roles_keyboard(
            chats
        ),
    )


@router.callback_query(
    F.data == "chat_roles"
)
async def chat_roles_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.clear()


    text, keyboard = (
        await render_chat_roles(
            callback.from_user.id
        )
    )


    await callback.message.edit_text(

        text,

        reply_markup=keyboard,

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data.startswith(
        "chat_role_set:"
    )
)
async def chat_role_set_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    try:

        chat_id = int(
            callback.data.split(
                ":",
                1,
            )[1]
        )

    except ValueError:

        await callback.answer(
            "Ошибка ID"
        )

        return


    await state.clear()


    await state.update_data(

        role_chat_id=chat_id,

        panel_message_id=(
            callback.message.message_id
        ),
    )


    await state.set_state(
        ChatRole.value
    )


    await callback.message.edit_text(

        "🎭 <b>Роль для чата</b>\n\n"

        "Опиши, кто этот человек и как "
        "с ним общаться.\n\n"

        "Например:\n"

        "<i>Это моя любовь — говори нежно, "
        "о любви, делай комплименты.</i>\n\n"

        "Чтобы убрать роль, отправь "
        "<code>-</code>.",

        reply_markup=back_main(),

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data == "chat_role_manual"
)
async def chat_role_manual_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.clear()


    await state.update_data(

        panel_message_id=(
            callback.message.message_id
        ),
    )


    await state.set_state(
        ChatRole.chat_id
    )


    await callback.message.edit_text(

        "🎭 <b>Роль для чата</b>\n\n"

        "Отправь <b>ID чата</b> (число) или "
        "<b>@username</b> человека.\n\n"

        "Например:\n"

        "<code>123456789</code> или "
        "<code>@anna</code>",

        reply_markup=back_main(),

        parse_mode="HTML",
    )


    await callback.answer()


@router.message(
    ChatRole.chat_id
)
async def chat_role_chat_id_handler(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not message.text:

        return


    data = await state.get_data()

    panel_message_id = data.get(
        "panel_message_id"
    )


    raw = message.text.strip()


    chat_id = None


    if (
        raw.lstrip("-").isdigit()
    ):

        chat_id = int(
            raw
        )

    else:

        username = (
            raw.lstrip("@")
        )


        chats = (
            await get_chats_for_roles(
                message.from_user.id
            )
        )


        for chat in chats:

            if (
                chat["username"]
                and chat[
                    "username"
                ].lstrip("@").lower()
                == username.lower()
            ):

                chat_id = chat[
                    "chat_id"
                ]

                break


    await delete_user_message(
        message
    )


    if chat_id is None:

        try:

            await bot.edit_message_text(

                chat_id=(
                    message.chat.id
                ),

                message_id=(
                    panel_message_id
                ),

                text=(
                    "❌ Не нашёл такой чат.\n\n"

                    "Отправь числовой ID или "
                    "@username человека, "
                    "который уже писал боту."
                ),

                reply_markup=back_main(),

                parse_mode="HTML",
            )

        except Exception:

            pass


        return


    await state.update_data(
        role_chat_id=chat_id
    )


    await state.set_state(
        ChatRole.value
    )


    try:

        await bot.edit_message_text(

            chat_id=(
                message.chat.id
            ),

            message_id=(
                panel_message_id
            ),

            text=(

                "🎭 <b>Роль для чата</b>\n\n"

                f"Чат: <code>{chat_id}</code>\n\n"

                "Опиши, кто этот человек и "
                "как с ним общаться.\n\n"

                "Чтобы убрать роль, отправь "
                "<code>-</code>."
            ),

            reply_markup=back_main(),

            parse_mode="HTML",
        )

    except Exception:

        pass


@router.message(
    ChatRole.value
)
async def chat_role_value_handler(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not message.text:

        return


    data = await state.get_data()

    chat_id = data.get(
        "role_chat_id"
    )

    panel_message_id = data.get(
        "panel_message_id"
    )


    if chat_id is None:

        await state.clear()

        return


    role = message.text.strip()


    if role.lower() in {

        "-",
        "очистить",
        "clear",
        "нет",
        "удалить",
    }:

        role = ""


    if role:

        settings = (
            await get_global_settings()
        )

        profile = await get_profile(
            message.from_user.id
        )

        is_premium = (
            profile["plan"] == "premium"
        )

        max_roles = int(
            settings[
                "max_chat_roles"
                if is_premium
                else "free_chat_roles"
            ]
        )


        chat_row = (
            await get_chat_settings(
                message.from_user.id,
                chat_id,
            )
        )

        had_role = bool(
            chat_row
            and chat_row.get("role")
        )


        if not had_role:

            roles_count = (
                await count_chat_roles(
                    message.from_user.id
                )
            )


            if roles_count >= max_roles:

                await state.clear()


                await delete_user_message(
                    message
                )


                text, keyboard = (
                    await render_chat_roles(
                        message.from_user.id
                    )
                )


                limit_note = (
                    "Максимум: "
                    f"<b>{max_roles}</b> "
                    "ролей.\n\n"
                    "Уберите роль с другого "
                    "чата, чтобы добавить "
                    "новую.\n\n"
                )

                if not is_premium:

                    limit_note = (
                        f"На бесплатном тарифе "
                        f"доступно "
                        f"<b>{max_roles}</b> "
                        f"роль(ей).\n\n"
                        "⭐ С тарифом "
                        "<b>Premium</b> — до "
                        f"<b>{settings['max_chat_roles']}</b> "
                        "ролей.\n\n"
                    )


                try:

                    await bot.edit_message_text(

                        chat_id=(
                            message.chat.id
                        ),

                        message_id=(
                            panel_message_id
                        ),

                        text=(
                            "⛔ <b>Лимит ролей "
                            "достигнут</b>\n\n"

                            + limit_note

                            + text
                        ),

                        reply_markup=keyboard,

                        parse_mode="HTML",
                    )

                except Exception:

                    pass


                return


    await set_chat_role(

        message.from_user.id,

        chat_id,

        role,
    )


    await state.clear()


    await delete_user_message(
        message
    )


    text, keyboard = (
        await render_chat_roles(
            message.from_user.id
        )
    )


    saved = (
        "✅ <b>Роль сохранена</b>\n\n"
        if role
        else "✅ <b>Роль убрана</b>\n\n"
    )


    try:

        await bot.edit_message_text(

            chat_id=(
                message.chat.id
            ),

            message_id=(
                panel_message_id
            ),

            text=(
                saved + text
            ),

            reply_markup=keyboard,

            parse_mode="HTML",
        )

    except Exception:

        pass


# =========================================================
# PREMIUM / PAYMENT (TELEGRAM STARS)
# =========================================================

PREMIUM_PERIODS = {

    "week": {

        "days": 7,

        "title": "Premium 1 неделя",

        "price_key": "premium_price_week",
    },

    "month": {

        "days": 30,

        "title": "Premium 1 месяц",

        "price_key": "premium_price_month",
    },
}


async def build_premium_buy(
    callback: CallbackQuery,
):

    settings = (
        await get_global_settings()
    )


    week_price = int(
        settings[
            "premium_price_week"
        ]
    )

    month_price = int(
        settings[
            "premium_price_month"
        ]
    )


    manual_enabled = (
        settings[
            "manual_payment_enabled"
        ]
        == "1"
    )


    text = (

        "💎 <b>PREMIUM</b>\n\n"

        "Сравнение тарифов:\n\n"

        "🧠 <b>AI-ответов в день</b>\n"

        f"🆓 Free: {settings['free_ai_daily_limit']}\n"

        f"⭐ Premium: "
        f"{settings['premium_ai_daily_limit']}\n\n"

        "📚 <b>Вопросов-ответов (FAQ)</b>\n"

        f"🆓 Free: {settings['free_faq_limit']}\n"

        f"⭐ Premium: "
        f"{settings['premium_faq_limit']}\n\n"

        "🎭 <b>Ролей чатов</b>\n"

        f"🆓 Free: "
        f"{settings.get('free_chat_roles', '1')}\n"

        f"⭐ Premium: "
        f"{settings['max_chat_roles']}\n\n"

        "📣 <b>Реклама в запасном ответе</b>\n"

        "🆓 Free: показывается\n"

        "⭐ Premium: можно отключить\n\n"

        "Также в Premium: приоритет в "
        "обработке и больше языков.\n\n"

        "—\n\n"

        f"⭐ Неделя — <b>{week_price}⭐</b>\n"

        f"⭐ Месяц — <b>{month_price}⭐</b>\n\n"

        "Оплата Telegram-звёздами. "
        "Premium активируется сразу и "
        "действует весь срок."
    )


    await callback.message.edit_text(

        text,

        reply_markup=(
            premium_buy_keyboard(

                week_price,

                month_price,

                manual_enabled,
            )
        ),

        parse_mode="HTML",
    )


@router.callback_query(
    F.data == "premium_buy"
)
async def premium_buy_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.clear()


    await build_premium_buy(
        callback
    )


    await callback.answer()


@router.callback_query(
    F.data.startswith(
        "buy_premium:"
    )
)
async def buy_premium_callback(
    callback: CallbackQuery,
    bot: Bot,
):

    period = callback.data.split(
        ":",
        1,
    )[1]


    info = (
        PREMIUM_PERIODS.get(
            period
        )
    )


    if not info:

        await callback.answer(
            "Ошибка",
            show_alert=True,
        )

        return


    settings = (
        await get_global_settings()
    )


    price = int(
        settings[
            info["price_key"]
        ]
    )


    if price < 1:

        await callback.answer(
            "Цена не настроена",
            show_alert=True,
        )

        return


    await bot.send_invoice(

        chat_id=(
            callback.from_user.id
        ),

        title=(
            info["title"]
        ),

        description=(
            "Активация Premium-тарифа"
        ),

        payload=(
            f"premium:{period}"
        ),

        currency="XTR",

        prices=[

            LabeledPrice(

                label=(
                    info["title"]
                ),

                amount=price,
            )
        ],
    )


    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout_handler(
    query: PreCheckoutQuery,
):

    await query.answer(
        ok=True
    )


@router.message(
    F.successful_payment
)
async def successful_payment_handler(
    message: Message,
):

    payment = (
        message.successful_payment
    )


    payload = (
        payment.invoice_payload
        or ""
    )


    info = None


    if payload.startswith(
        "premium:"
    ):

        info = (
            PREMIUM_PERIODS.get(
                payload.split(
                    ":",
                    1,
                )[1]
            )
        )


    if not info:

        await message.answer(
            "✅ Оплата получена."
        )

        return


    await set_premium(

        message.from_user.id,

        days=info[
            "days"
        ],
    )


    await message.answer(

        "🎉 <b>Premium активирован!</b>\n\n"

        f"Тариф: <b>{info['title']}</b>\n"

        f"Оплачено: "
        f"<b>{payment.total_amount}⭐</b>\n\n"

        "Спасибо за поддержку ❤️",

        reply_markup=(
            await build_main_markup(
                message.from_user.id
            )
        ),

        parse_mode="HTML",
    )


@router.callback_query(
    F.data == "manual_payment"
)
async def manual_payment_callback(
    callback: CallbackQuery,
):

    settings = (
        await get_global_settings()
    )


    text = (
        settings[
            "manual_payment_text"
        ]
        or ""
    )


    if not text.strip():

        await callback.answer(
            "Способ не настроен",
            show_alert=True,
        )

        return


    await callback.message.edit_text(

        "💳 <b>Другой способ оплаты</b>\n\n"

        f"{html.escape(text)}",

        reply_markup=(
            manual_payment_keyboard()
        ),

        parse_mode="HTML",
    )


    await callback.answer()


# =========================================================
# AI ON/OFF + LIMIT
# =========================================================

@router.callback_query(
    F.data == "ai_toggle"
)
async def ai_toggle_callback(
    callback: CallbackQuery,
):

    enabled = await toggle_ai(
        callback.from_user.id
    )


    await callback.message.edit_text(

        (
            "🧠 <b>AI включён</b>\n\n"

            "Сначала бот ищет готовый FAQ. "
            "AI используется только если "
            "готового ответа нет."
        )

        if enabled

        else

        (
            "🧠 <b>AI выключен</b>\n\n"

            "Теперь бот использует только "
            "готовые FAQ-ответы."
        ),

        reply_markup=(
            await build_main_markup(
                callback.from_user.id
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data == "my_ai_limit"
)
async def my_ai_limit_callback(
    callback: CallbackQuery,
):

    quota = (
        await get_user_quota_status(
            callback.from_user.id
        )
    )


    plan = (
        "⭐ Premium"
        if quota["plan"] == "premium"
        else
        "🆓 Free"
    )


    await callback.message.edit_text(

        "📊 <b>МОЙ AI-ЛИМИТ</b>\n\n"

        f"Тариф: <b>{plan}</b>\n\n"

        f"Использовано сегодня: "
        f"<b>{quota['used']}/{quota['limit']}</b>\n"

        f"Осталось: "
        f"<b>{quota['remaining']}</b>\n\n"

        "FAQ не расходуют AI-лимит.\n"

        "Если один AI-провайдер не работает "
        "и бот переключился на другой, "
        "успешный ответ всё равно считается "
        "как один AI-ответ.",

        reply_markup=back_main(),

        parse_mode="HTML",
    )


    await callback.answer()


# =========================================================
# SETTINGS
# =========================================================

@router.callback_query(
    F.data == "settings"
)
async def settings_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.clear()


    text, prefs = await settings_text(
        callback.from_user.id
    )


    await callback.message.edit_text(

        text,

        reply_markup=(
            settings_menu(
                prefs
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data == "settings_autoreply"
)
async def settings_autoreply_callback(
    callback: CallbackQuery,
):

    await toggle_autoreply(
        callback.from_user.id
    )


    text, prefs = await settings_text(
        callback.from_user.id
    )


    await callback.message.edit_text(

        text,

        reply_markup=(
            settings_menu(
                prefs
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer(
        "Статус изменён"
    )


# =========================================================
# LANGUAGES
# =========================================================

@router.callback_query(
    F.data == "settings_languages"
)
async def settings_languages_callback(
    callback: CallbackQuery,
):

    prefs = await get_preferences(
        callback.from_user.id
    )


    profile = await get_profile(
        callback.from_user.id
    )


    languages = (
        get_allowed_languages(
            prefs,
            profile["plan"],
        )
    )


    text = (

        "🌍 <b>ЯЗЫКИ</b>\n\n"

        f"Основной: "
        f"<b>{html.escape(prefs['primary_language'])}</b>\n"

        f"Второй: "
        f"<b>{html.escape(prefs['secondary_language'])}</b>\n\n"

        f"Активные:\n"

        f"<b>"
        f"{html.escape(', '.join(languages))}"
        f"</b>\n\n"
    )


    if profile["plan"] == "free":

        text += (

            "🆓 Free: максимум 2 языка.\n"

            "Можно заменить Русский и English "
            "на любые два нужных языка."
        )

    else:

        extras = (
            prefs[
                "extra_languages"
            ]
            or "не добавлены"
        )


        text += (

            "⭐ Premium: дополнительные языки:\n"

            f"<b>"
            f"{html.escape(extras)}"
            f"</b>"
        )


    await callback.message.edit_text(

        text,

        reply_markup=(
            languages_menu(
                profile["plan"]
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data == "premium_languages_info"
)
async def premium_languages_info(
    callback: CallbackQuery,
):

    await callback.answer(

        "Free использует максимум 2 языка. "
        "В Premium можно добавить дополнительные.",

        show_alert=True,
    )


@router.callback_query(
    F.data.startswith(
        "pref_edit:"
    )
)
async def preference_edit_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    field = callback.data.split(
        ":",
        1,
    )[1]


    allowed = {

        "primary_language",
        "secondary_language",
        "extra_languages",
        "timezone",
    }


    if field not in allowed:

        await callback.answer(
            "Ошибка",
            show_alert=True,
        )

        return


    profile = await get_profile(
        callback.from_user.id
    )


    if (
        field == "extra_languages"
        and profile["plan"] != "premium"
    ):

        await callback.answer(

            "Дополнительные языки "
            "доступны только Premium.",

            show_alert=True,
        )

        return


    await state.clear()


    await state.update_data(

        preference_field=field,

        panel_message_id=(
            callback.message.message_id
        ),
    )


    await state.set_state(
        PreferenceEdit.value
    )


    if field == "primary_language":

        instruction = (

            "🌍 Отправьте основной язык.\n\n"

            "Например:\n"

            "<code>Русский</code>\n"

            "<code>Тоҷикӣ</code>"
        )


    elif field == "secondary_language":

        instruction = (

            "🌍 Отправьте второй язык.\n\n"

            "Например:\n"

            "<code>English</code>"
        )


    elif field == "extra_languages":

        instruction = (

            "⭐ Отправьте дополнительные языки "
            "через запятую.\n\n"

            "Например:\n"

            "<code>"
            "Тоҷикӣ, Türkçe, العربية"
            "</code>"
        )


    else:

        instruction = (

            "🕐 Отправьте часовой пояс IANA.\n\n"

            "Например:\n"

            "<code>Asia/Dushanbe</code>\n"

            "<code>Europe/Moscow</code>"
        )


    await callback.message.edit_text(

        instruction,

        reply_markup=back_main(),

        parse_mode="HTML",
    )


    await callback.answer()


@router.message(
    PreferenceEdit.value
)
async def preference_value_handler(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not message.text:
        return


    value = (
        message.text.strip()
    )


    data = await state.get_data()


    field = data.get(
        "preference_field"
    )


    panel_message_id = data.get(
        "panel_message_id"
    )


    # =====================================
    # SCHEDULE RANGE
    # =====================================

    if field == "schedule_range":

        cleaned = (

            value
            .replace(" ", "")
            .replace("–", "-")
        )


        parts = cleaned.split(
            "-"
        )


        if len(parts) != 2:

            await message.answer(

                "❌ Используйте формат:\n"

                "09:00-18:00"
            )

            return


        start_time = (
            parts[0]
        )

        end_time = (
            parts[1]
        )


        if (
            not validate_time(
                start_time
            )

            or

            not validate_time(
                end_time
            )
        ):

            await message.answer(

                "❌ Некорректное время.\n"

                "Пример: 09:00-18:00"
            )

            return


        await set_preference(

            message.from_user.id,

            "schedule_start",

            start_time,
        )


        await set_preference(

            message.from_user.id,

            "schedule_end",

            end_time,
        )


        await state.clear()


        await delete_user_message(
            message
        )


        prefs = await get_preferences(
            message.from_user.id
        )


        try:

            await bot.edit_message_text(

                chat_id=(
                    message.chat.id
                ),

                message_id=(
                    panel_message_id
                ),

                text=(

                    "✅ <b>График сохранён</b>\n\n"

                    f"{start_time} – {end_time}\n"

                    f"{html.escape(prefs['timezone'])}"
                ),

                reply_markup=(
                    schedule_menu(
                        prefs
                    )
                ),

                parse_mode="HTML",
            )

        except Exception:

            pass


        return


    # =====================================
    # TIMEZONE MANUAL
    # =====================================

    if field == "timezone":

        if not validate_timezone(
            value
        ):

            await message.answer(

                "❌ Часовой пояс не найден.\n"

                "Пример: Asia/Dushanbe"
            )

            return


    if field not in {

        "primary_language",
        "secondary_language",
        "extra_languages",
        "timezone",

    }:

        await state.clear()

        return


    await set_preference(

        message.from_user.id,

        field,

        value,
    )


    await state.clear()


    await delete_user_message(
        message
    )


    text, prefs = (
        await settings_text(
            message.from_user.id
        )
    )


    try:

        await bot.edit_message_text(

            chat_id=(
                message.chat.id
            ),

            message_id=(
                panel_message_id
            ),

            text=(

                "✅ <b>Настройка сохранена</b>\n\n"

                + text
            ),

            reply_markup=(
                settings_menu(
                    prefs
                )
            ),

            parse_mode="HTML",
        )

    except Exception:

        pass


# =========================================================
# TIMEZONE
# =========================================================

@router.callback_query(
    F.data == "settings_timezone"
)
async def settings_timezone_callback(
    callback: CallbackQuery,
):

    prefs = await get_preferences(
        callback.from_user.id
    )


    await callback.message.edit_text(

        "🕐 <b>ЧАСОВОЙ ПОЯС</b>\n\n"

        f"Сейчас: "
        f"<b>{html.escape(prefs['timezone'])}</b>\n\n"

        "Выберите готовый вариант "
        "или введите вручную.",

        reply_markup=timezone_menu(),

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data.startswith(
        "timezone:"
    )
)
async def timezone_set_callback(
    callback: CallbackQuery,
):

    timezone_name = (
        callback.data.split(
            ":",
            1,
        )[1]
    )


    if not validate_timezone(
        timezone_name
    ):

        await callback.answer(

            "Некорректный часовой пояс",

            show_alert=True,
        )

        return


    await set_preference(

        callback.from_user.id,

        "timezone",

        timezone_name,
    )


    text, prefs = await settings_text(
        callback.from_user.id
    )


    await callback.message.edit_text(

        text,

        reply_markup=(
            settings_menu(
                prefs
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer(
        "Часовой пояс сохранён"
    )


# =========================================================
# SCHEDULE
# =========================================================

@router.callback_query(
    F.data == "settings_schedule"
)
async def settings_schedule_callback(
    callback: CallbackQuery,
):

    prefs = await get_preferences(
        callback.from_user.id
    )


    status = (
        "🟢 Включён"
        if prefs[
            "schedule_enabled"
        ]
        else
        "⚪ Выключен"
    )


    await callback.message.edit_text(

        "📅 <b>ГРАФИК РАБОТЫ</b>\n\n"

        f"Статус: "
        f"<b>{status}</b>\n\n"

        f"Время: "
        f"<b>"
        f"{prefs['schedule_start']} – "
        f"{prefs['schedule_end']}"
        f"</b>\n"

        f"Часовой пояс: "
        f"<b>{html.escape(prefs['timezone'])}</b>\n\n"

        "Когда график включён, вне этого "
        "времени автоответчик полностью молчит.",

        reply_markup=(
            schedule_menu(
                prefs
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data == "schedule_toggle"
)
async def schedule_toggle_callback(
    callback: CallbackQuery,
):

    await toggle_schedule(
        callback.from_user.id
    )


    prefs = await get_preferences(
        callback.from_user.id
    )


    await callback.message.edit_text(

        "📅 <b>ГРАФИК РАБОТЫ</b>\n\n"

        f"Время: "
        f"<b>"
        f"{prefs['schedule_start']} – "
        f"{prefs['schedule_end']}"
        f"</b>\n"

        f"Часовой пояс: "
        f"<b>{html.escape(prefs['timezone'])}</b>",

        reply_markup=(
            schedule_menu(
                prefs
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer(
        "Статус графика изменён"
    )


@router.callback_query(
    F.data == "schedule_set_time"
)
async def schedule_set_time_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.clear()


    await state.update_data(

        preference_field=(
            "schedule_range"
        ),

        panel_message_id=(
            callback.message.message_id
        ),
    )


    await state.set_state(
        PreferenceEdit.value
    )


    await callback.message.edit_text(

        "🕐 Отправьте график в формате:\n\n"

        "<code>09:00-18:00</code>\n\n"

        "Ночной график тоже можно:\n"

        "<code>20:00-08:00</code>",

        reply_markup=back_main(),

        parse_mode="HTML",
    )


    await callback.answer()


# =========================================================
# BUSINESS STATUS
# =========================================================

@router.callback_query(
    F.data == "business_status"
)
async def business_status_callback(
    callback: CallbackQuery,
):

    connections = (
        await get_connections(
            callback.from_user.id
        )
    )


    enabled = [

        item

        for item in connections

        if item[
            "enabled"
        ]
    ]


    if enabled:

        text = (

            "🔗 <b>TELEGRAM BUSINESS</b>\n\n"

            "✅ Подключение активно.\n\n"

            f"Активных подключений: "
            f"<b>{len(enabled)}</b>\n\n"

            "В управляемом личном чате Telegram "
            "показывает владельцу кнопку "
            "<b>Manage Bot</b>. Через неё можно "
            "открыть управление конкретным диалогом."
        )

    else:

        text = (

            "🔗 <b>TELEGRAM BUSINESS</b>\n\n"

            "❌ Активное подключение пока "
            "не обнаружено."
        )


    await callback.message.edit_text(

        text,

        reply_markup=back_main(),

        parse_mode="HTML",
    )


    await callback.answer()


# =========================================================
# CHAT ON/OFF
# =========================================================

@router.callback_query(
    F.data.startswith(
        "chat_toggle:"
    )
)
async def chat_toggle_callback(
    callback: CallbackQuery,
):

    try:

        chat_id = int(
            callback.data.split(
                ":",
                1,
            )[1]
        )

    except ValueError:

        await callback.answer(
            "Ошибка",
            show_alert=True,
        )

        return


    enabled = await toggle_chat(

        callback.from_user.id,

        chat_id,
    )


    if enabled is None:

        await callback.answer(

            "Этот Business-чат "
            "не найден.",

            show_alert=True,
        )

        return


    chat_settings = (
        await get_chat_settings(

            callback.from_user.id,

            chat_id,
        )
    )


    peer_name = (

        chat_settings[
            "peer_name"
        ]

        or (

            f"@{chat_settings['username']}"

            if chat_settings[
                "username"
            ]

            else
            f"ID {chat_id}"
        )
    )


    await callback.message.edit_text(

        "💬 <b>УПРАВЛЕНИЕ ДИАЛОГОМ</b>\n\n"

        f"Клиент:\n"

        f"<b>{html.escape(peer_name)}</b>\n\n"

        f"Автоответчик:\n"

        f"<b>"
        f"{'🟢 Включён' if enabled else '🔴 Выключен'}"
        f"</b>",

        reply_markup=(
            chat_manage_menu(
                chat_id,
                enabled,
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer(

        "Включено"
        if enabled
        else
        "Выключено"
    )


# =========================================================
# ADMIN
# =========================================================

async def deny_admin(
    callback: CallbackQuery,
):

    await callback.answer(

        "Нет доступа.",

        show_alert=True,
    )


@router.message(
    Command("admin")
)
async def admin_command(
    message: Message,
):

    if not is_admin(
        message.from_user.id
    ):

        return


    settings = (
        await get_global_settings()
    )


    await message.answer(

        await build_admin_text(),

        reply_markup=(
            admin_menu(
                settings[
                    "ai_global_enabled"
                ]
                == "1"
            )
        ),

        parse_mode="HTML",
    )


@router.callback_query(
    F.data == "admin"
)
async def admin_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    await state.clear()


    settings = (
        await get_global_settings()
    )


    await callback.message.edit_text(

        await build_admin_text(),

        reply_markup=(
            admin_menu(
                settings[
                    "ai_global_enabled"
                ]
                == "1"
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data == "admin_stats"
)
async def admin_stats_callback(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    await callback.message.edit_text(

        await build_admin_text(),

        reply_markup=admin_back(),

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data == "admin_ai_toggle"
)
async def admin_ai_toggle_callback(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    await toggle_global_ai()


    settings = (
        await get_global_settings()
    )


    await callback.message.edit_text(

        await build_admin_text(),

        reply_markup=(
            admin_menu(
                settings[
                    "ai_global_enabled"
                ]
                == "1"
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer(
        "AI-статус изменён"
    )


@router.callback_query(
    F.data == "admin_premium"
)
async def admin_premium_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    await state.clear()


    settings = (
        await get_global_settings()
    )


    await callback.message.edit_text(

        build_admin_premium_text(
            settings
        ),

        reply_markup=(
            admin_premium_menu(settings)
        ),

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data == "admin_manual_pay_toggle"
)
async def admin_manual_pay_toggle_callback(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    settings = (
        await get_global_settings()
    )


    new_value = (
        "0"
        if settings.get(
            "manual_payment_enabled"
        )
        == "1"
        else "1"
    )


    await set_global_setting(
        "manual_payment_enabled",
        new_value,
    )


    settings = (
        await get_global_settings()
    )


    await callback.message.edit_text(

        build_admin_premium_text(
            settings
        ),

        reply_markup=(
            admin_premium_menu(settings)
        ),

        parse_mode="HTML",
    )


    await callback.answer(
        "Ручной способ обновлён"
    )


@router.callback_query(
    F.data == "admin_broadcast"
)
async def admin_broadcast_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    await state.clear()


    await state.update_data(
        panel_message_id=(
            callback.message.message_id
        )
    )


    await state.set_state(
        Broadcast.waiting
    )


    await callback.message.edit_text(

        "📢 <b>РАССЫЛКА</b>\n\n"

        "Отправьте сообщение для "
        "рассылки всем пользователям.\n\n"

        "Поддерживаются:\n"
        "• текст\n"
        "• фото / видео / аудио\n"
        "• документы\n"
        "• пересланные сообщения\n\n"

        "Бот скопирует его каждому "
        "пользователю от своего имени.\n\n"

        "Для отмены отправьте "
        "<code>отмена</code>.",

        reply_markup=admin_back(),

        parse_mode="HTML",
    )


    await callback.answer()


@router.message(
    Broadcast.waiting
)
async def broadcast_message_handler(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not is_admin(
        message.from_user.id
    ):

        await state.clear()

        return


    if (
        message.text
        and message.text.strip().lower()
        in {
            "отмена",
            "cancel",
            "-",
        }
    ):

        await state.clear()

        await message.answer(
            "❌ Рассылка отменена."
        )

        return


    if message.forward_origin is None:

        if (
            message.text is None
            and message.caption is None
            and message.document is None
            and message.photo is None
            and message.video is None
            and message.audio is None
            and message.voice is None
            and message.animation is None
            and message.video_note is None
            and message.sticker is None
        ):

            await message.answer(
                "❌ Такой тип сообщения "
                "не поддерживается."
            )

            return


    user_ids = (
        await get_all_user_ids()
    )


    total = len(user_ids)


    settings = (
        await get_global_settings()
    )


    try:

        interval = float(
            settings.get(
                "broadcast_interval",
                "1",
            )
        )

    except ValueError:

        interval = 1.0


    if interval < 0:

        interval = 1.0


    await state.update_data(

        broadcast_chat_id=(
            message.chat.id
        ),

        broadcast_message_id=(
            message.message_id
        ),

        broadcast_interval=interval,

    )


    await state.set_state(
        Broadcast.confirm
    )


    await message.answer(

        "📢 <b>ПОДТВЕРЖДЕНИЕ РАССЫЛКИ</b>\n\n"

        f"Получателей: <b>{total}</b>\n"

        f"Интервал между отправками: "
        f"<b>{interval}с</b>\n\n"

        "Сообщение выше будет скопировано "
        "каждому пользователю.\n\n"

        "Отправить?",

        reply_markup=(
            broadcast_confirm_keyboard()
        ),

        parse_mode="HTML",
    )


@router.callback_query(
    F.data == "broadcast_cancel"
)
async def broadcast_cancel_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    await state.clear()


    await callback.message.edit_text(
        "❌ Рассылка отменена.",
        reply_markup=admin_back(),
    )


    await callback.answer()


@router.callback_query(
    F.data == "broadcast_confirm"
)
async def broadcast_confirm_callback(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    data = await state.get_data()


    from_chat_id = data.get(
        "broadcast_chat_id"
    )

    from_message_id = data.get(
        "broadcast_message_id"
    )

    interval = data.get(
        "broadcast_interval",
        1.0,
    )


    if from_message_id is None:

        await state.clear()

        await callback.answer(
            "Сообщение не найдено",
            show_alert=True,
        )

        return


    await state.clear()


    await callback.answer()


    user_ids = (
        await get_all_user_ids()
    )


    total = len(user_ids)


    status_message = (
        await callback.message.edit_text(
            f"📢 Рассылка начата: "
            f"<b>{total}</b> получателей…"
        )
    )


    delivered = 0
    failed = 0


    for index, user_id in enumerate(
        user_ids
    ):

        try:

            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=from_chat_id,
                message_id=from_message_id,
            )

            delivered += 1

        except Exception:

            failed += 1


        if interval > 0:

            await asyncio.sleep(
                interval
            )


        if (index + 1) % 25 == 0:

            try:

                await status_message.edit_text(
                    f"📢 Идёт рассылка: "
                    f"<b>{index + 1}</b>/"
                    f"<b>{total}</b>…"
                )

            except Exception:

                pass


    try:

        await status_message.edit_text(
            "✅ <b>Рассылка завершена</b>\n\n"
            f"📨 Доставлено: <b>{delivered}</b>\n"
            f"⚠️ Ошибок: <b>{failed}</b>\n"
            f"👥 Всего: <b>{total}</b>",
            parse_mode="HTML",
        )

    except Exception:

        pass


# =========================================================
# GUIDE (ИНСТРУКЦИЯ)
# =========================================================

def guide_preview(
    message: Message,
) -> str:

    text = (
        message.text
        or message.caption
        or ""
    )


    text = text.strip()


    if text:

        return text[:60]


    if message.photo:
        return "🖼 Фото"

    if message.video:
        return "🎬 Видео"

    if message.animation:
        return "🎞 GIF"

    if message.document:
        return "📄 Документ"

    if message.audio:
        return "🎵 Аудио"

    if message.voice:
        return "🎤 Голосовое"

    if message.video_note:
        return "⭕ Видеокружок"

    if message.sticker:
        return "😀 Стикер"


    return "Сообщение"


async def build_admin_guide_panel():

    messages = (
        await get_guide_messages()
    )


    total = len(messages)


    text = (
        "📖 <b>ИНСТРУКЦИЯ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ</b>\n\n"
        f"Сообщений: <b>{total}</b>\n\n"
        "Пользователи видят их в "
        "«Настройки → 📖 Инструкция».\n\n"
        "Добавляйте любые сообщения: текст, "
        "фото, видео, документы и т.д. "
        "Они отправляются в том же виде."
    )


    return (
        text,
        admin_guide_keyboard(
            messages
        ),
    )


@router.callback_query(
    F.data == "guide_view"
)
async def guide_view_callback(
    callback: CallbackQuery,
    bot: Bot,
):

    messages = (
        await get_guide_messages()
    )


    if not messages:

        await callback.answer(
            "Инструкция пока пустая.",
            show_alert=True,
        )

        return


    await callback.answer()


    for item in messages:

        try:

            await bot.copy_message(
                chat_id=(
                    callback.from_user.id
                ),
                from_chat_id=(
                    item["chat_id"]
                ),
                message_id=(
                    item["message_id"]
                ),
            )

        except Exception as error:

            logger.warning(
                "Guide send failed "
                "(id=%s): %s",
                item["id"],
                error,
            )


@router.callback_query(
    F.data == "admin_guide"
)
async def admin_guide_callback(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    text, keyboard = (
        await build_admin_guide_panel()
    )


    try:

        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    except Exception:

        await callback.message.answer(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )


    await callback.answer()


@router.callback_query(
    F.data == "guide_add"
)
async def guide_add_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    await state.set_state(
        Guide.waiting
    )


    await callback.message.answer(
        "📖 <b>ДОБАВЛЕНИЕ ИНСТРУКЦИИ</b>\n\n"
        "Отправляйте сообщения по одному — "
        "текст, фото, видео, документы и т.д.\n\n"
        "Каждое сохранится и будет показано "
        "пользователям в том же виде.\n\n"
        "Когда закончите, нажмите "
        "«✅ Готово».",
        reply_markup=(
            guide_adding_keyboard()
        ),
        parse_mode="HTML",
    )


    await callback.answer()


@router.message(
    Guide.waiting
)
async def guide_adding_handler(
    message: Message,
    bot: Bot,
    state: FSMContext,
):

    if not is_admin(
        message.from_user.id
    ):

        return


    if message.content_type == (
        ContentType.TEXT
    ) and (
        message.text
        or ""
    ).strip().lower() in (
        "готово",
        "стоп",
        "/stop",
    ):

        await guide_finish(
            message,
            state,
        )

        return


    preview = guide_preview(
        message
    )


    await add_guide_message(
        message.chat.id,
        message.message_id,
        preview,
    )


    try:

        await bot.send_message(
            message.chat.id,
            f"✅ Добавлено: {preview}",
        )

    except Exception:

        pass


async def guide_finish(
    message: Message,
    state: FSMContext = None,
):

    if state is not None:

        await state.clear()


    text, keyboard = (
        await build_admin_guide_panel()
    )


    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.callback_query(
    F.data == "guide_done"
)
async def guide_done_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    await state.clear()


    text, keyboard = (
        await build_admin_guide_panel()
    )


    try:

        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    except Exception:

        await callback.message.answer(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )


    await callback.answer(
        "Инструкция обновлена."
    )


@router.callback_query(
    F.data.startswith(
        "guide_delete:"
    )
)
async def guide_delete_callback(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    try:

        guide_id = int(
            callback.data.split(
                ":",
                1,
            )[1]
        )

    except ValueError:

        await callback.answer()

        return


    await delete_guide_message(
        guide_id
    )


    text, keyboard = (
        await build_admin_guide_panel()
    )


    try:

        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    except Exception:

        pass


    await callback.answer(
        "Удалено."
    )


@router.callback_query(
    F.data == "guide_clear"
)
async def guide_clear_callback(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    await clear_guide_messages()


    text, keyboard = (
        await build_admin_guide_panel()
    )


    try:

        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    except Exception:

        pass


    await callback.answer(
        "Инструкция очищена."
    )


ADMIN_EDIT_LABELS = {

    "free_ai_daily_limit":
        "дневной AI-лимит Free",

    "premium_ai_daily_limit":
        "дневной AI-лимит Premium",

    "blocked_topics":
        "запрещённые темы AI",

    "blocked_reply":
        "ответ на запрещённую тему",

    "premium_price_week":
        "цена Premium за 1 неделю (⭐)",

    "premium_price_month":
        "цена Premium за 1 месяц (⭐)",

    "free_faq_limit":
        "лимит FAQ (Free)",

    "premium_faq_limit":
        "лимит FAQ (Premium)",

    "max_chat_roles":
        "максимум ролей чатов (Premium)",

    "free_chat_roles":
        "количество ролей чатов (Free)",

    "manual_payment_text":
        "инструкцию ручного способа оплаты",

    "promo_signature_text":
        "рекламную подпись (используйте {link} для реф-ссылки)",

    "broadcast_interval":
        "интервал рассылки в секундах",
}


@router.callback_query(
    F.data.startswith(
        "admin_edit:"
    )
)
async def admin_edit_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    key = callback.data.split(
        ":",
        1,
    )[1]


    if key not in ADMIN_EDIT_LABELS:

        await callback.answer(
            "Ошибка",
            show_alert=True,
        )

        return


    settings = (
        await get_global_settings()
    )


    await state.clear()


    await state.update_data(

        admin_setting=key,

        panel_message_id=(
            callback.message.message_id
        ),
    )


    await state.set_state(
        AdminEdit.value
    )


    current = (
        settings[key]
    )


    if key == "blocked_topics":

        hint = (

            "\n\nВведите темы через запятую.\n"

            "Например:\n"

            "<code>"
            "казино, ставки, политика"
            "</code>\n\n"

            "Для очистки отправьте "

            "<code>очистить</code>."
        )

    else:

        hint = ""


    await callback.message.edit_text(

        "👑 <b>ИЗМЕНЕНИЕ НАСТРОЙКИ</b>\n\n"

        f"{ADMIN_EDIT_LABELS[key]}\n\n"

        f"Сейчас:\n"

        f"<code>"
        f"{html.escape(str(current))}"
        f"</code>"

        f"{hint}\n\n"

        "Отправьте новое значение.",

        reply_markup=admin_back(),

        parse_mode="HTML",
    )


    await callback.answer()


@router.message(
    AdminEdit.value
)
async def admin_edit_value_handler(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not is_admin(
        message.from_user.id
    ):

        await state.clear()

        return


    if not message.text:

        return


    data = await state.get_data()


    key = data.get(
        "admin_setting"
    )


    panel_message_id = data.get(
        "panel_message_id"
    )


    if key not in ADMIN_EDIT_LABELS:

        await state.clear()

        return


    value = (
        message.text.strip()
    )


    if key == "broadcast_interval":

        try:

            interval_value = float(value)

        except ValueError:

            interval_value = -1.0

        if interval_value < 0:

            await message.answer(
                "❌ Отправьте число секунд "
                "(например 1 или 0.5)."
            )

            return


    if key in {

        "free_ai_daily_limit",
        "premium_ai_daily_limit",

        "premium_price_week",
        "premium_price_month",

        "free_faq_limit",
        "premium_faq_limit",

        "max_chat_roles",
        "free_chat_roles",

    }:

        if (
            not value.isdigit()
            or int(value) < 0
        ):

            await message.answer(
                "❌ Отправьте целое число."
            )

            return


    if (
        key in {
            "blocked_topics",
            "manual_payment_text",
            "promo_signature_text",
        }

        and

        value.lower() in {

            "очистить",
            "clear",
            "нет",
            "-",
        }
    ):

        value = ""


    await set_global_setting(
        key,
        value,
    )


    await state.clear()


    await delete_user_message(
        message
    )


    settings = (
        await get_global_settings()
    )


    premium_keys = {
        "premium_price_week",
        "premium_price_month",
        "free_faq_limit",
        "premium_faq_limit",
        "max_chat_roles",
        "free_chat_roles",
        "manual_payment_text",
        "promo_signature_text",
        "broadcast_interval",
    }


    if key in premium_keys:

        result_text = (
            "✅ <b>Сохранено</b>\n\n"
            + build_admin_premium_text(
                settings
            )
        )

        result_markup = (
            admin_premium_menu(settings)
        )

    else:

        result_text = (
            "✅ <b>Сохранено</b>\n\n"
            + await build_admin_text()
        )

        result_markup = admin_menu(
            settings[
                "ai_global_enabled"
            ]
            == "1"
        )


    try:

        await bot.edit_message_text(

            chat_id=(
                message.chat.id
            ),

            message_id=(
                panel_message_id
            ),

            text=result_text,

            reply_markup=result_markup,

            parse_mode="HTML",
        )

    except Exception:

        pass


def build_providers_text(
    providers: list,
    configured: dict,
):

    lines = [
        "🤖 <b>AI-ПРОВАЙДЕРЫ</b>\n\n"

        "Нажми на провайдера, чтобы "
        "включить 🟢 или выключить 🔴 его.\n\n"

        "Порядок в списке = порядок "
        "переключения.\n"
    ]


    for index, item in enumerate(
        providers,
        start=1,
    ):

        name = item["name"]

        icon = (
            "🟢"
            if item["enabled"]
            else "🔴"
        )


        if name in configured:

            model = configured[
                name
            ][
                "model"
            ]

        else:

            model = (
                "ключ не установлен"
            )


        lines.append(

            f"\n{index}. {icon} "
            f"<b>{html.escape(name)}</b>\n"

            f"Модель: "
            f"{html.escape(str(model))}\n"
        )


    return "".join(
        lines
    )


@router.callback_query(
    F.data == "admin_providers"
)
async def admin_providers_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    await state.clear()


    configured = (
        get_configured_providers()
    )


    providers = (
        await get_provider_list()
    )


    await callback.message.edit_text(

        build_providers_text(
            providers,
            configured,
        ),

        reply_markup=(
            admin_providers_keyboard(
                providers
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data.startswith(
        "admin_prov_toggle:"
    )
)
async def admin_prov_toggle_callback(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    name = callback.data.split(
        ":",
        1,
    )[1]


    new_state = await toggle_provider(
        name
    )


    if new_state is None:

        await callback.answer(
            "Провайдер не найден"
        )

        return


    configured = (
        get_configured_providers()
    )


    providers = (
        await get_provider_list()
    )


    await callback.message.edit_text(

        build_providers_text(
            providers,
            configured,
        ),

        reply_markup=(
            admin_providers_keyboard(
                providers
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer(
        "Включён"
        if new_state
        else "Выключен"
    )


@router.callback_query(
    F.data == "admin_prov_order"
)
async def admin_prov_order_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    providers = (
        await get_provider_list()
    )


    names = [
        item["name"]
        for item in providers
    ]


    await state.update_data(

        panel_message_id=(
            callback.message.message_id
        ),
    )


    await state.set_state(
        ProviderOrder.value
    )


    await callback.message.edit_text(

        "🔄 <b>Порядок провайдеров</b>\n\n"

        "Отправь названия через запятую "
        "в нужном порядке.\n\n"

        "Доступные:\n"
        f"<code>"
        f"{html.escape(', '.join(names))}"
        f"</code>\n\n"

        "Пример:\n"
        "<code>gemini, openrouter, groq</code>",

        reply_markup=admin_back(),

        parse_mode="HTML",
    )


    await callback.answer()


@router.message(
    ProviderOrder.value
)
async def admin_prov_order_value(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not is_admin(
        message.from_user.id
    ):

        await state.clear()
        return


    if not message.text:

        return


    providers = (
        await get_provider_list()
    )


    valid = {
        item["name"]
        for item in providers
    }


    entered = [
        token.strip()
        for token in message.text.split(
            ","
        )
        if token.strip()
    ]


    data = await state.get_data()

    panel_message_id = data.get(
        "panel_message_id"
    )


    invalid = (
        not entered
        or len(
            set(entered)
        ) != len(entered)
        or any(
            name not in valid
            for name in entered
        )
    )


    if invalid:

        await delete_user_message(
            message
        )


        try:

            await bot.edit_message_text(

                chat_id=(
                    message.chat.id
                ),

                message_id=(
                    panel_message_id
                ),

                text=(
                    "❌ Неверный порядок.\n\n"
                    "Используй доступные "
                    "названия без повторов."
                ),

                reply_markup=admin_back(),
            )

        except Exception:

            pass


        return


    await set_provider_order(
        entered
    )


    await state.clear()


    await delete_user_message(
        message
    )


    configured = (
        get_configured_providers()
    )


    providers = (
        await get_provider_list()
    )


    try:

        await bot.edit_message_text(

            chat_id=(
                message.chat.id
            ),

            message_id=(
                panel_message_id
            ),

            text=(
                "✅ <b>Порядок сохранён</b>\n\n"
                + build_providers_text(
                    providers,
                    configured,
                )
            ),

            reply_markup=(
                admin_providers_keyboard(
                    providers
                )
            ),

            parse_mode="HTML",
        )

    except Exception:

        pass


ADMIN_USERS_PAGE_SIZE = 20


async def build_admin_users_view(
    offset: int,
    query: str,
):

    total = await count_users(
        query
    )


    if offset < 0:

        offset = 0


    if total and offset >= total:

        offset = (
            (total - 1)
            // ADMIN_USERS_PAGE_SIZE
            * ADMIN_USERS_PAGE_SIZE
        )


    users = (
        await get_users_for_admin(
            limit=(
                ADMIN_USERS_PAGE_SIZE
            ),
            offset=offset,
            query=query,
        )
    )


    page = (
        offset
        // ADMIN_USERS_PAGE_SIZE
        + 1
    )

    pages = max(
        1,
        (
            total
            + ADMIN_USERS_PAGE_SIZE
            - 1
        )
        // ADMIN_USERS_PAGE_SIZE,
    )


    search_line = (
        f"🔍 Поиск: "
        f"<code>{html.escape(query)}</code>\n\n"
        if query
        else ""
    )


    text = (

        "👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n\n"

        + search_line

        + f"Страница <b>{page}</b> из "
        f"<b>{pages}</b> · всего "
        f"<b>{total}</b>\n\n"

        + "🆓 Free · ⭐ Premium\n"

        "В скобках — AI-лимит за сегодня.\n\n"

        "Нажмите пользователя, чтобы "
        "переключить Free / Premium."
    )


    keyboard = (
        admin_users_keyboard(
            users,
            offset=offset,
            total=total,
            page_size=(
                ADMIN_USERS_PAGE_SIZE
            ),
            query=query,
        )
    )


    return text, keyboard, offset


@router.callback_query(
    F.data == "admin_users"
)
async def admin_users_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    await state.update_data(
        admin_users_query="",
        admin_users_offset=0,
    )


    text, keyboard, _ = (
        await build_admin_users_view(
            0,
            "",
        )
    )


    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data.startswith(
        "admin_users_page:"
    )
)
async def admin_users_page_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    data = await state.get_data()

    query = data.get(
        "admin_users_query",
        "",
    )


    try:

        offset = int(
            callback.data.split(
                ":",
                1,
            )[1]
        )

    except ValueError:

        offset = 0


    text, keyboard, off = (
        await build_admin_users_view(
            offset,
            query,
        )
    )


    await state.update_data(
        admin_users_offset=off
    )


    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data == "admin_users_clear"
)
async def admin_users_clear_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    await state.update_data(
        admin_users_query="",
        admin_users_offset=0,
    )


    text, keyboard, _ = (
        await build_admin_users_view(
            0,
            "",
        )
    )


    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


    await callback.answer(
        "Поиск сброшен"
    )


@router.callback_query(
    F.data == "admin_users_search"
)
async def admin_users_search_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    await state.update_data(
        admin_users_panel_id=(
            callback.message.message_id
        ),
    )


    await state.set_state(
        AdminUserSearch.query
    )


    await callback.message.edit_text(

        "🔍 <b>ПОИСК ПОЛЬЗОВАТЕЛЯ</b>\n\n"

        "Отправьте <b>ID</b>, "
        "<b>@username</b> или <b>имя</b>.\n\n"

        "Для отмены отправьте "
        "<code>отмена</code>.",

        reply_markup=admin_back(),

        parse_mode="HTML",
    )


    await callback.answer()


@router.message(
    AdminUserSearch.query
)
async def admin_users_search_handler(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not is_admin(
        message.from_user.id
    ):

        await state.clear()

        return


    if not message.text:

        return


    query = message.text.strip()


    if query.lower() in {
        "отмена",
        "cancel",
        "-",
    }:

        query = ""


    data = await state.get_data()

    panel_id = data.get(
        "admin_users_panel_id"
    )


    await state.update_data(
        admin_users_query=query,
        admin_users_offset=0,
    )


    await state.set_state(None)


    await delete_user_message(
        message
    )


    text, keyboard, off = (
        await build_admin_users_view(
            0,
            query,
        )
    )


    await state.update_data(
        admin_users_offset=off
    )


    if panel_id:

        try:

            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=panel_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )

            return

        except Exception:

            pass


    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.callback_query(
    F.data.startswith(
        "admin_plan:"
    )
)
async def admin_plan_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    try:

        user_id = int(
            callback.data.split(
                ":",
                1,
            )[1]
        )

    except ValueError:

        await callback.answer(
            "Ошибка ID",
            show_alert=True,
        )

        return


    new_plan = (
        await toggle_user_plan(
            user_id
        )
    )


    data = await state.get_data()

    query = data.get(
        "admin_users_query",
        "",
    )

    offset = data.get(
        "admin_users_offset",
        0,
    )


    text, keyboard, off = (
        await build_admin_users_view(
            offset,
            query,
        )
    )


    await state.update_data(
        admin_users_offset=off
    )


    await callback.message.edit_text(

        f"✅ Тариф изменён: "
        f"<b>{new_plan.upper()}</b>\n\n"

        + text,

        reply_markup=keyboard,

        parse_mode="HTML",
    )


    await callback.answer(
        "Тариф изменён"
    )


@router.callback_query(
    F.data == "admin_reset_usage"
)
async def admin_reset_usage_callback(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    await reset_daily_usage()


    settings = (
        await get_global_settings()
    )


    await callback.message.edit_text(

        "♻️ <b>AI-счётчики сброшены.</b>\n\n"

        + await build_admin_text(),

        reply_markup=(
            admin_menu(
                settings[
                    "ai_global_enabled"
                ]
                == "1"
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer(
        "Сброшено"
    )


# =========================================================
# BUSINESS CONNECTION
# =========================================================

@router.business_connection()
async def business_connection_handler(
    connection: BusinessConnection,
):

    await save_business_connection(

        connection.id,

        connection.user.id,

        connection.is_enabled,
    )


    logger.info(

        "Business connection | "
        "owner=%s | enabled=%s",

        connection.user.id,

        connection.is_enabled,
    )


# =========================================================
# BUSINESS MESSAGE
# =========================================================

async def build_ref_link(
    owner_id: int,
) -> str:

    return (
        f"https://t.me/{_bot_username}"
        f"?start=ref_{owner_id}"
    )


async def build_promo_signature(
    owner_id: int,
    profile: dict,
) -> str:

    is_premium = (
        profile.get("plan") == "premium"
    )

    show_promo = bool(
        profile.get(
            "show_promo",
            1,
        )
    )


    if is_premium and not show_promo:

        return ""


    settings = (
        await get_global_settings()
    )


    template = (
        settings.get(
            "promo_signature_text"
        )
        or ""
    )


    if not template.strip():

        return ""


    link = await build_ref_link(
        owner_id
    )


    return template.replace(
        "{link}",
        link,
    )


async def pick_fallback_text(
    owner_id: int,
    chat_id: int,
    profile: dict,
):

    first = (
        profile.get("fallback_text")
        or ""
    )

    second = (
        profile.get("fallback_text2")
        or ""
    )


    if not second:

        return first


    stage = await get_fallback_stage(
        owner_id,
        chat_id,
    )


    if stage >= 2:

        return None


    await set_fallback_stage(
        owner_id,
        chat_id,
        stage + 1,
    )


    if stage == 0:

        return first


    signature = (
        await build_promo_signature(
            owner_id,
            profile,
        )
    )


    return second + signature


async def send_faq_answer(
    bot: Bot,
    chat_id: int,
    connection_id: str,
    item: dict,
):

    answer_type = (
        item.get("answer_type")
        or "text"
    )

    file_id = (
        item.get("answer_file_id")
        or ""
    )

    caption = (
        item.get("answer")
        or ""
    )

    entities = _parse_entities_json(
        item.get("answer_entities")
    )

    payload = _parse_payload_json(
        item.get("answer_payload")
    )


    common = {
        "chat_id": chat_id,
        "business_connection_id": (
            connection_id
        ),
    }


    if answer_type == "text":

        if not caption:

            return


        await bot.send_message(
            text=caption,
            entities=entities,
            **common,
        )


        return


    if answer_type == "photo":

        await bot.send_photo(
            photo=file_id,
            caption=(caption or None),
            caption_entities=entities,
            **common,
        )

    elif answer_type == "video":

        await bot.send_video(
            video=file_id,
            caption=(caption or None),
            caption_entities=entities,
            **common,
        )

    elif answer_type == "animation":

        await bot.send_animation(
            animation=file_id,
            caption=(caption or None),
            caption_entities=entities,
            **common,
        )

    elif answer_type == "document":

        await bot.send_document(
            document=file_id,
            caption=(caption or None),
            caption_entities=entities,
            **common,
        )

    elif answer_type == "audio":

        await bot.send_audio(
            audio=file_id,
            caption=(caption or None),
            caption_entities=entities,
            **common,
        )

    elif answer_type == "voice":

        await bot.send_voice(
            voice=file_id,
            **common,
        )

    elif answer_type == "video_note":

        await bot.send_video_note(
            video_note=file_id,
            **common,
        )

    elif answer_type == "sticker":

        await bot.send_sticker(
            sticker=file_id,
            **common,
        )

    elif answer_type == "location":

        await bot.send_location(
            latitude=payload.get("latitude"),
            longitude=payload.get("longitude"),
            **common,
        )

    elif answer_type == "venue":

        await bot.send_venue(
            latitude=payload.get("latitude"),
            longitude=payload.get("longitude"),
            title=payload.get("title", ""),
            address=payload.get("address", ""),
            **common,
        )

    elif answer_type == "contact":

        await bot.send_contact(
            phone_number=(
                payload.get("phone_number", "")
            ),
            first_name=(
                payload.get("first_name", "")
            ),
            last_name=(
                payload.get("last_name") or None
            ),
            vcard=(
                payload.get("vcard") or None
            ),
            **common,
        )

    elif answer_type == "dice":

        await bot.send_dice(
            emoji=(
                payload.get("emoji") or None
            ),
            **common,
        )

    elif answer_type == "poll":

        options = [
            InputPollOption(
                text=option.get("text", ""),
                text_entities=(
                    _dicts_to_entities(
                        option.get("entities")
                    )
                ),
            )
            for option in payload.get(
                "options",
                [],
            )
        ]


        if options:

            await bot.send_poll(
                question=(
                    payload.get("question", "")
                ),
                options=options,
                is_anonymous=(
                    payload.get(
                        "is_anonymous",
                        True,
                    )
                ),
                type=(
                    payload.get(
                        "type",
                        "regular",
                    )
                ),
                allows_multiple_answers=(
                    payload.get(
                        "allow_multiple_answers",
                        False,
                    )
                ),
                **common,
            )

    elif answer_type == "media_group":

        media = []


        for entry in payload.get(
            "items",
            [],
        ):

            entry_type = entry.get("type")

            entry_file_id = (
                entry.get("file_id")
                or ""
            )

            entry_caption = (
                entry.get("text") or None
            )

            entry_entities = (
                _dicts_to_entities(
                    entry.get("entities")
                )
            )


            if entry_type == "photo":

                media.append(
                    InputMediaPhoto(
                        media=entry_file_id,
                        caption=entry_caption,
                        caption_entities=(
                            entry_entities
                        ),
                    )
                )

            elif entry_type == "video":

                media.append(
                    InputMediaVideo(
                        media=entry_file_id,
                        caption=entry_caption,
                        caption_entities=(
                            entry_entities
                        ),
                    )
                )

            elif entry_type == "animation":

                media.append(
                    InputMediaAnimation(
                        media=entry_file_id,
                        caption=entry_caption,
                        caption_entities=(
                            entry_entities
                        ),
                    )
                )

            elif entry_type == "document":

                media.append(
                    InputMediaDocument(
                        media=entry_file_id,
                        caption=entry_caption,
                        caption_entities=(
                            entry_entities
                        ),
                    )
                )

            elif entry_type == "audio":

                media.append(
                    InputMediaAudio(
                        media=entry_file_id,
                        caption=entry_caption,
                        caption_entities=(
                            entry_entities
                        ),
                    )
                )


        if media:

            await bot.send_media_group(
                media=media,
                **common,
            )

    else:

        if caption:

            await bot.send_message(
                text=caption,
                entities=entities,
                **common,
            )


@router.business_message()
async def business_message_handler(
    message: Message,
    bot: Bot,
):

    connection_id = (
        message.business_connection_id
    )


    if not connection_id:

        return


    owner_id = (
        await get_owner_by_connection(
            connection_id
        )
    )


    if not owner_id:

        try:

            connection = (
                await bot.get_business_connection(

                    business_connection_id=(
                        connection_id
                    )
                )
            )


            if not connection.is_enabled:

                return


            owner_id = (
                connection.user.id
            )


            await save_business_connection(

                connection.id,

                owner_id,

                connection.is_enabled,
            )


        except Exception as error:

            logger.exception(

                "Business connection "
                "error: %s",

                error,
            )

            return


    # Владелец написал сам

    if (
        message.from_user

        and

        message.from_user.id
        == owner_id
    ):

        return


    # Сообщение отправил сам Business Bot

    if message.sender_business_bot:

        return


    # =====================================
    # ЗАПОМИНАЕМ КЛИЕНТА
    # =====================================

    peer_name = ""

    username = ""


    if message.from_user:

        peer_name = " ".join(
            filter(
                None,
                [
                    message.from_user.first_name,
                    message.from_user.last_name,
                ],
            )
        )


        username = (
            message.from_user.username
            or ""
        )


    await remember_chat(

        owner_id=owner_id,

        chat_id=(
            message.chat.id
        ),

        peer_name=(
            peer_name
        ),

        username=(
            username
        ),
    )


    # =====================================
    # МОЖНО ЛИ ОТВЕЧАТЬ?
    # =====================================

    allowed, reason, prefs = (
        await should_autoreply(

            owner_id,

            message.chat.id,
        )
    )


    if not allowed:

        logger.info(

            "AutoReply skipped | "
            "owner=%s | chat=%s | reason=%s",

            owner_id,

            message.chat.id,

            reason,
        )


        return


    # =====================================
    # TEXT
    # =====================================

    user_text = ""


    if message.text:

        user_text = (
            message.text.strip()
        )


    elif message.caption:

        user_text = (
            message.caption.strip()
        )


    profile = await get_profile(
        owner_id
    )


    # =====================================
    # MEDIA WITHOUT TEXT
    # =====================================

    if not user_text:

        try:

            fallback_text = (
                await pick_fallback_text(
                    owner_id,
                    message.chat.id,
                    profile,
                )
            )


            if fallback_text is None:

                return


            await bot.send_message(

                chat_id=(
                    message.chat.id
                ),

                business_connection_id=(
                    connection_id
                ),

                text=(
                    fallback_text
                ),
            )


        except Exception as error:

            logger.exception(

                "Media fallback error: %s",

                error,
            )


        return


    if AUTO_REPLY_DELAY > 0:

        await asyncio.sleep(
            AUTO_REPLY_DELAY
        )


    # =====================================
    # 1. FAQ
    # =====================================

    faqs = await get_faqs(
        owner_id
    )


    faq_item, score = (
        find_direct_answer(

            user_text,

            faqs,

            FAQ_MATCH_THRESHOLD,
        )
    )


    answer = None


    if faq_item:

        logger.info(

            "FAQ answer | "
            "owner=%s | score=%.2f",

            owner_id,

            score,
        )


        await set_fallback_stage(
            owner_id,
            message.chat.id,
            0,
        )


        try:

            await send_faq_answer(
                bot,
                message.chat.id,
                connection_id,
                faq_item,
            )

        except Exception as error:

            logger.exception(
                "FAQ send error: %s",
                error,
            )


        return


    # =====================================
    # 2. AI
    # =====================================

    if (
        answer is None

        and USE_AI

        and profile[
            "ai_enabled"
        ]
    ):

        global_settings = (
            await get_global_settings()
        )


        blocked_topic = (
            find_blocked_topic(

                user_text,

                global_settings[
                    "blocked_topics"
                ],
            )
        )


        # -----------------------------
        # ADMIN BLOCK
        # -----------------------------

        if blocked_topic:

            answer = (
                global_settings[
                    "blocked_reply"
                ]
            )


            logger.info(
                "Blocked AI topic: %s",
                blocked_topic,
            )


        # -----------------------------
        # AI QUOTA
        # -----------------------------

        else:

            reservation = (
                await reserve_user_ai_slot(
                    owner_id
                )
            )


            if reservation[
                "allowed"
            ]:

                languages = (
                    get_allowed_languages(

                        prefs,

                        profile[
                            "plan"
                        ],
                    )
                )


                context = (
                    select_ai_context(

                        user_text,

                        faqs,
                    )
                )


                chat_role = ""


                if profile[
                    "plan"
                ] == "premium":

                    chat_row = (
                        await get_chat_settings(

                            owner_id,

                            message.chat.id,
                        )
                    )


                    if chat_row:

                        chat_role = (
                            chat_row.get(
                                "role",
                                "",
                            )
                            or ""
                        )


                result = (
                    await get_ai_reply(

                        user_text=(
                            user_text
                        ),

                        profile=(
                            profile
                        ),

                        faq_context=(
                            context
                        ),

                        languages=(
                            languages
                        ),

                        blocked_topics=(
                            global_settings[
                                "blocked_topics"
                            ]
                        ),

                        blocked_reply=(
                            global_settings[
                                "blocked_reply"
                            ]
                        ),

                        chat_role=(
                            chat_role
                        ),
                    )
                )


                if result.ok:

                    answer = (
                        result.text
                    )


                    logger.info(

                        "AI answer | "
                        "owner=%s | provider=%s "
                        "| model=%s",

                        owner_id,

                        result.provider,

                        result.model,
                    )


                else:

                    # Все AI не сработали.
                    # Возвращаем пользователю
                    # его AI-слот.

                    await release_user_ai_slot(
                        owner_id
                    )


                    logger.warning(

                        "All AI failed | "
                        "owner=%s | error=%s",

                        owner_id,

                        result.error_type,
                    )


            else:

                logger.info(

                    "AI quota denied | "
                    "owner=%s | reason=%s",

                    owner_id,

                    reservation.get(
                        "reason"
                    ),
                )


    # =====================================
    # 3. FALLBACK
    # =====================================

    if not answer:

        answer = (
            await pick_fallback_text(
                owner_id,
                message.chat.id,
                profile,
            )
        )


        if answer is None:

            return

    else:

        await set_fallback_stage(
            owner_id,
            message.chat.id,
            0,
        )


    # =====================================
    # SEND
    # =====================================

    try:

        await bot.send_message(

            chat_id=(
                message.chat.id
            ),

            business_connection_id=(
                connection_id
            ),

            text=(
                answer
            ),
        )


    except Exception as error:

        logger.exception(
            "Business send error: %s",
            error,
        )


# =========================================================
# MAIN
# =========================================================

async def main():

    await init_db()


    await init_providers(
        AI_PROVIDER_ORDER
    )


    bot = Bot(
        token=BOT_TOKEN
    )


    dp = Dispatcher(
        storage=MemoryStorage()
    )


    dp.include_router(
        router
    )


    await bot.delete_webhook(
        drop_pending_updates=True
    )


    me = await bot.get_me()


    global _bot_username
    _bot_username = me.username


    logger.info(
        "✅ @%s запущен",
        me.username,
    )


    logger.info(

        "AI providers: %s",

        ", ".join(
            get_configured_providers().keys()
        )
        or
        "none",
    )


    try:

        await dp.start_polling(

            bot,

            allowed_updates=(
                dp.resolve_used_update_types()
            ),
        )


    finally:

        await bot.session.close()


if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )


    except KeyboardInterrupt:

        print(
            "\nБот остановлен."
        )
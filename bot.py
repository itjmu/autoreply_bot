import asyncio
import html
import logging


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
    Message,
)


from ai_service import (
    get_ai_reply,
    get_configured_providers,
)

from config import (
    ADMIN_IDS,
    AUTO_REPLY_DELAY,
    BOT_TOKEN,
    FAQ_MATCH_THRESHOLD,
    USE_AI,
)

from database import (
    add_faq,
    delete_faq,
    ensure_user,
    get_admin_stats,
    get_allowed_languages,
    get_chat_settings,
    get_connections,
    get_faqs,
    get_global_settings,
    get_owner_by_connection,
    get_preferences,
    get_profile,
    get_provider_stats_today,
    get_user_quota_status,
    get_users_for_admin,
    init_db,
    release_user_ai_slot,
    remember_chat,
    reserve_user_ai_slot,
    reset_daily_usage,
    save_business_connection,
    set_global_setting,
    set_preference,
    should_autoreply,
    toggle_ai,
    toggle_autoreply,
    toggle_chat,
    toggle_global_ai,
    toggle_schedule,
    toggle_user_plan,
    update_profile_field,
    validate_time,
    validate_timezone,
)

from keyboards import (
    admin_back,
    admin_menu,
    admin_users_keyboard,
    back_main,
    chat_manage_menu,
    faq_list_keyboard,
    languages_menu,
    main_menu,
    profile_menu,
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
    PreferenceEdit,
    ProfileEdit,
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


# =========================================================
# HELPERS
# =========================================================

def is_admin(
    user_id: int,
):

    return (
        user_id in ADMIN_IDS
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
                "Теперь отправьте готовый ответ."
            ),

            reply_markup=back_main(),

            parse_mode="HTML",
        )

    except Exception:

        pass


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

    if not message.text:
        return


    answer = (
        message.text.strip()
    )


    data = await state.get_data()


    question = data.get(
        "question",
        "",
    )


    panel_message_id = data.get(
        "panel_message_id"
    )


    await add_faq(

        owner_id=(
            message.from_user.id
        ),

        question=question,

        answer=answer,
    )


    await state.clear()


    try:

        await bot.edit_message_text(

            chat_id=(
                message.chat.id
            ),

            message_id=(
                panel_message_id
            ),

            text=(
                "✅ <b>ВОПРОС СОХРАНЁН</b>\n\n"

                f"❓ {html.escape(question)}\n\n"

                f"💬 {html.escape(answer)}"
            ),

            reply_markup=(
                await build_main_markup(
                    message.from_user.id
                )
            ),

            parse_mode="HTML",
        )

    except Exception:

        pass


    await delete_user_message(
        message
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


            parts.append(
                (
                    f"\n<b>{number}.</b> "
                    f"{html.escape(question)}\n"
                    f"→ {html.escape(answer)}"
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

        reply_markup=profile_menu(),

        parse_mode="HTML",
    )


    await callback.answer()


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

            reply_markup=profile_menu(),

            parse_mode="HTML",
        )

    except Exception:

        pass


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


ADMIN_EDIT_LABELS = {

    "free_ai_daily_limit":
        "дневной AI-лимит Free",

    "premium_ai_daily_limit":
        "дневной AI-лимит Premium",

    "blocked_topics":
        "запрещённые темы AI",

    "blocked_reply":
        "ответ на запрещённую тему",
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


    if key in {

        "free_ai_daily_limit",
        "premium_ai_daily_limit",

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
        key == "blocked_topics"

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


    try:

        await bot.edit_message_text(

            chat_id=(
                message.chat.id
            ),

            message_id=(
                panel_message_id
            ),

            text=(

                "✅ <b>Сохранено</b>\n\n"

                + await build_admin_text()
            ),

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

    except Exception:

        pass


@router.callback_query(
    F.data == "admin_providers"
)
async def admin_providers_callback(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    configured = (
        get_configured_providers()
    )


    stats = (
        await get_provider_stats_today()
    )


    stats_map = {

        item["provider"]:
            item

        for item in stats
    }


    all_names = [

        "openrouter",
        "gemini",
        "groq",
        "deepseek",
        "openai",
    ]


    for name in configured:

        if name not in all_names:

            all_names.append(
                name
            )


    lines = [
        "🤖 <b>AI-ПРОВАЙДЕРЫ</b>\n"
    ]


    for name in all_names:

        provider_config = (
            configured.get(
                name
            )
        )


        item = stats_map.get(
            name,
            {},
        )


        if provider_config:

            status = "🟢"

            model = (
                provider_config[
                    "model"
                ]
            )

        else:

            status = "⚪"

            model = (
                "ключ не установлен"
            )


        lines.append(

            f"\n{status} "
            f"<b>{html.escape(name)}</b>\n"

            f"Модель: "
            f"{html.escape(str(model))}\n"

            f"Попыток: "
            f"{item.get('attempts', 0)} | "

            f"Успешно: "
            f"{item.get('successes', 0)} | "

            f"Ошибок: "
            f"{item.get('failures', 0)} | "

            f"429: "
            f"{item.get('rate_limits', 0)}\n"
        )


    lines.append(

        "\nПорядок переключения задаётся "
        "в <code>AI_PROVIDER_ORDER</code> "
        "файла .env."
    )


    await callback.message.edit_text(

        "".join(
            lines
        ),

        reply_markup=admin_back(),

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data == "admin_users"
)
async def admin_users_callback(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny_admin(
            callback
        )

        return


    users = await get_users_for_admin(
        limit=30
    )


    await callback.message.edit_text(

        "👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n\n"

        "🆓 Free\n"

        "⭐ Premium\n\n"

        "В квадратных скобках показан "
        "AI-лимит за текущий день пользователя.\n\n"

        "Нажмите пользователя, чтобы "
        "переключить Free / Premium.",

        reply_markup=(
            admin_users_keyboard(
                users
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer()


@router.callback_query(
    F.data.startswith(
        "admin_plan:"
    )
)
async def admin_plan_callback(
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


    users = await get_users_for_admin(
        limit=30
    )


    await callback.message.edit_text(

        "👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n\n"

        f"✅ Новый тариф пользователя: "

        f"<b>"
        f"{new_plan.upper()}"
        f"</b>\n\n"

        "Нажмите пользователя, чтобы "
        "изменить его тариф.",

        reply_markup=(
            admin_users_keyboard(
                users
            )
        ),

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

            await bot.send_message(

                chat_id=(
                    message.chat.id
                ),

                business_connection_id=(
                    connection_id
                ),

                text=(
                    profile[
                        "fallback_text"
                    ]
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


    answer, score = (
        find_direct_answer(

            user_text,

            faqs,

            FAQ_MATCH_THRESHOLD,
        )
    )


    if answer:

        logger.info(

            "FAQ answer | "
            "owner=%s | score=%.2f",

            owner_id,

            score,
        )


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
            profile[
                "fallback_text"
            ]
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
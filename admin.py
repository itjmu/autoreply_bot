import html


from aiogram import (
    F,
    Router,
)

from aiogram.filters import (
    Command,
)

from aiogram.fsm.context import (
    FSMContext,
)

from aiogram.types import (
    CallbackQuery,
    Message,
)


from config import (
    ADMIN_IDS,
)

from database import (
    get_admin_stats,
    get_global_settings,
    get_users,
    reset_today_ai_usage,
    set_global_setting,
    toggle_global_ai,
    toggle_user_plan,
)

from keyboards import (
    admin_back,
    admin_menu,
    admin_users_keyboard,
)

from policy import (
    parse_blocked_topics,
)

from states import (
    AdminEdit,
)


admin_router = Router(
    name="admin"
)


# ==========================================
# SECURITY
# ==========================================

def is_admin(
    user_id: int,
) -> bool:

    return (
        user_id in ADMIN_IDS
    )


async def deny(
    callback: CallbackQuery,
):

    await callback.answer(
        "Нет доступа.",
        show_alert=True,
    )


# ==========================================
# PANEL TEXT
# ==========================================

async def build_admin_text():

    settings = (
        await get_global_settings()
    )

    stats = (
        await get_admin_stats()
    )


    blocked = parse_blocked_topics(
        settings[
            "blocked_topics"
        ]
    )


    ai_status = (
        "🟢 Включён"
        if settings[
            "ai_global_enabled"
        ] == "1"
        else
        "🔴 Выключен"
    )


    return (
        "👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n"

        f"🤖 AI: <b>{ai_status}</b>\n\n"

        f"👥 Пользователей: "
        f"<b>{stats['users']}</b>\n"

        f"🆓 Free: "
        f"<b>{stats['free_users']}</b>\n"

        f"⭐ Premium: "
        f"<b>{stats['premium_users']}</b>\n"

        f"📚 FAQ в базе: "
        f"<b>{stats['faq_count']}</b>\n\n"

        f"🧠 Успешных AI-ответов сегодня: "
        f"<b>{stats['ai_answers_today']}</b>\n"

        f"🌐 Попыток OpenRouter: "
        f"<b>{stats['provider_attempts']}"
        f"/{stats['provider_limit']}</b>\n\n"

        f"5️⃣ Free лимит: "
        f"<b>{settings['free_ai_daily_limit']}"
        f"/день</b>\n"

        f"⭐ Premium лимит: "
        f"<b>{settings['premium_ai_daily_limit']}"
        f"/день</b>\n\n"

        f"🚫 Запрещённых тем: "
        f"<b>{len(blocked)}</b>\n\n"

        "ℹ️ FAQ не расходуют AI."
    )


# ==========================================
# /ADMIN
# ==========================================

@admin_router.message(
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

        reply_markup=admin_menu(
            settings[
                "ai_global_enabled"
            ] == "1"
        ),

        parse_mode="HTML",
    )


# ==========================================
# ADMIN CALLBACK
# ==========================================

@admin_router.callback_query(
    F.data == "admin"
)
async def admin_callback(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny(
            callback
        )

        return


    await state.clear()


    settings = (
        await get_global_settings()
    )


    await callback.message.edit_text(
        await build_admin_text(),

        reply_markup=admin_menu(
            settings[
                "ai_global_enabled"
            ] == "1"
        ),

        parse_mode="HTML",
    )


    await callback.answer()


# ==========================================
# STATS
# ==========================================

@admin_router.callback_query(
    F.data == "adm_stats"
)
async def admin_stats(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny(callback)
        return


    await callback.message.edit_text(
        await build_admin_text(),

        reply_markup=admin_back(),

        parse_mode="HTML",
    )


    await callback.answer()


# ==========================================
# GLOBAL AI ON / OFF
# ==========================================

@admin_router.callback_query(
    F.data == "adm_ai_toggle"
)
async def admin_ai_toggle(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny(callback)
        return


    await toggle_global_ai()


    settings = (
        await get_global_settings()
    )


    await callback.message.edit_text(
        await build_admin_text(),

        reply_markup=admin_menu(
            settings[
                "ai_global_enabled"
            ] == "1"
        ),

        parse_mode="HTML",
    )


    await callback.answer(
        "Настройка изменена"
    )


# ==========================================
# EDIT GLOBAL SETTINGS
# ==========================================

EDIT_LABELS = {

    "free_ai_daily_limit":
        "дневной лимит AI для Free",

    "premium_ai_daily_limit":
        "дневной лимит AI для Premium",

    "provider_daily_limit":
        "общий дневной лимит OpenRouter",

    "blocked_topics":
        "глобально запрещённые темы для AI",

    "blocked_reply":
        "ответ при запрещённой теме",
}


NUMERIC_SETTINGS = {

    "free_ai_daily_limit",
    "premium_ai_daily_limit",
    "provider_daily_limit",
}


@admin_router.callback_query(
    F.data.startswith(
        "adm_edit:"
    )
)
async def admin_edit(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny(callback)
        return


    key = callback.data.split(
        ":",
        1,
    )[1]


    if key not in EDIT_LABELS:

        await callback.answer(
            "Неизвестная настройка"
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


    current = settings.get(
        key,
        "",
    )


    if key == "blocked_topics":

        instruction = (
            "\n\nОтправь темы через запятую.\n\n"
            "Например:\n"
            "<code>"
            "казино, ставки, политика"
            "</code>\n\n"
            "Чтобы очистить список — отправь "
            "<code>очистить</code>."
        )

    else:

        instruction = ""


    await callback.message.edit_text(
        "⚙️ <b>Изменение настройки</b>\n\n"

        f"Настройка:\n"
        f"<b>{EDIT_LABELS[key]}</b>\n\n"

        f"Сейчас:\n"
        f"<code>{html.escape(str(current))}</code>"

        f"{instruction}\n\n"

        "Отправь новое значение.",

        reply_markup=admin_back(),

        parse_mode="HTML",
    )


    await callback.answer()


@admin_router.message(
    AdminEdit.value
)
async def admin_edit_value(
    message: Message,
    state: FSMContext,
):

    if not is_admin(
        message.from_user.id
    ):

        await state.clear()
        return


    if not message.text:

        return


    value = (
        message.text.strip()
    )


    data = await state.get_data()

    key = data.get(
        "admin_setting"
    )

    panel_message_id = data.get(
        "panel_message_id"
    )


    if key not in EDIT_LABELS:

        await state.clear()
        return


    if key in NUMERIC_SETTINGS:

        if (
            not value.isdigit()
            or int(value) < 0
        ):

            try:

                await message.delete()

            except Exception:
                pass


            try:

                await message.bot.edit_message_text(

                    chat_id=(
                        message.chat.id
                    ),

                    message_id=(
                        panel_message_id
                    ),

                    text=(
                        "❌ Нужно отправить "
                        "целое число.\n\n"
                        "Например:\n"
                        "<code>5</code>"
                    ),

                    reply_markup=admin_back(),

                    parse_mode="HTML",
                )

            except Exception:
                pass


            return


    if key == "blocked_topics":

        if value.lower() in {
            "очистить",
            "clear",
            "-",
            "нет",
        }:

            value = ""


    await set_global_setting(
        key,
        value,
    )


    await state.clear()


    try:

        await message.delete()

    except Exception:
        pass


    settings = (
        await get_global_settings()
    )


    try:

        await message.bot.edit_message_text(

            chat_id=message.chat.id,

            message_id=(
                panel_message_id
            ),

            text=(
                "✅ <b>Настройка сохранена</b>\n\n"
                + await build_admin_text()
            ),

            reply_markup=admin_menu(
                settings[
                    "ai_global_enabled"
                ] == "1"
            ),

            parse_mode="HTML",
        )

    except Exception:
        pass


# ==========================================
# USERS / PREMIUM
# ==========================================

@admin_router.callback_query(
    F.data == "adm_users"
)
async def admin_users(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny(callback)
        return


    users = await get_users(
        limit=30
    )


    text = (
        "👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n\n"
        "🆓 = Free\n"
        "⭐ = Premium\n"
        "[N] = AI-ответов сегодня\n\n"
        "Нажми пользователя, "
        "чтобы переключить Free / Premium."
    )


    await callback.message.edit_text(
        text,

        reply_markup=(
            admin_users_keyboard(
                users
            )
        ),

        parse_mode="HTML",
    )


    await callback.answer()


@admin_router.callback_query(
    F.data.startswith(
        "adm_plan:"
    )
)
async def admin_toggle_plan(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny(callback)
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
            "Ошибка ID"
        )

        return


    new_plan = await toggle_user_plan(
        user_id
    )


    users = await get_users(
        limit=30
    )


    await callback.message.edit_text(

        "👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n\n"

        f"✅ Новый тариф: "
        f"<b>{new_plan.upper()}</b>\n\n"

        "Нажми пользователя, "
        "чтобы изменить его тариф.",

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


# ==========================================
# RESET
# ==========================================

@admin_router.callback_query(
    F.data == "adm_reset_usage"
)
async def admin_reset_usage(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):

        await deny(callback)
        return


    await reset_today_ai_usage()


    settings = (
        await get_global_settings()
    )


    await callback.message.edit_text(

        "♻️ <b>Дневные счётчики сброшены.</b>\n\n"
        + await build_admin_text(),

        reply_markup=admin_menu(
            settings[
                "ai_global_enabled"
            ] == "1"
        ),

        parse_mode="HTML",
    )


    await callback.answer(
        "Сброшено"
    )
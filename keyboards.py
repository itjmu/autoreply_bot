from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


def main_menu(
    *,
    ai_enabled: bool,
    ai_used: int,
    ai_limit: int,
    global_ai_enabled: bool,
    autoreply_enabled: bool,
    is_admin: bool,
):

    if not autoreply_enabled:
        auto_text = (
            "🔴 Автоответчик выключен"
        )
    else:
        auto_text = (
            "🟢 Автоответчик включён"
        )

    if not global_ai_enabled:

        ai_text = (
            "⛔ AI отключён админом"
        )

    elif ai_enabled:

        ai_text = (
            f"🧠 AI: {ai_used}/{ai_limit}"
        )

    else:

        ai_text = (
            "🧠 AI выключен"
        )


    rows = [

        [
            InlineKeyboardButton(
                text=auto_text,
                callback_data="settings",
            )
        ],

        [
            InlineKeyboardButton(
                text="➕ Добавить вопрос / ответ",
                callback_data="faq_add",
            )
        ],

        [
            InlineKeyboardButton(
                text="📚 Мои вопросы",
                callback_data="faq_list",
            )
        ],

        [
            InlineKeyboardButton(
                text="👤 Профиль AI",
                callback_data="profile",
            )
        ],

        [
            InlineKeyboardButton(
                text=ai_text,
                callback_data="ai_toggle",
            )
        ],

        [
            InlineKeyboardButton(
                text="📊 Мой AI-лимит",
                callback_data="my_ai_limit",
            )
        ],

        [
            InlineKeyboardButton(
                text="⚙️ Языки, время и график",
                callback_data="settings",
            )
        ],

        [
            InlineKeyboardButton(
                text="🔗 Telegram Business",
                callback_data="business_status",
            )
        ],
    ]


    if is_admin:

        rows.append(
            [
                InlineKeyboardButton(
                    text="👑 Админ-панель",
                    callback_data="admin",
                )
            ]
        )


    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def back_main():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Главное меню",
                    callback_data="main",
                )
            ]
        ]
    )


def profile_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="👤 Имя / роль",
                    callback_data="profile_edit:owner_name",
                )
            ],

            [
                InlineKeyboardButton(
                    text="🎂 Возраст",
                    callback_data="profile_edit:age",
                ),

                InlineKeyboardButton(
                    text="⚧ Пол",
                    callback_data="profile_edit:gender",
                ),
            ],

            [
                InlineKeyboardButton(
                    text="💬 Темы владельца",
                    callback_data="profile_edit:topics",
                )
            ],

            [
                InlineKeyboardButton(
                    text="🧠 Характеристика AI",
                    callback_data="profile_edit:ai_description",
                )
            ],

            [
                InlineKeyboardButton(
                    text="🆘 Запасной ответ",
                    callback_data="profile_edit:fallback_text",
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅️ Главное меню",
                    callback_data="main",
                )
            ],
        ]
    )


def faq_list_keyboard(
    faqs: list,
):

    rows = []


    for faq in faqs[:20]:

        text = faq["question"]

        if len(text) > 30:
            text = text[:30] + "..."

        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 {text}",
                    callback_data=(
                        f"faq_delete:{faq['id']}"
                    ),
                )
            ]
        )


    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Добавить",
                callback_data="faq_add",
            )
        ]
    )


    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Главное меню",
                callback_data="main",
            )
        ]
    )


    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def settings_menu(
    prefs: dict,
):

    auto_text = (
        "🟢 Автоответчик включён"
        if prefs["autoreply_enabled"]
        else
        "🔴 Автоответчик выключен"
    )

    schedule_text = (
        "🟢 График включён"
        if prefs["schedule_enabled"]
        else
        "⚪ График выключен"
    )


    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text=auto_text,
                    callback_data="settings_autoreply",
                )
            ],

            [
                InlineKeyboardButton(
                    text="🌍 Языки",
                    callback_data="settings_languages",
                ),

                InlineKeyboardButton(
                    text="🕐 Часовой пояс",
                    callback_data="settings_timezone",
                ),
            ],

            [
                InlineKeyboardButton(
                    text=schedule_text,
                    callback_data="settings_schedule",
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅️ Главное меню",
                    callback_data="main",
                )
            ],
        ]
    )


def languages_menu(
    plan: str,
):

    rows = [

        [
            InlineKeyboardButton(
                text="1️⃣ Основной язык",
                callback_data="pref_edit:primary_language",
            )
        ],

        [
            InlineKeyboardButton(
                text="2️⃣ Второй язык",
                callback_data="pref_edit:secondary_language",
            )
        ],
    ]


    if plan == "premium":

        rows.append(
            [
                InlineKeyboardButton(
                    text="⭐ Дополнительные языки",
                    callback_data="pref_edit:extra_languages",
                )
            ]
        )

    else:

        rows.append(
            [
                InlineKeyboardButton(
                    text="🔒 Больше 2 языков — Premium",
                    callback_data="premium_languages_info",
                )
            ]
        )


    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Настройки",
                callback_data="settings",
            )
        ]
    )


    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def timezone_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🇹🇯 Душанбе",
                    callback_data="timezone:Asia/Dushanbe",
                ),

                InlineKeyboardButton(
                    text="🇷🇺 Москва",
                    callback_data="timezone:Europe/Moscow",
                ),
            ],

            [
                InlineKeyboardButton(
                    text="🇺🇿 Ташкент",
                    callback_data="timezone:Asia/Tashkent",
                ),

                InlineKeyboardButton(
                    text="🇰🇿 Алматы",
                    callback_data="timezone:Asia/Almaty",
                ),
            ],

            [
                InlineKeyboardButton(
                    text="🌐 UTC",
                    callback_data="timezone:UTC",
                )
            ],

            [
                InlineKeyboardButton(
                    text="✏️ Ввести вручную",
                    callback_data="pref_edit:timezone",
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅️ Настройки",
                    callback_data="settings",
                )
            ],
        ]
    )


def schedule_menu(
    prefs: dict,
):

    status = (
        "🟢 График включён"
        if prefs["schedule_enabled"]
        else
        "⚪ График выключен"
    )


    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text=status,
                    callback_data="schedule_toggle",
                )
            ],

            [
                InlineKeyboardButton(
                    text="🕐 Изменить время",
                    callback_data="schedule_set_time",
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅️ Настройки",
                    callback_data="settings",
                )
            ],
        ]
    )


def chat_manage_menu(
    chat_id: int,
    enabled: bool,
):

    status = (
        "🟢 Автоответ для чата ВКЛ"
        if enabled
        else
        "🔴 Автоответ для чата ВЫКЛ"
    )


    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text=status,
                    callback_data=f"chat_toggle:{chat_id}",
                )
            ],

            [
                InlineKeyboardButton(
                    text="⚙️ Общие настройки",
                    callback_data="settings",
                )
            ],

            [
                InlineKeyboardButton(
                    text="🏠 Главное меню",
                    callback_data="main",
                )
            ],
        ]
    )


def admin_menu(
    global_ai_enabled: bool,
):

    ai_text = (
        "🟢 AI для всех включён"
        if global_ai_enabled
        else
        "🔴 AI для всех выключен"
    )


    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="admin_stats",
                )
            ],

            [
                InlineKeyboardButton(
                    text=ai_text,
                    callback_data="admin_ai_toggle",
                )
            ],

            [
                InlineKeyboardButton(
                    text="5️⃣ Лимит Free",
                    callback_data="admin_edit:free_ai_daily_limit",
                ),

                InlineKeyboardButton(
                    text="⭐ Лимит Premium",
                    callback_data="admin_edit:premium_ai_daily_limit",
                ),
            ],

            [
                InlineKeyboardButton(
                    text="🚫 Запрещённые темы",
                    callback_data="admin_edit:blocked_topics",
                )
            ],

            [
                InlineKeyboardButton(
                    text="💬 Ответ на запрет",
                    callback_data="admin_edit:blocked_reply",
                )
            ],

            [
                InlineKeyboardButton(
                    text="🤖 AI-провайдеры",
                    callback_data="admin_providers",
                )
            ],

            [
                InlineKeyboardButton(
                    text="👥 Пользователи / тарифы",
                    callback_data="admin_users",
                )
            ],

            [
                InlineKeyboardButton(
                    text="♻️ Сбросить дневные лимиты",
                    callback_data="admin_reset_usage",
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅️ Главное меню",
                    callback_data="main",
                )
            ],
        ]
    )


def admin_back():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Админ-панель",
                    callback_data="admin",
                )
            ]
        ]
    )


def admin_users_keyboard(
    users: list,
):

    rows = []


    for user in users:

        icon = (
            "⭐"
            if user["plan"] == "premium"
            else
            "🆓"
        )

        name = (
            user["owner_name"]
            or user["first_name"]
            or (
                f"@{user['username']}"
                if user["username"]
                else str(
                    user["telegram_id"]
                )
            )
        )

        name = name[:22]


        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"{icon} {name} "
                        f"[{user['ai_used']}/{user['ai_limit']}]"
                    ),
                    callback_data=(
                        f"admin_plan:{user['telegram_id']}"
                    ),
                )
            ]
        )


    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Админ-панель",
                callback_data="admin",
            )
        ]
    )


    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )
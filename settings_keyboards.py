from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


def settings_menu(
    prefs: dict,
):

    autoreply = (
        "🟢 Автоответчик включён"
        if prefs["autoreply_enabled"]
        else
        "🔴 Автоответчик выключен"
    )

    schedule = (
        "🟢 График включён"
        if prefs["schedule_enabled"]
        else
        "⚪ График выключен"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text=autoreply,
                    callback_data=(
                        "settings_autoreply"
                    ),
                )
            ],

            [
                InlineKeyboardButton(
                    text="🌍 Языки",
                    callback_data=(
                        "settings_languages"
                    ),
                ),

                InlineKeyboardButton(
                    text="🕐 Часовой пояс",
                    callback_data=(
                        "settings_timezone"
                    ),
                ),
            ],

            [
                InlineKeyboardButton(
                    text=schedule,
                    callback_data=(
                        "settings_schedule"
                    ),
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
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
                callback_data=(
                    "setpref:"
                    "primary_language"
                ),
            )
        ],

        [
            InlineKeyboardButton(
                text="2️⃣ Второй язык",
                callback_data=(
                    "setpref:"
                    "secondary_language"
                ),
            )
        ],
    ]

    if plan == "premium":

        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        "⭐ Дополнительные языки"
                    ),
                    callback_data=(
                        "setpref:"
                        "extra_languages"
                    ),
                )
            ]
        )

    else:

        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        "🔒 Больше 2 языков — Premium"
                    ),
                    callback_data=(
                        "premium_languages_info"
                    ),
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
                    callback_data=(
                        "timezone:"
                        "Asia/Dushanbe"
                    ),
                ),

                InlineKeyboardButton(
                    text="🇷🇺 Москва",
                    callback_data=(
                        "timezone:"
                        "Europe/Moscow"
                    ),
                ),
            ],

            [
                InlineKeyboardButton(
                    text="🇺🇿 Ташкент",
                    callback_data=(
                        "timezone:"
                        "Asia/Tashkent"
                    ),
                ),

                InlineKeyboardButton(
                    text="🇰🇿 Алматы",
                    callback_data=(
                        "timezone:"
                        "Asia/Almaty"
                    ),
                ),
            ],

            [
                InlineKeyboardButton(
                    text="🌐 UTC",
                    callback_data=(
                        "timezone:UTC"
                    ),
                )
            ],

            [
                InlineKeyboardButton(
                    text="✏️ Ввести вручную",
                    callback_data=(
                        "setpref:timezone"
                    ),
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
        "🟢 Включён"
        if prefs["schedule_enabled"]
        else
        "⚪ Выключен"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text=(
                        f"График: {status}"
                    ),
                    callback_data=(
                        "schedule_toggle"
                    ),
                )
            ],

            [
                InlineKeyboardButton(
                    text=(
                        "🕐 Изменить время"
                    ),
                    callback_data=(
                        "schedule_set_time"
                    ),
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
        "🟢 Автоответ включён"
        if enabled
        else
        "🔴 Автоответ выключен"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text=status,
                    callback_data=(
                        f"chat_toggle:"
                        f"{chat_id}"
                    ),
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
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
        auto_text = "🔴 Автоответ"
    else:
        auto_text = "🟢 Автоответ"

    if not global_ai_enabled:
        ai_text = "⛔ AI откл"
    elif ai_enabled:
        ai_text = f"🧠 AI: {ai_used}/{ai_limit}"
    else:
        ai_text = "🧠 AI выкл"

    rows = [
        [
            InlineKeyboardButton(
                text=auto_text,
                callback_data="settings",
            ),
            InlineKeyboardButton(
                text=ai_text,
                callback_data="ai_toggle",
            ),
        ],
        [
            InlineKeyboardButton(
                text="➕ Добавить",
                callback_data="faq_add",
            ),
            InlineKeyboardButton(
                text="📚 Вопросы",
                callback_data="faq_list",
            ),
        ],
        [
            InlineKeyboardButton(
                text="👤 Профиль",
                callback_data="profile",
            ),
            InlineKeyboardButton(
                text="📊 Лимит",
                callback_data="my_ai_limit",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🔗 Business",
                callback_data="business_status",
            ),
            InlineKeyboardButton(
                text="🎁 Рефералы",
                callback_data="referrals",
            ),
        ],
        [
            InlineKeyboardButton(
                text="💎 Premium",
                callback_data="premium_buy",
            ),
            InlineKeyboardButton(
                text="⚙️ Настройки",
                callback_data="settings",
            ),
        ],
    ]

    if is_admin:
        rows.append(
            [
                InlineKeyboardButton(
                    text="👑 Админ",
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


def profile_menu(
    is_admin: bool = False,
    is_premium: bool = False,
    show_promo: bool = True,
):

    rows = [
        [
            InlineKeyboardButton(
                text="👤 Имя",
                callback_data="profile_edit:owner_name",
            ),
            InlineKeyboardButton(
                text="🎂 Возраст",
                callback_data="profile_edit:age",
            ),
        ],
        [
            InlineKeyboardButton(
                text="⚧ Пол",
                callback_data="profile_edit:gender",
            ),
            InlineKeyboardButton(
                text="💬 Темы",
                callback_data="profile_edit:topics",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🧠 AI",
                callback_data="profile_edit:ai_description",
            ),
            InlineKeyboardButton(
                text="🆘 Запасной",
                callback_data="profile_edit:fallback_text",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🆘 Запасной 2",
                callback_data="profile_edit:fallback_text2",
            ),
        ],
    ]

    rows.append(
        [
            InlineKeyboardButton(
                text="🎭 Роли чатов",
                callback_data="chat_roles",
            )
        ]
    )

    if is_premium:

        promo_text = (
            "📣 Реклама: вкл"
            if show_promo
            else "📣 Реклама: выкл"
        )

        rows.append(
            [
                InlineKeyboardButton(
                    text=promo_text,
                    callback_data="toggle_promo",
                )
            ]
        )

    bottom = [
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="main",
        ),
    ]

    if is_admin:
        bottom.append(
            InlineKeyboardButton(
                text="👑 Админ",
                callback_data="admin",
            )
        )

    rows.append(bottom)

    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def faq_list_keyboard(
    faqs: list,
):

    rows = []


    for faq in faqs[:10]:

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
                    text="📖 Инструкция",
                    callback_data="guide_view",
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
                ),

                InlineKeyboardButton(
                    text="♻️ Сброс лимитов",
                    callback_data="admin_reset_usage",
                ),
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
                    text="🚫 Темы",
                    callback_data="admin_edit:blocked_topics",
                ),

                InlineKeyboardButton(
                    text="💬 Ответ на запрет",
                    callback_data="admin_edit:blocked_reply",
                ),
            ],

            [
                InlineKeyboardButton(
                    text="🤖 Провайдеры",
                    callback_data="admin_providers",
                ),

                InlineKeyboardButton(
                    text="👥 Пользователи",
                    callback_data="admin_users",
                ),
            ],

            [
                InlineKeyboardButton(
                    text="💎 Premium / цены",
                    callback_data="admin_premium",
                ),

                InlineKeyboardButton(
                    text="📢 Рассылка",
                    callback_data="admin_broadcast",
                ),
            ],

            [
                InlineKeyboardButton(
                    text="📖 Инструкция",
                    callback_data="admin_guide",
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


def admin_guide_keyboard(
    messages: list,
):

    rows = []


    for index, item in enumerate(
        messages,
        start=1,
    ):

        preview = (
            item.get("preview")
            or "Медиа / сообщение"
        )

        preview = preview[:40]


        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"🗑 {index}. {preview}"
                    ),
                    callback_data=(
                        f"guide_delete:{item['id']}"
                    ),
                )
            ]
        )


    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Добавить сообщение",
                callback_data="guide_add",
            )
        ]
    )


    if messages:

        rows.append(
            [
                InlineKeyboardButton(
                    text="🧹 Очистить всё",
                    callback_data="guide_clear",
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


def guide_adding_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Готово",
                    callback_data="guide_done",
                )
            ]
        ]
    )


def admin_users_keyboard(
    users: list,
    offset: int = 0,
    total: int = 0,
    page_size: int = 20,
    query: str = "",
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


    nav = []

    if offset > 0:

        nav.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=(
                    f"admin_users_page:{max(0, offset - page_size)}"
                ),
            )
        )


    if offset + page_size < total:

        nav.append(
            InlineKeyboardButton(
                text="Вперёд ➡️",
                callback_data=(
                    f"admin_users_page:{offset + page_size}"
                ),
            )
        )


    if nav:

        rows.append(nav)


    search_row = [
        InlineKeyboardButton(
            text="🔍 Поиск",
            callback_data="admin_users_search",
        )
    ]

    if query:

        search_row.append(
            InlineKeyboardButton(
                text="✖️ Сброс",
                callback_data="admin_users_clear",
            )
        )

    rows.append(search_row)


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


def admin_providers_keyboard(
    providers: list,
):

    rows = []
    pair = []

    for item in providers:

        icon = (
            "🟢"
            if item["enabled"]
            else "🔴"
        )

        pair.append(
            InlineKeyboardButton(
                text=f"{icon} {item['name']}",
                callback_data=(
                    f"admin_prov_toggle:{item['name']}"
                ),
            )
        )

        if len(pair) == 2:
            rows.append(pair)
            pair = []

    if pair:
        rows.append(pair)

    rows.append(
        [
            InlineKeyboardButton(
                text="🔄 Изменить порядок",
                callback_data="admin_prov_order",
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


def referral_menu():

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


def chat_roles_keyboard(
    chats: list,
):

    rows = []

    for chat in chats:

        name = (
            chat["peer_name"]
            or (
                f"@{chat['username']}"
                if chat["username"]
                else f"ID {chat['chat_id']}"
            )
        )

        name = name[:28]

        icon = (
            "🎭"
            if chat["role"]
            else "💬"
        )

        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{icon} {name}",
                    callback_data=(
                        f"chat_role_set:{chat['chat_id']}"
                    ),
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="✏️ Ввести ID / username",
                callback_data="chat_role_manual",
            )
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Профиль",
                callback_data="profile",
            )
        ]
    )

    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def premium_buy_keyboard(
    week_price: int,
    month_price: int,
    manual_enabled: bool,
):

    rows = [
        [
            InlineKeyboardButton(
                text=f"⭐ Неделя — {week_price}⭐",
                callback_data="buy_premium:week",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"⭐ Месяц — {month_price}⭐",
                callback_data="buy_premium:month",
            )
        ],
    ]

    if manual_enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💳 Другой способ оплаты",
                    callback_data="manual_payment",
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


def manual_payment_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Premium",
                    callback_data="premium_buy",
                )
            ]
        ]
    )


def broadcast_confirm_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Отправить",
                    callback_data="broadcast_confirm",
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="broadcast_cancel",
                )
            ]
        ]
    )


def admin_premium_menu(
    settings: dict,
):

    manual_on = (
        settings.get(
            "manual_payment_enabled"
        )
        == "1"
    )

    manual_text = (
        "🟢 Ручной способ: вкл"
        if manual_on
        else "⚪ Ручной способ: выкл"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text=(
                        f"💰 Цена/нед: "
                        f"{settings['premium_price_week']}⭐"
                    ),
                    callback_data=(
                        "admin_edit:premium_price_week"
                    ),
                ),

                InlineKeyboardButton(
                    text=(
                        f"💰 Цена/мес: "
                        f"{settings['premium_price_month']}⭐"
                    ),
                    callback_data=(
                        "admin_edit:premium_price_month"
                    ),
                ),
            ],

            [
                InlineKeyboardButton(
                    text=(
                        f"🆓 FAQ Free: "
                        f"{settings['free_faq_limit']}"
                    ),
                    callback_data=(
                        "admin_edit:free_faq_limit"
                    ),
                ),

                InlineKeyboardButton(
                    text=(
                        f"⭐ FAQ Premium: "
                        f"{settings['premium_faq_limit']}"
                    ),
                    callback_data=(
                        "admin_edit:premium_faq_limit"
                    ),
                ),
            ],

            [
                InlineKeyboardButton(
                    text=(
                        f"🎭 Макс. ролей: "
                        f"{settings['max_chat_roles']}"
                    ),
                    callback_data=(
                        "admin_edit:max_chat_roles"
                    ),
                ),

                InlineKeyboardButton(
                    text=(
                        f"🆓 Ролей Free: "
                        f"{settings.get('free_chat_roles', '1')}"
                    ),
                    callback_data=(
                        "admin_edit:free_chat_roles"
                    ),
                ),
            ],

            [
                InlineKeyboardButton(
                    text=manual_text,
                    callback_data="admin_manual_pay_toggle",
                )
            ],

            [
                InlineKeyboardButton(
                    text="📝 Текст ручного способа",
                    callback_data=(
                        "admin_edit:manual_payment_text"
                    ),
                )
            ],

            [
                InlineKeyboardButton(
                    text="📣 Рекламная подпись",
                    callback_data=(
                        "admin_edit:promo_signature_text"
                    ),
                )
            ],

            [
                InlineKeyboardButton(
                    text=(
                        f"⏱ Интервал рассылки: "
                        f"{settings.get('broadcast_interval', '1')}с"
                    ),
                    callback_data=(
                        "admin_edit:broadcast_interval"
                    ),
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅️ Админ-панель",
                    callback_data="admin",
                )
            ],
        ]
    )
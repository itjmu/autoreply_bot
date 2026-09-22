from datetime import (
    datetime,
    timezone,
)

from zoneinfo import (
    ZoneInfo,
    ZoneInfoNotFoundError,
)

import aiosqlite


DB_PATH = "autoreply.db"


DEFAULT_SETTINGS = {

    "ai_global_enabled": "1",

    "free_ai_daily_limit": "5",

    "premium_ai_daily_limit": "25",

    "blocked_topics": "",

    "blocked_reply": (
        "По этой теме автоматический помощник "
        "не отвечает. Владелец сможет ответить лично."
    ),
}


def utc_day() -> str:

    return datetime.now(
        timezone.utc
    ).date().isoformat()


async def _column_exists(
    db,
    table: str,
    column: str,
) -> bool:

    cursor = await db.execute(
        f"PRAGMA table_info({table})"
    )

    rows = await cursor.fetchall()

    return any(
        row[1] == column
        for row in rows
    )


async def _add_column_if_missing(
    db,
    table: str,
    column: str,
    definition: str,
):

    if not await _column_exists(
        db,
        table,
        column,
    ):

        await db.execute(
            f"""
            ALTER TABLE {table}
            ADD COLUMN {column} {definition}
            """
        )


async def init_db():

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (

                telegram_id INTEGER PRIMARY KEY,

                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',

                owner_name TEXT DEFAULT '',
                age TEXT DEFAULT '',
                gender TEXT DEFAULT '',

                topics TEXT DEFAULT '',
                ai_description TEXT DEFAULT '',

                fallback_text TEXT DEFAULT
                'Спасибо за сообщение 👋 Владелец аккаунта ответит лично, как только сможет.',

                ai_enabled INTEGER DEFAULT 1,

                plan TEXT DEFAULT 'free'
            )
            """
        )


        await _add_column_if_missing(
            db,
            "users",
            "username",
            "TEXT DEFAULT ''",
        )

        await _add_column_if_missing(
            db,
            "users",
            "first_name",
            "TEXT DEFAULT ''",
        )

        await _add_column_if_missing(
            db,
            "users",
            "owner_name",
            "TEXT DEFAULT ''",
        )

        await _add_column_if_missing(
            db,
            "users",
            "age",
            "TEXT DEFAULT ''",
        )

        await _add_column_if_missing(
            db,
            "users",
            "gender",
            "TEXT DEFAULT ''",
        )

        await _add_column_if_missing(
            db,
            "users",
            "topics",
            "TEXT DEFAULT ''",
        )

        await _add_column_if_missing(
            db,
            "users",
            "ai_description",
            "TEXT DEFAULT ''",
        )

        await _add_column_if_missing(
            db,
            "users",
            "fallback_text",
            (
                "TEXT DEFAULT "
                "'Спасибо за сообщение 👋 Владелец аккаунта ответит лично, как только сможет.'"
            ),
        )

        await _add_column_if_missing(
            db,
            "users",
            "ai_enabled",
            "INTEGER DEFAULT 1",
        )

        await _add_column_if_missing(
            db,
            "users",
            "plan",
            "TEXT DEFAULT 'free'",
        )


        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS faq (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                owner_id INTEGER NOT NULL,

                question TEXT NOT NULL,
                answer TEXT NOT NULL,

                enabled INTEGER DEFAULT 1,

                created_at DATETIME
                DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS business_connections (

                connection_id TEXT PRIMARY KEY,

                owner_id INTEGER NOT NULL,

                enabled INTEGER DEFAULT 1
            )
            """
        )


        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS global_settings (

                key TEXT PRIMARY KEY,

                value TEXT NOT NULL
            )
            """
        )


        for key, value in (
            DEFAULT_SETTINGS.items()
        ):

            await db.execute(
                """
                INSERT OR IGNORE
                INTO global_settings (
                    key,
                    value
                )

                VALUES (?, ?)
                """,
                (
                    key,
                    value,
                ),
            )


        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_usage (

                owner_id INTEGER NOT NULL,

                day TEXT NOT NULL,

                used INTEGER DEFAULT 0,

                PRIMARY KEY (
                    owner_id,
                    day
                )
            )
            """
        )


        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_provider_stats (

                day TEXT NOT NULL,

                provider TEXT NOT NULL,

                attempts INTEGER DEFAULT 0,

                successes INTEGER DEFAULT 0,

                failures INTEGER DEFAULT 0,

                rate_limits INTEGER DEFAULT 0,

                last_error TEXT DEFAULT '',

                PRIMARY KEY (
                    day,
                    provider
                )
            )
            """
        )


        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_preferences (

                owner_id INTEGER PRIMARY KEY,

                autoreply_enabled INTEGER DEFAULT 1,

                primary_language TEXT DEFAULT 'Русский',

                secondary_language TEXT DEFAULT 'English',

                extra_languages TEXT DEFAULT '',

                timezone TEXT DEFAULT 'UTC',

                schedule_enabled INTEGER DEFAULT 0,

                schedule_start TEXT DEFAULT '09:00',

                schedule_end TEXT DEFAULT '18:00'
            )
            """
        )


        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_settings (

                owner_id INTEGER NOT NULL,

                chat_id INTEGER NOT NULL,

                enabled INTEGER DEFAULT 1,

                peer_name TEXT DEFAULT '',

                username TEXT DEFAULT '',

                last_seen DATETIME
                DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY (
                    owner_id,
                    chat_id
                )
            )
            """
        )


        await db.commit()


# =========================================================
# USERS
# =========================================================

async def ensure_user(
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
):

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            INSERT OR IGNORE
            INTO users (
                telegram_id
            )
            VALUES (?)
            """,
            (
                telegram_id,
            ),
        )


        if username is not None:

            await db.execute(
                """
                UPDATE users

                SET username = ?

                WHERE telegram_id = ?
                """,
                (
                    username,
                    telegram_id,
                ),
            )


        if first_name is not None:

            await db.execute(
                """
                UPDATE users

                SET first_name = ?

                WHERE telegram_id = ?
                """,
                (
                    first_name,
                    telegram_id,
                ),
            )


        await db.execute(
            """
            INSERT OR IGNORE
            INTO user_preferences (
                owner_id
            )
            VALUES (?)
            """,
            (
                telegram_id,
            ),
        )


        await db.commit()


async def get_profile(
    telegram_id: int,
):

    await ensure_user(
        telegram_id
    )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        db.row_factory = (
            aiosqlite.Row
        )


        cursor = await db.execute(
            """
            SELECT *

            FROM users

            WHERE telegram_id = ?
            """,
            (
                telegram_id,
            ),
        )


        row = await cursor.fetchone()


        return (
            dict(row)
            if row
            else None
        )


async def update_profile_field(
    telegram_id: int,
    field: str,
    value: str,
):

    allowed = {

        "owner_name",
        "age",
        "gender",
        "topics",
        "ai_description",
        "fallback_text",
    }


    if field not in allowed:

        raise ValueError(
            "Недопустимое поле профиля"
        )


    await ensure_user(
        telegram_id
    )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            f"""
            UPDATE users

            SET {field} = ?

            WHERE telegram_id = ?
            """,
            (
                value,
                telegram_id,
            ),
        )


        await db.commit()


async def toggle_ai(
    telegram_id: int,
):

    profile = await get_profile(
        telegram_id
    )


    new_value = (
        0
        if profile["ai_enabled"]
        else 1
    )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            UPDATE users

            SET ai_enabled = ?

            WHERE telegram_id = ?
            """,
            (
                new_value,
                telegram_id,
            ),
        )


        await db.commit()


    return bool(
        new_value
    )


async def toggle_user_plan(
    telegram_id: int,
):

    profile = await get_profile(
        telegram_id
    )


    new_plan = (
        "premium"
        if profile["plan"] == "free"
        else "free"
    )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            UPDATE users

            SET plan = ?

            WHERE telegram_id = ?
            """,
            (
                new_plan,
                telegram_id,
            ),
        )


        await db.commit()


    return new_plan


# =========================================================
# FAQ
# =========================================================

async def add_faq(
    owner_id: int,
    question: str,
    answer: str,
):

    await ensure_user(
        owner_id
    )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            INSERT INTO faq (
                owner_id,
                question,
                answer
            )

            VALUES (?, ?, ?)
            """,
            (
                owner_id,
                question,
                answer,
            ),
        )


        await db.commit()


async def get_faqs(
    owner_id: int,
):

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        db.row_factory = (
            aiosqlite.Row
        )


        cursor = await db.execute(
            """
            SELECT *

            FROM faq

            WHERE owner_id = ?
            AND enabled = 1

            ORDER BY id DESC
            """,
            (
                owner_id,
            ),
        )


        rows = await cursor.fetchall()


        return [
            dict(row)
            for row in rows
        ]


async def delete_faq(
    owner_id: int,
    faq_id: int,
):

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            DELETE FROM faq

            WHERE id = ?
            AND owner_id = ?
            """,
            (
                faq_id,
                owner_id,
            ),
        )


        await db.commit()


# =========================================================
# BUSINESS CONNECTIONS
# =========================================================

async def save_business_connection(
    connection_id: str,
    owner_id: int,
    enabled: bool,
):

    await ensure_user(
        owner_id
    )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            INSERT INTO business_connections (
                connection_id,
                owner_id,
                enabled
            )

            VALUES (?, ?, ?)

            ON CONFLICT(connection_id)

            DO UPDATE SET

                owner_id =
                    excluded.owner_id,

                enabled =
                    excluded.enabled
            """,
            (
                connection_id,
                owner_id,
                int(enabled),
            ),
        )


        await db.commit()


async def get_owner_by_connection(
    connection_id: str,
):

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        cursor = await db.execute(
            """
            SELECT owner_id

            FROM business_connections

            WHERE connection_id = ?
            AND enabled = 1
            """,
            (
                connection_id,
            ),
        )


        row = await cursor.fetchone()


        return (
            row[0]
            if row
            else None
        )


async def get_connections(
    owner_id: int,
):

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        db.row_factory = (
            aiosqlite.Row
        )


        cursor = await db.execute(
            """
            SELECT *

            FROM business_connections

            WHERE owner_id = ?
            """,
            (
                owner_id,
            ),
        )


        rows = await cursor.fetchall()


        return [
            dict(row)
            for row in rows
        ]


# =========================================================
# GLOBAL SETTINGS
# =========================================================

async def get_global_settings():

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        cursor = await db.execute(
            """
            SELECT key, value

            FROM global_settings
            """
        )


        rows = await cursor.fetchall()


    settings = dict(
        DEFAULT_SETTINGS
    )


    for key, value in rows:
        settings[key] = value


    return settings


async def set_global_setting(
    key: str,
    value: str,
):

    if key not in DEFAULT_SETTINGS:

        raise ValueError(
            "Неизвестная глобальная настройка"
        )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            INSERT INTO global_settings (
                key,
                value
            )

            VALUES (?, ?)

            ON CONFLICT(key)

            DO UPDATE SET

                value =
                    excluded.value
            """,
            (
                key,
                value,
            ),
        )


        await db.commit()


async def toggle_global_ai():

    settings = (
        await get_global_settings()
    )


    enabled = (
        settings[
            "ai_global_enabled"
        ]
        == "1"
    )


    new_value = (
        "0"
        if enabled
        else "1"
    )


    await set_global_setting(
        "ai_global_enabled",
        new_value,
    )


    return (
        new_value == "1"
    )


# =========================================================
# USER PREFERENCES
# =========================================================

async def get_preferences(
    owner_id: int,
):

    await ensure_user(
        owner_id
    )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        db.row_factory = (
            aiosqlite.Row
        )


        cursor = await db.execute(
            """
            SELECT *

            FROM user_preferences

            WHERE owner_id = ?
            """,
            (
                owner_id,
            ),
        )


        row = await cursor.fetchone()


        return dict(row)


async def set_preference(
    owner_id: int,
    field: str,
    value: str,
):

    allowed = {

        "primary_language",
        "secondary_language",
        "extra_languages",
        "timezone",
        "schedule_start",
        "schedule_end",
    }


    if field not in allowed:

        raise ValueError(
            "Недопустимая настройка"
        )


    await ensure_user(
        owner_id
    )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            f"""
            UPDATE user_preferences

            SET {field} = ?

            WHERE owner_id = ?
            """,
            (
                value,
                owner_id,
            ),
        )


        await db.commit()


async def toggle_autoreply(
    owner_id: int,
):

    prefs = await get_preferences(
        owner_id
    )


    new_value = (
        0
        if prefs[
            "autoreply_enabled"
        ]
        else 1
    )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            UPDATE user_preferences

            SET autoreply_enabled = ?

            WHERE owner_id = ?
            """,
            (
                new_value,
                owner_id,
            ),
        )


        await db.commit()


    return bool(
        new_value
    )


async def toggle_schedule(
    owner_id: int,
):

    prefs = await get_preferences(
        owner_id
    )


    new_value = (
        0
        if prefs[
            "schedule_enabled"
        ]
        else 1
    )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            UPDATE user_preferences

            SET schedule_enabled = ?

            WHERE owner_id = ?
            """,
            (
                new_value,
                owner_id,
            ),
        )


        await db.commit()


    return bool(
        new_value
    )


def validate_time(
    value: str,
) -> bool:

    try:

        datetime.strptime(
            value,
            "%H:%M",
        )

        return True

    except ValueError:

        return False


def validate_timezone(
    value: str,
) -> bool:

    try:

        ZoneInfo(
            value
        )

        return True

    except ZoneInfoNotFoundError:

        return False


def parse_extra_languages(
    value: str,
) -> list[str]:

    if not value:
        return []


    value = (
        value
        .replace("\n", ",")
        .replace(";", ",")
    )


    result = []


    for item in value.split(","):

        item = item.strip()

        if (
            item
            and item not in result
        ):

            result.append(
                item
            )


    return result


def get_allowed_languages(
    prefs: dict,
    plan: str,
):

    result = []


    for language in (

        prefs[
            "primary_language"
        ]
        or "Русский",

        prefs[
            "secondary_language"
        ]
        or "English",

    ):

        if language not in result:

            result.append(
                language
            )


    if plan == "premium":

        for language in (
            parse_extra_languages(
                prefs[
                    "extra_languages"
                ]
            )
        ):

            if language not in result:

                result.append(
                    language
                )


    return result


def schedule_is_active(
    prefs: dict,
) -> bool:

    if not prefs[
        "schedule_enabled"
    ]:

        return True


    timezone_name = (
        prefs["timezone"]
        or "UTC"
    )


    try:

        tz = ZoneInfo(
            timezone_name
        )

    except ZoneInfoNotFoundError:

        tz = ZoneInfo(
            "UTC"
        )


    now = datetime.now(
        tz
    )


    try:

        start = datetime.strptime(
            prefs[
                "schedule_start"
            ],
            "%H:%M",
        ).time()


        end = datetime.strptime(
            prefs[
                "schedule_end"
            ],
            "%H:%M",
        ).time()

    except ValueError:

        return True


    current = now.time()


    if start < end:

        return (
            start
            <= current
            < end
        )


    if start > end:

        return (
            current >= start
            or current < end
        )


    return True


# =========================================================
# CHAT SETTINGS
# =========================================================

async def remember_chat(
    owner_id: int,
    chat_id: int,
    peer_name: str = "",
    username: str = "",
):

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            INSERT INTO chat_settings (

                owner_id,
                chat_id,
                enabled,
                peer_name,
                username,
                last_seen
            )

            VALUES (
                ?, ?, 1, ?, ?,
                CURRENT_TIMESTAMP
            )

            ON CONFLICT(
                owner_id,
                chat_id
            )

            DO UPDATE SET

                peer_name =
                    excluded.peer_name,

                username =
                    excluded.username,

                last_seen =
                    CURRENT_TIMESTAMP
            """,
            (
                owner_id,
                chat_id,
                peer_name,
                username,
            ),
        )


        await db.commit()


async def get_chat_settings(
    owner_id: int,
    chat_id: int,
):

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        db.row_factory = (
            aiosqlite.Row
        )


        cursor = await db.execute(
            """
            SELECT *

            FROM chat_settings

            WHERE owner_id = ?
            AND chat_id = ?
            """,
            (
                owner_id,
                chat_id,
            ),
        )


        row = await cursor.fetchone()


        return (
            dict(row)
            if row
            else None
        )


async def toggle_chat(
    owner_id: int,
    chat_id: int,
):

    settings = (
        await get_chat_settings(
            owner_id,
            chat_id,
        )
    )


    if not settings:

        return None


    new_value = (
        0
        if settings["enabled"]
        else 1
    )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            UPDATE chat_settings

            SET enabled = ?

            WHERE owner_id = ?
            AND chat_id = ?
            """,
            (
                new_value,
                owner_id,
                chat_id,
            ),
        )


        await db.commit()


    return bool(
        new_value
    )


async def should_autoreply(
    owner_id: int,
    chat_id: int,
):

    prefs = await get_preferences(
        owner_id
    )


    if not prefs[
        "autoreply_enabled"
    ]:

        return (
            False,
            "global_off",
            prefs,
        )


    chat_settings = (
        await get_chat_settings(
            owner_id,
            chat_id,
        )
    )


    if (
        chat_settings
        and not chat_settings[
            "enabled"
        ]
    ):

        return (
            False,
            "chat_off",
            prefs,
        )


    if not schedule_is_active(
        prefs
    ):

        return (
            False,
            "schedule",
            prefs,
        )


    return (
        True,
        "ok",
        prefs,
    )


# =========================================================
# AI LIMITS
# =========================================================

async def _owner_usage_day(
    owner_id: int,
) -> str:

    prefs = await get_preferences(
        owner_id
    )


    timezone_name = (
        prefs["timezone"]
        or "UTC"
    )


    try:

        tz = ZoneInfo(
            timezone_name
        )

    except ZoneInfoNotFoundError:

        tz = ZoneInfo(
            "UTC"
        )


    return datetime.now(
        tz
    ).date().isoformat()


async def get_user_quota_status(
    owner_id: int,
):

    profile = await get_profile(
        owner_id
    )


    settings = (
        await get_global_settings()
    )


    day = await _owner_usage_day(
        owner_id
    )


    if profile["plan"] == "premium":

        limit = int(
            settings[
                "premium_ai_daily_limit"
            ]
        )

    else:

        limit = int(
            settings[
                "free_ai_daily_limit"
            ]
        )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        cursor = await db.execute(
            """
            SELECT used

            FROM ai_usage

            WHERE owner_id = ?
            AND day = ?
            """,
            (
                owner_id,
                day,
            ),
        )


        row = await cursor.fetchone()


    used = (
        row[0]
        if row
        else 0
    )


    return {

        "plan":
            profile["plan"],

        "used":
            used,

        "limit":
            limit,

        "remaining":
            max(
                limit - used,
                0,
            ),

        "global_enabled":
            settings[
                "ai_global_enabled"
            ]
            == "1",

        "user_enabled":
            bool(
                profile[
                    "ai_enabled"
                ]
            ),
    }


async def reserve_user_ai_slot(
    owner_id: int,
):

    profile = await get_profile(
        owner_id
    )


    settings = (
        await get_global_settings()
    )


    if (
        settings[
            "ai_global_enabled"
        ]
        != "1"
    ):

        return {
            "allowed": False,
            "reason": "global_off",
        }


    if not profile[
        "ai_enabled"
    ]:

        return {
            "allowed": False,
            "reason": "user_off",
        }


    day = await _owner_usage_day(
        owner_id
    )


    if profile["plan"] == "premium":

        limit = int(
            settings[
                "premium_ai_daily_limit"
            ]
        )

    else:

        limit = int(
            settings[
                "free_ai_daily_limit"
            ]
        )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            "BEGIN IMMEDIATE"
        )


        cursor = await db.execute(
            """
            SELECT used

            FROM ai_usage

            WHERE owner_id = ?
            AND day = ?
            """,
            (
                owner_id,
                day,
            ),
        )


        row = await cursor.fetchone()


        used = (
            row[0]
            if row
            else 0
        )


        if used >= limit:

            await db.rollback()


            return {

                "allowed": False,

                "reason":
                    "user_limit",

                "used":
                    used,

                "limit":
                    limit,
            }


        await db.execute(
            """
            INSERT INTO ai_usage (
                owner_id,
                day,
                used
            )

            VALUES (?, ?, 1)

            ON CONFLICT(
                owner_id,
                day
            )

            DO UPDATE SET

                used =
                    used + 1
            """,
            (
                owner_id,
                day,
            ),
        )


        await db.commit()


    return {

        "allowed": True,

        "used":
            used + 1,

        "limit":
            limit,
    }


async def release_user_ai_slot(
    owner_id: int,
):

    day = await _owner_usage_day(
        owner_id
    )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            UPDATE ai_usage

            SET used =

                CASE

                    WHEN used > 0
                    THEN used - 1

                    ELSE 0

                END

            WHERE owner_id = ?
            AND day = ?
            """,
            (
                owner_id,
                day,
            ),
        )


        await db.commit()


# =========================================================
# AI PROVIDER STATS
# =========================================================

async def record_provider_result(
    provider: str,
    success: bool,
    error_type: str | None = None,
    error: str | None = None,
):

    day = utc_day()


    failure = (
        0
        if success
        else 1
    )


    rate_limit = (
        1
        if error_type
        == "rate_limit"
        else 0
    )


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            INSERT INTO ai_provider_stats (

                day,
                provider,
                attempts,
                successes,
                failures,
                rate_limits,
                last_error
            )

            VALUES (?, ?, 1, ?, ?, ?, ?)

            ON CONFLICT(
                day,
                provider
            )

            DO UPDATE SET

                attempts =
                    attempts + 1,

                successes =
                    successes
                    + excluded.successes,

                failures =
                    failures
                    + excluded.failures,

                rate_limits =
                    rate_limits
                    + excluded.rate_limits,

                last_error =
                    excluded.last_error
            """,
            (
                day,
                provider,
                1 if success else 0,
                failure,
                rate_limit,
                (error or "")[:500],
            ),
        )


        await db.commit()


async def get_provider_stats_today():

    day = utc_day()


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        db.row_factory = (
            aiosqlite.Row
        )


        cursor = await db.execute(
            """
            SELECT *

            FROM ai_provider_stats

            WHERE day = ?

            ORDER BY attempts DESC
            """,
            (
                day,
            ),
        )


        rows = await cursor.fetchall()


        return [
            dict(row)
            for row in rows
        ]


# =========================================================
# ADMIN
# =========================================================

async def get_admin_stats():

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        cursor = await db.execute(
            """
            SELECT COUNT(*)

            FROM users
            """
        )

        users = (
            await cursor.fetchone()
        )[0]


        cursor = await db.execute(
            """
            SELECT COUNT(*)

            FROM users

            WHERE plan = 'premium'
            """
        )

        premium = (
            await cursor.fetchone()
        )[0]


        cursor = await db.execute(
            """
            SELECT COUNT(*)

            FROM faq

            WHERE enabled = 1
            """
        )

        faq_count = (
            await cursor.fetchone()
        )[0]


    provider_stats = (
        await get_provider_stats_today()
    )


    provider_attempts = sum(
        item["attempts"]
        for item in provider_stats
    )


    provider_successes = sum(
        item["successes"]
        for item in provider_stats
    )


    return {

        "users":
            users,

        "free_users":
            users - premium,

        "premium_users":
            premium,

        "faq_count":
            faq_count,

        "provider_attempts":
            provider_attempts,

        "provider_successes":
            provider_successes,
    }


async def get_users_for_admin(
    limit: int = 30,
):

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        db.row_factory = (
            aiosqlite.Row
        )


        cursor = await db.execute(
            """
            SELECT

                telegram_id,
                username,
                first_name,
                owner_name,
                plan,
                ai_enabled

            FROM users

            ORDER BY telegram_id DESC

            LIMIT ?
            """,
            (
                limit,
            ),
        )


        rows = await cursor.fetchall()


    users = []


    for row in rows:

        item = dict(
            row
        )


        quota = (
            await get_user_quota_status(
                item[
                    "telegram_id"
                ]
            )
        )


        item["ai_used"] = (
            quota["used"]
        )

        item["ai_limit"] = (
            quota["limit"]
        )


        users.append(
            item
        )


    return users


async def reset_daily_usage():

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        await db.execute(
            """
            DELETE FROM ai_usage
            """
        )


        await db.execute(
            """
            DELETE FROM ai_provider_stats
            """
        )


        await db.commit()
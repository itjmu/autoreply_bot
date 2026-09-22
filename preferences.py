import asyncio

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiosqlite


DB_PATH = "autoreply.db"

_initialized = False
_lock = asyncio.Lock()


# =========================================================
# DATABASE
# =========================================================

async def init_preferences():

    global _initialized

    if _initialized:
        return

    async with _lock:

        if _initialized:
            return

        async with aiosqlite.connect(DB_PATH) as db:

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

                    PRIMARY KEY (
                        owner_id,
                        chat_id
                    )
                )
                """
            )

            await db.commit()

        _initialized = True


# =========================================================
# USER SETTINGS
# =========================================================

async def get_preferences(
    owner_id: int,
):

    await init_preferences()

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute(
            """
            INSERT OR IGNORE
            INTO user_preferences (
                owner_id
            )
            VALUES (?)
            """,
            (owner_id,),
        )

        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            """
            SELECT *
            FROM user_preferences
            WHERE owner_id = ?
            """,
            (owner_id,),
        )

        row = await cursor.fetchone()

        await db.commit()

        return dict(row)


async def set_preference(
    owner_id: int,
    field: str,
    value,
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

    await get_preferences(owner_id)

    async with aiosqlite.connect(DB_PATH) as db:

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


# =========================================================
# FULL AUTOREPLY ON / OFF
# =========================================================

async def toggle_autoreply(
    owner_id: int,
):

    prefs = await get_preferences(
        owner_id
    )

    new_value = (
        0
        if prefs["autoreply_enabled"]
        else 1
    )

    async with aiosqlite.connect(DB_PATH) as db:

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

    return bool(new_value)


# =========================================================
# LANGUAGES
# =========================================================

def parse_extra_languages(
    value: str,
):

    if not value:
        return []

    value = (
        value
        .replace("\n", ",")
        .replace(";", ",")
    )

    result = []

    for item in value.split(","):

        language = item.strip()

        if (
            language
            and language not in result
        ):
            result.append(language)

    return result


def get_allowed_languages(
    prefs: dict,
    plan: str,
):

    languages = []

    primary = (
        prefs["primary_language"]
        or "Русский"
    )

    secondary = (
        prefs["secondary_language"]
        or "English"
    )

    for language in (
        primary,
        secondary,
    ):

        if language not in languages:
            languages.append(language)

    # Только Premium получает
    # дополнительные языки

    if plan == "premium":

        for language in parse_extra_languages(
            prefs["extra_languages"]
        ):

            if language not in languages:
                languages.append(language)

    return languages


# =========================================================
# TIMEZONE
# =========================================================

def validate_timezone(
    timezone_name: str,
):

    try:

        ZoneInfo(
            timezone_name
        )

        return True

    except ZoneInfoNotFoundError:

        return False


# =========================================================
# SCHEDULE
# =========================================================

def validate_time(
    value: str,
):

    try:

        datetime.strptime(
            value,
            "%H:%M",
        )

        return True

    except ValueError:

        return False


async def toggle_schedule(
    owner_id: int,
):

    prefs = await get_preferences(
        owner_id
    )

    new_value = (
        0
        if prefs["schedule_enabled"]
        else 1
    )

    async with aiosqlite.connect(DB_PATH) as db:

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

    return bool(new_value)


def schedule_is_active(
    prefs: dict,
):

    # График выключен = 24/7

    if not prefs[
        "schedule_enabled"
    ]:

        return True

    timezone_name = (
        prefs["timezone"]
        or "UTC"
    )

    try:

        timezone = ZoneInfo(
            timezone_name
        )

    except ZoneInfoNotFoundError:

        timezone = ZoneInfo(
            "UTC"
        )

    now = datetime.now(
        timezone
    )

    try:

        start = datetime.strptime(
            prefs["schedule_start"],
            "%H:%M",
        ).time()

        end = datetime.strptime(
            prefs["schedule_end"],
            "%H:%M",
        ).time()

    except ValueError:

        return True

    current = now.time()

    # Например:
    # 09:00 - 18:00

    if start < end:

        return (
            start
            <= current
            < end
        )

    # Например:
    # 20:00 - 08:00

    if start > end:

        return (
            current >= start
            or current < end
        )

    # Одинаковое время =
    # считаем режимом 24/7

    return True


# =========================================================
# BUSINESS CHAT
# =========================================================

async def remember_chat(
    owner_id: int,
    chat_id: int,
    peer_name: str = "",
    username: str = "",
):

    await init_preferences()

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute(
            """
            INSERT INTO chat_settings (

                owner_id,
                chat_id,
                enabled,
                peer_name,
                username
            )

            VALUES (?, ?, 1, ?, ?)

            ON CONFLICT(
                owner_id,
                chat_id
            )

            DO UPDATE SET

                peer_name =
                    excluded.peer_name,

                username =
                    excluded.username
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

    await remember_chat(
        owner_id,
        chat_id,
    )

    async with aiosqlite.connect(DB_PATH) as db:

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

        return dict(row)


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

    new_value = (
        0
        if settings["enabled"]
        else 1
    )

    async with aiosqlite.connect(DB_PATH) as db:

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

    return bool(new_value)


# =========================================================
# SHOULD BOT ANSWER?
# =========================================================

async def should_autoreply(
    owner_id: int,
    chat_id: int,
):

    prefs = await get_preferences(
        owner_id
    )

    # Полностью выключен

    if not prefs[
        "autoreply_enabled"
    ]:

        return False, "global_off", prefs

    # Конкретный клиент

    chat_settings = (
        await get_chat_settings(
            owner_id,
            chat_id,
        )
    )

    if not chat_settings[
        "enabled"
    ]:

        return False, "chat_off", prefs

    # График

    if not schedule_is_active(
        prefs
    ):

        return False, "schedule", prefs

    return True, "ok", prefs
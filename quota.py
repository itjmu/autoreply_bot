from datetime import (
    datetime,
    timezone,
)

import aiosqlite


from database import (
    DB_PATH,
    get_global_settings,
    get_profile,
)


def today() -> str:

    return (
        datetime.now(
            timezone.utc
        )
        .date()
        .isoformat()
    )


async def get_user_quota_status(
    owner_id: int,
):

    profile = await get_profile(
        owner_id
    )

    settings = (
        await get_global_settings()
    )


    if profile[
        "plan"
    ] == "premium":

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
                today(),
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
            ] == "1",

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

    quota = (
        await get_user_quota_status(
            owner_id
        )
    )


    if not quota[
        "global_enabled"
    ]:

        return {

            "allowed": False,

            "reason":
                "global_off",
        }


    if not quota[
        "user_enabled"
    ]:

        return {

            "allowed": False,

            "reason":
                "user_off",
        }


    if (
        quota["used"]
        >= quota["limit"]
    ):

        return {

            "allowed": False,

            "reason":
                "user_limit",

            "used":
                quota["used"],

            "limit":
                quota["limit"],
        }


    async with aiosqlite.connect(
        DB_PATH
    ) as db:

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
                used = used + 1
            """,
            (
                owner_id,
                today(),
            ),
        )


        await db.commit()


    return {

        "allowed": True,

        "used":
            quota["used"] + 1,

        "limit":
            quota["limit"],
    }


async def release_user_ai_slot(
    owner_id: int,
):

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
                today(),
            ),
        )


        await db.commit()
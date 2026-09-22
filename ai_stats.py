from datetime import (
    datetime,
    timezone,
)

import aiosqlite


DB_PATH = "autoreply.db"


async def init_ai_stats():

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

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


        await db.commit()


async def record_provider_result(
    provider: str,
    success: bool,
    error_type: str | None = None,
    error: str | None = None,
):

    await init_ai_stats()


    day = (
        datetime.now(
            timezone.utc
        )
        .date()
        .isoformat()
    )


    failure = (
        0 if success else 1
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
                error or "",
            ),
        )


        await db.commit()


async def get_provider_stats_today():

    await init_ai_stats()


    day = (
        datetime.now(
            timezone.utc
        )
        .date()
        .isoformat()
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
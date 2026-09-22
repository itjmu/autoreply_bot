import aiohttp


from ai.result import (
    AIResult,
)


def classify_status(
    status: int,
) -> str:

    if status == 429:
        return "rate_limit"

    if status in {
        401,
        403,
    }:
        return "auth"

    if status == 402:
        return "quota"

    if status >= 500:
        return "server"

    return "request"


def extract_text(
    data: dict,
) -> str | None:

    choices = data.get(
        "choices",
        [],
    )


    if not choices:
        return None


    message = (
        choices[0]
        .get(
            "message",
            {},
        )
    )


    content = message.get(
        "content"
    )


    if isinstance(
        content,
        str,
    ):

        result = (
            content.strip()
        )

        return (
            result
            if result
            else None
        )


    if isinstance(
        content,
        list,
    ):

        parts = []


        for item in content:

            if not isinstance(
                item,
                dict,
            ):
                continue


            text = item.get(
                "text"
            )


            if text:

                parts.append(
                    str(text)
                )


        result = (
            "\n".join(parts)
            .strip()
        )


        return (
            result
            if result
            else None
        )


    return None


async def call_openai_compatible(
    *,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    system_prompt: str,
    user_text: str,
    timeout_seconds: float,
    max_tokens: int,
):

    url = (
        f"{base_url.rstrip('/')}"
        "/chat/completions"
    )


    headers = {

        "Authorization":
            f"Bearer {api_key}",

        "Content-Type":
            "application/json",
    }


    payload = {

        "model":
            model,

        "messages": [

            {
                "role": "system",
                "content": system_prompt,
            },

            {
                "role": "user",
                "content": user_text,
            },
        ],

        "temperature":
            0.25,

        "max_tokens":
            max_tokens,
    }


    timeout = aiohttp.ClientTimeout(
        total=timeout_seconds
    )


    try:

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.post(
                url,
                headers=headers,
                json=payload,
            ) as response:

                status = (
                    response.status
                )


                if status != 200:

                    body = (
                        await response.text()
                    )


                    return AIResult(

                        ok=False,

                        provider=provider,

                        model=model,

                        status_code=status,

                        error_type=(
                            classify_status(
                                status
                            )
                        ),

                        error=body[:500],
                    )


                data = (
                    await response.json(
                        content_type=None
                    )
                )


        text = extract_text(
            data
        )


        if not text:

            return AIResult(

                ok=False,

                provider=provider,

                model=model,

                error_type="empty",

                error=(
                    "Провайдер вернул "
                    "пустой ответ"
                ),
            )


        return AIResult(

            ok=True,

            text=text,

            provider=provider,

            model=model,
        )


    except TimeoutError:

        return AIResult(

            ok=False,

            provider=provider,

            model=model,

            error_type="timeout",

            error="Timeout",
        )


    except aiohttp.ClientError as error:

        return AIResult(

            ok=False,

            provider=provider,

            model=model,

            error_type="connection",

            error=str(error),
        )


    except Exception as error:

        return AIResult(

            ok=False,

            provider=provider,

            model=model,

            error_type="unknown",

            error=str(error),
        )
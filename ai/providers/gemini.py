import aiohttp


from ai.result import (
    AIResult,
)


def classify_status(
    status: int,
):

    if status == 429:
        return "rate_limit"

    if status in {
        401,
        403,
    }:
        return "auth"

    if status >= 500:
        return "server"

    return "request"


async def call_gemini(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_text: str,
    timeout_seconds: float,
    max_tokens: int,
):

    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{model}:generateContent"
    )


    headers = {

        "Content-Type":
            "application/json",

        "x-goog-api-key":
            api_key,
    }


    payload = {

        "systemInstruction": {

            "parts": [
                {
                    "text":
                        system_prompt
                }
            ]
        },


        "contents": [

            {
                "role": "user",

                "parts": [
                    {
                        "text":
                            user_text
                    }
                ],
            }
        ],


        "generationConfig": {

            "temperature":
                0.25,

            "maxOutputTokens":
                max_tokens,
        },
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

                        provider="gemini",

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


        candidates = data.get(
            "candidates",
            [],
        )


        if not candidates:

            return AIResult(

                ok=False,

                provider="gemini",

                model=model,

                error_type="empty",

                error=(
                    "Gemini не вернул candidates"
                ),
            )


        parts = (
            candidates[0]
            .get(
                "content",
                {},
            )
            .get(
                "parts",
                [],
            )
        )


        texts = []


        for part in parts:

            text = part.get(
                "text"
            )


            if text:

                texts.append(
                    text
                )


        answer = (
            "\n".join(texts)
            .strip()
        )


        if not answer:

            return AIResult(

                ok=False,

                provider="gemini",

                model=model,

                error_type="empty",

                error="Пустой ответ Gemini",
            )


        return AIResult(

            ok=True,

            text=answer,

            provider="gemini",

            model=model,
        )


    except TimeoutError:

        return AIResult(

            ok=False,

            provider="gemini",

            model=model,

            error_type="timeout",

            error="Timeout",
        )


    except aiohttp.ClientError as error:

        return AIResult(

            ok=False,

            provider="gemini",

            model=model,

            error_type="connection",

            error=str(error),
        )


    except Exception as error:

        return AIResult(

            ok=False,

            provider="gemini",

            model=model,

            error_type="unknown",

            error=str(error),
        )
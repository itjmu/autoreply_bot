import aiohttp


from ai.result import (
    AIResult,
)


async def call_openai(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_text: str,
    timeout_seconds: float,
    max_tokens: int,
):

    url = (
        "https://api.openai.com/v1/responses"
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

        "instructions":
            system_prompt,

        "input":
            user_text,

        "max_output_tokens":
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


                    if status == 429:

                        error_type = (
                            "rate_limit"
                        )

                    elif status in {
                        401,
                        403,
                    }:

                        error_type = "auth"

                    elif status == 402:

                        error_type = "quota"

                    elif status >= 500:

                        error_type = "server"

                    else:

                        error_type = "request"


                    return AIResult(

                        ok=False,

                        provider="openai",

                        model=model,

                        status_code=status,

                        error_type=error_type,

                        error=body[:500],
                    )


                data = (
                    await response.json(
                        content_type=None
                    )
                )


        texts = []


        for item in data.get(
            "output",
            [],
        ):

            for content in item.get(
                "content",
                [],
            ):

                text = content.get(
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

                provider="openai",

                model=model,

                error_type="empty",
            )


        return AIResult(

            ok=True,

            text=answer,

            provider="openai",

            model=model,
        )


    except TimeoutError:

        return AIResult(

            ok=False,

            provider="openai",

            model=model,

            error_type="timeout",
        )


    except Exception as error:

        return AIResult(

            ok=False,

            provider="openai",

            model=model,

            error_type="unknown",

            error=str(error),
        )
import logging
import time


from ai.result import (
    AIResult,
)

from ai.providers.gemini import (
    call_gemini,
)

from ai.providers.openai_compatible import (
    call_openai_compatible,
)

from ai.providers.openai_provider import (
    call_openai,
)

from ai_stats import (
    record_provider_result,
)

from config import (
    AI_MAX_TOKENS,
    AI_PROVIDER_COOLDOWN,
    AI_PROVIDER_ORDER,
    AI_TIMEOUT,
    CUSTOM_PROVIDERS,
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
)


logger = logging.getLogger(
    "AIManager"
)


cooldowns: dict[
    str,
    float,
] = {}


def configured_providers():

    providers = {}


    if (
        OPENROUTER_API_KEY
        and OPENROUTER_MODEL
    ):

        providers[
            "openrouter"
        ] = {

            "type":
                "compatible",

            "api_key":
                OPENROUTER_API_KEY,

            "base_url":
                "https://openrouter.ai/api/v1",

            "model":
                OPENROUTER_MODEL,
        }


    if (
        GEMINI_API_KEY
        and GEMINI_MODEL
    ):

        providers[
            "gemini"
        ] = {

            "type":
                "gemini",

            "api_key":
                GEMINI_API_KEY,

            "model":
                GEMINI_MODEL,
        }


    if (
        GROQ_API_KEY
        and GROQ_MODEL
    ):

        providers[
            "groq"
        ] = {

            "type":
                "compatible",

            "api_key":
                GROQ_API_KEY,

            "base_url":
                "https://api.groq.com/openai/v1",

            "model":
                GROQ_MODEL,
        }


    if (
        DEEPSEEK_API_KEY
        and DEEPSEEK_MODEL
    ):

        providers[
            "deepseek"
        ] = {

            "type":
                "compatible",

            "api_key":
                DEEPSEEK_API_KEY,

            "base_url":
                "https://api.deepseek.com",

            "model":
                DEEPSEEK_MODEL,
        }


    if (
        OPENAI_API_KEY
        and OPENAI_MODEL
    ):

        providers[
            "openai"
        ] = {

            "type":
                "openai",

            "api_key":
                OPENAI_API_KEY,

            "model":
                OPENAI_MODEL,
        }


    # ======================================
    # CUSTOM PROVIDERS
    # ======================================

    for provider in (
        CUSTOM_PROVIDERS
    ):

        providers[
            provider["name"]
        ] = {

            "type":
                "compatible",

            "api_key":
                provider["api_key"],

            "base_url":
                provider["base_url"],

            "model":
                provider["model"],
        }


    return providers


def provider_in_cooldown(
    provider: str,
):

    until = cooldowns.get(
        provider,
        0,
    )


    return (
        until
        > time.monotonic()
    )


def set_cooldown(
    provider: str,
):

    cooldowns[
        provider
    ] = (
        time.monotonic()
        + AI_PROVIDER_COOLDOWN
    )


async def call_provider(
    name: str,
    config: dict,
    system_prompt: str,
    user_text: str,
):

    provider_type = (
        config["type"]
    )


    if provider_type == "gemini":

        return await call_gemini(

            api_key=(
                config["api_key"]
            ),

            model=(
                config["model"]
            ),

            system_prompt=(
                system_prompt
            ),

            user_text=(
                user_text
            ),

            timeout_seconds=(
                AI_TIMEOUT
            ),

            max_tokens=(
                AI_MAX_TOKENS
            ),
        )


    if provider_type == "openai":

        return await call_openai(

            api_key=(
                config["api_key"]
            ),

            model=(
                config["model"]
            ),

            system_prompt=(
                system_prompt
            ),

            user_text=(
                user_text
            ),

            timeout_seconds=(
                AI_TIMEOUT
            ),

            max_tokens=(
                AI_MAX_TOKENS
            ),
        )


    return await call_openai_compatible(

        provider=name,

        api_key=(
            config["api_key"]
        ),

        base_url=(
            config["base_url"]
        ),

        model=(
            config["model"]
        ),

        system_prompt=(
            system_prompt
        ),

        user_text=(
            user_text
        ),

        timeout_seconds=(
            AI_TIMEOUT
        ),

        max_tokens=(
            AI_MAX_TOKENS
        ),
    )


async def generate(
    system_prompt: str,
    user_text: str,
) -> AIResult:

    providers = (
        configured_providers()
    )


    if not providers:

        return AIResult(

            ok=False,

            error_type=(
                "no_providers"
            ),

            error=(
                "Нет настроенных AI-провайдеров"
            ),
        )


    # Сначала порядок из .env

    provider_order = list(
        AI_PROVIDER_ORDER
    )


    # Добавляем custom,
    # если забыли написать их в order.

    for name in providers:

        if name not in provider_order:

            provider_order.append(
                name
            )


    last_result = None


    for name in provider_order:

        config = providers.get(
            name
        )


        if not config:
            continue


        if provider_in_cooldown(
            name
        ):

            logger.info(
                "⏭ %s временно пропущен "
                "из-за cooldown",
                name,
            )

            continue


        logger.info(
            "🧠 Пробуем AI: %s / %s",
            name,
            config["model"],
        )


        result = await call_provider(

            name=name,

            config=config,

            system_prompt=system_prompt,

            user_text=user_text,
        )


        last_result = result


        await record_provider_result(

            provider=name,

            success=result.ok,

            error_type=(
                result.error_type
            ),

            error=(
                result.error
            ),
        )


        if result.ok:

            logger.info(
                "✅ Ответил %s",
                name,
            )

            return result


        logger.warning(

            "❌ %s не сработал: %s | %s",

            name,

            result.error_type,

            result.status_code,
        )


        # Такие проблемы обычно
        # не стоит проверять снова
        # при каждом сообщении.

        if result.error_type in {

            "rate_limit",
            "quota",
            "auth",
            "server",
            "timeout",
            "connection",
            "request",
        }:

            set_cooldown(
                name
            )


    return (
        last_result

        or AIResult(
            ok=False,
            error_type="all_failed",
        )
    )
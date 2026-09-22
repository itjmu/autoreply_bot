import os

from dotenv import load_dotenv


load_dotenv()


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

USE_AI = os.getenv("USE_AI", "true").lower() == "true"
AI_TIMEOUT = float(os.getenv("AI_TIMEOUT", "40"))
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "350"))

AI_PROVIDER_COOLDOWN = int(
    os.getenv(
        "AI_PROVIDER_COOLDOWN",
        "900",
    )
)


AI_PROVIDER_ORDER = [
    item.strip().lower()
    for item in os.getenv(
        "AI_PROVIDER_ORDER",
        "openrouter,gemini,groq,deepseek,openai",
    ).split(",")
    if item.strip()
]


# ==========================================
# OPENROUTER
# ==========================================

OPENROUTER_API_KEY = os.getenv(
    "OPENROUTER_API_KEY",
    "",
).strip()

OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "openrouter/free",
).strip()


# ==========================================
# GEMINI
# ==========================================

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY",
    "",
).strip()

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-2.5-flash-lite",
).strip()


# ==========================================
# GROQ
# ==========================================

GROQ_API_KEY = os.getenv(
    "GROQ_API_KEY",
    "",
).strip()

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-20b",
).strip()


# ==========================================
# DEEPSEEK
# ==========================================

DEEPSEEK_API_KEY = os.getenv(
    "DEEPSEEK_API_KEY",
    "",
).strip()

DEEPSEEK_MODEL = os.getenv(
    "DEEPSEEK_MODEL",
    "deepseek-v4-flash",
).strip()


# ==========================================
# OPENAI
# ==========================================

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY",
    "",
).strip()

OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "",
).strip()


# ==========================================
# CUSTOM PROVIDERS
# ==========================================

CUSTOM_PROVIDERS = []


for number in range(1, 6):

    prefix = f"CUSTOM{number}"

    name = os.getenv(
        f"{prefix}_NAME",
        "",
    ).strip().lower()

    api_key = os.getenv(
        f"{prefix}_API_KEY",
        "",
    ).strip()

    base_url = os.getenv(
        f"{prefix}_BASE_URL",
        "",
    ).strip()

    model = os.getenv(
        f"{prefix}_MODEL",
        "",
    ).strip()

    if (
        name
        and api_key
        and base_url
        and model
    ):
        CUSTOM_PROVIDERS.append(
            {
                "name": name,
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
            }
        )


AUTO_REPLY_DELAY = float(
    os.getenv(
        "AUTO_REPLY_DELAY",
        "1.5",
    )
)

FAQ_MATCH_THRESHOLD = float(
    os.getenv(
        "FAQ_MATCH_THRESHOLD",
        "0.78",
    )
)


def parse_admin_ids(
    value: str,
) -> set[int]:

    result = set()

    for item in value.split(","):

        item = item.strip()

        if item.isdigit():
            result.add(
                int(item)
            )

    return result


ADMIN_IDS = parse_admin_ids(
    os.getenv(
        "ADMIN_IDS",
        "",
    )
)


if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN отсутствует в .env"
    )
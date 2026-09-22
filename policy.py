import re


def normalize(
    text: str,
) -> str:

    text = text.lower()

    text = re.sub(
        r"[^\w\s]",
        " ",
        text,
        flags=re.UNICODE,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def parse_blocked_topics(
    value: str,
) -> list[str]:

    if not value:
        return []

    value = (
        value
        .replace("\n", ",")
        .replace(";", ",")
    )

    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]


def find_blocked_topic(
    text: str,
    blocked_value: str,
) -> str | None:

    normalized_text = normalize(
        text
    )

    for topic in parse_blocked_topics(
        blocked_value
    ):

        normalized_topic = normalize(
            topic
        )

        if (
            normalized_topic
            and normalized_topic
            in normalized_text
        ):
            return topic

    return None
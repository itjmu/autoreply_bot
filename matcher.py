import re

from difflib import SequenceMatcher


def normalize_text(
    text: str,
) -> str:

    text = text.lower().strip()

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


def similarity(
    first: str,
    second: str,
) -> float:

    first = normalize_text(
        first
    )

    second = normalize_text(
        second
    )

    if not first or not second:
        return 0.0

    if first == second:
        return 1.0

    if (
        len(first) >= 5
        and first in second
    ):
        return 0.95

    if (
        len(second) >= 5
        and second in first
    ):
        return 0.95

    return SequenceMatcher(
        None,
        first,
        second,
    ).ratio()


def find_direct_answer(
    user_text: str,
    faqs: list,
    threshold: float,
):

    best_item = None
    best_score = 0.0

    for item in faqs:

        score = similarity(
            user_text,
            item["question"],
        )

        if score > best_score:
            best_score = score
            best_item = item

    if (
        best_item
        and best_score >= threshold
    ):
        return (
            best_item["answer"],
            best_score,
        )

    return (
        None,
        best_score,
    )


def select_ai_context(
    user_text: str,
    faqs: list,
    limit: int = 6,
):

    scored = []

    for item in faqs:

        score = similarity(
            user_text,
            item["question"],
        )

        scored.append(
            (
                score,
                item,
            )
        )

    scored.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return [
        item
        for _, item in scored[:limit]
    ]
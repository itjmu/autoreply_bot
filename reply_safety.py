"""Remove explicitly tagged reasoning; reject untagged internal analysis as a whole."""

import re

_PAIR = re.compile(r"<\s*(reasoning|think|analysis)\s*>.*?<\s*/\s*\1\s*>", re.I | re.S)
_TAG = re.compile(r"<\s*/?\s*(?:reasoning|think|analysis)\s*>", re.I)
_MARKERS = (
    "the user sent",
    "the user is",
    "the user asks",
    "the user wants",
    "i should respond",
    "i should reply",
    "i should not pretend",
    "i need to respond",
    "i need to reply",
    "i need to identify the language",
    "let's analyze the message",
    "let’s analyze the message",
    "main instructions",
    "main instruction block",
    "system prompt",
    "according to the rules",
    "according to rule",
    "the priority list",
    "user safety:",
    "user safety :",
    "as an ai",
    "as an assistant",
    "rule 7",
    "rule 8",
    "rule 5",
    "внутренние рассуждения",
    "сначала проанализируем сообщение",
    "согласно системной инструкции",
)


def looks_like_reasoning(text):
    lowered = (text or "").casefold()
    return bool(_TAG.search(lowered)) or any(marker in lowered for marker in _MARKERS)


def sanitize_reply(text):
    cleaned = _PAIR.sub("", text or "")
    cleaned = re.split(
        r"<\s*(?:reasoning|think|analysis)\s*>", cleaned, maxsplit=1, flags=re.I
    )[0]
    cleaned = _TAG.sub("", cleaned).strip()
    # Strip a stray confirmation footer, preserving a standalone acknowledgement.
    cleaned = re.sub(r"\n\s*(?:ok|ок)[.!]?\s*$", "", cleaned, flags=re.I).strip()
    return "" if looks_like_reasoning(cleaned) else cleaned

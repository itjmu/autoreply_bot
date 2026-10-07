"""Conservative detection of conversational acknowledgements, without an AI call."""

import re
import unicodedata

_WORDS = re.compile(r"\w+", re.UNICODE)
_ACK_WORDS = {
    "ок",
    "окей",
    "оке",
    "океи",
    "ok",
    "okay",
    "окидоки",
    "хорошо",
    "понятно",
    "понял",
    "поняла",
    "поняли",
    "понимаю",
    "ясно",
    "принял",
    "приняла",
    "принято",
    "договорились",
    "ладно",
    "ладненько",
    "спасибо",
    "благодарю",
    "подожду",
    "подождем",
    "жду",
    "ожидаю",
    "согласен",
    "согласна",
    "да",
    "ага",
    "угу",
    "sure",
    "thanks",
    "thank",
    "you",
    "understood",
    "got",
    "it",
    "фаҳмо",
    "фахмо",
    "хуб",
    "ташаккур",
    "рахмат",
    "интизор",
    "мешавам",
    "rahmat",
    "tushunarli",
    "xop",
    "hop",
    "хоп",
    "kutaman",
    "я",
    "тогда",
    "буду",
    "ждать",
    "вас",
    "вашего",
    "ответа",
    "его",
    "владельца",
    "большое",
    "очень",
    "ну",
    "все",
    "за",
    "ответ",
    "информацию",
}
_ACK_CORE = _ACK_WORDS - {
    "я",
    "тогда",
    "буду",
    "ждать",
    "вас",
    "вашего",
    "ответа",
    "его",
    "владельца",
    "большое",
    "очень",
    "ну",
    "все",
    "за",
    "ответ",
    "информацию",
    "you",
    "got",
    "it",
    "thank",
    "мешавам",
}
_ACK_EMOJI = {"👍", "👌", "🤝", "🙏", "✅"}
_REQUEST = re.compile(
    r"\b(?:уточните|уточни|напишите|напиши|скажите|скажи|выберите|выбери|подтвердите|подтверди|пришлите|пришли|укажите|укажи|сообщите|сообщи|отправьте|отправь|please\s+(?:tell|send|choose|confirm|provide))\b",
    re.I,
)


def is_acknowledgement(text):
    text = (
        unicodedata.normalize("NFKC", text or "").casefold().replace("ё", "е").strip()
    )
    text = re.sub(r"(?<=\w)['’ʻ](?=\w)", "", text)
    # Any question punctuation or substantive extra word keeps normal reply handling.
    if not text or "?" in text or "？" in text or len(text) > 150:
        return False
    words = _WORDS.findall(text)
    if not words:
        emojis = [
            ch
            for ch in text
            if ch not in {"\ufe0f", "\u200d"}
            and not ch.isspace()
            and not 0x1F3FB <= ord(ch) <= 0x1F3FF
        ]
        return bool(emojis) and all(ch in _ACK_EMOJI for ch in emojis)
    if len(words) > 12 or not all(word in _ACK_WORDS for word in words):
        return False
    return bool(set(words) & _ACK_CORE) or " ".join(words) in {
        "thank you",
        "got it",
        "буду ждать",
    }


def should_silence_acknowledgement(text, previous_reply):
    if not previous_reply or not is_acknowledgement(text):
        return False
    # A short answer to the assistant's clarifying question may be meaningful.
    if (
        "?" in previous_reply
        or "？" in previous_reply
        or _REQUEST.search(previous_reply)
    ):
        return False
    return True

"""Explicit FAQ silence and bounded response delays."""
import json
import re


def payload(faq):
    return json.loads(faq.get("answer_payload") or "{}")


def valid_command(value):
    return isinstance(value, str) and re.fullmatch(r"/[a-z][a-z0-9_]{0,31}", value) is not None


def validate_delay(value, maximum=60):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"Delay must be 1–{maximum} seconds")
    return value


def mode_delay(settings, mode, source, faq=None):
    maximum = 3600 if mode == "business" else 60
    if faq is not None:
        value = payload(faq).get("delay", 1)
    else:
        field = source + "_delay"
        value = settings.get(field if mode == "business" else "personal_" + field, 1)
    return min(maximum, max(1, value))


def mode_faq(faq, mode):
    """Use only the first answer in Personal; preserve the shared stored FAQ."""
    if mode == "business":
        return faq
    result = dict(faq)
    data = payload(result)
    while result.get("answer_type") == "sequence":
        first = data["items"][0]
        result.update(answer_type=first["type"], answer=first.get("text", ""), answer_file_id=first.get("file_id", ""), answer_entities=json.dumps(first.get("entities", [])), answer_payload=json.dumps(first.get("payload", {})))
        data = payload(result)
    data.pop("buttons", None)
    data.pop("button_rows", None)
    result["answer_payload"] = json.dumps(data)
    return result


def match_faq(text, faqs, threshold, allow_commands=True):
    from matcher import find_direct_answer
    if text.startswith("/") and allow_commands:
        command = text.strip().lower()
        match = next((f for f in faqs if payload(f).get("command") == command), None)
        if match:
            return match, 1.0
    def normalize(value):
        return " ".join(re.findall(r"\w+", value.casefold())) or value.casefold().strip()
    for faq in faqs:
        if payload(faq).get("ignore") and normalize(text) == normalize(faq["question"]):
            return faq, 1.0
    return find_direct_answer(text, [f for f in faqs if not payload(f).get("ignore")], threshold)

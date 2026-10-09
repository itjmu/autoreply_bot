"""Validated FAQ button rows and compact menu presentation."""

def validate_rows(rows, count):
    if not isinstance(rows, list) or not rows or any(not isinstance(row, list) or not 1 <= len(row) <= 3 for row in rows):
        raise ValueError("Use 1–3 buttons per row")
    flat = [index for row in rows for index in row]
    if any(type(index) is not int for index in flat) or sorted(flat) != list(range(count)):
        raise ValueError("Each button must appear exactly once")
    return rows


def parse_rows(text, count):
    rows = [[int(number) - 1 for number in line.split()] for line in text.strip().splitlines()]
    return validate_rows(rows, count)


def button_rows(payload):
    buttons = payload.get("buttons", [])
    if not buttons:
        return []
    rows = payload.get("button_rows")
    if rows is None:
        rows = [list(range(index, min(index + 2, len(buttons)))) for index in range(0, len(buttons), 2)]
    return [[buttons[index] for index in row] for row in validate_rows(rows, len(buttons))]


_ICONS = {"faqs": "📚", "faq_add": "➕", "faq_extra": "➕", "faq_button_types": "🔘", "faq_buttons": "🔗", "faq_command": "⌨️", "faq_command_button": "⌨️", "faq_layout": "▦", "faq_preview": "👁", "settings": "⚙️", "advanced": "🛠", "export": "📤", "import": "📥", "setup": "🧭", "interface": "👤", "account": "👤", "premium": "⭐", "referrals": "🎁", "connect": "🔌", "knowledge": "📚", "details": "📝", "fallbacks": "💬", "reports": "📅", "report_edit": "🕒", "requests": "📋", "collect": "📥", "stats": "📊", "schedule": "🕒", "schedule_toggle": "🕒", "test": "🧪", "templates": "🧩", "suggestions": "💡", "undo": "↩️"}


def faq_rows(faqs, prefix="ux:faq:"):
    """Keep the original order; pack short labels without mixing widths."""
    rows, current, width = [], [], None
    for faq in faqs:
        label = faq["question"][:50]
        columns = 3 if len(faq["question"]) < 10 else 2 if len(faq["question"]) < 16 else 1
        if current and (width != columns or len(current) == width):
            rows.append(current)
            current = []
        width = columns
        current.append((label, f"{prefix}{faq['id']}"))
    if current:
        rows.append(current)
    return rows


def menu_rows(rows):
    result, pending = [], []
    def flush():
        if pending:
            result.append(pending.copy())
            pending.clear()
    for row in rows:
        decorated = []
        for label, data in row:
            action = data[3:].split(":")[0] if data.startswith("ux:") else ""
            icon = _ICONS.get(action)
            if icon and label and (label[0].isalnum() or label[0] == "+"):
                label = icon + " " + label
            decorated.append((label, data))
        # Leave navigation, toggles and confirmation controls on their own row.
        single = len(decorated) == 1 and len(decorated[0][0]) <= 30 and decorated[0][1].startswith("ux:") and decorated[0][1][3:].split(":")[0] in _ICONS and decorated[0][1] not in {"ux:settings", "ux:undo"}
        if single:
            pending.extend(decorated)
            if len(pending) == 2:
                flush()
        else:
            flush()
            if len(decorated) > 2 and any(len(label) > 20 for label, _ in decorated):
                result.extend(decorated[index:index + 2] for index in range(0, len(decorated), 2))
            else:
                result.append(decorated)
    flush()
    return result

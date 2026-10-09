"""Additive schema and owner-scoped operations; never replace existing user data."""

import json
import secrets
from datetime import datetime, timedelta, timezone

import aiosqlite
import database as db


SCHEMA_VERSION = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS fsm_state(storage_key TEXT PRIMARY KEY,state TEXT,data TEXT DEFAULT '{}',updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS owner_options(owner_id INTEGER PRIMARY KEY, language TEXT DEFAULT 'ru', setup_done INTEGER DEFAULT 0, collect_requests INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS handoffs(owner_id INTEGER, chat_id INTEGER, paused INTEGER DEFAULT 1, reason TEXT DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(owner_id,chat_id));
CREATE TABLE IF NOT EXISTS processed_messages(connection_id TEXT, chat_id INTEGER, message_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(connection_id,chat_id,message_id));
CREATE TABLE IF NOT EXISTS reply_events(id INTEGER PRIMARY KEY, owner_id INTEGER, chat_id INTEGER, source TEXT, question TEXT DEFAULT '', success INTEGER, latency REAL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_reply_events_owner ON reply_events(owner_id,created_at);
CREATE TABLE IF NOT EXISTS invoices(payload TEXT PRIMARY KEY, owner_id INTEGER, period TEXT, days INTEGER, amount INTEGER, currency TEXT DEFAULT 'XTR', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS payments(charge_id TEXT PRIMARY KEY, payload TEXT UNIQUE, owner_id INTEGER, amount INTEGER, currency TEXT, premium_until TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS customer_requests(id INTEGER PRIMARY KEY, owner_id INTEGER, chat_id INTEGER, kind TEXT, details TEXT, status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS owner_undo(owner_id INTEGER PRIMARY KEY, snapshot TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS fallback_messages(owner_id INTEGER, slot INTEGER, spec TEXT NOT NULL, PRIMARY KEY(owner_id,slot));
CREATE TABLE IF NOT EXISTS business_settings(owner_id INTEGER PRIMARY KEY, settings TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS assistant_settings(owner_id INTEGER PRIMARY KEY, settings TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS account_links(child_id INTEGER PRIMARY KEY,parent_id INTEGER NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_account_links_parent ON account_links(parent_id);
CREATE TABLE IF NOT EXISTS account_link_requests(token TEXT PRIMARY KEY,parent_id INTEGER NOT NULL,child_id INTEGER NOT NULL,status TEXT DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP,expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hub_events(id INTEGER PRIMARY KEY,owner_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,connection_id TEXT NOT NULL,direction TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_hub_events_chat ON hub_events(owner_id,chat_id,id);
"""


async def assistant_settings(owner_id):
    from assistant_rules import DEFAULTS
    async with db._connect() as conn:
        row = await (await conn.execute("SELECT settings FROM assistant_settings WHERE owner_id=?", (owner_id,))).fetchone()
    return {**DEFAULTS, **(json.loads(row[0]) if row else {})}


async def save_assistant_settings(owner_id, changes):
    from assistant_rules import validate_settings
    validate_settings(changes)
    current = {**(await assistant_settings(owner_id)), **changes}
    async with db._connect() as conn:
        await conn.execute("INSERT OR REPLACE INTO assistant_settings VALUES(?,?)", (owner_id, json.dumps(current, ensure_ascii=False)))
        await conn.commit()


async def save_fallback(owner_id, slot, spec):
    if slot not in {0, 1, 2}:
        raise ValueError("Invalid fallback slot")
    validate_message_spec(spec, owner_id=owner_id)
    async with db._connect() as conn:
        await conn.execute("INSERT OR REPLACE INTO fallback_messages VALUES(?,?,?)", (owner_id, slot, json.dumps(spec, ensure_ascii=False)))
        await conn.commit()


async def fallback_messages(owner_id):
    async with db._connect() as conn:
        rows = await (await conn.execute("SELECT slot,spec FROM fallback_messages WHERE owner_id=? ORDER BY slot", (owner_id,))).fetchall()
        return {slot: json.loads(spec) for slot, spec in rows}


async def business_settings(owner_id):
    async with db._connect() as conn:
        row = await (await conn.execute("SELECT settings FROM business_settings WHERE owner_id=?", (owner_id,))).fetchone()
    return {"report_time": "09:00", "reminders": ["12:00", "16:00", "19:00"], **(json.loads(row[0]) if row else {})}


async def save_business_setting(owner_id, field, value):
    if field not in {"report_time", "reminders", "ai_delay", "fallback_delay", "personal_ai_delay", "personal_fallback_delay"}:
        raise ValueError("Unknown business setting")
    if field.endswith("_delay"):
        from reply_policy import validate_delay
        validate_delay(value, 60 if field.startswith("personal_") else 3600)
    current = await business_settings(owner_id)
    current[field] = value
    async with db._connect() as conn:
        await conn.execute("INSERT OR REPLACE INTO business_settings VALUES(?,?)", (owner_id, json.dumps(current)))
        await conn.commit()


async def init_schema():
    async with db._connect() as conn:
        await conn.executescript(SCHEMA)
        await db._add_column_if_missing(
            conn, "owner_options", "ui_mode", "TEXT DEFAULT 'personal'"
        )
        await db._add_column_if_missing(
            conn, "owner_options", "mode_chosen", "INTEGER DEFAULT 0"
        )
        await conn.execute(
            "INSERT OR IGNORE INTO schema_versions(version) VALUES(?)",
            (SCHEMA_VERSION,),
        )
        await conn.commit()


async def options(owner_id, language_code=None):
    language = "en" if (language_code or "").startswith("en") else "ru"
    async with db._connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO owner_options(owner_id,language) VALUES(?,?)",
            (owner_id, language),
        )
        conn.row_factory = aiosqlite.Row
        row = await (
            await conn.execute(
                "SELECT * FROM owner_options WHERE owner_id=?", (owner_id,)
            )
        ).fetchone()
        await conn.commit()
        return dict(row)


async def set_option(owner_id, field, value):
    if field not in {
        "language",
        "setup_done",
        "collect_requests",
        "ui_mode",
        "mode_chosen",
    }:
        raise ValueError("Unknown option")
    if field == "ui_mode" and value not in {"personal", "business"}:
        raise ValueError("Invalid interface mode")
    await options(owner_id)
    async with db._connect() as conn:
        await conn.execute(
            f"UPDATE owner_options SET {field}=? WHERE owner_id=?", (value, owner_id)
        )
        await conn.commit()


async def claim_message(connection_id, chat_id, message_id):
    async with db._connect() as conn:
        cursor = await conn.execute(
            "INSERT OR IGNORE INTO processed_messages VALUES(?,?,?,CURRENT_TIMESTAMP)",
            (connection_id, chat_id, message_id),
        )
        await conn.commit()
        return cursor.rowcount == 1


async def handoff(owner_id, chat_id, paused=True, reason="manual"):
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO handoffs(owner_id,chat_id,paused,reason) VALUES(?,?,?,?) ON CONFLICT(owner_id,chat_id) DO UPDATE SET paused=excluded.paused,reason=excluded.reason,updated_at=CURRENT_TIMESTAMP",
            (owner_id, chat_id, int(paused), reason),
        )
        await conn.commit()


async def is_handoff(owner_id, chat_id):
    async with db._connect() as conn:
        row = await (
            await conn.execute(
                "SELECT paused FROM handoffs WHERE owner_id=? AND chat_id=?",
                (owner_id, chat_id),
            )
        ).fetchone()
        return bool(row and row[0])


async def record_event(owner_id, chat_id, source, question="", success=True, latency=0):
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO reply_events(owner_id,chat_id,source,question,success,latency) VALUES(?,?,?,?,?,?)",
            (owner_id, chat_id, source, question[:2000], int(success), latency),
        )
        await conn.commit()


async def last_assistant_reply(owner_id, chat_id):
    async with db._connect() as conn:
        row = await (await conn.execute(
            "SELECT content FROM chat_history WHERE owner_id=? AND chat_id=? AND role='assistant' ORDER BY id DESC LIMIT 1",
            (owner_id, chat_id),
        )).fetchone()
    return row[0] if row else ""


async def inbox(owner_id, offset=0):
    async with db._connect() as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (
            await conn.execute(
                """SELECT c.*,COALESCE(h.paused,0) AS paused,
            (SELECT source FROM reply_events e WHERE e.owner_id=c.owner_id AND e.chat_id=c.chat_id ORDER BY e.id DESC LIMIT 1) AS source
            FROM chat_settings c LEFT JOIN handoffs h ON h.owner_id=c.owner_id AND h.chat_id=c.chat_id
            WHERE c.owner_id=? ORDER BY c.last_seen DESC LIMIT 10 OFFSET ?""",
                (owner_id, max(0, offset)),
            )
        ).fetchall()
        return [dict(r) for r in rows]


async def unanswered(owner_id):
    async with db._connect() as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (
            await conn.execute(
                """SELECT id,question,chat_id FROM reply_events
            WHERE owner_id=? AND source IN ('fallback','handoff','error') AND question<>''
            ORDER BY id DESC LIMIT 20""",
                (owner_id,),
            )
        ).fetchall()
        return [dict(r) for r in rows]


async def statistics(owner_id):
    async with db._connect() as conn:
        rows = await (
            await conn.execute(
                "SELECT source,COUNT(*),SUM(success),ROUND(AVG(latency),2) FROM reply_events WHERE owner_id=? AND created_at>=datetime('now','-7 days') GROUP BY source",
                (owner_id,),
            )
        ).fetchall()
        return rows


async def today_contacts(owner_id, timezone_name):
    now = datetime.now(db._tz_or_utc(timezone_name))
    start = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    async with db._connect() as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (await conn.execute("""SELECT c.chat_id,c.peer_name,c.username,MAX(h.created_at) AS last_received
            FROM chat_settings c JOIN chat_history h ON c.owner_id=h.owner_id AND c.chat_id=h.chat_id
            WHERE c.owner_id=? AND h.role='user' AND h.created_at>=?
            GROUP BY c.chat_id ORDER BY last_received DESC""", (owner_id, start))).fetchall()
    return [dict(row) for row in rows]


def extended_expiry(current, days, now=None):
    now = now or datetime.now(timezone.utc)
    if days <= 0:
        raise ValueError("Invalid subscription duration")
    try:
        existing = datetime.fromisoformat(current or "")
        if existing.tzinfo is None:
            existing = existing.replace(tzinfo=timezone.utc)
    except ValueError:
        existing = now
    return (max(now, existing) + timedelta(days=days)).isoformat()


async def issue_invoice(owner_id, period, days, amount):
    payload = "premium:" + secrets.token_urlsafe(20)
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO invoices(payload,owner_id,period,days,amount) VALUES(?,?,?,?,?)",
            (payload, owner_id, period, days, amount),
        )
        await conn.commit()
    return payload


async def validate_invoice(payload, owner_id, currency, amount):
    async with db._connect() as conn:
        row = await (
            await conn.execute(
                "SELECT 1 FROM invoices i WHERE payload=? AND owner_id=? AND currency=? AND amount=? AND NOT EXISTS(SELECT 1 FROM payments p WHERE p.payload=i.payload)",
                (payload, owner_id, currency, amount),
            )
        ).fetchone()
        return bool(row)


async def apply_payment(payload, owner_id, currency, amount, charge_id):
    await db.ensure_user(owner_id)
    async with db._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        duplicate = await (
            await conn.execute(
                "SELECT premium_until,owner_id,payload,amount,currency FROM payments WHERE charge_id=?",
                (charge_id,),
            )
        ).fetchone()
        if duplicate:
            if tuple(duplicate[1:]) != (owner_id, payload, amount, currency):
                raise ValueError("Charge belongs to different payment terms")
            return duplicate[0], False
        invoice = await (
            await conn.execute(
                "SELECT days FROM invoices WHERE payload=? AND owner_id=? AND currency=? AND amount=?",
                (payload, owner_id, currency, amount),
            )
        ).fetchone()
        paid = await (
            await conn.execute("SELECT 1 FROM payments WHERE payload=?", (payload,))
        ).fetchone()
        if not invoice or paid or not charge_id:
            raise ValueError("Payment does not match an unpaid invoice")
        row = await (
            await conn.execute(
                "SELECT premium_until FROM users WHERE telegram_id=?", (owner_id,)
            )
        ).fetchone()
        until = extended_expiry(row[0], invoice[0])
        await conn.execute(
            "UPDATE users SET plan='premium',premium_until=? WHERE telegram_id=?",
            (until, owner_id),
        )
        await conn.execute(
            "INSERT INTO payments(charge_id,payload,owner_id,amount,currency,premium_until) VALUES(?,?,?,?,?,?)",
            (charge_id, payload, owner_id, amount, currency, until),
        )
        await conn.commit()
        return until, True


async def recover_legacy_invoice(payload, owner_id, currency, amount, charge_id):
    # SuccessfulPayment is a Telegram receipt for an invoice issued by the old bot.
    # Old unpaid invoices are refused at checkout and must be recreated.
    periods = {"premium:week": 7, "premium:month": 30}
    if payload not in periods or currency != "XTR" or amount <= 0 or not charge_id:
        raise ValueError("Invalid legacy receipt")
    migrated = "legacy:" + charge_id
    async with db._connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO invoices(payload,owner_id,period,days,amount,currency) VALUES(?,?,?,?,?,?)",
            (migrated, owner_id, payload, periods[payload], amount, currency),
        )
        await conn.commit()
    return migrated


async def save_request(owner_id, chat_id, kind, details):
    if kind not in {"booking", "contact"} or not details.strip():
        raise ValueError("Invalid request")
    async with db._connect() as conn:
        cursor = await conn.execute(
            "INSERT INTO customer_requests(owner_id,chat_id,kind,details) VALUES(?,?,?,?)",
            (owner_id, chat_id, kind, details[:2000]),
        )
        await conn.commit()
        return cursor.lastrowid


async def requests(owner_id):
    async with db._connect() as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (
            await conn.execute(
                "SELECT * FROM customer_requests WHERE owner_id=? AND status='pending' ORDER BY id DESC LIMIT 20",
                (owner_id,),
            )
        ).fetchall()
        return [dict(r) for r in rows]


async def complete_request(owner_id, request_id):
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE customer_requests SET status='done' WHERE id=? AND owner_id=?",
            (request_id, owner_id),
        )
        await conn.commit()


async def maintenance(days=30):
    cutoff = f"-{max(1, days)} days"
    async with db._connect() as conn:
        for table in ("chat_history", "reply_events", "processed_messages", "hub_events"):
            await conn.execute(
                f"DELETE FROM {table} WHERE created_at<datetime('now',?)", (cutoff,)
            )
        await conn.execute(
            "DELETE FROM owner_undo WHERE created_at<datetime('now','-1 day')"
        )
        await conn.execute(
            "DELETE FROM fsm_state WHERE updated_at<datetime('now','-1 day')"
        )
        await conn.execute(
            "DELETE FROM customer_requests WHERE status='done' AND created_at<datetime('now',?)",
            (cutoff,),
        )
        await conn.commit()


async def forget_chat(owner_id, chat_id):
    async with db._connect() as conn:
        for table in ("chat_history", "reply_events", "customer_requests", "handoffs", "hub_events"):
            await conn.execute(
                f"DELETE FROM {table} WHERE owner_id=? AND chat_id=?",
                (owner_id, chat_id),
            )
        await conn.execute(
            "DELETE FROM chat_settings WHERE owner_id=? AND chat_id=?",
            (owner_id, chat_id),
        )
        await conn.commit()


PROFILE_FIELDS = {
    "owner_name",
    "age",
    "gender",
    "topics",
    "ai_description",
    "fallback_text",
    "fallback_text2",
    "native_language",
}
PREFERENCE_FIELDS = {
    "primary_language",
    "secondary_language",
    "extra_languages",
    "timezone",
    "schedule_enabled",
    "schedule_start",
    "schedule_end",
    "autoreply_enabled",
}
FAQ_FIELDS = {
    "question",
    "answer",
    "answer_type",
    "answer_file_id",
    "answer_entities",
    "answer_payload",
}


async def export_owner(owner_id):
    profile = await db.get_profile(owner_id)
    prefs = await db.get_preferences(owner_id)
    opts = await options(owner_id)
    return {
        "format": "autoreply-v1",
        "profile": {k: profile[k] for k in PROFILE_FIELDS},
        "preferences": {k: prefs[k] for k in PREFERENCE_FIELDS},
        "options": {
            k: opts[k]
            for k in (
                "language",
                "collect_requests",
                "setup_done",
                "ui_mode",
                "mode_chosen",
            )
        },
        "faqs": [
            {k: f.get(k, "") for k in FAQ_FIELDS} for f in await db.get_faqs(owner_id)
        ],
        "fallbacks": {str(slot): spec for slot, spec in (await fallback_messages(owner_id)).items()},
        "business_settings": await business_settings(owner_id),
        "assistant_settings": await assistant_settings(owner_id),
    }


def validate_export(data):
    if not isinstance(data, dict) or data.get("format") != "autoreply-v1":
        raise ValueError("Unknown export format")
    profile = data.get("profile", {})
    prefs = data.get("preferences", {})
    faqs = data.get("faqs", [])
    opts = data.get("options", {})
    from assistant_rules import validate_settings
    validate_settings(data.get("assistant_settings", {}))
    fallbacks = data.get("fallbacks", {})
    if not isinstance(fallbacks, dict) or set(fallbacks) - {"0", "1", "2"}:
        raise ValueError("Invalid fallbacks")
    for spec in fallbacks.values():
        validate_message_spec(spec)
    reports = data.get("business_settings", {})
    if not isinstance(reports, dict) or set(reports) - {"report_time", "reminders", "ai_delay", "fallback_delay", "personal_ai_delay", "personal_fallback_delay"}:
        raise ValueError("Invalid report settings")
    from reply_policy import validate_delay
    for field in ("ai_delay", "fallback_delay", "personal_ai_delay", "personal_fallback_delay"):
        if field in reports:
            validate_delay(reports[field], 60 if field.startswith("personal_") else 3600)
    if "report_time" in reports and (not isinstance(reports["report_time"], str) or not db.validate_time(reports["report_time"])):
        raise ValueError("Invalid report time")
    if "reminders" in reports and (not isinstance(reports["reminders"], list) or len(reports["reminders"]) != 3 or not all(isinstance(v, str) and db.validate_time(v) for v in reports["reminders"])):
        raise ValueError("Invalid reminders")
    if not isinstance(opts, dict) or set(opts) - {
        "language",
        "collect_requests",
        "setup_done",
        "ui_mode",
        "mode_chosen",
    }:
        raise ValueError("Invalid options")
    if "language" in opts and opts["language"] not in {"ru", "en"}:
        raise ValueError("Invalid interface language")
    if "ui_mode" in opts and opts["ui_mode"] not in {"personal", "business"}:
        raise ValueError("Invalid interface mode")
    for field in ("collect_requests", "setup_done", "mode_chosen"):
        if field in opts and (
            type(opts[field]) is not int or opts[field] not in {0, 1}
        ):
            raise ValueError("Invalid option")
    if (
        not isinstance(profile, dict)
        or not isinstance(prefs, dict)
        or not isinstance(faqs, list)
        or len(faqs) > 500
    ):
        raise ValueError("Invalid export structure")
    if set(profile) - PROFILE_FIELDS or set(prefs) - PREFERENCE_FIELDS:
        raise ValueError("Unknown fields")
    for key, value in profile.items():
        limit = (
            2000
            if key in {"topics", "ai_description", "fallback_text", "fallback_text2"}
            else 120
        )
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError("Profile value too long")
    for key, value in prefs.items():
        if key in {"schedule_enabled", "autoreply_enabled"}:
            if type(value) is not int or value not in {0, 1}:
                raise ValueError("Invalid toggle")
        elif not isinstance(value, str) or len(value) > 200:
            raise ValueError("Invalid preference")
    if "timezone" in prefs and not db.validate_timezone(prefs["timezone"]):
        raise ValueError("Invalid timezone")
    for key in ("schedule_start", "schedule_end"):
        if key in prefs and not db.validate_time(prefs[key]):
            raise ValueError("Invalid schedule")
    for faq in faqs:
        if not isinstance(faq, dict) or set(faq) - FAQ_FIELDS:
            raise ValueError("Invalid FAQ")
        if (
            not isinstance(faq.get("question"), str)
            or not 1 <= len(faq["question"]) <= 500
        ):
            raise ValueError("Invalid question")
        for key in FAQ_FIELDS - {"question"}:
            if not isinstance(faq.get(key, ""), str) or len(faq.get(key, "")) > 20000:
                raise ValueError("Invalid FAQ field")
        if len(faq.get("answer", "")) > 4096:
            raise ValueError("Answer too long")
        if faq.get("answer_type", "text") not in {
            "text",
            "photo",
            "video",
            "animation",
            "document",
            "audio",
            "voice",
            "video_note",
            "sticker",
            "location",
            "venue",
            "contact",
            "dice",
            "poll",
            "media_group",
            "sequence",
            "forward",
        }:
            raise ValueError("Invalid media type")
        if (
            faq.get("answer_type", "text") == "text"
            and not faq.get("answer", "").strip()
        ):
            raise ValueError("Empty answer")
        for key in ("answer_entities", "answer_payload"):
            if faq.get(key):
                json.loads(faq[key])
        validate_message_spec({"type": faq.get("answer_type", "text"), "text": faq.get("answer", ""), "payload": json.loads(faq.get("answer_payload") or "{}")})


def validate_message_spec(spec, depth=0, owner_id=None):
    if depth > 3 or not isinstance(spec, dict) or spec.get("type") not in {"text", "photo", "video", "animation", "document", "audio", "voice", "video_note", "sticker", "location", "venue", "contact", "dice", "poll", "media_group", "sequence", "forward"}:
        raise ValueError("Invalid message spec")
    if not isinstance(spec.get("text", ""), str) or len(spec.get("text", "")) > 4096:
        raise ValueError("Message too long")
    payload = spec.get("payload", {})
    if not isinstance(payload, dict):
        raise ValueError("Invalid message payload")
    if "ignore" in payload and type(payload["ignore"]) is not bool:
        raise ValueError("Invalid ignore action")
    if "delay" in payload:
        from reply_policy import validate_delay
        validate_delay(payload["delay"], 3600)
    from reply_policy import valid_command
    if "command" in payload and not valid_command(payload["command"]):
        raise ValueError("Invalid FAQ command")
    if spec["type"] in {"media_group", "sequence"}:
        items = payload.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 10:
            raise ValueError("Invalid message sequence")
        for item in items:
            if spec["type"] == "media_group" and (not isinstance(item, dict) or item.get("type") not in {"photo", "video", "audio", "document"}):
                raise ValueError("Invalid album media")
            validate_message_spec(item, depth + 1, owner_id)
    if spec["type"] == "forward":
        if type(payload.get("from_chat_id")) is not int or type(payload.get("message_id")) is not int:
            raise ValueError("Invalid forward source")
        if owner_id is not None and payload["from_chat_id"] != owner_id:
            raise ValueError("Forward source must belong to the owner")
        validate_message_spec(payload.get("copy"), depth + 1, owner_id)
    buttons = payload.get("buttons", [])
    if not isinstance(buttons, list) or len(buttons) > 5:
        raise ValueError("Invalid buttons")
    if "button_rows" in payload:
        from button_layout import validate_rows
        validate_rows(payload["button_rows"], len(buttons))
    from urllib.parse import urlsplit
    for button in buttons:
        if not isinstance(button, dict) or set(button) not in ({"text", "url"}, {"text", "command"}) or not isinstance(button["text"], str) or not 1 <= len(button["text"]) <= 64:
            raise ValueError("Invalid button")
        if "command" in button:
            if not valid_command(button["command"]):
                raise ValueError("Invalid button command")
            continue
        if not isinstance(button["url"], str):
            raise ValueError("Invalid button URL")
        url = urlsplit(button["url"])
        if url.scheme not in {"http", "https"} or not url.netloc:
            raise ValueError("Invalid button URL")


async def import_owner(owner_id, data):
    validate_export(data)
    for spec in data.get("fallbacks", {}).values():
        validate_message_spec(spec, owner_id=owner_id)
    for faq in data.get("faqs", []):
        validate_message_spec({"type": faq.get("answer_type", "text"), "payload": json.loads(faq.get("answer_payload") or "{}")}, owner_id=owner_id)
    profile = await db.get_profile(owner_id)
    settings = await db.get_global_settings()
    await options(owner_id)
    limit = int(
        settings[
            "premium_faq_limit" if profile["plan"] == "premium" else "free_faq_limit"
        ]
    )
    async with db._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        existing = await (
            await conn.execute(
                "SELECT question FROM faq WHERE owner_id=? AND enabled=1", (owner_id,)
            )
        ).fetchall()
        questions = {r[0].strip().casefold() for r in existing}
        fresh = []
        for f in data.get("faqs", []):
            key = f["question"].strip().casefold()
            if key not in questions:
                questions.add(key)
                fresh.append(f)
        if len(existing) + len(fresh) > limit:
            raise ValueError(f"FAQ limit exceeded ({limit})")
        for key, value in data.get("profile", {}).items():
            await conn.execute(
                f"UPDATE users SET {key}=? WHERE telegram_id=?", (value, owner_id)
            )
        for key, value in data.get("preferences", {}).items():
            await conn.execute(
                f"UPDATE user_preferences SET {key}=? WHERE owner_id=?",
                (value, owner_id),
            )
        for key, value in data.get("options", {}).items():
            await conn.execute(
                f"UPDATE owner_options SET {key}=? WHERE owner_id=?", (value, owner_id)
            )
        for f in fresh:
            await conn.execute(
                "INSERT INTO faq(owner_id,question,answer,answer_type,answer_file_id,answer_entities,answer_payload) VALUES(?,?,?,?,?,?,?)",
                (
                    owner_id,
                    f["question"].strip(),
                    f.get("answer", ""),
                    f.get("answer_type", "text"),
                    f.get("answer_file_id", ""),
                    f.get("answer_entities", ""),
                    f.get("answer_payload", ""),
                ),
            )
        for slot, spec in data.get("fallbacks", {}).items():
            await conn.execute("INSERT OR REPLACE INTO fallback_messages VALUES(?,?,?)", (owner_id, int(slot), json.dumps(spec, ensure_ascii=False)))
        if "business_settings" in data:
            await conn.execute("INSERT OR REPLACE INTO business_settings VALUES(?,?)", (owner_id, json.dumps(data["business_settings"])))
        if "assistant_settings" in data:
            await conn.execute("INSERT OR REPLACE INTO assistant_settings VALUES(?,?)", (owner_id, json.dumps(data["assistant_settings"], ensure_ascii=False)))
        await conn.commit()
        return len(fresh)


async def append_faq(owner_id, question, spec):
    data = {
        "format": "autoreply-v1",
        "faqs": [
            {
                "question": question,
                "answer": spec.get("text", ""),
                "answer_type": spec["type"],
                "answer_file_id": spec.get("file_id", ""),
                "answer_entities": json.dumps(spec.get("entities") or []),
                "answer_payload": json.dumps(spec.get("payload") or {}),
            }
        ],
    }
    return await import_owner(owner_id, data)


async def save_undo(owner_id):
    snapshot = await export_owner(owner_id)
    snapshot["ai_enabled"] = (await db.get_profile(owner_id))["ai_enabled"]
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO owner_undo(owner_id,snapshot) VALUES(?,?) ON CONFLICT(owner_id) DO UPDATE SET snapshot=excluded.snapshot,created_at=CURRENT_TIMESTAMP",
            (owner_id, json.dumps(snapshot)),
        )
        await conn.commit()


async def restore_undo(owner_id):
    async with db._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        row = await (
            await conn.execute(
                "SELECT snapshot FROM owner_undo WHERE owner_id=? AND created_at>=datetime('now','-1 day')",
                (owner_id,),
            )
        ).fetchone()
        if not row:
            return False
        snapshot = json.loads(row[0])
        await conn.execute("INSERT OR REPLACE INTO assistant_settings VALUES(?,?)", (owner_id, json.dumps(snapshot.get("assistant_settings", {}), ensure_ascii=False)))
        await conn.execute("DELETE FROM fallback_messages WHERE owner_id=?", (owner_id,))
        for slot, spec in snapshot.get("fallbacks", {}).items():
            await conn.execute("INSERT INTO fallback_messages VALUES(?,?,?)", (owner_id, int(slot), json.dumps(spec)))
        await conn.execute("INSERT OR REPLACE INTO business_settings VALUES(?,?)", (owner_id, json.dumps(snapshot.get("business_settings", {}))))
        for key, value in snapshot["profile"].items():
            await conn.execute(
                f"UPDATE users SET {key}=? WHERE telegram_id=?", (value, owner_id)
            )
        for key, value in snapshot["preferences"].items():
            await conn.execute(
                f"UPDATE user_preferences SET {key}=? WHERE owner_id=?",
                (value, owner_id),
            )
        for key, value in snapshot.get("options", {}).items():
            await conn.execute(
                f"UPDATE owner_options SET {key}=? WHERE owner_id=?", (value, owner_id)
            )
        await conn.execute(
            "UPDATE users SET ai_enabled=? WHERE telegram_id=?",
            (snapshot["ai_enabled"], owner_id),
        )
        await conn.execute("DELETE FROM faq WHERE owner_id=?", (owner_id,))
        for f in snapshot["faqs"]:
            await conn.execute(
                "INSERT INTO faq(owner_id,question,answer,answer_type,answer_file_id,answer_entities,answer_payload) VALUES(?,?,?,?,?,?,?)",
                (
                    owner_id,
                    f["question"],
                    f["answer"],
                    f["answer_type"],
                    f["answer_file_id"],
                    f["answer_entities"],
                    f["answer_payload"],
                ),
            )
        await conn.execute("DELETE FROM owner_undo WHERE owner_id=?", (owner_id,))
        await conn.commit()
        return True

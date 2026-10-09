# AutoReplyBot — Release Handoff

**Prepared:** 9 October 2026 · Asia/Karachi  
**Purpose:** Replace the previous server version while preserving production data.  
**Deployment status:** Updated and verified locally. No server update or production polling was performed.

## 1. Release overview

This release introduces separate Personal and Business experiences, richer FAQ controls, configurable inline keyboards and private previews. It also strengthens owner takeover, conversational silence, delayed replies and AI output handling.

| Capability | Personal | Business |
|---|---|---|
| FAQ data, timezone, primary/native language | Shared and retained when switching | Shared and retained when switching |
| FAQ reply | First stored answer | Multiple stored answers, up to 10 |
| User-configured inline buttons | Hidden when sending | URL and FAQ-command buttons, up to 5 total |
| Button placement | — | Custom rows of 1–3 buttons; default is pairs |
| Private FAQ preview | Available | Available, including interactive buttons |
| Fallback replies | One | Two, alternating per conversation |
| Response delays | 1–60 seconds | 1–3600 seconds |
| Conversation memory and history UI | Simplified conversation controls | History and configurable AI memory |
| Business schedule, requests, reports, statistics | Business entry points hidden/blocked | Available |

Business extensions remain stored when Personal is selected. Personal sends the first FAQ answer without user-configured buttons and caps a shared FAQ delay at 60 seconds. A previously saved third fallback is retained in storage but is no longer sent.

Choosing Business is free; Premium governs the existing higher FAQ and AI quotas.

## 2. User workflows

### FAQ buttons and layout

1. Select Business, open **Saved FAQ**, and choose a question.
2. Use **Inline buttons → URL** for link buttons. Enter one `Label | https://example.com` line per URL button.
3. To call another FAQ, assign that FAQ a unique command such as `/prices` in its card.
4. Use **Inline buttons → Command** on the source FAQ. Enter two lines:

   ```text
   Our prices
   /prices
   ```

5. Select **Layout**. Button numbers are listed in their current order. Each input line defines one keyboard row:

   ```text
   1 2
   3
   ```

   This places buttons 1 and 2 side by side, with button 3 below. Use every number exactly once, with no more than three buttons per row. Reordering is supported, for example `2 1` followed by `3`.

6. Save and press **Preview**. The actual text/media and keyboard are sent privately to the owner. Preview skips delays and does not invoke AI or reserve AI quota. Clicking a command button in the owner's private preview sends its target FAQ there.

URL and command buttons coexist. Changing the button collection resets its custom placement to the default pairs so obsolete indices cannot reference unrelated buttons. Adding another answer preserves the keyboard layout and FAQ policy metadata.

In a connected customer conversation, command clicks use the normal per-chat queue, FAQ delays and send guards. They respect handoff and schedule restrictions. Removed commands and deleted targets cannot fall through to an AI-generated answer for a queued command click.

### FAQ silence and delays

- **Do not reply** can be selected while adding a question or toggled in its saved card. The draft question is preserved before saving the action.
- Silence matches the complete phrase, ignoring case and punctuation. `OK` can be ignored without swallowing `OK, when will it arrive?`.
- A silent FAQ does not call AI or send a fallback. Its preview explains that no customer message would be sent.
- Set an individual FAQ delay in its card. AI and fallback delays are separate settings for each interface mode.
- Delays are minimum timing targets, not delivery guarantees. Debounce, AI generation, Telegram latency and flood control can add time.

### Human takeover and conversation closing

- An outgoing owner message, an owner edit or **I'll reply** pauses every automatic reply in that conversation. Pending work is cancelled; undelivered AI quota is refunded.
- Handoff is persisted across restarts and resumes only through **Let bot reply**. Merely opening the Telegram chat cannot be detected through this implementation.
- After a completed bot reply, acknowledgements such as “OK”, “understood” or “I'll wait” are recorded without another AI, FAQ or fallback reply.
- A new question re-enters normal processing. A short answer to the bot's own clarification is not suppressed. Questions do not release a human takeover pause.

### Media and AI output

- FAQ and fallback content retain Telegram entities and supported media types. Albums are saved automatically; the manual album-completion button is hidden.
- Telegram keyboards cannot be attached directly to an album. The sender places the keyboard in a separate message after it.
- Business forwarding uses the stored content copy on behalf of the connected account; owner previews can use Telegram forwarding where permitted.
- AI output is sanitized for reasoning leakage and a stray final `OK`/`ОК` line. A standalone `OK` and ordinary sentences containing that word remain unchanged. FAQ text is not sanitized this way.
- Structured AI instructions cover role, verified facts, rules, style, language, examples and unknown-answer behavior. Ambiguous greetings such as `salom` use the configured primary language.

## 3. Reliability and performance changes in this preparation

| Finding | Resolution |
|---|---|
| A new message could wait behind an obsolete response delay of up to an hour | Per-chat wake events interrupt obsolete delays. The worker processes the newer batch and stale answers remain suppressed. |
| CPU-heavy FAQ matching could occupy the Telegram event loop | Matching/context selection run through `asyncio.to_thread`. Normalized input is reused; safe similarity upper bounds skip unnecessary work; exact matches return early. |
| Long-delay work could use a mode selected before the owner switched modes | The mode is checked again before the delayed reply is sent. An obsolete-mode reply is discarded. |
| A queued command target might disappear before processing | Unavailable queued commands end without invoking AI or fallback. |
| Custom row indices could become stale after button edits | Layout validation and automatic reset on collection edits prevent invalid placements. A layout editor rejects a button collection changed while it was open. |
| Converting a FAQ to multiple answers could copy keyboard metadata into a child item | Keyboard and policy metadata stay at the sequence level, keeping import/export validation consistent. |

Menus pair compatible short controls, use icons and retain navigation/confirmation controls in clear separate rows. Rows with long labels are split more conservatively. Actual text wrapping still depends on the Telegram client and screen width.

### Measured results

- Baseline local matcher microbenchmark: **524.00 ms median**, **591.62 ms maximum**.
- Optimized matcher microbenchmark: **72.74 ms median**, **109.36 ms maximum**.
- Both measurements: 1,000 synthetic FAQs, 10 unmatched-query samples, same local environment. This is approximately a **7.2× reduction in median CPU time for this sample**; it is not an end-to-end Telegram or AI latency measurement.
- The reference-equivalence test verifies matched records, scores, thresholds, first-match ties and substring/negation behavior on representative inputs.

## 4. Verification evidence

Local environment: Windows, Python **3.12.10**, project-managed `.tools/python/python.exe`.

| Check | Result |
|---|---|
| Full final regression suite | 115 tests passed |
| Static runtime-error/name checks | `ruff --select E9,F63,F7,F82`: passed |
| Python compilation | Passed, excluding local tool/virtual-environment directories |
| Dependency consistency | `pip check`: no broken requirements |
| Existing local DB migration rehearsal | Migrated a temporary SQLite-consistent backup; integrity `ok`; user/FAQ row counts preserved |
| Source DB protection during rehearsal | Source-file SHA-256 unchanged; original database not migrated by the check |
| Keyboard rendering | Mocked Telegram sender verified mixed URL/command buttons and saved row sizes |
| Delay interruption | Regression confirms a newer FAQ replaces an obsolete hour-long delayed reply |

Tests intentionally exercise failed Telegram sends and AI/provider failures. Their synthetic `ERROR` log entries are expected when the suite ends with `OK`; they are not evidence of a production outage.

Validation covers local logic and mocked Telegram interactions. Server credentials, Linux service permissions, actual mobile-client layout, real business callback delivery and production network behavior still need the staging checks below. This preparation did not send customer messages, deploy code, restart the server or run the production bot.

## 5. Files and data model

| File | Responsibility |
|---|---|
| `bot.py` | Telegram integration, media sending and FAQ keyboard rendering |
| `experience.py` | RU/EN interface, FAQ editors, layout/preview controls and command callbacks |
| `button_layout.py` | Row parsing, validation, default pairing and menu presentation |
| `reply_policy.py` | Explicit FAQ silence, command matching and mode-specific capabilities/delays |
| `business_runtime.py` | Per-chat queue, wakeable delays, handoff and final send guards |
| `matcher.py` | Optimized conservative FAQ similarity and AI context selection |
| `reply_safety.py`, `assistant_rules.py` | AI output sanitation and structured instructions |
| `extensions.py` | Additive schema, owner-scoped persistence and import/export validation |
| `release_readiness.py` | Temporary DB migration rehearsal and local matcher benchmark |
| `tests/test_button_layout.py` | Layout, preview, matcher equivalence and interruption regressions |

No destructive schema migration is introduced by button layout. New metadata lives in the existing JSON payloads. Example:

```json
{
  "command": "/welcome",
  "delay": 5,
  "buttons": [
    {"text": "Website", "url": "https://example.com"},
    {"text": "Prices", "command": "/prices"},
    {"text": "Contact", "url": "https://example.com/contact"}
  ],
  "button_rows": [[0, 1], [2]]
}
```

Stored row indices are zero-based; the UI accepts one-based numbers. FAQ commands use `/[a-z][a-z0-9_]{0,31}`. `ignore` is a Boolean. Import/export validates row coverage, button types and delay bounds. Legacy payloads without rows use pairs.

Business AI/fallback delays use `ai_delay` and `fallback_delay`; Personal uses `personal_ai_delay` and `personal_fallback_delay` in the existing owner settings JSON. Existing FAQ/media and language/timezone data remain shared.

## 6. Server update runbook

### Record and protect the current installation

1. Identify the actual service, application directory, virtual environment, `.env` and effective `DB_PATH`. The bundled root-systemd example uses `/opt/autoreplybot`, service `autoreplybot`, and account `autoreply`; a user-service installation has different paths and commands.
2. Record the current code revision or preserve the entire previous release. Preserve its dependency environment for rollback.
3. Stop the current poller before replacing code or moving the DB. Run only one poller for a token. The local instance guard does not coordinate separate hosts.
4. Make a SQLite-consistent backup using `backup_db.py`. Preserve the original DB and any WAL/SHM companions until verification finishes.
5. Keep the operational production DB outside the code checkout and set an absolute `DB_PATH`. Set `REQUIRE_EXISTING_DB=true` for this existing deployment. Do not upload the desktop database over the server database.

Example commands below assume the bundled root-systemd paths. **Set the variables to the real installation first; the DB and backup directory must be writable by the service account.**

```bash
APP_DIR=/opt/autoreplybot
DB_FILE=/var/lib/autoreplybot/autoreply.db
SNAPSHOT=/var/lib/autoreplybot/backups/pre-2026-10-07.db

sudo systemctl stop autoreplybot
sudo -u autoreply "$APP_DIR/.venv/bin/python" "$APP_DIR/backup_db.py" backup "$DB_FILE" "$SNAPSHOT"
```

If the current DB is still inside the old checkout, back it up **before** any Git pull or replacement. To move it, use `backup_db.py restore` into a new external destination, then change `DB_PATH` and verify permissions. Restore refuses an existing destination. Historical removal of tracked database files means an update can remove a checkout-local DB; see `IMPLEMENTATION.md`.

### Install the complete release

- Transfer all application modules, tests, `requirements.lock.txt` and deployment/documentation files. Uploading only `bot.py` is insufficient.
- Exclude `.env`, local databases/backups, logs, `.tools`, virtual environments and caches. Retain the existing server secrets and data paths.
- Install locked dependencies in a fresh Python 3.12 environment. Keep the previous environment until the release is accepted.
- The currently configured Gemini model is `gemini-3.5-flash-lite`; the former `gemini-2.5-flash-lite` returned a model-unavailable error in the prior API check. A successful API-key check does not guarantee remaining account quota at rollout time.

```bash
cd "$APP_DIR"
python3.12 -m venv .venv-release
.venv-release/bin/python -m pip install -r requirements.lock.txt
.venv-release/bin/python -m pip check
.venv-release/bin/python -m unittest discover -s tests
```

Before production startup, point the service's `ExecStart` at the selected environment, verify its `WorkingDirectory` and DB permissions, and retain a record of the previous values. For Docker, preserve the external data volume and environment; do not bake secrets or desktop DB files into the image.

### Staging acceptance

Use a separate Telegram token and a separate database. Never run a staging poller with the production token.

| Scenario | Expected result |
|---|---|
| New Personal user | Menu opens without business onboarding or business-only entries |
| Switch modes and press Back in FAQ/settings | Correct active-mode menu; FAQ, timezone and languages retained |
| Add `OK` and select Do not reply | Saved silence action; no FAQ, AI or fallback sent |
| Add formatted text, photo and album | Content/entities retained; album auto-saved |
| Mix URL and command buttons; set `1 2` / `3` | Matching arrangement in preview and real customer reply |
| Tap a command button in a connected customer chat | Correct owner-scoped FAQ; no AI quota consumed |
| Remove the target command/FAQ | Old button reports unavailable; no AI substitute |
| Preview a silent FAQ | Explanation only; no customer message |
| New question during a long delay | Old delayed reply discarded; newer question processed promptly |
| Owner replies during pending FAQ/AI | No automatic reply after takeover; persisted pause survives restart |
| `OK` after a completed reply, then a new question | Silence on acknowledgement; normal response to the question |
| Short answer to a clarification | Not discarded as an acknowledgement |
| AI/provider failure | Controlled fallback and quota recovery; no leaked reasoning or final OK footer |
| Existing connections, quotas and payments | Data retained; duplicate receipt remains idempotent |

Check narrow mobile screens and desktop Telegram. Confirm long labels remain readable; use fewer buttons in a row where needed.

### Start and observe

```bash
sudo systemctl daemon-reload
sudo systemctl start autoreplybot
sudo systemctl status autoreplybot --no-pager
sudo journalctl -u autoreplybot -n 100 --no-pager
```

For a user service, use the existing user-service equivalent. Check that exactly one poller is running, the correct bot username appears, the configured existing DB opens, and FAQ/history counts remain consistent with the pre-update snapshot. Watch for polling conflicts, permissions errors, callback failures, unavailable media, recurring fallback failures and provider cooldowns during the first customer conversations.

## 7. Rollback

1. Stop the new service. Preserve its logs and a SQLite-consistent snapshot of the post-update DB.
2. Restore the previous application release and environment/service configuration.
3. If reverting data is necessary, restore the pre-update backup into a **new** destination and point `DB_PATH` to it. Keep both DB copies. Reverting a snapshot loses subsequent messages, edits and payment records; reconcile those before reopening service.
4. Start one poller, confirm the bot identity and retained data, and verify a small FAQ/owner-takeover scenario.

Older code may not understand newer payload fields or command buttons. Keeping the new DB with the old release requires a compatibility decision; the pre-update backup is the known data baseline.

## 8. Operational limits and follow-up

- Hour-long delays and queued replies are held in memory. Restarting the process loses in-flight scheduled sends; saved delay settings and human handoff survive. This is not a durable job scheduler.
- Workers are bounded to 128 chats and 20 pending messages per chat. This release has local regression and CPU measurements, not a server concurrency/load certification.
- Provider limits and model availability can change independently of code. Check account quotas when diagnosing AI fallback.
- Missing/deleted/private forwarded media may fail in preview or delivery. Telegram business permissions, client behavior and the allowed reply window remain external constraints.
- A Telegram request already accepted by Telegram cannot be recalled by a later takeover; the guards prevent subsequent queued sends.
- Customer-facing previews, layout and Linux service startup require the staging acceptance above. No claim of a production deployment is made by this document.

Related documents: `MODE_WORKFLOW.md`, `AI_CONFIGURATION.md`, `IMPLEMENTATION.md`, `DEPLOY_LINUX.md`, and the historical `AUDIT.md`.

## 9. Update — 9 October 2026: menus and linked accounts

Saved FAQ buttons preserve their order and use three columns for questions shorter than 10 characters, two columns for 10–15 characters, and one column for longer questions. Rows are closed when the width changes. Settings are grouped into Replies & AI, Language & time, Connection, Data, and Account. The Business page groups conversations/statistics, requests, AI tools, schedule/reports, and linked accounts without duplicate request entries.

### Linked accounts: “My accounts”

A Business manager can link one additional registered account; Business Premium allows three. The manager opens Account → My accounts → Add account and enters the child's numeric Telegram user ID. The child receives the requesting manager's name, username and ID, an explanation of permissions, and Yes / No / Report buttons. Invitations expire after 24 hours. No access is granted until the child accepts. Repeated requests to the same pair are restricted; reporting blocks that pair and sends a best-effort notice to configured administrators.

Approved managers receive text/caption/type summaries of incoming messages, automated replies and owner replies, with account and chat IDs and a button to open the conversation. Media is summarized in notifications rather than copied in full. The conversation page exposes stored history, manual reply, resume automation, and add FAQ. Manual replies and new FAQ answers support the existing serialization pipeline, including formatting, media and automatically collected albums. FAQ entries are saved in the child's database and count against the child's own limits.

Manual replying pauses automation in the child's selected chat; it stays paused until explicitly resumed. Replies use the child's verified, enabled Telegram business connection and require reply permissions. Telegram delivery restrictions still apply. Both parties can revoke the link. Revocation immediately denies subsequent manager actions; already delivered notifications cannot be recalled. Pending notification delivery rechecks access.

An account cannot be managed by multiple parents or form nested management chains. Switching the parent to Personal suspends management. Premium expiry suspends additional links above the Business limit without deleting them. Switching back or renewing restores eligible links. Shared FAQ/language/timezone behavior within each account is unchanged; different accounts retain separate data.

### Storage, shutdown and acceptance

Schema version **5** adds account_links, account_link_requests, and hub_events through an additive migration. The existing migration backup policy applies. Activity summaries participate in retention and per-chat deletion. Invitation and link records remain separate from FAQ data. Background album and notification tasks are cancelled on shutdown; notification delivery is best effort and is not a durable outbox.

Before production rollout, use two staging accounts to verify invitation delivery, wrong-user rejection, accept/decline/report, both-party revocation, child connection permissions, incoming/outgoing notification routing, formatted/media replies, FAQ ownership, and suspension after changing the parent's mode or plan. Confirm automatic replies remain paused after a manager reply and only resume on explicit action. Local tests cover authorization, request expiry, quotas, concurrent acceptance, revocation, notification routing, reply ownership, menu grouping and FAQ row boundaries.

### Final local verification (9 October 2026)

All 130 unittest tests passed. Selected Ruff correctness checks, Python compilation and pip dependency checks passed. The schema-5 migration on a temporary copy preserved user/FAQ counts and SQLite integrity; the source database remained unchanged. The concurrent local 1,000-FAQ CPU microbenchmark measured a median of 523 ms and maximum of 875 ms; this is not a Telegram/network or production load benchmark. Live two-account staging acceptance and server deployment remain pending.

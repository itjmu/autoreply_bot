# Reliability and usability update

## Implemented

- AI disable settings respected; cooldown providers skipped; one overall AI deadline and bounded concurrent requests.
- Client history uses API message roles instead of system-prompt interpolation. Unclosed reasoning blocks are discarded.
- Persistent message deduplication; bounded per-chat processing with debounce and stale-answer suppression.
- Owner reply or customer human request pauses the whole conversation until manual resume. Pending replies are cancelled.
- FAQ send failures recover through fallback; AI quota is refunded for unusable, stale, cancelled or undelivered AI replies against the original reservation date.
- Pending Telegram updates retained on restart. Business messages older than one hour are ignored; payments remain eligible for reconciliation.
- Premium renewal extends existing expiry. Invoice terms and unique payment receipts are stored atomically. Legacy successful receipts are reconciled; old unpaid invoices must be recreated.
- Safer text lengths, word-boundary topic matching, conservative FAQ matching, Telegram flood-control handling, and local duplicate-process guard.
- Additive versioned schema, persistent FSM with a one-day expiry, automatic migration backup and daily SQLite-consistent backups, restore utility, retention cleanup, and rate-limited admin outage alerts.
- Database files removed from the Git index while preserved locally; database/backup/runtime files excluded from Git and Docker.
- Reproducible dependency pins and a Linux regression-test workflow.

## User features

| Feature | Where / behavior |
|---|---|
| Guided setup | Main menu → Guided setup: connect Business, choose language, enter details, test |
| Clear modes | Status: FAQ + fallback, FAQ + AI, or paused |
| Private test | Test a reply; source shown. FAQ tests are free; AI tests consume the normal daily quota |
| Handoff | Conversations → Pause / Resume. Owner and customer handoffs are persistent |
| Business templates | Shop, services, support, personal assistant; editable business facts |
| Inbox | Paginated conversations, recent history, pause and attention indicators |
| FAQ suggestions | Questions that received fallback/handoff; owner writes and approves the answer |
| Multilingual UI | Russian/English core flows; initial selection follows Telegram, with manual override |
| Import/export | Owner FAQ and profile/preferences JSON; no credentials, payments or customer history |
| Statistics | Seven-day reply sources, handoffs, failures, average latency, remaining AI quota |
| Booking/contact collection | Optional setting; `/booking date and service`, `/contact phone`, or contact card. Owner confirms requests |
| Undo | Last profile/mode/template/FAQ/import change, retained for one day |
| Data deletion | Conversation → Delete chat data → explicit confirmation |

The existing advanced admin interface remains in Russian. User-facing core navigation is bilingual. Existing FAQ media support remains available; new FAQ albums are buffered and persisted as drafts, with a finish button for recovery after restart. Existing profiles and FAQ are retained during migration.

## Verification

- 44 local regression tests passed. The suite covers databases, payments/replay/legacy receipts, quotas/midnight, provider routing, context roles, takeover, stale replies, failed sends, backup/restore, FSM persistence, album recovery/cancellation, owner isolation, bilingual menus, import confirmation, overnight schedules and sandbox behavior.
- Import/compilation/static-name checks and dependency consistency checks performed locally.
- Migrated copies of both existing SQLite files: integrity OK, user/FAQ row counts preserved, source-file hashes unchanged. Both copies had zero provider API-key values in `ai_providers`; this does not prove repository history contains no sensitive data.
- No production poller, live Telegram sends, paid AI calls, server deployment, push, or commit performed. Telegram Business permissions, real provider responses, Stars checkout and Docker/Linux execution still require a staging smoke test.

## Rollout: preserve the production database first

Removing tracked DB files means a later Git update can remove an unchanged tracked DB on the server. **Before pulling this update, back up the actual server database and move its operational location outside the checkout.** Do not copy the desktop database over production.

1. Record the server code revision, `.env` location, effective `DB_PATH`, installed dependencies and running service. Ensure only one production poller runs.
2. Stop the service for the path change. Preserve the current checkout and its DB/WAL/SHM files. Make a SQLite-consistent backup (the new standalone `backup_db.py` can be copied separately and run with Python).
3. Restore into a new external path such as `/var/lib/autoreplybot/autoreply.db`, give the service account access, and set the server `.env` `DB_PATH` to that absolute path. Set `REQUIRE_EXISTING_DB=true` on existing deployments. Keep the original DB intact until restoration is verified.
4. Update code and install `requirements.lock.txt` in a fresh virtual environment. Test with a separate staging token and database first. Do not launch staging with the production token.
5. Start the service. The first migration makes a consistent backup beside the configured DB before changing schema. Verify connections, FAQ, AI fallback, owner takeover and a small Stars purchase on staging before production rollout.
6. Monitor logs and the new Statistics/Conversations screens. An alert is rate-limited to once per 15 minutes; hourly maintenance handles retention and daily backup scheduling.

For Docker, restore the existing database into `./data/autoreply.db` before startup. This is a different path from the old project-root DB. The volume must be writable. Keep `.env` and `./data` outside image distribution.

## Backup and rollback

```bash
python backup_db.py backup /path/to/current/autoreply.db /safe/location/backup.sqlite3
python backup_db.py restore /safe/location/backup.sqlite3 /new/location/restored.db
python -m unittest discover -s tests -v
```

Restore refuses to overwrite an existing file. Stop the bot before switching its DB path. For rollback, stop the updated bot and restore the previous checkout, dependency environment and verified pre-migration database to a new path. Keep post-update backups for reconciliation: rolling back the database also rolls back new payments and customer requests.

Backups can contain sensitive data and are intentionally not automatically deleted. Protect the backup directory and set a disk/retention policy appropriate to the server. Pending customer requests and payment records are retained until explicitly handled; completed requests, history and reply events are cleaned according to `HISTORY_RETENTION_DAYS` (default 30). AI providers still receive the conversation context needed to generate answers.

Repository history cleanup and credential rotation require a separate coordinated operation if historical exposure is confirmed; removing files from current tracking does not erase old commits.

API behavior checked against [Telegram Bot API](https://core.telegram.org/bots/api), [aiogram Dispatcher](https://docs.aiogram.dev/en/latest/dispatcher/dispatcher.html), and [official OpenAI Responses guidance](https://developers.openai.com/api/docs/guides/migrate-to-responses).
# Simplified interface (October 5)

- `/start` offers Personal or Business. Change this anytime in Settings; switching preserves reply behavior, FAQs, requests and profile data.
- Personal home: Replies · Conversations · Test a reply · Settings.
- Business home: Knowledge · Inbox · Test a reply · Settings. Inbox contains requests, statistics and request collection.
- Settings contains interface/language/schedule, Advanced (import/export/setup), and Account (Premium/referrals). Admin remains accessible with `/admin`.
- UI language changes preserve an existing reply language such as Tajik.
- AI output removes tagged reasoning and rejects whole responses containing internal analysis, including the reported language-analysis example. Existing fallback handles rejected output.
- Verified: 48 offline tests; migrations on copies of both original databases preserved rows and integrity, with originals unchanged. Changes are local; no production deployment or second poller started.


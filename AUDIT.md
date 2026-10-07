# AutoReplyBot audit — 2026-10-05

> Historical findings from the pre-change repository. Local remediation and verification are documented in [IMPLEMENTATION.md](IMPLEMENTATION.md). Source line references below refer to the original baseline.

## Baseline and limits

- Local HEAD and GitHub `main` both equal `6538113d15dc99b693c60c35f9eefbbaae621fa3` (verified with `git ls-remote origin`). Tracked working tree was clean before this report.
- Repository: https://github.com/itjmu/autoreply_bot
- Latest commit only removes the unused `safe_send_message` helper from `bot.py`; the previous commit is `f256664`.
- Reviewed application structure, message flow, database operations, matching/policy, AI routing, FSM/menu wiring, payments, and deployment files. Findings below are static code findings and risks, not server incident diagnoses.
- Server commit, logs, process state, dependencies, and live database were not available. Matching GitHub does not prove the server runs this commit.
- No application code, configuration, database, or server changes. No Telegram polling or paid AI requests. Python is unavailable on this environment's PATH; runtime tests were not run. Secret values were not printed.

## Existing strengths

- Async Telegram/HTTP/SQLite architecture; database layer separated from handlers.
- FAQ first, AI second, fallback last; formatted/media FAQ support.
- SQLite WAL and atomic AI quota reservation (`BEGIN IMMEDIATE`, database.py:3105).
- Owner-scoped FAQ/chat queries and explicit admin checks in management handlers.
- Timezone-aware schedules and daily AI quotas; bounded history per chat.
- Persistent business connections/settings and restart configuration for Docker/systemd.

## Prioritized findings

| Priority | Finding and consequence | Evidence / correction |
|---|---|---|
| Critical exposure risk | Both `autoreply.db` and its backup are tracked in Git, despite ignore rules. They can contain customer data and provider keys. The backup is also included in Docker build context/image because `*.db` does not match `*.db.backup-*`. Actual contents and repository visibility were not verified. | `git ls-files`; `.gitignore`; `.dockerignore`; database.py:4055. Preserve production DB, remove DB artifacts from tracking, exclude backup patterns, inspect exposure privately and rotate any exposed keys. History cleanup needs separate coordination. |
| High | Disabling all configured providers can reactivate providers from the environment order. Empty enabled order triggers fallback without distinguishing explicit disable from missing configuration. | ai_service.py:265–308. Honor disabled DB rows; only use defaults when no persisted provider configuration exists. |
| High | Cooldown does not prevent calls: generation iterates `ready + cooling`. An outage can retry every failing provider on every message. With five providers and the default 40-second timeout, the provider chain can take about 200 seconds, plus overhead. | ai_service.py:1183–1320, especially 1245; config.py:12. Skip cooling providers and impose one overall response deadline. |
| High | Owner replies are ignored without recording takeover or cancelling pending answers. A bot answer already waiting on delay/AI can still arrive after the owner responds or disables autoreply. | bot.py:8968–8986, 9039, 9242, 9615. Record owner activity; recheck pause/settings before sending; cancel stale chat work. Telegram-side connection settings may also affect delivery. |
| High | No per-chat serialization/debounce or persistent processed-message marker in the business handler. Rapid messages can produce overlapping AI calls, reordered replies, mixed history, repeated album fallbacks, and racing fallback counters. | bot.py:8899–9645; database.py:2713–2777. Add bounded chat queues/debounce, stale-answer cancellation, and deduplication. |
| High | Every startup deletes pending Telegram updates. Messages and payment updates queued during downtime can be discarded. | bot.py:9854–9856. Preserve queued updates; deduplicate and explicitly decide how to handle old business messages. |
| High | Premium renewal sets expiry to `now + days`, losing remaining paid time; buying a week during an active month can shorten access. | database.py:1164–1214. Extend from `max(now, current_expiry)` atomically. |
| High | Payment handling has no stored charge ID/idempotency or payment ledger. Checkout always accepts; successful handling checks period but not currency/amount. Duplicate delivery or failures around activation cannot be reconciled reliably. | bot.py:3790–3872. Persist invoice terms and unique charge IDs; validate against issued invoice; apply activation and ledger transaction together. |
| Medium | A failed FAQ send logs an error and returns; fallback is never attempted. Customer receives no answer on that path. | bot.py:9296–9329. Fall through to a safe fallback after send failure. |
| Medium | AI quota can remain consumed after an exception, cancellation, or failed send. Release recomputes today's date, so a failure crossing owner midnight releases the wrong day. | bot.py:9398–9551, 9615–9645; database.py:3197–3235. Return a reservation identifier/day and finalize or release it reliably; document whether usage counts generation or successful delivery. |
| Medium | Client history is interpolated into the system prompt, increasing prompt-injection risk and confusing trusted instructions with customer text. | ai_service.py:1391–1415, 1462–1489. Use separate user/assistant message roles with explicit trust boundaries. |
| Medium | Direct FAQ matching forces a 0.95 score for substring matches, ignoring negation and extra meaning. `cancel order` can match `do not cancel order`. Blocked-topic substring matching can also catch unrelated words. | matcher.py:47–57; policy.py:63–66. Add representative language/negation cases and safer matching thresholds/token boundaries. |
| Medium | User/profile text can grow without field limits; fallback plus promotional signature can exceed message length. Most sends do not use the existing truncation helper. Broad swallowed UI errors can leave users with no visible result. | bot.py:2883–2969, 8353–8401, 8856–8895. Validate fields before saving, split/limit outgoing text safely, show recoverable UI errors. |
| Medium | Stop-AI wording suggests the assistant stops replying, but only AI pauses; FAQ/fallback continue. This conflicts with a customer's request for a human handoff. | bot.py:9104–9133, 9276, 9336, 9584. Provide separate, clearly named AI pause and full autoreply pause/handoff. |
| Medium | Deployment from a fresh Docker clone creates a new DB under `./data`, while the existing local DB sits at project root. Existing accounts/settings disappear unless data is migrated intentionally. | docker-compose.yml. Use a SQLite-consistent backup and explicit migration/restore instructions. |
| Low | FSM and pending FAQ albums live only in memory; restart loses in-progress setup. Report task is not retained/cancelled during shutdown. | bot.py:1947–2041, 9844–9846, 9884–9903. Add persistent FSM only if needed; manage background-task lifecycle. |
| Low | Referral insertion checks existence outside its write transaction; concurrent requests can race and raise a uniqueness error. | database.py:3728–3786. Use conflict-safe insertion and award bonuses only when insertion succeeds. |

Global blocked topics currently apply to the AI branch only, after direct FAQ matching. If the intended policy covers all replies, move the policy check before FAQ; otherwise document its AI-only scope.

## What is missing for dependable operation

1. A regression suite for provider disable/cooldown, renewals/payment replay, midnight quota release, rapid chat messages, takeover, overnight schedules, and failed FAQ sends.
2. Reproducible dependency locking and a separate staging bot/token/database.
3. Automated SQLite-consistent backups with a tested restore, explicit migration versioning, and rollback instructions.
4. Response latency/error metrics, outage alerts, bounded AI concurrency, Telegram retry-after handling, and actionable error logs.
5. Customer-data retention/deletion controls; historical chats remain stored even though each chat's message count is bounded.
6. Clear handoff behavior and honest media limitations: incoming media without text currently receives fallback, without transcription/image understanding.

Avoid a large rewrite initially. The current architecture can support these improvements incrementally.

## Safe implementation order

1. Establish server baseline read-only: deployed commit or file hashes, installed dependency versions, actual DB path, one running process, recent error logs. Never launch a second poller with the production token.
2. Secure DB artifacts and backups; verify whether repository history exposed credentials/data.
3. Patch provider disable/cooldown and Premium renewal/payment accounting in an isolated branch; verify with mocks and a temporary DB.
4. Add takeover/queue/deduplication and failure recovery; verify on a separate staging bot.
5. Back up production, deploy a reviewed commit, monitor errors/latency, and retain a tested rollback.

This report does not certify production health; it establishes the repository baseline and concrete repair priorities.

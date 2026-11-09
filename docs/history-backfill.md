# Discord history backfill and restart reconciliation

**Status (2026-11-09):** Live archive, FTS5 search, restart reconciliation and bounded backfill are implemented. The operator completed a 30-day production backfill; no full historical crawl or deletion audit is claimed.

The bot archives live guild text messages in SQLite. This feature adds two complementary ways to catch older messages without changing normal reply behavior.

## Automatic restart reconciliation

On the first Discord gateway-ready event after process startup, a background task replays the newest **100 messages per accessible text channel**. It uses the existing idempotent archive path. The bounded replay does not invoke the LLM, and it does not intentionally scan years of history. It is best-effort: outages with more than 100 messages per channel may require manual backfill. Discord deletions missed while offline cannot be reconstructed from history alone.

## Explicit historical backfill

Run inside the **dev** bot pod (uses its mounted SQLite database and Discord credentials):

```bash
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.storage.backfill --days 30 --limit-per-channel 100 --dry-run

kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.storage.backfill --days 30 --limit-per-channel 100
```

- `--days` is the oldest allowed message age, measured from execution time.
- `--limit-per-channel` caps messages read **per channel per invocation** (1–1000). Repeat the command to continue into older history.
- `--dry-run` counts accessible messages without writing rows or advancing checkpoints.
- Each imported message advances its channel's durable `backfill_cursors.before_message_id` checkpoint. An interrupted run resumes from the last successfully archived message.
- Channels are discovered from the bot's current server. No guild ID configuration or opt-in subsystem.
- Repeated reads do not duplicate rows (Discord message ID is the primary key). Deleted-message markers prevent resurrection; edit timestamps prevent stale snapshots overwriting newer revisions.
- The command starts a separate Discord gateway client using the same token as the running bot. SQLite WAL allows concurrent access, but run only **one backfill command at a time**.
- A channel's cursor is deliberately not reset automatically. To start a new historical pass from the newest messages, an operator must explicitly remove that channel's checkpoint. Automatic startup reconciliation already covers the newest 100.

The bot needs View Channel, Read Message History and Message Content access. Discord rate limits are handled by discord.py. Backfill currently covers ordinary guild text channels, not DMs or threads.

## Validation

1. Verify startup logs include `History reconciliation: channel=... scanned=...`.
2. Run the dry-run command; inspect per-channel scanned counts and confirm database row counts do not change.
3. Run a bounded 30-day import with 100 messages per channel; inspect `messages`, `messages_fts`, and `backfill_cursors`.
4. Repeat the import; confirm each channel continues from its saved checkpoint without duplicating messages.
5. Restart the bot; verify live replies still work and recently missed messages are reconciled.

**Outside this backfill command:** Reaction ingestion and shadow evaluation run as separate live features; automatic memory extraction, full historical deletion auditing and unbounded backfill are not implemented. The FTS5 history search tool is implemented separately.

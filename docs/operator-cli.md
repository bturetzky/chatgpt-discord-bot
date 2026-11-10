# Operator CLI

Run inside the existing bot container; no separate service or dashboard.

```bash
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin --help
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin status
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin reactions
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin reactions --react-only
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin archive
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin memories --stats
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin memories --limit 20
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin memories --verify-pinecone
```

Replace `discord-dev` with `discord-prod` to inspect production. `--json` is a **global** option, so put it before the subcommand, e.g. `python -m discord_bot.admin --json reactions`. The CLI uses the configured `DISCORD_SQLITE_PATH` and `REACTION_SHADOW_GUILD_ID`; override guild with global `--guild-id` when necessary. Never commit guild IDs or memory contents to the repository.

## Reports

- **status**: SQLite integrity and table counts, plus selected feature configuration; no external connectivity test.
- **reactions**: recorded shadow decisions, trigger, emoji, reason, tokens and Discord message links. An empty result means **zero persisted evaluations**, not proof the feature is disabled. Historical archive messages are not replayed as shadow candidates.
- **archive**: message count, channel coverage, oldest/newest timestamps, deletion count and cursor count. Backfill cursor count is global to the environment's SQLite file.
- **memories --stats**: candidate and batch statuses, cumulative extraction input/output tokens; not a billing statement.
- **memories**: accepted candidates by default; `--status all` includes proposed, rejected and superseded. `--verify-pinecone` fetches deterministic autonomous vector IDs and checks for `origin=autonomous-v1`; `not_found` does not prove an older manually stored memory is absent. A local `accepted` status alone does **not** prove the remote vector still exists.

All reports are read-only. `--verify-pinecone` makes read-only Pinecone requests and requires `PINECONE_API_KEY`.

## Historical extraction

```bash
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.admin backfill --days 30 --max-chunks 12 --chunk-hours 1

# Resume from the printed next_since timestamp:
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.admin backfill \
  --since 2026-11-01T12:00:00Z --until 2026-11-02T00:00:00Z \
  --max-chunks 12 --chunk-hours 1
```

This uses the **existing archived SQLite messages**, not the Discord history API. The CLI requires the OpenAI key and Discord bot token to identify the bot author. It uses the existing bounded extraction path and records candidate proposals in SQLite; already completed batches are skipped on reruns. It reports a `next_since` cursor for the operator to use in the next invocation. Each chunk must contain at most `--max-windows` windows (maximum 50) and `--max-rows` messages (default 1,000); narrow `--chunk-hours` if a busy chunk exceeds the limit. Model calls incur cost. Only one manual backfill should run at a time.

**Important:** The CLI does not call Pinecone directly. **However, when `AUTONOMOUS_MEMORY_ENABLED=true`, the running background worker can subsequently evaluate and publish newly proposed candidates.** Do not treat historical extraction as a harmless dry run in production. Use dev first and inspect candidates before deliberately running against prod. There is not yet a safe operator-controlled review-and-publish workflow.

## Deferred on purpose

No live reaction posting, memory deletion/correction, arbitrary Pinecone index enumeration, Discord slash admin commands, UI, generic SQL execution or automatic production changes. Keep this CLI a small inspection tool.

# Operations and manual acceptance

Use the existing bot container and persistent SQLite database; there is no separate dashboard. Start in dev. Replace `discord-dev` with `discord-prod` only for intentional production inspection. Avoid pasting real guild IDs, raw Discord messages or private memory content into GitHub.

## Operator CLI

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

Global `--json` and `--guild-id` options precede the subcommand. Inspection commands are read-only; `--verify-pinecone` makes read-only remote fetches. SQLite `accepted` does not by itself prove the vector still exists; a `not_found` result requires investigation of vector identity, namespace and deduplication, not automatic deletion. The previously observed discrepancy was operator-verified and is not an open acceptance item.

`status` shows integrity, flags and row counts; `reactions` reports recorded decisions/emoji/reason/token use and message links; `archive` reports coverage/cursors; `memories` reports candidates and extraction usage. Empty shadow results mean no persisted evaluations, not necessarily disabled observation.

## Two different backfills

**Discord message archive import** reads the Discord history API, storing messages in SQLite:

```bash
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.storage.backfill --days 30 --limit-per-channel 100 --dry-run
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.storage.backfill --days 30 --limit-per-channel 100
```

`--days` bounds age; `--limit-per-channel` caps each channel per invocation (1–1000). Durable per-channel cursors make repeated runs resumable without duplicate message IDs. `--dry-run` does not advance cursors. Run one backfill at a time; it opens a separate Discord gateway connection with the existing token. Startup also reconciles the newest 100 accessible messages per channel. Missed deletions while offline cannot be reconstructed.

**Historical memory extraction** processes *already archived SQLite messages* and records extraction proposals; it does not fetch Discord history:

```bash
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.admin backfill --days 30 --max-chunks 12 --chunk-hours 1
# Resume with the next_since cursor printed by the previous run:
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.admin backfill --since 2026-11-01T12:00:00Z \
  --until 2026-11-02T00:00:00Z --max-chunks 12 --chunk-hours 1
```

The second command's timestamps are **illustrative**, not current operational dates. Completed extraction batches are skipped. Narrow `--chunk-hours` if bounded window/row limits are exceeded. Model calls cost money. **Critical:** although the CLI does not directly publish to Pinecone, an enabled autonomous worker may later evaluate and publish the resulting proposals. It is not a production-safe dry run. Use dev and obtain approval for production historical processing.

## Reaction shadow inspection

```bash
kubectl -n discord-dev logs deploy/chatgpt-discord-bot --since=24h | grep 'Reaction shadow'
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.admin reactions
```

With `REACTION_SHADOW_ENABLED=true` and a matching guild ID, the evaluator observes eligible text/reactions but **never posts emoji**. For deterministic **dev-only** testing, set `REACTION_SHADOW_TEST_PREFIX` temporarily in dev GitOps, send a fresh eligible non-reply message starting with it, wait at least 60–90 seconds, and inspect logs and persisted rows. This consumes one of the 8 evaluations/rolling 24 hours; remove the prefix afterward. Two distinct humans reacting to a recent eligible message should yield a `pile_on` evaluation; one human adding several emoji must not. This multi-human path and sustained production decision quality remain pending operator acceptance.

## Discovery shadow dev acceptance

After the application rolls out to dev, configure `DISCOVERY_SHADOW_CHANNELS` through dev GitOps for test text channels with SQLite archive coverage and Brave access. Start with JSON `null` for channel hints so topic selection relies on archived discussion and accepted memories. The bot needs to see each configured channel. From the dev bot container, inspect the persisted runs and candidates with the dev guild ID:

```bash
python -m discord_bot.admin --guild-id "$DEV_GUILD_ID" --json discovery --limit 20
```

The worker rotates among quiet channels, reserving one attempt every six hours. When every available channel is active before reservation, the run outcome is `deferred_active`. This consumes none of the six-hour interval, and the worker checks again within a minute. A run outcome of `deferred_after_work` means activity was detected after discovery work began. The existing reservation still counts toward the six-hour interval. A restart does not reset a spent window. Inspect the outcome, channel, search, fetch, model and embedding attempt counts, reported tokens, and any candidate URL, reason, evidence and draft.

1. In a dev test channel, discuss a game or project with a recent public announcement across several substantive messages. Leave it quiet for at least 30 minutes before its turn. Look for a selected opener whose link and public excerpt support its claims. Confirm Discord receives no unsolicited message or reaction.
2. Before a later turn, share a result URL with a tracking query or discuss the same announcement in your own words. Expect `archived_url` or `same_story` when the source appears and the prior discussion is found. Check that a substantive later development can still qualify.
3. Keep a test channel active during its turn or configure a game query for a channel whose archived discussion is unrelated. Expect a preflight deferral with zero provider calls if every channel is active. When a channel becomes quiet, expect a run without waiting for a new six-hour window. Weak archive context or an unrelated candidate should produce no draft. An unreadable source should yield `source_unavailable` without a draft.

Record candidate quality and absence of unsolicited activity before accepting Phase 1. Remove the temporary dev configuration after the check.

## Dev Discord smoke test

After ARC dev rollout verification, **actually select the bot from Discord's @-mention picker**; typing a literal `@chatgpt-dev` string is not sufficient. Test a brief calculation (17 × 23 = 391), weather lookup, Brave search for official Python docs, public webpage fetch (`https://docs.python.org/3/`), and an existing-memory question that does not write new memories. Expect an accurate result or explicit provider failure, never a fabricated read. For changed image handling, test direct and replied-to images plus unsupported/expired attachments. For memory changes, test retrieval and source attribution without inserting false permanent facts. Live image/replied-image understanding and #99 retrieval enhancement have already been operator-verified; repeat targeted tests only when behavior changes.

```bash
kubectl -n discord-dev rollout status deployment/chatgpt-discord-bot --timeout=120s
kubectl -n discord-dev logs deploy/chatgpt-discord-bot --since=10m
```

A healthy Deployment or gateway-ready log is not a substitute for a real Discord response. Temporary DEBUG logging may expose memory contents; normal logging was operator-confirmed restored. Avoid collecting sensitive content. For promotion and rollback see [deployment](deployment.md).

For image ingestion failures, the `attachment_mime` field counts inspected attachments by sanitized MIME category and whether the filename had a recognized image extension. For example, `generic/recognized_extension=true:1` records one attachment with a generic MIME and a recognized extension. The field contains no filenames, URLs, or raw MIME values.

When a decoded image disagrees with an attachment or CDN MIME header, the `Image MIME mismatch` line records the detected supported format and two mismatch flags. The bot uses the decoded format.

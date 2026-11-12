# Operations and manual acceptance

Use the existing bot container and persistent SQLite database; there is no separate dashboard. Start in dev. Replace `discord-dev` with `discord-prod` only for intentional production inspection. Avoid pasting real guild IDs, raw Discord messages or private memory content into GitHub.

## Operator CLI

```bash
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin --help
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin status
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin reactions
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin reactions --posted-only
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin archive
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin memories --stats
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin memories --limit 20
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin memories --verify-pinecone
```

Global `--json` and `--guild-id` options precede the subcommand. Inspection commands are read-only; `--verify-pinecone` makes read-only remote fetches. SQLite `accepted` does not by itself prove the vector still exists; a `not_found` result requires investigation of vector identity, namespace and deduplication, not automatic deletion. The previously observed discrepancy was operator-verified and is not an open acceptance item.

`status` shows integrity, flags and row counts; `reactions` reports recorded decisions, posting outcomes, selected emoji and message links; `archive` reports coverage/cursors; `memories` reports candidates and extraction usage. Historical shadow rows have no posting outcome. An `attempting` row may represent an interrupted request with an uncertain outcome.

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

## Live emoji reaction regression procedure (operator-verified)

Live reaction posting and pile-ons have already been verified by the operator. Use these steps only for regressions or changed behavior. Select the dev Kubernetes namespace and use a dev text channel in the configured guild with persistent SQLite. The bot needs View Channel, Read Message History and Add Reactions. Choose fresh human messages with at least 12 characters and allow for recent channel and author cooldowns.

1. Send a playful message such as “The rubber duck found the bug before I did.” With the existing dev test prefix configured, start the message with that prefix to force sampling. Wait 60–90 seconds for a decision. The model can still ignore it.
2. On a fresh message, have two different people add an emoji. Look for a `pile_on` evaluation if the message was not independently sampled. If the bot posts, compare the visible emoji with the CLI result.
3. As a negative case, have one person add two emoji to a message. This alone should never trigger a pile-on. An `ignored` decision should leave the bot absent from the reaction list.

```bash
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin reactions
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin reactions --posted-only
kubectl logs deploy/chatgpt-discord-bot --since=24h | grep 'Reaction evaluated'
```

The CLI includes Discord message links. Use the first command to inspect cooldowns, model decisions and Discord errors. Remove the dev test prefix after use if it was set temporarily.

## Discovery shadow dev acceptance

After the application rolls out to dev, discovery starts automatically when the gateway is ready and the SQLite archive is available. External search uses the existing Brave credentials. From the dev bot container, inspect runs and candidates across all guilds. Add `--guild-id` before the subcommand to filter to one guild.

```bash
python -m discord_bot.admin --json discovery --limit 20
```

The worker checks channel eligibility each minute and reserves at most one attempt per six hours across the bot. If all available channels are active before reservation, `deferred_active` consumes no interval. A `deferred_after_work` run still counts toward the interval. Restarting preserves the reservation and rotation cursor.

1. Start dev with an eligible quiet text channel. On an empty archive, expect `weak_context` and zero provider calls. Restart within six hours and check that there is no new reservation, including for other guilds.
2. Add a standard text channel or grant the bot View Channel and Read Message History in an existing channel. Confirm it can enter rotation without restarting. Revoke either permission and confirm future runs skip it. An active channel should be skipped in favor of a quiet eligible one.
3. In an eligible dev channel, discuss a game or project with a recent public announcement across several substantive messages, then let the channel stay quiet for 30 minutes. Inspect the channel, evidence, reason, usage and any proposed draft at its turn. Confirm Discord receives no unsolicited message or reaction.

For a discovery `provider_error`, match the SQLite run ID to the application log. Logs use UTC timestamps and include the discovery stage, exception type and traceback locations. Discovery omits raw exception messages and response bodies.

## Dev Discord smoke test

After ARC dev rollout verification, **actually select the bot from Discord's @-mention picker**; typing a literal `@chatgpt-dev` string is not sufficient. Test a brief calculation (17 × 23 = 391), weather lookup, Brave search for official Python docs, public webpage fetch (`https://docs.python.org/3/`), and an existing-memory question that does not write new memories. Expect an accurate result or explicit provider failure, never a fabricated read. For changed image handling, test direct and replied-to images plus unsupported/expired attachments. For memory changes, test retrieval and source attribution without inserting false permanent facts. Desktop-pasted PNG, image embed/reply handling, live reactions, and #99 retrieval enhancement have already been operator-verified; repeat targeted tests only when behavior changes.

```bash
kubectl -n discord-dev rollout status deployment/chatgpt-discord-bot --timeout=120s
kubectl -n discord-dev logs deploy/chatgpt-discord-bot --since=10m
```

A healthy Deployment or gateway-ready log is not a substitute for a real Discord response. Temporary DEBUG logging may expose memory contents; normal logging was operator-confirmed restored. Avoid collecting sensitive content. For promotion and rollback see [deployment](deployment.md).

For image ingestion failures, the `attachment_mime` field counts inspected attachments by sanitized MIME category and whether the filename had a recognized image extension. For example, `generic/recognized_extension=true:1` records one attachment with a generic MIME and a recognized extension. The field contains no filenames, URLs, or raw MIME values.

When a decoded image disagrees with an attachment or CDN MIME header, the `Image MIME mismatch` line records the detected supported format and two mismatch flags. The bot uses the decoded format.

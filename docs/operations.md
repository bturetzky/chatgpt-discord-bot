# Operations and manual acceptance

Use the existing bot container and persistent SQLite database; there is no separate dashboard. Start in dev. Select the intended Kubernetes namespace in your current context before running these commands; they deliberately omit `-n` so the same commands work in dev and prod. Avoid pasting real guild IDs, raw Discord messages or private memory content into GitHub.

## Operator CLI

```bash
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin --help
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin status
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin reactions
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin reactions --posted-only
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin reactions --react-only
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin discovery
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin --json discovery --limit 20
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin archive
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin memories --stats
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin memories --limit 20
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin memories --verify-pinecone
```

Global `--json` and `--guild-id` options precede the subcommand. Inspection commands are read-only; `--verify-pinecone` makes read-only remote fetches. SQLite `accepted` does not by itself prove the vector still exists; a `not_found` result requires investigation of vector identity, namespace and deduplication, not automatic deletion. The previously observed discrepancy was operator-verified and is not an open acceptance item.

`status` shows integrity, flags and row counts. `reactions` shows pending windows and scheduling state, rolling model attempts, triggers, window sizes, reasons, token usage, selected emoji and message links, and posting outcomes. Historical shadow rows have no posting outcome. An `attempting` row may represent an interrupted request with an uncertain outcome.

`discovery` reports six-hour budgets, runs, reasons, source URLs and shadow drafts across all guilds by default. `archive` reports coverage and cursors. `memories` reports candidates and extraction usage.

## Two different backfills

**Discord message archive import** reads the Discord history API, storing messages in SQLite:

```bash
kubectl exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.storage.backfill --days 30 --limit-per-channel 100 --dry-run
kubectl exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.storage.backfill --days 30 --limit-per-channel 100
```

`--days` bounds age; `--limit-per-channel` caps each channel per invocation (1–1000). Durable per-channel cursors make repeated runs resumable without duplicate message IDs. `--dry-run` does not advance cursors. Run one backfill at a time; it opens a separate Discord gateway connection with the existing token. Startup also reconciles the newest 100 accessible messages per channel. Missed deletions while offline cannot be reconstructed.

**Historical memory extraction** processes *already archived SQLite messages* and records extraction proposals; it does not fetch Discord history:

```bash
kubectl exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.admin backfill --days 30 --max-chunks 12 --chunk-hours 1
# Resume with the next_since cursor printed by the previous run:
kubectl exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.admin backfill --since 2026-11-01T12:00:00Z \
  --until 2026-11-02T00:00:00Z --max-chunks 12 --chunk-hours 1
```

The second command's timestamps are **illustrative**, not current operational dates. Completed extraction batches are skipped. Narrow `--chunk-hours` if bounded window/row limits are exceeded. Model calls cost money. **Critical:** although the CLI does not directly publish to Pinecone, an enabled autonomous worker may later evaluate and publish the resulting proposals. It is not a production-safe dry run. Use dev and obtain approval for production historical processing.

## Direct reply reaction dev acceptance

Use the deployed dev bot in a test guild channel with Read Message History and Add Reactions permissions. Have a usable custom emoji ready. Mention the dev bot in each prompt. Reaction selection is optional, so try a few variations and check that any reaction appears on the mention that triggered the reply and that the bot sends its answer without a reaction progress message.

1. “My rubber duck just asked for a performance review. What should I put on it?” Look for an occasional fitting reaction alongside an answer.
2. “What is the capital of France?” Expect a normal answer without a reaction.
3. Include an actual guild emoji and ask “My rubber duck got promoted! If that fits, react with this emoji or 😂 and try both, then write a one-line toast.” Expect the toast and at most one reaction from the reply. Try variations to observe the custom emoji.
4. In a dev channel where the bot lacks Add Reactions, repeat the humorous prompt on a fresh message with no reactions. Expect the answer even if a reaction attempt fails. Automated tests verify the failure path and repeated or concurrent tool calls deterministically.

## Conversation reaction dev acceptance

After dev deployment, use a text channel in the configured guild with persistent SQLite and View Channel, Read Message History and Add Reactions permissions. Allow for recent channel and author cooldowns and check the rolling evaluation budget. Leave the dev test prefix out of the timing checks.

1. Send one playful message in a quiet channel and leave it idle. Expect a `conversation_window` decision with one new message after approximately an hour.
2. Have participants exchange 10 fresh messages in a quiet channel, including a joke or a surprise. Expect a `conversation_window` decision without waiting an hour.
3. On a fresh message, have one person add two emoji. This alone should produce no immediate evaluation. Have a second person add an emoji and expect a prompt `pile_on` decision. Later windows may include the message as context.

The model can ignore any window. If it selects a message and the CLI reports `posted`, check that the visible bot reaction matches the selected emoji.

```bash
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin reactions
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin reactions --posted-only
kubectl logs deploy/chatgpt-discord-bot --since=24h | grep -E 'Reaction (evaluating|evaluated|skipped|model failure)'
```

The CLI includes Discord message links. Use the first command to inspect cooldowns, model decisions and Discord errors. Remove the dev test prefix after use if it was set temporarily.

## Discovery shadow dev acceptance

After the application rolls out to dev, discovery starts automatically when the gateway is ready and the SQLite archive is available. External search uses the existing Brave credentials. From the dev bot container, inspect runs and candidates across all guilds. Add `--guild-id` before the subcommand to filter to one guild.

```bash
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin discovery
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin --json discovery --limit 20
kubectl logs deploy/chatgpt-discord-bot --since=24h | grep -i 'discovery'
```

The `started_at` field is a Unix UTC timestamp; compare it with the last deployment rollout and the six-hour reservation interval before concluding a fix has run. `Discovery shadow enabled` only confirms startup. `complete` means evaluation finished, not that a draft was accepted. `provider_error` requires examining the corresponding log stage; `weak_source` and `source_unavailable` are rejected candidates, not drafts. A new pod does not reset the persistent six-hour interval.

The worker checks channel eligibility each minute and reserves at most one attempt per six hours across the bot. If all available channels are active before reservation, `deferred_active` consumes no interval. A `deferred_after_work` run still counts toward the interval. Restarting preserves the reservation and rotation cursor.

1. Start dev with an eligible quiet text channel. On an empty archive, expect `weak_context` and zero provider calls. Restart within six hours and check that there is no new reservation, including for other guilds.
2. Add a standard text channel or grant the bot View Channel and Read Message History in an existing channel. Confirm it can enter rotation without restarting. Revoke either permission and confirm future runs skip it. An active channel should be skipped in favor of a quiet eligible one.
3. In an eligible dev channel, discuss a game or project with a recent public announcement across several substantive messages, then let the channel stay quiet for 30 minutes. Inspect the channel, evidence, reason, usage and any proposed draft at its turn. Confirm Discord receives no unsolicited message or reaction.

For a discovery `provider_error`, match the SQLite run ID to the application log. Logs use UTC timestamps and include the discovery stage, exception type and traceback locations. Discovery omits raw exception messages and response bodies.

## Dev Discord smoke test

After ARC dev rollout verification, **actually select the bot from Discord's @-mention picker**; typing a literal `@chatgpt-dev` string is not sufficient. Test a brief calculation (17 × 23 = 391), weather lookup, Brave search for official Python docs, public webpage fetch (`https://docs.python.org/3/`), and an existing-memory question that does not write new memories. Expect an accurate result or explicit provider failure, never a fabricated read. For changed image handling, test direct and replied-to images plus unsupported/expired attachments. For memory changes, test retrieval and source attribution without inserting false permanent facts. Desktop-pasted PNG, image embed/reply handling, live reactions, and #99 retrieval enhancement have already been operator-verified; repeat targeted tests only when behavior changes.

```bash
kubectl rollout status deployment/chatgpt-discord-bot --timeout=120s
kubectl logs deploy/chatgpt-discord-bot --since=10m
```

A healthy Deployment or gateway-ready log is not a substitute for a real Discord response. Temporary DEBUG logging may expose memory contents; normal logging was operator-confirmed restored. Avoid collecting sensitive content. For promotion and rollback see [deployment](deployment.md).

For image ingestion failures, the `attachment_mime` field counts inspected attachments by sanitized MIME category and whether the filename had a recognized image extension. For example, `generic/recognized_extension=true:1` records one attachment with a generic MIME and a recognized extension. The field contains no filenames, URLs, or raw MIME values.

When a decoded image disagrees with an attachment or CDN MIME header, the `Image MIME mismatch` line records the detected supported format and two mismatch flags. The bot uses the decoded format.

## Linked message dev acceptance

Use the dev bot after rollout. Prepare a message in a guild text channel that both the requester and bot can view and read history in, a message that the archive has observed being deleted, and a link to a channel the requester cannot read. Use test messages only.

1. Mention the bot with “What does <message link> say, who wrote it, and what attachments or reactions are there?” Expect the source content, correct author and jump link, and metadata when present.
2. Mention the bot with “Read channel ID <channel ID>, message ID <message ID>” for a known visible message outside the archive if available. Expect the same attribution and content via Discord.
3. Ask the bot to read the saved link to the deleted message. Expect an unavailable response without message content or attribution.
4. Ask the bot to read the restricted link. Expect an inaccessible response without details about the target message.

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

`discovery` reports the effective reservation interval, Pacific quiet hours, per-run budgets, run traces and shadow drafts across all guilds by default. `archive` reports coverage and cursors. `memories` reports candidates and extraction usage.

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

Use a dev guild with `DISCOVERY_ENABLED=true`, persistent SQLite, an eligible quiet text channel, archived discussion, and configured Brave credentials. The default randomized Pacific-day opportunity survives restart. A custom interval uses elapsed time after the last reservation. Discovery runs from 8 AM up to 10 PM Pacific. A reserved run that crosses 10 PM before selection or delivery records `deferred_quiet_hours`. Add `--guild-id` before the subcommand to filter results.

```bash
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin --json discovery --limit 3
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin discovery --run-id 1 --posts
kubectl exec deploy/chatgpt-discord-bot -- python -m discord_bot.admin --json discovery --run-id 1 --posts
```

Replace `1` with the run ID under review. Match `started_at` (Unix UTC seconds) against the rollout. Check context window scopes and sizes, search purposes, source read outcomes, rejected drafts and decisions. Compare `duration_ms`, call counts and reported input/output tokens across runs. The `cached_input_tokens` field is the cached portion of `input_tokens` and defaults to zero when the API has no cached count or the run predates tracking. `complete` includes runs that finish without a selection. A source error reports its provider code and any HTTP status. For `provider_error`, correlate the run ID and stage with the safe traceback in application logs.

1. Discuss base building or logistics in a dev text channel, then leave it quiet for at least 30 minutes. After an eligible run inspect the trace for a public query and an adjacent lead, such as a project with unusual automation mechanics. If selected, the draft should read like a conversational observation and link to a fetched source. An older date should not itself disqualify the find.
2. Share and discuss a public project link ahead of an eligible later run. If exploration revisits that link or rediscovers the same story, expect a duplicate decision for a previously selected source or a story the group already discussed. Unselected sources may retry after 24 hours in the same channel or on the next eligible run for another channel. If sources fail or nothing clears review, expect an inspectable reason and no selected post.
3. Keep the destination active around a scheduled check. Expect the worker to skip the active channel or suppress selection if conversation resumes during exploration. If selection succeeds, verify that Discord receives the reviewed text with one source link. If the destination is active at send time, expect suppression.

After rollout, inspect several new multi-call runs using the JSON command above. Compare `cached_input_tokens / input_tokens` alongside model call counts and context size. Expect reuse within a run with at least 1,024 eligible prefix tokens when the provider reports a cache hit. Daily runs can sample different contexts and begin with a cold cache. The SDK regression test verifies serialized requests and usage accounting with synthetic responses. Provider cache hits and discovery draft quality require deployment observation. If eligible multi-call runs still show zero cache reads, compare OpenAI project cache metrics and confirm the effective model before changing retention or routing. [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)

## Prometheus dev acceptance

After a dev rollout, scrape the bot's port 9100 from an authorized local or internal connection. Expect `process_start_time_seconds` and a connected gateway. For worker checks, use an environment where the relevant worker is already enabled. Before sending Discord prompts, confirm Prometheus has scraped the new process and record the DM answered and reply search success counters. Expect a zero for either series that has had no events in this process. Check the next scrape for the expected deltas.

1. DM the dev bot a short calculation. Expect one successful DM request and reply model usage. Send an ordinary unmentioned guild message and confirm that reply counts stay unchanged.
2. Mention the dev bot and ask it to use web search to find the official Python documentation. With Brave configured, expect a reply, a registered search tool execution, and model metrics for the reply. If the tool reports a provider failure, expect the tool error outcome and an honest fallback or answer from available context.
3. During an eligible discovery or reaction cycle, compare decision, delivery-attempt, and confirmed-delivery deltas with the existing operator CLI and the Discord result. A healthy idle poll should advance the worker's last-success timestamp without a delivery attempt.

## Dev Discord smoke test

After ARC dev rollout verification, **actually select the bot from Discord's @-mention picker**; typing a literal `@chatgpt-dev` string is not sufficient. Test a brief calculation (17 × 23 = 391), weather lookup, Brave search for official Python docs, public webpage fetch (`https://docs.python.org/3/`), and an existing-memory question that does not write new memories. Expect an accurate result or explicit provider failure, never a fabricated read. For changed image handling, test direct and replied-to images plus unsupported/expired attachments. For memory changes, test retrieval and source attribution without inserting false permanent facts. Desktop-pasted PNG, image embed/reply handling, live reactions, and #99 retrieval enhancement have already been operator-verified; repeat targeted tests only when behavior changes.

```bash
kubectl rollout status deployment/chatgpt-discord-bot --timeout=120s
kubectl logs deploy/chatgpt-discord-bot --since=10m
```

A healthy Deployment or gateway-ready log is not a substitute for a real Discord response. Temporary DEBUG logging may expose memory contents; normal logging was operator-confirmed restored. Avoid collecting sensitive content. For promotion and rollback see [deployment](deployment.md).

For image ingestion failures, the `attachment_mime` field counts inspected attachments by sanitized MIME category and whether the filename had a recognized image extension. For example, `generic/recognized_extension=true:1` records one attachment with a generic MIME and a recognized extension. The field contains no filenames, URLs, or raw MIME values.

The image downloader preserves the encoding of Discord proxy URLs, including escaped origin query parameters. A non-200 proxy response produces `download_unavailable` and logs only the HTTP status. If Discord's proxy refuses the image, the bot still answers from text context.

When a decoded image disagrees with an attachment or CDN MIME header, the `Image MIME mismatch` line records the detected supported format and two mismatch flags. The bot uses the decoded format.

## Linked message dev acceptance

Use the dev bot after rollout. Prepare a message in a guild text channel that both the requester and bot can view and read history in, a message that the archive has observed being deleted, and a link to a channel the requester cannot read. Use test messages only.

1. Mention the bot with “What does <message link> say, who wrote it, and what attachments or reactions are there?” Expect the source content, correct author and jump link, and metadata when present.
2. Mention the bot with “Read channel ID <channel ID>, message ID <message ID>” for a known visible message outside the archive if available. Expect the same attribution and content via Discord.
3. Ask the bot to read the saved link to the deleted message. Expect an unavailable response without message content or attribution.
4. Ask the bot to read the restricted link. Expect an inaccessible response without details about the target message.

## Discord thread dev acceptance

After dev rollout, use the dev bot in a guild channel where both test accounts and the bot can view the channel and read history. Create the test messages after rollout so their reply references enter the archive. Keep a second account outside a private thread for the permission check.

1. Post a root, an unrelated neighboring message and two Discord replies to the root. Reply to one of those replies. Ask the bot to “Follow the reply conversation from <reply link>.” Expect the root, both branches and the nested reply with jump links. The neighboring message should be absent.
2. Create a native thread and post two standalone messages and an explicit reply. Ask “Read native Discord thread <thread ID>.” Expect all three thread messages, with a parent link for the explicit reply only.
3. Delete the root of the first conversation and repeat the linked-reply request. Expect the surviving connected messages and an incomplete-coverage indication. Ask from the nonmember account to read the private thread. Expect an access failure without thread content.

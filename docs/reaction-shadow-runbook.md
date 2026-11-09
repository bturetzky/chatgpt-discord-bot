# Reaction shadow mode — rollout and observation

Status: proposed in PR; not verified in Discord until merged, deployed, and exercised.

Shadow mode **never posts emoji or unsolicited messages**. It uses the existing SQLite PVC and the existing OpenAI API key, but a separate tool-free Responses request. Normal mentions and DMs are unchanged.

## Configuration

- `REACTION_SHADOW_ENABLED=true` — explicitly opt in (default false).
- `REACTION_SHADOW_GUILD_ID=<numeric guild ID>` — required when enabled. Only this guild is evaluated, even if the bot belongs to multiple servers.
- `REACTION_SHADOW_TEST_PREFIX` — optional, **dev-only** acceptance hook. When set, a new eligible message starting with this literal prefix bypasses 1-in-12 sampling, but still obeys the 60-second delay, guild gate, content eligibility and persistent 8/24h budget. Never set in production.\n- `REACTION_SHADOW_MODEL` — optional model override; defaults to `OPENAI_MODEL`.

The environment variables belong in the deployment manifest in `homelab-gitops`. Set the guild ID independently in dev and production. Deploy and validate dev first, then use the existing manual digest-promotion workflow and a separate production GitOps configuration PR. Production must remain disabled until explicitly enabled. Never put tokens in Git.

## Cheap gates

- Independent candidates: stable 1-in-12 sampling of new eligible human text messages.
- Pile-ons: at least **two distinct observed human reactors**, regardless of the number of emoji from each person; reaction events are debounced 60 seconds.
- Candidate content must be a recent (within 10 minutes), nondeleted, archived guild text message of at least 12 characters. DMs, bot/webhook authors, mentions, replies, commands and non-text channels are excluded from independent sampling.
- At most 16 delayed candidates in memory; one pending/evaluated candidate per message. Both triggers share a single evaluation budget.
- Maximum **8 reserved model evaluations in a rolling 24-hour window**, persisted in `shadow_evaluations`. Restarting the bot does not reset the budget. Failed model requests also consume the allowance.
- Candidate decisions are advisory only; no calls to Discord's add-reaction API. No image/URL enrichment, history tools, Pinecone or memory writes.

These gates are conservative starting points to tune with actual production activity. No separate live-reaction posting budget has been approved.

## Deterministic dev acceptance\n\nWith the new image deployed, set `REACTION_SHADOW_TEST_PREFIX=[shadow-test]` in the **dev** GitOps deployment only. Send a fresh, ordinary non-reply text message in the dev guild, for example `[shadow-test] This should evaluate exactly once`. After 60–90 seconds, check the log for `Reaction shadow candidate`, `Reaction shadow evaluating` and `Reaction shadow: trigger=independent`. Inspect the SQLite row. This is a **real model call** and consumes one of the eight rolling daily evaluations; it cannot bypass the budget. Do not post the test message to the bot or as a reply. Remove the test prefix from GitOps after validation, before promoting to production.\n\n## Observe results

```bash
kubectl -n discord-dev logs deploy/chatgpt-discord-bot --since=24h | grep 'Reaction shadow'
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- python -c '
import os,sqlite3
db=sqlite3.connect(os.environ["DISCORD_SQLITE_PATH"])
for row in db.execute("""SELECT evaluated_at,trigger,status,decision,emoji_key,reason_category,input_tokens,output_tokens
 FROM shadow_evaluations ORDER BY evaluated_at DESC LIMIT 25"""):
 print(row)
'
```

Change namespace to `discord-prod` after explicit promotion. A zero-row table means no model evaluations were made; it is not proof that no events were observed. Reactions observed before enabling shadow mode do not trigger retroactive evaluations. Human reaction counts are event-derived and may be incomplete across outages.

## Manual acceptance

1. Confirm the configured guild ID is the intended dev server and the bot is responsive.
2. Add emoji from **two distinct humans** to a recent, non-bot message with at least 12 characters; allow at least 60 seconds. Expect a `pile_on` evaluation row and a log with decision/tokens. Multiple emoji from one human must not suffice.
3. Post ordinary messages; expect occasional `independent` evaluations, not a model call for every message.
4. Restart the bot; confirm rows persist and the 8/24h allowance is not reset.
5. Confirm the bot never adds an unsolicited emoji or text message. Confirm no evaluations in its other guilds.
6. Promote only after CI and live dev acceptance. Observe production results for several days before proposing live reaction posting.

Known limitations: event-derived reaction counts can miss pre-existing or offline reactions; a sampled message can be ignored by eligibility filters; the model may ignore all candidates; the evaluation budget is a cap, not a quota; logging includes no message bodies.

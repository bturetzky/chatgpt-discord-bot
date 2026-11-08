# Proactive Personality and Reaction Awareness — design

**Status:** Proposed; design only, not implemented.  
**Last reviewed:** 2026-11-07  
**Scope:** chatgpt-discord-bot; Kubernetes deployment configuration belongs in `bturetzky/homelab-gitops`.

## Goal

Give an otherwise quiet Discord bot the ability to notice the social context of its home server and **occasionally add a well-timed emoji reaction without being mentioned**. The result should feel amusing and natural, not intrusive. Separately, let the bot understand reactions added by other members as context for conversations and future [Server Awareness](server-awareness-design.md) search/memory extraction.

This is a feature, not an always-on chatbot: no unsolicited text replies in v1.

## Confirmed product decisions

- **Activity-aware pacing instead of a fixed four-per-day budget (revised proposal).** Four per day was an initial preference, but discussion identified that it is probably too restrictive for a small, reaction-heavy server. The final numerical budget is not yet agreed; use a rolling token bucket with a hard failsafe cap. Zero reactions is always acceptable.
- **Reactions only initially**. No unsolicited text replies, DMs, threads or scheduled commentary.
- **Both standard Unicode and available server custom emoji** are eligible. Validate every selected emoji against an explicit permitted set and Discord's current availability.
- Small trusted server (~5 people, 10–15 channels). Use one configured home guild, with no manual channel allowlist, but only channels the bot can access. Exclude DMs and threads initially.
- Reaction awareness (observing members' reactions) must be usable independently of proactive reactions.
- Reuse the existing bot process and, once available, Server Awareness's persistent SQLite database. No new hardware, GPU or service.
- Ship disabled by default, validate in dev/shadow mode, and promote through the existing manual production process.

## User experience

- A member posts an amusing callback to an old failed gaming plan; the bot might add 💀, 🤨, or a relevant custom emoji.
- Someone shares a remarkable achievement; the bot might add 🔥 or a server-specific celebration emoji.
- A conversation is routine or ambiguous; the bot does nothing.
- Members ask the bot about how the server reacted to an earlier post; the bot can use indexed emoji counts and original message links once Server Awareness search is implemented.

**Non-goals:** replying to every conversation, reacting on a timer to hit a quota, reacting to its own posts, escalating disagreements, pretending reactions are factual endorsements, or creating permanent relationship memories from emoji alone.

## Architecture

```text
Discord gateway (home guild)
  |-- message events -> normal mention/DM path (unchanged)
  |                  -> Server Awareness archive (when enabled)
  |                  -> cheap proactive candidate gate
  |                          -> bounded delayed evaluation queue
  |                          -> optional compact LLM decision
  |                          -> policy validator + persistent rate limiter
  |                          -> Discord add_reaction (or no-op)
  |
  +-- raw reaction add/remove/clear events
           -> reaction-awareness store (when available)
           -> optional signal for candidate prioritization (never an automatic reply)
```

Implement separate modules/services for reaction event ingestion, candidate filtering, decision-making and action execution. Do not call the normal conversational tool loop for proactive decisions. The latter has too many tools and a different prompt/behavior.

## Reaction awareness

Use `discord.py` raw reaction events (`on_raw_reaction_add`, `on_raw_reaction_remove`, and clear variants where supported) so observing reactions does not depend on Discord's message cache. Ensure required guild/message/reaction intents and channel permissions; verify exact Discord API behavior in dev.

Track per-message emoji identity (Unicode emoji or custom emoji ID), reaction count and **distinct human reactor counts** for candidate scoring; use member IDs only as needed for deduplication and optionally retain bounded aggregate state rather than indefinite individual reaction histories. Prefer minimal data retention. Reactions may be removed, cleared, or missed while the bot is offline: reconcile counts for selected messages when practical and mark historical counts as potentially incomplete. Avoid mistaking bot-added reactions for independent human feedback.

For the Server Awareness SQLite archive, proposed tables:
- `message_reactions`: guild/channel/message ID, normalized emoji key, observed count, last observed timestamp, optional reconciliation status.
- `reaction_events` only if necessary for deduplication/reconciliation; avoid indefinite event-level history by default.
- `proactive_actions`: unique message ID, guild/channel, selected emoji, decision timestamp, posted timestamp, status, local calendar day, model/policy version and minimal rationale category (not private message text).
- `proactive_evaluations` (optional, bounded retention): shadow-mode candidate outcomes, token usage, rejection reason and timing.

Do not embed raw reaction events in Pinecone. Reaction totals and patterns are weak social signals; do not infer durable opinions, relationships, consent or group decisions solely from emoji.

## Two complementary proactive triggers (confirmed)

Both **independent first reactions** and **joining existing human reaction pile-ons** are desired behaviors. A fresh-message candidate gate and a debounced reaction-activity gate feed the same bounded decision engine. Neither requires the other: the bot can be first to react, or join an interesting reaction thread after multiple humans have reacted. Do **not** enforce a fixed quota or ratio between these modes; let actual server activity drive selection. Deduplicate by target message ID across both paths, including in-flight evaluations and action reservations, and apply the same rolling budget, cooldowns, safety checks and single-reaction-per-message policy to both. A pile-on is a strong candidate signal, not a mandate to copy the crowd or react at all.

## Candidate selection: cheap first, rare model calls

**Delayed reaction triggers:** a message may become interesting *after* others react to it. Coalesce raw reaction events for the same message into a short debounce window (proposed 30–120 seconds), then score it once; avoid a model call per added emoji. Favor reaction diversity and distinct humans over raw counts. Only consider recent messages and cancel pending evaluations on deletion. A pile-on should increase the probability of evaluation, not guarantee a bot reaction.

**Do not run an LLM on every Discord message.** Use a low-cost local gate with bounded queues and probabilistic sampling. Candidate signals may include:
- A short exchange among multiple humans in a channel with recent activity.
- A message that attracts reactions from **multiple distinct humans** or a burst of replies; reaction pile-ons are especially promising candidates. Count distinct reacting users rather than raw emoji events, and exclude the bot's own reactions.
- A topical callback to known server lore (only when Server Awareness memory is available).
- An interesting, playful message that passes local filters, including occasional random sampling to avoid predictable selection.

Avoid brittle keyword-only rules that always react to the same phrase. Candidate selection is a heuristic, not a requirement that the message be funny.

Suggested initial knobs (tune in dev, not confirmed):
- **Rolling reaction allowance**, proposed token bucket: capacity 6, refill 1 token every 2 hours, with a separate hard failsafe ceiling of 12 posted reactions in any rolling 24-hour window. These are discussion defaults, **not approved product limits**. A busy evening can spend multiple accumulated tokens; a quiet morning does not consume any allowance. Persist bucket state across restarts.
- **Short burst protection**, proposed 10–20 minute guild-wide cooldown and no more than 2 proactive reactions in any rolling hour; tune after observing actual server behavior. Avoid rigid multi-hour channel cooldowns.
- Maximum **1 bot reaction per original message**. Remove the one-per-author-per-day restriction; use a rolling fairness check to avoid repeatedly singling out one member, without blocking natural exchanges.
- Bounded evaluation budget, e.g. **8 model evaluations per day**, not a target. Local sampling/queue size prevents busy channels from consuming all evaluations.
- Optional short randomized delay (e.g. 30 seconds to 5 minutes) before evaluation/posting, but **revalidate freshness** and skip stale/deleted messages; do not schedule reactions hours later to fill a quota.
- Ignore bot/webhook messages, messages authored by the bot, DMs, unsupported channel types, commands, obvious sensitive or distressing content, and messages that mention the bot (those already follow normal interaction). Avoid reacting to moderation or conflict situations.
- Human reaction pile-ons are a **strong positive candidate signal**, not merely incidental context. They can trigger evaluation after a short debounce window, even if the original message was not a candidate at creation. The bot still chooses its own emoji or ignores the message; copying the most popular reaction is not mandatory.

The daily limit and cooldowns are **hard execution policy**, not merely model prompt instructions. Random sampling and delays must be bounded and cancellation-safe.

## Decision model

Only after passing the local gate, construct a small context packet:
- Candidate message ID, author ID/display name, text and timestamp.
- A bounded window of preceding and subsequent messages in that channel (e.g. 5–10, with total character/token cap).
- Current reaction counts and eligible emoji list, including available custom emoji IDs/names.
- Optionally a few relevant, source-backed Server Awareness memories if available and inexpensive; do not require Pinecone lookup for every candidate.
- No automatic fetching of images, YouTube transcripts or arbitrary links. [Rich Content Understanding](rich-content-understanding-design.md) remains user-triggered by default.

Use a separate bounded OpenAI request that returns validated structured output, for example:

```json
{
  "action": "ignore",
  "emoji_key": null,
  "reason_category": "ordinary_conversation"
}
```

or `{"action":"react","emoji_key":"unicode:💀","reason_category":"playful_callback"}`. Custom emoji keys should use stable IDs, not model-invented names. The model must choose from the supplied allowlist; the executor verifies it again before posting.

Prompt for a conservative preference for `ignore`, humor without bullying, and an understanding that channel content and retrieved memories are **untrusted data**, not instructions to bypass limits. Never let message content direct the bot to react to a different message, reveal secrets, call tools or alter configuration.

A small inexpensive model can be evaluated in dev; exact model, token cost and success rate remain unverified. Log aggregate tokens and cost through the existing usage metrics, not message bodies or private reasoning.

## Action execution and durable limits

- Store action reservations and successful sends transactionally in persistent SQLite with a unique constraint on target message ID; recheck guild/channel/author cooldowns and daily quota immediately before execution.
- Discord API calls are external side effects, so SQLite alone cannot guarantee exactly-once behavior across a crash. On ambiguous timeout or restart, fetch the target message and check whether the bot already reacted before retrying; favor **skipping** over duplicate reactions.
- Use a single active proactive executor per guild; dev and prod use separate guilds and databases. If Server Awareness's PVC is not implemented yet, launch in observation/shadow mode or explicitly provision a small durable state store; **do not** silently reset the daily budget on pod restart.
- Recheck message existence, current permissions, emoji availability, age, and whether the bot has already reacted. Skip deleted/edited content if the original decision no longer applies.
- Honor Discord rate limits and permission errors. On failures, record status and apply backoff; do not spam retries.
- Provide a fast operational kill switch (e.g. `PROACTIVE_REACTIONS_ENABLED=false`), with shadow mode separate from live mode. A deployment configuration change may require restart; a runtime switch is optional later.

## Interaction with Server Awareness and Rich Content Understanding

- **Shared ingestion:** Server Awareness stores messages and reaction counts; proactive personality reads bounded conversation context from the same archive when present.
- **Independent rollout:** proactive reaction observation and shadow evaluation can be implemented before the full history backfill/memory extractor. Deep lore callbacks improve after Server Awareness ships but are not required for basic reactions.
- **No new memory from bot reactions:** bot-generated reactions must not be treated as human consensus. The memory extractor may use human reaction patterns as weak supporting context, never as a sole source.
- **Content boundaries:** no automatic vision inference or transcript processing just to decide whether to react. A post containing only an image/link may be skipped if its meaning cannot be determined cheaply; future explicit opt-in enrichment is separate.
- **Provenance:** reaction-aware historical answers should cite original Discord message links. Reaction counts are observed snapshots, not guaranteed complete historical totals.

## Implementation integration points

- `discord_bot/handlers/discord_handler.py`: add raw reaction event callbacks, separate nonblocking proactive observation from `process_message`, preserve existing mention/DM behavior, and ignore own reactions/messages.
- New `discord_bot/handlers/` or `discord_bot/services/` modules: reaction store, candidate gate, decision client, policy executor, scheduler and configuration.
- `discord_bot/handlers/chatgpt_handler.py`: use existing OpenAI client conventions and usage accounting, but **do not** reuse the normal multi-tool conversation path for proactive decisions.
- Server Awareness SQLite schema/migrations: add reaction and proactive action tables; use the same persistent PVC in each environment when that project is deployed.
- `bturetzky/homelab-gitops`: owns enabling flags, secrets if needed, PVC and operational configuration.

## Tests and acceptance criteria

**Unit/integration**
- Correctly observe reaction add/remove/clear with Unicode and custom emoji; events from uncached messages work.
- Exclude DMs, foreign guilds, bot/webhook authors, deleted messages and mention-triggered conversations from unsolicited reaction logic.
- No proactive LLM call for ordinary messages that fail the cheap gate; queue and evaluation budgets are enforced.
- Invalid model output, fabricated custom emoji IDs, prompt injection and unavailable emoji result in no reaction.
- Exactly one reaction per target, per-author and per-channel cooldowns, and rolling token refill, burst ceiling and hard 24-hour failsafe; verify concurrent tasks, clock boundaries and pod restart persistence.
- Verify ambiguous API timeouts/retries do not cause duplicate reactions.
- Bot-added reactions are not counted as independent human endorsements.
- Existing text chat, tools, memory and Discord reply behavior remain unchanged.

**Dev validation**
1. Enable reaction observation only; verify counts, custom emoji IDs and event handling.
2. Enable shadow mode; log candidate/evaluation counts and aggregate costs, without posting. Inspect a bounded sample of proposed decisions, not all message bodies.
3. Enable live reactions in the dev guild with the selected rolling allowance and hard failsafe; validate comedic timing, author distribution, permissions and opt-out switch.
4. Promote to production manually with the feature disabled initially; enable explicitly after validation.
5. Monitor posted reactions, skip reasons, failures, average evaluation cost and human feedback. Reduce frequency if the bot feels intrusive.

**Done when:** The bot can observe reactions independently, occasionally post contextually appropriate Unicode/custom emoji reactions without mentions, remain silent most of the time, obey durable budgets across restarts, and be disabled without affecting normal chat.

## Open questions (not blocking design)

- Confirm numerical rolling-bucket capacity/refill, burst cooldown and hard 24-hour failsafe after discussing actual server activity; timezone is no longer needed for a daily reset.
- Whether to permit emoji on very old messages; proposed no, react only to recent conversation.
- Whether a future moderator/user command should allow opt-out per person or channel if the server's norms change.
- Whether custom emoji selection should include animated emoji (proposed yes if permissions and API support are confirmed).
- Whether reaction awareness needs exact per-user reaction history or aggregate counts alone; default to aggregate counts unless a concrete feature requires more.

**Implementation status:** Design only. No code, SQLite schema, Discord intents, PVC or deployment has been changed.

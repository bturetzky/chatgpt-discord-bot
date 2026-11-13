# Feature backlog

This is the only list of **approved unfinished features** and concrete follow-up decisions. It is not a priority queue, release history, or speculative technical-debt inventory. A feature is ready for Codex when its scope and acceptance boundary are explicit. Implemented behavior belongs in [architecture](architecture.md), operator procedures in [operations](operations.md), and completed work in GitHub PR history.

## Approved on-demand LLM tool assignments

The independent Codex assignments for tool enhancements and new callable functions, including any pending dev acceptance, are indexed in [tool designs](tool-designs/README.md). Each design has its own scope, tests and dev acceptance boundary; implement one per PR. These are distinct from background discovery, reactions and memory extraction. The index is the authoritative list of these tool assignments; do not duplicate them here.

## Direct reply emoji reactions

Dev Discord acceptance is pending. Use the [dev acceptance procedure](operations.md#direct-reply-reaction-dev-acceptance).

## Conversation-aware emoji reactions

Dev Discord acceptance is pending for hourly quiet-channel evaluation, the 10-message trigger and immediate pile-ons with conversation context. Use the [dev acceptance procedure](operations.md#conversation-reaction-dev-acceptance).

## Approved feature assignments

### Memory lifecycle — assignment A: reliable publication

**Outcome:** SQLite/Pinecone publication is restart-safe, with deterministic vector identity and reconciled outcomes. Wire existing ledger/revision helpers into the worker rather than building a general transaction framework.

**Codex boundary:** Persist intent before remote writes; reconcile after ambiguous interruption (including a crash after remote success but before SQLite acceptance); use idempotent retries and bounded diagnostics. Add interruption/restart regression tests. Preserve current create-only behavior until assignment B.

### Memory lifecycle — assignment B: correct and forget

**Depends on:** assignment A.

**Outcome:** A narrow explicit way to correct or forget a memory, plus invalidation when its archived source evidence changes or is deleted.

**Codex boundary:** Implement targeted update/delete handling in SQLite and Pinecone, prevent retired memories from reappearing, and handle legacy vectors with missing provenance conservatively. Test correction, deletion, source edits/deletes, retries and retrieval after removal. No general multi-guild ACL system or wholesale legacy migration.

### Proactive external discovery — finish shadow review, then live posting

**Current implementation:** Discovery shadow mode exists and records inspectable decisions without posting. Operator review of the current shadow behavior remains the decision gate for a separate live-posting PR. Do not conflate this with the **already verified** live emoji reaction feature.

**Next Codex assignment:** Only after satisfactory shadow review, implement the Phase 2 live-posting behavior below. Keep dev acceptance and manual production promotion separate.

### Behavior and selection contract

- **Channel interests:** Phase 1 considers eligible text channels automatically and uses channel names and topics as weak hints. Refine interests from relevant archived channel discussion and existing durable server memories, including shared interests and context. Do not assume a generic channel name captures its actual interests. Do not persist private raw conversations or memory text in candidate logs.
- **Discovery:** Reuse existing bounded news/search and webpage-reading capabilities where suitable; fetch and verify the actual source before drafting claims. Prefer substantive, timely developments over generic headlines or recycled trending lists. If source access fails or facts cannot be supported, reject the candidate. Treat all external content as untrusted.
- **Novelty:** Check canonicalized URLs and persistent prior suggestions/posts, plus archived links and semantically similar prior discussions. Distinguish *the same story under a new URL* from a genuinely new development on an existing topic. Embedding similarity may shortlist related material, but must not alone decide novelty; use bounded evidence-aware comparison for ambiguous cases. Never post the same underlying story twice, including after restarts.
- **Decision:** Require strong channel relevance, meaningful new information, source quality, and a reason to interrupt. The bot should usually choose silence. Avoid interrupting an active conversation; prefer an appropriate quiet window without manufacturing activity. No posting quota to fill.
- **Voice:** Draft a short, conversational, opinionated opener with a source link and an optional natural invitation to discuss. Do not produce generic news digests, impersonate users, invent personal experiences, or fabricate article contents. Use memory only as context, not as an excuse to expose private facts.
- **Budget:** Initial live-posting target is **at most 1–2 posts per week across the entire server**, not per channel. Make the final limit configurable and durable; use cooldowns and dedupe as separate gates. Discovery runs may occur a few times daily, but must have bounded candidate counts, search calls, model calls and embedding use. Avoid idle repeated model evaluations of unchanged candidates.
- **Persistence and operations:** Use the existing per-environment SQLite database for discovery cursors/checkpoints, canonical source/story identity, evaluation decisions, proposed drafts and posting outcomes. Ensure idempotent retries and inspectable rejection reasons without retaining unnecessary source text or sensitive memory. No new database/service or generalized multi-guild framework. Add concise operator inspection via existing admin tooling if practical.

### Phase 1 — shadow review

Use the [dev acceptance procedure](operations.md#discovery-shadow-dev-acceptance) to assess the shadow worker and its persisted decisions.

**Phase 1 acceptance:**
1. Relevant new, accessible source yields a short, source-linked candidate for an appropriate eligible text channel; unrelated channel/source is rejected.
2. Identical/canonicalized links and different URLs describing the same already-discussed story are rejected, including after restart; a *meaningfully new development* about that topic may qualify.
3. Discovery derives a public topic from archived conversation or durable interests. Channel metadata does not override contrary discussion context. Empty or stale-only context is handled conservatively. Active channels defer without spending an unused discovery window.
4. Missing/unreadable sources, misleading article claims, exhausted API budgets and provider failures fail closed without fabricated drafts or unbounded retries.
5. SQLite survives restart without replaying accepted/rejected unchanged work; shadow never sends Discord messages. Verify that one durable six-hour budget applies across all joined guilds.
6. Operator can inspect enough bounded evidence to judge relevance, novelty, tone and cost before approving Phase 2. Include dev acceptance instructions; do not claim human verification from CI.

### Phase 2 — guarded live posting (separate approval and PR)

Only after the operator accepts Phase 1 candidate quality: implement an **explicit opt-in** posting switch, channel allowlist, durable server-wide weekly cap (initially 1–2), per-channel and server cooldowns, story-level dedupe, source verification at posting time where appropriate, permissions/rate-limit/error handling, and an immediate kill switch. Reserve/record posting intent and reconcile ambiguous delivery outcomes rather than blindly retrying and duplicating messages. Preserve manual dev acceptance and manual production promotion; do not silently enable production posting.

**Phase 2 acceptance:** demonstrate in dev that only permitted channels receive source-linked openers, active discussions are not interrupted, weekly/cooldown limits survive restart, duplicate stories are not reposted, provider/Discord failures are safe, and disabling posting stops further messages. Production enablement is a separate operator decision.


### Contextual conversational interjections — new approved feature

**Outcome:** The bot occasionally joins an ongoing server conversation with a genuinely relevant or funny short message without being mentioned. Unlike external discovery, this uses the **current conversation** as its trigger; it does not fetch news to start a new topic.

**Codex boundary:** One bounded, opt-in text-message feature in the existing configured guild. Observe eligible conversation windows, decide whether the bot has a worthwhile contribution, and otherwise remain silent. Use recent context and existing memory retrieval where helpful; do not create a new background indexing system. Respect quietness, cooldowns, an explicit disable switch, and restart-safe duplicate suppression. Never reply to its own messages or create loops. Make decisions inspectable without logging private raw chat. Define a modest configurable posting budget during design, not an arbitrary global priority.

**Acceptance:** In dev, demonstrate a relevant interjection, silence on mundane or stale conversations, no duplicate posting after restart, correct handling of Discord errors, and immediate disablement. Avoid triggering during an active exchange in which a bot message would be disruptive.

## Evaluation, not yet implementation

**Relationship/lore recall:** Test real multi-person shared history, attribution and callbacks beyond recent channel context. If retrieval already works, close the evaluation. If it fails, record concrete examples (without committing private messages) and scope a targeted Codex feature. No broad memory-quality project is approved.

## Ideas to discuss, not approved work

- **Server lore and callbacks:** Natural use of recurring jokes and shared history, beyond simply retrieving correct facts. May overlap with relationship-memory evaluation.
- **Long-running conversation awareness:** Recognize a discussion resuming after time has passed and restore the right context. Define a concrete experience before approving implementation.

Social games/challenges were explicitly rejected. Do not silently promote these ideas into approved tasks.

## Deliberately out of scope

Automatic historical catch-up, speculative richer reply/media archive, reaction-lock optimization, bot-message sleep refactor, generic provider edge-case work, routine memory-quality tuning, automatic production promotion, general multi-guild ACL platform, always-on dashboard, automatic Codex resumption, headless browser, and sweeping refactors. Revisit only on new evidence and an explicit decision.

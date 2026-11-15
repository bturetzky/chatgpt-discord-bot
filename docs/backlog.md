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

**Pending operator verification:** Review the contextual exploration worker in dev before considering a separate live-posting PR. Use the [dev acceptance procedure](operations.md#discovery-shadow-dev-acceptance) to assess conversational relevance, novelty, source grounding, privacy, duration and cost. Include an older find or an adjacent interest, an already-discussed item under different wording, and a run that ends without a selected post. Confirm durable scheduling and inspect rejection explanations alongside drafts. CI and rollout checks cover deployment and startup.

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

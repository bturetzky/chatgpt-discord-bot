# Server Awareness — design

> **Current implementation status:** See [memory lifecycle checkpoint](memory-lifecycle-status.md) for the authoritative implemented/tested/deferred breakdown. Historical sections below (including earlier “next implementation” language and “pending merge” PR notes) document decisions at the time; they do not override the current checkpoint. The read-only publication planner is pending merge/deployment, and Pinecone publication is still disabled.


**Status (2026-11-09):** SQLite persistence, live ingestion, FTS5 history search, restart reconciliation and bounded backfill implemented. Operator completed 30-day production backfill. Reaction add/remove/clear observation and shadow evaluation implemented; dev acceptance verified. Production reaction shadow mode verified running with posting disabled. Manual, bounded memory extraction is implemented and validated in dev and production; autonomous extraction, Pinecone publication, and live proactive reaction posting remain planned.  
**Last reviewed:** 2026-11-09  
**Scope:** chatgpt-discord-bot application. Kubernetes manifests and storage deployment belong in `bturetzky/homelab-gitops`.

## Goal

Let the bot learn from conversations in its home Discord server even when it is not mentioned. Enable evidence-backed cross-channel history search, selective automatic extraction of durable memories, and eventually richer understanding of shared links and attachments. The bot should not interrupt conversations merely because it indexed them.

## Context and decisions

- Small trusted server: approximately five active people, 10–15 channels, years of history; actual message count is unknown.
- Everyone in this server can access the channels the bot can access. No per-channel allowlist is planned.
- **Scope boundary:** this is a personal bot deployed to one Discord server per environment (dev has its own test server). Index ordinary guild messages received by the bot; ignore DMs and threads initially. No configured guild ID, per-guild opt-in, multi-tenant settings, or dynamic per-guild tables. Keep `guild_id` as message metadata. Historical backfill remains explicitly triggered.
- **Persistent SQLite** on a dedicated, initially **2 GiB Rook-Ceph RBD PVC** (proposed sizing; adjust based on measured usage). Do not rebuild the index on pod restart.
- **Keep current Discord recent-history fetch** for ordinary chat turns; SQLite is a historical archive/search index, not a replacement for current message context. Pinecone remains the semantic memory store.
- **No automatic unbounded historical crawl.** Backfill must be explicitly initiated with bounds, progress and resumability. Normal indexing and missed-message reconciliation can run automatically.
- **Automatic selective memory extraction**, initially dry-run for validation, then scheduled and autonomous. Memories must carry source references and avoid unsupported inferences.
- Keep implementation lightweight: Python, discord.py, SQLite/FTS5, existing OpenAI and Pinecone clients; no new server, Redis, Postgres, or GPU.

## Approved implementation sequence (2026-11-08)

1. Establish a small shared SQLite persistence foundation: database initialization, schema migrations, WAL/busy timeout, single-writer assumptions, tests, and separate dev/prod PVCs (manifests in `homelab-gitops`).
2. Implement Server Awareness message ingestion (including edits/deletes), FTS5 search, and bounded/resumable backfill, with staged validation.
3. Add reaction observation and shadow-mode candidate evaluation using the archived message context; retain reaction events and per-message counts in separate ordinary SQLite tables rather than FTS5.
4. Enable live proactive reactions only after durable budgets, cooldowns, action reservations and deduplication are implemented and validated. Exact numerical pacing remains undecided.
5. Add selective automatic memory extraction from indexed history, initially dry-run, with source provenance and Pinecone writes only after validation.

The shared database is infrastructure, **not** a single shared feature schema. Message text belongs in the archive/FTS5; reactions and their rate limits have separate tables and retention policies. The existing Discord recent-history path remains unchanged. Steps 1–3 are implemented as of 2026-11-09, with dev reaction observation and real shadow model evaluation verified. Production shadow rollout is configured and merged but runtime behavior has not been verified. Step 4 (live reaction posting) remains unimplemented. Step 5 has a validated manual dry-run extraction stage; scheduling and Pinecone writes remain unimplemented.

## Memory extraction architecture decision (2026-11-09)

**Primary outcome:** autonomously develop evidence-backed understanding of the server's collective culture (shared lore, recurring jokes, group experiences), not merely searchable history. Facts and preferences are useful secondary candidates. An extraction run may correctly produce zero memories.

- **One ingestion path:** live Discord messages and explicit historical backfill both populate SQLite. Extraction consumes **only the SQLite archive**, never the gateway event directly; no per-message LLM calls. The existing bot reply path and reaction shadow evaluation remain unchanged.
- **Execution:** run a bounded asynchronous background task in the existing single-replica bot pod, every several hours (initial suggested interval: **4 hours**, configurable). Avoid blocking the Discord event loop with synchronous model/database work. Provide an explicitly invoked, bounded historical processing mode against the same pipeline. Do not run competing schedulers. Initial code PRs establish segmentation and durable ledger only; they do **not** start the scheduler or call an LLM.
- **Conversation windows:** partition by guild/channel and idle gaps with message/token caps; use a settlement delay (initial suggestion: 30 minutes). Stable message boundaries, source hashes, and an extraction prompt version make retries and deliberate reprocessing reproducible. Small overlapping prior context may aid interpretation but must not become fresh extraction evidence.
- **Progress:** maintain a per-channel watermark or equivalent durable work discovery plus an `extraction_batches` ledger with processing status, attempts, source range/hash, extractor version, and timestamps. Advance progress only after successful durable completion; failures remain retryable. Handle changed/deleted source text by targeted re-evaluation rather than silently retaining invalid memories.
- **Candidate ledger:** persist proposed/rejected/accepted/superseded candidates with supporting message IDs, participants, attribution, and linked Pinecone IDs. Distinguish processing idempotency from **semantic memory deduplication**: match related memories and create/update/reinforce/ignore rather than writing repeated paraphrases. Track corrections and invalidation.
- **Prompt:** use a separate, evidence-focused extraction prompt, never the conversational personality prompt. Evaluate context, jokes versus assertions, disagreement and corrections; avoid inferring enduring relationships from isolated teasing. Extract shared lore only with sufficient evidence and avoid fabricated personal facts.
- **Retrieval:** accepted useful memories belong in the **existing Pinecone index**, because automatic response-time retrieval currently uses Pinecone, while SQLite history is only available through an explicitly invoked search tool. Don't add a second automatic SQLite retrieval path in this milestone. Ephemeral chatter should not become permanent memory; metadata/expiry and provenance allow future retention policies.
- **Rollout:** first process a bounded historical sample in **dry-run**, saving candidates and metrics to SQLite but making **no Pinecone writes**. Compare quality and token cost before enabling autonomous writes. Historical import never automatically triggers unbounded extraction. Preserve dev/prod isolation and manual production promotion.
- **Follow-on archive features, explicitly out of scope for this extraction milestone:** persist reply/reference/thread relationships for conversation reconstruction; persist attachment, URL and embed metadata without downloading binaries or automatically enriching every link/image. These need separate code PRs and their own tests.

### Staged code delivery

1. **PR 1:** SQLite migration for extraction ledger and deterministic, bounded text-only conversation segmentation; unit tests. No model calls, scheduling, Pinecone writes or Discord behavior changes.
2. **PR 2:** separate extraction prompt, structured candidates, bounded **operator-invoked** dry-run worker, durable result recording and token-usage metrics; no Pinecone writes. Implementation proposed in the dry-run PR; no scheduler or automated work discovery yet.
3. **PR 3:** semantic deduplication, provenance, correction/supersession and source invalidation; tests against realistic conversations.
4. **PR 4:** configurable multi-hour in-pod scheduling, guarded autonomous Pinecone writes and observability after dry-run acceptance.

## Architecture

```text
Discord gateway (bot's server; dev/prod isolated)
    |-- existing mention/DM reply path -> live Discord recent history + Pinecone
    |
    +-- new message/update/delete ingestion -> SQLite messages + FTS5
                                              |-- history search tool -> cited Discord links
                                              |-- periodic bounded conversation batching
                                              |       -> selective LLM extraction
                                              |       -> source-backed memory candidates
                                              |       -> Pinecone memories + SQLite provenance ledger
                                              +-- explicit, resumable historical backfill
```

### SQLite storage

Use a persistent single-writer SQLite database with WAL mode, migrations, appropriate busy timeout and periodic integrity checks. Prefer a dedicated PVC mounted only by the active deployment; **do not let dev and prod concurrently write the same SQLite file**. Use separate volumes/databases for dev and prod, or explicitly assign only one environment as the production indexer. Existing dev/prod Discord bots use different application tokens and servers.

Initial design tables (not a current schema inventory; see `discord_bot/storage/database.py` for authoritative migrations):
- `messages`: guild/channel/message IDs (unique), author ID, content, created/edited timestamps, deletion/tombstone state, attachment/link metadata, ingestion timestamp. Avoid storing unnecessary private metadata.
- `messages_fts`: FTS5 index over message text (with synchronized insert/update/delete handling).
- `channel_cursors`: per-channel last indexed message ID, reconciliation/backfill checkpoints and status.
- `extraction_batches`: stable batch ID, source range, processing version, status, usage/cost, retry count and completion timestamp.
- `memory_sources`: memory ID, source message IDs and links, participants, extraction timestamp, confidence/attribution, and invalidation status. Coordinate this ledger with Pinecone IDs.
- Optional `settings` / schema migration version.

Store Discord snowflake IDs as strings or 64-bit integers consistently. Build source links from the actual guild/channel/message IDs: `https://discord.com/channels/{guild_id}/{channel_id}/{message_id}`. A source link is not proof the content is still present; deletions/edits must be reconciled.

**Sizing:** 2 GiB is an initial hypothesis, not a measured requirement. Text-only history for a small server should be manageable, but years of activity and FTS overhead may exceed it. Measure database and WAL sizes after a bounded pilot; expand the PVC if necessary. Never archive attachment binaries in SQLite.

### Ingestion and reconciliation

- On new messages in eligible channels, store/update the archive without invoking OpenAI. Keep existing mention routing unchanged.
- Handle edits and deletes, including bulk deletes where available; tombstone or remove content and update FTS. If a deleted/edited source supported a memory, mark it for review/invalidation, rather than silently treating it as current evidence.
- Gateway events can be missed during downtime. On startup and periodically, reconcile recent messages per channel using persisted checkpoints, paginated and rate-limit-aware. Discord may not expose every deletion during downtime; document this limitation and consider a bounded periodic consistency pass.
- On first startup, **do not** automatically import all history. Provide an operator-triggered backfill (CLI/admin command or Kubernetes Job to be chosen) with channels discovered in the bot's server, lookback window and/or per-channel message cap, dry-run inventory, progress and resume support.
- Respect Discord permissions, pagination and rate limits; apply backpressure, bounded queues and retry policies. Never let indexing stall ordinary bot replies.
- Estimate volume using a cheap channel inventory (channel IDs, oldest/newest accessible messages, last indexed, sampled rate). Exact message counts require paginating history; report estimates honestly.
- Historical backfill may ingest messages in chunks; avoid triggering memory extraction until the selected chunks are fully indexed and validated.

### Search and retrieval

Implement a read-only `search_discord_history` tool, initially backed by SQLite FTS5, with bounded result counts and context windows. Support optional channel, author and date filters. Return short snippets, timestamps and source URLs; allow a follow-up fetch of adjacent messages for context. Avoid feeding entire channels into the model.

The current `discord_handler.py` path fetches recent Discord channel history (default 30 messages) and retrieves Pinecone context. **Do not replace this path initially.** Historical search is invoked when the user asks about older conversations or other channels. Semantic search over raw messages is a later enhancement if FTS proves insufficient; do not embed every message by default.

The five users share relevant channels. For history search, use the request's guild and check the requesting user's channel visibility before returning results; the dev and prod databases remain physically separate. No guild configuration or opt-in subsystem is needed.

### Selective memory extraction

- Schedule bounded analysis of newly indexed, coherent channel conversation windows (e.g. every four hours; split by idle gaps, participants, and maximum tokens). Do not run an LLM per message.
- Candidate categories: durable personal preferences explicitly stated, project/game plans and decisions, meaningful shared experiences, and recurring jokes clearly supported by context.
- Distinguish asserted fact, joke, quotation, speculation, disagreement and correction. Do not infer lasting relationships or personality traits from a single roast or ambiguous exchange.
- Each memory candidate should include concise text, type, explicit participant IDs, supporting source message IDs, source timestamps, and confidence/reason. Model confidence is a heuristic, not a guarantee of truth.
- Deduplicate against existing memories, and update/supersede contradicted facts rather than accumulating permanent conflicting claims. Preserve a correction/invalidation path and do not auto-resurrect invalidated memories.
- Persist accepted memories to existing Pinecone index with provenance metadata where feasible; keep full multi-source references in SQLite when metadata limits apply. Ensure deterministic IDs/idempotency across retries.
- Start with **dry-run** extraction into SQLite/logged aggregate metrics, with no Pinecone writes. Review sample candidates, false-positive rate and estimated cost, then enable autonomous writes with conservative thresholds. This is a rollout validation step, not ongoing manual approval.
- Process historic archives separately from new messages, with explicit bounded extraction ranges and budgets; backfill ingestion does not imply automatic mass memory generation.
- On retrieval, treat memory as potentially outdated and provide source links when relevant. If a source is deleted, edited materially, or becomes inaccessible, invalidate or withhold its dependent memory until revalidated.

### Cost, load and operations

- No LLM calls for routine ingestion or FTS queries; one bounded extraction pass every several hours initially, only for changed/eligible conversation windows.
- Configure maximum batches/day, messages/tokens/batch, total daily input/output tokens or estimated USD budget, concurrency and retry caps. Stop rather than exceed budget.
- Use existing OpenAI Responses API and usage logging; report extraction calls, tokens, estimated costs, candidates, accepted/rejected counts and indexing lag. Embeddings/Pinecone costs tracked separately where possible.
- Keep bounded ingestion queues; handle SQLite busy/disk-full errors gracefully without disrupting normal Discord responses. Surface backlog, indexing lag, disk usage and extraction failures.
- SQLite WAL and database must be backed up consistently (SQLite backup API or quiesced snapshot), with tested restore. GitOps repo owns PVC, backup and deployment details.
- No new hardware or additional long-running service is assumed; a small background task within the bot process is sufficient initially. Avoid duplicate schedulers when more than one replica is running.

### Future extensions (not initial scope)

- Extract webpage titles/content and YouTube transcripts for links, using existing webpage tooling and domain-specific readers with SSRF protections and limits.
- Understand selected image attachments and index useful descriptions; do **not** process every image automatically due to cost.
- Semantic message search if keyword search fails real user queries.
- Slash commands for search, history status, backfill control and memory provenance.
- User-visible corrections / forgetting with source-aware invalidation.

## Delivery sequence (proposed, not a task checklist)

1. **Archive foundation:** migrations, PVC, home-guild scoping, gateway ingestion, edits/deletes, checkpoints, tests, and storage metrics.
2. **Search:** FTS5 tool, contextual snippets and verified Discord permalinks; test real cross-channel questions.
3. **Bounded backfill:** inventory, explicit launch, resumability, reconciliation, and measured archive footprint.
4. **Extraction dry-run:** batch segmentation, candidate schema, source ledger, idempotency, cost instrumentation, and human evaluation of samples.
5. **Autonomous extraction:** conservative scheduled Pinecone writes, correction/invalidation behavior, monitoring and budget enforcement.
6. **Optional enrichment:** better link understanding and selective multimodal attachments.

## Open questions

- Which exact home guild ID and channel types should be in scope? Default: accessible ordinary text channels only; threads and DMs excluded.
- How much initial history should the operator request for the pilot (e.g. 30–90 days per channel) and for full backfill?
- Should edited/deleted messages be fully removed from the archive or retained as minimal tombstones? Proposed: delete original text, retain minimal tombstone for cursor/provenance bookkeeping.
- What retention policy should apply to raw archived messages and derived memories? No automatic indefinite retention decision has been made.
- How should corrections and explicit forget requests be exposed to server users?
- Should dev index only its own test guild (preferred) or use synthetic fixture archives to validate extraction behavior?
- Set a dollar/token ceiling after observing pilot extraction usage.

## Existing code integration points

- `discord_bot/handlers/discord_handler.py`: message gateway, current 30-message Discord history and Pinecone retrieval.
- `discord_bot/handlers/function_handler.py` and `discord_bot/functions/`: tool registration and history search.
- `discord_bot/handlers/chatgpt_handler.py`: Responses API and usage accounting; extraction should use a separate bounded prompt/path, not the normal chat personality prompt.
- `discord_bot/handlers/vector_handler.py` and `discord_bot/functions/memory_function.py`: existing embeddings and Pinecone memory writes; provenance/idempotency integration needed.


## Rich-content integration (design decision)

Server Awareness and [Rich Content Understanding](rich-content-understanding-design.md) share a reusable content reader/enrichment service but have **different invocation policies**. The passive indexer must never automatically perform expensive image inference, full YouTube transcript processing or arbitrary webpage reading for every posted message.

**Archive first:** record URL, attachment type/name/size, Discord embed metadata when present, surrounding message context, message IDs and timestamps. These are discovery hints, not proof of fetched content. Do not persist attachment binary content by default.

**Enrich selectively:** optional low-cost metadata fetching for supported public URLs can be introduced behind a queue with per-day budgets, deduplication, timeouts and failure caching. Default v1 is no automatic remote enrichment. If multiple messages share the same canonical URL, cache safe derived metadata keyed by canonical URL plus fetch version and expiry; do not conflate Discord message provenance with the fetched resource.

**On-demand deep reading:** when a user searches for a shared image/video/article, retrieve the original Discord message (if accessible) and invoke the rich-content reader as needed. Images may no longer be available if Discord attachment links expire or messages are deleted; say so rather than claiming the image was examined. YouTube transcript availability can also change.

**Memory extraction:** memory batches may use posted link titles, author commentary and discussion context; they must distinguish *what participants said about a link* from *what the linked content actually says*. No automatic memory claim about the contents of an unread video/article/image. Deep content-derived memory requires explicit enrichment and source provenance, and should not automatically store inferred facts about people.

**Provenance schema:** retain message-to-resource associations (message ID, URL/attachment ID, canonical URL, metadata source, retrieval timestamp, status, optional content digest and expiry). Derived descriptions/transcripts are optional and bounded, with clear deletion/invalidation behavior. Avoid storing full third-party article text, full transcripts or image binaries by default.

**Security and operations:** enforce the same SSRF defenses, fetch limits and prompt-injection isolation as interactive reading. The background indexer must not block Discord gateway handling or regular replies. On message edits/deletes, update associations and invalidate dependent enrichment/memories. Keep resource cache retention separate from raw-message and memory retention.

**Delivery dependency:** implement a stable rich-content reader interface now; Server Awareness can consume it later. Neither feature needs to wait for the other. The initial Server Awareness milestone remains text/URL/attachment-metadata indexing and search.

**Implementation status:** Nothing described here is deployed or implemented merely by creating this design. Keep this document updated as scope, decisions, validation and observed behavior change.


## History search dev acceptance

After CI passes and deployment to dev, mention the bot in a channel it can read:

1. Ask it to find a distinctive phrase known to exist in the dev archive; expect a short excerpt and a Discord message permalink.
2. Ask it to search for a phrase that appears only in a different accessible channel; verify the linked channel and source text.
3. Ask for a nonexistent phrase; expect an explicit no-results answer rather than invented quotes.
4. Test a channel hidden from the requesting member, if available; its messages must never be returned.
5. Edit or delete a known archived message and search for its old words; the old text must not be returned after the event is processed.

Search uses literal FTS5 words (AND semantics), at most ten snippets of 350 characters, with optional channel/author/date filters. It is scoped to the request guild and channels visible to the requester and bot. This does not yet implement adjacent-message expansion or semantic search. Production promotion remains deferred.

### History-search diagnostics (dev validation)

The history-search tool logs the literal query, optional requested channel, permitted channel IDs, and number of results for successful searches. Validation failures log the exception type. It does not log message content or excerpts. Use these logs to distinguish a permission-scope mismatch, unexpected query terms, and empty results. Search remains newest-first and defaults to five results; newer mentions can bury an older original message, so this is not yet relevance-ranked search. The November 7 `Roast me` message was verified present in SQLite and FTS5, but Discord end-to-end retrieval is still under investigation.

### Conversation-aware recall (dev acceptance pending)

After `search_discord_history` finds an anchor message, `get_discord_conversation_context` can read up to 10 archived messages before and after that anchor (16 combined), from the same channel, in chronological order. The caller must supply both IDs from the search result's Discord URL. Results include author, timestamp, bounded message content, permalink and anchor flag. The tool applies the requesting member's and bot's channel/history permissions, excludes deleted messages, and never crosses guild or channel boundaries. This is chronological context, not a verified reply graph. Test with the November 7 roast request: the bot should describe a specific detail from the subsequent reply rather than merely linking it. Search narration and response-style tuning remain separate follow-ups.

### Operator-invoked extraction dry-run (PR 2; pending merge and validation)

The second extraction PR introduces migration 8 (`extraction_candidates`, `extraction_usage`), an independent evidence-focused prompt, and a manual CLI. It is **not** wired into startup, Discord events, reaction shadow mode or Pinecone. There is no periodic scheduling or automatic checkpoint yet.

Choose a **small, settled, explicit UTC interval** in the dev guild, preferably containing a few actual conversations. Invoke from the dev pod with `DISCORD_SQLITE_PATH` and `OPENAI_API_KEY` already configured:

```bash
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- \\
  python -m discord_bot.storage.extraction_cli \\
  --guild-id "$DEV_GUILD_ID" \\
  --since 2026-11-08T12:00:00+00:00 \\
  --until 2026-11-08T13:00:00+00:00 \\
  --max-windows 5 --max-rows 1000
```

Replace the example dates with a window that actually has messages; the CLI does not discover a guild ID automatically. Avoid committing guild IDs to Git. **Running this command makes OpenAI API calls and stores proposed candidates locally**, but does not upsert Pinecone memories. It prints aggregate counts only; review the SQLite candidate table locally without pasting private message content into issues/logs. The input is capped at 40 messages per conversation window (1000 characters/message), five windows per invocation by default, and 1200 output tokens/model call. It rejects unsupported source/participant IDs and skips successfully completed unchanged batches. Changed source text reopens its batch. It does not yet resolve semantic duplicates or invalidate previously accepted Pinecone memories.

Validation: confirm migration 8, green unit tests, zero candidates is valid, failed calls remain retryable, and repeated invocation skips completed batches. Test with a copied representative archive if the dev guild has insufficient conversation history. The operator should assess candidate quality, source attribution, and token usage before authorizing autonomous writes. Do not run this against the production archive as an automatic task.

### Human evidence and memory feedback-loop decision (2026-11-09)

The first dev dry-run completed successfully (one window, one candidate, zero failures; 2,745 input and 288 output tokens), but proposed a real, previously stored Ireland-trip memory **only because the bot repeated it from Pinecone**. The event was true; the new Discord conversation was not new evidence. This is a memory-feedback-loop hazard, not proof of hallucination.

Decision: bot-authored recollections may be conversational context, never independent evidence for a new memory. Human corrections and newly stated facts are admissible; asking the bot what it remembers does not confirm its answer. For the next manual dry-run iteration, the operator CLI resolves the running bot's own user ID through Discord's authenticated `/users/@me` endpoint using its existing `DISCORD_TOKEN`. The extractor treats that author's messages as context only, and deterministically rejects candidates citing the bot as evidence. All other authors are provisionally eligible; windows consisting only of the bot's messages do not invoke the model. Future autonomous operation should persist Discord author/bot provenance during ingestion and backfill to exclude other bots and webhooks as well.

A proposed code PR adds exact normalized deduplication against existing SQLite extraction candidates. **It does not compare Pinecone memories or perform semantic deduplication**; both remain requirements before automatic acceptance. No production memory writes or scheduled extraction are authorized. The original dev candidate remains in SQLite for audit; do not interpret its existence as approval.


## Memory evaluation and lifecycle decision (2026-11-09)

**Approved scope:** remember both individual participants' interests, preferences, projects and meaningful history **and** collective server culture, including recurring jokes, shared references, traditions and experiences. Do not force a quota of cultural memories; absence of evidence is a valid result. The bot's own messages are context only, not independent evidence. The CLI resolves its own bot identity automatically; no human-ID allowlist or guild IDs in configuration or documentation.

### Observed production acceptance

- Production archive contained 1,483 messages at inspection. A bounded Nov 2 UTC sample produced two source-backed personal preferences; three additional historical slices produced six more candidates across four windows, with no reported extraction failures.
- Reviewed examples included entertainment preferences, AI-tool workflow, bot-development work, career perspectives, a game milestone and a recurring-comparison candidate. These demonstrate **individual-context extraction**, not yet reliable recognition of recurring collective lore.
- A dev regression previously re-extracted an old Pinecone recollection spoken by the bot; the human-evidence restriction yielded zero candidates when rerun. This verifies that case, not all possible provenance laundering.
- All eight inspected production proposals were high-confidence, but model confidence is not a publication decision. A transient milestone and an evolving project plan should not automatically receive the same lifetime as a durable preference.
- Production dry-runs write extraction ledgers/candidates/usage **only to SQLite**, not Pinecone or Discord. No automatic scheduler is active. Production reaction shadow posting remains disabled.

### Separate extraction, evaluation, consolidation and publication

1. **Extraction (implemented):** evidence-backed proposed candidates in SQLite; preserve exact message IDs and participants, guild, source hash and extractor version.
2. **Evaluation (next implementation):** independently decide whether each proposal is worth long-term retrieval. Classify scope as `individual` or `collective`, and durability as `durable`, `evolving`, or `transient`. Keep the original candidate immutable as evidence; store review decisions and reasons separately. Reject sensitive, weakly supported, misleading, or purely ephemeral claims. Favor concise attribution over overgeneralized personality labels. Human correction and explicit forget/invalidation take precedence over automated retention.
3. **Consolidation (subsequent implementation):** match against prior SQLite candidates **and existing Pinecone memories**, not just normalized text. Restrict matching to the same guild and appropriate participant(s); a shared interest between two people is not a duplicate. Distinguish `new`, `reinforce`, `update`, `supersede`, `conflict`, and `ignore`. Do not silently overwrite contradictory claims. A single newer statement may reflect a changed preference; preserve both provenance and effective dates. Never treat bot-recalled content as new corroboration.
4. **Publication (later, guarded):** publish accepted, consolidated memories to the existing Pinecone retrieval path with deterministic IDs and an SQLite publication ledger. Preserve source links, scope, timestamps and lifecycle status. Publish only after idempotency, reconciliation, deletion/correction handling and failure recovery are tested. Keep manual production promotion.

### Lifecycle semantics

- **Durable:** sustained preferences, personal background explicitly shared, well-supported group lore. Review when contradicted or source evidence changes; no arbitrary permanent-truth guarantee.
- **Evolving:** active projects, current tools, plans, changing opinions. Store an `observed_at` timestamp, permit updates/supersession and periodically re-evaluate relevance.
- **Transient:** temporary achievements, immediate plans and one-off trivia. Usually reject from long-term Pinecone publication while retaining the proposal/audit record in SQLite; exceptional shared milestones can qualify with explicit rationale.
- **Collective culture:** require explicit group-level evidence; an individual's one-off metaphor is not automatically a recurring server joke. Repeated independent human use across windows is stronger evidence. Attribution and source message IDs remain required.
- **Source edits/deletions:** invalidate dependent proposals/publications or queue re-evaluation before retrieval; do not silently preserve unsupported published facts. Explicit forget requests require a separate supported user-facing workflow before claiming completion.

### Implementation order and acceptance gates

1. **Evaluation PR:** schema and review layer for scope, durability, disposition and rationale, with deterministic rules and optional model-assisted review; bounded read-only preview/CLI of decisions. No Pinecone writes, scheduler or reaction changes. Include unit tests for transient milestones, evolving plans, durable preferences, individual-vs-collective attribution and unsafe/unsupported claims.
2. **Consolidation PR:** semantic candidate search and similarity evaluation, existing-Pinecone lookup, scoped identity matching, conflict/supersession ledger, and retry/idempotency tests. No automatic writes. Avoid relying on a cosine threshold alone for contradiction detection.
3. **Publication PR:** opt-in bounded manual publication first, deterministic upsert IDs, provenance metadata, partial-failure reconciliation, deletion/correction propagation and operational metrics. Then separately enable scheduled extraction and publication with rate/token caps and single-instance safeguards.
4. **Production acceptance:** sample varied conversations and review false positives; verify same claim paraphrased in different windows does not multiply, conflicting preferences are not silently merged, one-off game milestones are filtered, human-supported shared lore survives, and published memories are retrievable through the existing bot path. Preserve dev/prod isolation and existing reaction shadow behavior.

**Decision:** automated evaluation is intended to be autonomous after validation; no permanent per-memory human approval queue. The audit ledger exists for troubleshooting, corrections and rollback, not routine manual curation.


## Semantic consolidation preview (implementation in PR; not deployed until merged)

The operator-only `python -m discord_bot.storage.memory_consolidation_cli --limit 20` command re-evaluates candidate provenance and uses the existing embedding model to query the existing Pinecone index. It compares candidate summaries against bounded vector matches and same-scope candidates, then asks a separate model for a proposed `create`, `update`, `merge`, `discard`, or `review` operation and corrected standalone summary. The guild defaults to `REACTION_SHADOW_GUILD_ID`; `--guild-id` overrides it.

**Safety:** This is read-only with respect to SQLite and Pinecone; it does not accept candidates, publish memories, schedule jobs, or change Discord behavior. The Pinecone index currently contains legacy memories without guild/scope metadata. Such results are visible as context but cannot be selected as update/merge targets. Strong unscoped matches block automatic `create` proposals (falling back to `review`). A scoped target must match the candidate guild, scope, and exact participant set. Model-generated target IDs must be present in the scoped query results. Model proposals remain untrusted and require a later explicit publication design and operator validation.

The next implementation stage must handle split/compound memories, corrections, evidence invalidation and provenance-linked Pinecone writes. Existing unscoped records need a deliberate migration strategy before automated consolidation can safely modify them.


### Grounded consolidation preview (proposed, not deployed until merged)

The `memory_consolidation_cli` preview now supplies verified human source messages and a bounded set of adjacent human messages from the **same guild and channel** to consolidation. Adjacent context can clarify conversational references (e.g., the title of a show in a TV discussion), but the channel topic itself is not evidence of a specific title. Bot-authored, deleted and cross-channel messages are not accepted as evidence. The original candidate and Pinecone matches remain untrusted hints.

Consolidation may propose `split` with 2–3 standalone memories for compound candidates. Every proposed `create`, `update`, `merge` or `split` is passed to a separate model-based grounding check that examines the human messages. Failed grounding becomes `review`, not a publishable proposal. Canonical summaries containing Discord mention markup are rejected by this gate; participant IDs remain separate metadata. The preview still performs **no publication, candidate acceptance, or scheduler work**. Model verification is conservative but not a proof of truth; a future publication gate must revalidate sources and require explicit authorization.

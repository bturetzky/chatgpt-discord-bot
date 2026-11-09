# Server Awareness — design

**Status:** SQLite foundation deployed in dev; message ingestion is next.  
**Last reviewed:** 2026-11-08  
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

The shared database is infrastructure, **not** a single shared feature schema. Message text belongs in the archive/FTS5; reactions and their rate limits have separate tables and retention policies. The existing Discord recent-history path remains unchanged. This is an agreed priority order, not a claim of implementation.

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

Proposed tables:
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

- Schedule bounded analysis of newly indexed, coherent channel conversation windows (e.g. daily; split by idle gaps, participants, and maximum tokens). Do not run an LLM per message.
- Candidate categories: durable personal preferences explicitly stated, project/game plans and decisions, meaningful shared experiences, and recurring jokes clearly supported by context.
- Distinguish asserted fact, joke, quotation, speculation, disagreement and correction. Do not infer lasting relationships or personality traits from a single roast or ambiguous exchange.
- Each memory candidate should include concise text, type, explicit participant IDs, supporting source message IDs, source timestamps, and confidence/reason. Model confidence is a heuristic, not a guarantee of truth.
- Deduplicate against existing memories, and update/supersede contradicted facts rather than accumulating permanent conflicting claims. Preserve a correction/invalidation path and do not auto-resurrect invalidated memories.
- Persist accepted memories to existing Pinecone index with provenance metadata where feasible; keep full multi-source references in SQLite when metadata limits apply. Ensure deterministic IDs/idempotency across retries.
- Start with **dry-run** extraction into SQLite/logged aggregate metrics, with no Pinecone writes. Review sample candidates, false-positive rate and estimated cost, then enable autonomous writes with conservative thresholds. This is a rollout validation step, not ongoing manual approval.
- Process historic archives separately from new messages, with explicit bounded extraction ranges and budgets; backfill ingestion does not imply automatic mass memory generation.
- On retrieval, treat memory as potentially outdated and provide source links when relevant. If a source is deleted, edited materially, or becomes inaccessible, invalidate or withhold its dependent memory until revalidated.

### Cost, load and operations

- No LLM calls for routine ingestion or FTS queries; one scheduled extraction pass per day initially, only for changed/eligible conversation windows.
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

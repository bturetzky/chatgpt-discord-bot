# Architecture and current behavior

This document describes the implemented bot, not a proposed architecture. The [backlog](backlog.md) is the only source of unfinished features and pending operator acceptance. Kubernetes and Argo CD manifests live in [homelab-gitops](https://github.com/bturetzky/homelab-gitops).

## Request path and tools

```text
Discord mention / DM
  -> DiscordHandler (recent channel context, direct/replied images)
  -> VectorHandler + memory_selection (Pinecone retrieval)
  -> ChatGPTHandler (OpenAI Responses and tool loop)
  -> FunctionHandler (on-demand registered tools)
  -> Discord reply
```

Entry points are `run.py` and `discord_bot/app.py`. `discord_bot/handlers/` contains Discord, model, memory and image routing; `discord_bot/functions/` implements tools. Current tools include Brave search, public webpage/GitHub README reading, YouTube metadata/transcripts, weather, news, IGDB and Discord history search. URL/text from external sources is untrusted; readers use bounded network requests and must not pretend to have read inaccessible content.

`ImageContextBuilder` in `discord_bot/handlers/image_context.py` appends PNG/JPEG/WebP attachments and embed images present on a triggering message or its direct reply. The bot considers attachments with supported, missing, or generic MIME and uses HTTPS Discord CDN URLs, including Discord's media proxy. Pillow verifies and fully decodes only still PNG/JPEG/WebP files. The detected format supplies the model input MIME, even when the filename or headers disagree. The two sources share a cap of two selected images, 4 MiB each / 8 MiB total, and 20 megapixels each. Failed or unsupported images do not block the text response. Image bytes are not archived. YouTube support is transcript/metadata reading, not video-frame understanding.

## SQLite server archive

`discord_bot/storage/` provides one persistent SQLite database per environment, with WAL, busy timeout, foreign keys, ordered migrations, FTS5 search and integrity checks. It is a small embedded database, not an ORM or external service. The mounted directory must exist; avoid silently falling back to ephemeral storage. SQLite, WAL and SHM share the PVC. Dev and prod must never share a writable database. Use the SQLite backup API or a quiesced snapshot and test restores.

Live guild text ingestion records edits/deletes; recent Discord history remains the normal conversation context. Startup best-effort reconciliation reads up to 100 recent messages per accessible text channel. Explicit, bounded, resumable Discord history backfill uses per-channel cursors and idempotent message IDs; it does not cover DMs, threads, all historical deletions or an unbounded crawl. See [operations](operations.md).

Reaction observations, budgets and evaluations use separate SQLite tables, not FTS5. Historical archive messages are not replayed as reaction candidates.

## Autonomous server memory

The archive is the source of evidence. The opt-in worker (`discord_bot/storage/autonomous_memory.py`) periodically processes settled, bounded conversation windows, extracts evidence-linked candidates, evaluates grounding/durability and similarity, and publishes eligible **create** proposals to Pinecone. SQLite records extraction batches, candidates, evaluation fingerprints/decisions and accepted status. The manual historical **extraction** CLI operates on existing SQLite archive rows; it is distinct from Discord message import and can produce proposals subsequently published by the running worker.

The production worker and publication/retrieval have been operator-verified. The #96–97 idle/evaluation changes prevent repeated model requests for unchanged proposed evidence: persisted evaluation decisions and cycle checkpoints skip idle work; new evidence and publication errors remain eligible for processing. This is not a general billing ledger or a guarantee that no other bot activity calls OpenAI.

The existing Pinecone store remains the retrieval source, including legacy records. The #99 selection path uses a single query embedding from recent user turns, Pinecone ordering/similarity, a semantic pool plus participant-filtered relationship pool, caps and a rendered character budget. It avoids adding a second homegrown semantic classifier; an optional similarity floor can exclude low-score candidates. The operator verified this behavior in Discord. Attribution still depends on available record metadata; multi-person relationship/lore recall awaits separate acceptance.

**Important limitations:** The running worker does not implement autonomous memory corrections, merges, deletes or source-deletion invalidation. SQLite publication ledger/revision helpers and read-only Pinecone reconciliation exist, but are not a wired end-to-end transactional publication system. A Pinecone upsert and SQLite acceptance update are separate operations; a crash between them can leave ambiguous state. A previously observed verifier `not_found` discrepancy was investigated/verified by the operator; do not turn that old checkpoint into a pending incident, but preserve the broader crash/reconciliation limitation. Legacy Pinecone vectors may lack newer guild/scope metadata. Do not infer multi-tenant privacy isolation.

## Live emoji reactions

`discord_bot/handlers/reaction_shadow.py` evaluates recent eligible messages after a 60-second delay. It samples 1 in 12 independent messages and also considers pile-ons with at least two distinct observed human reactors. Both paths share a persisted rolling limit of 48 model evaluations in 24 hours and a queue of at most 16 delayed candidates. The dev test prefix can force independent sampling while leaving eligibility and limits in effect.

A positive model decision can post a standard emoji from the evaluator allowlist or an observed custom emoji usable in the configured guild. The bot fetches the current message before posting. Successful posts cool down the channel for five minutes and the author for 30 minutes. After 12 successes in a rolling 24 hours, roughly one in four otherwise eligible positive decisions can post. These limits apply at all hours.

SQLite reserves each message before evaluation and records the posting outcome separately from the model decision. An interrupted Discord request can leave an uncertain attempt. Previously evaluated messages are never retried, including after a restart.

## Proactive discovery shadow

The worker starts automatically when the gateway is ready and the SQLite archive is available. Each poll reads Discord's current cache of joined guilds and standard text channels where the bot can view the channel and read message history. The worker rotates in stable guild and channel ID order across eligible channels using the last persisted reservation as its cursor. One SQLite reservation gates the entire bot for six hours across all guilds, including after restart. Activity detected before reservation defers the channel without consuming the six-hour interval. If all available channels are active, the worker records a deferral. Activity detected after discovery work begins can consume the interval because the reservation is already persisted. The worker suppresses selection when that happens.

Topic selection samples up to 44 archived messages across four age bands covering the previous year, plus eight accepted SQLite memory summaries from the channel. It looks for a public topic supported by recurring discussion in the last 30 days or evidence of a durable shared interest in accepted memory. Channel names and topics are weak hints. The topic request instructs the model to omit private details, and the worker validates the query format before sending it to Brave. Search queries and private context are not persisted in discovery rows.

Each reserved six-hour window permits one Brave search, two page reads, four tool-free model calls including topic selection, and one embedding batch. The worker can fully review one candidate per window, with a second result available if the first fails an early gate. SDK retries are disabled. Drafting receives only the fetched public source. A separate reviewer compares the draft with source evidence, FTS results, up to eight semantically ranked archive excerpts, and up to 60 prior suggestions. Phase 1 semantic novelty detection embeds a bounded sample of eligible channels' archived messages in the selected guild per review. This accepted Phase 1 limit can miss paraphrases outside the sample. Comprehensive historical vector search is outside Phase 1 scope. Similarity shortlists evidence for review and cannot reject a candidate on its own.

Archive and memory context, prior suggestions and deduplication are scoped to the selected guild. SQLite stores canonical URL and exact selected story identities, categorical decisions, selected public evidence, drafts and attempted provider usage. The worker sends nothing to Discord and writes no memories. Interrupted attempts consume their reservation, and previously attempted canonical URLs are skipped across restarts. See [operations](operations.md#discovery-shadow-dev-acceptance).

## Operational boundaries

This is one small trusted production guild and a separate dev environment. No new service, database cluster or generalized tenant authorization is planned without a demonstrated need. External content and Discord messages are untrusted model input. Logs and documentation must not contain raw private memories, message bodies, tokens or real guild IDs. Use [operations](operations.md) for safe diagnostics and [deployment](deployment.md) for release gates.

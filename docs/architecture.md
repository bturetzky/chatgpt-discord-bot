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

`ImageContextBuilder` in `discord_bot/handlers/image_context.py` appends PNG/JPEG/WebP attachments and embed images present on a triggering message or its direct reply. When attachment MIME is missing or generic, a supported filename extension supplies the expected format and Pillow must verify the bytes match. If Discord declares a different supported MIME than the CDN serves, the filename extension must agree with the CDN MIME and Pillow must verify the bytes. A missing or generic CDN header uses the expected attachment format and still requires matching bytes. Embeds use HTTPS Discord CDN URLs, including Discord's media proxy, and require a supported response MIME that matches the decoded image. The two sources share a cap of two selected images, 4 MiB each / 8 MiB total, and 20 megapixels each. Failed or unsupported images do not block the text response. Image bytes are not archived. YouTube support is transcript/metadata reading, not video-frame understanding.

## SQLite server archive

`discord_bot/storage/` provides one persistent SQLite database per environment, with WAL, busy timeout, foreign keys, ordered migrations, FTS5 search and integrity checks. It is a small embedded database, not an ORM or external service. The mounted directory must exist; avoid silently falling back to ephemeral storage. SQLite, WAL and SHM share the PVC. Dev and prod must never share a writable database. Use the SQLite backup API or a quiesced snapshot and test restores.

Live guild text ingestion records edits/deletes; recent Discord history remains the normal conversation context. Startup best-effort reconciliation reads up to 100 recent messages per accessible text channel. Explicit, bounded, resumable Discord history backfill uses per-channel cursors and idempotent message IDs; it does not cover DMs, threads, all historical deletions or an unbounded crawl. See [operations](operations.md).

Reaction observations, budgets and evaluations use separate SQLite tables, not FTS5. Historical archive messages are not replayed as reaction candidates.

## Autonomous server memory

The archive is the source of evidence. The opt-in worker (`discord_bot/storage/autonomous_memory.py`) periodically processes settled, bounded conversation windows, extracts evidence-linked candidates, evaluates grounding/durability and similarity, and publishes eligible **create** proposals to Pinecone. SQLite records extraction batches, candidates, evaluation fingerprints/decisions and accepted status. The manual historical **extraction** CLI operates on existing SQLite archive rows; it is distinct from Discord message import and can produce proposals subsequently published by the running worker.

The production worker and publication/retrieval have been operator-verified. The #96–97 idle/evaluation changes prevent repeated model requests for unchanged proposed evidence: persisted evaluation decisions and cycle checkpoints skip idle work; new evidence and publication errors remain eligible for processing. This is not a general billing ledger or a guarantee that no other bot activity calls OpenAI.

The existing Pinecone store remains the retrieval source, including legacy records. The #99 selection path uses a single query embedding from recent user turns, Pinecone ordering/similarity, a semantic pool plus participant-filtered relationship pool, caps and a rendered character budget. It avoids adding a second homegrown semantic classifier; an optional similarity floor can exclude low-score candidates. The operator verified this behavior in Discord. Attribution still depends on available record metadata; multi-person relationship/lore recall awaits separate acceptance.

**Important limitations:** The running worker does not implement autonomous memory corrections, merges, deletes or source-deletion invalidation. SQLite publication ledger/revision helpers and read-only Pinecone reconciliation exist, but are not a wired end-to-end transactional publication system. A Pinecone upsert and SQLite acceptance update are separate operations; a crash between them can leave ambiguous state. A previously observed verifier `not_found` discrepancy was investigated/verified by the operator; do not turn that old checkpoint into a pending incident, but preserve the broader crash/reconciliation limitation. Legacy Pinecone vectors may lack newer guild/scope metadata. Do not infer multi-tenant privacy isolation.

## Reaction shadow and future personality

`discord_bot/handlers/reaction_shadow.py` observes human reactions and independently sampled messages, delays evaluation and asks a tool-free model whether an emoji would be appropriate. **Shadow mode never calls Discord to add an emoji.** Candidate gates include a recent eligible text message, 1-in-12 independent sampling, two distinct observed human reactors for pile-ons, 60-second debounce, at most 16 delayed candidates and a persisted cap of 8 model evaluations in a rolling 24 hours. These are evaluation limits, **not** a future posting budget. The dev-only prefix can force eligible sampling but cannot bypass other gates or the budget.

Production shadow startup has been observed; longer-term decision quality and distinct-human pile-on acceptance remain pending. Live posting requires a separate implementation with durable posting budget, dedupe, cooldown, kill switch, permission/rate-limit handling and standard/custom emoji allowlisting. Do not equate shadow model output with a posted reaction.

## Operational boundaries

This is one small trusted production guild and a separate dev environment. No new service, database cluster or generalized tenant authorization is planned without a demonstrated need. External content and Discord messages are untrusted model input. Logs and documentation must not contain raw private memories, message bodies, tokens or real guild IDs. Use [operations](operations.md) for safe diagnostics and [deployment](deployment.md) for release gates.

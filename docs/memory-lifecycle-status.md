# Autonomous memory idle-cycle API leak fix — 2026-11-10

**Proposed, not yet deployed or operator-verified.** Overnight logs repeatedly showed roughly 13 Responses calls and 5 embeddings calls per 30-minute cycle even when extraction reported zero new work. The scheduler was invoking read-only evidence evaluation, consolidation and grounding for the same proposed candidates on every cycle.

The worker now persists a per-guild SQLite checkpoint fingerprint after a successful cycle. It covers proposed candidate data, source message contents/edit/delete state, configured model and extraction/evaluation/consolidation versions. With no new extraction and an unchanged fingerprint, the next scheduled cycle skips evaluation, consolidation, grounding and similarity embeddings. Publication failures do not advance the checkpoint, preserving retries. No feature flags or scheduling interval are changed.

**Instrumentation:** Cycle logs expose `idle_checkpoint_hit` and `evaluation_usage` with successful Responses/embeddings request counts, Responses input/output tokens and embedding tokens. Extraction's existing `input_tokens` and `output_tokens` remain separate. These metrics exclude failed API requests, and are not an account-wide billing ledger.

**Known limitation:** This is a cycle-level idle checkpoint, not per-candidate persisted evaluations. Any new pending candidate or changed source invalidates the checkpoint and may cause other pending candidates to be reconsidered. External Pinecone changes alone do not invalidate it; operators can clear the checkpoint row when intentional re-evaluation is required. A later per-candidate state machine can improve this without changing the publication policy.

**Dev acceptance:** Run the unit suite, deploy to dev, wait for one complete cycle, then verify subsequent idle cycles report `idle_checkpoint_hit=True`, zero `evaluation_usage`, and no associated OpenAI requests. Edit a source or allow a new settled human conversation to enter extraction and confirm work resumes. Verify publication errors remain retryable. Promote to production only after observing these conditions.

---

# Operational checkpoint — 2026-11-09

**Dev operator-verified:** The autonomous memory worker is enabled in dev (`AUTONOMOUS_MEMORY_ENABLED=true`) and published two memories successfully (zero failures reported). After the dependency compatibility fix, dev logs showed `Retrieved memory:` summaries, confirming that OpenAI embedding-based lookup and Pinecone retrieval are functioning and summaries reach the model-context insertion path. A response that relies solely on a newly published memory, without Discord history search, has not been independently established.

**Production:** Promotion is planned by the operator, not yet confirmed. Do not describe the worker as verified in production.

**Dependency incident:** Dev OpenAI embeddings and Responses calls previously failed during SDK/Pydantic serialization (`by_alias=None`). The project now declares a compatible Pydantic dependency and targets Python 3.12; operator observed retrieval working after deploying the fix. Keep the SDK serialization regression test. The earlier Dockerfile override PR #91 was closed without merge.

**Follow-up, not release blockers:** Retrieved memories include semantically duplicated preferences and low-value historical observations. Improve deduplication and durability filtering later. Temporary DEBUG logging exposes full memory summaries and Discord identifiers; restore INFO logging after troubleshooting, especially before production promotion. Existing limitations around updates, deletes, cross-system atomicity and legacy records still apply.

---

## Autonomous memory worker (implemented; opt-in feature flag, disabled by default)

The bot now has an opt-in periodic worker (`AUTONOMOUS_MEMORY_ENABLED=true`) for the configured server (`AUTONOMOUS_MEMORY_GUILD_ID`, falling back to `REACTION_SHADOW_GUILD_ID`). Every 30 minutes it examines settled archived conversations (30-minute settling delay, bounded 24-hour lookback), extracts candidates, runs evidence evaluation and consolidation, and publishes **only unblocked, independently grounded create proposals** to Pinecone. SQLite records extraction progress and marks successfully published candidates accepted; Pinecone remains the retrieval store. Deterministic IDs include guild, scope and participant attribution. High-similarity existing vectors are not overwritten. The bot's `store_memory` tool remains available for explicit requests only; proactive tool-use instructions were removed.

**Operational limits:** No autonomous updates, merges, splits, forget/delete workflow, or full semantic dedup guarantee yet. Blocked candidates remain proposed and may be reconsidered in later cycles, which can incur model costs. Publication is not transactionally atomic across SQLite and Pinecone; a crash after Pinecone upsert may require manual cleanup. Legacy Pinecone vectors remain visible to existing retrieval. The worker has been deployed and exercised against a real Pinecone index in dev; production behavior has not been confirmed.

Dev verification after deployment: enable the flag in dev configuration, restart, converse in a test channel, wait at least 30 minutes for the window to settle and up to 30 minutes for the next worker cycle, then ask the bot a question requiring that memory. Inspect logs for `Autonomous memory cycle` and ensure no cross-person memory attribution.

## Pinecone read-only reconciliation (PR #87, proposed)

`memory_pinecone_reconciliation.py` constructs expected revision metadata directly from the SQLite ledger and fetches **one explicit vector ID** from a caller-supplied Pinecone index and namespace. It requires exact matching `publication_schema`, logical memory ID, revision, guild, scope, participant list, summary, SHA-256 summary hash, source hash, durability and proposal ID. Legacy Pinecone vectors lacking these fields are **mismatched**, never confirmed. A missing vector is `missing`; fetch exceptions or unrecognized responses are `unknown` (never silently `missing`). No secrets, vector values, or summaries are logged.

The expected metadata format is a **contract for a future writer**, not a claim that any current vector contains it. This module does not write vectors, modify SQLite, reconcile an attempt automatically, authenticate observations, or run in the bot's runtime. The existing `reconcile_recorded_attempt` API still trusts caller-supplied flags; production callers must use a future tightly coupled, verified adapter before applying `matching_vector=True`. Namespace and index configuration must be aligned with the future writer; do not infer a namespace from an ID.

## Transactional ledger operations (PR #86, deployed in dev)

`memory_publication_ledger.py` adds **operator-invoked SQLite-only functions**, not a scheduled pipeline: `stage_create` checks current archived human evidence inside `BEGIN IMMEDIATE`, snapshots source hashes and attribution, and stages revision 1 against a caller-supplied logical memory ID. Repeated identical proposal staging is idempotent; changed sources and conflicting IDs fail closed. `validate_sources` compares archived content, timestamps, author and channel to snapshots; `invalidate_changed_sources` can invalidate staged or failed revisions, but deliberately refuses to silently invalidate pending/published remote vectors. `record_attempt` records intent only, while `reconcile_recorded_attempt` records an externally supplied observation.

**Important limits:** These APIs are not connected to the planner or bot runtime; the caller must independently verify the plan, choose a semantically deduplicated logical ID, and supply trustworthy remote observations. The APIs do not contact Pinecone, validate a remote response themselves, implement updates/merges/splits, or safely retire an already published vector. Do not treat a caller-supplied `matching_vector=True` as independently verified without a future trusted reconciliation adapter. No automatic writes are enabled.

# Server Awareness memory: implementation checkpoint

**Updated:** 2026-11-09. This is the current status; older implementation-order sections in [the design](server-awareness-design.md) are retained as historical decisions, not a current task list.

## Implemented and operator-observed

- SQLite message archive, search and bounded historical backfill; deterministic conversation-window segmentation and extraction batches.
- Operator-invoked LLM extraction into SQLite candidates with source-message attribution, human-only evidence, bot-identity discovery and candidate/usage ledger. Extraction **does not publish** to Pinecone.
- Evidence evaluation: source validation, scope and durability classification, and explicit exclusion of bot-authored recollections and low-value transient milestones.
- Semantic consolidation preview (v2): bounded Pinecone similarity lookup, same-participant candidate comparisons, human source and adjacent same-channel conversation context, optional split proposals, and an independent model grounding check.
- Dev preview correctly discarded the bot-authored Ireland recollection; production preview processed eight candidates with **four create, three review, one discard** and no publication. The Witcher conversation demonstrated that human adjacent context can clarify a title; channel name alone cannot prove it. The Mario Odyssey compound preference was still proposed as a single create, despite optional splitting.
- **Read-only publication planner:** deterministic proposal IDs, explicit provenance and scope, lifecycle classification, fail-closed blockers and review-required output. It makes no Pinecone upserts, candidate acceptance decisions, or publication ledger writes. This is a plan preview, not a working publication pipeline.

## Operator commands and boundaries

Run after deployment, starting in dev:

```bash
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.storage.memory_publication_plan_cli --limit 20
```

The planner re-runs the evidence and consolidation models, so results can vary between runs and incur API costs; **proposal IDs and deterministic eligibility rules** do not vary for the same candidate identity. The output has `recorded: false` and `publishable: false` even when an entry is `review_required`. `review_required` is not authorization to publish. The CLI opens the existing SQLite database using the application's normal connection lifecycle, but does not add planner records or publish memories. Production promotion remains manual.

## Publication ledger foundation (migration 10; deployed in dev)

A new ordered SQLite migration defines `memory_records` (logical identity, guild, scope, participant set, lifecycle and current revision), `memory_revisions` (immutable numbered revisions, proposal link, source hash and supersession pointer), `memory_revision_sources` (source IDs, authors, channels, timestamps and content hashes), and `memory_publication_attempts` (upsert/delete attempt state, vector ID and reconciliation status). The migration creates empty tables; it does **not** backfill, approve, publish or change existing Pinecone retrieval.

Pure state-transition helpers reject publication without independent remote confirmation, prohibit unconfirmed supersession and preserve uncertain remote outcomes as uncertain. They do **not** implement a writer or automatically mutate these tables. The planner still reports `publishable: false`; no new CLI, scheduler or automated writes are introduced.

Before connecting a writer, implement transactional persistence APIs with source validation, stable logical identity and semantic deduplication; vector-operation idempotency and reconciliation; and an explicit invalidation/retrieval policy. A schema is not a functioning publication lifecycle.

## Explicitly deferred / to revisit

1. **Publication ledger operations and revisions:** The schema and pure state rules are proposed in this PR; transactional persistence, source snapshot validation, actual revision updates, rollback, and partial-failure reconciliation are not implemented. Proposal IDs are *not* semantic deduplication keys or Pinecone vector IDs.
2. **Legacy Pinecone migration:** older records lack guild/scope provenance. Never silently adopt or overwrite them; establish attribution, migration or quarantine rules and duplicate detection before enabling writes.
3. **Atomic memory splitting:** consolidation can propose `split`, but it is not consistently chosen (Mario Odyssey). Require per-atom evidence and duplicate checks before split publication; avoid automatic creation of compound preferences.
4. **Source invalidation:** edits, deletes, explicit corrections/forget requests and stale evolving projects must invalidate or supersede retrieval entries. The planner conservatively blocks edited sources rather than attempting automatic repair.
5. **Scope/identity and safety:** prevent cross-guild, cross-person and bot-feedback contamination, including other bots/webhooks; validate collective lore with repeated independent human evidence. Sensitive/private inference and model agreement still require stronger policy gates.
6. **Idempotent publishing and retrieval:** deterministic semantic identity, source-linked metadata, scoped retrieval, controlled Pinecone writes, retries and reconciliation, then tests that the live bot retrieves correct memories without duplicates.
7. **Automation:** bounded scheduled extraction/evaluation/publication with cost/rate limits, concurrency control, telemetry and alerts. No automatic scheduler or autonomous memory publication is enabled.

**Decision:** The eventual design is autonomous after validation, not a permanent human approval queue. Until the write path and safety gates are implemented and tested, no candidate is eligible for automatic publication.

See [engineering roadmap](engineering-roadmap.md) and [server-awareness design](server-awareness-design.md) for wider context.

## Transactional ledger operations (PR #86, proposed)

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
- **Read-only publication planner (this PR, pending merge/deployment):** deterministic proposal IDs, explicit provenance and scope, lifecycle classification, fail-closed blockers and review-required output. It makes no Pinecone upserts, candidate acceptance decisions, or publication ledger writes. This is a plan preview, not a working publication pipeline.

## Operator commands and boundaries

Run after deployment, starting in dev:

```bash
kubectl -n discord-dev exec deploy/chatgpt-discord-bot -- \
  python -m discord_bot.storage.memory_publication_plan_cli --limit 20
```

The planner re-runs the evidence and consolidation models, so results can vary between runs and incur API costs; **proposal IDs and deterministic eligibility rules** do not vary for the same candidate identity. The output has `recorded: false` and `publishable: false` even when an entry is `review_required`. `review_required` is not authorization to publish. The CLI opens the existing SQLite database using the application's normal connection lifecycle, but does not add planner records or publish memories. Production promotion remains manual.

## Publication ledger foundation (this PR; not deployed until merged)

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

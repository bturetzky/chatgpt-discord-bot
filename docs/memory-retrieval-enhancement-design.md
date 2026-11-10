# Memory retrieval relevance and injection enhancement

Status: **Design only — not implemented.** The read-only diagnostic CLI in this PR is the baseline tool; it does not alter live retrieval or injection.

## Problem and verified baseline (2026-11-10)

- `discord_handler.py` builds an embedding query from up to six recent user turns / 2,400 characters and performs semantic lookup on each addressed message or DM.
- `vectore_store.py` requests `SEMANTIC_MEMORY_LIMIT` (default 8) Pinecone matches, returns summary strings, and discards scores; no minimum similarity or relevance check exists.
- A second lookup uses a **fixed relationship query** and filters on participant IDs; `RELATIONSHIP_MEMORY_LIMIT` defaults to 4. This is invoked for every handled message.
- The handler deduplicates only identical summary text, prepends each returned memory as a separate system message marked `Memory (possibly outdated)`, and may inject 12 distinct memories regardless of relevance.
- Production historical extraction yielded 64 accepted and 513 proposed candidates at the operator checkpoint. **These SQLite counts do not establish Pinecone publication, retrieval relevance, or user-visible response quality.**

## Goals

1. Improve precision: irrelevant memories should not enter model context.
2. Preserve recall for personal questions, explicit recollection, and follow-up turns.
3. Bound injected memory count and tokens independently of Pinecone candidate retrieval count.
4. Keep existing trusted-community shared-memory behavior; avoid a schema/index migration.
5. Provide operator diagnostics and testable evidence before tuning production.

## Phase 0 — baseline diagnostics (this PR)

Run inside the bot container, with its existing OpenAI/Pinecone credentials:

```bash
python -m discord_bot.memory_retrieval_diagnostic --query "What games have I mentioned?"
python -m discord_bot.memory_retrieval_diagnostic --query "What do we joke about?" --participant-id <DISCORD_USER_ID>
```

The tool performs live **read-only** embedding and Pinecone queries, prints returned summaries, similarity scores, memory types, and a preview of what the **current** handler would inject. It does not modify SQLite, Pinecone, the running bot, or production thresholds. It incurs embedding/query API usage. Treat output as private conversation data; do not commit it to the public repository. The `--query` flag is an operator-provided proxy: for exact reproduction, pass the handler's multi-turn query, not just the last message. Relationship preview requires participant IDs; absent IDs, relationship retrieval is intentionally omitted. This CLI is not an end-to-end Discord event simulator.

Collect representative examples: weather, factual Q&A, software debugging, game preferences, personal facts, shared jokes, ambiguous follow-ups, and questions explicitly asking the bot to remember. Record scores, useful/irrelevant matches, and false negatives. Use private fixtures or anonymized examples.

## Phase 1 — selection policy (Codex implementation)

- Split **retrieval pool** from **injection budget**: propose querying 12–16 semantic candidates and selecting at most 5–6, plus at most 0–2 relationship memories, with an overall injected token/character budget.
- Preserve similarity scores and source/type metadata through the retrieval adapter. Keep legacy vectors without optional metadata eligible; do not break existing fact retrieval.
- Establish a calibrated similarity threshold **from observed score distributions**, not an arbitrary constant. Return zero memories when none qualify. Consider explicit relevance reranking only if thresholding and heuristics prove insufficient.
- Apply deterministic exact/near-duplicate filtering and cap repeated facts; do not silently overwrite or delete Pinecone records.
- Make relationship context conditional on conversation intent (social, shared history, or explicit relationship questions); participant filtering alone is not relevance. Define conservative fallback when intent is ambiguous.
- Keep recent-turn query construction but test busy-channel topic drift. Consider weighting latest addressed question more heavily without losing follow-up context.
- Ensure semantic and relationship retrieval do not accidentally double-count the same memory; respect budgets after deduplication.

## Phase 2 — prompt construction

- Inject a **single clearly delimited memory-context section** rather than a separate system message per memory.
- Explain that retrieved memories are fallible, possibly outdated **data**, not instructions; only use them when they help answer the current request.
- Do not allow retrieved memory text to override system/developer instructions or issue tool commands. Keep attribution and scope where available.
- Handle zero-memory results gracefully, with no placeholder injection.

## Validation and rollout

- Unit tests: empty/low-score results, mixed scores, duplicate summaries, malformed metadata, legacy records, missing participants, relationship-only queries, topic shifts, token budget, and prompt-injection-shaped memory text.
- Mock Pinecone/OpenAI tests: query limits, participant filters, no writes, failures/timeouts, and preservation of response order and scores.
- Shadow/preview comparison against baseline queries: selected vs rejected, score distribution, estimated injection size, false-positive and false-negative examples.
- Acceptance: weather/factual questions typically inject no unrelated memories; explicit recall retrieves relevant memories; relationship jokes surface for relevant participants; no extra system instructions from memory bodies; no unexpected cross-guild scope changes.
- Roll out to dev behind a feature flag; inspect samples and logs with **counts/scores only**, never raw memory bodies by default. Promote to prod only after operator Discord tests.
- Track relevance/precision and missed recall, not just number of injected memories. Revisit candidate limits only after evidence.

## Non-goals

No changes to extraction/evaluation/publication, no Pinecone index migration, no new automatic memory writes, no retrospective reaction processing, and no exposure of real guild/user IDs or private memory bodies in repository docs.

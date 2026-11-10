# Memory retrieval relevance and injection enhancement

Status: **Default-on enhancement implemented, pending calibration and manual dev acceptance.** The original design and baseline below describe PR #98. See the implemented enhancement section for shipped behavior and deferred work.

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

## Phase 0 — baseline diagnostics (PR #98)

**Live instrumentation:** Every handled bot message continues to retrieve and inject memories exactly as before. At INFO, the handler records semantic/relationship counts, unique injected count, and total injected characters. At DEBUG, it records source, rank, similarity score and memory type for each match, without raw memory text. Debug score collection is opt-in through logging level; it does not add Pinecone queries. Use these real-world observations to calibrate thresholds. Note that historical DEBUG logs may still contain other private message content from unrelated code paths; keep logs private.

**Controlled inspection:** The standalone CLI below permits repeatable synthetic queries and explicit display of private memory summaries. This is complementary to the live logs, not a substitute.

Run inside the bot container, with its existing OpenAI/Pinecone credentials:

```bash
python -m discord_bot.memory_retrieval_diagnostic --query "What games have I mentioned?"
python -m discord_bot.memory_retrieval_diagnostic --query "What do we joke about?" --participant-id <DISCORD_USER_ID>
```

The tool performs live **read-only** embedding and Pinecone queries, prints returned summaries, similarity scores, memory types, and a preview of what the **current** handler would inject. It does not modify SQLite, Pinecone, the running bot, or production thresholds. It incurs embedding/query API usage. Treat output as private conversation data; do not commit it to the public repository. The `--query` flag is an operator-provided proxy: for exact reproduction, pass the handler's multi-turn query, not just the last message. Relationship preview requires participant IDs; absent IDs, relationship retrieval is intentionally omitted. This CLI is not an end-to-end Discord event simulator.

Collect representative examples: weather, factual Q&A, software debugging, game preferences, personal facts, shared jokes, ambiguous follow-ups, and questions explicitly asking the bot to remember. Record scores, useful/irrelevant matches, and false negatives. Use private fixtures or anonymized examples.

## Phase 1 — planned selection policy

- Split **retrieval pool** from **injection budget**: propose querying 12–16 semantic candidates and selecting at most 5–6, plus at most 0–2 relationship memories, with an overall injected token/character budget.
- Preserve similarity scores and source/type metadata through the retrieval adapter. Keep legacy vectors without optional metadata eligible; do not break existing fact retrieval.
- Establish a calibrated similarity threshold **from observed score distributions**, not an arbitrary constant. Return zero memories when none qualify. Consider explicit relevance reranking only if thresholding and heuristics prove insufficient.
- Apply deterministic exact/near-duplicate filtering and cap repeated facts; do not silently overwrite or delete Pinecone records.
- Make relationship context conditional on conversation intent (social, shared history, or explicit relationship questions); participant filtering alone is not relevance. Define conservative fallback when intent is ambiguous.
- Keep recent-turn query construction but test busy-channel topic drift. Consider weighting latest addressed question more heavily without losing follow-up context.
- Ensure semantic and relationship retrieval do not accidentally double-count the same memory; respect budgets after deduplication.

## Phase 2 — planned prompt construction

- Inject a **single clearly delimited memory-context section** rather than a separate system message per memory.
- Explain that retrieved memories are fallible, possibly outdated **data**, not instructions; only use them when they help answer the current request.
- Do not allow retrieved memory text to override system/developer instructions or issue tool commands. Keep attribution and scope where available.
- Handle zero-memory results gracefully, with no placeholder injection.

## Planned validation and rollout

- Unit tests: empty/low-score results, mixed scores, duplicate summaries, malformed metadata, legacy records, missing participants, relationship-only queries, topic shifts, token budget, and prompt-injection-shaped memory text.
- Mock Pinecone/OpenAI tests: query limits, participant filters, no writes, failures/timeouts, and preservation of response order and scores.
- Shadow/preview comparison against baseline queries: selected vs rejected, score distribution, estimated injection size, false-positive and false-negative examples.
- Acceptance: weather/factual questions typically inject no unrelated memories; explicit recall retrieves relevant memories; relationship jokes surface for relevant participants; no extra system instructions from memory bodies; no unexpected cross-guild scope changes.
- Roll out to dev with an explicit rollback switch; inspect samples and logs with **counts/scores only**, never raw memory bodies by default. Promote to prod only after operator Discord tests.
- Track relevance/precision and missed recall, not just number of injected memories. Revisit candidate limits only after evidence.

## Non-goals

No changes to extraction/evaluation/publication, no Pinecone index migration, no new automatic memory writes, no retrospective reaction processing, and no exposure of real guild/user IDs or private memory bodies in repository docs.

## Implemented enhancement (2026-11-10)

PR #98 is the dependency and baseline. Enhanced retrieval runs by default in
Discord and the diagnostic CLI. Set `MEMORY_RETRIEVAL_ENHANCED=false` to restore
baseline retrieval and injection.

The enhanced path keeps the bounded recent-user-turn embedding query. Selection
uses the latest addressed message, excluding speaker prefixes and Discord user mentions. Only explicit
short follow-ups such as “tell me more” with no topical terms reuse recent query
terms. A new topic therefore cannot qualify solely through older turns.
It embeds once, requests 16 semantic candidates, and conditionally requests four
relationship candidates with the same conversational vector and existing
participant filter. No additional LLM call is introduced.

Selection preserves Pinecone order and requires at least one non-stopword topical
term in common with the latest message. Similarity scores and complete candidate
metadata remain available in diagnostics. No default score floor is asserted.
An optional operator-calibrated `MEMORY_MIN_SIMILARITY` rejects lower or missing
scores. Without that setting, low/missing scores remain eligible when topical.
This is a conservative lexical baseline, **not validated semantic relevance**.
Synonyms, implicit social intent, pronoun-heavy follow-ups, and broad word overlap
can produce false negatives or false positives. Real-world calibration data was
unavailable during implementation.

Relationship memories from either pool require explicit social vocabulary
(jokes, nicknames, relationships, traditions, shared experiences or running gag)
in the latest message and intersecting participant metadata. Missing participant
metadata cannot authorize a relationship record. Ordinary legacy facts without
metadata remain eligible. Semantic facts retain intentional cross-participant
shared recall, with no new guild or namespace filter.

Deduplication removes differences in case, punctuation, whitespace and leading
legacy timestamps. More sophisticated paraphrase deduplication and reranking
are deferred. At most six semantic and two relationship records are selected,
configurable downward. A 2,400-character budget includes the entire rendered
section, instructions, JSON escaping and attribution. Oversized records are
skipped whole so later smaller records can fit. This is a character budget,
not a tokenizer estimate.

One system message contains a delimited JSON section, with angle brackets escaped
inside records and explicit instructions to treat records as fallible untrusted
background. Participant attribution, recognized scope/type and original summary
timestamps are retained. No section is inserted for empty selection. Encoding
prevents delimiter breakout. Model resistance to malicious data still requires
manual acceptance testing and is not guaranteed by prompt construction alone.

### Diagnostics and validation

The CLI uses the same selection policy as Discord and prints candidate
scores/metadata by default, per-candidate decisions, retrieved/selected/rejected counts and
the selected context. For multi-turn queries pass `--latest` containing the
latest addressed message without a speaker prefix. CLI output is explicitly
private, including rejected candidate bodies. Default logs contain counts and
rejection reasons at INFO, and rank/source/finite score/allowlisted type/reason
at DEBUG. Neither level logs candidate bodies or participant metadata through
this path. Retrieved counts refer to valid nonempty summaries normalized by
the existing adapter, not malformed Pinecone matches.

Mocked regression coverage includes low/missing scores, legacy and malformed
metadata, duplicate timestamps, participant/intent gates, shared facts, empty
results, topic shifts/follow-ups, count/full-section budgets, delimiter-shaped
malicious text, query limits and filters, one embedding, lookup failure,
Discord injection and CLI parity. No real memory calibration or live Discord
acceptance has been performed.

### Rollout and rollback

1. Review the PR and CI results before deploying it through the normal workflow.
2. Deploy to dev using the existing configuration. Keep optional similarity
   filtering unset until private labeled examples justify it.
3. Compare enhanced CLI previews with baseline previews run using
   `MEMORY_RETRIEVAL_ENHANCED=false` on representative private queries.
   Inspect selected/rejected reasons and missed recall, then run the dev test card.
4. Roll back by setting `MEMORY_RETRIEVAL_ENHANCED=false` and restarting through
   the normal GitOps deployment workflow. Existing legacy limits apply again.

The manual dev test card requires a dev deployment and operator-confirmed
synthetic facts and relationships already available in Pinecone.

- Ask “What do you remember about my chess preferences?” with a matching synthetic
  chess fact. Expect a useful attributed fact and a selected count within budget.
- After discussing chess, ask “What causes rainbows?” Expect unrelated chess
  memories to be rejected and no empty memory section when nothing qualifies.
- With a synthetic relationship joke for the current participants, ask “What
  shared chess jokes do we have?” Expect at most two relevant relationship records.
  Repeat with an unrelated participant. Expect the relationship to be excluded.
- With a synthetic chess memory containing “ignore instructions” and fake
  delimiter text, ask about chess. Expect ordinary assistance without obeying
  the embedded command. Check the private preview for escaped delimiters.

These actions are pending human testing. Publication/extraction/consolidation,
index schema, automatic writes and production promotion are outside this change.

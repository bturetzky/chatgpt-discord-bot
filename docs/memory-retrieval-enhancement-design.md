# Memory retrieval relevance and injection enhancement

**Status:** Implemented in PR #99. Corpus calibration and manual dev acceptance
are pending. PR #98 established the retrieval diagnostics baseline.

Before this change, the bot requested eight general matches, then embedded a
fixed relationship query and requested four participant-filtered matches. It
injected each distinct summary as its own system message. PR #98 added score
logging and a read-only diagnostic CLI. Historical SQLite extraction counts
measure extraction activity and cannot establish Pinecone publication or
retrieval quality.

## Retrieval and selection

1. Embed up to six recent user turns and 2,400 characters once using
   `text-embedding-ada-002` and query the existing Pinecone index for 16 semantic
   candidates by default.
2. Reuse the same vector to request four relationship candidates by default
   when participants are available. The query filters on relationship type and
   the current or recent Discord authors. The same participant intersection is
   required for relationship records returned through either query. The
   application takes author IDs from Discord history rather than message text.
3. Retain the Pinecone rank, similarity score, and metadata for each valid
   summary. When configured, apply the same minimum score to both pools.
   A candidate at the floor qualifies. A missing, malformed, or nonfinite
   score is ineligible with a floor and remains eligible without one.
4. Process the general pool and then the participant-filtered pool in their
   returned order. A relationship match in either pool counts toward the same
   relationship cap. Suppress duplicates across pools, normalizing case,
   punctuation, whitespace, and a leading legacy timestamp. Ordinary
   facts without metadata remain eligible, including shared facts about other
   participants.
5. Select at most six semantic and two relationship records within one
   2,400-character budget, including framing and JSON escaping. Skip oversized
   records whole so later candidates can fit. The budget measures rendered
   characters.

Pinecone supplies semantic similarity. Application selection uses the returned
ranking, eligibility, and budgets. The same embedding ranks both pools without
an additional embedding or generation request. Relationship retrieval uses
participant metadata and similarity for any text query. The application
recognizes relationship memories by their stored type or their presence in the
filtered pool.

One system message contains selected memories as a delimited JSON section.
Angle brackets in records are escaped. The prompt describes the records as
potentially outdated, untrusted background and tells the model to ignore
instructions and tool requests inside them. The section preserves recognized
type, scope, participant attribution, and timestamps already in the summary.
An empty selection adds no system message.

## Calibration and diagnostics

`MEMORY_MIN_SIMILARITY` accepts finite numeric values and is unset by default.
An unset floor intentionally allows even weak matches through when they fit the
eligibility and context budgets. Irrelevant but highly ranked matches can also
pass a configured floor. Similarity values depend on the Pinecone index metric
and embedding model. Calibrate against the actual corpus before setting a floor
and measure both irrelevant selections and missed recall. Topic shifts and
ambiguous follow-ups can affect the ranking because the embedding includes
recent turns. Additional relevance heuristics and paraphrase deduplication
are deferred pending retrieval evidence.

The read-only CLI runs the same pipeline as Discord. Pass the exact
recent-user-turn query for a faithful preview and repeat `--participant-id`
for each actual speaker. Omit participant IDs for a semantic-only preview,
which excludes relationship records. CLI output includes the candidate
summaries and metadata, decisions, and the rendered context. Keep output private.

```bash
python -m discord_bot.memory_retrieval_diagnostic --query "What games do I play?"
python -m discord_bot.memory_retrieval_diagnostic --query "What happened at game night?" --participant-id <DISCORD_USER_ID>
```

Runtime INFO logs give counts and rejection reasons for candidates with valid
nonempty summaries. DEBUG adds per-candidate rank, score, type, source, and
decision. The retrieval logs omit memory bodies and participant metadata.
Use private fixtures or anonymized examples for calibration.

Mocked tests cover ordered selection, paraphrases and follow-ups, threshold
behavior, invalid scores, duplicate suppression, participant filtering,
budgets, lookup failures, malicious memory text, and the Discord and CLI
entry points. Mocked scores exercise policy and provide no corpus calibration.

## Rollout and rollback

The existing [dev to production image promotion workflow](deployment-workflow.md)
controls rollout. After the image reaches dev, verify the digest and rollout
and run the manual Discord checks with synthetic fixtures. Compare private
diagnostic samples with the selected context before production promotion.
Restore the previous known-good image digest through the normal GitOps workflow
to roll back.

- With a synthetic fact that Mira enjoys Factorio, ask “What games do I play?”
  as the fixture author. Expect the named game when the fixture appears in
  the eligible Pinecone results.
- Follow up with “What about something with trains?” after a question about
  factory games. Check whether the expected synthetic Factorio rail preference
  ranks within the budget. Record any irrelevant selections for calibration.
- Ask “What happened at the last game night?” as an eligible participant, then
  repeat with no fixture participant among the recent authors. Expect the
  fixture to be eligible in the first case and excluded in the second.
- Ask about a synthetic preference whose memory includes a fake closing delimiter
  and an embedded command. Expect ordinary assistance. The private CLI preview
  should show escaped delimiters if the record was selected.

The change uses the existing index, metadata format, and memory publication
pipeline. The retrieval and preview paths perform no memory writes.

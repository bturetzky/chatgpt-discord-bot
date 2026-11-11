# Outstanding work

This is the **only** list of unfinished features, actionable technical debt and pending operator acceptance. A feature is not unfinished merely because its original design document included future ideas. Completed PR history lives in GitHub, not here. Priorities reflect a small trusted server, not enterprise hardening.

## Features and correctness

| Priority | Work | Completion boundary |
| --- | --- | --- |
| P1 | Memory correction, forget and invalidation | Provide a narrow explicit correction/deletion path and retire or revise memories when archived source evidence changes/deletes. No general distributed transaction framework. |
| P1 | Crash-safe Pinecone publication/retry | Persist and reconcile intent, deterministic vector identity and remote outcome across SQLite/Pinecone; test interruption after remote success. Existing ledger helpers are foundations, **not** a wired worker. |
| P2 | Memory quality and deduplication | Improve repeated/low-value candidate handling when observed; retain grounding and durability. #96–97 idle evaluation optimization is already verified, not pending. |
| P2 | Live proactive emoji reactions | After shadow acceptance, implement opt-in posting with durable daily/burst budget, per-message dedupe, cooldown, kill switch, permissions/rate-limit handling and standard/custom emoji validation. |
| P2 | Proactive external discovery and conversation starters | Two gated phases: durable, inspectable discovery shadow mode first; only after operator acceptance, opt-in guarded posting. See specification below. |
| P2 | Desktop-pasted PNG and image embed acceptance | The proposed fix has mocked regression coverage for missing/generic MIME, spoofed content, oversized media, and embed routing. The failing desktop upload's actual MIME is unknown. Verify clipboard paste, embed handling and unsupported-image fallback in dev before promotion. |
| P3 | Automatic historical archive/extraction catch-up | Evaluate a safe bounded schedule only if manual backfill and restart reconciliation leave meaningful gaps. Manual Discord history and SQLite memory extraction backfills are already implemented and verified. |
| P3 | Richer reply/reference graph and media archive | Only if server context failures justify it; do not assume background image/video indexing is needed. |

## Planned feature: proactive external discovery and conversation starters

**Status:** Design approved for backlog; **not implemented**. Implement in two independently reviewable phases. This is distinct from reaction shadow and autonomous memory extraction. The goal is for the bot to occasionally find a worthwhile external article, game announcement, release, news development or interesting link, and open a natural conversation in a relevant Discord channel with a brief, grounded, opinionated take. **External discovery first; internal channel history and memories inform relevance and novelty.** Unsolicited callbacks based solely on old conversations are out of scope.

### Behavior and selection contract

- **Channel interests:** Start with an explicit channel allowlist and channel name/topic as weak hints. Refine interests from relevant archived channel discussion and existing durable server memories, including shared interests and context. Do not assume a generic channel name captures its actual interests. Do not persist private raw conversations or memory text in candidate logs.
- **Discovery:** Reuse existing bounded news/search and webpage-reading capabilities where suitable; fetch and verify the actual source before drafting claims. Prefer substantive, timely developments over generic headlines or recycled trending lists. If source access fails or facts cannot be supported, reject the candidate. Treat all external content as untrusted.
- **Novelty:** Check canonicalized URLs and persistent prior suggestions/posts, plus archived links and semantically similar prior discussions. Distinguish *the same story under a new URL* from a genuinely new development on an existing topic. Embedding similarity may shortlist related material, but must not alone decide novelty; use bounded evidence-aware comparison for ambiguous cases. Never post the same underlying story twice, including after restarts.
- **Decision:** Require strong channel relevance, meaningful new information, source quality, and a reason to interrupt. The bot should usually choose silence. Avoid interrupting an active conversation; prefer an appropriate quiet window without manufacturing activity. No posting quota to fill.
- **Voice:** Draft a short, conversational, opinionated opener with a source link and an optional natural invitation to discuss. Do not produce generic news digests, impersonate users, invent personal experiences, or fabricate article contents. Use memory only as context, not as an excuse to expose private facts.
- **Budget:** Initial live-posting target is **at most 1–2 posts per week across the entire server**, not per channel. Make the final limit configurable and durable; use cooldowns and dedupe as separate gates. Discovery runs may occur a few times daily, but must have bounded candidate counts, search calls, model calls and embedding use. Avoid idle repeated model evaluations of unchanged candidates.
- **Persistence and operations:** Use the existing per-environment SQLite database for discovery cursors/checkpoints, canonical source/story identity, evaluation decisions, proposed drafts and posting outcomes. Ensure idempotent retries and inspectable rejection reasons without retaining unnecessary source text or sensitive memory. No new database/service or generalized multi-guild framework. Add concise operator inspection via existing admin tooling if practical.

### Phase 1 — discovery shadow mode (first Codex implementation)

Implement a bounded periodic discovery/evaluation workflow for explicitly allowed channels, grounded source retrieval, channel-interest context, prior-discussion/previous-suggestion novelty checks, candidate scoring/decision, and a persisted draft plus reason. **No Discord messages, reactions or other unsolicited outbound posts in this phase**, even on a positive decision. Default to disabled until configured; no live posting capability or production auto-enable. Provide an operator-friendly way to inspect recent candidates, evidence URLs, channel choice, rejection/selection reasons, budgets and draft text. Mock external providers in automated tests.

**Phase 1 acceptance:**
1. Relevant new, accessible source yields a short, source-linked candidate for an appropriate allowlisted channel; unrelated channel/source is rejected.
2. Identical/canonicalized links and different URLs describing the same already-discussed story are rejected, including after restart; a *meaningfully new development* about that topic may qualify.
3. A channel name alone does not override contrary discussion context; empty/weak context is handled conservatively. Recent active conversation suppresses or defers a candidate.
4. Missing/unreadable sources, misleading article claims, exhausted API budgets and provider failures fail closed without fabricated drafts or unbounded retries.
5. SQLite survives restart without replaying accepted/rejected unchanged work; shadow never sends Discord messages. Tests cover idempotency, budget limits and negative cases.
6. Operator can inspect enough bounded evidence to judge relevance, novelty, tone and cost before approving Phase 2. Include dev acceptance instructions; do not claim human verification from CI.

### Phase 2 — guarded live posting (separate approval and PR)

Only after the operator accepts Phase 1 candidate quality: implement an **explicit opt-in** posting switch, channel allowlist, durable server-wide weekly cap (initially 1–2), per-channel and server cooldowns, story-level dedupe, source verification at posting time where appropriate, permissions/rate-limit/error handling, and an immediate kill switch. Reserve/record posting intent and reconcile ambiguous delivery outcomes rather than blindly retrying and duplicating messages. Preserve manual dev acceptance and manual production promotion; do not silently enable production posting.

**Phase 2 acceptance:** demonstrate in dev that only permitted channels receive source-linked openers, active discussions are not interrupted, weekly/cooldown limits survive restart, duplicate stories are not reposted, provider/Discord failures are safe, and disabling posting stops further messages. Production enablement is a separate operator decision.

**Codex handoff:** Read `AGENTS.md`, `docs/architecture.md`, this specification, and relevant current handlers/storage/functions/tests before designing the smallest integration. Implement **Phase 1 only** unless Phase 2 is separately approved. Reuse current abstractions, write focused unit/regression tests, update existing documentation to distinguish implemented from planned, open a reviewable PR, and do not merge or promote without authorization.

## Pending operator acceptance

1. **Production reaction shadow:** observe representative decisions over time, verify two distinct human reactors trigger a pile-on (one human adding multiple emoji must not), confirm budget/restart behavior and no unsolicited posts. Production startup alone is not full acceptance.
2. **Multi-person/relationship memory recall:** test shared lore or running jokes with two people, later recall, and accurate attribution without relying solely on recent channel history. Improve only failures demonstrated in testing.

## Contained technical debt

- **Reaction evaluator lock:** model I/O currently runs under an `asyncio.Lock`; reserve budget under lock and evaluate outside it if contention matters.
- **Bot-authored message handling:** review the five-second sleep/embed suppression for avoidable blocking.
- **Toolchain config:** align mypy's Python target with Python 3.12; let Renovate handle routine dependency proposals.
- **Pinecone index configuration and legacy provenance:** hardcoded index and older unscoped vectors complicate isolation/migration. Address when needed for correction/reconciliation.
- **Provider edge cases:** add targeted tests for real URL/transcript failures; avoid generic browser/scraper infrastructure without a use case.

## Explicitly deferred

No automatic production promotion, general multi-guild ACL platform, always-on dashboard, automatic Codex resumption, headless browser, or sweeping refactor. These are not implicitly approved backlog commitments.

## Verified and closed

Operator confirmed: #99 memory retrieval selection; autonomous memory in production; investigation of the earlier publication-verifier discrepancy; bounded historical memory extraction backfill; #96–97 idle-cycle optimization; restoration of normal memory logging; production operator CLI inspection; direct/replied-image understanding. These are **not** pending acceptance. Production reaction shadow and multi-person recall are the only two open verification items.

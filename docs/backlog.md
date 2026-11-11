# Outstanding work

This is the **only** list of unfinished features, actionable technical debt and pending operator acceptance. A feature is not unfinished merely because its original design document included future ideas. Completed PR history lives in GitHub, not here. Priorities reflect a small trusted server, not enterprise hardening.

## Features and correctness

| Priority | Work | Completion boundary |
| --- | --- | --- |
| P1 | Memory correction, forget and invalidation | Provide a narrow explicit correction/deletion path and retire or revise memories when archived source evidence changes/deletes. No general distributed transaction framework. |
| P1 | Crash-safe Pinecone publication/retry | Persist and reconcile intent, deterministic vector identity and remote outcome across SQLite/Pinecone; test interruption after remote success. Existing ledger helpers are foundations, **not** a wired worker. |
| P2 | Memory quality and deduplication | Improve repeated/low-value candidate handling when observed; retain grounding and durability. #96–97 idle evaluation optimization is already verified, not pending. |
| P2 | Live proactive emoji reactions | After shadow acceptance, implement opt-in posting with durable daily/burst budget, per-message dedupe, cooldown, kill switch, permissions/rate-limit handling and standard/custom emoji validation. |
| P3 | Automatic historical archive/extraction catch-up | Evaluate a safe bounded schedule only if manual backfill and restart reconciliation leave meaningful gaps. Manual Discord history and SQLite memory extraction backfills are already implemented and verified. |
| P3 | Richer reply/reference graph and media archive | Only if server context failures justify it; do not assume background image/video indexing is needed. |

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

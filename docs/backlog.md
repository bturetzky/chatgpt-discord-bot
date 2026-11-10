# Verified backlog — small-server bot

**Reviewed:** 2026-11-09 against `main`. **Audience:** one production guild with ~5 friends, separate dev bot. This is a prioritized burndown, not an enterprise hardening checklist.

## How to use this list

- **P1**: correctness or recurring cost/quality problem worth fixing soon; **P2**: next useful feature or contained debt; **P3**: optional polish, only if it becomes annoying.
- **Implemented** means a code path exists; **operator-verified** requires live Discord or deployment evidence. Documentation and code can disagree; prefer current code and the newest operator checkpoint.
- Keep feature design and historical decisions in their existing documents. Move work here only while outstanding. A green build does not prove a live feature.
- No blanket demand for multi-tenancy, complex authorization, HA services, enterprise observability, exhaustive privacy machinery, or automated prod promotion.

## P1 — correctness and memory quality

| Item | Verification on main | Practical completion |
| --- | --- | --- |
| **M1. Memory corrections, deletion and invalidation** | **Real gap.** `storage/autonomous_memory.py` publishes create proposals only; no autonomous update/merge/split/delete. `memory_publication_ledger.py` and `memory_pinecone_reconciliation.py` provide operator/read-only foundations but are not wired into the worker. Archived message deletion does not automatically remove a published Pinecone memory. | Support a small explicit forget/correct path, and retire/revise affected autonomous vectors on changed/deleted source evidence. Verify in dev with a deliberately corrected fact. Do not require a general-purpose distributed transaction framework. |
| **M2. Crash-safe memory publication / retry** | **Real gap.** `autonomous_memory.run_once` upserts Pinecone, then separately marks SQLite candidate accepted; the worker does not use the publication-attempt ledger. A crash between those steps leaves ambiguous state. | Reconcile deterministic vector IDs before retry, persist intent/outcome, and test interruption after remote success. Reuse existing ledger helpers where practical. |
| **M3. Repeated/low-value memories and repeated evaluation cost** | **Observed in dev** per `memory-lifecycle-status.md`; the worker performs similarity checks but only skips matches at a fixed threshold and leaves blocked/review candidates proposed. `run_forever` repeats every 30 minutes. | Improve durability filter, semantic duplicate handling and candidate terminal/retry state; log cycle costs/counts. Verify that unchanged rejected candidates do not repeatedly consume model calls. |
| **M4. Restore ordinary logging after memory troubleshooting** | **Operational check, not proven current production defect.** `memory-lifecycle-status.md` explicitly reports temporary DEBUG logs with full retrieved summaries and identifiers. Default INFO logging may already be restored; deployment env is owned by `homelab-gitops`. | Check actual dev/prod log level; disable verbose memory logging in prod, keep sanitized counts. No elaborate redaction subsystem needed. |

## P2 — features worth finishing

| Item | Verification on main | Practical completion |
| --- | --- | --- |
| **F1. Live proactive emoji reactions** | **Not implemented.** `handlers/reaction_shadow.py` explicitly never posts. Candidate sampling, pile-on detection, delayed model decisions, persistent 8-evaluation/24h shadow budget and reaction observation **are implemented**. | Observe shadow results for a few days, then implement guarded posting with a small durable per-day reaction budget, per-message dedupe, cooldown, Discord permission/rate-limit handling and a kill switch. Test standard and existing server custom emoji in dev. Avoid overengineering for five people. |
| **F2. Server lore / multi-person memory acceptance** | **Partially implemented.** SQLite archive, FTS5, bounded backfill, conversation context, extraction, grounding and autonomous create-only Pinecone publication exist. The docs note that multi-person relationship recall and bot-only-memory recall are not fully acceptance-tested. | Run realistic two-person conversation and later recall tests, including one correction and one running joke. Improve only demonstrated failures. |
| **F3. Production autonomous-memory confirmation** | **Status check.** Latest `README.md` and `memory-lifecycle-status.md` confirm dev publication and retrieval, not production promotion. The production state is outside this repo. | Confirm promoted image, feature flag, one cycle and recall in prod; update checkpoint. Do not claim unverified deployment. |
| **F4. Historical reply/reference graph and richer archive metadata** | **Not implemented as designed.** `server-awareness-design.md` defers reply/reference graph and URL/attachment/embed archiving; current context expansion is chronological, not a reply graph. | Only add if actual server-context questions fail. Start with reply references before full media indexing. |
| **F5. Rich-content enhancements** | **Partially implemented.** Discord image understanding, on-demand public HTML/GitHub README reading and YouTube transcripts exist. No common reader service, background enrichment/indexing, generic video/GIF understanding, or headless browser. | Treat these as optional separate features. Prefer specific requested media types over a generalized ingestion platform; document inaccessible/paywalled/JS-only pages honestly. |
| **F6. Agentic Codex workflow follow-ups** | **Partial.** Codex PR→CI→dev ARC verification worked; `agent-development-design.md` says event-driven resumption, CI-repair loop and live Discord automated acceptance were not tested/implemented. Automatic prod promotion is intentionally manual. | Defer until repeated manual waiting is a real pain. Live Discord smoke testing has more value than event-driven agent orchestration. |

## P2 — contained code/maintenance debt

| Item | Verification on main | Practical completion |
| --- | --- | --- |
| **D1. Reaction evaluator serializes expensive model calls under lock** | **Code-confirmed.** `ReactionShadow._delayed` holds `asyncio.Lock` through `await self._evaluate(...)`; model request has a 25-second timeout. This needlessly blocks other candidates. | Reserve budget atomically under lock, release it before model I/O, then update evaluation. Test two simultaneous candidates and the 24-hour cap. Not urgent until live posting. |
| **D2. Bot-authored message handler sleeps five seconds before suppressing embeds** | **Code-confirmed.** `DiscordHandler.process_message` sleeps and edits messages authored by the bot before returning. This is avoidable per-message work and could produce needless errors. | Check whether embed suppression is still necessary. If yes, make it narrowly scoped and non-blocking; otherwise remove it. |
| **D3. Configuration/tooling mismatch** | **Code-confirmed.** `pyproject.toml` supports Python 3.12 only, while `[tool.mypy]` still says Python 3.10; Poetry remains on 1.8.3. | Align mypy target to 3.12, then consider Poetry and dependency updates through Renovate. Python 3.14 is not a current requirement. |
| **D4. Hardcoded Pinecone index and shared legacy memory metadata** | **Code/docs-confirmed.** README identifies hardcoded index `discord-bot-context2`; legacy vectors may lack guild/participant provenance. | Make index configurable if dev/prod isolation or migrations need it. Handle legacy records explicitly during memory correction work; do not build a full tenant-isolation system for this server. |
| **D5. Integration gaps around external providers** | **Known limitations, not blanket defects.** URL reader has explicit timeouts, content and network restrictions; prior dev checks observed some news sites blocked or timing out. YouTube transcript support is already operator-confirmed. | Add targeted regression tests when a real link/video fails. Avoid headless browser and generic scraping infrastructure by default. |
| **D6. Roadmap/status drift** | **Verified.** `engineering-roadmap.md` includes historical 'next' sections; `server-awareness-design.md` still calls autonomous extraction/publication planned while newer README and memory checkpoint confirm dev operation. `memory-lifecycle-status.md` ends with stale 'no scheduler' language after describing a live worker. | Use this backlog as the pending-work source. In a separate doc cleanup, label historical plans and reconcile current status without erasing decision history. |

## P3 — optional / explicitly deferred

- Conversation-aware semantic search, richer source provenance UI and admin slash commands: useful only if ordinary history lookup becomes frustrating.
- Full automatic vector splitting, complex revision trees, cross-store atomicity, generic replay framework, multi-guild ACLs and elaborate retention policies: **not justified yet**; implement the narrow correction/forget case first.
- Broader proactive personality beyond reactions, richer media enrichment and advanced agent autonomy: ideas, not release blockers.
- Automated production promotion: **intentionally not wanted**; retain manual approval.
- Python 3.14, large refactors and lint/type cleanup: opportunistic, not a reason to delay features.

## Already shipped — do not reopen as missing

- Python 3.12 container, Poetry lockfile, dependency cleanup, Renovate configuration and manual production promotion workflow.
- Modern OpenAI Responses/tool calls, Brave search, weather/news/IGDB, YouTube transcripts, public webpage/GitHub README fetching and image inputs.
- SQLite archive, FTS5 history search, bounded backfill, restart reconciliation, reaction add/remove/clear observation and shadow evaluation.
- Dev autonomous extraction, evidence evaluation, consolidation and guarded **create-only** Pinecone publication, with operator-observed retrieval.
- Codex/ARC pipeline experiment and dev deployment verification (not a guarantee of live Discord behavior).

## Suggested burndown order

1. Confirm production memory deployment and restore INFO logging (small operational checks).
2. Fix memory duplicate/retry behavior, then provide a narrow correct/forget mechanism and crash reconciliation.
3. Review real shadow reaction decisions and ship live emoji reactions behind a kill switch.
4. Run a real two-person lore/recall acceptance session.
5. Tackle D1–D3 alongside related changes; pick any other feature only when it sounds fun or solves an observed problem.

**Review boundary:** This is a static review of the repository and its documented operator evidence, not a fresh test against running Kubernetes/Discord/Pinecone. Feature status may change after merges or promotions. See `engineering-roadmap.md`, `memory-lifecycle-status.md`, `proactive-personality-design.md`, `rich-content-understanding-design.md`, and `agent-development-design.md` for detail.

# Engineering roadmap and code review

**Reviewed:** 2026-11-09 | **Status:** Living roadmap; Python 3.12 promoted, Renovate enabled, dependency cleanup promoted; ARC dev verification and first autonomous Codex pipeline experiment passed; expanded ARC gateway/stability verifier passed live and orphaned ARC ServiceAccount cleanup restored Synced/Healthy; public URL feature PRs #41–42 deployed and manually exercised; live article access failures classified, while GitHub README and local-address rejection passed.

This roadmap covers application code. The separate [deployment workflow](deployment-workflow.md) covers CI, image publishing, dev deployment and production promotion. Deployment manifests remain authoritative in [homelab-gitops](https://github.com/bturetzky/homelab-gitops).

## Current implementation checkpoint (2026-11-09)

- **Implemented:** Persistent SQLite with separate dev/prod PVCs, live message archive, FTS5 history search, bounded/resumable historical backfill, startup reconciliation and reaction add/remove/clear observation. Operator completed a 30-day production backfill and verified dev reaction membership persistence.
- **Shadow evaluation (bot PRs #70–71):** Two candidate paths (1-in-12 independent sampling and pile-on after 2 distinct human reactors), 60-second debounce, 8 persistent evaluations/rolling 24h, diagnostic logs and an opt-in dev-only deterministic test prefix. Dev real-model test completed with `ignore/no_clear_reaction` (303 input, 41 output tokens), no reaction posted. GitOps PRs #224–225 were merged to remove the dev test prefix and configure production guild `<production guild ID>` with the validated image. **Production runtime confirmation and multi-day observation remain outstanding.**
- **Next:** Keep production reaction shadow evaluation unchanged for multi-day observation. In parallel, begin Server Awareness extraction infrastructure (conversation segmentation and SQLite ledger), followed by bounded dry-run extraction. Live reaction posting remains a separate future decision; no live proactive reaction posting is implemented.
- **Documentation:** [reaction shadow runbook](reaction-shadow-runbook.md), [proactive design](proactive-personality-design.md), [SQLite foundation](sqlite-foundation.md), [Server Awareness](server-awareness-design.md). Kubernetes configuration remains in `homelab-gitops`.

## Server culture memory extraction decision (2026-11-09)

- **Approved direction:** build persistent, provenance-backed server collective culture/lore memories from ordinary SQLite-archived conversations, including messages not addressed to the bot. Accepted memories will use the existing Pinecone recall path. Extraction uses a separate prompt, runs periodically every several hours in the existing bot pod after dry-run validation, and supports explicit bounded historical processing.
- **First code PR:** extraction ledger schema and deterministic text-only conversation segmentation with tests; no LLM calls, scheduling, Pinecone writes, or reaction changes. Subsequent PRs cover dry-run candidate extraction, deduplication/invalidation, then guarded autonomous writes and scheduling.
- **Deferred:** reply/reference graph persistence and attachment/URL/embed metadata archiving are distinct future enhancements, not dependencies of the first extraction PR.
- **Design:** [Server Awareness](server-awareness-design.md#memory-extraction-architecture-decision-2026-11-09). These are approved plans, not deployed behavior.

## Autonomous feature development checkpoint (2026-11-08)

- **Implemented and operator-verified:** ARC runner installed and smoke-tested; dedicated get-only dev Deployment/Argo CD Application RBAC; main-branch build → dev GitOps update → Argo CD rollout → digest/readiness verification job passed. No inbound homelab webhook or extra HTTP verification service.
- **Experiment completed (PR #38):** Codex created a trivial health helper and test, passed 85 local tests and PR CI, merged its PR, polled the main-branch workflow, and posted successful digest-matched ARC verification to the original PR. Commit `9f147f5eab71e36f48b4c99937d899125622ed08`; [workflow evidence](https://github.com/bturetzky/chatgpt-discord-bot/actions/runs/42538409045). No manual handoff during polling.
- **Completed user-visible experiment (PRs #41–42):** Codex implemented bounded public HTML/article and GitHub README reading, deployed to dev with passing ARC verification, and improved safe diagnostic categorization after operator smoke tests. The operator observed a successful GitHub README answer, HTTP 403 for Ars Technica, timeout for The News Tribune, honest search-excerpt fallback, and correct refusal of a loopback URL. These are observed outcomes, not proof of general news-site coverage. The pasted Discord transcript's malformed Markdown was a copy/paste artifact; rendering was fine in Discord.
- **Approved next implementation order (2026-11-08):** shared persistent SQLite foundation → Server Awareness message ingestion/FTS5 search/bounded backfill → reaction observation/shadow mode → live proactive reactions → selective automatic memory extraction. Keep reaction budgets/deduplication in separate tables while reusing the archive and event infrastructure. Numerical reaction budgets remain undecided. YouTube transcript support is operator-confirmed complete; prior notes calling it pending live acceptance are stale. This was the original implementation order; SQLite, archive/FTS5/backfill and reaction observation/shadow evaluation are now implemented. Live posting and automatic memory extraction remain pending.
- **Verification boundary:** Green CI/ARC proves deployment and startup, not external-site accessibility or correct conversational behavior. CI-repair loop remains untested.
- **Not implemented/tested:** Event-driven agent resumption (Codex remained active and polled), automated live Discord integration verification, CI-repair loop, and automatic production promotion (intentionally manual). See [agent development design](agent-development-design.md).

## Server Awareness and proactive reactions priority decision (2026-11-08)

- Build and test the shared SQLite persistence layer first, with migrations, WAL/busy-timeout handling and a dedicated per-environment PVC; Kubernetes resources are owned by `homelab-gitops`.
- Deliver message ingestion, edit/delete handling, searchable FTS5 archive and explicitly bounded/resumable backfill before proactive reactions. The archive provides message context, not reaction policy or rate limiting.
- Reaction observation and shadow evaluation reuse that context; live reactions add separate durable reaction/event state, budgets, cooldowns and deduplication. Do not block the archive on unapproved numerical reaction budgets.
- Memory extraction follows a working archive, starts dry-run, and retains Pinecone as the semantic store. Preserve existing mention/reply behavior throughout.
- Operator confirmed YouTube transcript support complete. Reconcile any older 'pending validation' wording in the rich-content design without claiming tests or deployment details not independently verified.

## Per-chat usage instrumentation (proposed, 2026-11-07)

- **Implementation:** Each Discord chat turn logs model, Responses API call count (including tool round trips), total input tokens, cached input tokens, output tokens, elapsed milliseconds, and optional estimated USD cost. No message bodies or memories are logged.
- **Optional price configuration:** `OPENAI_INPUT_USD_PER_1M`, `OPENAI_CACHED_INPUT_USD_PER_1M`, and `OPENAI_OUTPUT_USD_PER_1M` are rates per million tokens. Defaults for `gpt-6.1-terra` are the published Standard API rates as of 2026-11-07: $1 input, $0.05 cached input, and $5 output per million tokens. Environment variables override defaults. Other model IDs without configured rates log `estimated_cost_usd=unconfigured`. Cached tokens are charged at the standard input rate when a cached rate is omitted or set to zero.
- **Scope:** USD estimate covers Responses usage only; embedding calls, Pinecone, Brave/weather services and infrastructure are not included. Actual billing can differ. Logs are emitted even when a Responses request fails (with usage collected up to that point).
- **Validation:** Verify log line after a simple message and a tool-using message, then check configured prices and totals against API usage.

## Memory retrieval observability (2026-11-07)

- Log semantic, relationship, and deduplicated memory counts at INFO level for each processed Discord request. Counts only; no memory content or participant identifiers are logged. This supports dev validation and production troubleshooting alongside the existing per-chat token/cost metrics.

## Relationship memory retrieval (proposed, 2026-11-07)

- **Implementation proposed:** Store optional `memory_type` and `participant_ids` in existing Pinecone metadata. New relationship memories can be filtered by Discord ID; older unstructured records remain available via ordinary semantic search without migration.
- **Retrieval:** Discord history defaults to 30 messages (was 13), semantic memories to eight (was nine), and relationship memories to four for the current/recent speakers. Configure with `DISCORD_CONTEXT_LIMIT`, `SEMANTIC_MEMORY_LIMIT`, and `RELATIONSHIP_MEMORY_LIMIT`.
- **Limitations:** This is not a profile database. Relationship retrieval only covers newly tagged records; existing memories do not acquire participant metadata automatically. Model-selected memory categories and IDs require live validation.
- **Validation:** Run CI, smoke-test dev, inspect sanitized memory counts, test writing and retrieving a confirmed relationship memory, and compare token usage and latency. Multi-person recall remains unverified.

## Personality iteration — v2 (proposed, 2026-11-07)

- **Observed in dev after v1:** Disagreement, roast, technical answers and weather tone were strong. Casual greetings and weekend suggestions still sounded like an overly helpful assistant. Memory recall worked but mostly surfaced old factual snippets; multi-person relationship continuity remains untested.
- **Proposed in v2:** Favor conversational replies over unsolicited lists, generic greetings, needless follow-up questions, and routine tool narration. Improve memory guidance for established running jokes, shared experiences, friendly rivalries, and explicit communication preferences, with speaker attribution and repeated evidence for inferred patterns.
- **Scope:** Prompt-only changes and deterministic regression tests. Reuses existing Pinecone index, retrieval, and store_memory tool; does not add profiles, schema changes, background capture, or automatic relationship extraction. No claim of improved memory retrieval until tested.
- **Validation after dev deploy:** Repeat casual greeting, weekend idea, roast, serious Kubernetes question, and tool call. Test a two-person disagreement, then later recall; confirm no invented relationship history and no assumption that a single roast request implies permanent consent.

## Current checkpoint — dependency cleanup and promotion (2026-11-07)

- **Completed:** PR #24 configured Renovate for Poetry, Monday 06:00–10:00 Pacific, with lockfile maintenance and no automerge. Mend repository access was enabled. First Renovate PR review remains pending.
- **Completed:** Obsolete `duckduckgo-search` was removed with a regenerated Poetry lockfile; PR #27 subsequently removed five unused direct dependencies (`discord`, `chatgpt`, `aiosqlite`, `numpy`, `html5lib`) and their orphaned transitive packages. The bot retains `discord.py`, `aiohttp`, `beautifulsoup4`, and `lxml` where used.
- **Verified by operator:** PR #27 Docker build passed; PR merged and resulting image promoted to production. No separate post-promotion smoke-test details were supplied.
- **Stopping point:** No further cleanup planned now. Review Renovate's first update PRs when available, test changes in dev, and promote deliberately. Poetry/tooling and Python 3.14 compatibility remain future work, not completed changes.

## Runtime modernization PR #23 — Python 3.12 compatibility step (2026-11-07)

- **Completed and verified:** PR #23 switched the container from `python:3.10-slim` to `python:3.12-slim` while retaining Poetry 1.8.3 and the dependency lockfile. Operator confirmed green CI, successful dev smoke tests, and production promotion. The remaining lxml and other dependency compatibility constraints should be checked before a future Python 3.14 upgrade.
- **Validation:** Docker build and regression suite passed; dev smoke tests passed; operator confirmed production promotion. Individual dev smoke test coverage was not enumerated.
- **Next:** Review Renovate updates, then assess Poetry modernization and Python 3.14 compatibility. Do not claim this interim runtime upgrade completes dependency modernization.

## Historical checkpoint — memory PR #22 and modernization planning (2026-11-07)

- **Confirmed:** PR #22 passed the Docker build and test suite, was merged to main, and deployed to dev. Operator reports satisfactory limited dev testing. A two-person conversation test with Alan remains outstanding because he was unavailable; do not claim full multi-person recall was validated.
- **Historical checkpoint:** Operator initiated production promotion of the memory changes; later confirmed Python 3.12 deployment was promoted after dev smoke tests. Separate memory-specific production recall validation was not reported.
- **Implemented in PR #22:** Recent multi-person Discord history now carries readable speaker names and stable IDs; Pinecone retrieval queries use up to six recent user turns (2400-character bound); memory guidance encourages capturing useful attributed facts from any participant; retrieved metadata is presented as clean summary text; deterministic IDs make exact normalized repeated writes idempotent. Existing UUID memories remain; paraphrases and conflicting facts are not deduplicated.
- **Historical plan, now completed in part:** Python 3.10 container replacement and unused direct dependency cleanup were subsequently completed; Poetry 1.8.3 remains and Python 3.14 compatibility has not been validated.
- **Dependency maintenance:** Renovate is configured for weekly Poetry dependency PRs without automerge. Keep major upgrades separate and smoke-test dev before production promotion.

## Confirmed progress and live validation (2026-11-06–07)

- **Implemented:** Modern OpenAI Responses API integration, configurable model, updated SDK and Poetry lockfile, async tool dispatch, focused regression tests, and serialization of response output for follow-up tool calls (PRs #10 and #11). Dev Discord basic conversation and weather tool succeeded after the fix.
- **Observed:** Memory retrieval appears in dev logs and the bot reported a successful memory write; a separate retrieval test is not required for the current promotion decision. Memory privacy and retention quality remain open engineering concerns.
- **Historical:** Unofficial DuckDuckGo searches returned HTTP `202 Ratelimit`, prompting the move to the official Brave Search API.
- **Verified in dev (PR #21, 2026-11-07):** Replaced unofficial DuckDuckGo scraping with Brave Search's official API using `BRAVE_SEARCH_API_KEY` from the existing Kubernetes Secret. Structured results and explicit errors are implemented, tests passed CI, and the user confirmed live dev search results. Production promotion was initiated but is not yet confirmed complete.
- **Historical plan (completed by PR #24):** Add Renovate for Poetry `pyproject.toml` and `poetry.lock`: weekly dependency PRs, periodic lockfile maintenance, major upgrades separate, no automerge initially. Bot main merges automatically deploy to dev, so dependency PRs should be reviewed and validated before merge. Implemented; first scheduled PR review pending.
- **Verified:** Manual production promotion workflow implemented (PR #12). User ran it against main, reviewed and merged the resulting GitOps PR, confirmed dev/prod image digests match, observed production rollout, and confirmed the production bot remains responsive. No image rebuild or automatic production merge.
- **Remaining:** Memory capture/retrieval quality, dependency maintenance, remaining blocking I/O, and SSRF defense in depth are active improvement areas; historical findings below may already be addressed.

## Production validation (2026-11-07)

- **Confirmed by operator:** Logging cleanup and gateway intent changes deployed to production, production bot responsive. Dev smoke test exercised weather, webpage fetch, IGDB, news and memory write. DDG search returned RatelimitException and was handled without crashing. Brave Search subsequently passed CI and a live dev search; production validation is pending.

## Logging cleanup and smoke-test correction (proposed PR, 2026-11-07)

- **Confirmed:** Dev bot was responsive; the apparent outage was caused by copying plain-text `@chatgpt-dev` from the smoke-test runbook instead of selecting a real Discord mention. No gateway regression was established.
- Replace full tool-schema startup dump with tool-name summary; standardize tool success/failure logging with duration, avoid logging web queries/results, OpenAI exception text, or full memory contents; keep per-message event diagnostics at DEBUG.
- Correct smoke-test mention instructions. **Validation pending:** CI and dev smoke checks.

## Discord gateway diagnostics and message-content intent (proposed PR, 2026-11-07)

- **Observed:** After PR #18 reached dev, pod was Ready but user messages produced no handler logs. Root cause not yet confirmed; the existing `on_ready` message was DEBUG-only and message content intent was not explicitly enabled.
- **Proposed fix:** Explicitly request `message_content` intent, configure INFO logging, log gateway ready/disconnect/resume and incoming message metadata (without bodies), and avoid printing retrieved memory contents. Add an intent regression test.
- **Validation pending:** CI and dev smoke test. The **Message Content Intent must also be enabled in the Discord Developer Portal** for the dev application; application code alone cannot grant it. Avoid production promotion until live dev messages work.
- SSRF DNS rebinding and egress policy remain separate security work.

## Webpage SSRF hardening (PR #18 merged, dev validation pending; 2026-11-07)

- Restrict model-provided webpage fetches to HTTP(S) with public IP/DNS answers and standard ports; reject local/private/reserved destinations, URL credentials and non-HTML content.
- Validate each redirect target, disable ambient proxy settings, enforce request timeouts and cap streamed response bodies at 1 MB. Add security regression tests for private IPs, mixed DNS, redirects, content types and oversized bodies.
- **Defense-in-depth still needed:** DNS is resolved during validation and again by the HTTP transport, leaving a DNS rebinding/time-of-check-to-time-of-use window. Add an egress network policy/firewall blocking pod access to private/cluster/metadata addresses before treating this as a complete SSRF boundary. The app-level checks reduce risk but do not replace network enforcement.
- **Validation:** User reported green build and dev rollout, but Discord messages stopped reaching the handler; live webpage smoke test remains pending. No Pinecone/memory behavior changes.

## Memory regression coverage and dev smoke runbook (merged PR #17, 2026-11-07)

- Add mocked embedding/Pinecone retrieval, upsert, error and empty-result tests, memory tool persistence, and Discord injection of retrieved memories into model context. No live Pinecone changes, migrations or credentials.
- Add [dev smoke-test runbook](dev-smoke-test.md) for rollout, conversation, weather, Brave search, webpage fetching, existing-memory recall, optional restart and explicit production promotion.
- **Validated:** User reported green CI and merged PR #17. Manual dev smoke checks remain separate from CI; memory writes are not part of routine smoke tests.
- **Confirmed:** User reported PR #16 green and merged.

## Tool and API regression coverage (merged PR #16, 2026-11-07)

- Add mocked tests for multi-call Responses API correlation, malformed/non-object tool arguments, tool error propagation, empty responses, and OpenAI timeouts.
- Cover weather geocoding and forecast failures, forecast trimming, webpage HTTP failures and parser fallback/truncation, and search-provider failure handling. No external requests or credentials.
- **Validated:** User reported green CI and merged PR #16. New tests are discovered automatically by the Docker image build; CI success is required before merge. This is deterministic component-level testing, not live integration.
- Next: memory write/retrieval tests, message edge cases, and documented post-deployment live smoke tests. Do not change shared Pinecone memory behavior.

## Test suite modernization (merged PR #15, 2026-11-07)

- Replaced the obsolete `tests/test_chat_bot.py` (removed module and Python `imp`) with tests of current Discord routing, DMs, shutdown gating, chronological history, and message splitting.
- Changed `make test` to propagate failures and run all discovered tests in the Docker build, not just the two previously selected modules.
- **Validated:** User reported green CI and merged PR #15. This is mocked application behavior coverage, not a live Discord/OpenAI/Pinecone end-to-end test. A separate dev smoke-test procedure remains useful.
- **Observed after PR #14:** User confirmed successful build, merge, dev deployment, and live conversation/weather/webpage/memory smoke checks. DuckDuckGo web search remained rate-limited at that point; the provider was later replaced with Brave Search. User initiated production promotion; completion not yet verified.

## Startup regression and CI correction (2026-11-07)

- **Observed after PR #13 merged:** Dev CrashLoop due to an empty `VectorStore.close()` function body; Python raised `IndentationError` before bot startup.
- **Corrective PR #14 merged and dev-validated:** Add executable `pass` to the no-op close hook. Make Docker image build run `compileall` and both focused Responses API and reliability regression suites **before** the image can be published. This prevents the same syntax/import failure from reaching dev again.
- **Follow-up:** Modernize the legacy `tests/test_chat_bot.py` suite separately; it still references the removed `chat_bot` module. Verify dev health and Discord smoke tests before production promotion.

## Reliability hardening PR (2026-11-07)

- **PR #13 merged; dev smoke-tested after corrective PR #14:** Correct Discord shutdown to close the actual vector handler and always close resources when the client exits. Remove the obsolete Pinecone `deinit` call.
- **Proposed:** Run synchronous Pinecone/embedding lookups and blocking weather, news and webpage HTTP calls off the Discord event loop; add network timeouts to weather calls and a 30-second async tool execution timeout.
- **Proposed:** Continue responding if Discord history or memory retrieval fails; handle empty geocoding results and pages without article/div tags; add focused regression tests.
- **Scope decision:** This bot serves five trusted friends on one Discord server. Shared memory across guild and DMs is intentional and acceptable. Defer Pinecone namespace/schema changes, retention work, logging cleanup and SSRF protections; revisit SSRF as P1 rather than a release blocker. No Pinecone data migration is planned.
- **Validation needed:** Run regression tests and smoke-test dev (conversation, weather, memory retrieval, shutdown/restart) after merge. The existing legacy test suite remains a separate cleanup item.

## Priority guide

- **P0:** security/correctness risks to address before expanding features
- **P1:** high-impact reliability and modernization
- **P2:** maintainability, performance and quality
- **P3:** optional features and product ideas

## P0 — secure and stabilize

1. **Completed — Fix async function dispatch** — `handlers/function_handler.py` defines synchronous `execute_function` returning `instance.execute(args)`, where the tool's `execute` is async; `chatgpt_handler.py` awaits the wrapper once, receiving a coroutine rather than its resolved value. Make dispatch async, await the implementation, and return a consistently serialized result. Add mocked tool-call round-trip tests.
2. **Protect webpage fetching against SSRF** — `functions/get_webpage_contents.py` fetches model-provided URLs with `requests.get`. Restrict to http/https, reject loopback/private/link-local/metadata IPs (including DNS resolution and redirect targets), bound response size/content type, and consider an egress policy. This is particularly relevant inside a home Kubernetes network.
3. **Remove sensitive prompt and memory logging** — `chatgpt_handler.py` prints full messages and model responses; `discord_handler.py` prints user messages and retrieved memories. Switch to structured, redacted logging with request IDs and no secrets/private conversation bodies by default.
4. **Deferred — Memory namespace/retention improvements (shared memory intentional)** — `vectore_store.py` queries the shared index without namespace or metadata filter; `discord_handler.py` includes the author in query text but that is not an access boundary. Shared recall between server and DMs is intentional for this small trusted community. Do not migrate existing Pinecone records now; revisit optional metadata, retention and inspection only if useful.
5. **Partially verified — Verify and repair memory tool end-to-end** — `functions/memory_function.py` calls `VectorHandler()` during function discovery; singleton initialization depends on ordering. Validate persistence, namespace metadata, and retrieval with integration tests. Memory is currently encouraged automatically in the system prompt; introduce deliberate retention/consent behavior.

## P1 — reliability and modern API

6. **Replace obsolete tests with real tests** — `tests/test_chat_bot.py` imports a `chat_bot` module absent from the current tree and uses removed `imp`. Rebuild tests against `discord_bot`; cover message routing, history, chunking, tool dispatch, OpenAI errors, memory isolation and shutdown. Fix `Makefile` test target, which currently masks failures with `|| echo`.
7. **Completed (core migration) — Modernize OpenAI client/tool calls** — `handlers/chatgpt_handler.py` uses legacy `openai.ChatCompletion.create` and `functions/function_call`; `vector_handler.py` uses legacy `openai.Embedding.create`. Move to a supported client/API with an explicit model configuration, retries, timeouts, and regression tests. Avoid coupling this to unrelated features.
8. **Fix graceful shutdown** — `discord_handler.py` calls `self.vector_store.close()` although it owns `self.vector_handler`; `vectore_store.py` calls `pinecone.deinit()` without importing `pinecone`, and current client lifecycle needs review. Handle SIGTERM/CancelledError cleanly in Kubernetes.
9. **Remove blocking I/O from async handlers** — synchronous OpenAI calls, Pinecone calls, `requests` in weather/page tools, and NewsAPI may block the Discord event loop. Use async clients or bounded `asyncio.to_thread` wrappers, with timeouts and concurrency limits.
10. **Harden error paths** — `discord_handler.py` continues if history fetch fails (potentially unbound `messages`); `vectore_store.py` can return `None` which the caller iterates; malformed tool JSON can break the response loop. Return safe fallback responses and test failures.
11. **Partially implemented — Make function-call behavior bounded** — enforce tool call count, execution time, output size and parameter validation; confirm forced-final-response semantics on the chosen API. Avoid long unconditional sleeps between model/tool steps.
12. **Harden Discord message handling** — test mention precedence, DM handling, empty/oversized messages, role ordering, and splitting very long lines or fenced code. Prevent accidental mentions with allowed_mentions restrictions and ensure message content intent is configured.

## P2 — maintainability and performance

13. **Centralize configuration** — replace hardcoded `GPT_MODEL`, `EMBEDDING_MODEL`, `INDEX_NAME`, `CONTEXT_LIMIT`, `RETRIEVAL_LIMIT`, timeouts and sleeps with validated environment-based configuration; document defaults.
14. **Partially completed — Modernize dependencies/runtime** — Python 3.12 is promoted; unused direct dependencies removed; Renovate enabled with no automerge. Next review dependency PRs, then modernize Poetry and evaluate Python 3.14 compatibility separately. Consider dependency scanning and reproducible builds.
15. **Refactor lifecycle and dependencies** — remove global `openai.api_key` and `VectorHandler` singleton; inject client and storage dependencies into handlers for isolation and testability.
16. **Improve tool implementations** — `get_weather.py` uses HTTP for geocoding and lacks timeouts/error validation; `get_webpage_contents.py` may raise `ValueError` if no matching tags; IGDB fetches a token per call and lacks timeouts. Standardize HTTP, retries, response bounds and errors.
17. **Completed in dev — Review search integration** — replaced unofficial DuckDuckGo integration with Brave Search API; added mocked tests for success, empty results, authentication, rate limiting, timeout, network errors and malformed results. Live dev search succeeded; production promotion pending.
18. **Partially completed (PR #22) — Improve memory capture and retrieval** — keep broad, useful memory capture rather than aggressively filtering writes. Current implementation embeds an author-ID-prefixed message, retrieves nine nearest Pinecone vectors without checking similarity scores, and injects raw metadata dictionaries as system messages. Model-initiated writes are optional; each write creates a new UUID without deduplication or updates. Explore better capture guidance, readable memory text, relevance thresholds and mechanisms to update conflicting/outdated facts. Shared guild/DM memory remains intentional; no Pinecone migration planned.
19. **Improve observability** — structured logs, model/tool latency, error counters, startup readiness checks and an explicit verification runbook. Do not emit user content as telemetry.
20. **Clean up dead code and naming** — obsolete `get_summary` references undefined `utilities`; duplicated imports, stale comments, `vectore_store.py` typo, confusing `WeatherLookup` class name in `memory_function.py`, and unused `guild_id`.
21. **Improve code quality tooling** — format/lint/type-check with CI gating, resolve misleading Makefile targets, add pre-commit checks as desired.

## P3 — optional improvements

- Per-channel or per-user conversation controls, explicit reset/forget commands and memory inspection.
- Discord slash commands for configuration, help and diagnostics rather than mention-only interaction.
- Configurable model selection and token/cost budgets.
- Better search source citations, tool-result summarization and caching.
- Health/status reporting and alerts for repeated model/provider failures.
- Consider additional AI providers only after stabilizing the current integration.

## Suggested sequencing

**Phase 1: Safety and a trustworthy baseline.** Fix the async tool dispatcher, SSRF, private logging and memory scoping. Replace stale tests and ensure CI actually fails on test failure. Avoid broad dependency upgrades until this baseline is established.

**Phase 2: Modernization.** Upgrade OpenAI client and tool calling, fix async I/O, error handling and shutdown, then update runtime/dependencies incrementally.

**Phase 3: Operational quality.** Implement the [CI/CD promotion design](deployment-workflow.md), centralized configuration, observability and improved test coverage.

**Phase 4: User-facing improvements.** Prioritize new capabilities based on actual usage after stability is demonstrated.

## Memory capture and recall improvement (proposed PR, 2026-11-07)

- Encourage proactive capture of durable ordinary facts, plans, preferences and ongoing project context, with standalone statements identifying the subject. Do not store credentials or repeat identical facts in a turn.
- Retrieve against the recent multi-person conversation: up to six user turns (bounded to 2400 characters), with readable Discord names and stable IDs in history. The model sees the wider recent conversation and is instructed to attribute facts to any participant, not just the user who mentioned the bot. This is a relevance hint, not an ownership boundary; existing memories have no user-ID metadata. Shared memory remains intentional.
- Pass the stored summary strings to the model instead of raw Pinecone metadata dictionaries. Preserve existing Pinecone index, embeddings, top-nine nearest-neighbor retrieval and stored records.
- Use deterministic Pinecone vector IDs derived from normalized memory text (excluding the tool's timestamp), so exact repeat writes overwrite the same vector rather than occupying multiple retrieval slots. Previously stored UUID records remain untouched; paraphrases and contradictions are not deduplicated.
- Add focused regression coverage for multi-person queries, bounds, clean summaries, idempotent writes and history fallback. **CI and live dev validation pending.** No score threshold or index migration; evaluate semantic duplicates and conflicting memories separately.

## Memory implementation review (2026-11-07)

- **Confirmed in code:** `DiscordHandler.process_message` embeds `author_id says: <message>` and retrieves Pinecone context on each handled message. `VectorStore.fetch_context` requests `top_k=9` with metadata but does not inspect match scores or apply a similarity threshold; it returns metadata dictionaries rather than the `summary` field alone.
- **Confirmed in code:** The model is instructed to store important preferences/details and can call `store_memory`, but there is no automatic extraction pass. Writes prepend a timestamp, embed the text, and upsert under a fresh UUID; there is no deduplication, update or conflict resolution.
- **Interpretation:** Large volumes of ordinary memories are not inherently harmful: vector search ranks candidates. But nearest-neighbor ranking alone does not guarantee relevance, and missing captures cannot be recovered by retrieval. Prioritize improving capture and retrieval over suppressing routine writes. Shared memory across trusted users remains a deliberate choice.
- **Proposed next steps (not implemented):** return clean memory text and optionally scores; inspect real match score distributions before choosing thresholds; improve capture instructions and handling of outdated/duplicate facts; add focused regression tests. Avoid index migrations until there is evidence they are needed.

## Decisions and validation still needed

- Live conversation and weather tool confirmed; memory retrieval observed in logs and write reported successful. Additional memory isolation/retention validation remains open.
- Decision: guild/DM-shared memory is acceptable; no per-user isolation or schema migration planned now.
- Decide which bot interactions need retention, deletion or opt-in.
- Production bot responded successfully after promotion of the tested Responses API image; precise API model identity was not independently verified from response metadata.
- Dev smoke tests completed for conversation and weather; historical DuckDuckGo rate limiting was resolved by moving to Brave Search, which succeeded in dev. Expand automated coverage later.
- Check existing Pinecone data before changing embedding dimensions or namespace strategy.

**Status note:** Historical sections preserve original inspection findings for context. Completion labels and confirmed progress above take precedence over their original wording; unresolved items remain future work.

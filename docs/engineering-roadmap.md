# Engineering roadmap and code review

**Reviewed:** 2026-11-07 | **Status:** Living roadmap; initial findings came from static inspection, with later live dev validation noted below.

This roadmap covers application code. The separate [deployment workflow](deployment-workflow.md) covers CI, image publishing, dev deployment and production promotion. Deployment manifests remain authoritative in [homelab-gitops](https://github.com/bturetzky/homelab-gitops).

## Confirmed progress and live validation (2026-11-06–07)

- **Implemented:** Modern OpenAI Responses API integration, configurable model, updated SDK and Poetry lockfile, async tool dispatch, focused regression tests, and serialization of response output for follow-up tool calls (PRs #10 and #11). Dev Discord basic conversation and weather tool succeeded after the fix.
- **Observed:** Memory retrieval appears in dev logs and the bot reported a successful memory write; a separate retrieval test is not required for the current promotion decision. Memory privacy and retention quality remain open engineering concerns.
- **Observed:** Web search failed twice because DuckDuckGo returned HTTP `202 Ratelimit`. The bot reported failure without crashing. Search-provider reliability is a separate issue, not a blocker for promoting the working API migration.
- **Deferred:** Improve search provider reliability/fallback, make rate-limit errors explicit to the model to avoid immediate retries, and tighten memory-write criteria to avoid saving trivial interactions.
- **Deferred:** Add Renovate for Poetry `pyproject.toml` and `poetry.lock`: weekly dependency PRs, periodic lockfile maintenance, major upgrades separate, no automerge initially. Bot main merges automatically deploy to dev, so dependency PRs should be reviewed and validated before merge. Not started.
- **Verified:** Manual production promotion workflow implemented (PR #12). User ran it against main, reviewed and merged the resulting GitOps PR, confirmed dev/prod image digests match, observed production rollout, and confirmed the production bot remains responsive. No image rebuild or automatic production merge.
- **Remaining:** SSRF protection, sensitive logging, memory isolation/retention, test coverage, shutdown/error handling, and search reliability remain open; see original findings below.

## Webpage SSRF hardening (proposed PR, 2026-11-07)

- Restrict model-provided webpage fetches to HTTP(S) with public IP/DNS answers and standard ports; reject local/private/reserved destinations, URL credentials and non-HTML content.
- Validate each redirect target, disable ambient proxy settings, enforce request timeouts and cap streamed response bodies at 1 MB. Add security regression tests for private IPs, mixed DNS, redirects, content types and oversized bodies.
- **Defense-in-depth still needed:** DNS is resolved during validation and again by the HTTP transport, leaving a DNS rebinding/time-of-check-to-time-of-use window. Add an egress network policy/firewall blocking pod access to private/cluster/metadata addresses before treating this as a complete SSRF boundary. The app-level checks reduce risk but do not replace network enforcement.
- **Validation pending:** PR CI and dev smoke-test webpage fetching. No Pinecone/memory behavior changes.

## Memory regression coverage and dev smoke runbook (merged PR #17, 2026-11-07)

- Add mocked embedding/Pinecone retrieval, upsert, error and empty-result tests, memory tool persistence, and Discord injection of retrieved memories into model context. No live Pinecone changes, migrations or credentials.
- Add [dev smoke-test runbook](dev-smoke-test.md) for rollout, conversation, weather, DDG search, webpage fetching, existing-memory recall, optional restart and explicit production promotion.
- **Validated:** User reported green CI and merged PR #17. Manual dev smoke checks remain separate from CI; memory writes are not part of routine smoke tests.
- **Confirmed:** User reported PR #16 green and merged.

## Tool and API regression coverage (merged PR #16, 2026-11-07)

- Add mocked tests for multi-call Responses API correlation, malformed/non-object tool arguments, tool error propagation, empty responses, and OpenAI timeouts.
- Cover weather geocoding and forecast failures, forecast trimming, webpage HTTP failures and parser fallback/truncation, and DDG rate-limit fallback. No external requests or credentials.
- **Validated:** User reported green CI and merged PR #16. New tests are discovered automatically by the Docker image build; CI success is required before merge. This is deterministic component-level testing, not live integration.
- Next: memory write/retrieval tests, message edge cases, and documented post-deployment live smoke tests. Do not change shared Pinecone memory behavior.

## Test suite modernization (merged PR #15, 2026-11-07)

- Replaced the obsolete `tests/test_chat_bot.py` (removed module and Python `imp`) with tests of current Discord routing, DMs, shutdown gating, chronological history, and message splitting.
- Changed `make test` to propagate failures and run all discovered tests in the Docker build, not just the two previously selected modules.
- **Validated:** User reported green CI and merged PR #15. This is mocked application behavior coverage, not a live Discord/OpenAI/Pinecone end-to-end test. A separate dev smoke-test procedure remains useful.
- **Observed after PR #14:** User confirmed successful build, merge, dev deployment, and live conversation/weather/webpage/memory smoke checks. DuckDuckGo web search remained rate-limited; fallback response was graceful. User initiated production promotion; completion not yet verified.

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
14. **Modernize dependencies/runtime** — upgrade Python 3.10 base, Poetry and dependencies in tested steps; remove redundant/unused packages after import audit. Add dependency scanning and reproducible builds.
15. **Refactor lifecycle and dependencies** — remove global `openai.api_key` and `VectorHandler` singleton; inject client and storage dependencies into handlers for isolation and testability.
16. **Improve tool implementations** — `get_weather.py` uses HTTP for geocoding and lacks timeouts/error validation; `get_webpage_contents.py` may raise `ValueError` if no matching tags; IGDB fetches a token per call and lacks timeouts. Standardize HTTP, retries, response bounds and errors.
17. **Review search integration** — verify current `AsyncDDGS.text` usage and results shape; add mocked tests for empty results, provider errors and rate limiting.
18. **Improve memory quality** — avoid flooding prompt with nine raw matches; return bounded, deduplicated text, relevance thresholds, timestamps and retention/delete controls. Decide whether memory storage is opt-in.
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

## Decisions and validation still needed

- Live conversation and weather tool confirmed; memory retrieval observed in logs and write reported successful. Additional memory isolation/retention validation remains open.
- Decision: guild/DM-shared memory is acceptable; no per-user isolation or schema migration planned now.
- Decide which bot interactions need retention, deletion or opt-in.
- Production bot responded successfully after promotion of the tested Responses API image; precise API model identity was not independently verified from response metadata.
- Dev smoke tests completed for conversation and weather; web search exposed DuckDuckGo rate limiting. Expand automated coverage later.
- Check existing Pinecone data before changing embedding dimensions or namespace strategy.

**Status note:** Numbered items retain their original inspection findings for context. Completion labels and confirmed progress above take precedence over their original wording; unresolved items remain future work.

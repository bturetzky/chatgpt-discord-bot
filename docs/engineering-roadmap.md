# Engineering roadmap and code review

**Reviewed:** 2026-11-06 | **Status:** Proposed; findings are from static code inspection, not verified live failures.

This roadmap covers application code. The separate [deployment workflow](deployment-workflow.md) covers CI, image publishing, dev deployment and production promotion. Deployment manifests remain authoritative in [homelab-gitops](https://github.com/bturetzky/homelab-gitops).

## Priority guide

- **P0:** security/correctness risks to address before expanding features
- **P1:** high-impact reliability and modernization
- **P2:** maintainability, performance and quality
- **P3:** optional features and product ideas

## P0 — secure and stabilize

1. **Fix async function dispatch** — `handlers/function_handler.py` defines synchronous `execute_function` returning `instance.execute(args)`, where the tool's `execute` is async; `chatgpt_handler.py` awaits the wrapper once, receiving a coroutine rather than its resolved value. Make dispatch async, await the implementation, and return a consistently serialized result. Add mocked tool-call round-trip tests.
2. **Protect webpage fetching against SSRF** — `functions/get_webpage_contents.py` fetches model-provided URLs with `requests.get`. Restrict to http/https, reject loopback/private/link-local/metadata IPs (including DNS resolution and redirect targets), bound response size/content type, and consider an egress policy. This is particularly relevant inside a home Kubernetes network.
3. **Remove sensitive prompt and memory logging** — `chatgpt_handler.py` prints full messages and model responses; `discord_handler.py` prints user messages and retrieved memories. Switch to structured, redacted logging with request IDs and no secrets/private conversation bodies by default.
4. **Scope vector memory per user and environment** — `vectore_store.py` queries the shared index without namespace or metadata filter; `discord_handler.py` includes the author in query text but that is not an access boundary. Define explicit bot/environment, guild and user scope in stored metadata and query filters. Decide whether any shared memories are intentional; plan migration for existing unscoped entries.
5. **Verify and repair memory tool end-to-end** — `functions/memory_function.py` calls `VectorHandler()` during function discovery; singleton initialization depends on ordering. Validate persistence, namespace metadata, and retrieval with integration tests. Memory is currently encouraged automatically in the system prompt; introduce deliberate retention/consent behavior.

## P1 — reliability and modern API

6. **Replace obsolete tests with real tests** — `tests/test_chat_bot.py` imports a `chat_bot` module absent from the current tree and uses removed `imp`. Rebuild tests against `discord_bot`; cover message routing, history, chunking, tool dispatch, OpenAI errors, memory isolation and shutdown. Fix `Makefile` test target, which currently masks failures with `|| echo`.
7. **Modernize OpenAI client/tool calls** — `handlers/chatgpt_handler.py` uses legacy `openai.ChatCompletion.create` and `functions/function_call`; `vector_handler.py` uses legacy `openai.Embedding.create`. Move to a supported client/API with an explicit model configuration, retries, timeouts, and regression tests. Avoid coupling this to unrelated features.
8. **Fix graceful shutdown** — `discord_handler.py` calls `self.vector_store.close()` although it owns `self.vector_handler`; `vectore_store.py` calls `pinecone.deinit()` without importing `pinecone`, and current client lifecycle needs review. Handle SIGTERM/CancelledError cleanly in Kubernetes.
9. **Remove blocking I/O from async handlers** — synchronous OpenAI calls, Pinecone calls, `requests` in weather/page tools, and NewsAPI may block the Discord event loop. Use async clients or bounded `asyncio.to_thread` wrappers, with timeouts and concurrency limits.
10. **Harden error paths** — `discord_handler.py` continues if history fetch fails (potentially unbound `messages`); `vectore_store.py` can return `None` which the caller iterates; malformed tool JSON can break the response loop. Return safe fallback responses and test failures.
11. **Make function-call behavior bounded** — enforce tool call count, execution time, output size and parameter validation; confirm forced-final-response semantics on the chosen API. Avoid long unconditional sleeps between model/tool steps.
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

- Confirm live tool behavior and whether memory writes/reads currently succeed.
- Establish expected memory privacy: per-user by default, and whether guild-shared memory is ever desired.
- Decide which bot interactions need retention, deletion or opt-in.
- Confirm current production model/API compatibility before choosing the OpenAI migration target.
- Identify a representative set of Discord smoke tests against the isolated dev bot.
- Check existing Pinecone data before changing embedding dimensions or namespace strategy.

**Implementation status:** No application code was changed by this review. Priorities are recommendations, not commitments or verified incidents.

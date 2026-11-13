# Enhance search_web with useful search metadata

**Status:** Approved design; not implemented. **Assignment:** 02 — independent Codex handoff.

## Outcome
Enhance search_web with useful search metadata. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/functions/search_web.py`

## Scope and approach
Return short snippets and available publication metadata alongside title/URL; expose a validated optional freshness parameter in the tool schema (current code checks pw but schema omits it). Keep existing 1–5 result bound and structured rate-limit/auth errors. Do not imply snippets prove the full article.

## Acceptance criteria
Tests for missing metadata, provider errors, freshness serialization, result limits and malformed payloads; no secrets logged.

## Manual dev verification
Ask for this week's news, compare snippets, and request an article; verify a no-results query reports uncertainty.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

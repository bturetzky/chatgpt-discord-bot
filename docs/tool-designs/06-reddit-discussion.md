# Implement get_reddit_discussion for public threads

**Status:** Approved design; not implemented. **Assignment:** 06 — independent Codex handoff.

## Outcome
Implement get_reddit_discussion for public threads. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/functions/get_webpage_contents.py`
- `discord_bot/functions/base.py`

## Scope and approach
Accept a Reddit thread URL or post ID; retrieve bounded public post text and top comments with scores, timestamps, nesting and permalink, using an allowed API/endpoint and respecting access/rate limits. Preserve parent-child context and explicitly flag removed, deleted, inaccessible or truncated discussions. No posting, voting or login requirements.

## Acceptance criteria
Tests for nested comments, sorting, truncation, removed comments, rate limits, invalid URLs and injection-like untrusted content.

## Manual dev verification
Ask about a linked gaming discussion and request the top opposing viewpoints; verify inaccessible thread fallback.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

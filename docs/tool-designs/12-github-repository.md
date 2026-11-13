# Implement get_github_repository for public project context

**Status:** Approved design; not implemented. **Assignment:** 12 — independent Codex handoff.

## Outcome
Implement get_github_repository for public project context. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/functions/base.py`
- `discord_bot/functions/get_webpage_contents.py`

## Scope and approach
Accept a public GitHub repo URL or owner/repo; retrieve bounded repo metadata, README summary, latest release and recent commits via public endpoints. Clearly label stale/missing release and rate-limit errors. No GitHub writes, private repository access or token requirements by default.

## Acceptance criteria
Tests for URL parsing, 404, rate limit, README absence, release absence, huge README and redirect safety.

## Manual dev verification
Ask about a public repo's purpose, latest release and recent changes.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

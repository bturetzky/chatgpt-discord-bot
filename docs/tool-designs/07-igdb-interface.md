# Simplify IGDB game/platform lookup and cache authentication

**Status:** Approved design; not implemented. **Assignment:** 07 — independent Codex handoff.

## Outcome
Simplify IGDB game/platform lookup and cache authentication. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/functions/get_igdb_game_info.py`
- `discord_bot/functions/get_igdb_platform_ids.py`

## Scope and approach
Keep compatibility with current Apicalypse calls or migrate deliberately. Add safe structured title/platform/genre/date inputs and useful defaults; resolve platform IDs internally where possible. Cache Twitch token until near expiry, handle refresh/retry once, bound result sizes, normalize errors, and avoid exposing credentials.

## Acceptance criteria
Tests for token reuse/expiry, malformed query, ambiguity, platform filtering, missing metadata and API errors.

## Manual dev verification
Find a game by title and platform in one call; query similar games and a nonexistent title.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

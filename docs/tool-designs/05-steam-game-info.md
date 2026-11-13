# Implement get_steam_game_info for Steam store questions

**Status:** Approved design; not implemented. **Assignment:** 05 — independent Codex handoff.

## Outcome
Implement get_steam_game_info for Steam store questions. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/functions/get_igdb_game_info.py`
- `discord_bot/functions/base.py`

## Scope and approach
Read public Steam store/app data for game title or app ID, resolving ambiguous names explicitly. Return currency/region-qualified price and discount, release date, review summary/count, supported platforms and Steam Deck status only when an authoritative source exposes it. Do not scrape login-only pages or guess compatibility; use timeouts and short bounded results.

## Acceptance criteria
Tests cover ambiguous titles, unavailable prices/regions, free games, delisted apps, provider errors, missing Deck data and proper source attribution.

## Manual dev verification
Ask current price of a popular game, compare two games and test a title with multiple editions.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

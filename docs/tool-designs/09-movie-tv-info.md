# Implement get_movie_tv_info for entertainment lookups

**Status:** Approved design; not implemented. **Assignment:** 09 — independent Codex handoff.

## Outcome
Implement get_movie_tv_info for entertainment lookups. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/functions/base.py`

## Scope and approach
Use a supported public movie/TV metadata source (e.g. TMDB with documented credentials). Search by title and optionally year/type; return concise synopsis, cast, release dates, seasons, ratings and source links. Streaming availability must be region-qualified, timestamped and omitted if not reliable. Disambiguate remakes and similarly named titles.

## Acceptance criteria
Tests for title ambiguity, movies vs series, unreleased entries, missing cast/streaming data, provider failure and result bounds.

## Manual dev verification
Ask about two same-name films, an ongoing series and where to watch it in a specified country.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

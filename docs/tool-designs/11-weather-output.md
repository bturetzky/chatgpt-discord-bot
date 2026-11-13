# Enhance weather_lookup with targeted forecast modes

**Status:** Approved design; not implemented. **Assignment:** 11 — independent Codex handoff.

## Outcome
Enhance weather_lookup with targeted forecast modes. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/functions/get_weather.py`

## Scope and approach
Add optional forecast scope current|today|tomorrow|extended while preserving default behavior as needed. Return compact relevant fields with units and location/timezone; validate US state ambiguity, use HTTPS for geocoding, normalize errors and avoid dumping unnecessary hourly JSON.

## Acceptance criteria
Tests for each scope, location ambiguity, empty geocoding, timezone/units, API errors and data gaps.

## Manual dev verification
Ask if rain is expected tomorrow, current temperature and a multi-day forecast.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

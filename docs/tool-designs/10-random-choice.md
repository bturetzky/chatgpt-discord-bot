# Implement roll_dice and random_choice as bounded utilities

**Status:** Approved design; not implemented. **Assignment:** 10 — independent Codex handoff.

## Outcome
Implement roll_dice and random_choice as bounded utilities. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/functions/base.py`

## Scope and approach
Provide one small function with operation=roll|choose (or two if clearer). Use Python secrets/SystemRandom for real server-side randomness; validate dice count/sides and list size, return transparent rolls/choice, no persistence or member scraping. Explicitly exclude gambling/betting integration.

## Acceptance criteria
Tests verify input bounds, output ranges, empty choices, repeat-safe formatting and injection-resistant string handling.

## Manual dev verification
Roll 2d20, pick among three names and reject a request for an enormous number of dice.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

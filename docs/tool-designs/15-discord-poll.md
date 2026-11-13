# Implement create_discord_poll as an explicit on-demand action

**Status:** Approved design; not implemented. **Assignment:** 15 — independent Codex handoff.

## Outcome
Implement create_discord_poll as an explicit on-demand action. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/handlers/function_handler.py`
- `discord_bot/handlers/discord_handler.py`

## Scope and approach
Create a native Discord poll only in the current authorized channel after an explicit user request; validate question, 2–10 answers and duration against Discord API limits. Avoid duplicate submissions within one reply; return a link or clear error. Do not add autonomous polls or moderation permissions.

## Acceptance criteria
Tests for validation, permissions, API failures, duplicate calls and correct channel scope.

## Manual dev verification
Ask for a two-option poll, verify the native poll appears, and test invalid options/permission denial.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

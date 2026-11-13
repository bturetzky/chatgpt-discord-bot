# Implement get_discord_member_info for permitted guild context

**Status:** Approved design; not implemented. **Assignment:** 13 — independent Codex handoff.

## Outcome
Implement get_discord_member_info for permitted guild context. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/handlers/function_handler.py`
- `discord_bot/handlers/discord_handler.py`

## Scope and approach
Resolve a mentioned member or guild-local ID only in current guild. Return display name, nickname, join date and non-sensitive role names; presence/activity only when intents, availability and user expectations permit. Never enumerate all members, leak privileged details or infer private relationships.

## Acceptance criteria
Tests for unknown member, cross-guild ID, missing intents, bot/user permission context and optional fields.

## Manual dev verification
Ask who a mentioned person is, then try a nonmember ID and ensure no cross-server disclosure.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

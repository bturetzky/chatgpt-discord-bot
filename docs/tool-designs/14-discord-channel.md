# Implement get_discord_channel_info for visible channel metadata

**Status:** Approved design; not implemented. **Assignment:** 14 — independent Codex handoff.

## Outcome
Implement get_discord_channel_info for visible channel metadata. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/handlers/function_handler.py`
- `discord_bot/handlers/discord_handler.py`

## Scope and approach
Accept channel mention/ID from current guild; return channel name, topic, type and a bounded list of pinned message summaries if caller and bot can view/read them. Avoid private channel discovery, broad listing or arbitrary message scraping.

## Acceptance criteria
Tests for hidden channels, missing pins, deleted pins, forum/thread types and permission changes.

## Manual dev verification
Ask about channel purpose and pinned guidance; test an inaccessible channel.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

# Implement get_discord_message for a linked message

**Status:** Approved design; not implemented. **Assignment:** 04 — independent Codex handoff.

## Outcome
Implement get_discord_message for a linked message. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/functions/discord_history_function.py`
- `discord_bot/handlers/function_handler.py`
- `discord_bot/handlers/discord_handler.py`

## Scope and approach
Accept a Discord message URL or channel/message IDs; use current guild and caller/bot permission context, prefer archive where possible and optionally fetch Discord API for current metadata. Return bounded full text, author display name, timestamp, jump URL, attachment metadata, reaction summary and reply reference. No cross-guild reads or arbitrary API access; don't download attachment bytes.

## Acceptance criteria
Tests validate URL parsing, permission denials, deleted/missing messages, archive fallback, Discord fetch errors, size limits and correct attribution.

## Manual dev verification
Paste a visible message link, a deleted link and a link to a restricted channel; verify content and errors.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

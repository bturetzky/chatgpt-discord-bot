# Implement get_discord_thread for actual reply chains

**Status:** Approved design; not implemented. **Assignment:** 08 — independent Codex handoff.

## Outcome
Implement get_discord_thread for actual reply chains. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/functions/discord_history_function.py`
- `discord_bot/storage/message_archive.py`

## Scope and approach
Given a visible message or thread ID, follow explicit Discord reply references or native thread membership, not chronological adjacency. Reuse archive and selectively fetch visible Discord data if needed. Return ordered bounded messages with parent links, authors and jump URLs; state when a chain is incomplete. Do not require a new background crawler.

## Acceptance criteria
Tests for branch replies, missing parents, thread channels, deleted messages, permissions, cycles and bounded traversal.

## Manual dev verification
Ask the bot to follow a reply chain, compare with neighboring unrelated messages, and try an inaccessible thread.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

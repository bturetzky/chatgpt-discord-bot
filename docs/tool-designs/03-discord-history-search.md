# Enhance archived Discord search for natural-language recall

**Status:** Approved design; not implemented. **Assignment:** 03 — independent Codex handoff.

## Outcome
Enhance archived Discord search for natural-language recall. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/functions/discord_history_function.py`
- `discord_bot/storage/message_archive.py`

## Scope and approach
Preserve guild/channel visibility checks and SQLite FTS5. Add optional relevance ordering versus newest, phrase/OR modes or a safe query normalization strategy, full-hit retrieval path, and display-name attribution from permitted guild cache where available. Keep results bounded and return stable message URLs; do not expose private channels.

## Acceptance criteria
Tests cover keyword/phrase matches, chronological vs relevance sorting, deleted messages, visibility boundaries, name fallback, malformed query and result limits.

## Manual dev verification
Ask what game was discussed weeks ago, who said a phrase, and for a message in an inaccessible channel.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

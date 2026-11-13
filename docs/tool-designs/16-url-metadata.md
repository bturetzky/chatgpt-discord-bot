# Enhance get_webpage_contents with link-preview metadata

**Status:** Approved design; not implemented. **Assignment:** 16 — independent Codex handoff.

## Outcome
Enhance get_webpage_contents with link-preview metadata. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/functions/get_webpage_contents.py`

## Scope and approach
Extract safe Open Graph/title/description/canonical URL metadata from already fetched public HTML; return alongside article content with size bounds and normalized absolute URLs. Treat metadata as untrusted; never fetch arbitrary embedded image URLs or bypass SSRF restrictions. Avoid creating a redundant tool unless needed.

## Acceptance criteria
Tests for missing/duplicate/malicious OG tags, canonical URLs, large metadata and redirect behavior.

## Manual dev verification
Read a page with a rich preview, a plain page and a malformed metadata page.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

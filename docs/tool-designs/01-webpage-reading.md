# Enhance get_webpage_contents for complete, navigable article reading

**Status:** Implemented on the feature branch; dev Discord verification pending. **Assignment:** 01 — independent Codex handoff.

## Outcome
Enhance get_webpage_contents for complete, navigable article reading. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/functions/get_webpage_contents.py`
- `discord_bot/handlers/chatgpt_handler.py`

## Scope and approach
Keep the existing public-URL/redirect/DNS protections, 1 MB response cap and untrusted-source warning. Improve main-content selection and preserve headings/links. Add bounded cursor-based continuation and optional find_text or section targeting; return next_cursor, total/remaining estimates and explicit truncation. Decide whether the two-read response budget needs adjustment for continuations, without making unbounded fetches.

## Acceptance criteria
A long article can be read in multiple bounded chunks; targeted text is findable; repeated cursor reads are stable; navigation noise is minimized; oversized/blocked/JS-only pages fail transparently; SSRF and redirect regression tests pass.

## Manual dev verification
Try a long public article and request a detail beyond 12k characters; try section-specific lookup; try an invalid/internal URL and confirm safe failure.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

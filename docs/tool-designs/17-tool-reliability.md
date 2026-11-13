# Standardize tool errors and budget-aware model behavior

**Status:** Implementation pending review and dev Discord acceptance. **Assignment:** 17 — independent Codex handoff.

## Outcome
Standardize tool errors and budget-aware model behavior. This is an on-demand LLM-callable capability, not an autonomous/background feature.

## Relevant existing code
- `discord_bot/handlers/function_handler.py`
- `discord_bot/handlers/chatgpt_handler.py`
- `discord_bot/functions/*`

## Scope and approach
Adopt a consistent ok/error/code/retryable result convention without breaking working callers. Make 30-second tool timeouts and function-call and shared read limits explicit to the model through actionable errors; ensure paging and multi-step workflows can finish. Keep tool logs sanitized; don't introduce a generalized agent loop or new infrastructure.

## Acceptance criteria
Tests for timeout, invalid args, provider errors, read limits, recovery paths and no leaked URLs/tokens in logs.

## Manual dev verification
Exercise a failed URL, a valid tool chain and a bounded continuation; verify one consolidated progress update.

## Implementation boundaries
- One standalone Codex PR; implement only this assignment, not adjacent proposals.
- Keep existing Python/Poetry, Responses API function-discovery architecture, dev/prod workflow and current trust model. No new background worker, database or feature flag unless genuinely required.
- External/Discord text is untrusted. Preserve existing authorization, SSRF protections and bounded outputs where applicable.
- Add focused unit tests with mocked providers; run `poetry run python -m unittest discover -s tests -t .`.
- Update architecture/README/operations only when implemented. A passing CI check is not Discord acceptance; production promotion remains manual.

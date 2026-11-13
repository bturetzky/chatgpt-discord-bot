"""Bound model-visible tool output after reader continuation processing."""

import json

from ..functions.base import tool_error

MAX_TOOL_RESULT_CHARS = 16_000
# Readers already bound their content and carry cursor offsets into it. Allow
# room for two YouTube pages, including timestamps and segment metadata.
READER_RESULT_LIMITS = {"get_webpage_contents": 48_000, "read_youtube": 192_000}


def _encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def bound_tool_output(name, result):
    limit = READER_RESULT_LIMITS.get(name, MAX_TOOL_RESULT_CHARS)
    output = str(result)
    if len(output) <= limit:
        return output

    try:
        payload = json.loads(output)
    except (ValueError, RecursionError):
        payload = output

    # Legacy readers serialize Unicode as escapes. Measure the compact JSON
    # before rejecting it so normal caption paging works across languages.
    if payload is not output:
        compact = _encode(payload)
        if len(compact) <= limit:
            return compact

    if name in READER_RESULT_LIMITS:
        error = json.loads(tool_error(
            "RESULT_TOO_LARGE", "Reader result exceeded the output limit. Use a narrower range or another source."
        ))
        error["result_truncated"] = True
        return _encode(error)

    # Keep complete JSON fields/items and retain the result type inside a
    # marked envelope. A text result gets a prefix, with room for JSON escapes.
    if isinstance(payload, dict):
        preview = {}
        items = payload.items()
    elif isinstance(payload, list):
        preview = []
        items = enumerate(payload)
    else:
        text = payload if isinstance(payload, str) else output
        preview = text[:(limit - 64) // 6]
        return _encode({"result_truncated": True, "result": preview})

    size = len(_encode({"result_truncated": True, "result": preview}))
    for key, value in items:
        item_size = len(_encode(value)) + 1
        if isinstance(preview, dict):
            item_size += len(_encode(key)) + 1
        if size + item_size > limit:
            break
        if isinstance(preview, dict):
            preview[key] = value
        else:
            preview.append(value)
        size += item_size
    return _encode({"result_truncated": True, "result": preview})

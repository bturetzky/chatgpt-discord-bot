"""Pure publication lifecycle rules; no database or vector-store writes.

Callers must validate evidence, compare existing logical memories, and reconcile
remote vector state before persisting any proposed transition.
"""

REVISION_STATES = frozenset({
    "staged", "pending", "published", "superseded", "invalidated", "failed",
})
TRANSITIONS = {
    "staged": frozenset({"pending", "invalidated"}),
    "pending": frozenset({"published", "failed", "invalidated"}),
    "failed": frozenset({"pending", "invalidated"}),
    "published": frozenset({"superseded", "invalidated"}),
    "superseded": frozenset({"invalidated"}),
    "invalidated": frozenset(),
}
ATTEMPT_STATES = frozenset({"pending", "confirmed", "failed", "uncertain"})


def next_revision_state(current, requested, *, remote_confirmed=False):
    """Validate one transition; never infer success from an API call attempt."""
    if current not in REVISION_STATES or requested not in TRANSITIONS[current]:
        raise ValueError("invalid publication revision transition")
    if requested == "published" and not remote_confirmed:
        raise ValueError("publication requires independently confirmed remote state")
    if requested == "superseded" and not remote_confirmed:
        raise ValueError("supersession requires confirmed replacement or deletion")
    return requested


def reconcile_attempt(status, observed, *, matching_vector=False):
    """Interpret a read-only reconciliation observation.

    Unknown remote outcomes remain uncertain; retries require separate
    reconciliation and explicit idempotent operation design.
    """
    if status not in ATTEMPT_STATES:
        raise ValueError("invalid attempt state")
    if observed == "matching" and matching_vector:
        return "confirmed"
    if observed == "missing":
        return "failed"
    if observed in {"unknown", "mismatched", "matching"}:
        return "uncertain"
    raise ValueError("invalid remote observation")


def next_revision_number(revisions):
    """Assign a monotonically increasing revision for an existing logical ID."""
    if any(type(n) is not int or n <= 0 for n in revisions):
        raise ValueError("invalid revision history")
    if len(revisions) != len(set(revisions)):
        raise ValueError("duplicate revision")
    return max(revisions, default=0) + 1

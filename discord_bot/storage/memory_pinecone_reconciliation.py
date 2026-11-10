"""Read-only Pinecone reconciliation for revision-specific publication metadata.

No upserts, deletes, model calls, or ledger transitions. A vector is confirmed
only if every expected identity and content field matches exactly.
"""
import hashlib
import json
import re

REQUIRED_FIELDS = frozenset({
    "memory_id", "revision", "guild_id", "scope", "participant_ids",
    "summary", "summary_hash", "source_hash", "durability", "proposal_id",
    "publication_schema",
})
SCHEMA = "memory-publication-v1"


def summary_hash(summary):
    return hashlib.sha256(summary.encode("utf-8")).hexdigest()


def expected_metadata(connection, memory_id, revision):
    """Construct expected metadata from persisted SQLite revision, not an LLM plan."""
    if type(revision) is not int or revision <= 0:
        raise ValueError("invalid revision")
    row = connection.execute(
        """SELECT r.guild_id, r.scope, r.participant_ids,
                  v.summary, v.source_hash, v.durability, v.proposal_id
           FROM memory_records r JOIN memory_revisions v ON v.memory_id=r.memory_id
           WHERE r.memory_id=? AND v.revision=?""",
        (memory_id, revision),
    ).fetchone()
    if row is None:
        raise ValueError("unknown memory revision")
    guild, scope, raw_participants, summary, source_hash, durability, proposal_id = row
    participants = json.loads(raw_participants)
    if (not isinstance(participants, list) or not participants
            or len(set(participants)) != len(participants)
            or not all(isinstance(p, str) and p.isdecimal() for p in participants)
            or not isinstance(summary, str) or not summary.strip()
            or not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash)):
        raise ValueError("invalid ledger revision")
    return {
        "publication_schema": SCHEMA,
        "memory_id": memory_id, "revision": revision,
        "guild_id": guild, "scope": scope,
        "participant_ids": sorted(participants),
        "summary": summary, "summary_hash": summary_hash(summary),
        "source_hash": source_hash, "durability": durability,
        "proposal_id": proposal_id,
    }


def _vectors(response):
    if isinstance(response, dict):
        return response.get("vectors")
    return getattr(response, "vectors", None)


def _vector_metadata(vector):
    if isinstance(vector, dict):
        return vector.get("metadata")
    return getattr(vector, "metadata", None)


def classify_fetch(response, *, vector_id, expected):
    """Classify Pinecone fetch output; fail closed on partial or legacy metadata."""
    if not isinstance(vector_id, str) or not vector_id:
        raise ValueError("vector ID required")
    if not isinstance(expected, dict) or not REQUIRED_FIELDS.issubset(expected):
        raise ValueError("complete expected metadata required")
    vectors = _vectors(response)
    if vectors is None or not hasattr(vectors, "get"):
        return {"observation": "unknown", "matching_vector": False, "reason": "unrecognized fetch response"}
    vector = vectors.get(vector_id)
    if vector is None:
        return {"observation": "missing", "matching_vector": False, "reason": "vector absent"}
    metadata = _vector_metadata(vector)
    if not isinstance(metadata, dict) or not REQUIRED_FIELDS.issubset(metadata):
        return {"observation": "mismatched", "matching_vector": False, "reason": "legacy or incomplete metadata"}
    if any(type(metadata[key]) is not type(expected[key]) or metadata[key] != expected[key]
           for key in REQUIRED_FIELDS):
        return {"observation": "mismatched", "matching_vector": False, "reason": "revision metadata differs"}
    return {"observation": "matching", "matching_vector": True, "reason": "all revision metadata matches"}


def fetch_revision(index, connection, *, memory_id, revision, vector_id, namespace=""):
    """Perform one read-only Pinecone fetch and compare with SQLite expectations.

    Caller supplies the configured namespace explicitly. Network exceptions are
    represented as unknown; never turn a timeout into a missing vector.
    """
    expected = expected_metadata(connection, memory_id, revision)
    if not isinstance(namespace, str):
        raise ValueError("namespace must be a string")
    try:
        response = index.fetch(ids=[vector_id], namespace=namespace)
    except Exception:
        return {"observation": "unknown", "matching_vector": False,
                "reason": "remote fetch failed"}
    return classify_fetch(response, vector_id=vector_id, expected=expected)

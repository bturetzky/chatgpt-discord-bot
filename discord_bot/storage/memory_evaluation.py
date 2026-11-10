"""Conservative, deterministic triage of extracted memory candidates.

This is a preview/ledger, NOT approval for Pinecone publication.
"""
from dataclasses import asdict, dataclass
import json
import re

EVALUATOR_VERSION = "triage-v1"
EVOLVING = re.compile(r"\b(currently|current|now|working on|planning|plans to|plan to|"
                     r"setting up|in progress|recently|next|this week|this month)\b", re.I)
TRANSIENT = re.compile(r"\b(reached the credits|\d+ moons|finished today|"
                       r"just beat|just completed)\b", re.I)


@dataclass(frozen=True)
class Assessment:
    scope: str
    durability: str
    disposition: str
    rationale: str


def evaluate(candidate):
    """Triage conservatively; never treat a heuristic as semantic validation."""
    kind = candidate["memory_type"]
    confidence = candidate["confidence"]
    summary = candidate["summary"]
    participants = json.loads(candidate["participant_ids"])
    sources = json.loads(candidate["source_message_ids"])
    if not isinstance(participants, list) or not isinstance(sources, list) or not sources:
        return Assessment("uncertain", "uncertain", "review", "Missing or malformed attribution")
    if kind == "lore" and len(set(participants)) > 1:
        scope = "collective"
    elif kind in ("fact", "event") and len(set(participants)) == 1:
        scope = "individual"
    else:
        scope = "uncertain"

    if kind == "event" or TRANSIENT.search(summary):
        durability = "transient"
    elif EVOLVING.search(summary):
        durability = "evolving"
    elif kind == "fact":
        durability = "durable"
    else:
        durability = "uncertain"

    # Do not reject events automatically: an event may be shared group history.
    # Do not auto-approve anything: corroboration, sensitivity and semantic
    # deduplication against Pinecone have not happened yet.
    if durability == "transient":
        rationale = "Likely short-lived event; inspect for exceptional shared significance"
    elif durability == "evolving":
        rationale = "Time-sensitive claim; requires freshness and supersession handling"
    elif scope == "collective":
        rationale = "Possible group lore; recurrence across windows not yet established"
    else:
        rationale = "Potentially useful context; semantic and safety review not yet implemented"
    if confidence != "high":
        rationale += "; extractor confidence is not high"
    return Assessment(scope, durability, "review", rationale)


def preview(connection, *, guild_id, limit=20):
    """Return a bounded, guild-scoped preview without modifying SQLite."""
    if not guild_id or not 1 <= limit <= 100:
        raise ValueError("guild_id and limit (1..100) required")
    connection.row_factory = __import__("sqlite3").Row
    rows = connection.execute(
        """SELECT c.batch_id, c.candidate_index, c.memory_type, c.summary,
                  c.participant_ids, c.source_message_ids, c.confidence,
                  c.status, b.guild_id
           FROM extraction_candidates c
           JOIN extraction_batches b ON b.batch_id=c.batch_id
           WHERE b.guild_id=? AND c.status='proposed'
           ORDER BY b.created_at DESC, c.batch_id, c.candidate_index
           LIMIT ?""", (str(guild_id), limit),
    ).fetchall()
    return [{**dict(row), "evaluation": asdict(evaluate(row))} for row in rows]


def record(connection, entries):
    """Explicit operator action. Does not change candidate acceptance status."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        for item in entries:
            decision = item["evaluation"]
            connection.execute(
                """INSERT INTO candidate_evaluations
                   (batch_id, candidate_index, evaluator_version, scope,
                    durability, disposition, rationale)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(batch_id, candidate_index, evaluator_version)
                   DO UPDATE SET scope=excluded.scope,
                     durability=excluded.durability,
                     disposition=excluded.disposition,
                     rationale=excluded.rationale,
                     evaluated_at=CURRENT_TIMESTAMP""",
                (item["batch_id"], item["candidate_index"], EVALUATOR_VERSION,
                 decision["scope"], decision["durability"],
                 decision["disposition"], decision["rationale"]),
            )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise

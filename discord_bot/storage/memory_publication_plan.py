"""Deterministic, read-only publication planning for proposed Discord memories.

A plan is never authorization to write to Pinecone or accept a candidate.
"""
import hashlib
import json
import re

from .evidence_evaluation import source_evidence

VERSION = "publication-plan-v1"
OPERATIONS = {"create", "update", "merge", "split", "review", "discard"}
ALLOWED_SCOPES = {"individual", "collective"}
ALLOWED_DURABILITY = {"durable", "evolving"}


def stable_id(guild_id, batch_id, candidate_index, split_index):
    """Stable proposal ID, not a semantic-deduplication key."""
    payload = json.dumps([str(guild_id), str(batch_id), int(candidate_index),
                          int(split_index)], separators=(",", ":"))
    return "proposal-v1-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def plan_entries(connection, entries, *, guild_id, bot_author_id):
    """Produce an auditable, fail-closed plan without modifying either store."""
    plans = []
    for entry in entries:
        if str(entry.get("guild_id")) != str(guild_id):
            raise ValueError("cross-guild candidate in publication preview")
        evaluation = entry.get("evaluation") or {}
        consolidation = entry.get("consolidation") or {}
        operation = consolidation.get("operation")
        reasons = []
        if entry.get("status") != "proposed":
            reasons.append("candidate is not proposed")
        if entry.get("batch_status") != "completed":
            reasons.append("extraction batch incomplete")
        if entry.get("evaluation_version") != "evidence-v1":
            reasons.append("evidence evaluation missing or outdated")
        if entry.get("consolidation_version") != "consolidation-v2":
            reasons.append("consolidation missing or outdated")
        if evaluation.get("disposition") != "review":
            reasons.append("evidence evaluation excluded candidate")
        scope = evaluation.get("scope")
        durability = evaluation.get("durability")
        if scope not in ALLOWED_SCOPES:
            reasons.append("scope not established")
        if durability not in ALLOWED_DURABILITY:
            reasons.append("durability not established")
        if operation not in OPERATIONS:
            reasons.append("unknown consolidation operation")
        if operation in {"discard", "review"}:
            reasons.append("consolidation requires discard or further review")
        if operation in {"update", "merge"}:
            reasons.append("revision/supersession ledger not implemented")
        if operation == "split":
            reasons.append("split proposals require per-atom provenance and deduplication")
        verification = entry.get("grounding_verification") or {}
        if operation in {"create", "update", "merge", "split"} and verification.get("supported") is not True:
            reasons.append("independent grounding not confirmed")
        evidence, evidence_error = source_evidence(
            connection, entry, bot_author_id=bot_author_id)
        if evidence_error:
            reasons.append("source invalid: " + evidence_error)
            evidence = []
        if any(connection.execute(
            "SELECT edited_at FROM messages WHERE message_id=?", (row["message_id"],)
        ).fetchone()[0] is not None for row in evidence):
            reasons.append("source edited; re-extract and re-evaluate before publication")
        try:
            participants = json.loads(entry["participant_ids"])
            sources = json.loads(entry["source_message_ids"])
        except (ValueError, TypeError, KeyError):
            participants, sources = [], []
            reasons.append("invalid attribution")
        if not isinstance(participants, list) or not participants or any(
            not isinstance(value, str) or not value.isdecimal() for value in participants
        ):
            reasons.append("participant attribution invalid")
            participants = []
        if not isinstance(sources, list) or not sources or any(
            not isinstance(value, str) or not value.isdecimal() for value in sources
        ):
            reasons.append("source attribution invalid")
            sources = []
        if scope == "individual" and len(set(participants)) != 1:
            reasons.append("individual memory must have exactly one participant")
        summary = consolidation.get("summary", "")
        if operation == "create" and (not isinstance(summary, str) or not summary.strip()):
            reasons.append("missing consolidated summary")
        if isinstance(summary, str) and re.search(r"<@!?[0-9]+>", summary):
            reasons.append("Discord mention markup is not canonical memory text")
        # These IDs identify proposal revisions. They deliberately do NOT claim
        # semantic uniqueness across extraction windows or authorize upserts.
        proposal_id = stable_id(entry["guild_id"], entry["batch_id"],
                                entry["candidate_index"], 0)
        plans.append({
            "proposal_id": proposal_id,
            "candidate": {"batch_id": entry["batch_id"],
                          "candidate_index": entry["candidate_index"]},
            "operation": operation,
            "decision": "review_required" if not reasons else "blocked",
            "blockers": list(dict.fromkeys(reasons)),
            "memory": {
                "summary": summary if isinstance(summary, str) else "",
                "guild_id": str(entry["guild_id"]),
                "scope": scope,
                "durability": durability,
                "participant_ids": sorted(set(participants)),
                "source_message_ids": sorted(set(sources)),
                "source_channel_id": str(entry["channel_id"]),
                "source_observed_at": min(
                    (row["created_at"] for row in evidence), default=None),
                "extractor_version": entry["extractor_version"],
                "evaluation_version": entry["evaluation_version"],
                "consolidation_version": entry["consolidation_version"],
            },
            "revision": {
                "target_id": consolidation.get("existing_id"),
                "supersedes": None,
                "status": "not_implemented",
            },
        })
    return {"version": VERSION, "recorded": False, "publishable": False,
            "count": len(plans), "plans": plans}

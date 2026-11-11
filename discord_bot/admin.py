"""Small-server operator CLI. Inspection is read-only; backfill writes SQLite proposals only.\nThe running autonomous worker may subsequently publish eligible proposals.

Run: python -m discord_bot.admin --help
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3

def connect():
    path = os.getenv("DISCORD_SQLITE_PATH")
    if not path:
        raise SystemExit("DISCORD_SQLITE_PATH is required")
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db

def guild(args):
    value = args.guild_id or os.getenv("REACTION_SHADOW_GUILD_ID")
    if not value or not value.isdecimal():
        raise SystemExit("Supply --guild-id or REACTION_SHADOW_GUILD_ID")
    return value

def output(data, args):
    if args.json:
        print(json.dumps(data, indent=2, default=str, ensure_ascii=False))
    elif isinstance(data, list):
        if not data:
            print("No matching records.")
        for item in data:
            print(json.dumps(item, ensure_ascii=False, default=str))
    else:
        for key, value in data.items():
            print(f"{key}: {value}")

def status(args):
    with connect() as db:
        tables = ("messages", "reaction_members", "shadow_evaluations",
                  "extraction_batches", "extraction_candidates")
        counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in tables}
        counts["sqlite_quick_check"] = db.execute("PRAGMA quick_check").fetchone()[0]
        counts["autonomous_memory_enabled"] = os.getenv("AUTONOMOUS_MEMORY_ENABLED", "").lower() == "true"
        counts["reaction_shadow_configured"] = bool(os.getenv("REACTION_SHADOW_GUILD_ID"))
        counts["sqlite_path"] = os.getenv("DISCORD_SQLITE_PATH")
        output(counts, args)

def reactions(args):
    gid = guild(args)
    with connect() as db:
        totals = [dict(r) for r in db.execute(
            """SELECT status, COALESCE(decision,'pending') AS decision, COUNT(*) AS count
               FROM shadow_evaluations WHERE guild_id=? GROUP BY status, decision""", (gid,))]
        where = "AND decision='react'" if args.react_only else ""
        rows = [dict(r) for r in db.execute(
            f"""SELECT evaluated_at, status, trigger, decision, emoji_key, reason_category,
                       guild_id, channel_id, message_id, input_tokens, output_tokens
                FROM shadow_evaluations WHERE guild_id=? {where}
                ORDER BY evaluated_at DESC LIMIT ?""", (gid, args.limit))]
    for r in rows:
        r["url"] = f"https://discord.com/channels/{r['guild_id']}/{r['channel_id']}/{r['message_id']}"
    if args.json:
        output({"totals": totals, "evaluations": rows}, args)
    else:
        print("Shadow evaluation totals:", totals or "none recorded")
        output(rows, args)

def discovery(args):
    from .storage.discovery_shadow import INTERVAL, LIMITS

    gid = guild(args)
    with connect() as db:
        runs = db.execute(
            """SELECT * FROM discovery_runs WHERE guild_id=? ORDER BY id DESC LIMIT ?""",
            (gid, args.limit),
        ).fetchall()
        candidates = db.execute(
            """SELECT c.url, c.source_url, c.reason, c.story, c.evidence, c.draft,
                      r.channel_id, r.started_at, c.run_id
               FROM discovery_candidates c JOIN discovery_runs r ON r.id=c.run_id
               WHERE c.guild_id=? ORDER BY c.run_id DESC, c.url LIMIT ?""",
            (gid, args.limit),
        ).fetchall()
        output({"interval_seconds": INTERVAL, "limits_per_run": LIMITS,
                "runs": [dict(row) for row in runs],
                "candidates": [dict(row) for row in candidates]}, args)


def archive(args):
    gid = guild(args)
    with connect() as db:
        result = dict(db.execute(
            """SELECT COUNT(*) AS messages, COUNT(DISTINCT channel_id) AS channels,
                      MIN(created_at) AS oldest, MAX(created_at) AS newest,
                      SUM(CASE WHEN deleted_at IS NOT NULL THEN 1 ELSE 0 END) AS deleted
               FROM messages WHERE guild_id=?""", (gid,)).fetchone())
        result["backfill_cursors"] = db.execute("SELECT COUNT(*) FROM backfill_cursors").fetchone()[0]
        result["reaction_members"] = db.execute(
            "SELECT COUNT(*) FROM reaction_members WHERE guild_id=?", (gid,)).fetchone()[0]
        output(result, args)

def memory_stats(args):
    gid = guild(args)
    with connect() as db:
        counts = [dict(r) for r in db.execute(
            """SELECT c.status, COUNT(*) AS count FROM extraction_candidates c
               JOIN extraction_batches b ON b.batch_id=c.batch_id
               WHERE b.guild_id=? GROUP BY c.status""", (gid,))]
        batches = [dict(r) for r in db.execute(
            "SELECT status, COUNT(*) AS count FROM extraction_batches WHERE guild_id=? GROUP BY status", (gid,))]
        usage = dict(db.execute(
            """SELECT COALESCE(SUM(u.input_tokens),0) AS input_tokens,
                      COALESCE(SUM(u.output_tokens),0) AS output_tokens
               FROM extraction_usage u JOIN extraction_batches b ON b.batch_id=u.batch_id
               WHERE b.guild_id=?""", (gid,)).fetchone())
        output({"candidates": counts, "batches": batches, "extraction_usage": usage}, args)

def memories(args):
    gid = guild(args)
    with connect() as db:
        where = "AND c.status=?" if args.status != "all" else ""
        params = [gid] + ([args.status] if where else []) + [args.limit]
        rows = [dict(r) for r in db.execute(
            f"""SELECT c.batch_id, c.candidate_index, c.status, c.memory_type,
                       c.summary, c.participant_ids, c.source_message_ids,
                       b.channel_id
                FROM extraction_candidates c JOIN extraction_batches b ON b.batch_id=c.batch_id
                WHERE b.guild_id=? {where}
                ORDER BY b.created_at DESC, c.candidate_index DESC LIMIT ?""", params)]
    for row in rows:
        row["participant_ids"] = json.loads(row["participant_ids"])
        row["source_message_ids"] = json.loads(row["source_message_ids"])
        row["source_urls"] = [
            f"https://discord.com/channels/{gid}/{row['channel_id']}/{mid}"
            for mid in row["source_message_ids"]
        ]
        row["pinecone"] = "not_checked"
    if args.verify_pinecone:
        if not os.getenv("PINECONE_API_KEY"):
            raise SystemExit("PINECONE_API_KEY required for --verify-pinecone")
        from pinecone import Pinecone
        from .storage.autonomous_memory import memory_vector_id
        from .handlers.vectore_store import INDEX_NAME
        index = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(INDEX_NAME)
        for row in rows:
            if row["status"] != "accepted":
                row["pinecone"] = "not_accepted"
                continue
            ids = [memory_vector_id(gid, scope, row["participant_ids"], row["summary"])
                   for scope in ("individual", "collective")]
            response = index.fetch(ids=ids)
            vectors = response.get("vectors", {}) if isinstance(response, dict) else getattr(response, "vectors", {})
            row["pinecone"] = "confirmed" if any(
                (v.get("metadata", {}) if isinstance(v, dict) else getattr(v, "metadata", {})).get("origin") == "autonomous-v1"
                for v in vectors.values()
            ) else "not_found"
    output(rows, args)

def parse_date(value):
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamps require timezone (e.g. Z)")
    return date.astimezone(timezone.utc)

async def extract(args):
    from .storage.database import Database
    from .storage.extraction_dry_run import dry_run
    from .storage.memory_evaluation_cli import discover_bot_id
    gid = guild(args)
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY required for extraction")
    since = args.since or (datetime.now(timezone.utc) - timedelta(days=args.days))
    until = args.until or (datetime.now(timezone.utc) - timedelta(minutes=30))
    if since >= until or until > datetime.now(timezone.utc):
        raise SystemExit("Invalid historical range; end must be in the past")
    bot_id = await discover_bot_id()
    results = []
    cursor = since
    # Explicit bounded run. Re-invocation skips already completed batches.
    with Database(os.environ["DISCORD_SQLITE_PATH"]) as db:
        for _ in range(args.max_chunks):
            if cursor >= until:
                break
            end = min(cursor + timedelta(hours=args.chunk_hours), until)
            result = await dry_run(
                db.connection, guild_id=gid, since=cursor, until=end,
                max_windows=args.max_windows, max_rows=args.max_rows,
                max_messages=40, model=args.model, bot_author_id=bot_id)
            results.append({"since": cursor.isoformat(), "until": end.isoformat(), **result})
            cursor = end
    output({"chunks": results, "next_since": cursor.isoformat(),
            "complete": cursor >= until,
            "direct_pinecone_writes": False,
            "warning": "The running autonomous worker may publish these proposals later."}, args)

def main():
    parser = argparse.ArgumentParser(description="Discord bot operator inspection and historical extraction")
    parser.add_argument("--guild-id", help="Defaults to REACTION_SHADOW_GUILD_ID")
    parser.add_argument("--json", action="store_true", help="Structured output")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Feature flags, SQLite integrity and row counts")
    reaction = commands.add_parser("reactions", help="Shadow decisions and message links")
    reaction.add_argument("--react-only", action="store_true")
    reaction.add_argument("--limit", type=int, default=30)
    discovery_parser = commands.add_parser("discovery", help="Discovery budgets, decisions and shadow drafts")
    discovery_parser.add_argument("--limit", type=int, default=20)
    archive_parser = commands.add_parser("archive", help="Archive coverage and backfill counts")
    memory = commands.add_parser("memories", help="Candidate inspection and statistics")
    memory.add_argument("--stats", action="store_true")
    memory.add_argument("--status", choices=["all", "accepted", "proposed", "rejected", "superseded"], default="accepted")
    memory.add_argument("--limit", type=int, default=30)
    memory.add_argument("--verify-pinecone", action="store_true", help="Fetch deterministic autonomous IDs from Pinecone")
    backfill = commands.add_parser("backfill", help="Extract candidates to SQLite (running worker may later publish)")
    backfill.add_argument("--since", type=parse_date)
    backfill.add_argument("--until", type=parse_date)
    backfill.add_argument("--days", type=int, default=30)
    backfill.add_argument("--chunk-hours", type=int, default=1)
    backfill.add_argument("--max-chunks", type=int, default=12)
    backfill.add_argument("--max-windows", type=int, default=50)
    backfill.add_argument("--max-rows", type=int, default=1000)
    backfill.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-6.1-terra"))
    args = parser.parse_args()
    if getattr(args, "limit", 1) < 1 or getattr(args, "limit", 1) > 1000:
        parser.error("--limit must be 1..1000")
    if args.command == "backfill":
        if not 1 <= args.max_chunks <= 100 or not 1 <= args.chunk_hours <= 24 or not 1 <= args.max_windows <= 50 or args.days < 1:
            parser.error("Invalid backfill bounds")
        asyncio.run(extract(args))
    elif args.command == "status":
        status(args)
    elif args.command == "reactions":
        reactions(args)
    elif args.command == "discovery":
        discovery(args)
    elif args.command == "archive":
        archive(args)
    elif args.stats:
        memory_stats(args)
    else:
        memories(args)

if __name__ == "__main__":
    main()

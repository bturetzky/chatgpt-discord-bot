# ChatGPT Discord Bot

Self-hosted Python Discord bot for a small trusted server, with OpenAI Responses, on-demand tools, SQLite server history, and Pinecone-backed memory. Development and production use separate Discord applications and deployments.

## Capabilities

- Responds to mentions and direct messages, with recent channel context and a tool-calling loop.
- Reads linked messages from accessible server text channels, with author attribution and available Discord metadata.
- Follows explicit Discord reply chains with archived branches and reads accessible native threads on demand.
- Brave web search, public webpage/GitHub README reading with continuation and phrase lookup, YouTube metadata and best-effort transcripts, weather, news and IGDB game/platform information.
- Direct and replied-to Discord image understanding for supported still images.
- SQLite message archive with FTS5 search, edit/delete handling, restart reconciliation and bounded historical import.
- Autonomous evidence-grounded memory extraction and guarded **create-only** Pinecone publication; semantic and participant-aware retrieval. Operator-verified in production.
- With a SQLite archive, proactive discovery shadow mode automatically evaluates recent public sources for eligible Discord text channels and record decisions and drafts in SQLite. See [dev acceptance](docs/operations.md#discovery-shadow-dev-acceptance).
- Occasional live emoji reactions in the configured guild, triggered by conversation windows or reactions from two distinct people. Supports standard and observed server emoji.

Memory is shared within the bot's existing trust model; legacy Pinecone records may lack participant provenance. Do not use the bot for sensitive conversations. Memory correction/deletion and crash-safe cross-store publication remain future work; see [backlog](docs/backlog.md).

## Requirements and local run

Python 3.12, Poetry 1.8.3 (or Docker), Discord bot permissions/message-content intent, OpenAI and Pinecone credentials. Optional tool credentials depend on the tools used.

```bash
poetry install --only main --no-root
poetry run python -m run
poetry run python -m unittest discover -s tests -t .
```

Or build with `docker build -t chatgpt-discord-bot:local .` and run with a securely supplied env file. Never commit `.env`, Discord tokens or API keys.

## Configuration

Required at startup:

| Variable | Purpose |
| --- | --- |
| `DISCORD_TOKEN` | Discord bot token |
| `OPENAI_API_KEY` | OpenAI API access |
| `PINECONE_API_KEY` | Pinecone memory store |

Optional tool credentials:

| Variable | Purpose |
| --- | --- |
| `OPENWEATHER_API_KEY` | Weather |
| `NEWS_API_KEY` | News |
| `BRAVE_SEARCH_API_KEY` | Web search |
| `IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET` | IGDB/Twitch |

Runtime settings:

| Variable | Purpose / default |
| --- | --- |
| `DISCORD_SQLITE_PATH` | Persistent SQLite file; needed for archive/reaction/memory worker; dev/prod use separate PVCs |
| `REACTION_SHADOW_GUILD_ID` | Numeric guild ID for live reactions when persistent SQLite is configured |
| `REACTION_SHADOW_MODEL` | Reaction evaluator model; defaults to `OPENAI_MODEL` |
| `REACTION_SHADOW_TEST_PREFIX` | Dev-only prefix to trigger an immediate conversation evaluation; unset in production |
| `AUTONOMOUS_MEMORY_ENABLED` | Opt-in background extraction/evaluation/publication, default `false` |
| `AUTONOMOUS_MEMORY_GUILD_ID` | Target guild for worker; falls back to shadow guild setting |
| `OPENAI_MODEL` | Main Responses model override |
| `DISCORD_CONTEXT_LIMIT` | Recent Discord context limit, default 30 |
| `MEMORY_SEMANTIC_CANDIDATES` | Retrieval pool, default 16, range 1–50 |
| `MEMORY_RELATIONSHIP_CANDIDATES` | Participant pool, default 4, range 0–20; zero disables relationship selection |
| `MEMORY_SEMANTIC_SELECTED` | Semantic selection cap, default 6, range 0–6 |
| `MEMORY_RELATIONSHIP_SELECTED` | Relationship selection cap, default 2, range 0–2 |
| `MEMORY_CONTEXT_MAX_CHARS` | Rendered memory budget, default 2400, range 0–12000 |
| `MEMORY_MIN_SIMILARITY` | Optional finite Pinecone score floor; unset by default |
| `OPENAI_INPUT_USD_PER_1M` | Optional estimated input token price |
| `OPENAI_CACHED_INPUT_USD_PER_1M` | Optional estimated cached input token price |
| `OPENAI_OUTPUT_USD_PER_1M` | Optional estimated output token price |

The Pinecone index name is currently hardcoded in the application. Invalid memory retrieval settings skip memory context and emit a sanitized warning. See [architecture](docs/architecture.md) for the selection behavior.

## Development and deployment

PR checks run unit tests and a Docker build. Merging application `main` publishes an immutable image to `ghcr.io/bturetzky/chatgpt-discord-bot`, updates dev GitOps, and invokes read-only ARC rollout verification. Live Discord acceptance is separate. Production promotion is manual, reviewed, and uses the dev-tested digest.

Deployment manifests and Secrets belong to [homelab-gitops](https://github.com/bturetzky/homelab-gitops), not this repository.

## Documentation

- [Architecture and current behavior](docs/architecture.md)
- [Approved feature backlog and evaluation ideas](docs/backlog.md)
- [On-demand LLM tool design assignments](docs/tool-designs/README.md)
- [Deployment and promotion](docs/deployment.md)
- [Operations, diagnostics and smoke tests](docs/operations.md)
- [Agent and documentation rules](AGENTS.md)

## License

See [LICENSE](LICENSE).

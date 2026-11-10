# ChatGPT Discord Bot

A self-hosted Python Discord bot that responds to mentions and direct messages using OpenAI, with optional tools for web search, webpage reading, weather, news, video-game information and Pinecone-backed long-term memory.

> **Project status:** This is a personal project deployed in separate development and production Discord environments. The application is functional in its existing deployment, but the codebase has known technical debt. See the [engineering roadmap](docs/engineering-roadmap.md) before making major upgrades.

## What it does

- Responds to bot mentions in Discord servers and to direct messages.
- Includes recent channel history as conversational context.
- Can call tools for Brave Search, webpage extraction, OpenWeather forecasts, NewsAPI headlines and IGDB game/platform information.
- Uses OpenAI embeddings and a Pinecone index to retrieve and store long-term memories.
- Splits long replies into Discord messages and can send interim tool-progress messages.

**Privacy note:** The current memory implementation does not enforce per-user namespace isolation. Logging has been hardened to avoid recording message bodies and memory contents by default. Shared memory still has privacy and retention limitations; do not use it for sensitive conversations.

## Architecture

```text
Discord message / DM
    -> DiscordHandler (message history and routing)
    -> VectorHandler (embedding + Pinecone memory lookup)
    -> ChatGPTHandler (OpenAI chat and tool loop)
    -> FunctionHandler (registered tool implementations)
    -> Discord reply
```

- `run.py` and `discord_bot/app.py`: application entry point and environment configuration
- `discord_bot/handlers/`: Discord, OpenAI, function dispatch and vector storage
- `discord_bot/functions/`: dynamically registered tools, each subclassing `BaseFunction`
- `tests/`: regression tests for Discord routing, Responses API, tools, memory, and security

## Requirements

- Python 3.12 runtime (Docker uses `python:3.12-slim`) and Poetry 1.8.3, or Docker
- Discord bot application with appropriate permissions and message content intent
- OpenAI API key and Pinecone API key/index
- Optional credentials for OpenWeather, NewsAPI and IGDB

The bot uses the OpenAI Responses API and the modern OpenAI Python SDK. Renovate proposes weekly Poetry updates; review dependency changes and test dev before production promotion.

## Configuration

The application currently requires these environment variables at startup:

| Variable | Purpose |
| --- | --- |
| `DISCORD_TOKEN` | Discord bot token |
| `OPENAI_API_KEY` | OpenAI API access |
| `PINECONE_API_KEY` | Pinecone memory store |

Tool-specific optional variables:

| Variable | Purpose |
| --- | --- |
| `OPENWEATHER_API_KEY` | Weather lookups |
| `NEWS_API_KEY` | News search |
| `BRAVE_SEARCH_API_KEY` | Brave web search |
| `IGDB_CLIENT_ID` | IGDB/Twitch API client ID |
| `IGDB_CLIENT_SECRET` | IGDB/Twitch API client secret |

Additional runtime configuration (all optional unless noted):

| Variable | Purpose / default |
| --- | --- |
| `DISCORD_SQLITE_PATH` | Persistent SQLite file path; required for archive/reaction features. Both deployments use `/data/sqlite/bot.sqlite3` on separate PVCs. |
| `REACTION_SHADOW_ENABLED` | Explicit opt-in for observation-only reaction evaluation; default `false`. |
| `REACTION_SHADOW_GUILD_ID` | Numeric guild ID; required when shadow mode is enabled. Dev: `<dev guild ID>`; prod: `<production guild ID>`. |
| `REACTION_SHADOW_MODEL` | Optional shadow evaluator model; falls back to `OPENAI_MODEL`, then the built-in default. |
| `REACTION_SHADOW_TEST_PREFIX` | **Dev-only** deterministic acceptance prefix; unset in normal operation and production. |
| `OPENAI_MODEL` | Main Responses model override; also used by shadow mode when its override is absent. |
| `DISCORD_CONTEXT_LIMIT` | Recent Discord context message limit (default 30). |
| `SEMANTIC_MEMORY_LIMIT` | Legacy semantic memory retrieval limit (default 8). |
| `RELATIONSHIP_MEMORY_LIMIT` | Legacy relationship retrieval limit (default 4). |
| `MEMORY_RETRIEVAL_ENHANCED` | Enhanced relevance selection is on by default. Set to `false` to restore legacy retrieval and injection. |
| `MEMORY_SEMANTIC_CANDIDATES` | Enhanced semantic pool, default 16, range 1–50. |
| `MEMORY_RELATIONSHIP_CANDIDATES` | Enhanced intent-gated relationship pool, default 4, range 0–20. |
| `MEMORY_SEMANTIC_SELECTED` | Enhanced semantic selection cap, default 6, range 0–6. |
| `MEMORY_RELATIONSHIP_SELECTED` | Enhanced relationship selection cap, default 2, range 0–2. |
| `MEMORY_CONTEXT_MAX_CHARS` | Enhanced full rendered section budget, default 2400, range 0–12000. |
| `MEMORY_MIN_SIMILARITY` | Optional finite score floor for enhanced selection. Unset by default pending private calibration. |
| `OPENAI_INPUT_USD_PER_1M` | Optional model input price for usage estimates. |
| `OPENAI_CACHED_INPUT_USD_PER_1M` | Optional cached input price for usage estimates. |
| `OPENAI_OUTPUT_USD_PER_1M` | Optional output price for usage estimates. |

The Pinecone index name (`discord-bot-context2`) remains hardcoded; not all configuration is environment-driven. See the [reaction shadow runbook](docs/reaction-shadow-runbook.md) and [engineering roadmap](docs/engineering-roadmap.md) for behavior, limitations, and remaining work.

**Never commit API keys or Discord tokens.** For Kubernetes, supply credentials via a Secret and `envFrom`; the manifests live in the separate GitOps repository.

Enhanced retrieval configuration, calibration caveats, diagnostic CLI behavior and dev rollout/rollback are described in [the memory retrieval design](docs/memory-retrieval-enhancement-design.md#implemented-enhancement-2026-11-10). Invalid enhanced settings skip memory context for that request and emit a sanitized warning.

## Running locally

Install dependencies with Poetry, provide the required environment variables securely, then run:

```bash
poetry install --only main --no-root
poetry run python -m run
```

Or build and run the container with the same environment variables:

```bash
docker build -t chatgpt-discord-bot:local .
docker run --rm --env-file .env chatgpt-discord-bot:local
```

These commands describe the existing application entry point; successful startup additionally depends on valid Discord/OpenAI/Pinecone credentials and an accessible Pinecone index. Do not expose the local `.env` file or use real production tokens for development.

## Tests and development

```bash
make test
```

The current test suite is run as part of the Docker build and CI; failures block image publication. After a main-branch merge, an ephemeral ARC runner verifies the expected dev image digest, Argo CD health and Deployment readiness. The first full run passed on 2026-11-08. Live Discord and external-service smoke tests are still required before production promotion.

## Deployment and release process

Container images are published to GitHub Container Registry at `ghcr.io/bturetzky/chatgpt-discord-bot`.

The Kubernetes deployments are managed separately through [homelab-gitops](https://github.com/bturetzky/homelab-gitops):

- `discord-dev`: separate development Discord application, token and server; successful main builds automatically update its GitOps image digest.
- `discord-prod`: separate production Discord application, token and server; image digest is updated only through reviewed manual promotion.

Both environments are reconciled by Argo CD. Immutable-image CI/CD, automatic read-only ARC dev rollout verification (first run passed 2026-11-08), and manual production promotion are implemented and verified; see [Deployment workflow](docs/deployment-workflow.md). The operator confirmed the latest dependency-cleanup image was merged and promoted on 2026-11-07.

## Current feature checkpoint (2026-11-09)

- Persistent SQLite archive, FTS5 search, bounded backfill and restart reconciliation are implemented; production 30-day backfill was operator-run. Reaction add/remove/clear observation is implemented and tested in dev.
- Reaction **shadow evaluation** is deployed in dev and production GitOps configuration. Dev live acceptance succeeded: a deterministic candidate produced a real model decision (`ignore`, `no_clear_reaction`, 303 input/41 output tokens). Production configuration PRs were merged; production runtime startup and ongoing evaluations have **not yet been independently verified**. No unsolicited reactions are posted.
- Autonomous memory extraction and guarded Pinecone publication are implemented and enabled in dev. The operator observed successful publication (two memories, zero failures) and later DEBUG logs showing retrieved summaries from Pinecone. This verifies retrieval and context insertion, but does not by itself prove a response was based exclusively on retrieved memories. Production enablement/promotion has not yet been confirmed. Live proactive reaction posting remains unimplemented. See [memory lifecycle status](docs/memory-lifecycle-status.md).

## Documentation

- [Autonomous development design](docs/agent-development-design.md) — Codex permissions, verified pipeline, and remaining limitations
- [Agent instructions](AGENTS.md) — rules for the first supervised Codex experiment
- [Engineering roadmap and code review](docs/engineering-roadmap.md) — prioritized debt, improvements and sequencing
- [Deployment workflow](docs/deployment-workflow.md) — implemented testing, image publishing, dev rollout and production promotion
- [homelab-gitops](https://github.com/bturetzky/homelab-gitops) — authoritative Kubernetes and Argo CD configuration

## License

See [LICENSE](LICENSE).

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

The Pinecone index name (`discord-bot-context2`), model choices and other settings are currently hardcoded. See the roadmap for planned configuration improvements.

**Never commit API keys or Discord tokens.** For Kubernetes, supply credentials via a Secret and `envFrom`; the manifests live in the separate GitOps repository.

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

The current test suite is run as part of the Docker build and CI; failures block image publication. Live Discord and external-service smoke tests are still required before production promotion.

## Deployment and release process

Container images are published to GitHub Container Registry at `ghcr.io/bturetzky/chatgpt-discord-bot`.

The Kubernetes deployments are managed separately through [homelab-gitops](https://github.com/bturetzky/homelab-gitops):

- `discord-dev`: separate development Discord application, token and server; successful main builds automatically update its GitOps image digest.
- `discord-prod`: separate production Discord application, token and server; image digest is updated only through reviewed manual promotion.

Both environments are reconciled by Argo CD. Immutable-image CI/CD and manual production promotion are implemented and verified; see [Deployment workflow](docs/deployment-workflow.md). The operator confirmed the latest dependency-cleanup image was merged and promoted on 2026-11-07.

## Documentation

- [Engineering roadmap and code review](docs/engineering-roadmap.md) — prioritized debt, improvements and sequencing
- [Deployment workflow](docs/deployment-workflow.md) — implemented testing, image publishing, dev rollout and production promotion
- [homelab-gitops](https://github.com/bturetzky/homelab-gitops) — authoritative Kubernetes and Argo CD configuration

## License

See [LICENSE](LICENSE).

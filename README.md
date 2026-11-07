# ChatGPT Discord Bot

A self-hosted Python Discord bot that responds to mentions and direct messages using OpenAI, with optional tools for web search, webpage reading, weather, news, video-game information and Pinecone-backed long-term memory.

> **Project status:** This is a personal project deployed in separate development and production Discord environments. The application is functional in its existing deployment, but the codebase has known technical debt. See the [engineering roadmap](docs/engineering-roadmap.md) before making major upgrades.

## What it does

- Responds to bot mentions in Discord servers and to direct messages.
- Includes recent channel history as conversational context.
- Can call tools for DuckDuckGo search, webpage extraction, OpenWeather forecasts, NewsAPI headlines and IGDB game/platform information.
- Uses OpenAI embeddings and a Pinecone index to retrieve and store long-term memories.
- Splits long replies into Discord messages and can send interim tool-progress messages.

**Privacy note:** The current memory implementation does not enforce per-user namespace isolation. It also logs message content. Do not treat the existing implementation as appropriate for sensitive conversations until the roadmap's privacy work is completed.

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
- `tests/`: legacy tests requiring modernization (see roadmap)

## Requirements

- Python 3.10-compatible environment and Poetry, or Docker
- Discord bot application with appropriate permissions and message content intent
- OpenAI API key and Pinecone API key/index
- Optional credentials for OpenWeather, NewsAPI and IGDB

The project currently uses the legacy OpenAI Python SDK (`0.28`). Do not upgrade it independently of the application API migration.

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

**Known limitation:** The current test suite references a removed `chat_bot` module and is not a reliable regression suite. The current Makefile also suppresses test failure status. Replacing and gating these tests is a top roadmap item. Do not interpret a successful `make test` exit code as proof that tests passed.

## Deployment and release process

Container images are published to GitHub Container Registry at `ghcr.io/bturetzky/chatgpt-discord-bot`.

The Kubernetes deployments are managed separately through [homelab-gitops](https://github.com/bturetzky/homelab-gitops):

- `discord-dev`: separate development Discord application, token and server; currently uses `latest`.
- `discord-prod`: separate production Discord application, token and server; currently uses image tag `1.0.4`.

Both environments are reconciled by Argo CD. The planned immutable-image CI/CD and manual production promotion process is documented in [Deployment workflow](docs/deployment-workflow.md); **it has not been implemented yet**.

## Documentation

- [Engineering roadmap and code review](docs/engineering-roadmap.md) — prioritized debt, improvements and sequencing
- [Deployment workflow design](docs/deployment-workflow.md) — proposed testing, image publishing, dev rollout and production promotion
- [homelab-gitops](https://github.com/bturetzky/homelab-gitops) — authoritative Kubernetes and Argo CD configuration

## License

See [LICENSE](LICENSE).
